#!/usr/bin/env node

/*
 * Exercise the shipped NvStreamer UI upload and WebRTC player with a real
 * browser. The caller supplies Playwright through NODE_PATH and retains only
 * this bounded, redacted receipt.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

function fail(message) {
    throw new Error(message);
}

function parseArgs(argv) {
    const values = {};
    for (let index = 0; index < argv.length; index += 2) {
        const flag = argv[index];
        const value = argv[index + 1];
        if (!flag?.startsWith('--') || value === undefined) fail('arguments must be --name value pairs');
        values[flag.slice(2)] = value;
    }
    for (const required of ['endpoint', 'upload', 'sensor-name', 'output', 'chromium']) {
        if (!values[required]) fail(`missing --${required}`);
    }
    const endpoint = new URL(values.endpoint);
    if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' || endpoint.port !== '31000') {
        fail('the browser qualifier is fixed to http://127.0.0.1:31000');
    }
    return values;
}

function safeNetworkRecord(rawUrl, method, status = undefined) {
    const url = new URL(rawUrl);
    return {
        host: url.host,
        loopback: url.hostname === '127.0.0.1' || url.hostname === 'localhost' || url.hostname === '[::1]',
        method,
        path: url.pathname,
        ...(status === undefined ? {} : { status }),
    };
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const upload = await fs.readFile(args.upload);
    if (upload.length < 1024) fail('UI fixture is unexpectedly small');

    const receipt = {
        schema_version: 1,
        status: 'failed',
        endpoint: args.endpoint,
        upload: {
            filename: path.basename(args.upload),
            bytes: upload.length,
            request_status: null,
            sensor_info_status: null,
        },
        network: {
            requests: [],
            failures: [],
            response_count: null,
            api_response_count: null,
            api_failure_count: null,
            external_request_count: 0,
            websocket: null,
        },
        webrtc: {
            sensor_name: args['sensor-name'],
            video_samples: [],
            connecting_overlay_count: null,
            first_frame_observed: false,
        },
    };

    const browser = await chromium.launch({
        executablePath: args.chromium,
        headless: true,
        args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
    });
    try {
        const context = await browser.newContext();
        const page = await context.newPage();
        const responseRecords = [];

        page.on('response', response => {
            const request = response.request();
            const record = safeNetworkRecord(response.url(), request.method(), response.status());
            responseRecords.push(record);
            if (!record.loopback) receipt.network.external_request_count += 1;
        });
        page.on('requestfailed', request => {
            const record = safeNetworkRecord(request.url(), request.method());
            receipt.network.failures.push({ ...record, error: request.failure()?.errorText || 'unknown' });
            if (!record.loopback) receipt.network.external_request_count += 1;
        });
        page.on('websocket', websocket => {
            const wsUrl = new URL(websocket.url());
            const record = {
                host: wsUrl.host,
                path: wsUrl.pathname,
                loopback: wsUrl.hostname === '127.0.0.1',
                frames_sent: 0,
                frames_received: 0,
                closed: false,
            };
            receipt.network.websocket = record;
            websocket.on('framesent', () => {
                record.frames_sent += 1;
            });
            websocket.on('framereceived', () => {
                record.frames_received += 1;
            });
            websocket.on('close', () => {
                record.closed = true;
            });
        });

        await page.goto(`${args.endpoint}/#/media-upload`, { waitUntil: 'networkidle', timeout: 30_000 });
        const fileInputs = page.locator('input[type=file]');
        const inputCount = await fileInputs.count();
        if (inputCount < 1) fail('the shipped Media Upload UI exposes no file input');

        const uploadResponse = page.waitForResponse(
            response =>
                new URL(response.url()).pathname === '/api/v1/storage/file' &&
                response.request().method() === 'POST',
            { timeout: 30_000 },
        );
        await fileInputs.last().setInputFiles({
            name: path.basename(args.upload),
            mimeType: 'video/mp4',
            buffer: upload,
        });
        const response = await uploadResponse;
        receipt.upload.request_status = response.status();
        if (response.status() < 200 || response.status() >= 300) fail(`UI upload returned HTTP ${response.status()}`);
        const uploadBody = await response.json();
        if (!uploadBody || typeof uploadBody.id !== 'string' || typeof uploadBody.streamId !== 'string') {
            fail('UI upload response omitted id or streamId');
        }
        receipt.upload.id = uploadBody.id;
        receipt.upload.stream_id = uploadBody.streamId;

        await page.getByText(/Success - File upload successfully/).waitFor({ state: 'visible', timeout: 20_000 });
        await page.waitForTimeout(500);
        const infoResponse = responseRecords.find(
            item => item.method === 'POST' && item.path === `/api/v1/sensor/${encodeURIComponent(uploadBody.id)}/info`,
        );
        receipt.upload.sensor_info_status = infoResponse?.status ?? null;

        await page.goto(`${args.endpoint}/#/media-streams`, { waitUntil: 'networkidle', timeout: 30_000 });
        const comboboxes = page.getByRole('combobox');
        if ((await comboboxes.count()) !== 2) fail('Media Streams did not expose the expected tag and sensor selectors');
        await comboboxes.nth(1).click();
        const option = page.getByRole('option', { name: args['sensor-name'], exact: true });
        await option.waitFor({ state: 'visible', timeout: 15_000 });
        await option.click();

        const video = page.locator('video[id^="video-live-"]').first();
        await video.waitFor({ state: 'attached', timeout: 15_000 });
        for (let elapsed = 0; elapsed <= 25; elapsed += 1) {
            const sample = await video.evaluate(element => ({
                current_time: element.currentTime,
                ready_state: element.readyState,
                network_state: element.networkState,
                paused: element.paused,
                ended: element.ended,
                video_width: element.videoWidth,
                video_height: element.videoHeight,
                has_src_object: Boolean(element.srcObject),
                tracks: element.srcObject
                    ? Array.from(element.srcObject.getTracks()).map(track => ({
                          kind: track.kind,
                          ready_state: track.readyState,
                          muted: track.muted,
                          enabled: track.enabled,
                      }))
                    : [],
            }));
            receipt.webrtc.video_samples.push({ elapsed_seconds: elapsed, ...sample });
            if (
                sample.current_time > 0 &&
                sample.ready_state >= 2 &&
                sample.video_width > 0 &&
                sample.video_height > 0 &&
                sample.has_src_object &&
                sample.tracks.some(track => track.kind === 'video' && track.ready_state === 'live')
            ) {
                receipt.webrtc.first_frame_observed = true;
                break;
            }
            await page.waitForTimeout(1_000);
        }
        receipt.webrtc.connecting_overlay_count = await page.getByText('WebRTC Connecting...', { exact: true }).count();

        const websocket = receipt.network.websocket;
        if (
            !receipt.webrtc.first_frame_observed ||
            receipt.webrtc.connecting_overlay_count !== 0 ||
            !websocket ||
            !websocket.loopback ||
            websocket.frames_sent < 1 ||
            websocket.frames_received < 1 ||
            receipt.network.external_request_count !== 0
        ) {
            fail('the UI WebRTC playback contract did not close');
        }
        const finalSample = receipt.webrtc.video_samples.at(-1);
        if (
            finalSample.video_width <= 0 ||
            finalSample.video_height <= 0 ||
            finalSample.video_width * 9 !== finalSample.video_height * 16
        ) {
            fail(`WebRTC rendered surface is not a positive 16:9 frame: ${JSON.stringify(finalSample)}`);
        }

        receipt.network.requests = responseRecords.filter(
            item =>
                item.path === '/api/v1/storage/file' ||
                item.path.startsWith('/api/v1/live/'),
        );
        receipt.network.response_count = responseRecords.length;
        receipt.network.api_response_count = responseRecords.filter(item => item.path.startsWith('/api/')).length;
        receipt.network.api_failure_count = receipt.network.failures.filter(item => item.path.startsWith('/api/')).length;
        receipt.status = 'passed';
    } finally {
        await browser.close();
    }

    const output = path.resolve(args.output);
    await fs.writeFile(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o644 });
    process.stdout.write(`${JSON.stringify({ status: receipt.status, output })}\n`);
}

main().catch(async error => {
    process.stderr.write(`${JSON.stringify({ status: 'failed', error: error.message })}\n`);
    process.exitCode = 1;
});
