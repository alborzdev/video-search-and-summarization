// SPDX-License-Identifier: MIT
import type { CityEvent, CityMetric, CityRule, CitySource } from './types';

export function sourceName(source: Pick<CitySource, 'name'>): string {
  const names: Record<string, string> = {
    'isaac-intersection-southwest': 'Southwest corner',
    'isaac-intersection-northeast': 'Northeast corner',
  };
  return Object.hasOwn(names, source.name) ? names[source.name] : source.name;
}

export function cameraColor(index: number): string {
  return ['#67d3bd', '#8cbcff', '#cfacf5', '#efc582'][Math.max(0, index) % 4];
}

export function ruleMeasure(rule: CityRule, metric?: CityMetric): string {
  if (!rule.enabled) return 'Disabled';
  if (!metric) return 'Waiting for observations';
  if (metric.status === 'unknown') return rule.kind === 'stopped-in-zone' && metric.evidenceReasons?.includes('stop-observation-pending')
    ? 'Checking evidence' : 'Not enough evidence';
  if (rule.kind === 'line-crossing') return metric.totalCrossings == null ? 'Waiting for observations' : `${metric.totalCrossings} crossing${metric.totalCrossings === 1 ? '' : 's'}`;
  if (['stopped-in-zone', 'dwell', 'wrong-way', 'area-entry'].includes(rule.kind)) {
    if (metric.activeEventCount) return `${metric.activeEventCount} active alert${metric.activeEventCount === 1 ? '' : 's'}`;
    // Area occupancy does not establish a stop, dwell time, or wrong-way movement.
    return metric.occupancy == null ? 'Waiting for observations' : 'No active alerts';
  }
  if (rule.kind === 'queue') return metric.count == null ? 'Waiting for observations' : `${metric.count} slow vehicle${metric.count === 1 ? '' : 's'}`;
  return metric.occupancy == null ? 'Waiting for observations' : `${metric.occupancy} in area`;
}

const EVIDENCE_REASONS: Record<string, string> = {
  'source-stale': 'Camera observations are delayed.',
  'observation-gap': 'A gap interrupted object tracking.',
  'waiting-for-fresh-observation': 'Waiting for a fresh detection.',
  'projection-unavailable': 'Ground position is unavailable.',
  'speed-unavailable': 'Speed is not available yet.',
  'direction-unavailable': 'Movement direction is not available yet.',
  'duration-requalification': 'Checking the required duration again.',
  'clear-hysteresis': 'Confirming that the condition has cleared.',
  'lost-track-membership': 'An object was lost before its exit was confirmed.',
  'lost-track-capacity': 'The rule cannot verify all missing objects.',
  'stop-observation-pending': 'Checking a brief detection gap. Unconfirmed time is excluded.',
};

/** Explain only server-supplied causes; older snapshots keep their generic state. */
export function ruleEvidenceReasons(metric?: Pick<CityMetric, 'status'> & { evidenceReasons?: readonly string[] }): string[] {
  if (metric?.status !== 'unknown' || !Array.isArray(metric.evidenceReasons)) return [];
  return [...new Set(metric.evidenceReasons.filter(reason => typeof reason === 'string' && Object.hasOwn(EVIDENCE_REASONS, reason)).map(reason => EVIDENCE_REASONS[reason]))];
}

export function recentEvents(events: CityEvent[]): CityEvent[] {
  const time = (event: CityEvent) => Date.parse(event.triggeredAt) || 0;
  return [...events].sort((a, b) => time(b) - time(a) || a.id.localeCompare(b.id));
}

/** A retained incident is not proof of its condition during a brief loss. */
export function eventEvidencePending(event: CityEvent): boolean {
  return event.kind === 'stopped-in-zone' && event.state === 'active'
    && (event.stopEvidenceStatus === 'pending' || event.stopEvidenceStatus === 'clearing');
}

export function eventStateLabel(event: CityEvent): string {
  if (eventEvidencePending(event)) return event.stopEvidenceStatus === 'clearing' ? 'Checking clearance' : 'Checking evidence';
  return event.state;
}

export function eventStateDescription(event: CityEvent): string {
  if (eventEvidencePending(event)) return event.stopEvidenceStatus === 'clearing'
    ? 'Fresh observations show movement or an exit. Clearance is being checked. Unconfirmed time is excluded.'
    : 'A brief detection gap is being checked. Unconfirmed time is excluded.';
  return event.state === 'unknown' ? 'Observation is incomplete. Check source health.'
    : event.state === 'cleared' ? 'The event has cleared.' : 'The rule is active.';
}

export function ruleCaption(rule: CityRule): string {
  const names: Record<string, string> = { 'line-crossing': 'Crossing line', 'occupancy-threshold': 'Count area',
    'stopped-in-zone': 'Stopped vehicle', dwell: 'Dwell', queue: 'Queue',
    'wrong-way': 'Direction check', 'area-entry': 'Entry' };
  return Object.hasOwn(names, rule.kind) ? names[rule.kind] : rule.name;
}

/** One visible outline for shared geometry; any active rule keeps it highlighted. */
export function groupRuleGeometry(rules: CityRule[]): { key: string; rules: CityRule[]; caption: string }[] {
  const groups = new Map<string, CityRule[]>();
  for (const rule of rules) {
    const key = JSON.stringify([rule.sourceId, rule.geometry.space, rule.geometry.points, rule.geometry.direction ?? null]);
    const group = groups.get(key) ?? []; group.push(rule); groups.set(key, group);
  }
  return Array.from(groups, ([key, grouped]) => ({ key, rules: grouped, caption: [...new Set(grouped.map(ruleCaption))].join(' · ') }));
}
