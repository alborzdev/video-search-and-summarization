import { act, renderHook } from "@testing-library/react";
import { useVisionStreams } from "../useVisionStreams";

it("does not load or retry the catalog in an inactive workspace", async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 502 });
  const { rerender, unmount } = renderHook(({ active }) => useVisionStreams("/vst/api", active), { initialProps: { active: false } });
  try {
    expect(global.fetch).not.toHaveBeenCalled();
    await act(async () => { rerender({ active: true }); });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    rerender({ active: false });
    await act(async () => { jest.advanceTimersByTime(30_000); });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  } finally { unmount(); jest.useRealTimers(); }
});

it("recovers the source catalog after a video service outage without remounting", async () => {
  jest.useFakeTimers();
  const fetchMock = jest.fn()
    .mockResolvedValueOnce({ ok: false, status: 502 })
    .mockResolvedValue({ ok: true, json: async () => [] });
  global.fetch = fetchMock;
  const { result, unmount } = renderHook(() => useVisionStreams("/vst/api"));
  try {
    await act(async () => { await Promise.resolve(); });
    expect(result.current.error).toContain("502");
    await act(async () => { jest.advanceTimersByTime(15000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);
  } finally { unmount(); jest.useRealTimers(); }
});

it("tracks disconnection and recovery independently from the catalog and stops polling when hidden", async () => {
  jest.useFakeTimers();
  let state = 'offline';
  global.fetch = jest.fn(async (input) => ({ ok: true, json: async () => String(input).endsWith('/sensor/status')
    ? { camera: { state } }
    : [{ camera: [{ streamId: 'camera', name: 'Camera', type: 'Rtsp', url: 'rtsp://camera', metadata: {}, isMain: true }] }] }));
  const { result, rerender, unmount } = renderHook(({ active }) => useVisionStreams('/vst/api', active), { initialProps: { active: true } });
  try {
    await act(async () => { await Promise.resolve(); });
    expect(result.current.streams[0].connectionState).toBe('offline');
    state = 'online';
    await act(async () => { jest.advanceTimersByTime(15000); });
    expect(result.current.streams[0].connectionState).toBe('online');
    const calls = (global.fetch as jest.Mock).mock.calls.length;
    rerender({ active: false });
    await act(async () => { jest.advanceTimersByTime(30000); });
    expect(global.fetch).toHaveBeenCalledTimes(calls);
  } finally { unmount(); jest.useRealTimers(); }
});

it("discovers a camera registered after a successful empty startup catalog", async () => {
  jest.useFakeTimers();
  let registered = false;
  global.fetch = jest.fn(async (input) => ({ ok: true, json: async () => String(input).endsWith('/sensor/status')
    ? { camera: { state: 'online' } }
    : registered ? [{ camera: [{ streamId: 'camera', name: 'Camera', type: 'Rtsp', url: 'rtsp://camera', metadata: {}, isMain: true }] }] : [] }));
  const { result, unmount } = renderHook(() => useVisionStreams('/vst/api'));
  try {
    await act(async () => { await Promise.resolve(); });
    expect(result.current.streams).toEqual([]);
    expect(result.current.error).toBeNull();
    registered = true;
    await act(async () => { jest.advanceTimersByTime(15000); });
    expect(result.current.streams[0].connectionState).toBe('online');
  } finally { unmount(); jest.useRealTimers(); }
});

it("ignores an old catalog when the endpoint changes during a request", async () => {
  let finishOld!: (response: unknown) => void;
  global.fetch = jest.fn((input) => String(input).startsWith('/old')
    ? new Promise((resolve) => { finishOld = resolve; })
    : Promise.resolve({ ok: true, json: async () => [] }));
  const { result, rerender, unmount } = renderHook(({ url }) => useVisionStreams(url), { initialProps: { url: '/old' } });
  try {
    await act(async () => { rerender({ url: '/new' }); });
    await act(async () => { finishOld({ ok: true, json: async () => [{ camera: [{ streamId: 'camera', name: 'Old camera', type: 'Rtsp', url: 'rtsp://old', metadata: {}, isMain: true }] }] }); });
    expect(result.current.streams).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  } finally { unmount(); }
});

it('retains sources through an empty background startup snapshot while respecting catalog replacements and explicit refresh', async () => {
  jest.useFakeTimers();
  let catalog = [{ camera: [{ streamId: 'camera', name: 'Camera', type: 'Rtsp', url: 'rtsp://camera', metadata: {}, isMain: true }] }];
  global.fetch = jest.fn(async (input) => ({ ok: true, json: async () => String(input).endsWith('/sensor/status') ? { camera: { state: 'online' } } : catalog }));
  const { result, unmount } = renderHook(() => useVisionStreams('/vst/api'));
  try {
    await act(async () => { await Promise.resolve(); });
    expect(result.current.streams[0].streamId).toBe('camera');
    expect(result.current.streams[0].connectionState).toBe('online');
    catalog = [];
    await act(async () => { jest.advanceTimersByTime(15000); });
    expect(result.current.streams[0].streamId).toBe('camera');
    expect(result.current.streams[0].connectionState).toBe('unknown');
    expect(result.current.error).toContain('restoring its source catalog');
    catalog = [{ camera: [{ streamId: 'replacement', name: 'Camera', type: 'Rtsp', url: 'rtsp://camera', metadata: {}, isMain: true }] }];
    await act(async () => { jest.advanceTimersByTime(15000); });
    expect(result.current.streams[0].streamId).toBe('replacement');
    expect(result.current.streams[0].connectionState).toBe('online');
    expect(result.current.error).toBeNull();
    catalog = [];
    await act(async () => { await result.current.refresh(); });
    expect(result.current.streams).toEqual([]);
  } finally { unmount(); jest.useRealTimers(); }
});
