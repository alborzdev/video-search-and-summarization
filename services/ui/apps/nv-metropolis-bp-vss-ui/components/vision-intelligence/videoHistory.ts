// SPDX-License-Identifier: MIT

export type VideoHistoryStatus = "building" | "error" | "ready";

export interface VideoHistoryRecord {
  error?: string;
  events: string[];
  knowledgeId: string;
  lastSynchronizedAt?: string;
  scenario: string;
  sourceId: string;
  sourceKind: "live" | "replay";
  sourceName: string;
  startedAt: string;
  status: VideoHistoryStatus;
  summary?: string;
  timelineEnd?: string;
  timelineStart?: string;
}

export interface VideoHistoryCitation {
  endTime: string;
  label: string;
  startTime: string;
}

export interface VideoHistoryAnswer {
  answer: string;
  citations: VideoHistoryCitation[];
  generatedAt: string;
  knowledgeId: string;
  warning?: string;
}

export interface VideoHistoryStartRequest {
  action: "start";
  events: string[];
  scenario: string;
  source: {
    id: string;
    kind: "live" | "replay";
    name: string;
  };
}

export interface VideoHistoryAskRequest {
  action: "ask";
  messages: Array<{ content: string; role: "assistant" | "user" }>;
  sourceId: string;
}
