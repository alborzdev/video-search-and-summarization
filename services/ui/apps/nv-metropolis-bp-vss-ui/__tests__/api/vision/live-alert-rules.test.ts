// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

const sourceId = '11111111-1111-4111-8111-111111111111';
const storeDirectory = `/tmp/vss-live-alert-test-${process.pid}`;

function responseHarness() {
  const state: { body?: any; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader() {
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
    text: async () => JSON.stringify(body),
  } as Response;
}

function request(method: string, body: Record<string, unknown> = {}, query: Record<string, string> = {}) {
  return { body, method, query } as unknown as NextApiRequest;
}

describe('resource-safe live alert orchestration', () => {
  let handler: (request: NextApiRequest, response: NextApiResponse) => Promise<unknown>;

  beforeAll(async () => {
    process.env.ALERT_BRIDGE_INTERNAL_URL = 'http://bridge.test/api/v1';
    process.env.LVS_BACKEND_URL = 'http://lvs.test';
    process.env.LVS_VLM_MODEL = 'cosmos-test';
    process.env.RTVI_VLM_URL = 'http://vlm.test';
    process.env.VISION_HISTORY_DIR = storeDirectory;
    await mkdir(storeDirectory, { recursive: true });
    await writeFile(
      path.join(storeDirectory, `${sourceId}.json`),
      JSON.stringify({
        events: ['pedestrian crossing', 'traffic safety risk'],
        knowledgeId: sourceId,
        scenario: 'urban traffic intersection',
        sourceId,
        sourceKind: 'live',
        sourceName: 'Traffic camera',
        startedAt: '2026-08-19T20:00:00.000Z',
        status: 'ready',
      })
    );
    handler = (await import('../../../pages/api/vision/live-alert-rules')).default;
  });

  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.ALERT_BRIDGE_INTERNAL_URL;
    delete process.env.LVS_BACKEND_URL;
    delete process.env.LVS_VLM_MODEL;
    delete process.env.RTVI_VLM_URL;
    delete process.env.VISION_HISTORY_DIR;
  });

  afterEach(() => jest.restoreAllMocks());

  it('hands Cosmos from background history to one rule, then restores history on delete', async () => {
    let rules: Array<Record<string, unknown>> = [];
    const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === 'http://bridge.test/api/v1/realtime' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        rules = [{ ...body, id: 'rule-1', status: 'active' }];
        return jsonResponse({ id: 'rule-1', status: 'success' }, 201);
      }
      if (url === 'http://bridge.test/api/v1/realtime') {
        return jsonResponse({ rules });
      }
      if (url === 'http://vlm.test/v1/health/ready') return jsonResponse({ ready: true });
      if (url === 'http://vlm.test/v1/stream/get-stream-info') {
        return jsonResponse({
          stream_list: [{ camera_id: sourceId, inference_active: true }],
        });
      }
      if (url === `http://vlm.test/v1/generate_captions/${sourceId}`) {
        return jsonResponse({ deleted: true });
      }
      if (url === 'http://bridge.test/api/v1/realtime/rule-1' && init?.method === 'DELETE') {
        rules = [];
        return jsonResponse({ id: 'rule-1', status: 'success' });
      }
      if (url === 'http://lvs.test/v1/generate_captions' && init?.method === 'POST') {
        return jsonResponse({ status: 'accepted' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;

    const createHarness = responseHarness();
    await handler(
      request('POST', {
        alert_type: 'traffic-risk',
        live_stream_url: 'rtsp://camera.test/live',
        prompt: 'Alert on unsafe pedestrian crossings.',
        sensor_id: sourceId,
        sensor_name: 'Traffic camera',
      }),
      createHarness.response
    );

    expect(createHarness.state.statusCode).toBe(201);
    const alertPost = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === 'http://bridge.test/api/v1/realtime' && init?.method === 'POST'
    );
    expect(JSON.parse(String(alertPost?.[1]?.body))).toEqual(expect.objectContaining({
      chunk_duration: 30,
      enable_audio: false,
      enable_reasoning: false,
      max_tokens: 128,
      num_frames_per_second_or_fixed_frames_chunk: 4,
      preserve_rtvi_stream: true,
      sensor_id: sourceId,
      use_fps_for_chunking: false,
    }));

    const deleteHarness = responseHarness();
    await handler(request('DELETE', {}, { id: 'rule-1' }), deleteHarness.response);

    expect(deleteHarness.state.statusCode).toBe(200);
    expect(deleteHarness.state.body.historyResumed).toBe(true);
    const resumeCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === 'http://lvs.test/v1/generate_captions' && init?.method === 'POST'
    );
    expect(JSON.parse(String(resumeCall?.[1]?.body))).toEqual(expect.objectContaining({
      chunk_duration: 30,
      events: ['pedestrian crossing', 'traffic safety risk'],
      id: sourceId,
      model: 'cosmos-test',
      scenario: 'urban traffic intersection',
    }));
  });

  it('rejects a second continuous rule before touching Cosmos', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input) === 'http://bridge.test/api/v1/realtime') {
        return jsonResponse({ rules: [{ id: 'existing-rule', sensor_id: sourceId, status: 'active' }] });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    global.fetch = fetchMock as jest.Mock;
    const harness = responseHarness();

    await handler(
      request('POST', {
        alert_type: 'traffic-risk',
        live_stream_url: 'rtsp://camera.test/live',
        prompt: 'Watch this camera.',
        sensor_id: sourceId,
      }),
      harness.response
    );

    expect(harness.state.statusCode).toBe(409);
    expect(harness.state.body.error).toContain('already focused');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('restores background history when Alert Bridge rejects creation', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === 'http://bridge.test/api/v1/realtime' && init?.method === 'POST') {
        return jsonResponse({ message: 'model unavailable' }, 503);
      }
      if (url === 'http://bridge.test/api/v1/realtime') return jsonResponse({ rules: [] });
      if (url === 'http://vlm.test/v1/health/ready') return jsonResponse({ ready: true });
      if (url === 'http://vlm.test/v1/stream/get-stream-info') {
        return jsonResponse({ stream_list: [{ camera_id: sourceId, inference_active: true }] });
      }
      if (url === `http://vlm.test/v1/generate_captions/${sourceId}`) return jsonResponse({});
      if (url === 'http://lvs.test/v1/generate_captions') return jsonResponse({ status: 'accepted' });
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;
    const harness = responseHarness();

    await handler(
      request('POST', {
        alert_type: 'traffic-risk',
        live_stream_url: 'rtsp://camera.test/live',
        prompt: 'Watch this camera.',
        sensor_id: sourceId,
      }),
      harness.response
    );

    expect(harness.state.statusCode).toBe(502);
    expect(harness.state.body.error).toBe('model unavailable');
    expect(fetchMock.mock.calls.some(
      ([input, init]) => String(input) === 'http://lvs.test/v1/generate_captions' && init?.method === 'POST'
    )).toBe(true);
  });

  it('releases every rule for a source before source reset or deletion', async () => {
    let rules = [
      { id: 'source-rule-1', sensor_id: sourceId, status: 'active' },
      { id: 'other-rule', sensor_id: 'other-source', status: 'active' },
    ];
    const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === 'http://bridge.test/api/v1/realtime') return jsonResponse({ rules });
      if (url === 'http://bridge.test/api/v1/realtime/source-rule-1' && init?.method === 'DELETE') {
        rules = rules.filter((rule) => rule.id !== 'source-rule-1');
        return jsonResponse({ status: 'success' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;
    const harness = responseHarness();

    await handler(request('DELETE', {}, { sourceId }), harness.response);

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual({ deleted: 1, sourceId });
    expect(rules).toEqual([expect.objectContaining({ id: 'other-rule' })]);
  });

  it('rejects a new rule before caption handoff when Cosmos is unavailable', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === 'http://bridge.test/api/v1/realtime') return jsonResponse({ rules: [] });
      if (url === 'http://vlm.test/v1/health/ready') return jsonResponse({}, 503);
      if (url === 'http://vlm.test/v1/stream/get-stream-info') return jsonResponse({ stream_list: [] });
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;
    const harness = responseHarness();

    await handler(
      request('POST', {
        alert_type: 'traffic-risk',
        live_stream_url: 'rtsp://camera.test/live',
        prompt: 'Watch this camera.',
        sensor_id: sourceId,
      }),
      harness.response
    );

    expect(harness.state.statusCode).toBe(503);
    expect(harness.state.body).toEqual(expect.objectContaining({
      code: 'VLM_UNAVAILABLE',
      admission: expect.objectContaining({ workload: 'live_vlm_alert' }),
    }));
    expect(fetchMock.mock.calls.some(
      ([input, init]) => String(input) === 'http://bridge.test/api/v1/realtime' && init?.method === 'POST'
    )).toBe(false);
  });
});
