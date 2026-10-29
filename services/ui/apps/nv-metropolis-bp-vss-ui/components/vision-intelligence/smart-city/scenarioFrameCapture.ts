// SPDX-License-Identifier: MIT
import type { CityVideoFrame } from './types';
import type { ScenarioObservationFrame } from './scenarioObservation';
import type { SceneDescriptionFrame } from './sceneDescription';
type Capture = () => { image: HTMLVideoElement | HTMLCanvasElement; frame: CityVideoFrame } | null;
const cameras = new Map<string, Capture>();
export function registerScenarioCamera(sourceId: string, capture: Capture): () => void {
  cameras.set(sourceId, capture);
  return () => { if (cameras.get(sourceId) === capture) cameras.delete(sourceId); };
}
/** Copy only raw video pixels; tracking labels and scripted text never enter
 * the model. Lossless PNG preserves small details in the single-frame input. */
export function captureScenarioFrame(identity: Omit<ScenarioObservationFrame, 'sourceTimeNs' | 'imageBase64'>): ScenarioObservationFrame | null {
  const current = cameras.get(identity.sourceId)?.();
  const scope = current?.frame.snapshot.analyticsScope;
  if (!current || scope?.kind !== 'scenario' || scope.suppressed || scope.epoch !== identity.epoch ||
      scope.runId !== identity.runId || scope.scenarioId !== identity.scenarioId ||
      current.frame.sessionId !== identity.sessionId || current.frame.sourceId !== identity.sourceId) return null;
  const pixels = capturePixels(current);
  return pixels ? { ...identity, ...pixels } : null;
}
/** Main-map descriptions need a fresh normal-traffic frame, not an event. */
export function captureSceneFrame(identity: Omit<SceneDescriptionFrame, 'sourceTimeNs' | 'imageBase64'>): SceneDescriptionFrame | null {
  const current = cameras.get(identity.sourceId)?.();
  const scope = current?.frame.snapshot.analyticsScope;
  if (!current || scope?.kind !== 'normal' || scope.suppressed !== false || scope.epoch !== identity.epoch ||
      current.frame.snapshot.siteId !== identity.siteId || current.frame.sessionId !== identity.sessionId ||
      current.frame.sourceId !== identity.sourceId) return null;
  const pixels = capturePixels(current);
  return pixels ? { ...identity, ...pixels } : null;
}
function capturePixels(current: NonNullable<ReturnType<Capture>>): Pick<SceneDescriptionFrame, 'sourceTimeNs' | 'imageBase64'> | null {
  if (!/^\d{1,24}$/.test(current.frame.sourceTimeNs)) return null;
  const age = Date.now() - Number(BigInt(current.frame.sourceTimeNs) / BigInt(1_000_000));
  if (age < -1000 || age > 4000) return null;
  const width = current.image instanceof HTMLVideoElement ? current.image.videoWidth : current.image.width;
  const height = current.image instanceof HTMLVideoElement ? current.image.videoHeight : current.image.height;
  if (!width || !height || width * height > 4_000_000) return null;
  const scale = Math.min(1, 1280 / width, 720 / height);
  const canvas = document.createElement('canvas'); canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
  const drawing = canvas.getContext('2d'); if (!drawing) return null;
  drawing.drawImage(current.image, 0, 0, canvas.width, canvas.height);
  const url = canvas.toDataURL('image/png'); const imageBase64 = url.slice(url.indexOf(',') + 1);
  if (!url.startsWith('data:image/png;base64,') || imageBase64.length > 2_800_000) return null;
  return { sourceTimeNs: current.frame.sourceTimeNs, imageBase64 };
}
