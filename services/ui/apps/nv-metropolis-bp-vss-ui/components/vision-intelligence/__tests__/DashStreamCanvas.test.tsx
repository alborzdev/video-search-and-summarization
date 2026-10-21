// SPDX-License-Identifier: MIT

import { DashPlaybackCapability } from "../DashPlaybackCapability";
import { DashStreamCanvas } from "../DashStreamCanvas";
import { VisionStreamCanvas } from "../VisionStreamCanvas";
import type { VisionStream } from "../types";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

const start = jest.fn(),
  stop = jest.fn(),
  seek = jest.fn();
jest.mock(
  "@vss/vios-dash",
  () => ({
    DashStream: class {
      start = start;
      stop = stop;
      seekReplay = seek;
    },
  }),
  { virtual: true }
);
const source = {
  streamId: "saved-source",
  sensorId: "saved-source",
  name: "Saved clip",
  type: "file",
  url: "clip.mp4",
  vodUrl: "",
  metadata: {},
  isMain: true,
} as VisionStream;
const timeline = {
  startTime: "2025-01-01T00:00:00Z",
  endTime: "2025-01-01T00:00:08Z",
};
const pending = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
describe("DASH recorded adapter", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    start.mockReset().mockResolvedValue({ viewerId: "viewer" });
    stop.mockReset().mockResolvedValue(undefined);
    seek.mockReset().mockResolvedValue({ viewerId: "viewer" });
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => [timeline],
    })) as jest.Mock;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.useRealTimers();
  });
  it("waits for decoded first frame, passes exact window and releases its own client on unmount", async () => {
    const status = jest.fn(),
      fallback = jest.fn();
    const view = render(
      <DashStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        onPlaybackStatus={status}
        onFallback={fallback}
      />
    );
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        streamId: source.streamId,
        endpoint: window.location.origin,
        startTime: "2025-01-01T00:00:00.000Z",
        endTime: "2025-01-01T00:00:08.000Z",
      })
    );
    expect(status).not.toHaveBeenCalledWith("playing");
    act(() => start.mock.calls[0][0].onFirstFrame());
    expect(status).toHaveBeenLastCalledWith("playing");
    view.unmount();
    expect(stop).toHaveBeenCalledTimes(1);
    expect(fallback).not.toHaveBeenCalled();
  });
  it("aborts a pending source timeline without creating a session after unmount", async () => {
    const held = pending<any>();
    global.fetch = jest.fn(() => held.promise) as jest.Mock;
    const view = render(
      <DashStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        onFallback={jest.fn()}
      />
    );
    const signal = (global.fetch as jest.Mock).mock.calls[0][1].signal;
    view.unmount();
    await act(async () =>
      held.resolve({ ok: true, json: async () => [timeline] })
    );
    expect(signal.aborted).toBe(true);
    expect(start).not.toHaveBeenCalled();
  });
  it("reports failure for MP4 fallback and ignores callbacks from an unmounted session", async () => {
    const fallback = jest.fn(),
      status = jest.fn();
    const view = render(
      <DashStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        onPlaybackStatus={status}
        onFallback={fallback}
      />
    );
    await waitFor(() => expect(start).toHaveBeenCalled());
    const callbacks = start.mock.calls[0][0];
    act(() => callbacks.onError("packager offline"));
    expect(fallback).toHaveBeenCalledTimes(1);
    view.unmount();
    status.mockClear();
    act(() => {
      callbacks.onFirstFrame();
      callbacks.onError("late failure");
    });
    expect(status).not.toHaveBeenCalled();
    expect(fallback).toHaveBeenCalledTimes(1);
  });
  it("bounds a replay seek that never produces its replacement frame", async () => {
    const fallback = jest.fn();
    const view = render(
      <DashStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        onFallback={fallback}
      />
    );
    await waitFor(() => expect(start).toHaveBeenCalled());
    jest.useFakeTimers();
    act(() => start.mock.calls[0][0].onFirstFrame());
    seek.mockReturnValue(new Promise(() => {}));
    fireEvent.change(
      screen.getByRole("slider", { name: "Recorded video position" }),
      { target: { value: "3" } }
    );
    await act(async () => {
      jest.advanceTimersByTime(250);
    });
    act(() => jest.advanceTimersByTime(60_000));
    expect(fallback).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(stop).toHaveBeenCalledTimes(1);
  });
  it("debounces replay seeks and keeps source timestamps exact", async () => {
    const view = render(
      <DashStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        onFallback={jest.fn()}
      />
    );
    await waitFor(() => expect(start).toHaveBeenCalled());
    act(() => start.mock.calls[0][0].onFirstFrame());
    jest.useFakeTimers();
    fireEvent.change(
      screen.getByRole("slider", { name: "Recorded video position" }),
      { target: { value: "2" } }
    );
    fireEvent.change(
      screen.getByRole("slider", { name: "Recorded video position" }),
      { target: { value: "6" } }
    );
    await act(async () => {
      jest.advanceTimersByTime(250);
    });
    expect(seek).toHaveBeenCalledTimes(1);
    expect(seek).toHaveBeenCalledWith("2025-01-01T00:00:06.000Z");
    view.unmount();
  });
});

describe("recorded protocol selection", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    start.mockReset().mockResolvedValue({ viewerId: "viewer" });
    stop.mockReset().mockResolvedValue(undefined);
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => {});
    jest.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    global.fetch = jest.fn(async (input) => ({
      ok: true,
      json: async () =>
        String(input).includes("/evidence?")
          ? { videoUrl: "http://video.test/clip.mp4" }
          : [timeline],
    })) as jest.Mock;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });
  it("keeps MP4 default and disables DASH without explicit runtime capability", async () => {
    const view = render(
      <VisionStreamCanvas
        stream={source}
        vstApiUrl="http://video.test/vst/api"
        showReplayControls
      />
    );
    expect(
      screen.getByRole("combobox", { name: "Playback protocol" })
    ).toHaveValue("mp4");
    expect(screen.getByRole("option", { name: /DASH/ })).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(view.container.querySelector("video")).toHaveAttribute(
        "src",
        "http://video.test/clip.mp4"
      )
    );
    view.unmount();
  });
  it("keeps verified event and analyst-window playback on its exact MP4 path", async () => {
    const view = render(
      <DashPlaybackCapability.Provider value={true}>
        <VisionStreamCanvas
          stream={source}
          vstApiUrl="http://video.test/vst/api"
          showReplayControls
          observedRange={{ startSeconds: 2, endSeconds: 4 }}
        />
      </DashPlaybackCapability.Provider>
    );
    expect(
      screen.queryByRole("combobox", { name: "Playback protocol" })
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(view.container.querySelector("video")).toHaveAttribute(
        "src",
        "http://video.test/clip.mp4"
      )
    );
    expect(start).not.toHaveBeenCalled();
    view.unmount();
  });
  it("resets protocol on source change and never starts DASH for the new source implicitly", async () => {
    const content = (stream: VisionStream) => (
      <DashPlaybackCapability.Provider value={true}>
        <VisionStreamCanvas
          stream={stream}
          vstApiUrl="http://video.test/vst/api"
          showReplayControls
        />
      </DashPlaybackCapability.Provider>
    );
    const view = render(content(source));
    fireEvent.change(
      screen.getByRole("combobox", { name: "Playback protocol" }),
      { target: { value: "dash" } }
    );
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    view.rerender(
      content({
        ...source,
        streamId: "different-source",
        sensorId: "different-source",
      })
    );
    expect(
      screen.getByRole("combobox", { name: "Playback protocol" })
    ).toHaveValue("mp4");
    await waitFor(() =>
      expect(view.container.querySelector("video")).toHaveAttribute(
        "src",
        "http://video.test/clip.mp4"
      )
    );
    expect(start).toHaveBeenCalledTimes(1);
    expect(stop).toHaveBeenCalledTimes(1);
    view.unmount();
  });
  it("starts only on opt-in and restores MP4 with a visible error when DASH fails", async () => {
    const view = render(
      <DashPlaybackCapability.Provider value={true}>
        <VisionStreamCanvas
          stream={source}
          vstApiUrl="http://video.test/vst/api"
          showReplayControls
        />
      </DashPlaybackCapability.Provider>
    );
    expect(start).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Playback protocol" }),
      { target: { value: "dash" } }
    );
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    act(() => start.mock.calls[0][0].onError("packager unavailable"));
    expect(
      screen.getByRole("combobox", { name: "Playback protocol" })
    ).toHaveValue("mp4");
    expect(screen.getByRole("status")).toHaveTextContent("MP4 restored");
    expect(stop).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(view.container.querySelector("video")).toHaveAttribute(
        "src",
        "http://video.test/clip.mp4"
      )
    );
    view.unmount();
  });
});
