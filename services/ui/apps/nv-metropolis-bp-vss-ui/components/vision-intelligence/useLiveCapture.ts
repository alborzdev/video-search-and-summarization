// SPDX-License-Identifier: MIT

import type { VisionStream } from "./types";
import { sourceKind } from "./utils";
import { DEFAULT_LOOKBACK_SECONDS, validLookbackSeconds } from "./footageWindow";
import { useCallback, useEffect, useRef, useState } from "react";

export type LiveCaptureStatus = "on" | "off" | "unknown";
interface CaptureOptions {
  visualAnalystAvailable?: boolean | null;
  busy?: boolean;
  lookbackSeconds?: number;
}
interface RecordingReadiness {
  questionReady?: unknown;
  questionBlockReason?: unknown;
  remainingSeconds?: unknown;
  questionReadinessError?: unknown;
}

export function useLiveCapture(
  stream: VisionStream,
  { visualAnalystAvailable, busy = false, lookbackSeconds = DEFAULT_LOOKBACK_SECONDS }: CaptureOptions = {}
) {
  const seconds = validLookbackSeconds(lookbackSeconds) ? lookbackSeconds : DEFAULT_LOOKBACK_SECONDS;
  const durationQuery = seconds === DEFAULT_LOOKBACK_SECONDS ? "" : `&lookbackSeconds=${seconds}`;
  const key = `${stream.sensorId}\0${stream.streamId}\0${seconds}`;
  const live = sourceKind(stream) === "Live";
  const activeKey = useRef(key);
  activeKey.current = key;
  const mounted = useRef(false);
  const mutation = useRef(false);
  const generation = useRef(0);
  const mutationController = useRef<AbortController | null>(null);
  const [state, setState] = useState({
    key,
    capture: "unknown" as LiveCaptureStatus,
    changing: false,
    error: null as string | null,
    questionBlockReason: null as string | null,
    questionReady: false,
    remainingSeconds: null as number | null,
    readinessError: null as string | null,
  });

  const apply = useCallback(
    (capture: LiveCaptureStatus, readiness: RecordingReadiness = {}) => {
      setState((current) => ({
        ...current,
        key,
        capture,
        questionBlockReason: typeof readiness.questionBlockReason === "string" ? readiness.questionBlockReason : null,
        questionReady: capture === "on" && readiness.questionReady === true,
        remainingSeconds: capture === "on" && typeof readiness.remainingSeconds === "number" &&
          Number.isFinite(readiness.remainingSeconds) && readiness.remainingSeconds >= 0
          ? readiness.remainingSeconds : null,
        readinessError: capture === "on" && typeof readiness.questionReadinessError === "string"
          ? readiness.questionReadinessError : null,
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
    ++generation.current;
    setState({
      key,
      capture: "unknown",
      changing: false,
      error: null,
      questionBlockReason: null,
      questionReady: false,
      remainingSeconds: null,
      readinessError: null,
    });
    const controller = new AbortController();
    let reading = false;
    const read = async () => {
      if (!live || mutation.current || reading) return;
      reading = true;
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
          )}${durationQuery}`,
          { cache: "no-store", signal: controller.signal }
        );
        const payload = await response.json();
        if (!response.ok || !["on", "off"].includes(payload.recordingStatus))
          throw new Error(payload.error || "Capture status is unavailable.");
        if (current()) {
          apply(payload.recordingStatus, payload);
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
      } finally {
        reading = false;
      }
    };
    void read();
    const poll = live
      ? window.setInterval(() => void read(), 3_000)
      : undefined;
    return () => {
      mounted.current = false;
      invalidateCaptureRead();
      controller.abort();
      mutationController.current?.abort();
      if (poll !== undefined) window.clearInterval(poll);
    };
  }, [apply, durationQuery, invalidateCaptureRead, key, live, stream.streamId]);

  const capture = state.key === key ? state.capture : "unknown";
  const changing = state.key === key && state.changing;
  const remainingSeconds = state.key === key ? state.remainingSeconds : null;
  const warming = capture === "on" && !state.questionReady;
  const removed = stream.connectionState === "removed";
  const canAsk =
    visualAnalystAvailable === true &&
    !busy &&
    !(state.key === key && state.questionBlockReason) &&
    // A fresh, continuous recorded interval is the authority for questions.
    // VIOS sensor discovery can lag its independently running recorder after
    // the RTSP publisher reconnects; that must not block verified footage.
    (!live || (capture === "on" && !warming && stream.connectionState !== "removed" && !changing));

  const toggle = useCallback(async () => {
    if (
      !live ||
      busy ||
      mutation.current ||
      changing ||
      capture === "unknown" ||
      // Discovery may still report CameraNotFound after the publisher has
      // recovered. Let an explicit start reach the server for verification.
      (capture === "off" && removed)
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
          ...(seconds !== DEFAULT_LOOKBACK_SECONDS ? { lookbackSeconds: seconds } : {}),
        }),
        signal: controller.signal,
      });
      const payload = await response.json();
      verified = ["on", "off"].includes(payload.recordingStatus);
      if (current() && verified) apply(payload.recordingStatus, payload);
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
    removed,
    key,
    live,
    seconds,
    stream.streamId,
  ]);

  return {
    capture,
    changing,
    error: state.key === key ? state.error : null,
    warming,
    remainingSeconds,
    readinessError: state.key === key ? state.readinessError : null,
    questionBlockReason: state.key === key ? state.questionBlockReason : null,
    canAsk,
    toggle,
  };
}
