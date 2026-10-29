// SPDX-License-Identifier: MIT
import { displaySnapshot } from '../alignedSnapshot';
import type { CitySite, CitySnapshot } from '../types';
const time = Date.parse('2026-10-22T00:00:00Z');
const source = { id: 'a', name: 'A', width: 1000, height: 1000, browserClockVerified: true };
const site: CitySite = { id: 'city', name: 'City', revision: 1, mode: 'live', sources: [source], map: { bounds: [0, 0, 10, 10], roads: [], buildings: [] } };
const latest: CitySnapshot = { siteId: 'city', mode: 'live', timestamp: new Date(time).toISOString(), sequence: 9, sources: [source], tracks: [{ id: 'future', sourceId: 'a', sessionId: 's', localTrackId: '1', class: 'person', bboxPx: [0, 0, 10, 20], positionM: [9, 9], confidence: 1, stale: false, trail: [] }], zones: [], rules: [], events: [], metrics: [] };
const frame: CitySnapshot = { ...latest, sequence: 4, sources: [{ ...source, timestampBasis: 'source-rtcp', clockAligned: true, lastSourceTimeNs: '1700000000000000000' }], requestedSourceTimeNs: '1700000000000000000', tracks: [{ ...latest.tracks[0], id: 'displayed-frame', positionM: [1, 2] }] };
describe('camera-aligned map observations', () => {
  it('uses the displayed camera frame rather than future processor positions after clock verification', () => {
    const result = displaySnapshot(site, latest, { a: frame }, time + 100);
    expect(result?.tracks.map(track => track.id)).toEqual(['displayed-frame']);
    expect(result?.videoClockAligned).toBe(true);
  });
  it('does not present old or arrival-clock positions as aligned map positions', () => {
    expect(displaySnapshot(site, latest, { a: frame }, time + 2000)?.tracks).toEqual([]);
    expect(displaySnapshot(site, latest, { a: { ...frame, sources: [{ ...frame.sources[0], timestampBasis: 'arrival-pts-unsynchronized' }] } }, time)?.tracks).toEqual([]);
  });
  it('retains explicitly unverified source observations without making an aligned-clock claim', () => {
    expect(displaySnapshot({ ...site, sources: [{ ...source, browserClockVerified: false }] }, latest, { a: frame }, time)).toBe(latest);
  });
  it('uses exact presented analyzed frames without claiming physical clock verification', () => {
    const exact: CitySnapshot = { ...frame, siteRevision: 1, sources: [{ ...frame.sources[0], sessionId: 'epoch', sequence: '4' }], presentedPreview: { sourceId: 'a', sessionId: 'epoch', sequence: '4', sourceTimeNs: frame.requestedSourceTimeNs!, presentedAtMs: time } };
    const latestWithSession = { ...latest, sources: [{ ...source, sessionId: 'epoch' }] };
    const result = displaySnapshot({ ...site, sources: [{ ...source, browserClockVerified: false }] }, latestWithSession, { a: exact }, time + 100);
    expect(result?.tracks[0].id).toBe('displayed-frame'); expect(result?.videoFrameMatched).toBe(true); expect(result?.videoClockAligned).toBe(false);
    expect(displaySnapshot({ ...site, revision: 2 }, latestWithSession, { a: exact }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot({ ...site, sources: [{ ...source, calibrationRevision: 'new-calibration' }] }, latestWithSession, { a: exact }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot({ ...site, sources: [{ ...source, classImageToGroundHomographies: { person: [[1,0,0],[0,1,0],[0,0,1]] } }] }, latestWithSession, { a: exact }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot({ ...site, sources: [{ ...source, width: 2000 }] }, latestWithSession, { a: exact }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot(site, latest, { a: exact }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot(site, latest, { a: exact }, time + 2100)?.tracks).toEqual([]);
    expect(displaySnapshot(site, latest, { a: { ...exact, presentedPreview: { ...exact.presentedPreview!, sequence: 'wrong' } } }, time + 100)?.tracks).toEqual([]);
    expect(displaySnapshot(site, latest, { a: { ...exact, presentedPreview: undefined, processedPreviewUnavailable: true } }, time + 100)?.tracks).toEqual([]);
  });
  it('does not accept retained raw observations from an unverified camera beside a processed preview', () => {
    const other = { ...source, id: 'b', browserClockVerified: false };
    const exact: CitySnapshot = { ...frame, siteRevision: 1, sources: [{ ...frame.sources[0], sessionId: 'epoch', sequence: '4' }], presentedPreview: { sourceId: 'a', sessionId: 'epoch', sequence: '4', sourceTimeNs: frame.requestedSourceTimeNs!, presentedAtMs: time } };
    const raw: CitySnapshot = { ...frame, sources: [{ ...frame.sources[0], id: 'b' }], tracks: [{ ...frame.tracks[0], id: 'unverified-raw', sourceId: 'b' }] };
    const result = displaySnapshot({ ...site, sources: [source, other] }, { ...latest, sources: [{ ...source, sessionId: 'epoch' }, other] }, { a: exact, b: raw }, time + 100);
    expect(result?.tracks.map(track => track.id)).toEqual(['displayed-frame']); expect(result?.videoFrameMatched).toBe(false); expect(result?.videoClockAligned).toBe(false);
  });
  it('rejects a previous analytics epoch even when the RTSP session and capture clock stay continuous', () => {
    const oldScope = { kind: 'scenario', epoch: 'old', suppressed: false };
    const newScope = { ...oldScope, epoch: 'new' };
    const exact: CitySnapshot = { ...frame, siteRevision: 1, analyticsScope: oldScope,
      sources: [{ ...frame.sources[0], sessionId: 'same-session', sequence: '4', analyticsScope: oldScope, trackingEpoch: 'same-tracker' }],
      presentedPreview: { sourceId: 'a', sessionId: 'same-session', sequence: '4', sourceTimeNs: frame.requestedSourceTimeNs!, presentedAtMs: time } };
    const current = { ...latest, analyticsScope: newScope, sources: [{ ...source, sessionId: 'same-session', analyticsScope: newScope, trackingEpoch: 'same-tracker' }] };
    expect(displaySnapshot(site, current, { a: exact }, time + 100)?.tracks).toEqual([]);
    const fresh = { ...exact, analyticsScope: newScope, sources: [{ ...exact.sources[0], analyticsScope: newScope }] };
    expect(displaySnapshot(site, current, { a: fresh }, time + 100)?.tracks[0].id).toBe('displayed-frame');
    expect(displaySnapshot(site, { ...current, sources: [{ ...current.sources[0], trackingEpoch: 'new-tracker' }] }, { a: fresh }, time + 100)?.tracks).toEqual([]);
  });
});
