# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pause and resume live analysis without removing a registered source."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
import logging
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from vss_agents.api.analysis_profile_capacity import AnalysisProfileCapacityError
from vss_agents.api.analysis_profile_capacity import claim_source_analysis_profile_capacity
from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import WAREHOUSE_PROFILE_ID
from vss_agents.api.analysis_profiles import require_analysis_profile
from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.rtsp_ingest import _resolve_service_config
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_generation
from vss_agents.api.rtsp_ingest import cleanup_source_from_all_rtvi_cv
from vss_agents.api.rtsp_ingest import detector_endpoint_for_profile
from vss_agents.api.rtsp_ingest import get_live_analysis_runtime_steps
from vss_agents.api.rtsp_ingest import get_stream_info_by_name
from vss_agents.api.rtsp_ingest import reconcile_live_source_now
from vss_agents.api.rtsp_ingest import set_live_analysis_runtime_steps
from vss_agents.api.rtsp_ingest import stop_managed_embedding_generation
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import is_source_detection_enabled
from vss_agents.api.source_analysis_state import is_source_paused
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.api.source_analysis_state import set_source_paused
from vss_agents.tools.vst.utils import get_streams_info as vst_get_streams_info
from vss_agents.utils.sanitize import scrub_log

logger = logging.getLogger(__name__)


async def _semantic_index_is_fresh(config: ServiceConfig, stream_id: str, *, max_age_seconds: float = 60.0) -> bool:
    """Prove that live embeddings are reaching Elasticsearch, not just decoding."""
    if not config.elasticsearch_url:
        return True
    try:
        # RTVI resources are keyed by VST UUID, but NVIDIA's embedding
        # document schema uses the human-readable VST sensor name. Resolve
        # both identities so this health probe follows the same source across
        # that boundary instead of silently querying the wrong identifier.
        source_identifiers = {stream_id}
        streams = await vst_get_streams_info(config.vst_url)
        stream_name = streams.get(stream_id, {}).get("name", "").strip()
        if stream_name:
            source_identifiers.add(stream_name)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{config.elasticsearch_url}/mdx-embed-filtered-*/_search",
                json={
                    "_source": ["timestamp"],
                    "query": {
                        "bool": {
                            "minimum_should_match": 1,
                            "should": [
                                {"terms": {"info.sensorId.keyword": sorted(source_identifiers)}},
                                {"terms": {"sensor.id.keyword": sorted(source_identifiers)}},
                            ],
                        }
                    },
                    "size": 1,
                    "sort": [{"timestamp": {"order": "desc", "unmapped_type": "date"}}],
                },
            )
            response.raise_for_status()
            hits = response.json().get("hits", {}).get("hits", [])
            timestamp = hits[0].get("_source", {}).get("timestamp") if hits else None
            if not isinstance(timestamp, str):
                return False
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()
            return -5.0 <= age <= max_age_seconds
    except Exception:
        logger.warning(
            "Could not prove fresh semantic indexing for %s",
            scrub_log(stream_id),
            exc_info=True,
        )
        return False


class SourceAnalysisRequest(BaseModel):
    action: Literal["configure", "pause", "resume"]
    name: str = Field(min_length=1, max_length=256)
    detection_enabled: bool | None = Field(default=None, alias="detectionEnabled")
    analysis_profile_id: str | None = Field(default=None, alias="analysisProfileId")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def require_detection_choice_for_configuration(self) -> SourceAnalysisRequest:
        if self.action == "configure" and self.detection_enabled is None and self.analysis_profile_id is None:
            raise ValueError("configure requires analysisProfileId")
        if self.analysis_profile_id is not None:
            require_analysis_profile(self.analysis_profile_id)
        return self

    def resolved_profile_id(self) -> str:
        if self.analysis_profile_id is not None:
            return self.analysis_profile_id
        return SEMANTIC_PROFILE_ID if self.detection_enabled is False else WAREHOUSE_PROFILE_ID


class SourceAnalysisResponse(BaseModel):
    action: Literal["configure", "pause", "resume", "status"]
    analysis_active: bool = Field(alias="analysisActive")
    detection_enabled: bool = Field(alias="detectionEnabled")
    analysis_profile_id: str = Field(alias="analysisProfileId")
    message: str
    name: str
    sensor_id: str = Field(alias="sensorId")
    state: Literal["active", "paused", "partial"]
    steps: dict[str, bool] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


def create_source_control_router(config: ServiceConfig) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/rtsp-streams/{stream_id}/analysis",
        response_model=SourceAnalysisResponse,
        tags=["RTSP Streams"],
        summary="Read the desired live-analysis state",
    )
    async def analysis_status(stream_id: str) -> SourceAnalysisResponse:
        paused = is_source_paused(stream_id)
        profile_id = get_source_analysis_profile(stream_id)
        detection_enabled = is_source_detection_enabled(stream_id)
        steps = get_live_analysis_runtime_steps(stream_id)
        detector_endpoint = detector_endpoint_for_profile(config, profile_id)
        if not detection_enabled:
            # Do not let stale runtime state advertise a detector after the
            # operator has selected semantic-only analysis.
            steps["detection"] = False
        elif not detector_endpoint:
            steps["detection"] = False
        if not config.rtvi_embed_url:
            steps["embedding_resource"] = True
            steps["embedding"] = True
        steps["indexing"] = False if paused else await _semantic_index_is_fresh(config, stream_id)

        active = (
            bool(steps)
            and (not detection_enabled or steps.get("detection", False))
            and steps.get("embedding", False)
            and steps.get("indexing", False)
        )
        if paused:
            state: Literal["active", "paused", "partial"] = "paused"
            message = "Live analysis is paused"
        elif active:
            state = "active"
            message = "Live analysis is active"
        else:
            state = "partial"
            message = "Source is registered; live analysis is recovering"
        return SourceAnalysisResponse(
            action="status",
            analysis_active=active and not paused,
            detection_enabled=detection_enabled,
            analysis_profile_id=profile_id,
            message=message,
            name="",
            sensor_id=stream_id,
            state=state,
            steps=steps,
        )

    @router.post(
        "/api/v1/rtsp-streams/{stream_id}/analysis",
        response_model=SourceAnalysisResponse,
        tags=["RTSP Streams"],
        summary="Pause or resume live analysis",
        description=(
            "Stops or restores detection and semantic embedding for one registered "
            "live source. The UI history controller coordinates Cosmos captioning "
            "with its saved scenario. Retained media and indexed history are unchanged."
        ),
    )
    async def set_analysis_state(stream_id: str, request: SourceAnalysisRequest) -> SourceAnalysisResponse:
        found, _, resolved_id, rtsp_url = await get_stream_info_by_name(config, request.name)
        if not found or resolved_id != stream_id or not rtsp_url:
            return SourceAnalysisResponse(
                action=request.action,
                analysis_active=False,
                detection_enabled=is_source_detection_enabled(stream_id),
                analysis_profile_id=get_source_analysis_profile(stream_id),
                message="The selected live source could not be verified",
                name=request.name,
                sensor_id=stream_id,
                state="partial",
            )

        steps: dict[str, bool] = {}
        if request.action == "configure":
            profile = require_analysis_profile(request.resolved_profile_id())
            try:
                claim_source_analysis_profile_capacity(stream_id, profile.id)
            except AnalysisProfileCapacityError as exc:
                raise HTTPException(status_code=409, detail=exc.detail) from exc

        # A successful request through the live-camera control surface is an
        # authoritative schema-v4 migration signal for older saved sources.
        # Keep a rejected finite-profile switch free of any durable mutation.
        set_source_kind(stream_id, "live")

        async with httpx.AsyncClient(timeout=60.0) as client:
            if request.action == "configure":
                paused = is_source_paused(stream_id)
                if paused:
                    detector_stopped, detector_message = await cleanup_source_from_all_rtvi_cv(
                        client, config, stream_id, request.name, rtsp_url
                    )
                    steps = get_live_analysis_runtime_steps(stream_id)
                    steps["detection"] = False
                    set_live_analysis_runtime_steps(stream_id, steps)
                    complete = detector_stopped
                    if not detector_stopped:
                        logger.warning(
                            "Detector profile change is waiting for %s: %s",
                            scrub_log(stream_id),
                            scrub_log(detector_message),
                        )
                else:
                    try:
                        steps = await reconcile_live_source_now(
                            config,
                            stream_id,
                            request.name,
                            rtsp_url,
                        )
                    except Exception:
                        logger.warning(
                            "Detector profile change failed for %s",
                            scrub_log(stream_id),
                            exc_info=True,
                        )
                        steps = get_live_analysis_runtime_steps(stream_id)
                        steps["detection"] = False
                    complete = (not profile.detection_enabled or steps.get("detection", False)) and steps.get(
                        "embedding", False
                    )

                state: Literal["active", "paused", "partial"]
                if paused:
                    state = "paused"
                elif complete:
                    state = "active"
                else:
                    state = "partial"
                return SourceAnalysisResponse(
                    action="configure",
                    analysis_active=state == "active",
                    detection_enabled=profile.detection_enabled,
                    analysis_profile_id=profile.id,
                    message=(
                        f"{profile.name} enabled"
                        if complete and not paused
                        else "Analytics profile saved for the next resume"
                        if paused
                        else "The requested analytics profile is still being applied"
                    ),
                    name=request.name,
                    sensor_id=stream_id,
                    state=state,
                    steps=steps,
                )

            if request.action == "pause":
                # Persist desired-paused before touching ephemeral services so
                # a concurrent reboot can never reactivate this source.
                set_source_paused(stream_id, True)
                await stop_managed_embedding_generation(stream_id)
                for key, result in (
                    (
                        "embedding",
                        await cleanup_rtvi_embed_generation(client, config, stream_id),
                    ),
                    (
                        "detection",
                        await cleanup_source_from_all_rtvi_cv(
                            client,
                            config,
                            stream_id,
                            request.name,
                            rtsp_url,
                        ),
                    ),
                ):
                    steps[key] = result[0]
                complete = all(steps.values())
                set_live_analysis_runtime_steps(
                    stream_id,
                    {
                        "detection": False,
                        "embedding_resource": True,
                        "embedding": False,
                    },
                )
                logger.info(
                    "Live analysis pause for %s: %s",
                    scrub_log(stream_id),
                    "complete" if complete else "partial",
                )
                return SourceAnalysisResponse(
                    action="pause",
                    analysis_active=False,
                    detection_enabled=is_source_detection_enabled(stream_id),
                    analysis_profile_id=get_source_analysis_profile(stream_id),
                    message=(
                        "Live analysis paused; retained and indexed evidence was preserved"
                        if complete
                        else "Some analysis services could not be paused"
                    ),
                    name=request.name,
                    sensor_id=stream_id,
                    state="paused" if complete else "partial",
                    steps=steps,
                )

            # Desired-active is durable even when a dependency is still
            # booting; the background reconciler will continue recovery.
            set_source_paused(stream_id, False)
            try:
                steps = await reconcile_live_source_now(config, stream_id, request.name, rtsp_url)
            except Exception:
                logger.warning(
                    "Immediate live-analysis recovery failed for %s",
                    scrub_log(stream_id),
                    exc_info=True,
                )
                steps = {
                    "detection": False,
                    "embedding_resource": False,
                    "embedding": False,
                    "caption_resource": False,
                }
                set_live_analysis_runtime_steps(stream_id, steps)
            detection_enabled = is_source_detection_enabled(stream_id)
            profile_id = get_source_analysis_profile(stream_id)
            complete = (not detection_enabled or steps.get("detection", False)) and steps.get("embedding", False)
            logger.info(
                "Live analysis resume for %s: %s",
                scrub_log(stream_id),
                "complete" if complete else "partial",
            )
            return SourceAnalysisResponse(
                action="resume",
                analysis_active=complete,
                detection_enabled=detection_enabled,
                analysis_profile_id=profile_id,
                message=(
                    "Live analysis resumed; new evidence is being indexed"
                    if complete
                    else "Some analysis services could not be resumed"
                ),
                name=request.name,
                sensor_id=stream_id,
                state="active" if complete else "partial",
                steps=steps,
            )

    return router


def register_source_control_routes(app: FastAPI, config: Any) -> None:
    service_config = _resolve_service_config(config)
    app.include_router(create_source_control_router(service_config))
    logger.info("Live source analysis control routes registered")
