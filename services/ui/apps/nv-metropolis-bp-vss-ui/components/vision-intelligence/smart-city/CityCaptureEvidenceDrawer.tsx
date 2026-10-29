// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useDialogAccessibility } from '@aiqtoolkit-ui/common';
import { IconClock, IconRefresh, IconVideo, IconX } from '@tabler/icons-react';
import { evidenceClipEndpoint } from '../evidenceClip';
import { normalizeAnswerEvidenceUrl } from './answerEvidence';
import { sourceName as displayCameraName } from './presentation';
import type { CityIndexingMatch } from './cityIndexing';
import styles from './CityCaptureEvidenceDrawer.module.css';

interface Props { inline?: boolean; match: CityIndexingMatch; sourceName?: string; vstApiUrl?: string | null; onClose: () => void }
type ClipState = { key: string; status: 'loading' | 'ready' | 'error'; url?: string; message?: string; verified?: boolean };
function timestamp(value: string) { return /(?:Z|[+-]\d\d:\d\d)$/i.test(value) && Number.isFinite(Date.parse(value)); }
function clock(value: string) { return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' }); }

/** Mounted only by an explicit Open clip action; one retained interval, no inference. */
export function CityCaptureEvidenceDrawer({ match, sourceName, vstApiUrl, onClose, inline = false }: Props) {
  const identity = `${match.sensor_id}:${match.start_time}:${match.end_time}`;
  const requestedSeconds = (Date.parse(match.end_time) - Date.parse(match.start_time)) / 1000;
  const valid = /^[A-Za-z0-9_.:-]{1,160}$/.test(match.sensor_id) && timestamp(match.start_time) && timestamp(match.end_time) && requestedSeconds > 0 && requestedSeconds <= 600;
  const [state, setState] = useState<ClipState>({ key: identity, status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const operation = useRef<AbortController | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const current = state.key === identity ? state : null;
  const registeredName = sourceName || match.video_name || 'Selected camera';
  const title = displayCameraName({ name: registeredName });
  const close = () => { operation.current?.abort(); video.current?.pause(); onClose(); };
  const dialog = useDialogAccessibility<HTMLElement>({ isOpen: !inline, onClose: close });

  useEffect(() => {
    if (!valid) { setState({ key: identity, status: 'error', message: 'This result has no valid camera and retained video interval.' }); return; }
    const controller = new AbortController(); operation.current = controller;
    let stopped = false;
    const deadline = setTimeout(() => { controller.abort('timeout'); if (!stopped) setState({ key: identity, status: 'error', message: 'Clip preparation timed out. Retry this result or choose a more recent capture.' }); }, 90_000);
    setState({ key: identity, status: 'loading' });
    const load = async () => {
      try {
        const response = await fetch(evidenceClipEndpoint(match.sensor_id, match.start_time, match.end_time), { signal: controller.signal, cache: 'no-store' });
        const payload = await response.json();
        if (stopped || controller.signal.aborted) return;
        if (!response.ok) throw new Error(response.status === 410 ? 'The recording for this result is no longer retained. Capture a new window to find recent clips.' : typeof payload?.error === 'string' ? payload.error.slice(0, 500) : 'The retained clip could not be prepared. Retry this result.');
        if (!payload || typeof payload !== 'object' || typeof payload.startTime !== 'string' || !timestamp(payload.startTime) || Math.abs(Date.parse(payload.startTime) - Date.parse(match.start_time)) > 1) throw new Error('The returned clip does not confirm the selected start time. Playback was withheld.');
        const url = normalizeAnswerEvidenceUrl(payload.videoUrl, window.location.origin, vstApiUrl);
        if (!url) throw new Error('The evidence service returned an unsupported media URL.');
        setState({ key: identity, status: 'ready', url, verified: false });
      } catch (cause) {
        if (!stopped) setState({ key: identity, status: 'error', message: controller.signal.aborted ? 'Clip preparation timed out. Retry this result or choose a more recent capture.' : cause instanceof Error ? cause.message : 'The retained clip is unavailable.' });
      } finally { clearTimeout(deadline); if (operation.current === controller) operation.current = null; }
    };
    void load();
    return () => { stopped = true; clearTimeout(deadline); controller.abort(); if (operation.current === controller) operation.current = null; };
  }, [identity, match.sensor_id, match.start_time, match.end_time, valid, vstApiUrl, attempt]);

  const validateDuration = (element: HTMLVideoElement) => {
    const tolerance = Math.max(.5, Math.min(1, requestedSeconds * .02));
    if (!Number.isFinite(element.duration) || element.duration <= 0 || Math.abs(element.duration - requestedSeconds) > tolerance) {
      element.pause(); element.removeAttribute('src'); element.load();
      setState(previous => previous.key === identity ? { key: identity, status: 'error', message: 'The returned video length does not match the selected interval. Playback was withheld.' } : previous);
      return;
    }
    setState(previous => previous.key === identity && previous.status === 'ready' ? { ...previous, verified: true } : previous);
  };
  if (typeof document === 'undefined') return null;
  const content = <aside ref={inline ? undefined : dialog} className={`${styles.drawer} ${inline ? styles.inline : ''}`} role={inline ? 'region' : 'dialog'} aria-modal="false" aria-label="Retained search clip" data-source-id={match.sensor_id} data-start-time={match.start_time} data-end-time={match.end_time}>
    <header><div><span className={styles.eyebrow}><IconVideo size={13} />Retained video</span><h2>{title}</h2></div><button type="button" onClick={close} aria-label="Close retained clip"><IconX size={19} /></button></header>
    <div className={styles.interval}><IconClock size={14} /><div><strong>Selected recording interval</strong><time>{valid ? `${clock(match.start_time)} – ${clock(match.end_time)}` : 'Unavailable'}</time></div></div>
    <div className={styles.media}>
      {current?.status === 'ready' && current.url ? <video key={identity} ref={video} src={current.url} controls={current.verified} playsInline preload="metadata" aria-label={`Retained clip from ${title}`} onLoadedMetadata={event => validateDuration(event.currentTarget)} onError={() => setState(previous => previous.key === identity && previous.status === 'ready' ? { key: identity, status: 'error', message: 'This retained clip could not be played. Its recording may have expired.' } : previous)} /> : <div className={styles.placeholder} role={current?.status === 'error' ? undefined : 'status'}><IconVideo size={29} /><strong>{current?.status === 'error' ? 'Clip unavailable' : 'Preparing this clip…'}</strong><span>{current?.status === 'error' ? 'Live camera analysis continues.' : 'Loading only the selected camera and interval.'}</span></div>}
      {current?.status === 'ready' && !current.verified && <span className={styles.verifying} role="status">Checking recorded clip length…</span>}
    </div>
    {current?.status === 'error' && <div className={styles.failure}><p role="alert">{current.message}</p>{valid && <button type="button" onClick={() => setAttempt(value => value + 1)}><IconRefresh size={14} />Retry clip</button>}</div>}
    {current?.verified && <p className={styles.ready}>{requestedSeconds.toFixed(1)} s retained clip · Play to review</p>}
    {match.description && match.description !== 'VST live stream' && <p className={styles.description}>{match.description}</p>}
    <details className={styles.source}><summary>Camera and time reference</summary><dl><dt>Registered camera</dt><dd>{registeredName}</dd><dt>Camera UUID</dt><dd>{match.sensor_id}</dd><dt>Start</dt><dd>{match.start_time}</dd><dt>End</dt><dd>{match.end_time}</dd></dl></details>
    <footer>Live camera analysis continues while you review this recording.</footer>
  </aside>;
  return inline ? content : createPortal(content, document.body);
}
