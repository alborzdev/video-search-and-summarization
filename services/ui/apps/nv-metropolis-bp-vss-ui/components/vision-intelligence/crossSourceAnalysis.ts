// SPDX-License-Identifier: MIT
import type { VisionAnalystRequest, VisionAnalystSource, VisionAnalystResponse } from './analyst';
import {
  consolidateIncidents,
  incidentVerdict,
  isOperatorRelevantIncident,
  type AnalyticsIncident,
} from './incidentModel';
import { streamDisplayName } from './utils';

export interface CrossSourceIntelligence {
  evidenceEvents: number | null;
  semanticSegments: number | null;
  trackedObservations: number | null;
}

export type CrossSourceIncident = AnalyticsIncident;

export interface CrossSourceEvidence {
  incidents: CrossSourceIncident[];
  intelligenceByStreamId: Record<string, CrossSourceIntelligence>;
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

export function incidentMatchesSource(incident: CrossSourceIncident, source: VisionAnalystSource): boolean {
  const sensor = normalize(incident.sensorId ?? '');
  return Boolean(sensor) && [source.name, source.sensorId, source.streamId]
    .map(normalize)
    .some((candidate) => candidate === sensor || candidate.includes(sensor) || sensor.includes(candidate));
}

export function scoreSource(
  source: VisionAnalystSource,
  evidence: CrossSourceEvidence
): number {
  const intelligence = evidence.intelligenceByStreamId[source.streamId];
  const incidentScore = consolidateIncidents(evidence.incidents).filter((incident) =>
    isOperatorRelevantIncident(incident) && incidentMatchesSource(incident, source)
  ).length;
  return (source.kind === 'live' ? 1_000_000_000 : 0)
    + incidentScore * 10_000_000
    + (intelligence?.evidenceEvents ?? 0) * 1_000_000
    + (intelligence?.trackedObservations ?? 0) * 100
    + (intelligence?.semanticSegments ?? 0);
}

export function rankCrossSources(
  sources: VisionAnalystSource[],
  evidence: CrossSourceEvidence
): VisionAnalystSource[] {
  return [...sources].sort((left, right) => scoreSource(right, evidence) - scoreSource(left, evidence));
}

export function isCrossSourceOverviewQuestion(query: string): boolean {
  return /\b(?:where|which|camera|source|attention|activity|active|risk|safety|alert|event|incident|status|overview)\b/i.test(query);
}

export function summarizeCrossSourceEvidence(
  request: VisionAnalystRequest,
  evidence: CrossSourceEvidence,
  generatedAt = new Date().toISOString()
): VisionAnalystResponse {
  const ranked = rankCrossSources(request.sources, evidence);
  const consolidated = consolidateIncidents(evidence.incidents);
  const summaries = ranked.map((source) => {
    const intelligence = evidence.intelligenceByStreamId[source.streamId];
    const incidents = consolidated.filter((incident) =>
      isOperatorRelevantIncident(incident) && incidentMatchesSource(incident, source)
    );
    const confirmed = incidents.filter((incident) => incidentVerdict(incident) === 'confirmed').length;
    const needsReview = incidents.filter((incident) => ['failed', 'unverified'].includes(incidentVerdict(incident))).length;
    return {
      confirmed,
      events: intelligence?.evidenceEvents ?? 0,
      name: streamDisplayName(source.name),
      needsReview,
      observations: intelligence?.trackedObservations ?? 0,
      source,
    };
  });
  const active = summaries.filter((summary) => summary.confirmed || summary.needsReview || summary.events || summary.observations);
  const leaders = active.slice(0, 3);
  let answer: string;
  if (!leaders.length) {
    answer = `No operator events or tracked observations are currently indexed across the ${request.sources.length} available sources. Open a specific source for direct visual inspection or use Investigate to search indexed video moments.`;
  } else {
    const lead = leaders[0];
    const operatorIncidentCount = leaders.reduce(
      (total, summary) => total + summary.confirmed + summary.needsReview,
      0
    );
    const detail = leaders.map((summary) => {
      const facts = [
        summary.confirmed ? `${summary.confirmed} confirmed ${summary.confirmed === 1 ? 'incident' : 'incidents'}` : '',
        summary.needsReview ? `${summary.needsReview} awaiting review` : '',
        summary.events ? `${summary.events} indexed ${summary.events === 1 ? 'event' : 'events'}` : '',
        summary.observations ? `${summary.observations.toLocaleString()} tracked observations` : '',
      ].filter(Boolean).join(', ');
      return `${summary.name}: ${facts}`;
    }).join('; ');
    answer = operatorIncidentCount
      ? `${lead.name} currently has the strongest local evidence signal. ${detail}. These counts come from indexed analytics on this Thor; open a source to visually inspect the footage.`
      : `No operator-ready incident currently requires attention. ${lead.name} has the strongest searchable activity signal. ${detail}. These are indexed activity counts, not alerts; open a source to visually inspect the footage.`;
  }
  return {
    answer,
    evidenceTools: ['video_analytics', 'source_intelligence'],
    generatedAt,
    grounded: true,
    query: request.query.trim(),
    scope: 'all-sources',
    sourceNames: leaders.map((summary) => summary.source.name),
  };
}
