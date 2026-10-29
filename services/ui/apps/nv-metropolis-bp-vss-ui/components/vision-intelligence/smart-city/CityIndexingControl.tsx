// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconSearch, IconRefresh, IconX, IconPlayerStop, IconVideoPlus } from '@tabler/icons-react';
import type { CityCaptureSearch, CityIndexingMatch, CityIndexingSource, CityIndexingStatus } from './cityIndexing';
import { useDocumentVisible } from './useDocumentVisible';
import { sourceName } from './presentation';
import { proxyVstPictureUrl } from '../utils';
import styles from './CityIndexingControl.module.css';

const API = '/api/vision/city-indexing';
const LABELS: Record<string, string> = {
  idle: 'Ready for a short capture', disabled: 'Indexing off', running: 'Indexing this capture', recovering: 'Connecting to indexing',
  starting: 'Starting capture', stopping: 'Stopping indexing', completed: 'Capture ended', cancelled: 'Capture stopped',
  interrupted: 'Capture interrupted', failed: 'Capture failed', paused: 'Camera analysis paused',
  'stop-failed': 'Stop not confirmed', 'policy-error': 'Indexing settings unavailable',
};
function time(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function range(start: string | null | undefined, end: string | null | undefined) { return `${time(start)} – ${time(end)}`; }
async function request<T>(sourceId: string, signal: AbortSignal, body?: object): Promise<T> {
  const response = await fetch(body ? API : `${API}?sourceId=${encodeURIComponent(sourceId)}`, {
    method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', signal,
    ...(body ? { body: JSON.stringify({ sourceId, ...body }) } : {}),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.error === 'string' ? value.error : 'Capture indexing is unavailable.');
  return value as T;
}

export interface CityIndexingControlProps {
  sources: readonly CityIndexingSource[]; inline?: boolean;
  className?: string;
  disabled?: boolean;
  onOpenEvidence?: (match: CityIndexingMatch) => void;
  onSourceChange?: (sourceId: string) => void;
  selectedMatch?: CityIndexingMatch | null;
}

/** No polling while closed; only explicit actions can start an embedding job. */
export function CityIndexingControl({ sources, className, disabled, onOpenEvidence, onSourceChange, selectedMatch, inline = false }: CityIndexingControlProps) {
  const visible = useDocumentVisible();
  const [open, setOpen] = useState(inline);
  const [sourceId, setSourceId] = useState('');
  const selected = sources.find(source => source.id === sourceId) ?? sources[0];
  const selectedId = selected?.id ?? '';
  const [status, setStatus] = useState<CityIndexingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<CityCaptureSearch | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [now, setNow] = useState(Date.now);
  const [position, setPosition] = useState({ top: 72, left: 12 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const camera = useRef<HTMLSelectElement>(null);
  const operation = useRef<AbortController | null>(null);
  const shown = status?.sensorId === selectedId ? status : null;
  const session = shown?.session;
  const active = Boolean(session && ['starting', 'running'].includes(session.state));
  const continuous = shown?.mode === 'continuous';
  const hasDocuments = typeof shown?.evidence.documentCount === 'number' && shown.evidence.documentCount > 0;
  const canSearch = Boolean(session?.startedAt && shown?.searchScope.available && hasDocuments && !error);

  function close() { if (!inline) { setOpen(false); trigger.current?.focus(); } }

  useEffect(() => {
    operation.current?.abort(); operation.current = null;
    setStatus(null); setResults(null); setQuery(''); setError(null); setActionError(null); setBusy(null);
  }, [selectedId]);
  useEffect(() => () => { operation.current?.abort(); }, []);
  useEffect(() => { onSourceChange?.(selectedId); }, [selectedId, onSourceChange]);
  useEffect(() => {
    if (!open) { operation.current?.abort(); setBusy(null); return; }
    if (inline) return;
    const place = () => {
      const box = trigger.current?.getBoundingClientRect(); if (!box) return;
      const width = Math.min(420, window.innerWidth - 24);
      setPosition({ top: Math.min(box.bottom + 8, Math.max(12, window.innerHeight - 220)), left: Math.max(12, Math.min(box.right - width, window.innerWidth - width - 12)) });
    };
    place(); camera.current?.focus();
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open, inline]);
  useEffect(() => {
    if (!open || !visible || !selectedId || busy) return;
    let stopped = false; let controller: AbortController | null = null; let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      controller = new AbortController(); const current = controller; const deadline = setTimeout(() => current.abort(), 25_000);
      try {
        const value = await request<CityIndexingStatus>(selectedId, current.signal);
        if (value.sensorId !== selectedId) throw new Error('The selected camera status could not be verified.');
        if (!stopped && !current.signal.aborted) { setStatus(value); setError(null); }
      } catch (cause) { if (!stopped) setError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : 'Capture status timed out. Refresh to retry.'); }
      finally { clearTimeout(deadline); if (!stopped) timer = setTimeout(poll, 5000); }
    };
    void poll();
    return () => { stopped = true; controller?.abort(); if (timer) clearTimeout(timer); };
  }, [open, visible, selectedId, busy, refresh]);
  useEffect(() => {
    if (!open || !visible || !active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer);
  }, [open, visible, active]);

  async function act(action: 'start' | 'cancel' | 'policy' | 'search') {
    if (!selected || busy || operation.current) return;
    const controller = new AbortController(); operation.current = controller;
    const deadline = setTimeout(() => controller.abort(), 110_000);
    const chosen = { id: selected.id, name: selected.name };
    setBusy(action); setActionError(null);
    try {
      if (action === 'search') {
        if (!session || !query.trim()) return;
        const value = await request<CityCaptureSearch>(chosen.id, controller.signal, { action, name: chosen.name, sessionId: session.id, query: query.trim(), topK: 6 });
        if (!controller.signal.aborted && value.scope.sourceId === chosen.id && value.sessionId === session.id) setResults(value);
      } else {
        if (action === 'start' && shown?.mode === 'disabled') await request(chosen.id, controller.signal, { action: 'policy', name: chosen.name, mode: 'on-demand' });
        const value = await request<CityIndexingStatus>(chosen.id, controller.signal, {
          action, name: chosen.name, ...(action === 'policy' ? { mode: 'on-demand' } : {}), ...(action === 'start' ? { durationSeconds: 120 } : {}),
        });
        if (!controller.signal.aborted && value.sensorId === chosen.id) { setStatus(value); if (action !== 'cancel') setResults(null); }
      }
    } catch (cause) { if (!controller.signal.aborted) setActionError(cause instanceof Error ? cause.message : 'The capture request did not complete.'); else if (operation.current === controller) setActionError('The request ended before confirmation. Refresh its actual status before retrying.'); }
    finally { clearTimeout(deadline); if (operation.current === controller) { operation.current = null; setBusy(null); setRefresh(value => value + 1); } }
  }

  const remaining = session ? Math.max(0, Math.ceil((Date.parse(session.deadlineAt) - now) / 1000)) : 0;
  const content = <section ref={panel} className={`${styles.panel} ${inline ? styles.inline : ''}`} style={inline ? undefined : { ...position, maxHeight: `calc(100dvh - ${position.top + 12}px)` }} role={inline ? 'region' : 'dialog'} aria-label="Search capture">
      <header><div><strong>Search a short capture</strong><p>Traffic tracking stays on.</p></div><button type="button" onClick={close} aria-label="Close capture search"><IconX size={17} /></button></header>
      <div className={styles.controls}><label className={styles.camera}>Camera<select ref={camera} value={selectedId} disabled={Boolean(busy)} onChange={event => { operation.current?.abort(); setSourceId(event.target.value); }}>{sources.map(source => <option key={source.id} value={source.id}>{sourceName(source)}</option>)}</select></label>
      <div className={styles.captureState}><span className={styles.dot} data-active={shown?.generationConnected || false} /><strong>{busy === 'start' ? 'Starting capture' : !selectedId ? 'Connect a city camera to search' : shown ? LABELS[shown.state] ?? 'Status needs checking' : 'Reading capture status'}</strong><button type="button" aria-label="Refresh capture status" disabled={Boolean(busy)} onClick={() => setRefresh(value => value + 1)}><IconRefresh size={14} /></button></div>
      {continuous && <p className={styles.warning}>Continuous indexing is active on this camera. Switch to short captures to keep indexing bounded.</p>}
      {session && <div className={styles.session}><span>Capture {new Date(session.requestedAt).toLocaleDateString([], { month: 'short', day: 'numeric' })} · {time(session.requestedAt)}</span><strong>{range(session.startedAt || session.requestedAt, session.endedAt || (active ? new Date(Math.min(now, Date.parse(session.deadlineAt))).toISOString() : session.deadlineAt))}</strong><small>{active ? `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')} remaining` : 'Retained search window'}{hasDocuments ? ` · ${shown?.evidence.documentCount} indexed clips` : ' · index not confirmed'}</small></div>}
      <div className={styles.actions}>{shown?.state === 'stop-failed' ? <button type="button" disabled={Boolean(busy)} onClick={() => void act('cancel')}>Retry stop</button> : continuous ? <button type="button" className={styles.primary} disabled={Boolean(busy)} onClick={() => void act('policy')}>Use short captures</button> : active ? <button type="button" disabled={Boolean(busy)} onClick={() => void act('cancel')}><IconPlayerStop size={14} />Stop capture</button> : <button type="button" className={styles.primary} disabled={Boolean(busy) || !shown || !shown.configured || shown.sourcePaused || shown.state === 'stopping' || Boolean(error)} onClick={() => void act('start')}><IconVideoPlus size={15} />Index next 2 min</button>}{continuous && <button type="button" disabled={Boolean(busy)} onClick={() => void act('cancel')}>Stop indexing</button>}</div>
      {!session && !continuous && <p className={styles.note}>Index one short window when you want to show semantic search.</p>}
      {shown?.sourcePaused && <p className={styles.note}>Resume camera analysis before starting a new capture.</p>}
      {shown && !shown.configured && <p className={styles.warning}>Semantic indexing is not configured on this system.</p>}
      {error && <p role="alert" className={styles.warning}>{error}</p>}
      {actionError && <p role="alert" className={styles.warning}>{actionError}</p>}
      </div><form className={styles.search} onSubmit={event => { event.preventDefault(); void act('search'); }}><label htmlFor={`capture-query-${selectedId}`}>Find something in this capture</label><div><input id={`capture-query-${selectedId}`} value={query} onChange={event => setQuery(event.target.value)} maxLength={1000} placeholder="A bus stops at the curb" disabled={!canSearch || Boolean(busy)} /><button type="submit" disabled={!canSearch || !query.trim() || Boolean(busy)}><IconSearch size={15} />{busy === 'search' ? 'Searching…' : 'Find clips'}</button></div><div className={styles.queryExamples} aria-label="Example clip searches">{['People using the crossing', 'A vehicle stopped at the curb', 'Traffic turning at the intersection'].map(example => <button key={example} type="button" disabled={!canSearch || Boolean(busy)} onClick={() => setQuery(example)}>{example}</button>)}</div>{!canSearch && <small>{session?.startedAt ? 'Search is ready when clips reach the index.' : 'Start a capture to prepare searchable clips.'}</small>}</form>
      {(results || inline) && <div className={styles.results} aria-live="polite"><div className={styles.resultsHeading}><strong>{busy === 'search' ? 'Searching this capture…' : results ? results.results.length ? `${results.results.length} matching clip${results.results.length === 1 ? '' : 's'}` : 'No matches in this capture' : 'Search results'}</strong>{results ? <small>{sourceName({name:results.scope.sourceName})} · {range(results.scope.timestampStart, results.scope.timestampEnd)}</small> : <small>One camera · One capture</small>}</div>{results?.results.map((match, index) => <article key={`${match.sensor_id}:${match.start_time}:${index}`} data-selected={selectedMatch?.sensor_id === match.sensor_id && selectedMatch?.start_time === match.start_time && selectedMatch?.end_time === match.end_time}>{match.screenshot_url && <img src={proxyVstPictureUrl(match.screenshot_url)} alt="" loading="lazy" decoding="async" />}<div><strong>{range(match.start_time, match.end_time)}</strong><p>{match.description === 'VST live stream' ? 'Semantic video match' : match.description || 'Semantic video match'}</p>{onOpenEvidence && <button type="button" onClick={() => { onOpenEvidence(match); close(); }}>Open clip</button>}</div></article>)}{Boolean(results?.excludedResults) && <small>Unverified source or time matches were omitted.</small>}{results ? <small>Clip start times are inside this capture. Clips can extend past its end.</small> : <div className={styles.emptyResults}><IconSearch size={27} /><strong>Describe a moment to find it.</strong><p>Enter a description above. Results stay within the selected camera and capture.</p></div>}</div>}
      <footer>Only this camera and capture are searched. Existing footage is kept.</footer>
    </section>;
  return <>
    {!inline && <button ref={trigger} type="button" className={className ?? styles.trigger} disabled={disabled || !sources.length} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(value => !value)}><IconSearch size={15} /><span>Search capture</span></button>}
    {open && typeof document !== 'undefined' && (inline ? content : createPortal(content, document.body))}
  </>;
}
