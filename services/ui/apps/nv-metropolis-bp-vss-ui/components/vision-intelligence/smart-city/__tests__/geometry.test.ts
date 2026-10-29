// SPDX-License-Identifier: MIT
import { cameraLabels, eventMediaTime, formatMediaTimeTenths, isAligned, normalizedPoint, projectPoint, ruleGroundPoints, ruleImagePoints, safeMediaUrl, formatMediaTime } from '../geometry';
import type { CityEvent, CityRule, CityTrack } from '../types';
describe('city observation geometry', () => {
  it('draws ground regions through their matching calibrated camera plane', () => {
    const rule = { geometry: { space: 'site-metres', points: [[15, 10], [20, 5]] }, classes: ['person'], calibrationRevision: 'r1' } as CityRule;
    const matrix = [[.1, 0, 5], [0, -.1, 30], [0, 0, 1]];
    const source = { id: 'a', name: 'A', width: 1000, height: 500, calibrationRevision: 'r1', classImageToGroundHomographies: { person: matrix } };
    const points = ruleImagePoints(rule, source);
    expect(points[0][0]).toBeCloseTo(.1); expect(points[0][1]).toBeCloseTo(.4);
    expect(points[1][0]).toBeCloseTo(.15); expect(points[1][1]).toBeCloseTo(.5);
    expect(ruleImagePoints(rule, { ...source, calibrationRevision: 'r2' })).toEqual([]);
    expect(ruleImagePoints(rule, { ...source, classImageToGroundHomographies: {} })).toEqual([]);
    expect(ruleImagePoints(rule, { ...source, classImageToGroundHomographies: { person: [[1, 0, 0], [0, 0, 0], [0, 0, 0]] } })).toEqual([]);
  });
  it('uses the video content rectangle, rejecting clicks in letterboxing', () => {
    const rect = { left: 100, top: 100, width: 800, height: 600 };
    expect(normalizedPoint(500, 400, rect, 1920, 1080)).toEqual([.5, .5]);
    expect(normalizedPoint(500, 120, rect, 1920, 1080)).toBeNull();
    expect(normalizedPoint(100, 175, rect, 1920, 1080)).toEqual([0, 0]);
  });
  it('maps editing clicks through the same cover crop as edge-to-edge video and overlays', () => {
    const rect={left:100,top:100,width:800,height:600};
    expect(normalizedPoint(500,400,rect,1920,1080,'cover')).toEqual([.5,.5]);
    const edge=normalizedPoint(100,100,rect,1920,1080,'cover')!;
    expect(edge[0]).toBeCloseTo(.125);expect(edge[1]).toBeCloseTo(0);
  });
  it('projects to site metres only with a valid calibration', () => {
    const projected = projectPoint([100, 200], [[.1, 0, 5], [0, -.1, 30], [0, 0, 1]]);
    expect(projected?.[0]).toBeCloseTo(15); expect(projected?.[1]).toBeCloseTo(10);
    expect(projectPoint([100, 200])).toBeNull();
    expect(projectPoint([1, 2], [[1, 0, 0], [0, 1, 0], [0, 0, 0]])).toBeNull();
    expect(ruleGroundPoints([[.5, .5]], 'image-normalized', { id: 'a', name: 'A', width: 100, height: 100 })).toEqual([]);
    expect(ruleGroundPoints([[4, 5]], 'site-metres')).toEqual([[4, 5]]);
  });
  it('keeps projected rule geometry invariant to homography scale', () => {
    const matrix = [[.1, 0, 5], [0, -.1, 30], [0, 0, 1]];
    for (const scale of [1e-15, 1e15, -1e-12]) {
      const point = projectPoint([100, 200], matrix.map(row => row.map(value => value * scale)));
      expect(point?.[0]).toBeCloseTo(15); expect(point?.[1]).toBeCloseTo(10);
    }
  });
  it('shows boxes only when their observation matches the displayed media time', () => {
    const source = { id: 'a', name: 'A', width: 100, height: 100, mediaTimeSeconds: 4 };
    expect(isAligned(source, 4.12)).toBe(true);
    expect(isAligned(source, 4.3)).toBe(false);
    expect(isAligned({ ...source, clockAligned: false }, 4)).toBe(false);
    expect(isAligned({ ...source, mediaTimeSeconds: undefined }, 4)).toBe(false);
  });
  it('accepts only same-origin registered-source media', () => {
    expect(safeMediaUrl('/api/vision/city/media/camera-1')).toBe('/api/vision/city/media/camera-1');
    expect(safeMediaUrl('https://example.com/traffic.mp4')).toBeUndefined();
    expect(safeMediaUrl('/api/vision/city/media/../../secrets')).toBeUndefined();
  });
  it('formats source media time without inventing wall-clock time', () => {
    expect(formatMediaTime(64.8)).toBe('01:04');
    expect(formatMediaTime(-2)).toBe('00:00');
  });
  it('keeps dense camera labels in-frame and gives the selected object priority', () => {
    const track: CityTrack = { id: 'a', sourceId: 'cam', sessionId: 's', localTrackId: '18446744073709551614', class: 'person', bboxPx: [1900, 100, 20, 30], positionM: null, confidence: .9, stale: false, trail: [] };
    const labels = cameraLabels([track, { ...track, id: 'b' }, { ...track, id: 'c' }], 1920, 1080, 'b');
    expect(Array.from(labels.keys())[0]).toBe('b'); expect(labels.size).toBe(2);
    for (const label of labels.values()) { expect(label.x).toBeGreaterThanOrEqual(0); expect(label.x + label.width).toBeLessThanOrEqual(1920); expect(label.text).toBe('P…1614'); }
  });
  it('distinguishes candidate onset from activation and rounds fractional seconds once', () => {
    const event = { mode: 'recorded-inference', startedAt: '2025-01-01T00:00:00.200Z', triggeredAt: '2025-01-01T00:00:00.700Z', evidence: { status: 'source-recording', mediaTimeSeconds: .19999999999999996 } } as CityEvent;
    expect(eventMediaTime(event, 'started')).toBeCloseTo(.2);
    expect(eventMediaTime(event)).toBeCloseTo(.7);
    expect(formatMediaTimeTenths(eventMediaTime(event, 'started')!)).toBe('00:00.2');
    expect(formatMediaTimeTenths(59.999)).toBe('01:00.0');
    expect(eventMediaTime({ ...event, mode: 'live' })).toBeNull();
  });

});
