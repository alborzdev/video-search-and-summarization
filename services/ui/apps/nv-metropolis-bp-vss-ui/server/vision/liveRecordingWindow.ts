// SPDX-License-Identifier: MIT

import { DEFAULT_LOOKBACK_SECONDS, validLookbackSeconds } from "../../components/vision-intelligence/footageWindow";
import { observedProgress } from "./observedProgress";
export const LIVE_QUESTION_WINDOW_SECONDS = DEFAULT_LOOKBACK_SECONDS;
const RECORDING_EDGE_DELAY_SECONDS = 5;
const MAX_RECORDING_AGE_SECONDS = 30;

export interface LiveRecordingWindowStatus {
  ready: boolean;
  window: { startTime: string; endTime: string } | null;
  remainingSeconds: number | null;
  error?: string;
}

/** Pick a continuous retained interval, rather than guessing from capture uptime. */
export function chooseLiveRecordingWindow(
  timelines: unknown,
  askedAt: string,
  lookbackSeconds = DEFAULT_LOOKBACK_SECONDS,
  advancing = false
): LiveRecordingWindowStatus {
  const askedMs = Date.parse(askedAt);
  const unavailable: LiveRecordingWindowStatus = {
    ready: false, window: null, remainingSeconds: null,
    error: "Recent recorded footage could not be verified. Checking again shortly.",
  };
  if (!Number.isFinite(askedMs) || !Array.isArray(timelines) || !validLookbackSeconds(lookbackSeconds)) return unavailable;
  const intervals: Array<{ start: number; end: number }> = [];
  for (const timeline of timelines) {
    if (!timeline || typeof timeline !== "object" || Array.isArray(timeline)) continue;
    const { startTime, endTime } = timeline;
    if (typeof startTime !== "string" || typeof endTime !== "string") continue;
    const start = Date.parse(startTime);
    const end = Date.parse(endTime);
    if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
      intervals.push({ start, end });
    }
  }
  // Merge only touching/overlapping retained intervals, never a recording gap.
  intervals.sort((left, right) => left.start - right.start);
  const continuous: typeof intervals = [];
  for (const interval of intervals) {
    const previous = continuous[continuous.length - 1];
    if (previous && interval.start <= previous.end) previous.end = Math.max(previous.end, interval.end);
    else continuous.push({ ...interval });
  }
  const latestEnd = Math.max(...continuous.map(({ end }) => end));
  // On a lagging camera, use its observed advancing storage edge and preserve
  // those exact source timestamps. Static old footage never enables this path.
  const referenceMs = advancing ? Math.min(askedMs, latestEnd) : askedMs;
  const safeEdge = referenceMs - RECORDING_EDGE_DELAY_SECONDS * 1_000;
  const recent = continuous
    .map(({ start, end }) => ({ start, end: Math.min(end, safeEdge) }))
    .filter(({ start, end }) => end > start && end >= referenceMs - MAX_RECORDING_AGE_SECONDS * 1_000)
    .sort((left, right) => right.end - left.end);
  const durationMs = lookbackSeconds * 1_000;
  const retained = recent[0];
  if (retained && retained.end - retained.start >= durationMs) {
    return {
      ready: true,
      window: {
        startTime: new Date(retained.end - durationMs).toISOString(),
        endTime: new Date(retained.end).toISOString(),
      },
      remainingSeconds: 0,
    };
  }
  if (!intervals.length) return unavailable;
  if (!recent.length) {
    return { ...unavailable, error: "Recent recording is still catching up. Checking again shortly." };
  }
  return {
    ready: false, window: null,
    remainingSeconds: Math.ceil((durationMs - (recent[0].end - recent[0].start)) / 1_000),
  };
}

export async function readLiveRecordingWindow(
  sensorId: string,
  askedAt = new Date().toISOString(),
  lookbackSeconds = DEFAULT_LOOKBACK_SECONDS
): Promise<LiveRecordingWindowStatus> {
  const base = (process.env.VST_INTERNAL_API_URL || "http://127.0.0.1:30888/vst/api").replace(/\/$/, "");
  try {
    const mediaBase = process.env.EVIDENCE_CLIP_API_URL?.replace(/\/$/, "");
    // A live VIOS timeline can extrapolate past the last saved packet. On the
    // local stack, derive readiness and progress from actual retained media.
    const response = mediaBase
      ? await fetch(`${mediaBase}/recording-window`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sensorId, askedAt }),
          cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15_000),
        })
      : await fetch(`${base}/v1/storage/${encodeURIComponent(sensorId)}/timelines`, {
          cache: "no-store", redirect: "error", signal: AbortSignal.timeout(4_000),
        });
    if (!response.ok) throw new Error("Recording timeline unavailable");
    const timelines = await response.json();
    const latestEnd = Array.isArray(timelines)
      ? Math.max(...timelines.map(row => Date.parse(row?.endTime))) : Number.NaN;
    const advancing = observedProgress(`recording:${base}:${sensorId}`, latestEnd, 30_000);
    return chooseLiveRecordingWindow(timelines, askedAt, lookbackSeconds, advancing);
  } catch {
    return {
      ready: false, window: null, remainingSeconds: null,
      error: "Recent recorded footage could not be verified. Checking again shortly.",
    };
  }
}
