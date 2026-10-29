// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/city-detections';
const payload = { schemaVersion: 'city.detections.v1', state: 'stopped', ready: true, detail: 'Ready',
  sources: [{ id: 'camera', name: 'Camera', inputUri: 'rtsp://private/password' }], lastExitCode: 1 };
function request(method = 'GET', body?: unknown): NextApiRequest { return { method, body, headers: {} } as NextApiRequest; }
function harness() {
  const state = { code: 200, body: undefined as any, headers: {} as Record<string, unknown> };
  const res = { status(code: number) { state.code = code; return res; }, json(body: unknown) { state.body = body; return res; },
    setHeader(key: string, value: unknown) { state.headers[key] = value; } } as unknown as NextApiResponse;
  return { state, res };
}
beforeEach(() => { process.env.VSS_CITY_CONTROLLER_URL = 'http://controller.test:9190'; global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => payload }); });
afterEach(() => { delete process.env.VSS_CITY_CONTROLLER_URL; jest.restoreAllMocks(); });
it('reads actual stopped worker status from the fixed controller and strips camera URIs', async () => {
  const { state, res } = harness(); await handler(request(), res);
  expect(state.body.state).toBe('stopped'); expect(state.body.lastExitCode).toBe(1);
  expect(state.body.sources).toEqual([{ id: 'camera', name: 'Camera' }]);
  expect(state.headers['Cache-Control']).toBe('no-store');
  expect(String((fetch as jest.Mock).mock.calls[0][0])).toBe('http://controller.test:9190/api/v1/detections');
});
it.each(['start', 'stop', 'restart'])('forwards the bounded %s operation', async action => {
  const { state, res } = harness(); await handler(request('POST', { action }), res);
  expect(state.code).toBe(200); expect(JSON.parse((fetch as jest.Mock).mock.calls[0][1].body)).toEqual({ action });
});
it.each([null, [], { action: 'delete' }, { action: 'start', sourceId: 'other' }, { action: 'stop', command: 'docker' }])('rejects invalid controls before touching runtime: %j', async body => {
  const { state, res } = harness(); await handler(request('POST', body), res);
  expect(state.code).toBe(422); expect(fetch).not.toHaveBeenCalled();
});
it('rejects cross-site controls and unsupported methods', async () => {
  const req = request('POST', { action: 'stop' }); req.headers['sec-fetch-site'] = 'cross-site';
  const first = harness(); await handler(req, first.res); expect(first.state.code).toBe(403);
  const second = harness(); await handler(request('DELETE'), second.res); expect(second.state.code).toBe(405);
  expect(fetch).not.toHaveBeenCalled();
});
it('preserves guard/admission failures', async () => {
  (fetch as jest.Mock).mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'Cold-start headroom is unavailable' }) });
  const { state, res } = harness(); await handler(request('POST', { action: 'start' }), res);
  expect(state.code).toBe(503); expect(state.body.error).toMatch(/headroom/);
});
it('fails closed on malformed or disconnected controller status', async () => {
  (fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ ...payload, sources: [{}] }) });
  const { state, res } = harness(); await handler(request(), res); expect(state.code).toBe(503);
});
