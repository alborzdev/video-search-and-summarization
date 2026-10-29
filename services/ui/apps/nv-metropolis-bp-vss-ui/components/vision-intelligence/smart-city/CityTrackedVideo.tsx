// SPDX-License-Identifier: MIT
import React, { startTransition, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CityPreviewContext, CitySource, CityVideoFrame } from './types';
import { cameraLabelLayout, type CameraLabelLayout } from './cameraLabelLayout';
import { normalizedPoint } from './geometry';
import { parseVideoFrame, parseVideoManifest, RtpFrameBuffer, type VideoManifest } from './trackedVideo';
import { matchesPreviewContext } from './processedPreview';
import { matchesObservationScope } from './analyticsScope';
import { subscribeCityEvent } from './cityEvents';
import { registerScenarioCamera } from './scenarioFrameCapture';
import styles from './SmartCity.module.css';

interface Props {
  sourceId: string; expectedSession?: string; context?: CityPreviewContext; enabled: boolean;
  latestSource?: CitySource; quietLabels?: boolean;
  selectedTrack: string | null; selectedTrackIds?: readonly string[]; editing: boolean; fillFrame: boolean; color: string;
  onSelect: (id: string) => void; onPresented: (frame: CityVideoFrame | null) => void;
  onStatus: (status: 'connecting' | 'playing' | 'error') => void;
}
const API = '/api/vision/city-video';
const MATCH_STALE_MS = 2000;
const CAPTURE_MAX_AGE_MS = 1500;
// At most 32 MiB of raw pending pixels per camera, independently of source FPS.
const CAPTURE_PIXEL_LIMIT = 8 * 1024 * 1024;
const CAPTURE_COUNT_LIMIT = 24;

/** Native browser playback and one canvas batch per actual presented RTP frame.
 * Selection/controls are React state; transient pixels and metadata stay in refs.
 */
export function CityTrackedVideo(props: Props) {
  const video = useRef<HTMLVideoElement>(null); const canvas = useRef<HTMLCanvasElement>(null);
  const imageCanvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props); const redraw = useRef<(() => void) | null>(null);
  const hitFrame = useRef<CityVideoFrame | null>(null);
  const displaySize = useRef({ width: 1, height: 1, dpr: 1 });
  const [message, setMessage] = useState('Connecting analyzed video…');
  const messageRef = useRef(message);
  const setVideoMessage = useCallback((value: string) => { if (messageRef.current !== value) { messageRef.current = value; setMessage(value); } }, []);
  useLayoutEffect(() => { latest.current = props; });
  useLayoutEffect(() => { redraw.current?.(); }, [props.quietLabels, props.selectedTrack, props.selectedTrackIds, props.editing, props.fillFrame, props.color, props.latestSource, props.expectedSession, props.context?.configurationKey]);
  useLayoutEffect(() => {
    const element = canvas.current; if (!element) return;
    const rect = element.getBoundingClientRect();
    displaySize.current = { width: Math.max(1, rect.width), height: Math.max(1, rect.height), dpr: Math.min(3, window.devicePixelRatio || 1) };
    if (typeof ResizeObserver !== 'function') return;
    const observer = new ResizeObserver(entries => {
      const rect = entries[0]?.contentRect;
      if (rect) displaySize.current = { width: Math.max(1, rect.width), height: Math.max(1, rect.height), dpr: Math.min(3, window.devicePixelRatio || 1) };
      redraw.current?.();
    });
    observer.observe(element); return () => observer.disconnect();
  }, []);
  const key = props.context?.configurationKey;
  useEffect(() => {
    const element = video.current; const overlay = canvas.current; const image = imageCanvas.current;
    if (!props.enabled || !props.expectedSession || !props.context || !element || !overlay || !image) return;
    const context = props.context; const session = props.expectedSession;
    const drawing = overlay.getContext('2d', { alpha: true }); const imageDrawing = image.getContext('2d');
    if (!drawing || !imageDrawing || typeof element.requestVideoFrameCallback !== 'function' || typeof RTCPeerConnection !== 'function') {
      setVideoMessage('Frame-matched playback is unavailable in this browser.'); props.onStatus('error'); return;
    }
    let retryDelay = 1000;
    let active = true; let reconnect: ReturnType<typeof setTimeout> | null = null; let stopConnection = () => {};
    let displayedPair: { frame: CityVideoFrame; at: number } | null = null;
    let paused = false; let interruptions = 0; let maxPairGap = 0;
    const scopeReason = (frame: CityVideoFrame) => latest.current.expectedSession !== session ? 'session-changed'
      : latest.current.context?.configurationKey !== context.configurationKey ? 'configuration-changed'
      : latest.current.latestSource?.sessionId && latest.current.latestSource.sessionId !== frame.sessionId ? 'source-session-changed'
      : !matchesPreviewContext(frame, context, session) ? 'invalid-context'
      : !matchesObservationScope(frame.snapshot, latest.current.latestSource) ? 'scope-changed' : '';
    const validScope = (frame: CityVideoFrame) => !scopeReason(frame);
    const recordGap = () => {
      if (displayedPair) maxPairGap = Math.max(maxPairGap, performance.now() - displayedPair.at);
      overlay.dataset.videoMaxPairGapMs = maxPairGap.toFixed(1);
    };
    const clear = () => {
      drawing.setTransform(1, 0, 0, 1, 0, 0); drawing.clearRect(0, 0, overlay.width, overlay.height);
      imageDrawing.clearRect(0, 0, image.width, image.height); hitFrame.current = null; displayedPair = null;
      overlay.dataset.videoMatched = 'false'; delete overlay.dataset.videoSequence; delete overlay.dataset.videoSourceTimeNs;
      delete overlay.dataset.videoRtpTimestamp; delete overlay.dataset.videoSession;
      overlay.dataset.videoDisplayState = 'connecting';
    };
    const invalidateRetained = () => {
      if (displayedPair && !validScope(displayedPair.frame)) {
        overlay.dataset.videoGapReason = scopeReason(displayedPair.frame);
        clear(); latest.current.onPresented(null);
      }
    };
    const pause = (value = 'Video paused · reconnecting analysis…') => {
      recordGap();
      const changed = !paused;
      if (changed && displayedPair) interruptions++;
      paused = true; hitFrame.current = null;
      overlay.dataset.videoMatched = 'false'; overlay.dataset.videoDisplayState = 'paused';
      overlay.dataset.videoDisplayInterruptions = String(interruptions);
      // Keep the last exact pair visible, but never report or select its boxes
      // as current observations. A real outage is labelled instead of blanking.
      if (changed) { latest.current.onPresented(null); latest.current.onStatus('connecting'); }
      setVideoMessage(value);
    };
    const restart = () => {
      if (!active || reconnect !== null) return;
      stopConnection();
      if (displayedPair && validScope(displayedPair.frame)) pause();
      else { clear(); latest.current.onPresented(null); latest.current.onStatus('connecting'); setVideoMessage('Reconnecting analyzed video…'); }
      reconnect = setTimeout(() => { reconnect = null; begin(); }, retryDelay);
      retryDelay = Math.min(15000, retryDelay * 2);
    };
    const begin = () => {
      if (!active) return;
      let current = true; let manifest: VideoManifest | null = null; let pc: RTCPeerConnection | null = null;
      let token: string | null = null; let connecting = false; let callback = 0;
      let leaseTimer: ReturnType<typeof setTimeout> | null = null; let statsTimer: ReturnType<typeof setTimeout> | null = null;
      let leaseExpiresAt = 0;
      const beganAt = performance.now();
      let lastFrameAt = beganAt; let displayedRtp: number | null = null;
      let labels: CameraLabelLayout | undefined; let reportedAt = -Infinity; let reportedKey = '';
      let presented = 0; let matched = 0; let missing = 0; let lastCountRtp: number | null = null;
      let reportTimer: ReturnType<typeof setTimeout> | null = null;
      let reportedPlaying = false; let lateFrames = 0; let maximumMatchLag = 0;
      let captureOrder = 0; let paintedOrder = 0; let recoveryAt = 0; let recoveryCount = 0; let lastMatchReceivedAt = -Infinity;
      type Capture = { image: HTMLCanvasElement; rtp: number; order: number; at: number; awaitingMetadata: boolean };
      const captures = new Map<number, Capture>(); const spareImages: HTMLCanvasElement[] = [];
      let pendingHighWater = 0;
      const recycle = (capture: Capture) => { captures.delete(capture.rtp); spareImages.push(capture.image); };
      const expireCaptures = () => {
        const now = performance.now();
        for (const capture of captures.values()) if (now - capture.at > CAPTURE_MAX_AGE_MS || capture.order <= paintedOrder) recycle(capture);
      };
      const frames = new RtpFrameBuffer(); const abort = new AbortController();
      const subscriptions: (() => void)[] = [];
      const listen = (type: string, callback: EventListener) => subscriptions.push(subscribeCityEvent(type + ':' + props.sourceId, callback));
      const matchingFrame = (rtp: number) => {
        const frame = frames.get(rtp, performance.now());
        const reason = !frame ? 'metadata-not-received' : latest.current.expectedSession !== session ? 'session-changed'
          : latest.current.context?.configurationKey !== context.configurationKey ? 'configuration-changed'
          : latest.current.latestSource?.sessionId && latest.current.latestSource.sessionId !== frame.sessionId ? 'source-session-changed'
          : !matchesPreviewContext(frame, context, session) ? 'invalid-context'
          : !matchesObservationScope(frame.snapshot, latest.current.latestSource) ? 'scope-changed'
          : element.videoWidth !== frame.image.width || element.videoHeight !== frame.image.height ? 'geometry-mismatch' : '';
        overlay.dataset.videoGapReason = reason;
        if (reason) return null;
        return frame;
      };
      const heldFrameValid = () => {
        const held = displayedPair?.frame;
        return Boolean(held && current && validScope(held));
      };
      const publish = (frame: CityVideoFrame | null) => {
        const now = performance.now();
        if (!frame) { if (reportTimer) { clearTimeout(reportTimer); reportTimer = null; } if (reportedKey) { reportedKey = ''; latest.current.onPresented(null); } return; }
        const identity = String(frame.sequence) + ':' + frame.sourceTimeNs;
        // Map/summary updates are bounded separately from the video/overlay loop.
        if (identity === reportedKey) return;
        if (now - reportedAt >= 100) {
          if (reportTimer) { clearTimeout(reportTimer); reportTimer = null; }
          reportedAt = now; reportedKey = identity; startTransition(() => latest.current.onPresented(frame));
        } else if (reportTimer === null) {
          // Flush the currently displayed frame at the deadline. Waiting for
          // another video callback quantizes a 13 FPS source down to 6.5 FPS.
          reportTimer = setTimeout(() => { reportTimer = null; publish(!paused && heldFrameValid() ? hitFrame.current : null); }, Math.ceil(100 - (now - reportedAt)));
        }
      };
      subscriptions.push(registerScenarioCamera(props.sourceId, () => {
        const pair = displayedPair;
        return pair && !paused && heldFrameValid() && performance.now() - pair.at < 500 && !element.paused && element.readyState >= 2
          ? { image, frame: pair.frame } : null;
      }));
      const paint = (pair?: { frame: CityVideoFrame; capture: Capture }) => {
        if (!current) return;
        if (!pair && !heldFrameValid()) {
          if (displayedPair) overlay.dataset.videoGapReason = scopeReason(displayedPair.frame);
          clear(); publish(null); return;
        }
        const frame = pair?.frame ?? displayedPair!.frame;
        const { width, height } = frame.image;
        // A health/selection/resize redraw must not sample pixels from a later
        // video frame; only a presentation or matching metadata arrival can do that.
        if (pair) {
          if (image.width !== width) image.width = width;
          if (image.height !== height) image.height = height;
          imageDrawing.drawImage(pair.capture.image, 0, 0, width, height);
        }
        const size = displaySize.current;
        const imageScale = (latest.current.fillFrame ? Math.max : Math.min)(size.width / width, size.height / height);
        const pixels = Math.max(1, Math.round(width * imageScale * size.dpr));
        const rows = Math.max(1, Math.round(pixels * height / width));
        if (overlay.width !== pixels) overlay.width = pixels;
        if (overlay.height !== rows) overlay.height = rows;
        drawing.setTransform(pixels / width, 0, 0, rows / height, 0, 0);
        drawing.clearRect(0, 0, width, height);
        const tracks = frame.snapshot.tracks.filter(track => !track.stale && track.observedThisFrame !== false);
        const settings = latest.current;
        const selected = tracks.find(track => settings.selectedTrackIds?.includes(track.id))?.id ?? settings.selectedTrack;
        labels = cameraLabelLayout(tracks, width, height, selected, context.configurationKey + ':' + frame.sessionId,
          Number(frame.sourceTimeNs) / 1e6, labels);
        const scale = 1 / imageScale;
        drawing.lineWidth = 1.2 * scale; drawing.font = '500 ' + width / 48 + 'px Arial, sans-serif';
        for (const track of tracks) {
          const [x, y, w, h] = track.bboxPx;
          drawing.strokeStyle = '#67d3bd'; drawing.lineWidth = (track.id === selected ? 2.3 : 1.2) * scale;
          drawing.strokeRect(x, y, w, h);
          const label = labels.labels.get(track.id);
          if (!label || settings.quietLabels && track.id !== selected) continue;
          drawing.fillStyle = '#142329e8';
          drawing.beginPath(); drawing.roundRect(label.x, label.y, label.width, label.height, 4); drawing.fill();
          drawing.fillStyle = '#f1f5f7'; drawing.fillText(label.text, label.x + width / 130, label.y + label.height * .76);
        }
        hitFrame.current = paused ? null : frame;
        overlay.dataset.videoMatched = String(!paused); overlay.dataset.videoSequence = String(frame.sequence);
        overlay.dataset.videoSourceTimeNs = frame.sourceTimeNs; overlay.dataset.videoSession = frame.sessionId;
        overlay.dataset.videoRtpTimestamp = String(frame.transport.rtpTimestamp); overlay.dataset.videoModel = frame.modelRevision;
        overlay.dataset.videoConfigurationKey = context.configurationKey;
        if (lastCountRtp !== frame.transport.rtpTimestamp) { lastCountRtp = frame.transport.rtpTimestamp; matched++; }
        if (!paused) { publish(frame); setVideoMessage(''); }
      };
      redraw.current = () => paint();
      const matchCapture = (capture: Capture) => {
        if (!current || capture.order <= paintedOrder || performance.now() - capture.at > CAPTURE_MAX_AGE_MS) return false;
        const frame = matchingFrame(capture.rtp);
        if (!frame) {
          // An old/invalid arriving record cannot invalidate a newer valid
          // display. Only the current configuration/scope owns that boundary.
          if (displayedPair && !validScope(displayedPair.frame)) { clear(); publish(null); }
          return false;
        }
        // Arrival order can differ from RTP order, and RTP itself wraps. The
        // source sequence is authoritative within this verified session.
        if (displayedPair && displayedPair.frame.sourceSessionId === frame.sourceSessionId &&
          BigInt(frame.sequence) <= BigInt(displayedPair.frame.sequence)) { recycle(capture); return false; }
        const now = performance.now(); recordGap();
        if (paused) {
          if (now - lastMatchReceivedAt > 500) { recoveryAt = now; recoveryCount = 0; }
          recoveryCount++;
          if (recoveryCount >= 3 && now - recoveryAt >= 200) paused = false;
        }
        lastMatchReceivedAt = now; paintedOrder = capture.order;
        displayedPair = { frame, at: capture.at };
        overlay.dataset.videoDisplayState = paused ? 'recovering' : 'live';
        if (capture.awaitingMetadata) {
          lateFrames++; maximumMatchLag = Math.max(maximumMatchLag, now - capture.at);
          overlay.dataset.videoLateMetadataFrames = String(lateFrames); overlay.dataset.videoMatchLagMaxMs = maximumMatchLag.toFixed(1);
        }
        paint({ frame, capture }); expireCaptures();
        overlay.dataset.videoMatchedFrames = String(matched);
        if (!paused && !reportedPlaying) { reportedPlaying = true; latest.current.onStatus('playing'); }
        return true;
      };
      const presentedFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
        if (!current) return;
        callback = element.requestVideoFrameCallback(presentedFrame);
        lastFrameAt = performance.now(); presented++; retryDelay = 1000;
        const rtp = (metadata as VideoFrameCallbackMetadata & { rtpTimestamp?: number }).rtpTimestamp;
        displayedRtp = typeof rtp === 'number' && Number.isInteger(rtp) ? rtp : null;
        expireCaptures(); recordGap();
        if (displayedRtp !== null && element.videoWidth && element.videoHeight) {
          const width = element.videoWidth; const height = element.videoHeight;
          if (width * height > CAPTURE_PIXEL_LIMIT) { reportedPlaying = false; pause('Video paused · camera frame exceeds the display limit.'); return; }
          const limit = Math.max(1, Math.min(CAPTURE_COUNT_LIMIT, Math.floor(CAPTURE_PIXEL_LIMIT / (width * height))));
          // Recycle the oldest unmatched capture before allocating another one.
          while (captures.size >= limit) recycle(captures.values().next().value!);
          const duplicate = captures.get(displayedRtp); if (duplicate) recycle(duplicate);
          const pendingImage = spareImages.pop() ?? document.createElement('canvas');
          while (spareImages.length + captures.size >= limit) { const unused = spareImages.pop()!; unused.width = 0; unused.height = 0; }
          if (pendingImage.width !== width) pendingImage.width = width;
          if (pendingImage.height !== height) pendingImage.height = height;
          const pendingDrawing = pendingImage.getContext('2d');
          if (pendingDrawing) {
            try { pendingDrawing.drawImage(element, 0, 0, width, height); }
            catch {
              spareImages.push(pendingImage);
              overlay.dataset.videoCaptureErrors = String(Number(overlay.dataset.videoCaptureErrors ?? 0) + 1);
              return;
            }
            const capture = { image: pendingImage, rtp: displayedRtp, order: ++captureOrder, at: lastFrameAt, awaitingMetadata: false };
            captures.set(displayedRtp, capture);
            pendingHighWater = Math.max(pendingHighWater, captures.size);
            overlay.dataset.videoPendingHighWater = String(pendingHighWater);
            if (!matchCapture(capture) && overlay.dataset.videoGapReason === 'metadata-not-received') {
              capture.awaitingMetadata = true; missing++;
              overlay.dataset.videoLastGap = JSON.stringify({ reason: overlay.dataset.videoGapReason,
                rtp: displayedRtp, at: lastFrameAt, lastMetadataRtp: overlay.dataset.videoLastMetadataRtp,
                lastMetadataAt: overlay.dataset.videoLastMetadataAtMs });
            }
          } else { pendingImage.width = 0; pendingImage.height = 0; reportedPlaying = false; pause('Video paused · camera rendering unavailable.'); }
        }
        if (displayedRtp === null) setVideoMessage('Frame-matched overlays are unavailable in this browser.');
        overlay.dataset.videoPresentedRtp = displayedRtp === null ? '' : String(displayedRtp);
        overlay.dataset.videoPresentedAtMs = String(lastFrameAt);
        overlay.dataset.videoPresentedFrames = String(presented); overlay.dataset.videoMatchedFrames = String(matched);
        overlay.dataset.videoMissingMetadataFrames = String(missing);
      };
      callback = element.requestVideoFrameCallback(presentedFrame);
      const renew = async () => {
        if (!current || !token) return;
        const request = new AbortController();
        const cancel = () => request.abort(); abort.signal.addEventListener('abort', cancel, { once: true });
        const deadline = setTimeout(() => request.abort(), 5000);
        try {
          const response = await fetch(API + '/sessions/' + encodeURIComponent(props.sourceId) + '/' + token, { method: 'PUT', signal: request.signal });
          if (!current) return;
          if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) { restart(); return; }
          if (!response.ok) throw new Error();
          // The server lease is 90s; keep a 5s margin and retry a temporary
          // request failure without throwing away a healthy media connection.
          leaseExpiresAt = performance.now() + 85000;
          overlay.dataset.videoLeaseState = 'renewed';
          leaseTimer = setTimeout(() => void renew(), 30000);
        } catch {
          if (current) {
            if (leaseExpiresAt - performance.now() > 10000) {
              overlay.dataset.videoLeaseState = 'retrying'; leaseTimer = setTimeout(() => void renew(), 3000);
            } else restart();
          }
        } finally { clearTimeout(deadline); abort.signal.removeEventListener('abort', cancel); }
      };
      const inspectStats = async () => {
        if (!current || !pc) return;
        try {
          const statistics = await pc.getStats();
          if (!current) return;
          statistics.forEach(row => {
            if (row.type !== 'inbound-rtp' || row.kind !== 'video') return;
            element.dataset.videoInboundFps = String(row.framesPerSecond ?? '');
            element.dataset.videoDecoder = String(row.decoderImplementation ?? 'unknown').slice(0, 80);
            element.dataset.videoFramesDecoded = String(row.framesDecoded ?? '');
            element.dataset.videoFramesDropped = String(row.framesDropped ?? '');
            if (row.jitterBufferEmittedCount > 0) element.dataset.videoJitterMeanMs = String(row.jitterBufferDelay / row.jitterBufferEmittedCount * 1000);
          });
        } catch { /* A closing peer has no statistics. */ }
        if (current) statsTimer = setTimeout(() => void inspectStats(), 2000);
      };
      const negotiate = async () => {
        if (!current || connecting) return;
        connecting = true;
        try {
          pc = new RTCPeerConnection({ iceServers: [] });
          const transceiver = pc.addTransceiver('video', { direction: 'recvonly' });
          const receiver = transceiver?.receiver as (RTCRtpReceiver & { jitterBufferTarget?: number | null }) | undefined;
          // Leave a small matching/recovery window, instead of forcing a zero
          // jitter buffer. This is a preference; actual delay is measured below.
          if (receiver && 'jitterBufferTarget' in receiver) {
            try { receiver.jitterBufferTarget = 200; element.dataset.videoJitterTargetMs = '200'; } catch { /* Browser chooses its own supported buffering. */ }
          }
          pc.ontrack = event => { if (current) { element.srcObject = new MediaStream([event.track]); void element.play().catch(restart); } };
          pc.onconnectionstatechange = () => { if (current) { element.dataset.videoConnectionState = pc?.connectionState; if (pc?.connectionState === 'failed' || pc?.connectionState === 'closed') restart(); } };
          await pc.setLocalDescription(await pc.createOffer());
          if (pc.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
            const peer = pc!; const deadline = setTimeout(() => { cleanup(); reject(new Error('ICE gathering timed out.')); }, 3000);
            const change = () => { if (peer.iceGatheringState === 'complete') { cleanup(); resolve(); } };
            const cancel = () => { cleanup(); reject(new Error('Camera session closed.')); };
            const cleanup = () => { clearTimeout(deadline); peer.removeEventListener('icegatheringstatechange', change); abort.signal.removeEventListener('abort', cancel); };
            peer.addEventListener('icegatheringstatechange', change); abort.signal.addEventListener('abort', cancel, { once: true });
          });
          if (!current || !pc.localDescription?.sdp) return;
          const response = await fetch(API + '/whep/' + encodeURIComponent(props.sourceId) + '?sessionId=' + encodeURIComponent(session),
            { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: pc.localDescription.sdp, signal: abort.signal, cache: 'no-store' });
          const value = response.headers.get('X-City-Video-Session');
          if (response.status !== 201 || !value || !/^[a-f0-9]{32}$/.test(value)) { overlay.dataset.videoConnectionStatus = String(response.status); throw new Error('Camera connection is unavailable.'); }
          overlay.dataset.videoConnectionStatus = '201'; token = value; leaseExpiresAt = performance.now() + 85000;
          if (!current) { void fetch(API + '/sessions/' + encodeURIComponent(props.sourceId) + '/' + token, { method: 'DELETE', keepalive: true }).catch(() => {}); return; }
          const answer = await response.text();
          if (!current) return;
          await pc.setRemoteDescription({ type: 'answer', sdp: answer });
          if (!current) return;
          leaseTimer = setTimeout(() => void renew(), 30000); void inspectStats();
        } catch { if (current) restart(); }
      };
      listen('video-manifest', event => {
        if (!current) return;
        try {
          if (JSON.parse((event as MessageEvent).data).sessionId !== session) return;
          manifest = parseVideoManifest((event as MessageEvent).data, props.sourceId, session);
        }
        // One malformed or superseded SSE record must not tear down a healthy
        // media peer. The matched-frame watchdog handles sustained failure.
        catch { overlay.dataset.videoRejectedMetadata = String(Number(overlay.dataset.videoRejectedMetadata ?? 0) + 1); }
      });
      listen('video-frame', event => {
        if (!current || !manifest) return;
        try {
          const frame = parseVideoFrame((event as MessageEvent).data, manifest, context, session);
          frames.push(frame, performance.now());
          overlay.dataset.videoLastMetadataRtp = String(frame.transport.rtpTimestamp);
          overlay.dataset.videoLastMetadataAtMs = String(performance.now());
          expireCaptures();
          const capture = captures.get(frame.transport.rtpTimestamp);
          if (capture) matchCapture(capture);
          void negotiate();
        }
        catch { overlay.dataset.videoRejectedMetadata = String(Number(overlay.dataset.videoRejectedMetadata ?? 0) + 1); }
      });
      listen('video-reset', restart);
      // EventSource reconnects automatically. Retain exact in-flight pairs
      // during its retry; a transport error alone is not a camera reset.
      subscriptions.push(subscribeCityEvent('error', () => { if (current) overlay.dataset.videoMetadataTransport = 'reconnecting'; }));
      subscriptions.push(subscribeCityEvent('open', () => { if (current) overlay.dataset.videoMetadataTransport = 'open'; }));
      const watchdog = setInterval(() => {
        if (!current) return;
        expireCaptures(); recordGap();
        if (displayedPair && !validScope(displayedPair.frame)) { clear(); publish(null); }
        const now = performance.now(); const age = now - (displayedPair?.at ?? beganAt);
        if (age >= MATCH_STALE_MS && displayedPair && !paused) {
          if (reportTimer) { clearTimeout(reportTimer); reportTimer = null; }
          reportedKey = ''; reportedPlaying = false; pause();
        }
        if (now - lastFrameAt > 10000 || now - Math.max(beganAt, lastMatchReceivedAt) > 10000) restart();
      }, 250);
      stopConnection = () => {
        if (!current) return;
        current = false; subscriptions.forEach(stop => stop()); abort.abort(); pc?.close(); frames.clear();
        // Scope authority still applies to retained pixels during reconnect
        // backoff, when there is no active per-connection paint/watchdog loop.
        element.cancelVideoFrameCallback(callback); element.srcObject = null; redraw.current = invalidateRetained;
        clearInterval(watchdog); if (reportTimer) clearTimeout(reportTimer); if (leaseTimer) clearTimeout(leaseTimer); if (statsTimer) clearTimeout(statsTimer);
        for (const capture of captures.values()) { capture.image.width = 0; capture.image.height = 0; }
        for (const unused of spareImages) { unused.width = 0; unused.height = 0; }
        captures.clear(); spareImages.length = 0;
        if (token) void fetch(API + '/sessions/' + encodeURIComponent(props.sourceId) + '/' + token, { method: 'DELETE', keepalive: true }).catch(() => {});
      };
    };
    overlay.dataset.videoDisplayInterruptions = '0'; overlay.dataset.videoMaxPairGapMs = '0';
    overlay.dataset.videoDisplayState = 'connecting'; latest.current.onStatus('connecting'); begin();
    return () => { active = false; if (reconnect) clearTimeout(reconnect); stopConnection(); redraw.current = null; clear(); latest.current.onPresented(null); };
  }, [props.sourceId, props.expectedSession, key, props.enabled]);

  return <>
    <video ref={video} autoPlay muted playsInline className={styles.trackedVideoSource} aria-label="Analyzed camera WebRTC video" />
    <canvas ref={imageCanvas} className={styles.trackedVideoImage} aria-label="Matched camera video" />
    <canvas ref={canvas} className={styles.trackedVideoOverlay} aria-label="Frame matched WebRTC tracking overlay" style={{ pointerEvents: props.editing ? 'none' : 'auto' }} onClick={event => {
      const frame = hitFrame.current; if (!frame || props.editing) return;
      const point = normalizedPoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(), frame.image.width, frame.image.height, props.fillFrame ? 'cover' : 'contain');
      if (!point) return;
      const x = point[0] * frame.image.width; const y = point[1] * frame.image.height;
      const track = frame.snapshot.tracks.filter(item => !item.stale && item.observedThisFrame !== false
        && x >= item.bboxPx[0] && x <= item.bboxPx[0] + item.bboxPx[2] && y >= item.bboxPx[1] && y <= item.bboxPx[1] + item.bboxPx[3])
        .sort((a, b) => a.bboxPx[2] * a.bboxPx[3] - b.bboxPx[2] * b.bboxPx[3])[0];
      if (track) props.onSelect(track.id);
    }} />
    {message && <div className={styles.trackedVideoMessage} role="status">{message}</div>}
  </>;
}
