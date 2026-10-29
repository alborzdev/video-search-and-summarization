// SPDX-License-Identifier: MIT
import React from 'react';
import type { AnalyticsScope, CitySite } from './types';
import type { MobilityCoverage, MobilityReport } from './mobilityTypes';
import { useMobility } from './useMobility';
import styles from './ScenarioEvidence.module.css';

interface Props {
  site: CitySite;
  scenarioId: string;
  currentScope: AnalyticsScope | null | undefined;
}

type Finding = { primary: string; secondary?: string };
const waiting: Finding = { primary: 'Waiting for camera observations' };
const number = (value: number, digits = 0) => value.toLocaleString(undefined, { maximumFractionDigits: digits });
const count = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 0;
const nonnegative = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;

/** Camera coverage must belong to this run and advance beyond its start. */
function cameraCoverage(report: MobilityReport, site: CitySite, sourceId: string, scope: AnalyticsScope): MobilityCoverage | null {
  if (!site.sources.some(source => source.id === sourceId)) return null;
  const camera = report.coverage.find(item => item.sourceId === sourceId);
  const startMs = Date.parse(scope.startedAt ?? '');
  if (!camera || camera.status !== 'live' || !camera.windowEndNs || !/^\d+$/.test(camera.windowEndNs) || !Number.isFinite(startMs)) return null;
  if (BigInt(camera.windowEndNs) < BigInt(startMs) * BigInt(1_000_000)) return null;
  return camera;
}
function hasIssue(report: MobilityReport, kind: string, id: string) {
  return report.configurationIssues.some(issue => issue.kind === kind && issue.id === id);
}
function atCameraTime(time: string | null | undefined, camera: MobilityCoverage) {
  return typeof time === 'string' && /^\d+$/.test(time) && time === camera.windowEndNs;
}
function plural(value: number, singular: string, pluralForm = `${singular}s`) { return `${number(value)} ${value === 1 ? singular : pluralForm}`; }

/** Uses only measurements from the actual camera run; scripted actor actions are never detections. */
export function scenarioFinding(report: MobilityReport, site: CitySite, scope: AnalyticsScope, scenarioId: string): Finding {
  if (scenarioId === 'turning-demand') {
    const ids = ['northbound-left', 'northbound-through', 'northbound-right'];
    const exits = ['mobility-isaac-west-exit', 'mobility-isaac-north-exit', 'mobility-isaac-east-right-exit'];
    const rows = ids.map(id => report.movements.find(row => row.id === id));
    const configs = ids.map(id => report.config.movements.find(row => row.id === id));
    if (rows.some(row => !row || row.status === 'unavailable' || !count(row.completedCount) || !count(row.incompleteCount)) || configs.some((row, index) => !row || row.entryRuleId !== 'cam_sw-northbound-line' || row.exitRuleId !== exits[index] || hasIssue(report, 'movement', ids[index]))) return waiting;
    const sourceId = rows[0]!.sourceId;
    if (rows.some(row => row!.sourceId !== sourceId) || !cameraCoverage(report, site, sourceId, scope)) return waiting;
    const completed = rows.reduce((sum, row) => sum + row!.completedCount, 0);
    // Interrupted alternatives can overlap for one entry; never add them to the
    // completed turn totals or sum them into a person/vehicle count.
    const incomplete = rows.some(row => row!.incompleteCount > 0);
    const approach = report.lineCounts.find(row => row.ruleId === 'cam_sw-northbound-line' && row.sourceId === sourceId);
    if (completed === 0 && approach && approach.status !== 'unavailable' && count(approach.count) && approach.count > 0) {
      return { primary: plural(approach.count, 'approach line crossing'), secondary: `0 completed turns${incomplete ? ' · Some journeys incomplete' : ''}` };
    }
    return { primary: `${plural(completed, 'completed movement')}`, secondary: `Left ${number(rows[0]!.completedCount)} · Straight ${number(rows[1]!.completedCount)} · Right ${number(rows[2]!.completedCount)}${incomplete ? ' · Some journeys incomplete' : ''}` };
  }
  if (scenarioId === 'queue-recovery') {
    const id = 'northbound-queue'; const row = report.queues.find(item => item.id === id);
    if (!row || row.zoneRuleId !== 'mobility-isaac-northbound-queue' || !report.config.queues.some(item => item.id === id && item.zoneRuleId === row.zoneRuleId) || hasIssue(report, 'queue', id)) return waiting;
    const camera = cameraCoverage(report, site, row.sourceId, scope);
    if (!camera || !atCameraTime(row.asOfSourceTimeNs, camera) || row.status === 'disabled' || row.currentCountsAvailable === false || !count(row.count) || row.status === 'unknown' && row.countBasis !== 'currently-observed') return waiting;
    const partial = row.membershipComplete === false || row.status === 'unknown';
    const extent = !partial && nonnegative(row.observedExtentM) ? `${row.extentIsLowerBound ? 'At least ' : ''}${number(row.observedExtentM, 1)} m observed queue` : undefined;
    return { primary: `${plural(row.count, 'vehicle')} observed in queue`, secondary: partial ? 'Some tracks are incomplete' : extent };
  }
  if (scenarioId === 'pedestrian-service') {
    const id = 'east-crossing-south-north'; const row = report.crossings.find(item => item.id === id);
    if (!row || row.waitingRuleId !== 'mobility-isaac-east-waiting-south' || row.crossingRuleId !== 'mobility-isaac-east-crossing-measurement' || !report.config.crossings.some(item => item.id === id && item.waitingRuleId === row.waitingRuleId && item.crossingRuleId === row.crossingRuleId) || hasIssue(report, 'crossing', id)) return waiting;
    const camera = cameraCoverage(report, site, row.sourceId, scope);
    if (!camera || !atCameraTime(row.asOfSourceTimeNs, camera) || row.status === 'disabled' || row.currentCountsAvailable === false || row.status === 'unknown' && row.countBasis !== 'currently-observed' || !count(row.waitingCount) || !count(row.crossingCount)) return waiting;
    const incomplete = row.membershipComplete === false || (row.incompleteCount ?? 0) > 0;
    // A previous interrupted journey must not hide a person visible now. Keep
    // the interruption caveat alongside the current observation when present.
    const crossingNow = row.crossingCount > 0;
    const primary = crossingNow ? `${plural(row.crossingCount, 'person', 'people')} observed crossing` : `${plural(row.waitingCount, 'person', 'people')} observed in approach`;
    return { primary, secondary: incomplete ? 'Some journeys are incomplete' : crossingNow ? `${plural(row.waitingCount, 'person', 'people')} observed in approach` : `${plural(row.crossingCount, 'person', 'people')} observed crossing` };
  }
  if (scenarioId === 'curb-obstruction') {
    const id = 'north-curbside-access'; const row = report.curbs?.find(item => item.id === id);
    if (!row || row.zoneRuleId !== 'mobility-isaac-north-curbside-lane' || !report.config.curbs?.some(item => item.id === id && item.zoneRuleId === row.zoneRuleId) || hasIssue(report, 'curb', id)) return waiting;
    const camera = cameraCoverage(report, site, row.sourceId, scope);
    if (!camera || !atCameraTime(row.asOfSourceTimeNs, camera) || !count(row.observedOccupancy)) return waiting;
    const partial = row.status === 'unknown' || Boolean(row.occupancyIsLowerBound) || (row.pendingTrackCount ?? 0) > 0 || (row.lostTrackCount ?? 0) > 0;
    const dwell = !partial && nonnegative(row.longestActiveObservedDwellMs) ? `${number(row.longestActiveObservedDwellMs / 1000, 1)} s observed dwell` : undefined;
    return { primary: `${plural(row.observedOccupancy, 'vehicle')} observed at curb`, secondary: partial ? 'Curb occupancy is incomplete' : dwell };
  }
  if (scenarioId === 'crossing-obstruction') {
    const row = report.obstructions.find(item => item.ruleId === 'cam_sw-blocked-crossing');
    if (!row || row.status === 'unavailable' || !cameraCoverage(report, site, row.sourceId, scope) || !count(row.ongoingEpisodes) || !count(row.completedEpisodes) || !count(row.unknownEpisodes) || !nonnegative(row.blockedSeconds)) return waiting;
    if (row.ongoingEpisodes > 0) return { primary: 'Stopped vehicle detected in crossing', secondary: `${number(row.blockedSeconds, 1)} s observed stopped-zone time` };
    if (row.unknownEpisodes > 0) return { primary: 'Stopped-vehicle observation incomplete', secondary: `${number(row.blockedSeconds, 1)} s observed stopped-zone time` };
    if (row.completedEpisodes > 0) return { primary: `${plural(row.completedEpisodes, 'stopped-vehicle episode')} observed`, secondary: `${number(row.blockedSeconds, 1)} s observed stopped-zone time` };
    return { primary: 'Watching the crossing for stopped vehicles' };
  }
  return waiting;
}

export function ScenarioEvidence({ site, scenarioId, currentScope }: Props) {
  const { report, error, receivedAt } = useMobility(site);
  const [, expire] = React.useState(0);
  // If a request and the city stream both stall, invalidate the last finding
  // at the receipt deadline even without a parent re-render.
  React.useEffect(() => {
    const age = receivedAt ? Date.now() - Date.parse(receivedAt) : NaN;
    if (!Number.isFinite(age) || age < -2000 || age > 6000) return;
    const timer = window.setTimeout(() => expire(value => value + 1), Math.max(1, 6001 - age));
    return () => window.clearTimeout(timer);
  }, [receivedAt]);
  const age = receivedAt ? Date.now() - Date.parse(receivedAt) : NaN;
  const scope = report?.analyticsScope;
  const valid = Boolean(site.mode === 'live' && !error && report && Number.isFinite(age) && age >= -2000 && age <= 6000 &&
    currentScope?.kind === 'scenario' && !currentScope.suppressed && currentScope.epoch && currentScope.runId && currentScope.scenarioId === scenarioId &&
    scope?.kind === 'scenario' && !scope.suppressed && scope.epoch === currentScope.epoch && scope.runId === currentScope.runId && scope.scenarioId === scenarioId);
  const finding = valid ? scenarioFinding(report!, site, currentScope!, scenarioId) : waiting;
  return <div className={styles.evidence} aria-label="VSS observes" aria-live="polite"><span className={styles.label}>VSS observes</span><strong>{finding.primary}</strong>{finding.secondary && <span className={styles.secondary}>{finding.secondary}</span>}</div>;
}
