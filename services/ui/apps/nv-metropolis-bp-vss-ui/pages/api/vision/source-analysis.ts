// SPDX-License-Identifier: MIT

import type { VideoHistoryRecord } from '../../../components/vision-intelligence/videoHistory';
import type { NextApiRequest, NextApiResponse } from 'next';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

import { THOR_LIVE_CAPTION_PROFILE } from '../../../server/vision/liveCaptionProfile';
import { isSourceLiveAlertFocused } from '../../../server/vision/liveAlertReservation';

const STORE_DIR = process.env.VISION_HISTORY_DIR || '/tmp/vss-vision-intelligence-history';
const AGENT_URL = (process.env.VISION_AGENT_INTERNAL_URL || 'http://127.0.0.1:8100/api/v1').replace(/\/$/, '');
const LVS_URL = (process.env.LVS_BACKEND_URL || 'http://127.0.0.1:38111').replace(/\/$/, '');
const RTVI_VLM_URL = (process.env.RTVI_VLM_URL || 'http://127.0.0.1:8018').replace(/\/$/, '');
const DEFAULT_MODEL = process.env.LVS_VLM_MODEL || 'nim_nvidia_cosmos3-nano-reasoner_bf16-final';
const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;

type Action = 'configure' | 'pause' | 'resume';

async function readHistory(sourceId: string): Promise<VideoHistoryRecord | null> {
  try {
    return JSON.parse(
      await readFile(path.join(STORE_DIR, `${sourceId}.json`), 'utf8')
    ) as VideoHistoryRecord;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'ENOENT' ? null : Promise.reject(error);
  }
}

async function requestJson(url: string, init: RequestInit, timeoutMs = 90_000) {
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = {};
  }
  return { payload, response };
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed.' });
  }
  const body = req.body as {
    action?: Action;
    analysisProfileId?: string;
    detectionEnabled?: boolean;
    name?: string;
    sourceKind?: 'live' | 'recorded';
    sourceId?: string;
  };
  const sourceId = typeof body.sourceId === 'string' ? body.sourceId.trim() : '';
  const name = typeof body.name === 'string' ? body.name.trim() : '';
  if (
    (body.action !== 'configure' && body.action !== 'pause' && body.action !== 'resume') ||
    (body.action === 'configure' &&
      typeof body.analysisProfileId !== 'string' &&
      typeof body.detectionEnabled !== 'boolean') ||
    (body.analysisProfileId !== undefined && !ID_PATTERN.test(body.analysisProfileId)) ||
    (body.sourceKind !== undefined && body.sourceKind !== 'live' && body.sourceKind !== 'recorded') ||
    (body.sourceKind === 'recorded' && body.action !== 'configure') ||
    !ID_PATTERN.test(sourceId) ||
    !name ||
    name.length > 256
  ) {
    return res.status(422).json({ error: 'Choose a valid live source and action.' });
  }

  try {
    if (body.sourceKind === 'recorded') {
      const { payload: agentPayload, response: agentResponse } = await requestJson(
        `${AGENT_URL}/videos/${encodeURIComponent(sourceId)}/analysis`,
        {
          body: JSON.stringify({ analysisProfileId: body.analysisProfileId }),
          headers: { 'Content-Type': 'application/json' },
          method: 'POST',
        },
        180_000
      );
      if (!agentResponse.ok) {
        return res.status(502).json({
          error:
            (typeof agentPayload.detail === 'string' && agentPayload.detail) ||
            (typeof agentPayload.message === 'string' && agentPayload.message) ||
            'The recording could not be reprocessed.',
        });
      }
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json({
        action: 'configure',
        analysisActive: true,
        analysisProfileId: agentPayload.analysisProfileId,
        detectionEnabled: agentPayload.detectionEnabled === true,
        generatedDataDeleted: agentPayload.generatedDataDeleted,
        message: agentPayload.message,
        name,
        sensorId: sourceId,
        state: 'active',
      });
    }

    if (body.action !== 'configure' && (await isSourceLiveAlertFocused(sourceId))) {
      return res.status(409).json({
        error: 'Remove this source\'s live alert rule before pausing or restarting its analysis.',
      });
    }
    const { payload: agentPayload, response: agentResponse } = await requestJson(
      `${AGENT_URL}/rtsp-streams/${encodeURIComponent(sourceId)}/analysis`,
      {
        body: JSON.stringify({
          action: body.action,
          ...(body.action === 'configure'
            ? body.analysisProfileId
              ? { analysisProfileId: body.analysisProfileId }
              : { detectionEnabled: body.detectionEnabled }
            : {}),
          name,
        }),
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
      }
    );
    if (!agentResponse.ok || agentPayload.state === 'partial') {
      return res.status(502).json({
        error:
          (typeof agentPayload.message === 'string' && agentPayload.message) ||
          'Detection and embedding control did not complete.',
      });
    }

    if (body.action === 'configure') {
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json({
        action: 'configure',
        analysisActive: agentPayload.analysisActive === true,
        analysisProfileId:
          typeof agentPayload.analysisProfileId === 'string'
            ? agentPayload.analysisProfileId
            : body.analysisProfileId,
        detectionEnabled: agentPayload.detectionEnabled === true,
        message:
          (typeof agentPayload.message === 'string' && agentPayload.message) ||
          'Analytics profile updated.',
        name,
        sensorId: sourceId,
        state: agentPayload.state,
        steps: agentPayload.steps,
      });
    }

    const history = await readHistory(sourceId);

    let captioning: 'active' | 'not-configured' | 'paused' = 'not-configured';
    if (history?.sourceKind === 'live') {
      if (body.action === 'pause') {
        const response = await fetch(
          `${RTVI_VLM_URL}/v1/generate_captions/${encodeURIComponent(sourceId)}`,
          { method: 'DELETE', signal: AbortSignal.timeout(90_000) }
        );
        if (!response.ok && response.status !== 404) {
          // Restore real-time paths when captioning could not reach the same
          // desired state, preventing a deceptively partial pause.
          await fetch(`${AGENT_URL}/rtsp-streams/${encodeURIComponent(sourceId)}/analysis`, {
            body: JSON.stringify({ action: 'resume', name }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
          }).catch(() => undefined);
          return res.status(502).json({ error: 'Cosmos captioning could not be paused.' });
        }
        captioning = 'paused';
      } else {
        const { response } = await requestJson(
          `${LVS_URL}/v1/generate_captions`,
          {
            body: JSON.stringify({
              ...THOR_LIVE_CAPTION_PROFILE,
              enable_qa: true,
              events: history.events,
              id: sourceId,
              model: DEFAULT_MODEL,
              objects_of_interest: [],
              scenario: history.scenario,
            }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
          },
          45_000
        );
        if (!response.ok) {
          await fetch(`${AGENT_URL}/rtsp-streams/${encodeURIComponent(sourceId)}/analysis`, {
            body: JSON.stringify({ action: 'pause', name }),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
          }).catch(() => undefined);
          return res.status(502).json({ error: 'Cosmos captioning could not be resumed.' });
        }
        captioning = 'active';
      }
    }

    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({
      action: body.action,
      analysisActive: body.action === 'resume',
      captioning,
      message:
        body.action === 'resume'
          ? 'Live analysis resumed; new searchable evidence is accumulating.'
          : 'Live analysis paused; retained and indexed evidence was preserved.',
      name,
      sensorId: sourceId,
      state: body.action === 'resume' ? 'active' : 'paused',
      steps: agentPayload.steps,
    });
  } catch (error) {
    return res.status(502).json({
      error:
        error instanceof Error
          ? error.message
          : 'Source analysis control is unavailable.',
    });
  }
}
