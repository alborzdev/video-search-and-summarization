// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import handler, { fetchAnalyticsIncidents } from '../../../pages/api/vision/incidents';

function responseHarness() {
  const state: { body?: unknown; headers: Record<string, string>; statusCode: number } = {
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

function rpcResponse(body: string, status = 200, sessionId: string | null = null): Response {
  return {
    headers: { get: () => sessionId } as Headers,
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  } as Response;
}

describe('incidents API', () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it('ignores progress events and returns the terminal MCP incident result', async () => {
    const incidents = [{ id: 'incident-1', sensorId: 'camera-1' }];
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(rpcResponse('', 200, 'session-1'))
      .mockResolvedValueOnce(
        rpcResponse(
          [
            'data: {"jsonrpc":"2.0","method":"notifications/progress"}',
            `data: ${JSON.stringify({
              jsonrpc: '2.0',
              result: { content: [{ type: 'text', text: JSON.stringify({ incidents }) }] },
            })}`,
          ].join('\n')
        )
      );
    const harness = responseHarness();

    await handler({ method: 'GET' } as NextApiRequest, harness.response);

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual({ hasMore: false, incidents });
    expect(harness.state.headers['Cache-Control']).toContain('max-age=5');
  });

  it('reports an invalid terminal event stream instead of silently returning no incidents', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(rpcResponse('', 200, 'session-1'))
      .mockResolvedValueOnce(rpcResponse('data: {"method":"notifications/progress"}\n'));

    await expect(fetchAnalyticsIncidents()).rejects.toThrow('invalid event stream');
  });

  it('returns a stable unavailable response when MCP initialization fails', async () => {
    global.fetch = jest.fn(async () => rpcResponse('', 503, null));
    const harness = responseHarness();

    await handler({ method: 'GET' } as NextApiRequest, harness.response);

    expect(harness.state.statusCode).toBe(503);
    expect(harness.state.body).toEqual(expect.objectContaining({ incidents: [] }));
  });
});
