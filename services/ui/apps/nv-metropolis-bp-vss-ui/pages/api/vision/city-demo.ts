// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST'); return res.status(405).json({ error: 'Method not supported.' });
  }
  if (req.method === 'POST' && req.headers['sec-fetch-site'] === 'cross-site') {
    return res.status(403).json({ error: 'Open the demo to use its controls.' });
  }
  const body = req.body;
  if (req.method === 'POST' && (!body || typeof body !== 'object' || Array.isArray(body) || !['prepare', 'play', 'start', 'cancel', 'retry'].includes(body.operation) ||
    typeof body.requestId !== 'string' || !/^[A-Za-z0-9-]{16,80}$/.test(body.requestId) ||
    Object.keys(body).some(key => !['operation', 'requestId', 'scenarioId', 'runId'].includes(key)) ||
    (['prepare', 'start'].includes(body.operation) && (typeof body.scenarioId !== 'string' || !/^[a-z][a-z-]{1,79}$/.test(body.scenarioId))) ||
    (body.operation === 'play' && typeof body.runId !== 'string') ||
    (body.runId !== undefined && (typeof body.runId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$/.test(body.runId))) ||
    (!['prepare', 'start'].includes(body.operation) && body.scenarioId !== undefined))) {
    return res.status(422).json({ error: 'Choose a valid scenario operation.' });
  }
  try {
    const base = new URL(process.env.VSS_CITY_CONTROLLER_URL || 'http://127.0.0.1:9190');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error('Invalid controller');
    const response = await fetch(new URL('/api/v1/demo', base), {
      method: req.method, headers: { 'Content-Type': 'application/json' },
      body: req.method === 'POST' ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(6000),
    });
    const payload = await response.json();
    if (!response.ok) return res.status(response.status).json({ error: payload.detail || 'The simulator could not run this operation.' });
    if (payload.schemaVersion !== 'city.tradeshow-control.v1') throw new Error('Invalid simulator response');
    return res.status(200).json(payload);
  } catch {
    return res.status(503).json({ error: 'The simulator controls are not connected.' });
  }
}
