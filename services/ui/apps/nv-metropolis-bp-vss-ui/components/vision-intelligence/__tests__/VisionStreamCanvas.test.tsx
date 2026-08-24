// SPDX-License-Identifier: MIT

import { VisionStreamCanvas } from "../VisionStreamCanvas";
import {
  act,
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
  afterEach(() => {
    jest.restoreAllMocks();
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

    render(
      <VisionStreamCanvas
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
});
