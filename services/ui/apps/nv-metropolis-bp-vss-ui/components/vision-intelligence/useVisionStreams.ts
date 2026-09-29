// SPDX-License-Identifier: MIT
import { useCallback, useEffect, useState } from 'react';

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

  const refresh = useCallback(async () => {
    if (!vstApiUrl) {
      setError('Video I/O endpoint is not configured.');
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(`${vstApiUrl}/v1/live/streams`);
      if (!response.ok) {
        throw new Error(`Video I/O returned ${response.status}.`);
      }
      const data = (await response.json()) as VisionStreamsApiResponse;
      const catalog = parseVisionStreams(data);
      setStreams(withConnectionStates(catalog, {}));
      setIsLoading(false);
      const states = catalog.length ? await connectionStates(vstApiUrl) : {};
      setStreams(withConnectionStates(catalog, states));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not load video sources.'
      );
    } finally {
      setIsLoading(false);
    }
  }, [vstApiUrl]);

  useEffect(() => {
    if (active) void refresh();
  }, [active, refresh]);

  // Connection health is independent of whether AI ingestion is paused.
  useEffect(() => {
    if (!active || !vstApiUrl || !streams.length) return;
    let disposed = false;
    const interval = window.setInterval(async () => {
      const states = await connectionStates(vstApiUrl);
      if (!disposed) setStreams((current) => withConnectionStates(current, states));
    }, 15_000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, [active, vstApiUrl, streams.length]);

  // Recover a failed catalog after local video services restart, without a page reload.
  useEffect(() => {
    if (!active || !error || !vstApiUrl || isLoading) return;
    const retry = window.setTimeout(() => void refresh(), 15_000);
    return () => window.clearTimeout(retry);
  }, [active, error, isLoading, refresh, vstApiUrl]);

  return { error, isLoading, refresh, streams };
}
