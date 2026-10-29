// SPDX-License-Identifier: MIT
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CityMode, CityAnalyzedFrame, CitySite, CitySnapshot, CitySource, CityRule, RuleSet } from './types';
import { calibrationKey, matchesPreviewContext, previewContext } from './processedPreview';
import { FrameRequestQueue } from './FrameRequestQueue';
import { useDocumentVisible } from './useDocumentVisible';
import { matchesObservationScope } from './analyticsScope';
import { subscribeCityEvent } from './cityEvents';

export const CITY_API = '/api/vision/city';
export async function cityRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${CITY_API}/${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  let body: any;
  try { body = await response.json(); }
  catch { if (init?.signal?.aborted) throw new DOMException('City request was cancelled.', 'AbortError'); throw new Error('The city service returned an unreadable response.'); }
  if (init?.signal?.aborted) throw new DOMException('City request was cancelled.', 'AbortError');
  if (!body || typeof body !== 'object') throw new Error('The city service returned an unreadable response.');
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.join('.') ?? 'Request'}: ${item.msg ?? 'invalid'}`).join('; ') : body.error || body.detail;
    throw new Error(typeof detail === 'string' ? detail.slice(0, 1200) : `City service returned ${response.status}.`);
  }
  return body as T;
}
export function siteMatchesSnapshot(site: CitySite, snapshot: CitySnapshot): boolean {
  return site.id === snapshot.siteId && site.mode === snapshot.mode &&
    (typeof snapshot.siteRevision !== 'number' || snapshot.siteRevision === site.revision) &&
    sourceConfiguration(site.sources) === sourceConfiguration(snapshot.sources);
}
function sourceConfiguration(sources: CitySource[]): string {
  return JSON.stringify([...sources].sort((a, b) => a.id.localeCompare(b.id)).map(source =>
    [source.id, source.width, source.height, source.mediaUrl ?? null, source.vssSensorId ?? null, calibrationKey(source)]));
}
function siteConfiguration(site: CitySite): string {
  return JSON.stringify([site.id, site.mode, site.revision, sourceConfiguration(site.sources)]);
}
function snapshotConfiguration(snapshot: CitySnapshot): string {
  return JSON.stringify([snapshot.siteId, snapshot.mode, snapshot.siteRevision, sourceConfiguration(snapshot.sources)]);
}
export function useCity() {
  const visible = useDocumentVisible();
  const [site, setSite] = useState<CitySite | null>(null);
  const [snapshot, setSnapshot] = useState<CitySnapshot | null>(null);
  const [sourceSnapshots, setSourceSnapshots] = useState<Record<string, CitySnapshot>>({});
  const [rules, setRules] = useState<RuleSet>({ rules: [], revision: 0 });
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewGeneration, setPreviewGeneration] = useState(0);
  const latestSnapshot = useRef<CitySnapshot | null>(null);
  const historyQueue = useRef<FrameRequestQueue<number> | null>(null);
  const replayTime = useRef<number | null>(null);
  const siteMode = useRef<CityMode | null>(null);
  const sourceQueues = useRef(new Map<string, FrameRequestQueue<number>>());
  const staticSite = useRef<CitySite | null>(null);
  const staticController = useRef<AbortController | null>(null);
  const staticGeneration = useRef(0);
  const previewGenerationRef = useRef(0);
  const snapshotUpdates = useRef(0);
  const rulesController = useRef<AbortController | null>(null);
  const staticTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastStaticRefresh = useRef(0);
  const staticFailures = useRef(0);
  const configurationPending = useRef(false);
  const announcedConfiguration = useRef<string | null>(null);
  const scheduleRefreshRef = useRef<() => void>(() => {});
  if (!historyQueue.current) historyQueue.current = new FrameRequestQueue(async (seconds, signal) => {
    try {
      const value = await cityRequest<CitySnapshot>(`snapshot?mediaTimeSeconds=${seconds.toFixed(4)}`, { signal });
      if (!signal.aborted) { setSnapshot(value); setError(null); }
    } catch (cause) { if (!signal.aborted) setError(cause instanceof Error ? cause.message : 'Replay observations are unavailable.'); }
  }, () => setError('Replay observations timed out. Retrying the latest frame.'));
  const abortFrames = useCallback(() => {
    historyQueue.current?.clear(); sourceQueues.current.forEach(queue => queue.clear()); sourceQueues.current.clear();
  }, []);
  const invalidatePreviews = useCallback(() => {
    setPreviewGeneration(++previewGenerationRef.current);
    latestSnapshot.current = null; abortFrames(); setSourceSnapshots({});
  }, [abortFrames]);
  const discardObsoletePresentedFrames = useCallback((value: CitySnapshot) => {
    setSourceSnapshots(current => {
      let retained = current;
      for (const [sourceId, presented] of Object.entries(current)) {
        if (!presented.presentedPreview) continue;
        const source = value.sources.find(item => item.id === sourceId);
        if (!source?.sessionId || source.sessionId !== presented.presentedPreview.sessionId || !matchesObservationScope(presented, source)) {
          if (retained === current) retained = { ...current };
          // Keep the processed-preview marker so the map cannot fall back
          // to unpaired latest detections while this camera reacquires.
          retained[sourceId] = { ...presented, presentedPreview: undefined, processedPreviewUnavailable: true, tracks: [], events: [], metrics: [] };
        }
      }
      return retained;
    });
  }, []);
  const refresh = useCallback(async () => {
    const generation = ++staticGeneration.current;
    const updatesAtStart = snapshotUpdates.current;
    rulesController.current?.abort('configuration-changed'); rulesController.current = null; setSaving(false);
    staticController.current?.abort('superseded');
    if (staticTimer.current !== null) { clearTimeout(staticTimer.current); staticTimer.current = null; }
    const controller = new AbortController(); staticController.current = controller;
    const timeout = setTimeout(() => controller.abort('timeout'), 10_000);
    lastStaticRefresh.current = performance.now();
    // A state refresh is a background read. Keep valid paired frames, media
    // peers and SSE updates alive until a configuration change is confirmed.
    if (!staticSite.current || configurationPending.current) { configurationPending.current = true; setLoading(true); }
    try {
      const init = { signal: controller.signal };
      const [nextSite, nextSnapshot, nextRules] = await Promise.all([
        cityRequest<CitySite>('site', init), cityRequest<CitySnapshot>('snapshot', init), cityRequest<RuleSet>('rules', init),
      ]);
      if (controller.signal.aborted || generation !== staticGeneration.current) return;
      const changed = !staticSite.current || siteConfiguration(staticSite.current) !== siteConfiguration(nextSite);
      if (changed) invalidatePreviews();
      siteMode.current = nextSite.mode; staticSite.current = nextSite; announcedConfiguration.current = null;
      if (nextSite.mode === 'live') replayTime.current = null;
      // SSE may have advanced sessions/scopes while the HTTP reads were in
      // flight. Never replace that newer observation with the captured read.
      const streamed = latestSnapshot.current;
      const accepted = !changed && snapshotUpdates.current !== updatesAtStart && streamed && siteMatchesSnapshot(nextSite, streamed)
        ? streamed : siteMatchesSnapshot(nextSite, nextSnapshot) ? nextSnapshot : null;
      const compatible = accepted !== null;
      if (!compatible) {
        if (!changed && !configurationPending.current) invalidatePreviews();
        setSnapshot(null);
      }
      latestSnapshot.current = accepted;
      configurationPending.current = !compatible; staticFailures.current = 0;
      if (accepted) discardObsoletePresentedFrames(accepted);
      setSite(nextSite);
      if (replayTime.current === null || changed) setSnapshot(accepted);
      setRules(accepted && typeof accepted.rulesRevision === 'number' && accepted.rulesRevision > nextRules.revision
        ? { rules: accepted.rules, revision: accepted.rulesRevision } : nextRules);
      setError(null);
    } catch (cause) {
      if (generation === staticGeneration.current && (!controller.signal.aborted || controller.signal.reason === 'timeout')) {
        staticFailures.current += 1; setError(controller.signal.reason === 'timeout' ? 'City configuration request timed out. Retry the connection.' : cause instanceof Error ? cause.message : 'City service is unavailable.');
        // Promise.all fails before its sibling fetches finish. Stop them before retrying.
        if (!controller.signal.aborted) controller.abort('request-failed');
      }
    } finally {
      clearTimeout(timeout);
      if (generation === staticGeneration.current) {
        staticController.current = null;
        const retryable = !controller.signal.aborted || controller.signal.reason === 'timeout' || controller.signal.reason === 'request-failed';
        // Keep invalid configurations covered throughout retries. Otherwise
        // each failed read briefly re-enables obsolete camera peers.
        if (retryable) setLoading(Boolean(staticSite.current && configurationPending.current));
        if ((configurationPending.current || staticFailures.current) && retryable) scheduleRefreshRef.current();
      }
    }
  }, [invalidatePreviews, discardObsoletePresentedFrames]);
  const scheduleRefresh = useCallback(() => {
    if (staticTimer.current !== null || (staticController.current && !staticController.current.signal.aborted)) return;
    // Do not postpone on every video frame. At most one static fetch per second.
    const backoff = staticFailures.current ? Math.min(15_000, 1000 * 2 ** Math.min(staticFailures.current, 4)) : 0;
    const delay = Math.max(250, backoff, 1000 - (performance.now() - lastStaticRefresh.current));
    staticTimer.current = setTimeout(() => { staticTimer.current = null; void refresh(); }, delay);
  }, [refresh]);
  useEffect(() => {
    if (!visible) { setConnected(false); return; }
    scheduleRefreshRef.current = scheduleRefresh;
    void refresh();
    let active = true;
    const update = (event: MessageEvent<string>) => {
      if (!active) return;
      try {
        const value = JSON.parse(event.data) as CitySnapshot;
        if (!value || !Array.isArray(value.tracks) || !Array.isArray(value.sources)) return;
        setConnected(true);
        const currentSite = staticSite.current;
        if (!currentSite) { scheduleRefresh(); return; }
        if (!siteMatchesSnapshot(currentSite, value)) {
          const announced = snapshotConfiguration(value);
          if (announced !== announcedConfiguration.current) { announcedConfiguration.current = announced; staticController.current?.abort('configuration-changed'); }
          if (!configurationPending.current) { configurationPending.current = true; invalidatePreviews(); setSnapshot(null); setLoading(true); }
          scheduleRefresh(); return;
        }
        if (configurationPending.current) return;
        ++snapshotUpdates.current;
        latestSnapshot.current = value;
        discardObsoletePresentedFrames(value);
        setError(null);
        if (typeof value.rulesRevision === 'number') setRules(current => current.revision === value.rulesRevision ? current : { rules: value.rules, revision: value.rulesRevision! });
        if (replayTime.current === null) setSnapshot(value);
      } catch { setError('The city stream sent an invalid update.'); }
    };
    const subscriptions = [subscribeCityEvent('message', update as EventListener), subscribeCityEvent('snapshot', update as EventListener),
      subscribeCityEvent('open', () => { if (active) setConnected(true); }),
      subscribeCityEvent('error', () => { if (active) setConnected(false); })];
    return () => {
      active = false;
      subscriptions.forEach(stop => stop()); ++staticGeneration.current; configurationPending.current = true; staticController.current?.abort('unmounted'); invalidatePreviews();
      rulesController.current?.abort('unmounted'); rulesController.current = null;
      if (staticTimer.current !== null) { clearTimeout(staticTimer.current); staticTimer.current = null; }
    };
  }, [refresh, scheduleRefresh, invalidatePreviews, discardObsoletePresentedFrames, visible]);
  const atMediaTime = useCallback((seconds: number, force = false) => {
    if (configurationPending.current || siteMode.current === 'live' || !Number.isFinite(seconds) || seconds < 0) return;
    replayTime.current = seconds;
    historyQueue.current?.enqueue(seconds, force);
  }, []);
  const atSourceTime = useCallback((sourceId: string, unixMs: number) => {
    if (configurationPending.current || !Number.isFinite(unixMs) || unixMs <= 0 || !Number.isSafeInteger(Math.round(unixMs * 1000))) return;
    let queue = sourceQueues.current.get(sourceId);
    if (!queue) {
      queue = new FrameRequestQueue(async (time, signal) => {
        const nanoseconds = BigInt(Math.round(time * 1000)) * BigInt(1000);
        try {
          const value = await cityRequest<CitySnapshot>(`snapshot?sourceId=${encodeURIComponent(sourceId)}&sourceTimeNs=${nanoseconds.toString()}`, { signal });
          if (!signal.aborted) setSourceSnapshots(current => ({ ...current, [sourceId]: { ...value, requestedSourceTimeNs: nanoseconds.toString() } }));
        } catch { /* Missing source clocks suppress overlays; shared source health remains visible. */ }
      });
      sourceQueues.current.set(sourceId, queue);
    }
    queue.enqueue(unixMs);
  }, []);
  const presentProcessedFrame = useCallback((sourceId: string, frame: CityAnalyzedFrame | null, configurationKey?: string) => {
    const site = staticSite.current; const source = site?.sources.find(item => item.id === sourceId);
    if (configurationPending.current || siteMode.current !== 'live' || !site || !source) return;
    const context = previewContext(site, source, previewGenerationRef.current);
    const latestSource = latestSnapshot.current?.sources.find(item => item.id === sourceId);
    if (configurationKey !== context.configurationKey || frame && (!matchesPreviewContext(frame, context, latestSource?.sessionId) || !matchesObservationScope(frame.snapshot, latestSource))) return;
    sourceQueues.current.get(sourceId)?.clear(); sourceQueues.current.delete(sourceId);
    setSourceSnapshots(current => {
      if (!frame) {
        if (!current[sourceId]?.presentedPreview) return current;
        return { ...current, [sourceId]: { ...current[sourceId], presentedPreview: undefined, processedPreviewUnavailable: true, tracks: [], events: [], metrics: [] } };
      }
      return { ...current, [sourceId]: { ...frame.snapshot, requestedSourceTimeNs: frame.sourceTimeNs,
        presentedPreview: { sourceId, sessionId: frame.sessionId, sequence: String(frame.sequence), sourceTimeNs: frame.sourceTimeNs, presentedAtMs: Date.now(), configurationKey } } };
    });
  }, []);
  const saveRules = useCallback(async (nextRules: CityRule[], expectedRevision = rules.revision) => {
    if (configurationPending.current || !staticSite.current) throw new Error('Wait for the current city configuration before saving rules.');
    const generation = staticGeneration.current; const controller = new AbortController();
    rulesController.current?.abort('superseded'); rulesController.current = controller;
    const timeout = setTimeout(() => controller.abort('timeout'), 10_000);
    setSaving(true);
    try {
      const saved = await cityRequest<RuleSet>('rules', { signal: controller.signal, method: 'PUT', body: JSON.stringify({ rules: nextRules, expectedRevision }) });
      if (controller.signal.aborted || generation !== staticGeneration.current || rulesController.current !== controller) throw new DOMException('The rule save belongs to a previous city configuration.', 'AbortError');
      setRules(saved); setError(null); return saved;
    } catch (cause) {
      if (controller.signal.aborted && controller.signal.reason !== 'timeout' || generation !== staticGeneration.current || rulesController.current !== controller) throw new DOMException('The rule save was cancelled.', 'AbortError');
      const message = controller.signal.reason === 'timeout' ? 'Saving rules timed out. Refresh rules before retrying; the service may have accepted the change.' : cause instanceof Error ? cause.message : 'Rules could not be saved.';
      setError(message); throw new Error(message);
    } finally {
      clearTimeout(timeout);
      if (rulesController.current === controller) { rulesController.current = null; setSaving(false); }
    }
  }, [rules.revision]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (replayTime.current !== null) atMediaTime(replayTime.current); }, 500);
    return () => window.clearInterval(timer);
  }, [atMediaTime]);
  return { site, snapshot, sourceSnapshots, previewGeneration, rules, error, connected, loading, saving, refresh, atMediaTime, atSourceTime, presentProcessedFrame, saveRules };
}
