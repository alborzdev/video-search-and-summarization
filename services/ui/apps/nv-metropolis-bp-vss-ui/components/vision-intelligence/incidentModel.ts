// SPDX-License-Identifier: MIT

export interface AnalyticsIncidentInfo {
  alertCategory?: string;
  description?: string;
  reasoning?: string;
  snapshotUrls?: string;
  verdict?: string;
  verificationResponseStatus?: string;
  videoSource?: string;
}

export interface AnalyticsIncident {
  Id: string;
  end?: string;
  info?: AnalyticsIncidentInfo;
  objectIds?: string[];
  sensorId?: string;
  timestamp: string;
}

export interface ConsolidatedIncident extends AnalyticsIncident {
  candidateCount: number;
  candidateIds: string[];
  candidateVerdicts: IncidentVerdict[];
}

export type IncidentVerdict =
  | "confirmed"
  | "rejected"
  | "failed"
  | "unverified";

export function incidentVerdict(incident: AnalyticsIncident): IncidentVerdict {
  const verdict = (incident.info?.verdict ?? "").toLowerCase();
  if (verdict === "confirmed") return "confirmed";
  if (verdict === "rejected") return "rejected";
  if (verdict.includes("failed")) return "failed";
  return "unverified";
}

export function incidentVerdictLabel(incident: AnalyticsIncident): string {
  const verdict = incidentVerdict(incident);
  if (!isOperatorIncidentCandidate(incident)) {
    return verdict === "failed" ? "Processing failed" : "Processed";
  }
  if (verdict === "confirmed") return "Confirmed";
  if (verdict === "rejected") return "Dismissed";
  if (verdict === "failed") return "Needs review";
  return "Pending review";
}

export function incidentDurationSeconds(
  incident: AnalyticsIncident
): number | null {
  if (!incident.end) return null;
  const duration =
    (Date.parse(incident.end) - Date.parse(incident.timestamp)) / 1_000;
  return Number.isFinite(duration) && duration >= 0 ? duration : null;
}

export function incidentDurationLabel(incident: AnalyticsIncident): string {
  const duration = incidentDurationSeconds(incident);
  if (duration === null) return "Duration unavailable";
  if (duration < 60) return `${Math.max(1, Math.round(duration))} sec`;
  const minutes = Math.floor(duration / 60);
  const seconds = Math.round(duration % 60);
  return seconds ? `${minutes} min ${seconds} sec` : `${minutes} min`;
}

export function incidentTitle(incident: AnalyticsIncident): string {
  const configured =
    incident.info?.alertCategory?.trim() || incident.info?.description?.trim();
  if (configured) return configured;
  const reasoning = incident.info?.reasoning ?? "";
  if (
    /forklift/i.test(reasoning) &&
    /person|pedestrian|worker/i.test(reasoning)
  )
    return "Forklift and pedestrian proximity";
  if (/forklift/i.test(reasoning)) return "Forklift activity observed";
  if (/person|pedestrian|worker/i.test(reasoning))
    return "Person observed in monitored area";
  if (/vehicle|car|truck|bus/i.test(reasoning))
    return "Vehicle activity observed";
  if (!isOperatorIncidentCandidate(incident))
    return "Analytics processing record";
  const verdict = incidentVerdict(incident);
  if (verdict === "confirmed") return "Visual activity confirmed";
  if (verdict === "rejected") return "Candidate dismissed after review";
  if (verdict === "failed") return "Visual candidate needs review";
  return "Visual event candidate";
}

export function isDiagnosticIncident(incident: AnalyticsIncident): boolean {
  const value = [
    incident.Id,
    incident.sensorId,
    incident.info?.alertCategory,
    incident.info?.description,
    incident.info?.reasoning,
    incident.info?.verificationResponseStatus,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return /(?:qualification|diag|probe|ssrf|unprocessableentity|invalid vlm request|vst service unavailable|training room)/.test(
    value
  );
}

function hasText(value: string | undefined): boolean {
  return Boolean(value?.trim());
}

function hasSnapshots(value: string | undefined): boolean {
  if (!value?.trim()) return false;
  try {
    const parsed = JSON.parse(value) as unknown;
    return (
      Array.isArray(parsed) && parsed.some((item) => hasText(String(item)))
    );
  } catch {
    return false;
  }
}

export function hasOperatorIncidentEvidence(
  incident: AnalyticsIncident
): boolean {
  const info = incident.info;
  return Boolean(
    hasText(info?.alertCategory) ||
      hasText(info?.description) ||
      hasText(info?.reasoning) ||
      hasText(info?.videoSource) ||
      hasSnapshots(info?.snapshotUrls)
  );
}

export function isOperatorIncidentCandidate(
  incident: AnalyticsIncident
): boolean {
  return (
    !isDiagnosticIncident(incident) && hasOperatorIncidentEvidence(incident)
  );
}

export function isOperatorRelevantIncident(
  incident: AnalyticsIncident
): boolean {
  return (
    isOperatorIncidentCandidate(incident) &&
    incidentVerdict(incident) !== "rejected"
  );
}

function overlap(left: AnalyticsIncident, right: AnalyticsIncident): boolean {
  if (left.sensorId !== right.sensorId) return false;
  const leftStart = Date.parse(left.timestamp);
  const leftEnd = Date.parse(left.end ?? left.timestamp);
  const rightStart = Date.parse(right.timestamp);
  const rightEnd = Date.parse(right.end ?? right.timestamp);
  if (![leftStart, leftEnd, rightStart, rightEnd].every(Number.isFinite))
    return false;
  return Math.max(leftStart, rightStart) <= Math.min(leftEnd, rightEnd) + 500;
}

function verdictPriority(incident: AnalyticsIncident): number {
  return { confirmed: 4, unverified: 3, failed: 2, rejected: 1 }[
    incidentVerdict(incident)
  ];
}

export function consolidateIncidents(
  incidents: AnalyticsIncident[]
): ConsolidatedIncident[] {
  const sorted = [...incidents].sort(
    (left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp)
  );
  const groups: AnalyticsIncident[][] = [];
  for (const incident of sorted) {
    const group = groups.find((candidate) =>
      candidate.some((member) => overlap(member, incident))
    );
    if (group) group.push(incident);
    else groups.push([incident]);
  }
  return groups.map((group) => {
    const primary = [...group].sort(
      (left, right) => verdictPriority(right) - verdictPriority(left)
    )[0];
    const starts = group
      .map((incident) => Date.parse(incident.timestamp))
      .filter(Number.isFinite);
    const ends = group
      .map((incident) => Date.parse(incident.end ?? incident.timestamp))
      .filter(Number.isFinite);
    return {
      ...primary,
      candidateCount: group.length,
      candidateIds: group.map((incident) => incident.Id),
      candidateVerdicts: group.map(incidentVerdict),
      timestamp: new Date(Math.min(...starts)).toISOString(),
      end: new Date(Math.max(...ends)).toISOString(),
      objectIds: [
        ...new Set(group.flatMap((incident) => incident.objectIds ?? [])),
      ],
    };
  });
}
