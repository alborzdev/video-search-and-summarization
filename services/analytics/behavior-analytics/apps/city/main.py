# SPDX-License-Identifier: Apache-2.0
"""Run with uvicorn apps.city.main:app --host 0.0.0.0 --port 9184."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import time
from threading import RLock
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .engine import CityEngine, ConflictError
from .models import MobilityConfig, Observation, RuleSet, Site
from .native import NativeAnalyticsBridge
from .preview import (
    FRAME_MEDIA_TYPE,
    MAX_JPEG_BYTES,
    FrameIdentity,
    PreviewError,
    PreviewStore,
    jpeg_dimensions,
    native_preview_status,
)
from .scenario_boundary import ScenarioBoundary
from .store import CityStore
from .video import install_video_routes


class RequestBodyLimitMiddleware:
    """Bound request memory for ordinary and chunked HTTP bodies alike."""
    def __init__(self, app, maximum: int = 8 * 1024 * 1024):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        maximum = MAX_JPEG_BYTES if scope["path"] == "/api/v1/city/preview" else self.maximum
        if scope["path"] == "/api/v1/city/video/frame":
            maximum = 2048
        elif scope["path"].startswith("/api/v1/city/video/whep/"):
            maximum = 128 * 1024
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > maximum):
            return await Response("request body exceeds route limit", status_code=413)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > maximum:
                return await Response("request body exceeds route limit", status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        return await self.app(scope, replay_receive, send)


def _load_media(engine: CityEngine, registry: dict[str, str] | None = None, root: str | None = None):
    """Registration is server configuration, never an HTTP-supplied file path."""
    registry = registry if registry is not None else json.loads(os.environ.get("CITY_MEDIA_REGISTRY_JSON", "{}"))
    media_root = Path(root or os.environ.get("CITY_MEDIA_ROOT", "/opt/city/media")).resolve()
    validated = {}
    for source_id, relative_path in registry.items():
        candidate = (media_root / relative_path).resolve()
        if not candidate.is_relative_to(media_root) or not candidate.is_file():
            raise ValueError(f"media registration for {source_id} is missing or outside media root")
        validated[source_id] = str(candidate)
    engine.media.update(validated)


def create_app(engine: CityEngine | None = None, media_registry: dict[str, str] | None = None, media_root: str | None = None) -> FastAPI:
    owned_store = engine is None
    if engine is None:
        engine = CityEngine(CityStore(os.environ.get("CITY_STATE_DB", "/tmp/vss-city/state.sqlite3")))
    _load_media(engine, media_registry, media_root)
    native = NativeAnalyticsBridge(os.environ.get("CITY_NATIVE_CONFIG_DIR"))
    previews = PreviewStore(engine)
    # Replace, rather than clear, each notification. Readers retain their own
    # generation while checking the store off-thread, so publication cannot be
    # lost between that check and awaiting the next exact frame.
    preview_changed = asyncio.Event()
    site_file = os.environ.get("CITY_SITE_FILE")
    rules_file = os.environ.get("CITY_RULES_FILE")
    if site_file and not engine.site.sources:
        engine.put_site(Site.model_validate_json(Path(site_file).read_text()))
    if rules_file and not engine.rules:
        raw_rules = json.loads(Path(rules_file).read_text())
        engine.put_rules(RuleSet.model_validate({"rules": raw_rules} if isinstance(raw_rules, list) else raw_rules))
    native.apply(engine.site, engine.rules, engine.rules_revision)
    boundary = ScenarioBoundary(engine, native.directory)

    @asynccontextmanager
    async def lifespan(app):
        async def reap_video_sessions():
            while True:
                await asyncio.sleep(5)
                await run_in_threadpool(app.state.video_sessions.reap)
        reaper = asyncio.create_task(reap_video_sessions())
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await run_in_threadpool(app.state.video_sessions.shutdown)
            if owned_store:
                engine.store.close()

    app = FastAPI(title="VSS Smart City Analytics", version="1.0.0", lifespan=lifespan)
    app.state.city = engine
    app.state.previews = previews
    app.add_middleware(RequestBodyLimitMiddleware)
    videos = install_video_routes(app, engine)

    def decorate_preview(payload):
        payload = previews.decorate(payload)
        for source in payload.get("sources", []):
            video = videos.capability(source["id"])
            if video["available"]:
                source["processedPreview"] = {**video, "transport": "webrtc"}
        return payload

    def native_status():
        result = native.status()
        with engine.lock:
            has_frames = bool(engine.sources)
            fresh = any(engine.clock() - source["received"] <= engine.freshness for source in engine.sources.values())
        result.update(lastAppliedRevision=result.get("appliedRevision"), operationalStatus="fresh" if fresh else ("stale" if has_frames else "awaiting-observations"))
        if result["status"] == "active" and not fresh:
            result.update(status="applied-inactive", lastAppliedStatus="active")
        return result

    @app.get("/api/v1/city/health")
    def health():
        state = engine.health_state()
        preview_health = previews.health()
        preview_health["nativeDelivery"] = native_preview_status(native.directory, engine._site_sources())
        return {"status": "ok", "service": "vss-city-analytics", **state, "nativeAnalyticsStatus": native_status(), "processedPreview": preview_health, "processedVideo": videos.health(), "globalFusionEnabled": False, "scenarioBoundary": boundary.status()}

    @app.get("/api/v1/city/scenario-boundary")
    def scenario_boundary_get():
        return boundary.status()

    @app.post("/api/v1/city/scenario-boundary")
    def scenario_boundary_post(payload: dict):
        try:
            return boundary.command(payload)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/city/analytics-scopes")
    def analytics_scopes_get():
        with engine.lock:
            return {"current": engine.scope_json(), "prior": engine.store.get(f"analytics-scopes:{engine.site.id}", [])}

    @app.get("/api/v1/city/site")
    def site_get():
        return decorate_preview(engine.site_json())

    @app.put("/api/v1/city/site")
    def site_put(site: Site):
        try:
            result = engine.put_site(site)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        native.apply(engine.site, engine.rules, engine.rules_revision)
        return result

    @app.get("/api/v1/city/rules")
    def rules_get():
        with engine.lock:
            return {**engine.rules_json(), "nativeAnalytics": native_status()}

    @app.put("/api/v1/city/rules")
    def rules_put(payload: RuleSet):
        try:
            result = engine.put_rules(payload)
            return {**result, "nativeAnalytics": native.apply(engine.site, engine.rules, engine.rules_revision)}
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/city/observations")
    def observations_post(observation: Observation):
        try:
            return engine.ingest(observation)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/city/snapshot")
    def snapshot(sourceId: str | None = None, mediaTimeSeconds: float | None = Query(default=None, ge=0), sourceTimeNs: str | None = Query(default=None, pattern=r"^\d{1,19}$"), maximumSkewSeconds: float = Query(default=0.25, ge=0, le=5)):
        return decorate_preview({**engine.snapshot(sourceId, mediaTimeSeconds, maximumSkewSeconds, int(sourceTimeNs) if sourceTimeNs is not None else None), "nativeAnalytics": native_status()})

    @app.get("/api/v1/city/mobility")
    def mobility_get(windowMinutes: int = Query(default=5)):
        try:
            return engine.mobility_json(windowMinutes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/v1/city/mobility/config")
    def mobility_config_put(config: MobilityConfig):
        try:
            return engine.put_mobility_config(config)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/city/preview")
    async def preview_post(request: Request):
        nonlocal preview_changed
        try:
            if request.headers.get("content-type", "").split(";", 1)[0].lower() != "image/jpeg":
                raise PreviewError(415, "preview-content-type-must-be-image-jpeg")
            identity = FrameIdentity.headers(request.headers)
            jpeg = await request.body()
            dimensions = jpeg_dimensions(jpeg)
            deadline = asyncio.get_running_loop().time() + 0.2
            while True:
                # Hashing and building the exact-frame envelope can be CPU
                # work. Keep it off the ASGI loop so one camera cannot stall
                # observation ingress, the other camera or preview readers.
                result = await run_in_threadpool(previews.accept, identity, jpeg, dimensions)
                if result is not None:
                    if not result["duplicate"]:
                        changed, preview_changed = preview_changed, asyncio.Event()
                        changed.set()
                    return Response(json.dumps(result), status_code=200 if result["duplicate"] else 201, media_type="application/json", headers={"Cache-Control": "no-store"})
                if asyncio.get_running_loop().time() >= deadline:
                    return Response(json.dumps({"accepted": False, "reason": "metadata-pending", "retryable": True}), status_code=202, media_type="application/json", headers={"Cache-Control": "no-store"})
                await asyncio.sleep(0.01)
        except PreviewError as exc:
            raise HTTPException(exc.status, exc.reason) from exc

    @app.get("/api/v1/city/preview/{source_id}")
    async def preview_get(source_id: str, request: Request, waitMs: int = Query(default=0, ge=0, le=1000)):
        deadline = asyncio.get_running_loop().time() + waitMs / 1000
        while True:
            changed = preview_changed
            try:
                body, etag, status = await run_in_threadpool(previews.get, source_id)
            except PreviewError as exc:
                raise HTTPException(exc.status, exc.reason) from exc
            headers = {"Cache-Control": "no-store", "X-City-Preview-Status": status, "X-Content-Type-Options": "nosniff"}
            if body is None:
                return Response(status_code=204, headers=headers)
            headers["ETag"] = etag
            if request.headers.get("if-none-match") != etag:
                return Response(body, media_type=FRAME_MEDIA_TYPE, headers=headers)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return Response(status_code=304, headers=headers)
            try:
                await asyncio.wait_for(changed.wait(), remaining)
            except asyncio.TimeoutError:
                # Recheck expiry/session validity even when no frame arrived.
                deadline = 0

    @app.get("/api/v1/city/events")
    def events(sourceId: str | None = None, ruleId: str | None = None, state: str | None = None, limit: int = Query(default=100, ge=1, le=1000)):
        with engine.lock:
            # Query durable history so missed browser notifications are recoverable.
            records = engine.store.events(limit, site_id=engine.site.id, source_id=sourceId, rule_id=ruleId, state=state)
            return {"events": records, "limit": limit, "mode": engine.site.mode}

    @app.get("/api/v1/city/reports")
    def reports(format: str = "json"):
        with engine.lock:
            records = engine.store.events(1000, site_id=engine.site.id)
            totals = {}
            for event in records:
                totals[event["kind"]] = totals.get(event["kind"], 0) + 1
            if format == "csv":
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=["id", "sourceId", "ruleId", "kind", "state", "startedAt", "triggeredAt", "endedAt", "mode"])
                writer.writeheader()
                writer.writerows({key: event.get(key) for key in writer.fieldnames} for event in records)
                return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="smart-city-events.csv"'})
            if format != "json":
                raise HTTPException(status_code=422, detail="format must be json or csv")
            return {"siteId": engine.site.id, "mode": engine.site.mode, "eventCount": len(records), "totalsByKind": totals, "events": records, "qualification": "Structured observations; camera-local totals may include the same object in multiple cameras", "truncated": len(records) == 1000}

    @app.get("/api/v1/city/showcase")
    def showcase():
        with engine.lock:
            return {"siteId": engine.site.id, "mode": engine.site.mode,
                    "analyticsScope": engine.scope_json(), "measurements": engine.showcase.snapshot(engine)}

    stream_cache, stream_cache_lock = {}, RLock()

    def encode_stream_snapshot():
        # Health summaries have one shared 4 Hz cadence. Serializing identical
        # full snapshots independently for every viewer competes with native
        # observation/metadata admission under Python's GIL.
        with stream_cache_lock:
            with engine.lock:
                key = (engine.frame_generation, engine.site.revision, engine.rules_revision)
            now = time.monotonic()
            if stream_cache.get("key") == key and now - stream_cache["at"] < .25:
                return stream_cache["body"]
            snapshot = decorate_preview(engine.snapshot())
            body = f"id: {snapshot['sequence']}\nevent: snapshot\ndata: {json.dumps(snapshot, separators=(',', ':'), allow_nan=False)}\n\n"
            stream_cache.update(key=key, at=time.monotonic(), body=body)
            return body

    @app.get("/api/v1/city/stream")
    async def stream(request: Request, video: bool = False):
        async def snapshots():
            after, manifests, ready = {}, {}, set()
            loop = asyncio.get_running_loop()
            next_snapshot = 0
            pending_snapshot = None
            try:
                while not await request.is_disconnected():
                    signal = videos.changed
                    if not video:
                        yield await run_in_threadpool(encode_stream_snapshot)
                        await asyncio.sleep(.25)
                        continue
                    # Exact frame metadata has a presentation deadline. Building
                    # a large health snapshot must not hold its SSE delivery up.
                    rows = await run_in_threadpool(videos.stream_records, after)
                    for source, (available, records) in rows.items():
                        if not available and source in ready:
                            yield f"event: video-reset:{source}\ndata: {{}}\n\n"
                            ready.discard(source)
                            manifests.pop(source, None)
                        for serial, key, config, frame in records:
                            if manifests.get(source) != key:
                                yield b"event: video-manifest:" + source.encode() + b"\ndata: " + config + b"\n\n"
                                manifests[source] = key
                            yield b"event: video-frame:" + source.encode() + b"\ndata: " + frame + b"\n\n"
                            after[source] = serial
                            ready.add(source)
                    if pending_snapshot is not None and pending_snapshot.done():
                        yield pending_snapshot.result()
                        pending_snapshot = None
                        next_snapshot = loop.time() + .25
                    if pending_snapshot is None and loop.time() >= next_snapshot:
                        pending_snapshot = asyncio.create_task(run_in_threadpool(encode_stream_snapshot))
                    changed = asyncio.create_task(signal.wait())
                    try:
                        await asyncio.wait({changed, pending_snapshot} if pending_snapshot is not None else {changed},
                                           timeout=None if pending_snapshot is not None else max(.001, next_snapshot - loop.time()),
                                           return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        changed.cancel()
                        with suppress(asyncio.CancelledError):
                            await changed
            finally:
                if pending_snapshot is not None:
                    pending_snapshot.cancel()
                    with suppress(asyncio.CancelledError):
                        await pending_snapshot
        return StreamingResponse(snapshots(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/v1/city/media/{source_id}")
    def media(source_id: str):
        path = engine.media.get(source_id)
        if source_id not in engine._site_sources() or path is None or not Path(path).is_file():
            raise HTTPException(status_code=404, detail="no registered recording for source")
        return FileResponse(path, media_type="video/mp4", filename=None, headers={"Cache-Control": "private, max-age=60"})

    @app.put("/api/v1/city/media-registration")
    def media_registration(payload: dict):
        sources = payload.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 16:
            raise HTTPException(422, "sources must contain at most 16 controlled recordings")
        registry = {}
        for source in sources:
            if not isinstance(source, dict) or source.get("sourceId") not in engine._site_sources():
                raise HTTPException(422, "media source must be registered in the current site")
            filename = source.get("filename")
            if not isinstance(filename, str) or Path(filename).name != filename or not filename.lower().endswith((".mp4", ".webm", ".avi", ".mkv")):
                raise HTTPException(422, "filename must name an existing controlled video")
            registry[source["sourceId"]] = filename
        try:
            _load_media(engine, registry, media_root)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        engine.media = {source_id: path for source_id, path in engine.media.items() if source_id in registry}
        return {"registeredSourceIds": list(registry)}

    return app


app = create_app()
