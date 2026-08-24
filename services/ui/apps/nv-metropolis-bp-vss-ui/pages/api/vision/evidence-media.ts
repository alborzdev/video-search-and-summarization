// SPDX-License-Identifier: MIT
import { request as httpRequest } from 'node:http';
import type { NextApiRequest, NextApiResponse } from 'next';

const EVIDENCE_HOST = '127.0.0.1';
const EVIDENCE_PORT = Number(new URL(process.env.EVIDENCE_CLIP_API_URL || 'http://127.0.0.1:8098').port || 8098);
const KEY_PATTERN = /^[a-f0-9]{64}$/;

export const config = {
  api: {
    responseLimit: false,
  },
};

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    res.status(405).end();
    return;
  }
  const rawKey = Array.isArray(req.query.key) ? req.query.key[0] : req.query.key;
  if (!rawKey || !KEY_PATTERN.test(rawKey)) {
    res.status(422).json({ error: 'A valid evidence key is required.' });
    return;
  }

  const upstream = httpRequest({
    host: EVIDENCE_HOST,
    port: EVIDENCE_PORT,
    method: req.method,
    path: `/media/${rawKey}.mp4`,
    headers: req.headers.range ? { Range: req.headers.range } : undefined,
  }, (upstreamResponse) => {
    res.statusCode = upstreamResponse.statusCode || 502;
    for (const header of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'cache-control']) {
      const value = upstreamResponse.headers[header];
      if (value !== undefined) res.setHeader(header, value);
    }
    upstreamResponse.pipe(res);
  });
  upstream.setTimeout(330_000, () => upstream.destroy(new Error('Evidence media timed out.')));
  upstream.on('error', () => {
    if (!res.headersSent) res.status(502).json({ error: 'Evidence media is unavailable.' });
    else res.destroy();
  });
  res.on('close', () => upstream.destroy());
  upstream.end();
}
