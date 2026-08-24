// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import handler from '../../../pages/api/vision/vst-image';

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
    send(body: unknown) {
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

describe('VST image proxy', () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it('proxies only an image from an allowed VST picture route', async () => {
    global.fetch = jest.fn(async (input) => {
      expect(String(input)).toBe('http://127.0.0.1:7777/vst/api/v1/live/stream/camera-1/picture');
      return {
        arrayBuffer: async () => Uint8Array.from([1, 2, 3]).buffer,
        headers: { get: () => 'image/jpeg' },
        ok: true,
        status: 200,
      } as unknown as Response;
    });
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { path: '/vst/api/v1/live/stream/camera-1/picture' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.headers['Content-Type']).toBe('image/jpeg');
    expect(Buffer.isBuffer(harness.state.body)).toBe(true);
  });

  it('blocks cross-origin and non-picture proxy targets', async () => {
    global.fetch = jest.fn();
    for (const path of [
      'http://attacker.test/v1/live/stream/camera-1/picture',
      '/vst/api/v1/live/streams',
    ]) {
      const harness = responseHarness();
      await handler(
        { method: 'GET', query: { path } } as unknown as NextApiRequest,
        harness.response
      );
      expect(harness.state.statusCode).toBe(400);
    }
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('renders a stable placeholder for a successful non-image upstream response', async () => {
    global.fetch = jest.fn(async () => ({
      headers: { get: () => 'text/html' },
      ok: true,
      status: 200,
    })) as jest.Mock;
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { path: '/vst/api/v1/live/stream/camera-1/picture' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.headers['Content-Type']).toContain('image/svg+xml');
    expect(harness.state.headers['X-Vision-Image-Fallback']).toBe(
      'unexpected-content'
    );
    expect(String(harness.state.body)).toContain(
      'Preview temporarily unavailable'
    );
  });

  it('renders a temporary placeholder when a trusted live preview cannot be reached', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('connection reset');
    }) as jest.Mock;
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { path: '/vst/api/v1/live/stream/camera-1/picture' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.headers['X-Vision-Image-Fallback']).toBe('unavailable');
    expect(String(harness.state.body)).toContain(
      'Preview temporarily unavailable'
    );
  });

  it('falls back to the storage snapshot when VST rejects a replay picture', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        headers: { get: () => 'application/json' },
        ok: false,
        status: 500,
      } as unknown as Response)
      .mockResolvedValueOnce({
        arrayBuffer: async () => Uint8Array.from([4, 5, 6]).buffer,
        headers: { get: () => 'image/jpeg' },
        ok: true,
        status: 200,
      } as unknown as Response);
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: {
          path:
            '/vst/api/v1/replay/stream/camera-1/picture?startTime=2026-08-19T22%3A37%3A14Z',
        },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        pathname: '/vst/api/v1/storage/stream/camera-1/picture',
        searchParams: expect.objectContaining({}),
      }),
      expect.objectContaining({ cache: 'no-store' })
    );
    const fallbackTarget = (global.fetch as jest.Mock).mock.calls[1][0] as URL;
    expect(fallbackTarget.searchParams.get('startTime')).toBe(
      '2026-08-19T22:37:14Z'
    );
    expect(fallbackTarget.searchParams.get('width')).toBe('1280');
    expect(fallbackTarget.searchParams.get('height')).toBe('720');
    expect(harness.state.statusCode).toBe(200);
    expect(Buffer.isBuffer(harness.state.body)).toBe(true);
  });

  it('returns a stable visual placeholder when a valid snapshot is no longer retained', async () => {
    global.fetch = jest.fn(async () => ({
      headers: { get: () => 'application/json' },
      ok: false,
      status: 410,
    })) as jest.Mock;
    const harness = responseHarness();

    await handler(
      {
        method: 'GET',
        query: { path: '/vst/api/v1/storage/stream/camera-1/picture' },
      } as unknown as NextApiRequest,
      harness.response
    );

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.headers['Content-Type']).toContain('image/svg+xml');
    expect(harness.state.headers['X-Vision-Image-Fallback']).toBe('410');
    expect(String(harness.state.body)).toContain('Preview no longer retained');
  });
});
