// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/source-intelligence';

function responseHarness() {
  const state: { body?: any; headers: Record<string, string>; statusCode: number } = {
    headers: {},
    statusCode: 200,
  };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader(name: string, value: string) {
      state.headers[name] = value;
      return response;
    },
    status(statusCode: number) {
      state.statusCode = statusCode;
      return response;
    },
  } as unknown as NextApiResponse;
  return { response, state };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
  } as Response;
}

describe('source intelligence API', () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it('aggregates semantic, detector, incident, and caption health for one source', async () => {
    const recent = new Date(Date.now() - 5_000).toISOString();
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.includes('/default_camera_1/_search')) {
        return jsonResponse({
          hits: { hits: [{ _source: { '@timestamp': recent } }], total: { value: 4 } },
        });
      }
      if (url.includes('/mdx-embed-filtered-*/_search')) {
        return jsonResponse({ hits: { hits: [{ _source: { timestamp: recent } }] } });
      }
      if (url.includes('/mdx-embed-filtered-*/_count')) return jsonResponse({ count: 12 });
      if (url.includes('/mdx-raw-*/_count')) return jsonResponse({ count: 2 });
      if (url.includes('/mdx-incidents-*/_count')) return jsonResponse({ count: 1 });
      throw new Error(`Unexpected request: ${url}`);
    }) as jest.Mock;
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { name: 'Main Camera', sensorId: 'camera-1' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual(
      expect.objectContaining({
        captionSegments: 4,
        evidenceEvents: 1,
        semanticFresh: true,
        semanticSegments: 12,
        source: { name: 'Main Camera', sensorId: 'camera-1' },
        trackedObservations: 2,
      })
    );
  });

  it('returns unavailable rather than inventing zero counts when every backend query fails', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('offline');
    });
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { name: 'Main Camera', sensorId: 'camera-1' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(503);
    expect(harness.state.body).toEqual({ error: 'Source intelligence data is unavailable.' });
  });

  it('rejects malformed source input without querying Elasticsearch', async () => {
    global.fetch = jest.fn();
    const harness = responseHarness();

    await handler(
      { method: 'GET', query: { name: 'Camera', sensorId: '../all' } } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(400);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
