// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, readFile, rm, unlink, writeFile } from 'node:fs/promises';
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

  it.each([{ streams: [] }, { streams: [{ id: `${sourceId}-other`, chunk_duration: 30 }] }])(
    'pauses saved history after a fresh offline boot when RTVI confirms the source is absent ($streams)',
    async ({ streams }) => {
      const historyPath = path.join(storeDirectory, `${sourceId}.json`);
      const retainedHistory = await readFile(historyPath, 'utf8');
      const actions: string[] = [];
      global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith('http://agent.test/')) {
          actions.push(JSON.parse(String(init?.body)).action);
          return jsonResponse({ state: 'paused', steps: { detection: true, embedding: true } });
        }
        if (url === `http://vlm.test/v1/generate_captions/${sourceId}`) {
          expect(init?.method).toBe('DELETE');
          return jsonResponse({ code: 'BadParameter', message: `No such resource ${sourceId}` }, 400);
        }
        if (url === 'http://vlm.test/v1/streams/get-stream-info') {
          expect(init?.method).toBe('GET');
          return jsonResponse(streams);
        }
        throw new Error(`Unexpected request: ${url}`);
      });
      const harness = responseHarness();

      await handler(request('pause'), harness.response);

      expect(harness.state.statusCode).toBe(200);
      expect(harness.state.body).toEqual(expect.objectContaining({
        analysisActive: false, captioning: 'paused', state: 'paused',
      }));
      expect(actions).toEqual(['pause']);
      expect(await readFile(historyPath, 'utf8')).toBe(retainedHistory);
    }
  );

  it.each([
    { captionStatus: 503, message: 'Caption worker unavailable' },
    { captionStatus: 400, message: 'Invalid caption parameters' },
    { captionStatus: 400, message: `No such resource ${sourceId}-other` },
    { captionStatus: 400, message: `No such resource ${sourceId}`, streams: [{ id: sourceId, chunk_duration: 30 }] },
    { captionStatus: 400, message: `No such resource ${sourceId}`, streams: [{}] },
    { captionStatus: 400, message: `No such resource ${sourceId}`, streams: [], inventoryStatus: 503 },
    { captionStatus: 0, message: 'Caption connection refused' },
  ])('rolls back real or unverified caption pause failures without reporting paused ($message)', async failure => {
    const actions: string[] = [];
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('http://agent.test/')) {
        const action = JSON.parse(String(init?.body)).action;
        actions.push(action);
        return jsonResponse({ state: action === 'resume' ? 'active' : 'paused' });
      }
      if (url === `http://vlm.test/v1/generate_captions/${sourceId}`) {
        if (!failure.captionStatus) throw new Error(failure.message);
        return jsonResponse({ code: 'BadParameter', message: failure.message }, failure.captionStatus);
      }
      if (url === 'http://vlm.test/v1/streams/get-stream-info') {
        if (!('streams' in failure)) throw new Error('Unrelated failure must not be treated as missing');
        return jsonResponse(failure.streams, failure.inventoryStatus || 200);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const harness = responseHarness();

    await handler(request('pause'), harness.response);

    expect(harness.state.statusCode).toBe(502);
    expect(harness.state.body).not.toHaveProperty('state', 'paused');
    expect(harness.state.body).not.toHaveProperty('analysisActive', false);
    expect(harness.state.body.error).toContain(failure.message);
    expect(actions).toEqual(['pause', 'resume']);
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
