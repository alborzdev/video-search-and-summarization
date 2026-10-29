// SPDX-License-Identifier: MIT
import { act, renderHook } from '@testing-library/react';
import { usePreviewHealth } from '../usePreviewHealth';
describe('preview delivery diagnostics', () => {
  const originalFetch = global.fetch;
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => { jest.useRealTimers(); global.fetch = originalFetch; });
  it('retains reported counters and clears them when a later health request fails', async () => {
    const nativeDelivery = { status: 'fresh', enabled: true, failed: false, fpsLimitPerSource: 30, sources: [{ sourceId: 'a', observedPublishedFps: 9.8, rateDropped: 12, networkQueueDropped: 2 }] };
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ processedPreview: { nativeDelivery } }) }).mockRejectedValue(new Error('offline'));
    const { result, unmount } = renderHook(() => usePreviewHealth(true)); await act(async () => {}); expect(result.current).toEqual(nativeDelivery);
    await act(async () => { jest.advanceTimersByTime(2000); }); expect(result.current).toBeNull(); unmount();
  });
  it('does not poll when disabled and aborts the one pending read on unmount', async () => {
    let signal!: AbortSignal; global.fetch = jest.fn().mockImplementation((_url, init) => { signal = init.signal; return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('abort')))); });
    const { rerender, unmount } = renderHook(({ enabled }) => usePreviewHealth(enabled), { initialProps: { enabled: false } });
    expect(fetch).not.toHaveBeenCalled(); rerender({ enabled: true }); expect(fetch).toHaveBeenCalledTimes(1); unmount(); expect(signal.aborted).toBe(true);
    await act(async () => { jest.advanceTimersByTime(10_000); }); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('stops hidden-tab polling and requests fresh health when the tab returns', async () => {
    const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const nativeDelivery = { status: 'fresh', sources: [{ sourceId: 'a', observedPublishedFps: 8 }] };
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ processedPreview: { nativeDelivery } }) });
    const { result, unmount } = renderHook(() => usePreviewHealth(true));
    try {
      await act(async () => {}); expect(result.current).toEqual(nativeDelivery);
      act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')); });
      expect(result.current).toBeNull();
      await act(async () => { jest.advanceTimersByTime(10_000); }); expect(fetch).toHaveBeenCalledTimes(1);
      await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')); });
      expect(fetch).toHaveBeenCalledTimes(2); expect(result.current).toEqual(nativeDelivery);
    } finally { unmount(); visibility.mockRestore(); }
  });
});
