// SPDX-License-Identifier: MIT

import { EventEmitter, once } from 'node:events';
import { Readable, PassThrough } from 'node:stream';
import type { NextApiRequest, NextApiResponse } from 'next';

jest.mock('node:http', () => ({ request: jest.fn() }));

import { request as httpRequest } from 'node:http';
import handler from '../../../pages/api/vision/evidence-media';

const evidenceKey = 'a'.repeat(64);

interface ResponseState {
  body?: unknown;
  headers: Record<string, number | string | string[]>;
  statusCode: number;
}

function responseHarness() {
  const stream = new PassThrough();
  const state: ResponseState = { headers: {}, statusCode: 200 };
  const chunks: Buffer[] = [];
  stream.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
  Object.assign(stream, {
    json(body: unknown) {
      state.body = body;
      return stream;
    },
    setHeader(name: string, value: number | string | string[]) {
      state.headers[name] = value;
      return stream;
    },
    status(statusCode: number) {
      state.statusCode = statusCode;
      return stream;
    },
  });
  Object.defineProperty(stream, 'statusCode', {
    configurable: true,
    get: () => state.statusCode,
    set: (value: number) => {
      state.statusCode = value;
    },
  });
  Object.defineProperty(stream, 'headersSent', { configurable: true, value: false });
  return {
    body: () => Buffer.concat(chunks),
    response: stream as unknown as NextApiResponse,
    state,
  };
}

function request(method: string, key = evidenceKey, range?: string): NextApiRequest {
  return {
    headers: range ? { range } : {},
    method,
    query: { key },
  } as unknown as NextApiRequest;
}

function fakeClientRequest(onEnd?: (emitter: EventEmitter) => void) {
  const emitter = new EventEmitter() as EventEmitter & {
    destroy: jest.Mock;
    end: jest.Mock;
    setTimeout: jest.Mock;
  };
  emitter.destroy = jest.fn();
  emitter.setTimeout = jest.fn(() => emitter);
  emitter.end = jest.fn(() => onEnd?.(emitter));
  return emitter;
}

describe('evidence media proxy', () => {
  const requestMock = httpRequest as unknown as jest.Mock;

  beforeEach(() => {
    requestMock.mockReset();
  });

  it('forwards range requests and streams the exact media response', async () => {
    requestMock.mockImplementation((options, callback) => {
      expect(options).toEqual(
        expect.objectContaining({
          headers: { Range: 'bytes=10-19' },
          method: 'GET',
          path: `/media/${evidenceKey}.mp4`,
        })
      );
      const upstream = Readable.from([Buffer.from('clip-bytes')]) as Readable & {
        headers: Record<string, string>;
        statusCode: number;
      };
      upstream.statusCode = 206;
      upstream.headers = {
        'accept-ranges': 'bytes',
        'content-range': 'bytes 10-19/100',
        'content-type': 'video/mp4',
      };
      callback(upstream);
      return fakeClientRequest();
    });
    const harness = responseHarness();
    const finished = once(harness.response as unknown as EventEmitter, 'finish');

    handler(request('GET', evidenceKey, 'bytes=10-19'), harness.response);
    await finished;

    expect(harness.state.statusCode).toBe(206);
    expect(harness.state.headers).toEqual(
      expect.objectContaining({
        'accept-ranges': 'bytes',
        'content-range': 'bytes 10-19/100',
        'content-type': 'video/mp4',
      })
    );
    expect(harness.body().toString()).toBe('clip-bytes');
  });

  it('returns a stable gateway error when the media service cannot be reached', async () => {
    requestMock.mockImplementation(() =>
      fakeClientRequest((emitter) => emitter.emit('error', new Error('offline')))
    );
    const harness = responseHarness();

    handler(request('GET'), harness.response);

    expect(harness.state.statusCode).toBe(502);
    expect(harness.state.body).toEqual({ error: 'Evidence media is unavailable.' });
  });

  it('rejects malformed keys without opening an upstream request', () => {
    const harness = responseHarness();

    handler(request('GET', '../../clip'), harness.response);

    expect(harness.state.statusCode).toBe(422);
    expect(requestMock).not.toHaveBeenCalled();
  });
});
