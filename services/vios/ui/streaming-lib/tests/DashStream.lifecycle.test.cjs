// SPDX-License-Identifier: Apache-2.0
// Node 22.13+: executes the actual TS class without installing browser packages.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { stripTypeScriptTypes } = require('node:module');

const source = stripTypeScriptTypes(fs.readFileSync(path.join(__dirname, '../src/dash/DashStream.ts'), 'utf8'))
    .replace("import dashjs from 'dashjs';", '')
    .replace('export class DashStream', 'class DashStream') + '\nDashStream;';
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const response = viewerId => ({ ok: true, json: async () => ({ data: { viewerId, manifestUrl: '/manifest.mpd', state: 'playing', audioAvailable: false } }) });
const tick = () => new Promise(resolve => setImmediate(resolve));
const config = (streamId, replay = false, endpoint = 'http://original.test') => ({ endpoint, streamId, videoElement: {}, ...(replay ? { startTime: '2025-01-01T00:00:00Z', endTime: '2025-01-01T00:00:08Z' } : {}) });
function setup(handler) {
    const calls = [], attached = [], listeners = new Set();
    const DashStream = vm.runInNewContext(source, {
        URL, setTimeout, clearTimeout, setInterval, clearInterval, console, dashjs: {},
        window: { addEventListener: (_name, listener) => listeners.add(listener), removeEventListener: (_name, listener) => listeners.delete(listener) },
        fetch: (url, options) => { const call = { url, body: options?.body ? JSON.parse(options.body) : undefined, options }; calls.push(call); return handler(call); },
    });
    const stream = new DashStream();
    stream.attachPlayer = async (_config, result) => { attached.push(result.viewerId); };
    return { stream, calls, attached, listeners };
}

test('stop during a pending start releases only the late returned viewer', async () => {
    const pending = deferred();
    const { stream, calls, attached, listeners } = setup(call => call.url.endsWith('/start') ? pending.promise : Promise.resolve({ ok: true }));
    const started = stream.start(config('old'));
    await tick();
    await stream.stop();
    pending.resolve(response('late-viewer'));
    assert.equal(await started, null);
    assert.deepEqual(attached, []);
    assert.equal(listeners.size, 0);
    assert.deepEqual(calls.filter(call => call.url.endsWith('/stop')).map(call => call.body.viewerId), ['late-viewer']);
    assert.equal(calls.at(-1).url, 'http://original.test/vst/api/v1/live/dash/stop');
});

test('an old live response cannot overwrite a newer replay viewer or its endpoint', async () => {
    const old = deferred(), replacement = deferred();
    const { stream, calls, attached, listeners } = setup(call => call.url.endsWith('/start') ? (call.body.streamId === 'old' ? old.promise : replacement.promise) : Promise.resolve({ ok: true }));
    const first = stream.start(config('old'));
    await tick();
    const second = stream.start(config('new', true, 'http://replacement.test'));
    await tick();
    replacement.resolve(response('new-viewer'));
    assert.equal((await second).viewerId, 'new-viewer');
    old.resolve(response('old-viewer'));
    assert.equal(await first, null);
    assert.deepEqual(attached, ['new-viewer']);
    assert.equal(listeners.size, 1);
    await stream.stop('http://unrelated.test', 'unrelated');
    const stops = calls.filter(call => call.url.endsWith('/stop'));
    assert.deepEqual(stops.map(call => [call.url, call.body.viewerId, call.options.headers.streamid]), [
        ['http://original.test/vst/api/v1/live/dash/stop', 'old-viewer', 'old'],
        ['http://replacement.test/vst/api/v1/replay/dash/stop', 'new-viewer', 'new'],
    ]);
    assert.equal(listeners.size, 0);
});

test('cancellation while the previous lease is stopping prevents a new start request', async () => {
    const releasing = deferred();
    const { stream, calls, attached } = setup(call => call.url.endsWith('/start') ? Promise.resolve(response('initial-viewer')) : releasing.promise);
    await stream.start(config('initial'));
    const replacement = stream.start(config('cancelled'));
    await tick();
    await stream.stop();
    releasing.resolve({ ok: true });
    assert.equal(await replacement, null);
    assert.equal(calls.filter(call => call.url.endsWith('/start')).length, 1);
    assert.deepEqual(attached, ['initial-viewer']);
});

test('a stale network failure does not report failure for a replacement', async () => {
    const old = deferred();
    const { stream, attached } = setup(call => call.url.endsWith('/start') && call.body.streamId === 'old' ? old.promise : Promise.resolve(call.url.endsWith('/start') ? response('new-viewer') : { ok: true }));
    const first = stream.start(config('old'));
    await tick();
    await stream.start(config('new'));
    old.reject(new Error('old request disconnected'));
    assert.equal(await first, null);
    assert.deepEqual(attached, ['new-viewer']);
    await stream.stop();
});

test('an active start failure still reaches its caller', async () => {
    const { stream } = setup(() => Promise.reject(new Error('current request disconnected')));
    await assert.rejects(stream.start(config('current')), /current request disconnected/);
});

test('a late seek cannot reset or replace a newly started viewer', async () => {
    const seeking = deferred();
    const { stream, calls, attached } = setup(call => {
        if (call.url.endsWith('/seek')) return seeking.promise;
        return Promise.resolve(call.url.endsWith('/start') ? response(call.body.streamId + '-viewer') : { ok: true });
    });
    await stream.start(config('old', true));
    const seek = stream.seekReplay('2025-01-01T00:00:04Z');
    await tick();
    await stream.start(config('new', true));
    seeking.resolve(response('new-seek-viewer'));
    assert.equal(await seek, null);
    assert.deepEqual(attached, ['old-viewer', 'new-viewer']);
    assert.equal(calls.at(-1).body.viewerId, 'new-seek-viewer');
    await stream.stop();
    assert.equal(calls.at(-1).body.viewerId, 'new-viewer');
});

test('replay seeks serialize server packager replacements and attach only the latest position', async () => {
    const first = deferred(), second = deferred();
    const { stream, calls, attached } = setup(call => {
        if (call.url.endsWith('/seek')) return call.body.startTime.endsWith('02Z') ? first.promise : second.promise;
        return Promise.resolve(call.url.endsWith('/start') ? response('viewer') : { ok: true });
    });
    await stream.start(config('replay', true));
    const older = stream.seekReplay('2025-01-01T00:00:02Z');
    await tick();
    const latest = stream.seekReplay('2025-01-01T00:00:06Z');
    await tick();
    assert.equal(calls.filter(call => call.url.endsWith('/seek')).length, 1);
    first.resolve(response('viewer-B'));
    assert.equal(await older, null);
    await tick();
    assert.equal(calls.filter(call => call.url.endsWith('/seek')).length, 2);
    assert.deepEqual(calls.filter(call => call.url.endsWith('/seek')).map(call => call.body.viewerId), ['viewer', 'viewer-B']);
    second.resolve(response('viewer-C'));
    assert.equal((await latest).viewerId, 'viewer-C');
    assert.deepEqual(attached, ['viewer', 'viewer-C']);
    await stream.stop();
    assert.equal(calls.at(-1).body.viewerId, 'viewer-C');
});


test('stop while native seek allocates a new viewer releases that returned lease', async () => {
    const seeking = deferred();
    const { stream, calls, attached, listeners } = setup(call => call.url.endsWith('/seek') ? seeking.promise : Promise.resolve(call.url.endsWith('/start') ? response('viewer-A') : { ok: true }));
    await stream.start(config('replay', true));
    const seek = stream.seekReplay('2025-01-01T00:00:03Z');
    await tick();
    await stream.stop();
    seeking.resolve(response('viewer-B'));
    assert.equal(await seek, null);
    assert.deepEqual(calls.filter(call => call.url.endsWith('/stop')).map(call => call.body.viewerId), ['viewer-A', 'viewer-B']);
    assert.deepEqual(attached, ['viewer-A']);
    assert.equal(listeners.size, 0);
});


test('retired dash.js instances destroy their context and remove the video error listener', async () => {
    const { stream } = setup(() => Promise.resolve({ ok: true }));
    let destroyed = 0, reset = 0;
    const removed = [];
    const listener = () => {};
    stream.videoElement = { removeEventListener: (name, handler) => removed.push([name, handler]) };
    stream.videoErrorListener = listener;
    stream.player = { destroy() { destroyed += 1; assert.equal(stream.player, null); }, reset() { reset += 1; } };
    await stream.stop();
    assert.equal(destroyed, 1);
    assert.equal(reset, 0);
    assert.equal(removed[0][0], 'error');
    assert.equal(removed[0][1], listener);
    await stream.stop();
    assert.equal(destroyed, 1);
});


test('SDK destruction failure cannot prevent releasing the native viewer lease', async () => {
    const { stream, calls } = setup(call => Promise.resolve(call.url.endsWith('/start') ? response('owned-viewer') : { ok: true }));
    await stream.start(config('replay', true));
    stream.player = { destroy() { throw new Error('SDK teardown failed'); } };
    await stream.stop();
    assert.equal(calls.at(-1).body.viewerId, 'owned-viewer');
    assert.equal(stream.player, null);
});
