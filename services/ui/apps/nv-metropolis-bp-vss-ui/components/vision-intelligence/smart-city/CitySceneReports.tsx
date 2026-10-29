// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { IconArrowRight, IconDownload, IconFileDescription, IconRefresh } from '@tabler/icons-react';
import { validShowcaseMeasurement, type ShowcaseMeasurement } from './ShowcaseEvidence';
import type { CityEvent, CitySite } from './types';
import type { MobilityReport } from './mobilityTypes';
import { cityRequest } from './useCity';
import { mobilityReportMatches } from './useMobility';
import { cityChallenge } from './cityChallenges';
import { getScenarioPresentation } from './scenarioPresentation';
import { sourceName } from './presentation';
import { cityEventWindow } from './CityEventEvidence';
import styles from './CitySceneReports.module.css';

export interface ArchivedScene {
  epoch: string; kind: 'scenario'; runId: string; scenarioId: string; startedAt: string; endedAt: string;
  mobilitySnapshotBasis: 'last-observed-before-boundary'; mobility: MobilityReport;
  showcase?: ShowcaseMeasurement[];
  observationEnd?: { reason?: string; activeEventState?: string };
}
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0;
const number = (n: unknown, suffix = '') => finite(n) ? `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}` : '—';
const date = (v: string) => new Date(v).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
export function archivedScene(value: unknown, site: CitySite): value is ArchivedScene {
  if (!value || typeof value !== 'object') return false;
  const row = value as ArchivedScene; const report = row.mobility;
  const owned = (group: readonly { sourceId: string }[]) => group.every(source => source && typeof source === 'object' && site.sources.some(current => current.id === source.sourceId));
  return Boolean(site.mode === 'live' && row.kind === 'scenario' && typeof row.epoch === 'string' && /^[A-Za-z0-9:-]{1,160}$/.test(row.epoch) &&
    typeof row.runId === 'string' && /^[A-Za-z0-9:-]{1,160}$/.test(row.runId) && getScenarioPresentation(row.scenarioId) &&
    typeof row.startedAt === 'string' && row.startedAt.length <= 64 && typeof row.endedAt === 'string' && row.endedAt.length <= 64 && Number.isFinite(Date.parse(row.startedAt)) && Number.isFinite(Date.parse(row.endedAt)) && Date.parse(row.endedAt) >= Date.parse(row.startedAt) &&
    (row.showcase === undefined || Array.isArray(row.showcase) && row.showcase.length <= 4 && row.showcase.every(item => validShowcaseMeasurement(item) && site.sources.some(source => source.id === item.sourceId) && BigInt(item.asOfSourceTimeNs) >= BigInt(Date.parse(row.startedAt)) * BigInt(1000000) && BigInt(item.asOfSourceTimeNs) <= BigInt(Date.parse(row.endedAt)) * BigInt(1000000))) &&
    row.mobilitySnapshotBasis === 'last-observed-before-boundary' && report && Number.isInteger(report.siteRevision) && report.siteRevision >= 0 &&
    report.windowMinutes === 5 && mobilityReportMatches(report, { ...site, revision: report.siteRevision }, 5) &&
    [report.coverage, report.lineCounts, report.movements, report.obstructions, report.queues, report.crossings, report.curbs ?? []].every(owned));
}
export function archivedFinding(scene: ArchivedScene) {
  if (['crossing-occupancy', 'queue-blockage', 'emergency-access'].includes(scene.scenarioId)) {
    const crossing = scene.scenarioId === 'crossing-occupancy';
    const id = crossing ? 'expo-crossing-occupancy' : scene.scenarioId === 'queue-blockage' ? 'expo-junction-blockage' : 'expo-emergency-blockage';
    const row = scene.showcase?.find(x => validShowcaseMeasurement(x) && x.ruleId === id);
    const queue = scene.showcase?.find(x => validShowcaseMeasurement(x) && x.ruleId === 'expo-approach-queue');
    return { value: number(row?.occupiedSeconds, ' s'), label: crossing ? 'Observed crossing occupancy' : 'Observed junction blockage',
      note: row?.hasGaps ? 'Partial camera coverage. Missing intervals are excluded.' : 'Camera-observed intervals within this run. No time is added across missing frames.', sourceId: row?.sourceId,
      facts: [[crossing ? 'Peak people in crossing' : 'Peak stopped in junction', number(row?.peakCount)],
        ...(scene.scenarioId === 'queue-blockage' ? [['Peak approach queue', number(queue?.peakCount)]] : []),
        ['Saved camera events', number(row?.savedEventIds.length)], ['Last observed state', row?.status ?? 'Unverified']] };
  }
  const r = scene.mobility;
  const observed = (id: string | undefined) => r.coverage.some(x => x.sourceId === id && finite(x.observedSeconds) && x.observedSeconds > 0);
  if (scene.scenarioId === 'crossing-obstruction') {
    const row = r.obstructions.find(x => x.ruleId === 'cam_sw-blocked-crossing'); const valid = row && observed(row.sourceId) && row.status !== 'unavailable';
    return { value: number(valid ? row.blockedSeconds : null, ' s'), label: 'Observed stopped-zone time', note: 'Confirmed camera intervals; gaps and candidate time are excluded.', sourceId: row?.sourceId,
      facts: [['Completed episodes', number(valid ? row.completedEpisodes : null)], ['Ongoing at observation end', number(valid ? row.ongoingEpisodes : null)], ['Unresolved episodes', number(valid ? row.unknownEpisodes : null)]] };
  }
  if (scene.scenarioId === 'queue-recovery') {
    const row = r.queues.find(x => x.id === 'northbound-queue'); const valid = row && observed(row.sourceId) && row.status !== 'disabled';
    return { value: number(valid ? row.maximumObservedExtentM : null, ' m'), label: 'Maximum observed queue extent', note: 'Ground-anchor estimate within this report window. It is not a validated vehicle footprint.', sourceId: row?.sourceId,
      facts: [['Vehicles observed at report end', number(valid && row.currentCountsAvailable !== false ? row.count : null)], ['Membership at report end', row?.membershipComplete === false ? 'Incomplete' : row?.membershipComplete === true ? 'Complete' : 'Unverified']] };
  }
  if (scene.scenarioId === 'curb-obstruction') {
    const candidate = r.curbs?.find(x => x.id === 'north-curbside-access'); const row = candidate && observed(candidate.sourceId) ? candidate : undefined;
    return { value: number(row?.occupiedSeconds, ' s'), label: 'Observed curb occupancy time', note: 'Camera evidence of occupancy. It does not establish loading activity, permission or a violation.', sourceId: row?.sourceId,
      facts: [['Completed visits', number(row?.completedVisitCount)], ['Median completed visit', number(row && finite(row.completedDwellP50Ms) ? row.completedDwellP50Ms / 1000 : null, ' s')], ['Incomplete visits', number(row?.incompleteVisitCount)]] };
  }
  if (scene.scenarioId === 'turning-demand') {
    const ids = ['northbound-left', 'northbound-through', 'northbound-right']; const rows = ids.map(id => r.movements.find(x => x.id === id));
    const valid = rows.every(x => x && observed(x.sourceId) && x.status !== 'unavailable' && finite(x.completedCount)) && new Set(rows.map(x => x?.sourceId)).size === 1 && !r.configurationIssues.some(x => x.kind === 'movement' && ids.includes(x.id));
    const approach = r.lineCounts.find(x => x.ruleId === 'cam_sw-northbound-line');
    const total = valid ? rows.reduce((sum, x) => sum + x!.completedCount, 0) : null;
    const approachCount = approach && observed(approach.sourceId) && approach.status !== 'unavailable' ? approach.count : null;
    const showApproach = total === 0 && finite(approachCount) && approachCount > 0;
    return { value: number(showApproach ? approachCount : total), label: showApproach ? 'Approach line crossings' : 'Completed camera-owned movements', note: showApproach ? '0 completed turns. A line crossing is separate from a complete entry-to-exit journey.' : 'A complete entry-to-exit identity is required. Approach line crossings are a separate measure.', sourceId: rows[0]?.sourceId,
      facts: [['Left', number(valid ? rows[0]?.completedCount : null)], ['Straight', number(valid ? rows[1]?.completedCount : null)], ['Right', number(valid ? rows[2]?.completedCount : null)], ['Approach line crossings', number(approach && observed(approach.sourceId) && approach.status !== 'unavailable' ? approach.count : null)], ['Interrupted journey evidence', valid ? rows.some(x => finite(x?.incompleteCount) && x!.incompleteCount > 0) ? 'Present' : 'Not reported' : 'Unverified']] };
  }
  const row = r.crossings.find(x => x.id === 'east-crossing-south-north'); const valid = row && observed(row.sourceId) && row.status !== 'disabled';
  return { value: number(valid ? row.completedCount : null), label: 'Completed south-to-north journeys', note: 'Requires an observed far-side exit with the same camera identity. Interrupted journeys are kept separate.', sourceId: row?.sourceId,
    facts: [['Incomplete journeys', number(valid ? row.incompleteCount : null)], ['Observed approach samples', number(valid ? row.waitSampleCount : null)], ['Median observed approach time', number(valid && finite(row.waitP50Ms) ? row.waitP50Ms / 1000 : null, ' s')]] };
}

export function CitySceneReports({ site, onReviewEvent }: { site: CitySite; onReviewEvent: (event: CityEvent) => void }) {
  const [rows, setRows] = useState<ArchivedScene[]>([]); const [loadedContext, setLoadedContext] = useState(''); const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [refresh, setRefresh] = useState(0);
  const [reviewing, setReviewing] = useState(false); const [reviewError, setReviewError] = useState<string | null>(null);
  const reviewController = useRef<AbortController | null>(null);
  const context = JSON.stringify([site.id, site.mode, site.sources.map(x => x.id)]);
  useEffect(() => {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort('timeout'), 10000);
    setLoading(true); setRows([]); setError(null);
    void cityRequest<{ prior: unknown[] }>('analytics-scopes', { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      if (!value || !Array.isArray(value.prior) || value.prior.length > 100) throw new Error('The scene report index is invalid.');
      const valid = value.prior.filter(row => archivedScene(row, site)).sort((a, b) => Date.parse(b.endedAt) - Date.parse(a.endedAt));
      setRows(valid); setLoadedContext(context); setSelected(current => valid.some(x => x.epoch === current) ? current : valid[0]?.epoch ?? '');
    }).catch(cause => { if (!controller.signal.aborted || controller.signal.reason === 'timeout') setError(controller.signal.reason === 'timeout' ? 'Scene reports timed out. Try Refresh reports.' : cause instanceof Error ? cause.message : 'Scene reports are unavailable.'); })
      .finally(() => { clearTimeout(timer); if (!controller.signal.aborted || controller.signal.reason === 'timeout') setLoading(false); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [context, refresh]);
  const validRows = loadedContext === context ? rows : [];
  const scene = !loading ? validRows.find(x => x.epoch === selected) : undefined;
  useEffect(() => { reviewController.current?.abort(); setReviewing(false); setReviewError(null); return () => reviewController.current?.abort(); }, [context, selected]);
  const finding = scene ? archivedFinding(scene) : null;
  const presentation = getScenarioPresentation(scene?.scenarioId); const challenge = scene ? cityChallenge(scene.scenarioId) : null;
  const owner = site.sources.find(x => x.id === finding?.sourceId);
  const review = async () => {
    if (!scene || reviewing) return;
    const controller = new AbortController(); reviewController.current = controller; const timer = setTimeout(() => controller.abort('timeout'), 10000);
    setReviewing(true); setReviewError(null);
    try {
      const value = await cityRequest<{ events: CityEvent[] }>('reports', { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!value || !Array.isArray(value.events)) throw new Error('Event history is unavailable.');
      const relevant = value.events.filter(x => x.analyticsScope?.epoch === scene.epoch && x.mode === site.mode && presentation?.ruleIds.includes(x.ruleId) && cityEventWindow(x, site.sources.find(source => source.id === x.sourceId)));
      const event = relevant.find(x => x.ruleId === presentation?.primaryRuleId) ?? relevant[0];
      if (!event) throw new Error('No retained event interval is available for this scene report. Its measurements remain available.');
      onReviewEvent(event);
    } catch (cause) { if (!controller.signal.aborted || controller.signal.reason === 'timeout') setReviewError(controller.signal.reason === 'timeout' ? 'Event history timed out. Try again.' : cause instanceof Error ? cause.message : 'Event history is unavailable.'); }
    finally { clearTimeout(timer); if (reviewController.current === controller) { reviewController.current = null; setReviewing(false); } }
  };
  const download = () => {
    if (!scene) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schemaVersion: 'city.archived-scene-export.v1', exportedAt: new Date().toISOString(), scope: 'Historical camera-owned report; not live; observation closure does not prove clearance.', ...scene }, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `smart-city-scene-${scene.scenarioId}-${scene.epoch}.json`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
  };
  return <section className={styles.page} aria-label="Recorded scene reports">
    <aside className={styles.index}><header><h2>Recorded scenes</h2><button type="button" aria-label="Refresh scene reports" disabled={loading} onClick={() => setRefresh(x => x + 1)}><IconRefresh size={18} /></button></header><p>Camera evidence saved when observation closed.</p>
      {loading ? <p role="status">Loading scene reports…</p> : error ? <p role="alert">{error}</p> : validRows.length ? <nav aria-label="Recorded scene selection">{validRows.map(row => <button type="button" key={row.epoch} aria-current={selected === row.epoch ? 'true' : undefined} onClick={() => setSelected(row.epoch)}><IconFileDescription size={21} /><span><strong>{getScenarioPresentation(row.scenarioId)?.title}</strong><small>{date(row.endedAt)}</small></span><IconArrowRight size={17} /></button>)}</nav> : <p>Run a city challenge to retain its camera report. No sample results are shown.</p>}
    </aside>
    {scene && finding && presentation && challenge ? <article className={styles.report} key={scene.epoch}>
      <h2>{presentation.title}</h2><span className={styles.badge}>Recorded scene · Not live</span><p className={styles.time}>{date(scene.startedAt)} – {date(scene.endedAt)} · {Date.parse(scene.endedAt) - Date.parse(scene.startedAt) <= 300000 ? `${Math.round((Date.parse(scene.endedAt) - Date.parse(scene.startedAt)) / 1000)} s scene` : 'Final 5 min of this run'}</p>
      <section className={styles.metrics} aria-label="Archived camera measurements"><div className={styles.primary}><strong>{finding.value}</strong><span>{finding.label}</span><small>{finding.note}</small></div><dl>{finding.facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}<div><dt>Owner camera</dt><dd>{owner ? sourceName(owner) : 'Unverified'}</dd></div></dl></section>
      <section className={styles.context}><h3>Why it matters</h3><p>{challenge.problem}</p><h3>Use this insight</h3><p>{challenge.action}</p><a href={challenge.researchUrl} target="_blank" rel="noreferrer">Why this matters · {challenge.researchTitle}<IconArrowRight size={15} /></a></section>
      <div className={styles.actions}><button className={styles.action} type="button" disabled={reviewing} onClick={() => void review()}>{reviewing ? 'Finding a camera event…' : 'Review a camera event'}<IconArrowRight size={17} /></button><button type="button" onClick={download}><IconDownload size={17} />Export scene report</button></div>
      {reviewError && <p role="status" className={styles.notice}>{reviewError}</p>}
      <details className={styles.scope}><summary>Evidence scope &amp; limitations</summary><p>Last observed before the scene boundary. Ending observation is not proof of departure or clearance. Counts belong to their owner camera, with no combined unique site total.</p><p>Run {scene.runId} · Configuration {scene.mobility.configRevision}</p>{scene.mobility.coverage.map(camera => <p key={camera.sourceId}>{site.sources.find(x => x.id === camera.sourceId)?.name ?? camera.sourceId}: {number(camera.observedSeconds, ' s')} observed camera time · {camera.timestampBasis}</p>)}{scene.mobility.limitations.map((limit, index) => <p key={index}>{limit}</p>)}</details>
    </article> : <article className={styles.empty}><IconFileDescription size={32} /><h2>Review a recorded city challenge.</h2><p>Its camera measurements remain separate from the current live traffic.</p></article>}
  </section>;
}
