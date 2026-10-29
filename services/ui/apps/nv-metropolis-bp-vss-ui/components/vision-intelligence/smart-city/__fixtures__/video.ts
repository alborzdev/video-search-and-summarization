// SPDX-License-Identifier: MIT
import { previewContext } from '../processedPreview';
import type { CityVideoFrame } from '../types';
import type { VideoManifest } from '../trackedVideo';
export const source = { id: 'a', name: 'Camera A', width: 1000, height: 1000, browserClockVerified: false };
export const context = previewContext({ id: 'city', revision: 1, mode: 'live' } as any, source, 1);
export const manifest: VideoManifest = { schemaVersion: 'city.video-manifest.v1', key: 'a'.repeat(64), sourceId: 'a',
  sessionId: 'epoch', sourceSessionId: 'native', snapshot: { siteId: 'city', siteRevision: 1, mode: 'live', sources: [source], rulesRevision: 1, rules: [], zones: [] } as any };
export function wire(sequence = 1, rtp = 9000, x = 100): CityVideoFrame {
  const ns = String(BigInt('1700000000000000000') + BigInt(sequence) * BigInt(100000000));
  return { schemaVersion: 'city.video-frame.v1', manifestKey: manifest.key, sourceId: 'a', sourceSessionId: 'native', sessionId: 'epoch',
    sequence: String(sequence), sourceTimeNs: ns, timestampBasis: 'source-rtcp', modelRevision: 'model-1', image: { width: 1000, height: 1000 },
    provenance: { kind: 'native-webrtc-exact-frame', correlation: 'source-session-sequence-time-rtp', clockAlignment: 'source-frame-exact', browserClockVerified: false },
    transport: { kind: 'webrtc-rtp', rtpTimestamp: rtp, clockRate: 90000, codec: 'H264', encoder: 'nvenc-h264' },
    snapshot: { timestamp: '2026-10-28T00:00:00Z', sequence, sources: [{ sessionId: 'epoch', sourceSessionId: 'native', sequence: String(sequence),
      timestampBasis: 'source-rtcp', modelRevision: 'model-1', lastSourceTimeNs: ns }],
      tracks: [{ id: 'a:epoch:7', sourceId: 'a', sessionId: 'epoch', localTrackId: '7', class: 'car', bboxPx: [x, 100, 100, 200], confidence: .9, stale: false, observedThisFrame: true, positionM: null, trail: [] }],
      zones: [], events: [], metrics: [] } as any };
}
