// SPDX-License-Identifier: MIT
import { OBSERVATION_RULES, type ScenarioObservationFrame } from '../../components/vision-intelligence/smart-city/scenarioObservation';
import type { AnalyticsScope } from '../../components/vision-intelligence/smart-city/types';

const ID = /^[A-Za-z0-9._:-]{1,160}$/;
const FIELDS = new Set(['siteId', 'scenarioId', 'epoch', 'runId', 'sourceId', 'sessionId', 'sourceTimeNs', 'imageBase64']);
export class ObservationError extends Error {
  constructor(message: string, readonly status = 409) { super(message); }
}
export function validateObservationFrame(value: unknown): ScenarioObservationFrame {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ObservationError('A current camera frame is required.', 422);
  const body = value as ScenarioObservationFrame;
  if (Object.keys(body).some(key => !FIELDS.has(key)) ||
      !['siteId', 'scenarioId', 'epoch', 'runId', 'sourceId', 'sessionId'].every(key => { const item = (body as unknown as Record<string, unknown>)[key]; return typeof item === 'string' && ID.test(item); }) ||
      !Object.prototype.hasOwnProperty.call(OBSERVATION_RULES, body.scenarioId) ||
      typeof body.sourceTimeNs !== 'string' || !/^\d{1,24}$/.test(body.sourceTimeNs)) throw new ObservationError('The scenario frame identity is invalid.', 422);
  validateCameraPng(body.imageBase64);
  return body;
}
export function validateCameraPng(encoded: unknown): void {
  if (typeof encoded !== 'string' || encoded.length > 2_800_000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new ObservationError('A PNG camera frame up to 2 MiB is required.', 422);
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.length < 33 || bytes.length > 2 * 1024 * 1024 || bytes.toString('base64') !== encoded ||
      !bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || bytes.subarray(12,16).toString() !== 'IHDR' ||
      bytes.readUInt32BE(16) < 1 || bytes.readUInt32BE(16) > 1280 || bytes.readUInt32BE(20) < 1 || bytes.readUInt32BE(20) > 720) throw new ObservationError('A PNG camera frame up to 1280 × 720 and 2 MiB is required.', 422);
}
export interface ObservationReport {
  siteId: string; mode: string; analyticsScope: AnalyticsScope;
  measurements: { ruleId: string; sourceId: string; sessionId: string; peakCount: number; status: string; asOfSourceTimeNs: string }[];
}
export function assertObservationScope(report: ObservationReport, frame: ScenarioObservationFrame, fresh = true): void {
  const scope = report?.analyticsScope;
  const row = report?.measurements?.find(item => item.ruleId === OBSERVATION_RULES[frame.scenarioId]);
  const captureMs = Number(BigInt(frame.sourceTimeNs) / BigInt(1_000_000));
  const age = Date.now() - captureMs;
  if (report.siteId !== frame.siteId || report.mode !== 'live' || scope?.kind !== 'scenario' || scope.suppressed !== false ||
      scope.epoch !== frame.epoch || scope.runId !== frame.runId || scope.scenarioId !== frame.scenarioId ||
      !Number.isFinite(Date.parse(scope.startedAt ?? '')) || captureMs < Date.parse(scope.startedAt!) ||
      !row || row.sourceId !== frame.sourceId || row.sessionId !== frame.sessionId ||
      !(row.peakCount > 0) || fresh && !['occupied', 'clear'].includes(row.status)) throw new ObservationError('Waiting for camera evidence in this scenario.');
  if (fresh && (age < -1000 || age > 5000 || !/^\d{1,24}$/.test(row.asOfSourceTimeNs) ||
      Math.abs(captureMs - Number(BigInt(row.asOfSourceTimeNs) / BigInt(1_000_000))) > 4000)) throw new ObservationError('Waiting for a fresh camera frame.');
}
// These questions identify the subject; no actor counts, scripted outcomes or
// detector measurements are supplied as facts for the model to repeat.
export const SCENARIO_OBSERVATION_PROMPTS: Readonly<Record<string, string>> = {
  'crossing-occupancy': 'Describe people on the pedestrian crossing in one sentence of at most 25 words. Describe positions, not exact counts. Use only visible evidence.',
  'queue-blockage': 'In at most 25 words, describe vehicles in the junction and any visible road obstruction. Use only visible positions; do not infer motion or why vehicles stopped.',
  'emergency-access': 'Where is any emergency vehicle relative to other vehicles? Describe visible positions and obstacles in at most 25 words. If none is identifiable, say so.',
};

export function observationText(value: unknown): string {
  if (typeof value !== 'string' || value.length > 12000) throw new ObservationError('The VLM returned no usable observation.', 502);
  const text = value.replace(/<(?:think|reasoning|agent-think)>[\s\S]*?<\/(?:think|reasoning|agent-think)>/gi, '')
    .replace(/<(?:think|reasoning|agent-think)\b[\s\S]*$/gi, '')
    .replace(/<\/?answer>/gi, '').replace(/^\s*(?:At\s+0(?:\.0+)?\s*seconds?[,,:]?\s*)/i, '').trim();
  if (!text || text.length > 1000) throw new ObservationError('The VLM returned no usable observation.', 502);
  return text;
}
