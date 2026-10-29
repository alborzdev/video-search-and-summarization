// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import handler, { publicLocalVisionPayload, validateLocalVisionInput } from '../../../pages/api/vision/local-model';
const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).toString('base64');
function request(body?: unknown, method = 'POST') { return { method, body, query: {}, headers: {} } as NextApiRequest; }
function responseHarness() {
  const state = { body: undefined as any, status: 200, headers: {} as Record<string, unknown> };
  const response = { status(code: number) { state.status = code; return response; }, json(body: unknown) { state.body = body; return response; }, setHeader(key: string, value: unknown) { state.headers[key] = value; }, on: jest.fn(), off: jest.fn() } as unknown as NextApiResponse;
  return { state, response };
}
function upstream(value: unknown, status = 200, reportedSize = 0): Response {
  const bytes = Buffer.from(JSON.stringify(value)); let read = false;
  return { ok: status < 300, status, headers: { get: () => String(reportedSize) }, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { done: false, value: bytes }), cancel: jest.fn(), releaseLock: jest.fn() }) } } as unknown as Response;
}
beforeEach(() => { process.env.LOCAL_VISION_API_TOKEN = 'server-secret'; process.env.LOCAL_VISION_API_URL = 'http://127.0.0.1:8026'; });
afterEach(() => { delete process.env.LOCAL_VISION_API_TOKEN; delete process.env.LOCAL_VISION_API_URL; });
it('forwards canonical image tasks to a fixed service with a server-only token', async () => {
  global.fetch = jest.fn().mockResolvedValue(upstream({ operation: 'segment', objects: [{ point: [.2, .3], mask_png_base64: 'png' }], timings_ms: { total: 500 }, moondream_receipt: { path: '/private/weights' }, token: 'server-secret' }));
  const { state, response } = responseHarness(); await handler(request({ task: 'segment', image_base64: png, object: ' person ' }), response);
  expect(state.status).toBe(200); expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toBe('http://127.0.0.1:8026/infer');
  const sent = (global.fetch as jest.Mock).mock.calls[0][1];
  expect(sent.headers['X-VSS-Model-Token']).toBe('server-secret'); expect(JSON.parse(sent.body)).toEqual({ task: 'segment', image_base64: png, object: 'person', grounded_by: 'point', presence: 'off' });
  expect(state.body.objects[0].mask_png_base64).toBe('png'); expect(JSON.stringify(state.body)).not.toMatch(/private|secret|receipt/);
});
it.each([{ task: 'segment', image_base64: png, object: 'person', url: 'http://other' }, { task: 'detect', image_base64: '/tmp/file', object: 'person' }, { task: 'point', image_base64: png, object: '' }, { task: 'segment', image_base64: png, object: 'person', grounded_by: 'oracle' }])('rejects invalid or path/URL input without reaching the model', async body => {
  global.fetch = jest.fn(); const { state, response } = responseHarness(); await handler(request(body), response); expect(state.status).toBe(422); expect(global.fetch).not.toHaveBeenCalled();
});
it('omits spatial-only options for a description and bounds image bytes', () => {
  expect(validateLocalVisionInput({ task: 'describe', image_base64: png })).toEqual({ task: 'describe', image_base64: png });
  expect(validateLocalVisionInput({ task: 'describe', image_base64: Buffer.alloc(2 * 1024 * 1024 + 1).toString('base64') })).toBeNull();
});
it('preserves busy status without leaking upstream diagnostics', async () => {
  global.fetch = jest.fn().mockResolvedValue(upstream({ error: '/secret/token', status: 'busy' }, 429));
  const { state, response } = responseHarness(); await handler(request({ task: 'describe', image_base64: png }), response);
  expect(state.status).toBe(429); expect(state.headers['Retry-After']).toBe('2'); expect(state.body.error).toMatch(/busy/); expect(JSON.stringify(state.body)).not.toMatch(/secret/);
});
it('fails unavailable without a token and rejects foreign-origin requests', async () => {
  global.fetch = jest.fn(); delete process.env.LOCAL_VISION_API_TOKEN;
  const first = responseHarness(); await handler(request(undefined, 'GET'), first.response); expect(first.state.status).toBe(503);
  const req = request({ task: 'describe', image_base64: png }); req.headers = { origin: 'http://untrusted.example', host: 'localhost:3001' };
  const second = responseHarness(); await handler(req, second.response); expect(second.state.status).toBe(403); expect(global.fetch).not.toHaveBeenCalled();
});
it('returns only public readiness fields and rejects an oversized response', async () => {
  const payload = { ready: true, model: 'moondream2', segmenter: 'sam2.1-tiny', busy: false, private_path: '/weights' };
  expect(publicLocalVisionPayload(payload)).toEqual({ ready: true, model: 'moondream2', segmenter: 'sam2.1-tiny', busy: false });
  global.fetch = jest.fn().mockResolvedValue(upstream(payload, 200, 13 * 1024 * 1024)); const { state, response } = responseHarness(); await handler(request(undefined, 'GET'), response); expect(state.status).toBe(502);
});
