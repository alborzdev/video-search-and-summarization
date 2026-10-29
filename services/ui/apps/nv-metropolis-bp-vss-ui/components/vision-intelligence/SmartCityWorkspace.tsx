// SPDX-License-Identifier: MIT
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { IconAlertCircle, IconArrowRight, IconPencil, IconPlayerPause, IconPlayerPlay, IconRefresh, IconVideo, IconAdjustmentsHorizontal, IconMessageCircle, IconX } from '@tabler/icons-react';
import { CityCamera } from './smart-city/CityCamera';
import { CityMap, type QueueMapOverlay } from './smart-city/CityMap';
import type { MobilityQueue } from './smart-city/mobilityTypes';
import { CityInspector, type CityPanel } from './smart-city/CityInspector';
import { CityRuleEditor, type RuleDraft } from './smart-city/CityRuleEditor';
import { eventMediaTime, eventTitle, formatMediaTime, objectName } from './smart-city/geometry';
import { MODE_LABELS, type CityWorkspaceView, type CityEvent, type CityRule, type CitySnapshot, type CitySource, type Point } from './smart-city/types';
import { useCity } from './smart-city/useCity';
import styles from './smart-city/SmartCity.module.css';
import { displaySnapshot } from './smart-city/alignedSnapshot';
import { matchesObservationScope } from './smart-city/analyticsScope';
import { usePreviewHealth } from './smart-city/usePreviewHealth';
import { LocalVisionLauncher } from './LocalVisionLauncher';
import { previewContext } from './smart-city/processedPreview';
import { deriveMapObjects, type CityMapObject } from './smart-city/mapObjects';
import { CityDemoControls } from './smart-city/CityDemoControls';
import { CityAvatarControl } from './smart-city/CityAvatarControl';
import { CityIndexingControl } from './smart-city/CityIndexingControl';
import { CityCaptureEvidenceDrawer } from './smart-city/CityCaptureEvidenceDrawer';
import type { CityIndexingMatch } from './smart-city/cityIndexing';
import { CityMobilityPanel, type InsightTopic } from './smart-city/CityMobilityPanel';
import { areaLabel, overviewObservation, ruleTopic } from './smart-city/overviewObservation';
import { groundAreaHighlight } from './smart-city/areaProjection';
import { sourceName } from './smart-city/presentation';
import { getScenarioPresentation, rulesForScenario } from './smart-city/scenarioPresentation';
import { CityEdgePage } from './smart-city/CityEdgePage';
import { ShowcaseEvidence } from './smart-city/ShowcaseEvidence';
import { SceneDescriptionBar } from './smart-city/SceneDescriptionBar';
import { ScenarioEvidence } from './smart-city/ScenarioEvidence';
import { CitySceneReports } from './smart-city/CitySceneReports';
import { CityDetectionControl, type DetectionStatus } from './smart-city/CityDetectionControl';

const EMPTY_POINTS: Point[] = [];
const SCENARIO_INSIGHT_TOPICS: Record<string, InsightTopic> = {
  'crossing-occupancy': 'crossings', 'queue-blockage': 'queues', 'emergency-access': 'obstructions',
  'queue-recovery': 'queues', 'curb-obstruction': 'curbs', 'pedestrian-service': 'crossings',
  'crossing-obstruction': 'obstructions', 'turning-demand': 'movements',
};

function analyzedCamera(source: CitySource, latest: CitySnapshot | null, frame: CitySnapshot | undefined, shown: CitySnapshot | null, now: number): boolean {
  const live = latest?.sources.find(item => item.id === source.id);
  const displayed = shown?.sources.find(item => item.id === source.id);
  if (!live || ['paused', 'stopped'].includes(live.status ?? '') || !frame || !matchesObservationScope(frame, live) || frame.processedPreviewUnavailable || !displayed || displayed.status === 'waiting-for-frame-clock') return false;
  const preview = frame.presentedPreview;
  if (preview) return preview.sourceId === source.id && preview.sessionId === live.sessionId && preview.sessionId === displayed.sessionId &&
    preview.sequence === String(displayed.sequence) && preview.sourceTimeNs === displayed.lastSourceTimeNs && now >= preview.presentedAtMs && now - preview.presentedAtMs <= 2000;
  const captured = frame.sources.find(item => item.id === source.id);
  const age = now - Date.parse(frame.timestamp);
  // A fresh exact pair is stronger evidence than the independently polled health
  // snapshot. The raw-video path still needs that source-health confirmation.
  return Boolean(live.status === 'live' && source.browserClockVerified && captured?.clockAligned && captured.timestampBasis === 'source-rtcp' &&
    captured.sessionId === live.sessionId && displayed.lastSourceTimeNs === captured.lastSourceTimeNs && frame.requestedSourceTimeNs && captured.lastSourceTimeNs &&
    age >= 0 && age <= 1000 && Math.abs(Number(frame.requestedSourceTimeNs) - Number(captured.lastSourceTimeNs)) <= 160_000_000);
}

function freshDraft(sourceId: string, rulesRevision?: number): RuleDraft {
  return { sourceId, name: '', kind: 'occupancy-threshold', classes: ['person'], points: [], minimumDurationMs: 1000, countThreshold: 1, direction: [0, -1], rulesRevision };
}
export function SmartCityWorkspace({ vstApiUrl, onOpenExplainer, activeView, onViewChange }: { vstApiUrl?: string | null; onOpenExplainer?: () => void; activeView?: CityWorkspaceView; onViewChange?: (view: CityWorkspaceView) => void }) {
  const pageRoot = useRef<HTMLDivElement>(null);
  const [localView, setLocalView] = useState<CityWorkspaceView>('overview'); const view = activeView ?? localView;
  const setView = useCallback((next: CityWorkspaceView) => { setLocalView(next); onViewChange?.(next); }, [onViewChange]);
  const [searchMode, setSearchMode] = useState<'ask' | 'find' | 'reports' | 'scenes'>('ask');
  useEffect(() => {
    const main = pageRoot.current?.closest('main');
    if (main) main.scrollTop = 0;
    if (pageRoot.current) pageRoot.current.scrollTop = 0;
  }, [view, searchMode]);

  const [askCameraId, setAskCameraId] = useState(''); const [detailsOpen, setDetailsOpen] = useState(false);
  const [demoStatus, setDemoStatus] = useState('Connecting scenario controls');
  const [measurementHeader, setMeasurementHeader] = useState<HTMLDivElement | null>(null);
  const city = useCity(); const previewHealth = usePreviewHealth(city.site?.mode === 'live'); const [panel, setPanel] = useState<CityPanel>('now');
  const previewFpsLimit = previewHealth?.status === 'fresh' && previewHealth.enabled === true && previewHealth.failed === false ? previewHealth.fpsLimitPerSource : undefined;
  const [playing, setPlaying] = useState(false); const [mediaTime, setMediaTime] = useState(0);
  const [duration, setDuration] = useState(0); const [seekTime, setSeekTime] = useState(0); const [seekToken, setSeekToken] = useState(0);
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);
  const [backendPreparingScene, setPreparingScene] = useState(false);
  const [awaitingCameraReveal, setAwaitingCameraReveal] = useState(false);
  const [revealScene, setRevealScene] = useState<{ id: string; requestedAt: number } | null>(null);
  const preparingScene = backendPreparingScene || awaitingCameraReveal || revealScene !== null;
  const preparationChanged = useCallback((covered: boolean) => {
    setPreparingScene(covered);
    if (covered) setAwaitingCameraReveal(true);
  }, []);
  const [detectionState, setDetectionState] = useState<DetectionStatus['state'] | null>(null);
  const [guideRequest, setGuideRequest] = useState(0);
  const [preparationTarget, setPreparationTarget] = useState<HTMLDivElement | null>(null);
  const [previewRuleId, setPreviewRuleId] = useState<string | null>(null);
  const [areaFocusCleared, setAreaFocusCleared] = useState(false);
  const [focusedRuleId, setFocusedRuleId] = useState<string | null>(null);
  const [queueOverlay, setQueueOverlay] = useState<QueueMapOverlay | null>(null);
  const [queueDrawing, setQueueDrawing] = useState<Point[] | null>(null);
  const queueApply = React.useRef<((points: [Point, Point, Point]) => void) | null>(null);
  const cancelQueueDrawing = useCallback(() => { queueApply.current = null; setQueueDrawing(null); }, []);
  const pickQueueGeometry = useCallback((apply: (points: [Point, Point, Point]) => void) => {
    queueApply.current = apply; setQueueDrawing([]); setQueueOverlay(null); setFocusedRuleId(null);
  }, []);
  const addQueuePoint = useCallback((point: Point) => {
    if (!queueDrawing) return;
    const next = [...queueDrawing, point];
    if (next.length < 3) { setQueueDrawing(next); return; }
    const apply = queueApply.current;
    cancelQueueDrawing(); apply?.(next as [Point, Point, Point]);
  }, [queueDrawing, cancelQueueDrawing]);
  const focusRule = useCallback((id: string) => { setFocusedRuleId(id); setAreaFocusCleared(false); setQueueOverlay(null); setSelectedTrackId(null); }, []);
  const focusQueue = useCallback((queue: MobilityQueue) => {
    setFocusedRuleId(queue.zoneRuleId); setSelectedTrackId(null);
    setQueueOverlay(queue.stopLineM?.length === 2 && queue.upstreamPointM ? {
      name: queue.name, sourceId: queue.sourceId, status: queue.status, stopLineM: queue.stopLineM,
      upstreamPointM: queue.upstreamPointM, tailPositionM: queue.tailPositionM, observedExtentM: queue.observedExtentM,
    } : null);
  }, []);
  const [selectedEventRecord, setSelectedEventRecord] = useState<CityEvent | null>(null);
  const [captureEvidence, setCaptureEvidence] = useState<CityIndexingMatch | null>(null);
  const clearCaptureEvidence = useCallback(() => setCaptureEvidence(null), []);
  const [insightTopic, setInsightTopic] = useState<InsightTopic>('movements');
  const [draft, setDraftState] = useState<RuleDraft | null>(null); const [ruleError, setRuleError] = useState<string | null>(null);
  const [showSavedAreas, setShowSavedAreas] = useState(false);
  const draftGeneration = React.useRef(0);
  const setDraft = useCallback((value: React.SetStateAction<RuleDraft | null>) => {
    ++draftGeneration.current;
    setDraftState(value);
  }, []);
  const previousView = React.useRef(view);
  React.useEffect(() => {
    if (previousView.current !== view) { setDraft(null); setRuleError(null); setDetailsOpen(false); }
    previousView.current = view;
  }, [view, setDraft]);
  React.useEffect(() => {
    if (view !== 'measurements' || draft) { cancelQueueDrawing(); setQueueOverlay(null); }
  }, [view, draft, cancelQueueDrawing]);
  React.useEffect(() => { cancelQueueDrawing(); setQueueOverlay(null); setFocusedRuleId(null); setPreviewRuleId(null); setAreaFocusCleared(false); }, [city.site?.id, city.site?.revision, cancelQueueDrawing]);
  const currentTime = React.useRef(0);
  const shownSnapshot = useMemo(() => displaySnapshot(city.site, city.snapshot, city.sourceSnapshots), [city.site, city.snapshot, city.sourceSnapshots]);
  const mapSnapshot = view === 'overview' || view === 'measurements' || draft ? shownSnapshot : city.snapshot;
  const previousMapObjects = React.useRef<CityMapObject[]>([]);
  const mapObjects = useMemo(() => deriveMapObjects(city.site, mapSnapshot, previousMapObjects.current), [city.site, mapSnapshot]);
  React.useLayoutEffect(() => { previousMapObjects.current = mapObjects; }, [mapObjects]);
  const selectedTrackIds = useMemo(() => selectedTrackId ? mapObjects.find(object => object.memberTrackIds.includes(selectedTrackId))?.memberTrackIds ?? [selectedTrackId] : [], [mapObjects, selectedTrackId]);
  const onTime = useCallback((seconds: number) => { currentTime.current = seconds; setMediaTime(seconds); city.atMediaTime(seconds); }, [city.atMediaTime]);
  const secondaryTime = useCallback((_seconds: number) => {}, []);
  const onPlaybackEnd = useCallback(() => setPlaying(false), []);
  const onDuration = useCallback((seconds: number) => setDuration(value => value ? Math.min(value, seconds) : seconds), []);
  const seek = useCallback((seconds: number) => { setSeekTime(seconds); setSeekToken(value => value + 1); setMediaTime(seconds); currentTime.current = seconds; city.atMediaTime(seconds, true); }, [city.atMediaTime]);
  const selectedTrack = mapSnapshot?.tracks.find(track => track.id === selectedTrackId) ?? null;
  // A report can select an older event outside the rolling live snapshot.
  const selectedEvent = shownSnapshot?.events.find(event => event.id === selectedEventRecord?.id) ?? selectedEventRecord;
  const selectTrack = useCallback((id: string) => { setSelectedTrackId(id); setSelectedEventRecord(null); setPanel('now'); if (city.snapshot?.analyticsScope?.kind === 'normal') setDetailsOpen(true); }, [city.snapshot?.analyticsScope?.kind]);
  const selectEvent = useCallback((event: CityEvent) => { setSelectedEventRecord(event); setSelectedTrackId(event.trackIds[0] ?? null); setPanel('now'); }, []);
  const clearSelection = useCallback(() => { setSelectedTrackId(null); setSelectedEventRecord(null); }, []);
  const clearMapFocus = useCallback(() => { setFocusedRuleId(null); setPreviewRuleId(null); setAreaFocusCleared(true); setQueueOverlay(null); clearSelection(); }, [clearSelection]);
  const scenarioStarted = useCallback((id: string) => {
    setRevealScene({ id, requestedAt: Date.now() });
    setPanel('now'); setView('overview');
    const topic = SCENARIO_INSIGHT_TOPICS[id]; if (topic) setInsightTopic(topic);
    setDraft(null); setRuleError(null); setCaptureEvidence(null); setFocusedRuleId(null); setPreviewRuleId(null); setAreaFocusCleared(false); setQueueOverlay(null); clearSelection();
  }, [clearSelection, setDraft, setView]);
  const editRule = (rule: CityRule) => {
    if (rule.geometry.space !== 'image-normalized') { setRuleError('This rule uses site coordinates. Edit its camera polygon after calibration conversion.'); return; }
    setRuleError(null); setDraft({ id: rule.id, sourceId: rule.sourceId, name: rule.name, kind: rule.kind, classes: rule.classes, points: rule.geometry.points, rulesRevision: city.rules.revision,
      minimumDurationMs: rule.conditions.minimumDurationMs ?? 0, countThreshold: rule.conditions.countThreshold ?? 1, direction: rule.geometry.direction ?? [0, -1] });
  };
  const save = async () => {
    if (!draft) return;
    const generation = draftGeneration.current;
    const existing = city.rules.rules.find(rule => rule.id === draft.id);
    const rule: CityRule = { id: draft.id ?? `city-${crypto.randomUUID()}`, name: draft.name.trim(), kind: draft.kind, sourceId: draft.sourceId,
      classes: draft.classes, geometry: { space: 'image-normalized', points: draft.points, ...(draft.kind === 'line-crossing' || draft.kind === 'wrong-way' ? { direction: draft.direction } : {}) },
      conditions: { ...existing?.conditions, minimumDurationMs: draft.minimumDurationMs, countThreshold: draft.countThreshold, clearAfterMs: existing?.conditions.clearAfterMs ?? 500,
        maximumObservationGapMs: existing?.conditions.maximumObservationGapMs ?? 1500, ...(draft.kind === 'stopped-in-zone' || draft.kind === 'queue' ? { speedBelowMps: existing?.conditions.speedBelowMps ?? .5 } : {}) },
      enabled: existing?.enabled ?? true, revision: (existing?.revision ?? 0) + 1 };
    try {
      await city.saveRules([...city.rules.rules.filter(item => item.id !== rule.id), rule], draft.rulesRevision);
      if (generation !== draftGeneration.current) return;
      setDraft(null); setRuleError(null);
      if (city.site?.mode !== 'live') city.atMediaTime(currentTime.current, true);
    } catch (cause) {
      if (generation === draftGeneration.current && !(cause instanceof Error && cause.name === 'AbortError')) setRuleError(cause instanceof Error ? cause.message : 'The rule could not be saved.');
    }
  };
  const deleteRule = async (rule: CityRule) => {
    const generation = draftGeneration.current;
    try {
      await city.saveRules(city.rules.rules.filter(item => item.id !== rule.id));
      if (generation !== draftGeneration.current) return;
      setRuleError(null);
      if (draft?.id === rule.id) setDraft(null);
    } catch (cause) {
      if (generation === draftGeneration.current && !(cause instanceof Error && cause.name === 'AbortError')) setRuleError(cause instanceof Error ? cause.message : 'The rule could not be deleted.');
    }
  };
  const addPoint = useCallback((point: Point) => {
    if (city.saving) return;
    setDraft(value => {
      if (!value) return value;
      if (value.points.length >= (value.kind === 'line-crossing' ? 2 : 128)) return value;
      const points = [...value.points, point];
      if (value.kind === 'line-crossing' && points.length === 2) {
        const dx = points[1][0] - points[0][0]; const dy = points[1][1] - points[0][1]; const length = Math.hypot(dx, dy);
        return { ...value, points, direction: length > 1e-9 ? [dy / length, -dx / length] : value.direction };
      }
      return { ...value, points };
    });
  }, [setDraft, city.saving]);
  const visibleSources = useMemo(() => city.site?.sources.slice(0, 2) ?? [], [city.site?.sources]);
  const previewContexts = useMemo(() => city.site ? Object.fromEntries(visibleSources.map(source => [source.id, previewContext(city.site!, source, city.previewGeneration)])) : {}, [city.site, visibleSources, city.previewGeneration]);
  const playbackIdentity = `${city.site?.id ?? ''}:${city.site?.revision ?? ''}:${city.site?.mode ?? ''}:${visibleSources.map(source => source.id).join('|')}`;
  React.useEffect(() => {
    setPlaying(false); setDuration(0); setMediaTime(0); setSeekTime(0); setSeekToken(value => value + 1); currentTime.current = 0; clearSelection(); setDraft(null); setCaptureEvidence(null); setInsightTopic('movements');
  }, [playbackIdentity, clearSelection, setDraft]);
  React.useEffect(() => {
    if (city.site?.mode !== 'fixture-replay') return;
    const fixtureDuration = city.site.sources[0]?.fixtureDurationSeconds ?? city.site.sources[0]?.durationSeconds;
    if (typeof fixtureDuration === 'number') { setDuration(fixtureDuration); city.atMediaTime(currentTime.current, true); }
  }, [city.site, city.atMediaTime]);
  React.useEffect(() => {
    if (!playing || city.site?.mode !== 'fixture-replay' || !duration) return;
    let frame = 0; const started = performance.now(); const startMedia = currentTime.current;
    const tick = (now: number) => {
      const next = Math.max(0, Math.min(duration, startMedia + (now - started) / 1000));
      onTime(next);
      if (next >= duration) setPlaying(false); else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick); return () => cancelAnimationFrame(frame);
  }, [playing, city.site?.mode, duration, onTime, seekToken]);
  React.useEffect(() => {
    if (!revealScene || backendPreparingScene || !city.site) return;
    const scope = city.snapshot?.analyticsScope;
    if (scope?.kind === 'normal' && Date.parse(scope.startedAt ?? '') >= revealScene.requestedAt) {
      setRevealScene(null); return;
    }
    if (scope?.kind !== 'scenario' || scope.suppressed || scope.scenarioId !== revealScene.id) return;
    if (visibleSources.length && visibleSources.every(source => analyzedCamera(source, city.snapshot, city.sourceSnapshots[source.id], shownSnapshot, Date.now()))) setRevealScene(null);
  }, [revealScene, backendPreparingScene, city.site, city.snapshot, city.sourceSnapshots, city.rules.rules, visibleSources, shownSnapshot]);
  React.useEffect(() => {
    // Recovery, cancellation and failed preparation also reset camera scope.
    // Keep their cover until both current pairs arrive, just as for playback.
    if (!awaitingCameraReveal || backendPreparingScene || revealScene || !city.site) return;
    if (city.snapshot?.analyticsScope?.suppressed || !visibleSources.length) return;
    if (visibleSources.every(source => analyzedCamera(source, city.snapshot, city.sourceSnapshots[source.id], shownSnapshot, Date.now()))) setAwaitingCameraReveal(false);
  }, [awaitingCameraReveal, backendPreparingScene, revealScene, city.site, city.snapshot, city.sourceSnapshots, visibleSources, shownSnapshot]);
  if (city.loading && !city.site) return <div className={styles.loading} role="status"><span className="vi-spinner" />Loading Smart City…</div>;
  if (!city.site) return <div className={styles.unavailable}><IconAlertCircle size={34} /><h1>Smart City is unavailable</h1><p>{city.error ?? 'The city analytics service has not been connected.'}</p><LocalVisionLauncher className={styles.outlineButton} /><button type="button" className={styles.outlineButton} onClick={() => void city.refresh()}><IconRefresh size={18} />Retry connection</button></div>;
  const site = city.site;
  const analyzedCount = visibleSources.filter(source => analyzedCamera(source, city.snapshot, city.sourceSnapshots[source.id], shownSnapshot, Date.now())).length;
  const liveStatusDot = !analyzedCount ? styles.dotMuted : analyzedCount === visibleSources.length ? styles.dot : styles.dotWarning;
  const liveStatus = analyzedCount ? `${analyzedCount}/${visibleSources.length} camera${visibleSources.length === 1 ? '' : 's'} analyzed` : !city.connected ? 'Analytics connection lost' : 'Waiting for camera analysis';
  const frameRules = shownSnapshot?.rules ?? [];
  // Preserve each displayed frame's rule version. Configured rules without a frame
  // remain visible with no metric instead of disappearing or borrowing stale counts.
  const displayedRuleIds = new Set(frameRules.map(rule => rule.id));
  const inspectorRules = site.mode === 'live' ? [...frameRules, ...city.rules.rules.filter(rule => !displayedRuleIds.has(rule.id))] : shownSnapshot?.rules ?? city.rules.rules;
  // The scenario scope is assigned by the analytics service, not by the scene's
  // scripted cues. Return to the normal view as soon as that scope closes.
  const scenario = site.mode === 'live' && site.id === 'isaac-intersection-a' && view === 'overview' && !draft && city.snapshot?.analyticsScope?.kind === 'scenario'
    ? getScenarioPresentation(city.snapshot.analyticsScope.scenarioId) : null;
  const overviewRules = scenario ? rulesForScenario(inspectorRules, scenario) : inspectorRules.filter(rule => !rule.id.startsWith('expo-'));
  const readySourceIds = visibleSources.filter(source => site.mode !== 'live' || analyzedCamera(source, city.snapshot, city.sourceSnapshots[source.id], shownSnapshot, Date.now())).map(source => source.id);
  const descriptionSource = visibleSources.find(source => city.snapshot?.sources.some(live => live.id === source.id && live.status === 'live')) ?? visibleSources[0];
  const descriptionSession = city.snapshot?.sources.find(source => source.id === descriptionSource?.id)?.sessionId;
  const showDescription = site.mode === 'live' && view === 'overview' && !draft && !scenario;
  const observation = overviewObservation(shownSnapshot, overviewRules, readySourceIds, focusedRuleId ?? scenario?.primaryRuleId);
  const highlightedRuleId = draft ? draft.id : previewRuleId ?? focusedRuleId ?? (areaFocusCleared ? undefined : observation.rule?.id);
  const areaHighlight = draft || scenario ? null : groundAreaHighlight(inspectorRules.find(rule => rule.id === highlightedRuleId), site.sources);
  const selectedMapObject = mapObjects.find(object => object.memberTrackIds.includes(selectedTrackId ?? '')) ?? null;
  const selectedSource = visibleSources.find(source => source.id === (selectedTrack?.sourceId ?? observation.rule?.sourceId));
  const shownAskId = visibleSources.some(source => source.id === askCameraId) ? askCameraId : visibleSources[0]?.id;
  const previewedCameraId = draft?.sourceId ?? shownAskId;
  const openMeasurements = () => { const id = observation.rule?.id ?? scenario?.primaryRuleId; if (id) setFocusedRuleId(id); setInsightTopic(scenario?.topic ?? observation.topic); setView('measurements'); setDetailsOpen(false); };
  const changePanel = (next: CityPanel) => { setPanel(next); if (next === 'ask' || next === 'reports') { setSearchMode(next); setView('search'); setDetailsOpen(false); } else if (next === 'insights') setView('measurements'); };
  const viewArea = (ruleId: string) => { focusRule(ruleId); setView('overview'); setDetailsOpen(false); };
  const inspectorProps = { insightTopic, onInsightTopicChange: setInsightTopic, onFocusRule: focusRule, onPickQueueGeometry: pickQueueGeometry, onQueueFocus: focusQueue, vstApiUrl, onPanel: changePanel, site, snapshot: mapSnapshot, rules: inspectorRules, selectedEvent, selectedTrack, selectedMapObject, onEvent: selectEvent, onSeek: seek, onClearSelection: clearSelection, mediaTime, liveAnalysisReady: site.mode === 'live' ? analyzedCount > 0 && city.connected : undefined, embedded: true, onCameraChange: setAskCameraId, onShowMeasurements: () => setView('measurements'), onViewArea: viewArea };
  return <div ref={pageRoot} className={styles.workspace} data-testid="smart-city-workspace" data-view={view} data-showcase={['crossing-occupancy', 'queue-blockage', 'emergency-access'].includes(scenario?.id ?? '') ? scenario?.id : undefined} data-search-mode={searchMode} data-editing={Boolean(draft)}>
    {!onViewChange && <nav className={styles.workspaceNav} aria-label="Smart City views">{(['overview', 'measurements', 'search', 'edge'] as const).map(item => <button key={item} type="button" aria-current={view === item ? 'page' : undefined} onClick={() => setView(item)}>{item === 'overview' ? 'Overview' : item === 'measurements' ? 'Measurements' : item === 'edge' ? 'Why edge AI' : 'Search & reports'}</button>)}</nav>}
    {view === 'edge' && !draft && <CityEdgePage cameraCount={visibleSources.length} liveCameraCount={city.connected ? city.snapshot?.sources.filter(source => source.status === 'live').length ?? 0 : 0} onView={setView} onReview={() => { setSearchMode('reports'); setView('search'); }} />}
    <header className={styles.workspaceHeading}><div ref={view === 'measurements' && !draft ? setMeasurementHeader : undefined} className={view === 'measurements' && !draft ? styles.measurementHeaderMount : styles.headingCopy}>{draft ? <><button type="button" className={styles.backButton} onClick={() => { setDraft(null); setRuleError(null); }}><IconArrowRight size={17} style={{ transform: 'rotate(180deg)' }} />Back to overview</button><h1>Edit monitoring area</h1><p>Choose the view. Draw the area. Define what matters.</p></> : view === 'overview' ? <><h1>{/^(Isaac Sim · )?Intersection A$/.test(site.name) ? 'City intersection' : site.name.replace(/^Isaac Sim · /, '')}</h1><p>{!visibleSources.length ? 'Connect city cameras' : site.mode === 'live' ? 'See traffic problems. Review the evidence.' : MODE_LABELS[site.mode]}</p></> : view === 'search' ? <><h1>Search &amp; reports</h1><p>Ask about current footage, find a captured moment, or review measured events.</p></> : null}</div>
      {view === 'overview' && !draft && <div className={styles.headingActions}><span className={styles.sceneStatus}><i className={liveStatusDot} />{!visibleSources.length ? 'No cameras connected' : site.mode === 'live' ? demoStatus : MODE_LABELS[site.mode]}</span>{site.mode === 'live' && site.id === 'isaac-intersection-a' && <button type="button" className={styles.primaryButton} disabled={preparingScene} onClick={() => setGuideRequest(value => value + 1)}><IconPlayerPlay size={18} />Choose a demo</button>}<button type="button" className={styles.outlineButton} onClick={() => { setSearchMode('ask'); setView('search'); }}><IconMessageCircle size={18} />Ask this scene</button><details className={styles.presenterMenu}><summary aria-label="Presenter tools"><IconAdjustmentsHorizontal size={18} /></summary><div><button type="button" disabled={!visibleSources.length} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); setDraft(freshDraft(visibleSources[0].id, city.rules.revision)); setRuleError(null); }}><IconPencil size={17} />Edit monitoring areas</button><button type="button" onClick={() => { clearSelection(); setDetailsOpen(true); setPanel('now'); }}>Events &amp; technical details</button><LocalVisionLauncher className={styles.quietButton} captureSelector='[data-testid="smart-city-workspace"] video, [data-testid="smart-city-workspace"] canvas[aria-label="Frame matched analyzed camera preview"]' />{onOpenExplainer && <button type="button" onClick={onOpenExplainer}>Illustrated deployment story<IconArrowRight size={16} /></button>}<button type="button" onClick={() => void city.refresh()}><IconRefresh size={17} />Refresh city state</button></div></details></div>}
    </header>
    {site.mode === 'live' && view !== 'edge' && <CityDetectionControl siteId={site.id} analyzedCount={view === 'search' && searchMode !== 'ask' ? city.snapshot?.sources.filter(source => source.status === 'live').length ?? 0 : analyzedCount} disabled={preparingScene} onChanged={city.refresh} onStatusChange={setDetectionState} />}
    {view !== 'overview' && /recovery needs attention/i.test(demoStatus) && <div className={styles.runtimeAlert} role="alert"><IconAlertCircle size={20}/><span>Camera recovery needs attention. Retained reports remain available.</span><button type="button" onClick={() => { setView('overview'); setGuideRequest(value => value + 1); }}>Open recovery controls</button></div>}
    {view === 'search' && !draft && <nav className={styles.searchTabs} aria-label="Search and reports views">{(['ask', 'find', 'reports', 'scenes'] as const).map(item => <button key={item} type="button" aria-current={searchMode === item ? 'page' : undefined} onClick={() => setSearchMode(item)}>{item === 'ask' ? 'Ask scene' : item === 'find' ? 'Find clips' : item === 'scenes' ? 'Scene reports' : 'Events & reports'}</button>)}</nav>}
    {city.error && <div className={styles.errorBanner} role="alert"><IconAlertCircle size={17} /><span>{city.error}</span><button type="button" onClick={() => void city.refresh()}>Retry<IconArrowRight size={15} /></button></div>}
    <div className={styles.content}>
      <div className={styles.cameraRail}>
        {draft && <div className={styles.editorTools}><span>Drawing tool</span><button type="button" aria-pressed={draft.kind !== 'line-crossing'} onClick={() => { if (draft.kind === 'line-crossing') setDraft({ ...draft, kind: 'occupancy-threshold', points: [] }); }}>Area</button><button type="button" aria-pressed={draft.kind === 'line-crossing'} onClick={() => { if (draft.kind !== 'line-crossing') setDraft({ ...draft, kind: 'line-crossing', points: [] }); }}>Directed line</button><label><input type="checkbox" checked={showSavedAreas} onChange={event => setShowSavedAreas(event.target.checked)} />Show saved areas</label></div>}
        <div className={styles.cameras}>{visibleSources.map((source, index) => {
          const shown = draft ? source.id === draft.sourceId : view === 'overview' || view === 'measurements' || view === 'search' && searchMode === 'ask' && source.id === shownAskId;
          return <div key={`${playbackIdentity}:${source.id}`} className={shown ? styles.cameraSlot : styles.cameraHidden}><CityCamera analysisEnabled={detectionState !== 'paused' && detectionState !== 'stopped'} source={source} mode={site.mode} index={index} snapshot={site.mode === 'live' ? city.sourceSnapshots[source.id] ?? city.snapshot : city.snapshot} vstApiUrl={vstApiUrl} onSourceTime={city.atSourceTime} onProcessedFrame={city.presentProcessedFrame} previewContext={previewContexts[source.id]} previewEnabled={!city.loading && shown} latestSource={city.snapshot?.sources.find(item => item.id === source.id)} deliveryHealth={previewHealth?.sources.find(item => item.sourceId === source.id)} deliveryStatus={previewHealth?.status} previewFpsLimit={previewFpsLimit} previewTransport={previewHealth?.transport} onEnded={onPlaybackEnd} rules={city.rules.rules} selectedTrack={selectedTrackId} selectedTrackIds={selectedTrackIds} onSelect={selectTrack} playing={playing} seekTime={seekTime} seekToken={seekToken} leaderTime={index === 1 ? mediaTime : undefined} fixtureTime={mediaTime} onTime={index === 0 ? onTime : secondaryTime} onDuration={onDuration} editing={draft?.sourceId === source.id} draft={draft?.sourceId === source.id ? draft.points : EMPTY_POINTS} draftKind={draft?.kind ?? 'occupancy'} onPoint={addPoint} fillFrame={false} areaHighlight={areaHighlight} focusedRuleId={highlightedRuleId} showAllRules={Boolean(draft) && showSavedAreas} scenarioRuleIds={scenario?.ruleIds} onEdit={() => { setDraft(freshDraft(source.id, city.rules.revision)); setRuleError(null); }} /></div>;
        })}{Array.from({ length: Math.max(0, (draft || view === 'search' && searchMode === 'ask' ? 1 : 2) - visibleSources.length) }, (_, index) => <section key={`empty-${index}`} className={styles.camera}><header><strong>Camera {visibleSources.length + index + 1}</strong></header><div className={styles.mediaEmpty}><IconVideo size={28} /><strong>No source connected</strong><span>Add a registered camera in the city site configuration.</span></div></section>)}</div>
        <p className={styles.sourceNote} aria-label={site.mode === 'live' ? 'Live analysis status' : 'Camera evidence status'}>{!visibleSources.length ? 'No camera connected' : site.mode === 'live' ? draft || view === 'search' && searchMode === 'ask' ? <><i className={readySourceIds.includes(previewedCameraId ?? '') ? styles.dot : styles.dotMuted} />{readySourceIds.includes(previewedCameraId ?? '') ? 'Selected camera analyzed · On this device' : 'Waiting for selected camera analysis'}</> : <><i className={liveStatusDot} />{liveStatus}<span> · {visibleSources.length} camera view{visibleSources.length === 1 ? '' : 's'}</span></> : <><IconVideo size={15} />Analyzed camera frames</>}</p>
        {view === 'search' && <details className={styles.technicalDetails}><summary>Source timing &amp; evidence</summary><p>Your question uses the recent five seconds from the selected camera. It does not automatically select an earlier event. Source clock time is unverified.</p></details>}
      </div>
      <div className={styles.mapRegion}><CityMap analysisEnabled={detectionState !== 'paused' && detectionState !== 'stopped'} site={site} snapshot={mapSnapshot} mapObjects={mapObjects} rules={draft ? city.rules.rules : overviewRules} selectedTrack={selectedTrackId} onSelect={selectTrack} inspectable={!draft && !queueDrawing} onFocusRule={focusRule} onPreviewRule={setPreviewRuleId} onClearFocus={clearMapFocus} onInspectRule={id => { const rule = inspectorRules.find(item => item.id === id); if (!rule) return; focusRule(id); setInsightTopic(ruleTopic(rule)); setView('measurements'); setDetailsOpen(false); }} focusedRuleId={draft ? draft.id : focusedRuleId ?? (areaFocusCleared ? undefined : observation.rule?.id ?? scenario?.primaryRuleId)} queueOverlay={queueOverlay} contextClassName={scenario ? styles.scenarioContext : showDescription ? styles.descriptionContext : undefined} keepContextVisible={Boolean(scenario) || showDescription} showAllRules={Boolean(draft) && showSavedAreas} onGroundPoint={queueDrawing ? addQueuePoint : undefined} groundDraft={queueDrawing ?? undefined} onCancelGround={cancelQueueDrawing} groundPrompt={queueDrawing ? ['Click the first end of the stop line', 'Click the other end of the stop line', 'Click upstream, along the approach'][queueDrawing.length] : undefined}>
        {scenario && <section className={styles.scenarioStory} aria-label="Scenario story" data-scenario-id={scenario.id}>
          <div className={styles.scenarioStoryQuestion}>
            <span>Scenario · {scenario.title}</span><h2>{scenario.question}</h2><p>{scenario.scene}</p>
          </div>
          <div className={styles.scenarioStoryEvidence}>
            {['crossing-occupancy', 'queue-blockage', 'emergency-access'].includes(scenario.id) ? <ShowcaseEvidence site={site} scenarioId={scenario.id} currentScope={city.snapshot?.analyticsScope} /> : <ScenarioEvidence site={site} scenarioId={scenario.id} currentScope={city.snapshot?.analyticsScope} />}
            <p><strong>Why it matters</strong> {scenario.value}</p>
          </div>
          <button type="button" className={styles.textButton} onClick={openMeasurements}>View measurements<IconArrowRight size={16} /></button>
        </section>}
        {showDescription && <SceneDescriptionBar siteId={site.id} epoch={city.snapshot?.analyticsScope?.epoch} sourceId={descriptionSource?.id} sessionId={descriptionSession} sourceName={descriptionSource ? sourceName(descriptionSource) : undefined} enabled={city.connected && !preparingScene && city.snapshot?.analyticsScope?.kind === 'normal' && city.snapshot.analyticsScope.suppressed === false && detectionState !== 'paused' && detectionState !== 'stopped'} />}
        {view === 'overview' && !draft && !scenario && !showDescription && <section className={styles.observationCard} aria-label="Current camera finding" data-tone={selectedTrack ? 'normal' : observation.tone}>
          <div className={styles.observationSummary}>
          <div><i className={selectedTrack ? styles.dot : observation.tone === 'attention' ? styles.dotWarning : observation.tone === 'waiting' ? styles.dotMuted : styles.dot} /><span>{selectedTrack ? 'Selected observation' : focusedRuleId ? 'Selected area' : observation.label}</span></div>
          <h2>{selectedTrack ? objectName(selectedTrack.class) : observation.title}</h2><p>{selectedTrack ? selectedSource ? sourceName(selectedSource) : 'Camera observation' : observation.rule ? `${areaLabel(observation.rule.name)} · ${sourceName(visibleSources.find(source => source.id === observation.rule?.sourceId) ?? { name: 'Camera' })}` : visibleSources.length === 2 ? 'Two-camera intersection view' : visibleSources.length ? 'Intersection camera view' : 'No connected camera'}</p>
          <p className={styles.observationPurpose}>{selectedTrack ? selectedMapObject?.shared ? `Linked in ${selectedMapObject.sourceIds.length} camera views · map display association` : 'Camera-owned track' : observation.detail}</p>
          </div>
          <div className={styles.observationActions}>
          {selectedTrack ? <button type="button" className={styles.textButton} onClick={() => { setPanel('now'); setDetailsOpen(true); }}>View track details<IconArrowRight size={16} /></button> : observation.rule && <button type="button" className={styles.textButton} onClick={openMeasurements}>View measurement<IconArrowRight size={16} /></button>}
          {observation.event && !selectedTrack && <button type="button" className={styles.textButton} onClick={() => { selectEvent(observation.event!); setSearchMode('reports'); setView('search'); }}>Review event<IconArrowRight size={16} /></button>}
          </div>
          <div className={styles.observationDismiss}>{selectedTrack ? <button type="button" aria-label="Clear object selection" onClick={clearSelection}><IconX size={16} /></button> : focusedRuleId && <button type="button" aria-label="Show automatic finding" title="Return to automatic camera findings" onClick={() => { setFocusedRuleId(null); setQueueOverlay(null); }}><IconX size={16} /></button>}</div>
        </section>}
      </CityMap></div>
      {view === 'measurements' && !draft && <div className={styles.measurementsPane}><CityMobilityPanel headerTarget={measurementHeader} site={site} rules={inspectorRules} currentScope={city.snapshot?.analyticsScope} topic={insightTopic} onTopicChange={setInsightTopic} onFocusRule={focusRule} onPickQueueGeometry={pickQueueGeometry} onQueueFocus={focusQueue} /></div>}
      {view === 'search' && !draft && <div className={styles.searchPane}>{searchMode === 'scenes' ? <CitySceneReports site={site} onReviewEvent={event => { selectEvent(event); setSearchMode('reports'); }} /> : searchMode === 'find' ? <div className={styles.captureLayout}><CityIndexingControl inline sources={visibleSources} onOpenEvidence={setCaptureEvidence} selectedMatch={captureEvidence} onSourceChange={clearCaptureEvidence} />{captureEvidence && visibleSources.some(source => source.id === captureEvidence.sensor_id) ? <CityCaptureEvidenceDrawer inline match={captureEvidence} sourceName={visibleSources.find(source => source.id === captureEvidence.sensor_id)?.name} vstApiUrl={vstApiUrl} onClose={() => setCaptureEvidence(null)} /> : <div className={styles.captureEmpty}><IconVideo size={30} /><h2>Find a moment, then review the footage.</h2><p>Search one retained camera capture. Open a result to inspect its exact recording interval.</p></div>}</div> : <CityInspector {...inspectorProps} panel={searchMode} />}</div>}
      {draft && <div className={styles.editorPane}><CityRuleEditor draft={draft} onChange={setDraft} onClose={() => { setDraft(null); setRuleError(null); }} onSave={() => void save()} onDelete={rule => void deleteRule(rule)} rules={city.rules.rules} sources={visibleSources} saving={city.saving} error={ruleError} onEdit={editRule} /></div>}
      {preparingScene && site.mode === 'live' && site.id === 'isaac-intersection-a' && <div ref={setPreparationTarget} className={styles.preparationCover} role="status" aria-label="Scene preparation cover" />}
    </div>
    {site.mode === 'live' && site.id === 'isaac-intersection-a' && <div className={styles.scenarioShelf} data-hidden={view !== 'overview' || Boolean(draft)}><CityDemoControls onReviewResults={() => { setSearchMode('scenes'); setView('search'); }} guideRequest={guideRequest} preparationTarget={preparationTarget} onScenarioStarted={scenarioStarted} onPreparationChange={preparationChanged} onStatusChange={setDemoStatus} /><CityAvatarControl /></div>}
    {site.mode !== 'live' && visibleSources.some(source => source.mediaUrl || site.mode === 'fixture-replay') && <div className={styles.timeline} aria-label="Shared camera playback timeline"><button type="button" className={styles.playButton} onClick={() => setPlaying(value => !value)} disabled={!duration} aria-label={playing ? 'Pause city playback' : 'Play city playback'}>{playing ? <IconPlayerPause size={23} /> : <IconPlayerPlay size={23} />}</button><span>{formatMediaTime(mediaTime)}</span><div className={styles.timelineTrack}><input type="range" min="0" max={duration || 1} step=".04" value={Math.min(mediaTime, duration || 1)} disabled={!duration} onChange={event => seek(Number(event.target.value))} aria-label="City playback time" />{(city.snapshot?.events ?? []).map(event => { const time = eventMediaTime(event); return typeof time === 'number' && duration > 0 ? <button type="button" key={event.id} className={styles.eventMarker} style={{ left: `${Math.min(100, time / duration * 100)}%` }} aria-label={`Review ${eventTitle(event)}`} title={eventTitle(event)} onClick={() => { selectEvent(event); seek(time); }} /> : null; })}</div><span>{formatMediaTime(duration)}</span></div>}
    {detailsOpen && !draft && <div className={styles.detailDrawer} role="dialog" aria-modal="false" aria-label="Camera observation details"><header><h2>Camera evidence</h2><button type="button" aria-label="Close observation details" onClick={() => setDetailsOpen(false)}><IconX size={20} /></button></header><CityInspector {...inspectorProps} panel={panel === 'insights' ? 'now' : panel} /></div>}
  </div>;
}
