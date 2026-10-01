// SPDX-License-Identifier: MIT

import type { VisionStream } from "../types";
import { useLiveCapture } from "../useLiveCapture";
import { act, renderHook, waitFor } from "@testing-library/react";

const live: VisionStream = {
  name: "Camera 1",
  sensorId: "sensor-1",
  streamId: "stream-1",
  connectionState: "online",
  type: "rtsp",
  url: "rtsp://camera.test/live",
  vodUrl: "",
  metadata: {},
  isMain: true,
};
const response = (recordingStatus: string, ok = true, error?: string) =>
  ({ ok, json: async () => ({ recordingStatus, error, questionReady: recordingStatus === "on", remainingSeconds: recordingStatus === "on" ? 0 : null }) } as Response);

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it("does not read or mutate replay capture and gates replay questions on readiness and busy", () => {
  const fetch = jest.fn();
  global.fetch = fetch;
  const replay = { ...live, type: "file", url: "/recorded.mp4" };
  const { result, rerender } = renderHook(
    ({ busy, ready }) =>
      useLiveCapture(replay, { busy, visualAnalystAvailable: ready }),
    { initialProps: { busy: false, ready: true } }
  );
  expect(result.current.canAsk).toBe(true);
  act(() => {
    void result.current.toggle();
  });
  expect(fetch).not.toHaveBeenCalled();
  rerender({ busy: true, ready: true });
  expect(result.current.canAsk).toBe(false);
  rerender({ busy: false, ready: false });
  expect(result.current.canAsk).toBe(false);
});

it("rejects a delayed status from the old exact source after switching", async () => {
  let old: (value: Response) => void = () => {};
  global.fetch = jest.fn((input) =>
    String(input).includes("stream-1")
      ? new Promise<Response>((resolve) => {
          old = resolve;
        })
      : Promise.resolve(response("off"))
  );
  const { result, rerender } = renderHook(
    (stream) => useLiveCapture(stream, { visualAnalystAvailable: true }),
    { initialProps: live }
  );
  const other = { ...live, sensorId: "sensor-2", streamId: "stream-2" };
  rerender(other);
  await waitFor(() => expect(result.current.capture).toBe("off"));
  await act(async () => {
    old(response("on"));
  });
  expect(result.current.capture).toBe("off");
  expect(result.current.canAsk).toBe(false);
  expect(
    (global.fetch as jest.Mock).mock.calls.every(
      ([, options]) => !options.method
    )
  ).toBe(true);
});

it("preserves verified off state and backend failure detail without permitting questions", async () => {
  global.fetch = jest.fn((_input, options) =>
    Promise.resolve(
      options?.method === "POST"
        ? response("off", false, "Storage capacity reservation failed")
        : response("on")
    )
  );
  const { result } = renderHook(() =>
    useLiveCapture(live, { visualAnalystAvailable: true })
  );
  await waitFor(() => expect(result.current.capture).toBe("on"));
  await act(async () => {
    await result.current.toggle();
  });
  expect(result.current.capture).toBe("off");
  expect(result.current.error).toBe("Storage capacity reservation failed");
  expect(result.current.changing).toBe(false);
  expect(result.current.canAsk).toBe(false);
  const post = (global.fetch as jest.Mock).mock.calls.find(
    ([, options]) => options.method === "POST"
  );
  expect(JSON.parse(post[1].body)).toEqual({
    streamId: "stream-1",
    action: "stop",
  });
});

it("uses verified recent footage despite stale sensor discovery, but blocks busy and removed sources", async () => {
  global.fetch = jest.fn(async () => response("on"));
  const { result, rerender } = renderHook(
    ({ stream, busy }) => useLiveCapture(stream, { visualAnalystAvailable: true, busy }),
    { initialProps: { stream: live, busy: false } }
  );
  await waitFor(() => expect(result.current.canAsk).toBe(true));
  expect(result.current.remainingSeconds).toBe(0);
  expect(result.current.warming).toBe(false);
  rerender({ stream: live, busy: true });
  expect(result.current.canAsk).toBe(false);
  rerender({ stream: { ...live, connectionState: "offline" }, busy: false });
  expect(result.current.canAsk).toBe(true);
  rerender({ stream: { ...live, connectionState: "removed" }, busy: false });
  expect(result.current.canAsk).toBe(false);
});

it("blocks disconnected questions when no fresh recorded interval is verified", async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ recordingStatus: "on", questionReady: false }) } as Response));
  const { result } = renderHook(() => useLiveCapture({ ...live, connectionState: "offline" }, { visualAnalystAvailable: true }));
  await waitFor(() => expect(result.current.capture).toBe("on"));
  expect(result.current.canAsk).toBe(false);
});

it("waits for verified footage rather than enabling questions after an arbitrary timer", async () => {
  jest.useFakeTimers();
  let ready = false;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ recordingStatus: "on", questionReady: ready, remainingSeconds: ready ? 0 : 8 }) } as Response));
  const { result } = renderHook(() => useLiveCapture(live, { visualAnalystAvailable: true }));
  await act(async () => {});
  expect(result.current.remainingSeconds).toBe(8);
  expect(result.current.canAsk).toBe(false);
  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(result.current.canAsk).toBe(false);
  ready = true;
  await act(async () => { jest.advanceTimersByTime(3_000); });
  expect(result.current.canAsk).toBe(true);
});

it("does not invent readiness from recording status alone", async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ recordingStatus: "on" }) } as Response));
  const { result } = renderHook(() => useLiveCapture(live, { visualAnalystAvailable: true }));
  await waitFor(() => expect(result.current.capture).toBe("on"));
  expect(result.current.canAsk).toBe(false);
  expect(result.current.warming).toBe(true);
  expect(result.current.remainingSeconds).toBeNull();
});

it("discards readiness for the old duration and only reads metadata when duration changes", async () => {
  let oldRead: (value: Response) => void = () => {};
  global.fetch = jest.fn((input) => String(input).includes("lookbackSeconds=60")
    ? Promise.resolve({ ok: true, json: async () => ({ recordingStatus: "on", questionReady: false, remainingSeconds: 45 }) } as Response)
    : new Promise<Response>(resolve => { oldRead = resolve; }));
  const { result, rerender } = renderHook(
    ({ seconds }) => useLiveCapture(live, { visualAnalystAvailable: true, lookbackSeconds: seconds }),
    { initialProps: { seconds: 15 } }
  );
  rerender({ seconds: 60 });
  await waitFor(() => expect(result.current.remainingSeconds).toBe(45));
  await act(async () => { oldRead(response("on")); });
  expect(result.current.canAsk).toBe(false);
  expect(result.current.remainingSeconds).toBe(45);
  expect((global.fetch as jest.Mock).mock.calls.every(([, init]) => !init.method)).toBe(true);
});

it('blocks questions for exclusive visual monitoring without stopping verified recording, then recovers when paused', async () => {
  jest.useFakeTimers();
  let blocked = true;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ recordingStatus: 'on', questionReady: true, remainingSeconds: 0,
    questionBlockReason: blocked ? 'Pause visual monitoring in Alert rules to ask a question.' : null }) } as Response));
  const { result, unmount } = renderHook(() => useLiveCapture(live, { visualAnalystAvailable: true }));
  try {
    await act(async () => {});
    expect(result.current.capture).toBe('on');
    expect(result.current.warming).toBe(false);
    expect(result.current.canAsk).toBe(false);
    expect(result.current.questionBlockReason).toContain('Pause visual monitoring');
    blocked = false;
    await act(async () => { jest.advanceTimersByTime(3000); });
    expect(result.current.canAsk).toBe(true);
    expect(result.current.questionBlockReason).toBeNull();
    expect((global.fetch as jest.Mock).mock.calls.every(([, options]) => !options?.method)).toBe(true);
  } finally { unmount(); }
});
