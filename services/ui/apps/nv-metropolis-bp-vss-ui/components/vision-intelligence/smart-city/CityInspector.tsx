// SPDX-License-Identifier: MIT
import { CityEventEvidence } from './CityEventEvidence';
import React, { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { IconArrowRight, IconDownload, IconFileReport, IconMessageCircle, IconPlayerPlay, IconVideo, IconX } from '@tabler/icons-react';
import type { CityEvent, CityRule, CitySite, CitySnapshot, CityTrack, Point } from './types';
import type { VisionAnalystResponse } from '../analyst';
import { eventMeasure, eventMediaTime, eventTitle, formatMediaTimeTenths, safeMediaUrl, objectName } from './geometry';
import { cityRequest } from './useCity';
import styles from './SmartCity.module.css';
import { eventEvidencePending, eventStateDescription, eventStateLabel, recentEvents, ruleEvidenceReasons, ruleMeasure, sourceName } from './presentation';
import { CityAnswerEvidence } from './CityAnswerEvidence';
import { observedWindowLabel, type CityAnswerSource } from './answerEvidence';
import { CityMobilityPanel, type InsightTopic } from './CityMobilityPanel';
import type { MobilityQueue } from './mobilityTypes';
import type { CityMapObject } from './mapObjects';
import { analyticsScopeLabel } from './analyticsScope';

export type CityPanel = 'now' | 'insights' | 'ask' | 'reports';
const PANELS: readonly CityPanel[] = ['now', 'insights', 'ask', 'reports'];
const EVENT_PAGE_SIZE = 6;
interface CityReportHistory { events: CityEvent[]; eventCount: number; truncated?: boolean; }
function exportFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function displayTime(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function eventClock(event: CityEvent, start = false, live = false): string {
  const media = live ? null : eventMediaTime(event, start ? 'started' : 'triggered');
  return media === null ? displayTime(start ? event.startedAt : event.triggeredAt) : formatMediaTimeTenths(media);
}
export function CityInspector({ panel, onPanel, site, snapshot, rules, selectedEvent: requestedEvent, selectedTrack, onEvent, onSeek, onClearSelection, mediaTime, vstApiUrl, liveAnalysisReady, onFocusRule, onPickQueueGeometry, onQueueFocus, insightTopic, onInsightTopicChange, embedded = false, selectedMapObject, onCameraChange, onShowMeasurements, onViewArea }: {
  panel: CityPanel; onPanel: (panel: CityPanel) => void; site: CitySite; snapshot: CitySnapshot | null;
  rules: CityRule[]; selectedEvent: CityEvent | null; selectedTrack: CityTrack | null;
  onEvent: (event: CityEvent) => void; onSeek: (seconds: number) => void; onClearSelection: () => void; mediaTime: number;
  vstApiUrl?: string | null; liveAnalysisReady?: boolean;
  onFocusRule?: (ruleId: string) => void; onPickQueueGeometry?: (apply: (points: [Point, Point, Point]) => void) => void; onQueueFocus?: (queue: MobilityQueue) => void;
  embedded?: boolean; selectedMapObject?: CityMapObject | null; onCameraChange?: (sourceId: string) => void; onShowMeasurements?: () => void; onViewArea?: (ruleId: string) => void;
  insightTopic?: InsightTopic; onInsightTopicChange?: (topic: InsightTopic) => void;
}) {
  const selectedEvent = requestedEvent && requestedEvent.mode === site.mode && site.sources.some(source => source.id === requestedEvent.sourceId) ? requestedEvent : null;
  const tabsId = React.useId(); const tabButtons = React.useRef<Partial<Record<CityPanel, HTMLButtonElement | null>>>({});
  const [question, setQuestion] = useState(''); const [askedQuestion, setAskedQuestion] = useState('');
  const [answerState, setAnswerState] = useState<{ id: number; result: VisionAnalystResponse; source: CityAnswerSource; context: string } | null>(null);
  const [asking, setAsking] = useState(false); const [askError, setAskError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState(''); const conversation = React.useRef(`city-${Date.now()}`);
  const askController = React.useRef<AbortController | null>(null);
  const askGeneration = React.useRef(0);
  const [historyState, setHistoryState] = useState<{ context: string; value: CityReportHistory; loadedAt: string } | null>(null);
  const reportGeneration = React.useRef(0);
  const [reportError, setReportError] = useState<string | null>(null);
  const sourceIdentity = site.sources.map(source => `${source.id}:${source.vssSensorId ?? ''}`).join('|');
  const answerContext = JSON.stringify([site.id, site.revision, site.mode, sourceIdentity, vstApiUrl ?? null]);
  const reportContext = JSON.stringify([site.id, site.revision, site.mode, sourceIdentity]);
  const history = historyState?.context === reportContext ? historyState.value : null;
  const answer = answerState?.context === answerContext ? answerState.result : null;
  const answeredSource = answer ? answerState!.source : null;
  const answerMediaUrl = answeredSource?.mediaUrl;
  useEffect(() => {
    ++askGeneration.current; setAnswerState(null); setAskedQuestion(''); setQuestion(''); setSourceId(''); setAskError(null); setAsking(false);
    conversation.current = `city-${Date.now()}`;
    return () => askController.current?.abort();
  }, [answerContext]);
  useEffect(() => {
    const generation = ++reportGeneration.current;
    if (panel !== 'reports') return;
    const controller = new AbortController(); setReportError(null); setHistoryState(null);
    const timeout = setTimeout(() => controller.abort('timeout'), 10_000);
    void cityRequest<CityReportHistory>('reports', { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted || generation !== reportGeneration.current) return;
        if (!Array.isArray(value.events) || !Number.isInteger(value.eventCount) || value.eventCount < 0) throw new Error('The city service returned an invalid report.');
        setHistoryState({ context: reportContext, value, loadedAt: new Date().toISOString() });
      }).catch(cause => {
        if (generation === reportGeneration.current && (!controller.signal.aborted || controller.signal.reason === 'timeout')) setReportError(controller.signal.reason === 'timeout' ? 'Report history request timed out. Reopen Reports to retry.' : cause instanceof Error ? cause.message : 'Report history is unavailable.');
      }).finally(() => clearTimeout(timeout));
    return () => { controller.abort(); clearTimeout(timeout); };
  }, [panel, reportContext]);
  const events = recentEvents((snapshot?.events ?? []).filter(event => event.mode === site.mode && site.sources.some(source => source.id === event.sourceId)));
  const checking = events.filter(eventEvidencePending);
  const active = events.filter(event => event.state === 'active' && !eventEvidencePending(event));
  const reportedSources = snapshot?.sources?.filter(item => site.sources.some(source => source.id === item.id)) ?? [];
  const reportedReady = reportedSources.some(source => source.status) ? reportedSources.some(source => source.status === 'live') : undefined;
  const waiting = snapshot?.setupRequired || (snapshot?.awaitingObservations && !snapshot.sources.some(item => item.status === 'replay')) ||
    (site.mode === 'live' && (liveAnalysisReady ?? reportedReady) === false);
  const metrics = snapshot?.metrics ?? [];
  const source = site.sources.find(item => item.id === (sourceId || selectedEvent?.sourceId || selectedTrack?.sourceId)) ?? site.sources[0];
  useLayoutEffect(() => { ++askGeneration.current; askController.current?.abort(); setAsking(false); setAskError(null); setAnswerState(null); setAskedQuestion(''); }, [source?.id, source?.vssSensorId]);
  useEffect(() => { if (source) onCameraChange?.(source.id); }, [source?.id, onCameraChange]);
  const [eventFilter, setEventFilter] = useState<'all' | 'active' | 'cleared'>('all');
  const [eventPage, setEventPage] = useState(0);
  const eventDetailRef = React.useRef<HTMLDivElement>(null);
  useEffect(() => { setEventPage(0); }, [eventFilter, reportContext]);
  useEffect(() => {
    if (selectedEvent && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 1150px)').matches) eventDetailRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [selectedEvent?.id]);
  const metricByRule = useMemo(() => new Map(metrics.map(metric => [metric.ruleId, metric])), [metrics]);
  const selectedSource = site.sources.find(item => item.id === (selectedEvent?.sourceId ?? selectedTrack?.sourceId));
  const review = (event: CityEvent) => { onEvent(event); const seconds = site.mode === 'live' ? null : eventMediaTime(event); if (seconds !== null) onSeek(seconds); };
  const ask = async (event: React.FormEvent) => {
    event.preventDefault(); if (!question.trim() || !source || asking || site.mode === 'fixture-replay') return;
    const query = question.trim(); const controller = new AbortController(); askController.current?.abort(); askController.current = controller;
    const generation = ++askGeneration.current;
    const pinned: CityAnswerSource = { id: source.id, sensorId: source.vssSensorId ?? source.id, name: source.name, mode: site.mode, mediaUrl: safeMediaUrl(source.mediaUrl), vstApiUrl };
    setAsking(true); setAskError(null); setAnswerState(null); setAskedQuestion(query);
    const deadline = setTimeout(() => {
      controller.abort('timeout');
      if (generation === askGeneration.current) { setAskError('The visual analyst took too long. Try again.'); setAsking(false); }
    }, site.mode === 'live' ? 90_000 : 210_000);
    controller.signal.addEventListener('abort', () => clearTimeout(deadline), { once: true });
    try {
      const response = await fetch('/api/vision/analyst', { signal: controller.signal, method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        askedAt: new Date().toISOString(), conversationId: conversation.current, query, scope: 'selected-source', ...(site.mode === 'live' ? { lookbackSeconds: 5 } : {}),
        sources: [{ kind: site.mode === 'live' ? 'live' : 'replay', name: source.name,
          sensorId: source.vssSensorId ?? source.id, streamId: source.vssSensorId ?? source.id,
          playback: { capturedAt: new Date().toISOString(), ...(site.mode === 'live' ? {} : { currentTimeSeconds: mediaTime }) } }],
      }) });
      const result = await response.json();
      if (!response.ok || !result.answer) throw new Error(result.error || 'The visual analyst could not inspect this evidence.');
      if (!controller.signal.aborted && generation === askGeneration.current) { setAnswerState({ id: generation, result: result as VisionAnalystResponse, source: pinned, context: answerContext }); setQuestion(''); }
    } catch (cause) { if (!controller.signal.aborted && generation === askGeneration.current) setAskError(cause instanceof Error ? cause.message : 'The visual analyst is unavailable.'); }
    finally { clearTimeout(deadline); if (!controller.signal.aborted && generation === askGeneration.current) setAsking(false); }
  };
  const report = () => ({ schemaVersion: '1.0', generatedAt: new Date().toISOString(), siteId: site.id, siteName: site.name,
    analyticsScope: snapshot?.analyticsScope ?? null,
    mode: site.mode, historyScope: 'site', historyLoadedAt: history ? historyState!.loadedAt : null, metricsScope: site.mode === 'live' ? snapshot?.videoFrameMatched ? 'displayed-camera-frames' : 'per-source-observations' : 'selected-media-time', metricsMediaTimeSeconds: site.mode === 'live' ? null : mediaTime, siteRevision: site.revision, ruleRevisions: rules.map(rule => ({ id: rule.id, revision: rule.revision })),
    metricSourceFrames: snapshot?.sources.map(item => ({ sourceId: item.id, sessionId: item.sessionId ?? null, sequence: item.sequence ?? null, sourceTimeNs: item.lastSourceTimeNs ?? null })) ?? [],
    cameraIdentityScope: 'Per-camera unless globalTrackId is present; totals are not deduplicated across cameras.',
    metrics, events: history?.events ?? [], eventCount: history?.eventCount ?? 0, historyTruncated: history?.truncated ?? false,
    ...(answer ? { visualAnalysis: answer, visualAnalysisSource: { id: answeredSource!.id, sensorId: answeredSource!.sensorId, name: answeredSource!.name } } : {}), qualification: 'Scene-specific calibration and final hardware qualification are recorded separately.' });
  const navigateTabs = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const current = PANELS.indexOf(panel);
    const next = event.key === 'ArrowRight' ? PANELS[(current + 1) % PANELS.length] : event.key === 'ArrowLeft' ? PANELS[(current + PANELS.length - 1) % PANELS.length] : event.key === 'Home' ? PANELS[0] : event.key === 'End' ? PANELS[PANELS.length - 1] : null;
    if (!next) return;
    event.preventDefault(); onPanel(next); tabButtons.current[next]?.focus();
  };
  const downloadEvents = () => {
    const cell = (value: unknown) => { let text = String(value ?? ''); if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`; return `"${text.replace(/"/g, '""')}"`; };
    const rows = [['event_id', 'source', 'rule', 'state', 'evidence_status', 'triggered_at', 'message', 'scope_epoch', 'scope_kind', 'run_id', 'scenario_id', 'scope_started_at'], ...(history?.events ?? []).map(event => [event.id, event.sourceId, event.ruleName, event.state, event.stopEvidenceStatus ?? '', event.triggeredAt, event.message, event.analyticsScope?.epoch, event.analyticsScope?.kind, event.analyticsScope?.runId, event.analyticsScope?.scenarioId, event.analyticsScope?.startedAt])];
    exportFile(`smart-city-${site.id}-events.csv`, rows.map(row => row.map(cell).join(',')).join('\r\n'), 'text/csv');
  };
  const reportedEvents = recentEvents(history?.events ?? events).filter(event => eventFilter === 'all' || event.state === eventFilter && (eventFilter !== 'active' || !eventEvidencePending(event)));
  const page = Math.min(eventPage, Math.max(0, Math.ceil(reportedEvents.length / EVENT_PAGE_SIZE) - 1));
  const pageEvents = reportedEvents.slice(page * EVENT_PAGE_SIZE, (page + 1) * EVENT_PAGE_SIZE);
  const eventDetail = selectedEvent ? <div className={styles.eventDetail}>
    <div className={styles.detailMeta}><span>{selectedEvent.ruleName}</span><button type="button" aria-label="Clear event selection" onClick={onClearSelection}><IconX size={18} /></button></div>
    <h2>{eventTitle(selectedEvent)}</h2><span className={styles.eventState} data-state={eventEvidencePending(selectedEvent) ? 'unknown' : selectedEvent.state}>{eventStateLabel(selectedEvent)}</span>
    <p className={styles.eventDescription}>{eventStateDescription(selectedEvent)}</p>
    <h3>Evidence</h3><div className={styles.evidenceRow}><IconVideo size={19} /><span>{selectedSource ? sourceName(selectedSource) : selectedEvent.sourceId}<small>{selectedEvent.trackIds.length} linked track{selectedEvent.trackIds.length !== 1 ? 's' : ''}</small></span></div>
    {site.mode !== 'live' && eventMediaTime(selectedEvent) !== null ? <button type="button" className={styles.outlineButton} onClick={() => review(selectedEvent)}><IconPlayerPlay size={18} />Review event</button> : <CityEventEvidence key={selectedEvent.id} event={selectedEvent} source={selectedSource} vstApiUrl={vstApiUrl} />}
    {selectedEvent.evidence?.clipUrl?.startsWith('/api/') && <a className={styles.evidenceLink} href={selectedEvent.evidence.clipUrl} target="_blank" rel="noreferrer">Open source evidence<IconArrowRight size={17} /></a>}
    <div className={styles.detailActions}><button type="button" className={styles.primaryButton} onClick={() => { setSourceId(selectedEvent.sourceId); const time = site.mode === 'live' ? null : eventMediaTime(selectedEvent); if (time !== null) onSeek(time); onPanel('ask'); }}><IconMessageCircle size={18} />{site.mode === 'live' ? 'Ask current camera' : 'Ask about this event'}</button>{onViewArea && <button type="button" className={styles.outlineButton} onClick={() => onViewArea(selectedEvent.ruleId)}>View area on map<IconArrowRight size={16} /></button>}</div>
    <dl className={styles.eventFacts}><div><dt>Started</dt><dd>{eventClock(selectedEvent, true, site.mode === 'live')}</dd></div><div><dt>Triggered</dt><dd>{eventClock(selectedEvent, false, site.mode === 'live')}</dd></div>{Object.entries((selectedEvent.kind === 'stopped-in-zone' && selectedEvent.latestMetrics ? selectedEvent.latestMetrics : selectedEvent.metrics) ?? {}).filter(([key]) => !['durationBasis', 'direction'].includes(key)).map(([key, value]) => { const [label, display] = eventMeasure(key, value); return <div key={key}><dt>{label}</dt><dd>{display}</dd></div>; })}</dl>
    <details className={styles.technicalDetails}><summary>Technical evidence</summary><p>{analyticsScopeLabel(selectedEvent.analyticsScope, true)}</p><p>Source clock time is unverified.</p><dl><dt>Event ID</dt><dd>{selectedEvent.id}</dd>{selectedEvent.metrics?.direction !== undefined && <><dt>Configured line direction vector</dt><dd>{JSON.stringify(selectedEvent.metrics.direction)}</dd></>}<dt>Linked tracks</dt><dd>{selectedEvent.trackIds.join(', ') || 'Unavailable'}</dd></dl></details>
  </div> : null;
  return <aside className={`${styles.inspector} ${embedded ? styles.embeddedInspector : ''}`} aria-label="City activity, insights, questions and reports">
    {!embedded && <div className={styles.tabs} style={{ gridTemplateColumns: 'repeat(4, 1fr)' }} role="tablist" aria-label="City inspector" onKeyDown={navigateTabs}>{PANELS.map(value => <button key={value} ref={element => { tabButtons.current[value] = element; }} id={`${tabsId}-tab-${value}`} role="tab" aria-selected={panel === value} aria-controls={`${tabsId}-panel`} tabIndex={panel === value ? 0 : -1} type="button" onClick={() => onPanel(value)}>{value === 'now' ? 'Now' : value === 'insights' ? 'Insights' : value === 'ask' ? 'Ask' : 'Reports'}</button>)}</div>}
    <div className={styles.inspectorBody} id={`${tabsId}-panel`} role={embedded ? undefined : 'tabpanel'} aria-labelledby={embedded ? undefined : `${tabsId}-tab-${panel}`}>
      {panel === 'now' && <>
        {eventDetail ?? (selectedTrack ? <div className={styles.eventDetail}>
          <div className={styles.detailMeta}><span>Selected object</span><button type="button" aria-label="Clear track selection" onClick={onClearSelection}><IconX size={18} /></button></div><h2>{objectName(selectedTrack.class)}</h2><p>{selectedSource ? sourceName(selectedSource) : selectedTrack.sourceId}</p>
          <p className={styles.identitySummary}>{selectedMapObject?.shared ? `Linked in ${selectedMapObject.sourceIds.length} camera views` : selectedTrack.globalTrackId ? 'Associated across cameras' : 'Camera-owned observation'}</p>
          {selectedMapObject?.shared && <p className={styles.muted}>Experimental map association. Measurements remain camera-owned.</p>}
          <button type="button" className={styles.outlineButton} onClick={() => { setSourceId(selectedTrack.sourceId); onPanel('ask'); }}><IconMessageCircle size={18} />Ask about this camera</button>
          <details className={styles.technicalDetails}><summary>Technical track details</summary><dl><dt>Detection confidence</dt><dd>{selectedTrack.confidence === null ? 'Unavailable' : `${(selectedTrack.confidence * 100).toFixed(0)}%`}</dd><dt>Position</dt><dd>{selectedTrack.positionM ? `${selectedTrack.positionM[0].toFixed(1)}, ${selectedTrack.positionM[1].toFixed(1)} m` : 'Uncalibrated'}</dd><dt>Full track ID</dt><dd>{selectedTrack.globalTrackId ?? selectedTrack.localTrackId}</dd><dt>Identity</dt><dd>{selectedTrack.globalTrackId ? 'Associated across cameras' : 'Camera local'}</dd>{selectedMapObject?.shared && <><dt>Member observations</dt><dd>{selectedMapObject.memberTrackIds.join(', ')}</dd></>}</dl></details>
        </div> : <div className={styles.liveSummary}><h2>{waiting ? 'Waiting for observations' : active.length ? `${active.length} active event${active.length === 1 ? '' : 's'}` : checking.length ? 'Checking camera evidence' : 'Watching the intersection'}</h2><p>Select an object or measurement area to inspect its camera evidence.</p></div>)}
        {!selectedTrack && !selectedEvent && <><div className={styles.eventList}><h3>Recent events <span>{events.length}</span></h3>{events.slice(0, 8).map(event => <button key={event.id} type="button" onClick={() => review(event)}><i className={eventEvidencePending(event) ? styles.dotMuted : event.state === 'active' ? styles.dotWarning : styles.dot} /><span><strong>{eventTitle(event)}</strong><small>{event.ruleName} · {eventClock(event, false, site.mode === 'live')} · {eventStateLabel(event)}</small></span><IconArrowRight size={16} /></button>)}{!events.length && <p className={styles.muted}>No events in this observation scope.</p>}</div>
        <details className={styles.technicalDetails}><summary>All monitoring rules ({rules.filter(rule => rule.enabled).length})</summary>{rules.filter(rule => rule.enabled).map(rule => <div className={styles.watchingRow} key={rule.id}><span>{rule.name}<small>{ruleMeasure(rule, metricByRule.get(rule.id))}</small>{ruleEvidenceReasons(metricByRule.get(rule.id)).map(reason => <small key={reason}>{reason}</small>)}</span></div>)}</details></>}
      </>}
      {panel === 'insights' && <CityMobilityPanel site={site} rules={rules} currentScope={snapshot?.analyticsScope} topic={insightTopic} onTopicChange={onInsightTopicChange} onFocusRule={onFocusRule} onPickQueueGeometry={onPickQueueGeometry} onQueueFocus={onQueueFocus} />}
      {panel === 'ask' && <>
        <div className={styles.askHeading}><h2>Ask this scene</h2><p>Choose a useful question, or ask your own.</p></div>
        <label className={styles.askSource}>Camera<select aria-label="Visual analyst camera" value={source?.id ?? ''} onChange={event => { ++askGeneration.current; askController.current?.abort(); setAsking(false); setAskError(null); setSourceId(event.target.value); }}>{site.sources.map(item => <option key={item.id} value={item.id}>{sourceName(item)}</option>)}</select></label>
        {!askedQuestion && <div className={styles.questionSuggestions}>{['What is happening at the crossing?', 'Is a vehicle stopped in the crossing?', 'Describe the visible traffic.'].map(prompt => <button key={prompt} type="button" disabled={asking || !source || site.mode === 'fixture-replay'} onClick={() => setQuestion(prompt)}>{prompt}<IconArrowRight size={17} /></button>)}</div>}
        <form className={styles.questionForm} onSubmit={ask}><textarea value={question} maxLength={1000} onChange={event => setQuestion(event.target.value)} placeholder={site.mode === 'fixture-replay' ? 'Register video to ask…' : answer ? 'Ask a follow-up…' : 'Ask about this camera…'} aria-label="Question for the visual analyst" disabled={asking || !site.sources.length || site.mode === 'fixture-replay'} /><button className={styles.primaryButton} type="submit" disabled={asking || !question.trim() || !source || site.mode === 'fixture-replay'} aria-label="Ask visual analyst"><IconMessageCircle size={18} />{asking ? 'Inspecting footage…' : 'Ask the camera'}</button></form>
        {askedQuestion && <div className={styles.questionBubble}>{askedQuestion}</div>}
        {asking && <div role="status" className={styles.analystPending}><span className="vi-spinner" />Inspecting video evidence…</div>}
        {askError && <div className={styles.error} role="alert">{askError}<small>No answer is shown. Check the message above, then try again.</small></div>}
        {answer && answeredSource && <div className={styles.answer}><h3>Visual analyst response</h3><p>{answer.answer}</p><span>Analyzed source: {sourceName(answeredSource)}.</span><span>{observedWindowLabel(answer) ? `Observed video · ${observedWindowLabel(answer)}` : answer.observedRange ? `Video evidence · ${formatMediaTimeTenths(answer.observedRange.startSeconds)}–${formatMediaTimeTenths(answer.observedRange.endSeconds)}` : `Inspected interval unavailable · answer generated ${new Date(answer.generatedAt).toLocaleTimeString()}`}</span>{answeredSource.mode === 'live' ? <CityAnswerEvidence key={answerState!.id} answer={answer} source={answeredSource} selectionKey={source?.id ?? ''} /> : answerMediaUrl && <a className={styles.evidenceLink} href={answerMediaUrl} target="_blank" rel="noreferrer">Open camera evidence<IconArrowRight size={17} /></a>}</div>}
        {!answer && !asking && !askError && <div className={styles.answerEmpty}><IconFileReport size={28} /><strong>Your answer will appear here.</strong><p>{!site.sources.length ? 'Connect a registered city camera to inspect footage.' : site.mode === 'fixture-replay' ? 'Geometry fixtures have no camera video for visual analysis.' : 'Review the footage before using a visual-model answer.'}</p></div>}
        <p className={styles.askScope}>{site.mode === 'live' ? 'Current footage only · recent 5 seconds from this camera.' : 'Selected camera footage.'} Source clock time is unverified.</p><div className={styles.measurementRoute}><span>Counts and durations come from Measurements.</span>{onShowMeasurements && <button type="button" onClick={onShowMeasurements}>Open measurements<IconArrowRight size={16} /></button>}</div>
      </>}
      {panel === 'reports' && <div className={styles.reportsLayout}>
        <div className={styles.reportList}><div className={styles.reportHeading}><div><h2>Measured events</h2><p>Retained camera history · Each event keeps its run and scope.</p></div><div className={styles.filterButtons} aria-label="Event state filter">{(['all', 'active', 'cleared'] as const).map(filter => <button key={filter} type="button" aria-pressed={eventFilter === filter} onClick={() => setEventFilter(filter)}>{filter}</button>)}</div></div>
          {reportError && <p role="alert" className={styles.error}>{reportError}</p>}
          <div className={styles.eventTable}><div className={styles.eventTableHead}><span>Event</span><span>Camera</span><span>Time</span><span>State</span></div>{pageEvents.map(event => <button type="button" className={selectedEvent?.id === event.id ? styles.selectedEvent : ''} key={event.id} disabled={event.mode !== site.mode || !site.sources.some(item => item.id === event.sourceId)} onClick={() => review(event)}><span><strong>{eventTitle(event)}</strong><small>{event.ruleName}</small></span><span>{sourceName(site.sources.find(item => item.id === event.sourceId) ?? { name: 'Disconnected camera' })}</span><time>{eventClock(event, false, site.mode === 'live')}<small>{event.triggeredAt && Number.isFinite(Date.parse(event.triggeredAt)) ? new Date(event.triggeredAt).toLocaleDateString([], { month: 'short', day: 'numeric' }) : ''}</small></time><span className={styles.eventState} data-state={eventEvidencePending(event) ? 'unknown' : event.state}>{eventStateLabel(event)}</span></button>)}{!reportedEvents.length && <div className={styles.answerEmpty}><IconFileReport size={25} /><strong>{history ? 'No events in this view' : 'Reading saved events…'}</strong><p>Measured camera events will appear here with their source and state.</p></div>}</div>
          {reportedEvents.length > 0 && <nav className={styles.eventPagination} aria-label="Event pages"><span>{page * EVENT_PAGE_SIZE + 1}–{Math.min((page + 1) * EVENT_PAGE_SIZE, reportedEvents.length)} of {reportedEvents.length} events</span><button type="button" disabled={page === 0} onClick={() => setEventPage(page - 1)}>Previous</button><button type="button" disabled={(page + 1) * EVENT_PAGE_SIZE >= reportedEvents.length} onClick={() => setEventPage(page + 1)}>Next</button></nav>}
          <section className={styles.reportExports}><h3>Report exports</h3><p>Counts and events with source, run and observation scope.</p><div className={styles.detailActions}><button type="button" disabled={!history} className={styles.outlineButton} onClick={() => exportFile(`smart-city-${site.id}.json`, JSON.stringify(report(), null, 2), 'application/json')}><IconDownload size={18} />Download site JSON</button><button type="button" disabled={!history} className={styles.outlineButton} onClick={downloadEvents}><IconDownload size={18} />Export events CSV</button></div><details className={styles.technicalDetails}><summary>Rule measures &amp; report scope</summary><p>Saved events retain their original scope. {history?.truncated ? 'This export contains the most recent 1,000 events.' : ''}</p><table className={styles.reportTable}><thead><tr><th>Rule</th><th>Measure</th></tr></thead><tbody>{rules.map(rule => <tr key={rule.id}><td>{rule.name}</td><td>{ruleMeasure(rule, metricByRule.get(rule.id))}</td></tr>)}</tbody></table></details></section>
        </div>
        <div ref={eventDetailRef} className={styles.reportDetail}>{eventDetail ?? <div className={styles.answerEmpty}><IconFileReport size={30} /><strong>Select an event</strong><p>Review its camera, observed duration and evidence status.</p></div>}<p className={styles.scopeNote}>Counts belong to their camera. Overlapping views are not a unique site total.</p></div>
      </div>}
    </div>
  </aside>;
}
