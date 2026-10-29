// SPDX-License-Identifier: MIT
import React, { useEffect, useState } from 'react';
import type { AnalyticsScope, CitySite } from './types';
import { cityRequest } from './useCity';
import styles from './ShowcaseEvidence.module.css';
import { ScenarioVlmObservation } from './ScenarioVlmObservation';
import { sourceName } from './presentation';

export interface ShowcaseMeasurement {
  ruleId: string; sourceId: string; sessionId: string; name: string;
  status: 'waiting' | 'unknown' | 'occupied' | 'clear'; count: number | null; peakCount: number;
  occupiedSeconds: number; continuousSeconds: number; hasGaps: boolean;
  asOfSourceTimeNs: string; savedEventIds: string[];
}
interface Report { siteId: string; mode: string; analyticsScope: AnalyticsScope; measurements: ShowcaseMeasurement[] }
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0;
export function validShowcaseMeasurement(value: unknown): value is ShowcaseMeasurement {
  if (!value || typeof value !== 'object') return false;
  const row = value as ShowcaseMeasurement;
  return typeof row.ruleId === 'string' && typeof row.sourceId === 'string' && typeof row.sessionId === 'string' &&
    ['waiting', 'unknown', 'occupied', 'clear'].includes(row.status) && (row.count === null || finite(row.count) && Number.isInteger(row.count)) &&
    finite(row.peakCount) && Number.isInteger(row.peakCount) && finite(row.occupiedSeconds) && finite(row.continuousSeconds) &&
    typeof row.hasGaps === 'boolean' && typeof row.asOfSourceTimeNs === 'string' && /^\d{1,24}$/.test(row.asOfSourceTimeNs) &&
    Array.isArray(row.savedEventIds) && row.savedEventIds.length <= 16 && row.savedEventIds.every(id => typeof id === 'string' && id.length <= 200);
}
export function showcaseMatches(report: Report, site: CitySite, scope: AnalyticsScope): boolean {
  return site.mode === 'live' && report?.siteId === site.id && report.mode === site.mode &&
    scope.kind === 'scenario' && !scope.suppressed && !!scope.epoch && !!scope.runId &&
    report.analyticsScope?.kind === 'scenario' && !report.analyticsScope.suppressed &&
    report.analyticsScope.epoch === scope.epoch && report.analyticsScope.runId === scope.runId && report.analyticsScope.scenarioId === scope.scenarioId &&
    Array.isArray(report.measurements) && report.measurements.length <= 4 && report.measurements.every(validShowcaseMeasurement);
}
const seconds = (n: number | undefined) => n === undefined ? '—' : `${n.toFixed(1)} s`;

/** Every number is source-observed. Poll receipt expiry never advances a timer. */
export function ShowcaseEvidence({ site, scenarioId, currentScope }: { site: CitySite; scenarioId: string; currentScope: AnalyticsScope | null | undefined }) {
  const [sample, setSample] = useState<{ report: Report; received: number } | null>(null);
  const [now, setNow] = useState(0);
  const epoch = currentScope?.epoch;
  useEffect(() => {
    let disposed = false; let timer: ReturnType<typeof setTimeout>; let pending: AbortController | undefined;
    setSample(null);
    const poll = async () => {
      pending = new AbortController(); const timeout = setTimeout(() => pending?.abort(), 2500);
      try {
        const report = await cityRequest<Report>('showcase', { signal: pending.signal });
        if (!disposed) { const received = Date.now(); setSample({ report, received }); setNow(received); }
      } catch { /* Keep history briefly; the receipt deadline removes live status. */ }
      finally { clearTimeout(timeout); if (!disposed) timer = setTimeout(poll, 700); }
    };
    if (site.mode === 'live' && epoch) void poll();
    const expiry = setInterval(() => setNow(Date.now()), 750);
    return () => { disposed = true; clearTimeout(timer); clearInterval(expiry); pending?.abort(); };
  }, [site.id, site.mode, epoch]);
  const scope = currentScope;
  const valid = sample && scope && scope.scenarioId === scenarioId && now - sample.received < 3000 && showcaseMatches(sample.report, site, scope);
  const row = (id: string) => {
    const result = valid ? sample.report.measurements.find(item => item.ruleId === id) : undefined;
    const startMs = Date.parse(scope?.startedAt ?? '');
    return result && site.sources.some(source => source.id === result.sourceId) && Number.isFinite(startMs) &&
      BigInt(result.asOfSourceTimeNs) >= BigInt(startMs) * BigInt(1_000_000) ? result : undefined;
  };
  const crossing = scenarioId === 'crossing-occupancy';
  const primary = row(crossing ? 'expo-crossing-occupancy' : scenarioId === 'queue-blockage' ? 'expo-junction-blockage' : 'expo-emergency-blockage');
  const live = primary && ['occupied', 'clear'].includes(primary.status) && primary.count !== null;
  const occupied = live && primary.status === 'occupied';
  const saved = primary?.savedEventIds.length ? primary.savedEventIds.length : 0;
  const finding = !live ? !crossing && primary?.status === 'unknown' ? 'Checking for blockage' : 'Waiting for camera evidence' : crossing ? occupied ? 'Crossing occupied' : 'Crossing clear'
    : occupied ? 'Junction blocked' : primary.peakCount > 0 ? 'Junction cleared' : 'Junction clear';
  return <div className={styles.evidence} aria-label="Live scenario measurements" data-state={occupied ? 'occupied' : live ? 'clear' : 'waiting'}>
    <div className={styles.head}><strong><i />{finding}</strong><span>Camera measured</span></div>
    <div className={styles.readouts}>
      <div><output>{live ? primary.count : '—'}</output><span>{crossing ? 'people in crossing' : 'stopped in junction'}</span></div>
      <div><output>{seconds(live ? primary.continuousSeconds : undefined)}</output><span>{crossing ? 'occupied now' : 'blocked now'}</span></div>
      <div><output>{crossing || scenarioId === 'queue-blockage' ? live ? primary.peakCount : '—' : saved ? 'Saved' : '—'}</output><span>{crossing ? 'peak people' : scenarioId === 'emergency-access' ? 'incident record' : 'peak stopped'}</span></div>
    </div>
    <div className={styles.foot}><span>{primary ? `${seconds(primary.occupiedSeconds)} observed ${crossing ? 'occupied' : 'blocked'}${primary.hasGaps ? ' · partial coverage' : ''}` : 'Observing this run'}</span><span data-saved={saved > 0}>{saved ? '✓ Camera event saved' : 'Monitoring the area'}</span></div>
    <ScenarioVlmObservation siteId={site.id} scenarioId={scenarioId} epoch={scope?.epoch} runId={scope?.runId}
      sourceId={primary?.sourceId} sessionId={primary?.sessionId}
      sourceName={primary ? sourceName(site.sources.find(source => source.id === primary.sourceId) ?? { name: 'Camera' }) : undefined}
      enabled={Boolean(valid && primary && primary.peakCount > 0)} />
  </div>;
}
