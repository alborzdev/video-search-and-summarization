// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import { admitWorkload, WorkloadAdmissionError } from '../../../server/vision/workloadAdmissionAdapter';
import { withCosmosReservation, CosmosReservationError } from '../../../server/vision/cosmosReservation';
import { ObservationError } from '../../../server/vision/scenarioObservation';
import { assertSceneScope, validateSceneFrame, sceneDescriptionText, SCENE_DESCRIPTION_PROMPT } from '../../../server/vision/sceneDescription';
import type { CitySnapshot } from '../../../components/vision-intelligence/smart-city/types';
import { OBSERVATION_INTERVAL_MS } from '../../../components/vision-intelligence/smart-city/scenarioObservation';
import type { SceneDescription } from '../../../components/vision-intelligence/smart-city/sceneDescription';
import { acquireObservationLane, readObservationLane, writeObservationLane, type ObservationLaneState } from '../../../server/vision/scenarioObservationLane';

export const config = { api: { bodyParser: { sizeLimit: '3mb' }, responseLimit: '16kb' } };
async function currentReport(): Promise<CitySnapshot> {
  const base = process.env.VSS_CITY_ANALYTICS_URL || 'http://127.0.0.1:9184';
  const response = await fetch(new URL('/api/v1/city/snapshot', base), { cache: 'no-store', signal: AbortSignal.timeout(2500), redirect: 'error' });
  if (!response.ok) throw new ObservationError('Camera evidence is unavailable.', 503);
  return response.json();
}
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed.' }); }
  if (req.headers.origin) {
    try { if (new URL(req.headers.origin).host !== req.headers.host) return res.status(403).json({ error: 'Use Describe scene in this app.' }); }
    catch { return res.status(403).json({ error: 'Invalid request origin.' }); }
  }
  let release: (() => Promise<void>) | null = null;
  let previous: ObservationLaneState | undefined;
  let modelStarted = false;
  let modelSettled = false;
  let persisted = false;
  let started = Date.now();
  try {
    const frame = validateSceneFrame(req.body);
    assertSceneScope(await currentReport(), frame);
    release = await acquireObservationLane();
    previous = await readObservationLane();
    if (!release || Date.now() < previous.nextAt) {
      res.setHeader('Retry-After', '3'); throw new ObservationError('VLM is busy. Try Describe scene again in a moment.', 429);
    }
    const admission = await admitWorkload('current_visual_question');
    if (admission.decision !== 'allow') throw new ObservationError('VLM is busy. Try Describe scene again in a moment.', 429);
    // Share the scenario lane and defer to existing caption work.
    if (admission.active.captions.sourceIds.length) throw new ObservationError('VLM is analyzing another stream.', 429);
    started = Date.now();
    const result = await withCosmosReservation(async () => {
      assertSceneScope(await currentReport(), frame);
      // A browser disconnect does not cancel GPU work. If this UI process
      // dies, other viewers wait out the bounded upstream deadline.
      await writeObservationLane({ ...previous!, nextAt: Date.now() + 60_000 });
      modelStarted = true;
      const response = await fetch(new URL('/v1/chat/completions', process.env.RTVI_VLM_URL || 'http://127.0.0.1:8018'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, redirect: 'error', signal: AbortSignal.timeout(45_000),
        body: JSON.stringify({ model: process.env.LVS_VLM_MODEL || 'nim_nvidia_cosmos3-nano-reasoner_bf16-final',
          messages: [{ role: 'user', content: [
            { type: 'image_url', image_url: { url: `data:image/png;base64,${frame.imageBase64}` } },
            { type: 'text', text: SCENE_DESCRIPTION_PROMPT },
          ] }], max_tokens: 110, temperature: 0, enable_reasoning: false, stream: false,
          num_frames_per_second_or_fixed_frames_chunk: 1 }),
      });
      modelSettled = true;
      if (!response.ok) throw new ObservationError('The VLM could not inspect this frame.', response.status === 503 ? 503 : 502);
      const payload = await response.json();
      const text = sceneDescriptionText(payload?.choices?.[0]?.message?.content);
      return { text, model: typeof payload.model === 'string' ? payload.model.slice(0, 160) : 'Cosmos' };
    });
    // A late answer must never appear after a scene or camera session changes.
    assertSceneScope(await currentReport(), frame, false);
    const observation: SceneDescription = { ...result, siteId: frame.siteId, epoch: frame.epoch,
      sourceId: frame.sourceId, sessionId: frame.sessionId, sourceTimeNs: frame.sourceTimeNs,
      observedAt: new Date(Number(BigInt(frame.sourceTimeNs) / BigInt(1_000_000))).toISOString(),
      completedAt: new Date().toISOString(), inferenceMs: Date.now() - started };
    previous = { ...previous, nextAt: Math.max(started + OBSERVATION_INTERVAL_MS, Date.now() + 1000) };
    await writeObservationLane(previous);
    persisted = true;
    return res.status(200).json(observation);
  } catch (error) {
    const known = error instanceof ObservationError || error instanceof CosmosReservationError;
    if (!known && !(error instanceof WorkloadAdmissionError)) console.warn('[city-description] Request failed:', error instanceof Error ? error.message : 'Unknown error');
    const status = known ? (error instanceof ObservationError ? error.status : error.statusCode) : error instanceof WorkloadAdmissionError ? error.statusCode : 503;
    return res.status(status).json({ error: known ? error.message : error instanceof WorkloadAdmissionError ? 'VLM paused by runtime admission. Check device readiness.' : 'VLM is unavailable. Try Describe scene again.' });
  } finally {
    if (release) {
      try {
        if (modelStarted && modelSettled && previous && !persisted) {
          // If persistence fails, keep the existing quarantine deadline.
          await writeObservationLane({ ...previous, nextAt: Math.max(started + OBSERVATION_INTERVAL_MS, Date.now() + 1000) }).catch(() => {});
        }
      } finally { await release(); }
    }
  }
}
