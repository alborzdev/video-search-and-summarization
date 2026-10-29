// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import type { CityIndexingMatch } from '../../../components/vision-intelligence/smart-city/cityIndexing';

export const config = { api: { bodyParser: { sizeLimit: '16kb' } } };
const ID = /^[A-Za-z0-9._:-]{1,160}$/;
const LIMIT = 512 * 1024;
type Json = Record<string, any>;
class ProxyFailure extends Error { constructor(message: string, readonly code: number) { super(message); } }

async function boundedJson(response: Response): Promise<Json> {
  if (Number(response.headers.get('content-length') || 0) > LIMIT) throw new ProxyFailure('The indexing response is too large.', 502);
  const reader = response.body?.getReader();
  if (!reader) throw new ProxyFailure('The indexing service returned an empty response.', 502);
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const row = await reader.read(); if (row.done) break;
      size += row.value.length;
      if (size > LIMIT) { await reader.cancel(); throw new ProxyFailure('The indexing response is too large.', 502); }
      chunks.push(row.value);
    }
  } finally { reader.releaseLock(); }
  try {
    let value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (typeof value === 'string') value = JSON.parse(value);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid JSON');
    return value;
  } catch { throw new ProxyFailure('The indexing service returned an unreadable response.', 502); }
}

async function agentRequest(base: string, path: string, method: string, body?: Json): Promise<Json> {
  const response = await fetch(`${base}${path}`, {
    method, cache: 'no-store', headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(method === 'GET' ? 30_000 : 100_000),
  });
  const value = await boundedJson(response);
  if (!response.ok) throw new ProxyFailure(
    typeof value.detail === 'string' ? value.detail.slice(0, 300) : 'The capture request could not be completed.',
    response.status >= 400 && response.status < 500 ? response.status : 502,
  );
  return value;
}

function validTime(value: unknown): value is string {
  return typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}
function safeImage(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length > 4000) return;
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : undefined; }
  catch { return; }
}

/** A booth search always executes a server-prepared camera/session interval. */
export async function searchCityCapture(base: string, sourceId: string, body: Json): Promise<Json> {
  const prepared = await agentRequest(base, `/rtsp-streams/${encodeURIComponent(sourceId)}/indexing/search-request`, 'POST', {
    name: body.name, sessionId: body.sessionId, query: body.query.trim(), topK: body.topK ?? 6,
  });
  const scope = prepared.scope; const input = prepared.request; const params = input?.params;
  let aliases: unknown; try { aliases = JSON.parse(params?.exact_sensor_ids || 'null'); } catch { aliases = null; }
  if (prepared.endpoint !== '/api/v1/embed_search' || prepared.sessionId !== body.sessionId || input?.source_type !== 'rtsp' ||
      scope?.sourceId !== sourceId || scope?.sourceName !== body.name ||
      !validTime(params?.timestamp_start) || !validTime(params?.timestamp_end) || Date.parse(params.timestamp_end) <= Date.parse(params.timestamp_start) ||
      params.timestamp_start !== scope.timestampStart || params.timestamp_end !== scope.timestampEnd ||
      !Array.isArray(aliases) || aliases.length !== 2 || aliases[0] !== sourceId || aliases[1] !== body.name ||
      params.query !== body.query.trim() || String(params.top_k) !== String(body.topK ?? 6)) {
    throw new ProxyFailure('The selected capture could not be pinned. Refresh its status and try again.', 502);
  }
  // Reconstruct the allowlisted input; never forward a browser-supplied tool
  // payload, upstream URL, precomputed vector or broad source wildcard.
  const found = await agentRequest(base, '/embed_search', 'POST', { source_type: 'rtsp', params: {
    query: params.query, top_k: params.top_k, exact_sensor_ids: params.exact_sensor_ids,
    timestamp_start: params.timestamp_start, timestamp_end: params.timestamp_end,
  } });
  if (!Array.isArray(found.results)) throw new ProxyFailure('The capture search returned no readable result list.', 502);
  const start = Date.parse(params.timestamp_start); const end = Date.parse(params.timestamp_end);
  const matches = found.results.filter((row: Json) => row && [sourceId, body.name].includes(row.sensor_id) && validTime(row.start_time) && validTime(row.end_time) &&
    Date.parse(row.start_time) >= start && Date.parse(row.start_time) <= end && Date.parse(row.end_time) >= Date.parse(row.start_time));
  const results: CityIndexingMatch[] = matches.slice(0, body.topK ?? 6).map((row: Json) => ({
    sensor_id: sourceId, video_name: typeof row.video_name === 'string' ? row.video_name.slice(0, 256) : body.name,
    description: typeof row.description === 'string' ? row.description.slice(0, 2000) : '', start_time: row.start_time, end_time: row.end_time,
    screenshot_url: safeImage(row.screenshot_url),
    ...(typeof row.similarity_score === 'number' && Number.isFinite(row.similarity_score) ? { similarity_score: row.similarity_score } : {}),
  }));
  return { sessionId: prepared.sessionId, scope: { sourceId, sourceName: body.name, timestampStart: params.timestamp_start,
    timestampEnd: params.timestamp_end, executed: true }, results, excludedResults: found.results.length - matches.length };
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (!['GET', 'POST'].includes(req.method || '')) { res.setHeader('Allow', 'GET, POST'); return res.status(405).json({ error: 'Method not allowed.' }); }
  if (req.method === 'POST' && req.headers.origin) {
    try { if (new URL(req.headers.origin).host !== req.headers.host) return res.status(403).json({ error: 'Use the capture control in this app.' }); }
    catch { return res.status(403).json({ error: 'Invalid request origin.' }); }
  }
  const body = req.body && typeof req.body === 'object' && !Array.isArray(req.body) ? req.body as Json : {};
  const sourceId = req.method === 'GET' ? req.query.sourceId : body.sourceId;
  if (typeof sourceId !== 'string' || !ID.test(sourceId) || sourceId === '.' || sourceId === '..') return res.status(422).json({ error: 'Choose a valid camera.' });
  let base: string;
  try {
    const url = new URL(process.env.VISION_AGENT_INTERNAL_URL || 'http://127.0.0.1:8100/api/v1');
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid URL');
    base = url.href.replace(/\/$/, '');
  } catch { return res.status(503).json({ error: 'The Agent endpoint is not configured correctly.' }); }
  try {
    const path = `/rtsp-streams/${encodeURIComponent(sourceId)}/indexing`;
    if (req.method === 'GET') return res.status(200).json(await agentRequest(base, path, 'GET'));
    if (typeof body.name !== 'string' || !body.name.trim() || body.name.length > 256) return res.status(422).json({ error: 'Choose the registered camera name.' });
    const allowed = body.action === 'policy' ? ['action', 'sourceId', 'name', 'mode'] : body.action === 'start' ? ['action', 'sourceId', 'name', 'durationSeconds'] : body.action === 'cancel' ? ['action', 'sourceId', 'name'] : ['action', 'sourceId', 'name', 'query', 'sessionId', 'topK'];
    if (Object.keys(body).some(key => !allowed.includes(key))) return res.status(422).json({ error: 'The capture request contains unsupported options.' });
    if (body.action === 'policy') {
      if (!['on-demand', 'disabled'].includes(body.mode)) return res.status(422).json({ error: 'Choose short captures or disable indexing.' });
      return res.status(200).json(await agentRequest(base, path, 'PUT', { name: body.name, mode: body.mode }));
    }
    if (body.action === 'start' || body.action === 'cancel') {
      if (body.action === 'start' && body.durationSeconds !== undefined && (!Number.isInteger(body.durationSeconds) || body.durationSeconds < 30 || body.durationSeconds > 600)) return res.status(422).json({ error: 'Choose a capture from 30 to 600 seconds.' });
      return res.status(200).json(await agentRequest(base, path, 'POST', { name: body.name, action: body.action,
        ...(body.action === 'start' ? { durationSeconds: body.durationSeconds ?? 120 } : {}) }));
    }
    if (body.action !== 'search' || typeof body.query !== 'string' || !body.query.trim() || body.query.length > 1000 ||
        typeof body.sessionId !== 'string' || !/^[A-Za-z0-9-]{1,64}$/.test(body.sessionId) ||
        (body.topK !== undefined && (!Number.isInteger(body.topK) || body.topK < 1 || body.topK > 20))) return res.status(422).json({ error: 'Choose a capture and enter a short search.' });
    return res.status(200).json(await searchCityCapture(base, sourceId, body));
  } catch (cause) {
    return res.status(cause instanceof ProxyFailure ? cause.code : 502).json({ error: cause instanceof ProxyFailure ? cause.message : 'Capture indexing is unavailable. Refresh its status and retry.' });
  }
}
