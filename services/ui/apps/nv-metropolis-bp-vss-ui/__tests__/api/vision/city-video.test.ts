// SPDX-License-Identifier: MIT
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { request } from 'node:http';
import handler from '../../../pages/api/vision/city-video/[...path]';
jest.mock('node:http', () => ({ request: jest.fn() }));
jest.mock('node:https', () => ({ request: jest.fn() }));
const mockRequest = request as jest.Mock;
function response() {
  const value: any = new EventEmitter();
  value.status = jest.fn((status: number) => { value.statusCode = status; return value; });
  for (const key of ['json', 'end', 'write', 'setHeader', 'destroy', 'flushHeaders']) value[key] = jest.fn();
  return value;
}
function incoming(path: string[], method = 'GET', body?: Buffer) {
  return Object.assign(Readable.from(body ? [body] : []), { method, query: { path, sessionId: 'epoch', url: 'http://untrusted.invalid' },
    headers: { 'content-type': 'application/sdp', cookie: 'private-cookie' } });
}
function upstream(status = 201, type = 'application/sdp') {
  const request: any = new EventEmitter(); request.setTimeout = jest.fn(); request.destroy = jest.fn(); request.end = jest.fn();
  const stream: any = new EventEmitter(); stream.statusCode = status; stream.headers = { 'content-type': type, 'x-city-video-session': 'a'.repeat(32) }; stream.setEncoding = jest.fn();
  mockRequest.mockImplementation((_options: any, callback: Function) => { callback(stream); return request; });
  return { request, stream };
}
beforeEach(() => { delete process.env.VSS_CITY_ANALYTICS_URL; mockRequest.mockReset(); });
it('proxies a bounded SDP offer to the fixed backend and returns only the viewer token', async () => {
  const remote = upstream(); const res = response();
  await handler(incoming(['whep', 'a'], 'POST', Buffer.from('v=0\r\n')) as any, res);
  expect(mockRequest.mock.calls[0][0]).toMatchObject({ hostname: '127.0.0.1', path: '/api/v1/city/video/whep/a?sessionId=epoch', headers: { 'Content-Type': 'application/sdp', 'Content-Length': '5' } });
  expect(mockRequest.mock.calls[0][0].headers.cookie).toBeUndefined();
  remote.stream.emit('data', Buffer.from('v=0\r\n')); remote.stream.emit('end');
  expect(res.statusCode).toBe(201); expect(res.end).toHaveBeenCalledWith(Buffer.from('v=0\r\n'));
  res.emit('close'); expect(remote.request.destroy).toHaveBeenCalled();
});
it('streams sanitized exact metadata and closes a slow viewer instead of accumulating frames', async () => {
  const remote = upstream(200, 'text/event-stream'); const res = response();
  await handler(incoming(['metadata', 'a']) as any, res);
  remote.stream.emit('data', 'event: manifest\ndata: {"snapshot":{"sources":[{"id":"a","width":1280,"inputUri":"private"}]}}\n\n');
  expect(res.write.mock.calls.map((row: any[]) => row[0]).join('')).toContain('"width":1280');
  expect(res.write.mock.calls.map((row: any[]) => row[0]).join('')).not.toContain('private');
  res.writableLength = 600000; remote.stream.emit('data', ': ping\n');
  expect(remote.request.destroy).toHaveBeenCalled(); expect(res.end).toHaveBeenCalled();
});
it('never exposes native frame publication or accepts arbitrary upstream routes', async () => {
  const res = response(); await handler(incoming(['frame'], 'POST', Buffer.from('v=0')) as any, res);
  expect(res.status).toHaveBeenCalledWith(404); expect(mockRequest).not.toHaveBeenCalled();
  const large = response(); await handler(incoming(['whep', 'a'], 'POST', Buffer.alloc(128 * 1024 + 1)) as any, large);
  expect(large.status).toHaveBeenCalledWith(413); expect(mockRequest).not.toHaveBeenCalled();
});
