// SPDX-License-Identifier: MIT

import type { VisionStreamCanvasProps } from "./VisionStreamCanvas";
import type { DashStream } from "@vss/vios-dash";
import React, { useEffect, useRef, useState } from "react";

const MAX_REPLAY_SECONDS = 600;
const PLAYBACK_DEADLINE_MS = 60_000;

export function DashStreamCanvas({
  stream,
  vstApiUrl,
  onPlaybackContext,
  onPlaybackStatus,
  onPreviewAvailable,
  onFallback,
}: VisionStreamCanvasProps & { onFallback: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const client = useRef<DashStream | null>(null);
  const timeline = useRef<{ start: number; duration: number } | null>(null);
  const offset = useRef(0);
  const seekTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbacks = useRef({
    onPlaybackContext,
    onPlaybackStatus,
    onPreviewAvailable,
    onFallback,
  });
  callbacks.current = {
    onPlaybackContext,
    onPlaybackStatus,
    onPreviewAvailable,
    onFallback,
  };
  const [phase, setPhase] = useState("Packaging recorded video");
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const request = useRef(0);
  const deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const decoded = useRef(false);
  const alive = useRef(false);

  useEffect(() => {
    let disposed = false;
    alive.current = true;
    decoded.current = false;
    offset.current = 0;
    timeline.current = null;
    setPosition(0);
    setDuration(0);
    setReady(false);
    setSeeking(false);
    setPhase("Packaging recorded video");
    const controller = new AbortController();
    let owned: DashStream | null = null;
    deadline.current = setTimeout(() => {
      if (!disposed) callbacks.current.onFallback();
    }, PLAYBACK_DEADLINE_MS);
    const fail = () => {
      if (!disposed) callbacks.current.onFallback();
    };
    callbacks.current.onPlaybackStatus?.("connecting");
    callbacks.current.onPreviewAvailable?.(false);
    void (async () => {
      try {
        if (!vstApiUrl) throw new Error("Video I/O unavailable");
        const response = await fetch(
          `${vstApiUrl}/v1/storage/${encodeURIComponent(
            stream.streamId
          )}/timelines`,
          { signal: controller.signal }
        );
        if (!response.ok) throw new Error("Recording timeline unavailable");
        const ranges = (await response.json()) as Array<{
          startTime: string;
          endTime: string;
        }>;
        if (disposed) return;
        const range = ranges.at(-1),
          start = Date.parse(range?.startTime || ""),
          end = Date.parse(range?.endTime || "");
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start)
          throw new Error("Recording timeline unavailable");
        const seconds = Math.min(MAX_REPLAY_SECONDS, (end - start) / 1000);
        timeline.current = { start, duration: seconds };
        setDuration(seconds);
        const { DashStream } = await import("@vss/vios-dash");
        if (disposed || !video.current) return;
        owned = new DashStream();
        client.current = owned;
        await owned.start({
          // Native session APIs share the UI ingress; the configured VST URL
          // can be a bridge address whose wildcard CORS forbids credentials.
          endpoint: window.location.origin,
          streamId: stream.streamId,
          startTime: new Date(start).toISOString(),
          endTime: new Date(start + seconds * 1000).toISOString(),
          videoElement: video.current,
          onPhase: (value) => {
            if (!disposed) {
              setPhase(
                value === "loading"
                  ? "Packaging recorded video"
                  : value === "buffering"
                  ? "Buffering recorded video"
                  : "Playing recorded video"
              );
              if (value !== "playing")
                callbacks.current.onPlaybackStatus?.("connecting");
              else if (decoded.current)
                callbacks.current.onPlaybackStatus?.("playing");
            }
          },
          onFirstFrame: () => {
            if (!disposed) {
              if (deadline.current) clearTimeout(deadline.current);
              decoded.current = true;
              setPhase("Playing recorded video");
              setReady(true);
              setSeeking(false);
              callbacks.current.onPlaybackStatus?.("playing");
              callbacks.current.onPreviewAvailable?.(true);
            }
          },
          onError: fail,
        });
      } catch (error) {
        if (!disposed) {
          console.warn("DASH replay initialization failed", error);
          fail();
        }
      }
    })();
    return () => {
      disposed = true;
      alive.current = false;
      request.current += 1;
      controller.abort();
      if (deadline.current) clearTimeout(deadline.current);
      if (seekTimer.current) clearTimeout(seekTimer.current);
      client.current = null;
      void owned?.stop();
      callbacks.current.onPreviewAvailable?.(false);
    };
  }, [stream.streamId, vstApiUrl]);

  const seek = (seconds: number) => {
    setPosition(seconds);
    if (seekTimer.current) clearTimeout(seekTimer.current);
    const generation = ++request.current;
    seekTimer.current = setTimeout(() => {
      const active = client.current,
        range = timeline.current;
      if (!active || !range || !alive.current) return;
      offset.current = seconds;
      decoded.current = false;
      if (deadline.current) clearTimeout(deadline.current);
      deadline.current = setTimeout(() => {
        if (alive.current && generation === request.current)
          callbacks.current.onFallback();
      }, PLAYBACK_DEADLINE_MS);
      setPhase("Seeking recorded video");
      setSeeking(true);
      setReady(false);
      callbacks.current.onPlaybackStatus?.("connecting");
      void active
        .seekReplay(new Date(range.start + seconds * 1000).toISOString())
        .then((result) => {
          if (result && alive.current && generation === request.current)
            setSeeking(false);
        })
        .catch(() => {
          if (alive.current && generation === request.current)
            callbacks.current.onFallback();
        });
    }, 250);
  };

  return (
    <div
      className="vi-stream-canvas vi-dash-canvas"
      data-playback-protocol="dash"
      aria-label="DASH recorded playback"
    >
      <video
        ref={video}
        className="vi-stream-video"
        autoPlay
        muted
        playsInline
        aria-label="DASH recorded video"
        style={{ visibility: ready ? "visible" : "hidden" }}
        onPlaying={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(event) => {
          const seconds = Math.min(
            duration,
            offset.current + event.currentTarget.currentTime
          );
          if (!seeking) setPosition(seconds);
          callbacks.current.onPlaybackContext?.({
            capturedAt: new Date().toISOString(),
            currentTimeSeconds: seconds,
            durationSeconds: duration,
          });
        }}
      />
      {(!ready || phase !== "Playing recorded video") && (
        <div className="vi-stream-state">
          <span className="vi-spinner" />
          {phase}
        </div>
      )}
      <div
        className="vi-replay-controls"
        aria-label="DASH recorded video controls"
      >
        <button
          type="button"
          disabled={!ready}
          aria-label={playing ? "Pause recorded video" : "Play recorded video"}
          onClick={() => {
            const element = video.current;
            if (element?.paused)
              void element.play().catch(() => callbacks.current.onFallback());
            else element?.pause();
          }}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <input
          aria-label="Recorded video position"
          type="range"
          min="0"
          max={Math.max(0.1, duration - 0.1)}
          step="0.1"
          value={Math.min(position, Math.max(0.1, duration - 0.1))}
          disabled={!ready || seeking}
          onChange={(event) => seek(Number(event.target.value))}
        />
        <time>
          {position.toFixed(1)} / {duration.toFixed(1)} s
        </time>
      </div>
    </div>
  );
}
