// SPDX-License-Identifier: MIT
import { useEffect, useState } from 'react';
import { cityRequest } from './useCity';
import { useDocumentVisible } from './useDocumentVisible';
export interface PreviewDeliverySource {
  sourceId: string; observedEncodedFps?: number; observedPublishedFps?: number;
  selected?: number; encoded?: number; published?: number; rateDropped?: number;
  sourceQueueOverruns?: number; networkQueueDropped?: number; postFailed?: number;
  pendingDropped?: number; identityMissing?: number; identityEvicted?: number; oversizeDropped?: number;
  timingMs?: Partial<Record<'selectedToJpeg' | 'selectedToEncode' | 'postQueue' | 'post', { count: number; mean: number; last: number; max: number; p50Upper: number; p95Upper: number }>>;
}
export interface PreviewDeliveryHealth { status: string; transport?: 'jpeg' | 'webrtc'; codec?: string; enabled?: boolean; failed?: boolean; fpsLimitPerSource?: number; deliveryAgeSeconds?: number; sources: PreviewDeliverySource[]; }
/** Delivery counters describe the preview transport, independently of capture clocks. */
export function usePreviewHealth(enabled: boolean) {
  const visible = useDocumentVisible();
  const [health, setHealth] = useState<PreviewDeliveryHealth | null>(null);
  useEffect(() => {
    setHealth(null); if (!enabled || !visible) return;
    let active = true; let timer: ReturnType<typeof setTimeout> | null = null; let controller: AbortController | null = null;
    const poll = async () => {
      controller = new AbortController(); const pending = controller;
      const timeout = setTimeout(() => pending.abort(), 1500);
      try {
        const value = await cityRequest<{ processedPreview?: { nativeDelivery?: PreviewDeliveryHealth } }>('health', { signal: pending.signal });
        if (active && !pending.signal.aborted) setHealth(Array.isArray(value.processedPreview?.nativeDelivery?.sources) ? value.processedPreview!.nativeDelivery! : null);
      } catch { if (active) setHealth(null); }
      finally { clearTimeout(timeout); if (active) timer = setTimeout(() => void poll(), 2000); }
    };
    void poll();
    return () => { active = false; controller?.abort(); if (timer !== null) clearTimeout(timer); };
  }, [enabled, visible]);
  return health;
}
