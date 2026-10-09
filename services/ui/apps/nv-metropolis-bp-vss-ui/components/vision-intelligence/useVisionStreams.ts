// SPDX-License-Identifier: MIT
import { useCallback, useEffect, useRef, useState } from 'react';

import type { VisionStream, VisionStreamsApiResponse } from './types';
import { parseVisionStreams } from './utils';

interface VisionStreamsState {
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
  streams: VisionStream[];
}

async function connectionStates(vstApiUrl: string): Promise<Record<string, { state?: string }>> {
  try {
    const response = await fetch(`${vstApiUrl}/v1/sensor/status`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return {};
    const data = await response.json();
    return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
  } catch { return {}; }
}

function withConnectionStates(streams: VisionStream[], states: Record<string, { state?: string }>): VisionStream[] {
  let changed = false;
  const next = streams.map((stream) => {
    const state = states[stream.sensorId]?.state;
    const connectionState = state === 'online' || state === 'offline' || state === 'removed' ? state : 'unknown';
    if (stream.connectionState === connectionState) return stream;
    changed = true;
    return { ...stream, connectionState } as VisionStream;
  });
  return changed ? next : streams;
}

export function useVisionStreams(vstApiUrl?: string | null, active = true): VisionStreamsState {
  const [streams, setStreams] = useState<VisionStream[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const populated = useRef(false);

  const refreshCatalog = useCallback(async (background: boolean) => {
    if (!vstApiUrl) {
      setError('Video I/O endpoint is not configured.');
      setIsLoading(false);
      return;
    }

    const request = ++generation.current;
    const current = () => request === generation.current;
    if (!populated.current) setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(`${vstApiUrl}/v1/live/streams`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) {
        throw new Error(`Video I/O returned ${response.status}.`);
      }
      const data = (await response.json()) as VisionStreamsApiResponse;
      let catalog = parseVisionStreams(data);
      if (catalog.length) {
        // Primary selection is appliance-local and persists across browser
        // sessions, including when the camera is temporarily disconnected.
        try {
          const preference = await fetch('/api/vision/primary-source', { signal: AbortSignal.timeout(5000) });
          if (preference.ok) {
            const { streamId } = await preference.json();
            if (typeof streamId === 'string')
              catalog = catalog.map(stream => ({ ...stream, isPrimary: stream.streamId === streamId }));
          }
        } catch { /* An unavailable optional preference must not hide cameras. */ }
      }
      if (!current()) return;
      // VST can briefly return an empty successful list while restoring its
      // sensors. Background polling must not unmount an operator's live desk.
      // Explicit refresh still lets the operator confirm an empty catalog.
      if (background && !catalog.length && populated.current) {
        setStreams((previous) => withConnectionStates(previous, {}));
        setError('Video I/O is restoring its source catalog. Showing previously known cameras until it responds.');
        return;
      }
      populated.current = catalog.length > 0;
      setStreams((previous) => withConnectionStates(catalog, Object.fromEntries(previous.map((stream) => [stream.sensorId, { state: stream.connectionState }]))));
      setIsLoading(false);
      const states = catalog.length ? await connectionStates(vstApiUrl) : {};
      if (current()) setStreams(withConnectionStates(catalog, states));
    } catch (requestError) {
      if (!current()) return;
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not load video sources.'
      );
    } finally {
      if (current()) setIsLoading(false);
    }
  }, [vstApiUrl]);

  const refresh = useCallback(() => refreshCatalog(false), [refreshCatalog]);

  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    // A successful empty catalog is common while offline services are starting.
    // Refresh catalogs as well as health so later camera registration is visible.
    const poll = async () => {
      await refreshCatalog(true);
      if (!disposed) timer = setTimeout(() => void poll(), 15_000);
    };
    void poll();
    return () => {
      disposed = true;
      ++generation.current;
      clearTimeout(timer);
    };
  }, [active, refreshCatalog]);

  return { error, isLoading, refresh, streams };
}
