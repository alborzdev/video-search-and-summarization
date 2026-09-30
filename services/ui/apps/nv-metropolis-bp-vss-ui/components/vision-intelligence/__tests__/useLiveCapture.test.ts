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
  ({ ok, json: async () => ({ recordingStatus, error }) } as Response);

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

it("waits thirty seconds after observing capture and blocks disconnected or busy live questions", async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn(async () => response("on"));
  const { result, rerender } = renderHook(
    ({ stream, busy }) =>
      useLiveCapture(stream, { visualAnalystAvailable: true, busy }),
    { initialProps: { stream: live, busy: false } }
  );
  await act(async () => {});
  expect(result.current.remainingSeconds).toBe(30);
  expect(result.current.canAsk).toBe(false);
  await act(async () => {
    jest.advanceTimersByTime(30_000);
  });
  expect(result.current.canAsk).toBe(true);
  rerender({ stream: live, busy: true });
  expect(result.current.canAsk).toBe(false);
  rerender({ stream: { ...live, connectionState: "offline" }, busy: false });
  expect(result.current.canAsk).toBe(false);
});
