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
RTSP stream deletion: ``DELETE /api/v1/rtsp-streams/delete/{name}``.

Best-effort teardown — each step logs success or failure but doesn't abort,
and the response status (``success`` / ``partial`` / ``failure``) reflects the
aggregated outcome. Reuses ``ServiceConfig``, ``get_stream_info_by_name``, and
the ``cleanup_*`` helpers from :mod:`vss_agents.api.rtsp_ingest` so both ends
of the lifecycle share the same VST / RTVI logic.
"""

import logging
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.rtsp_ingest import _resolve_service_config
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_generation
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_stream
from vss_agents.api.rtsp_ingest import cleanup_rtvi_vlm_stream
from vss_agents.api.rtsp_ingest import cleanup_source_from_all_rtvi_cv
from vss_agents.api.rtsp_ingest import cleanup_vst_sensor
from vss_agents.api.rtsp_ingest import cleanup_vst_storage
from vss_agents.api.rtsp_ingest import clear_live_analysis_runtime
from vss_agents.api.rtsp_ingest import configured_detector_endpoints
from vss_agents.api.rtsp_ingest import get_stream_info_by_name
from vss_agents.api.rtsp_ingest import stop_managed_embedding_generation
from vss_agents.api.source_analysis_state import forget_source_analysis_state
from vss_agents.api.source_analysis_state import set_source_deleting
from vss_agents.api.source_cleanup import delete_generated_source_data
from vss_agents.api.source_cleanup import delete_lvs_graph_history
from vss_agents.utils.sanitize import scrub_log

logger = logging.getLogger(__name__)


class DeleteStreamResponse(BaseModel):
    """Response model for delete stream operation."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["success", "partial", "failure"] = Field(..., description="'success', 'partial', or 'failure'")
    message: str = Field(..., description="Human-readable status message")
    name: str = Field(..., description="The sensor name that was deleted")
    sensor_id: str | None = Field(
        None,
        alias="sensorId",
        description="Stable VST sensor identity resolved before cleanup",
    )
    generated_data_deleted: int = Field(
        0,
        alias="generatedDataDeleted",
        description="Number of source-owned generated documents removed from Elasticsearch",
    )

    @model_validator(mode="after")
    def require_resolved_identity(self) -> "DeleteStreamResponse":
        """Success or partial cleanup must remain bound to the resolved sensor."""
        if self.status in {"success", "partial"} and not self.sensor_id:
            raise ValueError("successful or partial RTSP delete response requires sensorId")
        return self


async def _delete_resolved_stream(
    config: ServiceConfig,
    name: str,
    stream_id: str,
    rtsp_url: str | None,
) -> DeleteStreamResponse:
    """Tear down every resource owned by an already-resolved live source."""
    results: list[bool] = []
    generated_data_deleted = 0

    # RTVI cleanup runs only when at least one RTVI URL is configured.
    # The individual cleanup helpers self-skip when their URL is empty,
    # but we avoid opening an httpx client when nothing's configured.
    if (
        config.rtvi_embed_url
        or configured_detector_endpoints(config)
        or config.rtvi_vlm_url
        or config.lvs_backend_url
    ):
        # Prevent the live supervisor from reconnecting while this
        # explicit teardown removes the backing RTVI resource.
        await stop_managed_embedding_generation(stream_id)
        async with httpx.AsyncClient(timeout=60.0) as client:
            success, msg = await cleanup_rtvi_embed_generation(client, config, stream_id)
            results.append(success)
            logger.info(f"Stop embedding generation: {'OK' if success else msg}")

            success, msg = await cleanup_rtvi_embed_stream(client, config, stream_id)
            results.append(success)
            logger.info(f"Delete from RTVI-embed: {'OK' if success else msg}")

            success, msg = await cleanup_source_from_all_rtvi_cv(
                client,
                config,
                stream_id,
                name=name,
                sensor_url=rtsp_url or "",
            )
            results.append(success)
            logger.info(f"Delete from RTVI-CV: {'OK' if success else msg}")

            success, msg = await cleanup_rtvi_vlm_stream(client, config, stream_id)
            results.append(success)
            logger.info(f"Delete from RTVI-VLM: {'OK' if success else msg}")

            success, msg = await delete_lvs_graph_history(client, config.lvs_backend_url, stream_id)
            results.append(success)
            logger.info(f"Delete graph history: {'OK' if success else msg}")

    # Delete generated records only after stopping their producers. Exact
    # source ID/name terms are used across every date partition so old
    # embeddings and detector frames cannot survive source removal.
    if config.elasticsearch_url:
        generated_cleanup = await delete_generated_source_data(
            config.elasticsearch_url,
            stream_id,
            name,
        )
        generated_data_deleted = generated_cleanup.total_deleted
        results.append(generated_cleanup.success)
        if generated_cleanup.failures:
            logger.error(
                "Generated-data cleanup was incomplete for %s: %s",
                scrub_log(stream_id),
                sorted(generated_cleanup.failures),
            )

    success, msg = await cleanup_vst_sensor(config, stream_id)
    results.append(success)
    logger.info(f"Delete VST sensor: {'OK' if success else msg}")
    if success:
        clear_live_analysis_runtime(stream_id)
        forget_source_analysis_state(stream_id)

    if config.delete_vst_storage_on_stream_remove:
        success, msg = await cleanup_vst_storage(config, stream_id)
        results.append(success)
        logger.info(f"Delete VST storage: {'OK' if success else msg}")

    all_success = all(results)
    any_success = any(results)

    status: Literal["success", "partial", "failure"]
    if all_success:
        status = "success"
        message = f"Stream '{name}' deleted successfully"
    elif any_success:
        status = "partial"
        message = f"Stream '{name}' partially deleted - some services failed"
    else:
        status = "failure"
        message = f"Failed to delete stream '{name}'"

    logger.info("Delete stream '%s' completed with status: %s", scrub_log(name), status)

    return DeleteStreamResponse(
        status=status,
        message=message,
        name=name,
        sensor_id=stream_id,
        generated_data_deleted=generated_data_deleted,
    )


def create_rtsp_delete_router(config: ServiceConfig) -> APIRouter:
    """Create the router that handles ``DELETE /api/v1/rtsp-streams/delete/{name}``."""

    router = APIRouter()

    @router.delete(
        "/api/v1/rtsp-streams/delete/{name}",
        response_model=DeleteStreamResponse,
        response_model_exclude_none=True,
        summary="Delete an RTSP stream by name",
        description=(
            "Removes the stream from VST. RTVI cleanup steps run when their URLs are "
            "configured. VST storage is also removed when "
            "``delete_vst_storage_on_stream_remove`` is True (default)."
        ),
        tags=["RTSP Streams"],
    )
    async def delete_stream(name: str) -> DeleteStreamResponse:
        """
        Delete an RTSP stream from services by camera/sensor name.

        Best-effort: continues even if individual steps fail.

        1. Find stream_id and RTSP URL from VST by name
        2. Stop embedding generation (skipped when ``rtvi_embed_base_url`` empty)
        3. Delete from RTVI-embed (skipped when ``rtvi_embed_base_url`` empty)
        4. Delete from RTVI-CV (skipped when ``rtvi_cv_base_url`` empty)
        5. Delete sensor from VST
        6. Delete storage from VST (only when ``delete_vst_storage_on_stream_remove`` True)
        """
        logger.info("Deleting stream by name '%s'", scrub_log(name))

        success, msg, stream_id, rtsp_url = await get_stream_info_by_name(config, name)
        if not success:
            logger.error("Failed to find stream '%s': %s", scrub_log(name), scrub_log(msg))
            return DeleteStreamResponse(
                status="failure",
                message=f"Failed to find stream with name '{name}': {msg}",
                name=name,
            )

        logger.info("Found stream_id '%s' for name '%s'", scrub_log(stream_id), scrub_log(name))
        if stream_id is None:
            return DeleteStreamResponse(
                status="failure",
                message=f"Found stream '{name}' but stream ID is missing",
                name=name,
            )

        # Keep the short-lived tombstone set until every teardown step has
        # returned.  The periodic reconciler otherwise sees the stale VST
        # snapshot and can recreate an RTVI resource during this request.
        set_source_deleting(stream_id, True)
        try:
            return await _delete_resolved_stream(config, name, stream_id, rtsp_url)
        finally:
            set_source_deleting(stream_id, False)

    return router


def register_rtsp_delete_routes(app: FastAPI, config: Any) -> None:
    """Register ``DELETE /api/v1/rtsp-streams/delete/{name}``.

    Reads the same ``streaming_ingest`` config as ``register_rtsp_ingest_routes``;
    only ``vst_internal_url`` is required.
    """
    try:
        service_config = _resolve_service_config(config)
        app.include_router(create_rtsp_delete_router(service_config))
        logger.info(
            "RTSP delete route registered "
            f"(rtvi_embed={'on' if service_config.rtvi_embed_url else 'off'}, "
            f"rtvi_cv={'on' if service_config.rtvi_cv_url else 'off'}, "
            f"delete_vst_storage_on_stream_remove={service_config.delete_vst_storage_on_stream_remove})"
        )
    except Exception as e:
        logger.error(f"Failed to register RTSP delete route: {e}", exc_info=True)
        raise
