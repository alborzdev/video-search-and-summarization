// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/city-demo';

const requestId = '11111111-2222-4333-8444-555555555555';
const runId = 'native-session:000007';
const payload = { schemaVersion: 'city.tradeshow-control.v1', available: true, playing: true,
  scenario: { active: true, state: 'ready', runId, catalog: [], analyticsBoundary: { ready: true } } };
function req(body?: unknown, method = 'POST'): NextApiRequest { return { method, body, headers: {} } as NextApiRequest; }
function harness() {
  const state = { code: 200, body: undefined as any, headers: {} as Record<string, unknown> };
  const res = { status(code: number) { state.code = code; return res; }, json(body: unknown) { state.body = body; return res; },
    setHeader(key: string, value: unknown) { state.headers[key] = value; } } as unknown as NextApiResponse;
  return { state, res };
}
function response(value: unknown, code = 200) { return { ok: code < 300, status: code, json: async () => value }; }
beforeEach(() => { process.env.VSS_CITY_CONTROLLER_URL = 'http://controller.test:9190'; global.fetch = jest.fn().mockResolvedValue(response(payload)); });
afterEach(() => { delete process.env.VSS_CITY_CONTROLLER_URL; jest.restoreAllMocks(); });

it('reads status from the fixed controller endpoint without changing the scene', async () => {
  const { state, res } = harness(); await handler(req(undefined, 'GET'), res);
  expect(state.code).toBe(200); expect(state.body).toEqual(payload); expect(state.headers['Cache-Control']).toBe('no-store');
  const [url, options] = (fetch as jest.Mock).mock.calls[0]; expect(String(url)).toBe('http://controller.test:9190/api/v1/demo');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined();
});

it.each([
  { operation: 'prepare', scenarioId: 'queue-recovery', requestId },
  { operation: 'play', runId, requestId },
  { operation: 'cancel', runId, requestId },
  { operation: 'retry', runId, requestId },
])('forwards the exact prepared operation and current run identity: $operation', async body => {
  const { state, res } = harness(); await handler(req(body), res);
  expect(state.code).toBe(200); expect(state.body.scenario.analyticsBoundary.ready).toBe(true);
  const [url, options] = (fetch as jest.Mock).mock.calls[0]; expect(String(url)).toBe('http://controller.test:9190/api/v1/demo');
  expect(JSON.parse(options.body)).toEqual(body);
});

it.each([
  { operation: 'prepare', requestId },
  { operation: 'prepare', scenarioId: '../scene', requestId },
  { operation: 'play', requestId },
  { operation: 'play', runId: '', requestId },
  { operation: 'play', runId: '../old', requestId },
  { operation: 'play', runId, scenarioId: 'queue-recovery', requestId },
  { operation: 'cancel', runId: 7, requestId },
  { operation: 'retry', runId, requestId: 'short' },
  { operation: 'prepare', scenarioId: 'queue-recovery', requestId, resetAll: true },
  { operation: 'teleport', runId, requestId },
  null,
  [],
])('rejects malformed or broad operations before contacting the controller', async body => {
  const { state, res } = harness(); await handler(req(body), res); expect(state.code).toBe(422); expect(fetch).not.toHaveBeenCalled();
});

it('preserves a stale-run conflict rather than disguising it as success', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ detail: 'That prepared run is no longer current.' }, 409));
  const { state, res } = harness(); await handler(req({ operation: 'play', runId, requestId }), res);
  expect(state.code).toBe(409); expect(state.body.error).toBe('That prepared run is no longer current.');
});

it('fails closed for an invalid controller response', async () => {
  (fetch as jest.Mock).mockResolvedValue(response({ schemaVersion: 'other' }));
  const { state, res } = harness(); await handler(req(undefined, 'GET'), res); expect(state.code).toBe(503);
});

it('rejects cross-site writes and unsupported methods', async () => {
  const foreign = req({ operation: 'prepare', scenarioId: 'queue-recovery', requestId }); foreign.headers['sec-fetch-site'] = 'cross-site';
  const first = harness(); await handler(foreign, first.res); expect(first.state.code).toBe(403);
  const second = harness(); await handler(req(undefined, 'DELETE'), second.res); expect(second.state.code).toBe(405);
  expect(second.state.headers.Allow).toBe('GET, POST'); expect(fetch).not.toHaveBeenCalled();
});
