// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import handler, { attributeDetectorIncident, fetchAnalyticsIncidents } from '../../../pages/api/vision/incidents';

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
      .mockResolvedValueOnce({ ok: true, json: async () => ({ incidents: [] }) })
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
      )
      .mockResolvedValueOnce(rpcResponse('', 200));
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
      .mockResolvedValueOnce(rpcResponse('data: {"method":"notifications/progress"}\n'))
      .mockRejectedValueOnce(new Error('Cleanup network failure'));

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


it('merges detector rule incidents and removes legacy ad-hoc affirmative answers', async () => {
  const detector = { Id: 'detector-1', category: 'Restricted Area Violation', timestamp: '2026-10-01T17:59:48.743Z', info: { roiId: 'ctai-rule-rule-1' } };
  const visual = { Id: 'visual-1', timestamp: '2026-10-01T17:59:49Z', info: { alertRuleId: 'visual-rule-1' } };
  const question = { Id: 'question-1', timestamp: '1970-01-01T00:00:00Z', info: { requestId: 'question-request', prompt: 'Is a forklift visible?' } };
  const recordedRule = { ...question, Id: 'recorded-rule', info: { ...question.info, alertCategory: 'ppe-check' } };
  global.fetch = jest.fn(async (url: RequestInfo | URL) => String(url).includes('/incidents?')
    ? { ok: true, json: async () => ({ incidents: [detector, { Id: 'fov', category: 'FOV Count Violation' }] }) }
    : (global.fetch as jest.Mock).mock.calls.filter(([value]) => !String(value).includes('/incidents?')).length === 1
      ? rpcResponse('', 200, 'session-1')
      : rpcResponse(`data: ${JSON.stringify({ result: { content: [{ text: JSON.stringify({ incidents: [visual, question, recordedRule] }) }] } })}`));
  const harness = responseHarness();
  await handler({ method: 'GET' } as NextApiRequest, harness.response);
  expect(harness.state.statusCode).toBe(200);
  expect(harness.state.body).toEqual({ hasMore: false, incidents: [visual, { ...detector, info: { ...detector.info, alertRuleId: 'rule-1' } }, recordedRule] });
});


it('attributes named RT-CV detector events to their durable source and rule UUID', () => {
  const incident = { Id: 'event-1', sensorId: 'Warehouse camera', info: { roiId: 'ctai-rule-rule-1' } };
  expect(attributeDetectorIncident(incident, [{ id: 'rule-1', engine: 'deepstream', sourceId: 'source-uuid', sourceRuntimeName: 'Warehouse camera' } as any])).toEqual({
    ...incident, sensorId: 'source-uuid', info: { ...incident.info, alertRuleId: 'rule-1', runtimeSensorId: 'Warehouse camera' },
  });
});


it('closes each MCP polling session without losing data when teardown fails', async () => {
  const incidents = [{ Id: 'real-rule-event', timestamp: '2026-10-01T17:59:48Z' }];
  global.fetch = jest.fn()
    .mockResolvedValueOnce(rpcResponse('', 200, 'owned-session'))
    .mockResolvedValueOnce(rpcResponse(`data: ${JSON.stringify({ result: { content: [{ text: JSON.stringify({ incidents }) }] } })}`))
    .mockRejectedValueOnce(new Error('Cleanup network failure'));
  await expect(fetchAnalyticsIncidents()).resolves.toEqual(incidents);
  expect(global.fetch).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({
    method: 'DELETE', headers: { 'mcp-session-id': 'owned-session' }, signal: expect.any(AbortSignal),
  }));
});


it('preserves detector rule events during a visual service outage and reports a partial feed', async () => {
  const detector = { Id: 'area-event', timestamp: '2026-10-01T18:00:00Z', info: { roiId: 'ctai-rule-area-rule' } };
  global.fetch = jest.fn(async url => String(url).includes('/incidents?')
    ? { ok: true, json: async () => ({ incidents: [detector] }) }
    : rpcResponse('', 503));
  const harness = responseHarness();
  await handler({ method: 'GET' } as NextApiRequest, harness.response);
  expect(harness.state.statusCode).toBe(200);
  expect(harness.state.body).toEqual(expect.objectContaining({ partial: true, errors: { visual: expect.stringContaining('initialized') },
    incidents: [expect.objectContaining({ Id: 'area-event' })] }));
});

it('preserves visual events during a detector outage', async () => {
  const visual = { Id: 'visual-event', timestamp: '2026-10-01T18:00:00Z', info: { alertRuleId: 'visual-rule' } };
  global.fetch = jest.fn(async (url, init) => String(url).includes('/incidents?')
    ? rpcResponse('', 503)
    : init?.method === 'DELETE' ? rpcResponse('', 200)
      : JSON.parse(String(init?.body)).method === 'initialize' ? rpcResponse('', 200, 'session')
        : rpcResponse(`data: ${JSON.stringify({ result: { content: [{ text: JSON.stringify({ incidents: [visual] }) }] } })}`));
  const harness = responseHarness();
  await handler({ method: 'GET' } as NextApiRequest, harness.response);
  expect(harness.state.statusCode).toBe(200);
  expect(harness.state.body).toEqual(expect.objectContaining({ partial: true, errors: { detector: expect.stringContaining('503') }, incidents: [visual] }));
});
