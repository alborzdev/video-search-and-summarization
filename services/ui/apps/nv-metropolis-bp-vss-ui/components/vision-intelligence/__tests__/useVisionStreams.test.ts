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
