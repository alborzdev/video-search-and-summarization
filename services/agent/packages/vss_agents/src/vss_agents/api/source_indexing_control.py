# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Operator-owned finite semantic indexing for live Smart City demonstrations."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.rtsp_ingest import add_to_rtvi_embed
from vss_agents.api.rtsp_ingest import embedding_cleanup_status
from vss_agents.api.rtsp_ingest import embedding_operation_lock
from vss_agents.api.rtsp_ingest import embedding_task_active
from vss_agents.api.rtsp_ingest import get_live_analysis_runtime_steps
from vss_agents.api.rtsp_ingest import get_stream_info_by_name
from vss_agents.api.rtsp_ingest import start_embedding_generation
from vss_agents.api.rtsp_ingest import stop_source_indexing
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import get_source_kind
from vss_agents.api.source_analysis_state import is_source_deleting
from vss_agents.api.source_analysis_state import is_source_paused
from vss_agents.api.source_indexing import IndexingMode
from vss_agents.api.source_indexing import begin_indexing_session
from vss_agents.api.source_indexing import finish_indexing_session
from vss_agents.api.source_indexing import get_indexing_policy
from vss_agents.api.source_indexing import indexing_is_allowed
from vss_agents.api.source_indexing import indexing_policy_error
from vss_agents.api.source_indexing import set_indexing_mode
from vss_agents.tools.vst.utils import get_streams_info


class IndexingPolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    mode: IndexingMode

    model_config = ConfigDict(extra="forbid")


class IndexingActionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    action: Literal["start", "cancel"]
    duration_seconds: int = Field(default=120, alias="durationSeconds", ge=30, le=600, strict=True)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BoothSearchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    session_id: str = Field(alias="sessionId", min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=6, alias="topK", ge=1, le=20, strict=True)

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def _verify_source(config: ServiceConfig, stream_id: str, name: str) -> str:
    if is_source_deleting(stream_id):
        raise HTTPException(status_code=409, detail="Source deletion is in progress")
    if get_source_kind(stream_id) == "recorded":
        raise HTTPException(status_code=409, detail="Finite live indexing requires a live source")
    found, _, resolved_id, url = await get_stream_info_by_name(config, name)
    if not found or resolved_id != stream_id or not url:
        raise HTTPException(status_code=404, detail="The selected live source could not be verified")
    return url


async def _window_evidence(
    config: ServiceConfig, stream_id: str, name: str, start: str | None, end: str | None
) -> dict[str, Any]:
    """ES JSON is an external boundary; a task acknowledgement is not indexing proof."""
    if not config.elasticsearch_url or not start or not end:
        return {"status": "unverified", "documentCount": None, "latestTimestamp": None, "liveFresh": False}
    aliases = sorted({value for value in (stream_id, name) if value})
    query = {
        "size": 1,
        "track_total_hits": True,
        "_source": ["timestamp"],
        "sort": [{"timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "query": {
            "bool": {
                "filter": [
                    {
                        "bool": {
                            "minimum_should_match": 1,
                            "should": [
                                {"terms": {"sensor.id.keyword": aliases}},
                                {"terms": {"info.sensorId.keyword": aliases}},
                            ],
                        }
                    },
                    {"range": {"timestamp": {"gte": start, "lte": end}}},
                ]
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"{config.elasticsearch_url}/mdx-embed-filtered-*/_search", json=query)
            response.raise_for_status()
            hits = response.json()["hits"]
            total = hits["total"]
            count = total["value"] if isinstance(total, dict) else total
            if type(count) is not int or count < 0:
                raise ValueError("Invalid document count")
            documents = hits.get("hits", [])
            latest = documents[0].get("_source", {}).get("timestamp") if documents else None
            age = (
                (datetime.now(UTC) - datetime.fromisoformat(latest.replace("Z", "+00:00"))).total_seconds()
                if isinstance(latest, str)
                else None
            )
            return {
                "status": "indexed-window" if count else "no-documents",
                "documentCount": count,
                "latestTimestamp": latest,
                "liveFresh": age is not None and -5 <= age <= 60,
            }
    except Exception:
        return {"status": "unavailable", "documentCount": None, "latestTimestamp": None, "liveFresh": False}


async def indexing_status(config: ServiceConfig, stream_id: str, name: str) -> dict[str, Any]:
    """Return honest producer state and an explicitly opt-in source/time search scope."""
    allowed = indexing_is_allowed(stream_id)
    policy = get_indexing_policy(stream_id)
    runtime = get_live_analysis_runtime_steps(stream_id)
    connected = bool(runtime.get("embedding"))
    cleanup = embedding_cleanup_status(stream_id)
    now = datetime.now(UTC)
    session = policy.session
    start = _iso(session.started_at or session.requested_at) if session else None
    end = _iso(min(now, session.ended_at or session.deadline_at)) if session else None
    if policy.mode == "continuous" and not session:
        start, end = _iso(now - timedelta(minutes=5)), _iso(now)
    evidence = await _window_evidence(config, stream_id, name, start, end)
    if not (connected and allowed):
        evidence["liveFresh"] = False
    if indexing_policy_error():
        state = "policy-error"
    elif cleanup is not None and not cleanup[0]:
        state = "stop-failed"
    elif is_source_paused(stream_id):
        state = "paused"
    elif embedding_task_active(stream_id) and not allowed:
        state = "stopping"
    elif allowed:
        state = "running" if connected else "recovering"
    elif session:
        state = session.state
    else:
        state = "disabled" if policy.mode == "disabled" else "idle"
    params = (
        {
            "video_sources": json.dumps([name]),
            "exact_sensor_ids": json.dumps([stream_id, name]),
            "timestamp_start": start,
            "timestamp_end": end,
        }
        if start and end and (session is None or session.started_at is not None)
        else None
    )
    return {
        "sensorId": stream_id,
        "name": name,
        "analysisProfileId": get_source_analysis_profile(stream_id),
        "mode": policy.mode,
        "revision": policy.revision,
        "state": state,
        "generationConnected": connected,
        "generationManaged": embedding_task_active(stream_id),
        "indexingRequested": allowed,
        "configured": bool(config.rtvi_embed_url),
        "cvIndependent": True,
        "sourcePaused": is_source_paused(stream_id),
        "session": session.model_dump(mode="json", by_alias=True) if session else None,
        "cleanup": {"status": "confirmed" if cleanup[0] else "failed", "message": cleanup[1]}
        if cleanup
        else {"status": "not-checked"},
        "evidence": evidence,
        "searchScope": {
            "available": params is not None,
            "applied": False,
            "sourceId": stream_id,
            "sourceName": name,
            "timestampStart": start,
            "timestampEnd": end,
            "sourceType": "rtsp",
            "queryParams": params,
            "basis": "source-and-camera-timestamp-range; not an indexed session tag",
        },
        "limits": [
            "Requested wall-clock interval is not proof of complete camera-time coverage; camera clocks remain unverified.",
            "Existing vector history is retained. Search callers must explicitly apply the returned source/time parameters.",
            "General assistant search is not automatically restricted. Booth requests use exact source aliases and time bounds.",
            "Completed means the producer lease ended, not that every chunk reached the search index.",
            "Time bounds select chunk start timestamps; a matching clip can extend past the requested upper bound.",
        ],
    }


def build_booth_search_request(stream_id: str, request: BoothSearchRequest) -> dict[str, Any]:
    """Prepare the existing direct search call with a pinned finite session."""
    indexing_is_allowed(stream_id)
    session = get_indexing_policy(stream_id).session
    if session is None or session.id != request.session_id:
        raise ValueError("The selected indexing session is no longer current; choose a session again")
    if session.started_at is None:
        raise ValueError("This indexing window has no generation acknowledgement yet")
    start = session.started_at
    end = min(datetime.now(UTC), session.ended_at or session.deadline_at)
    if end <= start:
        raise ValueError("This indexing window has no elapsed search interval")
    return {
        "endpoint": "/api/v1/embed_search",
        "method": "POST",
        "sessionId": session.id,
        "scope": {
            "sourceId": stream_id,
            "sourceName": request.name,
            "timestampStart": _iso(start),
            "timestampEnd": _iso(end),
            "basis": "exact-source-aliases-and-chunk-start-timestamps",
            "prepared": True,
            "executed": False,
        },
        "request": {
            "source_type": "rtsp",
            "params": {
                "query": request.query,
                "top_k": str(request.top_k),
                "video_sources": json.dumps([request.name]),
                "exact_sensor_ids": json.dumps([stream_id, request.name]),
                "timestamp_start": _iso(start),
                "timestamp_end": _iso(end),
            },
        },
    }


def create_source_indexing_router(config: ServiceConfig) -> APIRouter:
    router = APIRouter()
    path = "/api/v1/rtsp-streams/{stream_id}/indexing"

    @router.get(path, tags=["RTSP Streams"], summary="Read semantic indexing policy and finite-window evidence")
    async def status(stream_id: str) -> dict[str, Any]:
        streams = await get_streams_info(config.vst_url)
        stream = streams.get(stream_id)
        if (
            not stream
            or get_source_kind(stream_id) == "recorded"
            or not str(stream.get("url", "")).startswith(("rtsp://", "rtsps://"))
        ):
            raise HTTPException(status_code=404, detail="Registered live source not found")
        return await indexing_status(config, stream_id, str(stream.get("name", stream_id)))

    @router.put(path, tags=["RTSP Streams"], summary="Set indexing independently from live detection")
    async def policy(stream_id: str, request: IndexingPolicyRequest) -> dict[str, Any]:
        url = await _verify_source(config, stream_id, request.name)
        async with embedding_operation_lock(stream_id), httpx.AsyncClient(timeout=15.0) as client:
            try:
                set_indexing_mode(stream_id, request.mode)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            success, _ = await stop_source_indexing(client, config, stream_id)
            if request.mode == "continuous" and not is_source_paused(stream_id) and success:
                registered, _, _ = await add_to_rtvi_embed(client, config, stream_id, request.name, url)
                if registered:
                    await start_embedding_generation(None, config, stream_id)
        return await indexing_status(config, stream_id, request.name)

    @router.post(path, tags=["RTSP Streams"], summary="Start or cancel a bounded 30-600 second indexing window")
    async def action(stream_id: str, request: IndexingActionRequest) -> dict[str, Any]:
        url = await _verify_source(config, stream_id, request.name)
        async with embedding_operation_lock(stream_id), httpx.AsyncClient(timeout=15.0) as client:
            if request.action == "cancel":
                if get_indexing_policy(stream_id).mode == "continuous":
                    set_indexing_mode(stream_id, "disabled")
                finish_indexing_session(stream_id, "cancelled", "operator-cancelled")
                await stop_source_indexing(client, config, stream_id)
            else:
                if not config.rtvi_embed_url:
                    raise HTTPException(status_code=409, detail="Semantic embedding is not configured")
                indexing_is_allowed(stream_id)
                prior = get_indexing_policy(stream_id)
                if prior.mode != "on-demand":
                    raise HTTPException(status_code=409, detail="Choose on-demand indexing before starting a window")
                if prior.session and prior.session.state in {"starting", "running"}:
                    raise HTTPException(status_code=409, detail="An indexing window is already active")
                if is_source_paused(stream_id):
                    raise HTTPException(status_code=409, detail="Resume this source before indexing")
                clean, _ = await stop_source_indexing(client, config, stream_id)
                if not clean:
                    raise HTTPException(status_code=409, detail="Previous embedding resources could not be stopped")
                try:
                    begin_indexing_session(stream_id, request.duration_seconds)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                try:
                    registered, _, _ = await add_to_rtvi_embed(client, config, stream_id, request.name, url)
                    started = False
                    if registered:
                        started, _ = await start_embedding_generation(None, config, stream_id)
                    if not started:
                        finish_indexing_session(stream_id, "failed", "generation-start-failed")
                        await stop_source_indexing(client, config, stream_id)
                except BaseException:
                    finish_indexing_session(stream_id, "failed", "indexing-request-interrupted")
                    await stop_source_indexing(client, config, stream_id)
                    raise
        return await indexing_status(config, stream_id, request.name)

    @router.post(
        path + "/search-request", tags=["RTSP Streams"], summary="Prepare direct search scoped to one demo session"
    )
    async def search_request(stream_id: str, request: BoothSearchRequest) -> dict[str, Any]:
        await _verify_source(config, stream_id, request.name)
        try:
            return build_booth_search_request(stream_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
