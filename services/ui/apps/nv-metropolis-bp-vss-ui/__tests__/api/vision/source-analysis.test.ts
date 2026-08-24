// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, rm, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

const sourceId = '11111111-1111-4111-8111-111111111111';
const storeDirectory = `/tmp/vss-source-analysis-test-${process.pid}`;

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

function request(
  action: 'configure' | 'pause' | 'resume',
  detectionEnabled?: boolean
): NextApiRequest {
  return {
    body: {
      action,
      ...(typeof detectionEnabled === 'boolean' ? { detectionEnabled } : {}),
      name: 'Camera 1',
      sourceId,
    },
    method: 'POST',
    query: {},
  } as unknown as NextApiRequest;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe('source analysis orchestration', () => {
  let handler: (request: NextApiRequest, response: NextApiResponse) => Promise<unknown>;

  beforeAll(async () => {
    process.env.VISION_HISTORY_DIR = storeDirectory;
    process.env.VISION_AGENT_INTERNAL_URL = 'http://agent.test/api/v1';
    process.env.LVS_BACKEND_URL = 'http://lvs.test';
    process.env.RTVI_VLM_URL = 'http://vlm.test';
    process.env.LVS_VLM_MODEL = 'cosmos-test';
    await mkdir(storeDirectory, { recursive: true });
    await writeFile(
      path.join(storeDirectory, `${sourceId}.json`),
      JSON.stringify({
        events: ['robot movement'],
        knowledgeId: sourceId,
        scenario: 'indoor mobile robotics',
        sourceId,
        sourceKind: 'live',
        sourceName: 'Camera 1',
        startedAt: '2026-08-17T20:00:00.000Z',
        status: 'ready',
      })
    );
    handler = (await import('../../../pages/api/vision/source-analysis')).default;
  });

  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.VISION_HISTORY_DIR;
    delete process.env.VISION_AGENT_INTERNAL_URL;
    delete process.env.LVS_BACKEND_URL;
    delete process.env.RTVI_VLM_URL;
    delete process.env.LVS_VLM_MODEL;
  });

  it('pauses real-time models and Cosmos captions without deleting history', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('http://agent.test/'))
        return jsonResponse({ state: 'paused', steps: { detection: true, embedding: true } });
      if (url === `http://vlm.test/v1/generate_captions/${sourceId}`)
        return jsonResponse({ deleted: true });
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock;
    const harness = responseHarness();

    await handler(request('pause'), harness.response);

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual(expect.objectContaining({ captioning: 'paused', state: 'paused' }));
  });

  it('resumes using the saved scenario and event recipe', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('http://agent.test/'))
        return jsonResponse({ state: 'active', steps: { detection: true, embedding: true } });
      if (url === 'http://lvs.test/v1/generate_captions')
        return jsonResponse({ status: 'accepted' });
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock;
    const harness = responseHarness();

    await handler(request('resume'), harness.response);

    expect(harness.state.statusCode).toBe(200);
    const captionCall = fetchMock.mock.calls.find(
      ([input]) => String(input) === 'http://lvs.test/v1/generate_captions'
    );
    expect(JSON.parse(String(captionCall?.[1]?.body))).toEqual(
      expect.objectContaining({
        chunk_duration: 30,
        events: ['robot movement'],
        id: sourceId,
        max_tokens: 256,
        model: 'cosmos-test',
        num_frames_per_second_or_fixed_frames_chunk: 4,
        scenario: 'indoor mobile robotics',
        use_fps_for_chunking: false,
        vlm_input_height: 512,
        vlm_input_width: 512,
      })
    );
  });

  it('changes detector mode without interrupting Cosmos caption history', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('http://agent.test/')) {
        expect(JSON.parse(String(init?.body))).toEqual({
          action: 'configure',
          detectionEnabled: false,
          name: 'Camera 1',
        });
        return jsonResponse({
          analysisActive: true,
          detectionEnabled: false,
          message: 'General-scene analysis enabled',
          state: 'active',
          steps: { detection: false, embedding: true },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock;
    const harness = responseHarness();

    await handler(request('configure', false), harness.response);

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual(
      expect.objectContaining({
        action: 'configure',
        analysisActive: true,
        detectionEnabled: false,
        state: 'active',
      })
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reprocesses a recording through the selected profile without live-caption orchestration', async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe(`http://agent.test/api/v1/videos/${sourceId}/analysis`);
      expect(JSON.parse(String(init?.body))).toEqual({ analysisProfileId: 'traffic-monitoring' });
      return jsonResponse({
        analysisProfileId: 'traffic-monitoring',
        detectionEnabled: true,
        generatedDataDeleted: 12,
        message: 'Traffic and roadway is reprocessing this recording',
        sensorId: sourceId,
      });
    });
    global.fetch = fetchMock;
    const harness = responseHarness();

    await handler({
      body: {
        action: 'configure',
        analysisProfileId: 'traffic-monitoring',
        name: 'Intersection replay',
        sourceId,
        sourceKind: 'recorded',
      },
      method: 'POST',
      query: {},
    } as unknown as NextApiRequest, harness.response);

    expect(harness.state.statusCode).toBe(200);
    expect(harness.state.body).toEqual(expect.objectContaining({
      analysisProfileId: 'traffic-monitoring',
      generatedDataDeleted: 12,
      state: 'active',
    }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not interrupt a continuous live alert with source lifecycle control', async () => {
    const reservation = path.join(storeDirectory, '.live-alert-rule-focused.json');
    await writeFile(reservation, JSON.stringify({ resumeHistory: true, sourceId }));
    global.fetch = jest.fn();
    const harness = responseHarness();

    await handler(request('pause'), harness.response);

    expect(harness.state.statusCode).toBe(409);
    expect(harness.state.body.error).toContain('live alert rule');
    expect(global.fetch).not.toHaveBeenCalled();
    await unlink(reservation);
  });
});
