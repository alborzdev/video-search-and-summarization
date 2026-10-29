// SPDX-License-Identifier: MIT
import type { AnalyticsScope, CitySnapshot, CitySource } from './types';

/** In-place resets keep the RTSP session; the captured analytics epoch must also match. */
export function matchesObservationScope(snapshot: CitySnapshot | null | undefined, latest: CitySource | undefined): boolean {
  const source = snapshot?.sources.find(item => item.id === latest?.id) ?? (snapshot?.sources.length === 1 ? snapshot.sources[0] : undefined);
  const expected = latest?.analyticsScope?.epoch ?? null;
  const sourceEpoch = source?.analyticsScope?.epoch ?? null;
  const snapshotEpoch = snapshot?.analyticsScope?.epoch ?? null;
  return sourceEpoch === expected && snapshotEpoch === expected && (source?.trackingEpoch ?? null) === (latest?.trackingEpoch ?? null);
}

/** Historical events keep their own scope; missing legacy scope is never this run. */
export function analyticsScopeLabel(scope: AnalyticsScope | null | undefined, historical = false): string {
  if (!scope) return historical ? 'Earlier / unspecified scope' : 'Observation scope unavailable';
  if (scope.kind === 'historical-per-camera') return 'Historical scope by camera';
  const at = scope.startedAt && Number.isFinite(Date.parse(scope.startedAt)) ?
    new Date(scope.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : null;
  if (scope.suppressed) return 'Preparing — analytics paused';
  if (scope.kind === 'scenario') return historical ? `Prepared run${at ? ` · ${at}` : ''}` : 'This prepared run';
  if (scope.kind === 'normal') return `Normal traffic${at ? ` since ${at}` : ''}`;
  return historical ? 'Earlier / unspecified scope' : 'Observation scope unavailable';
}
