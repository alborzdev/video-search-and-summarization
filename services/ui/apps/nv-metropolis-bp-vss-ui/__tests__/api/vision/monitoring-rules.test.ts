// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { rm } from 'node:fs/promises';

const storeDirectory = `/tmp/vss-monitoring-rule-test-${process.pid}`;

function responseHarness() {
  const state: { body?: any; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) { state.body = body; return response; },
    setHeader() { return response; },
    status(statusCode: number) { state.statusCode = statusCode; return response; },
  } as unknown as NextApiResponse;
  return { response, state };
}

function request(method: string, body?: unknown, query: Record<string, string> = {}) {
  return { body, method, query } as unknown as NextApiRequest;
}

function jsonTextResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) } as Response;
}

describe('monitoring rules API', () => {
  let handler: (req: NextApiRequest, res: NextApiResponse) => Promise<unknown>;

  beforeAll(async () => {
    process.env.VISION_RULES_DIR = storeDirectory;
    process.env.VIDEO_ANALYTICS_INTERNAL_URL = 'http://analytics.test';
    handler = (await import('../../../pages/api/vision/monitoring-rules')).default;
  });

  beforeEach(() => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('/analysis-profiles/sources/')) {
        return jsonTextResponse({ profile: {
          detectionEnabled: true,
          id: 'warehouse-safety',
          objectTypes: ['Person', 'Forklift', 'Pallet'],
          ruleKinds: ['area-entry', 'proximity'],
        } });
      }
      if (String(input).includes('/config/calibration?')) {
        return jsonTextResponse({ version: '1.0', calibrationType: '', sensors: [] });
      }
      return jsonTextResponse({ status: 'accepted' });
    }) as jest.Mock;
  });

  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.VISION_RULES_DIR;
    delete process.env.VIDEO_ANALYTICS_INTERNAL_URL;
  });

  it('persists a recorded ROI before processing and applies pixel calibration', async () => {
    const create = responseHarness();
    await handler(request('POST', {
      analysisProfileId: 'warehouse-safety',
      backendStatus: 'pending', cooldownSeconds: 30,
      description: 'Create an incident when a person enters the dock.', engine: 'deepstream',
      geometry: { frameHeight: 1080, frameWidth: 1920, kind: 'polygon', points: [{ x: .1, y: .2 }, { x: .5, y: .2 }, { x: .5, y: .8 }] },
      kind: 'area-entry', name: 'Dock entry', notify: false, objectTypes: ['Person'], severity: 'warning',
      sourceId: 'recorded-1', sourceKind: 'recorded', sourceName: 'Dock replay', status: 'active', threshold: { dwellSeconds: 1 },
    }), create.response);

    expect(create.state.statusCode).toBe(201);
    expect(create.state.body.rule).toMatchObject({ name: 'Dock entry', backendStatus: 'active' });
    const calibrationCall = (global.fetch as jest.Mock).mock.calls.find(([url]) => String(url).endsWith('/config/calibration/upsert'));
    const calibration = JSON.parse(String(calibrationCall?.[1]?.body));
    expect(calibration.calibrationType).toBe('image');
    expect(calibration.sensors[0].rois[0]).toMatchObject({ restrictedObjectTypes: ['Person'], roiCoordinates: [{ x: 192, y: 216 }, { x: 960, y: 216 }, { x: 960, y: 864 }] });

    const list = responseHarness();
    await handler(request('GET'), list.response);
    expect(list.state.body.rules).toHaveLength(1);
  });

  it('repairs a legacy blank sensor type before applying a recorded ROI', async () => {
    (global.fetch as jest.Mock).mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes('/analysis-profiles/sources/')) {
        return jsonTextResponse({ profile: {
          detectionEnabled: true,
          id: 'warehouse-safety',
          objectTypes: ['Person', 'Forklift', 'Pallet'],
          ruleKinds: ['area-entry', 'proximity'],
        } });
      }
      if (String(input).includes('/config/calibration?')) {
        return jsonTextResponse({
          calibrationType: '',
          sensors: [{
            attributes: [], coordinates: { x: 0, y: 0 }, geoLocation: { lat: 0, lng: 0 },
            globalCoordinates: [], id: 'legacy-recording', imageCoordinates: [],
            origin: { lat: 0, lng: 0 }, place: [], rois: [], scaleFactor: 0,
            tripwires: [], type: '',
          }],
          version: '1.0',
        });
      }
      return jsonTextResponse({ status: 'accepted' });
    });

    const create = responseHarness();
    await handler(request('POST', {
      analysisProfileId: 'warehouse-safety', cooldownSeconds: 30,
      description: 'Alert when a person enters the selected area.', engine: 'deepstream',
      geometry: { frameHeight: 1080, frameWidth: 1920, kind: 'polygon', points: [{ x: .1, y: .2 }, { x: .5, y: .2 }, { x: .5, y: .8 }] },
      kind: 'area-entry', name: 'Legacy recording area', notify: false,
      objectTypes: ['Person'], severity: 'warning', sourceId: 'legacy-recording',
      sourceKind: 'recorded', sourceName: 'Legacy recording', status: 'active',
      threshold: { dwellSeconds: 1 },
    }), create.response);

    expect(create.state.statusCode).toBe(201);
    const calibrationCall = (global.fetch as jest.Mock).mock.calls.find(
      ([url]) => String(url).endsWith('/config/calibration/upsert'),
    );
    const calibration = JSON.parse(String(calibrationCall?.[1]?.body));
    expect(calibration.calibrationType).toBe('image');
    expect(calibration.sensors[0]).toMatchObject({ id: 'legacy-recording', type: 'camera' });
    expect(calibration.sensors[0].rois).toHaveLength(1);
  });

  it('retains an unapplied rule as a recoverable draft instead of active', async () => {
    (global.fetch as jest.Mock).mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes('/analysis-profiles/sources/')) {
        return jsonTextResponse({ profile: {
          detectionEnabled: true,
          id: 'warehouse-safety',
          objectTypes: ['Person'],
          ruleKinds: ['area-entry'],
        } });
      }
      if (String(input).includes('/config/calibration?')) {
        return jsonTextResponse({ calibrationType: 'image', sensors: [], version: '1.0' });
      }
      if (String(input).endsWith('/config/calibration/upsert')) {
        return jsonTextResponse({ error: 'Calibration rejected.' }, 400);
      }
      return jsonTextResponse({ status: 'accepted' });
    });

    const create = responseHarness();
    await handler(request('POST', {
      analysisProfileId: 'warehouse-safety', cooldownSeconds: 30,
      description: 'Alert when a person enters the selected area.', engine: 'deepstream',
      geometry: { frameHeight: 1080, frameWidth: 1920, kind: 'polygon', points: [{ x: .1, y: .2 }, { x: .5, y: .2 }, { x: .5, y: .8 }] },
      kind: 'area-entry', name: 'Rejected area', notify: false, objectTypes: ['Person'],
      severity: 'warning', sourceId: 'rejected-recording', sourceKind: 'recorded',
      sourceName: 'Rejected recording', status: 'active', threshold: { dwellSeconds: 1 },
    }), create.response);

    expect(create.state.statusCode).toBe(502);
    expect(create.state.body.rule).toMatchObject({
      backendStatus: 'unavailable',
      status: 'draft',
    });
  });

  it('rejects area rules without a usable polygon', async () => {
    const result = responseHarness();
    await handler(request('POST', {
      analysisProfileId: 'warehouse-safety',
      cooldownSeconds: 30, description: '', engine: 'deepstream',
      geometry: { frameHeight: 1080, frameWidth: 1920, kind: 'polygon', points: [] },
      kind: 'area-entry', name: 'Bad area', notify: false, objectTypes: ['Person'], severity: 'warning',
      sourceId: 'recorded-2', sourceKind: 'recorded', sourceName: 'Replay', status: 'active', threshold: {},
    }), result.response);
    expect(result.state.statusCode).toBe(422);
    expect(result.state.body.error).toMatch(/at least three points/i);
  });

  it('removes every rule for a deleted source and clears its managed ROI', async () => {
    const sourceId = 'source-to-delete';
    for (const name of ['Door entry', 'Loading proximity']) {
      const create = responseHarness();
      await handler(request('POST', {
        analysisProfileId: 'warehouse-safety',
        cooldownSeconds: 30, description: 'Temporary source rule.', engine: 'deepstream',
        geometry: name === 'Door entry'
          ? { frameHeight: 1080, frameWidth: 1920, kind: 'polygon', points: [{ x: .1, y: .1 }, { x: .6, y: .1 }, { x: .6, y: .7 }] }
          : { frameHeight: 1080, frameWidth: 1920, kind: 'none', points: [] },
        kind: name === 'Door entry' ? 'area-entry' : 'proximity', name, notify: false,
        objectTypes: name === 'Door entry' ? ['Person'] : ['Person', 'Forklift'], severity: 'warning',
        sourceId, sourceKind: 'recorded', sourceName: 'Temporary source', status: 'active',
        threshold: name === 'Door entry' ? { dwellSeconds: 1 } : { proximityPixels: 140 },
      }), create.response);
      expect(create.state.statusCode).toBe(201);
    }

    (global.fetch as jest.Mock).mockClear();
    const deletion = responseHarness();
    await handler(request('DELETE', undefined, { sourceId }), deletion.response);

    expect(deletion.state.statusCode).toBe(200);
    expect(deletion.state.body).toEqual({ deleted: 2, sourceId });
    expect((global.fetch as jest.Mock).mock.calls.some(([url]) => String(url).endsWith('/config/calibration/upsert'))).toBe(true);
    const list = responseHarness();
    await handler(request('GET', undefined, { sourceId }), list.response);
    expect(list.state.body.rules).toEqual([]);
  });
});
