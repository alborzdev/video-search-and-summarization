// SPDX-License-Identifier: MIT
import { cameraCategory, cameraLabelLayout } from '../cameraLabelLayout';
import type { CityTrack } from '../types';

const track = (id: string, bboxPx: CityTrack['bboxPx'] = [100, 100, 100, 100], className = 'car'): CityTrack => ({
  id, sourceId: 'camera', sessionId: 'session', localTrackId: id, class: className,
  bboxPx, positionM: null, confidence: .9, stale: false, trail: [],
});
const layout = (tracks: CityTrack[], timeMs = 0, previous?: ReturnType<typeof cameraLabelLayout>, selected: string | null = null, scope = 'session') =>
  cameraLabelLayout(tracks, 1000, 1000, selected, scope, timeMs, previous);

it('uses a truthful stable vehicle category without revising detector data', () => {
  const car = track('SUV'); const truck = { ...car, class: 'truck' };
  const first = layout([car]); const next = layout([truck], 33, first);
  expect(first.labels.get('SUV')?.text).toBe('Vehicle');
  expect(next.labels.get('SUV')).toEqual(first.labels.get('SUV'));
  expect(car.class).toBe('car'); expect(truck.class).toBe('truck');
  expect(cameraCategory('person')).toBe('Person');
  expect(cameraCategory('bicycle')).toBe('Bicycle');
});

it('holds label position through minor box jitter while leaving the actual box untouched', () => {
  const first = layout([track('a')]);
  const current = track('a', [103, 102, 99, 101]);
  const next = layout([current], 33, first);
  expect(next.labels.get('a')).toEqual(first.labels.get('a'));
  expect(current.bboxPx).toEqual([103, 102, 99, 101]);
  const moving = layout([track('a', [120, 110, 100, 100])], 66, next);
  expect(moving.labels.get('a')?.x).toBe(120);
});

it('does not let near-equal box areas constantly replace the eight admitted labels', () => {
  const tracks = Array.from({ length: 9 }, (_, i) => track(String(i), [20 + (i % 4) * 240, 100 + Math.floor(i / 4) * 250, 100, 100 - i]));
  const first = layout(tracks);
  const changed = tracks.map(t => ({ ...t, bboxPx: [t.bboxPx[0], t.bboxPx[1], 100, t.id === '8' ? 120 : 100] as CityTrack['bboxPx'] })).reverse();
  const next = layout(changed, 33, first);
  expect(Array.from(next.labels.keys())).toEqual(Array.from(first.labels.keys()));
  expect(layout(changed, 66, next, '8').labels.has('8')).toBe(true);
});

it('uses size hysteresis for distant objects and always admits the selected object', () => {
  const far = track('a', [100, 100, 30, 30], 'person');
  expect(layout([far]).labels.size).toBe(0);
  expect(layout([far], 0, undefined, 'a').labels.get('a')?.text).toBe('Person');
  const near = layout([track('a', [100, 100, 50, 70])]);
  const jitter = layout([track('a', [100, 100, 50, 60])], 33, near);
  expect(jitter.labels.has('a')).toBe(true);
  const distant = layout([track('a', [100, 100, 50, 40])], 66, jitter);
  expect(distant.labels.size).toBe(0);
});

it('keeps the chosen side and requires room to remain clear before a crowded label returns', () => {
  const a = track('a', [100, 300, 100, 100]);
  const b = track('b', [300, 300, 100, 100]);
  const first = layout([a, b]);
  const crowded = layout([a, { ...b, bboxPx: [150, 300, 100, 100] }], 33, first, 'a');
  expect(crowded.labels.has('b')).toBe(false);
  const clearing = layout([a, b], 66, crowded);
  expect(clearing.labels.has('b')).toBe(false);
  const clear = layout([a, b], 266, clearing);
  expect(clear.labels.get('b')?.y).toBe(first.labels.get('b')?.y);
});

it('never carries visible labels over a missing observation, stale/predicted track, or clock gate', () => {
  const first = layout([track('a')]);
  expect(layout([], 33, first).labels.size).toBe(0);
  expect(layout([{ ...track('a'), stale: true }], 33, first).labels.size).toBe(0);
  expect(layout([{ ...track('a'), observedThisFrame: false }], 33, first).labels.size).toBe(0);
});

it('resets placement after session/configuration changes, backward seeks, long gaps and geometry changes', () => {
  const first = layout([track('a')], 1000);
  const shifted = track('a', [103, 100, 100, 100]);
  expect(layout([shifted], 1033, first, null, 'new-scene').labels.get('a')?.x).toBe(103);
  expect(layout([shifted], 999, first).labels.get('a')?.x).toBe(103);
  expect(layout([shifted], 1500, first).labels.get('a')?.x).toBe(103);
  expect(cameraLabelLayout([shifted], 1200, 1000, null, 'session', 1033, first).labels.get('a')?.x).toBe(103);
  expect(first.labels.get('a')?.x).toBe(100);
});

it('keeps edge labels inside the image and ignores invalid or offscreen detections', () => {
  const edge = layout([track('edge', [980, 5, 20, 100])]);
  const label = edge.labels.get('edge')!;
  expect(label.x + label.width).toBeLessThanOrEqual(1000);
  expect(label.y).toBeGreaterThanOrEqual(0);
  expect(layout([track('bad', [NaN, 0, 100, 100]), track('outside', [1010, 0, 100, 100])]).labels.size).toBe(0);
});
