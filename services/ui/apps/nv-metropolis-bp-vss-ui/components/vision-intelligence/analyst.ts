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
  /** Recent live footage to inspect, in seconds; omitted uses the 1-second default. */
  lookbackSeconds?: number;
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
  observedWindow?: { startTime: string; endTime: string };
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
