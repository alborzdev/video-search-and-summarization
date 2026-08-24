// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

const EVIDENCE_CLIP_API_URL = (process.env.EVIDENCE_CLIP_API_URL || 'http://127.0.0.1:8098').replace(/\/$/, '');
const SENSOR_PATTERN = /^[A-Za-z0-9_.:-]{1,160}$/;

function single(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || '' : value || '';
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'DELETE') {
    res.setHeader('Allow', 'DELETE');
    return res.status(405).json({ error: 'Method not allowed.' });
  }

  const sensorId = single(req.query.sensorId);
  if (!SENSOR_PATTERN.test(sensorId)) {
    return res.status(422).json({ error: 'A valid source is required.' });
  }

  try {
    const response = await fetch(`${EVIDENCE_CLIP_API_URL}/purge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sensorId }),
      signal: AbortSignal.timeout(30_000),
    });
    const payload = await response.json() as { removedBytes?: number; removedFiles?: number };
    if (!response.ok) throw new Error(`Evidence cache returned ${response.status}.`);
    return res.status(200).json({
      removedBytes: typeof payload.removedBytes === 'number' ? payload.removedBytes : 0,
      removedFiles: typeof payload.removedFiles === 'number' ? payload.removedFiles : 0,
    });
  } catch {
    return res.status(502).json({ error: 'Generated evidence clips could not be cleared.' });
  }
}
