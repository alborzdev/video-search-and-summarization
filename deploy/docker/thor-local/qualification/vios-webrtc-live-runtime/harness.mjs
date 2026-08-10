#!/usr/bin/env node

/*
 * Exercise the shipped VIOS/NvStreamer live WebRTC UI through a fresh,
 * loopback-only Chromium instance. Peer IDs, media-session IDs, SDP, and ICE
 * candidates stay in memory and are never written to retained evidence.
 */

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const MAX_DURATION_MS = 90_000;
const MAX_BROWSER_ACTIONS = 16;
const MAX_HTTP_RESPONSES = 400;
const MAX_WEBSOCKET_FRAMES = 240;
const MAX_OUTPUT_BYTES = 2 * 1024 * 1024;

const sha = value => crypto.createHash('sha256').update(value).digest('hex');

function fail(code) {
    const error = new Error(code);
    error.code = code;
    throw error;
}

function parseArgs(argv) {
    if (argv.length % 2 !== 0) fail('arguments');
    const result = {};
    for (let index = 0; index < argv.length; index += 2) {
        const flag = argv[index];
        const value = argv[index + 1];
        if (!flag?.startsWith('--') || !value || flag.slice(2) in result) fail('arguments');
        result[flag.slice(2)] = value;
    }
    for (const required of [
        'ui-origin',
        'chromium-executable',
        'playwright-module',
        'sensor-name',
        'stream-id-sha256',
        'output',
        'run-id',
    ]) {
        if (!result[required]) fail(`missing_${required}`);
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(result['run-id'])) fail('run_id');
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/.test(result['sensor-name'])) fail('sensor_name');
    if (!/^[0-9a-f]{64}$/.test(result['stream-id-sha256'])) fail('stream_hash');
    return result;
}

function loopbackOrigin(text, expectedPort) {
    const value = new URL(text);
    const host = value.hostname.replace(/^\[|\]$/g, '');
    const family = net.isIP(host);
    const loopback = (family === 4 && host.startsWith('127.')) || (family === 6 && host === '::1');
    if (
        value.protocol !== 'http:' ||
        !loopback ||
        value.port !== expectedPort ||
        value.username ||
        value.password ||
        !['', '/'].includes(value.pathname) ||
        value.search ||
        value.hash
    ) {
        fail('origin');
    }
    return value.origin;
}

function isLoopbackUrl(raw) {
    const value = new URL(raw);
    const host = value.hostname.replace(/^\[|\]$/g, '');
    return host === 'localhost' || host === '::1' || host.startsWith('127.');
}

function parseFrame(payload) {
    if (typeof payload !== 'string') return null;
    try {
        const value = JSON.parse(payload);
        return value && typeof value === 'object' ? value : null;
    } catch {
        return null;
    }
}

function apiKey(value) {
    return typeof value?.apiKey === 'string' ? value.apiKey.replace(/^\/+/, '') : null;
}

function countValues(values) {
    const result = {};
    for (const value of values) result[value] = (result[value] || 0) + 1;
    return Object.fromEntries(Object.entries(result).sort());
}

async function mediaSample(video) {
    return video.evaluate(element => {
        const quality = typeof element.getVideoPlaybackQuality === 'function' ? element.getVideoPlaybackQuality() : null;
        const tracks = element.srcObject instanceof MediaStream
            ? element.srcObject.getVideoTracks().map(track => ({
                  enabled: track.enabled,
                  kind: track.kind,
                  muted: track.muted,
                  ready_state: track.readyState,
              }))
            : [];
        return {
            current_time: Number(element.currentTime.toFixed(3)),
            decoded_frames: quality?.totalVideoFrames ?? element.webkitDecodedFrameCount ?? 0,
            dropped_frames: quality?.droppedVideoFrames ?? element.webkitDroppedFrameCount ?? 0,
            ended: element.ended,
            media_error: element.error?.code ?? null,
            paused: element.paused,
            ready_state: element.readyState,
            tracks,
            video_height: element.videoHeight,
            video_width: element.videoWidth,
        };
    });
}

async function waitForFrameAdvance(page, video, baseline, minimumDelta = 12) {
    await page.waitForFunction(
        ({ selector, prior, delta }) => {
            const element = document.querySelector(selector);
            if (!(element instanceof HTMLVideoElement)) return false;
            const quality = typeof element.getVideoPlaybackQuality === 'function' ? element.getVideoPlaybackQuality() : null;
            const frames = quality?.totalVideoFrames ?? element.webkitDecodedFrameCount ?? 0;
            return element.readyState === 4 && frames >= prior + delta && element.currentTime >= 0;
        },
        { selector: 'video[id^="video-live-"]', prior: baseline.decoded_frames, delta: minimumDelta },
        { timeout: 20_000 },
    );
    return mediaSample(video);
}

async function liveRead(page, uiOrigin, streamId, peerId, operation) {
    return page.evaluate(
        async ({ origin, stream, peer, op }) => {
            const endpoint = new URL(`/api/v1/live/stream/${op}`, origin);
            endpoint.searchParams.set(op === 'query' ? 'peerid' : 'peerId', peer);
            if (op === 'query') endpoint.searchParams.set('metadata', 'false');
            const response = await fetch(endpoint, { headers: { streamId: stream } });
            const text = await response.text();
            let body = null;
            try {
                body = JSON.parse(text);
            } catch {
                body = text;
            }
            return { status: response.status, body };
        },
        { origin: uiOrigin, stream: streamId, peer: peerId, op: operation },
    );
}

async function statusAfterStop(page, uiOrigin, streamId, peerId) {
    return page.evaluate(
        async ({ origin, stream, peer }) => {
            const request = async endpoint => {
                const response = await fetch(endpoint, { headers: { streamId: stream } });
                const text = await response.text();
                let body = null;
                try {
                    body = JSON.parse(text);
                } catch {
                    body = text;
                }
                return { status: response.status, body };
            };
            const targeted = new URL('/api/v1/live/stream/status', origin);
            targeted.searchParams.set('peerId', peer);
            return {
                targeted: await request(targeted),
                aggregate: await request(new URL('/api/v1/live/stream/status', origin)),
            };
        },
        { origin: uiOrigin, stream: streamId, peer: peerId },
    );
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const started = Date.now();
    const uiOrigin = loopbackOrigin(args['ui-origin'], '31000');
    const chromiumExecutable = path.resolve(args['chromium-executable']);
    if (chromiumExecutable !== '/snap/bin/chromium') fail('chromium_executable');
    await fs.access(chromiumExecutable);
    const modulePath = path.resolve(args['playwright-module']);
    const moduleRaw = await fs.readFile(modulePath);
    if (moduleRaw.length === 0 || moduleRaw.length > MAX_OUTPUT_BYTES) fail('playwright_module');
    const imported = await import(pathToFileURL(modulePath).href);
    const chromium = imported.chromium ?? imported.default?.chromium;
    if (!chromium?.launch) fail('playwright_module');

    const receipt = {
        schema_version: 1,
        status: 'failed',
        bounds: {
            duration_ms: null,
            external_request_count: 0,
            max_browser_actions: MAX_BROWSER_ACTIONS,
            max_duration_ms: MAX_DURATION_MS,
            max_http_responses: MAX_HTTP_RESPONSES,
            max_websocket_frames: MAX_WEBSOCKET_FRAMES,
            numeric_loopback_only: true,
        },
        browser: {
            executable_path: chromiumExecutable,
            launch_mode: 'fresh-headless',
            playwright_module_sha256: sha(moduleRaw),
        },
        cleanup: {
            post_stop_status: null,
            stop_frame_observed: false,
            video_removed: false,
            websocket_closed: false,
        },
        errors: [],
        network: {
            external_requests: 0,
            http_response_count: 0,
            http_status_counts: {},
            request_failure_count: 0,
            websocket_frame_count: 0,
        },
        privacy: {
            ice_candidates_retained: false,
            media_session_ids_retained: false,
            peer_ids_retained: false,
            sdp_retained: false,
        },
        ui: { route: '/#/media-streams', sensor_name: args['sensor-name'] },
        webrtc: {},
    };

    let browser;
    let context;
    let page;
    let active = false;
    let peerId = null;
    let mediaSessionId = null;
    let streamId = null;
    let browserActions = 0;
    let liveSocket = null;
    let liveSocketClosed = false;
    let stage = 'browser-connect';
    const sentKeys = [];
    const receivedKeys = [];
    const responseStatuses = [];
    const requestFailures = [];

    try {
        browser = await chromium.launch({
            executablePath: chromiumExecutable,
            headless: true,
            args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
        });
        context = await browser.newContext();
        page = await context.newPage();
        browserActions += 1;
        page.setDefaultTimeout(30_000);
        page.setDefaultNavigationTimeout(30_000);

        const pageErrors = [];
        page.on('pageerror', error => pageErrors.push(error.message));
        page.on('requestfailed', request => {
            const url = new URL(request.url());
            requestFailures.push({
                error: request.failure()?.errorText ?? 'unknown',
                loopback: isLoopbackUrl(request.url()),
                method: request.method(),
                path: url.pathname,
            });
        });
        page.on('response', response => {
            if (responseStatuses.length >= MAX_HTTP_RESPONSES) return;
            const url = new URL(response.url());
            responseStatuses.push({
                loopback: isLoopbackUrl(response.url()),
                method: response.request().method(),
                path: url.pathname,
                status: response.status(),
            });
        });
        await page.route(/^https?:\/\//, async route => {
            if (!isLoopbackUrl(route.request().url())) {
                receipt.bounds.external_request_count += 1;
                await route.abort('blockedbyclient');
                return;
            }
            await route.continue();
        });
        page.on('websocket', socket => {
            const url = new URL(socket.url());
            if (url.pathname !== '/api/v1/live/ws') return;
            liveSocket = socket;
            socket.on('framesent', event => {
                receipt.network.websocket_frame_count += 1;
                const frame = parseFrame(event.payload);
                const key = apiKey(frame);
                if (key) sentKeys.push(key);
                if (key === 'api/v1/live/stream/start') {
                    peerId = frame?.peerId ?? frame?.data?.peerId ?? peerId;
                    streamId = frame?.data?.streamId ?? streamId;
                    active = true;
                }
                if (key === 'api/v1/live/stream/stop') receipt.cleanup.stop_frame_observed = true;
            });
            socket.on('framereceived', event => {
                receipt.network.websocket_frame_count += 1;
                const frame = parseFrame(event.payload);
                const key = apiKey(frame);
                if (key) receivedKeys.push(key);
                if (key === 'api/v1/live/stream/start' || key === 'api/v1/live/setAnswer') {
                    peerId = frame?.peerId ?? peerId;
                    mediaSessionId = frame?.data?.mediaSessionId ?? mediaSessionId;
                }
            });
            socket.on('close', () => {
                liveSocketClosed = true;
            });
        });

        stage = 'navigate';
        await page.setViewportSize({ width: 1600, height: 1000 });
        browserActions += 1;
        await page.goto(`${uiOrigin}/#/media-upload`, { waitUntil: 'networkidle' });
        browserActions += 1;
        await page.goto(`${uiOrigin}/#/media-streams`, { waitUntil: 'networkidle' });
        browserActions += 1;
        const comboboxes = page.locator('input[role="combobox"]:visible');
        await comboboxes.first().waitFor();
        if ((await comboboxes.count()) !== 2) fail('sensor_selector_count');
        stage = 'select-sensor';
        await comboboxes.nth(1).click();
        browserActions += 1;
        const sensorOption = page.getByRole('option', { name: args['sensor-name'], exact: true });
        await sensorOption.waitFor({ state: 'visible', timeout: 45_000 });
        await sensorOption.click();
        browserActions += 1;

        stage = 'media-ready';
        const video = page.locator('video[id^="video-live-"]').first();
        await video.waitFor({ state: 'attached' });
        await page.waitForFunction(
            selector => {
                const element = document.querySelector(selector);
                if (!(element instanceof HTMLVideoElement)) return false;
                const tracks = element.srcObject instanceof MediaStream ? element.srcObject.getVideoTracks() : [];
                return (
                    element.readyState === 4 &&
                    element.videoWidth > 0 &&
                    element.videoHeight > 0 &&
                    tracks.some(track => track.readyState === 'live' && !track.muted)
                );
            },
            'video[id^="video-live-"]',
            { timeout: 30_000 },
        );
        stage = 'signaling-identity';
        const identifierDeadline = Date.now() + 15_000;
        while ((!peerId || !mediaSessionId || !streamId) && Date.now() < identifierDeadline) await page.waitForTimeout(100);
        if (!peerId || !mediaSessionId || !streamId || !liveSocket) fail('signaling_identity');
        if (sha(streamId) !== args['stream-id-sha256']) fail('stream_identity');

        stage = 'media-and-timestamps';
        const first = await mediaSample(video);
        const second = await waitForFrameAdvance(page, video, first);
        const queryFirst = await liveRead(page, uiOrigin, streamId, peerId, 'query');
        browserActions += 1;
        const third = await waitForFrameAdvance(page, video, second);
        const querySecond = await liveRead(page, uiOrigin, streamId, peerId, 'query');
        browserActions += 1;
        const status = await liveRead(page, uiOrigin, streamId, peerId, 'status');
        browserActions += 1;
        if (
            third.ready_state !== 4 ||
            ![
                [320, 180],
                [1920, 1080],
            ].some(([width, height]) => third.video_width === width && third.video_height === height) ||
            third.media_error !== null ||
            third.current_time < second.current_time ||
            !third.tracks.some(track => track.ready_state === 'live' && !track.muted)
        ) {
            fail('decoded_media');
        }
        if (
            queryFirst.status !== 200 ||
            querySecond.status !== 200 ||
            !Number.isInteger(queryFirst.body?.ts) ||
            !Number.isInteger(querySecond.body?.ts) ||
            querySecond.body.ts < queryFirst.body.ts
        ) {
            fail('timestamp_query');
        }
        if (status.status !== 200 || status.body?.error !== false || status.body?.state !== 'PLAYING') fail('playing_status');

        const screenshotPath = `/tmp/vss-vios-webrtc-live-${args['run-id']}.png`;
        await page.screenshot({ path: screenshotPath, fullPage: false });
        browserActions += 1;
        const screenshot = await fs.readFile(screenshotPath);
        receipt.ui = {
            ...receipt.ui,
            browser_actions: browserActions,
            screenshot_bytes: screenshot.length,
            screenshot_path: screenshotPath,
            screenshot_sha256: sha(screenshot),
            title: await page.title(),
        };
        receipt.webrtc = {
            decoded_frame_deltas: {
                initial: second.decoded_frames - first.decoded_frames,
                sustained: third.decoded_frames - second.decoded_frames,
            },
            first_sample: first,
            final_sample: third,
            presentation_time_nondecreasing: third.current_time >= second.current_time,
            received_api_keys: countValues(receivedKeys),
            sent_api_keys: countValues(sentKeys),
            signaling_complete: true,
            status_while_active: { error: status.body.error, state: status.body.state, status: status.status },
            timestamp_query: {
                first_integer: true,
                nondecreasing: querySecond.body.ts >= queryFirst.body.ts,
                second_integer: true,
                statuses: [queryFirst.status, querySecond.status],
            },
            websocket_path: new URL(liveSocket.url()).pathname,
        };

        stage = 'explicit-stop';
        const closeButton = page.getByRole('button', { name: 'close', exact: true }).last();
        await closeButton.click();
        browserActions += 1;
        await page.locator('video[id^="video-live-"]').waitFor({ state: 'detached', timeout: 15_000 });
        receipt.cleanup.video_removed = true;
        const stopDeadline = Date.now() + 10_000;
        while (!receipt.cleanup.stop_frame_observed && Date.now() < stopDeadline) await page.waitForTimeout(100);
        if (!receipt.cleanup.stop_frame_observed) fail('stop_not_observed');
        const closeDeadline = Date.now() + 10_000;
        while (!liveSocketClosed && Date.now() < closeDeadline) await page.waitForTimeout(100);
        receipt.cleanup.websocket_closed = liveSocketClosed;
        const stopped = await statusAfterStop(page, uiOrigin, streamId, peerId);
        browserActions += 2;
        receipt.cleanup.post_stop_status = {
            aggregate: { body_is_null: stopped.aggregate.body === null, status: stopped.aggregate.status },
            targeted: {
                error_code: stopped.targeted.body?.error_code ?? null,
                error_message: stopped.targeted.body?.error_message ?? null,
                status: stopped.targeted.status,
            },
        };
        if (
            stopped.aggregate.status !== 200 ||
            stopped.aggregate.body !== null ||
            stopped.targeted.status !== 400 ||
            stopped.targeted.body?.error_code !== 'InvalidParameterError'
        ) {
            fail('post_stop_status');
        }
        active = false;

        if (pageErrors.length !== 0) fail('page_error');
        if (receipt.bounds.external_request_count !== 0) fail('external_request');
        if (responseStatuses.length > MAX_HTTP_RESPONSES) fail('response_budget');
        if (receipt.network.websocket_frame_count > MAX_WEBSOCKET_FRAMES) fail('websocket_budget');
        if (browserActions > MAX_BROWSER_ACTIONS) fail('browser_action_budget');
        if (Date.now() - started > MAX_DURATION_MS) fail('duration_budget');
        if (!liveSocketClosed) fail('websocket_cleanup');
        receipt.status = 'passed';
        stage = 'passed';
    } catch (error) {
        receipt.errors.push({ code: error?.code || error?.message || 'runtime_error', stage });
        receipt.diagnostic = {
            live_socket_observed: liveSocket !== null,
            media_session_observed: mediaSessionId !== null,
            peer_observed: peerId !== null,
            received_api_keys: countValues(receivedKeys),
            sent_api_keys: countValues(sentKeys),
            stage,
            stream_observed: streamId !== null,
        };
        if (page) {
            try {
                const diagnosticVideo = page.locator('video[id^="video-live-"]').first();
                if (await diagnosticVideo.count()) receipt.diagnostic.media_sample = await mediaSample(diagnosticVideo);
                receipt.diagnostic.connecting_overlay_count = await page.getByText('WebRTC Connecting...', { exact: true }).count();
            } catch {
                receipt.diagnostic.media_sample_unavailable = true;
            }
        }
    } finally {
        if (active && page) {
            try {
                const closeButton = page.getByRole('button', { name: 'close', exact: true }).last();
                if (await closeButton.count()) await closeButton.click({ timeout: 5_000 });
            } catch {
                receipt.errors.push({ code: 'fallback_cleanup_failed' });
            }
        }
        if (page) await page.close().catch(() => {});
        if (context) await context.close().catch(() => {});
        if (browser) await browser.close().catch(() => {});
        receipt.bounds.duration_ms = Date.now() - started;
        receipt.network.external_requests = receipt.bounds.external_request_count;
        receipt.network.http_response_count = responseStatuses.length;
        receipt.network.http_status_counts = countValues(responseStatuses.map(value => String(value.status)));
        receipt.network.request_failure_count = requestFailures.length;
        receipt.network.loopback_request_failure_count = requestFailures.filter(value => value.loopback).length;
        receipt.network.non_loopback_request_failure_count = requestFailures.filter(value => !value.loopback).length;
        receipt.network.response_path_counts = countValues(responseStatuses.map(value => `${value.method} ${value.path}`));
        const output = `${JSON.stringify(receipt, null, 2)}\n`;
        if (Buffer.byteLength(output) > MAX_OUTPUT_BYTES) fail('output_bound');
        await fs.writeFile(path.resolve(args.output), output, { encoding: 'utf8', mode: 0o600 });
    }

    process.stdout.write(`${JSON.stringify({ status: receipt.status, error_codes: receipt.errors.map(value => value.code) })}\n`);
    if (receipt.status !== 'passed') process.exitCode = 1;
}

await main();
