// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';
import { IconSparkles } from '@tabler/icons-react';
import { captureSceneFrame } from './scenarioFrameCapture';
import type { SceneDescription } from './sceneDescription';
import styles from './SceneDescriptionBar.module.css';

interface Props {
  siteId: string; epoch?: string; sourceId?: string; sessionId?: string;
  sourceName?: string; enabled: boolean;
}
export function SceneDescriptionBar({ siteId, epoch, sourceId, sessionId, sourceName, enabled }: Props) {
  const [result, setResult] = useState<{ key: string; value: SceneDescription } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const key = JSON.stringify([siteId, epoch, sourceId, sessionId]);
  const description = result?.key === key ? result.value : null;
  const ready = enabled && !!epoch && !!sourceId && !!sessionId;
  useEffect(() => {
    setBusy(false); setError('');
    return () => { request.current?.abort(); request.current = null; };
  }, [key, enabled]);

  async function describe() {
    if (!ready || request.current || !epoch || !sourceId || !sessionId) return;
    const controller = new AbortController(); request.current = controller;
    const deadline = setTimeout(() => controller.abort(), 50_000);
    setBusy(true); setError('');
    try {
      const identity = { siteId, epoch, sourceId, sessionId };
      let frame = captureSceneFrame(identity);
      // Exact-frame metadata can trail the displayed RTP frame. Retry locally
      // for two seconds; one operator click still sends just one model request.
      for (let i = 0; !frame && i < 8 && !controller.signal.aborted; i++) {
        await new Promise(resolve => setTimeout(resolve, 250));
        frame = captureSceneFrame(identity);
      }
      if (controller.signal.aborted) return;
      if (!frame) throw new Error('Camera frame not ready. Try again in a moment.');
      const response = await fetch('/api/vision/city-description', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(frame) });
      const value: SceneDescription & { error?: string } = await response.json();
      if (request.current !== controller) return;
      if (!response.ok) throw new Error(value.error || 'Could not describe this frame. Try again.');
      if (!value || !['siteId', 'epoch', 'sourceId', 'sessionId', 'sourceTimeNs'].every(field =>
        value[field as keyof SceneDescription] === frame![field as keyof typeof frame]) ||
        typeof value.text !== 'string' || !value.text.trim() || value.text.length > 1000 ||
        Date.parse(value.observedAt) !== Number(BigInt(frame.sourceTimeNs) / BigInt(1_000_000))) {
        throw new Error('The scene changed. Describe the new view again.');
      }
      setResult({ key, value });
    } catch (failure) {
      if (request.current === controller) setError(controller.signal.aborted ? 'Description timed out. Try again.' : failure instanceof Error ? failure.message : 'Could not describe this frame. Try again.');
    } finally {
      clearTimeout(deadline);
      if (request.current === controller) { request.current = null; setBusy(false); }
    }
  }
  return <section className={styles.bar} aria-label="Scene description">
    <button type="button" className={styles.button} onClick={() => void describe()} disabled={!ready || busy}>
      {busy ? <span className="vi-spinner" /> : <IconSparkles size={17} />}<span>{busy ? 'Describing…' : 'Describe scene'}</span>
    </button>
    <div className={styles.copy} role="status" aria-live="polite" aria-atomic="true">
      <p>{busy ? 'Reading a fresh camera frame…' : error || description?.text || (ready ? 'Get a short description of the current view.' : 'Waiting for a live camera frame.')}</p>
      <small>{description && !busy && !error ? `Cosmos VLM · ${sourceName ?? 'Camera'} · captured ${new Date(description.observedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : sourceName ? `Cosmos VLM · ${sourceName}` : 'Cosmos VLM'}</small>
    </div>
  </section>;
}
