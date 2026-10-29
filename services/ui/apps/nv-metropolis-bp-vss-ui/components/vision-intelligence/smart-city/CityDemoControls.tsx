// SPDX-License-Identifier: MIT
import React, { memo, useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal, flushSync } from 'react-dom';
import { IconCheck, IconExternalLink, IconPlayerPlay, IconPlayerStop, IconRotate, IconX } from '@tabler/icons-react';
import styles from './CityDemoControls.module.css';
import { cityChallenge } from './cityChallenges';
import { getScenarioPresentation } from './scenarioPresentation';

type Episode = { id: string; title: string; question: string; durationSimSeconds: number; measurements: string[]; available: boolean;
  readiness?: { state?: string } };
type Demo = { available: boolean; playing: boolean; scenario: {
  active: boolean; state: string; title?: string; scenarioId?: string; runId?: string; elapsedSimSeconds?: number;
  durationSimSeconds?: number; reason?: string; restored?: boolean; normalFlowVerified?: boolean; catalog: Episode[];
  nativePreparationNotStarted?: boolean; normalFlowUnchanged?: boolean;
  phase?: string; progressClock?: string; phaseElapsedWallSeconds?: number; phaseBudgetWallSeconds?: number;
  analyticsBoundary?: { ready?: boolean; state?: string; reason?: string; captureRenewalAttempted?: boolean };
  events?: { kind: string; detail?: string }[];
} };

const PHASES: Record<string, string> = { preparing: 'Preparing scenario', ready: 'Ready to play', running: 'Event in progress',
  recovering: 'Returning to normal', 'recovery-failed': 'Recovery needs attention',
  failed: 'Event stopped', completed: 'Event complete', cancelled: 'Event cancelled' };
const BOOTH_PHASES: Record<string, string> = { staging: 'Traffic is approaching', 'awaiting-green': 'Waiting for a green signal', 'awaiting-traffic': 'Waiting for approaching traffic', observing: 'Observe the event',
  releasing: 'Returning to normal', clearing: 'Traffic is clearing', recovering: 'Returning to normal',
  'waiting-for-clearance': 'Waiting for clear space', 'queue-forming': 'Queue forming', 'junction-blocked': 'Junction blocked', 'person-waiting': 'Waiting at the crossing', 'observing-clearance': 'Watching for clearance', approaching: 'Person approaching', waiting: 'Person waiting', 'awaiting-walk': 'Waiting for WALK', crossing: 'Group crossing', starting: 'Starting observation' };
const PREPARATION_PHASES: Record<string, string> = {
  'validating-starts': 'Finding a clear starting position',
  'placing-loaded-actors': 'Positioning the scene',
  'settling-native-starts': 'Confirming starting positions',
  'settling': 'Preparing camera tracking',
  'waiting-for-clearance': 'Waiting for clear space',
};
const REASONS: Record<string, string> = {
  'booth-staging-deadline': 'A car did not stop in the zone within the staging time limit.',
  'booth-departure-not-verified': 'The car’s departure was not verified before the time limit.',
  'booth-release-deadline': 'The simulator did not confirm release of the stopped car in time.',
  'departure-not-verified': 'The simulator could not verify that the car drove out of the zone.',
  'operator-cancel': 'Stopped by the operator.',
  'timeline-paused': 'The simulation paused.',
  'simulation-clock-reset': 'The simulation clock reset.',
  'stage-or-controller-generation-changed': 'The scene or its traffic controller changed.',
  'classic-incident-started': 'A different scene event started.',
  'native-navigation-task-failed': 'The pedestrian navigation task did not complete.',
  'pedestrian-approach-deadline': 'The person did not reach the curb within the preparation time limit.',
  'pedestrian-walk-signal-deadline': 'A safe WALK period did not arrive within the time limit.',
  'pedestrian-crossing-deadline': 'The person’s far-side arrival was not verified before the time limit.',
  'pedestrian-clearance-not-verified': 'The person’s arrival beyond the crossing was not verified before the time limit.',
  'pedestrian-entry-not-verified': 'The person’s arrival at the curb was not verified.',
  'pedestrian-walk-gate-not-verified': 'The simulator did not verify a usable WALK period for this crossing.',
  'pedestrian-native-action-refused': 'The simulator did not accept the person’s navigation action.',
  'pedestrian-presentation-budget-insufficient': 'There was not enough time to finish this crossing within the scenario’s time limit.',
  'episode-wall-deadline': 'The scenario reached its overall time limit.',
  'action-deadline': 'A scene action was not confirmed before its time limit.',
  'action-refused': 'The simulator did not accept a scene action.',
  'runtime-update-error': 'The scenario controller encountered an error.',
  'prepared-staging-deadline': 'The starting positions were not confirmed before the preparation time limit.',
  'Prepared scene deadline expired': 'A clear, reachable starting position was not found in time. Traffic has resumed; you can choose another scenario.',
  'post-reset-camera-settling-timeout': 'Fresh camera tracking did not become ready. The scenario has stopped.',
  'camera-capture-clock-rejected': 'Camera timing could not be verified. The scene stopped and traffic is being restored.',
  'analytics-boundary-failed': 'Fresh camera tracking could not be confirmed. The scenario has not been played.',
};

async function readResponse(response: Response): Promise<Demo> {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The simulator did not accept this action.');
  if (!data.scenario || !Array.isArray(data.scenario.catalog)) throw new Error('The simulator status is unavailable.');
  return data as Demo;
}

export const CityDemoControls = memo(function CityDemoControls({ onScenarioStarted, onPreparationChange, onStatusChange, guideRequest = 0, preparationTarget, onReviewResults }: {
  guideRequest?: number; preparationTarget?: HTMLDivElement | null; onReviewResults?: () => void;
  onScenarioStarted?: (id: string) => void; onPreparationChange?: (covered: boolean) => void; onStatusChange?: (status: string) => void;
}) {
  const [demo, setDemo] = useState<Demo | null>(null);
  const [statusRead, setStatusRead] = useState(false);
  const [checking, setChecking] = useState(false);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState('crossing-occupancy');
  const [busy, setBusy] = useState(false);
  const [dismissedResult, setDismissedResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const mutationVersion = useRef(0);
  const actionPending = useRef(false);
  const fastPolling = useRef(false);
  const switchTo = useRef<string | null>(null);
  const autoPlay = useRef<{ scenarioId: string; runId: string } | null>(null);
  const pendingPlay = useRef<{ scenarioId: string; runId: string } | null>(null);
  const playGuard = useRef<{ scenarioId: string; runId: string } | null>(null);
  const started = useRef(onScenarioStarted); started.current = onScenarioStarted;
  const preparation = useRef(onPreparationChange); preparation.current = onPreparationChange;
  const covered = useRef(false);
  const cover = useCallback((value: boolean) => {
    if (covered.current === value) return;
    covered.current = value; preparation.current?.(value);
  }, []);
  const acceptDemo = useCallback((data: Demo) => {
    setStatusRead(true);
    setChecking(false);
    setDemo(data);
    const scene = data.scenario;
    fastPolling.current = scene.active && ['preparing','ready','recovering'].includes(scene.state);
    const pending = pendingPlay.current;
    if (pending && scene.runId === pending.runId && scene.scenarioId === pending.scenarioId &&
        data.available === true && data.playing === true && scene.active === true && scene.state === 'running') {
      pendingPlay.current = null;
      setOpen(false); started.current?.(pending.scenarioId);
    } else if (pending && (scene.runId !== pending.runId || scene.scenarioId !== pending.scenarioId ||
        ['failed', 'cancelled', 'completed', 'recovering', 'recovery-failed'].includes(scene.state))) {
      pendingPlay.current = null;
    }
    if (switchTo.current) { cover(true); return; }
    const guard = playGuard.current;
    if (guard) {
      const sameRun = scene.runId === guard.runId && scene.scenarioId === guard.scenarioId;
      const confirmedRunning = sameRun && data.available === true && data.playing === true && scene.active === true && scene.state === 'running';
      const confirmedRestored = sameRun && !scene.active && scene.restored === true &&
        (scene.normalFlowVerified === true || scene.nativePreparationNotStarted === true && scene.normalFlowUnchanged === true);
      if (confirmedRunning || confirmedRestored) playGuard.current = null;
      else { cover(true); return; }
    }
    if (scene.state === 'recovery-failed'  && scene.restored === true && scene.normalFlowVerified === true) cover(false);
    else if (['preparing', 'recovering', 'recovery-failed'].includes(scene.state) || scene.state === 'ready' && scene.analyticsBoundary?.ready !== true) cover(true);
    else if (data.available && data.playing && (scene.state === 'ready' && scene.analyticsBoundary?.ready === true ||
      scene.state === 'running' || !scene.active && (scene.state === 'idle' || scene.restored === true && (scene.normalFlowVerified === true || scene.nativePreparationNotStarted === true && scene.normalFlowUnchanged === true)))) cover(false);
    // Unknown/offline responses retain the current cover until status proves a safe state.
  }, [cover]);
  const id = useId();
  useEffect(() => { if (guideRequest > 0) setOpen(true); }, [guideRequest]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let request: AbortController | undefined;
    let generation = 0;
    const poll = async () => {
      if (disposed || document.hidden) return;
      const mine = ++generation;
      const version = mutationVersion.current;
      const current = new AbortController();
      request = current;
      const timeout = setTimeout(() => current.abort(), 6500);
      try {
        const data = await readResponse(await fetch('/api/vision/city-demo', { signal: current.signal, cache: 'no-store' }));
        if (!disposed && mine === generation && version === mutationVersion.current && !actionPending.current) acceptDemo(data);
      } catch {
        if (!disposed && !document.hidden && mine === generation && version === mutationVersion.current && !actionPending.current) { setStatusRead(true); setChecking(false); setDemo(null); }
      } finally {
        clearTimeout(timeout);
        if (!disposed && !document.hidden && mine === generation) timer = setTimeout(poll, fastPolling.current ? 650 : 2000);
      }
    };
    const visibility = () => {
      ++generation; clearTimeout(timer); request?.abort();
      if (!document.hidden) void poll();
    };
    document.addEventListener('visibilitychange', visibility);
    void poll();
    return () => { disposed = true; clearTimeout(timer); request?.abort(); document.removeEventListener('visibilitychange', visibility); };
  }, [acceptDemo]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); } };
    document.addEventListener('mousedown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);

  const act = useCallback(async (operation: 'prepare' | 'play' | 'cancel' | 'retry', scenarioId?: string, runId?: string) => {
    if (actionPending.current) return;
    actionPending.current = true; fastPolling.current = true;
    ++mutationVersion.current;
    if (operation === 'cancel' || operation === 'retry') { autoPlay.current = null; pendingPlay.current = null; flushSync(() => cover(true)); }
    if (operation === 'play' && scenarioId && runId) {
      pendingPlay.current = { scenarioId, runId };
      playGuard.current = { scenarioId, runId };
      flushSync(() => cover(true));
    }
    if (operation === 'prepare') { autoPlay.current = null; flushSync(() => cover(true)); }
    setBusy(true); setError(null);
    try {
      const response = await fetch('/api/vision/city-demo', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operation, ...(operation === 'prepare' ? { scenarioId } : { runId }), requestId: crypto.randomUUID() }), signal: AbortSignal.timeout(8000) });
      const data = await readResponse(response);
      ++mutationVersion.current;
      if (operation === 'prepare') {
        if (scenarioId && data.available === true && data.playing === true && data.scenario.active === true &&
            data.scenario.scenarioId === scenarioId && data.scenario.runId && ['preparing', 'ready'].includes(data.scenario.state)) {
          autoPlay.current = { scenarioId, runId: data.scenario.runId };
          setSelected(scenarioId); setOpen(false);
        } else { setError('The simulator did not confirm preparation. Check its reported state before trying again.'); setOpen(true); }
      } else if (operation === 'play') {
        if (scenarioId && data.available === true && data.playing === true && data.scenario.active === true &&
            data.scenario.scenarioId === scenarioId && data.scenario.runId === runId && data.scenario.state === 'running') {
          setOpen(false);
        } else { setError('The simulator did not confirm playback. Check its reported state before trying again.'); setOpen(true); }
      }
      acceptDemo(data);
    } catch (problem) {
      // The request may have reached the host even when its response was lost.
      // Discard the old actionable state until a fresh status confirms the outcome.
      flushSync(() => cover(true));
      setDemo(null); setChecking(true);
      setError(problem instanceof Error ? problem.message : 'The operation did not complete.'); setOpen(true);
    }
    finally { actionPending.current = false; setBusy(false); }
  }, [acceptDemo, cover]);

  const state = demo?.scenario;
  const active = state?.active === true;
  const ready = state?.state === 'ready';
  const preparing = state?.state === 'preparing';
  const recovering = state?.state === 'recovering';
  const recoveryFailed = state?.state === 'recovery-failed';
  const terminalResult = !active && ['failed', 'cancelled', 'completed'].includes(state?.state ?? '');
  const unchanged = state?.nativePreparationNotStarted === true && state?.normalFlowUnchanged === true;
  const restored = state?.restored === true && (state?.normalFlowVerified === true || unchanged);
  const resultReason = state?.reason && REASONS[state.reason] ||
    (restored ? 'The scenario could not finish. Normal traffic has resumed.' : 'The scenario could not finish. Check recovery before trying again.');
  const resultDetail = [...(state?.events ?? [])].reverse().find(event =>
    ['action-refused', 'recovery-failed'].includes(event.kind) && event.detail)?.detail;
  const episode = state?.catalog.find(item => item.id === (active ? state.scenarioId : selected)) ?? state?.catalog.find(item => item.available);
  const analyticsReady = state?.analyticsBoundary?.ready === true;
  const scenePlaced = ready || preparing && state?.phase === 'settling';
  const presentation = getScenarioPresentation(episode?.id);
  const context = cityChallenge(episode?.id);
  const status = checking ? 'Checking scenario status' : !statusRead ? 'Connecting scenario controls' : !demo?.available ? 'Demo controls offline' : !demo.playing ? 'Simulation paused' :
    recoveryFailed ? PHASES['recovery-failed'] : preparing ? PREPARATION_PHASES[state?.phase ?? ''] || PHASES.preparing : ready ? (analyticsReady ? PHASES.ready : 'Preparing camera tracking') :
    recovering ? PHASES.recovering : active ? BOOTH_PHASES[state?.phase ?? ''] || PHASES[state?.state ?? ''] || 'Event in progress' :
    terminalResult && !restored ? 'Check scenario recovery' : 'Normal traffic';
  const wallClock = state?.progressClock === 'wall';
  const clockElapsed = wallClock ? state?.phaseElapsedWallSeconds : state?.elapsedSimSeconds;
  const hasClock = !ready && typeof clockElapsed === 'number' && Number.isFinite(clockElapsed) && clockElapsed >= 0;
  const canPrepare = demo?.available === true && demo.playing && !active && !recoveryFailed && (!terminalResult || restored);
  const canPlay = demo?.available === true && demo.playing && active && ready && analyticsReady && !!state?.runId;
  useEffect(() => {
    const intent = autoPlay.current;
    if (!intent || busy || !state) return;
    if (!state.active || state.scenarioId !== intent.scenarioId || state.runId !== intent.runId ||
        ['failed', 'cancelled', 'completed', 'recovering', 'recovery-failed'].includes(state.state)) {
      autoPlay.current = null;
      return;
    }
    if (canPlay) {
      // Leave the React lifecycle before synchronously covering and sending Play.
      let cancelled = false;
      queueMicrotask(() => {
        if (cancelled || autoPlay.current !== intent || actionPending.current) return;
        autoPlay.current = null;
        void act('play', intent.scenarioId, intent.runId);
      });
      return () => { cancelled = true; };
    }
  }, [act, busy, canPlay, state]);

  useEffect(() => {
    const next = switchTo.current;
    if (!next || busy || active || recoveryFailed || !demo?.available || !demo.playing || !state ||
        !(state.state === 'idle' || restored)) return;
    switchTo.current = null;
    // A switch owns the opaque cover through confirmed recovery and preparation.
    // Never prepare against a merely pending cancellation response.
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void act('prepare', next); else switchTo.current = next; });
    return () => { cancelled = true; };
  }, [act, active, busy, demo?.available, demo?.playing, recoveryFailed, restored, state]);

  useEffect(() => { onStatusChange?.(active ? `Scripted scene · ${status}` : status === 'Normal traffic' ? 'Live · Normal traffic' : status); }, [active, status, onStatusChange]);
  const labels: Record<string, string> = { 'crossing-occupancy': 'Crossing occupied', 'queue-blockage': 'Queue → blockage', 'emergency-access': 'Emergency access' };
  return <div ref={root} className={styles.root}>
    <div className={styles.shelfIntro}><strong>Load &amp; play a scenario</strong><span data-result={terminalResult && restored && state?.state === 'completed'}>{terminalResult && restored && state?.state === 'completed' ? <>Scene report saved. {onReviewResults && <button type="button" className={styles.resultLink} onClick={onReviewResults}>Review scene report</button>}</> : 'One click. Watch the cameras measure what happens.'}</span></div>
    <div className={styles.shelfChoices} role="group" aria-label="Demo scenarios">{Object.entries(labels).map(([key, label], index) => { const entry = state?.catalog.find(item => item.id === key); return <button key={key} type="button" aria-label={entry?.title ?? label} title={entry?.question ?? 'Scenario catalog unavailable'} data-scenario-id={key} aria-pressed={active ? state?.scenarioId === key : open && episode?.id === key} disabled={!entry || busy || (active ? recovering || recoveryFailed || !entry.available : !canPrepare || !entry.available)} onClick={() => { setSelected(key); if (active && state?.scenarioId === key) setOpen(true); else if (active) { switchTo.current = key; autoPlay.current = null; void act('cancel', undefined, state?.runId); } else void act('prepare', key); }}><span>{String(index + 1).padStart(2, '0')}</span>{label}</button>; })}</div>
    {active && <div className={styles.phaseHud} role="status" aria-label="Scripted scenario status"><span><strong>{status}</strong></span>{hasClock && !['crossing-occupancy','queue-blockage','emergency-access'].includes(state?.scenarioId ?? '') && <output>{Math.floor(clockElapsed!)} s</output>}
      <button type="button" disabled={busy || recovering} onClick={() => void act('cancel', undefined, state?.runId)}>{recovering ? 'Returning…' : 'Stop'}</button></div>}
    {terminalResult && state?.state === 'failed' && !open && !busy && dismissedResult !== state.runId && <div className={styles.recoveryNotice} role="alert">
      <span>{resultReason}</span><button type="button" onClick={() => setOpen(true)}>Review last run</button>{restored && <button type="button" aria-label="Dismiss restored scenario result" onClick={() => setDismissedResult(state?.runId ?? null)}><IconX size={16} /></button>}
    </div>}
    {recoveryFailed && !open && <div className={styles.recoveryNotice} role="alert" aria-label="Scenario recovery needs attention">
      <span>{restored ? 'Traffic restored. Camera recovery needed.' : 'Scene recovery needs attention.'}</span>
      <button type="button" disabled={busy} onClick={() => void act('retry', undefined, state?.runId)}>{busy ? 'Retrying…' : 'Retry recovery'}</button>
    </div>}
    {preparationTarget && createPortal(<div className={styles.preparation}>
      <span>{presentation?.title ?? 'City scenario'}</span>
      <h2>{recoveryFailed ? 'Scene recovery needs attention' : recovering ? 'Returning to normal traffic' : checking || !demo ? 'Checking the scenario state' : presentation?.question ?? 'Preparing the city scenario'}</h2>
      <p>{recoveryFailed ? resultReason : status}</p>
      {!recovering && !recoveryFailed && <ol aria-label="Scenario preparation steps">
        <li data-state={scenePlaced ? 'complete' : 'working'}><i>{scenePlaced ? <IconCheck size={18} /> : <span className="vi-spinner" />}</i><span>Place the starting scene{!scenePlaced && state?.phase === 'validating-starts' && <small>Checking native paths and clear space</small>}</span></li>
        <li data-state={scenePlaced ? 'working' : 'pending'}><i>{scenePlaced ? <span className="vi-spinner" /> : '2'}</i><span>Confirm fresh camera tracking{scenePlaced && <small>{state?.analyticsBoundary?.captureRenewalAttempted ? 'Checking a fresh camera session' : 'Preparing camera tracking'}</small>}</span></li>
        <li data-state="pending"><i>3</i><span>Show the live event</span></li>
      </ol>}

      {recoveryFailed ? <button type="button" className={styles.secondary} disabled={busy || !state?.runId} onClick={() => void act('retry', undefined, state?.runId)}><IconRotate size={17} />Retry recovery</button> : <button type="button" className={styles.secondary} disabled={busy || !active || recovering || !state?.runId} onClick={() => void act('cancel', undefined, state?.runId)}><IconPlayerStop size={17} />{recovering ? 'Returning to traffic…' : 'Stop and return to traffic'}</button>}

    </div>, preparationTarget)}
    {open && <section id={id} className={styles.panel} aria-label="Demo scenario">
      <header><div><span className={styles.scenarioLabel}>{presentation?.title ?? 'City challenge'}</span><h3>{presentation?.question ?? episode?.question ?? 'Choose a city challenge'}</h3></div>
        <button type="button" aria-label="Close scenario controls" onClick={() => setOpen(false)}><IconX size={18} /></button></header>
      {!active && !recoveryFailed && presentation && context && <div className={styles.guide}>
        <div><strong>The city problem</strong><p>{context.problem}</p></div>
        <div><strong>Watch the live view</strong><p>{presentation.scene}</p></div>
        <div><strong>VSS will observe</strong><p>{context.observe}</p></div>
        <a href={context.researchUrl} target="_blank" rel="noreferrer">Research context · {context.researchTitle}<IconExternalLink size={15} /></a>
      </div>}
      {checking ? <div className={styles.content}><p role="status">Checking scenario status…</p></div> : active || recoveryFailed ? <div className={styles.content}>
        {recoveryFailed ? <><p role="status">{resultReason}</p>{resultDetail && <p>{resultDetail}</p>}
          <button type="button" className={styles.primary} disabled={busy} onClick={() => void act('retry', undefined, state?.runId)}><IconRotate size={16} />Retry recovery</button></> : <>
          <p role="status">{status}</p>
          {ready && analyticsReady && !autoPlay.current && <button type="button" className={styles.primary} disabled={busy || !canPlay} onClick={() => void act('play', state?.scenarioId, state?.runId)}><IconPlayerPlay size={16} />Play scenario</button>}
          <button type="button" className={styles.secondary} disabled={busy || recovering} onClick={() => void act('cancel', undefined, state?.runId)}>{recovering ? 'Returning to normal…' : 'Stop scenario'}</button>
        </>}
      </div> : <div className={styles.content}>
        {terminalResult && state?.state === 'failed' && <p role="status">{resultReason}</p>}
        {terminalResult && !restored && <p role="status">Scene recovery needs attention before another scenario can start.</p>}
        {demo?.available && !demo.playing && <p>Resume the simulation to start a scenario.</p>}
        {episode ? <button type="button" className={styles.primary} disabled={busy || !canPrepare || !episode.available} onClick={() => void act('prepare', episode.id)}><IconPlayerPlay size={16} />{busy ? 'Starting…' : 'Start demo'}</button> : <p>Scenarios are unavailable.</p>}
      </div>}
      {!active && <p className={styles.sourceNote}>The situation is scripted in Isaac Sim. Measurements come independently from the cameras.</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </section>}
  </div>;
});
