// SPDX-License-Identifier: MIT
import { objectName } from './geometry';
import type { CityTrack } from './types';

export interface CameraLabel { x: number; y: number; width: number; height: number; text: string; }
interface Entry {
  seenAt: number; eligible: boolean; shown: boolean; side?: 'above' | 'below';
  label?: CameraLabel; clearSince?: number;
}
export interface CameraLabelLayout {
  scope: string; width: number; height: number; timeMs: number;
  entries: Map<string, Entry>; labels: Map<string, CameraLabel>;
}

// These are overview categories, not revised detector classifications. In particular,
// an ambiguous SUV must not alternate between Car and Truck in the camera overlay.
export function cameraCategory(className: string): string {
  return ['car', 'truck', 'bus', 'vehicle'].includes(className) ? 'Vehicle' : objectName(className);
}

/** Remember label layout only. Every returned label belongs to a current observation;
 * boxes, IDs, classes and analytics are never interpolated or carried forward here. */
export function cameraLabelLayout(
  tracks: readonly CityTrack[], width: number, height: number, selectedId: string | null,
  scope: string, timeMs: number, previous?: CameraLabelLayout,
): CameraLabelLayout {
  const reusable = previous?.scope === scope && previous.width === width && previous.height === height
    && timeMs >= previous.timeMs && timeMs - previous.timeMs <= 400;
  const history = reusable ? previous.entries : new Map<string, Entry>();
  const entries = new Map<string, Entry>();
  // A brief gap may retain placement preferences, never visible objects.
  for (const [id, entry] of history) if (timeMs - entry.seenAt <= 400) entries.set(id, entry);
  const labels = new Map<string, CameraLabel>();
  const result = { scope, width, height, timeMs, entries, labels };
  if (!(width > 0 && height > 0 && Number.isFinite(timeMs))) return result;
  const retainedOrder = new Map(reusable ? Array.from(previous.labels.keys(), (id, i) => [id, i]) : []);
  const ordered = [...tracks].sort((a, b) => Number(b.id === selectedId) - Number(a.id === selectedId)
    || (retainedOrder.get(a.id) ?? Infinity) - (retainedOrder.get(b.id) ?? Infinity)
    || b.bboxPx[2] * b.bboxPx[3] - a.bboxPx[2] * a.bboxPx[3]
    || a.id.localeCompare(b.id));
  const clamp = (n: number, max: number) => Math.max(0, Math.min(max, n));
  for (const track of ordered) {
    const old = entries.get(track.id);
    const [x, y, w, h] = track.bboxPx;
    const selected = track.id === selectedId;
    const eligible = h >= height * (old?.eligible ? .045 : .065);
    const entry: Entry = { ...old, seenAt: timeMs, eligible, shown: false, clearSince: undefined };
    entries.set(track.id, entry);
    if (track.stale || track.observedThisFrame === false || ![x, y, w, h].every(Number.isFinite)
      || w <= 0 || h <= 0 || x + w <= 0 || y + h <= 0 || x >= width || y >= height
      || (!eligible && !selected) || labels.size >= 8) continue;
    const text = cameraCategory(track.class);
    const labelHeight = width / 35;
    const labelWidth = Math.min(width, Math.max(width / 20, text.length * width / 83 + width / 65));
    // Once placed, keep the same side of the box. Crowding must not bounce text
    // between the roof and wheels on adjacent frames.
    const sides: ('above' | 'below')[] = old?.side
      ? selected ? [old.side, old.side === 'above' ? 'below' : 'above'] : [old.side]
      : ['above', 'below'];
    for (const side of sides) {
      const desired = { x: clamp(x, width - labelWidth), y: clamp(side === 'above' ? y - labelHeight - 3 : y + h + 3, height - labelHeight), width: labelWidth, height: labelHeight, text };
      const hold = old?.label && old.side === side && old.label.text === text
        && Math.hypot(old.label.x - desired.x, old.label.y - desired.y) <= width / 160;
      const label = hold ? old!.label! : desired;
      const crowded = Array.from(labels.values()).some(other => label.x < other.x + other.width + 4
        && label.x + label.width + 4 > other.x && label.y < other.y + other.height + 4
        && label.y + label.height + 4 > other.y);
      if (crowded) continue;
      entry.side = side; entry.label = label;
      // A suppressed label needs sustained room before returning. Selection is immediate.
      entry.clearSince = old?.clearSince ?? timeMs;
      if (!selected && old && !old.shown && timeMs - entry.clearSince < 180) break;
      entry.shown = true; labels.set(track.id, label); break;
    }
  }
  return result;
}
