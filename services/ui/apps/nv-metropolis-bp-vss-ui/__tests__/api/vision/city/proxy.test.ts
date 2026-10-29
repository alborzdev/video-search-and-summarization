// SPDX-License-Identifier: MIT
import { EventEmitter } from 'node:events';
import { request } from 'node:http';
import { TextDecoder } from 'node:util';
import handler, { publicCityPayload } from '../../../../pages/api/vision/city/[...path]';
import { parsePreviewEnvelope } from '../../../../components/vision-intelligence/smart-city/processedPreview';
import nativePreviewMetadata from './fixtures/native-sei-preview-metadata.json';
Object.assign(global, { TextDecoder });
jest.mock('node:http', () => ({ request: jest.fn() }));
jest.mock('node:https', () => ({ request: jest.fn() }));
const mockRequest = request as jest.Mock;
function response() {
  const res: any = new EventEmitter();
  res.status = jest.fn((code: number) => { res.statusCode = code; return res; });
  res.json = jest.fn(); res.write = jest.fn(); res.setHeader = jest.fn(); res.removeHeader = jest.fn(); res.end = jest.fn(); res.destroy = jest.fn(); res.flushHeaders = jest.fn();
  return res;
}
describe('city same-origin gateway', () => {
  beforeEach(() => { delete process.env.VSS_CITY_ANALYTICS_URL; mockRequest.mockReset(); });
  it('removes internal camera credentials and file paths from JSON and SSE payloads', () => {
    expect(publicCityPayload({ sources: [{ id: 'a', name: 'A', inputUri: 'rtsp://user:secret@camera', filename: '/private/video.mp4', width: 1920, clockAligned: true, browserClockVerified: false }], evidence: { filename: '/private/evidence.mp4', clipUrl: '/api/vision/city/media/a' } })).toEqual({ sources: [{ id: 'a', name: 'A', width: 1920, clockAligned: true, browserClockVerified: false }], evidence: { clipUrl: '/api/vision/city/media/a' } });
  });
  it('preserves frame-specific rule explanations without forwarding private nested fields', () => {
    expect(publicCityPayload({ metrics: [{ ruleId: 'crossing', status: 'unknown', evidenceReasons: ['observation-gap', 'speed-unavailable'], credentials: 'private' }] }))
      .toEqual({ metrics: [{ ruleId: 'crossing', status: 'unknown', evidenceReasons: ['observation-gap', 'speed-unavailable'] }] });
  });
  it('preserves class-specific calibration for frame context invalidation', () => {
    const calibration = { person: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] };
    expect(publicCityPayload({ sources: [{ id: 'a', classImageToGroundHomographies: calibration, inputUri: 'private' }] })).toEqual({ sources: [{ id: 'a', classImageToGroundHomographies: calibration }] });
  });
  it('passes only bounded calibrated camera geometry for real map footprints', () => {
    const calibrated = { id: 'a', calibrationRevision: 'cal-1', imageToGroundHomography: [[1,0,0],[0,1,0],[0,0,1]], cameraPositionWorldM: [-33.1,65,8], groundCoverageM: [[-30,60],[-10,60],[-10,90]], T_cv_from_site: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]] };
    expect(publicCityPayload({ sources: [{ ...calibrated, inputUri: 'rtsp://private' }] })).toEqual({ sources: [calibrated] });
    for (const invalid of [{ cameraPositionWorldM: [1,2,Infinity] }, { groundCoverageM: [[0,0],[1,1]] }, { T_cv_from_site: [[1]] }]) {
      const field = Object.keys(invalid)[0];
      expect((publicCityPayload({ sources: [{ ...calibrated, ...invalid }] }) as any).sources[0]).not.toHaveProperty(field);
    }
    const { calibrationRevision, imageToGroundHomography, ...uncalibrated } = calibrated;
    expect((publicCityPayload({ sources: [uncalibrated] }) as any).sources[0]).toEqual({ id: 'a' });
    expect((publicCityPayload({ sources: [{...calibrated,imageToGroundHomography:[[0,0,0],[0,0,0],[0,0,0]]}] }) as any).sources[0]).not.toHaveProperty('cameraPositionWorldM');
  });
  it('preserves reported clock health while removing private source fields', () => {
    const clock = { ingestAgeSeconds: .02, sourceClockAgeSeconds: 100.2, sourceClockProgressRatio: .7, sourceClockPrecision: 'unverified', sourceClockStatus: 'delayed-or-unsynchronized' };
    expect(publicCityPayload({ sources: [{ id: 'a', ...clock, inputUri: 'rtsp://user:secret@camera', filename: '/private/file' }] })).toEqual({ sources: [{ id: 'a', ...clock }] });
  });
  it('keeps exact native clock proof in source JSON while still removing private values', () => {
    // Real direct-gateway metadata, reduced to public frame identity/source and
    // one actual track. This reproduces the live proxy's removed nested proof.
    const source = nativePreviewMetadata.snapshot.sources[0];
    const output = publicCityPayload({ sources: [{ ...source, inputUri: 'rtsp://user:secret@camera', filename: '/private/video.mp4', credentials: 'secret' }] }) as any;
    expect(output.sources[0]).toEqual(source);
    expect(output.sources[0].sourceClockEvidence).toEqual(nativePreviewMetadata.sourceClockEvidence);
    expect(output.sources[0].sourceClockMode).toBe('source-native-sei');
    expect(output.sources[0].browserClockVerified).toBe(false);
  });
  it('round-trips a real native frame through the binary proxy into the browser frame validator', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'application/vnd.connecttech.city-frame' };
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['preview', nativePreviewMetadata.sourceId] }, headers: {} } as any, res);
    const original = JSON.parse(JSON.stringify(nativePreviewMetadata));
    original.snapshot.sources[0].inputUri = 'rtsp://user:secret@camera'; original.snapshot.sources[0].filename = '/private/video.mp4';
    const dto = Buffer.from(JSON.stringify(original)); const prefix = Buffer.alloc(4); prefix.writeUInt32BE(dto.length);
    // Marker fixture tests the metadata/proxy contract, not JPEG pixel fidelity.
    const jpeg = Buffer.from([255, 216, 1, 255, 217]); const input = Buffer.concat([prefix, dto, jpeg]);
    stream.emit('data', input.subarray(0, 17)); stream.emit('data', input.subarray(17)); stream.emit('end');
    const bytes = Buffer.concat([...res.write.mock.calls.map(([chunk]: [Buffer]) => chunk), res.end.mock.calls[0][0]]);
    const parsed = parsePreviewEnvelope(bytes, nativePreviewMetadata.sourceId);
    expect(parsed.frame.snapshot.sources[0].sourceClockEvidence).toEqual(parsed.frame.sourceClockEvidence);
    expect(parsed.frame.sourceClockEvidence!.captureTimeNs).toBe(nativePreviewMetadata.sourceTimeNs);
    expect(parsed.frame.sourceClockEvidence!.auPtsNs).toBe(nativePreviewMetadata.snapshot.sources[0].rawSourcePtsNs);
    expect(parsed.frame.sourceClockEvidence!.frameCounter).toBe(nativePreviewMetadata.sourceClockEvidence.frameCounter);
    expect(parsed.frame.provenance.browserClockVerified).toBe(false);
    expect(Array.from(parsed.jpeg)).toEqual(Array.from(jpeg));
    expect(bytes.toString()).not.toContain('rtsp://'); expect(bytes.toString()).not.toContain('/private');
  });
  it('preserves the same native source proof through an ordinary snapshot response', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'application/json' }; stream.setEncoding = jest.fn();
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['snapshot'] }, headers: {} } as any, res);
    const value = JSON.parse(JSON.stringify(nativePreviewMetadata.snapshot)); value.sources[0].inputUri = 'rtsp://secret';
    stream.emit('data', JSON.stringify(value)); stream.emit('end');
    const output = JSON.parse(res.end.mock.calls[0][0]);
    expect(output.sources[0].sourceClockEvidence).toEqual(nativePreviewMetadata.sourceClockEvidence);
    expect(output.sources[0].sourceClockMode).toBe('source-native-sei');
    expect(output.sources[0].browserClockVerified).toBe(false); expect(output.sources[0].inputUri).toBeUndefined();
  });
  it('preserves safe native delivery counters without forwarding native credentials', () => {
    expect(publicCityPayload({ processedPreview: { nativeDelivery: { sources: [{ sourceId: 'a', observedPublishedFps: 9.8, rateDropped: 12, networkQueueDropped: 2, inputUri: 'private', error: 'private native error' }] } } })).toEqual({ processedPreview: { nativeDelivery: { sources: [{ sourceId: 'a', observedPublishedFps: 9.8, rateDropped: 12, networkQueueDropped: 2 }] } } });
  });
  it('forwards only bounded preview timing summaries, with no raw samples or extra stages', () => {
    const row = { count: 20, mean: 10.5, last: 20, max: 20, p50Upper: 10, p95Upper: 20 };
    expect(publicCityPayload({ sources: [{ sourceId: 'a', timingMs: {
      post: { ...row, rawSamples: [1, 2], inputUri: 'rtsp://private' },
      postQueue: { ...row, mean: Infinity }, other: row,
    } }] })).toEqual({ sources: [{ sourceId: 'a', timingMs: { post: row } }] });
  });
  it('rejects arbitrary paths before creating any upstream request', () => {
    const res = response(); handler({ method: 'GET', query: { path: ['media', '..', 'etc'] }, headers: {} } as any, res);
    expect(res.status).toHaveBeenCalledWith(404); expect(mockRequest).not.toHaveBeenCalled();
  });
  it.each(['__proto__', 'constructor', 'toString'])('rejects inherited object key route %s instead of throwing a server error', route => {
    const res = response(); handler({ method: 'GET', query: { path: [route] }, headers: {} } as any, res); expect(res.status).toHaveBeenCalledWith(404); expect(mockRequest).not.toHaveBeenCalled();
  });
  it('rejects unsupported methods and does not pass arbitrary target URLs', () => {
    const res = response(); handler({ method: 'DELETE', query: { path: ['site'], url: 'http://other/' }, headers: {} } as any, res);
    expect(res.status).toHaveBeenCalledWith(405); expect(mockRequest).not.toHaveBeenCalled();
  });
  it('streams source ranges and preserves upstream errors and content metadata', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 206; stream.headers = { 'content-type': 'video/mp4', 'content-range': 'bytes 0-9/100' }; stream.pipe = jest.fn();
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['media', 'cam1'], url: 'http://other/' }, headers: { range: 'bytes=0-9', cookie: 'private=secret' } } as any, res);
    expect(mockRequest.mock.calls[0][0]).toEqual(expect.objectContaining({ hostname: '127.0.0.1', port: '9184', path: '/api/v1/city/media/cam1', headers: { Range: 'bytes=0-9' } }));
    expect(res.statusCode).toBe(206); expect(res.setHeader).toHaveBeenCalledWith('content-range', 'bytes 0-9/100'); expect(stream.pipe).toHaveBeenCalledWith(res);
    res.emit('close'); expect(upstream.destroy).toHaveBeenCalled();
  });
  it('uses a configured API base once and passes only supported query fields', () => {
    process.env.VSS_CITY_ANALYTICS_URL = 'http://city:9184/api/v1/city';
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn(); mockRequest.mockReturnValue(upstream);
    handler({ method: 'GET', query: { path: ['snapshot'], mediaTimeSeconds: '3.2', sourceId: 'a', url: 'http://other' }, headers: {} } as any, response());
    expect(mockRequest.mock.calls[0][0].path).toBe('/api/v1/city/snapshot?sourceId=a&mediaTimeSeconds=3.2');
  });
  it('multiplexes frame metadata through the existing stream with fixed-origin signaling and bounded viewer output', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'text/event-stream' }; stream.setEncoding = jest.fn();
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); res.writableLength = 0;
    handler({ method: 'GET', query: { path: ['stream'], video: '1', url: 'http://other/' }, headers: {} } as any, res);
    expect(mockRequest.mock.calls[0][0].path).toBe('/api/v1/city/stream?video=1');
    stream.emit('data', 'event: video-frame:a\ndata: {"sourceId":"a","transport":{"rtpTimestamp":4294967295},"inputUri":"rtsp://private"}\n\n');
    const output = res.write.mock.calls.map(([part]: [string]) => part).join('');
    expect(output).toContain('event: video-frame:a'); expect(output).toContain('"rtpTimestamp":4294967295'); expect(output).not.toContain('private');
    res.writableLength = 8 * 1024 * 1024 + 1;
    stream.emit('data', ': heartbeat\n'); expect(upstream.destroy).toHaveBeenCalled(); expect(res.destroy).toHaveBeenCalled();
  });
  function streamingProxy() {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'text/event-stream' };
    stream.setEncoding = jest.fn(); stream.pause = jest.fn(); stream.resume = jest.fn();
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); res.writableLength = 0; res.write.mockReturnValue(true);
    handler({ method: 'GET', query: { path: ['stream'], video: '1' }, headers: {} } as any, res);
    return { stream, upstream, res };
  }
  it('pauses large snapshot writes and resumes remaining metadata in order after drain', () => {
    const { stream, upstream, res } = streamingProxy();
    const text = 'x'.repeat(600 * 1024);
    res.write.mockImplementation((value: string) => {
      if (value.startsWith('data:')) { res.writableLength = Buffer.byteLength(value); return false; }
      return true;
    });
    stream.emit('data', `event: snapshot\ndata: ${JSON.stringify({ text, credentials: 'private' })}\n\nevent: video-frame:a\ndata: {"sequence":2}\n\n`);
    expect(stream.pause).toHaveBeenCalledTimes(1); expect(upstream.destroy).not.toHaveBeenCalled();
    expect(res.write.mock.calls.map(([value]: [string]) => value).join('')).not.toContain('video-frame:a');
    res.writableLength = 0; res.write.mockReturnValue(true); res.emit('drain');
    expect(stream.resume).toHaveBeenCalledTimes(1); expect(upstream.destroy).not.toHaveBeenCalled();
    const output = res.write.mock.calls.map(([value]: [string]) => value).join('');
    expect(output).toContain(`data: ${JSON.stringify({ text })}\n\nevent: video-frame:a\ndata: {"sequence":2}\n\n`);
    expect(output).not.toContain('private'); stream.emit('end'); expect(res.end).toHaveBeenCalledTimes(1);
  });
  it('finishes an upstream EOF only after its buffered metadata drains', () => {
    const { stream, res } = streamingProxy(); res.write.mockReturnValueOnce(false);
    stream.emit('data', 'event: video-frame:a\ndata: {"sequence":1}\n\n'); stream.emit('end');
    expect(res.end).not.toHaveBeenCalled();
    res.emit('drain'); expect(res.end).toHaveBeenCalledTimes(1); expect(stream.resume).not.toHaveBeenCalled();
    expect(res.write.mock.calls.map(([value]: [string]) => value).join('')).toContain('data: {"sequence":1}\n\n');
  });
  it.each(['close', 'error'])('releases pending output and drain deadlines on browser %s', event => {
    jest.useFakeTimers();
    try {
      const { stream, res } = streamingProxy(); res.write.mockReturnValueOnce(false);
      stream.emit('data', 'event: video-frame:a\ndata: {"sequence":1}\n\n');
      res.emit(event); res.emit('drain'); stream.emit('data', 'late\n'); stream.emit('end'); jest.advanceTimersByTime(6000);
      expect(res.write).toHaveBeenCalledTimes(1); expect(res.end).not.toHaveBeenCalled(); expect(res.destroy).not.toHaveBeenCalled();
      expect(stream.resume).not.toHaveBeenCalled(); expect(res.listenerCount('drain')).toBe(0);
    } finally { jest.useRealTimers(); }
  });
  it('disconnects a viewer that never drains without retaining an unlimited queue', () => {
    jest.useFakeTimers();
    try {
      const { stream, res, upstream } = streamingProxy(); res.write.mockReturnValueOnce(false);
      stream.emit('data', 'event: video-frame:a\ndata: {"sequence":1}\n\n');
      jest.advanceTimersByTime(5000); expect(upstream.destroy).toHaveBeenCalledTimes(1); expect(res.destroy).toHaveBeenCalledTimes(1);
      res.emit('drain'); stream.emit('data', 'late\n'); expect(res.write).toHaveBeenCalledTimes(1); expect(stream.resume).not.toHaveBeenCalled();
    } finally { jest.useRealTimers(); }
  });
  it('forwards the mobility window without forwarding arbitrary query targets', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn(); mockRequest.mockReturnValue(upstream);
    handler({ method: 'GET', query: { path: ['mobility'], windowMinutes: '5', url: 'http://other' }, headers: {} } as any, response());
    expect(mockRequest.mock.calls[0][0].path).toBe('/api/v1/city/mobility?windowMinutes=5');
  });
  it('allows only the exact mobility configuration write path and preserves its revision', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn(); mockRequest.mockReturnValue(upstream);
    const body = { expectedRevision: 3, movements: [], crossings: [], queues: [] };
    handler({ method: 'PUT', query: { path: ['mobility', 'config'] }, headers: {}, body } as any, response());
    expect(mockRequest.mock.calls[0][0].path).toBe('/api/v1/city/mobility/config');
    expect(upstream.end).toHaveBeenCalledWith(JSON.stringify(body));
    mockRequest.mockClear();
    const wrongMethod = response(); handler({ method: 'POST', query: { path: ['mobility', 'config'] }, headers: {} } as any, wrongMethod);
    expect(wrongMethod.status).toHaveBeenCalledWith(405);
    const wrongPath = response(); handler({ method: 'PUT', query: { path: ['mobility', 'other'] }, headers: {} } as any, wrongPath);
    expect(wrongPath.status).toHaveBeenCalledWith(404); expect(mockRequest).not.toHaveBeenCalled();
  });
  it('preserves mobility coverage while removing private nested fields', () => {
    expect(publicCityPayload({ coverage: [{ sourceId: 'a', observedSeconds: 45, windowSeconds: 60, credentials: 'private' }], movements: [{ id: 'turn', count: 4 }] }))
      .toEqual({ coverage: [{ sourceId: 'a', observedSeconds: 45, windowSeconds: 60 }], movements: [{ id: 'turn', count: 4 }] });
  });
  it('forwards the bounded-wait query and frame identity without arbitrary query targets', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn(); mockRequest.mockReturnValue(upstream);
    handler({ method: 'GET', query: { path: ['preview', 'cam1'], waitMs: '1000', url: 'http://other/' }, headers: { 'if-none-match': 'frame-1' } } as any, response());
    expect(mockRequest.mock.calls[0][0]).toEqual(expect.objectContaining({ path: '/api/v1/city/preview/cam1?waitMs=1000', headers: { 'If-None-Match': 'frame-1' } }));
  });
  it.each([1, 7])('forwards and sanitizes a bounded binary envelope arriving in %i chunks', count => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'application/vnd.connecttech.city-frame', etag: 'frame-1' };
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['preview', 'cam1'] }, headers: { 'if-none-match': 'old-frame', cookie: 'secret' } } as any, res);
    expect(mockRequest.mock.calls[0][0]).toEqual(expect.objectContaining({ path: '/api/v1/city/preview/cam1', headers: { 'If-None-Match': 'old-frame' } }));
    const dto = Buffer.from(JSON.stringify({ snapshot: { sources: [{ id: 'cam1', sequence: '1', sourceSessionId: 'native', processedPreview: { available: true, status: 'ready' }, inputUri: 'rtsp://secret', filename: '/private/file' }] } }));
    const prefix = Buffer.alloc(4); prefix.writeUInt32BE(dto.length); const jpeg = Buffer.from([255, 216, 255, 217]);
    const input = Buffer.concat([prefix, dto, jpeg]);
    for (let i = 0; i < count; i += 1) stream.emit('data', input.subarray(Math.floor(i * input.length / count), Math.floor((i + 1) * input.length / count)));
    stream.emit('end');
    const result = Buffer.concat([...res.write.mock.calls.map(([chunk]: [Buffer]) => chunk), res.end.mock.calls[0][0]]); const size = result.readUInt32BE(0);
    expect(JSON.parse(result.subarray(4, 4 + size).toString())).toEqual({ snapshot: { sources: [{ id: 'cam1', sequence: '1', sourceSessionId: 'native', processedPreview: { available: true, status: 'ready' } }] } });
    expect(result.subarray(4 + size)).toEqual(jpeg);
    if (count === 1) expect(res.end.mock.calls[0][0].buffer).toBe(input.buffer);
    expect(res.setHeader).toHaveBeenCalledWith('Cache-Control', 'no-store');
  });
  it('does not process or send a preview after its browser disconnected', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'application/vnd.connecttech.city-frame' };
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['preview', 'cam1'] }, headers: {} } as any, res);
    stream.emit('data', Buffer.from([0, 0])); res.emit('close');
    stream.emit('data', Buffer.from('late frame bytes')); stream.emit('end');
    expect(upstream.destroy).toHaveBeenCalled(); expect(res.write).not.toHaveBeenCalled(); expect(res.end).not.toHaveBeenCalled();
  });
  it('rejects an oversized frame before forwarding it', () => {
    const upstream: any = new EventEmitter(); upstream.setTimeout = jest.fn(); upstream.end = jest.fn(); upstream.destroy = jest.fn();
    const stream: any = new EventEmitter(); stream.statusCode = 200; stream.headers = { 'content-type': 'application/vnd.connecttech.city-frame' };
    mockRequest.mockImplementation((_options: unknown, callback: (value: any) => void) => { callback(stream); return upstream; });
    const res = response(); handler({ method: 'GET', query: { path: ['preview', 'cam1'] }, headers: {} } as any, res);
    stream.emit('data', Buffer.alloc(2621445)); expect(upstream.destroy).toHaveBeenCalled(); expect(res.destroy).toHaveBeenCalled();
    stream.emit('data', Buffer.from('late bytes')); stream.emit('end');
    expect(res.write).not.toHaveBeenCalled(); expect(res.end).not.toHaveBeenCalled();
  });
});

it('preserves bounded analytics scopes on snapshots, sources and historical events without private fields', () => {
  const scope = { epoch: 'epoch-123', kind: 'scenario', runId: 'run-456', scenarioId: 'queue-recovery', startedAt: '2026-10-26T15:00:00Z', suppressed: false };
  const privateScope = { ...scope, filesystem: '/private/state', secretToken: 'secret', credentials: 'private' };
  expect(publicCityPayload({ analyticsScope: privateScope, sources: [{ id: 'camera', trackingEpoch: 'tracker-789', analyticsScope: privateScope }], events: [{ id: 'old', analyticsScope: privateScope }, { id: 'legacy' }] }))
    .toEqual({ analyticsScope: scope, sources: [{ id: 'camera', trackingEpoch: 'tracker-789', analyticsScope: scope }], events: [{ id: 'old', analyticsScope: scope }, { id: 'legacy' }] });
  expect(publicCityPayload({ analyticsScope: { kind: 'historical-per-camera', sources: { camera: privateScope, other: null } } }))
    .toEqual({ analyticsScope: { kind: 'historical-per-camera', sources: { camera: scope, other: null } } });
});
