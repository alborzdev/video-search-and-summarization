import type { NextApiRequest, NextApiResponse } from 'next';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST'); return res.status(405).json({ error: 'Method not supported.' });
  }
  if (req.method === 'POST') {
    if (req.headers['sec-fetch-site'] === 'cross-site' ||
        req.headers.origin && req.headers.origin !== `http://${req.headers.host}` && req.headers.origin !== `https://${req.headers.host}`) {
      return res.status(403).json({ error: 'Open VSS to control embeddings.' });
    }
    if (!req.body || !['start', 'stop'].includes(req.body.operation) || Object.keys(req.body).some(key => key !== 'operation')) {
      return res.status(422).json({ error: 'Choose start or stop embeddings.' });
    }
  }
  try {
    const base = new URL(process.env.VSS_CITY_CONTROLLER_URL || 'http://127.0.0.1:9190');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error('Invalid controller');
    const response = await fetch(new URL('/api/v1/embedding', base), {
      method: req.method, headers: { 'Content-Type': 'application/json' },
      body: req.method === 'POST' ? JSON.stringify(req.body) : undefined, signal: AbortSignal.timeout(5000),
    });
    const data = await response.json();
    if (!response.ok) return res.status(response.status).json({ error: data.detail || 'Embedding action failed. Check status before retrying.' });
    if (data.schemaVersion !== 'city.embedding-control.v1') throw new Error('Invalid avatar status');
    return res.status(200).json(data);
  } catch {
    return res.status(503).json({ error: 'Embedding controls are not connected. Start Smart City Demo, then retry.' });
  }
}
