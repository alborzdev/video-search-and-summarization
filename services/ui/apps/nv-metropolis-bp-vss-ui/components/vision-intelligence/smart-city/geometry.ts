// SPDX-License-Identifier: MIT
import type { CityEvent, CityRule, CitySource, CityTrack, Point } from './types';

/** Use the same centered contain/cover fit as the decoded media and SVG overlay. */
export function normalizedPoint(clientX: number, clientY: number, rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>, width: number, height: number, fit: 'contain' | 'cover' = 'contain'): Point | null {
  const scale = (fit === 'cover' ? Math.max : Math.min)(rect.width / width, rect.height / height);
  const left = rect.left + (rect.width - width * scale) / 2;
  const top = rect.top + (rect.height - height * scale) / 2;
  const x = (clientX - left) / (width * scale);
  const y = (clientY - top) / (height * scale);
  return x >= 0 && y >= 0 && x <= 1 && y <= 1 ? [x, y] : null;
}
export function projectPoint(point: Point, homography?: number[][]): Point | null {
  if (!homography || homography.length !== 3 || homography.some(row => row.length !== 3)) return null;
  const coefficients = homography.flat();
  if (!coefficients.every(Number.isFinite)) return null;
  const scale = Math.max(...coefficients.map(Math.abs));
  if (!scale) return null;
  const [x, y] = point; const h = homography.map(row => row.map(value => value / scale));
  const divisor = h[2][0] * x + h[2][1] * y + h[2][2];
  if (!Number.isFinite(divisor) || Math.abs(divisor) < 1e-9) return null;
  const result: Point = [(h[0][0] * x + h[0][1] * y + h[0][2]) / divisor, (h[1][0] * x + h[1][1] * y + h[1][2]) / divisor];
  return result.every(Number.isFinite) ? result : null;
}
export function ruleGroundPoints(points: Point[], space: string, source?: CitySource): Point[] {
  if (space === 'site-metres') return points;
  if (!source) return [];
  const projected = points.map(([x, y]) => projectPoint([x * source.width, y * source.height], source.imageToGroundHomography));
  return projected.some(point => point === null) ? [] : projected as Point[];
}
/** Invert the calibrated plane so map-authored measurement regions also appear on video. */
export function ruleImagePoints(rule: CityRule, source: CitySource): Point[] {
  if (rule.geometry.space === 'image-normalized') return rule.geometry.points;
  if (rule.calibrationRevision && rule.calibrationRevision !== source.calibrationRevision) return [];
  const matrix = rule.classes.length === 1 ? source.classImageToGroundHomographies?.[rule.classes[0]] ?? source.imageToGroundHomography : source.imageToGroundHomography;
  if (!matrix || matrix.length !== 3 || matrix.some(row => row.length !== 3) || !matrix.flat().every(Number.isFinite) || source.width <= 0 || source.height <= 0) return [];
  const scale = Math.max(...matrix.flat().map(Math.abs)); if (!scale) return [];
  const [[a,b,c],[d,e,f],[g,h,i]] = matrix.map(row => row.map(value => value / scale));
  const determinant = a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);
  if (!Number.isFinite(determinant) || determinant === 0) return [];
  const inverse = [[e*i-f*h,c*h-b*i,b*f-c*e],[f*g-d*i,a*i-c*g,c*d-a*f],[d*h-e*g,b*g-a*h,a*e-b*d]];
  const points = rule.geometry.points.map(point => projectPoint(point, inverse));
  return points.some(point => !point) ? [] : (points as Point[]).map(([x,y]) => [x / source.width,y / source.height]);
}
export function formatMediaTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60).toString().padStart(2, '0')}:${(safe % 60).toString().padStart(2, '0')}`;
}
/** Event evidence begins at the candidate onset; activation can follow a dwell threshold. */
export function eventMediaTime(event: CityEvent, at: 'started' | 'triggered' = 'triggered'): number | null {
  const explicit = at === 'started' ? event.evidence?.startMediaTimeSeconds : event.evidence?.triggerMediaTimeSeconds;
  if (event.mode !== 'live' && typeof explicit === 'number' && Number.isFinite(explicit)) return Math.max(0, explicit);
  const onset = event.evidence?.startMediaTimeSeconds ?? event.evidence?.mediaTimeSeconds;
  if (event.mode === 'live' || typeof onset !== 'number' || !Number.isFinite(onset)) return null;
  if (at === 'started') return Math.max(0, onset);
  const delay = (Date.parse(event.triggeredAt) - Date.parse(event.startedAt)) / 1000;
  return Number.isFinite(delay) ? Math.max(0, onset + Math.max(0, delay)) : null;
}
export function formatMediaTimeTenths(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10));
  return `${formatMediaTime(tenths / 10)}.${tenths % 10}`;
}
export function trackLabel(track: CityTrack, localOnly = false): string {
  const identifier = localOnly ? track.localTrackId : track.globalTrackId ?? track.localTrackId;
  const short = identifier.length > 8 ? `…${identifier.slice(-4)}` : identifier;
  return `${track.class} ${!localOnly && track.globalTrackId ? 'G' : ''}${short}`;
}
export function compactTrackLabel(track: CityTrack, localOnly = false): string {
  const prefixes: Record<string, string> = { person: 'P', car: 'V', bus: 'B', truck: 'T', bicycle: 'C', motorcycle: 'M', 'two-wheeler': 'W' };
  const identifier = localOnly ? track.localTrackId : track.globalTrackId ?? track.localTrackId;
  const short = identifier.length > 8 ? `…${identifier.slice(-4)}` : identifier;
  return `${prefixes[track.class.toLowerCase()] ?? track.class[0]?.toUpperCase() ?? '?'}${short}`;
}
export function objectName(kind: string): string {
  const names: Record<string, string> = { person: 'Person', car: 'Car', bus: 'Bus', truck: 'Truck', bicycle: 'Bicycle', motorcycle: 'Motorcycle', 'two-wheeler': 'Two-wheeler', vehicle: 'Vehicle' };
  return names[kind.toLowerCase()] ?? (kind.charAt(0).toUpperCase() + kind.slice(1));
}
export function cameraLabels(tracks: CityTrack[], width: number, height: number, selectedId: string | null, localOnly = false, display: 'identity' | 'class' = 'identity'): Map<string, { x: number; y: number; width: number; height: number; text: string }> {
  const labels = new Map<string, { x: number; y: number; width: number; height: number; text: string }>();
  const ordered = [...tracks].sort((a, b) => Number(b.id === selectedId) - Number(a.id === selectedId) || b.bboxPx[2] * b.bboxPx[3] - a.bboxPx[2] * a.bboxPx[3]);
  for (const track of ordered) {
    // Keep all selectable boxes; limit only redundant class labels in busy scenes.
    if (display === 'class' && labels.size >= 8) break;
    const text = display === 'class' ? objectName(track.class) : compactTrackLabel(track, localOnly); const labelWidth = Math.max(width / 20, text.length * width / 67 + width / 70); const labelHeight = width / 30;
    const [x, y, , h] = track.bboxPx;
    const left = Math.min(width - labelWidth, Math.max(0, x));
    for (const top of [Math.max(0, y - labelHeight), Math.min(height - labelHeight, y + h)]) {
      const label = { x: left, y: top, width: labelWidth, height: labelHeight, text };
      const overlaps = Array.from(labels.values()).some(other => label.x < other.x + other.width + 4 && label.x + label.width + 4 > other.x && label.y < other.y + other.height + 4 && label.y + label.height + 4 > other.y);
      if (!overlaps) { labels.set(track.id, label); break; }
    }
  }
  return labels;
}
export function isAligned(source: CitySource | undefined, mediaTime: number): boolean {
  return source?.clockAligned !== false && typeof source?.mediaTimeSeconds === 'number' && Math.abs(source.mediaTimeSeconds - mediaTime) <= 0.16;
}
export function safeMediaUrl(value?: string): string | undefined {
  // Media is served only by the same-origin registered-source gateway.
  return value?.startsWith('/api/vision/city/media/') && !value.includes('..') ? value : undefined;
}
export function eventTitle(event: CityEvent): string {
  const titles: Record<string, string> = {
    'occupancy-threshold': 'Area occupancy limit reached',
    'line-crossing': 'Line crossing detected', 'area-entry': 'Object entered the area',
    dwell: 'Object remained in the area', 'stopped-in-zone': 'Vehicle stopped in the area',
    queue: 'Vehicle queue detected', 'wrong-way': 'Movement against the allowed direction',
  };
  return titles[event.kind] ?? event.message;
}
export function eventMeasure(key: string, value: string | number | null): [string, string] {
  if (key === 'durationMs' && typeof value === 'number') return ['Observed duration', `${(value / 1000).toFixed(1)} s`];
  if (key === 'speedMps' && typeof value === 'number') return ['Estimated speed', `${value.toFixed(1)} m/s`];
  const labels: Record<string, string> = { count: 'Objects when triggered', threshold: 'Rule limit', direction: 'Direction' };
  return [labels[key] ?? key.replace(/([A-Z])/g, ' $1'), value === null ? '—' : String(value)];
}
