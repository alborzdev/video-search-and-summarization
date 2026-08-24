# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reset generated analytics for an active RTSP source without removing it."""

from datetime import UTC
from datetime import datetime
import logging
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.rtsp_ingest import _resolve_service_config
from vss_agents.api.rtsp_ingest import add_to_rtvi_cv
from vss_agents.api.rtsp_ingest import add_to_rtvi_vlm
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_generation
from vss_agents.api.rtsp_ingest import cleanup_rtvi_vlm_stream
from vss_agents.api.rtsp_ingest import cleanup_source_from_all_rtvi_cv
from vss_agents.api.rtsp_ingest import cleanup_vst_storage
from vss_agents.api.rtsp_ingest import detector_endpoint_for_profile
from vss_agents.api.rtsp_ingest import get_stream_info_by_name
from vss_agents.api.rtsp_ingest import start_embedding_generation
from vss_agents.api.rtsp_ingest import stop_managed_embedding_generation
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import is_source_detection_enabled
from vss_agents.api.source_cleanup import delete_generated_source_data
from vss_agents.api.source_cleanup import delete_lvs_graph_history
from vss_agents.utils.sanitize import scrub_log

logger = logging.getLogger(__name__)


class ResetLiveSourceRequest(BaseModel):
    """User-confirmed options for resetting one active camera."""

    name: str = Field(min_length=1, max_length=256)
    clear_recordings: bool = Field(
        default=True,
        alias="clearRecordings",
        description="Also delete retained VIOS archive media while keeping the sensor active",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ResetLiveSourceResponse(BaseModel):
    """Result of a live-source analytics reset."""

    status: Literal["success", "partial", "failure"]
    message: str
    sensor_id: str = Field(alias="sensorId")
    name: str
    deleted_documents: int = Field(alias="deletedDocuments")
    deleted_by_category: dict[str, int] = Field(alias="deletedByCategory")
    recordings_cleared: bool = Field(alias="recordingsCleared")
    analysis_resumed: bool = Field(alias="analysisResumed")
    reset_at: datetime = Field(alias="resetAt")

    model_config = ConfigDict(populate_by_name=True)


def create_source_reset_router(config: ServiceConfig) -> APIRouter:
    """Create the route that resets, then resumes, one live source."""
    router = APIRouter()

    @router.post(
        "/api/v1/rtsp-streams/{stream_id}/reset",
        response_model=ResetLiveSourceResponse,
        summary="Clear generated data for a live stream",
        description=(
            "Pauses live analytics, removes source-owned embeddings, detections, behavior, "
            "incidents, captions, and optionally retained archive media, then resumes analysis. "
            "The VST sensor remains registered."
        ),
        tags=["RTSP Streams"],
    )
    async def reset_live_source(stream_id: str, request: ResetLiveSourceRequest) -> ResetLiveSourceResponse:
        if not config.elasticsearch_url:
            return ResetLiveSourceResponse(
                status="failure",
                message="Generated-data cleanup is not configured for this deployment",
                sensor_id=stream_id,
                name=request.name,
                deleted_documents=0,
                deleted_by_category={},
                recordings_cleared=False,
                analysis_resumed=False,
                reset_at=datetime.now(UTC),
            )

        success, message, resolved_stream_id, rtsp_url = await get_stream_info_by_name(config, request.name)
        if not success or resolved_stream_id != stream_id or not rtsp_url:
            return ResetLiveSourceResponse(
                status="failure",
                message="The selected live source could not be verified",
                sensor_id=stream_id,
                name=request.name,
                deleted_documents=0,
                deleted_by_category={},
                recordings_cleared=False,
                analysis_resumed=False,
                reset_at=datetime.now(UTC),
            )

        logger.info("Resetting generated data for live source %s", scrub_log(stream_id))
        operation_results: list[bool] = []
        recordings_cleared = False

        # Stop all source-specific producers before deleting their documents so
        # the reset has a clean boundary. The registered VST sensor and RTVI
        # Embed resource remain in place for the restore phase.
        await stop_managed_embedding_generation(stream_id)
        async with httpx.AsyncClient(timeout=60.0) as client:
            pause_results = (
                await cleanup_rtvi_embed_generation(client, config, stream_id),
                await cleanup_source_from_all_rtvi_cv(client, config, stream_id, request.name, rtsp_url),
                await cleanup_rtvi_vlm_stream(client, config, stream_id),
            )
            for step_success, step_message in pause_results:
                operation_results.append(step_success)
                if not step_success:
                    logger.warning(
                        "Live reset pause step failed for %s: %s",
                        scrub_log(stream_id),
                        scrub_log(step_message),
                    )

            generated_cleanup = await delete_generated_source_data(
                config.elasticsearch_url,
                stream_id,
                request.name,
            )
            operation_results.append(generated_cleanup.success)

            graph_success, graph_message = await delete_lvs_graph_history(
                client,
                config.lvs_backend_url,
                stream_id,
            )
            operation_results.append(graph_success)
            if not graph_success:
                logger.warning(
                    "Live reset graph cleanup failed for %s: %s",
                    scrub_log(stream_id),
                    scrub_log(graph_message),
                )

            if request.clear_recordings:
                storage_success, storage_message = await cleanup_vst_storage(config, stream_id)
                recordings_cleared = storage_success
                operation_results.append(storage_success)
                if not storage_success:
                    logger.warning(
                        "Live reset storage cleanup failed for %s: %s",
                        scrub_log(stream_id),
                        scrub_log(storage_message),
                    )

            # Restore every configured analysis path even when one cleanup step
            # was partial. This keeps the camera useful and surfaces the partial
            # result instead of leaving it silently paused.
            vlm_success, vlm_message, _ = await add_to_rtvi_vlm(
                client,
                config,
                stream_id,
                request.name,
                rtsp_url,
            )
            if is_source_detection_enabled(stream_id):
                profile_id = get_source_analysis_profile(stream_id)
                detector_endpoint = detector_endpoint_for_profile(config, profile_id)
                if detector_endpoint:
                    cv_success, cv_message = await add_to_rtvi_cv(
                        client,
                        config,
                        stream_id,
                        request.name,
                        rtsp_url,
                        base_url=detector_endpoint,
                    )
                else:
                    cv_success, cv_message = False, "Selected detector worker is unavailable"
            else:
                cv_success, cv_message = True, "Skipped (semantic-only analysis)"
            embed_success, embed_message = await start_embedding_generation(None, config, stream_id)
            restore_results = (vlm_success, cv_success, embed_success)
            operation_results.extend(restore_results)
            for step_success, step_message in (
                (vlm_success, vlm_message),
                (cv_success, cv_message),
                (embed_success, embed_message),
            ):
                if not step_success:
                    logger.error(
                        "Live reset restore step failed for %s: %s",
                        scrub_log(stream_id),
                        scrub_log(step_message),
                    )

        analysis_resumed = all(restore_results)
        all_success = bool(operation_results) and all(operation_results)
        any_success = any(operation_results)
        status: Literal["success", "partial", "failure"]
        if all_success:
            status = "success"
            message = f"Generated data for '{request.name}' was cleared and live analysis resumed"
        elif any_success:
            status = "partial"
            message = f"Generated data for '{request.name}' was partially reset; review service health"
        else:
            status = "failure"
            message = f"Generated data for '{request.name}' could not be reset"

        return ResetLiveSourceResponse(
            status=status,
            message=message,
            sensor_id=stream_id,
            name=request.name,
            deleted_documents=generated_cleanup.total_deleted,
            deleted_by_category=generated_cleanup.deleted_documents,
            recordings_cleared=recordings_cleared,
            analysis_resumed=analysis_resumed,
            reset_at=datetime.now(UTC),
        )

    return router


def register_source_reset_routes(app: FastAPI, config: Any) -> None:
    """Register live-source reset using the shared streaming configuration."""
    service_config = _resolve_service_config(config)
    app.include_router(create_source_reset_router(service_config))
    logger.info(
        "Live source reset route registered (es=%s, clear-storage-policy=user-confirmed)",
        "on" if service_config.elasticsearch_url else "off",
    )
