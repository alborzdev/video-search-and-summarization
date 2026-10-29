// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { DEMO_MAX_CAPTURE_SKEW_NS, deriveMapObjects } from '../mapObjects';
import { CityMap } from '../CityMap';
import type { CitySite, CitySnapshot } from '../types';
const time = '1792770000123456789';
const sources = ['a','b'].map(id => ({ id, name: `Camera ${id.toUpperCase()}`, width: 100, height: 100, calibrationRevision: `cal-${id}`, imageToGroundHomography: [[1,0,0],[0,1,0],[0,0,1]], sessionId: `session-${id}`, status: 'live', timestampBasis: 'source-rtcp', lastSourceTimeNs: time }));
const site: CitySite = { id: 'city', revision: 2, name: 'City', mode: 'live', sources, map: { bounds: [0,0,10,10], roads: [], buildings: [] } };
function snapshot(): CitySnapshot {
  return { siteId: 'city', siteRevision: 2, mode: 'live', sequence: '1', timestamp: new Date().toISOString(), sources, videoFrameMatched: true,
    association: { mode: 'camera-local', globalFusionEnabled: false, mapFusion: { mode: 'mv3dt-demo', enabled: true, experimental: true, qualified: false, positionBasis: 'camera-local-homography' } },
    tracks: sources.map((source, index) => ({ id: `${source.id}:${source.sessionId}:7`, sourceId: source.id, sessionId: source.sessionId, localTrackId: '7', class: 'person', bboxPx: [1,1,3,4], positionM: [2+index*.5,3], confidence: .9, stale: false, observedThisFrame: true, sourceTimeNs: time, trail: [{ positionM: [1,3], sourceTimeNs: '1' }],
      mapAssociation: { method: 'mv3dt-demo', globalTrackId: 'shared-target-7', targetId: '7', fusionEpoch: 'epoch', calibrationRevision: source.calibrationRevision, visibility: .8, sourceClockBasis: 'source-rtcp' } })),
    rules: [], zones: [], metrics: [], events: [] };
}
function nativeSnapshot(): CitySnapshot {
  const value = JSON.parse(JSON.stringify(snapshot())) as CitySnapshot;
  value.sources.forEach(source => {
    source.timestampBasis = 'source-native-sei'; source.sourceClockMode = 'source-native-sei'; source.rawSourcePtsNs = '123400000'; source.modelRevision = 'pinned-model';
    source.browserClockVerified = false;
    source.sourceClockEvidence = { schemaVersion: 'city.source-native-sei.v1', method: 'isaac-native-sei-wall-capture', correlation: 'exact-au-pts', captureTimeNs: source.lastSourceTimeNs!, auPtsNs: source.rawSourcePtsNs, frameCounter: '42' };
  });
  value.tracks.forEach(track => { track.mapAssociation!.sourceClockBasis = 'source-native-sei'; track.modelRevision = 'pinned-model'; });
  return value;
}
it('joins exact native handoff clocks only with source proof and the current model', () => {
  expect(deriveMapObjects(site, nativeSnapshot()).filter(object => object.shared)).toHaveLength(1);
});
it('joins car/truck labels only under the same explicit native association policy', () => {
  const value = nativeSnapshot();
  value.association!.mapFusion!.positionBasis = 'native-mv3dt-world-foot';
  value.tracks.forEach((track, index) => {
    track.class = index ? 'truck' : 'car';
    Object.assign(track.mapAssociation!, { positionM: [2 + index*.5, 3], positionBasis: 'native-mv3dt-world-foot', classPolicy: 'car-truck-family-v1' });
  });
  expect(deriveMapObjects(site, value).filter(object => object.shared)).toHaveLength(1);
  expect(value.tracks.map(track => track.class)).toEqual(['car', 'truck']);
  delete value.tracks[1].mapAssociation!.classPolicy;
  expect(deriveMapObjects(site, value)).toHaveLength(2);
  value.tracks[1].mapAssociation!.classPolicy = 'car-truck-family-v1';
  value.tracks[1].class = 'bus'; expect(deriveMapObjects(site, value)).toHaveLength(2);
  value.tracks[1].class = 'person'; expect(deriveMapObjects(site, value)).toHaveLength(2);
});
it.each(['mixed clocks', 'missing proof', 'wrong capture', 'wrong pts', 'wrong model', 'different source models', 'unapproved mode'])('refuses native map joins for %s', reason => {
  const value = nativeSnapshot();
  if (reason === 'mixed clocks') { value.sources[1].timestampBasis = 'source-rtcp'; value.tracks[1].mapAssociation!.sourceClockBasis = 'source-rtcp'; }
  if (reason === 'missing proof') delete value.sources[1].sourceClockEvidence;
  if (reason === 'wrong capture') value.sources[1].sourceClockEvidence!.captureTimeNs = '1';
  if (reason === 'wrong pts') value.sources[1].sourceClockEvidence!.auPtsNs = '1';
  if (reason === 'wrong model') value.tracks[1].modelRevision = 'newer-model';
  if (reason === 'different source models') { value.tracks[1].modelRevision = 'newer-model'; value.sources[1].modelRevision = 'newer-model'; }
  if (reason === 'unapproved mode') value.sources[1].sourceClockMode = 'source-rtcp';
  expect(deriveMapObjects(site, value).filter(object => object.shared)).toHaveLength(0);
});
it('keeps the native join window at exactly150ms and rejects one nanosecond beyond it', () => {
  const value = nativeSnapshot(); const source = value.sources[1];
  source.lastSourceTimeNs = (BigInt(time) + BigInt(DEMO_MAX_CAPTURE_SKEW_NS)).toString();
  source.sourceClockEvidence!.captureTimeNs = source.lastSourceTimeNs; value.tracks[1].sourceTimeNs = source.lastSourceTimeNs;
  expect(deriveMapObjects(site, value)).toHaveLength(1);
  source.lastSourceTimeNs = (BigInt(source.lastSourceTimeNs) + BigInt(1)).toString();
  source.sourceClockEvidence!.captureTimeNs = source.lastSourceTimeNs; value.tracks[1].sourceTimeNs = source.lastSourceTimeNs;
  expect(deriveMapObjects(site, value)).toHaveLength(2);
});
it('joins validated exact-frame people across camera-specific calibrations with one unaveraged anchor', () => {
  const input = snapshot(); const before = JSON.stringify(input); const objects = deriveMapObjects(site, input);
  expect(objects).toHaveLength(1); expect(objects[0].shared).toBe(true); expect(objects[0].track.positionM).toEqual([2,3]);
  expect(objects[0].memberTrackIds).toEqual(input.tracks.map(track => track.id)); expect(objects[0].track.trail).toEqual([]);
  expect(JSON.stringify(input)).toBe(before); expect(input.tracks).toHaveLength(2);
});
it.each([
  ['disabled', (s: CitySnapshot) => { s.association!.mapFusion!.enabled = false; }],
  ['latest-only snapshot', (s: CitySnapshot) => { s.videoFrameMatched = false; }],
  ['different site revision', (s: CitySnapshot) => { s.siteRevision = 3; }],
  ['class mismatch', (s: CitySnapshot) => { s.tracks[1].class = 'car'; }],
  ['unknown method', (s: CitySnapshot) => { (s.tracks[1].mapAssociation as any).method = 'unknown'; }],
  ['epoch mismatch', (s: CitySnapshot) => { s.tracks[1].mapAssociation!.fusionEpoch = 'old'; }],
  ['target correction', (s: CitySnapshot) => { s.tracks[1].mapAssociation!.targetId = '99'; }],
  ['current calibration mismatch', (s: CitySnapshot) => { s.tracks[1].mapAssociation!.calibrationRevision = 'old'; }],
  ['low visibility', (s: CitySnapshot) => { s.tracks[1].mapAssociation!.visibility = .249; }],
  ['unverified source clock', (s: CitySnapshot) => { (s.tracks[1].mapAssociation as any).sourceClockBasis = 'arrival-pts-unsynchronized'; }],
  ['retired source session', (s: CitySnapshot) => { s.tracks[1].sessionId = 'old'; }],
  ['position disagreement', (s: CitySnapshot) => { s.tracks[1].positionM = [3.001,3]; }],
  ['same camera twice', (s: CitySnapshot) => { s.tracks[1] = { ...s.tracks[0], id: 'second-same-camera' }; }],
])('keeps observations separate for %s', (_name, change) => {
  const input = snapshot(); (change as (s: CitySnapshot) => void)(input); expect(deriveMapObjects(site, input).filter(object => object.shared)).toHaveLength(0);
});
it.each([[149, 1], [150, 1], [151, 2]])('uses the explicit demo display window at %ims', (milliseconds, count) => {
  const input = snapshot(); const shifted = (BigInt(time)+BigInt(milliseconds * 1_000_000)).toString();
  input.sources = [sources[0], { ...sources[1], lastSourceTimeNs: shifted }]; input.tracks[1].sourceTimeNs = shifted;
  expect(deriveMapObjects(site, input)).toHaveLength(count);
});
it('enforces the exact150ms demo boundary without losing nanosecond precision', () => {
  const input = snapshot(); const shifted = (BigInt(time)+BigInt(DEMO_MAX_CAPTURE_SKEW_NS)).toString();
  input.sources = [sources[0], { ...sources[1], lastSourceTimeNs: shifted }]; input.tracks[1].sourceTimeNs = shifted;
  expect(deriveMapObjects(site, input)).toHaveLength(1);
  input.sources[1].lastSourceTimeNs = (BigInt(shifted)+BigInt(1)).toString(); input.tracks[1].sourceTimeNs = input.sources[1].lastSourceTimeNs;
  expect(deriveMapObjects(site, input)).toHaveLength(2);
});
it('uses current positions with demo-only entry and split distance hysteresis', () => {
  const outside = snapshot(); outside.tracks[1].positionM = [3.01, 3];
  expect(deriveMapObjects(site, outside)).toHaveLength(2);
  const previous = deriveMapObjects(site, snapshot());
  const current = snapshot(); current.tracks[0].positionM = [4, 3]; current.tracks[1].positionM = [5.08, 3];
  const held = deriveMapObjects(site, current, previous);
  expect(held).toHaveLength(1); expect(held[0].shared).toBe(true); expect(held[0].track.positionM).toEqual([4, 3]);
  current.tracks[1].positionM = [5.5, 3]; expect(deriveMapObjects(site, current, held)).toHaveLength(1);
  current.tracks[1].positionM = [5.51, 3]; const split = deriveMapObjects(site, current, held);
  expect(split).toHaveLength(2);
  current.tracks[1].positionM = [5.08, 3]; expect(deriveMapObjects(site, current, split)).toHaveLength(2);
});
it.each(['member', 'session', 'epoch', 'time', 'visibility', 'frame', 'calibration'])('does not preserve a shared display through changed %s evidence', change => {
  const previous = deriveMapObjects(site, snapshot()); const current = snapshot(); current.tracks[1].positionM = [3.08, 3];
  if (change === 'member') { current.tracks[1].id = 'new-local-id'; current.tracks[1].localTrackId = 'new'; }
  if (change === 'session') { current.tracks[1].sessionId = 'replacement'; current.sources = [sources[0], { ...sources[1], sessionId: 'replacement' }]; }
  if (change === 'epoch') current.tracks.forEach(track => { track.mapAssociation!.fusionEpoch = 'replacement'; });
  if (change === 'time') { const t = (BigInt(time)+BigInt(151_000_000)).toString(); current.tracks[1].sourceTimeNs = t; current.sources = [sources[0], { ...sources[1], lastSourceTimeNs: t }]; }
  if (change === 'visibility') current.tracks[1].mapAssociation!.visibility = .24;
  if (change === 'frame') current.videoFrameMatched = false;
  if (change === 'calibration') current.tracks[1].mapAssociation!.calibrationRevision = 'changed';
  expect(deriveMapObjects(site, current, previous).filter(object => object.shared)).toHaveLength(0);
});
it('does not let predicted or stale members keep a shared marker alive', () => {
  const input = snapshot(); input.tracks[1].observedThisFrame = false;
  expect(deriveMapObjects(site, input)).toHaveLength(1); expect(deriveMapObjects(site, input)[0].shared).toBe(false);
  input.tracks[0].stale = true; expect(deriveMapObjects(site, input)).toEqual([]);
});
it('renders one accessible glyph for a shared person and selects its original representative', () => {
  const input = snapshot(); const select = jest.fn(); const { container } = render(<CityMap site={site} snapshot={input} rules={[]} selectedTrack={input.tracks[1].id} onSelect={select} />);
  expect(container.querySelectorAll('[data-track]')).toHaveLength(1);
  expect(screen.getByText('Display association · 1 linked object · unmatched camera views can show an object twice')).toBeInTheDocument(); expect(screen.getByText('1 map object')).toBeInTheDocument();
  const marker = screen.getByRole('button', { name: 'Person · 2 camera views · Camera A + Camera B on map' });
  expect(marker).toHaveAttribute('aria-pressed', 'true'); fireEvent.click(marker); expect(select).toHaveBeenCalledWith(input.tracks[0].id);
  expect(marker.querySelector('polyline')).toBeNull();
});

it.each(['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler'])('joins native MV3DT %s IDs using native world feet', className => {
  const value = snapshot();
  value.tracks.forEach((track, index) => {
    track.class = className;
    track.positionM = [index * 8, 0]; // camera rectangle anchors disagree
    track.mapAssociation!.positionBasis = 'native-mv3dt-world-foot';
    track.mapAssociation!.positionM = [3 + index * .2, 4];
  });
  const original = JSON.stringify(value);
  const objects = deriveMapObjects(site, value);
  expect(objects).toHaveLength(1);
  expect(objects[0].shared).toBe(true);
  expect(objects[0].track.positionM).toEqual([3, 4]);
  expect(JSON.stringify(value)).toBe(original);
});

it('rejects equal native IDs when classes or position authorities disagree', () => {
  const value = snapshot();
  value.tracks.forEach(track => {
    track.class = 'car';
    track.mapAssociation!.positionBasis = 'native-mv3dt-world-foot';
    track.mapAssociation!.positionM = [3, 4];
  });
  value.tracks[1].class = 'truck';
  expect(deriveMapObjects(site, value).every(object => !object.shared)).toBe(true);
  value.tracks[1].class = 'car';
  delete value.tracks[1].mapAssociation!.positionBasis;
  expect(deriveMapObjects(site, value).every(object => !object.shared)).toBe(true);
});

it('keeps one native SDK identity when camera positions disagree and reports the spread', () => {
  const value = nativeWorldSnapshot();
  value.tracks[1].mapAssociation!.positionM = [6, 4];
  const before = JSON.stringify(value);
  const objects = deriveMapObjects(site, value);
  expect(objects).toHaveLength(1);
  expect(objects[0].shared).toBe(true);
  expect(objects[0].nativePositionSpreadM).toBeGreaterThan(1);
  expect(objects[0].track.positionM).toEqual(value.tracks[0].mapAssociation!.positionM);
  expect(JSON.stringify(value)).toBe(before);
  render(<CityMap site={site} snapshot={value} rules={[]} selectedTrack={null} onSelect={jest.fn()} />);
  expect(screen.getByRole('status')).toHaveTextContent('1 shared ID has uncertain position');
  expect(document.querySelectorAll('[data-position-disagreement]')).toHaveLength(1);
});

it('never consolidates different SDK identities even at the same native position', () => {
  const value = nativeWorldSnapshot();
  value.tracks[1].mapAssociation!.globalTrackId = 'different-id';
  value.tracks[1].mapAssociation!.targetId = '8';
  value.tracks[1].mapAssociation!.positionM = value.tracks[0].mapAssociation!.positionM;
  expect(deriveMapObjects(site, value)).toHaveLength(2);
});

function nativeWorldSnapshot(): CitySnapshot {
  const value = nativeSnapshot();
  value.association!.mapFusion!.positionBasis = 'native-mv3dt-world-foot';
  value.tracks.forEach((track, index) => {
    track.class = 'car';
    track.mapAssociation!.positionBasis = 'native-mv3dt-world-foot';
    track.mapAssociation!.positionM = [3 + index * .2, 4];
  });
  return value;
}

it.each(['absent metadata', 'missing position', 'low visibility', 'invalid position'])('does not replace a native ground position with a rectangle anchor after %s', reason => {
  const value = nativeWorldSnapshot();
  if (reason === 'absent metadata') value.tracks[1].mapAssociation = null;
  if (reason === 'missing position') delete value.tracks[1].mapAssociation!.positionM;
  if (reason === 'low visibility') value.tracks[1].mapAssociation!.visibility = .249;
  if (reason === 'invalid position') value.tracks[1].mapAssociation!.positionM = [NaN, 4];
  const before = JSON.stringify(value);
  const objects = deriveMapObjects(site, value);
  expect(objects).toHaveLength(1); expect(objects[0].track.positionM).toEqual([3, 4]);
  expect(objects[0].shared).toBe(false); expect(value.tracks).toHaveLength(2);
  expect(JSON.stringify(value)).toBe(before);
});

it('uses valid native feet when the camera rectangle cannot be projected', () => {
  const value = nativeWorldSnapshot(); value.tracks.forEach(track => { track.positionM = null; });
  expect(deriveMapObjects(site, value)).toHaveLength(1);
  expect(deriveMapObjects(site, value)[0].track.positionM).toEqual([3, 4]);
});

it('labels a shared vehicle correctly and discloses withheld positions without removing camera tracks', () => {
  const value = nativeWorldSnapshot(); const { rerender } = render(<CityMap site={site} snapshot={value} rules={[]} selectedTrack={null} onSelect={jest.fn()} />);
  expect(screen.getByRole('button', { name: 'Car · 2 camera views · Camera A + Camera B on map' })).toBeInTheDocument();
  value.tracks[1].mapAssociation = null;
  rerender(<CityMap site={site} snapshot={value} rules={[]} selectedTrack={null} onSelect={jest.fn()} />);
  expect(screen.getByRole('status')).toHaveTextContent('1 uncertain map position hidden · camera detections remain visible');
  expect(value.tracks).toHaveLength(2);
});
