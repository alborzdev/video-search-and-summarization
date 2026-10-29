// SPDX-License-Identifier: MIT
export type DefenseScenario = 'site' | 'drone' | 'vehicle';
export type DefenseMode = 'preview' | 'disconnected';
export type EvidenceKind = 'illustrative' | 'recorded' | 'live';
export interface DefenseEvidence {
  id: string;
  sourceId: string;
  sourceName: string;
  kind: EvidenceKind;
  imageUrl: string | null;
  // Server-issued clip URL only. Illustrations never get a playable video URL.
  clipUrl?: string;
  timeLabel: string;
  mediaSeconds: number | null;
  clockVerified: boolean;
  observation?: string;
}
export interface DefenseFinding {
  id: string;
  title: string;
  location: string;
  evidenceIds: readonly string[];
  limitations: readonly string[];
}
export interface DefenseSnapshot {
  provenance: 'illustrative' | 'disconnected';
  evidence: readonly DefenseEvidence[];
  findings: readonly DefenseFinding[];
}
export interface DefenseReport {
  schemaVersion: 'defense.preview-report.v1';
  provenance: 'illustrative';
  title: string;
  scenario: DefenseScenario;
  createdAt: string;
  observations: string[];
  limitations: string[];
  evidence: DefenseEvidence[];
  analystNotes: string;
}
