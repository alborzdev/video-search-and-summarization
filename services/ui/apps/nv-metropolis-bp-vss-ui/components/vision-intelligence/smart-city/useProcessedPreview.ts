// SPDX-License-Identifier: MIT
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CityPreviewContext, CityPreviewFrame } from './types';
import { matchesPreviewContext, parsePreviewEnvelope, PREVIEW_STALE_MS, readPreviewBytes } from './processedPreview';
import { CITY_API } from './useCity';

export interface PreviewPair {
  frame: CityPreviewFrame; bitmap: ImageBitmap; receivedAtMs: number; configurationKey: string; released?: boolean;
  /** bitmaprenderer consumes the bitmap. It may only be reused on this canvas. */
  transferredTo?: HTMLCanvasElement;
  timing?: { requestMs: number; decodeMs: number; readyAtMs: number };
}
function release(pair: PreviewPair) { if (!pair.released) { pair.released = true; pair.bitmap.close(); } }

/** One bounded request/decode at a time; presentation never outruns its own DTO. */
export function useProcessedPreview(sourceId: string, enabled: boolean, expectedSession?: string, context?: CityPreviewContext, nativeFpsLimit?: number) {
  const [pair, setPair] = useState<PreviewPair | null>(null);
  // React may skip intermediate state updates. Own decoded pixels before commit as well.
  const pendingPair = useRef<PreviewPair | null>(null);
  const committedPair = useRef<PreviewPair | null>(null);
  // Native limits are whole frames/s, 1..30. Unknown health retains the safe default.
  const fpsLimit = typeof nativeFpsLimit === 'number' && Number.isInteger(nativeFpsLimit) && nativeFpsLimit >= 1 ? Math.min(30, nativeFpsLimit) : 15;
  const intervalMs = useRef(1000 / fpsLimit);
  useLayoutEffect(() => { intervalMs.current = 1000 / fpsLimit; }, [fpsLimit]);
  const configurationKey = context?.configurationKey;
  const eligible = enabled && Boolean(expectedSession && context && context.sourceId === sourceId);
  useEffect(() => {
    const clearPending = () => {
      const pending = pendingPair.current; pendingPair.current = null;
      if (pending && pending !== committedPair.current) release(pending);
    };
    const publish = (next: PreviewPair | null) => {
      clearPending(); pendingPair.current = next; setPair(next);
    };
    publish(null);
    if (!eligible || typeof createImageBitmap !== 'function') return;
    let active = true; let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null; let etag: string | null = null; let lastNewFrame: number | null = null; let lastStarted = -Infinity;
    const tick = async () => {
      if (!active) return;
      // A changed health limit must not restart a valid pair or race an already scheduled read.
      const remaining = Math.ceil(intervalMs.current - (performance.now() - lastStarted));
      if (remaining > 0) { timer = setTimeout(() => void tick(), remaining); return; }
      const started = performance.now();
      lastStarted = started;
      let ready = false;
      controller = new AbortController(); const requestController = controller;
      const deadline = setTimeout(() => requestController.abort(), 1500);
      try {
        const response = await fetch(`${CITY_API}/preview/${encodeURIComponent(sourceId)}?waitMs=1000`, { signal: requestController.signal, cache: 'no-store', headers: etag ? { 'If-None-Match': etag } : {} });
        if (!active || requestController.signal.aborted) return;
        if (response.status === 304) {
          ready = lastNewFrame !== null && performance.now() - lastNewFrame < PREVIEW_STALE_MS;
          if (!ready) { etag = null; publish(null); }
        } else if (response.status === 204 || response.status === 404) {
          etag = null; lastNewFrame = null; publish(null);
        } else {
          if (!response.ok || !response.headers.get('Content-Type')?.startsWith('application/vnd.connecttech.city-frame')) throw new Error('Analyzed preview is unavailable.');
          const { frame, jpeg } = parsePreviewEnvelope(await readPreviewBytes(response, requestController.signal), sourceId);
          if (!active || requestController.signal.aborted) return;
          if (!matchesPreviewContext(frame, context, expectedSession)) throw new Error('Analyzed preview belongs to a previous site configuration.');
          const decodeStarted = performance.now();
          const bitmap = await createImageBitmap(new Blob([jpeg as BlobPart], { type: 'image/jpeg' }));
          if (!active || requestController.signal.aborted) { bitmap.close(); return; }
          if (bitmap.width !== frame.image.jpegWidth || bitmap.height !== frame.image.jpegHeight) { bitmap.close(); throw new Error('Analyzed preview dimensions differ from its frame metadata.'); }
          etag = response.headers.get('ETag'); lastNewFrame = performance.now(); ready = true;
          const readyAtMs = performance.now();
          publish({ frame, bitmap, receivedAtMs: Date.now(), configurationKey: configurationKey!,
            timing: { requestMs: decodeStarted - started, decodeMs: readyAtMs - decodeStarted, readyAtMs } });
        }
      } catch {
        ready = active && lastNewFrame !== null && performance.now() - lastNewFrame < PREVIEW_STALE_MS;
        if (active && !ready) { publish(null); etag = null; }
      } finally {
        clearTimeout(deadline); controller = null;
        // Request and decode time belong inside the interval, not on top of it.
        if (active) timer = setTimeout(() => void tick(), ready ? Math.max(0, Math.ceil(intervalMs.current - (performance.now() - started))) : 1000);
      }
    };
    void tick();
    return () => { active = false; controller?.abort(); if (timer !== null) clearTimeout(timer); clearPending(); };
  }, [sourceId, eligible, expectedSession, configurationKey]);
  const current = Boolean(eligible && pair && !pair.released && pair.configurationKey === configurationKey && matchesPreviewContext(pair.frame, context, expectedSession));
  useLayoutEffect(() => {
    if (!pair) return;
    if (pendingPair.current === pair) pendingPair.current = null;
    if (!current) { release(pair); return; }
    committedPair.current = pair;
    const expiry = setTimeout(() => setPair(current => current === pair ? null : current), PREVIEW_STALE_MS);
    return () => { clearTimeout(expiry); if (committedPair.current === pair) committedPair.current = null; release(pair); };
  }, [pair, current, configurationKey]);
  return current ? pair : null;
}
