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
Delete video API endpoint.

Provides a DELETE endpoint for removing uploaded videos from the system.
Per-step behavior is driven by what's configured:
  - VST sensor + storage cleanup: always runs.
  - RTVI-CV cleanup: runs when ``rtvi_cv_base_url`` is set.
  - Elasticsearch cleanup (embed, behavior, raw indexes): runs when an
    ``EsCleanupConfig`` is provided.
"""

import logging
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch import NotFoundError
from fastapi import APIRouter
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.api.analysis_profiles import ANALYSIS_PROFILES
from vss_agents.api.analysis_profiles import analysis_profile_endpoint
from vss_agents.api.source_analysis_state import forget_source_analysis_state
from vss_agents.api.source_cleanup import delete_generated_source_data
from vss_agents.api.source_cleanup import registered_rtvi_cv_stream_ids
from vss_agents.tools.vst.utils import VSTError
from vss_agents.tools.vst.utils import delete_vst_sensor
from vss_agents.tools.vst.utils import delete_vst_storage
from vss_agents.tools.vst.utils import get_sensor_id_from_stream_id
from vss_agents.utils.sanitize import scrub_log
from vss_agents.utils.time_measure import TimeMeasure

logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================


class DeleteVideoResponse(BaseModel):
    """Response model for delete video operation."""

    model_config = ConfigDict(populate_by_name=True)

    status: str = Field(..., description="'success', 'partial', or 'failure'")
    message: str = Field(..., description="Human-readable status message")
    video_id: str = Field(..., description="The video/sensor ID that was deleted")
    generated_data_deleted: int = Field(
        0,
        alias="generatedDataDeleted",
        description="Number of source-owned generated documents removed from Elasticsearch",
    )


class EsCleanupConfig(BaseModel):
    """Elasticsearch configuration for video-delete cleanup.

    Bundles the ES URL with its index names so callers can't pass index
    names without a URL (or vice versa). Pass ``None`` to ``create_video_delete_router``
    when ES cleanup should be skipped entirely.
    """

    url: str = Field(..., description="Elasticsearch endpoint URL")
    embed_index: str = Field(
        default="mdx-embed-filtered-2025-01-01",
        description="ES index for video embeddings",
    )
    behavior_index: str = Field(
        default="mdx-behavior-2025-01-01",
        description="ES index for object behavior data",
    )
    raw_index: str = Field(
        default="mdx-raw-2025-01-01",
        description="ES index for raw detection data",
    )


# ============================================================================
# RTVI-CV Cleanup Helper
# ============================================================================


async def _remove_from_rtvi_cv(
    client: httpx.AsyncClient, rtvi_cv_url: str, sensor_id: str, sensor_name: str
) -> tuple[bool, str]:
    """
    Remove a video stream from RTVI-CV.

    Args:
        client: HTTP client
        rtvi_cv_url: Base RTVI-CV URL (e.g., http://localhost:9000)
        sensor_id: The sensor UUID
        sensor_name: The sensor/video name

    Returns:
        (success, message) tuple
    """
    if not rtvi_cv_url:
        logger.info("RTVI-CV not configured, skipping")
        return True, "Skipped (not configured)"

    try:
        registered_ids = await registered_rtvi_cv_stream_ids(client, rtvi_cv_url)
    except Exception:
        # Older RTVI-CV deployments may not expose inventory. Keep their
        # existing removal behavior, while current workers get the stronger
        # source-isolation guarantee below.
        logger.warning(
            "Could not read RTVI-CV inventory at %s before removing %s; falling back to remove",
            scrub_log(rtvi_cv_url),
            scrub_log(sensor_id),
            exc_info=True,
        )
    else:
        if sensor_id not in registered_ids:
            logger.info(
                "RTVI-CV stream %s is already absent from %s; skipping unsafe remove",
                scrub_log(sensor_id),
                scrub_log(rtvi_cv_url),
            )
            return True, "Already absent"

    url = f"{rtvi_cv_url}/api/v1/stream/remove"
    payload = {
        "key": "sensor",
        "value": {
            "camera_id": sensor_id,
            "camera_name": sensor_name,
            "camera_url": "",
            "change": "camera_remove",
            "metadata": {"resolution": "1920x1080", "codec": "h264", "framerate": 30},
        },
        "headers": {"source": "vst"},
    }

    logger.info(f"Removing from RTVI-CV: POST {url}")

    try:
        # Match the add path's SDR affinity contract. Without this header an
        # SDR-fronted deployment may route removal to a worker that does not
        # own the stream and leave the actual registration behind.
        response = await client.post(url, json=payload, headers={"x-stream-id": sensor_id})
        missing = response.status_code == 404 or (
            response.status_code == 400
            and (
                "no such resource" in response.text.casefold()
                or "resource not found" in response.text.casefold()
            )
        )
        if response.status_code in (200, 201, 204) or missing:
            logger.info("RTVI-CV stream removed: %s", scrub_log(sensor_id))
            return True, "Already absent" if missing else "OK"
        return False, f"RTVI-CV returned {response.status_code}: {response.text}"
    except Exception as e:
        logger.error(f"RTVI-CV remove failed: {e}", exc_info=True)
        return False, str(e)


# ============================================================================
# Elasticsearch Cleanup Helper
# ============================================================================


async def _delete_es_documents(es_endpoint: str, index_pattern: str, id_value: str, id_field: str) -> tuple[bool, str]:
    """
    Delete all Elasticsearch documents matching a field value.

    Uses the delete_by_query API to remove all documents where the specified
    field matches the given value.

    The field name and ID value vary by index (use .keyword for exact match):
      - mdx-embed-filtered:    field="sensor.id.keyword",  value=streamId (UUID)
      - mdx-behavior: field="sensor.id.keyword",  value=sensorName
      - mdx-raw:      field="sensorId.keyword",   value=sensorName

    Args:
        es_endpoint: Elasticsearch URL (e.g., http://localhost:9200)
        index_pattern: ES index name (e.g., "mdx-embed-filtered-2025-01-01")
        id_value: The value to match (either UUID or sensorName)
        id_field: The ES document field to match against (use .keyword for exact match)

    Returns:
        (success, message) tuple
    """
    es_client = AsyncElasticsearch(es_endpoint)
    try:
        result = await es_client.delete_by_query(
            index=index_pattern,
            body={
                "query": {
                    "term": {
                        id_field: id_value,
                    }
                }
            },
            refresh=True,
            conflicts="proceed",  # Don't fail on version conflicts
        )
        timed_out = result.get("timed_out")
        failures = result.get("failures")
        version_conflicts = result.get("version_conflicts")
        deleted = result.get("deleted")
        complete = (
            timed_out is False
            and failures == []
            and type(version_conflicts) is int
            and version_conflicts == 0
            and type(deleted) is int
            and deleted >= 0
        )
        if not complete:
            details = (
                f"timed_out_valid={timed_out is False}, failures_valid={failures == []}, "
                f"version_conflicts_valid={type(version_conflicts) is int and version_conflicts == 0}, "
                f"deleted_valid={type(deleted) is int and deleted >= 0}"
            )
            logger.error("ES delete_by_query was incomplete for index '%s': %s", index_pattern, details)
            return False, f"Delete incomplete: {details}"
        logger.info(
            "Deleted %s docs from ES index '%s' (field=%s, value=%s)",
            deleted,
            index_pattern,
            id_field,
            scrub_log(id_value),
        )
        return True, f"Deleted {deleted} documents"
    except NotFoundError:
        # Deletion is intentionally idempotent. Profiles do not necessarily
        # create every optional analytics index, so an absent index means
        # there is nothing left to remove rather than a partial failure.
        logger.info("ES index '%s' does not exist; nothing to delete", index_pattern)
        return True, "Index not present"
    except Exception as e:
        logger.error(f"ES delete_by_query failed for index '{index_pattern}': {e}", exc_info=True)
        return False, str(e)
    finally:
        await es_client.close()


# ============================================================================
# Router Factory
# ============================================================================


def create_video_delete_router(
    vst_internal_url: str,
    rtvi_cv_base_url: str = "",
    es_config: EsCleanupConfig | None = None,
) -> APIRouter:
    """
    Create a FastAPI router for video deletion.

    Per-step behavior is driven by what's configured: ES cleanup runs only
    when ``es_config`` is provided, RTVI-CV cleanup runs only when
    ``rtvi_cv_base_url`` is set. VST sensor + storage cleanup always runs.

    Args:
        vst_internal_url: Internal VST URL for API calls
        rtvi_cv_base_url: RTVI-CV service URL. Empty = skip RTVI-CV cleanup.
        es_config: Bundled ES URL + index names. ``None`` = skip ES cleanup.
            The URL and the index names live together so callers can't supply
            indexes without a URL.

    Returns:
        APIRouter with the delete video route
    """
    router = APIRouter()
    vst_url = vst_internal_url.rstrip("/")
    rtvi_cv_url = rtvi_cv_base_url.rstrip("/") if rtvi_cv_base_url else ""
    detector_urls = tuple(
        dict.fromkeys(
            endpoint
            for profile in ANALYSIS_PROFILES
            if profile.detection_enabled and (endpoint := analysis_profile_endpoint(rtvi_cv_url, profile.id))
        )
    )

    @router.delete(
        "/api/v1/videos/{video_id}",
        response_model=DeleteVideoResponse,
        response_model_exclude_none=True,
        summary="Delete an uploaded video",
        description=(
            "Deletes a video by its sensor/video ID (UUID). "
            "ES cleanup runs when es_config is provided; "
            "RTVI-CV cleanup runs when rtvi_cv_base_url is configured. "
            "VST sensor + storage are always removed."
        ),
        tags=["Video Management"],
    )
    async def delete_video(video_id: str) -> DeleteVideoResponse:
        """
        Delete a video from the system by sensor/video ID.

        Best-effort: continues even if individual steps fail and reports the
        overall result as 'success', 'partial', or 'failure'.

        Steps:
          0. Look up sensorName from VST (only when ES cleanup will run; needed
             for behavior/raw index queries).
          1. ES embed index delete by sensor.id = video_id        (skipped if no es_config)
          2. ES behavior index delete by sensor.id = sensorName   (skipped if no es_config)
          3. ES raw index delete by sensorId = sensorName         (skipped if no es_config)
          4. RTVI-CV remove                                       (skipped if no RTVI-CV URL)
          5. VST sensor delete
          6. VST storage delete

        Args:
            video_id: The sensor/video UUID (e.g., from the upload response)

        Returns:
            DeleteVideoResponse with overall status
        """
        results: list[bool] = []
        sensor_name = ""
        generated_data_deleted = 0

        logger.info("Deleting video '%s'", scrub_log(video_id))

        async with httpx.AsyncClient(timeout=60.0) as client:
            # --- Step 0: Look up sensorName from VST (only when ES cleanup will run) ---
            # Must happen BEFORE any deletions, since we need sensorName for ES queries.
            if es_config is not None:
                try:
                    with TimeMeasure("video_delete: lookup sensor name from VST"):
                        sensor_name = await get_sensor_id_from_stream_id(video_id, vst_url)
                except VSTError as e:
                    logger.warning(
                        "Could not look up sensorName for '%s': %s. ES cleanup for behavior/raw may not work.",
                        scrub_log(video_id),
                        scrub_log(e),
                    )
                    sensor_name = ""
                    # This is not an optional step when ES cleanup is enabled:
                    # behavior/raw documents are keyed by the VST name. Keep
                    # cleaning everything that can be identified, but ensure
                    # the aggregate result cannot report success.
                    results.append(False)

            # --- Generated-data cleanup (done before source/storage removal) ---
            # The source may be represented by UUID in embeddings and by name
            # in detector/analytics data. The shared cleanup covers every date
            # partition plus incidents and per-source caption collections.
            if es_config is not None:
                with TimeMeasure("video_delete: generated source data"):
                    generated_cleanup = await delete_generated_source_data(
                        es_config.url,
                        video_id,
                        sensor_name,
                    )
                generated_data_deleted = generated_cleanup.total_deleted
                results.append(generated_cleanup.success)
                if generated_cleanup.failures:
                    logger.error(
                        "Generated-data cleanup was incomplete for '%s': %s",
                        scrub_log(video_id),
                        sorted(generated_cleanup.failures),
                    )

            # --- Remove from RTVI-CV ---
            for detector_url in detector_urls:
                with TimeMeasure("video_delete: remove from RTVI-CV"):
                    success, msg = await _remove_from_rtvi_cv(
                        client,
                        detector_url,
                        video_id,
                        sensor_name,
                    )
                results.append(success)
                logger.info("Remove from RTVI-CV %s: %s", detector_url, "OK" if success else msg)

            # --- Delete VST storage (using shared vst utils) ---
            with TimeMeasure("video_delete: delete VST storage"):
                success, msg = await delete_vst_storage(vst_url, video_id)
            results.append(success)
            logger.info("Delete VST storage: %s", "OK" if success else msg)

            # --- Delete VST sensor (using shared vst utils) ---
            # Required: delete_vst_storage only removes stored files, not the
            # sensor registration — the two must be paired to fully remove a
            # video. Without this, sensors are orphaned in VST.
            with TimeMeasure("video_delete: delete VST sensor"):
                success, msg = await delete_vst_sensor(vst_url, video_id)
            results.append(success)
            logger.info("Delete VST sensor: %s", "OK" if success else msg)
            if success:
                forget_source_analysis_state(video_id)

        # --- Determine overall status ---
        all_success = bool(results) and all(results)
        any_success = any(results)

        if all_success:
            status = "success"
            message = f"Video '{video_id}' deleted successfully"
        elif any_success:
            status = "partial"
            message = f"Video '{video_id}' partially deleted - some steps failed"
        else:
            status = "failure"
            message = f"Failed to delete video '{video_id}'"

        logger.info("Delete video '%s' completed with status: %s", scrub_log(video_id), status)

        return DeleteVideoResponse(
            status=status,
            message=message,
            video_id=video_id,
            generated_data_deleted=generated_data_deleted,
        )

    return router


# ============================================================================
# Registration Function
# ============================================================================


def register_video_delete_routes(app: "FastAPI", config: "Any") -> None:
    """
    Register ``DELETE /api/v1/videos/{video_id}``.

    Registered unconditionally on every profile by
    ``CustomFastApiFrontEndWorker._register_streaming_routes`` — there's no
    capability flag. Every profile is expected to expose this endpoint so
    the UI's "delete uploaded video" action works the same way everywhere.

    Reads configuration from ``general.front_end.streaming_ingest``. Only
    ``vst_internal_url`` is required; ``elasticsearch_url`` and
    ``rtvi_cv_base_url`` are optional — empty values cause the corresponding
    cleanup steps to self-skip at request time.

    Raises:
        ValueError: when ``streaming_ingest`` is missing or
            ``vst_internal_url`` is empty.
    """
    try:
        streaming_config = getattr(config.general.front_end, "streaming_ingest", None)
        if streaming_config is None:
            raise ValueError(
                "streaming_ingest must be configured under general.front_end to register video delete routes"
            )

        vst_internal_url = getattr(streaming_config, "vst_internal_url", "") or ""
        elasticsearch_url = getattr(streaming_config, "elasticsearch_url", "") or ""
        rtvi_cv_base_url = getattr(streaming_config, "rtvi_cv_base_url", "") or ""

        if not vst_internal_url:
            raise ValueError("streaming_ingest.vst_internal_url must be set for video delete routes")

        # Uploaded videos use a fixed timestamp (2025-01-01) so they always land
        # in these specific indexes. Only build the ES config when a URL is set;
        # otherwise pass None and ES cleanup self-skips at request time.
        embed_index = (
            getattr(streaming_config, "rtvi_embed_es_index", "") or EsCleanupConfig.model_fields["embed_index"].default
        )
        es_config = EsCleanupConfig(url=elasticsearch_url, embed_index=embed_index) if elasticsearch_url else None

        router = create_video_delete_router(
            vst_internal_url=vst_internal_url,
            rtvi_cv_base_url=rtvi_cv_base_url,
            es_config=es_config,
        )
        app.include_router(router)
        logger.info(
            "Video delete routes registered "
            f"(es={'on' if es_config else 'off'}, "
            f"rtvi_cv={'on' if rtvi_cv_base_url else 'off'})"
        )

    except Exception as e:
        logger.error(f"Failed to register video delete routes: {e}", exc_info=True)
        raise
