// SPDX-License-Identifier: MIT
import type { SceneDescriptionFrame } from '../../components/vision-intelligence/smart-city/sceneDescription';
import type { CitySnapshot } from '../../components/vision-intelligence/smart-city/types';
import { ObservationError, observationText, validateCameraPng } from './scenarioObservation';

const FIELDS = new Set(['siteId', 'epoch', 'sourceId', 'sessionId', 'sourceTimeNs', 'imageBase64']);
export function validateSceneFrame(value: unknown): SceneDescriptionFrame {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ObservationError('A current camera frame is required.', 422);
  const body = value as SceneDescriptionFrame;
  if (Object.keys(body).some(key => !FIELDS.has(key)) ||
      !['siteId', 'epoch', 'sourceId', 'sessionId'].every(key => {
        const item = (body as unknown as Record<string, unknown>)[key];
        return typeof item === 'string' && /^[A-Za-z0-9._:-]{1,160}$/.test(item);
      }) || typeof body.sourceTimeNs !== 'string' || !/^\d{1,24}$/.test(body.sourceTimeNs)) throw new ObservationError('The camera frame identity is invalid.', 422);
  validateCameraPng(body.imageBase64);
  return body;
}
export function assertSceneScope(snapshot: CitySnapshot, frame: SceneDescriptionFrame, fresh = true): void {
  const scope = snapshot?.analyticsScope;
  const source = snapshot?.sources?.find(item => item.id === frame.sourceId);
  const captured = Number(BigInt(frame.sourceTimeNs) / BigInt(1_000_000));
  if (snapshot?.siteId !== frame.siteId || snapshot.mode !== 'live' || scope?.kind !== 'normal' ||
      scope.suppressed !== false || scope.epoch !== frame.epoch ||
      !Number.isFinite(Date.parse(scope.startedAt ?? '')) || captured < Date.parse(scope.startedAt!) ||
      !source || source.sessionId !== frame.sessionId || source.analyticsScope?.kind !== 'normal' ||
      source.analyticsScope.epoch !== frame.epoch || source.analyticsScope.suppressed !== false) {
    throw new ObservationError('The scene changed. Describe the new view again.');
  }
  if (fresh && (source.status !== 'live' || Date.now() - captured < -1000 || Date.now() - captured > 5000 ||
      !/^\d{1,24}$/.test(source.lastSourceTimeNs ?? '') ||
      Math.abs(captured - Number(BigInt(source.lastSourceTimeNs!) / BigInt(1_000_000))) > 4000)) {
    throw new ObservationError('A fresh camera frame is not ready. Try again in a moment.');
  }
}
export const SCENE_DESCRIPTION_PROMPT = 'Describe vehicles and pedestrians at this intersection in one sentence of at most 35 words. Mention their visible positions around the crossing and junction. Do not infer movement, duration or intent from this still image.';
export function sceneDescriptionText(value: unknown): string {
  // Keep the footer brief even if the model ignores the requested sentence count.
  return observationText(value).split(/(?<=[.!?])\s+/).slice(0, 2).join(' ');
}
