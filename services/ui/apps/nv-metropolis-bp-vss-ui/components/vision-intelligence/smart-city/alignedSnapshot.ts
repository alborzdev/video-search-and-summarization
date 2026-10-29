// SPDX-License-Identifier: MIT
import type { CitySite, CitySnapshot } from './types';
import { calibrationKey } from './processedPreview';
import { matchesObservationScope } from './analyticsScope';
/** Join each camera's already aligned observations; no spatial fusion or ID association. */
export function displaySnapshot(site: CitySite | null, latest: CitySnapshot | null, frames: Record<string, CitySnapshot>, now = Date.now()): CitySnapshot | null {
  if (!site || !latest || site.mode !== 'live' || !site.sources.length) return latest;
  const processed = site.sources.some(source => frames[source.id]?.presentedPreview || frames[source.id]?.processedPreviewUnavailable);
  if (!processed && !site.sources.every(source => source.browserClockVerified)) return latest;
  const valid = site.sources.flatMap(source => {
    const frame = frames[source.id]; const clock = frame?.sources.find(item => item.id === source.id);
    const latestSource = latest.sources.find(item => item.id === source.id);
    if (!matchesObservationScope(frame, latestSource)) return [];
    const requested = frame?.requestedSourceTimeNs;
    if (frame?.processedPreviewUnavailable) return [];
    const preview = frame?.presentedPreview;
    if (preview) {
      if (!clock || frame.siteId !== site.id || frame.siteRevision !== site.revision || frame.mode !== site.mode || clock.width !== source.width || clock.height !== source.height ||
          calibrationKey(clock) !== calibrationKey(source) ||
          preview.sourceId !== source.id || preview.sessionId !== clock.sessionId || preview.sequence !== String(clock.sequence) || preview.sourceTimeNs !== clock.lastSourceTimeNs || now - preview.presentedAtMs < 0 || now - preview.presentedAtMs > 2000 || !latestSource?.sessionId || latestSource.sessionId !== preview.sessionId) return [];
      return [{ sourceId: source.id, frame, clock }];
    }
    if (!source.browserClockVerified || !frame || !clock?.clockAligned || clock.timestampBasis !== 'source-rtcp' || !requested || !clock.lastSourceTimeNs || now - Date.parse(frame.timestamp) > 1000 || Math.abs(Number(requested) - Number(clock.lastSourceTimeNs)) > 160_000_000) return [];
    return [{ sourceId: source.id, frame, clock }];
  });
  const metrics = valid.flatMap(({ sourceId, frame }) => frame.metrics.filter(metric => frame.rules.some(rule => rule.id === metric.ruleId && rule.sourceId === sourceId)));
  return { ...latest,
    tracks: valid.flatMap(({ sourceId, frame }) => frame.tracks.filter(track => track.sourceId === sourceId)),
    sources: site.sources.map(source => valid.find(item => item.sourceId === source.id)?.clock ?? { ...source, status: 'waiting-for-frame-clock' }),
    events: valid.flatMap(({ sourceId, frame }) => frame.events.filter(event => event.sourceId === sourceId)),
    metrics,
    rules: processed ? valid.flatMap(({ sourceId, frame }) => frame.rules.filter(rule => rule.sourceId === sourceId)) : latest.rules,
    zones: processed ? valid.flatMap(({ sourceId, frame }) => frame.zones.filter(zone => zone.sourceId === sourceId)) : latest.zones.map(zone => { const metric = metrics.find(item => item.ruleId === zone.id); return { ...zone, active: metric?.status === 'active', occupancy: metric?.occupancy ?? null }; }),
    videoFrameMatched: valid.length === site.sources.length,
    videoClockAligned: !processed && valid.length === site.sources.length,
  };
}
