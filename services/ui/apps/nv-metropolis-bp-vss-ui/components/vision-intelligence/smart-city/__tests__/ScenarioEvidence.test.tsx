// SPDX-License-Identifier: MIT
import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { ScenarioEvidence, scenarioFinding } from '../ScenarioEvidence';
import { useMobility } from '../useMobility';
import type { AnalyticsScope, CitySite } from '../types';
import type { MobilityReport } from '../mobilityTypes';

jest.mock('../useMobility', () => ({ useMobility: jest.fn() }));
const scope: AnalyticsScope = { kind: 'scenario', epoch: 'epoch-1', runId: 'run-1', scenarioId: 'queue-recovery', startedAt: '2026-10-26T00:00:00Z', suppressed: false };
const site: CitySite = { id: 'site', name: 'Site', revision: 1, mode: 'live', sources: [{ id: 'cam', name: 'Camera', width: 960, height: 540 }], map: { bounds: [0, 0, 10, 10], roads: [], buildings: [] } };
const at = '1792972801000000000'; // One second after scope start, in source nanoseconds.
const movementIds = ['northbound-left', 'northbound-through', 'northbound-right'];
const exitIds = ['mobility-isaac-west-exit', 'mobility-isaac-north-exit', 'mobility-isaac-east-right-exit'];
const report: MobilityReport = {
  schemaVersion: 'city.mobility.v1', siteId: 'site', siteRevision: 1, mode: 'live', configRevision: 1, windowMinutes: 5, timeBasis: 'per-camera-source-time', globalFusionEnabled: false,
  analyticsScope: scope,
  config: { revision: 1, movements: movementIds.map((id, index) => ({ id, name: id, entryRuleId: 'cam_sw-northbound-line', exitRuleId: exitIds[index] })),
    queues: [{ id: 'northbound-queue', name: 'queue', zoneRuleId: 'mobility-isaac-northbound-queue', stopLine: [[0,0],[1,0]], upstreamPoint: [0,1], spillbackDistanceM: 10 }],
    crossings: [{ id: 'east-crossing-south-north', name: 'crossing', waitingRuleId: 'mobility-isaac-east-waiting-south', crossingRuleId: 'mobility-isaac-east-crossing-measurement' }],
    curbs: [{ id: 'north-curbside-access', name: 'curb', zoneRuleId: 'mobility-isaac-north-curbside-lane', role: 'general', dwellThresholdMs: 8000, maximumObservationGapMs: 1000 }] },
  coverage: [{ sourceId: 'cam', name: 'Camera', status: 'live', windowStartNs: at, windowEndNs: at, timestampBasis: 'source-native-sei', observedSeconds: 1, windowSeconds: 300, coverageRatio: 1/300, truncated: false }],
  lineCounts: [{ ruleId: 'cam_sw-northbound-line', name: 'entry', sourceId: 'cam', count: 3, byClass: {}, status: 'partial' }],
  movements: movementIds.map((id, index) => ({ id, name: id, sourceId: 'cam', completedCount: index === 0 ? 1 : 0, incompleteCount: 0, activeCount: 0, byClass: {}, medianTravelSeconds: null, p95TravelSeconds: null, status: 'partial' })),
  queues: [{ id: 'northbound-queue', name: 'queue', sourceId: 'cam', ruleId: 'mobility-isaac-northbound-queue', zoneRuleId: 'mobility-isaac-northbound-queue', status: 'queued', count: 2, observedExtentM: 9.5, extentIsLowerBound: false, extentBasis: 'ground-anchor-distance', tailPositionM: null, stopLineM: [[0,0],[1,0]], upstreamPointM: [0,1], spillbackDistanceM: 10, spillback: false, durationMs: 10, trackIds: [], qualityReasons: [], asOfSourceTimeNs: at, windowMinutes: 5, maximumObservedExtentM: 9.5, currentCountsAvailable: true, membershipComplete: true }],
  crossings: [{ id: 'east-crossing-south-north', name: 'crossing', sourceId: 'cam', waitingRuleId: 'mobility-isaac-east-waiting-south', crossingRuleId: 'mobility-isaac-east-crossing-measurement', status: 'active', waitingCount: 1, crossingCount: 1, oldestObservedWaitMs: null, completedCount: 0, abandonedCount: 0, returnedCount: 0, incompleteCount: 0, waitSampleCount: 0, waitP50Ms: null, waitP95Ms: null, windowMinutes: 5, asOfSourceTimeNs: at, qualityReasons: [], completionBasis: 'observed-far-side-exit', timeBasis: 'source-time', currentCountsAvailable: true, membershipComplete: true }],
  curbs: [{ id: 'north-curbside-access', name: 'curb', sourceId: 'cam', ruleId: 'mobility-isaac-north-curbside-lane', zoneRuleId: 'mobility-isaac-north-curbside-lane', role: 'general', status: 'active', asOfSourceTimeNs: at, windowMinutes: 5, timeBasis: 'source-time', occupancy: 1, observedOccupancy: 1, byClass: {}, arrivalCount: 1, departureCount: 0, turnoverCount: 0, completedVisitCount: 0, incompleteVisitCount: 0, partialVisitCount: 0, occupiedSeconds: 5, completedDwellP50Ms: null, completedDwellP95Ms: null, longestActiveObservedDwellMs: 5000, persistentOccupancyCount: 0, persistentByClass: {}, stoppedCount: 1, stoppedByClass: {}, observedStoppedSeconds: 1, stoppedEvidenceSeconds: 5, activeVisits: [], qualityReasons: [] }],
  obstructions: [{ ruleId: 'cam_sw-blocked-crossing', name: 'south crossing', sourceId: 'cam', episodeCount: 1, completedEpisodes: 0, ongoingEpisodes: 1, unknownEpisodes: 0, blockedSeconds: 4, longestObservedEpisodeSeconds: null, eventIds: [], status: 'partial' }], configurationIssues: [], limitations: []
};
const state = (next = report) => ({ report: next, error: null, receivedAt: new Date().toISOString() });

it('reports compact actual measurements for each scenario', () => {
  expect(scenarioFinding(report, site, scope, 'turning-demand')).toEqual({ primary: '1 completed movement', secondary: 'Left 1 · Straight 0 · Right 0' });
  expect(scenarioFinding(report, site, scope, 'queue-recovery')).toEqual({ primary: '2 vehicles observed in queue', secondary: '9.5 m observed queue' });
  expect(scenarioFinding(report, site, scope, 'pedestrian-service')).toEqual({ primary: '1 person observed crossing', secondary: '1 person observed in approach' });
  expect(scenarioFinding(report, site, scope, 'curb-obstruction')).toEqual({ primary: '1 vehicle observed at curb', secondary: '5 s observed dwell' });
  expect(scenarioFinding(report, site, scope, 'crossing-obstruction')).toEqual({ primary: 'Stopped vehicle detected in crossing', secondary: '4 s observed stopped-zone time' });
});

it('fails closed for previous run, suppressed scopes, a stale request, and request errors', () => {
  (useMobility as jest.Mock).mockReturnValue(state());
  const { rerender } = render(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={scope} />);
  expect(screen.getByLabelText('VSS observes')).toHaveTextContent('2 vehicles observed in queue');
  rerender(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={{ ...scope, runId: 'old' }} />);
  expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
  rerender(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={{ ...scope, suppressed: true }} />);
  expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
  (useMobility as jest.Mock).mockReturnValue({ ...state(), receivedAt: '2000-01-01T00:00:00Z' });
  rerender(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={scope} />);
  expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
  (useMobility as jest.Mock).mockReturnValue({ ...state(), error: 'disconnected' });
  rerender(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={scope} />);
  expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
});

it('refuses stale or missing source evidence, mismatched source time and broken measurement configuration', () => {
  const wait = 'Waiting for camera observations';
  expect(scenarioFinding({ ...report, coverage: [{ ...report.coverage[0], status: 'stale' }] }, site, scope, 'queue-recovery').primary).toBe(wait);
  expect(scenarioFinding(report, { ...site, sources: [] }, scope, 'queue-recovery').primary).toBe(wait);
  expect(scenarioFinding({ ...report, queues: [{ ...report.queues[0], asOfSourceTimeNs: '1' }] }, site, scope, 'queue-recovery').primary).toBe(wait);
  expect(scenarioFinding({ ...report, coverage: [{ ...report.coverage[0], windowEndNs: '1' }] }, site, scope, 'turning-demand').primary).toBe(wait);
  expect(scenarioFinding({ ...report, configurationIssues: [{ kind: 'queue', id: 'northbound-queue', reason: 'disabled' }] }, site, scope, 'queue-recovery').primary).toBe(wait);
  expect(scenarioFinding({ ...report, config: { ...report.config, movements: [] } }, site, scope, 'turning-demand').primary).toBe(wait);
});

it('does not turn interrupted tracks or unavailable status into confirmed clearance', () => {
  const partialQueue = { ...report.queues[0], status: 'unknown' as const, count: 0, countBasis: 'currently-observed' as const, membershipComplete: false };
  expect(scenarioFinding({ ...report, queues: [partialQueue] }, site, scope, 'queue-recovery')).toEqual({ primary: '0 vehicles observed in queue', secondary: 'Some tracks are incomplete' });
  const crossing = { ...report.crossings[0], incompleteCount: 1, membershipComplete: false };
  expect(scenarioFinding({ ...report, crossings: [crossing] }, site, scope, 'pedestrian-service').secondary).toBe('Some journeys are incomplete');
  const stopped = { ...report.obstructions[0], ongoingEpisodes: 0, unknownEpisodes: 1 };
  expect(scenarioFinding({ ...report, obstructions: [stopped] }, site, scope, 'crossing-obstruction').primary).toBe('Stopped-vehicle observation incomplete');
  const curb = { ...report.curbs![0], status: 'unknown' as const, observedOccupancy: 0 };
  expect(scenarioFinding({ ...report, curbs: [curb] }, site, scope, 'curb-obstruction').secondary).toBe('Curb occupancy is incomplete');
});

it('shows a current pedestrian crossing even when an earlier journey is incomplete', () => {
  const row = { ...report.crossings[0], waitingCount: 0, crossingCount: 1, incompleteCount: 2, membershipComplete: false };
  expect(scenarioFinding({ ...report, crossings: [row] }, site, scope, 'pedestrian-service')).toEqual({ primary: '1 person observed crossing', secondary: 'Some journeys are incomplete' });
});

it('checks the owner camera rather than borrowing another live camera for every scenario', () => {
  const otherSite = { ...site, sources: [...site.sources, { ...site.sources[0], id: 'owner' }] };
  const coverage = [...report.coverage, { ...report.coverage[0], sourceId: 'owner', status: 'stale' as const }];
  const candidate = { ...report, coverage,
    movements: report.movements.map(row => ({ ...row, sourceId: 'owner' })),
    queues: report.queues.map(row => ({ ...row, sourceId: 'owner' })),
    crossings: report.crossings.map(row => ({ ...row, sourceId: 'owner' })),
    curbs: report.curbs!.map(row => ({ ...row, sourceId: 'owner' })),
    obstructions: report.obstructions.map(row => ({ ...row, sourceId: 'owner' })) };
  for (const id of ['turning-demand', 'queue-recovery', 'pedestrian-service', 'curb-obstruction', 'crossing-obstruction']) {
    expect(scenarioFinding(candidate, otherSite, scope, id).primary).toBe('Waiting for camera observations');
  }
  // Even two individually live cameras cannot be combined into one turn count.
  const bothLive = { ...candidate, coverage: candidate.coverage.map(row => ({ ...row, status: 'live' as const })), movements: candidate.movements.map((row, index) => index === 0 ? { ...row, sourceId: 'cam' } : row) };
  expect(scenarioFinding(bothLive, otherSite, scope, 'turning-demand').primary).toBe('Waiting for camera observations');
});

it.each(['turning-demand', 'queue-recovery', 'pedestrian-service', 'curb-obstruction', 'crossing-obstruction'])(
  'rejects stale and mismatched scope reports for %s', scenarioId => {
    const current = { ...scope, scenarioId };
    const matchingReport = { ...report, analyticsScope: current };
    (useMobility as jest.Mock).mockReturnValue(state(matchingReport));
    const { rerender, unmount } = render(<ScenarioEvidence site={site} scenarioId={scenarioId} currentScope={current} />);
    expect(screen.getByLabelText('VSS observes')).not.toHaveTextContent('Waiting for camera observations');
    for (const mismatch of [
      { ...current, epoch: 'other-epoch' },
      { ...current, runId: 'other-run' },
      { ...current, scenarioId: 'other-scenario' },
      { ...current, kind: 'normal' },
      { ...current, suppressed: true },
    ]) {
      (useMobility as jest.Mock).mockReturnValue(state({ ...matchingReport, analyticsScope: mismatch }));
      rerender(<ScenarioEvidence site={site} scenarioId={scenarioId} currentScope={current} />);
      expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
    }
    (useMobility as jest.Mock).mockReturnValue({ ...state(matchingReport), receivedAt: new Date(Date.now() - 7000).toISOString() });
    rerender(<ScenarioEvidence site={site} scenarioId={scenarioId} currentScope={current} />);
    expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
    (useMobility as jest.Mock).mockReturnValue({ ...state(matchingReport), error: 'report failed' });
    rerender(<ScenarioEvidence site={site} scenarioId={scenarioId} currentScope={current} />);
    expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
    unmount();
  }
);

it('suppresses stale point-in-time measurements and confirms only observed stopped episodes', () => {
  const wait = 'Waiting for camera observations';
  const oldTime = '1792972800000000000';
  expect(scenarioFinding({ ...report, crossings: [{ ...report.crossings[0], asOfSourceTimeNs: oldTime }] }, site, scope, 'pedestrian-service').primary).toBe(wait);
  expect(scenarioFinding({ ...report, curbs: [{ ...report.curbs![0], asOfSourceTimeNs: oldTime }] }, site, scope, 'curb-obstruction').primary).toBe(wait);
  expect(scenarioFinding({ ...report, queues: [{ ...report.queues[0], currentCountsAvailable: false }] }, site, scope, 'queue-recovery').primary).toBe(wait);
  expect(scenarioFinding({ ...report, crossings: [{ ...report.crossings[0], currentCountsAvailable: false }] }, site, scope, 'pedestrian-service').primary).toBe(wait);
  expect(scenarioFinding({ ...report, obstructions: [{ ...report.obstructions[0], ongoingEpisodes: 0, completedEpisodes: 0 }] }, site, scope, 'crossing-obstruction').primary).toBe('Watching the crossing for stopped vehicles');
  expect(scenarioFinding({ ...report, obstructions: [{ ...report.obstructions[0], ongoingEpisodes: 0, completedEpisodes: 1, unknownEpisodes: 1 }] }, site, scope, 'crossing-obstruction').primary).toBe('Stopped-vehicle observation incomplete');
});

it('reports directional completed turns while flagging interrupted alternative histories without adding them', () => {
  const movements = report.movements.map((row, index) => ({ ...row, completedCount: [1, 2, 3][index], incompleteCount: 2 }));
  expect(scenarioFinding({ ...report, movements }, site, scope, 'turning-demand')).toEqual({
    primary: '6 completed movements', secondary: 'Left 1 · Straight 2 · Right 3 · Some journeys incomplete',
  });
});

it('expires a last received finding even when neither report nor parent updates', () => {
  jest.useFakeTimers();
  try {
    (useMobility as jest.Mock).mockReturnValue(state());
    render(<ScenarioEvidence site={site} scenarioId="queue-recovery" currentScope={scope} />);
    expect(screen.getByLabelText('VSS observes')).toHaveTextContent('2 vehicles observed in queue');
    act(() => jest.advanceTimersByTime(6002));
    expect(screen.getByLabelText('VSS observes')).toHaveTextContent('Waiting for camera observations');
  } finally { jest.useRealTimers(); }
});

it('shows an observed approach crossing without mislabelling it as a completed turn', () => {
 const movements=report.movements.map(row=>({...row,completedCount:0,incompleteCount:1}));
 expect(scenarioFinding({...report,movements},site,scope,'turning-demand')).toEqual({primary:'3 approach line crossings',secondary:'0 completed turns · Some journeys incomplete'});
 expect(scenarioFinding({...report,movements,lineCounts:[{...report.lineCounts[0],sourceId:'foreign'}]},site,scope,'turning-demand').primary).toBe('0 completed movements');
});
