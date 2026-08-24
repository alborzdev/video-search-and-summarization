// SPDX-License-Identifier: MIT

import type { VideoHistoryRecord } from '../../../components/vision-intelligence/videoHistory';
import type { NextApiRequest, NextApiResponse } from 'next';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

import { THOR_LIVE_ALERT_PROFILE, THOR_LIVE_CAPTION_PROFILE } from '../../../server/vision/liveCaptionProfile';
import {
  liveAlertReservationsForSource,
  readLiveAlertReservation,
  removeLiveAlertReservation,
  writeLiveAlertReservation,
} from '../../../server/vision/liveAlertReservation';
import {
  admitWorkload,
  WorkloadAdmissionError,
  workloadAdmissionFailure,
} from '../../../server/vision/workloadAdmissionAdapter';

interface RealtimeRule {
  id: string;
  sensor_id?: string;
  status?: string;
}

interface StreamState {
  active: boolean;
  exists: boolean;
}

const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;
let coordinatorQueue: Promise<void> = Promise.resolve();

function alertBridgeUrl(): string {
  return (process.env.ALERT_BRIDGE_INTERNAL_URL || 'http://127.0.0.1:9080/api/v1').replace(/\/$/, '');
}

function historyDirectory(): string {
  return process.env.VISION_HISTORY_DIR || '/tmp/vss-vision-intelligence-history';
}

function lvsUrl(): string {
  return (process.env.LVS_BACKEND_URL || 'http://127.0.0.1:38111').replace(/\/$/, '');
}

function modelName(): string {
  return process.env.LVS_VLM_MODEL || 'nim_nvidia_cosmos3-nano-reasoner_bf16-final';
}

function rtviVlmUrl(): string {
  return (process.env.RTVI_VLM_URL || 'http://127.0.0.1:8018').replace(/\/$/, '');
}

async function exclusive<T>(operation: () => Promise<T>): Promise<T> {
  const previous = coordinatorQueue;
  let release: () => void = () => undefined;
  coordinatorQueue = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  try {
    return await operation();
  } finally {
    release();
  }
}

async function readJson(response: Response): Promise<Record<string, any>> {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) as Record<string, any> : {};
  } catch {
    return {};
  }
}

async function bridgeRequest(pathname: string, init: RequestInit = {}) {
  const response = await fetch(`${alertBridgeUrl()}${pathname}`, {
    ...init,
    signal: AbortSignal.timeout(60_000),
  });
  return { payload: await readJson(response), response };
}

async function listRules(): Promise<RealtimeRule[]> {
  const { payload, response } = await bridgeRequest('/realtime', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `Alert service returned ${response.status}.`);
  }
  return Array.isArray(payload.rules) ? payload.rules as RealtimeRule[] : [];
}

async function readHistory(sourceId: string): Promise<VideoHistoryRecord | null> {
  try {
    return JSON.parse(
      await readFile(path.join(historyDirectory(), `${sourceId}.json`), 'utf8')
    ) as VideoHistoryRecord;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

async function streamState(sourceId: string): Promise<StreamState> {
  const response = await fetch(`${rtviVlmUrl()}/v1/stream/get-stream-info`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) throw new Error('Cosmos stream state is unavailable.');
  const payload = await response.json() as {
    stream_list?: Array<{ asset_id?: string; camera_id?: string; inference_active?: boolean }>;
  };
  const stream = (payload.stream_list ?? []).find(
    (candidate) => candidate.camera_id === sourceId || candidate.asset_id === sourceId
  );
  return { active: Boolean(stream?.inference_active), exists: Boolean(stream) };
}

async function suspendHistory(sourceId: string): Promise<void> {
  const response = await fetch(
    `${rtviVlmUrl()}/v1/generate_captions/${encodeURIComponent(sourceId)}`,
    { method: 'DELETE', signal: AbortSignal.timeout(60_000) }
  );
  if (!response.ok && response.status !== 404) {
    throw new Error('Cosmos could not focus on this live rule.');
  }
}

async function resumeHistory(sourceId: string): Promise<boolean> {
  const history = await readHistory(sourceId);
  if (history?.sourceKind !== 'live' || !history.events.length || !history.scenario.trim()) return false;
  const response = await fetch(`${lvsUrl()}/v1/generate_captions`, {
    body: JSON.stringify({
      ...THOR_LIVE_CAPTION_PROFILE,
      enable_qa: true,
      events: history.events,
      id: sourceId,
      model: modelName(),
      objects_of_interest: [],
      scenario: history.scenario,
    }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
    signal: AbortSignal.timeout(45_000),
  });
  return response.ok;
}

function apiError(payload: Record<string, any>, status: number, fallback: string): string {
  return String(payload.message || payload.error || `${fallback} (${status}).`);
}

async function createRule(req: NextApiRequest, res: NextApiResponse) {
  const body = req.body as Record<string, unknown>;
  const sourceId = typeof body.sensor_id === 'string' ? body.sensor_id.trim() : '';
  const liveStreamUrl = typeof body.live_stream_url === 'string' ? body.live_stream_url.trim() : '';
  const prompt = typeof body.prompt === 'string' ? body.prompt.trim() : '';
  const alertType = typeof body.alert_type === 'string' ? body.alert_type.trim() : '';
  if (
    !ID_PATTERN.test(sourceId) || !liveStreamUrl.toLowerCase().startsWith('rtsp://') ||
    !prompt || prompt.length > 2_000 || !alertType || alertType.length > 160
  ) {
    return res.status(422).json({ error: 'Choose a valid live source and visual condition.' });
  }

  return exclusive(async () => {
    const existing = (await listRules()).filter((rule) => rule.status !== 'failed');
    if (existing.length) {
      return res.status(409).json({
        error: 'Thor is already focused on a continuous visual rule. Remove it before creating another; search and detection remain active for every source.',
      });
    }

    // A queued outcome is intentionally allowed here: this coordinator owns
    // the caption handoff below and never starts a second continuous rule.
    await admitWorkload('live_vlm_alert');

    const state = await streamState(sourceId);
    if (state.active) await suspendHistory(sourceId);

    let createdId = '';
    try {
      const { payload, response } = await bridgeRequest('/realtime', {
        body: JSON.stringify({
          ...body,
          ...THOR_LIVE_ALERT_PROFILE,
          alert_type: alertType,
          live_stream_url: liveStreamUrl,
          preserve_rtvi_stream: state.exists,
          prompt,
          sensor_id: sourceId,
        }),
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
      });
      if (!response.ok) {
        throw Object.assign(
          new Error(apiError(payload, response.status, 'Alert service rejected the rule')),
          { statusCode: response.status }
        );
      }
      createdId = typeof payload.id === 'string' ? payload.id : '';
      if (!ID_PATTERN.test(createdId)) throw new Error('Alert service returned an invalid rule identifier.');
      await writeLiveAlertReservation(createdId, { resumeHistory: state.active, sourceId });
      res.setHeader('Cache-Control', 'no-store');
      return res.status(201).json({ ...payload, focused: true });
    } catch (error) {
      if (createdId) {
        await bridgeRequest(`/realtime/${encodeURIComponent(createdId)}`, { method: 'DELETE' }).catch(() => undefined);
      }
      if (state.active) await resumeHistory(sourceId).catch(() => false);
      const statusCode = Number((error as { statusCode?: number }).statusCode) || 502;
      return res.status(statusCode >= 400 && statusCode < 500 ? statusCode : 502).json({
        error: error instanceof Error ? error.message : 'The live rule could not be created.',
      });
    }
  });
}

async function deleteRule(req: NextApiRequest, res: NextApiResponse) {
  const sourceQuery = typeof req.query.sourceId === 'string' ? req.query.sourceId.trim() : '';
  if (sourceQuery) {
    if (!ID_PATTERN.test(sourceQuery)) return res.status(422).json({ error: 'Choose a valid source.' });
    return exclusive(async () => {
      const rules = await listRules();
      const targets = rules.filter((rule) => rule.sensor_id === sourceQuery);
      for (const rule of targets) {
        const { payload, response } = await bridgeRequest(
          `/realtime/${encodeURIComponent(rule.id)}`,
          { method: 'DELETE' }
        );
        if (!response.ok) {
          return res.status(response.status).json({
            error: apiError(payload, response.status, 'Alert service could not release the source rule'),
          });
        }
        await removeLiveAlertReservation(rule.id);
      }
      // Remove an orphaned reservation as well (for example after Alert
      // Bridge was restarted and lost a non-persistent rule).
      const stale = await liveAlertReservationsForSource(sourceQuery);
      await Promise.all(stale.map(({ ruleId }) => removeLiveAlertReservation(ruleId)));
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json({ deleted: targets.length, sourceId: sourceQuery });
    });
  }

  const ruleId = typeof req.query.id === 'string' ? req.query.id.trim() : '';
  if (!ID_PATTERN.test(ruleId)) return res.status(422).json({ error: 'Choose a valid alert rule.' });

  return exclusive(async () => {
    const rulesBefore = await listRules();
    const target = rulesBefore.find((rule) => rule.id === ruleId);
    const reservation = await readLiveAlertReservation(ruleId);
    const sourceId = reservation?.sourceId || target?.sensor_id || '';
    const { payload, response } = await bridgeRequest(
      `/realtime/${encodeURIComponent(ruleId)}`,
      { method: 'DELETE' }
    );
    if (!response.ok) {
      return res.status(response.status).json({
        error: apiError(payload, response.status, 'Alert service could not delete the rule'),
      });
    }

    const remaining = await listRules();
    const sourceStillFocused = Boolean(
      sourceId && remaining.some((rule) => rule.sensor_id === sourceId && rule.status !== 'failed')
    );
    let historyResumed = false;
    if (sourceId && reservation?.resumeHistory && !sourceStillFocused) {
      historyResumed = await resumeHistory(sourceId).catch(() => false);
    }
    await removeLiveAlertReservation(ruleId);

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ ...payload, historyResumed });
  });
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  try {
    if (req.method === 'GET') {
      const rules = await listRules();
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json({ rules });
    }
    if (req.method === 'POST') return await createRule(req, res);
    if (req.method === 'DELETE') return await deleteRule(req, res);
    res.setHeader('Allow', 'GET, POST, DELETE');
    return res.status(405).json({ error: 'Method not allowed.' });
  } catch (error) {
    if (error instanceof WorkloadAdmissionError) {
      return res.status(error.statusCode).json(workloadAdmissionFailure(error));
    }
    return res.status(503).json({
      error: error instanceof Error ? error.message : 'Live alert orchestration is unavailable.',
    });
  }
}
