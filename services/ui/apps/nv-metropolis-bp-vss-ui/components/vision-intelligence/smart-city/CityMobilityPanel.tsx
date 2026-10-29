// SPDX-License-Identifier: MIT
import { createPortal } from 'react-dom';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { IconAdjustmentsHorizontal, IconArrowRight, IconCheck, IconDownload, IconMapPin, IconPlus, IconRefresh, IconTrash, IconX, IconArrowUp, IconCornerUpLeft, IconCornerUpRight } from '@tabler/icons-react';
import type { AnalyticsScope, CityRule, CitySite, Point } from './types';
import { analyticsScopeLabel } from './analyticsScope';
import type { MobilityConfig, MobilityCurbConfig, MobilityCurbRole, MobilityConfigInput, MobilityCoverage, MobilityMembershipEvidence, MobilityQueue, MobilityReport, MobilityWindow } from './mobilityTypes';
import { useMobility } from './useMobility';
import { sourceName } from './presentation';
import styles from './CityMobility.module.css';
import { cityChallenge, TOPIC_CHALLENGE } from './cityChallenges';
import { getScenarioPresentation } from './scenarioPresentation';

type SetupSection = 'movements' | 'crossings' | 'queues' | 'curbs';
type MobilityDraft = MobilityConfig & { curbs: MobilityCurbConfig[] };
export type InsightTopic = SetupSection | 'obstructions';
const TOPICS: { id: InsightTopic; label: string }[] = [{ id: 'movements', label: 'Turning traffic' }, { id: 'obstructions', label: 'Crossing access' }, { id: 'queues', label: 'Queues' }, { id: 'crossings', label: 'Walking' }, { id: 'curbs', label: 'Curb access' }];
interface Props {
  headerTarget?: HTMLElement | null;
  currentScope?: AnalyticsScope | null;
  site: CitySite; rules: CityRule[]; onFocusRule?: (ruleId: string) => void;
  onPickQueueGeometry?: (apply: (points: [Point, Point, Point]) => void) => void;
  onQueueFocus?: (queue: MobilityQueue) => void;
  topic?: InsightTopic; onTopicChange?: (topic: InsightTopic) => void;
}
const CLASSES = ['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler'];
const VEHICLE_CLASSES = CLASSES.filter(name => name !== 'person');
const CURB_ROLES: { value: MobilityCurbRole; label: string }[] = [{ value: 'general', label: 'General curb' }, { value: 'loading', label: 'Loading area' }, { value: 'bus-stop', label: 'Bus stop' }, { value: 'cycle-lane', label: 'Cycle lane' }];
const curbRole = (value: string) => CURB_ROLES.find(role => role.value === value)?.label ?? 'Curb area';
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const number = (value: number | null | undefined, decimals = 0) => finite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: decimals }) : '—';
const seconds = (value: number | null | undefined) => finite(value) ? value >= 60 ? `${number(value / 60, 1)} min` : `${number(value, 1)} s` : '—';
const wait = (value: number | null | undefined) => finite(value) ? seconds(value / 1000) : '—';
const cloneConfig = (value: MobilityConfig): MobilityDraft => ({ ...value, curbs: (value.curbs ?? []).map(row => ({ ...row })), revision: value.revision, movements: value.movements.map(row => ({ ...row, classes: row.classes ? [...row.classes] : undefined })), crossings: value.crossings.map(row => ({ ...row })), queues: value.queues.map(row => ({ ...row, stopLine: row.stopLine.map(point => [...point]) as [Point, Point], upstreamPoint: [...row.upstreamPoint] })) });
const identifier = (kind: string) => `city-${kind}-${typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function statusLabel(status: string) {
  const labels: Record<string, string> = { ready: 'Observed', partial: 'Partial window', unavailable: 'No observation', unknown: 'Not enough evidence', empty: 'No queue observed', candidate: 'Checking queue', queued: 'Queue observed', spillback: 'Boundary reached', disabled: 'Disabled', active: 'Observing' };
  return labels[status] ?? 'Not enough evidence';
}
function Status({ status, label }: { status: string; label?: string }) { return <span className={styles.status} data-status={status}>{label ?? statusLabel(status)}</span>; }
function currentCountsAvailable(row: MobilityMembershipEvidence & { status: string }, sourceFresh: boolean) {
  return sourceFresh && row.currentCountsAvailable !== false && row.status !== 'disabled' && (row.status !== 'unknown' || row.countBasis === 'currently-observed');
}
function observedCount(value: number, row: MobilityMembershipEvidence) { return `${row.membershipComplete === false && value > 0 ? '≥ ' : ''}${number(value)}`; }
function MembershipNote({ row }: { row: MobilityMembershipEvidence }) {
  const notes: string[] = [];
  if ((row.pendingTrackCount ?? 0) > 0) notes.push(`${number(row.pendingTrackCount)} briefly missing`);
  if ((row.unresolvedHistoricalTrackCount ?? 0) > 0) notes.push(`${number(row.unresolvedHistoricalTrackCount)} earlier tracks unresolved`);
  if ((row.lostTrackCount ?? 0) > 0) notes.push(`${number(row.lostTrackCount)} lost in this window`);
  return notes.length || row.membershipComplete === false ? <p className={styles.note}>{notes.length ? `${notes.join(' · ')}. ` : ''}Counts include currently observed objects only; zero does not confirm an empty area.</p> : null;
}
function Breakdown({ values }: { values: Record<string, number> }) {
  const entries = Object.entries(values).filter(([, value]) => finite(value) && value > 0);
  return entries.length ? <dl className={styles.breakdown}>{entries.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{number(value)}</dd></div>)}</dl> : <p className={styles.note}>No class counts in this window.</p>;
}
function Coverage({ rows }: { rows: MobilityCoverage[] }) {
  return <details className={styles.coverage}><summary>Observed video time <span>{rows.length} camera{rows.length === 1 ? '' : 's'}</span></summary><p>Valid observation time in each camera’s trailing window. Gaps are excluded. This is not detector accuracy or wall time.</p>{rows.map(row => <div key={row.sourceId} className={styles.coverageRow}><div><strong>{sourceName({ name: row.name })}</strong><span>{seconds(row.observedSeconds)} / {seconds(row.windowSeconds)}</span></div><progress aria-label={`Observed time for ${row.name}`} value={Math.max(0, Math.min(1, finite(row.coverageRatio) ? row.coverageRatio : 0))} max="1" /><small>{row.status === 'live' ? 'Camera observations arriving' : row.status === 'stale' ? 'Camera observations delayed' : 'Waiting for camera observations'}{row.truncated ? ' · retained history is incomplete' : ''}</small></div>)}</details>;
}

export function mobilityConfigError(config: MobilityConfig, rules: CityRule[]): string | null {
  const available = new Map(rules.filter(rule => rule.enabled).map(rule => [rule.id, rule])); const ids = new Set<string>();
  for (const row of [...config.movements, ...config.crossings, ...config.queues, ...(config.curbs ?? [])]) {
    if (!row.name.trim()) return 'Give each measurement a name.';
    if (!row.id || ids.has(row.id)) return 'Each measurement must have a unique ID.'; ids.add(row.id);
  }
  for (const row of config.movements) {
    const entry = available.get(row.entryRuleId); const exit = available.get(row.exitRuleId);
    if (!entry || !exit || entry.id === exit.id || entry.sourceId !== exit.sourceId) return `${row.name}: choose two different enabled rules from one camera.`;
    if (row.classes && !row.classes.length) return `${row.name}: choose at least one object class.`;
    const selected = row.classes?.length ? row.classes : CLASSES;
    if (!selected.some(name => (!entry.classes.length || entry.classes.includes(name)) && (!exit.classes.length || exit.classes.includes(name)))) return `${row.name}: both rules must allow at least one selected object class.`;
  }
  for (const row of config.crossings) {
    const entry = available.get(row.waitingRuleId); const exit = available.get(row.crossingRuleId);
    if (!entry || !exit || entry.id === exit.id || entry.sourceId !== exit.sourceId || entry.geometry.points.length < 3 || exit.geometry.points.length < 3) return `${row.name}: choose different waiting and crossing polygons from one camera.`;
    if ([entry, exit].some(rule => rule.classes.length > 0 && !rule.classes.includes('person'))) return `${row.name}: both polygons must allow the person class.`;
  }
  for (const row of config.queues) {
    const zone = available.get(row.zoneRuleId);
    if (!zone || zone.kind !== 'queue' || zone.geometry.points.length < 3) return `${row.name}: choose an enabled queue polygon.`;
    if (![...row.stopLine.flat(), ...row.upstreamPoint, row.spillbackDistanceM].every(finite)) return `${row.name}: set the stop line, upstream point and boundary distance.`;
    const [a, b] = row.stopLine; const midpoint: Point = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-6 || Math.hypot(row.upstreamPoint[0] - midpoint[0], row.upstreamPoint[1] - midpoint[1]) < 1e-6 || row.spillbackDistanceM <= 0) return `${row.name}: use a distinct stop line, upstream point and positive boundary distance.`;
  }
  for (const row of config.curbs ?? []) {
    const zone = available.get(row.zoneRuleId);
    if (!zone || zone.geometry.points.length < 3 || (zone.classes.length > 0 && !zone.classes.some(name => VEHICLE_CLASSES.includes(name)))) return `${row.name}: choose an enabled polygon that permits vehicle classes.`;
    if (!CURB_ROLES.some(role => role.value === row.role)) return `${row.name}: choose a curb role.`;
    if (!Number.isInteger(row.dwellThresholdMs) || row.dwellThresholdMs < 0 || row.dwellThresholdMs > 3_600_000) return `${row.name}: use a dwell threshold from 0 to 3600 seconds.`;
    if (!Number.isInteger(row.maximumObservationGapMs) || row.maximumObservationGapMs < 50 || row.maximumObservationGapMs > 60_000) return `${row.name}: use an observation gap from 0.05 to 60 seconds.`;
  }
  return null;
}

/** Tidy CSV keeps each measure camera-scoped and carries its observation coverage. */
export function mobilityCsv(report: MobilityReport, receivedAt: string | null): string {
  const rows: unknown[][] = [['section', 'measurement_id', 'name', 'source_id', 'metric', 'value', 'unit', 'status', 'window_minutes', 'observed_video_seconds', 'time_basis', 'received_at', 'scope_epoch', 'scope_kind', 'run_id', 'scenario_id', 'scope_started_at']];
  const add = (section: string, id: string, name: string, sourceId: string, status: string, metric: string, value: unknown, unit = 'count') => rows.push([section, id, name, sourceId, metric, value, unit, status, report.windowMinutes, report.coverage.find(row => row.sourceId === sourceId)?.observedSeconds ?? null, report.timeBasis, receivedAt, report.analyticsScope?.epoch, report.analyticsScope?.kind, report.analyticsScope?.runId, report.analyticsScope?.scenarioId, report.analyticsScope?.startedAt]);
  for (const row of report.lineCounts) { add('gate', row.ruleId, row.name, row.sourceId, row.status, 'crossings', row.status === 'unavailable' ? null : row.count); for (const [kind, count] of Object.entries(row.byClass)) add('gate', row.ruleId, row.name, row.sourceId, row.status, `class_${kind}`, row.status === 'unavailable' ? null : count); }
  for (const row of report.movements) { for (const metric of ['completedCount', 'activeCount', 'incompleteCount'] as const) add('movement', row.id, row.name, row.sourceId, row.status, metric, row.status === 'unavailable' ? null : row[metric]); for (const [kind, count] of Object.entries(row.byClass)) add('movement', row.id, row.name, row.sourceId, row.status, `class_${kind}`, row.status === 'unavailable' ? null : count); }
  for (const row of report.obstructions) { add('obstruction', row.ruleId, row.name, row.sourceId, row.status, 'observed_blocked_time', row.status === 'unavailable' ? null : row.blockedSeconds, 'seconds'); for (const metric of ['episodeCount', 'completedEpisodes', 'ongoingEpisodes', 'unknownEpisodes'] as const) add('obstruction', row.ruleId, row.name, row.sourceId, row.status, metric, row.status === 'unavailable' ? null : row[metric]); }
  const fresh = (sourceId: string) => report.mode !== 'live' || report.coverage.find(source => source.sourceId === sourceId)?.status === 'live';
  const membership = (section: string, row: (MobilityReport['queues'] | MobilityReport['crossings'])[number]) => {
    add(section, row.id, row.name, row.sourceId, row.status, 'currentCountsAvailable', currentCountsAvailable(row, fresh(row.sourceId)), 'boolean');
    add(section, row.id, row.name, row.sourceId, row.status, 'membershipComplete', row.membershipComplete, 'boolean');
    for (const metric of ['pendingTrackCount', 'unresolvedHistoricalTrackCount', 'lostTrackCount'] as const) add(section, row.id, row.name, row.sourceId, row.status, metric, row[metric]);
  };
  for (const row of report.queues) {
    const known = fresh(row.sourceId) && row.currentCountsAvailable !== false && !['unknown', 'disabled'].includes(row.status);
    add('queue', row.id, row.name, row.sourceId, row.status, 'current_extent', known ? row.observedExtentM : null, row.extentIsLowerBound ? 'metres_lower_bound' : 'metres');
    add('queue', row.id, row.name, row.sourceId, row.status, 'window_maximum_extent', row.maximumObservedExtentM, 'metres');
    add('queue', row.id, row.name, row.sourceId, row.status, 'current_count', currentCountsAvailable(row, fresh(row.sourceId)) ? row.count : null); membership('queue', row);
  }
  for (const row of report.crossings) {
    for (const metric of ['completedCount', 'incompleteCount', 'abandonedCount', 'returnedCount', 'waitSampleCount', 'firstSeenWaitingCount', 'briefGapRecoveredWaitCount'] as const) add('crossing', row.id, row.name, row.sourceId, row.status, metric, row[metric]);
    for (const metric of ['waitingCount', 'crossingCount'] as const) add('crossing', row.id, row.name, row.sourceId, row.status, metric, currentCountsAvailable(row, fresh(row.sourceId)) ? row[metric] : null);
    for (const metric of ['waitP50Ms', 'waitP95Ms', 'lowerBoundWaitP50Ms'] as const) add('crossing', row.id, row.name, row.sourceId, row.status, metric, row[metric], metric === 'lowerBoundWaitP50Ms' ? 'milliseconds_lower_bound' : 'milliseconds');
    membership('crossing', row);
  }
  for (const row of report.curbs ?? []) {
    const known = row.status !== 'unknown' && (report.mode !== 'live' || report.coverage.find(source => source.sourceId === row.sourceId)?.status === 'live');
    add('curb', row.id, row.name, row.sourceId, row.status, 'configured_role', row.role, 'label');
    for (const metric of ['arrivalCount', 'departureCount', 'turnoverCount', 'completedVisitCount', 'incompleteVisitCount', 'partialVisitCount'] as const) add('curb', row.id, row.name, row.sourceId, row.status, metric, row[metric]);
    for (const metric of ['occupancy', 'persistentOccupancyCount', 'stoppedCount'] as const) add('curb', row.id, row.name, row.sourceId, row.status, metric, known ? row[metric] : null);
    add('curb', row.id, row.name, row.sourceId, row.status, 'occupancyIsLowerBound', known ? Boolean(row.occupancyIsLowerBound) : null, 'boolean');
    for (const metric of ['occupiedSeconds', 'observedStoppedSeconds', 'stoppedEvidenceSeconds'] as const) add('curb', row.id, row.name, row.sourceId, row.status, metric, row[metric], 'observed_seconds');
    for (const metric of ['completedDwellP50Ms', 'completedDwellP95Ms'] as const) add('curb', row.id, row.name, row.sourceId, row.status, metric, row[metric], 'milliseconds');
    add('curb', row.id, row.name, row.sourceId, row.status, 'longestActiveObservedDwellMs', known ? row.longestActiveObservedDwellMs : null, 'observed_milliseconds');
  }
  const cell = (value: unknown) => { let text = value == null ? '' : String(value); if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`; return `"${text.replace(/"/g, '""')}"`; };
  return rows.map(row => row.map(cell).join(',')).join('\r\n');
}

export function CityMobilityPanel({ site, rules, currentScope, onFocusRule, onPickQueueGeometry, onQueueFocus, topic: controlledTopic, onTopicChange, headerTarget }: Props) {
  const mobility = useMobility(site); const { receivedAt, error, saving } = mobility;
  const scopePending = !!currentScope?.epoch && mobility.report?.analyticsScope?.epoch !== currentScope.epoch;
  const report = scopePending ? null : mobility.report;
  const loading = mobility.loading || scopePending;
  useEffect(() => { if (currentScope?.epoch) mobility.refresh(); }, [currentScope?.epoch, mobility.refresh]);
  const [localTopic, setTopic] = useState<InsightTopic>('movements');
  const topic = controlledTopic ?? localTopic;
  const [draft, setDraft] = useState<MobilityDraft | null>(null); const [setupSection, setSetupSection] = useState<SetupSection>('movements');
  const [saveError, setSaveError] = useState<string | null>(null); const [saved, setSaved] = useState(false); const [draftSources, setDraftSources] = useState<Record<string, string>>({});
  const generation = useRef(0); const mounted = useRef(true);
  const [selectedQueueId, setSelectedQueueId] = useState<string | null>(null); const lastQueue = useRef<MobilityQueue | null>(null); const queueFocus = useRef(onQueueFocus); queueFocus.current = onQueueFocus;
  const identity = `${site.id}:${site.revision}:${site.mode}`;
  useEffect(() => { ++generation.current; setDraft(null); setSaveError(null); setDraftSources({}); setSaved(false); setTopic('movements'); setSelectedQueueId(null); lastQueue.current = null; }, [identity]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++generation.current; }; }, []);
  useEffect(() => {
    if (topic !== 'queues' && lastQueue.current) { queueFocus.current?.({ ...lastQueue.current, status: 'unknown', tailPositionM: null, observedExtentM: null, spillback: null }); setSelectedQueueId(null); lastQueue.current = null; }
  }, [topic]);
  useEffect(() => {
    if (!selectedQueueId || !queueFocus.current) return;
    const latest = report?.queues.find(row => row.id === selectedQueueId) ?? null;
    const value = latest ?? lastQueue.current;
    if (!value || value.id !== selectedQueueId) return;
    const current = Boolean(latest && !error && (site.mode !== 'live' || report?.coverage.find(row => row.sourceId === value.sourceId)?.status === 'live'));
    const shown: MobilityQueue = current && value.currentCountsAvailable !== false && !['unknown', 'disabled'].includes(value.status) ? value : { ...value, status: 'unknown', tailPositionM: null, observedExtentM: null, spillback: null, qualityReasons: ['Current queue observations are unavailable.'] };
    lastQueue.current = shown; queueFocus.current(shown);
  }, [report, error, selectedQueueId, site.mode]);
  const available = useMemo(() => rules.filter(rule => rule.enabled), [rules]);
  const source = (id: string) => { const value = site.sources.find(item => item.id === id); return value ? sourceName(value) : id; };
  const currentEvidence = (id: string) => !error && (site.mode !== 'live' || report?.coverage.find(row => row.sourceId === id)?.status === 'live');
  const openSetup = (section: SetupSection = 'movements') => { if (!report) return; ++generation.current; setDraft(cloneConfig(report.config)); setSetupSection(section); setSaveError(null); setDraftSources({}); setSaved(false); };
  const closeSetup = () => { ++generation.current; setDraft(null); setSaveError(null); };
  const selectTopic = (next: InsightTopic) => {
    if (next !== 'queues' && lastQueue.current) { queueFocus.current?.({ ...lastQueue.current, status: 'unknown', tailPositionM: null, observedExtentM: null, spillback: null }); setSelectedQueueId(null); lastQueue.current = null; }
    setTopic(next); onTopicChange?.(next);
  };
  const invalid = draft ? mobilityConfigError(draft, rules) : null;
  const conflict = Boolean(draft && report && draft.revision !== report.configRevision);
  const update = (section: SetupSection, id: string, patch: object) => setDraft(value => value ? { ...value, [section]: value[section].map(row => row.id === id ? { ...row, ...patch } : row) } as MobilityDraft : null);
  const remove = (section: SetupSection, id: string) => setDraft(value => value ? { ...value, [section]: (value[section] as { id: string }[]).filter(row => row.id !== id) } as MobilityDraft : null);
  const add = (section: SetupSection) => {
    const id = identifier(section); const row = section === 'movements' ? { id, name: 'New movement', entryRuleId: '', exitRuleId: '', classes: [...CLASSES] } : section === 'crossings' ? { id, name: 'New crossing', waitingRuleId: '', crossingRuleId: '' } : section === 'curbs' ? { id, name: 'New curb area', zoneRuleId: '', role: 'general', dwellThresholdMs: 30_000, maximumObservationGapMs: 1000 } : { id, name: 'New queue', zoneRuleId: '', stopLine: [[NaN, NaN], [NaN, NaN]], upstreamPoint: [NaN, NaN], spillbackDistanceM: 20 };
    setDraft(value => value ? { ...value, [section]: [...value[section], row] } as MobilityDraft : null); setDraftSources(value => ({ ...value, [id]: site.sources[0]?.id ?? '' }));
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); if (!draft || saving || invalid || conflict) return;
    const current = generation.current; setSaveError(null); setSaved(false);
    const { revision, ...configuration } = draft;
    const input: MobilityConfigInput = { ...configuration, expectedRevision: revision };
    try { await mobility.saveConfig(input); if (mounted.current && generation.current === current) { setDraft(null); setSaved(true); } }
    catch (cause) { if (mounted.current && generation.current === current) setSaveError(cause instanceof Error ? cause.message : 'Settings could not be saved.'); }
  };
  const focus = (ruleId: string | undefined) => ruleId && onFocusRule ? <button type="button" className={styles.mapLink} onClick={() => { setSelectedQueueId(null); lastQueue.current = null; onFocusRule(ruleId); }}><IconMapPin size={14} />Show on map</button> : null;
  const empty = (title: string, body: string, section: SetupSection) => <div className={styles.empty}><strong>{title}</strong><p>{body}</p><button type="button" onClick={() => openSetup(section)} disabled={!report}><IconPlus size={15} />Set up {section === 'movements' ? 'a movement' : section === 'crossings' ? 'a crossing' : section === 'curbs' ? 'a curb area' : 'a queue'}</button></div>;
  const ruleSelect = (label: string, id: string, candidates: CityRule[], change: (value: string) => void) => <label>{label}<select value={id} onChange={event => change(event.target.value)} disabled={saving} required><option value="">Choose a zone or line</option>{candidates.map(rule => <option key={rule.id} value={rule.id}>{rule.name}</option>)}</select></label>;
  const cameraSelect = (id: string, ruleId: string, reset: object) => { const sourceId = draftSources[id] ?? rules.find(rule => rule.id === ruleId)?.sourceId ?? site.sources[0]?.id ?? ''; return <label>Camera<select value={sourceId} disabled={saving} onChange={event => { setDraftSources(value => ({ ...value, [id]: event.target.value })); update(setupSection, id, reset); }}>{site.sources.map(item => <option key={item.id} value={item.id}>{sourceName(item)}</option>)}</select></label>; };
  const challenge = cityChallenge(TOPIC_CHALLENGE[topic]);
  const presentation = getScenarioPresentation(TOPIC_CHALLENGE[topic]);
  const heading = <header className={styles.heading}><div><h2>Intersection measurements</h2><p>Understand what the cameras observed—and what needs a closer look.</p></div><div className={styles.toolbar}><div className={styles.windows} role="group" aria-label="Report window">{([1, 5, 15] as MobilityWindow[]).map(value => <button key={value} type="button" aria-pressed={mobility.windowMinutes === value} disabled={saving} onClick={() => mobility.setWindowMinutes(value)}>{value} min</button>)}</div><details className={styles.exportMenu}><summary><IconDownload size={17} />Export report</summary><div><button type="button" disabled={!report} onClick={() => report && download(`smart-city-${site.id}-mobility-${report.windowMinutes}min.csv`, mobilityCsv(report, receivedAt), 'text/csv;charset=utf-8')}>Download measurements CSV</button><button type="button" disabled={!report} onClick={() => report && download(`smart-city-${site.id}-mobility-${report.windowMinutes}min.json`, JSON.stringify({ receivedAt, ...report }, null, 2), 'application/json')}>Download measurements JSON</button></div></details><button type="button" aria-label="Configure insights" title="Measurement setup" className={styles.secondaryButton} disabled={!report || saving} onClick={() => openSetup(topic === 'obstructions' ? 'movements' : topic)}><IconAdjustmentsHorizontal size={18} />Measurement setup</button><button type="button" className={styles.iconButton} aria-label="Refresh insights" title="Refresh measurements" disabled={saving} onClick={mobility.refresh}><IconRefresh size={17} /></button></div></header>;
  return <div className={styles.panel}>
    {headerTarget ? createPortal(heading, headerTarget) : heading}
    {site.mode === 'live' && <p className={styles.windowNote} aria-label="Insights observation scope">{analyticsScopeLabel(currentScope ?? report?.analyticsScope)}{scopePending ? ' · Updating this scope…' : report?.analyticsScope ? ' · Window limited to this scope' : ''}</p>}
    {error && <p role="alert" className={styles.error}>{error}{report && <small>Showing the last received report. Current camera state is unverified.</small>}</p>}
    {saved && <p className={styles.success} role="status"><IconCheck size={15} />Settings saved. New observations will populate the report.</p>}
    {draft ? <form className={styles.setup} onSubmit={save} aria-label="Insights settings">
      <div className={styles.setupHeading}><div><h3>Measurement setup</h3><p>One owner camera per measurement.</p></div><button type="button" className={styles.iconButton} aria-label="Close insights settings" onClick={closeSetup}><IconX size={18} /></button></div>
      <div className={styles.setupTabs} role="group" aria-label="Measurement type">{(['movements', 'crossings', 'queues', 'curbs'] as SetupSection[]).map(section => <button type="button" key={section} aria-pressed={setupSection === section} onClick={() => setSetupSection(section)}>{section === 'curbs' ? 'Curb areas' : section}</button>)}</div>
      <p className={styles.note}>Create the required zones with <strong>Edit zones</strong> above. Pair enabled rules from the same camera. Saving starts a new measurement revision.</p>
      {!draft[setupSection].length && <p className={styles.note}>No {setupSection} configured. Add one below.</p>}
      {draft[setupSection].map(row => {
        const firstRuleId = 'entryRuleId' in row ? row.entryRuleId : 'waitingRuleId' in row ? row.waitingRuleId : row.zoneRuleId;
        const owner = draftSources[row.id] ?? rules.find(rule => rule.id === firstRuleId)?.sourceId ?? site.sources[0]?.id ?? '';
        const candidates = available.filter(rule => rule.sourceId === owner);
        const polygons = candidates.filter(rule => rule.geometry.points.length >= 3);
        const pedestrianPolygons = polygons.filter(rule => !rule.classes.length || rule.classes.includes('person'));
        return <fieldset key={row.id} className={styles.configCard} disabled={saving}><legend>{row.name || 'Measurement'}</legend><div className={styles.configName}><label>Name<input value={row.name} maxLength={100} required onChange={event => update(setupSection, row.id, { name: event.target.value })} /></label><button type="button" className={styles.iconButton} aria-label={`Remove ${row.name || 'measurement'}`} onClick={() => remove(setupSection, row.id)}><IconTrash size={16} /></button></div>
          {'entryRuleId' in row && <>{cameraSelect(row.id, row.entryRuleId, { entryRuleId: '', exitRuleId: '' })}{ruleSelect('Entry gate or area', row.entryRuleId, candidates.filter(rule => rule.id !== row.exitRuleId), value => update('movements', row.id, { entryRuleId: value }))}{ruleSelect('Exit gate or area', row.exitRuleId, candidates.filter(rule => rule.id !== row.entryRuleId), value => update('movements', row.id, { exitRuleId: value }))}<div className={styles.classes}>{CLASSES.map(name => <label key={name}><input type="checkbox" checked={(row.classes ?? CLASSES).includes(name)} onChange={event => update('movements', row.id, { classes: event.target.checked ? [...(row.classes ?? CLASSES), name] : (row.classes ?? CLASSES).filter(value => value !== name) })} />{name}</label>)}</div><p className={styles.note}>Name the movement, for example “North → East”. Counts require a continuous track and a class enabled in both rules.</p></>}
          {'waitingRuleId' in row && <>{cameraSelect(row.id, row.waitingRuleId, { waitingRuleId: '', crossingRuleId: '' })}{ruleSelect('Waiting area', row.waitingRuleId, pedestrianPolygons.filter(rule => rule.id !== row.crossingRuleId), value => update('crossings', row.id, { waitingRuleId: value }))}{ruleSelect('Crossing area', row.crossingRuleId, pedestrianPolygons.filter(rule => rule.id !== row.waitingRuleId), value => update('crossings', row.id, { crossingRuleId: value }))}<p className={styles.note}>Time before crossing starts with observed approach-area entry. It can include walking and waiting; signal delay is not measured.</p></>}
          {'stopLine' in row && <>{cameraSelect(row.id, row.zoneRuleId, { zoneRuleId: '' })}{ruleSelect('Queue area', row.zoneRuleId, polygons.filter(rule => rule.kind === 'queue' && site.sources.find(item => item.id === rule.sourceId)?.imageToGroundHomography), value => update('queues', row.id, { zoneRuleId: value }))}{onPickQueueGeometry && <button type="button" className={styles.secondaryButton} onClick={() => { const current = generation.current; onPickQueueGeometry(points => { if (mounted.current && current === generation.current) update('queues', row.id, { stopLine: [points[0], points[1]], upstreamPoint: points[2] }); }); }}><IconMapPin size={16} />Draw queue axis on map</button>}<p className={styles.note}>Set two stop-line endpoints and one point upstream, in site metres. The queue grows from the stop line toward the upstream point.</p>{(['Stop line A', 'Stop line B', 'Upstream point'] as const).map((label, index) => { const point = index < 2 ? row.stopLine[index] : row.upstreamPoint; return <div className={styles.coordinate} key={label}><span>{label}</span>{(['X', 'Y'] as const).map((axis, axisIndex) => <label key={axis}>{axis}<input type="number" step="any" aria-label={`${row.name} ${label} ${axis}`} value={finite(point[axisIndex]) ? point[axisIndex] : ''} onChange={event => { const next: Point = [...point]; next[axisIndex] = event.target.valueAsNumber; update('queues', row.id, index < 2 ? { stopLine: row.stopLine.map((old, i) => i === index ? next : old) } : { upstreamPoint: next }); }} /></label>)}</div>; })}<label>Spillback boundary from stop line (m)<input type="number" min="0.1" step="any" value={finite(row.spillbackDistanceM) ? row.spillbackDistanceM : ''} onChange={event => update('queues', row.id, { spillbackDistanceM: event.target.valueAsNumber })} /></label></>}
          {'role' in row && <>
            {cameraSelect(row.id, row.zoneRuleId, { zoneRuleId: '' })}
            {ruleSelect('Curb area', row.zoneRuleId, polygons.filter(rule => !rule.classes.length || rule.classes.some(name => VEHICLE_CLASSES.includes(name))), value => update('curbs', row.id, { zoneRuleId: value }))}
            <label>Configured use<select value={row.role} onChange={event => update('curbs', row.id, { role: event.target.value })}>{CURB_ROLES.map(role => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
            <label>Persistent occupancy after (s)<input type="number" min="0" max="3600" step="0.001" value={finite(row.dwellThresholdMs) ? row.dwellThresholdMs / 1000 : ''} onChange={event => update('curbs', row.id, { dwellThresholdMs: Math.round(event.target.valueAsNumber * 1000) })} /></label>
            <details className={styles.evidenceSettings}><summary>Evidence settings</summary><label>Maximum observation gap (s)<input type="number" min="0.05" max="60" step="0.001" value={finite(row.maximumObservationGapMs) ? row.maximumObservationGapMs / 1000 : ''} onChange={event => update('curbs', row.id, { maximumObservationGapMs: Math.round(event.target.valueAsNumber * 1000) })} /></label><p className={styles.note}>A longer gap ends the visit as incomplete. A first-seen vehicle inside the area is a partial visit, not an observed arrival.</p></details>
            <p className={styles.note}>The role labels the space. Presence does not establish loading activity, permission or a violation.</p>
          </>}
        </fieldset>;
      })}
      <button type="button" className={styles.secondaryButton} disabled={saving} onClick={() => add(setupSection)}><IconPlus size={16} />Add {setupSection === 'movements' ? 'movement' : setupSection === 'crossings' ? 'crossing' : setupSection === 'curbs' ? 'curb area' : 'queue'}</button>
      {conflict && <p className={styles.error} role="alert">Settings changed elsewhere. <button type="button" onClick={() => openSetup(setupSection)}>Reload saved settings</button> before saving.</p>}
      {invalid && <p className={styles.note} role="status">{invalid}</p>}{saveError && <p className={styles.error} role="alert">{saveError}</p>}
      <button type="submit" className={styles.primaryButton} disabled={saving || Boolean(invalid) || conflict}>{saving ? 'Saving settings…' : 'Save measurement settings'}<IconArrowRight size={16} /></button>
      <span className={styles.note}>Revision {draft.revision}. Existing observations are not retroactively assigned to a new measurement.</span>
    </form> : <>
      {!report && <div className={styles.empty} role="status"><strong>{loading ? 'Loading intersection measures…' : 'Insights are not available yet'}</strong><p>{loading ? 'Reading the configured rules and observed camera time.' : 'The mobility service must be running for this site. Refresh after it is connected.'}</p>{!loading && <button type="button" onClick={mobility.refresh}><IconRefresh size={15} />Retry insights</button>}</div>}
      {report && <>
        <div className={styles.topics} role="group" aria-label="Insight topic">{TOPICS.map(item => <button type="button" key={item.id} aria-pressed={topic === item.id} onClick={() => selectTopic(item.id)}>{item.label}</button>)}</div>
        {challenge && presentation && <section className={styles.topicContext} aria-label="City problem context"><h3>{presentation.question}</h3><span className={styles.contextWindow}>{report.analyticsScope ? 'Up to' : 'Last'} {report.windowMinutes} min</span><p>{topic === 'movements' ? 'Turning-movement counts help traffic teams review lane demand and signal timing.' : challenge.problem}</p></section>}
        {report.configurationIssues.length > 0 && <details className={styles.issue}><summary>{report.configurationIssues.length} measurement{report.configurationIssues.length === 1 ? '' : 's'} need setup</summary>{report.configurationIssues.map((issue, index) => <p key={`${issue.kind}:${issue.id}:${index}`}><strong>{[...report.config.movements, ...report.config.crossings, ...report.config.queues, ...(report.config.curbs ?? [])].find(row => row.id === issue.id)?.name ?? issue.id}</strong><span>{issue.reason}</span></p>)}<button type="button" onClick={() => openSetup()}>Review settings<IconArrowRight size={14} /></button></details>}
        {topic === 'movements' && <section className={styles.section} aria-label="Movement demand"><div className={styles.visuallyHidden}><h3>Movement demand</h3></div>
          {report.movements.length > 0 && <div className={styles.tableScroll}><table className={styles.movementTable}><thead><tr><th>Movement</th><th>Completed</th><th>In progress</th><th>Observed travel</th><th><span className={styles.visuallyHidden}>Map</span></th></tr></thead><tbody>{report.movements.map(row => { const Direction = /left/i.test(row.name) ? IconCornerUpLeft : /right/i.test(row.name) ? IconCornerUpRight : IconArrowUp; return <tr key={row.id}><td><div className={styles.movementName}><Direction size={23} stroke={1.7} /><div><strong>{row.name}</strong></div></div><details className={styles.rowDetails}><summary>{source(row.sourceId)} · Classes &amp; evidence</summary><Status status={row.status} /><Breakdown values={row.byClass} /><p>{number(row.incompleteCount)} incomplete · P95 travel {seconds(row.p95TravelSeconds)}</p></details></td><td>{row.status === 'unavailable' ? '—' : number(row.completedCount)}</td><td>{row.status === 'unavailable' ? '—' : number(row.activeCount)}</td><td>{seconds(row.medianTravelSeconds)}</td><td>{focus(report.config.movements.find(item => item.id === row.id)?.entryRuleId)}</td></tr>; })}</tbody></table></div>}
          <p className={styles.note}>Camera-owned completed movements. No combined unique count across cameras.</p>
          {!report.movements.length && empty('Follow a complete movement', 'Pair an entry and exit rule to separate approach movements by object class.', 'movements')}
          {challenge && <section className={styles.useInsight}><h3>Use this insight</h3><p>{challenge.action}</p><a href={challenge.researchUrl} target="_blank" rel="noreferrer">Why this matters · {challenge.researchTitle}<IconArrowRight size={15} /></a></section>}
          {report.lineCounts.length > 0 && <details className={styles.gateDetails}><summary>Individual gate counts <span>{report.lineCounts.length}</span></summary>
          {report.lineCounts.map(row => <article className={styles.card} key={row.ruleId}><header><div><h4>{row.name}</h4><span>{source(row.sourceId)} · directed gate</span></div><Status status={row.status} /></header><div className={styles.mainMetric}><strong>{row.status === 'unavailable' ? '—' : number(row.count)}</strong><span>line crossings</span></div>{row.status !== 'unavailable' && <Breakdown values={row.byClass} />}{focus(row.ruleId)}</article>)}
          </details>}
        </section>}
        {topic === 'obstructions' && <section className={styles.section} aria-label="Crossing access"><div className={styles.sectionHeading}><h3>Crossing access</h3><span>Observed stopped vehicles</span></div>
          {report.obstructions.map(row => <article className={styles.card} key={row.ruleId}><header><div><h4>{row.name}</h4><span>{source(row.sourceId)}</span></div><Status status={row.status} /></header><div className={styles.mainMetric}><strong>{row.status === 'unavailable' ? '—' : seconds(row.blockedSeconds)}</strong><span>observed stopped-zone time · lower bound</span></div><dl className={styles.factGrid}><div><dt>Episodes</dt><dd>{row.status === 'unavailable' ? '—' : number(row.episodeCount)}</dd></div><div><dt>Ongoing</dt><dd>{row.status === 'unavailable' ? '—' : number(row.ongoingEpisodes)}</dd></div><div><dt>Completed</dt><dd>{row.status === 'unavailable' ? '—' : number(row.completedEpisodes)}</dd></div><div><dt>Unresolved</dt><dd>{row.status === 'unavailable' ? '—' : number(row.unknownEpisodes)}</dd></div></dl><p className={styles.note}>Confirmed active intervals only; gaps and candidate time are excluded. Simultaneous stops do not add duplicate time.</p>{focus(row.ruleId)}</article>)}
          {!report.obstructions.length && <div className={styles.empty}><strong>No stopped-zone measure</strong><p>Use Edit zones to add an enabled Stopped vehicle polygon at the crossing. Observed episodes will appear here.</p></div>}
        </section>}
        {topic === 'queues' && <section className={styles.section} aria-label="Approach queues"><div className={styles.sectionHeading}><h3>Approach queues</h3><span>Ground-position estimates</span></div>
          {report.queues.map(row => {
            const known = currentEvidence(row.sourceId) && row.currentCountsAvailable !== false && !['unknown', 'disabled'].includes(row.status);
            const visible = currentCountsAvailable(row, currentEvidence(row.sourceId));
            return <article className={styles.card} data-attention={known && row.status === 'spillback'} key={row.id}>
              <header><div><h4>{row.name}</h4><span>{source(row.sourceId)}</span></div><Status status={known || row.status === 'disabled' ? row.status : 'unknown'} /></header>
              <div className={styles.mainMetric}><strong>{known && row.observedExtentM !== null ? `${row.extentIsLowerBound ? '≥ ' : ''}${number(row.observedExtentM, 1)} m` : '—'}</strong><span>{row.extentIsLowerBound ? 'at least this queue extent' : 'current observed queue extent'}</span></div>
              <dl className={styles.factGrid}><div><dt>Currently observed queue objects</dt><dd>{visible ? observedCount(row.count, row) : '—'}</dd></div><div><dt>Window maximum</dt><dd>{row.maximumObservedExtentM === null ? '—' : `${number(row.maximumObservedExtentM, 1)} m`}</dd></div></dl>
              {visible && <MembershipNote row={row} />}<p className={styles.note}>Spillback boundary {number(row.spillbackDistanceM, 1)} m from the stop line.</p>
              {row.qualityReasons.length > 0 && <details className={styles.curbEvidence}><summary>Queue evidence</summary>{row.qualityReasons.map(reason => <p className={styles.note} key={reason}>{reason}</p>)}</details>}
              {onQueueFocus ? <button type="button" className={styles.mapLink} onClick={() => { lastQueue.current = row; setSelectedQueueId(row.id); }}><IconMapPin size={14} />Show queue on map</button> : focus(row.zoneRuleId)}
            </article>;
          })}
          {!report.queues.length && empty('Measure an approach queue', 'Choose a queue zone and draw its stop line and upstream direction on the map.', 'queues')}
        </section>}
        {topic === 'crossings' && <section className={styles.section} aria-label="Pedestrian service"><div className={styles.sectionHeading}><h3>Pedestrian service</h3><span>Observed journeys</span></div>
          {report.crossings.map(row => {
            const visible = currentCountsAvailable(row, currentEvidence(row.sourceId));
            return <article className={styles.card} key={row.id}>
              <header><div><h4>{row.name}</h4><span>{source(row.sourceId)}</span></div><Status status={(currentEvidence(row.sourceId) && row.currentCountsAvailable !== false) || row.status === 'disabled' ? row.status : 'unknown'} /></header>
              <div className={styles.mainMetric}><strong>{wait(row.waitP50Ms)}</strong><span>median time before crossing · {number(row.waitSampleCount)} valid samples</span></div>
              <dl className={styles.factGrid}><div><dt>Observed in approach area</dt><dd>{visible ? observedCount(row.waitingCount, row) : '—'}</dd></div><div><dt>Currently observed crossing</dt><dd>{visible ? observedCount(row.crossingCount, row) : '—'}</dd></div><div><dt>Completed crossings</dt><dd>{number(row.completedCount)}</dd></div><div><dt>P95 time before crossing</dt><dd>{wait(row.waitP95Ms)}</dd></div></dl>
              {visible && <MembershipNote row={row} />}
              <div className={styles.facts}><span>{number(row.incompleteCount)} incomplete</span><span>{number(row.abandonedCount)} left approach area</span><span>{number(row.returnedCount)} returned</span></div>
              {(row.firstSeenWaitingCount ?? 0) > 0 && <p className={styles.note}>{number(row.firstSeenWaitingCount)} journeys began with a person already in the approach area. Their arrival time is unknown; they are excluded from full entry-to-crossing samples.{finite(row.lowerBoundWaitP50Ms) ? ` Median minimum time before crossing: ≥ ${wait(row.lowerBoundWaitP50Ms)}.` : ''}</p>}
              {(row.briefGapRecoveredWaitCount ?? 0) > 0 && <p className={styles.note}>{number(row.briefGapRecoveredWaitCount)} wait journeys recovered the same track within the configured gap limit.</p>}
              {row.qualityReasons.length > 0 && <details className={styles.curbEvidence}><summary>Walking evidence</summary>{row.qualityReasons.map(reason => <p className={styles.note} key={reason}>{reason}</p>)}</details>}
              <p className={styles.note}>Completed means an observed far-side exit. Approach time includes observed walking or waiting, measured in source video time. Signal delay is not measured.</p>{focus(row.crossingRuleId)}
            </article>;
          })}
          {!report.crossings.length && empty('Measure waiting and crossing', 'Pair a waiting area with a crossing polygon. Interrupted journeys stay incomplete.', 'crossings')}
        </section>}
        {topic === 'curbs' && <section className={styles.section} aria-label="Curb access">
          <div className={styles.sectionHeading}><h3>Curb access</h3><span>Occupancy &amp; observed visits</span></div>
          {(report.curbs ?? []).map(row => {
            const coverage = report.coverage.find(item => item.sourceId === row.sourceId);
            // The API also uses zero as an unavailable placeholder. Only a
            // valid curb sample at this fresh source observation can show it.
            const visible = currentEvidence(row.sourceId) && coverage?.status === 'live'
              && typeof row.asOfSourceTimeNs === 'string' && /^\d+$/.test(row.asOfSourceTimeNs)
              && row.asOfSourceTimeNs === coverage.windowEndNs
              && Number.isInteger(row.observedOccupancy) && row.observedOccupancy >= 0
              && !report.configurationIssues.some(issue => issue.kind === 'curb' && issue.id === row.id);
            const known = visible && row.status !== 'unknown';
            const membership: string[] = [];
            if ((row.pendingTrackCount ?? 0) > 0) membership.push(`${number(row.pendingTrackCount)} temporarily missing`);
            if ((row.lostTrackCount ?? 0) > 0) membership.push(`${number(row.lostTrackCount)} interrupted visits unresolved`);
            const threshold = report.config.curbs?.find(item => item.id === row.id)?.dwellThresholdMs;
            return <article className={styles.card} data-attention={known && (row.persistentOccupancyCount ?? 0) > 0} key={row.id}>
              <header><div><h4>{row.name}</h4><span>{source(row.sourceId)} · {curbRole(row.role)}</span></div><Status status={known ? row.status : 'unknown'} label={known ? row.status === 'empty' ? 'Observed empty' : 'Occupied' : undefined} /></header>
              <div className={styles.mainMetric}><strong aria-label="Vehicles detected now">{visible ? number(row.observedOccupancy) : '—'}</strong><span>vehicles detected now</span></div>
              {visible && Object.values(row.byClass).some(value => value > 0) && <Breakdown values={row.byClass} />}
              {known && row.occupancyIsLowerBound && <p className={styles.note}>Total occupancy: ≥ {number(row.occupancy)}. Other tracked vehicles remain unresolved.</p>}
              {visible && !known && <p className={styles.note}>{row.observedOccupancy === 0 ? 'No vehicles are detected in the latest observation. Total occupancy is still unknown; zero detections do not confirm a clear curb.' : 'Total occupancy is unknown; other tracked vehicles remain unresolved.'}</p>}
              {membership.length > 0 && <p className={styles.note}>{membership.join(' · ')}.</p>}
              <dl className={styles.curbHighlights}><div><dt>Observed occupied time</dt><dd>{seconds(row.occupiedSeconds)}</dd></div><div><dt>Current observed dwell</dt><dd>{known ? wait(row.longestActiveObservedDwellMs) : '—'}</dd></div><div><dt>Zone turnover</dt><dd>{number(row.turnoverCount)}</dd></div></dl>
              <dl className={styles.factGrid}><div><dt>Observed arrivals</dt><dd>{number(row.arrivalCount)}</dd></div><div><dt>Observed departures</dt><dd>{number(row.departureCount)}</dd></div><div><dt>{finite(threshold) ? `At least ${wait(threshold)} observed dwell` : 'Persistent occupancy'}</dt><dd>{known ? number(row.persistentOccupancyCount) : '—'}</dd></div><div><dt>Confirmed stopped now</dt><dd>{known ? number(row.stoppedCount) : '—'}</dd></div></dl>
              {known && row.stoppedCount === null && <p className={styles.note}>Stopped status needs fresh speed evidence.</p>}
              <details className={styles.visitDetails}><summary>Visit outcomes <span>{number(row.completedVisitCount)} complete</span></summary><dl className={styles.factGrid}><div><dt>Completed visits</dt><dd>{number(row.completedVisitCount)}</dd></div><div><dt>Zone turnover</dt><dd>{number(row.turnoverCount)}</dd></div><div><dt>Incomplete visits</dt><dd>{number(row.incompleteVisitCount)}</dd></div><div><dt>Partial visits</dt><dd>{number(row.partialVisitCount)}</dd></div><div><dt>Complete-visit median dwell</dt><dd>{wait(row.completedDwellP50Ms)}</dd></div><div><dt>Complete-visit P95 dwell</dt><dd>{wait(row.completedDwellP95Ms)}</dd></div></dl><p className={styles.note}>Arrivals and departures require observed transitions. Partial or interrupted visits do not supply completed-visit dwell samples.</p></details>
              <details className={styles.curbEvidence}><summary>Evidence and limits</summary>{row.qualityReasons.map(reason => <p className={styles.note} key={reason}>{reason}</p>)}<p className={styles.note}>Occupied time is a union of observed intervals; gaps are excluded. Current class, dwell and stopped counts describe visible vehicles. The configured role does not establish actual loading, permission or a parking/access violation.</p></details>
              {focus(row.zoneRuleId)}
            </article>;
          })}
          {!report.curbs?.length && empty('See how curb space is used', 'Choose a vehicle-enabled polygon for a loading area, bus stop, cycle lane or general curb.', 'curbs')}
        </section>}
        {topic !== 'movements' && challenge && <section className={styles.useInsight}><h3>Use this insight</h3><p>{challenge.action}</p><a href={challenge.researchUrl} target="_blank" rel="noreferrer">Why this matters · {challenge.researchTitle}<IconArrowRight size={15} /></a></section>}
        <Coverage rows={report.coverage} />
        <footer className={styles.reportReceipt}>Received {receivedAt ? new Date(receivedAt).toLocaleTimeString() : '—'} · configuration {report.configRevision}. Exports include camera scope, window and coverage.</footer>
        <details className={styles.limits}><summary>How to read these measures</summary><p>Each measurement belongs to one camera. Views are not fused or summed into unique site-wide travelers. Bicycle detections are not validated cyclist counts. Vehicle classes and map positions need local validation.</p>{report.limitations.map(value => <p key={value}>{value}</p>)}</details>
      </>}
    </>}
  </div>;
}
