// SPDX-License-Identifier: MIT

export interface EvidenceAnalysisClipRequest {
  client_id: string;
  end_time: string;
  match_type: string;
  search_description: string;
  sensor_id: string;
  source_name: string;
  start_time: string;
}

export interface EvidenceAnalysisRequest {
  evidence: EvidenceAnalysisClipRequest[];
  query: string;
  question?: string;
}

export interface EvidenceAnalysisClaim {
  evidence_ids: string[];
  text: string;
}

export interface EvidenceAnalysisTimelineEntry {
  end_time: string;
  evidence_id: string;
  label: string;
  source_name: string;
  start_time: string;
}

export interface EvidenceVisualInspection {
  client_id: string;
  end_time: string;
  evidence_id: string;
  inspection_source:
    | "retained_cosmos_caption"
    | "fresh_cosmos_inspection";
  match_type: string;
  observation: string;
  source_name: string;
  start_time: string;
}

export interface EvidenceAnalysisResponse {
  evidence: EvidenceVisualInspection[];
  interpretations: EvidenceAnalysisClaim[];
  observations: EvidenceAnalysisClaim[];
  query: string;
  question: string;
  status: "complete" | "degraded";
  suggested_questions: string[];
  summary: string;
  timeline: EvidenceAnalysisTimelineEntry[];
  warning?: string | null;
}
