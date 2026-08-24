// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/evidence-cache';

function responseHarness() {
  const state: { body?: unknown; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader: jest.fn(),
    status(statusCode: number) {
      state.statusCode = statusCode;
      return response;
    },
  } as unknown as NextApiResponse;
  return { response, state };
}

function request(method: string, sensorId = 'camera-1'): NextApiRequest {
  return { method, query: { sensorId } } as unknown as NextApiRequest;
}

describe('evidence cache API', () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it('purges generated evidence for only the requested source', async () => {
    global.fetch = jest.fn(async (_input, init) => {
      expect(init).toEqual(expect.objectContaining({ method: 'POST' }));
      expect(JSON.parse(String(init?.body))).toEqual({ sensorId: 'camera-1' });
      return {
        json: async () => ({ removedBytes: 4096, removedFiles: 3 }),
        ok: true,
        status: 200,
      } as Response;
    });
    const harness = responseHarness();

    await handler(request('DELETE'), harness.response);

    expect(harness.state).toEqual({
      body: { removedBytes: 4096, removedFiles: 3 },
      statusCode: 200,
    });
  });

  it('rejects invalid source identifiers before contacting the cache service', async () => {
    global.fetch = jest.fn();
    const harness = responseHarness();

    await handler(request('DELETE', '../../all'), harness.response);

    expect(harness.state.statusCode).toBe(422);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('turns cache service failures into a stable gateway error', async () => {
    global.fetch = jest.fn(async () => ({
      json: async () => ({ error: 'failed' }),
      ok: false,
      status: 500,
    })) as jest.Mock;
    const harness = responseHarness();

    await handler(request('DELETE'), harness.response);

    expect(harness.state.statusCode).toBe(502);
    expect(harness.state.body).toEqual({ error: 'Generated evidence clips could not be cleared.' });
  });
});
