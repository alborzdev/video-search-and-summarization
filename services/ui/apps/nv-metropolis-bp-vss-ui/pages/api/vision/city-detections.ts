// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST'); return res.status(405).json({ error: 'Method not supported.' });
  }
  if (req.method === 'POST' && req.headers['sec-fetch-site'] === 'cross-site') {
    return res.status(403).json({ error: 'Open Smart City to use detection controls.' });
  }
  if (req.method === 'POST' && (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)
    || !['start', 'stop', 'restart'].includes(req.body.action) || Object.keys(req.body).some(key => key !== 'action'))) {
    return res.status(422).json({ error: 'Choose start, stop or restart detections.' });
  }
  try {
    const base = new URL(process.env.VSS_CITY_CONTROLLER_URL || 'http://127.0.0.1:9190');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error('Invalid controller');
    const response = await fetch(new URL('/api/v1/detections', base), {
      method: req.method, headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
      body: req.method === 'POST' ? JSON.stringify({ action: req.body.action }) : undefined,
      signal: AbortSignal.timeout(req.method === 'POST' ? 45000 : 6000),
    });
    const payload = await response.json();
    if (!response.ok) return res.status(response.status).json({ error: typeof payload.detail === 'string' ? payload.detail : 'Detection control did not complete.' });
    if (payload.schemaVersion !== 'city.detections.v1' || !['running', 'paused', 'stopped'].includes(payload.state)
      || typeof payload.ready !== 'boolean' || !Array.isArray(payload.sources) || payload.sources.length > 2
      || payload.sources.some((source: any) => !source || !/^[A-Za-z0-9._:-]{1,160}$/.test(source.id) || typeof source.name !== 'string' || source.name.length > 256)) throw new Error('Invalid status');
    return res.status(200).json({ schemaVersion: payload.schemaVersion, state: payload.state, ready: payload.ready,
      detail: typeof payload.detail === 'string' ? payload.detail.slice(0, 256) : '',
      sources: payload.sources.map((source: { id: string; name: string }) => ({ id: source.id, name: source.name })),
      lastExitCode: Number.isInteger(payload.lastExitCode) ? payload.lastExitCode : null });
  } catch {
    return res.status(503).json({ error: 'Detection controls are unavailable. Check System, then retry.' });
  }
}
