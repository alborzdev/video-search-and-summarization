// SPDX-License-Identifier: MIT
import { waitForSourceIndex } from '../lib-src/indexReadiness';

describe('uploaded source index visibility', () => {
  const originalFetch = global.fetch;
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => { jest.useRealTimers(); global.fetch = originalFetch; });
  const receipt = (sensorId: string, semanticSegments: number) => ({ ok: true, json: async () => ({ source: { sensorId }, semanticSegments }) });

  it('waits for the exact source and never accepts a different source receipt', async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(receipt('older-upload', 99))
      .mockResolvedValueOnce(receipt('new-upload', 0)).mockResolvedValue(receipt('new-upload', 2));
    global.fetch = fetchMock;
    const waiting = waitForSourceIndex('new-upload', { signal: new AbortController().signal, pollIntervalMs: 10 });
    await jest.advanceTimersByTimeAsync(25);
    await expect(waiting).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/vision/source-intelligence?sensorId=new-upload&name=new-upload');
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ cache: 'no-store' }));
  });

  it('does not overlap polls while an index request is still pending', async () => {
    let finish!: (value: unknown) => void;
    const fetchMock = jest.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValue(receipt('new-upload', 2));
    global.fetch = fetchMock;
    const waiting = waitForSourceIndex('new-upload', { signal: new AbortController().signal, pollIntervalMs: 10 });
    await jest.advanceTimersByTimeAsync(100);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish(receipt('new-upload', 0));
    await jest.advanceTimersByTimeAsync(10);
    await expect(waiting).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('bounds even an unresponsive request and preserves an actionable saved-video outcome', async () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock;
    const waiting = waitForSourceIndex('new-upload', { signal: new AbortController().signal, timeoutMs: 30 });
    const outcome = waiting.catch(error => error);
    await jest.advanceTimersByTimeAsync(30);
    expect(await outcome).toEqual(expect.objectContaining({ message: expect.stringMatching(/Video saved.*Retry indexing.*preserved/) }));
    expect((global.fetch as jest.Mock).mock.calls[0][1].signal.aborted).toBe(true);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('cancels an in-flight poll and schedules no further request', async () => {
    const controller = new AbortController();
    global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock;
    const outcome = waitForSourceIndex('new-upload', { signal: controller.signal, pollIntervalMs: 10 }).catch(error => error);
    controller.abort();
    expect(await outcome).toEqual(expect.objectContaining({ name: 'AbortError' }));
    await jest.advanceTimersByTimeAsync(60_000);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('does not start a request after cancellation', async () => {
    const controller = new AbortController(); controller.abort();
    global.fetch = jest.fn();
    await expect(waitForSourceIndex('new-upload', { signal: controller.signal })).rejects.toHaveProperty('name', 'AbortError');
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
