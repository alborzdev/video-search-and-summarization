// SPDX-License-Identifier: MIT

import type { VisionStream } from "../types";
import { useLiveCapture } from "../useLiveCapture";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

const first: VisionStream = {
  name: "First camera",
  sensorId: "sensor-first",
  streamId: "storage-first",
  isMain: true,
  metadata: {},
  type: "Rtsp",
  url: "rtsp://camera.test/first",
  vodUrl: "",
  connectionState: "online",
};
const second: VisionStream = {
  ...first,
  name: "Second camera",
  sensorId: "sensor-second",
  streamId: "storage-second",
  url: "rtsp://camera.test/second",
};
function json(body: unknown): Response {
  return { ok: true, json: async () => body } as Response;
}
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function CaptureHarness({
  stream,
  ready = true,
}: {
  stream: VisionStream;
  ready?: boolean | null;
}) {
  const capture = useLiveCapture(stream, { visualAnalystAvailable: ready });
  return (
    <div>
      <output aria-label="Capture state">{capture.capture}</output>
      <output aria-label="Capture warmup">{capture.remainingSeconds}</output>
      <button disabled={!capture.canAsk}>Ask this source</button>
      <button
        disabled={capture.changing || capture.capture === "unknown"}
        onClick={() => void capture.toggle()}
      >
        Toggle capture
      </button>
    </div>
  );
}

describe("source-bound live capture", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    cleanup();
    jest.useRealTimers();
    global.fetch = originalFetch;
  });

  it("ignores a late previous-source read and uses the new source’s verified footage without a delay", async () => {
    jest.useFakeTimers({ now: new Date("2026-09-30T03:00:00Z") });
    const oldRead = deferred();
    global.fetch = jest.fn(async (input) =>
      String(input).includes(first.streamId)
        ? oldRead.promise
        : json({ streamId: second.streamId, recordingStatus: "on", questionReady: true, remainingSeconds: 0 })
    ) as jest.Mock;
    const view = render(<CaptureHarness stream={first} />);
    expect(
      screen.getByRole("button", { name: "Ask this source" })
    ).toBeDisabled();
    view.rerender(<CaptureHarness stream={second} />);
    await waitFor(() =>
      expect(screen.getByLabelText("Capture state")).toHaveTextContent("on")
    );
    expect(screen.getByLabelText("Capture warmup")).toHaveTextContent("0");
    await act(async () => {
      oldRead.resolve(
        json({ streamId: first.streamId, recordingStatus: "off" })
      );
    });
    expect(screen.getByLabelText("Capture state")).toHaveTextContent("on");
    expect(screen.getByRole("button", { name: "Ask this source" })).toBeEnabled();
    expect(
      (global.fetch as jest.Mock).mock.calls.every(([, init]) => !init?.method)
    ).toBe(true);
  });

  it("aborts an old source capture mutation and ignores its late verified-on response", async () => {
    const oldStart = deferred();
    let startSignal: AbortSignal | undefined;
    global.fetch = jest.fn(async (input, init) => {
      if (init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({
          streamId: first.streamId,
          action: "start",
        });
        startSignal = init.signal as AbortSignal;
        return oldStart.promise;
      }
      return json({ recordingStatus: "off" });
    }) as jest.Mock;
    const view = render(<CaptureHarness stream={first} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Toggle capture" })
      ).toBeEnabled()
    );
    fireEvent.click(screen.getByRole("button", { name: "Toggle capture" }));
    expect(
      screen.getByRole("button", { name: "Toggle capture" })
    ).toBeDisabled();
    view.rerender(<CaptureHarness stream={second} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Toggle capture" })
      ).toBeEnabled()
    );
    expect(startSignal?.aborted).toBe(true);
    await act(async () => {
      oldStart.resolve(
        json({ streamId: first.streamId, recordingStatus: "on" })
      );
    });
    expect(screen.getByLabelText("Capture state")).toHaveTextContent("off");
    expect(
      screen.getByRole("button", { name: "Ask this source" })
    ).toBeDisabled();
    expect(
      (global.fetch as jest.Mock).mock.calls.filter(
        ([, init]) => init?.method === "POST"
      )
    ).toHaveLength(1);
  });
});
