// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { IconPlayerPlay, IconPlayerStop, IconRefresh } from '@tabler/icons-react';
import { useDocumentVisible } from './useDocumentVisible';
import styles from './CityDetectionControl.module.css';

export interface DetectionStatus {
  schemaVersion: 'city.detections.v1'; state: 'running' | 'paused' | 'stopped'; ready: boolean;
  detail: string; sources: { id: string; name: string }[]; lastExitCode: number | null;
}
type Action = 'start' | 'stop' | 'restart';

export function CityDetectionControl({ siteId, analyzedCount, disabled = false, onChanged, onStatusChange }: {
  siteId: string; analyzedCount: number; disabled?: boolean; onChanged?: () => void; onStatusChange?: (state: DetectionStatus['state'] | null) => void;
}) {
  const visible = useDocumentVisible();
  const [status, setStatus] = useState<{ siteId: string; value: DetectionStatus } | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState(''); const [statusError, setStatusError] = useState('');
  const action = useRef<AbortController | null>(null);
  useEffect(() => {
    setBusy(null); setError(''); setStatusError('');
    return () => { action.current?.abort(); action.current = null; };
  }, [siteId]);
  useEffect(() => {
    if (!visible || busy) return;
    let active = true; let timer: ReturnType<typeof setTimeout>; let reader: AbortController;
    async function poll() {
      reader = new AbortController(); const deadline = setTimeout(() => reader.abort(), 8000);
      try {
        const response = await fetch('/api/vision/city-detections', { cache: 'no-store', signal: reader.signal });
        const value = await response.json();
        if (!response.ok || value.schemaVersion !== 'city.detections.v1') throw new Error(value.error || 'Detection status is unavailable.');
        if (active) { setStatus({ siteId, value }); setStatusError(''); }
      } catch (cause) {
        if (active) setStatusError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : 'Detection status timed out. Retrying…');
      } finally { clearTimeout(deadline); if (active) timer = setTimeout(poll, 3000); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); reader?.abort(); };
  }, [siteId, visible, busy]);
  const current = status?.siteId === siteId ? status.value : null;
  // A failed status read is not an instruction to resume a paused camera.
  const detectionState = current?.state ?? null;
  useEffect(() => { onStatusChange?.(detectionState); }, [detectionState, onStatusChange]);
  async function control(next: Action) {
    if (action.current || disabled) return;
    const request = new AbortController(); action.current = request;
    setBusy(next); setError('');
    const deadline = setTimeout(() => request.abort(), 50000);
    try {
      const response = await fetch('/api/vision/city-detections', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: next }), signal: request.signal });
      const value = await response.json();
      if (!response.ok || value.schemaVersion !== 'city.detections.v1') throw new Error(value.error || 'Detection control did not complete.');
      if (action.current === request) { setStatus({ siteId, value }); setStatusError(''); onChanged?.(); }
    } catch (cause) {
      if (action.current === request) setError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : 'The request timed out. Check detection status before retrying.');
    } finally {
      clearTimeout(deadline);
      if (action.current === request) { action.current = null; setBusy(null); }
    }
  }
  const running = current?.state === 'running';
  const confirmed = running && current.sources.length > 0 && analyzedCount >= current.sources.length;
  // Detector operation and preview delivery are independent. A late display
  // frame must not toggle the worker's on/off indicator or announce a restart.
  const label = busy ? busy === 'stop' ? 'Stopping detections…' : 'Connecting detections…'
    : statusError ? 'Detection status unavailable'
    : !current ? 'Checking detections…' : current.state === 'paused' ? 'Detections off'
      : !running ? 'Detections stopped' : `Detections on · ${current.sources.length} cameras`;
  const unavailable = !current || Boolean(statusError) || Boolean(busy) || disabled;
  return <section className={styles.controls} aria-label="Detection controls" aria-busy={Boolean(busy)}>
    <div className={styles.summary}><span className={styles.dot} data-active={Boolean(running && !busy && !statusError)} /><div>
      <strong role="status">{label}</strong><small>{current?.state === 'paused' ? 'Camera video stays available.'
        : disabled ? 'Preparing scenario…' : running && !confirmed ? 'Waiting for camera previews · detections remain on' : 'People and vehicles · tracking and map updates'}</small>
    </div></div>
    <div className={styles.actions}>
      {running && <button type="button" disabled={unavailable || !current.ready} onClick={() => void control('restart')}><IconRefresh size={15} />Reconnect detections</button>}
      <button type="button" className={!running ? styles.start : undefined} disabled={unavailable || (!running && (!current.ready || !current.sources.length))}
        onClick={() => void control(running ? 'stop' : 'start')}>
        {running ? <IconPlayerStop size={15} /> : <IconPlayerPlay size={15} />}{running ? 'Stop detections' : 'Start detections'}
      </button>
    </div>
    {(error || statusError || (current && !current.ready)) && <p className={styles.error} role="alert">{error || statusError || current?.detail}</p>}
    {current && !current.sources.length && <p className={styles.note}>Connect Smart City cameras in Live cameras before starting detections.</p>}
  </section>;
}
