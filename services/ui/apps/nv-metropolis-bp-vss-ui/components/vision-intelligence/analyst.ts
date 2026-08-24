// SPDX-License-Identifier: MIT

export type VisionAnalystSourceKind = 'live' | 'replay';

export interface VisionAnalystPlaybackContext {
  /** Wall-clock moment when this playback state was observed in the browser. */
  capturedAt: string;
  /** Current offset for recorded media. Live sources intentionally omit it. */
  currentTimeSeconds?: number;
  durationSeconds?: number;
}

export interface VisionAnalystSource {
  kind: VisionAnalystSourceKind;
  name: string;
  playback?: VisionAnalystPlaybackContext;
  sensorId: string;
  streamId: string;
}

export interface VisionAnalystRequest {
  askedAt: string;
  conversationId: string;
  query: string;
  scope: 'all-sources' | 'selected-source';
  sources: VisionAnalystSource[];
}

export interface VisionAnalystObservedRange {
  endSeconds: number;
  startSeconds: number;
}

export interface VisionAnalystResponse {
  answer: string;
  evidenceTools: string[];
  generatedAt: string;
  grounded: true;
  observedRange?: VisionAnalystObservedRange;
  query: string;
  scope: VisionAnalystRequest['scope'];
  sourceNames: string[];
}

/** Keep internal tool traces useful to the server without exposing them at a tradeshow. */
export function cleanAgentAnswer(value: string): string {
  return value
    .replace(/<agent-think>[\s\S]*?<\/agent-think>/gi, '')
    .replace(/<intermediatestep>[\s\S]*?<\/intermediatestep>/gi, '')
    .replace(/<(?:agent-think|intermediatestep)\b[\s\S]*$/gi, '')
    .replace(/^\s*(?:answer|response)\s*:\s*/i, '')
    .replace(/^\s*\d+(?:\.\d+)?\s*(?:seconds?|s)?\s*[-–]\s*\d+(?:\.\d+)?\s*(?:seconds?|s)\s*[,;:]?\s*/i, '')
    .replace(/\bAt\s+0(?:\.0+)?\s*(?:seconds?|s)?\s*,/gi, 'At the start of the inspected clip,')
    .replace(/\bFrom\s+\d+\.\d+\s*(?:seconds?|s)?\s+(?:to|[-–])\s+\d+\.\d+\s*(?:seconds?|s)?\s*,/gi, 'Later in the inspected clip,')
    .replace(/\bBy\s+\d+\.\d+\s*(?:seconds?|s)?\s*,/gi, 'By the end of the inspected clip,')
    .replace(/\bAt\s+\d+\.\d+\s*(?:seconds?|s)?\s*,/gi, 'During the inspected clip,')
    .trim();
}

const EVIDENCE_TOOL_PATTERN = '(?:video_understanding|lvs_video_understanding|lvs_stream_understanding)';
const FAILED_TOOL_RESULT = /(?:\berror\b|\bexception\b|\bfailed\b|could not|unable to|unavailable|timed?\s*out)/i;

/** Return only local visual tools whose trace contains a non-error result. */
export function extractSuccessfulEvidenceTools(value: string): string[] {
  const tools = new Set<string>();
  const stepPattern = new RegExp(
    `<agent-think-step\\b[^>]*>[\\s\\S]*?Tool:\\s*(${EVIDENCE_TOOL_PATTERN})\\b[\\s\\S]*?Result:\\s*([\\s\\S]*?)<\\/agent-think-step>`,
    'gi'
  );
  for (const match of value.matchAll(stepPattern)) {
    const result = match[2].trim();
    if (result && !FAILED_TOOL_RESULT.test(result)) tools.add(match[1].toLowerCase());
  }
  return [...tools];
}

/** Prefer the precise interval emitted by video_understanding over a broader requested range. */
export function extractObservedRange(value: string): VisionAnalystObservedRange | undefined {
  const intervals: VisionAnalystObservedRange[] = [];
  const stepPattern = new RegExp(
    `<agent-think-step\\b[^>]*>[\\s\\S]*?Tool:\\s*${EVIDENCE_TOOL_PATTERN}\\b[\\s\\S]*?Result:\\s*([\\s\\S]*?)<\\/agent-think-step>`,
    'gi'
  );
  for (const step of value.matchAll(stepPattern)) {
    for (const match of step[1].matchAll(/(\d+(?:\.\d+)?)\s*(?:s\s*)?[-–]\s*(\d+(?:\.\d+)?)\s*(?:s\b)?/gi)) {
      const startSeconds = Number(match[1]);
      const endSeconds = Number(match[2]);
      if (Number.isFinite(startSeconds) && Number.isFinite(endSeconds) && endSeconds >= startSeconds) {
        intervals.push({ startSeconds, endSeconds });
      }
    }
  }
  if (intervals.length) {
    return {
      startSeconds: Math.min(...intervals.map((interval) => interval.startSeconds)),
      endSeconds: Math.max(...intervals.map((interval) => interval.endSeconds)),
    };
  }

  const fallback = value.match(
    /(?:observed|time range|interval)[^\d]{0,24}(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:seconds?|s\b)/i
  );
  if (!fallback) return undefined;

  const startSeconds = Number(fallback[1]);
  const endSeconds = Number(fallback[2]);
  if (!Number.isFinite(startSeconds) || !Number.isFinite(endSeconds) || endSeconds < startSeconds) {
    return undefined;
  }
  return { startSeconds, endSeconds };
}
