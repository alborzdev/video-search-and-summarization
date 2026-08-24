// SPDX-License-Identifier: MIT

import type { EvidenceAnalysisResponse } from "./evidenceAnalysis";

export type InvestigationSeverity = "critical" | "high" | "medium" | "low";
export type InvestigationDisposition =
  | "dismissed"
  | "open"
  | "resolved"
  | "under_review";

export interface InvestigationEvidence {
  client_id: string;
  end_time: string;
  image_url: string;
  match_type: string;
  media_status?: "retained" | "source_retention";
  sensor_id: string;
  source_name: string;
  start_time: string;
  title: string;
  video_url?: string;
}

export interface InvestigationCreateRequest {
  analysis: EvidenceAnalysisResponse;
  disposition: InvestigationDisposition;
  evidence: InvestigationEvidence[];
  notes: string;
  query: string;
  severity: InvestigationSeverity;
  title: string;
}

export interface InvestigationRecord extends InvestigationCreateRequest {
  created_at: string;
  id: string;
  report_url: string;
}
