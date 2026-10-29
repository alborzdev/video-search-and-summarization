// SPDX-License-Identifier: MIT
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import type { NextApiRequest, NextApiResponse } from 'next';
import { publicCityPayload } from '../city/[...path]';

export const config = { api: { bodyParser: false, responseLimit: false, externalResolver: true } };
const MAX_SDP = 128 * 1024;
const MAX_EVENT = 512 * 1024;

/** SDP and read-only metadata use the existing same-origin application boundary.
 * Browser requests cannot publish native frame identities or choose a relay URL.
 */
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const segments = Array.isArray(req.query.path) ? req.query.path : [];
  const [route, source, token] = segments;
  const methods = route === 'metadata' && segments.length === 2 ? ['GET']
    : route === 'whep' && segments.length === 2 ? ['POST']
    : route === 'sessions' && segments.length === 3 && /^[a-f0-9]{32}$/.test(token) ? ['PUT', 'DELETE'] : [];
  if (!methods.length || !/^[A-Za-z0-9._:-]{1,160}$/.test(source) || source === '.' || source === '..') {
    res.status(404).json({ error: 'Unknown camera video operation.' }); return;
  }
  if (!req.method || !methods.includes(req.method)) { res.setHeader('Allow', methods.join(', ')); res.status(405).end(); return; }
  const session = req.query.sessionId;
  if (route !== 'sessions' && (typeof session !== 'string' || !/^[A-Za-z0-9._:-]{1,200}$/.test(session))) {
    res.status(422).json({ error: 'A valid analyzed camera session is required.' }); return;
  }
  let base: URL;
  try {
    base = new URL(process.env.VSS_CITY_ANALYTICS_URL || 'http://127.0.0.1:9184');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error();
  } catch { res.status(503).json({ error: 'The camera analytics service is unavailable.' }); return; }
  let body: Buffer | undefined;
  if (req.method === 'POST') {
    if (req.headers['content-type'] !== 'application/sdp') { res.status(415).end(); return; }
    const parts: Buffer[] = []; let size = 0;
    try {
      for await (const part of req) {
        const bytes = Buffer.isBuffer(part) ? part : Buffer.from(part);
        size += bytes.length;
        if (size > MAX_SDP) { res.status(413).end(); return; }
        parts.push(bytes);
      }
    } catch { if (!res.writableEnded) res.status(400).end(); return; }
    body = Buffer.concat(parts, size);
    if (!body.length || !body.subarray(0, 3).equals(Buffer.from('v=0'))) { res.status(422).end(); return; }
  }
  const root = base.pathname.replace(/\/$/, '');
  const prefix = root.endsWith('/api/v1/city') ? root : root + '/api/v1/city';
  const path = prefix + '/video/' + segments.map(encodeURIComponent).join('/')
    + (route === 'sessions' ? '' : '?sessionId=' + encodeURIComponent(session as string));
  const request = base.protocol === 'https:' ? httpsRequest : httpRequest;
  const upstream = request({ protocol: base.protocol, hostname: base.hostname, port: base.port || undefined,
    path, method: req.method, headers: body ? { 'Content-Type': 'application/sdp', 'Content-Length': String(body.length) } : {} }, response => {
    res.statusCode = response.statusCode || 502;
    for (const header of ['content-type', 'cache-control', 'x-city-video-session']) {
      const value = response.headers[header]; if (value !== undefined) res.setHeader(header, value);
    }
    response.on('error', () => res.destroy());
    if (route === 'metadata' && res.statusCode === 200) {
      res.setHeader('Cache-Control', 'no-cache, no-transform'); res.setHeader('X-Accel-Buffering', 'no'); res.flushHeaders();
      response.setEncoding('utf8'); let pending = '';
      response.on('data', (chunk: string) => {
        pending += chunk;
        if (Buffer.byteLength(pending) > MAX_EVENT) { upstream.destroy(); res.destroy(); return; }
        let boundary: number;
        while ((boundary = pending.indexOf('\n')) >= 0) {
          const line = pending.slice(0, boundary); pending = pending.slice(boundary + 1);
          try { res.write(line.startsWith('data:') ? 'data: ' + JSON.stringify(publicCityPayload(JSON.parse(line.slice(5)))) + '\n' : line + '\n'); }
          catch { upstream.destroy(); res.destroy(); return; }
          // An obsolete frame queue cannot build up behind a slow viewer.
          if (res.writableLength > MAX_EVENT) { upstream.destroy(); res.end(); return; }
        }
      });
      response.on('end', () => res.end());
    } else {
      let size = 0; const parts: Buffer[] = [];
      response.on('data', (part: Buffer) => {
        size += part.length;
        if (size > MAX_SDP) { upstream.destroy(); res.destroy(); return; }
        parts.push(part);
      });
      response.on('end', () => { if (!res.destroyed) res.end(Buffer.concat(parts, size)); });
    }
  });
  upstream.setTimeout(route === 'metadata' ? 0 : 8000, () => upstream.destroy(new Error('Camera video request timed out.')));
  upstream.on('error', () => { if (!res.headersSent) res.status(503).json({ error: 'Camera video is unavailable.' }); else res.destroy(); });
  res.on('close', () => upstream.destroy());
  upstream.end(body);
}
