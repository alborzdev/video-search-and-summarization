// SPDX-License-Identifier: MIT
import type { CityAnalyzedFrame, CityPreviewContext, CityPreviewFrame, CitySite, CitySource } from './types';
import { nativeSeiClockEvidence, nativeSeiSourceClock } from './sourceClock';

export const PREVIEW_JSON_MAX = 512 * 1024;
export const PREVIEW_JPEG_MAX = 2 * 1024 * 1024;
export const PREVIEW_ENVELOPE_MAX = 4 + PREVIEW_JSON_MAX + PREVIEW_JPEG_MAX;
export const PREVIEW_STALE_MS = 2000;

export function calibrationKey(source: CitySource): string {
  const classes = source.classImageToGroundHomographies;
  return JSON.stringify([source.calibrationRevision ?? null, source.imageToGroundHomography ?? null,
    classes ? Object.keys(classes).sort().map(key => [key, classes[key]]) : null, source.validGroundPolygon ?? null]);
}

export function previewContext(site: CitySite, source: CitySource, generation: number): CityPreviewContext {
  const geometryKey = calibrationKey(source);
  return { siteId: site.id, siteRevision: site.revision, mode: site.mode, sourceId: source.id, width: source.width, height: source.height, geometryKey,
    configurationKey: JSON.stringify([generation, site.id, site.revision, site.mode, source.id, source.width, source.height, geometryKey]) };
}

export function matchesPreviewContext(frame: CityAnalyzedFrame, context: CityPreviewContext | undefined, expectedSession: string | undefined): boolean {
  const source = frame.snapshot?.sources?.find(item => item.id === context?.sourceId);
  return Boolean(context && expectedSession && frame.sessionId === expectedSession && frame.sourceId === context.sourceId &&
    frame.snapshot.siteId === context.siteId && frame.snapshot.siteRevision === context.siteRevision && frame.snapshot.mode === context.mode &&
    frame.image.width === context.width && frame.image.height === context.height && source?.width === context.width && source.height === context.height &&
    calibrationKey(source) === context.geometryKey);
}

/** Decode the pair only after validating frame identity against its exact history row. */
export function parsePreviewEnvelope(bytes: Uint8Array, sourceId: string): { frame: CityPreviewFrame; jpeg: Uint8Array } {
  if (bytes.byteLength < 8 || bytes.byteLength > PREVIEW_ENVELOPE_MAX) throw new Error('Invalid analyzed preview size.');
  const length = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(0, false);
  if (!length || length > PREVIEW_JSON_MAX || length + 4 >= bytes.byteLength || bytes.byteLength - length - 4 > PREVIEW_JPEG_MAX) throw new Error('Invalid analyzed preview envelope.');
  const frame = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(4, length + 4))) as CityPreviewFrame;
  const source = frame.snapshot?.sources?.find(item => item.id === sourceId);
  const size = frame.image;
  if (frame.schemaVersion !== 'city.preview.v1' || frame.sourceId !== sourceId || typeof frame.sessionId !== 'string' || !frame.sessionId || typeof frame.sourceSessionId !== 'string' || !frame.sourceSessionId || typeof frame.sourceTimeNs !== 'string' || !/^\d{1,24}$/.test(frame.sourceTimeNs) || !/^\d{1,24}$/.test(String(frame.sequence)) || !source || frame.snapshot.sources.length !== 1 ||
      source.sessionId !== frame.sessionId || source.sourceSessionId !== frame.sourceSessionId || String(source.sequence) !== String(frame.sequence) || source.lastSourceTimeNs !== frame.sourceTimeNs ||
      (source.timestampBasis !== undefined && source.timestampBasis !== frame.timestampBasis) ||
      (frame.timestampBasis === 'source-native-sei' && (!nativeSeiSourceClock(source)
        || typeof frame.modelRevision !== 'string' || !frame.modelRevision || source.modelRevision !== frame.modelRevision
        || !nativeSeiClockEvidence(frame.sourceClockEvidence, frame.sourceTimeNs, source.rawSourcePtsNs)
        || frame.sourceClockEvidence.frameCounter !== source.sourceClockEvidence?.frameCounter)) ||
      frame.provenance?.kind !== 'native-post-inference-exact-frame' || frame.provenance.correlation !== 'source-session-sequence-time' || frame.provenance.clockAlignment !== 'source-frame-exact' || frame.provenance.browserClockVerified !== false ||
      !size || size.mimeType !== 'image/jpeg' || ![size.width, size.height, size.jpegWidth, size.jpegHeight].every(value => Number.isInteger(value) && value > 0 && value <= 8192) ||
      source.width !== size.width || source.height !== size.height || Math.abs(size.width / size.height - size.jpegWidth / size.jpegHeight) > .01 ||
      !['tracks', 'zones', 'events', 'rules', 'metrics'].every(key => Array.isArray(frame.snapshot[key as keyof typeof frame.snapshot])) || frame.snapshot.tracks.some(track => track.sourceId !== sourceId || track.sessionId !== frame.sessionId || !Array.isArray(track.bboxPx) || track.bboxPx.length !== 4 || !track.bboxPx.every(Number.isFinite))) {
    throw new Error('Analyzed preview and observations do not identify the same frame.');
  }
  const jpeg = bytes.subarray(length + 4);
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8 || jpeg[jpeg.length - 2] !== 0xff || jpeg[jpeg.length - 1] !== 0xd9) throw new Error('Analyzed preview image is incomplete.');
  return { frame, jpeg };
}

export async function readPreviewBytes(response: Response, signal: AbortSignal): Promise<Uint8Array> {
  const declared = response.headers.get('Content-Length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > PREVIEW_ENVELOPE_MAX)) throw new Error('Analyzed preview is too large.');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Analyzed preview body is unavailable.');
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      if (signal.aborted) throw new Error('Analyzed preview was cancelled.');
      const item = await reader.read(); if (item.done) break;
      size += item.value.byteLength;
      if (size > PREVIEW_ENVELOPE_MAX) throw new Error('Analyzed preview is too large.');
      chunks.push(item.value);
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}
