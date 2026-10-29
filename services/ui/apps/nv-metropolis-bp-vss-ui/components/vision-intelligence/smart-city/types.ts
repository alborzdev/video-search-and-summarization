// SPDX-License-Identifier: MIT
export type Point = [number, number];
export type CityWorkspaceView = 'overview' | 'measurements' | 'search' | 'edge';
export type CityMode = 'live' | 'recorded-inference' | 'fixture-replay';
export interface AnalyticsScope {
  epoch?: string; kind: string; runId?: string | null; scenarioId?: string | null;
  startedAt?: string; suppressed?: boolean; sources?: Record<string, AnalyticsScope | null>;
}
export interface NativeSeiClockEvidence {
  schemaVersion: 'city.source-native-sei.v1'; method: 'isaac-native-sei-wall-capture';
  correlation: 'exact-au-pts'; captureTimeNs: string; auPtsNs: string; frameCounter: string;
}
export interface CitySource {
  id: string; name: string; width: number; height: number; mediaUrl?: string;
  vssSensorId?: string; sessionId?: string; status?: string; mediaTimeSeconds?: number;
  durationSeconds?: number; fixtureDurationSeconds?: number;
  timestampBasis?: string; lastSourceTimeNs?: string; clockAligned?: boolean;
  sourceClockMode?: 'source-rtcp' | 'source-native-sei'; sourceClockEvidence?: NativeSeiClockEvidence | null;
  sequence?: string | number; sourceSessionId?: string;
  analyticsScope?: AnalyticsScope | null; trackingEpoch?: string | null;
  modelRevision?: string; currentModelRevision?: string;
  processedPreview?: { status: 'ready' | 'waiting' | 'stale'; available: boolean; transport?: 'jpeg' | 'webrtc' };
  mediaTimeBasis?: string; rawSourcePtsNs?: string;
  browserClockVerified?: boolean;
  ingestAgeSeconds?: number | null; sourceClockAgeSeconds?: number | null; sourceClockProgressRatio?: number | null;
  sourceClockPrecision?: 'unverified';
  sourceClockStatus?: 'delayed-or-unsynchronized' | 'unverified-source-rtcp' | 'unverified-source-native-sei' | 'unavailable';
  imageToGroundHomography?: number[][]; calibrationRevision?: string;
  classImageToGroundHomographies?: Record<string, number[][]>;
  validGroundPolygon?: Point[];
  /** Static geometry exported with this exact calibration, never inferred from detections. */
  cameraPositionWorldM?: [number, number, number];
  groundCoverageM?: Point[];
  T_cv_from_site?: number[][];
}
export interface CitySite {
  id: string; name: string; revision: number; mode: CityMode; sources: CitySource[];
  map: { bounds: [number, number, number, number]; imageUrl?: string;
    roads: { id: string; points: Point[]; width?: number }[];
    buildings: { id: string; points: Point[] }[] };
}
export interface CityTrack {
  id: string; sourceId: string; sessionId: string; localTrackId: string;
  globalTrackId?: string | null; class: string; bboxPx: [number, number, number, number];
  mapAssociation?: { method: 'mv3dt-demo'; globalTrackId: string; fusionEpoch: string; targetId: string; classPolicy?: 'car-truck-family-v1';
    positionM?: [number, number]; positionBasis?: 'native-mv3dt-world-foot';
    calibrationRevision: string; visibility: number; sourceClockBasis: 'source-rtcp' | 'source-native-sei' } | null;
  modelRevision?: string | null;
  positionM: Point | null; confidence: number | null; stale: boolean; observedThisFrame?: boolean; velocityMps?: Point | null;
  mediaTimeSeconds?: number; sourceTimeNs?: number | string;
  trail: { positionM: Point; sourceTimeNs: number | string }[];
}
export interface CityRule {
  calibrationRevision?: string;
  id: string; name: string; kind: string; sourceId: string; classes: string[];
  geometry: { space: 'image-normalized' | 'site-metres'; points: Point[]; direction?: Point };
  conditions: { minimumDurationMs?: number; clearAfterMs?: number; countThreshold?: number;
    speedBelowMps?: number; maximumObservationGapMs?: number };
  enabled: boolean; revision: number;
}
export interface CityEvidence {
  status: string; sourceId?: string; mediaTimeSeconds?: number; startMediaTimeSeconds?: number; triggerMediaTimeSeconds?: number; clipUrl?: string | null;
  startTimeNs?: number | string; endTimeNs?: number | string;
}
export interface CityEvent {
  analyticsScope?: AnalyticsScope | null;
  id: string; ruleId: string; ruleName: string; kind: string; sourceId: string;
  sessionId: string; trackIds: string[]; state: 'active' | 'cleared' | 'unknown';
  startedAt: string; triggeredAt: string; endedAt?: string | null; message: string;
  metrics: Record<string, number | string | null>; evidence?: CityEvidence; mode: CityMode;
  stateReason?: string | null;
  stopEvidenceStatus?: 'confirmed' | 'pending' | 'clearing' | 'unknown' | 'cleared';
  stopEvidenceAtNs?: string | null;
  latestMetrics?: Record<string, number | string | null>;
}
export interface CityMetric {
  ruleId: string; count?: number; activeEventCount?: number; totalCrossings?: number;
  occupancy: number | null; oldestDwellMs?: number; status: string; timestamp?: string;
  evidenceReasons?: string[];
}
export interface CityZone {
  id: string; name: string; sourceId: string; kind: string; geometry: CityRule['geometry'];
  enabled: boolean; active: boolean; occupancy: number | null;
}
export interface CitySnapshot {
  analyticsScope?: AnalyticsScope | null;
  siteId: string; mode: CityMode; timestamp: string; sequence: number | string;
  rulesRevision?: number; siteRevision?: number;
  requestedSourceTimeNs?: string; videoClockAligned?: boolean;
  sources: CitySource[]; tracks: CityTrack[]; zones: CityZone[]; rules: CityRule[];
  events: CityEvent[]; metrics: CityMetric[]; setupRequired?: boolean; awaitingObservations?: boolean;
  presentedPreview?: { sourceId: string; sessionId: string; sequence: string; sourceTimeNs: string; presentedAtMs: number; configurationKey?: string };
  videoFrameMatched?: boolean;
  processedPreviewUnavailable?: boolean;
  association?: { mode: string; globalFusionEnabled: boolean;
    mapFusion?: { mode: string; enabled: boolean; experimental: boolean; qualified: boolean; positionBasis: string } };
}
export interface CityAnalyzedFrame {
  sourceId: string; sourceSessionId: string;
  sessionId: string; sequence: string | number; sourceTimeNs: string; timestampBasis: string; modelRevision: string;
  sourceClockEvidence?: NativeSeiClockEvidence | null;
  image: { width: number; height: number };
  snapshot: CitySnapshot;
}
export interface CityPreviewFrame extends CityAnalyzedFrame {
  schemaVersion: 'city.preview.v1';
  image: { width: number; height: number; jpegWidth: number; jpegHeight: number; mimeType: 'image/jpeg' };
  provenance: { kind: 'native-post-inference-exact-frame'; correlation: 'source-session-sequence-time'; clockAlignment: 'source-frame-exact'; browserClockVerified: false };
}
export interface CityVideoFrame extends CityAnalyzedFrame {
  schemaVersion: 'city.video-frame.v1'; manifestKey: string;
  provenance: { kind: 'native-webrtc-exact-frame'; correlation: 'source-session-sequence-time-rtp'; clockAlignment: 'source-frame-exact'; browserClockVerified: false };
  transport: { kind: 'webrtc-rtp'; rtpTimestamp: number; clockRate: 90000; codec: 'H264'; encoder: 'nvenc-h264' };
}
export interface CityPreviewContext {
  siteId: string; siteRevision: number; mode: CityMode; sourceId: string;
  width: number; height: number; geometryKey: string; configurationKey: string;
}
export interface RuleSet { rules: CityRule[]; revision: number; }
export const MODE_LABELS: Record<CityMode, string> = {
  live: 'Live inference', 'recorded-inference': 'Recorded video · real inference',
  'fixture-replay': 'Labelled fixture replay',
};
