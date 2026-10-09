// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const directory = process.env.VISION_HISTORY_DIR || '/tmp/vss-vision-intelligence-history';
  const filename = path.join(directory, '.primary-source.json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'GET') {
    try {
      const saved = JSON.parse(await readFile(filename, 'utf8'));
      return res.status(200).json({ streamId: saved.streamId || null });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT')
        return res.status(200).json({ streamId: null });
      return res.status(500).json({ error: 'Primary camera configuration could not be read.' });
    }
  }
  if (req.method !== 'PUT') {
    res.setHeader('Allow', 'GET, PUT');
    return res.status(405).json({ error: 'Method not allowed.' });
  }
  const streamId = req.body?.streamId;
  if (typeof streamId !== 'string' || !/^[A-Za-z0-9._:-]{1,160}$/.test(streamId))
    return res.status(400).json({ error: 'Choose a registered live camera.' });
  try {
    const base = (process.env.VST_INTERNAL_API_URL || 'http://127.0.0.1:30888/vst/api').replace(/\/$/, '');
    const response = await fetch(`${base}/v1/sensor/streams`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('Video I/O unavailable');
    const catalog = await response.json();
    const exists = Array.isArray(catalog) && catalog.some(group => Object.values(group).some(streams =>
      Array.isArray(streams) && streams.some(stream => stream.streamId === streamId &&
        (stream.type === 'Rtsp' || /^rtsps?:\/\//i.test(stream.url || '')))));
    if (!exists) return res.status(404).json({ error: 'Registered live camera not found.' });
    await mkdir(directory, { recursive: true });
    const temporary = `${filename}.${randomUUID()}.tmp`;
    await writeFile(temporary, JSON.stringify({ streamId }), { mode: 0o600 });
    await rename(temporary, filename);
    return res.status(200).json({ streamId });
  } catch {
    return res.status(503).json({ error: 'Primary camera could not be saved. Check Video I/O.' });
  }
}
