// SPDX-License-Identifier: MIT
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import type { NextApiRequest, NextApiResponse } from 'next';
import { PREVIEW_ENVELOPE_MAX, PREVIEW_JPEG_MAX, PREVIEW_JSON_MAX } from '../../../../components/vision-intelligence/smart-city/processedPreview';

export const config = { api: { bodyParser: { sizeLimit: '1mb' }, responseLimit: false, externalResolver: true } };
const ROUTES: Record<string, readonly string[]> = {
  showcase: ['GET'], 'analytics-scopes': ['GET'], site: ['GET', 'PUT'], snapshot: ['GET'], events: ['GET'], rules: ['GET', 'PUT'],
  observations: ['POST'], stream: ['GET'], health: ['GET'], reports: ['GET'], media: ['GET', 'HEAD'], preview: ['GET'], mobility: ['GET'],
};
const PUBLIC_SOURCE_FIELDS = new Set(['analyticsScope', 'trackingEpoch', 'sourceId', 'observedEncodedFps', 'observedPublishedFps', 'selected', 'encoded', 'published', 'rateDropped', 'sourceQueueOverruns', 'identityMissing', 'identityEvicted', 'identitiesPending', 'geometryMismatch', 'oversizeDropped', 'networkQueueDropped', 'postFailed', 'pendingDropped', 'lastPublishedAtNs', 'timingMs', 'available', 'id', 'name', 'width', 'height', 'mediaUrl', 'vssSensorId', 'sessionId', 'sourceSessionId', 'sequence', 'processedPreview', 'modelRevision', 'currentModelRevision', 'status', 'lastSourceTimeNs', 'mediaTimeSeconds', 'imageToGroundHomography', 'classImageToGroundHomographies', 'validGroundPolygon', 'cameraPositionWorldM', 'groundCoverageM', 'T_cv_from_site', 'calibrationRevision', 'durationSeconds', 'fixtureDurationSeconds', 'timestampBasis', 'clockAligned', 'alignmentSkewSeconds', 'browserClockVerified', 'calibrationStatus', 'mediaTimeBasis', 'rawSourcePtsNs', 'ingestAgeSeconds', 'sourceClockAgeSeconds', 'sourceClockProgressRatio', 'sourceClockPrecision', 'sourceClockStatus', 'sourceClockMode', 'sourceClockEvidence']);
function publicPreviewTiming(value: unknown) {
  const output: Record<string, Record<string, number>> = {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) return output;
  for (const name of ['selectedToJpeg', 'selectedToEncode', 'postQueue', 'post']) {
    const sample = (value as Record<string, unknown>)[name];
    if (!sample || typeof sample !== 'object' || Array.isArray(sample)) continue;
    const row = sample as Record<string, unknown>; const keys = ['mean', 'last', 'max', 'p50Upper', 'p95Upper'];
    if (typeof row.count !== 'number' || !Number.isSafeInteger(row.count) || row.count < 0 ||
        keys.some(key => typeof row[key] !== 'number' || !Number.isFinite(row[key]) || (row[key] as number) < 0 || (row[key] as number) > 1e9)) continue;
    output[name] = Object.fromEntries(['count', ...keys].map(key => [key, row[key] as number]));
  }
  return output;
}
function publicAnalyticsScope(value: unknown, nested = false): unknown {
  if (value === null) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const scope = value as Record<string, unknown>;
  if (scope.kind === 'historical-per-camera' && !nested && scope.sources && typeof scope.sources === 'object' && !Array.isArray(scope.sources)) {
    return { kind: scope.kind, sources: Object.fromEntries(Object.entries(scope.sources).slice(0, 16)
      .filter(([id]) => /^[A-Za-z0-9._:-]{1,160}$/.test(id)).map(([id, item]) => [id, publicAnalyticsScope(item, true) ?? null])) };
  }
  if (!['normal', 'preparing', 'settling', 'scenario', 'recovering', 'recovery'].includes(String(scope.kind))) return undefined;
  const result: Record<string, unknown> = { kind: scope.kind };
  for (const key of ['epoch', 'runId', 'scenarioId']) {
    const item = scope[key];
    if (item === null || typeof item === 'string' && /^[A-Za-z0-9_.:-]{1,256}$/.test(item)) result[key] = item;
  }
  if (typeof scope.startedAt === 'string' && scope.startedAt.length <= 64 && Number.isFinite(Date.parse(scope.startedAt))) result.startedAt = scope.startedAt;
  if (typeof scope.suppressed === 'boolean') result.suppressed = scope.suppressed;
  return result;
}
/** Only finite, bounded static geometry accompanies a valid calibration. */
function publicCameraField(field: string, value: unknown, source: Record<string, unknown>): boolean {
  if (!['cameraPositionWorldM', 'groundCoverageM', 'T_cv_from_site'].includes(field)) return true;
  const vector = (item: unknown, length: number) => Array.isArray(item) && item.length === length && item.every(v => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e7);
  const h = source.imageToGroundHomography;
  if (typeof source.calibrationRevision !== 'string' || !source.calibrationRevision || source.calibrationRevision.length > 256 || !Array.isArray(h) || h.length !== 3 || !h.every(row => vector(row, 3))) return false;
  const determinant = h[0][0] * (h[1][1] * h[2][2] - h[1][2] * h[2][1]) - h[0][1] * (h[1][0] * h[2][2] - h[1][2] * h[2][0]) + h[0][2] * (h[1][0] * h[2][1] - h[1][1] * h[2][0]);
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) return false;
  if (field === 'cameraPositionWorldM') return vector(value, 3);
  if (field === 'T_cv_from_site') return Array.isArray(value) && value.length === 4 && value.every(row => vector(row, 4));
  return Array.isArray(value) && value.length >= 3 && value.length <= 128 && value.every(point => vector(point, 2));
}
/** Internal worker input URIs and local filenames never enter the browser API. */
export function publicCityPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(publicCityPayload);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !['inputUri', 'filename', 'input_uri', 'rtspUrl', 'rtspUri', 'password', 'credentials'].includes(key)).map(([key, item]) => [key,
    key === 'analyticsScope' ? publicAnalyticsScope(item) : key === 'sources' && Array.isArray(item) ? item.map(source => publicCityPayload(Object.fromEntries(Object.entries(source).filter(([field, value]) => PUBLIC_SOURCE_FIELDS.has(field) && publicCameraField(field, value, source))))) : key === 'timingMs' ? publicPreviewTiming(item) : publicCityPayload(item),
  ]));
}
/** Only known city operations reach the configured service; the browser supplies no upstream URL. */
export default function handler(req: NextApiRequest, res: NextApiResponse) {
  const segments = Array.isArray(req.query.path) ? req.query.path : [req.query.path ?? ''];
  const [route, sourceId] = segments;
  const mobilityConfig = route === 'mobility' && segments.length === 2 && sourceId === 'config';
  if (!Object.prototype.hasOwnProperty.call(ROUTES, route) || (!mobilityConfig && segments.length !== (route === 'media' || route === 'preview' ? 2 : 1)) || (sourceId && (!/^[A-Za-z0-9._:-]{1,160}$/.test(sourceId) || sourceId === '.' || sourceId === '..'))) {
    res.status(404).json({ error: 'Unknown city operation.' }); return;
  }
  const methods = mobilityConfig ? ['PUT'] : ROUTES[route];
  if (!req.method || !methods.includes(req.method)) { res.setHeader('Allow', methods.join(', ')); res.status(405).json({ error: 'Method is not supported.' }); return; }
  let base: URL;
  try { base = new URL(process.env.VSS_CITY_ANALYTICS_URL || 'http://127.0.0.1:9184'); }
  catch { res.status(503).json({ error: 'The city service is not configured correctly.' }); return; }
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) { res.status(503).json({ error: 'The city service address is invalid.' }); return; }
  const query = new URLSearchParams();
  const allowed = route === 'stream' ? ['video'] : route === 'snapshot' ? ['sourceId', 'mediaTimeSeconds', 'sourceTimeNs'] : route === 'preview' ? ['waitMs'] : route === 'events' ? ['limit', 'sourceId', 'ruleId', 'state'] : route === 'reports' ? ['format'] : route === 'mobility' && !mobilityConfig ? ['windowMinutes'] : [];
  for (const key of allowed) {
    const value = req.query[key];
    if (typeof value === 'string' && value.length <= 160) query.set(key, value);
  }
  const root = base.pathname.replace(/\/$/, '');
  const prefix = root.endsWith('/api/v1/city') ? root : `${root}/api/v1/city`;
  const queryString = query.toString();
  const path = `${prefix}/${segments.map(encodeURIComponent).join('/')}${queryString ? `?${queryString}` : ''}`;
  const headers: Record<string, string> = {};
  if (req.headers.range && route === 'media') headers.Range = req.headers.range;
  if (typeof req.headers['if-range'] === 'string' && route === 'media') headers['If-Range'] = req.headers['if-range'];
  if (route === 'preview' && typeof req.headers['if-none-match'] === 'string' && req.headers['if-none-match'].length <= 512) headers['If-None-Match'] = req.headers['if-none-match'];
  const body = req.method === 'PUT' || req.method === 'POST' ? JSON.stringify(req.body ?? {}) : undefined;
  if (body && Buffer.byteLength(body) > 1024 * 1024) { res.status(413).json({ error: 'The city request is too large.' }); return; }
  if (body) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = String(Buffer.byteLength(body)); }
  const request = base.protocol === 'https:' ? httpsRequest : httpRequest;
  const upstream = request({ protocol: base.protocol, hostname: base.hostname, port: base.port || undefined, path, method: req.method, headers }, response => {
    res.statusCode = response.statusCode || 502;
    const paired = route === 'preview' && res.statusCode === 200;
    const json = route !== 'media' && route !== 'preview' && !(route === 'reports' && req.query.format === 'csv');
    for (const header of ['content-type', 'content-length', 'content-range', 'content-disposition', 'accept-ranges', 'cache-control', 'etag', 'x-city-preview-status']) {
      if ((json || paired) && header === 'content-length' || json && header === 'etag') continue;
      const value = response.headers[header]; if (value !== undefined) res.setHeader(header, value);
    }
    response.on('error', () => res.destroy());
    if (paired) {
      let size = 0; let finished = false; const chunks: Buffer[] = [];
      const discard = () => { finished = true; chunks.length = 0; };
      // A navigation/abort can leave already queued response callbacks. Release
      // their buffers and never parse or write a frame after the reader closed.
      res.once('close', discard); response.once('error', discard);
      response.on('data', (chunk: Buffer) => {
        if (finished) return;
        size += chunk.length;
        if (size > PREVIEW_ENVELOPE_MAX) { discard(); upstream.destroy(); res.destroy(); return; }
        // IncomingMessage owns each immutable Buffer until this callback takes
        // it; copying every chunk adds a full JPEG allocation at camera rate.
        chunks.push(chunk);
      });
      response.on('end', () => {
        if (finished) return;
        finished = true;
        try {
          const bytes = chunks.length === 1 ? chunks[0] : Buffer.concat(chunks, size);
          chunks.length = 0;
          if (bytes.length < 8 || !String(response.headers['content-type']).startsWith('application/vnd.connecttech.city-frame')) throw new Error('Invalid envelope');
          const length = bytes.readUInt32BE(0); const jpeg = bytes.subarray(4 + length);
          if (!length || length > PREVIEW_JSON_MAX || 4 + length >= bytes.length || jpeg.length > PREVIEW_JPEG_MAX) throw new Error('Invalid envelope');
          const dto = Buffer.from(JSON.stringify(publicCityPayload(JSON.parse(bytes.subarray(4, 4 + length).toString('utf8')))));
          if (dto.length > PREVIEW_JSON_MAX) throw new Error('Invalid envelope');
          const prefix = Buffer.alloc(4); prefix.writeUInt32BE(dto.length);
          res.setHeader('Cache-Control', 'no-store'); res.setHeader('Content-Length', prefix.length + dto.length + jpeg.length);
          // Send the existing JPEG slice directly. Only metadata is rewritten
          // for public-field filtering; the complete image needs no second copy.
          res.write(Buffer.concat([prefix, dto])); res.end(jpeg);
        } catch { chunks.length = 0; res.statusCode = 502; res.removeHeader('content-length'); res.removeHeader('etag'); res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ error: 'The analyzed preview is invalid.' })); }
      }); return;
    }
    if (route === 'stream' && res.statusCode === 200) {
      res.setHeader('Cache-Control', 'no-cache, no-transform'); res.setHeader('X-Accel-Buffering', 'no'); res.flushHeaders();
      response.setEncoding('utf8'); let pending = ''; let stopped = false; let waitingForDrain = false; let ended = false;
      let drainTimeout: ReturnType<typeof setTimeout> | null = null;
      const bufferedBytes = () => Buffer.byteLength(pending) + (res.writableLength || 0);
      const cleanup = () => {
        if (drainTimeout !== null) { clearTimeout(drainTimeout); drainTimeout = null; }
        res.removeListener('drain', drain);
      };
      const stop = () => { stopped = true; pending = ''; cleanup(); };
      const fail = () => { if (stopped) return; stop(); upstream.destroy(); res.destroy(); };
      const pump = () => {
        if (stopped || waitingForDrain) return;
        let index: number;
        while ((index = pending.indexOf('\n')) >= 0) {
          const line = pending.slice(0, index); pending = pending.slice(index + 1);
          let output = `${line}\n`;
          if (line.startsWith('data:')) {
            try { output = `data: ${JSON.stringify(publicCityPayload(JSON.parse(line.slice(5))))}\n`; }
            catch { fail(); return; }
          }
          const writable = res.write(output);
          if (bufferedBytes() > 8 * 1024 * 1024) { fail(); return; }
          // A normal full snapshot can exceed 512 KiB. Honor Node's bounded
          // backpressure instead of disconnecting both camera metadata feeds
          // whenever one socket write needs time to drain.
          if (writable === false) {
            waitingForDrain = true; response.pause(); res.once('drain', drain);
            drainTimeout = setTimeout(fail, 5000);
            return;
          }
        }
        if (ended) { stop(); res.end(); }
      };
      function drain() {
        if (stopped) return;
        cleanup(); waitingForDrain = false; pump();
        if (!stopped && !waitingForDrain && !ended) response.resume();
      }
      response.on('data', (chunk: string) => {
        if (stopped) return;
        pending += chunk;
        if (bufferedBytes() > 8 * 1024 * 1024) { fail(); return; }
        pump();
      });
      res.once('close', stop); res.once('error', stop); response.once('error', stop); response.once('aborted', fail);
      response.on('end', () => { ended = true; pump(); }); return;
    }
    if (json) {
      response.setEncoding('utf8'); let payload = '';
      response.on('data', (chunk: string) => { payload += chunk; if (Buffer.byteLength(payload) > 8 * 1024 * 1024) { upstream.destroy(); res.destroy(); } });
      response.on('end', () => {
        try { res.end(JSON.stringify(publicCityPayload(JSON.parse(payload)))); }
        catch { if (res.statusCode < 400) res.statusCode = 502; res.end(JSON.stringify({ error: 'The city service returned an unreadable response.' })); }
      }); return;
    }
    response.pipe(res);
  });
  upstream.setTimeout(route === 'stream' ? 0 : route === 'preview' ? 2000 : 120_000, () => upstream.destroy(new Error('City service timed out.')));
  upstream.on('error', () => { if (!res.headersSent) res.status(502).json({ error: 'The city analytics service is unavailable. Check its health and retry.' }); else res.destroy(); });
  res.on('close', () => upstream.destroy());
  upstream.end(body);
}
