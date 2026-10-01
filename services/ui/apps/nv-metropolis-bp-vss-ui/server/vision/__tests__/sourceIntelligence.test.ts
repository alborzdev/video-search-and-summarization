/** @jest-environment node */
import { fetchSourceIntelligence } from '../sourceIntelligence';

function stalledFetch(_url: unknown, options?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(options.signal?.reason), { once: true });
  });
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.spyOn(AbortSignal, 'timeout').mockImplementation((milliseconds) => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(new Error('Deadline elapsed')), milliseconds);
    return controller.signal;
  });
});
afterEach(() => { jest.useRealTimers(); });

it('aborts every stalled Elasticsearch request after five seconds and reports unavailable', async () => {
  global.fetch = jest.fn(stalledFetch) as typeof fetch;
  const pending = fetchSourceIntelligence('camera-id', 'Camera');
  expect(global.fetch).toHaveBeenCalledTimes(5);
  expect(AbortSignal.timeout).toHaveBeenCalledTimes(5);
  for (const [milliseconds] of (AbortSignal.timeout as jest.Mock).mock.calls) expect(milliseconds).toBe(5000);
  await jest.advanceTimersByTimeAsync(4999);
  for (const [, options] of (global.fetch as jest.Mock).mock.calls) expect(options.signal.aborted).toBe(false);
  await jest.advanceTimersByTimeAsync(1);
  await expect(pending).resolves.toBeNull();
  for (const [, options] of (global.fetch as jest.Mock).mock.calls) expect(options.signal.aborted).toBe(true);
});

it('retains successful source-scoped facts when other Elasticsearch requests time out', async () => {
  global.fetch = jest.fn((url, options) => String(url).includes('/mdx-incidents-')
    ? Promise.resolve({ ok: true, json: async () => ({ count: 3 }) } as Response)
    : stalledFetch(url, options)) as typeof fetch;
  const pending = fetchSourceIntelligence('camera-id', 'Camera');
  await jest.advanceTimersByTimeAsync(5000);
  const result = await pending;
  expect(result).toMatchObject({ source: { name: 'Camera', sensorId: 'camera-id' }, evidenceEvents: 3,
    semanticSegments: null, trackedObservations: null, captionSegments: null, lastSemanticAt: null, semanticFresh: null });
  const incidentCall = (global.fetch as jest.Mock).mock.calls.find(([url]) => url.includes('/mdx-incidents-'));
  expect(JSON.parse(incidentCall![1].body).query.bool.should).toEqual([
    { term: { 'sensorId.keyword': 'camera-id' } }, { term: { 'sensorId.keyword': 'Camera' } },
    { term: { 'sensor.id.keyword': 'camera-id' } }, { term: { 'sensor.id.keyword': 'Camera' } },
  ]);
});
