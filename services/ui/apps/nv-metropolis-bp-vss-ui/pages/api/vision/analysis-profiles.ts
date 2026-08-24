// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';

const AGENT_URL = (
  process.env.VISION_AGENT_INTERNAL_URL || 'http://127.0.0.1:8100/api/v1'
).replace(/\/$/, '');
const SOURCE_ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;

async function forward(response: Response, res: NextApiResponse) {
  const text = await response.text();
  res.setHeader('Cache-Control', 'no-store');
  res.status(response.status);
  if (!text) return res.end();
  try {
    return res.json(JSON.parse(text));
  } catch {
    return res.json({ error: text });
  }
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET' && req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ error: 'Method not allowed.' });
  }
  const sourceId = typeof req.query.sourceId === 'string' ? req.query.sourceId.trim() : '';
  if (sourceId && !SOURCE_ID_PATTERN.test(sourceId)) {
    return res.status(422).json({ error: 'Choose a valid source.' });
  }
  try {
    const path = sourceId
      ? `/analysis-profiles/sources/${encodeURIComponent(sourceId)}`
      : req.method === 'POST'
        ? '/analysis-profiles/recommend'
        : '/analysis-profiles';
    const response = await fetch(`${AGENT_URL}${path}`, {
      ...(req.method === 'POST'
        ? {
            body: JSON.stringify(req.body),
            headers: { 'Content-Type': 'application/json' },
          }
        : { cache: 'no-store' as const }),
      method: req.method,
      signal: AbortSignal.timeout(15_000),
    });
    return forward(response, res);
  } catch (error) {
    return res.status(502).json({
      error: error instanceof Error ? error.message : 'Analysis profiles are unavailable.',
    });
  }
}
