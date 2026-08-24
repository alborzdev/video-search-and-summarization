// SPDX-License-Identifier: MIT

import { evidenceClipEndpoint } from "./evidenceClip";
import type { StreamTimeline, VisionStream } from "./types";
import {
  createLiveWebSocketUrl,
  createPeerId,
  isLiveStream,
  proxyVstPictureUrl,
  sourceKind,
} from "./utils";
import {
  IconAlertCircle,
  IconChevronLeft,
  IconChevronRight,
  IconPlayerPauseFilled,
  IconPlayerPlayFilled,
  IconRefresh,
} from "@tabler/icons-react";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type PlaybackStatus = "idle" | "connecting" | "playing" | "poster" | "error";

interface VisionStreamCanvasProps {
  className?: string;
  eager?: boolean;
  evidenceEvents?: ReplayEvidenceEvent[];
  liveSnapshotEnabled?: boolean;
  onPlaybackContext?: (context: {
    capturedAt: string;
    currentTimeSeconds?: number;
    durationSeconds?: number;
  }) => void;
  showStatus?: boolean;
  showReplayControls?: boolean;
  stream: VisionStream;
  vstApiUrl?: string | null;
  observedRange?: { endSeconds: number; startSeconds: number };
}

export interface ReplayEvidenceEvent {
  endTime?: string;
  id: string;
  label: string;
  startTime: string;
}

interface SignalingMessage {
  apiKey?: string;
  data?: Record<string, unknown> | unknown[];
}

function signalingError(data: Record<string, unknown>): {
  code: string;
  message: string;
} {
  return {
    code:
      typeof data.error_code === "string"
        ? data.error_code
        : typeof data.errorCode === "string"
        ? data.errorCode
        : "",
    message:
      typeof data.error_message === "string"
        ? data.error_message
        : typeof data.errorMessage === "string"
        ? data.errorMessage
        : "",
  };
}

function chooseSnapshotTime(timelines: StreamTimeline[]): string | null {
  const timeline = timelines.at(-1);
  if (!timeline) return null;
  const start = Date.parse(timeline.startTime);
  const end = Date.parse(timeline.endTime);
  if (!Number.isFinite(start) || !Number.isFinite(end))
    return timeline.startTime;
  return new Date(
    start + Math.min(10_000, Math.max(1_000, (end - start) / 2))
  ).toISOString();
}

export function VisionStreamCanvas({
  className = "",
  eager = true,
  evidenceEvents = [],
  liveSnapshotEnabled = true,
  onPlaybackContext,
  showStatus = true,
  showReplayControls = false,
  stream,
  vstApiUrl,
  observedRange,
}: VisionStreamCanvasProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const posterUrlRef = useRef<string | null>(null);
  const [status, setStatus] = useState<PlaybackStatus>(
    eager ? "connecting" : "idle"
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [posterUrl, setPosterUrl] = useState<string | null>(null);
  const [playRequested, setPlayRequested] = useState(eager);
  const [retryKey, setRetryKey] = useState(0);
  const [replayTimeline, setReplayTimeline] = useState<StreamTimeline | null>(
    null
  );
  const [replayTime, setReplayTime] = useState(0);
  const [replayDuration, setReplayDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const initialEventApplied = useRef(false);
  const autoRescanAttempted = useRef<string | null>(null);
  const liveSource = useMemo(() => isLiveStream(stream), [stream]);
  const eventOffsets = useMemo(() => {
    if (!replayTimeline) return [];
    const timelineStart = Date.parse(replayTimeline.startTime);
    if (!Number.isFinite(timelineStart)) return [];
    return evidenceEvents
      .map((event) => ({
        ...event,
        offsetSeconds: (Date.parse(event.startTime) - timelineStart) / 1_000,
      }))
      .filter(
        (event) =>
          Number.isFinite(event.offsetSeconds) && event.offsetSeconds >= 0
      )
      .sort((left, right) => left.offsetSeconds - right.offsetSeconds);
  }, [evidenceEvents, replayTimeline]);

  useEffect(() => {
    initialEventApplied.current = false;
    autoRescanAttempted.current = null;
    setReplayTimeline(null);
    setReplayTime(0);
    setReplayDuration(0);
  }, [stream.streamId]);

  const formatReplayTime = (seconds: number) => {
    const whole = Math.max(0, Math.round(seconds));
    return `${Math.floor(whole / 60)}:${(whole % 60)
      .toString()
      .padStart(2, "0")}`;
  };

  const seekReplay = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    const duration =
      replayDuration || (Number.isFinite(video.duration) ? video.duration : 0);
    video.currentTime = Math.min(duration || seconds, Math.max(0, seconds));
    setReplayTime(video.currentTime);
  }, [replayDuration]);

  useEffect(() => {
    if (
      !showReplayControls ||
      initialEventApplied.current ||
      !eventOffsets.length
    )
      return;
    const video = videoRef.current;
    if (!video) return;
    initialEventApplied.current = true;
    seekReplay(Math.max(0, eventOffsets[0].offsetSeconds - 2));
  }, [eventOffsets, seekReplay, showReplayControls]);

  useEffect(() => {
    posterUrlRef.current = posterUrl;
  }, [posterUrl]);

  useEffect(() => {
    if (!onPlaybackContext) return;
    const publish = () => {
      const video = videoRef.current;
      const currentTimeSeconds =
        video && Number.isFinite(video.currentTime)
          ? video.currentTime
          : undefined;
      const durationSeconds =
        video && Number.isFinite(video.duration) ? video.duration : undefined;
      onPlaybackContext({
        capturedAt: new Date().toISOString(),
        ...(liveSource ? {} : { currentTimeSeconds, durationSeconds }),
      });
    };
    publish();
    const interval = window.setInterval(publish, 1_000);
    return () => window.clearInterval(interval);
  }, [liveSource, onPlaybackContext, stream.streamId]);

  useEffect(() => {
    if (!vstApiUrl) return;
    let disposed = false;
    let objectUrl: string | null = null;

    const loadPoster = async () => {
      try {
        const timelinesResponse = await fetch(
          `${vstApiUrl}/v1/storage/${encodeURIComponent(
            stream.streamId
          )}/timelines`
        );
        let response: Response | null = null;
        if (timelinesResponse.ok) {
          const timelines =
            (await timelinesResponse.json()) as StreamTimeline[];
          const startTime = chooseSnapshotTime(timelines);
          if (startTime) {
            response = await fetch(
              proxyVstPictureUrl(
                `${vstApiUrl}/v1/storage/stream/${encodeURIComponent(
                  stream.streamId
                )}/picture?startTime=${encodeURIComponent(
                  startTime
                )}&width=1280&height=720`
              )
            );
          }
        }

        // A retained frame is the most reliable poster for a paused RTSP
        // source. Ask the live endpoint only when no archived frame exists;
        // otherwise VST emits a noisy 500 for every paused camera card.
        if ((!response || !response.ok) && liveSource && liveSnapshotEnabled) {
          response = await fetch(
            proxyVstPictureUrl(
              `${vstApiUrl}/v1/live/stream/${encodeURIComponent(
                stream.streamId
              )}/picture?width=1280&height=720`
            ),
            { headers: { streamId: stream.streamId } }
          );
        }

        if (!response?.ok) return;
        const blob = await response.blob();
        if (!blob.type.startsWith("image/")) return;
        objectUrl = URL.createObjectURL(blob);
        if (!disposed) setPosterUrl(objectUrl);
      } catch {
        // Playback can still succeed even when a poster is unavailable.
      }
    };

    void loadPoster();
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [liveSnapshotEnabled, liveSource, stream.streamId, vstApiUrl]);

  useEffect(() => {
    if (!playRequested || !stream.streamId || !vstApiUrl || !liveSource) return;

    const videoElement = videoRef.current;
    let disposed = false;
    let peerConnection: RTCPeerConnection | null = null;
    let mediaSessionId: string | null = null;
    let websocket: WebSocket | null = null;
    let retryTimer: number | null = null;
    const peerId = createPeerId();
    const pendingCandidates: RTCIceCandidateInit[] = [];
    const fallbackStream = new MediaStream();

    setStatus("connecting");
    setErrorMessage("");

    const fail = (message: string) => {
      if (disposed) return;
      setErrorMessage(message);
      setStatus(posterUrlRef.current ? "poster" : "error");
    };

    const send = (apiKey: string, data: Record<string, unknown> = {}) => {
      if (websocket?.readyState !== WebSocket.OPEN) return;
      websocket.send(JSON.stringify({ apiKey, peerId, data }));
    };

    const addRemoteCandidate = async (candidate: RTCIceCandidateInit) => {
      if (!peerConnection?.remoteDescription) {
        pendingCandidates.push(candidate);
        return;
      }
      try {
        await peerConnection.addIceCandidate(candidate);
      } catch {
        fail("The video connection could not exchange network candidates.");
      }
    };

    const startPeerConnection = async (iceServers: RTCIceServer[]) => {
      if (disposed || peerConnection) return;
      const pc = new RTCPeerConnection({ iceServers });
      peerConnection = pc;
      pc.addTransceiver("audio", { direction: "recvonly" });
      pc.addTransceiver("video", { direction: "recvonly" });

      pc.ontrack = (event) => {
        const video = videoElement;
        if (!video) return;
        const remoteStream = event.streams[0];
        if (remoteStream) {
          video.srcObject = remoteStream;
        } else {
          fallbackStream.addTrack(event.track);
          video.srcObject = fallbackStream;
        }
        void video.play().catch(() => {
          video.muted = true;
          void video.play();
        });
      };

      pc.onicecandidate = (event) => {
        if (!event.candidate) return;
        send("api/v1/live/iceCandidate", {
          candidate: event.candidate.toJSON(),
          peerId,
        });
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") setStatus("playing");
        if (
          pc.connectionState === "failed" ||
          pc.connectionState === "disconnected"
        ) {
          fail("Live playback was interrupted.");
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send("api/v1/live/stream/start", {
        clientIpAddr: null,
        options: { quality: "auto", rtptransport: "udp", timeout: 60 },
        peerId,
        sessionDescription: pc.localDescription,
        streamId: stream.streamId,
      });
    };

    try {
      websocket = new WebSocket(
        createLiveWebSocketUrl(vstApiUrl, stream.streamId, peerId)
      );
    } catch {
      fail("The video endpoint is not configured correctly.");
      return;
    }

    websocket.onopen = () => send("api/v1/live/iceServers", { peerId });
    websocket.onerror = () => fail("Could not connect to the video service.");
    websocket.onmessage = (event) => {
      void (async () => {
        let message: SignalingMessage;
        try {
          message = JSON.parse(String(event.data)) as SignalingMessage;
        } catch {
          return;
        }
        const data = message.data ?? {};

        if (message.apiKey === "api/v1/live/iceServers") {
          const record = Array.isArray(data) ? {} : data;
          const iceServers = Array.isArray(record.iceServers)
            ? (record.iceServers as RTCIceServer[])
            : [];
          try {
            await startPeerConnection(iceServers);
          } catch {
            fail("Could not initialize video playback.");
          }
          return;
        }

        if (message.apiKey === "api/v1/live/setAnswer") {
          if (!peerConnection || Array.isArray(data)) return;
          mediaSessionId =
            typeof data.mediaSessionId === "string"
              ? data.mediaSessionId
              : null;
          if (typeof data.sdp !== "string" || typeof data.type !== "string") {
            const signalingFailure = signalingError(data);
            if (
              signalingFailure.code === "CameraNotFoundError" &&
              autoRescanAttempted.current !== stream.streamId
            ) {
              autoRescanAttempted.current = stream.streamId;
              setErrorMessage(
                "This camera was offline when video services started. Retrying its connection…"
              );
              setStatus("connecting");
              try {
                await fetch(`${vstApiUrl}/v1/sensor/scan`, { method: "POST" });
              } catch {
                // The retry below can still succeed if another service restored the sensor.
              }
              if (!disposed) {
                retryTimer = window.setTimeout(
                  () => setRetryKey((value) => value + 1),
                  1_200
                );
              }
              return;
            }
            fail(
              signalingFailure.code === "CameraNotFoundError"
                ? "The camera is still reconnecting. Its indexed history remains searchable."
                : signalingFailure.message ||
                    "The video service could not start this camera."
            );
            return;
          }
          try {
            await peerConnection.setRemoteDescription({
              sdp: data.sdp,
              type: data.type as RTCSdpType,
            });
            for (const candidate of pendingCandidates.splice(0)) {
              await peerConnection.addIceCandidate(candidate);
            }
          } catch {
            fail("The video answer could not be applied.");
          }
          return;
        }

        if (message.apiKey === "api/v1/live/iceCandidate") {
          const candidates = Array.isArray(data) ? data : Object.values(data);
          for (const candidate of candidates) {
            if (
              candidate &&
              typeof candidate === "object" &&
              "candidate" in candidate
            ) {
              await addRemoteCandidate(candidate as RTCIceCandidateInit);
            }
          }
        }
      })();
    };

    return () => {
      disposed = true;
      if (websocket?.readyState === WebSocket.OPEN && mediaSessionId) {
        send("api/v1/live/stream/stop", { mediaSessionId, peerId });
      }
      websocket?.close();
      peerConnection?.close();
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      if (videoElement) videoElement.srcObject = null;
    };
  }, [liveSource, playRequested, retryKey, stream.streamId, vstApiUrl]);

  useEffect(() => {
    if (!playRequested || !stream.streamId || !vstApiUrl || liveSource) return;
    const controller = new AbortController();
    const videoElement = videoRef.current;

    const playReplay = async () => {
      try {
        setStatus("connecting");
        const timelineResponse = await fetch(
          `${vstApiUrl}/v1/storage/${encodeURIComponent(
            stream.streamId
          )}/timelines`,
          { signal: controller.signal }
        );
        if (!timelineResponse.ok)
          throw new Error("Recording timeline is unavailable.");
        const timelines = (await timelineResponse.json()) as StreamTimeline[];
        const timeline = timelines.at(-1);
        if (!timeline) throw new Error("This source has no recorded timeline.");
        setReplayTimeline(timeline);
        const timelineDuration =
          (Date.parse(timeline.endTime) - Date.parse(timeline.startTime)) /
          1_000;
        if (Number.isFinite(timelineDuration) && timelineDuration > 0)
          setReplayDuration(timelineDuration);

        const videoResponse = await fetch(
          evidenceClipEndpoint(
            stream.streamId,
            timeline.startTime,
            timeline.endTime
          ),
          { signal: controller.signal }
        );
        if (!videoResponse.ok) throw new Error("Replay could not be prepared.");
        const data = (await videoResponse.json()) as { videoUrl?: string };
        if (!data.videoUrl) throw new Error("Replay URL was not returned.");

        const apiOrigin = new URL(vstApiUrl).origin;
        const returnedUrl = new URL(data.videoUrl, apiOrigin);
        const playableUrl = `${apiOrigin}${returnedUrl.pathname}${returnedUrl.search}`;
        const video = videoRef.current;
        if (!video) return;
        video.src = playableUrl;
        video.loop = true;
        await video.play();
      } catch (error) {
        if (controller.signal.aborted) return;
        setErrorMessage(
          error instanceof Error ? error.message : "Replay is unavailable."
        );
        setStatus(posterUrlRef.current ? "poster" : "error");
      }
    };

    void playReplay();
    return () => {
      controller.abort();
      if (videoElement) {
        videoElement.pause();
        videoElement.removeAttribute("src");
        videoElement.load();
      }
    };
  }, [liveSource, playRequested, stream.streamId, vstApiUrl]);

  return (
    <div
      className={`vi-stream-canvas ${className}`}
      data-playback-status={status}
    >
      {posterUrl && (
        <img
          className="vi-stream-poster"
          src={posterUrl}
          alt=""
          aria-hidden="true"
        />
      )}
      <video
        ref={videoRef}
        className="vi-stream-video"
        autoPlay
        muted
        playsInline
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          if (Number.isFinite(video.duration))
            setReplayDuration(video.duration);
          if (
            showReplayControls &&
            !initialEventApplied.current &&
            eventOffsets.length
          ) {
            initialEventApplied.current = true;
            seekReplay(Math.max(0, eventOffsets[0].offsetSeconds - 2));
          }
        }}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
        onPlaying={() => {
          setStatus("playing");
          setIsPlaying(true);
        }}
        onTimeUpdate={(event) => setReplayTime(event.currentTarget.currentTime)}
      />

      {showReplayControls && !liveSource && playRequested && (
        <div
          className="vi-replay-controls"
          aria-label="Recorded video controls"
        >
          <button
            type="button"
            aria-label={
              isPlaying ? "Pause recorded video" : "Play recorded video"
            }
            onClick={() => {
              const video = videoRef.current;
              if (!video) return;
              if (video.paused) void video.play();
              else video.pause();
            }}
          >
            {isPlaying ? (
              <IconPlayerPauseFilled size={16} />
            ) : (
              <IconPlayerPlayFilled size={16} />
            )}
          </button>
          <button
            type="button"
            aria-label="Previous verified event"
            disabled={!eventOffsets.length}
            onClick={() => {
              const previous =
                [...eventOffsets]
                  .reverse()
                  .find((event) => event.offsetSeconds < replayTime - 3) ??
                eventOffsets[0];
              if (previous) seekReplay(Math.max(0, previous.offsetSeconds - 2));
            }}
          >
            <IconChevronLeft size={17} />
          </button>
          <div className="vi-replay-timeline">
            <input
              aria-label="Recorded video position"
              type="range"
              min="0"
              max={Math.max(1, replayDuration)}
              step="0.1"
              value={Math.min(replayTime, Math.max(1, replayDuration))}
              onChange={(event) => seekReplay(Number(event.target.value))}
            />
            {observedRange && replayDuration > 0 && (
              <span
                className="vi-replay-observed-range"
                aria-label={`Analyst observed ${formatReplayTime(
                  observedRange.startSeconds
                )} to ${formatReplayTime(observedRange.endSeconds)}`}
                style={{
                  left: `${Math.min(
                    100,
                    (observedRange.startSeconds / replayDuration) * 100
                  )}%`,
                  width: `${Math.max(
                    0.8,
                    ((observedRange.endSeconds - observedRange.startSeconds) /
                      replayDuration) *
                      100
                  )}%`,
                }}
              />
            )}
            {eventOffsets.map((event) => (
              <button
                className="vi-replay-event-marker"
                key={event.id}
                type="button"
                aria-label={`Jump to verified event: ${event.label}`}
                title={event.label}
                style={{
                  left: `${Math.min(
                    100,
                    (event.offsetSeconds / Math.max(1, replayDuration)) * 100
                  )}%`,
                }}
                onClick={() => seekReplay(Math.max(0, event.offsetSeconds - 2))}
              />
            ))}
          </div>
          <time>
            {formatReplayTime(replayTime)} / {formatReplayTime(replayDuration)}
          </time>
          <button
            type="button"
            aria-label="Next verified event"
            disabled={!eventOffsets.length}
            onClick={() => {
              const next =
                eventOffsets.find(
                  (event) => event.offsetSeconds > replayTime + 3
                ) ?? eventOffsets.at(-1);
              if (next) seekReplay(Math.max(0, next.offsetSeconds - 2));
            }}
          >
            <IconChevronRight size={17} />
          </button>
        </div>
      )}

      {!playRequested && (
        <button
          className="vi-stream-play"
          type="button"
          onClick={() => setPlayRequested(true)}
          aria-label={`Play ${stream.name}`}
        >
          <IconPlayerPlayFilled size={20} />
        </button>
      )}

      {showStatus && status === "connecting" && (
        <div className="vi-stream-state">
          <span className="vi-spinner" />
          {errorMessage ||
            `Connecting to ${sourceKind(stream).toLowerCase()} video`}
        </div>
      )}

      {showStatus && status === "error" && (
        <div className="vi-stream-state vi-stream-state--error">
          <IconAlertCircle size={19} />
          <span>{errorMessage || "Video is unavailable."}</span>
          <button
            type="button"
            onClick={() => {
              setErrorMessage("");
              setStatus("connecting");
              if (liveSource && vstApiUrl) {
                void fetch(`${vstApiUrl}/v1/sensor/scan`, {
                  method: "POST",
                }).finally(() => setRetryKey((value) => value + 1));
                return;
              }
              setPlayRequested(false);
              window.setTimeout(() => setPlayRequested(true), 0);
            }}
          >
            <IconRefresh size={17} />
            Retry
          </button>
        </div>
      )}

      {showStatus && status === "poster" && (
        <div className="vi-stream-state vi-stream-state--poster">
          <span>Showing the latest available frame</span>
          <button
            type="button"
            onClick={() => {
              setPlayRequested(false);
              window.setTimeout(() => setPlayRequested(true), 0);
            }}
          >
            <IconRefresh size={17} />
            Reconnect
          </button>
        </div>
      )}
    </div>
  );
}
