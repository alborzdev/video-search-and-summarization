# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Standalone CTAILabs analysis-profile catalog and intent router.

The profile is the operator-facing contract for one source.  Semantic search
and Cosmos reasoning are shared capabilities; a detector profile optionally
adds one concrete DeepStream worker, its object vocabulary, and the monitoring
rules that vocabulary can support.  Keeping this manifest in VSS avoids a
runtime dependency on the separate Vision Playground project.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

logger = logging.getLogger(__name__)

SEMANTIC_PROFILE_ID = "semantic-search"
WAREHOUSE_PROFILE_ID = "warehouse-safety"
TRAFFIC_PROFILE_ID = "traffic-monitoring"
DEFAULT_DETECTION_PROFILE_ID = WAREHOUSE_PROFILE_ID


@dataclass(frozen=True)
class AnalysisProfileDefinition:
    id: str
    name: str
    short_name: str
    description: str
    model_id: str | None
    model_label: str
    scene_types: tuple[str, ...]
    object_types: tuple[str, ...]
    rule_kinds: tuple[str, ...]
    resource_tier: Literal["low", "medium", "high"]
    max_sources: int

    @property
    def detection_enabled(self) -> bool:
        return self.model_id is not None


ANALYSIS_PROFILES: tuple[AnalysisProfileDefinition, ...] = (
    AnalysisProfileDefinition(
        id=SEMANTIC_PROFILE_ID,
        name="Semantic search + Vision Analyst",
        short_name="Search only",
        description=(
            "Index the source with Cosmos Embed and keep visual question answering available "
            "without running an object detector."
        ),
        model_id=None,
        model_label="Cosmos Embed + Cosmos Reason",
        scene_types=("general", "unstructured", "unknown"),
        object_types=(),
        rule_kinds=("semantic",),
        resource_tier="low",
        max_sources=8,
    ),
    AnalysisProfileDefinition(
        id=WAREHOUSE_PROFILE_ID,
        name="Warehouse safety",
        short_name="Warehouse",
        description=(
            "Detect and track workers, mobile robots, forklifts, transporters, and pallets "
            "for industrial safety and material-flow monitoring."
        ),
        model_id="nvidia/rtdetr-warehouse-v1.0.2",
        model_label="NVIDIA RT-DETR Warehouse",
        scene_types=("warehouse", "factory", "loading dock", "industrial"),
        object_types=(
            "Person",
            "Agility Digit Humanoid",
            "Fourier GR1 T2 Humanoid",
            "Nova Carter",
            "Transporter",
            "Forklift",
            "Pallet",
        ),
        # Only conditions implemented end-to-end by this VSS deployment are
        # advertised. More templates can be added without changing the UI.
        rule_kinds=("area-entry", "proximity"),
        resource_tier="medium",
        max_sources=8,
    ),
    AnalysisProfileDefinition(
        id=TRAFFIC_PROFILE_ID,
        name="Traffic and roadway",
        short_name="Traffic",
        description=(
            "Detect and track people, bicycles, cars, and road signs for intersections, "
            "crossings, parking areas, and roadway activity."
        ),
        model_id="nvidia/rtdetr-its",
        model_label="NVIDIA RT-DETR Intelligent Transportation",
        scene_types=("traffic", "road", "intersection", "crosswalk", "parking", "smart city"),
        object_types=("Bicycle", "Car", "Person", "Road sign"),
        rule_kinds=("area-entry", "proximity"),
        resource_tier="medium",
        # The checked-in Thor engine is batch one.  The UI must communicate
        # this instead of silently overcommitting the appliance.
        max_sources=1,
    ),
)

PROFILE_BY_ID = {profile.id: profile for profile in ANALYSIS_PROFILES}


def require_analysis_profile(profile_id: str) -> AnalysisProfileDefinition:
    try:
        return PROFILE_BY_ID[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown analysis profile: {profile_id}") from exc


def analysis_profile_endpoint(warehouse_rtvi_cv_url: str, profile_id: str) -> str:
    """Resolve the private DeepStream worker for a detector profile."""
    profile = require_analysis_profile(profile_id)
    if not profile.detection_enabled:
        return ""
    if profile_id == WAREHOUSE_PROFILE_ID:
        return warehouse_rtvi_cv_url.rstrip("/")
    if profile_id == TRAFFIC_PROFILE_ID:
        return os.getenv("VSS_TRAFFIC_RTVI_CV_URL", "").rstrip("/")
    return ""


class AnalysisProfileResponse(BaseModel):
    id: str
    name: str
    short_name: str = Field(alias="shortName")
    description: str
    detection_enabled: bool = Field(alias="detectionEnabled")
    model_id: str | None = Field(alias="modelId")
    model_label: str = Field(alias="modelLabel")
    object_types: list[str] = Field(alias="objectTypes")
    ready: bool
    ready_detail: str = Field(alias="readyDetail")
    resource_tier: Literal["low", "medium", "high"] = Field(alias="resourceTier")
    max_sources: int = Field(alias="maxSources")
    rule_kinds: list[str] = Field(alias="ruleKinds")
    scene_types: list[str] = Field(alias="sceneTypes")

    model_config = ConfigDict(populate_by_name=True)


class AnalysisProfilesResponse(BaseModel):
    profiles: list[AnalysisProfileResponse]


class AnalysisProfileRecommendationRequest(BaseModel):
    source_kind: Literal["live", "recorded"] = Field(alias="sourceKind")
    source_name: str = Field(alias="sourceName", min_length=1, max_length=256)
    intent: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AnalysisProfileRecommendationResponse(BaseModel):
    profile_id: str = Field(alias="profileId")
    confidence: float = Field(ge=0, le=1)
    reason: str
    alternatives: list[str]
    planner: Literal["nemotron", "local-fallback"]

    model_config = ConfigDict(populate_by_name=True)


class SourceAnalysisProfileResponse(BaseModel):
    source_id: str = Field(alias="sourceId")
    profile_id: str = Field(alias="profileId")
    profile: AnalysisProfileResponse

    model_config = ConfigDict(populate_by_name=True)


def _local_profile_recommendation(source_name: str, intent: str) -> tuple[str, float, str]:
    text = f"{source_name} {intent}".casefold()
    warehouse_terms = {
        "warehouse",
        "forklift",
        "pallet",
        "loading dock",
        "factory",
        "worker safety",
        "restricted zone",
        "robot",
        "transporter",
    }
    traffic_terms = {
        "traffic",
        "road",
        "intersection",
        "crosswalk",
        "vehicle",
        "car",
        "bicycle",
        "parking",
        "jaywalk",
        "pedestrian crossing",
    }
    warehouse_score = sum(term in text for term in warehouse_terms)
    traffic_score = sum(term in text for term in traffic_terms)
    if warehouse_score > traffic_score:
        return (
            WAREHOUSE_PROFILE_ID,
            min(0.97, 0.72 + warehouse_score * 0.06),
            ("The source description and monitoring intent indicate an industrial or material-handling scene."),
        )
    if traffic_score > warehouse_score:
        return (
            TRAFFIC_PROFILE_ID,
            min(0.97, 0.72 + traffic_score * 0.06),
            ("The source description and monitoring intent indicate a roadway or vehicle scene."),
        )
    return (
        SEMANTIC_PROFILE_ID,
        0.62,
        (
            "No detector-specific scene was stated, so semantic indexing is the safest resource-efficient starting point."
        ),
    )


async def _nemotron_profile_recommendation(
    source_name: str,
    intent: str,
) -> tuple[str, float, str] | None:
    if os.getenv("VSS_ANALYSIS_PLANNER_ENABLED", "true").casefold() not in {"1", "true", "yes", "on"}:
        return None
    base_url = os.getenv("VSS_ANALYSIS_PLANNER_BASE_URL", "").rstrip("/")
    if not base_url:
        return None
    model = os.getenv("VSS_ANALYSIS_PLANNER_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8")
    tools = [
        {
            "type": "function",
            "function": {
                "name": profile.id.replace("-", "_"),
                "description": profile.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string"},
                    },
                    "required": ["confidence", "reason"],
                },
            },
        }
        for profile in ANALYSIS_PROFILES
    ]
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Choose exactly one supported source analysis profile. Prefer a detector only when its object "
                    "vocabulary matches the stated scene or goal. Use semantic_search for unknown or broad scenes. "
                    "Never invent a profile or model."
                ),
            },
            {"role": "user", "content": f"Source: {source_name}\nMonitoring goal: {intent or 'not specified'}"},
        ],
        "tools": tools,
        "tool_choice": "required",
        "temperature": 0,
        "max_tokens": 128,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload)
            response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        call = message["tool_calls"][0]["function"]
        profile_id = str(call["name"]).replace("_", "-")
        require_analysis_profile(profile_id)
        arguments_value = call.get("arguments", {})
        arguments = json.loads(arguments_value) if isinstance(arguments_value, str) else arguments_value
        confidence = max(0.0, min(1.0, float(arguments.get("confidence", 0.75))))
        reason = str(arguments.get("reason") or "Nemotron matched the requested scene and monitoring goal.").strip()
        return profile_id, confidence, reason[:500]
    except Exception:
        logger.warning("Nemotron analysis-profile planning failed; using the deterministic fallback", exc_info=True)
        return None


async def _profile_readiness(
    client: httpx.AsyncClient,
    warehouse_rtvi_cv_url: str,
    profile: AnalysisProfileDefinition,
) -> tuple[bool, str]:
    endpoint = analysis_profile_endpoint(warehouse_rtvi_cv_url, profile.id)
    if not endpoint:
        return (True, "Shared semantic services") if not profile.detection_enabled else (False, "No worker configured")
    try:
        response = await client.get(f"{endpoint}/api/v1/health/get-dsready-state")
        response.raise_for_status()
        return True, "Ready on NVIDIA Thor"
    except Exception:
        return False, "Detector worker is offline"


def create_analysis_profiles_router(warehouse_rtvi_cv_url: str) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/analysis-profiles",
        response_model=AnalysisProfilesResponse,
        tags=["Analysis Profiles"],
        summary="List VSS-owned source analysis profiles and real runtime readiness",
    )
    async def list_analysis_profiles() -> AnalysisProfilesResponse:
        timeout = httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=1.5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            readiness = [
                await _profile_readiness(client, warehouse_rtvi_cv_url, profile) for profile in ANALYSIS_PROFILES
            ]
        return AnalysisProfilesResponse(
            profiles=[
                AnalysisProfileResponse(
                    id=profile.id,
                    name=profile.name,
                    short_name=profile.short_name,
                    description=profile.description,
                    detection_enabled=profile.detection_enabled,
                    model_id=profile.model_id,
                    model_label=profile.model_label,
                    object_types=list(profile.object_types),
                    ready=ready,
                    ready_detail=detail,
                    resource_tier=profile.resource_tier,
                    max_sources=profile.max_sources,
                    rule_kinds=list(profile.rule_kinds),
                    scene_types=list(profile.scene_types),
                )
                for profile, (ready, detail) in zip(ANALYSIS_PROFILES, readiness, strict=True)
            ]
        )

    @router.get(
        "/api/v1/analysis-profiles/sources/{source_id}",
        response_model=SourceAnalysisProfileResponse,
        tags=["Analysis Profiles"],
        summary="Read the durable analysis profile selected for one source",
    )
    async def get_source_profile(source_id: str) -> SourceAnalysisProfileResponse:
        # Imported lazily because durable state validates against this module's
        # manifest. This keeps the dependency one-way at module import time.
        from vss_agents.api.source_analysis_state import get_source_analysis_profile

        profile = require_analysis_profile(get_source_analysis_profile(source_id))
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            ready, detail = await _profile_readiness(client, warehouse_rtvi_cv_url, profile)
        return SourceAnalysisProfileResponse(
            source_id=source_id,
            profile_id=profile.id,
            profile=AnalysisProfileResponse(
                id=profile.id,
                name=profile.name,
                short_name=profile.short_name,
                description=profile.description,
                detection_enabled=profile.detection_enabled,
                model_id=profile.model_id,
                model_label=profile.model_label,
                object_types=list(profile.object_types),
                ready=ready,
                ready_detail=detail,
                resource_tier=profile.resource_tier,
                max_sources=profile.max_sources,
                rule_kinds=list(profile.rule_kinds),
                scene_types=list(profile.scene_types),
            ),
        )

    @router.post(
        "/api/v1/analysis-profiles/recommend",
        response_model=AnalysisProfileRecommendationResponse,
        tags=["Analysis Profiles"],
        summary="Recommend a validated source analysis profile with local Nemotron",
    )
    async def recommend_analysis_profile(
        request: AnalysisProfileRecommendationRequest,
    ) -> AnalysisProfileRecommendationResponse:
        recommendation = await _nemotron_profile_recommendation(request.source_name, request.intent)
        planner: Literal["nemotron", "local-fallback"] = "nemotron"
        if recommendation is None:
            planner = "local-fallback"
            recommendation = _local_profile_recommendation(request.source_name, request.intent)
        profile_id, confidence, reason = recommendation
        alternatives = [profile.id for profile in ANALYSIS_PROFILES if profile.id != profile_id]
        return AnalysisProfileRecommendationResponse(
            profile_id=profile_id,
            confidence=confidence,
            reason=reason,
            alternatives=alternatives,
            planner=planner,
        )

    return router


def register_analysis_profile_routes(app: FastAPI, config: Any) -> None:
    streaming_config = getattr(config.general.front_end, "streaming_ingest", None)
    warehouse_rtvi_cv_url = getattr(streaming_config, "rtvi_cv_base_url", "") if streaming_config is not None else ""
    app.include_router(create_analysis_profiles_router(warehouse_rtvi_cv_url or ""))
    logger.info("Standalone source analysis-profile routes registered")
