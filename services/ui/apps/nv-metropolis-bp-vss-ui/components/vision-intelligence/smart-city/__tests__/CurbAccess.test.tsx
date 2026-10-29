// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { CityMobilityPanel, mobilityConfigError, mobilityCsv } from '../CityMobilityPanel';
import { useMobility, mobilityReportMatches } from '../useMobility';
import type { CityRule, CitySite } from '../types';
import type { MobilityCurb, MobilityCurbConfig, MobilityReport } from '../mobilityTypes';
jest.mock('../useMobility', () => ({ ...jest.requireActual('../useMobility'), useMobility: jest.fn() }));
const site: CitySite = { id: 'city', name: 'City', revision: 1, mode: 'live', sources: [{ id: 'cam', name: 'North camera', width: 1000, height: 1000 }], map: { bounds: [0,0,10,10], roads: [], buildings: [] } };
const rules: CityRule[] = ['Curb zone','People zone'].map((name, index) => ({ id: index ? 'people' : 'curb', name, sourceId: 'cam', kind: 'occupancy-threshold', classes: index ? ['person'] : ['car','truck','bus'], enabled: true, revision: 1, geometry: { space: 'image-normalized', points: [[.1,.1],[.8,.1],[.8,.8]] }, conditions: {} }));
const config: MobilityCurbConfig = { id: 'c', name: 'North curbside access', zoneRuleId: 'curb', role: 'general', dwellThresholdMs: 30000, maximumObservationGapMs: 1000 };
const curb: MobilityCurb = { id: 'c', name: config.name, sourceId: 'cam', ruleId: 'curb', zoneRuleId: 'curb', role: 'general', status: 'active', asOfSourceTimeNs: '40000000000', windowMinutes: 5, timeBasis: 'source-time', occupancy: 2, observedOccupancy: 2, occupancyIsLowerBound: false, pendingTrackCount: 0, lostTrackCount: 0, byClass: { car: 2 }, arrivalCount: 6, departureCount: 4, turnoverCount: 3, completedVisitCount: 3, incompleteVisitCount: 1, partialVisitCount: 2, occupiedSeconds: 12.5, completedDwellP50Ms: 8000, completedDwellP95Ms: 11000, longestActiveObservedDwellMs: 20000, persistentOccupancyCount: 0, persistentByClass: {}, stoppedCount: null, stoppedByClass: {}, observedStoppedSeconds: null, stoppedEvidenceSeconds: 0, activeVisits: [], qualityReasons: [] };
const report: MobilityReport = { schemaVersion: 'city.mobility.v1', siteId: 'city', siteRevision: 1, mode: 'live', configRevision: 1, windowMinutes: 5, timeBasis: 'per-camera-source-time', globalFusionEnabled: false,
  config: { revision: 1, movements: [], crossings: [], queues: [], curbs: [config] }, coverage: [{ sourceId: 'cam', name: 'North camera', status: 'live', windowStartNs: '0', windowEndNs: '40000000000', timestampBasis: 'pipeline-pts', observedSeconds: 35, windowSeconds: 300, coverageRatio: 35/300, truncated: false }],
  lineCounts: [], movements: [], obstructions: [], queues: [], crossings: [], curbs: [curb], configurationIssues: [], limitations: [] };
const state = (value: MobilityReport = report) => ({ report: value, receivedAt: '2026-10-23T19:00:00Z', error: null as string | null, loading: false, saving: false, windowMinutes: 5, setWindowMinutes: jest.fn(), refresh: jest.fn(), saveConfig: jest.fn().mockResolvedValue({ config: value.config, configRevision: 1 }) });
const metric = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling;
function open() { fireEvent.click(screen.getByRole('button', { name: 'Curb access' })); }
beforeEach(() => (useMobility as jest.Mock).mockReturnValue(state()));
it('keeps legacy reports usable when curb arrays are absent and rejects malformed optional arrays', () => {
  const old: MobilityReport = { ...report, curbs: undefined, config: { ...report.config, curbs: undefined } };
  expect(mobilityReportMatches(old, site, 5)).toBe(true); expect(mobilityReportMatches({ ...old, curbs: {} } as any, site, 5)).toBe(false);
  expect(mobilityReportMatches({ ...old, config: { ...old.config, curbs: 'invalid' } } as any, site, 5)).toBe(false);
  (useMobility as jest.Mock).mockReturnValue(state(old)); render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByText('See how curb space is used')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Set up a curb area' })).toBeEnabled();
});
it('shows observed occupancy, interval time, distinct visits and zone map focus without parking claims', () => {
  const focus = jest.fn(); render(<CityMobilityPanel site={site} rules={rules} onFocusRule={focus} />); open();
  expect(screen.getByText('vehicles detected now')).toBeInTheDocument(); expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent(/^2$/); expect(screen.getByText('Occupied', { selector: 'span' })).toBeInTheDocument();
  expect(metric('Observed occupied time')).toHaveTextContent('12.5 s'); expect(metric('Observed arrivals')).toHaveTextContent('6'); expect(metric('Observed departures')).toHaveTextContent('4');
  expect(metric('Confirmed stopped now')).toHaveTextContent('—'); expect(screen.getByText('Stopped status needs fresh speed evidence.')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Visit outcomes')); expect(metric('Completed visits')).toHaveTextContent('3'); expect(metric('Incomplete visits')).toHaveTextContent('1'); expect(metric('Partial visits')).toHaveTextContent('2'); expect(metric('Complete-visit median dwell')).toHaveTextContent('8 s');
  fireEvent.click(screen.getByRole('button', { name: 'Show on map' })); expect(focus).toHaveBeenCalledWith('curb');
  expect(screen.queryByText('Parking turnover')).not.toBeInTheDocument();
});
it('shows a fresh visible lower-bound count while retaining unresolved membership honestly', () => {
  (useMobility as jest.Mock).mockReturnValue(state({ ...report, curbs: [{ ...curb, occupancyIsLowerBound: true, lostTrackCount: 1, qualityReasons: ['One earlier track is unresolved.'] }] }));
  render(<CityMobilityPanel site={site} rules={rules} />); open(); expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent(/^2$/); expect(screen.getByText(/Total occupancy: ≥ 2/)).toBeInTheDocument(); expect(screen.getByText(/Other tracked vehicles remain unresolved/)).toBeInTheDocument();
});
it.each(['fetch error', 'stale source'])('hides current curb values on %s but retains labelled historical measures', condition => {
  const value = state({ ...report, curbs: [{ ...curb, occupancy: 77, persistentOccupancyCount: 66, stoppedCount: 55 }] });
  if (condition === 'fetch error') value.error = 'Connection lost'; else value.report = { ...value.report, coverage: [{ ...report.coverage[0], status: 'stale' }] };
  (useMobility as jest.Mock).mockReturnValue(value); render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByText('Not enough evidence')).toBeInTheDocument(); expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent('—'); expect(screen.queryByText('77')).not.toBeInTheDocument(); expect(metric('Current observed dwell')).toHaveTextContent('—'); expect(metric('Confirmed stopped now')).toHaveTextContent('—'); expect(metric('At least 30 s observed dwell')).toHaveTextContent('—'); expect(metric('Observed occupied time')).toHaveTextContent('12.5 s');
});
it('shows a known visible subset separately when total occupancy is unresolved', () => {
  (useMobility as jest.Mock).mockReturnValue(state({ ...report, curbs: [{ ...curb, status: 'unknown', occupancy: null, observedOccupancy: 2 }] }));
  render(<CityMobilityPanel site={site} rules={rules} />); open(); expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent(/^2$/); expect(screen.getByText('Total occupancy is unknown; other tracked vehicles remain unresolved.')).toBeInTheDocument(); expect(metric('Current observed dwell')).toHaveTextContent('—');
});
it('shows fresh zero detections while keeping interrupted occupancy unknown and its evidence visible', () => {
  (useMobility as jest.Mock).mockReturnValue(state({ ...report, curbs: [{ ...curb, status: 'unknown', occupancy: null,
    observedOccupancy: 0, occupancyIsLowerBound: true, byClass: {}, activeVisits: [], pendingTrackCount: 1,
    lostTrackCount: 3, qualityReasons: ['Interrupted visits remain unresolved within the 15-minute evidence horizon.'] }] }));
  render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent(/^0$/);
  expect(screen.getByText('Not enough evidence')).toBeInTheDocument();
  expect(screen.getByText(/zero detections do not confirm a clear curb/)).toBeInTheDocument();
  expect(screen.getByText('1 temporarily missing · 3 interrupted visits unresolved.')).toBeInTheDocument();
  expect(screen.queryByText('Observed empty')).not.toBeInTheDocument();
  expect(metric('Current observed dwell')).toHaveTextContent('—');
  expect(metric('Confirmed stopped now')).toHaveTextContent('—');
  expect(screen.getByText('Interrupted visits remain unresolved within the 15-minute evidence horizon.')).toBeInTheDocument();
});
it('also shows zero for a fresh observed-empty sample without inventing a visit or departure', () => {
  (useMobility as jest.Mock).mockReturnValue(state({ ...report, curbs: [{ ...curb, status: 'empty', occupancy: 0,
    observedOccupancy: 0, byClass: {}, activeVisits: [] }] }));
  render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent(/^0$/);
  expect(screen.getByText('Observed empty', { selector: 'span' })).toBeInTheDocument();
  expect(metric('Observed departures')).toHaveTextContent('4');
});
it.each(['fetch error', 'stale source', 'awaiting source', 'missing coverage', 'missing sample time', 'older sample', 'invalid curb config'])('does not turn unavailable current observations into zero: %s', condition => {
  const value = state({ ...report, curbs: [{ ...curb, status: 'unknown', occupancy: null, observedOccupancy: 0 }] });
  if (condition === 'fetch error') value.error = 'Connection lost';
  if (condition === 'stale source') value.report.coverage = [{ ...report.coverage[0], status: 'stale' }];
  if (condition === 'awaiting source') value.report.coverage = [{ ...report.coverage[0], status: 'awaiting-observations' }];
  if (condition === 'missing coverage') value.report.coverage = [];
  if (condition === 'missing sample time') value.report.curbs![0].asOfSourceTimeNs = null;
  if (condition === 'older sample') value.report.curbs![0].asOfSourceTimeNs = '39000000000';
  if (condition === 'invalid curb config') value.report.configurationIssues = [{ kind: 'curb', id: 'c', reason: 'The curb rule is disabled.' }];
  (useMobility as jest.Mock).mockReturnValue(value); render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent('—');
  expect(screen.queryByText(/No vehicles are detected in the latest observation/)).not.toBeInTheDocument();
});
it.each([undefined, null, NaN, Infinity, -1, 1.5])('does not substitute zero for a missing or invalid observed count: %s', observedOccupancy => {
  (useMobility as jest.Mock).mockReturnValue(state({ ...report, curbs: [{ ...curb, observedOccupancy } as MobilityCurb] }));
  render(<CityMobilityPanel site={site} rules={rules} />); open();
  expect(screen.getByLabelText('Vehicles detected now')).toHaveTextContent('—');
});
it('creates curb settings with bounded defaults and excludes person-only polygons', async () => {
  const value = state({ ...report, curbs: [], config: { ...report.config, curbs: [] } }); (useMobility as jest.Mock).mockReturnValue(value);
  render(<CityMobilityPanel site={site} rules={rules} />); open(); fireEvent.click(screen.getByRole('button', { name: 'Set up a curb area' })); fireEvent.click(screen.getByRole('button', { name: 'Add curb area' }));
  expect(screen.getByLabelText('Persistent occupancy after (s)')).toHaveValue(30); expect(screen.getByLabelText('Maximum observation gap (s)')).toHaveValue(1);
  const select = screen.getByLabelText('Curb area'); expect(within(select).queryByRole('option', { name: 'People zone' })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: 'curb' } }); fireEvent.change(screen.getByLabelText('Configured use'), { target: { value: 'loading' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save measurement settings' })));
  expect(value.saveConfig).toHaveBeenCalledWith(expect.objectContaining({ expectedRevision: 1, curbs: [expect.objectContaining({ role: 'loading', zoneRuleId: 'curb', dwellThresholdMs: 30000, maximumObservationGapMs: 1000 })] }));
});
it('preserves hidden configuration fields and other measurement settings when saving curb edits', async () => {
  const savedConfig: any = { ...report.config, operatorNote: 'keep this', movements: [{ id: 'm', name: 'Movement', entryRuleId: 'curb', exitRuleId: 'other', classes: ['car'], maximumObservationGapMs: 4500 }], curbs: [{ ...config, speedBelowMps: .3 }] };
  const value = state({ ...report, config: savedConfig }); (useMobility as jest.Mock).mockReturnValue(value);
  render(<CityMobilityPanel site={site} rules={[...rules, { ...rules[0], id: 'other' }]} />); open(); fireEvent.click(screen.getByRole('button', { name: 'Configure insights' })); fireEvent.change(screen.getByLabelText('Configured use'), { target: { value: 'bus-stop' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Save measurement settings' })));
  expect(value.saveConfig).toHaveBeenCalledWith(expect.objectContaining({ expectedRevision: 1, operatorNote: 'keep this', movements: savedConfig.movements, curbs: [expect.objectContaining({ role: 'bus-stop', speedBelowMps: .3 })] }));
});
it('validates curb polygon classes and evidence thresholds before saving', () => {
  expect(mobilityConfigError({ ...report.config, curbs: [{ ...config, zoneRuleId: 'people' }] }, rules)).toMatch(/vehicle classes/);
  expect(mobilityConfigError({ ...report.config, curbs: [{ ...config, dwellThresholdMs: NaN }] }, rules)).toMatch(/dwell threshold/);
  expect(mobilityConfigError({ ...report.config, curbs: [{ ...config, maximumObservationGapMs: 49 }] }, rules)).toMatch(/observation gap/);
});
it('exports curb visits/time and keeps unknown current occupancy blank', () => {
  const csv = mobilityCsv({ ...report, curbs: [{ ...curb, status: 'unknown', occupancy: 99, persistentOccupancyCount: 88 }] }, '2026-10-23T19:00:00Z');
  expect(csv).toContain('"occupiedSeconds","12.5","observed_seconds"'); expect(csv).toContain('"arrivalCount","6"'); expect(csv).toContain('"occupancy","","count"'); expect(csv).not.toContain('"occupancy","99"'); expect(csv).toContain('"partialVisitCount","2"'); expect(csv).toContain('"observedStoppedSeconds","","observed_seconds"'); expect(csv).toContain('"stoppedEvidenceSeconds","0","observed_seconds"');
});
