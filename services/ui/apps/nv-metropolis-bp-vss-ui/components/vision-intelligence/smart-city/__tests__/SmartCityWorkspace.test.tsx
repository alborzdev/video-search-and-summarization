// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SmartCityWorkspace } from '../../SmartCityWorkspace';
jest.mock('../CityDetectionControl', () => ({ CityDetectionControl: () => <section aria-label="Detection controls" /> }));
import { useCity } from '../useCity';
import { usePreviewHealth } from '../usePreviewHealth';

jest.mock('../useCity', () => ({ useCity: jest.fn() }));
jest.mock('../usePreviewHealth', () => ({ usePreviewHealth: jest.fn(() => null) }));
jest.mock('../ScenarioEvidence', () => ({ ScenarioEvidence: (props: any) => <div aria-label="VSS observes">{props.scenarioId} camera evidence</div> }));
jest.mock('../CityDemoControls', () => ({ CityDemoControls: (props: any) => <div>Demo controls<button onClick={() => props.onPreparationChange(true)}>Mock preparing</button><button onClick={() => props.onPreparationChange(false)}>Mock ready</button>{['queue-recovery', 'curb-obstruction', 'pedestrian-service', 'crossing-obstruction', 'turning-demand'].map(id => <button key={id} onClick={() => props.onScenarioStarted(id)}>Confirmed {id}</button>)}</div> }));
jest.mock('../CityIndexingControl', () => ({ CityIndexingControl: (props: any) => <button onClick={() => props.onOpenEvidence({ sensor_id: props.sources[0].id, video_name: 'Indexed alias', description: 'Match', start_time: '2026-10-26T08:00:00Z', end_time: '2026-10-26T08:00:05Z' })}>Open mock capture clip</button> }));
jest.mock('../CityCaptureEvidenceDrawer', () => ({ CityCaptureEvidenceDrawer: (props: any) => <section role="dialog" aria-label="Mock retained clip"><span>{props.sourceName}</span><output aria-label="Retained clip source">{props.match.sensor_id}</output><button onClick={props.onClose}>Close mock clip</button></section> }));
jest.mock('../CityCamera', () => ({ CityCamera: (props: any) => <div>Camera<output aria-label={`Camera framing ${props.source.id}`}>{props.fillFrame ? 'cropped' : 'full frame'}</output><output aria-label={`Scenario areas ${props.source.id}`}>{props.scenarioRuleIds?.join('|') ?? 'all'}</output><output aria-label={`Area guide ${props.source.id}`}>{props.areaHighlight?.id ?? 'none'}</output><button onClick={() => props.onPoint([.2, .3])}>Place mock point</button><output aria-label={`Selected camera ${props.source.id}`}>{props.selectedTrackIds?.join('|')}</output><output aria-label={`Preview limit ${props.source.id}`}>{props.previewFpsLimit ?? 'default'}</output></div> }));
jest.mock('../CityMap', () => ({ CityMap: (props: any) => <div>Map<output aria-label="Map areas">{props.rules.map((rule: any) => rule.id).join('|')}</output>{props.children}<button onClick={() => props.onPreviewRule?.(props.rules[0]?.id)}>Preview map area</button><button onClick={props.onClearFocus}>Clear map focus</button>{props.rules?.length > 0 && <button onClick={() => props.onInspectRule(props.rules[0].id)}>Inspect map measurement</button>}{props.mapObjects?.some((object: any) => object.shared) && <button onClick={() => props.onSelect(props.mapObjects.find((object: any) => object.shared).track.id)}>Select shared map object</button>}</div> }));
jest.mock('../alignedSnapshot', () => ({ displaySnapshot: (_site: unknown, snapshot: unknown) => snapshot }));
jest.mock('../CityMobilityPanel', () => ({ CityMobilityPanel: (props: any) => <div><output aria-label="Measurement topic">{props.topic}</output><button onClick={() => props.onTopicChange('curbs')}>Manually select curb insights</button></div> }));
jest.mock('../CityInspector', () => ({ CityInspector: (props: any) => <div>
  <output aria-label="Inspector panel">{props.panel}</output><output aria-label="Inspector topic">{props.insightTopic}</output>
  <button onClick={() => props.onPanel('reports')}>Mock reports tab</button>
  <button onClick={() => props.onEvent({ id: 'old-event', mode: 'live', sourceId: 'camera', trackIds: [], ruleName: 'Historical occupancy', state: 'cleared' })}>Select saved event</button>
  {props.selectedEvent && <span>{props.selectedEvent.ruleName}: {props.selectedEvent.state}</span>}
  <output aria-label="Inspector rule versions">{props.rules.map((rule: any) => `${rule.id}:${rule.revision}:${rule.name}`).join('|')}</output>
  <output aria-label="Inspector metric count">{props.snapshot?.metrics?.length ?? 0}</output>
  <output aria-label="Inspector live readiness">{String(props.liveAnalysisReady)}</output>
</div> }));
jest.mock('../CityRuleEditor', () => ({ CityRuleEditor: (props: any) => <div>
  <button onClick={() => props.onEdit(props.rules[0])}>Edit existing</button>
  <button onClick={props.onSave}>Save existing</button>
  <button onClick={props.onClose}>Close mock editor</button>
  <button onClick={() => props.onDelete(props.rules[0])}>Delete existing</button>
  <button onClick={() => props.onChange({ ...props.draft, name: 'New draft' })}>Change draft</button>
  <button onClick={() => props.onChange({ ...props.draft, kind: 'line-crossing', points: [[0, 0], [1, 1]] })}>Set completed line</button>
  <button onClick={() => props.onChange({ ...props.draft, kind: 'area-entry', points: Array.from({ length: 128 }, () => [0, 0]) })}>Set full polygon</button>
  <output aria-label="Draft name">{props.draft.name}</output>
  <output aria-label="Draft points">{props.draft.points.length}</output>
  {props.error && <span role="alert">{props.error}</span>}
</div> }));
const site = { id: 'site-a', revision: 1, mode: 'live', name: 'Site A', sources: [{ id: 'camera', name: 'Camera', width: 640, height: 480 }], map: { bounds: [0, 0, 10, 10], roads: [], buildings: [] } };
function state() {
  return { site, snapshot: { siteId: 'site-a', mode: 'live', tracks: [], events: [], sources: [], rules: [], zones: [] }, sourceSnapshots: {}, rules: { revision: 3, rules: [{ id: 'stop', name: 'Custom stop rule', kind: 'stopped-in-zone', sourceId: 'camera', classes: ['car'], enabled: false, revision: 2, geometry: { space: 'image-normalized', points: [[0, 0], [1, 0], [1, 1]] }, conditions: { speedBelowMps: 1.25, minimumDurationMs: 2500, maximumObservationGapMs: 1200 } }] }, connected: true, loading: false, saving: false, error: null, previewGeneration: 1, saveRules: jest.fn().mockResolvedValue({}), atMediaTime: jest.fn(), atSourceTime: jest.fn(), presentProcessedFrame: jest.fn(), refresh: jest.fn() };
}
describe('Smart City workspace state', () => {

  it('preserves full camera frames in overview and measurements', () => {
    const city = state();
    (useCity as jest.Mock).mockReturnValue({ ...city, site: { ...city.site, sources: [site.sources[0], { ...site.sources[0], id: 'other' }] } });
    render(<SmartCityWorkspace />);
    for (const id of ['camera', 'other']) expect(screen.getByLabelText(`Camera framing ${id}`)).toHaveTextContent('full frame');
    fireEvent.click(screen.getByRole('button', { name: 'Measurements' }));
    for (const id of ['camera', 'other']) expect(screen.getByLabelText(`Camera framing ${id}`)).toHaveTextContent('full frame');
  });

  it('shows the active scenario areas and restores the normal map after its analytics scope closes', () => {
    const city = state();
    const base = { ...city.rules.rules[0], enabled: true };
    const rules = ['mobility-isaac-north-curbside-lane', 'cam_sw-blocked-crossing', 'unrelated'].map(id => ({ ...base, id }));
    const active = { ...city, site: { ...city.site, id: 'isaac-intersection-a' }, rules: { ...city.rules, rules }, snapshot: { ...city.snapshot, analyticsScope: { kind: 'scenario', scenarioId: 'curb-obstruction' } } };
    (useCity as jest.Mock).mockReturnValue(active);
    const { rerender } = render(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Map areas')).toHaveTextContent(/^mobility-isaac-north-curbside-lane$/);
    expect(screen.getByLabelText('Scenario areas camera')).toHaveTextContent(/^mobility-isaac-north-curbside-lane$/);
    expect(screen.getByLabelText('Scenario story')).toHaveTextContent('Is curb access available?');
    expect(screen.getByLabelText('Scenario story')).toHaveTextContent('A vehicle stops in the curbside lane.');
    expect(screen.getByLabelText('VSS observes')).toHaveTextContent('curb-obstruction camera evidence');
    (useCity as jest.Mock).mockReturnValue({ ...active, snapshot: { ...active.snapshot, analyticsScope: { kind: 'scenario', scenarioId: 'crossing-obstruction' } } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Map areas')).toHaveTextContent(/^cam_sw-blocked-crossing$/);
    expect(screen.getByLabelText('Scenario areas camera')).toHaveTextContent(/^cam_sw-blocked-crossing$/);
    expect(screen.getByLabelText('Scenario story')).toHaveTextContent('Is the crossing blocked?');
    (useCity as jest.Mock).mockReturnValue({ ...active, snapshot: { ...active.snapshot, analyticsScope: { kind: 'normal' } } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Map areas')).toHaveTextContent('unrelated');
    expect(screen.getByLabelText('Scenario areas camera')).toHaveTextContent('all');
    expect(city.saveRules).not.toHaveBeenCalled();
  });
  it('covers both cameras and the map while preserving the mounted camera nodes', () => {
    const city = state();
    const sources = [site.sources[0], { ...site.sources[0], id: 'other' }];
    const active = { ...city, site: { ...city.site, id: 'isaac-intersection-a', sources } };
    (useCity as jest.Mock).mockReturnValue(active);
    const { rerender } = render(<SmartCityWorkspace />);
    const first = screen.getByLabelText('Preview limit camera');
    const second = screen.getByLabelText('Preview limit other');
    fireEvent.click(screen.getByRole('button', { name: 'Mock preparing' }));
    const cover = screen.getByRole('status', { name: 'Scene preparation cover' });
    expect(cover).toHaveClass('preparationCover'); // The scenario controller portals the real progress into this opaque mount.
    expect(cover.parentElement).toContainElement(first);
    expect(cover.parentElement).toContainElement(second);
    expect(cover.parentElement).toContainElement(screen.getByText('Map'));
    expect(screen.getByLabelText('Preview limit camera')).toBe(first);
    expect(screen.getByLabelText('Preview limit other')).toBe(second);
    fireEvent.click(screen.getByRole('button', { name: 'Mock ready' }));
    expect(screen.getByRole('status', { name: 'Scene preparation cover' })).toBeInTheDocument();
    const fresh = sources.map(source => ({ ...source, status: 'live', sessionId: 'new-session', sequence: '7', lastSourceTimeNs: '7000000000' }));
    const frames = Object.fromEntries(fresh.map(source => [source.id, { ...city.snapshot, sources: [source], presentedPreview: {
      sourceId: source.id, sessionId: source.sessionId, sequence: '7', sourceTimeNs: source.lastSourceTimeNs, presentedAtMs: Date.now(),
    } }]));
    (useCity as jest.Mock).mockReturnValue({ ...active, snapshot: { ...city.snapshot, sources: fresh }, sourceSnapshots: { camera: frames.camera } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByRole('status', { name: 'Scene preparation cover' })).toBeInTheDocument();
    (useCity as jest.Mock).mockReturnValue({ ...active, snapshot: { ...city.snapshot, sources: fresh }, sourceSnapshots: frames });
    rerender(<SmartCityWorkspace />);
    expect(screen.queryByRole('status', { name: 'Scene preparation cover' })).toBeNull();
    expect(screen.getByLabelText('Preview limit camera')).toBe(first);
    expect(screen.getByLabelText('Preview limit other')).toBe(second);
  });

  it('shares transient map-area preview with both camera views and clears it without a rule write', () => {
    const city=state();city.rules.rules[0].enabled=true;
    const calibrated={...site.sources[0],calibrationRevision:'r1',imageToGroundHomography:[[1,0,0],[0,1,0],[0,0,1]]};
    city.site={...site,sources:[calibrated,{...calibrated,id:'other'}]};
    (useCity as jest.Mock).mockReturnValue(city);render(<SmartCityWorkspace/>);
    fireEvent.click(screen.getByRole('button',{name:'Preview map area'}));
    expect(screen.getByLabelText('Area guide camera')).toHaveTextContent('stop');expect(screen.getByLabelText('Area guide other')).toHaveTextContent('stop');
    fireEvent.click(screen.getByRole('button',{name:'Clear map focus'}));
    expect(screen.getByLabelText('Area guide camera')).toHaveTextContent('none');expect(screen.getByLabelText('Area guide other')).toHaveTextContent('none');expect(city.saveRules).not.toHaveBeenCalled();
  });

  it('opens the matching measurement topic from a configured map area before live metrics arrive', () => {
    const city = state(); city.rules.rules[0] = {...city.rules.rules[0],kind:'queue',enabled:true};
    (useCity as jest.Mock).mockReturnValue(city); render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button',{name:'Inspect map measurement'}));
    expect(screen.getByLabelText('Measurement topic')).toHaveTextContent('queues');
  });

  beforeEach(() => { (usePreviewHealth as jest.Mock).mockReturnValue(null); });
  it.each([['queue-recovery', 'queues'], ['curb-obstruction', 'curbs'], ['pedestrian-service', 'crossings'], ['crossing-obstruction', 'obstructions'], ['turning-demand', 'movements']])('shows the correct actual Insights topic after confirmed %s', (scenario, topic) => {
    (useCity as jest.Mock).mockReturnValue({ ...state(), site: { ...site, id: 'isaac-intersection-a' } });
    render(<SmartCityWorkspace />); fireEvent.click(screen.getByRole('button', { name: 'Search & reports' }));
    fireEvent.click(screen.getByRole('button', { name: `Confirmed ${scenario}` }));
    expect(screen.getByTestId('smart-city-workspace')).toHaveAttribute('data-view', 'overview'); fireEvent.click(screen.getByRole('button', { name: 'Measurements' })); expect(screen.getByLabelText('Measurement topic')).toHaveTextContent(topic);
  });
  it('preserves manual topic choice after scenario context across live state polling', () => {
    const city = { ...state(), site: { ...site, id: 'isaac-intersection-a' } }; (useCity as jest.Mock).mockReturnValue(city);
    const { rerender } = render(<SmartCityWorkspace />); fireEvent.click(screen.getByRole('button', { name: 'Confirmed queue-recovery' }));
    fireEvent.click(screen.getByRole('button', { name: 'Measurements' })); fireEvent.click(screen.getByRole('button', { name: 'Manually select curb insights' }));
    (useCity as jest.Mock).mockReturnValue({ ...city, snapshot: { ...city.snapshot, sequence: 2 } }); rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Measurement topic')).toHaveTextContent('curbs');
  });
  it('opens the capture clip for its actual registered camera, closes it, and retires it on site change', () => {
    const city = { ...state(), site: { ...site, id: 'isaac-intersection-a' } };
    (useCity as jest.Mock).mockReturnValue(city); const { rerender } = render(<SmartCityWorkspace />);
    expect(screen.queryByRole('dialog', { name: 'Mock retained clip' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Search & reports' })); fireEvent.click(screen.getByRole('button', { name: 'Find clips' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open mock capture clip' }));
    expect(screen.getByLabelText('Retained clip source')).toHaveTextContent('camera');
    expect(screen.getByRole('dialog')).toHaveTextContent('Camera');
    fireEvent.click(screen.getByRole('button', { name: 'Close mock clip' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open mock capture clip' }));
    (useCity as jest.Mock).mockReturnValue({ ...city, site: { ...city.site, revision: 2 } }); rerender(<SmartCityWorkspace />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('uses a fresh enabled native preview limit and falls back when health is stale, failed or unknown', () => {
    (useCity as jest.Mock).mockReturnValue(state());
    const healthy = { status: 'fresh', enabled: true, failed: false, fpsLimitPerSource: 30, sources: [] };
    (usePreviewHealth as jest.Mock).mockReturnValue(healthy); const { rerender } = render(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Preview limit camera')).toHaveTextContent('30');
    for (const value of [{ ...healthy, status: 'stale' }, { ...healthy, enabled: false }, { ...healthy, failed: true }, { ...healthy, failed: undefined }, { ...healthy, enabled: undefined }, null]) {
      (usePreviewHealth as jest.Mock).mockReturnValue(value); rerender(<SmartCityWorkspace />); expect(screen.getByLabelText('Preview limit camera')).toHaveTextContent('default');
    }
  });
  it('highlights both camera members only while the displayed map association still agrees', () => {
    const city = state(); const clock = '1792770000123456789';
    const sources = ['camera', 'other'].map(id => ({ ...site.sources[0], id, name: id, calibrationRevision: `cal-${id}`,
      status: 'live', sessionId: `session-${id}`, timestampBasis: 'source-rtcp', lastSourceTimeNs: clock }));
    const tracks = sources.map((source, index) => ({ id: `${source.id}:7`, sourceId: source.id, sessionId: source.sessionId,
      localTrackId: '7', class: 'person', positionM: [2 + index * .5, 3], observedThisFrame: true, sourceTimeNs: clock,
      stale: false, trail: [], mapAssociation: { method: 'mv3dt-demo', globalTrackId: 'shared7', targetId: '7', fusionEpoch: 'epoch',
        calibrationRevision: source.calibrationRevision, visibility: .8, sourceClockBasis: 'source-rtcp' } }));
    const shared = { ...city, site: { ...site, sources }, snapshot: { ...city.snapshot, siteRevision: site.revision,
      videoFrameMatched: true, sources, tracks, association: { mode: 'camera-local', globalFusionEnabled: false,
        mapFusion: { mode: 'mv3dt-demo', enabled: true, experimental: true, qualified: false } } } };
    (useCity as jest.Mock).mockReturnValue(shared); const { rerender } = render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Select shared map object' }));
    expect(screen.getByLabelText('Selected camera camera')).toHaveTextContent('camera:7|other:7');
    expect(screen.getByLabelText('Selected camera other')).toHaveTextContent('camera:7|other:7');
    (useCity as jest.Mock).mockReturnValue({ ...shared, snapshot: { ...shared.snapshot, tracks: [tracks[0], { ...tracks[1], positionM: [3.08, 3] }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByRole('button', { name: 'Select shared map object' })).toBeInTheDocument();
    expect(screen.getByLabelText('Selected camera other')).toHaveTextContent('camera:7|other:7');
    (useCity as jest.Mock).mockReturnValue({ ...shared, snapshot: { ...shared.snapshot, tracks: [tracks[0], { ...tracks[1], positionM: [5, 3] }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.queryByRole('button', { name: 'Select shared map object' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Selected camera camera')).toHaveTextContent(/^camera:7$/);
    expect(screen.getByLabelText('Selected camera other')).toHaveTextContent(/^camera:7$/);
  });

  it('keeps completed lines and full polygons when extra camera points are clicked', () => {
    (useCity as jest.Mock).mockReturnValue(state()); render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Set completed line' }));
    fireEvent.click(screen.getByRole('button', { name: 'Place mock point' }));
    expect(screen.getByLabelText('Draft points')).toHaveTextContent('2');
    fireEvent.click(screen.getByRole('button', { name: 'Set full polygon' }));
    fireEvent.click(screen.getByRole('button', { name: 'Place mock point' }));
    expect(screen.getByLabelText('Draft points')).toHaveTextContent('128');
  });
  it('ignores camera drawing while a rule save is pending', () => {
    const city = state(); (useCity as jest.Mock).mockReturnValue({ ...city, saving: true });
    const { rerender } = render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Place mock point' }));
    expect(screen.getByLabelText('Draft points')).toHaveTextContent('0');
    (useCity as jest.Mock).mockReturnValue(city); rerender(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Place mock point' }));
    expect(screen.getByLabelText('Draft points')).toHaveTextContent('1');
  });
  it('does not close a newer draft when an earlier save completes', async () => {
    const city = state(); let finish!: () => void;
    city.saveRules.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    (useCity as jest.Mock).mockReturnValue(city); render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change draft' }));
    await act(async () => finish());
    expect(screen.getByLabelText('Draft name')).toHaveTextContent('New draft');
  });
  it('does not attach an old save error to a reopened editor', async () => {
    const city = state(); let fail!: (error: Error) => void;
    city.saveRules.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject; }));
    (useCity as jest.Mock).mockReturnValue(city); render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close mock editor' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    await act(async () => fail(new Error('Old request failed')));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save existing' })).toBeInTheDocument();
  });
  it('closes a deleted rule draft so saving cannot recreate it by accident', async () => {
    const city = state(); (useCity as jest.Mock).mockReturnValue(city); render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete existing' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Save existing' })).not.toBeInTheDocument());
    expect(city.saveRules).toHaveBeenCalledWith([]);
  });
  it('opens saved events outside the rolling snapshot, prefers refreshed state, and clears selection for a new site', () => {
    const city = state(); (useCity as jest.Mock).mockReturnValue(city);
    const { rerender } = render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Search & reports' })); fireEvent.click(screen.getByRole('button', { name: 'Events & reports', exact: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Select saved event' }));
    expect(screen.getByText('Historical occupancy: cleared')).toBeInTheDocument();
    (useCity as jest.Mock).mockReturnValue({ ...city, snapshot: { ...city.snapshot, events: [{ id: 'old-event', ruleName: 'Historical occupancy', state: 'unknown', trackIds: [] }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByText('Historical occupancy: unknown')).toBeInTheDocument();
    (useCity as jest.Mock).mockReturnValue({ ...city, site: { ...site, id: 'site-b' } });
    rerender(<SmartCityWorkspace />);
    expect(screen.queryByText(/Historical occupancy:/)).not.toBeInTheDocument();
  });
  it('preserves configured speed and disabled status when editing an existing rule', async () => {
    const city = state(); (useCity as jest.Mock).mockReturnValue(city);
    render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit monitoring areas' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit existing' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save existing' }));
    await waitFor(() => expect(city.saveRules).toHaveBeenCalled());
    const [rules, revision] = city.saveRules.mock.calls[0];
    expect(revision).toBe(3);
    expect(rules[0]).toMatchObject({ enabled: false, revision: 3, conditions: { speedBelowMps: 1.25, minimumDurationMs: 2500, maximumObservationGapMs: 1200 } });
  });
  it('shows live status instead of a nonfunctional replay control', () => {
    (useCity as jest.Mock).mockReturnValue(state());
    render(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('1 camera view');
    expect(screen.queryByRole('slider', { name: 'City playback time' })).not.toBeInTheDocument();
  });
  it('does not call an open event stream live camera analysis before a frame is displayed', () => {
    const city = state();
    (useCity as jest.Mock).mockReturnValue({ ...city, snapshot: { ...city.snapshot, sources: [{ ...site.sources[0], status: 'live', sessionId: 'session' }] } });
    render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('Waiting for camera analysis');
    expect(screen.getByLabelText('Live analysis status').querySelector('i')).toHaveClass('dotMuted');
    expect(screen.getByLabelText('Inspector live readiness')).toHaveTextContent('false');
  });
  it('counts only fresh accepted camera frames and identifies a partial camera outage', () => {
    const city = state(); const now = Date.now();
    const first = { ...site.sources[0], status: 'live', sessionId: 'session', sequence: '7', lastSourceTimeNs: '7000000000' };
    const second = { ...first, id: 'other', name: 'Other camera' };
    const frame = (source: typeof first) => ({ ...city.snapshot, siteRevision: site.revision, sources: [source], presentedPreview: { sourceId: source.id, sessionId: 'session', sequence: '7', sourceTimeNs: '7000000000', presentedAtMs: now } });
    const both = { ...city, site: { ...site, sources: [first, second] }, snapshot: { ...city.snapshot, sources: [first, second] }, sourceSnapshots: { camera: frame(first), other: frame(second) } };
    (useCity as jest.Mock).mockReturnValue(both);
    const { rerender } = render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('2/2 cameras analyzed');
    expect(screen.getByLabelText('Live analysis status').querySelector('i')).toHaveClass('dot');
    expect(screen.getByLabelText('Inspector live readiness')).toHaveTextContent('true');
    (useCity as jest.Mock).mockReturnValue({ ...both, sourceSnapshots: { ...both.sourceSnapshots, other: { ...frame(second), presentedPreview: { ...frame(second).presentedPreview, presentedAtMs: now - 2500 } } } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('1/2 cameras analyzed');
    expect(screen.getByLabelText('Live analysis status').querySelector('i')).toHaveClass('dotWarning');
    (useCity as jest.Mock).mockReturnValue({ ...both, snapshot: { ...both.snapshot, sources: [{ ...first, status: 'stale' }, { ...second, status: 'stale' }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('2/2 cameras analyzed');
    (useCity as jest.Mock).mockReturnValue({ ...both, connected: false });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('2/2 cameras analyzed');
    (useCity as jest.Mock).mockReturnValue({ ...both, snapshot: { ...both.snapshot, sources: [{ ...first, status: 'paused' }, { ...second, status: 'stopped' }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('Waiting for camera analysis');
  });
  it('does not accept a frame from an older camera session and distinguishes an API outage', () => {
    const city = state(); const now = Date.now();
    const source = { ...site.sources[0], status: 'live', sessionId: 'replacement', sequence: '7', lastSourceTimeNs: '7000000000' };
    const old = { ...city.snapshot, sources: [source], presentedPreview: { sourceId: 'camera', sessionId: 'old', sequence: '7', sourceTimeNs: '7000000000', presentedAtMs: now } };
    const changed = { ...city, snapshot: { ...city.snapshot, sources: [source] }, sourceSnapshots: { camera: old } };
    (useCity as jest.Mock).mockReturnValue(changed);
    const { rerender } = render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('Waiting for camera analysis');
    (useCity as jest.Mock).mockReturnValue({ ...changed, connected: false });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('Analytics connection lost');
    expect(screen.getByLabelText('Inspector live readiness')).toHaveTextContent('false');
  });
  it('recognizes the verified aligned raw-camera path but rejects unverified clocks', () => {
    const city = state(); const now = Date.now();
    const source = { ...site.sources[0], browserClockVerified: true, status: 'live', sessionId: 'session', sequence: '7', lastSourceTimeNs: '7000000000', timestampBasis: 'source-rtcp', clockAligned: true };
    const raw = { ...city.snapshot, timestamp: new Date(now).toISOString(), requestedSourceTimeNs: '7000000000', sources: [source] };
    const aligned = { ...city, site: { ...site, sources: [source] }, snapshot: { ...city.snapshot, sources: [source] }, sourceSnapshots: { camera: raw } };
    (useCity as jest.Mock).mockReturnValue(aligned);
    const { rerender } = render(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('1/1 camera analyzed');
    (useCity as jest.Mock).mockReturnValue({ ...aligned, site: { ...site, sources: [{ ...source, browserClockVerified: false }] } });
    rerender(<SmartCityWorkspace />);
    expect(screen.getByLabelText('Live analysis status')).toHaveTextContent('Waiting for camera analysis');
  });
  it('keeps configured rules visible without a camera frame and does not invent their metrics', () => {
    const city = state(); (useCity as jest.Mock).mockReturnValue(city);
    render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Inspector rule versions')).toHaveTextContent('stop:2:Custom stop rule');
    expect(screen.getByLabelText('Inspector metric count')).toHaveTextContent('0');
  });
  it('keeps a displayed frame rule version instead of attaching its count to a new rule revision', () => {
    const city = state(); const displayed = { ...city.rules.rules[0], revision: 1, name: 'Original frame rule' };
    const added = { ...city.rules.rules[0], id: 'new', name: 'New rule awaiting frame' };
    (useCity as jest.Mock).mockReturnValue({ ...city, rules: { ...city.rules, rules: [...city.rules.rules, added] }, snapshot: { ...city.snapshot, rules: [displayed], metrics: [{ ruleId: 'stop', count: 4 }] } });
    render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Inspector rule versions')).toHaveTextContent('stop:1:Original frame rule|new:2:New rule awaiting frame');
    expect(screen.getByLabelText('Inspector rule versions')).not.toHaveTextContent('Custom stop rule');
    expect(screen.getByLabelText('Inspector metric count')).toHaveTextContent('1');
  });
  it('keeps historical replay rules at the selected time instead of appending current configuration', () => {
    const city = state();
    (useCity as jest.Mock).mockReturnValue({ ...city, site: { ...site, mode: 'recorded-inference' }, snapshot: { ...city.snapshot, mode: 'recorded-inference', rules: [] } });
    render(<SmartCityWorkspace />);
    fireEvent.click(screen.getByRole('button', { name: 'Events & technical details' }));
    expect(screen.getByLabelText('Inspector rule versions')).toBeEmptyDOMElement();
    expect(screen.getByLabelText('Inspector live readiness')).toHaveTextContent('undefined');
  });
});
