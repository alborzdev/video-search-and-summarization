// SPDX-License-Identifier: MIT

import type { VisionStream } from "./types";
import { sourceKind } from "./utils";
import { useCallback, useEffect, useRef, useState } from "react";

export type LiveCaptureStatus = "on" | "off" | "unknown";
interface CaptureOptions {
  visualAnalystAvailable?: boolean | null;
  busy?: boolean;
}

export function useLiveCapture(
  stream: VisionStream,
  { visualAnalystAvailable, busy = false }: CaptureOptions = {}
) {
  const key = `${stream.sensorId}\0${stream.streamId}`;
  const live = sourceKind(stream) === "Live";
  const activeKey = useRef(key);
  activeKey.current = key;
  const mounted = useRef(false);
  const mutation = useRef(false);
  const generation = useRef(0);
  const observed = useRef<LiveCaptureStatus>("unknown");
  const mutationController = useRef<AbortController | null>(null);
  const [state, setState] = useState({
    key,
    capture: "unknown" as LiveCaptureStatus,
    changing: false,
    error: null as string | null,
    readyAt: 0,
  });
  const [now, setNow] = useState(Date.now());

  const apply = useCallback(
    (capture: LiveCaptureStatus) => {
      const readyAt =
        capture === "on" && observed.current !== "on"
          ? Date.now() + 30_000
          : null;
      observed.current = capture;
      setNow(Date.now());
      setState((current) => ({
        ...current,
        key,
        capture,
        readyAt: capture !== "on" ? 0 : readyAt ?? current.readyAt,
      }));
    },
    [key]
  );

  const invalidateCaptureRead = useCallback(() => {
    ++generation.current;
  }, []);

  useEffect(() => {
    mounted.current = true;
    mutation.current = false;
    observed.current = "unknown";
    ++generation.current;
    setState({
      key,
      capture: "unknown",
      changing: false,
      error: null,
      readyAt: 0,
    });
    const controller = new AbortController();
    const read = async () => {
      if (!live || mutation.current) return;
      const token = ++generation.current;
      const current = () =>
        mounted.current &&
        activeKey.current === key &&
        !controller.signal.aborted &&
        !mutation.current &&
        generation.current === token;
      try {
        const response = await fetch(
          `/api/vision/live-capture?streamId=${encodeURIComponent(
            stream.streamId
          )}`,
          { cache: "no-store", signal: controller.signal }
        );
        const payload = await response.json();
        if (!response.ok || !["on", "off"].includes(payload.recordingStatus))
          throw new Error(payload.error || "Capture status is unavailable.");
        if (current()) {
          apply(payload.recordingStatus);
          setState((value) => ({ ...value, error: null }));
        }
      } catch (failure) {
        if (current()) {
          apply("unknown");
          setState((value) => ({
            ...value,
            error:
              failure instanceof Error
                ? failure.message
                : "Capture status is unavailable.",
          }));
        }
      }
    };
    void read();
    const poll = live
      ? window.setInterval(() => void read(), 15_000)
      : undefined;
    return () => {
      mounted.current = false;
      invalidateCaptureRead();
      controller.abort();
      mutationController.current?.abort();
      if (poll !== undefined) window.clearInterval(poll);
    };
  }, [apply, invalidateCaptureRead, key, live, stream.streamId]);

  useEffect(() => {
    if (!state.readyAt) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(tick);
  }, [state.readyAt]);

  const capture = state.key === key ? state.capture : "unknown";
  const changing = state.key === key && state.changing;
  const remainingSeconds =
    capture === "on" ? Math.max(0, Math.ceil((state.readyAt - now) / 1000)) : 0;
  const warming = remainingSeconds > 0;
  const disconnected =
    stream.connectionState === "offline" ||
    stream.connectionState === "removed";
  const canAsk =
    visualAnalystAvailable === true &&
    !busy &&
    (!live || (capture === "on" && !warming && !disconnected && !changing));

  const toggle = useCallback(async () => {
    if (
      !live ||
      busy ||
      mutation.current ||
      changing ||
      capture === "unknown" ||
      (capture === "off" && disconnected)
    )
      return;
    mutation.current = true;
    const token = ++generation.current;
    const controller = new AbortController();
    mutationController.current = controller;
    const current = () =>
      mounted.current &&
      activeKey.current === key &&
      generation.current === token &&
      !controller.signal.aborted;
    setState((value) => ({ ...value, changing: true, error: null }));
    let verified = false;
    try {
      const response = await fetch("/api/vision/live-capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          streamId: stream.streamId,
          action: capture === "on" ? "stop" : "start",
        }),
        signal: controller.signal,
      });
      const payload = await response.json();
      verified = ["on", "off"].includes(payload.recordingStatus);
      if (current() && verified) apply(payload.recordingStatus);
      if (!response.ok)
        throw new Error(payload.error || "Capture could not be updated.");
      if (!verified) throw new Error("Capture status could not be verified.");
    } catch (failure) {
      if (current()) {
        if (!verified) apply("unknown");
        setState((value) => ({
          ...value,
          error:
            failure instanceof Error
              ? failure.message
              : "Capture could not be updated.",
        }));
      }
    } finally {
      if (current()) {
        mutation.current = false;
        setState((value) => ({ ...value, changing: false }));
      }
    }
  }, [
    apply,
    busy,
    capture,
    changing,
    disconnected,
    key,
    live,
    stream.streamId,
  ]);

  return {
    capture,
    changing,
    error: state.key === key ? state.error : null,
    warming,
    remainingSeconds,
    canAsk,
    toggle,
  };
}
