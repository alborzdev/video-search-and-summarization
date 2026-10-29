// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { CityCamera } from '../CityCamera';
import type { CityRule, CitySnapshot, CitySource } from '../types';
import { useProcessedPreview } from '../useProcessedPreview';
jest.mock('../useProcessedPreview', () => ({ useProcessedPreview: jest.fn(() => null) }));
let mockTrackedVideoProps: any;
jest.mock('next/dynamic', () => () => {
  const React = require('react');
  return function LivePreview(props: any) {
    if (props.onPresented) mockTrackedVideoProps = props;
    React.useEffect(() => { props.onStatus('playing'); props.onFrame?.({ mediaTimeSeconds: 2, presentedAtMs: 10, width: 1000, height: 1000, sourceTimeUnixMs: 1700000000000, rtpTimestamp: 42, clockBasis: 'webrtc-capture-time' }); }, [props.onFrame, props.onStatus]);
    return <div>{props.onPresented ? 'Tracked VSS preview adapter' : 'Actual VSS preview adapter'}</div>;
  };
});
const source: CitySource = { id: 'a', name: 'Camera A', width: 1000, height: 1000, browserClockVerified: true };
const snapshot: CitySnapshot = { siteId: 'city', mode: 'live', timestamp: '2026-10-22T00:00:00Z', sequence: 1, sources: [{ ...source, timestampBasis: 'source-rtcp', clockAligned: true, lastSourceTimeNs: '1700000000000000000' }], tracks: [{ id: 'a:session:7', sourceId: 'a', sessionId: 'session', localTrackId: '7', class: 'person', bboxPx: [100, 100, 100, 200], positionM: null, confidence: .9, stale: false, trail: [] }], zones: [], rules: [], events: [], metrics: [] };
const common = { previewContext: { siteId: 'city', siteRevision: 1, mode: 'live' as const, sourceId: 'a', width: 1000, height: 1000, geometryKey: '[null,null,null]', configurationKey: 'configuration-1' }, mode: 'live' as const, index: 0, rules: [], selectedTrack: null, onSelect: jest.fn(), playing: false, seekTime: 0, seekToken: 0, onTime: jest.fn(), onDuration: jest.fn(), editing: false, draft: [], draftKind: 'occupancy-threshold', onPoint: jest.fn(), onEdit: jest.fn(), onSourceTime: jest.fn() };
describe('city live overlay clock gate', () => {
  beforeEach(() => { jest.clearAllMocks(); (useProcessedPreview as jest.Mock).mockReturnValue(null); });
  it('keeps distant boxes selectable without permanent text clutter, revealing the selected label', () => {
    const distant = { ...snapshot, tracks: [{ ...snapshot.tracks[0], bboxPx: [100, 100, 20, 30] as [number, number, number, number] }] };
    const { container, rerender } = render(<CityCamera {...common} source={source} snapshot={distant} />);
    const box = screen.getByRole('button', { name: 'Person · Camera A' });
    expect(box).toHaveAttribute('height', '30');
    expect(container.querySelector('[data-camera-label]')).toBeNull();
    fireEvent.click(box); expect(common.onSelect).toHaveBeenCalledWith(distant.tracks[0].id);
    rerender(<CityCamera {...common} source={source} snapshot={distant} selectedTrack={distant.tracks[0].id} />);
    expect(container.querySelector('[data-camera-label] text')).toHaveTextContent('Person');
    expect(screen.getByRole('button', { name: 'Person · Camera A' })).toHaveAttribute('height', '30');
  });
  it('stabilizes text through minor jitter and SUV class changes while rendering exact current boxes', () => {
    const car = { ...snapshot, tracks: [{ ...snapshot.tracks[0], class: 'car' }] };
    const { container, rerender } = render(<CityCamera {...common} source={source} snapshot={car} />);
    const label = container.querySelector('[data-camera-label] rect')!;
    const initialX = label.getAttribute('x');
    const truck = { ...car, tracks: [{ ...car.tracks[0], class: 'truck', bboxPx: [103, 102, 99, 201] as [number, number, number, number] }] };
    rerender(<CityCamera {...common} source={source} snapshot={truck} />);
    expect(container.querySelector('[data-camera-label] text')).toHaveTextContent('Vehicle');
    expect(container.querySelector('[data-camera-label] rect')).toHaveAttribute('x', initialX);
    const exact = screen.getByRole('button', { name: 'Truck · Camera A' });
    expect(exact).toHaveAttribute('x', '103'); expect(exact).toHaveAttribute('y', '102');
    expect(exact).toHaveAttribute('width', '99'); expect(exact).toHaveAttribute('height', '201');
    expect(exact.querySelector('title')).toHaveTextContent('Truck · 90% confidence');
    rerender(<CityCamera {...common} source={source} snapshot={{ ...truck, tracks: [] }} />);
    expect(container.querySelector('[data-track-id]')).toBeNull();
    expect(container.querySelector('[data-camera-label]')).toBeNull();
  });
  it('does not carry a label anchor across an analytics epoch change', () => {
    const { container, rerender } = render(<CityCamera {...common} source={source} snapshot={snapshot} />);
    const scope = { kind: 'scenario', epoch: 'new' };
    const latest = { ...source, analyticsScope: scope };
    const next = { ...snapshot, analyticsScope: scope, sources: [{ ...snapshot.sources[0], analyticsScope: scope }], tracks: [{ ...snapshot.tracks[0], bboxPx: [103, 100, 100, 200] as [number, number, number, number] }] };
    rerender(<CityCamera {...common} source={source} latestSource={latest} snapshot={next} />);
    expect(container.querySelector('[data-camera-label] rect')).toHaveAttribute('x', '103');
  });
  it('shows the same ground area as a guide in the other calibrated camera without creating measurements', () => {
    const target:CitySource={...source,id:'b',name:'Camera B',calibrationRevision:'b-current',imageToGroundHomography:[[1,0,0],[0,1,0],[0,0,1]],groundCoverageM:[[0,0],[1000,0],[1000,1000],[0,1000]]};
    const {container}=render(<CityCamera {...common} mode="fixture-replay" source={target} snapshot={null} areaHighlight={{id:'original',name:'East crossing',sourceId:'a',points:[[100,100],[800,100],[800,800]]}}/>);
    const guide=screen.getByLabelText('East crossing · calibrated area guide');expect(guide).toHaveAttribute('data-projected-rule-id','original');
    expect(guide.querySelector('polygon')).toHaveAttribute('points','100,100 800,100 800,800');
    expect(container.querySelector('svg.cameraOverlay')).toHaveAttribute('preserveAspectRatio','xMidYMid slice');
    expect(screen.queryByText(/in area|active alerts/)).not.toBeInTheDocument();
  });
  it('can preserve the full frame for operator editing and analyst views with matching overlay geometry', () => {
    const {container}=render(<CityCamera {...common} mode="fixture-replay" source={source} snapshot={null} fillFrame={false}/>);
    expect(container.querySelector('section')).toHaveAttribute('data-camera-fit','contain');
    expect(container.querySelector('svg.cameraOverlay')).toHaveAttribute('preserveAspectRatio','xMidYMid meet');
  });
  it('does not decode the hidden camera as a raw fallback when a different workspace panel is selected', () => {
    render(<CityCamera {...common} source={source} snapshot={snapshot} previewEnabled={false} />);
    expect(useProcessedPreview).toHaveBeenCalledWith('a', false, undefined, common.previewContext, undefined);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
  });
  it('forwards the health-qualified native preview ceiling to the bounded reader', () => {
    render(<CityCamera {...common} source={source} snapshot={snapshot} previewFpsLimit={30} />);
    expect(useProcessedPreview).toHaveBeenCalledWith('a', true, undefined, common.previewContext, 30);
  });
  it('retains the established transport through missing health and capability without restarting the reader', () => {
    const native = { ...source, browserClockVerified: false };
    const latest = { ...native, sessionId: 'session', processedPreview: { available: true, status: 'ready', transport: 'webrtc' as const } };
    const { rerender } = render(<CityCamera {...common} source={native} latestSource={latest} snapshot={snapshot} previewTransport="webrtc" />);
    const reader = screen.getByText('Tracked VSS preview adapter');
    rerender(<CityCamera {...common} source={native} latestSource={{ ...latest, processedPreview: { available: false, status: 'waiting' } }} snapshot={snapshot} />);
    expect(screen.getByText('Tracked VSS preview adapter')).toBe(reader);
    expect(useProcessedPreview).toHaveBeenLastCalledWith('a', false, 'session', common.previewContext, undefined);
    rerender(<CityCamera {...common} source={native} latestSource={{ ...latest, sessionId: 'replacement', processedPreview: { available: false, status: 'waiting' } }} snapshot={snapshot} />);
    expect(screen.queryByText('Tracked VSS preview adapter')).not.toBeInTheDocument();
    expect(useProcessedPreview).toHaveBeenLastCalledWith('a', true, 'replacement', common.previewContext, undefined);
  });
  it('honors an explicit transport replacement and disables analysis while retaining only the capability', () => {
    const native = { ...source, browserClockVerified: false };
    const latest = { ...native, sessionId: 'session', processedPreview: { available: true, status: 'ready', transport: 'webrtc' as const } };
    const { rerender } = render(<CityCamera {...common} source={native} latestSource={latest} snapshot={snapshot} previewTransport="webrtc" />);
    rerender(<CityCamera {...common} source={native} latestSource={latest} snapshot={snapshot} previewTransport="jpeg" />);
    expect(screen.queryByText('Tracked VSS preview adapter')).not.toBeInTheDocument();
    expect(useProcessedPreview).toHaveBeenLastCalledWith('a', true, 'session', common.previewContext, undefined);
    rerender(<CityCamera {...common} source={native} latestSource={latest} snapshot={snapshot} previewTransport="webrtc" analysisEnabled={false} />);
    expect(screen.queryByText('Tracked VSS preview adapter')).not.toBeInTheDocument();
    expect(useProcessedPreview).toHaveBeenLastCalledWith('a', false, 'session', common.previewContext, undefined);
    expect(screen.getByText('Detections are off')).toBeInTheDocument();
  });
  it('rejects a retained analyzed frame immediately when its source session changes', () => {
    const native = { ...source, browserClockVerified: false };
    const latest = { ...native, sessionId: 'session', processedPreview: { available: true, status: 'ready', transport: 'webrtc' as const } };
    const dto: any = { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', image: { width: 1000, height: 1000 }, snapshot, provenance: { kind: 'native-webrtc-exact-frame' } };
    const presented = jest.fn();
    const { rerender } = render(<CityCamera {...common} source={native} latestSource={latest} snapshot={snapshot} onProcessedFrame={presented} />);
    act(() => mockTrackedVideoProps.onPresented(dto));
    expect(screen.getByText('Frame matched · analyzed preview · 1 tracked')).toBeInTheDocument();
    rerender(<CityCamera {...common} source={native} latestSource={{ ...latest, sessionId: 'replacement' }} snapshot={snapshot} onProcessedFrame={presented} />);
    expect(screen.queryByText('Frame matched · analyzed preview · 1 tracked')).not.toBeInTheDocument();
    expect(presented).toHaveBeenLastCalledWith('a', null, 'configuration-1');
  });
  it('stops both analyzed reads and raw fallback when hidden, then reconnects on return', async () => {
    const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const { unmount } = render(<CityCamera {...common} source={source} snapshot={snapshot} />);
    try {
      expect(await screen.findByText('Actual VSS preview adapter')).toBeInTheDocument();
      act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')); });
      expect(useProcessedPreview).toHaveBeenLastCalledWith('a', false, undefined, common.previewContext, undefined);
      expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Person · Camera A' })).not.toBeInTheDocument();
      expect(screen.getByText('Camera analysis continues on the device.')).toBeInTheDocument();
      act(() => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')); });
      expect(await screen.findByText('Actual VSS preview adapter')).toBeInTheDocument();
      expect(useProcessedPreview).toHaveBeenLastCalledWith('a', true, undefined, common.previewContext, undefined);
    } finally { unmount(); visibility.mockRestore(); }
  });
  it('displays live boxes only with verified capture-time correspondence', async () => {
    render(<CityCamera {...common} source={source} snapshot={snapshot} />);
    expect(await screen.findByRole('button', { name: 'Person · Camera A' })).toBeInTheDocument();
    expect(common.onSourceTime).toHaveBeenCalledWith('a', 1700000000000);
    const camera = screen.getByRole('region', { name: 'Camera A camera' });
    expect(camera).toHaveAttribute('data-live-capture-time-ms', '1700000000000');
    expect(camera).toHaveAttribute('data-live-rtp-timestamp', '42');
    expect(camera).toHaveAttribute('data-live-clock-gate', 'aligned');
    expect(camera).toHaveAttribute('data-live-source-skew-ms', '0');
  });
  it('highlights a shared-map member while preserving its local camera label', async () => {
    const track = { ...snapshot.tracks[0], globalTrackId: 'shared-999' };
    render(<CityCamera {...common} source={source} snapshot={{ ...snapshot, tracks: [track] }} selectedTrack="other-camera-track" selectedTrackIds={[track.id, 'other-camera-track']} />);
    const box = await screen.findByRole('button', { name: 'Person · Camera A' }); expect(box).toHaveAttribute('aria-pressed', 'true');
    expect(box.parentElement).toHaveClass('selectedTrack'); expect(screen.getByText('Person')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /999/ })).not.toBeInTheDocument();
  });
  it('opens unverified video only on request, without starting automatic WebRTC during a detector outage', async () => {
    render(<CityCamera {...common} source={{ ...source, browserClockVerified: false }} snapshot={snapshot} />);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Play video only' }));
    expect(await screen.findByText('Live video · overlay clock is not yet verified')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Person · Camera A' })).not.toBeInTheDocument();
    expect(common.onSourceTime).not.toHaveBeenCalled();
  });
  it('selects objects by Space but leaves rule drawing in control while editing', async () => {
    const { rerender } = render(<CityCamera {...common} source={source} snapshot={snapshot} />);
    fireEvent.keyDown(await screen.findByRole('button', { name: 'Person · Camera A' }), { key: ' ' });
    expect(common.onSelect).toHaveBeenCalledWith('a:session:7');
    common.onSelect.mockClear();
    rerender(<CityCamera {...common} source={source} snapshot={snapshot} editing />);
    fireEvent.keyDown(screen.getByRole('button', { name: 'Person · Camera A' }), { key: 'Enter' });
    expect(common.onSelect).not.toHaveBeenCalled();
  });
  it('releases requested video when exact frames recover and requires a new click after another outage', () => {
    const native = { ...source, browserClockVerified: false };
    const draw = jest.fn(); jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw } as any);
    const { rerender } = render(<CityCamera {...common} source={native} snapshot={snapshot} />);
    fireEvent.click(screen.getByRole('button', { name: 'Play video only' }));
    expect(screen.getByText('Actual VSS preview adapter')).toBeInTheDocument();
    (useProcessedPreview as jest.Mock).mockReturnValue({ bitmap: {}, frame: { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', image: { width: 1000, height: 1000 }, snapshot, provenance: { kind: 'native-post-inference-exact-frame' } } });
    rerender(<CityCamera {...common} source={native} snapshot={snapshot} seekToken={1} />);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument(); expect(draw).toHaveBeenCalledTimes(1);
    (useProcessedPreview as jest.Mock).mockReturnValue(null);
    rerender(<CityCamera {...common} source={native} snapshot={snapshot} seekToken={2} />);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Play video only' })).toBeInTheDocument();
  });
  it('does not treat decoder arrival time as camera capture time', async () => {
    render(<CityCamera {...common} source={source} snapshot={{ ...snapshot, sources: [{ ...snapshot.sources[0], timestampBasis: 'arrival-pts-unsynchronized' }] }} />);
    expect(await screen.findByText('Waiting for source capture timestamps')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Person · Camera A' })).not.toBeInTheDocument();
  });
  it('keeps an old recorded source on its direct file path when an incompatible live snapshot arrives', () => {
    const pause = jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    const { container, unmount } = render(<CityCamera {...common} mode="recorded-inference" source={{ ...source, mediaUrl: '/api/vision/city/media/a' }} snapshot={snapshot} />);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
    expect(container.querySelector('video')).toHaveAttribute('src', '/api/vision/city/media/a');
    unmount(); pause.mockRestore();
  });

  it('warns about a delayed source clock even when ingestion is fresh and preview is playing', async () => {
    render(<CityCamera {...common} source={{ ...source, browserClockVerified: false }} snapshot={{ ...snapshot, sources: [{ ...snapshot.sources[0], ingestAgeSeconds: .02, sourceClockAgeSeconds: 100.2, sourceClockProgressRatio: .7, sourceClockPrecision: 'unverified', sourceClockStatus: 'delayed-or-unsynchronized' }] }} />);
    expect(await screen.findByText('Video is delayed or its clock needs checking · reported source clock age 100.2 s')).toBeInTheDocument();
    expect(screen.queryByText('Live video · overlay clock is not yet verified')).not.toBeInTheDocument();
    expect(screen.queryByText(/latency/i)).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Camera A camera' })).toHaveAttribute('data-ingest-age-seconds', '0.02');
  });
  it('does not invent a zero age when the reported source clock age is unavailable, including while editing', async () => {
    render(<CityCamera {...common} editing source={source} snapshot={{ ...snapshot, sources: [{ ...snapshot.sources[0], sourceClockAgeSeconds: null, sourceClockStatus: 'delayed-or-unsynchronized' }] }} />);
    expect(await screen.findByText('Video is delayed or its clock needs checking · Click to place rule points')).toBeInTheDocument();
    expect(screen.queryByText(/reported source clock age/)).not.toBeInTheDocument();
  });

  it('renders matching analyzed pixels and boxes together, unmounting raw WebRTC', () => {
    const draw = jest.fn(); jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw } as any);
    const oldRule: any = { id: 'old', name: 'Frame rule', kind: 'occupancy-threshold', sourceId: 'a', classes: ['person'], enabled: true, revision: 1, conditions: {}, geometry: { space: 'image-normalized', points: [[.1, .1], [.8, .1], [.8, .8]] } };
    const latestRule = { ...oldRule, id: 'new', name: 'Latest editing rule', revision: 2 };
    const exact = { ...snapshot, rules: [oldRule], tracks: [{ ...snapshot.tracks[0], localTrackId: 'exact', id: 'exact' }, { ...snapshot.tracks[0], localTrackId: 'predicted', id: 'predicted', stale: false, observedThisFrame: false }] };
    const dto: any = { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500 }, snapshot: exact, provenance: { kind: 'native-post-inference-exact-frame' } };
    const bitmap = { width: 500, height: 500 }; (useProcessedPreview as jest.Mock).mockReturnValue({ frame: dto, bitmap });
    const presented = jest.fn(); const { rerender } = render(<CityCamera {...common} rules={[latestRule]} source={{ ...source, browserClockVerified: false }} snapshot={snapshot} focusedRuleId="old" onProcessedFrame={presented} />);
    expect(draw).toHaveBeenCalledWith(bitmap, 0, 0, 1000, 1000); expect(screen.getByRole('button', { name: 'Person · Camera A' }).parentElement).toHaveAttribute('data-track-id', 'exact');
    expect(screen.getByRole('button', { name: 'Person · Camera A' }).parentElement).not.toHaveAttribute('data-track-id', 'a:session:7'); expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument();
    expect(screen.getByText('Frame matched · analyzed preview · 1 tracked')).toBeInTheDocument(); expect(presented).toHaveBeenCalledWith('a', dto, 'configuration-1');
    expect(screen.getByText('Frame rule', { selector: 'text' })).toBeInTheDocument(); expect(screen.queryByText('Latest editing rule')).not.toBeInTheDocument(); expect(screen.getAllByRole('button', { name: 'Person · Camera A' })).toHaveLength(1);
    rerender(<CityCamera {...common} rules={[latestRule]} editing showAllRules source={{ ...source, browserClockVerified: false }} snapshot={snapshot} focusedRuleId="old" onProcessedFrame={presented} />);
    expect(screen.getByText('Latest editing rule', { selector: 'text' })).toBeInTheDocument(); expect(screen.queryByText('Frame rule')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Camera A camera' })).toHaveAttribute('data-live-clock-gate', 'exact-processed-frame');
    (useProcessedPreview as jest.Mock).mockReturnValue(null);
    rerender(<CityCamera {...common} source={{ ...source, browserClockVerified: false }} snapshot={snapshot} focusedRuleId="old" onProcessedFrame={presented} />);
    expect(screen.queryByText('Actual VSS preview adapter')).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Play video only' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Person · Camera A' })).not.toBeInTheDocument(); expect(presented).toHaveBeenLastCalledWith('a', null, 'configuration-1');
  });

  it('identifies TrafficCamNet only on a matched analyzed frame and labels its coarse two-wheeler class', () => {
    jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as any);
    const exact = { ...snapshot, tracks: [{ ...snapshot.tracks[0], class: 'two-wheeler' }] };
    const dto: any = { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', modelRevision: 'trafficcamnet@sha256:abc', image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500 }, snapshot: exact, provenance: { kind: 'native-post-inference-exact-frame' } };
    (useProcessedPreview as jest.Mock).mockReturnValue({ frame: dto, bitmap: { width: 500, height: 500 } });
    const { rerender } = render(<CityCamera {...common} source={source} snapshot={snapshot} />);
    expect(screen.getByRole('button', { name: 'Two-wheeler · Camera A' })).toBeInTheDocument();
    expect(screen.getByText(/TrafficCamNet: people, cars, two-wheelers/)).toBeInTheDocument();
    (useProcessedPreview as jest.Mock).mockReturnValue(null);
    rerender(<CityCamera {...common} source={source} snapshot={{ ...snapshot }} />);
    expect(screen.queryByText(/TrafficCamNet:/)).not.toBeInTheDocument();
  });

  it('filters the exact analyzed frame rules to the active scenario without substituting newer geometry', () => {
    jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as any);
    const frameRule: CityRule = { id: 'chosen', name: 'Frame area', kind: 'occupancy-threshold', sourceId: 'a', classes: ['person'], enabled: true, revision: 1, conditions: {}, geometry: { space: 'image-normalized', points: [[.1, .1], [.8, .1], [.8, .8]] } };
    const other = { ...frameRule, id: 'other', name: 'Other area', geometry: { ...frameRule.geometry, points: [[.2, .2], [.6, .2], [.6, .6]] as CityRule['geometry']['points'] } };
    const dto: any = { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500 }, snapshot: { ...snapshot, rules: [frameRule, other] }, provenance: { kind: 'native-post-inference-exact-frame' } };
    (useProcessedPreview as jest.Mock).mockReturnValue({ frame: dto, bitmap: { width: 500, height: 500 } });
    const { container } = render(<CityCamera {...common} rules={[{ ...frameRule, name: 'Newer area' }, other]} source={{ ...source, browserClockVerified: false }} snapshot={snapshot} scenarioRuleIds={['chosen']} />);
    expect(screen.getByText('Frame area', { selector: 'text' })).toBeInTheDocument();
    expect(screen.queryByText('Other area', { selector: 'text' })).not.toBeInTheDocument();
    expect(screen.queryByText('Newer area', { selector: 'text' })).not.toBeInTheDocument();
    expect(container.querySelector('[data-rule-id="chosen"] polygon')).toHaveAttribute('points', '100,100 800,100 800,800');
  });

  it('uses one shared polygon and preserves its active highlight regardless of rule order', () => {
    const entry: CityRule = { id: 'entry', name: 'Crosswalk person present', kind: 'area-entry', sourceId: 'a', classes: ['person'], enabled: true, revision: 1, conditions: {}, geometry: { space: 'image-normalized', points: [[.1, .1], [.8, .1], [.8, .8]] } };
    const stopped = { ...entry, id: 'stop', name: 'Crosswalk vehicle stopped', kind: 'stopped-in-zone', classes: ['car'] };
    const exact: CitySnapshot = { ...snapshot, mode: 'fixture-replay', zones: [
      { ...entry, active: true, occupancy: 1 },
      { ...stopped, active: false, occupancy: 0 },
    ] };
    const { rerender } = render(<CityCamera {...common} mode="fixture-replay" source={source} snapshot={exact} rules={[entry, stopped]} showAllRules />);
    const overlay = screen.getByLabelText('Camera A detections and rules');
    expect(overlay.querySelectorAll('polygon')).toHaveLength(1);
    expect(overlay.querySelector('polygon')?.parentElement).toHaveClass('activeZone');
    expect(screen.getByText('Crosswalk person present')).toBeInTheDocument();
    expect(overlay.querySelector('text title')).toHaveTextContent('Crosswalk person present · Crosswalk vehicle stopped');
    rerender(<CityCamera {...common} mode="fixture-replay" source={source} snapshot={exact} rules={[stopped, entry]} showAllRules />);
    expect(overlay.querySelectorAll('polygon')).toHaveLength(1);
    expect(overlay.querySelector('polygon')?.parentElement).toHaveClass('activeZone');
    rerender(<CityCamera {...common} mode="fixture-replay" source={source} snapshot={{ ...exact, zones: exact.zones.map(zone => ({ ...zone, active: false })) }} rules={[stopped, entry]} showAllRules />);
    expect(overlay.querySelector('polygon')?.parentElement).toHaveClass('zone');
    expect(overlay.querySelector('polygon')?.parentElement).not.toHaveClass('activeZone');
  });

});

it('hides obsolete scope pixels without restarting the preview reader or replacing its canvas', () => {
  const draw = jest.fn();
  const canvasContext = jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw } as any);
  const oldScope = { epoch: 'old', kind: 'scenario', suppressed: false };
  const newScope = { ...oldScope, epoch: 'new' };
  const exact = { ...snapshot, analyticsScope: oldScope, sources: [{ ...snapshot.sources[0], analyticsScope: oldScope, trackingEpoch: 'same-tracker' }] };
  const dto: any = { sourceId: 'a', sessionId: 'session', sequence: '7', sourceTimeNs: '1700000000000000000', image: { width: 1000, height: 1000, jpegWidth: 500, jpegHeight: 500 }, snapshot: exact, provenance: { kind: 'native-post-inference-exact-frame' } };
  (useProcessedPreview as jest.Mock).mockReturnValue({ frame: dto, bitmap: {}, configurationKey: 'configuration-1', receivedAtMs: Date.now() });
  const latest = { ...source, sessionId: 'session', analyticsScope: oldScope, trackingEpoch: 'same-tracker' };
  const { rerender } = render(<CityCamera {...common} source={source} snapshot={snapshot} latestSource={latest} />);
  const canvas = screen.getByLabelText('Frame matched analyzed camera preview');
  expect(canvas).toHaveStyle({ visibility: 'visible' });
  const requests = (useProcessedPreview as jest.Mock).mock.calls.slice(-1)[0];
  rerender(<CityCamera {...common} source={source} snapshot={snapshot} latestSource={{ ...latest, analyticsScope: newScope }} />);
  expect(screen.getByLabelText('Frame matched analyzed camera preview')).toBe(canvas);
  expect(canvas).toHaveStyle({ visibility: 'hidden' });
  expect(screen.queryByText('Actual VSS preview adapter')).toBeNull();
  expect((useProcessedPreview as jest.Mock).mock.calls.slice(-1)[0]).toEqual(requests);
  expect(screen.queryAllByRole('button', { name: /person/i })).toHaveLength(0);
  canvasContext.mockRestore();
});

// Turning analytics off must not interpret an old observation clock as a video fault.
it('shows video only and hides old detections and clock warnings when analysis is off', async () => {
  jest.clearAllMocks(); (useProcessedPreview as jest.Mock).mockReturnValue(null);
  render(<CityCamera {...common} source={source} analysisEnabled={false} snapshot={{ ...snapshot, sources: [{ ...snapshot.sources[0], sourceClockAgeSeconds: 732.4, sourceClockStatus: 'delayed-or-unsynchronized' }] }} />);
  expect(await screen.findByText('Video only · detections off')).toBeInTheDocument();
  expect(screen.queryByText(/clock needs checking/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Person ·/ })).not.toBeInTheDocument();
});
