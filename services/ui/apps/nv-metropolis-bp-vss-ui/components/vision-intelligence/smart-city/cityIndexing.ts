// SPDX-License-Identifier: MIT
export interface CityIndexingSource { id: string; name: string; status?: string }
export interface CityIndexingSession {
  id: string; requestedAt: string; startedAt: string | null; deadlineAt: string;
  endedAt: string | null; durationSeconds: number; state: string; reason?: string | null;
}
export interface CityIndexingStatus {
  sensorId: string; name: string; mode: 'continuous' | 'on-demand' | 'disabled'; state: string;
  revision: number; configured: boolean; indexingRequested: boolean; generationConnected: boolean;
  generationManaged: boolean; sourcePaused: boolean; session: CityIndexingSession | null;
  cleanup: { status: 'confirmed' | 'failed' | 'not-checked'; message?: string };
  evidence: { status: string; documentCount: number | null; latestTimestamp: string | null; liveFresh: boolean };
  searchScope: { available: boolean; timestampStart: string | null; timestampEnd: string | null };
}
export interface CityIndexingMatch {
  video_name: string; description: string; start_time: string; end_time: string; sensor_id: string;
  screenshot_url?: string; similarity_score?: number;
}
export interface CityCaptureSearch {
  sessionId: string;
  scope: { sourceId: string; sourceName: string; timestampStart: string; timestampEnd: string; executed: true };
  results: CityIndexingMatch[]; excludedResults?: number;
}
