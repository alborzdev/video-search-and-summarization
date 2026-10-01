// SPDX-License-Identifier: MIT
import { chooseLiveRecordingWindow, readLiveRecordingWindow } from '../../../server/vision/liveRecordingWindow';

const askedAt = '2026-10-01T12:00:30Z';
const timeline = (start: string, end: string) => ({
  startTime: `2026-10-01T12:00:${start}Z`, endTime: `2026-10-01T12:00:${end}Z`,
});

describe('live question recording window', () => {
  afterEach(() => jest.restoreAllMocks());

  it('uses an existing recording immediately and defaults to three seconds', () => {
    expect(chooseLiveRecordingWindow([timeline('00', '30')], askedAt)).toEqual({
      ready: true, remainingSeconds: 0,
      window: { startTime: '2026-10-01T12:00:22.000Z', endTime: '2026-10-01T12:00:25.000Z' },
    });
  });

  it('ends at the actual storage boundary when the recording tail is delayed', () => {
    expect(chooseLiveRecordingWindow([timeline('00', '22')], askedAt, 15).window).toEqual({
      startTime: '2026-10-01T12:00:07.000Z', endTime: '2026-10-01T12:00:22.000Z',
    });
  });

  it('inspects exactly two retained seconds without requiring fifteen seconds of recording', () => {
    expect(chooseLiveRecordingWindow([timeline('21', '30')], askedAt, 2)).toEqual({
      ready: true, remainingSeconds: 0,
      window: { startTime: '2026-10-01T12:00:23.000Z', endTime: '2026-10-01T12:00:25.000Z' },
    });
  });

  it('requires the whole chosen interval and never joins across a gap', () => {
    const older = { startTime: '2026-10-01T11:58:00Z', endTime: '2026-10-01T12:00:10Z' };
    expect(chooseLiveRecordingWindow([older, timeline('20', '30')], askedAt, 60)).toEqual({
      ready: false, remainingSeconds: 55, window: null,
    });
    expect(chooseLiveRecordingWindow([{ ...older, endTime: '2026-10-01T12:00:30Z' }], askedAt, 60).window).toEqual({
      startTime: '2026-10-01T11:59:25.000Z', endTime: '2026-10-01T12:00:25.000Z',
    });
  });

  it('waits only for the missing footage and respects the five-second storage edge', () => {
    expect(chooseLiveRecordingWindow([timeline('17', '30')], askedAt, 15)).toEqual({
      ready: false, remainingSeconds: 7, window: null,
    });
  });

  it('joins contiguous segments but never counts across a recording gap', () => {
    expect(chooseLiveRecordingWindow([timeline('05', '15'), timeline('15', '25')], askedAt, 15).ready).toBe(true);
    expect(chooseLiveRecordingWindow([timeline('05', '15'), timeline('18', '25')], askedAt, 15).ready).toBe(false);
  });

  it('waits for a restarted recording instead of substituting an older complete interval', () => {
    expect(chooseLiveRecordingWindow([timeline('00', '16'), timeline('20', '25')], askedAt, 15)).toEqual({
      ready: false, remainingSeconds: 10, window: null,
    });
  });

  it.each([null, {}, [], [{ startTime: 'invalid', endTime: askedAt }], [
    { startTime: '2026-10-01T11:58:00Z', endTime: '2026-10-01T11:59:00Z' },
  ]])('does not fabricate a live window from absent, invalid, or stale timelines: %p', (raw) => {
    expect(chooseLiveRecordingWindow(raw, askedAt)).toEqual(expect.objectContaining({ ready: false, window: null }));
  });

  it('reports unknown readiness without throwing when metadata lookup fails', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
    expect(await readLiveRecordingWindow('camera')).toEqual(expect.objectContaining({
      ready: false, window: null, remainingSeconds: null, error: expect.any(String),
    }));
  });
});
