// SPDX-License-Identifier: MIT
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { IconDotsVertical, IconVideoOff } from '@tabler/icons-react';
import type { CityMode, CityPreviewContext, CityAnalyzedFrame, CityVideoFrame, CityRule, CitySnapshot, CitySource, CityTrack, Point } from './types';
import { isAligned, normalizedPoint, objectName, ruleImagePoints, safeMediaUrl } from './geometry';
import { cameraLabelLayout, type CameraLabelLayout } from './cameraLabelLayout';
import { areaInCamera, type GroundAreaHighlight } from './areaProjection';
import { areaLabel } from './overviewObservation';
import styles from './SmartCity.module.css';
import { cameraColor, groupRuleGeometry, sourceName } from './presentation';
import type { PresentedVideoFrame, PlaybackStatus } from '../VisionStreamCanvas';
import { useProcessedPreview, type PreviewPair } from './useProcessedPreview';
import { CityProcessedPreview } from './CityProcessedPreview';
import type { PreviewDeliverySource } from './usePreviewHealth';
import { useDocumentVisible } from './useDocumentVisible';
import { matchesObservationScope } from './analyticsScope';
const CityLivePreview = dynamic(() => import('./CityLivePreview').then(module => module.CityLivePreview), { ssr: false });
const CityTrackedVideo = dynamic(() => import('./CityTrackedVideo').then(module => module.CityTrackedVideo), { ssr: false });

interface Props {
  source: CitySource; mode: CityMode; index: number; snapshot: CitySnapshot | null; rules: CityRule[];
  selectedTrack: string | null; selectedTrackIds?: string[]; onSelect: (id: string) => void; playing: boolean;
  seekTime: number; seekToken: number; onTime: (seconds: number) => void;
  leaderTime?: number; fixtureTime?: number;
  onDuration: (seconds: number) => void; editing: boolean; draft: Point[];
  draftKind: string; onPoint: (point: Point) => void; onEdit: () => void;
  vstApiUrl?: string | null; onSourceTime: (sourceId: string, unixMs: number) => void;
  onProcessedFrame?: (sourceId: string, frame: CityAnalyzedFrame | null, configurationKey?: string) => void;
  previewContext?: CityPreviewContext; previewEnabled?: boolean; analysisEnabled?: boolean;
  latestSource?: CitySource;
  deliveryHealth?: PreviewDeliverySource; deliveryStatus?: string; previewFpsLimit?: number; previewTransport?: 'jpeg' | 'webrtc';
  onEnded?: () => void; fillFrame?: boolean; areaHighlight?: GroundAreaHighlight | null; focusedRuleId?: string | null; showAllRules?: boolean; scenarioRuleIds?: readonly string[];
}
export const CityCamera = memo(function CityCamera({ source, mode, index, snapshot, rules, selectedTrack, selectedTrackIds, onSelect, playing, seekTime, seekToken, leaderTime, fixtureTime, onTime, onDuration, editing, draft, draftKind, onPoint, onEdit, vstApiUrl, onSourceTime, onProcessedFrame, previewContext, previewEnabled = true, analysisEnabled = true, latestSource, deliveryHealth, deliveryStatus, previewFpsLimit, previewTransport, onEnded, focusedRuleId, areaHighlight, fillFrame = true, showAllRules = false, scenarioRuleIds }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const [mediaError, setMediaError] = useState(false);
  const [mediaTime, setMediaTime] = useState(0);
  const [dimensions, setDimensions] = useState({ width: source.width, height: source.height });
  const [mediaReady, setMediaReady] = useState(false);
  const [liveFrame, setLiveFrame] = useState<PresentedVideoFrame | null>(null);
  const presentationTimes = useRef<{ key: string; times: number[]; total: number; reportedAt: number }>({ key: '', times: [], total: 0, reportedAt: -Infinity });
  const [presentationRate, setPresentationRate] = useState<{ fps: number | null; total: number }>({ fps: null, total: 0 });
  const live = mode === 'live';
  const visible = useDocumentVisible();
  const transportScope = JSON.stringify([mode, source.id, previewContext?.configurationKey]);
  const reportedTransport = previewTransport ?? latestSource?.processedPreview?.transport;
  const reportedSession = latestSource?.sessionId;
  const [transport, setTransport] = useState({ scope: transportScope, session: reportedSession, kind: reportedTransport });
  const transportChanged = transport.scope !== transportScope || Boolean(reportedSession && reportedSession !== transport.session);
  const retainedTransport = transportChanged ? reportedTransport : reportedTransport ?? transport.kind;
  // Missing health/capability is an observation gap, not a transport change.
  // Retain the established reader until a new scope/session or explicit mode
  // says otherwise; freshness remains the exact-frame reader's responsibility.
  if (transportChanged || retainedTransport !== transport.kind) {
    setTransport({ scope: transportScope, session: reportedSession ?? (transportChanged ? undefined : transport.session), kind: retainedTransport });
  }
  const rtcMode = live && retainedTransport === 'webrtc';
  const [videoFrame, setVideoFrame] = useState<CityVideoFrame | null>(null);
  const candidatePair = useProcessedPreview(source.id, live && !rtcMode && analysisEnabled && previewEnabled && visible, latestSource?.sessionId, previewContext, previewFpsLimit);
  const [rejectedPair, setRejectedPair] = useState<PreviewPair | null>(null);
  const previewPair = analysisEnabled && candidatePair !== rejectedPair ? candidatePair : null;
  const onProcessedFailure = useCallback(() => setRejectedPair(candidatePair), [candidatePair]);
  const analyzedFrame = rtcMode ? videoFrame : previewPair?.frame;
  const currentScope = matchesObservationScope(analyzedFrame?.snapshot ?? snapshot, latestSource) &&
    (!analyzedFrame || !latestSource?.sessionId || analyzedFrame.sessionId === latestSource.sessionId);
  const processed = Boolean(analyzedFrame) && analysisEnabled && currentScope;
  const [videoOnlyRequested, setVideoOnlyRequested] = useState(false);
  // Native exact-frame cameras do not need a second playback pipeline. In
  // particular, a worker restart must not fan out WebRTC encoders per viewer.
  const liveFallback = Boolean(source.browserClockVerified || videoOnlyRequested);
  useEffect(() => { setVideoOnlyRequested(false); }, [processed, source.id, previewContext?.configurationKey, visible, previewEnabled, analysisEnabled]);
  useEffect(() => { if (!liveFallback) { setMediaReady(false); setLiveFrame(null); } }, [liveFallback]);
  const frameSnapshot = live && !currentScope ? null : analyzedFrame?.snapshot ?? snapshot;
  const url = safeMediaUrl(source.mediaUrl);
  const observationSource = frameSnapshot?.sources.find(item => item.id === source.id);
  const fixture = mode === 'fixture-replay' && !url;
  const healthSource = latestSource ?? observationSource;
  const delayed = live && analysisEnabled && healthSource?.sourceClockStatus === 'delayed-or-unsynchronized';
  const reportedClockAge = healthSource?.sourceClockAgeSeconds;
  const clockWarning = `Video is delayed or its clock needs checking${typeof reportedClockAge === 'number' && Number.isFinite(reportedClockAge) ? ` · reported source clock age ${reportedClockAge.toFixed(1)} s` : ''}`;
  const liveTimeNs = liveFrame?.sourceTimeUnixMs ? liveFrame.sourceTimeUnixMs * 1e6 : null;
  const liveAspectMatches = processed || Boolean(liveFrame && liveFrame.width > 0 && liveFrame.height > 0 && Math.abs(liveFrame.width / liveFrame.height - source.width / source.height) < .01);
  const liveSkewMs = liveTimeNs && observationSource?.lastSourceTimeNs ? (Number(observationSource.lastSourceTimeNs) - liveTimeNs) / 1e6 : null;
  const liveClockGate = processed ? 'exact-processed-frame' : !liveFrame ? 'awaiting-frame' : !liveAspectMatches ? 'geometry-mismatch' : !source.browserClockVerified ? 'verification-required' : !liveTimeNs ? 'capture-time-missing' : observationSource?.timestampBasis !== 'source-rtcp' ? 'source-clock-unverified' : !observationSource.clockAligned ? 'observation-unaligned' : liveSkewMs === null || Math.abs(liveSkewMs) > 160 ? 'timestamp-skew' : 'aligned';
  const liveAligned = Boolean(visible && liveAspectMatches && source.browserClockVerified && observationSource?.timestampBasis === 'source-rtcp' && observationSource.clockAligned && liveTimeNs && observationSource.lastSourceTimeNs && Math.abs(Number(observationSource.lastSourceTimeNs) - liveTimeNs) <= 160_000_000);
  useEffect(() => { if (!visible) { setLiveFrame(null); setMediaReady(false); } }, [visible]);
  const aligned = live ? analysisEnabled && (processed || liveAligned) : isAligned(observationSource, fixture ? fixtureTime ?? 0 : mediaTime);
  const onProcessedPresented = useCallback((frame: CityAnalyzedFrame) => {
    const key = `${previewContext?.configurationKey}:${frame.sessionId}:${frame.sequence}:${frame.sourceTimeNs}`; const stats = presentationTimes.current;
    if (stats.key === key) return;
    const now = performance.now(); stats.key = key; stats.total += 1; stats.times = [...stats.times.filter(time => now - time <= 1000), now];
    // Diagnostic counters need one update per second, not a second render for every image.
    if (now - stats.reportedAt >= 1000) {
      stats.reportedAt = now; const span = now - stats.times[0];
      setPresentationRate({ fps: stats.times.length > 1 && span > 0 ? (stats.times.length - 1) * 1000 / span : null, total: stats.total });
    }
    onProcessedFrame?.(source.id, frame, previewContext?.configurationKey);
  }, [onProcessedFrame, source.id, previewContext?.configurationKey]);
  const onVideoPresented = useCallback((frame: CityVideoFrame | null) => {
    setVideoFrame(frame);
    if (frame) onProcessedPresented(frame);
    else onProcessedFrame?.(source.id, null, previewContext?.configurationKey);
  }, [onProcessedPresented, onProcessedFrame, source.id, previewContext?.configurationKey]);
  useEffect(() => { if (!processed) onProcessedFrame?.(source.id, null, previewContext?.configurationKey); }, [processed, source.id, onProcessedFrame, previewContext?.configurationKey]);
  useEffect(() => () => onProcessedFrame?.(source.id, null, previewContext?.configurationKey), [source.id, onProcessedFrame, previewContext?.configurationKey]);
  const onLiveFrame = useCallback((frame: PresentedVideoFrame) => {
    setLiveFrame(frame); setDimensions({ width: source.width, height: source.height });
    if (source.browserClockVerified && typeof frame.sourceTimeUnixMs === 'number') onSourceTime(source.id, frame.sourceTimeUnixMs);
  }, [source.id, source.width, source.height, source.browserClockVerified, onSourceTime]);
  const onLiveStatus = useCallback((status: PlaybackStatus) => { setMediaReady(status === 'playing'); setMediaError(status === 'error'); }, []);
  const tracks: CityTrack[] = useMemo(() => aligned ? (frameSnapshot?.tracks.filter(track => track.sourceId === source.id && !track.stale && track.observedThisFrame !== false) ?? []) : [], [aligned, frameSnapshot?.tracks, source.id]);
  useEffect(() => {
    if (live) return;
    const element = video.current; setMediaError(false); setMediaReady(Boolean(element && element.readyState >= 1));
    if (element && element.readyState >= 1) {
      setDimensions({ width: element.videoWidth || source.width, height: element.videoHeight || source.height });
      if (Number.isFinite(element.duration)) onDuration(element.duration);
    }
  }, [live, url, source.width, source.height, onDuration]);
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (playing) void element.play().catch(() => setMediaError(true));
    else element.pause();
  }, [playing, url, mediaReady]);
  useEffect(() => {
    if (video.current && Number.isFinite(seekTime) && Math.abs(video.current.currentTime - seekTime) > 0.08) video.current.currentTime = seekTime;
  }, [seekTime, seekToken]);
  useEffect(() => {
    const element = video.current;
    if (element && typeof leaderTime === 'number' && !element.seeking && Math.abs(element.currentTime - leaderTime) > .16) element.currentTime = leaderTime;
  }, [leaderTime]);
  useEffect(() => {
    const element = video.current;
    if (!element || !url) return;
    let frame = 0; let active = true;
    const update = (_now: number, metadata?: { mediaTime: number }) => {
      if (!active) return;
      const time = metadata?.mediaTime ?? element.currentTime;
      setMediaTime(time); onTime(time);
      if ('requestVideoFrameCallback' in element) frame = element.requestVideoFrameCallback(update);
    };
    if ('requestVideoFrameCallback' in element) frame = element.requestVideoFrameCallback(update);
    const fallback = () => { if (!('requestVideoFrameCallback' in element)) update(performance.now()); };
    element.addEventListener('timeupdate', fallback);
    return () => { active = false; if (frame && 'cancelVideoFrameCallback' in element) element.cancelVideoFrameCallback(frame); element.removeEventListener('timeupdate', fallback); };
  }, [onTime, url]);
  const { width, height } = analyzedFrame?.image ?? dimensions;
  const cameraSelectedId = tracks.find(track => selectedTrackIds?.includes(track.id))?.id ?? selectedTrack;
  const trafficCamNet = processed && analyzedFrame?.modelRevision?.startsWith('trafficcamnet');
  const previousLabelLayout = useRef<CameraLabelLayout>();
  const labelScope = JSON.stringify([mode, source.id, analyzedFrame?.sessionId ?? observationSource?.sessionId,
    observationSource?.sourceSessionId, observationSource?.trackingEpoch, seekToken,
    observationSource?.analyticsScope?.epoch, frameSnapshot?.analyticsScope?.epoch, previewContext?.configurationKey,
    analyzedFrame?.modelRevision ?? observationSource?.modelRevision, observationSource?.calibrationRevision ?? source.calibrationRevision]);
  const labelTimeMs = Number(analyzedFrame?.sourceTimeNs ?? observationSource?.lastSourceTimeNs) / 1e6
    || Date.parse(frameSnapshot?.timestamp ?? '') || 0;
  const labelLayout = useMemo(() => cameraLabelLayout(tracks, width, height, cameraSelectedId, labelScope,
    labelTimeMs, aligned ? previousLabelLayout.current : undefined), [tracks, width, height, cameraSelectedId, labelScope, labelTimeMs, aligned]);
  // Commit history after render, so speculative React renders cannot alter placement.
  useEffect(() => { previousLabelLayout.current = aligned ? labelLayout : undefined; }, [labelLayout, aligned]);
  const labels = labelLayout.labels;
  const imageRules = (processed && !editing ? frameSnapshot?.rules ?? [] : rules)
    .filter(rule => rule.sourceId === source.id && rule.enabled && (!live || liveAspectMatches) && (scenarioRuleIds ? scenarioRuleIds.includes(rule.id) : showAllRules || rule.id === focusedRuleId))
    .map(rule => ({ ...rule, geometry: { ...rule.geometry, space: 'image-normalized' as const, points: ruleImagePoints(rule, observationSource ?? source) } }))
    .filter(rule => rule.geometry.points.length >= 2);
  const projectedArea = !editing && (!live || liveAspectMatches) && areaHighlight?.sourceId !== source.id ? areaInCamera(areaHighlight, source) : [];
  const points = (values: Point[]) => values.map(([x, y]) => `${x * width},${y * height}`).join(' ');
  return <section className={`${styles.camera} ${editing ? styles.cameraEditing : ''}`} style={{ '--camera-color': cameraColor(index) } as React.CSSProperties} aria-label={`${source.name} camera`} data-source-id={source.id} data-camera-fit={fillFrame ? 'cover' : 'contain'} data-decoded-media-time={fixture ? fixtureTime ?? 0 : mediaTime} data-observation-media-time={observationSource?.mediaTimeSeconds} data-overlay-aligned={aligned}
    data-live-capture-time-ms={processed ? undefined : liveFrame?.sourceTimeUnixMs} data-live-rtp-timestamp={processed ? undefined : liveFrame?.rtpTimestamp}
    data-live-presented-at-ms={processed ? undefined : liveFrame?.presentedAtMs} data-live-clock-basis={processed ? undefined : liveFrame?.clockBasis}
    data-preview-sequence={analyzedFrame?.sequence} data-preview-session={analyzedFrame?.sessionId} data-preview-source-time-ns={analyzedFrame?.sourceTimeNs} data-preview-provenance={analyzedFrame?.provenance.kind}
    data-preview-configuration-key={previewPair?.configurationKey} data-preview-scope-current={currentScope}
    data-preview-transport={rtcMode ? "webrtc" : "jpeg"} data-preview-render-fps={processed && !rtcMode ? presentationRate.fps?.toFixed(1) : undefined} data-preview-rendered-frames={presentationRate.total} data-preview-jpeg-width={previewPair?.frame.image.jpegWidth} data-preview-jpeg-height={previewPair?.frame.image.jpegHeight}
    data-preview-model-revision={analyzedFrame?.modelRevision} data-preview-delivery-status={deliveryStatus} data-preview-native-published-fps={deliveryHealth?.observedPublishedFps} data-preview-native-encoded-fps={deliveryHealth?.observedEncodedFps}
    data-preview-rate-skipped={deliveryHealth?.rateDropped} data-preview-network-queue-dropped={deliveryHealth?.networkQueueDropped} data-preview-source-queue-overruns={deliveryHealth?.sourceQueueOverruns} data-preview-post-failed={deliveryHealth?.postFailed} data-preview-pending-dropped={deliveryHealth?.pendingDropped}
    data-observation-source-time-ns={observationSource?.lastSourceTimeNs} data-live-source-skew-ms={liveSkewMs ?? undefined}
    data-ingest-age-seconds={observationSource?.ingestAgeSeconds ?? undefined} data-source-clock-age-seconds={reportedClockAge ?? undefined}
    data-source-clock-progress-ratio={observationSource?.sourceClockProgressRatio ?? undefined} data-source-clock-precision={observationSource?.sourceClockPrecision} data-source-clock-status={observationSource?.sourceClockStatus}
    data-live-clock-gate={live ? liveClockGate : undefined} data-live-aspect-matches={live ? liveAspectMatches : undefined}>
    <header><div><span className={styles.cameraIndex}>{String(index + 1).padStart(2, '0')}</span><strong title={source.name}>{sourceName(source)}</strong></div><div><span className={styles.sourceState} title={deliveryHealth ? `Analyzed preview delivery: ${deliveryStatus ?? 'unknown'}. Published ${deliveryHealth.observedPublishedFps ?? 'unknown'} frames/s. Preview rate skips: ${deliveryHealth.rateDropped ?? 'unknown'}. Network queue drops: ${deliveryHealth.networkQueueDropped ?? 'unknown'}. Post failures: ${deliveryHealth.postFailed ?? 'unknown'}. These are preview transport counters.` : undefined}><i className={delayed ? styles.dotWarning : processed || mediaReady && !mediaError ? styles.dot : styles.dotMuted} />{live ? processed ? 'Live' : mediaReady && !mediaError ? 'Video only' : healthSource?.status === 'paused' || healthSource?.status === 'stale' || mediaError ? 'Feed unavailable' : 'Connecting' : fixture ? 'Test fixture' : 'Recorded'}</span><button type="button" onClick={onEdit} aria-label={`Edit zones in ${source.name}`} title="Edit zones and lines"><IconDotsVertical size={16} /></button></div></header>
    <div className={styles.cameraStage}><div className={styles.cameraFrame}>
      {!previewEnabled ? <div className={styles.mediaEmpty}><strong>Preview not in this view</strong></div> : live ? !visible ? <div className={styles.mediaEmpty}><strong>Preview paused in this tab</strong><span>Camera analysis continues on the device.</span></div> : rtcMode && analysisEnabled ? <CityTrackedVideo quietLabels={Boolean(scenarioRuleIds?.length)} sourceId={source.id} expectedSession={latestSource?.sessionId} latestSource={latestSource} context={previewContext} enabled={previewEnabled && visible && analysisEnabled} selectedTrack={selectedTrack} selectedTrackIds={selectedTrackIds} editing={editing} fillFrame={fillFrame} color={cameraColor(index)} onSelect={onSelect} onPresented={onVideoPresented} onStatus={onLiveStatus} /> : previewPair ? <CityProcessedPreview presentable={currentScope} pair={previewPair} onPresented={onProcessedPresented} onFailure={onProcessedFailure} /> : liveFallback ? <CityLivePreview source={source} vstApiUrl={vstApiUrl} onFrame={onLiveFrame} onStatus={onLiveStatus} /> : <div className={styles.mediaEmpty}><strong>{analysisEnabled ? 'Waiting for analyzed video' : 'Detections are off'}</strong><span>{analysisEnabled ? 'Frame-matched video appears when analysis is ready.' : 'Start detections to see tracked objects.'}</span><button type="button" className={styles.outlineButton} onClick={() => setVideoOnlyRequested(true)}>Play video only</button></div> : fixture ? <div className={styles.fixtureCanvas}><span>Geometry fixture · synthetic observations</span><small>No camera video or AI inference in this view</small></div> : url && !mediaError ? <video ref={video} src={url} playsInline muted preload="metadata" onEnded={onEnded} onError={() => setMediaError(true)} onLoadedMetadata={event => {
        const element = event.currentTarget; setDimensions({ width: element.videoWidth || source.width, height: element.videoHeight || source.height });
        setMediaReady(true); if (Number.isFinite(element.duration)) onDuration(element.duration);
      }} onSeeked={event => { setMediaTime(event.currentTarget.currentTime); onTime(event.currentTarget.currentTime); }} /> : <div className={styles.mediaEmpty}><IconVideoOff size={28} /><strong>{mediaError ? 'Video could not be loaded' : 'Waiting for a registered camera'}</strong><span>{mediaError ? 'Check the recorded source and city service.' : 'Connect a recorded source or the final RTSP feed.'}</span></div>}
      <svg className={`${styles.cameraOverlay} ${editing ? styles.editable : ''}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio={fillFrame ? 'xMidYMid slice' : 'xMidYMid meet'} aria-label={`${source.name} detections and rules`} onClick={event => {
        if (!editing || (live && !liveAspectMatches)) return;
        const point = normalizedPoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(), width, height, fillFrame ? 'cover' : 'contain');
        if (point) onPoint(point);
      }}>
        <defs><marker id={`city-arrow-${index}`} markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto" markerUnits="strokeWidth"><path d="M 0 0 L 9 4.5 L 0 9 z" fill="currentColor" /></marker></defs>
        {groupRuleGeometry(imageRules).map(group => {
          const rule = group.rules[0];
          const active = frameSnapshot?.zones.some(zone => group.rules.some(item => item.id === zone.id) && zone.active);
          const line = rule.kind === 'line-crossing' || rule.geometry.points.length === 2;
          const [first, second] = rule.geometry.points;
          const caption = areaLabel(rule.name); const captionWidth = Math.min(width - 16, caption.length * width / 100);
          return <g key={group.key} data-rule-id={rule.id} className={active ? styles.activeZone : styles.zone}>
            {line ? <><polyline points={points(rule.geometry.points)} fill="none" vectorEffect="non-scaling-stroke" /><line x1={(first[0] + second[0]) * width / 2} y1={(first[1] + second[1]) * height / 2} x2={(first[0] + second[0]) * width / 2 + (rule.geometry.direction?.[0] ?? 0) * 35} y2={(first[1] + second[1]) * height / 2 + (rule.geometry.direction?.[1] ?? -1) * 35} markerEnd={`url(#city-arrow-${index})`} vectorEffect="non-scaling-stroke" /></> : <polygon points={points(rule.geometry.points)} vectorEffect="non-scaling-stroke" />}
            {first && <text x={Math.max(8, Math.min(width - captionWidth - 8, first[0] * width + 7))} y={Math.max(24, first[1] * height - 8)} fontSize={width / 47}><title>{group.rules.map(item => item.name).join(' · ')}</title>{caption}</text>}
          </g>;
        })}
        {projectedArea.length >= 2 && <g className={`${styles.zone} ${styles.projectedArea}`} data-projected-rule-id={areaHighlight!.id} aria-label={`${areaLabel(areaHighlight!.name)} · calibrated area guide`}>
          <title>The same ground area in this camera. Measurements remain owned by the original camera.</title>
          {projectedArea.length === 2 ? <polyline points={points(projectedArea)} fill="none" vectorEffect="non-scaling-stroke" /> : <polygon points={points(projectedArea)} vectorEffect="non-scaling-stroke" />}
          <text x={Math.max(8, Math.min(width - Math.min(width - 16, areaLabel(areaHighlight!.name).length * width / 100) - 8, projectedArea[0][0] * width + 7))} y={Math.max(24, projectedArea[0][1] * height - 8)} fontSize={width / 47}>{areaLabel(areaHighlight!.name)}</text>
        </g>}
        {(!rtcMode ? tracks : []).map(track => {
          const [x, y, w, h] = track.bboxPx; const selected = selectedTrack === track.id || Boolean(selectedTrackIds?.includes(track.id));
          const label = labels.get(track.id);
          return <g key={track.id} data-track-id={track.id} className={`${styles.trackBox} ${selected ? styles.selectedTrack : ''}`} onClick={event => { if (!editing) { event.stopPropagation(); onSelect(track.id); } }}>
            <rect role="button" tabIndex={0} aria-label={`${objectName(track.class)} · ${sourceName(source)}`} aria-pressed={selected} onKeyDown={event => { if (!editing && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect(track.id); } }} x={x} y={y} width={w} height={h} pointerEvents="all" vectorEffect="non-scaling-stroke"><title>{`${objectName(track.class)}${track.confidence === null ? '' : ` · ${Math.round(track.confidence * 100)}% confidence`} · Click to inspect`}</title></rect>{label && <g data-camera-label={track.id} pointerEvents="none"><rect className={styles.boxLabel} rx={4} x={label.x} y={label.y} width={label.width} height={label.height} /><text x={label.x + width / 130} y={label.y + label.height * .76} fontSize={width / 48}>{label.text}</text></g>}
          </g>;
        })}
        {editing && <g className={styles.draft}><polyline points={points(draft)} fill={draftKind === 'line-crossing' ? 'none' : 'rgba(63,194,189,.14)'} vectorEffect="non-scaling-stroke" />{draft.map(([x, y], key) => <circle key={key} cx={x * width} cy={y * height} r={width / 140} />)}</g>}
      </svg>
      {rtcMode && !editing && tracks.map(track => <button key={track.id} type="button" className={styles.trackedKeyboardTarget}
        aria-label={`${objectName(track.class)} · ${sourceName(source)}`} aria-pressed={selectedTrack === track.id || Boolean(selectedTrackIds?.includes(track.id))}
        onClick={() => onSelect(track.id)}>Inspect {objectName(track.class).toLowerCase()}</button>)}
      {(mediaReady || processed || fixture || delayed) && (!editing || delayed) && <div className={`${styles.cameraFootnote} ${delayed ? styles.clockWarning : ''}`}>{delayed ? `${processed ? 'Frame matched · analyzed preview · ' : ''}${clockWarning}${editing ? ' · Click to place rule points' : ''}` : processed ? `Frame matched · analyzed preview · ${tracks.length} tracked` : aligned ? `${tracks.length} tracked · ${fixture ? 'fixture time aligned' : 'frame aligned'}` : live ? !analysisEnabled ? 'Video only · detections off' : !liveAspectMatches ? 'Preview geometry needs verification' : source.browserClockVerified ? 'Waiting for source capture timestamps' : 'Live video · overlay clock is not yet verified' : 'Waiting for aligned observations'}{trafficCamNet && ' · TrafficCamNet: people, cars, two-wheelers'}</div>}
      {editing && !delayed && <div className={styles.cameraFootnote}>Click to place {draftKind === 'line-crossing' ? 'two line points' : 'polygon vertices'}</div>}
    </div></div>
  </section>;
});
