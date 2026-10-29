// SPDX-License-Identifier: MIT
import { TextDecoder } from 'node:util';
import { matchesPreviewContext, parsePreviewEnvelope, previewContext, PREVIEW_ENVELOPE_MAX, readPreviewBytes } from '../processedPreview';
import type { CityPreviewFrame } from '../types';
Object.assign(global, { TextDecoder });
const frame = (): CityPreviewFrame => ({ schemaVersion: 'city.preview.v1', sourceId: 'a', sourceSessionId: 'native', sessionId: 'epoch', sequence: '7', sourceTimeNs: '1700000000000000000', timestampBasis: 'source-rtcp', modelRevision: 'model', image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500, mimeType: 'image/jpeg' }, provenance: { kind: 'native-post-inference-exact-frame', correlation: 'source-session-sequence-time', clockAlignment: 'source-frame-exact', browserClockVerified: false }, snapshot: { siteId: 'city', mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: 7, sources: [{ id: 'a', name: 'A', width: 1000, height: 1000, sessionId: 'epoch', sourceSessionId: 'native', sequence: '7', lastSourceTimeNs: '1700000000000000000' }], tracks: [], zones: [], rules: [], events: [], metrics: [] } });
function envelope(dto = frame()) { const json = Buffer.from(JSON.stringify(dto)); const prefix = Buffer.alloc(4); prefix.writeUInt32BE(json.length); return Buffer.concat([prefix, json, Buffer.from([255, 216, 1, 255, 217])]); }
function nativeFrame(): CityPreviewFrame {
  const dto = frame(); const source = dto.snapshot.sources[0];
  dto.timestampBasis = 'source-native-sei'; source.timestampBasis = 'source-native-sei'; source.sourceClockMode = 'source-native-sei';
  source.browserClockVerified = false;
  source.modelRevision = dto.modelRevision; source.rawSourcePtsNs = '123400000';
  dto.sourceClockEvidence = { schemaVersion: 'city.source-native-sei.v1', method: 'isaac-native-sei-wall-capture', correlation: 'exact-au-pts', captureTimeNs: dto.sourceTimeNs, auPtsNs: source.rawSourcePtsNs, frameCounter: '42' };
  source.sourceClockEvidence = { ...dto.sourceClockEvidence };
  return dto;
}
describe('exact analyzed frame envelope', () => {
  it('retains unverified physical clocks while matching exact source, session, sequence and time', () => {
    const parsed = parsePreviewEnvelope(envelope(), 'a');
    expect(parsed.frame.provenance.browserClockVerified).toBe(false); expect(Array.from(parsed.jpeg)).toEqual([255, 216, 1, 255, 217]);
  });
  it('retains the exact native AU proof with an unverified browser clock', () => {
    const parsed = parsePreviewEnvelope(envelope(nativeFrame()), 'a');
    expect(parsed.frame.timestampBasis).toBe('source-native-sei');
    expect(parsed.frame.sourceClockEvidence!.frameCounter).toBe('42');
    expect(parsed.frame.provenance.browserClockVerified).toBe(false);
  });
  it.each(['mode', 'model', 'empty model', 'basis', 'capture', 'pts', 'counter', 'missing'])('refuses native envelope mismatched %s', field => {
    const dto = nativeFrame(); const source = dto.snapshot.sources[0];
    if (field === 'mode') source.sourceClockMode = 'source-rtcp';
    if (field === 'model') source.modelRevision = 'newer-model';
    if (field === 'empty model') { source.modelRevision = ''; dto.modelRevision = ''; }
    if (field === 'basis') source.timestampBasis = 'source-rtcp';
    if (field === 'capture') dto.sourceClockEvidence!.captureTimeNs = '1';
    if (field === 'pts') dto.sourceClockEvidence!.auPtsNs = '1';
    if (field === 'counter') dto.sourceClockEvidence!.frameCounter = '43';
    if (field === 'missing') delete dto.sourceClockEvidence;
    expect(() => parsePreviewEnvelope(envelope(dto), 'a')).toThrow();
  });
  it.each(['sessionId', 'sourceSessionId', 'sequence', 'lastSourceTimeNs'])('rejects mismatched source %s rather than nearest-frame overlays', field => {
    const dto = frame(); (dto.snapshot.sources[0] as any)[field] = 'different';
    expect(() => parsePreviewEnvelope(envelope(dto), 'a')).toThrow(/same frame/);
  });
  it('rejects other-source tracks, mismatched image geometry and incomplete JPEGs', () => {
    const dto = frame(); dto.image.jpegWidth = 300;
    expect(() => parsePreviewEnvelope(envelope(dto), 'a')).toThrow();
    const other = frame(); other.snapshot.tracks = [{ sourceId: 'b' } as any]; expect(() => parsePreviewEnvelope(envelope(other), 'a')).toThrow();
    const bytes = envelope(); bytes[bytes.length - 1] = 0; expect(() => parsePreviewEnvelope(bytes, 'a')).toThrow(/incomplete/);
    expect(() => parsePreviewEnvelope(envelope(), 'other-source')).toThrow(/same frame/);
  });
  it('bounds a streamed response even without Content-Length', async () => {
    const cancel = jest.fn().mockResolvedValue(undefined); const releaseLock = jest.fn();
    const reader = { read: jest.fn().mockResolvedValueOnce({ done: false, value: new Uint8Array(PREVIEW_ENVELOPE_MAX) }).mockResolvedValueOnce({ done: false, value: new Uint8Array(1) }), cancel, releaseLock };
    await expect(readPreviewBytes({ headers: { get: () => null }, body: { getReader: () => reader } } as any, new AbortController().signal)).rejects.toThrow(/too large/);
    expect(cancel).toHaveBeenCalled(); expect(releaseLock).toHaveBeenCalled();
  });
  it('requires the current site revision, original geometry, calibration and a known session', () => {
    const dto = frame(); dto.snapshot.siteRevision = 1;
    const site: any = { id: 'city', revision: 1, mode: 'live' }; const source = dto.snapshot.sources[0];
    const current = previewContext(site, source, 1);
    expect(matchesPreviewContext(dto, current, 'epoch')).toBe(true);
    expect(matchesPreviewContext(dto, current, undefined)).toBe(false);
    expect(matchesPreviewContext(dto, previewContext({ ...site, id: 'other' }, source, 1), 'epoch')).toBe(false);
    expect(matchesPreviewContext(dto, previewContext({ ...site, revision: 2 }, source, 2), 'epoch')).toBe(false);
    expect(matchesPreviewContext(dto, previewContext(site, { ...source, width: 999 }, 2), 'epoch')).toBe(false);
    expect(matchesPreviewContext(dto, previewContext(site, { ...source, calibrationRevision: 'changed' }, 2), 'epoch')).toBe(false);
    expect(matchesPreviewContext(dto, previewContext(site, { ...source, classImageToGroundHomographies: { person: [[1,0,0],[0,1,0],[0,0,1]] } }, 2), 'epoch')).toBe(false);
  });
});
