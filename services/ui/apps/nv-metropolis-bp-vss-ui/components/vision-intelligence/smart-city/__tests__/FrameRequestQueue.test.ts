// SPDX-License-Identifier: MIT
import { FrameRequestQueue } from '../FrameRequestQueue';
const flush = async () => { for (let turn = 0; turn < 6; turn++) await Promise.resolve(); };
describe('coalesced frame history requests', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  it('finishes slow work without abort starvation and retains only the newest pending frame', async () => {
    const pending: { value: number; signal: AbortSignal; finish: () => void }[] = [];
    const queue = new FrameRequestQueue<number>((value, signal) => new Promise(resolve => pending.push({ value, signal, finish: resolve })));
    queue.enqueue(1); await flush(); jest.advanceTimersByTime(150); queue.enqueue(2); queue.enqueue(3); await flush();
    expect(pending.map(item => item.value)).toEqual([1]); expect(pending[0].signal.aborted).toBe(false);
    pending[0].finish(); await flush(); expect(pending.map(item => item.value)).toEqual([1, 3]); queue.clear(); expect(pending[1].signal.aborted).toBe(true);
  });
  it('lets an explicit seek cancel old work without its late completion releasing the new request', async () => {
    const pending: { value: number; signal: AbortSignal; finish: () => void }[] = [];
    const queue = new FrameRequestQueue<number>((value, signal) => new Promise(resolve => pending.push({ value, signal, finish: resolve })));
    queue.enqueue(1); await flush(); queue.enqueue(2, true); await flush(); expect(pending[0].signal.aborted).toBe(true);
    queue.enqueue(3); pending[0].finish(); await flush(); expect(pending.map(item => item.value)).toEqual([1, 2]);
    jest.advanceTimersByTime(100); pending[1].finish(); await flush(); expect(pending.map(item => item.value)).toEqual([1, 2, 3]); queue.clear();
  });
  it('cancels pending timer work on a site switch or unmount', async () => {
    const work = jest.fn().mockResolvedValue(undefined); const queue = new FrameRequestQueue<number>(work);
    queue.enqueue(1); await flush(); queue.enqueue(2); queue.clear(); jest.advanceTimersByTime(10_000); await flush(); expect(work).toHaveBeenCalledTimes(1);
  });
  it('bounds hung work and proceeds to the latest frame without a late completion changing the active request', async () => {
    const pending: { value: number; signal: AbortSignal; finish: () => void }[] = []; const timeout = jest.fn();
    const queue = new FrameRequestQueue<number>((value, signal) => new Promise(resolve => pending.push({ value, signal, finish: resolve })), timeout);
    queue.enqueue(1); await flush(); queue.enqueue(2); jest.advanceTimersByTime(5000); await flush();
    expect(pending.map(item => item.value)).toEqual([1, 2]); expect(pending[0].signal.aborted).toBe(true); expect(timeout).toHaveBeenCalledTimes(1);
    pending[0].finish(); await flush(); expect(pending[1].signal.aborted).toBe(false); queue.clear();
  });
  it('does not serialize independent camera queues behind each other', async () => {
    const work = jest.fn().mockImplementation(() => new Promise(() => {})); const a = new FrameRequestQueue(work); const b = new FrameRequestQueue(work);
    a.enqueue('a'); b.enqueue('b'); await flush(); expect(work).toHaveBeenCalledTimes(2); a.clear(); b.clear();
  });
});
