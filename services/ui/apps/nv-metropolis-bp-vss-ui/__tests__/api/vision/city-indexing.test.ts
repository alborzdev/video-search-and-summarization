// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/city-indexing';
function req(body?: unknown, method = 'POST'): NextApiRequest { return { method, body, query: method === 'GET' ? { sourceId: 'camera' } : {}, headers: {} } as NextApiRequest; }
function harness() {
  const state = { code: 200, body: undefined as any, headers: {} as Record<string, unknown> };
  const res = { status(code: number) { state.code = code; return res; }, json(body: unknown) { state.body = body; return res; }, setHeader(key: string, value: unknown) { state.headers[key] = value; } } as unknown as NextApiResponse;
  return { state, res };
}
function response(value: unknown, code = 200): Response {
  const bytes = Buffer.from(JSON.stringify(value)); let done = false;
  return { ok: code < 300, status: code, headers: { get: () => null }, body: { getReader: () => ({ read: async () => done ? { done: true } : (done = true, { done: false, value: bytes }), cancel: jest.fn(), releaseLock: jest.fn() }) } } as unknown as Response;
}
const body = { sourceId: 'camera', name: 'Southwest', action: 'search', sessionId: 'session-one', query: 'a bus stops', topK: 6 };
const scope = { sourceId: 'camera', sourceName: 'Southwest', timestampStart: '2026-10-26T15:00:00Z', timestampEnd: '2026-10-26T15:02:00Z' };
const prepared = () => ({ endpoint: '/api/v1/embed_search', sessionId: 'session-one', scope, request: { source_type: 'rtsp', params: { query: 'a bus stops', top_k: '6', exact_sensor_ids: '["camera","Southwest"]', timestamp_start: scope.timestampStart, timestamp_end: scope.timestampEnd } } });
beforeEach(() => { process.env.VISION_AGENT_INTERNAL_URL = 'http://agent.test/api/v1'; global.fetch = jest.fn(); });
afterEach(() => { delete process.env.VISION_AGENT_INTERNAL_URL; });

it('reads only the fixed per-source status path', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response({ sensorId: 'camera', mode: 'on-demand' }));
  const { state, res } = harness(); await handler(req(undefined, 'GET'), res);
  expect(state.code).toBe(200); expect((global.fetch as jest.Mock).mock.calls[0][0]).toBe('http://agent.test/api/v1/rtsp-streams/camera/indexing');
  expect(state.headers['Cache-Control']).toBe('no-store');
});

it('forwards a finite explicit start without changing CV or enabling continuous indexing', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response({ state: 'recovering' }));
  const { state, res } = harness(); await handler(req({ sourceId: 'camera', name: 'Southwest', action: 'start', durationSeconds: 120 }), res);
  expect(state.code).toBe(200);
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toEqual({ name: 'Southwest', action: 'start', durationSeconds: 120 });
});

it.each([{ ...body, action: 'policy', mode: 'continuous' }, { ...body, action: 'start', durationSeconds: 9999 }, { ...body, exact_sensor_ids: '["other"]' }, { ...body, url: 'http://other' }, { ...body, sourceId: '../other' }])('rejects broad or malformed control input before a service request', async invalid => {
  const { state, res } = harness(); await handler(req(invalid), res); expect(state.code).toBe(422); expect(global.fetch).not.toHaveBeenCalled();
});

it('executes strict server-prepared source/time parameters and removes unverified hits and vectors', async () => {
  const hit = { sensor_id: 'camera', start_time: '2026-10-26T15:00:30Z', end_time: '2026-10-26T15:00:35Z', video_name: 'Southwest', description: 'A bus', screenshot_url: 'javascript:bad()', similarity_score: .9 };
  (global.fetch as jest.Mock).mockResolvedValueOnce(response(prepared())).mockResolvedValueOnce(response({ results: [hit, { ...hit, sensor_id: 'other' }, { ...hit, start_time: '2026-10-25T15:00:30Z' }], query_embedding: [1, 2] }));
  const { state, res } = harness(); await handler(req(body), res);
  expect(state.code).toBe(200); expect(state.body.results).toHaveLength(1); expect(state.body.excludedResults).toBe(2);
  expect(state.body.scope.executed).toBe(true); expect(state.body.sessionId).toBe('session-one'); expect(state.body.query_embedding).toBeUndefined();
  const sent = JSON.parse((global.fetch as jest.Mock).mock.calls[1][1].body);
  expect((global.fetch as jest.Mock).mock.calls[1][0]).toBe('http://agent.test/api/v1/embed_search');
  expect(sent.params.exact_sensor_ids).toBe('["camera","Southwest"]'); expect(sent.params.timestamp_start).toBe(scope.timestampStart);
  expect(sent.params.video_sources).toBeUndefined(); expect(state.body.results[0].screenshot_url).toBeUndefined();
});

it('does not call search if the prepared camera/session scope differs', async () => {
  const wrong = prepared(); wrong.request.params.exact_sensor_ids = '["other","Southwest"]';
  (global.fetch as jest.Mock).mockResolvedValue(response(wrong));
  const { state, res } = harness(); await handler(req(body), res);
  expect(state.code).toBe(502); expect(global.fetch).toHaveBeenCalledTimes(1);
});

it('accepts the exact registered name alias from released embedding schemas and canonicalizes the result ID', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(response(prepared())).mockResolvedValueOnce(response({ results: [
    { sensor_id: 'Southwest', start_time: '2026-10-26T15:00:30Z', end_time: '2026-10-26T15:00:35Z' },
    { sensor_id: 'Southwest-copy', start_time: '2026-10-26T15:00:30Z', end_time: '2026-10-26T15:00:35Z' },
  ] }));
  const { state, res } = harness(); await handler(req(body), res);
  expect(state.code).toBe(200); expect(state.body.results).toHaveLength(1);
  expect(state.body.results[0].sensor_id).toBe('camera'); expect(state.body.excludedResults).toBe(1);
});

it('preserves a stale-session conflict and rejects a foreign origin', async () => {
  (global.fetch as jest.Mock).mockResolvedValue(response({ detail: 'Choose the current session again' }, 409));
  const first = harness(); await handler(req(body), first.res); expect(first.state.code).toBe(409);
  (global.fetch as jest.Mock).mockClear(); const foreign = req(body); foreign.headers = { origin: 'http://foreign.test', host: 'local.test' };
  const second = harness(); await handler(foreign, second.res); expect(second.state.code).toBe(403); expect(global.fetch).not.toHaveBeenCalled();
});
