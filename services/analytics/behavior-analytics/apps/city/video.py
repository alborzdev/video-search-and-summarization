# SPDX-License-Identifier: Apache-2.0
"""Volatile exact RTP/frame identities and bounded, same-origin WHEP sessions.

The relay transports one already-encoded H.264 stream per source. It never
decodes video. Only native RTP timestamps matched to accepted observations
can supply overlays; neither HTTP arrival time nor a nearest timestamp can.
"""
from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import json
import re
import time
from threading import RLock
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from fastapi import HTTPException, Query, Request as WebRequest
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .preview import FrameIdentity, PreviewError, PreviewStore

VIDEO_HISTORY = 16
MAX_SDP = 128 * 1024
MAX_SESSIONS = 16
LEASE_SECONDS = 90
TRACK_FIELDS = set("id sourceId sessionId localTrackId globalTrackId class bboxPx positionM confidence stale observedThisFrame trail mapAssociation modelRevision velocityMps mediaTimeSeconds sourceTimeNs".split())
DYNAMIC_SOURCE = set("sessionId sourceSessionId sequence lastSourceTimeNs status modelRevision timestampBasis mediaTimeSeconds mediaTimeBasis rawSourcePtsNs sourceClockEvidence ingestAgeSeconds sourceClockAgeSeconds sourceClockProgressRatio sourceClockPrecision sourceClockStatus analyticsScope trackingEpoch processedPreview".split())


class VideoStore(PreviewStore):
    def __init__(self, engine):
        super().__init__(engine)
        self.changed = asyncio.Event()

    def stream_records(self, after):
        with self.engine.lock, self.lock:
            self._purge()
            result = {}
            for source in self.engine._site_sources():
                frame = self.frames.get(source)
                records = list(frame["history"]) if frame and frame.get("body") else []
                result[source] = (bool(records), records[-1:] if not after.get(source) else [row for row in records if row[0] > after[source]])
            return result

    def accept_rtp(self, identity: FrameIdentity, value: dict):
        if (not isinstance(value, dict) or set(value) != {"schemaVersion", "rtpTimestamp", "encoder", "clockRate"}
                or value.get("schemaVersion") != "city.video-rtp.v1" or value.get("encoder") != "nvenc-h264"
                or type(value.get("rtpTimestamp")) is not int or not 0 <= value["rtpTimestamp"] < 2**32
                or value.get("clockRate") != 90000):
            raise PreviewError(422, "invalid-native-rtp-identity")
        digest = str(value["rtpTimestamp"])
        with self.engine.lock, self.lock:
            self._purge()
            sample = self._sample(identity)
            if sample is None:
                return None
            generation = self.engine.frame_generation
            duplicate = self._order(identity, digest)
            if duplicate is not None:
                return duplicate
        snapshot = self._snapshot(sample)
        snapshot["tracks"] = [{key: item for key, item in track.items() if key in TRACK_FIELDS} for track in snapshot["tracks"]]
        source = snapshot["sources"][0]
        static = {key: snapshot.pop(key) for key in ("siteId", "siteRevision", "mode", "rulesRevision", "rules")}
        static["sources"] = [{key: item for key, item in source.items() if key not in DYNAMIC_SOURCE}]
        static["zones"] = [{key: item for key, item in zone.items() if key not in {"active", "occupancy"}} for zone in snapshot["zones"]]
        snapshot["sources"] = [{key: item for key, item in source.items() if key in DYNAMIC_SOURCE}]
        snapshot["zones"] = [{key: zone.get(key) for key in ("id", "active", "occupancy")} for zone in snapshot["zones"]]
        static_bytes = self._encode(static)
        manifest_key = hashlib.sha256(static_bytes + str(generation).encode() + source["sessionId"].encode()).hexdigest()
        manifest = {"schemaVersion": "city.video-manifest.v1", "key": manifest_key, "sourceId": identity.source,
                    "sessionId": source["sessionId"], "sourceSessionId": identity.session, "snapshot": static}
        frame = {
            "schemaVersion": "city.video-frame.v1", "manifestKey": manifest_key,
            "sourceId": identity.source, "sourceSessionId": identity.session, "sessionId": source["sessionId"],
            "sequence": identity.sequence, "sourceTimeNs": identity.ns,
            "timestampBasis": source["timestampBasis"], "sourceClockEvidence": source.get("sourceClockEvidence"),
            "modelRevision": source["modelRevision"],
            "image": {"width": identity.width, "height": identity.height},
            "provenance": {"kind": "native-webrtc-exact-frame", "correlation": "source-session-sequence-time-rtp",
                           "clockAlignment": "source-frame-exact", "browserClockVerified": False},
            "transport": {"kind": "webrtc-rtp", "rtpTimestamp": value["rtpTimestamp"], "clockRate": 90000,
                          "codec": "H264", "encoder": "nvenc-h264"},
            "snapshot": snapshot,
        }
        encoded, manifest_encoded = self._encode(frame), self._encode(manifest)
        with self.engine.lock, self.lock:
            self._purge()
            if generation != self.engine.frame_generation or self._sample(identity) is not sample:
                raise PreviewError(409, "video-frame-superseded-during-encoding")
            duplicate = self._order(identity, digest)
            if duplicate is not None:
                return duplicate
            old = self.frames.get(identity.source)
            history = old["history"] if old and old.get("body") else deque(maxlen=VIDEO_HISTORY)
            self.accepted += 1
            history.append((self.accepted, manifest_key, manifest_encoded, encoded))
            self.frames[identity.source] = {
                "body": encoded, "manifest": manifest_encoded, "history": history,
                "etag": str(self.accepted), "digest": digest, "receivedAt": self.engine.clock(),
                "generation": generation, "sessionId": source["sessionId"], "sourceSessionId": identity.session,
                "sequence": identity.sequence, "sourceTimeNs": identity.ns,
            }
        return {"accepted": True, "duplicate": False}

    def read(self, source_id: str, expected_session: str, after: int = 0):
        with self.engine.lock, self.lock:
            self._purge()
            frame = self.frames.get(source_id)
            if not frame or not frame.get("body") or frame["sessionId"] != expected_session:
                raise PreviewError(409, "video-session-unavailable")
            # A new viewer only needs the latest manifest/frame. Existing
            # readers can catch up within the bounded matching window.
            records = list(frame["history"])
            return records[-1:] if not after else [row for row in records if row[0] > after]

    def stream_path(self, source_id: str, expected_session: str):
        with self.engine.lock, self.lock:
            self._purge()
            frame = self.frames.get(source_id)
            if not frame or not frame.get("body") or frame["sessionId"] != expected_session:
                raise PreviewError(409, "video-session-unavailable")
            return "city/" + quote(source_id, safe="") + "/" + quote(frame["sourceSessionId"], safe="")

    def _purge(self):
        super()._purge()
        for frame in self.frames.values():
            if not frame.get("body"):
                frame.pop("history", None)
                frame.pop("manifest", None)

    def health(self):
        with self.engine.lock, self.lock:
            self._purge()
            return {"transport": "webrtc", "acceptedFrames": self.accepted, "maximumSources": 2,
                    "historyFramesPerSource": VIDEO_HISTORY, "ttlSeconds": 2,
                    "retainedBytes": sum(len(item[2]) + len(item[3]) for frame in self.frames.values() for item in frame.get("history", ())),
                    "sources": [{"id": source, **self.capability(source)} for source in self.engine._site_sources()]}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WhepSessions:
    def __init__(self, store: VideoStore, base: str = "http://127.0.0.1:9192"):
        self.store, self.base = store, base
        self.lock, self.sessions = RLock(), {}
        self.http = build_opener(NoRedirect())

    def _release(self, url):
        try:
            with self.http.open(Request(url, method="DELETE"), timeout=2):
                pass
        except OSError:
            pass

    def close(self, token):
        with self.lock:
            entry = self.sessions.pop(token, None)
        if entry and entry.get("url"):
            self._release(entry["url"])

    def reap(self):
        with self.lock:
            entries = list(self.sessions.items())
        for token, entry in entries:
            try:
                if time.monotonic() > entry["deadline"]:
                    raise PreviewError(409, "video-lease-expired")
                self.store.stream_path(entry["source"], entry["session"])
            except PreviewError:
                self.close(token)

    def shutdown(self):
        with self.lock:
            tokens = list(self.sessions)
        for token in tokens:
            self.close(token)

    def create(self, source_id, expected_session, offer):
        path = self.store.stream_path(source_id, expected_session)
        self.reap()
        token = uuid4().hex
        with self.lock:
            if len(self.sessions) >= MAX_SESSIONS:
                raise PreviewError(503, "video-viewer-capacity")
            self.sessions[token] = {"source": source_id, "session": expected_session, "deadline": time.monotonic() + LEASE_SECONDS}
        upstream = self.base + "/" + path + "/whep"
        try:
            with self.http.open(Request(upstream, data=offer, headers={"Content-Type": "application/sdp"}), timeout=5) as response:
                answer = response.read(MAX_SDP + 1)
                location = urljoin(upstream, response.headers.get("Location", ""))
                parsed, origin = urlsplit(location), urlsplit(self.base)
                if (response.status != 201 or len(answer) > MAX_SDP or not answer.startswith(b"v=0")
                        or (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
                        or not parsed.path.startswith("/" + path + "/whep/") or parsed.query or parsed.fragment):
                    raise PreviewError(502, "invalid-video-relay-answer")
            with self.lock:
                entry = self.sessions.get(token)
                if entry:
                    entry["url"] = location
            if entry is None:
                self._release(location)
                raise PreviewError(409, "video-viewer-retired-during-negotiation")
            # The worker might restart during SDP negotiation. Retire this
            # connection rather than offering a new epoch under an old key.
            if self.store.stream_path(source_id, expected_session) != path:
                raise PreviewError(409, "video-session-changed")
            return token, answer
        except (OSError, PreviewError) as exc:
            self.close(token)
            if isinstance(exc, PreviewError):
                raise
            raise PreviewError(503, "video-relay-unavailable") from exc

    def touch(self, source_id, token):
        with self.lock:
            entry = self.sessions.get(token)
            if not entry or entry["source"] != source_id:
                raise PreviewError(404, "video-viewer-unavailable")
            self.store.stream_path(source_id, entry["session"])
            entry["deadline"] = time.monotonic() + LEASE_SECONDS


def install_video_routes(app, engine):
    store = VideoStore(engine)
    sessions = WhepSessions(store)
    app.state.video, app.state.video_sessions = store, sessions

    def error(exc):
        return HTTPException(exc.status, exc.reason)

    @app.post("/api/v1/city/video/frame")
    async def publish(request: WebRequest):
        try:
            body = await request.body()
            if len(body) > 2048 or request.headers.get("content-type") != "application/json":
                raise PreviewError(422, "invalid-video-identity-body")
            identity, value = FrameIdentity.headers(request.headers), json.loads(body)
            deadline = asyncio.get_running_loop().time() + .2
            while True:
                result = await run_in_threadpool(store.accept_rtp, identity, value)
                if result is not None:
                    if not result["duplicate"]:
                        previous, store.changed = store.changed, asyncio.Event()
                        previous.set()
                    return Response(json.dumps(result), status_code=200 if result["duplicate"] else 201, media_type="application/json")
                if asyncio.get_running_loop().time() >= deadline:
                    return Response(status_code=202)
                await asyncio.sleep(.01)
        except PreviewError as exc:
            raise error(exc) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "invalid-video-identity") from exc

    @app.get("/api/v1/city/video/metadata/{source_id}")
    async def metadata(source_id: str, request: WebRequest, sessionId: str = Query(min_length=1, max_length=200)):
        try:
            await run_in_threadpool(store.read, source_id, sessionId)
        except PreviewError as exc:
            raise error(exc) from exc

        async def frames():
            after, manifest = 0, None
            yield "retry: 1000\n\n"
            while not await request.is_disconnected():
                signal = store.changed
                try:
                    records = await run_in_threadpool(store.read, source_id, sessionId, after)
                except PreviewError:
                    yield 'event: reset\ndata: {}\n\n'
                    return
                for serial, key, config, frame in records:
                    if key != manifest:
                        yield b"event: manifest\ndata: " + config + b"\n\n"
                        manifest = key
                    yield b"event: frame\ndata: " + frame + b"\n\n"
                    after = serial
                try:
                    await asyncio.wait_for(signal.wait(), 1)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/city/video/whep/{source_id}")
    async def offer(source_id: str, request: WebRequest, sessionId: str = Query(min_length=1, max_length=200)):
        body = await request.body()
        if request.headers.get("content-type") != "application/sdp" or not 1 <= len(body) <= MAX_SDP or not body.startswith(b"v=0"):
            raise HTTPException(422, "invalid-video-offer")
        try:
            token, answer = await run_in_threadpool(sessions.create, source_id, sessionId, body)
        except PreviewError as exc:
            raise error(exc) from exc
        if await request.is_disconnected():
            await run_in_threadpool(sessions.close, token)
            return Response(status_code=499)
        return Response(answer, status_code=201, media_type="application/sdp", headers={"X-City-Video-Session": token, "Cache-Control": "no-store"})

    @app.api_route("/api/v1/city/video/sessions/{source_id}/{token}", methods=["PUT", "DELETE"])
    async def lease(source_id: str, token: str, request: WebRequest):
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise HTTPException(404, "video-viewer-unavailable")
        try:
            if request.method == "DELETE":
                with sessions.lock:
                    entry = sessions.sessions.get(token)
                    if entry and entry["source"] != source_id:
                        raise PreviewError(404, "video-viewer-unavailable")
                await run_in_threadpool(sessions.close, token)
            else:
                await run_in_threadpool(sessions.touch, source_id, token)
        except PreviewError as exc:
            raise error(exc) from exc
        return Response(status_code=204)

    return store
