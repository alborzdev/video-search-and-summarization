// SPDX-License-Identifier: MIT
import type { AnalyticsScope, CityMode, Point } from './types';
export type MobilityWindow = 1 | 5 | 15;
export type MobilityMeasureStatus = 'ready' | 'partial' | 'unavailable';
export interface MobilityMovementConfig { id: string; name: string; entryRuleId: string; exitRuleId: string; classes?: string[]; }
export interface MobilityCrossingConfig { id: string; name: string; waitingRuleId: string; crossingRuleId: string; }
export interface MobilityQueueConfig { id: string; name: string; zoneRuleId: string; stopLine: [Point, Point]; upstreamPoint: Point; spillbackDistanceM: number; }
export type MobilityCurbRole = 'general' | 'loading' | 'bus-stop' | 'cycle-lane';
export interface MobilityCurbConfig { id: string; name: string; zoneRuleId: string; role: MobilityCurbRole; dwellThresholdMs: number; maximumObservationGapMs: number; }
export interface MobilityConfig { revision: number; movements: MobilityMovementConfig[]; crossings: MobilityCrossingConfig[]; queues: MobilityQueueConfig[]; curbs?: MobilityCurbConfig[]; }
export interface MobilityConfigInput { expectedRevision?: number; movements: MobilityMovementConfig[]; crossings: MobilityCrossingConfig[]; queues: MobilityQueueConfig[]; curbs?: MobilityCurbConfig[]; }
export interface MobilityCoverage { sourceId: string; name: string; status: 'live' | 'stale' | 'awaiting-observations'; windowStartNs: string | null; windowEndNs: string | null; timestampBasis: string | null; observedSeconds: number; windowSeconds: number; coverageRatio: number; truncated: boolean; }
export interface MobilityLineCount { ruleId: string; name: string; sourceId: string; count: number; byClass: Record<string, number>; status: MobilityMeasureStatus; }
export interface MobilityMovement { id: string; name: string; sourceId: string; completedCount: number; incompleteCount: number; activeCount: number; byClass: Record<string, number>; medianTravelSeconds: number | null; p95TravelSeconds: number | null; status: MobilityMeasureStatus; }
export interface MobilityObstruction { ruleId: string; name: string; sourceId: string; episodeCount: number; completedEpisodes: number; ongoingEpisodes: number; unknownEpisodes: number; blockedSeconds: number; longestObservedEpisodeSeconds: number | null; eventIds: string[]; status: MobilityMeasureStatus; }
export interface MobilityMembershipEvidence {
  countBasis?: 'currently-observed'; currentCountsAvailable?: boolean; membershipComplete?: boolean;
  pendingTrackCount?: number; oldestPendingGapMs?: number | null;
  unresolvedHistoricalTrackCount?: number; oldestLostTrackAgeMs?: number | null;
  lostTrackCount?: number; lossEvidenceRetentionSeconds?: number;
}
export interface MobilityQueue extends MobilityMembershipEvidence {
  id: string; name: string; sourceId: string; ruleId: string; zoneRuleId: string;
  status: 'unknown' | 'empty' | 'candidate' | 'queued' | 'spillback' | 'disabled';
  count: number; observedExtentM: number | null; extentIsLowerBound: boolean; extentBasis: 'ground-anchor-distance';
  tailPositionM: Point | null; stopLineM: [Point, Point]; upstreamPointM: Point; spillbackDistanceM: number;
  spillback: boolean | null; durationMs: number; trackIds: string[]; qualityReasons: string[];
  asOfSourceTimeNs: string; windowMinutes: MobilityWindow; maximumObservedExtentM: number | null;
}
export interface MobilityCrossing extends MobilityMembershipEvidence {
  id: string; name: string; sourceId: string; waitingRuleId: string; crossingRuleId: string;
  status: 'active' | 'unknown' | 'disabled'; waitingCount: number; crossingCount: number;
  oldestObservedWaitMs: number | null; completedCount: number; abandonedCount: number; returnedCount: number; incompleteCount: number;
  waitSampleCount: number; waitP50Ms: number | null; waitP95Ms: number | null; windowMinutes: MobilityWindow;
  asOfSourceTimeNs: string; qualityReasons: string[]; completionBasis: 'observed-far-side-exit'; timeBasis: 'source-time';
  firstSeenWaitingCount?: number; lowerBoundWaitP50Ms?: number | null; briefGapRecoveredWaitCount?: number;
}
export interface MobilityCurb {
  id: string; name: string; sourceId: string; ruleId: string; zoneRuleId: string; role: MobilityCurbRole;
  status: 'active' | 'empty' | 'unknown'; asOfSourceTimeNs: string | null; windowMinutes: MobilityWindow; timeBasis: 'source-time';
  occupancy: number | null; observedOccupancy: number; occupancyIsLowerBound?: boolean; pendingTrackCount?: number; lostTrackCount?: number; byClass: Record<string, number>;
  arrivalCount: number; departureCount: number; turnoverCount: number; completedVisitCount: number; incompleteVisitCount: number; partialVisitCount: number;
  occupiedSeconds: number; completedDwellP50Ms: number | null; completedDwellP95Ms: number | null; longestActiveObservedDwellMs: number | null;
  persistentOccupancyCount: number | null; persistentByClass: Record<string, number>; stoppedCount: number | null; stoppedByClass: Record<string, number>; observedStoppedSeconds: number | null; stoppedEvidenceSeconds: number;
  activeVisits: { trackId: string; class: string; observedDwellMs: number; partial: boolean; stopped: boolean | null }[];
  qualityReasons: string[];
}
export interface MobilityReport {
  analyticsScope?: AnalyticsScope | null;
  schemaVersion: 'city.mobility.v1'; siteId: string; siteRevision: number; mode: CityMode; configRevision: number;
  windowMinutes: MobilityWindow; timeBasis: 'per-camera-source-time'; globalFusionEnabled: false;
  config: MobilityConfig; coverage: MobilityCoverage[]; lineCounts: MobilityLineCount[]; movements: MobilityMovement[];
  obstructions: MobilityObstruction[]; queues: MobilityQueue[]; crossings: MobilityCrossing[]; curbs?: MobilityCurb[];
  configurationIssues: { kind: string; id: string; reason: string }[]; limitations: string[];
}
export interface MobilityConfigResponse { config: MobilityConfig; configRevision: number; }
