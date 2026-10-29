// SPDX-License-Identifier: MIT
import type { CityEvent, CityMetric, CityRule, CitySnapshot } from './types';
import type { InsightTopic } from './CityMobilityPanel';
import { eventEvidencePending, recentEvents } from './presentation';

export interface OverviewObservation {
  title: string; detail: string; label: string; rule: CityRule | null;
  topic: InsightTopic; event?: CityEvent; tone: 'normal' | 'attention' | 'waiting';
}
const known = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function ruleTopic(rule: CityRule): InsightTopic {
  if (rule.kind === 'queue') return 'queues';
  if (/curb/i.test(rule.name)) return 'curbs';
  if (rule.kind === 'stopped-in-zone') return 'obstructions';
  if (rule.classes.includes('person') && /crossing|pedestrian|corridor/i.test(rule.name)) return 'crossings';
  return 'movements';
}
export function areaLabel(name: string): string {
  return name.split(' · ').filter(part => !/^(person present|stopped vehicle|painted crossing|crossing count|vehicle occupancy|pedestrian corridor)$/i.test(part)).join(' · ');
}
function fromRule(rule: CityRule, metric: CityMetric | undefined, event?: CityEvent): OverviewObservation {
  const topic = ruleTopic(rule);
  const base = { rule, topic, label: 'Observed now', tone: 'normal' as const };
  if (!metric || metric.status === 'unknown') return { ...base, label: 'Evidence needed', tone: 'waiting', title: 'Waiting for a fresh observation', detail: 'Missing observations do not mean the area is empty.' };
  if (event && metric.status === 'active' && !eventEvidencePending(event)) return {
    ...base, event, tone: 'attention', title: rule.kind === 'stopped-in-zone' ? /crossing/i.test(rule.name) ? 'Vehicle stopped in crossing' : 'Vehicle stopped in area' : rule.kind === 'queue' ? 'A vehicle queue is forming' : known(metric.occupancy) && rule.classes.length === 1 && rule.classes[0] === 'person' ? `${metric.occupancy} ${metric.occupancy === 1 ? 'person' : 'people'} ${/waiting|approach/i.test(rule.name) ? 'in waiting area' : /crossing/i.test(rule.name) ? 'in crossing' : 'in area'}` : 'Activity detected in area',
    detail: rule.kind === 'stopped-in-zone' ? topic === 'curbs' ? 'Review its dwell time and curb access.' : /crossing/i.test(rule.name) ? 'Review the stopped time and crossing access.' : 'Review its stopped time and location.' : 'Open the measurement and its camera evidence.',
  };
  if (rule.kind === 'queue' && known(metric.count)) return { ...base, title: `${metric.count} vehicle${metric.count === 1 ? '' : 's'} observed in queue`, detail: 'See how far the approach queue extends.' };
  if (rule.kind === 'line-crossing' && known(metric.totalCrossings)) return { ...base, label: 'Observed in this scope', title: `${metric.totalCrossings} line crossing${metric.totalCrossings === 1 ? '' : 's'} observed`, detail: 'A line count is separate from a completed turning movement.' };
  if (known(metric.occupancy)) {
    const people = rule.classes.length === 1 && rule.classes[0] === 'person';
    const vehicles = rule.classes.length > 0 && rule.classes.every(item => ['vehicle', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'two-wheeler'].includes(item.toLowerCase()));
    const crossing = people && /crossing|pedestrian|corridor/i.test(rule.name) && !/waiting|approach/i.test(rule.name);
    const title = crossing ? `${metric.occupancy} ${metric.occupancy === 1 ? 'person' : 'people'} in crossing` : `${metric.occupancy} ${people ? metric.occupancy === 1 ? 'person' : 'people' : vehicles ? metric.occupancy === 1 ? 'vehicle' : 'vehicles' : metric.occupancy === 1 ? 'object' : 'objects'} detected in area`;
    return { ...base, title, detail: crossing ? 'Measure crossing demand.' : /curb/i.test(rule.name) ? 'See how curb space is used.' : 'Camera-owned observations for this area.' };
  }
  return { ...base, tone: 'waiting', label: 'Monitoring area', title: metric.status === 'active' ? 'Activity detected in this area' : 'No active event observed', detail: 'Open the measurement to inspect its evidence.' };
}
/** Only displayed, fresh, camera-owned evidence can produce the overview finding. */
export function overviewObservation(snapshot: CitySnapshot | null, rules: CityRule[], readySources: readonly string[], focusedRuleId?: string | null): OverviewObservation {
  const waiting: OverviewObservation = { title: 'Waiting for camera analysis', detail: 'Live findings appear when fresh analyzed frames arrive.', label: 'Camera evidence', rule: null, topic: 'crossings', tone: 'waiting' };
  if (snapshot?.analyticsScope?.suppressed) return { ...waiting, title: 'Preparing the next scene', detail: 'Measurements resume after fresh tracking is confirmed.' };
  if (!snapshot || !readySources.length) return waiting;
  const available = rules.filter(rule => rule.enabled && readySources.includes(rule.sourceId));
  const metrics = new Map((snapshot.metrics ?? []).map(metric => [metric.ruleId, metric]));
  const focused = available.find(rule => rule.id === focusedRuleId);
  if (focused) return fromRule(focused, metrics.get(focused.id), snapshot.events?.find(event => event.ruleId === focused.id && event.state === 'active'));
  const active = recentEvents(snapshot.events ?? []).filter(event => event.state === 'active' && !eventEvidencePending(event) && metrics.get(event.ruleId)?.status === 'active');
  const priority = (event: CityEvent) => event.kind === 'stopped-in-zone' ? 0 : event.kind === 'queue' ? 1 : 2;
  active.sort((a, b) => priority(a) - priority(b));
  for (const event of active) { const rule = available.find(item => item.id === event.ruleId); if (rule) return fromRule(rule, metrics.get(rule.id), event); }
  const crossing = available.find(rule => rule.kind === 'occupancy-threshold' && rule.classes.includes('person') && /painted crossing|pedestrian corridor/i.test(rule.name) && metrics.get(rule.id)?.status !== 'unknown' && known(metrics.get(rule.id)?.occupancy));
  if (crossing) return fromRule(crossing, metrics.get(crossing.id));
  const observed = available.find(rule => metrics.has(rule.id) && metrics.get(rule.id)?.status !== 'unknown');
  return observed ? fromRule(observed, metrics.get(observed.id)) : waiting;
}
