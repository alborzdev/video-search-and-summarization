// SPDX-License-Identifier: MIT

import { VisionStreamCanvas } from "../VisionStreamCanvas";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

const replay = {
  isMain: true,
  metadata: {},
  name: "Traffic — Main Intersection",
  sensorId: "traffic",
  streamId: "traffic-stream-id",
  type: "file",
  url: "",
  vodUrl: "",
};

describe("VisionStreamCanvas", () => {
  beforeEach(() => {
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => undefined);
  });
  afterEach(() => {
    cleanup();
    jest.restoreAllMocks();
  });

  it("keeps the empty player hidden until a decoded frame and ignores source-less cleanup errors", () => {
    const { container } = render(<VisionStreamCanvas stream={replay} />);
    const video = container.querySelector("video")!;
    expect(video).toHaveStyle({ visibility: "hidden" });
    fireEvent.error(video);
    expect(
      screen.queryByText(/Video could not be loaded/)
    ).not.toBeInTheDocument();
    fireEvent.loadedData(video);
    expect(video).toHaveStyle({ visibility: "visible" });
    fireEvent.emptied(video);
    expect(video).toHaveStyle({ visibility: "hidden" });
    video.setAttribute("src", "/missing.mp4");
    fireEvent.error(video);
    expect(screen.getByText(/Video could not be loaded/)).toBeInTheDocument();
  });

  it("never treats an unavailable illustration as a usable camera frame", async () => {
    const onPreviewAvailable = jest.fn();
    const blob = jest.fn(
      async () => new Blob(["<svg/>"], { type: "image/svg+xml" })
    );
    global.fetch = jest.fn(async (input) =>
      String(input).includes("/timelines")
        ? {
            ok: true,
            json: async () => [
              {
                startTime: "2025-01-01T00:00:00Z",
                endTime: "2025-01-01T00:00:10Z",
              },
            ],
          }
        : { ok: true, headers: { get: () => "unavailable" }, blob }
    ) as jest.Mock;
    const { container } = render(
      <VisionStreamCanvas
        eager={false}
        stream={replay}
        vstApiUrl="http://thor.test/vst/api"
        onPreviewAvailable={onPreviewAvailable}
      />
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(blob).not.toHaveBeenCalled();
    expect(container.querySelector("img")).toBeNull();
    expect(onPreviewAvailable).toHaveBeenLastCalledWith(false);
  });

  it("does not regenerate a replay when its poster finishes loading", async () => {
    let resolvePicture!: (response: Response) => void;
    const pictureResponse = new Promise<Response>((resolve) => {
      resolvePicture = resolve;
    });

    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:poster"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    jest.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation();
    jest.spyOn(HTMLMediaElement.prototype, "load").mockImplementation();

    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/timelines")) {
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2025-01-01T00:00:00.000Z",
              endTime: "2025-01-01T00:02:00.000Z",
            },
          ],
        } as Response;
      }
      if (url.includes("picture")) return pictureResponse;
      if (
        url.includes("/api/vision/evidence?") &&
        url.includes("sensorId=traffic-stream-id")
      ) {
        return {
          ok: true,
          json: async () => ({
            videoUrl: "http://thor.test/vst/storage/temp_files/traffic.mp4",
          }),
        } as Response;
      }
      return { ok: false, status: 404 } as Response;
    }) as jest.Mock;

    const onPreviewAvailable = jest.fn();
    const { container } = render(
      <VisionStreamCanvas
        onPreviewAvailable={onPreviewAvailable}
        stream={replay}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    const replayRequests = () =>
      (global.fetch as jest.Mock).mock.calls.filter(
        ([input]) =>
          String(input).includes("/api/vision/evidence?") &&
          String(input).includes("sensorId=traffic-stream-id")
      );
    await waitFor(() => expect(replayRequests()).toHaveLength(1));

    resolvePicture({
      ok: true,
      blob: async () => new Blob(["poster"], { type: "image/jpeg" }),
    } as Response);
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));

    // A returned image URL is not proof that the browser decoded a usable frame.
    expect(onPreviewAvailable).toHaveBeenLastCalledWith(false);
    const poster = container.querySelector("img")!;
    Object.defineProperty(poster, "naturalWidth", {
      configurable: true,
      value: 1280,
    });
    fireEvent.load(poster);
    expect(onPreviewAvailable).toHaveBeenLastCalledWith(true);
    fireEvent.error(poster);
    expect(onPreviewAvailable).toHaveBeenLastCalledWith(false);

    expect(replayRequests()).toHaveLength(1);
  });

  it("shows canonical replay time and seeks through verified event markers", async () => {
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    jest.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation();
    jest.spyOn(HTMLMediaElement.prototype, "load").mockImplementation();
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/timelines"))
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2025-01-01T00:00:00.000Z",
              endTime: "2025-01-01T00:04:00.000Z",
            },
          ],
        } as Response;
      if (
        url.includes("/api/vision/evidence?") &&
        url.includes("sensorId=traffic-stream-id")
      )
        return {
          ok: true,
          json: async () => ({
            videoUrl: "http://thor.test/vst/storage/temp_files/traffic.mp4",
          }),
        } as Response;
      return { ok: false, status: 404 } as Response;
    }) as jest.Mock;

    const { container } = render(
      <VisionStreamCanvas
        evidenceEvents={[
          {
            id: "first",
            endTime: "2025-01-01T00:01:09.000Z",
            label: "Person observed",
            startTime: "2025-01-01T00:01:07.000Z",
          },
          {
            id: "second",
            endTime: "2025-01-01T00:03:10.000Z",
            label: "Person observed",
            startTime: "2025-01-01T00:03:07.000Z",
          },
        ]}
        showReplayControls
        stream={replay}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await screen.findByRole("button", { name: "Next verified event" });
    const video = container.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 240,
    });
    Object.defineProperty(video, "currentTime", {
      configurable: true,
      writable: true,
      value: 0,
    });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(65);
    expect(screen.getByText("1:05 / 4:00")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Next verified event" })
    );
    expect(video.currentTime).toBe(185);
    expect(screen.getByText("3:05 / 4:00")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /Jump to verified event/ })
    ).toHaveLength(2);
  });

  it("uses retained storage for a paused live camera poster before calling the noisy live endpoint", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:retained-live-poster"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const decodedUrl = decodeURIComponent(url);
      if (url.includes("/timelines"))
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2025-01-01T00:00:00.000Z",
              endTime: "2025-01-01T00:02:00.000Z",
            },
          ],
        } as Response;
      if (
        decodedUrl.includes("/storage/stream/") &&
        decodedUrl.includes("/picture?")
      )
        return {
          ok: true,
          blob: async () => new Blob(["poster"], { type: "image/jpeg" }),
        } as Response;
      return { ok: false, status: 500 } as Response;
    }) as jest.Mock;
    const live = {
      ...replay,
      name: "Paused camera",
      streamId: "paused-live-stream",
      type: "rtsp",
      url: "rtsp://camera.test/live",
    };

    render(
      <VisionStreamCanvas
        eager={false}
        stream={live}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    expect(
      (global.fetch as jest.Mock).mock.calls.some(([input]) =>
        String(input).includes("/v1/live/stream/")
      )
    ).toBe(false);
  });

  it.each([
    {
      kind: "live",
      type: "rtsp",
      url: "rtsp://camera.test/live",
      expected: "2026-09-30T03:04:55.000Z",
    },
    {
      kind: "replay",
      type: "file",
      url: "",
      expected: "2026-09-30T00:00:10.000Z",
    },
  ])(
    "uses a recent retained frame for $kind without changing replay poster selection",
    async ({ type, url, expected }) => {
      const timelines = [
        {
          startTime: "2026-09-30T03:04:00.000Z",
          endTime: "2026-09-30T03:05:00.000Z",
        },
        { startTime: "invalid-start", endTime: "2100-01-01T00:00:00Z" },
        {
          startTime: "2026-09-30T00:00:00.000Z",
          endTime: "2026-09-30T00:02:00.000Z",
        },
      ];
      global.fetch = jest.fn(async (input) =>
        String(input).includes("/timelines")
          ? { ok: true, json: async () => timelines }
          : { ok: false, status: 500 }
      ) as jest.Mock;
      render(
        <VisionStreamCanvas
          eager={false}
          liveSnapshotEnabled={false}
          stream={{ ...replay, type, url }}
          vstApiUrl="http://thor.test/vst/api"
        />
      );
      await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
      const picture = new URL(
        String((global.fetch as jest.Mock).mock.calls[1][0]),
        "http://ui.test"
      );
      const storedRequest = new URL(
        picture.searchParams.get("path")!,
        "http://thor.test"
      );
      expect(storedRequest.pathname).toBe(
        `/vst/api/v1/storage/stream/${replay.streamId}/picture`
      );
      expect(storedRequest.searchParams.get("startTime")).toBe(expected);
      expect(
        (global.fetch as jest.Mock).mock.calls.every(
          ([, init]) => !init?.method
        )
      ).toBe(true);
    }
  );

  it.each([2_000, 500])(
    "keeps a live poster timestamp inside a short %ims retained interval",
    async (duration) => {
      const start = Date.parse("2026-09-30T03:05:00.000Z");
      const end = start + duration;
      global.fetch = jest.fn(async (input) =>
        String(input).includes("/timelines")
          ? {
              ok: true,
              json: async () => [
                {
                  startTime: new Date(start).toISOString(),
                  endTime: new Date(end).toISOString(),
                },
                {
                  startTime: "2026-09-30T00:00:00.000Z",
                  endTime: "2026-09-30T00:10:00.000Z",
                },
              ],
            }
          : { ok: false, status: 500 }
      ) as jest.Mock;
      render(
        <VisionStreamCanvas
          eager={false}
          liveSnapshotEnabled={false}
          stream={{ ...replay, type: "rtsp", url: "rtsp://camera.test/live" }}
          vstApiUrl="http://thor.test/vst/api"
        />
      );
      await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
      const proxy = new URL(
        String((global.fetch as jest.Mock).mock.calls[1][0]),
        "http://ui.test"
      );
      const timestamp = new URL(
        proxy.searchParams.get("path")!,
        "http://thor.test"
      ).searchParams.get("startTime")!;
      expect(Date.parse(timestamp)).toBeGreaterThanOrEqual(start);
      expect(Date.parse(timestamp)).toBeLessThanOrEqual(end);
    }
  );

  it("does not probe the noisy live snapshot endpoint for an explicitly paused camera", async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/timelines")) {
        return { ok: true, json: async () => [] } as Response;
      }
      return { ok: false, status: 500 } as Response;
    }) as jest.Mock;
    const live = {
      ...replay,
      name: "Paused camera",
      streamId: "paused-without-poster",
      type: "rtsp",
      url: "rtsp://camera.test/live",
    };

    render(
      <VisionStreamCanvas
        eager={false}
        liveSnapshotEnabled={false}
        stream={live}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toContain(
      "/timelines"
    );
  });

  it("does not claim live playback on ICE connection and waits for a decoded frame callback", async () => {
    const originals = {
      WebSocket: global.WebSocket,
      RTCPeerConnection: global.RTCPeerConnection,
      MediaStream: global.MediaStream,
    };
    const sockets: MockSocket[] = [];
    const peers: MockPeer[] = [];
    class MockSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      send = jest.fn();
      close = jest.fn();
      constructor() {
        sockets.push(this);
      }
    }
    class MockPeer {
      connectionState = "new";
      localDescription = { type: "offer", sdp: "offer" };
      onconnectionstatechange: (() => void) | null = null;
      ontrack:
        | ((event: { streams: MediaStream[]; track: MediaStreamTrack }) => void)
        | null = null;
      addTransceiver = jest.fn();
      createOffer = jest
        .fn()
        .mockResolvedValue({ type: "offer", sdp: "offer" });
      setLocalDescription = jest.fn().mockResolvedValue(undefined);
      close = jest.fn();
      constructor() {
        peers.push(this);
      }
    }
    const globals = {
      WebSocket: MockSocket,
      RTCPeerConnection: MockPeer,
      MediaStream: class {
        addTrack = jest.fn();
      },
    };
    for (const [name, value] of Object.entries(globals))
      Object.defineProperty(global, name, { configurable: true, value });
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
    const onPlaybackStatus = jest.fn();
    const view = render(
      <VisionStreamCanvas
        stream={{ ...replay, type: "rtsp", url: "rtsp://camera.test/live" }}
        liveSnapshotEnabled={false}
        vstApiUrl="http://vst.test/vst/api"
        onPlaybackStatus={onPlaybackStatus}
      />
    );
    try {
      await waitFor(() => expect(sockets).toHaveLength(1));
      act(() => {
        sockets[0].onopen?.();
        sockets[0].onmessage?.({
          data: JSON.stringify({
            apiKey: "api/v1/live/iceServers",
            data: { iceServers: [] },
          }),
        });
      });
      await waitFor(() =>
        expect(sockets[0].send).toHaveBeenCalledWith(
          expect.stringContaining("api/v1/live/stream/start")
        )
      );
      act(() => {
        peers[0].connectionState = "connected";
        peers[0].onconnectionstatechange?.();
      });
      const video = view.container.querySelector("video")!;
      expect(onPlaybackStatus).not.toHaveBeenCalledWith("playing");
      expect(video).toHaveStyle({ visibility: "hidden" });
      let decodedFrame!: () => void;
      const requestFrame = jest.fn((callback: () => void) => {
        decodedFrame = callback;
        return 42;
      });
      Object.defineProperty(video, "requestVideoFrameCallback", {
        configurable: true,
        value: requestFrame,
      });
      const cancelFrame = jest.fn();
      Object.defineProperty(video, "cancelVideoFrameCallback", {
        configurable: true,
        value: cancelFrame,
      });
      act(() => {
        peers[0].ontrack?.({ streams: [], track: {} as MediaStreamTrack });
      });
      expect(requestFrame).toHaveBeenCalledTimes(1);
      expect(onPlaybackStatus).not.toHaveBeenCalledWith("playing");
      act(() => {
        decodedFrame();
      });
      expect(onPlaybackStatus).toHaveBeenLastCalledWith("playing");
      expect(video).toHaveStyle({ visibility: "visible" });
      act(() => {
        peers[0].ontrack?.({ streams: [], track: {} as MediaStreamTrack });
      });
      view.unmount();
      expect(cancelFrame).toHaveBeenCalledWith(42);
      const callbacksBeforeLateFrame = onPlaybackStatus.mock.calls.length;
      act(() => {
        decodedFrame();
      });
      expect(onPlaybackStatus).toHaveBeenCalledTimes(callbacksBeforeLateFrame);
    } finally {
      view.unmount();
      for (const [name, value] of Object.entries(originals))
        Object.defineProperty(global, name, { configurable: true, value });
    }
  });

  it("rescans a live camera that was offline when video services started", async () => {
    const realWebSocket = global.WebSocket;
    const realPeerConnection = global.RTCPeerConnection;
    const realMediaStream = global.MediaStream;
    const sockets: MockWebSocket[] = [];
    class MockWebSocket {
      static OPEN = 1;
      readyState = 1;
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      send = jest.fn();
      close = jest.fn();
      constructor() {
        sockets.push(this);
      }
      emit(payload: object) {
        this.onmessage?.({ data: JSON.stringify(payload) });
      }
    }
    class MockPeerConnection {
      connectionState = "new";
      localDescription = { sdp: "offer", type: "offer" };
      remoteDescription = null;
      ontrack = null;
      onicecandidate = null;
      onconnectionstatechange = null;
      addTransceiver = jest.fn();
      addIceCandidate = jest.fn().mockResolvedValue(undefined);
      createOffer = jest
        .fn()
        .mockResolvedValue({ sdp: "offer", type: "offer" });
      setLocalDescription = jest.fn().mockResolvedValue(undefined);
      setRemoteDescription = jest.fn().mockResolvedValue(undefined);
      close = jest.fn();
    }
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: MockWebSocket,
    });
    Object.defineProperty(global, "RTCPeerConnection", {
      configurable: true,
      value: MockPeerConnection,
    });
    Object.defineProperty(global, "MediaStream", {
      configurable: true,
      value: class {
        addTrack = jest.fn();
      },
    });
    global.fetch = jest.fn(
      async (input: RequestInfo | URL) =>
        ({
          ok: String(input).endsWith("/v1/sensor/scan"),
          status: String(input).endsWith("/v1/sensor/scan") ? 200 : 404,
        } as Response)
    ) as jest.Mock;

    const live = {
      ...replay,
      name: "Preview 01 Main",
      streamId: "preview-stream-id",
      type: "rtsp",
      url: "rtsp://camera.test/live",
    };
    const view = render(
      <VisionStreamCanvas stream={live} vstApiUrl="http://thor.test/vst/api" />
    );

    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0].onopen?.());
    act(() =>
      sockets[0].emit({
        apiKey: "api/v1/live/iceServers",
        data: { iceServers: [] },
      })
    );
    await waitFor(() => expect(sockets[0].send).toHaveBeenCalled());
    act(() =>
      sockets[0].emit({
        apiKey: "api/v1/live/setAnswer",
        data: {
          error_code: "CameraNotFoundError",
          error_message: "Camera not found OR camera id is not valid",
        },
      })
    );

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        "http://thor.test/vst/api/v1/sensor/scan",
        { method: "POST" }
      )
    );
    expect(
      screen.getByText(/offline when video services started/i)
    ).toBeInTheDocument();
    view.unmount();
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: realWebSocket,
    });
    Object.defineProperty(global, "RTCPeerConnection", {
      configurable: true,
      value: realPeerConnection,
    });
    Object.defineProperty(global, "MediaStream", {
      configurable: true,
      value: realMediaStream,
    });
  });
  it("does not allocate a poster object URL after its canvas was unmounted", async () => {
    let finishBlob!: (blob: Blob) => void;
    const body = new Promise<Blob>((resolve) => { finishBlob = resolve; });
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: jest.fn(() => "blob:late") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: jest.fn() });
    global.fetch = jest.fn(async (input) => String(input).includes('/timelines')
      ? { ok: true, json: async () => [{ startTime: '2026-10-01T00:00:00Z', endTime: '2026-10-01T00:01:00Z' }] }
      : { ok: true, headers: { get: () => null }, blob: () => body }) as jest.Mock;
    const view = render(<VisionStreamCanvas eager={false} stream={replay} vstApiUrl="http://thor.test/vst/api" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    view.unmount();
    for (const [, options] of (global.fetch as jest.Mock).mock.calls) expect(options.signal.aborted).toBe(true);
    await act(async () => { finishBlob(new Blob(['poster'], { type: 'image/jpeg' })); });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("ignores a late replay response body after switching cameras", async () => {
    let finishOld!: (body: { videoUrl: string }) => void;
    const oldBody = new Promise<{ videoUrl: string }>((resolve) => { finishOld = resolve; });
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.includes('/timelines')) return { ok: true, json: async () => [{ startTime: '2026-10-01T00:00:00Z', endTime: '2026-10-01T00:01:00Z' }] };
      if (url.includes('/api/vision/evidence?')) return { ok: true, json: () => url.includes('traffic-stream-id') ? oldBody : Promise.resolve({ videoUrl: 'http://thor.test/new-camera.mp4' }) };
      return { ok: false };
    }) as jest.Mock;
    const view = render(<VisionStreamCanvas stream={replay} vstApiUrl="http://thor.test/vst/api" />);
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([url]) => String(url).includes('/api/vision/evidence?'))).toBe(true));
    view.rerender(<VisionStreamCanvas stream={{ ...replay, streamId: 'new-camera' }} vstApiUrl="http://thor.test/vst/api" />);
    await waitFor(() => expect(view.container.querySelector('video')).toHaveAttribute('src', 'http://thor.test/new-camera.mp4'));
    await act(async () => { finishOld({ videoUrl: 'http://thor.test/old-camera.mp4' }); });
    expect(view.container.querySelector('video')).toHaveAttribute('src', 'http://thor.test/new-camera.mp4');
  });

});

function mockLiveRtc() {
  const originals = {
    WebSocket: global.WebSocket,
    RTCPeerConnection: global.RTCPeerConnection,
    MediaStream: global.MediaStream,
  };
  const sockets: Socket[] = [];
  const peers: Peer[] = [];
  class Socket {
    static OPEN = 1;
    readyState = 1;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    send = jest.fn();
    close = jest.fn();
    constructor(readonly url: string) {
      sockets.push(this);
    }
    emit(payload: object) {
      this.onmessage?.({ data: JSON.stringify(payload) });
    }
  }
  class Peer {
    connectionState = "new";
    localDescription = { type: "offer", sdp: "offer" };
    remoteDescription: unknown = null;
    ontrack:
      | ((event: { streams: MediaStream[]; track: MediaStreamTrack }) => void)
      | null = null;
    onconnectionstatechange: (() => void) | null = null;
    onicecandidate: unknown = null;
    addTransceiver = jest.fn();
    addIceCandidate = jest.fn().mockResolvedValue(undefined);
    createOffer = jest.fn().mockResolvedValue({ type: "offer", sdp: "offer" });
    setLocalDescription = jest.fn().mockResolvedValue(undefined);
    setRemoteDescription = jest.fn(async (description) => {
      this.remoteDescription = description;
    });
    close = jest.fn();
    constructor() {
      peers.push(this);
    }
  }
  for (const [name, value] of Object.entries({
    WebSocket: Socket,
    RTCPeerConnection: Peer,
    MediaStream: class {
      addTrack = jest.fn();
    },
  }))
    Object.defineProperty(global, name, { configurable: true, value });
  return {
    sockets,
    peers,
    restore: () => {
      for (const [name, value] of Object.entries(originals))
        Object.defineProperty(global, name, { configurable: true, value });
    },
  };
}

let liveHandoffTestId = 0;
describe("live Canvas handoff and decoded-frame deadline", () => {
  let rtc: ReturnType<typeof mockLiveRtc>;
  let live: typeof replay;
  const endpoint = "http://handoff.test/vst/api";
  const originalFetch = global.fetch;
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date("2026-09-30T12:00:00Z") });
    rtc = mockLiveRtc();
    live = {
      ...replay,
      streamId: `handoff-${++liveHandoffTestId}`,
      type: "rtsp",
      url: "rtsp://camera.test/live",
    };
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => undefined);
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
  });
  afterEach(async () => {
    await act(async () => {});
    cleanup();
    rtc.restore();
    jest.restoreAllMocks();
    jest.useRealTimers();
    global.fetch = originalFetch;
  });
  const advance = async (ms: number) => {
    await act(async () => {
      jest.advanceTimersByTime(ms);
    });
  };
  const mount = (
    stream = live,
    vstApiUrl = endpoint,
    onPlaybackStatus?: (status: string) => void
  ) =>
    render(
      <VisionStreamCanvas
        stream={stream}
        liveSnapshotEnabled={false}
        vstApiUrl={vstApiUrl}
        onPlaybackStatus={onPlaybackStatus}
      />
    );
  const connect = async () => {
    await act(async () => {
      rtc.sockets[0].onopen?.();
      rtc.sockets[0].emit({
        apiKey: "api/v1/live/iceServers",
        data: { iceServers: [] },
      });
    });
    expect(rtc.peers).toHaveLength(1);
    act(() => {
      rtc.peers[0].connectionState = "connected";
      rtc.peers[0].onconnectionstatechange?.();
    });
  };

  it("waits for same-camera teardown before opening a replacement websocket", async () => {
    const firstView = mount();
    await advance(0);
    expect(rtc.sockets).toHaveLength(1);
    await connect();
    await act(async () => {
      rtc.sockets[0].emit({
        apiKey: "api/v1/live/setAnswer",
        data: { type: "answer", sdp: "answer", mediaSessionId: "old-session" },
      });
    });
    firstView.unmount();
    expect(rtc.sockets[0].send).toHaveBeenCalledWith(
      expect.stringContaining("api/v1/live/stream/stop")
    );
    expect(rtc.sockets[0].close).toHaveBeenCalledTimes(1);
    mount();
    await advance(1_199);
    expect(rtc.sockets).toHaveLength(1);
    await advance(1);
    expect(rtc.sockets).toHaveLength(2);
  });

  it.each(["other-stream", "other-endpoint"])(
    "does not hold an independent %s behind another camera teardown",
    async (separation) => {
      const firstView = mount();
      await advance(0);
      expect(rtc.sockets).toHaveLength(1);
      firstView.unmount();
      mount(
        separation === "other-stream"
          ? { ...live, streamId: `${live.streamId}-other` }
          : live,
        separation === "other-endpoint"
          ? "http://other-vst.test/vst/api"
          : endpoint
      );
      await advance(0);
      expect(rtc.sockets).toHaveLength(2);
    }
  );

  it("cancels an abandoned delayed mount without creating a websocket or late playback status", async () => {
    const firstView = mount();
    await advance(0);
    firstView.unmount();
    const onPlaybackStatus = jest.fn();
    const replacement = mount(live, endpoint, onPlaybackStatus);
    await advance(400);
    expect(rtc.sockets).toHaveLength(1);
    replacement.unmount();
    const statusCount = onPlaybackStatus.mock.calls.length;
    await advance(25_000);
    expect(rtc.sockets).toHaveLength(1);
    expect(onPlaybackStatus).toHaveBeenCalledTimes(statusCount);
    expect(onPlaybackStatus).not.toHaveBeenCalledWith("error");
  });

  it("offers an explicit retry when ICE connects but no decoded video frame arrives", async () => {
    const onPlaybackStatus = jest.fn();
    const view = mount(live, endpoint, onPlaybackStatus);
    await advance(0);
    await connect();
    const video = view.container.querySelector("video")!;
    Object.defineProperty(video, "requestVideoFrameCallback", {
      configurable: true,
      value: jest.fn(() => 1),
    });
    Object.defineProperty(video, "cancelVideoFrameCallback", {
      configurable: true,
      value: jest.fn(),
    });
    await act(async () => {
      rtc.peers[0].ontrack?.({ streams: [], track: {} as MediaStreamTrack });
    });
    await advance(19_999);
    expect(
      screen.queryByRole("button", { name: "Retry" })
    ).not.toBeInTheDocument();
    expect(onPlaybackStatus).not.toHaveBeenCalledWith("playing");
    await advance(1);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(onPlaybackStatus).toHaveBeenLastCalledWith("error");
    expect(video).toHaveStyle({ visibility: "hidden" });
  });

  it("clears the connection deadline only after a decoded frame and does not later replace playback with an error", async () => {
    const onPlaybackStatus = jest.fn();
    const view = mount(live, endpoint, onPlaybackStatus);
    await advance(0);
    await connect();
    const video = view.container.querySelector("video")!;
    let decodedFrame!: () => void;
    Object.defineProperty(video, "requestVideoFrameCallback", {
      configurable: true,
      value: jest.fn((callback) => {
        decodedFrame = callback;
        return 1;
      }),
    });
    Object.defineProperty(video, "cancelVideoFrameCallback", {
      configurable: true,
      value: jest.fn(),
    });
    await act(async () => {
      rtc.peers[0].ontrack?.({ streams: [], track: {} as MediaStreamTrack });
    });
    await advance(19_999);
    act(() => decodedFrame());
    expect(onPlaybackStatus).toHaveBeenLastCalledWith("playing");
    expect(video).toHaveStyle({ visibility: "visible" });
    await advance(25_000);
    expect(
      screen.queryByRole("button", { name: "Retry" })
    ).not.toBeInTheDocument();
    expect(onPlaybackStatus).not.toHaveBeenCalledWith("error");
    expect(onPlaybackStatus).toHaveBeenLastCalledWith("playing");
  });
  it("reconnects a failed preview after the same camera publisher returns online", async () => {
    const view = mount({ ...live, connectionState: 'offline' } as typeof live);
    await advance(20_000);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    view.rerender(<VisionStreamCanvas stream={{ ...live, connectionState: 'online' }} liveSnapshotEnabled={false} vstApiUrl={endpoint} />);
    expect(rtc.sockets[0].close).toHaveBeenCalledTimes(1);
    await advance(1200);
    expect(rtc.sockets).toHaveLength(2);
    view.rerender(<VisionStreamCanvas stream={{ ...live, connectionState: 'online' }} liveSnapshotEnabled={false} vstApiUrl={endpoint} />);
    await advance(1000);
    expect(rtc.sockets).toHaveLength(2);
    view.unmount();
    expect(rtc.sockets[1].close).toHaveBeenCalledTimes(1);
    await advance(8 * 60 * 60 * 1000);
    expect(rtc.sockets).toHaveLength(2);
  });

  it("retries a failed live preview when a long-hidden browser returns, and removes resume listeners on unmount", async () => {
    const view = mount();
    await advance(20_000);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    fireEvent(document, new Event('visibilitychange'));
    await advance(8 * 60 * 60 * 1000);
    expect(rtc.sockets).toHaveLength(1);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    fireEvent(document, new Event('visibilitychange'));
    await advance(1200);
    expect(rtc.sockets).toHaveLength(2);
    view.unmount();
    fireEvent(window, new Event('online'));
    fireEvent(document, new Event('visibilitychange'));
    await advance(20_000);
    expect(rtc.sockets).toHaveLength(2);
  });

});
