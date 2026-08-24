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

"""
Custom FastAPI front-end worker that extends NAT's default worker
to support additional streaming endpoints and a lightweight health check.
"""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
import logging
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.workflow_builder import WorkflowBuilder
from nat.data_models.config import Config
from nat.front_ends.fastapi.fastapi_front_end_plugin_worker import FastApiFrontEndPluginWorker
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from vss_agents.api.analysis_profiles import register_analysis_profile_routes
from vss_agents.api.evidence_analysis import register_evidence_analysis_routes
from vss_agents.api.rtsp_delete import register_rtsp_delete_routes
from vss_agents.api.rtsp_ingest import register_rtsp_ingest_routes
from vss_agents.api.source_control import register_source_control_routes
from vss_agents.api.source_reset import register_source_reset_routes
from vss_agents.api.thor_workload_admission import ThorVisualWorkloadAdmission
from vss_agents.api.thor_workload_admission import ThorWorkloadAdmissionError
from vss_agents.api.video_delete import register_video_delete_routes
from vss_agents.api.video_ingest import register_video_upload
from vss_agents.api.video_ingest import register_video_upload_complete
from vss_agents.api.video_search_ingest import register_video_search_ingest_routes

logger = logging.getLogger(__name__)


# This is deliberately the advertised LVS semantic surface, rather than every
# function configured in the process.  The endpoint below resolves each name
# through the live WorkflowBuilder and returns no configuration values, URLs,
# credentials, prompts, or tool schemas.
LVS_RUNTIME_TOOL_NAMES = (
    "lvs_video_understanding",
    "lvs_config_media",
    "lvs_stream_understanding",
    "lvs_caption_retrieval",
    "video_report_gen",
)


class VisionInspectionRequest(BaseModel):
    """A deterministic, single-source visual inspection request from the UI."""

    source_kind: Literal["live", "replay"]
    sensor_id: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=1000)
    asked_at: datetime
    current_time_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, gt=0)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_playback(self):
        if self.source_kind == "live" and (self.current_time_seconds is not None or self.duration_seconds is not None):
            raise ValueError("Live inspection requests cannot include replay offsets")
        return self


def _replay_inspection_range(request: VisionInspectionRequest) -> tuple[float | None, float | None]:
    """Choose a fast, useful replay window without pretending it covers unseen footage."""

    query = request.query.lower()
    whole_replay = any(
        phrase in query
        for phrase in ("entire replay", "entire video", "whole replay", "whole video", "summarize this replay")
    )
    if whole_replay:
        return None, None

    duration = request.duration_seconds
    current = request.current_time_seconds or 0.0
    # At the initial playhead, inspect the opening rather than constructing an
    # invalid negative interval. Else center the observation around the frame
    # the presenter is looking at.
    start = max(0.0, current - 6.0)
    end = current + 18.0
    if duration is not None:
        end = min(duration, end)
        if end - start < 2.0:
            start = max(0.0, end - 24.0)
    return start, end


async def inspect_vision_source(builder: WorkflowBuilder, request: VisionInspectionRequest) -> dict:
    """Execute the visual evidence tool directly, bypassing agent planning."""

    if request.source_kind == "live":
        tool_name = "video_understanding_iso"
        asked_at = request.asked_at.astimezone(UTC)
        # Allow a small ingest/storage delay at the live edge.
        start_timestamp: str | float | None = (asked_at - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        end_timestamp: str | float | None = (asked_at - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        observed_range = None
    else:
        tool_name = "video_understanding"
        start_timestamp, end_timestamp = _replay_inspection_range(request)
        observed_range = (
            {"start_seconds": start_timestamp, "end_seconds": end_timestamp}
            if start_timestamp is not None and end_timestamp is not None
            else None
        )

    tool = await builder.get_tool(tool_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    if tool is None:
        raise RuntimeError(f"Visual evidence tool '{tool_name}' is unavailable")

    answer = await tool.ainvoke(
        input={
            "sensor_id": request.sensor_id,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "user_prompt": (
                "Answer the visitor's question only from visible evidence in this video. "
                "Be concise, name important objects or activity, and do not infer facts that are not visible. "
                f"Question: {request.query.strip()}"
            ),
            "vlm_reasoning": False,
        }
    )
    answer_text = str(answer).strip()
    if not answer_text:
        raise RuntimeError("The visual evidence tool returned no observation")
    return {
        "answer": answer_text,
        "evidence_tool": tool_name,
        "observed_range": observed_range,
    }


async def discover_lvs_runtime_tools(builder: WorkflowBuilder) -> dict:
    """Resolve the five advertised LVS tools from the running NAT builder.

    A source-config grep cannot prove that the deployed builder successfully
    constructed a tool.  This small, read-only probe performs the same
    ``get_tool`` resolution used by the agents and exposes only exact requested
    names and an aggregate readiness bit.
    """

    available: list[str] = []
    missing: list[str] = []
    for name in LVS_RUNTIME_TOOL_NAMES:
        try:
            tool = await builder.get_tool(
                name,
                wrapper_type=LLMFrameworkEnum.LANGCHAIN,
            )
        except Exception:
            logger.warning("LVS runtime tool resolution failed for %s", name, exc_info=True)
            missing.append(name)
            continue
        if tool is None:
            missing.append(name)
        else:
            available.append(name)
    return {
        "schema_version": 1,
        "catalog": "lvs-advertised-runtime-tools",
        "expected": list(LVS_RUNTIME_TOOL_NAMES),
        "available": available,
        "missing": missing,
        "ready": not missing,
    }


class CustomFastApiFrontEndWorker(FastApiFrontEndPluginWorker):
    """
    Custom FastAPI front-end worker that extends NAT's default worker.
    """

    def __init__(self, config: Config):
        super().__init__(config)
        logger.info("Initialized CustomFastApiFrontEndWorker")

    async def add_routes(self, app: FastAPI, builder: WorkflowBuilder) -> None:
        """
        Override add_routes to add custom endpoints.

        Args:
            app: FastAPI application instance
            builder: WorkflowBuilder instance
        """
        # Add standard NAT routes
        await super().add_routes(app, builder)

        # Remove NAT's default health endpoint and add our custom one
        # We need to override it to return the expected format for integration tests
        app.routes[:] = [route for route in app.routes if getattr(route, "path", None) != "/health"]

        # Add lightweight health endpoint (no telemetry)
        @app.get("/health", include_in_schema=False)
        async def health_check() -> dict:
            return {"value": {"isAlive": True}}

        logger.info("Registered custom /health endpoint (replaced NAT default)")

        @app.get("/api/v1/runtime-tools/lvs", include_in_schema=False)
        async def lvs_runtime_tools():
            result = await discover_lvs_runtime_tools(builder)
            return JSONResponse(status_code=200 if result["ready"] else 503, content=result)

        logger.info("Registered read-only /api/v1/runtime-tools/lvs discovery endpoint")

        visual_admission = ThorVisualWorkloadAdmission()

        @app.post("/api/v1/vision-inspection", include_in_schema=False)
        async def vision_inspection(request: VisionInspectionRequest):
            """Inspect one selected source through a real visual tool call."""

            try:
                async with visual_admission.reserve("current_visual_question"):
                    result = await inspect_vision_source(builder, request)
            except ThorWorkloadAdmissionError as exc:
                return JSONResponse(status_code=exc.status_code, content=exc.response_body())
            except Exception as exc:
                logger.warning("Direct visual inspection failed", exc_info=True)
                return JSONResponse(
                    status_code=502,
                    content={"error": f"Visual inspection could not be completed: {exc}"},
                )
            return JSONResponse(status_code=200, content=result)

        logger.info("Registered deterministic /api/v1/vision-inspection endpoint")

        register_evidence_analysis_routes(app, builder, visual_admission)
        logger.info("Registered grounded /api/v1/evidence-analysis endpoint")

        # Register custom streaming routes per capability flags in streaming_ingest
        self._register_streaming_routes(app)

    def _register_streaming_routes(self, app: FastAPI) -> None:
        """Register the custom video / RTSP / delete routes.

        Every route is registered unconditionally on every profile — each
        handler self-skips downstream calls (RTVI, storage delete, etc.)
        when its backing service isn't configured, so the same shape works
        on search/lvs/alerts/base:

        - ``POST /api/v1/videos`` — returns the VST upload URL for a new
          chat-tab video upload (UI handshake step 1).
        - ``POST /api/v1/videos/{sensor_id}/complete`` — universal upload
          completion hook (self-skips RTVI-CV / embedding when unset).
        - ``PUT /api/v1/videos-for-search/{filename}`` — *deprecated* compat
          shim for the ``metromind/ci-vss-oss`` search-profile test fixture.
          Registered with ``deprecated=True`` in OpenAPI; will be dropped
          once the fixture migrates to the new three-step flow.
        - ``POST /api/v1/rtsp-streams/add`` and ``DELETE /.../delete/{name}``.
        - ``POST /api/v1/rtsp-streams/{stream_id}/reset`` — clear generated
          live analytics and optionally archive media without removing the source.
        - ``DELETE /api/v1/videos/{video_id}``.

        Raises:
            ValueError: when ``streaming_ingest`` is missing from the config.
                Every profile is expected to declare it explicitly.
        """
        front_end_cfg = getattr(getattr(self.config, "general", None), "front_end", None)
        streaming_config = getattr(front_end_cfg, "streaming_ingest", None) if front_end_cfg else None

        if streaming_config is None:
            raise ValueError(
                "general.front_end.streaming_ingest must be set in the profile YAML "
                "to register custom video / RTSP routes"
            )

        # `stream_mode` and the old `enable_*` capability flags are no longer
        # supported. Routes register unconditionally now.
        legacy_extra = getattr(streaming_config, "model_extra", None)
        if isinstance(legacy_extra, dict) and "stream_mode" in legacy_extra:
            raise ValueError(
                "general.front_end.streaming_ingest.stream_mode is no longer supported. "
                "Drop it from the YAML; the upload-complete + RTSP + delete routes "
                "register unconditionally on every profile."
            )

        logger.info("Registering streaming_ingest routes")

        register_video_upload(app, self.config)
        register_video_upload_complete(app, self.config)
        register_video_search_ingest_routes(app, self.config)
        register_rtsp_ingest_routes(app, self.config)
        register_analysis_profile_routes(app, self.config)
        register_rtsp_delete_routes(app, self.config)
        register_source_reset_routes(app, self.config)
        register_source_control_routes(app, self.config)
        register_video_delete_routes(app, self.config)
