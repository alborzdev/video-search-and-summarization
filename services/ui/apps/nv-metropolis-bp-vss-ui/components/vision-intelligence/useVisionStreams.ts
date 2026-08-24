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

export function useVisionStreams(vstApiUrl?: string | null): VisionStreamsState {
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
      setStreams(parseVisionStreams(data));
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
    void refresh();
  }, [refresh]);

  return { error, isLoading, refresh, streams };
}

