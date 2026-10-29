// SPDX-License-Identifier: MIT
import React, { useEffect, useState } from 'react';
import { captureScenarioFrame } from './scenarioFrameCapture';
import { OBSERVATION_INTERVAL_MS, type ScenarioObservation, type ScenarioObservationFrame } from './scenarioObservation';
import styles from './ScenarioVlmObservation.module.css';
interface Props {
  siteId: string; scenarioId: string; epoch?: string; runId?: string | null;
  sourceId?: string; sessionId?: string; sourceName?: string; enabled: boolean;
}
export function observationMatches(value: ScenarioObservation, frame: ScenarioObservationFrame): boolean {
  return !!value && ['scenarioId', 'epoch', 'runId', 'sourceId', 'sessionId'].every(key =>
    value[key as keyof ScenarioObservation] === frame[key as keyof ScenarioObservationFrame]) &&
    typeof value.sourceTimeNs === 'string' && /^\d{1,24}$/.test(value.sourceTimeNs) &&
    (value.sourceTimeNs === frame.sourceTimeNs || value.shared === true && Date.now() - Date.parse(value.observedAt) <= 8000 && Date.parse(value.observedAt) <= Date.now() + 1000) &&
    typeof value.text === 'string' && value.text.length > 0 && value.text.length <= 1000 &&
    typeof value.observedAt === 'string' && Date.parse(value.observedAt) === Number(BigInt(value.sourceTimeNs) / BigInt(1_000_000)) &&
    Number.isFinite(value.inferenceMs) && value.inferenceMs >= 0;
}
export function ScenarioVlmObservation({ siteId, scenarioId, epoch, runId, sourceId, sessionId, sourceName, enabled }: Props) {
  const [paused, setPaused] = useState(false);
  const [visible, setVisible] = useState(true);
  const [result, setResult] = useState<{ key: string; value: ScenarioObservation } | null>(null);
  const [status, setStatus] = useState('Activates when the camera flags this area.');
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(0);
  const key = JSON.stringify([siteId, scenarioId, epoch, runId, sourceId, sessionId]);
  const observation = result?.key === key ? result.value : null;
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden'); update();
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    let disposed = false; let timer: ReturnType<typeof setTimeout>; let controller: AbortController | undefined;
    setBusy(false);
    if (!enabled) { setStatus('Activates when the camera flags this area.'); return; }
    if (paused || !visible || !epoch || !runId || !sourceId || !sessionId) return;
    const identity = { siteId, scenarioId, epoch, runId, sourceId, sessionId };
    const poll = async () => {
      const started = Date.now(); controller = new AbortController();
      let deadline: ReturnType<typeof setTimeout> | undefined;
      let requested = false;
      try {
        const frame = captureScenarioFrame(identity);
        if (!frame) { setStatus('Waiting for a fresh camera frame…'); return; }
        requested = true;
        setBusy(true); setStatus('Reading the camera frame…');
        deadline = setTimeout(() => controller?.abort(), 50_000);
        const response = await fetch('/api/vision/city-observation', { method: 'POST', signal: controller.signal,
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(frame) });
        const value = await response.json();
        if (disposed) return;
        if (!response.ok) throw new Error(typeof value.error === 'string' ? value.error : 'VLM unavailable · retrying shortly.');
        if (!observationMatches(value, frame)) throw new Error('Waiting for an observation from this run.');
        setResult({ key, value }); setNow(Date.now()); setStatus('');
      } catch (error) {
        if (!disposed) setStatus(error instanceof Error && error.name !== 'AbortError' ? error.message : 'VLM took too long · retrying shortly.');
      } finally {
        clearTimeout(deadline);
        // Metadata can arrive just after an RTP frame. Retry that local read
        // promptly; only model requests use the three-second cadence.
        if (!disposed) { setBusy(false); timer = setTimeout(poll, requested ? Math.max(1000, OBSERVATION_INTERVAL_MS - (Date.now() - started)) : 250); }
      }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
  }, [siteId, scenarioId, epoch, runId, sourceId, sessionId, key, enabled, paused, visible]);
  useEffect(() => {
    if (!observation) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [observation]);
  const age = observation ? Math.max(0, Math.floor((now - Date.parse(observation.observedAt)) / 1000)) : 0;
  const held = paused || !visible || !enabled;
  return <section className={styles.observation} aria-label="VLM observation" data-state={held ? 'paused' : busy ? 'reading' : observation ? 'observed' : 'waiting'}>
    <header><strong><i />Cosmos VLM</strong><span>{paused ? 'Paused' : !visible ? 'Tab hidden' : busy ? 'Reading frame' : observation ? age > 12 || !enabled ? 'Last observation' : 'Frame observation' : 'Waiting for event'}</span>
      <button type="button" aria-label={paused ? 'Resume VLM observations' : 'Pause VLM observations'} onClick={() => setPaused(value => !value)}>{paused ? 'Resume' : 'Pause'}</button></header>
    <div role="status" aria-live="polite" aria-atomic="true"><p>{observation?.text ?? (paused ? 'VLM observations paused.' : status)}</p></div>
    {observation && <footer><span title={`${sourceName ?? 'Camera'} · ${observation.observedAt}`}>{sourceName ?? 'Camera'} · frame {age}s ago</span><span>{(observation.inferenceMs / 1000).toFixed(1)}s analysis</span></footer>}
    {observation && status && !busy && !held && <small>{status}</small>}
  </section>;
}
