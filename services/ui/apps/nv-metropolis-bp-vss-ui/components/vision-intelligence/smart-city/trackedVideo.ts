// SPDX-License-Identifier: MIT
import type { CityPreviewContext, CitySnapshot, CityVideoFrame } from './types';
import { matchesPreviewContext, PREVIEW_STALE_MS } from './processedPreview';
import { nativeSeiClockEvidence, nativeSeiSourceClock } from './sourceClock';

export interface VideoManifest {
  schemaVersion: 'city.video-manifest.v1'; key: string; sourceId: string;
  sessionId: string; sourceSessionId: string; snapshot: CitySnapshot;
}
export function parseVideoManifest(text: string, sourceId: string, session: string): VideoManifest {
  if (text.length > 512 * 1024) throw new Error('Camera manifest exceeds its limit.');
  const value = JSON.parse(text) as VideoManifest;
  if (value.schemaVersion !== 'city.video-manifest.v1' || !/^[a-f0-9]{64}$/.test(value.key)
    || value.sourceId !== sourceId || value.sessionId !== session || typeof value.sourceSessionId !== 'string'
    || !Array.isArray(value.snapshot?.sources) || value.snapshot.sources.length !== 1 || value.snapshot.sources[0].id !== sourceId
    || !Array.isArray(value.snapshot.rules) || !Array.isArray(value.snapshot.zones)) throw new Error('Invalid camera manifest.');
  return value;
}
export function parseVideoFrame(text: string, manifest: VideoManifest, context: CityPreviewContext, session: string): CityVideoFrame {
  if (text.length > 512 * 1024) throw new Error('Camera frame metadata exceeds its limit.');
  const value = JSON.parse(text) as CityVideoFrame;
  const dynamic = value.snapshot;
  if (value.schemaVersion !== 'city.video-frame.v1' || value.manifestKey !== manifest.key
    || value.sourceId !== manifest.sourceId || value.sessionId !== manifest.sessionId || value.sourceSessionId !== manifest.sourceSessionId
    || !Array.isArray(dynamic?.sources) || dynamic.sources.length !== 1 || !Array.isArray(dynamic.zones)
    || !['tracks', 'events', 'metrics'].every(key => Array.isArray(dynamic[key as keyof CitySnapshot]))) throw new Error('Invalid camera frame.');
  const states = new Map(dynamic.zones.map(zone => [zone.id, zone]));
  const source = { ...manifest.snapshot.sources[0], ...dynamic.sources[0] };
  value.snapshot = { ...dynamic, ...manifest.snapshot, sources: [source],
    zones: manifest.snapshot.zones.map(zone => ({ ...zone, ...states.get(zone.id) })) };
  if (!matchesPreviewContext(value, context, session) || source.sessionId !== value.sessionId || source.sourceSessionId !== value.sourceSessionId
    || String(source.sequence) !== String(value.sequence) || !/^\d{1,30}$/.test(String(value.sequence))
    || typeof value.sourceTimeNs !== 'string' || !/^\d{1,24}$/.test(value.sourceTimeNs) || source.lastSourceTimeNs !== value.sourceTimeNs
    || source.timestampBasis !== value.timestampBasis || typeof value.modelRevision !== 'string' || !value.modelRevision || source.modelRevision !== value.modelRevision
    || ![value.image.width, value.image.height].every(n => Number.isInteger(n) && n > 0 && n <= 8192)
    || value.provenance?.kind !== 'native-webrtc-exact-frame' || value.provenance.correlation !== 'source-session-sequence-time-rtp'
    || value.provenance.clockAlignment !== 'source-frame-exact' || value.provenance.browserClockVerified !== false
    || value.transport?.kind !== 'webrtc-rtp' || value.transport.codec !== 'H264' || value.transport.encoder !== 'nvenc-h264'
    || value.transport.clockRate !== 90000 || !Number.isInteger(value.transport.rtpTimestamp) || value.transport.rtpTimestamp < 0 || value.transport.rtpTimestamp >= 2 ** 32
    || value.snapshot.tracks.some(track => track.sourceId !== value.sourceId || track.sessionId !== value.sessionId || !Array.isArray(track.bboxPx)
      || track.bboxPx.length !== 4 || !track.bboxPx.every(Number.isFinite))
    || value.timestampBasis === 'source-native-sei' && (!nativeSeiSourceClock(source)
      || !nativeSeiClockEvidence(value.sourceClockEvidence, value.sourceTimeNs, source.rawSourcePtsNs)
      || value.sourceClockEvidence?.frameCounter !== source.sourceClockEvidence?.frameCounter)) throw new Error('Video and tracking metadata do not identify the same frame.');
  return value;
}

/** Exact RTP lookup within one connection/session; no nearest-frame fallback. */
export class RtpFrameBuffer {
  private frames = new Map<number, { frame: CityVideoFrame; at: number }>();
  constructor(private limit = 64) {}
  clear() { this.frames.clear(); }
  push(frame: CityVideoFrame, at: number) {
    this.expire(at);
    const rtp = frame.transport.rtpTimestamp;
    const previous = this.frames.get(rtp)?.frame;
    if (previous && (previous.sourceSessionId !== frame.sourceSessionId || previous.sequence !== frame.sequence)) {
      this.clear(); throw new Error('Conflicting RTP frame identity.');
    }
    this.frames.set(rtp, { frame, at });
    while (this.frames.size > this.limit) this.frames.delete(this.frames.keys().next().value!);
  }
  get(rtp: number, now: number) { this.expire(now); return this.frames.get(rtp)?.frame ?? null; }
  private expire(now: number) { for (const [key, value] of this.frames) if (now - value.at > PREVIEW_STALE_MS || now < value.at) this.frames.delete(key); }
}
