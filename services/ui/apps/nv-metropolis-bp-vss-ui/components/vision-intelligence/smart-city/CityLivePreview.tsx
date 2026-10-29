// SPDX-License-Identifier: MIT
import React, { useMemo } from 'react';
import { VisionStreamCanvas, type PlaybackStatus, type PresentedVideoFrame } from '../VisionStreamCanvas';
import { useVisionStreams } from '../useVisionStreams';
import { isLiveStream } from '../utils';
import type { CitySource } from './types';
import styles from './SmartCity.module.css';
export function CityLivePreview({ source, vstApiUrl, onFrame, onStatus }: {
  source: CitySource; vstApiUrl?: string | null;
  onFrame: (frame: PresentedVideoFrame) => void; onStatus: (status: PlaybackStatus) => void;
}) {
  const catalog = useVisionStreams(vstApiUrl);
  const stream = useMemo(() => catalog.streams.find(item => item.sensorId === (source.vssSensorId ?? source.id) || item.streamId === (source.vssSensorId ?? source.id)), [catalog.streams, source.id, source.vssSensorId]);
  if (!stream) return <div className={styles.mediaEmpty}><strong>{catalog.isLoading ? 'Connecting the VSS live camera…' : catalog.error ? 'Camera service unavailable' : 'Camera not found in VSS'}</strong><span>{catalog.error ? 'VSS could not load its camera list. Restore the video service, then retry.' : 'Register the RTSP source in VSS and use its source ID in the city site.'}</span><button type="button" className={styles.outlineButton} onClick={() => void catalog.refresh()}>Refresh cameras</button></div>;
  if (!isLiveStream(stream)) return <div className={styles.mediaEmpty}><strong>Waiting for an RTSP source</strong><span>This source is a recording. Register an RTSP camera to use live preview.</span></div>;
  return <div className={styles.livePreview}><VisionStreamCanvas stream={stream} vstApiUrl={vstApiUrl} eager showStatus liveSnapshotEnabled={false} onPresentedFrame={onFrame} onPlaybackStatus={onStatus} /></div>;
}
