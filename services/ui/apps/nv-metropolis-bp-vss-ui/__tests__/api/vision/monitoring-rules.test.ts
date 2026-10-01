// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from 'next';
import { rm } from 'node:fs/promises';
import liveAlertHandler from '../../../pages/api/vision/live-alert-rules';

jest.mock('../../../pages/api/vision/live-alert-rules', () => ({
  __esModule: true,
  default: jest.fn(async (req, res) => res.status(200).json(req.method === 'POST' ? { id: 'resumed-backend' } : {})),
}));

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
      if (String(input).includes('/realtime/')) return jsonTextResponse({ rule: { status: 'active' } });
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
      sourceId: 'recorded-1', sourceKind: 'recorded', sourceName: 'Dock replay', sourceRuntimeName: 'Dock runtime', status: 'active', threshold: { dwellSeconds: 1 },
    }), create.response);

    expect(create.state.statusCode).toBe(201);
    expect(create.state.body.rule).toMatchObject({ name: 'Dock entry', backendStatus: 'active' });
    const calibrationCall = (global.fetch as jest.Mock).mock.calls.find(([url]) => String(url).endsWith('/config/calibration/upsert'));
    const calibration = JSON.parse(String(calibrationCall?.[1]?.body));
    expect(calibration.calibrationType).toBe('image');
    expect(calibration.sensors[0].rois[0]).toMatchObject({ restrictedObjectTypes: ['Person'], roiCoordinates: [{ x: 192, y: 216 }, { x: 960, y: 216 }, { x: 960, y: 864 }] });

    expect(calibration.sensors.map((sensor: any) => sensor.id)).toEqual(['recorded-1', 'Dock runtime']);
    expect(calibration.sensors[1].rois).toEqual(calibration.sensors[0].rois);
    const configCall = (global.fetch as jest.Mock).mock.calls.find(([url]) => String(url).endsWith('/config/update/behavior-analytics'));
    expect(JSON.parse(String(configCall?.[1]?.body)).sensors.map((sensor: any) => sensor.id)).toEqual(['recorded-1', 'Dock runtime']);
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

  it('keeps paused visual rules saved and rejects resuming a second active visual rule', async () => {
    const visualDraft = {
      analysisProfileId: 'warehouse-safety', cooldownSeconds: 30, description: '', engine: 'vlm',
      geometry: { kind: 'none', points: [] }, kind: 'semantic', notify: false, objectTypes: [],
      prompt: 'A medical cart is visible.', severity: 'info', sourceId: 'visual-source',
      sourceKind: 'live', sourceName: 'Corridor', threshold: {},
    };
    const active = responseHarness();
    await handler(request('POST', { ...visualDraft, name: 'Active visual rule', status: 'active', backendRuleId: 'active-backend' }), active.response);
    expect(active.state.statusCode).toBe(201);
    const paused = responseHarness();
    await handler(request('POST', { ...visualDraft, name: 'Paused visual rule', status: 'paused' }), paused.response);
    expect(paused.state.statusCode).toBe(201);
    const resume = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: paused.state.body.rule.id }), resume.response);
    expect(resume.state.statusCode).toBe(409);
    const list = responseHarness();
    await handler(request('GET'), list.response);
    expect(list.state.body.rules.find((rule: any) => rule.id === paused.state.body.rule.id).status).toBe('paused');
    const liveCreates = (liveAlertHandler as jest.Mock).mock.calls.filter(([req]) => req.method === 'POST').length;
    const selfResume = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: active.state.body.rule.id }), selfResume.response);
    expect(selfResume.state.statusCode).toBe(200);
    expect((liveAlertHandler as jest.Mock).mock.calls.filter(([req]) => req.method === 'POST')).toHaveLength(liveCreates);
  });

  it('stops a visual job before persisting pause and retains prior backend identity on resume', async () => {
    const list = responseHarness();
    await handler(request('GET'), list.response);
    const activeRule = list.state.body.rules.find((rule: any) => rule.engine === 'vlm' && rule.status === 'active');
    // The legacy record can recover its source URL from the bridge before pausing.
    const create = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: activeRule.id }), create.response);
    const draft = { ...activeRule, id: undefined, name: 'Lifecycle rule', status: 'active', backendRuleId: 'original-backend' };
    const saved = responseHarness();
    await handler(request('POST', draft), saved.response);
    (global.fetch as jest.Mock).mockImplementation(async () => jsonTextResponse({ rule: { live_stream_url: 'rtsp://camera/live' } }));
    (liveAlertHandler as jest.Mock).mockImplementationOnce(async (_req, res) => res.status(502).json({ error: 'Caption stop failed.' }));
    const failedPause = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: saved.state.body.rule.id }), failedPause.response);
    expect(failedPause.state.statusCode).toBe(502);
    const afterFailure = responseHarness();
    await handler(request('GET'), afterFailure.response);
    expect(afterFailure.state.body.rules.find((rule: any) => rule.id === saved.state.body.rule.id).status).toBe('active');
    const paused = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: saved.state.body.rule.id }), paused.response);
    expect(paused.state.statusCode).toBe(200);
    expect(liveAlertHandler).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE', query: { id: 'original-backend' } }), expect.anything());
    expect(paused.state.body.rule).toMatchObject({ status: 'paused', liveStreamUrl: 'rtsp://camera/live' });
    const resumed = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: saved.state.body.rule.id }), resumed.response);
    expect(resumed.state.statusCode).toBe(200);
    expect(resumed.state.body.rule).toMatchObject({ status: 'active', backendRuleId: 'resumed-backend', backendRuleIds: ['original-backend', 'resumed-backend'] });
  });
  it('does not resume a detector rule after its source profile has changed', async () => {
    const list = responseHarness();
    await handler(request('GET'), list.response);
    const rule = list.state.body.rules.find((value: any) => value.engine === 'deepstream');
    const paused = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: rule.id }), paused.response);
    expect(paused.state.statusCode).toBe(200);
    (global.fetch as jest.Mock).mockImplementation(async () => jsonTextResponse({ profile: { id: 'semantic-search', detectionEnabled: false, ruleKinds: [], objectTypes: [] } }));
    const resumed = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: rule.id }), resumed.response);
    expect(resumed.state.statusCode).toBe(502);
    expect(resumed.state.body.error).toMatch(/profile changed/i);
    const after = responseHarness();
    await handler(request('GET'), after.response);
    expect(after.state.body.rules.find((value: any) => value.id === rule.id).status).toBe('paused');
  });

  it('does not claim a second proximity rule is active when the backend supports one per source', async () => {
    const draft = {
      analysisProfileId: 'warehouse-safety', cooldownSeconds: 30,
      description: 'Objects too close', engine: 'deepstream',
      geometry: { kind: 'full-frame', points: [], frameWidth: 1920, frameHeight: 1080 },
      kind: 'proximity', name: 'Proximity first', notify: false, objectTypes: ['Person', 'Forklift'], severity: 'warning',
      sourceId: 'proximity-source', sourceKind: 'recorded', sourceName: 'Warehouse', status: 'active', threshold: { proximityPixels: 140 },
    };
    const first = responseHarness();
    await handler(request('POST', draft), first.response);
    expect(first.state.statusCode).toBe(201);
    const second = responseHarness();
    await handler(request('POST', { ...draft, name: 'Second proximity', threshold: { proximityPixels: 200 } }), second.response);
    expect(second.state.statusCode).toBe(502);
    expect(second.state.body.error).toMatch(/one active proximity rule/i);
    expect(second.state.body.rule).toMatchObject({ status: 'draft', backendStatus: 'unavailable' });
  });

  it('rehydrates an explicitly resumed visual rule after the bridge loses its job and tolerates a missing job on pause', async () => {
    const list = responseHarness();
    await handler(request('GET'), list.response);
    const old = list.state.body.rules.find((value: any) => value.engine === 'vlm' && value.status === 'active');
    const paused = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: old.id }), paused.response);
    const create = responseHarness();
    await handler(request('POST', { ...old, name: 'Restart recovery', status: 'active', backendRuleId: 'lost-job', liveStreamUrl: 'rtsp://warehouse/live' }), create.response);
    expect(create.state.statusCode).toBe(201);
    (global.fetch as jest.Mock).mockImplementation(async () => ({ ok: false, status: 404, text: async () => JSON.stringify({ error: 'Job not found' }) }));
    const resume = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: create.state.body.rule.id }), resume.response);
    expect(resume.state.statusCode).toBe(200);
    expect(resume.state.body.rule.backendRuleId).toBe('resumed-backend');
    expect(liveAlertHandler).toHaveBeenCalledWith(expect.objectContaining({ method: 'POST', body: expect.objectContaining({ live_stream_url: 'rtsp://warehouse/live' }) }), expect.anything());
    const stop = responseHarness();
    await handler(request('PATCH', { action: 'pause' }, { id: create.state.body.rule.id }), stop.response);
    expect(stop.state.statusCode).toBe(200);
    expect(stop.state.body.rule.status).toBe('paused');
    expect(liveAlertHandler).toHaveBeenCalledWith(expect.objectContaining({ method: 'DELETE', query: { id: 'resumed-backend' } }), expect.anything());
  });

  it('does not recreate or claim success when the bridge is temporarily unavailable', async () => {
    const list = responseHarness();
    await handler(request('GET'), list.response);
    const base = list.state.body.rules.find((value: any) => value.engine === 'vlm');
    const create = responseHarness();
    await handler(request('POST', { ...base, name: 'Transient outage', status: 'active', backendRuleId: 'existing-job', liveStreamUrl: 'rtsp://warehouse/live' }), create.response);
    expect(create.state.statusCode).toBe(201);
    (global.fetch as jest.Mock).mockImplementation(async () => ({ ok: false, status: 503, text: async () => JSON.stringify({ error: 'Bridge unavailable' }) }));
    const previousCalls = (liveAlertHandler as jest.Mock).mock.calls.length;
    const resume = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: create.state.body.rule.id }), resume.response);
    expect(resume.state.statusCode).toBe(502);
    expect(resume.state.body.error).toBe('Bridge unavailable');
    expect((liveAlertHandler as jest.Mock).mock.calls).toHaveLength(previousCalls);
  });

  it.each(['failed', 'stopped'])('does not claim an existing %s visual job is active', async status => {
    const list = responseHarness();
    await handler(request('GET'), list.response);
    const active = list.state.body.rules.find((value: any) => value.engine === 'vlm' && value.status === 'active');
    (global.fetch as jest.Mock).mockImplementation(async () => jsonTextResponse({ rule: { status } }));
    const previousCalls = (liveAlertHandler as jest.Mock).mock.calls.length;
    const resume = responseHarness();
    await handler(request('PATCH', { action: 'resume' }, { id: active.id }), resume.response);
    expect(resume.state.statusCode).toBe(502);
    expect(resume.state.body.error).toContain(status);
    expect((liveAlertHandler as jest.Mock).mock.calls).toHaveLength(previousCalls);
  });

});
