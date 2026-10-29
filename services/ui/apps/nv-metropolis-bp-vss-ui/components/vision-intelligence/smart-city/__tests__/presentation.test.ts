// SPDX-License-Identifier: MIT
import { cameraColor, eventEvidencePending, eventStateDescription, eventStateLabel, groupRuleGeometry, recentEvents, ruleCaption, ruleEvidenceReasons, ruleMeasure, sourceName } from '../presentation';
import type { CityEvent, CityMetric, CityRule } from '../types';

const rule: CityRule = { id: 'watch', name: 'Loading bay', kind: 'occupancy-threshold', sourceId: 'southwest', classes: ['car'], enabled: true, revision: 1, geometry: { space: 'image-normalized', points: [[0, 0], [1, 0], [1, 1]] }, conditions: {} };
const metric: CityMetric = { ruleId: 'watch', occupancy: 7, count: 7, activeEventCount: 0, status: 'normal' };
function event(id: string, sourceId: string, triggeredAt: string): CityEvent {
  return { id, sourceId, triggeredAt, startedAt: triggeredAt, ruleId: 'watch', ruleName: id, kind: 'line-crossing', sessionId: 'session', trackIds: [], state: 'cleared', message: id, metrics: {}, mode: 'live' };
}

describe('Smart City presentation', () => {
  it('does not turn absent or stale observations into a current count', () => {
    expect(ruleMeasure({ ...rule, kind: 'line-crossing' })).toBe('Waiting for observations');
    expect(ruleMeasure({ ...rule, kind: 'line-crossing' }, metric)).toBe('Waiting for observations');
    expect(ruleMeasure(rule, { ...metric, status: 'unknown' })).toBe('Not enough evidence');
    expect(ruleMeasure({ ...rule, kind: 'line-crossing' }, { ...metric, status: 'unknown', totalCrossings: 19 })).toBe('Not enough evidence');
    expect(ruleMeasure({ ...rule, enabled: false }, { ...metric, status: 'active' })).toBe('Disabled');
  });

  it('explains only reported unknown-state evidence causes, without inventing an offline camera', () => {
    expect(ruleEvidenceReasons({ ...metric, status: 'unknown', evidenceReasons: ['speed-unavailable', 'observation-gap', 'speed-unavailable'] })).toEqual(['Speed is not available yet.', 'A gap interrupted object tracking.']);
    expect(ruleEvidenceReasons({ ...metric, status: 'normal', evidenceReasons: ['source-stale'] })).toEqual([]);
    expect(ruleEvidenceReasons({ ...metric, status: 'unknown' })).toEqual([]);
    expect(ruleEvidenceReasons(undefined)).toEqual([]);
  });

  it('ignores unsupported and inherited evidence-reason names', () => {
    expect(ruleEvidenceReasons({ ...metric, status: 'unknown', evidenceReasons: ['new-server-code', 'constructor', '__proto__', 'lost-track-membership'] })).toEqual(['An object was lost before its exit was confirmed.']);
  });

  it('labels bounded stopped evidence loss separately from confirmed active alerts', () => {
    const pending = { ...event('stop', 'a', '2026-10-23T15:00:00Z'), kind: 'stopped-in-zone', state: 'active' as const, stopEvidenceStatus: 'pending' as const };
    expect(eventEvidencePending(pending)).toBe(true);
    expect(eventStateLabel(pending)).toBe('Checking evidence');
    expect(eventStateDescription(pending)).toContain('Unconfirmed time is excluded.');
    expect(eventStateLabel({ ...pending, stopEvidenceStatus: 'clearing' })).toBe('Checking clearance');
    expect(eventStateDescription({ ...pending, stopEvidenceStatus: 'clearing' })).toContain('movement or an exit');
    expect(ruleMeasure({ ...rule, kind: 'stopped-in-zone' }, { ...metric, status: 'unknown', evidenceReasons: ['stop-observation-pending'] })).toBe('Checking evidence');
    expect(ruleEvidenceReasons({ ...metric, status: 'unknown', evidenceReasons: ['stop-observation-pending'] })).toEqual(['Checking a brief detection gap. Unconfirmed time is excluded.']);
    for (const other of [{ ...pending, state: 'unknown' as const }, { ...pending, state: 'cleared' as const }, { ...pending, kind: 'dwell' }, { ...pending, stopEvidenceStatus: undefined }]) {
      expect(eventEvidencePending(other)).toBe(false);
      expect(eventStateLabel(other)).toBe(other.state);
    }
  });

  it.each(['stopped-in-zone', 'dwell', 'wrong-way', 'area-entry'])('does not present area occupancy as a %s condition count', kind => {
    expect(ruleMeasure({ ...rule, kind }, metric)).toBe('No active alerts');
    expect(ruleMeasure({ ...rule, kind }, { ...metric, activeEventCount: 1, status: 'active' })).toBe('1 active alert');
    expect(ruleMeasure({ ...rule, kind }, { ...metric, activeEventCount: 2, status: 'active' })).toBe('2 active alerts');
  });

  it('uses the qualifying queue count and preserves a measured zero', () => {
    expect(ruleMeasure({ ...rule, kind: 'queue' }, { ...metric, count: 2 })).toBe('2 slow vehicles');
    expect(ruleMeasure({ ...rule, kind: 'queue' }, { ...metric, count: 0 })).toBe('0 slow vehicles');
    expect(ruleMeasure(rule, { ...metric, occupancy: 0 })).toBe('0 in area');
    expect(ruleMeasure({ ...rule, kind: 'line-crossing' }, { ...metric, totalCrossings: 0 })).toBe('0 crossings');
    expect(ruleMeasure({ ...rule, kind: 'line-crossing' }, { ...metric, totalCrossings: 1 })).toBe('1 crossing');
  });

  it('orders interleaved cameras by event time without mutating either source list', () => {
    const oldest = event('oldest', 'southwest', '2026-10-23T15:00:00Z');
    const newest = event('newest', 'northeast', '2026-10-23T15:02:00Z');
    const middle = event('middle', 'southwest', '2026-10-23T15:01:00Z');
    const input = Object.freeze([oldest, middle, newest]) as unknown as CityEvent[];
    expect(recentEvents(input).map(item => item.id)).toEqual(['newest', 'middle', 'oldest']);
    expect(input.map(item => item.id)).toEqual(['oldest', 'middle', 'newest']);
  });

  it('keeps equal-time ordering deterministic and puts invalid dates last', () => {
    const time = '2026-10-23T15:00:00Z';
    expect(recentEvents([event('invalid', 'a', ''), event('b', 'a', time), event('a', 'b', time)]).map(item => item.id)).toEqual(['a', 'b', 'invalid']);
  });

  it('uses readable known camera names without changing custom source names', () => {
    expect(sourceName({ name: 'isaac-intersection-southwest' })).toBe('Southwest corner');
    expect(sourceName({ name: 'isaac-intersection-northeast' })).toBe('Northeast corner');
    for (const name of ['Main Street', 'constructor', 'toString', '__proto__']) expect(sourceName({ name })).toBe(name);
  });

  it('gives different cameras distinct repeated keys and preserves custom rule titles', () => {
    expect(cameraColor(0)).not.toBe(cameraColor(1));
    expect(cameraColor(4)).toBe(cameraColor(0));
    expect(ruleCaption({ ...rule, kind: 'line-crossing' })).toBe('Crossing line');
    expect(ruleCaption({ ...rule, kind: 'custom' })).toBe('Loading bay');
    expect(ruleCaption({ ...rule, kind: 'constructor' })).toBe('Loading bay');
  });

  it('groups shared geometry once while retaining every rule and distinct condition captions', () => {
    const entry = { ...rule, id: 'entry', name: 'Crosswalk person present', kind: 'area-entry' };
    const stopped = { ...rule, id: 'stopped', name: 'Crosswalk vehicle stop', kind: 'stopped-in-zone' };
    const secondEntry = { ...entry, id: 'entry-bus', name: 'Crosswalk bus present', classes: ['bus'] };
    const input = Object.freeze([entry, stopped, secondEntry]) as unknown as CityRule[];
    const groups = groupRuleGeometry(input);
    expect(groups).toHaveLength(1);
    expect(groups[0].caption).toBe('Entry · Stopped vehicle');
    expect(groups[0].rules).toEqual([entry, stopped, secondEntry]);
    expect(input).toEqual([entry, stopped, secondEntry]);
  });

  it('keeps separate camera, coordinate-space, and directed-line geometry independent', () => {
    const line: CityRule = { ...rule, kind: 'line-crossing', geometry: { space: 'image-normalized', points: [[.2, .2], [.8, .2]], direction: [0, -1] } };
    const opposite = { ...line, id: 'opposite', geometry: { ...line.geometry, direction: [0, 1] as [number, number] } };
    const otherCamera = { ...line, id: 'other-camera', sourceId: 'northeast' };
    const groundSpace = { ...line, id: 'ground', geometry: { ...line.geometry, space: 'site-metres' as const } };
    expect(groupRuleGeometry([line, opposite, otherCamera, groundSpace])).toHaveLength(4);
  });
});
