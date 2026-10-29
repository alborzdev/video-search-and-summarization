// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';
import { admitWorkload, WorkloadAdmissionError } from '../../../server/vision/workloadAdmissionAdapter';
import { withCosmosReservation, CosmosReservationError } from '../../../server/vision/cosmosReservation';
import { assertObservationScope, validateObservationFrame, ObservationError, observationText, SCENARIO_OBSERVATION_PROMPTS, type ObservationReport } from '../../../server/vision/scenarioObservation';
import { OBSERVATION_INTERVAL_MS, type ScenarioObservation } from '../../../components/vision-intelligence/smart-city/scenarioObservation';
import { acquireObservationLane, readObservationLane, writeObservationLane, sharedObservation, type ObservationLaneState } from '../../../server/vision/scenarioObservationLane';

export const config = { api: { bodyParser: { sizeLimit: '3mb' }, responseLimit: '16kb' } };
async function currentReport(): Promise<ObservationReport> {
  const base = process.env.VSS_CITY_ANALYTICS_URL || 'http://127.0.0.1:9184';
  const response = await fetch(new URL('/api/v1/city/showcase', base), { cache: 'no-store', signal: AbortSignal.timeout(2500), redirect: 'error' });
  if (!response.ok) throw new ObservationError('Camera evidence is unavailable.', 503);
  return response.json();
}
export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).json({ error: 'Method not allowed.' }); }
  if (req.headers.origin) {
    try { if (new URL(req.headers.origin).host !== req.headers.host) return res.status(403).json({ error: 'Use the scenario in this app.' }); }
    catch { return res.status(403).json({ error: 'Invalid request origin.' }); }
  }
  let release: (() => Promise<void>) | null = null;
  let previous: ObservationLaneState | undefined;
  let modelStarted = false;
  let modelSettled = false;
  let persisted = false;
  let started = Date.now();
  try {
    const frame = validateObservationFrame(req.body);
    assertObservationScope(await currentReport(), frame);
    release = await acquireObservationLane();
    previous = await readObservationLane();
    if (!release || Date.now() < previous.nextAt) {
      const cached = sharedObservation(previous, frame);
      if (cached) return res.status(200).json({ ...cached, shared: true });
      res.setHeader('Retry-After', '3'); throw new ObservationError('VLM busy · waiting for the next frame.', 429);
    }
    const admission = await admitWorkload('current_visual_question');
    if (admission.decision !== 'allow') throw new ObservationError('VLM busy · waiting for the next frame.', 429);
    // No caption suspension at a three-second cadence. Defer to existing work.
    if (admission.active.captions.sourceIds.length) throw new ObservationError('VLM is analyzing another stream.', 429);
    started = Date.now();
    const result = await withCosmosReservation(async () => {
      assertObservationScope(await currentReport(), frame);
      // A browser disconnect does not cancel GPU work. If this UI process
      // dies, other viewers wait out the bounded upstream deadline.
      await writeObservationLane({ ...previous!, nextAt: Date.now() + 60_000 });
      modelStarted = true;
      const response = await fetch(new URL('/v1/chat/completions', process.env.RTVI_VLM_URL || 'http://127.0.0.1:8018'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, redirect: 'error', signal: AbortSignal.timeout(45_000),
        body: JSON.stringify({ model: process.env.LVS_VLM_MODEL || 'nim_nvidia_cosmos3-nano-reasoner_bf16-final',
          messages: [{ role: 'user', content: [
            { type: 'image_url', image_url: { url: `data:image/png;base64,${frame.imageBase64}` } },
            { type: 'text', text: SCENARIO_OBSERVATION_PROMPTS[frame.scenarioId] },
          ] }], max_tokens: 75, temperature: 0, enable_reasoning: false, stream: false,
          num_frames_per_second_or_fixed_frames_chunk: 1 }),
      });
      modelSettled = true;
      if (!response.ok) throw new ObservationError('The VLM could not inspect this frame.', response.status === 503 ? 503 : 502);
      const payload = await response.json();
      const text = observationText(payload?.choices?.[0]?.message?.content);
      return { text, model: typeof payload.model === 'string' ? payload.model.slice(0, 160) : 'Cosmos' };
    });
    // A late answer must never appear in a newer run or camera session.
    assertObservationScope(await currentReport(), frame, false);
    const observation: ScenarioObservation = { ...result, scenarioId: frame.scenarioId, epoch: frame.epoch, runId: frame.runId,
      sourceId: frame.sourceId, sessionId: frame.sessionId, sourceTimeNs: frame.sourceTimeNs,
      observedAt: new Date(Number(BigInt(frame.sourceTimeNs) / BigInt(1_000_000))).toISOString(),
      completedAt: new Date().toISOString(), inferenceMs: Date.now() - started };
    previous = { nextAt: Math.max(started + OBSERVATION_INTERVAL_MS, Date.now() + 1000), observation };
    await writeObservationLane(previous);
    persisted = true;
    return res.status(200).json(observation);
  } catch (error) {
    const known = error instanceof ObservationError || error instanceof CosmosReservationError;
    const status = known ? (error instanceof ObservationError ? error.status : error.statusCode) : error instanceof WorkloadAdmissionError ? error.statusCode : 503;
    return res.status(status).json({ error: known ? error.message : error instanceof WorkloadAdmissionError ? 'VLM paused by runtime admission. Check device readiness.' : 'VLM unavailable · retrying shortly.' });
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
