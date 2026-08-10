#!/usr/bin/env node

/*
 * Exercise the shipped VIOS Recorded Streams page and replay REST controls
 * through an existing loopback-only Chromium CDP endpoint. Peer IDs,
 * media-session IDs, SDP, and ICE candidates remain in memory and are never
 * written to the retained receipt.
 */

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const MAX_DURATION_MS = 120_000;
const MAX_BROWSER_ACTIONS = 16;
const MAX_HTTP_RESPONSES = 500;
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
    for (const required of ['ui-origin', 'cdp-origin', 'playwright-module', 'sensor-name', 'stream-id-sha256', 'output', 'run-id']) {
        if (!result[required]) fail(`missing_${required}`);
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(result['run-id'])) fail('run_id');
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
            return element.readyState === 4 && frames >= prior + delta;
        },
        {
            selector: 'video[id^="video-replay-"]',
            prior: baseline.decoded_frames,
            delta: minimumDelta,
        },
        { timeout: 20_000 },
    );
    return mediaSample(video);
}

async function replayFetch(page, uiOrigin, streamId, peerId, mediaSessionId, request) {
    return page.evaluate(
        async ({ origin, stream, peer, media, spec }) => {
            const endpoint = new URL('/vst/api/v1/replay/stream/seek', origin);
            const init = {
                method: spec.method,
                headers: { streamId: stream },
            };
            if (spec.method === 'GET') {
                endpoint.searchParams.set('peerId', peer);
                endpoint.searchParams.set('mediaSessionId', media);
            } else {
                init.headers['Content-Type'] = 'application/json';
                init.body = JSON.stringify({
                    peerId: peer,
                    mediaSessionId: media,
                    action: spec.action,
                    ...(spec.value === undefined ? {} : { value: spec.value }),
                });
            }
            const response = await fetch(endpoint, init);
            const text = await response.text();
            let body = null;
            try {
                body = JSON.parse(text);
            } catch {
                body = text;
            }
            return { status: response.status, body };
        },
        {
            origin: uiOrigin,
            stream: streamId,
            peer: peerId,
            media: mediaSessionId,
            spec: request,
        },
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
            const targetedEndpoint = new URL('/vst/api/v1/replay/stream/status', origin);
            targetedEndpoint.searchParams.set('peerId', peer);
            const aggregateEndpoint = new URL('/vst/api/v1/replay/stream/status', origin);
            return {
                targeted: await request(targetedEndpoint),
                aggregate: await request(aggregateEndpoint),
            };
        },
        { origin: uiOrigin, stream: streamId, peer: peerId },
    );
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const started = Date.now();
    const uiOrigin = loopbackOrigin(args['ui-origin'], '7777');
    const cdpOrigin = loopbackOrigin(args['cdp-origin'], '9223');
    const modulePath = path.resolve(args['playwright-module']);
    const moduleRaw = await fs.readFile(modulePath);
    if (moduleRaw.length === 0 || moduleRaw.length > MAX_OUTPUT_BYTES) fail('playwright_module');
    const imported = await import(pathToFileURL(modulePath).href);
    const chromium = imported.chromium ?? imported.default?.chromium;
    if (!chromium?.connectOverCDP) fail('playwright_module');

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
            cdp_origin: cdpOrigin,
            playwright_module_sha256: sha(moduleRaw),
        },
        cleanup: {
            post_stop_status: null,
            stop_frame_observed: false,
            video_removed: false,
            websocket_closed: false,
        },
        controls: {},
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
        ui: {
            route: '/vst/#/recorded-streams',
            sensor_name: args['sensor-name'],
        },
        webrtc: {},
    };

    let browser;
    let page;
    let active = false;
    let peerId = null;
    let mediaSessionId = null;
    let streamId = null;
    let browserActions = 0;
    let replaySocket = null;
    let replaySocketClosed = false;
    const sentKeys = [];
    const receivedKeys = [];
    const responseStatuses = [];
    const requestFailures = [];

    try {
        browser = await chromium.connectOverCDP(cdpOrigin, { timeout: 10_000 });
        const contexts = browser.contexts();
        if (contexts.length !== 1) fail('browser_context');
        page = await contexts[0].newPage();
        browserActions += 1;
        page.setDefaultTimeout(30_000);
        page.setDefaultNavigationTimeout(30_000);

        const pageErrors = [];
        page.on('pageerror', error => pageErrors.push(error.message));
        page.on('requestfailed', request => {
            const url = new URL(request.url());
            requestFailures.push({
                host: url.host,
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
            if (url.pathname !== '/vst/api/v1/replay/ws') return;
            replaySocket = socket;
            socket.on('framesent', event => {
                receipt.network.websocket_frame_count += 1;
                const frame = parseFrame(event.payload);
                const key = apiKey(frame);
                if (key) sentKeys.push(key);
                if (key === 'api/v1/replay/stream/start') {
                    peerId = frame?.peerId ?? frame?.data?.peerId ?? peerId;
                    streamId = frame?.data?.streamId ?? streamId;
                    active = true;
                }
                if (key === 'api/v1/replay/stream/stop') receipt.cleanup.stop_frame_observed = true;
            });
            socket.on('framereceived', event => {
                receipt.network.websocket_frame_count += 1;
                const frame = parseFrame(event.payload);
                const key = apiKey(frame);
                if (key) receivedKeys.push(key);
                if (key === 'api/v1/replay/stream/start' || key === 'api/v1/replay/setAnswer') {
                    peerId = frame?.peerId ?? peerId;
                    mediaSessionId = frame?.data?.mediaSessionId ?? mediaSessionId;
                }
            });
            socket.on('close', () => {
                replaySocketClosed = true;
            });
        });

        await page.setViewportSize({ width: 1600, height: 1000 });
        browserActions += 1;
        await page.goto(`${uiOrigin}/vst/#/recorded-streams`, { waitUntil: 'domcontentloaded' });
        browserActions += 1;
        await page.getByRole('heading', { name: 'Replay Streaming', exact: true }).waitFor();
        const visibleComboboxes = page.locator('input[role="combobox"]:visible');
        const visibleLabels = await visibleComboboxes.evaluateAll(inputs =>
            inputs.map(input => input.labels?.[0]?.textContent?.trim() ?? ''),
        );
        const sensorInputIndex = visibleLabels.indexOf('Select Sensors');
        if (sensorInputIndex < 0 || visibleLabels.lastIndexOf('Select Sensors') !== sensorInputIndex) {
            fail('visible_sensor_selector');
        }
        const sensorInput = visibleComboboxes.nth(sensorInputIndex);
        await sensorInput.click();
        browserActions += 1;
        await page.getByRole('option', { name: args['sensor-name'], exact: true }).click();
        browserActions += 1;

        const video = page.locator('video[id^="video-replay-"]').first();
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
            'video[id^="video-replay-"]',
            { timeout: 30_000 },
        );
        await page.waitForFunction(
            () => window.performance.now() >= 0,
            null,
            { timeout: 1_000 },
        );
        const identifierDeadline = Date.now() + 15_000;
        while ((!peerId || !mediaSessionId || !streamId) && Date.now() < identifierDeadline) {
            await page.waitForTimeout(100);
        }
        if (!peerId || !mediaSessionId || !streamId) fail('signaling_identity');
        if (sha(streamId) !== args['stream-id-sha256']) fail('stream_identity');

        const first = await mediaSample(video);
        const second = await waitForFrameAdvance(page, video, first);
        if (
            second.ready_state !== 4 ||
            second.video_width !== 1280 ||
            second.video_height !== 720 ||
            second.media_error !== null ||
            !second.tracks.some(track => track.ready_state === 'live' && !track.muted)
        ) {
            fail('decoded_media');
        }

        const positive = await replayFetch(page, uiOrigin, streamId, peerId, mediaSessionId, {
            method: 'POST',
            action: 'seekForward',
            value: '2',
        });
        browserActions += 1;
        if (positive.status !== 200 || positive.body !== true) fail('positive_seek');
        const afterPositive = await waitForFrameAdvance(page, video, second);

        const position = await replayFetch(page, uiOrigin, streamId, peerId, mediaSessionId, { method: 'GET' });
        browserActions += 1;
        if (
            position.status !== 200 ||
            !position.body ||
            !Number.isInteger(position.body.position)
        ) {
            fail('position_lookup');
        }

        const invalid = await replayFetch(page, uiOrigin, streamId, peerId, mediaSessionId, {
            method: 'POST',
            action: 'seekSideways',
            value: '2',
        });
        browserActions += 1;
        if (invalid.status !== 501 || invalid.body?.error_code !== 'VMSNotSupportedError') fail('negative_seek');
        const afterNegative = await waitForFrameAdvance(page, video, afterPositive);

        const uiSeekResponsePromise = page.waitForResponse(response => {
            const url = new URL(response.url());
            return (
                url.pathname === '/vst/api/v1/replay/stream/seek' &&
                response.request().method() === 'POST'
            );
        });
        await page.locator('#seek-forward-control-btn').click();
        browserActions += 1;
        const uiSeekResponse = await uiSeekResponsePromise;
        if (uiSeekResponse.status() !== 200) fail('ui_seek');
        const afterUiSeek = await waitForFrameAdvance(page, video, afterNegative);

        const screenshotPath = `/tmp/vss-vios-webrtc-replay-${args['run-id']}.png`;
        await page.screenshot({ path: screenshotPath, fullPage: false });
        browserActions += 1;
        const screenshot = await fs.readFile(screenshotPath);

        receipt.controls = {
            invalid_action: {
                error_code: invalid.body.error_code,
                expected_status: 501,
                playback_continued: afterNegative.decoded_frames > afterPositive.decoded_frames,
                status: invalid.status,
            },
            position_lookup: {
                action_query_parameter_sent_by_client: false,
                opaque_integer_present: true,
                status: position.status,
            },
            positive_relative_seek: {
                action: 'seekForward',
                frames_continued: afterPositive.decoded_frames > second.decoded_frames,
                status: positive.status,
                value_type: 'string',
            },
            ui_seek_forward: {
                frames_continued: afterUiSeek.decoded_frames > afterNegative.decoded_frames,
                status: uiSeekResponse.status(),
            },
        };
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
                after_positive_seek: afterPositive.decoded_frames - second.decoded_frames,
                after_invalid_seek: afterNegative.decoded_frames - afterPositive.decoded_frames,
                after_ui_seek: afterUiSeek.decoded_frames - afterNegative.decoded_frames,
            },
            first_sample: first,
            final_sample: afterUiSeek,
            received_api_keys: countValues(receivedKeys),
            sent_api_keys: countValues(sentKeys),
            signaling_complete: true,
            websocket_path: new URL(replaySocket.url()).pathname,
        };

        const closeButton = page.getByRole('button', { name: 'close', exact: true }).last();
        await closeButton.click();
        browserActions += 1;
        await page.locator('video[id^="video-replay-"]').waitFor({ state: 'detached', timeout: 15_000 });
        receipt.cleanup.video_removed = true;
        const stopDeadline = Date.now() + 10_000;
        while (!receipt.cleanup.stop_frame_observed && Date.now() < stopDeadline) {
            await page.waitForTimeout(100);
        }
        if (!receipt.cleanup.stop_frame_observed) fail('stop_not_observed');
        const closeDeadline = Date.now() + 10_000;
        while (!replaySocketClosed && Date.now() < closeDeadline) {
            await page.waitForTimeout(100);
        }
        receipt.cleanup.websocket_closed = replaySocketClosed;
        const stopped = await statusAfterStop(page, uiOrigin, streamId, peerId);
        browserActions += 2;
        receipt.cleanup.post_stop_status = {
            aggregate: {
                body_is_null: stopped.aggregate.body === null,
                status: stopped.aggregate.status,
            },
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
            stopped.targeted.body?.error_code !== 'InvalidParameterError' ||
            stopped.targeted.body?.error_message !== 'getStreamStatus'
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
        if (!replaySocketClosed) fail('websocket_cleanup');

        receipt.status = 'passed';
    } catch (error) {
        receipt.errors.push({ code: error?.code || error?.message || 'runtime_error' });
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
