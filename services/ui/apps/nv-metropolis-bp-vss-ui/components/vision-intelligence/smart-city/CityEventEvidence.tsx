// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { IconPlayerPlay } from '@tabler/icons-react';
import { evidenceClipEndpoint } from '../evidenceClip';
import { normalizeAnswerEvidenceUrl } from './answerEvidence';
import type { CityEvent, CitySource } from './types';
import styles from './SmartCity.module.css';

/** Use the event's declared source interval, never current footage or a guessed time. */
export function cityEventWindow(event: CityEvent, source: CitySource | undefined) {
  const evidence = event.evidence;
  if (event.mode !== 'live' || !source || source.id !== event.sourceId || evidence?.sourceId !== event.sourceId) return null;
  const start = evidence.startTimeNs; const end = evidence.endTimeNs;
  if (typeof start !== 'string' || typeof end !== 'string' || !/^\d{1,19}$/.test(start) || !/^\d{1,19}$/.test(end)) return null;
  const startNs = BigInt(start); const endNs = BigInt(end);
  if (startNs <= BigInt(0) || endNs <= startNs || endNs > BigInt('9223372036854775807') || endNs - startNs > BigInt('600000000000')) return null;
  const sensorId = source.vssSensorId ?? source.id;
  if (!/^[A-Za-z0-9_.:-]{1,160}$/.test(sensorId)) return null;
  return { sensorId, startTime: new Date(Number(startNs / BigInt(1_000_000))).toISOString(), endTime: new Date(Number(endNs / BigInt(1_000_000))).toISOString(), durationSeconds: Number(endNs - startNs) / 1e9 };
}

export function CityEventEvidence({ event, source, vstApiUrl }: { event: CityEvent; source: CitySource | undefined; vstApiUrl?: string | null }) {
  const interval = cityEventWindow(event, source);
  const [url, setUrl] = useState<string | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null); const generation = useRef(0);
  const cancel = () => { ++generation.current; controller.current?.abort(); controller.current = null; };
  useEffect(() => { cancel(); setUrl(null); setError(null); setLoading(false); return cancel; }, [event.id, event.sourceId, source?.id, interval?.sensorId, interval?.startTime, interval?.endTime, vstApiUrl]);
  const load = async () => {
    if (!interval || loading) return;
    cancel(); const current = generation.current; const pending = new AbortController(); controller.current = pending;
    const timeout = setTimeout(() => pending.abort('timeout'), 90_000);
    setLoading(true); setUrl(null); setError(null);
    try {
      const response = await fetch(evidenceClipEndpoint(interval.sensorId, interval.startTime, interval.endTime), { signal: pending.signal });
      const value = await response.json().catch(() => { throw new Error('The evidence service returned an unreadable response.'); });
      if (generation.current !== current) return;
      if (pending.signal.aborted) throw new Error('The request ended before confirmation.');
      if (!value || typeof value !== 'object') throw new Error('The evidence service returned an unreadable response.');
      if (!response.ok) throw new Error(typeof value?.error === 'string' ? value.error.slice(0, 1200) : 'The retained event interval is unavailable.');
      if (value.startTime !== undefined && (!Number.isFinite(Date.parse(value.startTime)) || Math.abs(Date.parse(value.startTime) - Date.parse(interval.startTime)) > 1)) throw new Error('The returned recording belongs to a different event interval.');
      const safe = normalizeAnswerEvidenceUrl(value.videoUrl, window.location.origin, vstApiUrl);
      if (!safe) throw new Error('The returned recording URL is not supported.');
      setUrl(safe);
    } catch (failure) {
      if (generation.current === current) setError(pending.signal.reason === 'timeout' ? 'The event footage request timed out. Try this interval again.' : pending.signal.aborted ? null : failure instanceof Error ? failure.message : 'Event footage is unavailable.');
    } finally {
      clearTimeout(timeout); if (generation.current === current) { setLoading(false); controller.current = null; }
    }
  };
  if (!interval) return <p className={styles.muted}>A valid retained source interval is unavailable for this event.</p>;
  return <section className={styles.eventEvidence} aria-label="Retained event footage" data-event-id={event.id} data-event-source-id={event.sourceId} data-event-window-start={interval.startTime} data-event-window-end={interval.endTime}>
    {!url && <button type="button" className={styles.primaryButton} disabled={loading} onClick={() => void load()}><IconPlayerPlay size={18} />{loading ? 'Preparing event footage…' : 'Review event footage'}</button>}
    {loading && <button type="button" className={styles.textButton} onClick={() => { cancel(); setLoading(false); }}>Cancel footage request</button>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {url && <><h3>Retained event interval</h3><video src={url} className={styles.eventEvidenceVideo} controls playsInline preload="metadata" aria-label={`Event footage from ${source?.name ?? 'the selected camera'}`} onLoadedMetadata={e => { const duration = e.currentTarget.duration; if (!Number.isFinite(duration) || duration <= 0 || Math.abs(duration - interval.durationSeconds) > 1) { e.currentTarget.pause(); setUrl(null); setError('The recording duration does not match this event’s requested interval.'); } }} onError={() => { setUrl(null); setError('This event recording could not be played. It may no longer be retained.'); }} /><p className={styles.muted}>Recording around this event. Check the visible action against the finding.</p></>}
  </section>;
}
