// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { CityMobilityPanel, mobilityCsv } from '../CityMobilityPanel';
import { useMobility } from '../useMobility';
import type { CitySite } from '../types';
import type { MobilityCrossing, MobilityQueue, MobilityReport } from '../mobilityTypes';
jest.mock('../useMobility', () => ({ useMobility: jest.fn() }));
const site: CitySite = { id: 'city', name: 'City', revision: 1, mode: 'live', sources: [{ id: 'cam', name: 'North', width: 1000, height: 1000 }], map: { bounds: [0,0,10,10], roads: [], buildings: [] } };
const crossing: MobilityCrossing = { id: 'c', name: 'North walk', sourceId: 'cam', waitingRuleId: 'wait', crossingRuleId: 'cross', status: 'unknown', waitingCount: 2, crossingCount: 0, oldestObservedWaitMs: 1000, completedCount: 0, abandonedCount: 0, returnedCount: 0, incompleteCount: 7, waitSampleCount: 0, waitP50Ms: null, waitP95Ms: null, windowMinutes: 5, asOfSourceTimeNs: '30000000000', qualityReasons: [], completionBasis: 'observed-far-side-exit', timeBasis: 'source-time', countBasis: 'currently-observed', currentCountsAvailable: true, membershipComplete: false, pendingTrackCount: 1, unresolvedHistoricalTrackCount: 7, lostTrackCount: 7, firstSeenWaitingCount: 2, lowerBoundWaitP50Ms: 1500, briefGapRecoveredWaitCount: 1 };
const queue: MobilityQueue = { id: 'q', name: 'North queue', sourceId: 'cam', ruleId: 'queue', zoneRuleId: 'queue', status: 'unknown', count: 0, observedExtentM: null, extentIsLowerBound: true, extentBasis: 'ground-anchor-distance', tailPositionM: null, stopLineM: [[0,0],[1,0]], upstreamPointM: [0,10], spillbackDistanceM: 20, spillback: null, durationMs: 0, trackIds: [], qualityReasons: [], asOfSourceTimeNs: '30000000000', windowMinutes: 5, maximumObservedExtentM: 9, countBasis: 'currently-observed', currentCountsAvailable: true, membershipComplete: false, pendingTrackCount: 0, unresolvedHistoricalTrackCount: 1, lostTrackCount: 1 };
const report: MobilityReport = { schemaVersion: 'city.mobility.v1', siteId: 'city', siteRevision: 1, mode: 'live', configRevision: 1, windowMinutes: 5, timeBasis: 'per-camera-source-time', globalFusionEnabled: false, config: { revision: 1, movements: [], crossings: [], queues: [] }, coverage: [{ sourceId: 'cam', name: 'North', status: 'live', windowStartNs: '0', windowEndNs: '30000000000', timestampBasis: 'pipeline-pts', observedSeconds: 20, windowSeconds: 300, coverageRatio: .06, truncated: false }], lineCounts: [], movements: [], obstructions: [], queues: [queue], crossings: [crossing], configurationIssues: [], limitations: [] };
function setup(value: MobilityReport = report, error: string | null = null) { (useMobility as jest.Mock).mockReturnValue({ report: value, error, receivedAt: '2026-10-23T19:00:00Z', loading: false, saving: false, windowMinutes: 5, setWindowMinutes: jest.fn(), refresh: jest.fn(), saveConfig: jest.fn() }); render(<CityMobilityPanel site={site} rules={[]} />); }
const metric = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling;
it('shows fresh visible people during incomplete membership and separates first-seen lower bounds from valid waits', () => {
  setup(); fireEvent.click(screen.getByRole('button', { name: 'Walking' }));
  expect(metric('Observed in approach area')).toHaveTextContent('≥ 2'); expect(metric('Currently observed crossing')).toHaveTextContent('0');
  expect(screen.getByText(/median time before crossing · 0 valid samples/)).toBeInTheDocument(); expect(metric('P95 time before crossing')).toHaveTextContent('—');
  expect(screen.getByText(/7 earlier tracks unresolved/)).toHaveTextContent('zero does not confirm an empty area');
  expect(screen.getByText(/2 journeys began with a person already in the approach area/)).toHaveTextContent('Median minimum time before crossing: ≥ 1.5 s');
});
it.each(['expired row', 'stale camera', 'fetch error'])('hides retained people when %s even if membership fields remain', condition => {
  const value = { ...report, crossings: [{ ...crossing, currentCountsAvailable: condition !== 'expired row' }] };
  if (condition === 'stale camera') value.coverage = [{ ...report.coverage[0], status: 'stale' }];
  setup(value, condition === 'fetch error' ? 'Disconnected' : null); fireEvent.click(screen.getByRole('button', { name: 'Walking' }));
  expect(metric('Observed in approach area')).toHaveTextContent('—'); expect(metric('Currently observed crossing')).toHaveTextContent('—');
});
it('shows zero observed queue anchors without claiming clearance or a zero extent', () => {
  setup(); fireEvent.click(screen.getByRole('button', { name: 'Queues' })); expect(metric('Currently observed queue objects')).toHaveTextContent('0');
  expect(screen.getByText('Not enough evidence')).toBeInTheDocument(); expect(screen.queryByText('No queue observed')).not.toBeInTheDocument(); expect(screen.queryByText('0 m')).not.toBeInTheDocument();
});
it('keeps legacy unknown counts hidden and exports observed counts with membership and wait-basis evidence', () => {
  setup({ ...report, crossings: [{ ...crossing, countBasis: undefined, currentCountsAvailable: undefined }] }); fireEvent.click(screen.getByRole('button', { name: 'Walking' })); expect(metric('Observed in approach area')).toHaveTextContent('—');
  const csv = mobilityCsv(report, null); expect(csv).toContain('"waitingCount","2"'); expect(csv).toContain('"membershipComplete","false"'); expect(csv).toContain('"lowerBoundWaitP50Ms","1500","milliseconds_lower_bound"'); expect(csv).toContain('"waitP50Ms","","milliseconds"');
  expect(mobilityCsv({ ...report, crossings: [{ ...crossing, currentCountsAvailable: false }] }, null)).toContain('"waitingCount","","count"');
});
