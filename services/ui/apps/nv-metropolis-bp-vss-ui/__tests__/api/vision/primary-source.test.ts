/** @jest-environment node */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import handler from '../../../pages/api/vision/primary-source';
import type { NextApiRequest, NextApiResponse } from 'next';

it('persists only a registered live camera across requests and rejects missing sources', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'vss-primary-'));
  const old = process.env.VISION_HISTORY_DIR;
  process.env.VISION_HISTORY_DIR = directory;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => [{ camera: [{ streamId: 'camera', type: 'Rtsp', url: 'rtsp://private-camera' }] }] })) as jest.Mock;
  const run = async (method: string, streamId?: string) => {
    let status = 0; let result: any;
    const res = { setHeader() {}, status(code: number) { status = code; return this; }, json(body: unknown) { result = body; } };
    await handler({ method, body: { streamId } } as NextApiRequest, res as unknown as NextApiResponse);
    return { status, result };
  };
  try {
    expect(await run('GET')).toEqual({ status: 200, result: { streamId: null } });
    expect((await run('PUT', 'missing')).status).toBe(404);
    expect((await run('PUT', '../camera')).status).toBe(400);
    expect(await run('PUT', 'camera')).toEqual({ status: 200, result: { streamId: 'camera' } });
    expect(await run('GET')).toEqual({ status: 200, result: { streamId: 'camera' } });
  } finally {
    if (old === undefined) delete process.env.VISION_HISTORY_DIR; else process.env.VISION_HISTORY_DIR = old;
    await rm(directory, { recursive: true, force: true });
  }
});
