// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { CityMobilityPanel, mobilityConfigError, mobilityCsv } from '../CityMobilityPanel';
import { useMobility } from '../useMobility';
import type { CityRule, CitySite, Point } from '../types';
import type { MobilityReport } from '../mobilityTypes';
jest.mock('../useMobility', () => ({ useMobility: jest.fn() }));
const site: CitySite = { id: 'city', name: 'City', revision: 1, mode: 'live', sources: [{ id: 'cam', name: 'North camera', width: 1000, height: 1000, imageToGroundHomography: [[1,0,0],[0,1,0],[0,0,1]] }], map: { bounds: [0,0,10,10], roads: [], buildings: [] } };
const rules: CityRule[] = ['entry','exit','queue'].map((id, index) => ({ id, name: `${id} zone`, sourceId: 'cam', kind: index === 2 ? 'queue' : 'area-entry', classes: ['person'], enabled: true, revision: 1, geometry: { space: 'image-normalized', points: [[.1,.1],[.8,.1],[.8,.8]] }, conditions: {} }));
const report: MobilityReport = { schemaVersion: 'city.mobility.v1', siteId: 'city', siteRevision: 1, mode: 'live', configRevision: 1, windowMinutes: 5, timeBasis: 'per-camera-source-time', globalFusionEnabled: false,
  config: { revision: 1, movements: [], crossings: [], queues: [] }, coverage: [{ sourceId: 'cam', name: 'North camera', status: 'live', windowStartNs: '0', windowEndNs: '30000000000', timestampBasis: 'pipeline-pts', observedSeconds: 27, windowSeconds: 300, coverageRatio: .09, truncated: false }],
  lineCounts: [{ ruleId: 'entry', name: 'North gate', sourceId: 'cam', count: 7, byClass: { car: 5, person: 2 }, status: 'partial' }], movements: [], obstructions: [{ ruleId: 'exit', name: 'Crossing stop', sourceId: 'cam', episodeCount: 3, completedEpisodes: 1, ongoingEpisodes: 1, unknownEpisodes: 1, blockedSeconds: 12.5, longestObservedEpisodeSeconds: 10, eventIds: ['event'], status: 'partial' }], queues: [], crossings: [], configurationIssues: [], limitations: ['Source video time only.'] };
const state = () => ({ report, receivedAt: '2026-10-23T18:00:00Z', error: null, loading: false, saving: false, windowMinutes: 5, setWindowMinutes: jest.fn(), refresh: jest.fn(), saveConfig: jest.fn().mockResolvedValue({ config: report.config, configRevision: 1 }) });
beforeEach(() => (useMobility as jest.Mock).mockReturnValue(state()));
it('renders actual gate and stopped-time measures, coverage, selectors and map action', () => {
  const focus = jest.fn(); render(<CityMobilityPanel site={site} rules={rules} onFocusRule={focus} />);
  expect(screen.getByText('Intersection measurements')).toBeInTheDocument(); expect(screen.queryByRole('region', { name: 'Crossing access' })).not.toBeInTheDocument();
  expect(screen.getByText('7')).toBeInTheDocument(); expect(screen.getByText('27 s / 5 min')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '1 min' })); expect((useMobility as jest.Mock).mock.results[0].value.setWindowMinutes).toHaveBeenCalledWith(1);
  fireEvent.click(screen.getByText(/Individual gate counts/)); fireEvent.click(screen.getAllByRole('button', { name: 'Show on map' })[0]); expect(focus).toHaveBeenCalledWith('entry');
  fireEvent.click(screen.getByRole('button', { name: 'Crossing access' })); expect(screen.getByText('12.5 s')).toBeInTheDocument(); expect(screen.queryByRole('region', { name: 'Movement demand' })).not.toBeInTheDocument();
});
it('retains settings edits across polling and sends expected revision', async () => {
  const value = state(); (useMobility as jest.Mock).mockReturnValue(value);
  const { rerender } = render(<CityMobilityPanel site={site} rules={rules} />);
  fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.click(screen.getByRole('button', { name: 'Add movement' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'North to east' } });
  fireEvent.change(screen.getByLabelText('Entry gate or area'), { target: { value: 'entry' } }); fireEvent.change(screen.getByLabelText('Exit gate or area'), { target: { value: 'exit' } });
  (useMobility as jest.Mock).mockReturnValue({ ...value, report: { ...report, lineCounts: [] } }); rerender(<CityMobilityPanel site={site} rules={rules} />);
  expect(screen.getByLabelText('Name')).toHaveValue('North to east');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save measurement settings' })));
  expect(value.saveConfig).toHaveBeenCalledWith(expect.objectContaining({ expectedRevision: 1, movements: [expect.objectContaining({ name: 'North to east', entryRuleId: 'entry', exitRuleId: 'exit' })] }));
});
it('keeps manual topic selection stable across actual report polling', () => {
  const value = state(); (useMobility as jest.Mock).mockReturnValue(value);
  const { rerender } = render(<CityMobilityPanel site={site} rules={rules} />);
  fireEvent.click(screen.getByRole('button', { name: 'Queues' }));
  (useMobility as jest.Mock).mockReturnValue({ ...value, receivedAt: '2026-10-23T18:00:02Z', report: { ...report, lineCounts: [] } });
  rerender(<CityMobilityPanel site={site} rules={rules} />);
  expect(screen.getByRole('button', { name: 'Queues' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('region', { name: 'Approach queues' })).toBeInTheDocument();
});
it('supports a controlled scenario topic and subsequent manual choices without polling resets', () => {
  const changed = jest.fn(); function Controlled() {
    const [topic, setTopic] = React.useState<'queues' | 'curbs'>('queues');
    return <CityMobilityPanel site={site} rules={rules} topic={topic} onTopicChange={value => { changed(value); setTopic(value as 'queues' | 'curbs'); }} />;
  }
  const { rerender } = render(<Controlled />);
  expect(screen.getByRole('button', { name: 'Queues' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Curb access' })); expect(changed).toHaveBeenCalledWith('curbs');
  (useMobility as jest.Mock).mockReturnValue({ ...state(), receivedAt: '2026-10-23T18:00:04Z', report: { ...report } }); rerender(<Controlled />);
  expect(screen.getByRole('button', { name: 'Curb access' })).toHaveAttribute('aria-pressed', 'true');
});
it('detects changed revisions without overwriting an open draft', () => {
  const value = state(); (useMobility as jest.Mock).mockReturnValue(value); const { rerender } = render(<CityMobilityPanel site={site} rules={rules} />);
  fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.click(screen.getByRole('button', { name: 'Add movement' }));
  (useMobility as jest.Mock).mockReturnValue({ ...value, report: { ...report, configRevision: 2, config: { ...report.config, revision: 2 } } }); rerender(<CityMobilityPanel site={site} rules={rules} />);
  expect(screen.getByRole('alert')).toHaveTextContent('Settings changed elsewhere'); expect(screen.getByLabelText('Name')).toHaveValue('New movement'); expect(screen.getByRole('button', { name: 'Save measurement settings' })).toBeDisabled();
});
it('fills queue geometry after three map points without closing setup', () => {
  let apply!: (points: [Point,Point,Point]) => void; render(<CityMobilityPanel site={site} rules={rules} onPickQueueGeometry={callback => { apply = callback; }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.click(screen.getByRole('button', { name: 'queues' })); fireEvent.click(screen.getByRole('button', { name: 'Add queue' }));
  fireEvent.change(screen.getByLabelText('Queue area'), { target: { value: 'queue' } }); fireEvent.click(screen.getByRole('button', { name: 'Draw queue axis on map' }));
  act(() => apply([[1,2],[3,2],[2,9]])); expect(screen.getByLabelText('New queue Stop line A X')).toHaveValue(1); expect(screen.getByLabelText('New queue Upstream point Y')).toHaveValue(9);
  expect(screen.getByRole('form', { name: 'Insights settings' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Save measurement settings' })).toBeEnabled();
});
it('does not display retained current queue values as measured and clears a selected stale map tail', () => {
  const queue: any = { id: 'q', name: 'North queue', sourceId: 'cam', ruleId: 'queue', zoneRuleId: 'queue', status: 'queued', count: 77, observedExtentM: 8, extentIsLowerBound: false, extentBasis: 'ground-anchor-distance', tailPositionM: [2,8], stopLineM: [[1,2],[3,2]], upstreamPointM: [2,9], spillbackDistanceM: 20, spillback: false, durationMs: 2000, trackIds: [], qualityReasons: [], asOfSourceTimeNs: '30000000000', windowMinutes: 5, maximumObservedExtentM: 8 };
  const focus = jest.fn(); const value = { ...state(), report: { ...report, queues: [queue] } }; (useMobility as jest.Mock).mockReturnValue(value);
  const { rerender } = render(<CityMobilityPanel site={site} rules={rules} onQueueFocus={focus} />); fireEvent.click(screen.getByRole('button', { name: 'Queues' })); fireEvent.click(screen.getByRole('button', { name: 'Show queue on map' })); expect(focus).toHaveBeenLastCalledWith(expect.objectContaining({ tailPositionM: [2,8] }));
  (useMobility as jest.Mock).mockReturnValue({ ...value, error: 'Connection lost', report: { ...value.report, queues: [queue] } }); rerender(<CityMobilityPanel site={site} rules={rules} onQueueFocus={focus} />);
  expect(screen.queryByText('77')).not.toBeInTheDocument(); expect(within(screen.getByRole('region', { name: 'Approach queues' })).getByText('Not enough evidence')).toBeInTheDocument(); expect(focus).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'unknown', tailPositionM: null, observedExtentM: null }));
  fireEvent.click(screen.getByRole('button', { name: 'Turning traffic' })); expect(screen.queryByRole('region', { name: 'Approach queues' })).not.toBeInTheDocument(); expect(focus).toHaveBeenLastCalledWith(expect.objectContaining({ tailPositionM: null }));
});
it('exports real camera-scoped coverage and neutralizes formula-like names', () => {
  const csv = mobilityCsv({ ...report, lineCounts: [{ ...report.lineCounts[0], name: '=IMPORTXML("x")' }] }, '2026-10-23T18:00:00Z');
  expect(csv).toContain('"observed_video_seconds"'); expect(csv).toContain('"27"'); expect(csv).toContain("'=" ); expect(csv).toContain('"per-camera-source-time"');
});
it('rejects cross-camera pairings and unfilled queue coordinates', () => {
  const config = { ...report.config, movements: [{ id: 'm', name: 'Move', entryRuleId: 'entry', exitRuleId: 'exit' }] };
  expect(mobilityConfigError(config, rules.map(rule => rule.id === 'exit' ? { ...rule, sourceId: 'other' } : rule))).toMatch(/one camera/);
  expect(mobilityConfigError({ ...report.config, queues: [{ id: 'q', name: 'Queue', zoneRuleId: 'queue', stopLine: [[NaN,NaN],[NaN,NaN]], upstreamPoint: [NaN,NaN], spillbackDistanceM: 20 }] }, rules)).toMatch(/set the stop line/);
});
it('does not let a late settings save close a newer editor', async () => {
  let finish!: (value: unknown) => void; const value = state(); value.saveConfig.mockImplementation(() => new Promise(resolve => { finish = resolve; })); (useMobility as jest.Mock).mockReturnValue(value);
  render(<CityMobilityPanel site={site} rules={rules} />);
  fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.click(screen.getByRole('button', { name: 'Save measurement settings' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close insights settings' })); fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.click(screen.getByRole('button', { name: 'Add movement' }));
  await act(async () => finish({ config: report.config, configRevision: 1 })); expect(screen.getByLabelText('Name')).toHaveValue('New movement'); expect(screen.getByRole('form', { name: 'Insights settings' })).toBeInTheDocument();
});
it('requires shared movement classes and person-enabled crossing areas', () => {
  const config = { ...report.config, movements: [{ id: 'm', name: 'Move', entryRuleId: 'entry', exitRuleId: 'exit', classes: ['car'] }] };
  expect(mobilityConfigError(config, rules)).toMatch(/selected object class/);
  expect(mobilityConfigError({ ...report.config, crossings: [{ id: 'c', name: 'Cross', waitingRuleId: 'entry', crossingRuleId: 'exit' }] }, rules.map(rule => rule.id === 'entry' ? { ...rule, classes: ['car'] } : rule))).toMatch(/person class/);
});

it('hides previous-run counts until the report matches the current analytics epoch', () => {
  const value = state();
  const currentScope = { epoch: 'new-epoch', kind: 'scenario', runId: 'run-two', suppressed: false };
  (useMobility as jest.Mock).mockReturnValue({ ...value, report: { ...report, analyticsScope: { ...currentScope, epoch: 'old-epoch', runId: 'run-one' } } });
  const { rerender } = render(<CityMobilityPanel site={site} rules={rules} currentScope={currentScope} />);
  expect(screen.getByLabelText('Insights observation scope')).toHaveTextContent('This prepared run · Updating this scope…');
  expect(screen.queryByText('7')).toBeNull();
  expect(value.refresh).toHaveBeenCalledTimes(1);
  (useMobility as jest.Mock).mockReturnValue({ ...value, report: { ...report, analyticsScope: currentScope } });
  rerender(<CityMobilityPanel site={site} rules={rules} currentScope={currentScope} />);
  expect(screen.getByText('7')).toBeInTheDocument();
  expect(screen.getByLabelText('Insights observation scope')).toHaveTextContent('Window limited to this scope');
  expect(screen.getByText('Up to 5 min')).toBeInTheDocument();
});

it('keeps the analytics scope in CSV exports with each measurement', () => {
  const csv = mobilityCsv({ ...report, analyticsScope: { epoch: 'epoch-abc', kind: 'scenario', runId: 'run-two', scenarioId: 'queue-recovery', startedAt: '2026-10-26T15:00:00Z' } }, null);
  expect(csv).toContain('"scope_epoch","scope_kind","run_id","scenario_id","scope_started_at"');
  expect(csv).toContain('"epoch-abc","scenario","run-two","queue-recovery","2026-10-26T15:00:00Z"');
});
