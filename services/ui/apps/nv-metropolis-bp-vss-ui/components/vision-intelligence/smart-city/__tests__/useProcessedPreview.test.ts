// SPDX-License-Identifier: MIT
import { act, renderHook } from '@testing-library/react';
import React from 'react';
import { TextDecoder } from 'node:util';
import { useProcessedPreview } from '../useProcessedPreview';
import { previewContext } from '../processedPreview';
const context = (id = 'a', revision = 1) => previewContext({ id: 'city', revision, mode: 'live' } as any, { id, name: id, width: 1000, height: 1000 }, revision);
Object.assign(global, { TextDecoder });
function frameResponse(id = 'a', sequence = '1') {
  const source = { id, name: id, width: 1000, height: 1000, sequence, sessionId: 'epoch', sourceSessionId: 'native', lastSourceTimeNs: '1700000000000000000' };
  const dto = { schemaVersion: 'city.preview.v1', sourceId: id, sourceSessionId: 'native', sessionId: 'epoch', sequence, sourceTimeNs: source.lastSourceTimeNs, image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500, mimeType: 'image/jpeg' }, provenance: { kind: 'native-post-inference-exact-frame', correlation: 'source-session-sequence-time', clockAlignment: 'source-frame-exact', browserClockVerified: false }, snapshot: { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence, sources: [source], tracks: [], rules: [], events: [], metrics: [], zones: [] } };
  const json = Buffer.from(JSON.stringify(dto)); const prefix = Buffer.alloc(4); prefix.writeUInt32BE(json.length);
  const bytes = Buffer.concat([prefix, json, Buffer.from([255, 216, 1, 255, 217])]);
  return { ok: true, status: 200, headers: { get: (key: string) => key === 'Content-Type' ? 'application/vnd.connecttech.city-frame' : key === 'ETag' ? `${id}-${sequence}` : null }, body: { getReader: () => ({ read: jest.fn().mockResolvedValueOnce({ done: false, value: bytes }).mockResolvedValue({ done: true }), cancel: jest.fn(), releaseLock: jest.fn() }) } };
}
describe('bounded analyzed preview reader', () => {
  const originalFetch = global.fetch; const originalDecode = global.createImageBitmap;
  beforeEach(() => { jest.useFakeTimers(); global.createImageBitmap = jest.fn().mockImplementation(async () => ({ width: 500, height: 500, close: jest.fn() })); });
  afterEach(() => { jest.useRealTimers(); global.fetch = originalFetch; global.createImageBitmap = originalDecode; });
  it('presents decoded exact pairs, limits requests to fifteen per second and closes superseded bitmaps', async () => {
    let sequence = 0; global.fetch = jest.fn().mockImplementation(async () => frameResponse('a', String(++sequence)));
    const { result, unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context()));
    await act(async () => {}); const first = result.current!; expect(first.frame.sequence).toBe('1');
    await act(async () => { jest.advanceTimersByTime(66); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(2);
    expect(first.bitmap.close).toHaveBeenCalledTimes(1); const last = result.current!; unmount(); expect(last.bitmap.close).toHaveBeenCalledTimes(1);
  });
  it('uses conditional reads and drops a repeated frame after the independent stale deadline', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockResolvedValue({ ok: false, status: 304 });
    const { result, unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context())); await act(async () => {});
    const bitmap = result.current!.bitmap;
    await act(async () => { jest.advanceTimersByTime(67); });
    expect((fetch as jest.Mock).mock.calls[1][1].headers).toEqual({ 'If-None-Match': 'a-1' });
    expect(createImageBitmap).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(2000); }); expect(result.current).toBeNull(); expect(bitmap.close).toHaveBeenCalledTimes(1); unmount();
  });
  it('includes request latency in the frame interval while keeping one request in flight', async () => {
    let finish!: (value: unknown) => void;
    global.fetch = jest.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context()));
    await act(async () => { jest.advanceTimersByTime(50); });
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => finish(frameResponse()));
    await act(async () => { jest.advanceTimersByTime(16); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => { jest.advanceTimersByTime(100); }); expect(fetch).toHaveBeenCalledTimes(2);
    unmount();
  });
  it('permits the native30 ceiling with conditional reads and no repeated-frame decode', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockResolvedValue({ status: 304 });
    const { result, unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context(), 30)); await act(async () => {});
    const bitmap = result.current!.bitmap; await act(async () => { jest.advanceTimersByTime(33); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(2);
    expect((fetch as jest.Mock).mock.calls[1][1].headers).toEqual({ 'If-None-Match': 'a-1' }); expect(createImageBitmap).toHaveBeenCalledTimes(1); expect(bitmap.close).not.toHaveBeenCalled();
    unmount(); expect(bitmap.close).toHaveBeenCalledTimes(1);
  });
  it.each([undefined, Number.NaN, Infinity, 0, -1, 1.5])('retains the safe15 ceiling for invalid/unknown limit %s', async limit => {
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockResolvedValue({ status: 304 });
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context(), limit)); await act(async () => {});
    await act(async () => { jest.advanceTimersByTime(66); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(2); unmount();
  });
  it('caps excessive configured limits at30 instead of creating an unbounded poll loop', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockResolvedValue({ status: 304 });
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context(), 120)); await act(async () => {});
    await act(async () => { jest.advanceTimersByTime(33); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(2); unmount();
  });
  it('changes the rate without releasing a valid pair and rechecks lowered limits before a scheduled read', async () => {
    let sequence = 0; global.fetch = jest.fn().mockImplementation(async () => frameResponse('a', String(++sequence)));
    const { result, rerender, unmount } = renderHook(({ limit }) => useProcessedPreview('a', true, 'epoch', context(), limit), { initialProps: { limit: 15 } }); await act(async () => {});
    const first = result.current!.bitmap; await act(async () => { jest.advanceTimersByTime(34); }); rerender({ limit: 30 });
    expect(fetch).toHaveBeenCalledTimes(1); expect(first.close).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(33); }); expect(fetch).toHaveBeenCalledTimes(2); const next = result.current!.bitmap;
    rerender({ limit: 10 }); expect(next.close).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(99); }); expect(fetch).toHaveBeenCalledTimes(2); expect(next.close).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(1); }); expect(fetch).toHaveBeenCalledTimes(3); expect(next.close).toHaveBeenCalledTimes(1); unmount();
  });
  it('never overlaps a slow native30 read/decode with another request', async () => {
    let finish!: (value: unknown) => void; global.fetch = jest.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context(), 30));
    await act(async () => { jest.advanceTimersByTime(50); }); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => finish(frameResponse())); await act(async () => { jest.advanceTimersByTime(0); }); expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => { jest.advanceTimersByTime(100); }); expect(fetch).toHaveBeenCalledTimes(2); unmount();
  });
  it('suppresses a late decoded image from an obsolete source generation', async () => {
    let finish!: (bitmap: ImageBitmap) => void; const oldBitmap = { width: 500, height: 500, close: jest.fn() } as unknown as ImageBitmap;
    global.createImageBitmap = jest.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockResolvedValue({ ok: true, status: 204 });
    const { result, rerender, unmount } = renderHook(({ id }) => useProcessedPreview(id, true, 'epoch', context(id)), { initialProps: { id: 'a' } });
    await act(async () => {}); rerender({ id: 'b' }); await act(async () => { finish(oldBitmap); });
    expect(result.current).toBeNull(); expect(oldBitmap.close).toHaveBeenCalledTimes(1); unmount();
  });
  it('aborts a stalled request on deadline and unmount without concurrent retries', async () => {
    let signal!: AbortSignal; global.fetch = jest.fn().mockImplementation((_url, init) => { signal = init.signal; return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('abort')))); });
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context()));
    await act(async () => { jest.advanceTimersByTime(1500); }); expect(signal.aborted).toBe(true); expect(fetch).toHaveBeenCalledTimes(1);
    unmount(); await act(async () => { jest.advanceTimersByTime(10_000); }); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('hides and closes an already presented pair synchronously when configuration changes and the expected session disappears', async () => {
    global.fetch = jest.fn().mockResolvedValue(frameResponse());
    const { result, rerender, unmount } = renderHook(({ revision, session }) => useProcessedPreview('a', true, session, context('a', revision)), { initialProps: { revision: 1, session: 'epoch' as string | undefined } });
    await act(async () => {}); const bitmap = result.current!.bitmap;
    rerender({ revision: 2, session: undefined });
    expect(result.current).toBeNull(); expect(bitmap.close).toHaveBeenCalledTimes(1); expect(fetch).toHaveBeenCalledTimes(1); unmount();
  });
  it('closes an old same-source decode that finishes after a calibration generation change', async () => {
    let finish!: (bitmap: ImageBitmap) => void; const bitmap = { width: 500, height: 500, close: jest.fn() } as unknown as ImageBitmap;
    global.createImageBitmap = jest.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    global.fetch = jest.fn().mockResolvedValue(frameResponse());
    const { result, rerender, unmount } = renderHook(({ revision, session }) => useProcessedPreview('a', true, session, context('a', revision)), { initialProps: { revision: 1, session: 'epoch' as string | undefined } });
    await act(async () => {}); rerender({ revision: 2, session: undefined }); await act(async () => { finish(bitmap); });
    expect(result.current).toBeNull(); expect(bitmap.close).toHaveBeenCalledTimes(1);
    rerender({ revision: 2, session: 'epoch' }); await act(async () => {});
    expect(createImageBitmap).toHaveBeenCalledTimes(1); expect(result.current).toBeNull(); unmount();
  });
  it('retries promptly while the last exact pair is still valid instead of needlessly falling back to WebRTC', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(frameResponse()).mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new Error('timeout'))))).mockResolvedValue(frameResponse('a', '2'));
    const { result, unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context())); await act(async () => {});
    await act(async () => { jest.advanceTimersByTime(67); });
    await act(async () => { jest.advanceTimersByTime(1500); }); expect(result.current?.frame.sequence).toBe('1');
    await act(async () => { jest.advanceTimersByTime(67); }); expect(result.current?.frame.sequence).toBe('2'); expect(fetch).toHaveBeenCalledTimes(3); unmount();
  });
  it('does not start decoding a body that finishes reading after its source was cancelled', async () => {
    const response = frameResponse(); const original = response.body.getReader(); const first = await original.read();
    let finish!: (value: unknown) => void;
    response.body.getReader = () => ({ read: jest.fn().mockResolvedValueOnce(first).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })), cancel: jest.fn(), releaseLock: jest.fn() });
    global.fetch = jest.fn().mockResolvedValue(response);
    const { rerender, unmount } = renderHook(({ enabled }) => useProcessedPreview('a', enabled, 'epoch', context()), { initialProps: { enabled: true } });
    await act(async () => {}); rerender({ enabled: false }); await act(async () => finish({ done: true }));
    expect(createImageBitmap).not.toHaveBeenCalled(); unmount();
  });
  it('closes skipped decoded states while preserving the presented and next-to-present bitmaps', async () => {
    const bitmaps: { width: number; height: number; close: jest.Mock }[] = [];
    global.createImageBitmap = jest.fn().mockImplementation(async () => { const bitmap = { width: 500, height: 500, close: jest.fn() }; bitmaps.push(bitmap); return bitmap; });
    let sequence = 0; global.fetch = jest.fn().mockImplementation(async () => frameResponse('a', String(++sequence)));
    const settle = async () => { for (let turn = 0; turn < 30; turn++) await Promise.resolve(); };
    const { result, unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context())); await act(async () => {});
    expect(result.current?.frame.sequence).toBe('1');
    await act(async () => {
      jest.advanceTimersByTime(67); await settle();
      jest.advanceTimersByTime(67); await settle();
      expect(bitmaps).toHaveLength(3);
      // React has not committed these batched updates. Keep old pixels and the final candidate alive.
      expect(bitmaps[0].close).not.toHaveBeenCalled();
      expect(bitmaps[1].close).toHaveBeenCalledTimes(1);
      expect(bitmaps[2].close).not.toHaveBeenCalled();
    });
    expect(result.current?.frame.sequence).toBe('3'); expect(bitmaps[0].close).toHaveBeenCalledTimes(1);
    expect(bitmaps[1].close).toHaveBeenCalledTimes(1); expect(bitmaps[2].close).not.toHaveBeenCalled();
    unmount(); expect(bitmaps.every(bitmap => bitmap.close.mock.calls.length === 1)).toBe(true);
  });
  it('closes decoded states that never commit when the hook unmounts during a batched update', async () => {
    const bitmaps: { width: number; height: number; close: jest.Mock }[] = [];
    global.createImageBitmap = jest.fn().mockImplementation(async () => { const bitmap = { width: 500, height: 500, close: jest.fn() }; bitmaps.push(bitmap); return bitmap; });
    let sequence = 0; global.fetch = jest.fn().mockImplementation(async () => frameResponse('a', String(++sequence)));
    const settle = async () => { for (let turn = 0; turn < 30; turn++) await Promise.resolve(); };
    const { unmount } = renderHook(() => useProcessedPreview('a', true, 'epoch', context())); await act(async () => {});
    await act(async () => { jest.advanceTimersByTime(67); await settle(); jest.advanceTimersByTime(67); await settle(); unmount(); });
    expect(bitmaps).toHaveLength(3); expect(bitmaps.every(bitmap => bitmap.close.mock.calls.length === 1)).toBe(true);
  });
  it('cleans StrictMode replay and closes a cancelled decode while the surviving generation presents', async () => {
    const oldBitmap = { width: 500, height: 500, close: jest.fn() } as unknown as ImageBitmap;
    const currentBitmap = { width: 500, height: 500, close: jest.fn() } as unknown as ImageBitmap;
    let finishOld!: (value: ImageBitmap) => void; const signals: AbortSignal[] = [];
    global.fetch = jest.fn().mockImplementation(async (url, init) => { signals.push(init.signal); return frameResponse(new URL(String(url), 'http://city.test').pathname.endsWith('/b') ? 'b' : 'a'); });
    global.createImageBitmap = jest.fn().mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; })).mockResolvedValue(currentBitmap);
    const wrapper = ({ children }: { children: React.ReactNode }) => React.createElement(React.StrictMode, null, children);
    const { result, rerender, unmount } = renderHook(({ id }) => useProcessedPreview(id, true, 'epoch', context(id)), { initialProps: { id: 'a' }, wrapper });
    await act(async () => {}); expect(signals).toHaveLength(2); expect(signals[0].aborted).toBe(true); expect(createImageBitmap).toHaveBeenCalledTimes(1);
    rerender({ id: 'b' }); await act(async () => {}); expect(result.current?.frame.sourceId).toBe('b'); expect(currentBitmap.close).not.toHaveBeenCalled();
    await act(async () => finishOld(oldBitmap)); expect(oldBitmap.close).toHaveBeenCalledTimes(1); expect(result.current?.frame.sourceId).toBe('b'); expect(currentBitmap.close).not.toHaveBeenCalled();
    unmount(); expect(currentBitmap.close).toHaveBeenCalledTimes(1); expect(oldBitmap.close).toHaveBeenCalledTimes(1);
  });
});
