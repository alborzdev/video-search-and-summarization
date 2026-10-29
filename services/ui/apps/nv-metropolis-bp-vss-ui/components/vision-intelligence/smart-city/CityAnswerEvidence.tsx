// SPDX-License-Identifier: MIT
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { IconArrowRight, IconPlayerPlay } from '@tabler/icons-react';
import type { VisionAnalystResponse } from '../analyst';
import { evidenceClipEndpoint } from '../evidenceClip';
import { liveAnswerWindow, normalizeAnswerEvidenceUrl, type CityAnswerSource } from './answerEvidence';
import styles from './SmartCity.module.css';

/** Exports only on a deliberate click, for the source and interval pinned to this answer. */
export function CityAnswerEvidence({ answer, source, selectionKey }: { answer: VisionAnalystResponse; source: CityAnswerSource; selectionKey: string }) {
  const [url, setUrl] = useState<string | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null); const generation = useRef(0); const deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const window = liveAnswerWindow(answer);
  const cancel = useCallback(() => { ++generation.current; controller.current?.abort('cancelled'); controller.current = null; if (deadline.current !== null) clearTimeout(deadline.current); deadline.current = null; }, []);
  useEffect(() => () => cancel(), [cancel]);
  useEffect(() => { cancel(); setLoading(false); setUrl(null); setError(null); }, [selectionKey, source.id, source.sensorId, source.vstApiUrl, window?.startTime, window?.endTime, cancel]);
  const prepare = async () => {
    if (!window || loading) return;
    cancel(); const current = generation.current; const pending = new AbortController(); controller.current = pending;
    setLoading(true); setError(null); setUrl(null); deadline.current = setTimeout(() => pending.abort('timeout'), 90_000);
    try {
      const response = await fetch(evidenceClipEndpoint(source.sensorId, window.startTime, window.endTime), { signal: pending.signal });
      const payload = await response.json().catch(() => { throw new Error('The evidence service returned an unreadable response.'); });
      if (generation.current !== current) return;
      if (pending.signal.aborted) throw new Error('Evidence request was cancelled.');
      if (!payload || typeof payload !== 'object') throw new Error('The evidence service returned an unreadable response.');
      if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error.slice(0, 1200) : 'The inspected clip could not be prepared.');
      if (payload.startTime !== undefined && (!Number.isFinite(Date.parse(payload.startTime)) || Math.abs(Date.parse(payload.startTime) - Date.parse(window.startTime)) > 1)) throw new Error('The evidence service returned a different observation start time.');
      const safe = normalizeAnswerEvidenceUrl(payload.videoUrl, globalThis.window.location.origin, source.vstApiUrl);
      if (!safe) throw new Error('The evidence service returned an unsupported media URL.');
      setUrl(safe);
    } catch (failure) {
      if (generation.current === current) setError(pending.signal.reason === 'timeout' ? 'The evidence request timed out. You can retry this answer’s interval.' : pending.signal.aborted ? null : failure instanceof Error ? failure.message : 'The inspected clip is unavailable.');
    } finally {
      if (generation.current === current) { setLoading(false); if (deadline.current !== null) clearTimeout(deadline.current); deadline.current = null; controller.current = null; }
    }
  };
  if (!window) return <p className={styles.muted}>A valid inspected interval of up to five seconds is unavailable. Evidence playback cannot be prepared for this answer.</p>;
  return <div className={styles.answerEvidence} data-answer-source-id={source.id} data-answer-sensor-id={source.sensorId} data-answer-window-start={window.startTime} data-answer-window-end={window.endTime}>
    {!url && <button type="button" className={styles.outlineButton} disabled={loading} onClick={() => void prepare()}><IconPlayerPlay size={17} />{loading ? 'Preparing inspected clip…' : 'Load inspected clip (up to 5 s)'}</button>}
    {loading && <button type="button" className={styles.quietButton} onClick={() => { cancel(); setLoading(false); setError('Evidence request cancelled.'); }}>Cancel evidence request</button>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {url && <><video className={styles.answerEvidenceVideo} src={url} controls playsInline preload="metadata" aria-label={`Inspected evidence from ${source.name}`} onLoadedMetadata={event => { if (!Number.isFinite(event.currentTarget.duration) || event.currentTarget.duration <= 0 || event.currentTarget.duration > 5.5) { event.currentTarget.pause(); setUrl(null); setError('The returned clip does not match the requested five-second interval.'); } }} onError={() => setError('The inspected clip could not be played. Its recording may no longer be retained.')} /><a className={styles.evidenceLink} href={url} target="_blank" rel="noreferrer">Open inspected clip<IconArrowRight size={16} /></a><p className={styles.muted}>This clip is the returned observation interval from {source.name}, not the current camera frame.</p></>}
  </div>;
}
