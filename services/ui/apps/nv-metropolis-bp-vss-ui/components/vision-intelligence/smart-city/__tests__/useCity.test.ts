// SPDX-License-Identifier: MIT
import { act, renderHook, waitFor } from '@testing-library/react';
import { useCity } from '../useCity';
import { previewContext } from '../processedPreview';
import { displaySnapshot } from '../alignedSnapshot';
import type { CityMode, CitySnapshot } from '../types';
class CityEvents {
  static current: CityEvents;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen = null; onerror = null;
  constructor() { CityEvents.current = this; }
  addEventListener() {} close() {}
}
it('closes background subscriptions, ignores queued old events and refreshes on return', async () => {
  const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  const close = jest.spyOn(CityEvents.prototype, 'close');
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const snapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: '1', sources: [], tracks: [], events: [], metrics: [], zones: [], rules: [] };
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await waitFor(() => expect(result.current.loading).toBe(false));
    const old = CityEvents.current; const oldUpdate = old.onmessage;
    await act(async () => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')); });
    expect(close).toHaveBeenCalledTimes(1); expect(result.current.connected).toBe(false);
    const calls = (fetch as jest.Mock).mock.calls.length;
    act(() => oldUpdate?.({ data: JSON.stringify({ ...snapshot, sequence: 'obsolete' }) }));
    expect(result.current.snapshot?.sequence).toBe('1'); expect(fetch).toHaveBeenCalledTimes(calls);
    await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')); });
    expect(CityEvents.current).not.toBe(old); expect(fetch).toHaveBeenCalledTimes(calls + 3);
    expect(result.current.snapshot?.sequence).toBe('1');
  } finally { unmount(); visibility.mockRestore(); close.mockRestore(); }
});
it('clears recorded clock requests when switching to live and accepts new live updates', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let mode: CityMode = 'recorded-inference';
  const snapshot = (): CitySnapshot => ({ siteId: 'city', mode, timestamp: '2026-10-22T00:00:00Z', sequence: '1', sources: [], tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', mode, sources: [], map: { bounds: [0, 0, 1, 1], roads: [], buildings: [] } } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() }));
  const { result, unmount } = renderHook(() => useCity());
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => { result.current.atMediaTime(2, true); result.current.atSourceTime('old-camera', 1700000000000); });
  await waitFor(() => expect(result.current.sourceSnapshots['old-camera']).toBeDefined());
  mode = 'live'; await act(async () => { await result.current.refresh(); });
  expect(result.current.sourceSnapshots).toEqual({});
  const calls = (fetch as jest.Mock).mock.calls.length;
  act(() => result.current.atMediaTime(3, true)); expect(fetch).toHaveBeenCalledTimes(calls);
  act(() => CityEvents.current.onmessage?.({ data: JSON.stringify({ ...snapshot(), sequence: 'new-live-frame' }) }));
  expect(result.current.snapshot?.sequence).toBe('new-live-frame'); unmount();
});

it('debounces source/mode/revision changes from SSE and does not refetch per video frame', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let mode: CityMode = 'recorded-inference'; let sourceId = 'recorded'; let revision = 1;
  const site = () => ({ id: 'city', revision, mode, sources: [{ id: sourceId, name: sourceId, width: 100, height: 100 }], map: { bounds: [0, 0, 1, 1], roads: [], buildings: [] } });
  const snapshot = (): CitySnapshot => ({ siteId: 'city', siteRevision: revision, mode, timestamp: '2026-10-22T00:00:00Z', sequence: '1', sources: site().sources, tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? site() : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => { await Promise.resolve(); }); expect(result.current.site?.mode).toBe('recorded-inference');
    mode = 'live'; sourceId = 'rtsp'; revision = 2;
    act(() => { for (let i = 0; i < 40; i++) CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }); });
    expect(result.current.snapshot).toBeNull(); expect((fetch as jest.Mock).mock.calls.filter(([url]) => String(url).endsWith('/site'))).toHaveLength(1);
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(result.current.site?.sources[0].id).toBe('rtsp'); expect(result.current.site?.mode).toBe('live');
    act(() => { for (let i = 0; i < 40; i++) CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }); });
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect((fetch as jest.Mock).mock.calls.filter(([url]) => String(url).endsWith('/site'))).toHaveLength(2);
    revision = 3; act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }));
    await act(async () => { jest.advanceTimersByTime(1000); }); expect(result.current.site?.revision).toBe(3);
  } finally { unmount(); jest.useRealTimers(); }
});

it('aborts an obsolete static fetch and rejects its late response after a newer SSE configuration', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let revision = 1; let defer = false; const pending: { finish: (value: unknown) => void; value: unknown; signal: AbortSignal }[] = [];
  const site = () => ({ id: 'city', revision, mode: 'live', sources: [], map: { bounds: [0, 0, 1, 1], roads: [], buildings: [] } });
  const snapshot = () => ({ siteId: 'city', siteRevision: revision, mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: String(revision), sources: [], tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn((input, init) => {
    const value = String(input).endsWith('/site') ? site() : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot();
    const response = { ok: true, json: async () => value };
    return defer ? new Promise(resolve => pending.push({ finish: resolve, value: response, signal: init!.signal as AbortSignal })) : Promise.resolve(response);
  });
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => { await Promise.resolve(); });
    revision = 2; defer = true;
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }));
    await act(async () => { jest.advanceTimersByTime(1000); }); expect(pending).toHaveLength(3);
    revision = 3; defer = false;
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) })); expect(pending.every(item => item.signal.aborted)).toBe(true);
    await act(async () => { jest.advanceTimersByTime(1000); }); expect(result.current.site?.revision).toBe(3);
    await act(async () => { pending.forEach(item => item.finish(item.value)); }); expect(result.current.site?.revision).toBe(3);
  } finally { unmount(); jest.useRealTimers(); }
});

it('uses a confirmed exact preview snapshot directly without a nearest-time request and clears stale map positions', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch' };
  const snapshot: CitySnapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: '1', sources: [source], tracks: [], events: [], metrics: [], zones: [], rules: [] };
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [source] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot }));
  const { result, unmount } = renderHook(() => useCity()); await waitFor(() => expect(result.current.loading).toBe(false));
  const calls = (fetch as jest.Mock).mock.calls.length;
  const exact: any = { sourceId: 'a', sessionId: 'epoch', sequence: '3', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: { ...snapshot, sequence: '3', tracks: [{ id: 'exact' }] } };
  const key = previewContext(result.current.site!, source, result.current.previewGeneration).configurationKey;
  act(() => result.current.presentProcessedFrame('a', exact, key));
  expect(fetch).toHaveBeenCalledTimes(calls); expect(result.current.sourceSnapshots.a.tracks[0].id).toBe('exact'); expect(result.current.sourceSnapshots.a.presentedPreview?.sourceTimeNs).toBe(exact.sourceTimeNs);
  act(() => result.current.presentProcessedFrame('a', null, key));
  expect(result.current.sourceSnapshots.a.tracks).toEqual([]); expect(result.current.sourceSnapshots.a.processedPreviewUnavailable).toBe(true); unmount();
});

it('rejects obsolete configuration receipts at map acceptance, including when session metadata disappears', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let revision = 1;
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch', calibrationRevision: 'calibration-1' };
  const site = () => ({ id: 'city', revision, mode: 'live' as const, sources: [{ ...source, calibrationRevision: `calibration-${revision}` }] });
  const snapshot = () => ({ siteId: 'city', siteRevision: revision, mode: 'live' as const, timestamp: '2026-10-22T00:00:00Z', sequence: '1', sources: site().sources, tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? site() : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() }));
  const { result, unmount } = renderHook(() => useCity()); await waitFor(() => expect(result.current.loading).toBe(false));
  const oldFrame: any = { sourceId: 'a', sessionId: 'epoch', sequence: '1', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: snapshot() };
  const oldKey = previewContext(result.current.site!, source, result.current.previewGeneration).configurationKey;
  revision = 2; await act(async () => { await result.current.refresh(); });
  const newKey = previewContext(result.current.site!, result.current.site!.sources[0], result.current.previewGeneration).configurationKey;
  act(() => { result.current.presentProcessedFrame('a', oldFrame, oldKey); result.current.presentProcessedFrame('a', oldFrame, newKey); });
  expect(result.current.sourceSnapshots).toEqual({});
  const currentFrame = { ...oldFrame, snapshot: snapshot() };
  act(() => CityEvents.current.onmessage?.({ data: JSON.stringify({ ...snapshot(), sources: [{ ...site().sources[0], sessionId: undefined }] }) }));
  act(() => result.current.presentProcessedFrame('a', currentFrame, newKey)); expect(result.current.sourceSnapshots).toEqual({});
  act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }));
  act(() => result.current.presentProcessedFrame('a', currentFrame, newKey)); expect(result.current.sourceSnapshots.a.presentedPreview?.configurationKey).toBe(newKey); unmount();
});

it('coalesces slow replay history requests without cancelling every decoded-frame update', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const snapshot = (sequence = 'initial'): CitySnapshot => ({ siteId: 'city', siteRevision: 1, mode: 'recorded-inference', timestamp: '2026-10-22T00:00:00Z', sequence, sources: [], tracks: [], events: [], metrics: [], zones: [], rules: [] });
  const pending: { url: string; signal: AbortSignal; finish: (value: unknown) => void }[] = [];
  global.fetch = jest.fn((input, init) => {
    const url = String(input);
    if (url.includes('mediaTimeSeconds=')) return new Promise(resolve => pending.push({ url, signal: init!.signal as AbortSignal, finish: resolve }));
    return Promise.resolve({ ok: true, json: async () => url.endsWith('/site') ? { id: 'city', revision: 1, mode: 'recorded-inference', sources: [] } : url.endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() });
  });
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => {}); await act(async () => result.current.atMediaTime(1, true));
    await act(async () => { jest.advanceTimersByTime(100); result.current.atMediaTime(2); });
    await act(async () => { jest.advanceTimersByTime(100); result.current.atMediaTime(3); });
    expect(pending).toHaveLength(1); expect(pending[0].signal.aborted).toBe(false);
    await act(async () => pending[0].finish({ ok: true, json: async () => snapshot('first-completed') }));
    expect(result.current.snapshot?.sequence).toBe('first-completed'); expect(pending).toHaveLength(2); expect(pending[1].url).toContain('mediaTimeSeconds=3.0000');
    await act(async () => result.current.atMediaTime(4, true)); expect(pending[1].signal.aborted).toBe(true); expect(pending).toHaveLength(3);
    await act(async () => { pending[1].finish({ ok: true, json: async () => snapshot('obsolete') }); pending[2].finish({ ok: true, json: async () => snapshot('current-seek') }); });
    expect(result.current.snapshot?.sequence).toBe('current-seek');
  } finally { unmount(); jest.useRealTimers(); }
});

it('automatically retries a timed-out static configuration without waiting for a manual refresh', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let stalled = true;
  global.fetch = jest.fn((input, init) => {
    if (stalled) return new Promise((_resolve, reject) => init!.signal!.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
    const url = String(input); return Promise.resolve({ ok: true, json: async () => url.endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [] } : url.endsWith('/rules') ? { rules: [], revision: 0 } : { siteId: 'city', siteRevision: 1, mode: 'live', sequence: 'recovered', sources: [], tracks: [], rules: [], zones: [], events: [], metrics: [] } });
  });
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => { jest.advanceTimersByTime(10_000); }); expect(result.current.error).toContain('timed out'); stalled = false;
    await act(async () => { jest.advanceTimersByTime(2000); }); expect(result.current.site?.id).toBe('city'); expect(result.current.snapshot?.sequence).toBe('recovered');
  } finally { unmount(); jest.useRealTimers(); }
});

it('aborts sibling configuration reads after one read fails before scheduling a retry', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const signals: AbortSignal[] = []; let failing = true;
  global.fetch = jest.fn((input, init) => {
    const url = String(input); signals.push(init!.signal as AbortSignal);
    if (failing) return url.endsWith('/site') ? Promise.reject(new Error('Site read failed')) : new Promise(() => {});
    return Promise.resolve({ ok: true, json: async () => url.endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [] } : url.endsWith('/rules') ? { rules: [], revision: 0 } : { siteId: 'city', siteRevision: 1, mode: 'live', sources: [], tracks: [], rules: [], zones: [], events: [], metrics: [] } });
  });
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => {}); expect(signals).toHaveLength(3); expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(result.current.error).toBe('Site read failed'); failing = false;
    await act(async () => { jest.advanceTimersByTime(2000); }); expect(result.current.site?.id).toBe('city');
  } finally { unmount(); jest.useRealTimers(); }
});

it('cancels a rule save when configuration refreshes and ignores its late response', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let revision = 1; let finish: (value: unknown) => void = () => {}; let saveSignal: AbortSignal | undefined;
  global.fetch = jest.fn((input, init) => {
    if (init?.method === 'PUT') { saveSignal = init.signal as AbortSignal; return new Promise(resolve => { finish = resolve; }); }
    const url = String(input); return Promise.resolve({ ok: true, json: async () => url.endsWith('/site') ? { id: 'city', revision, mode: 'live', sources: [] } : url.endsWith('/rules') ? { rules: [], revision } : { siteId: 'city', siteRevision: revision, mode: 'live', sources: [], tracks: [], rules: [], zones: [], events: [], metrics: [] } });
  });
  const { result, unmount } = renderHook(() => useCity()); await waitFor(() => expect(result.current.loading).toBe(false));
  let saving: Promise<unknown> = Promise.resolve();
  await act(async () => { saving = result.current.saveRules([]).catch(cause => cause); }); expect(result.current.saving).toBe(true);
  revision = 2; await act(async () => { await result.current.refresh(); }); expect(saveSignal?.aborted).toBe(true); expect(result.current.rules.revision).toBe(2); expect(result.current.saving).toBe(false);
  await act(async () => { finish({ ok: true, json: async () => ({ rules: [], revision: 99 }) }); await saving; });
  expect(await saving).toEqual(expect.objectContaining({ name: 'AbortError' })); expect(result.current.rules.revision).toBe(2); expect(result.current.error).toBeNull(); unmount();
});

it('rejects old analytics epochs at exact-frame acceptance without changing the camera session', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const scope = { kind: 'scenario', epoch: 'new', suppressed: false };
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'same-session', analyticsScope: scope, trackingEpoch: 'tracker' };
  const snapshot: CitySnapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-26T15:00:00Z', sequence: '1', analyticsScope: scope, sources: [source], tracks: [], events: [], metrics: [], zones: [], rules: [] };
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [source] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot }));
  const { result, unmount } = renderHook(() => useCity()); await waitFor(() => expect(result.current.loading).toBe(false));
  const oldScope = { ...scope, epoch: 'old' };
  const frame: any = { sourceId: 'a', sessionId: 'same-session', sequence: '3', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: { ...snapshot, analyticsScope: oldScope, sources: [{ ...source, analyticsScope: oldScope }] } };
  const key = previewContext(result.current.site!, source, result.current.previewGeneration).configurationKey;
  act(() => result.current.presentProcessedFrame('a', frame, key)); expect(result.current.sourceSnapshots).toEqual({});
  act(() => result.current.presentProcessedFrame('a', { ...frame, snapshot }, key)); expect(result.current.sourceSnapshots.a.analyticsScope?.epoch).toBe('new');
  unmount();
});

it('keeps paired previews and accepts newer SSE observations during a same-configuration refresh', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch' };
  const site = { id: 'city', revision: 1, mode: 'live', sources: [source] };
  const initial: CitySnapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-29T00:00:00Z', sequence: '1', sources: [source], tracks: [], events: [], metrics: [], zones: [], rules: [], rulesRevision: 1 };
  const pending: (() => void)[] = []; let defer = false;
  global.fetch = jest.fn(input => {
    const value = String(input).endsWith('/site') ? site : String(input).endsWith('/rules') ? { rules: [], revision: 1 } : initial;
    const response = { ok: true, json: async () => value };
    return defer ? new Promise(resolve => pending.push(() => resolve(response))) : Promise.resolve(response);
  });
  const { result, unmount } = renderHook(() => useCity());
  try {
    await waitFor(() => expect(result.current.loading).toBe(false));
    const generation = result.current.previewGeneration;
    const key = previewContext(result.current.site!, source, generation).configurationKey;
    const frame: any = { sourceId: 'a', sessionId: 'epoch', sequence: '1', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: initial };
    act(() => result.current.presentProcessedFrame('a', frame, key));
    const presented = result.current.sourceSnapshots.a;
    defer = true; let refreshing: Promise<void>;
    act(() => { refreshing = result.current.refresh(); });
    expect(result.current.loading).toBe(false); expect(result.current.previewGeneration).toBe(generation);
    expect(result.current.sourceSnapshots.a).toBe(presented);
    const newer = { ...initial, sequence: '2', rulesRevision: 2 };
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(newer) }));
    expect(result.current.snapshot?.sequence).toBe('2');
    act(() => result.current.presentProcessedFrame('a', { ...frame, sequence: '2', snapshot: newer }, key));
    expect(result.current.sourceSnapshots.a.presentedPreview?.sequence).toBe('2');
    await act(async () => { pending.forEach(finish => finish()); await refreshing; });
    expect(result.current.loading).toBe(false); expect(result.current.previewGeneration).toBe(generation);
    expect(result.current.snapshot?.sequence).toBe('2'); expect(result.current.rules.revision).toBe(2);
    expect(result.current.sourceSnapshots.a.presentedPreview?.sequence).toBe('2');
  } finally { unmount(); }
});

it('keeps valid live frames through a failed background refresh and its automatic retry', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch' };
  const snapshot: CitySnapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-29T00:00:00Z', sequence: '1', sources: [source], tracks: [], events: [], metrics: [], zones: [], rules: [] };
  let failing = false;
  global.fetch = jest.fn(input => failing ? Promise.reject(new Error('Refresh unavailable')) : Promise.resolve({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [source] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => {});
    const generation = result.current.previewGeneration;
    const key = previewContext(result.current.site!, source, generation).configurationKey;
    const frame: any = { sourceId: 'a', sessionId: 'epoch', sequence: '1', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot };
    act(() => result.current.presentProcessedFrame('a', frame, key)); const presented = result.current.sourceSnapshots.a;
    failing = true; await act(async () => { await result.current.refresh(); });
    expect(result.current.error).toBe('Refresh unavailable'); expect(result.current.loading).toBe(false);
    expect(result.current.previewGeneration).toBe(generation); expect(result.current.sourceSnapshots.a).toBe(presented);
    failing = false; await act(async () => { jest.advanceTimersByTime(2000); });
    expect(result.current.error).toBeNull(); expect(result.current.loading).toBe(false);
    expect(result.current.previewGeneration).toBe(generation); expect(result.current.sourceSnapshots.a).toBe(presented);
  } finally { unmount(); jest.useRealTimers(); }
});

it('invalidates an unversioned calibration change immediately and rejects old presentation receipts', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let calibration = 'first';
  const source = () => ({ id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch', calibrationRevision: calibration });
  const snapshot = (): CitySnapshot => ({ siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-29T00:00:00Z', sequence: '1', sources: [source()], tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [source()] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => {}); const generation = result.current.previewGeneration;
    const oldKey = previewContext(result.current.site!, source(), generation).configurationKey;
    const oldFrame: any = { sourceId: 'a', sessionId: 'epoch', sequence: '1', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: snapshot() };
    act(() => result.current.presentProcessedFrame('a', oldFrame, oldKey));
    calibration = 'second'; act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }));
    expect(result.current.loading).toBe(true); expect(result.current.sourceSnapshots).toEqual({});
    expect(result.current.snapshot).toBeNull(); expect(result.current.previewGeneration).toBeGreaterThan(generation);
    await act(async () => { jest.advanceTimersByTime(1000); });
    const newKey = previewContext(result.current.site!, source(), result.current.previewGeneration).configurationKey;
    act(() => { result.current.presentProcessedFrame('a', oldFrame, oldKey); result.current.presentProcessedFrame('a', oldFrame, newKey); });
    expect(result.current.sourceSnapshots).toEqual({});
    act(() => result.current.presentProcessedFrame('a', { ...oldFrame, snapshot: snapshot() }, newKey));
    expect(result.current.sourceSnapshots.a.presentedPreview?.configurationKey).toBe(newKey);
  } finally { unmount(); jest.useRealTimers(); }
});

it('suppresses obsolete map observations without falling back to unpaired detections on a session or scope change', async () => {
  Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  const scope = { kind: 'scenario', epoch: 'first' };
  const source = { id: 'a', name: 'A', width: 100, height: 100, sessionId: 'epoch', analyticsScope: scope, browserClockVerified: false };
  const rawTrack: any = { id: 'unpaired-latest', sourceId: 'a', positionM: [12, 34] };
  const initial: CitySnapshot = { siteId: 'city', siteRevision: 1, mode: 'live', timestamp: '2026-10-29T00:00:00Z', sequence: '1', analyticsScope: scope, sources: [source], tracks: [rawTrack], events: [], metrics: [], zones: [], rules: [] };
  global.fetch = jest.fn(async input => ({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision: 1, mode: 'live', sources: [source] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : initial }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await waitFor(() => expect(result.current.loading).toBe(false)); const generation = result.current.previewGeneration;
    const key = previewContext(result.current.site!, source, generation).configurationKey;
    const frame: any = { sourceId: 'a', sessionId: 'epoch', sequence: '1', sourceTimeNs: '1700000000000000000', image: { width: 100, height: 100 }, snapshot: initial };
    act(() => result.current.presentProcessedFrame('a', frame, key));
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify({ ...initial, sources: [{ ...source, sessionId: undefined }] }) }));
    expect(result.current.sourceSnapshots.a).toEqual(expect.objectContaining({ processedPreviewUnavailable: true, tracks: [], events: [], metrics: [] }));
    expect(result.current.sourceSnapshots.a.presentedPreview).toBeUndefined();
    expect(displaySnapshot(result.current.site, result.current.snapshot, result.current.sourceSnapshots)?.tracks).toEqual([]);
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(initial) }));
    act(() => result.current.presentProcessedFrame('a', frame, key));
    const nextScope = { ...scope, epoch: 'second' };
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify({ ...initial, analyticsScope: nextScope, sources: [{ ...source, analyticsScope: nextScope }] }) }));
    expect(result.current.sourceSnapshots.a.processedPreviewUnavailable).toBe(true);
    expect(displaySnapshot(result.current.site, result.current.snapshot, result.current.sourceSnapshots)?.tracks).toEqual([]);
    expect(result.current.previewGeneration).toBe(generation);
    const fresh = { ...initial, analyticsScope: nextScope, sources: [{ ...source, analyticsScope: nextScope }] };
    act(() => result.current.presentProcessedFrame('a', { ...frame, snapshot: fresh }, key));
    expect(result.current.sourceSnapshots.a.processedPreviewUnavailable).toBeUndefined();
    expect(result.current.sourceSnapshots.a.presentedPreview).toBeDefined();
  } finally { unmount(); }
});

it('keeps an invalidated configuration covered while replacement reads fail and retry', async () => {
  jest.useFakeTimers(); Object.defineProperty(global, 'EventSource', { configurable: true, value: CityEvents });
  let revision = 1; let failing = false;
  const snapshot = (): CitySnapshot => ({ siteId: 'city', siteRevision: revision, mode: 'live', timestamp: '2026-10-29T00:00:00Z', sequence: '1', sources: [], tracks: [], events: [], metrics: [], zones: [], rules: [] });
  global.fetch = jest.fn(input => failing ? Promise.reject(new Error('Replacement not ready')) : Promise.resolve({ ok: true, json: async () => String(input).endsWith('/site') ? { id: 'city', revision, mode: 'live', sources: [] } : String(input).endsWith('/rules') ? { rules: [], revision: 0 } : snapshot() }));
  const { result, unmount } = renderHook(() => useCity());
  try {
    await act(async () => {}); expect(result.current.loading).toBe(false);
    revision = 2; failing = true;
    act(() => CityEvents.current.onmessage?.({ data: JSON.stringify(snapshot()) }));
    const invalidatedGeneration = result.current.previewGeneration;
    expect(result.current.loading).toBe(true);
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(result.current.error).toBe('Replacement not ready'); expect(result.current.loading).toBe(true);
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(result.current.loading).toBe(true); expect(result.current.previewGeneration).toBe(invalidatedGeneration);
    failing = false; await act(async () => { jest.advanceTimersByTime(4000); });
    expect(result.current.loading).toBe(false); expect(result.current.site?.revision).toBe(2);
  } finally { unmount(); jest.useRealTimers(); }
});
