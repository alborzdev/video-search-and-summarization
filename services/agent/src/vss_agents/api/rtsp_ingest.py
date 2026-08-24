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
RTSP stream ingestion: ``POST /api/v1/rtsp-streams/add``.

Adds a stream to VST and (when configured) registers it with RTVI-CV /
RTVI-Embed (search path) or RTVI-VLM (LVS path). On any failure, the
previously completed steps are rolled back in reverse.

Also defines the shared ``ServiceConfig`` and the VST / RTVI helper
functions used by both this module and ``rtsp_delete``. Keeping the helpers
here lets the ingest path use them directly for rollback while the delete
module just imports what it needs.
"""

import asyncio
from contextlib import suppress
import logging
from typing import Any
from typing import Literal
import urllib.parse

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from vss_agents.api.analysis_profile_capacity import AnalysisProfileCapacityError
from vss_agents.api.analysis_profile_capacity import commit_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import release_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import reserve_analysis_profile_capacity
from vss_agents.api.analysis_profiles import ANALYSIS_PROFILES
from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import WAREHOUSE_PROFILE_ID
from vss_agents.api.analysis_profiles import analysis_profile_endpoint
from vss_agents.api.analysis_profiles import require_analysis_profile
from vss_agents.api.source_analysis_state import forget_source_analysis_state
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import get_source_kind
from vss_agents.api.source_analysis_state import is_source_deleting
from vss_agents.api.source_analysis_state import is_source_detection_enabled
from vss_agents.api.source_analysis_state import is_source_paused
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.api.source_cleanup import registered_rtvi_cv_stream_ids
from vss_agents.tools.vst.utils import add_proxy_stream as vst_add_proxy_stream
from vss_agents.tools.vst.utils import add_sensor as vst_add_sensor
from vss_agents.tools.vst.utils import delete_proxy_stream as vst_delete_proxy_stream
from vss_agents.tools.vst.utils import delete_sensor as vst_delete_sensor
from vss_agents.tools.vst.utils import delete_storage as vst_delete_storage
from vss_agents.tools.vst.utils import get_rtsp_url as vst_get_rtsp_url
from vss_agents.tools.vst.utils import get_stream_info_by_name as vst_get_stream_info_by_name
from vss_agents.tools.vst.utils import get_streams_info as vst_get_streams_info
from vss_agents.utils.retry import create_retry_strategy
from vss_agents.utils.sanitize import scrub_log
from vss_agents.utils.time_measure import TimeMeasure

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================


class ServiceConfig:
    """Service URLs and settings - initialized once per router.

    Per-step runtime behavior is driven by URL presence: each integration
    self-skips when its URL is empty (see ``add_to_rtvi_cv``,
    ``add_to_rtvi_embed``, etc.). The only behavior that isn't reducible to
    URL presence is whether to also delete VST storage when an RTSP stream is
    removed, which is governed by ``delete_vst_storage_on_stream_remove``.
    """

    def __init__(
        self,
        vst_internal_url: str,
        vst_streamprocessor_url: str = "",
        rtvi_cv_base_url: str = "",
        rtvi_embed_base_url: str = "",
        rtvi_vlm_base_url: str = "",
        elasticsearch_url: str = "",
        lvs_backend_url: str = "",
        rtvi_embed_model: str = "cosmos-embed1-448p",
        rtvi_embed_chunk_duration: int = 5,
        delete_vst_storage_on_stream_remove: bool = True,
        enable_audio: bool = False,
    ):
        self.vst_url = vst_internal_url.rstrip("/")
        self.vst_streamprocessor_url = vst_streamprocessor_url.rstrip("/") if vst_streamprocessor_url else ""
        self.rtvi_cv_url = rtvi_cv_base_url.rstrip("/") if rtvi_cv_base_url else ""
        self.rtvi_embed_url = rtvi_embed_base_url.rstrip("/") if rtvi_embed_base_url else ""
        self.rtvi_vlm_url = rtvi_vlm_base_url.rstrip("/") if rtvi_vlm_base_url else ""
        self.elasticsearch_url = elasticsearch_url.rstrip("/") if elasticsearch_url else ""
        self.lvs_backend_url = lvs_backend_url.rstrip("/") if lvs_backend_url else ""
        self.rtvi_embed_model = rtvi_embed_model
        self.rtvi_embed_chunk_duration = rtvi_embed_chunk_duration
        self.delete_vst_storage_on_stream_remove = delete_vst_storage_on_stream_remove
        self.enable_audio = enable_audio


def _resolve_service_config(config: Any) -> ServiceConfig:
    """Build a ``ServiceConfig`` from ``general.front_end.streaming_ingest``.

    Shared between ``register_rtsp_ingest_routes`` and
    ``register_rtsp_delete_routes`` so both paths read the same YAML keys.
    """
    streaming_config = getattr(config.general.front_end, "streaming_ingest", None)
    if streaming_config is None:
        raise ValueError("streaming_ingest must be configured under general.front_end to register RTSP routes")

    vst_internal_url = getattr(streaming_config, "vst_internal_url", "") or ""
    if not vst_internal_url:
        raise ValueError("streaming_ingest.vst_internal_url must be set for RTSP routes")

    return ServiceConfig(
        vst_internal_url=vst_internal_url,
        vst_streamprocessor_url=getattr(streaming_config, "vst_streamprocessor_url", "") or "",
        rtvi_cv_base_url=getattr(streaming_config, "rtvi_cv_base_url", "") or "",
        rtvi_embed_base_url=getattr(streaming_config, "rtvi_embed_base_url", "") or "",
        rtvi_vlm_base_url=getattr(streaming_config, "rtvi_vlm_base_url", "") or "",
        elasticsearch_url=getattr(streaming_config, "elasticsearch_url", "") or "",
        lvs_backend_url=getattr(streaming_config, "lvs_backend_url", "") or "",
        rtvi_embed_model=getattr(streaming_config, "rtvi_embed_model", "cosmos-embed1-448p"),
        rtvi_embed_chunk_duration=getattr(streaming_config, "rtvi_embed_chunk_duration", 5),
        delete_vst_storage_on_stream_remove=bool(
            getattr(streaming_config, "delete_vst_storage_on_stream_remove", True)
        ),
        enable_audio=bool(getattr(streaming_config, "enable_audio", False)),
    )


# ============================================================================
# Request/Response Models
# ============================================================================


class AddStreamRequest(BaseModel):
    """Request model for adding an RTSP stream (matches VST API)."""

    model_config = ConfigDict(populate_by_name=True)

    sensor_url: str = Field(..., alias="sensorUrl", description="RTSP URL of the stream")
    name: str = Field(..., description="Name for the sensor/stream")
    username: str = Field(default="", description="RTSP authentication username")
    password: str = Field(default="", description="RTSP authentication password")
    location: str = Field(default="", description="Location information")
    tags: str = Field(default="", description="Tags for the sensor")
    detection_enabled: bool | None = Field(
        default=None,
        alias="detectionEnabled",
        description="Legacy detector toggle; analysisProfileId is authoritative when provided.",
    )
    analysis_profile_id: str | None = Field(
        default=None,
        alias="analysisProfileId",
        description="Validated VSS-owned source analysis profile",
    )

    @model_validator(mode="after")
    def resolve_analysis_profile(self) -> "AddStreamRequest":
        """Migrate the old detector bit to one concrete VSS profile."""
        profile_id = self.analysis_profile_id
        if profile_id is None:
            # Profile-aware callers always send ``analysisProfileId``.  Older
            # clients that omit both fields must remain usable without
            # silently allocating a heavyweight warehouse detector.  Only an
            # explicit legacy ``detectionEnabled: true`` opts into that worker.
            profile_id = WAREHOUSE_PROFILE_ID if self.detection_enabled is True else SEMANTIC_PROFILE_ID
        profile = require_analysis_profile(profile_id)
        self.analysis_profile_id = profile.id
        self.detection_enabled = profile.detection_enabled
        return self


class AddStreamResponse(BaseModel):
    """Response model for add stream operation."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["success", "failure"] = Field(..., description="'success' or 'failure'")
    message: str = Field(..., description="Human-readable status message")
    error: str | None = Field(None, description="Error details if failed")
    sensor_id: str | None = Field(None, alias="sensorId", description="Stable VST sensor identity on success")
    name: str | None = Field(None, description="Exact sensor name on success")
    detection_enabled: bool = Field(
        default=True,
        alias="detectionEnabled",
        description="Whether a detector profile is enabled for this source",
    )
    analysis_profile_id: str = Field(
        default=WAREHOUSE_PROFILE_ID,
        alias="analysisProfileId",
        description="Applied VSS-owned source analysis profile",
    )

    @model_validator(mode="after")
    def require_success_identity(self) -> "AddStreamResponse":
        """A successful lifecycle handoff must identify the exact VST sensor."""
        if self.status == "success" and (not self.sensor_id or not self.name):
            raise ValueError("successful RTSP add response requires sensorId and name")
        return self


# ============================================================================
# URL helpers
# ============================================================================


def _is_nvstream_url(url: str) -> bool:
    """True iff ``url`` path starts with ``/nvstream/`` (nvstreamer file -> RTSP)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # pragma: no cover
        return False
    return parsed.path.startswith("/nvstream/")


def _is_rtsp_url(url: str) -> bool:
    """Return whether a VST catalog entry is a live RTSP source.

    VST's ``sensor/streams`` inventory contains both live cameras and uploaded
    ``sensor_file`` recordings.  The live reconciler must never register a
    local file path with RTVI's live-stream APIs.
    """
    try:
        return urllib.parse.urlparse(url).scheme.casefold() == "rtsp"
    except Exception:  # pragma: no cover - urlparse is deliberately tolerant
        return False


def _with_include_audio(rtsp_url: str) -> str:
    """Merge ``includeAudio=true`` into ``rtsp_url``. No-op if already set."""
    parsed = urllib.parse.urlparse(rtsp_url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == "includeAudio" for key, _ in query_pairs):
        return rtsp_url
    query_pairs.append(("includeAudio", "true"))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query_pairs)))


# ============================================================================
# VST API Wrappers
# ============================================================================


async def add_to_vst(config: ServiceConfig, request: AddStreamRequest) -> tuple[bool, str, str | None, str | None]:
    """
    Add stream to VST and fetch the RTSP URL from streams API.
    Returns: (success, message, sensor_id, rtsp_url)
    """
    # Opt VST into nvstreamer's audio track when enable_audio is set.
    source_url = request.sensor_url
    if config.enable_audio and _is_nvstream_url(source_url):
        source_url = _with_include_audio(source_url)

    success, msg, sensor_id = await vst_add_sensor(
        sensor_url=source_url,
        name=request.name,
        username=request.username,
        password=request.password,
        location=request.location,
        tags=request.tags,
        vst_internal_url=config.vst_url,
    )
    if not success:
        return False, msg, None, None

    assert sensor_id is not None, "sensor_id should be set after successful VST add"

    if config.vst_streamprocessor_url:
        success, msg, rtsp_url = await vst_add_proxy_stream(
            sensor_id=sensor_id,
            sensor_url=source_url,
            name=request.name,
            streamprocessor_url=config.vst_streamprocessor_url,
        )
    else:
        success, msg, rtsp_url = await vst_get_rtsp_url(sensor_id, config.vst_url)
    if not success:
        return False, msg, sensor_id, None

    return True, "OK", sensor_id, rtsp_url


async def cleanup_vst_sensor(config: ServiceConfig, sensor_id: str | None) -> tuple[bool, str]:
    """Delete a directly provisioned proxy, then delete its VST sensor."""
    proxy_success = True
    proxy_msg = "OK"
    if config.vst_streamprocessor_url:
        proxy_success, proxy_msg = await vst_delete_proxy_stream(sensor_id, config.vst_streamprocessor_url)

    sensor_success, sensor_msg = await vst_delete_sensor(sensor_id, config.vst_url)
    if proxy_success and sensor_success:
        return True, "OK"
    failures = []
    if not proxy_success:
        failures.append(f"proxy: {proxy_msg}")
    if not sensor_success:
        failures.append(f"sensor: {sensor_msg}")
    return False, "; ".join(failures)


async def cleanup_vst_storage(config: ServiceConfig, sensor_id: str | None) -> tuple[bool, str]:
    """Delete storage files from VST using shared util."""
    return await vst_delete_storage(sensor_id, config.vst_url)


async def get_stream_info_by_name(config: ServiceConfig, name: str) -> tuple[bool, str, str | None, str | None]:
    """
    Find stream_id and RTSP URL from VST by camera/sensor name using shared util.
    Returns: (success, message, stream_id, rtsp_url)
    """
    stream_id, rtsp_url = await vst_get_stream_info_by_name(name, config.vst_url)
    if stream_id is None:
        return False, f"Stream with name '{name}' not found in VST", None, None
    return True, "OK", stream_id, rtsp_url


# ============================================================================
# RTVI API Functions (add)
# ============================================================================


def detector_endpoint_for_profile(config: ServiceConfig, profile_id: str) -> str:
    """Return the VSS-managed DeepStream worker assigned to one profile."""
    return analysis_profile_endpoint(config.rtvi_cv_url, profile_id)


def configured_detector_endpoints(config: ServiceConfig) -> tuple[str, ...]:
    """Return each distinct configured detector worker exactly once."""
    return tuple(
        dict.fromkeys(
            endpoint
            for profile in ANALYSIS_PROFILES
            if profile.detection_enabled and (endpoint := detector_endpoint_for_profile(config, profile.id))
        )
    )


async def add_to_rtvi_cv(
    client: httpx.AsyncClient,
    config: ServiceConfig,
    sensor_id: str,
    name: str,
    sensor_url: str,
    *,
    base_url: str | None = None,
) -> tuple[bool, str]:
    """
    Add stream to RTVI-CV.
    Returns: (success, message)
    """
    endpoint = config.rtvi_cv_url if base_url is None else base_url.rstrip("/")
    if not endpoint:
        logger.info("RTVI-CV not configured, skipping")
        return True, "Skipped (not configured)"

    url = f"{endpoint}/api/v1/stream/add"
    payload = {
        "key": "sensor",
        "value": {
            "camera_id": sensor_id,
            "camera_name": name,
            "camera_url": sensor_url,
            "change": "camera_add",
            "metadata": {"resolution": "1920x1080", "codec": "h264", "framerate": 30},
        },
        "headers": {"source": "vst"},
    }

    logger.info(f"Adding stream to RTVI-CV: POST {url}")
    logger.debug(f"Payload: {payload}")

    # `x-stream-id` is the routing key used by SDR's in-front-of-RTVI proxy
    # (HAProxy Ingress / Envoy + SDR coordinator). Consistent-hashing on this
    # header pins a stream to a single worker so subsequent add/delete/config
    # calls all land on the same pod. See Projects/SDR/wiki.md.
    try:
        async for retry in create_retry_strategy(delay=2, retries=6, exceptions=(httpx.TransportError, RuntimeError)):
            with retry:
                response = await client.post(url, json=payload, headers={"x-stream-id": sensor_id})
                if response.status_code not in (200, 201):
                    if response.status_code in (400, 409) and any(
                        marker in response.text.casefold()
                        for marker in ("already exists", "already registered", "duplicate")
                    ):
                        logger.info("RTVI-CV stream was already registered: %s", sensor_id)
                        return True, "Already registered"
                    error = f"RTVI-CV returned {response.status_code}: {response.text}"
                    if response.status_code in (408, 429) or response.status_code >= 500:
                        raise RuntimeError(error)
                    logger.error("RTVI-CV add failed (non-retryable): %s", error)
                    return False, error

                logger.info("RTVI-CV stream registered: %s", sensor_id)
                return True, "OK"

    except Exception as e:
        detail = str(e).strip() or type(e).__name__
        error = f"RTVI-CV request failed: {detail}"
        logger.error(error, exc_info=True)
        return False, error

    raise AssertionError("RTVI-CV: tenacity produced no retry attempt")


async def add_to_rtvi_embed(
    client: httpx.AsyncClient, config: ServiceConfig, sensor_id: str, name: str, sensor_url: str
) -> tuple[bool, str, str | None]:
    """
    Add stream to RTVI-embed with retries.

    During new stream ingestion the RTSP URL may exist but not yet be ready for
    consumption.  This function retries the POST to RTVI-embed so transient
    "stream not ready" failures are tolerated.

    Returns: (success, message, rtvi_stream_id)
    """
    if not config.rtvi_embed_url:
        logger.info("RTVI-embed not configured, skipping")
        return True, "Skipped (not configured)", sensor_id

    url = f"{config.rtvi_embed_url}/v1/streams/add"
    payload = {
        "streams": [
            {"liveStreamUrl": sensor_url, "description": "VST live stream", "sensor_name": name, "id": sensor_id}
        ]
    }

    logger.info(f"Adding stream to RTVI-embed: POST {url}")
    logger.debug(f"Payload: {payload}")

    # SDR routing key — same rationale as RTVI-CV add above.
    headers = {"x-stream-id": sensor_id}
    try:
        async for retry in create_retry_strategy(delay=2, retries=6, exceptions=(httpx.TransportError, RuntimeError)):
            with retry:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code not in (200, 201):
                    error = f"RTVI-embed returned {response.status_code}: {response.text}"
                    if response.status_code in (408, 429) or response.status_code >= 500:
                        raise RuntimeError(error)
                    logger.error(f"RTVI-embed add failed (non-retryable): {error}")
                    return False, error, None

                result = response.json()

                streams = result.get("streams", [])
                rtvi_stream_id = (streams[0].get("id") if streams else None) or sensor_id

                logger.info(f"RTVI-embed stream registered: {rtvi_stream_id}")
                return True, "Success", rtvi_stream_id
    except Exception as e:
        error = f"RTVI-embed request failed: {e!s}"
        logger.error(error, exc_info=True)
        return False, error, None

    raise AssertionError("RTVI-embed: tenacity produced no retry attempt")


async def add_to_rtvi_vlm(
    client: httpx.AsyncClient, config: ServiceConfig, sensor_id: str, name: str, sensor_url: str
) -> tuple[bool, str, str | None]:
    """
    Add stream to RTVI-VLM so LVS can use the VST sensor ID as a known resource.

    Returns: (success, message, rtvi_vlm_stream_id)
    """
    if not config.rtvi_vlm_url:
        logger.info("RTVI-VLM not configured, skipping")
        return True, "Skipped (not configured)", sensor_id

    url = f"{config.rtvi_vlm_url}/v1/streams/add"
    payload = {
        "streams": [
            {
                "liveStreamUrl": sensor_url,
                "description": name,
                # Pass sensor_id (not friendly name) so the protobuf streamId
                # stamped on raw_events == VST sensor_id. Logstash indexes
                # raw_events under `default_<streamId>`, the same key LVS
                # queries during summarization aggregation.
                "sensor_name": sensor_id,
                "id": sensor_id,
            }
        ],
    }

    logger.info(
        "Adding stream to RTVI-VLM (name=%r, sensor_id=%s): POST %s",
        scrub_log(name),
        scrub_log(sensor_id),
        scrub_log(url),
    )
    logger.debug("Payload: %s", scrub_log(payload))

    # SDR routing key — RTVI-VLM is also fronted by the same SDR proxy.
    headers = {"x-stream-id": sensor_id}
    try:
        async for retry in create_retry_strategy(delay=2, retries=6, exceptions=(httpx.TransportError, RuntimeError)):
            with retry:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code not in (200, 201):
                    error = f"RTVI-VLM returned {response.status_code}: {response.text}"
                    if response.status_code in (408, 429) or response.status_code >= 500:
                        raise RuntimeError(error)
                    logger.error(f"RTVI-VLM add failed (non-retryable): {error}")
                    return False, error, None

                result = response.json() if response.content else {}
                errors = result.get("errors") if isinstance(result, dict) else None
                results = result.get("results", []) if isinstance(result, dict) else []
                if errors and not results:
                    error = f"RTVI-VLM returned errors: {errors}"
                    # VST announces a newly allocated proxy URL before its SDP
                    # is necessarily ready. RTVI-VLM reports that short window
                    # as an HTTP-200 batch result containing InvalidFile/400,
                    # so classify it like the transport-level readiness errors
                    # already handled by this bounded retry loop. Schema and
                    # authentication errors remain immediately non-retryable.
                    if _rtvi_vlm_errors_are_retryable(errors):
                        raise RuntimeError(error)
                    return False, error, None

                rtvi_stream_id = (results[0].get("id") if results else None) or sensor_id
                logger.info(
                    "RTVI-VLM stream registered: rtvi_stream_id=%s (vst_sensor_id=%s)",
                    rtvi_stream_id,
                    sensor_id,
                )
                if rtvi_stream_id != sensor_id:
                    logger.warning(
                        "RTVI-VLM returned a different id than VST sensor_id; "
                        "downstream LVS lookups will use sensor_id=%s and may fail. "
                        "rtvi_stream_id=%s",
                        sensor_id,
                        rtvi_stream_id,
                    )
                return True, "OK", rtvi_stream_id
    except Exception as e:
        error = f"RTVI-VLM request failed: {e!s}"
        logger.error(error, exc_info=True)
        return False, error, None

    raise AssertionError("RTVI-VLM: tenacity produced no retry attempt")


def _rtvi_vlm_errors_are_retryable(errors: object) -> bool:
    """Return whether a failed RTSP batch contains only transient media-readiness errors."""
    if not isinstance(errors, list) or not errors:
        return False

    for item in errors:
        if not isinstance(item, dict):
            return False
        error_code = str(item.get("error_code", "")).casefold()
        status_code = item.get("status_code")
        if error_code != "invalidfile" or status_code != 400:
            return False

    return True


async def start_embedding_generation(
    client: httpx.AsyncClient | None, config: ServiceConfig, stream_id: str
) -> tuple[bool, str]:
    """
    Start and supervise embedding generation for a live stream.

    RTVI-Embed's live endpoint is an SSE response: closing the response also
    closes the embedding pipeline.  Keep a dedicated response open in a
    background task, reconnect when the RTSP source or service drops, and
    return once the first HTTP 200 proves that generation started.

    ``client`` remains in the signature for compatibility with existing
    callers, but a dedicated client is required because the ingest request's
    client is closed as soon as the add transaction completes.

    Returns: (success, message)
    """
    del client
    if not config.rtvi_embed_url:
        logger.info("RTVI-embed not configured, skipping embedding generation")
        return True, "Skipped (not configured)"

    existing = _embedding_generation_tasks.get(stream_id)
    if existing is not None and not existing.done():
        return True, "Already running"

    loop = asyncio.get_running_loop()
    started: asyncio.Future[tuple[bool, str]] = loop.create_future()
    task = asyncio.create_task(
        _supervise_embedding_generation(config, stream_id, started),
        name=f"live-embedding-{stream_id}",
    )
    _embedding_generation_tasks[stream_id] = task

    def remove_completed_task(completed: asyncio.Task[None]) -> None:
        if _embedding_generation_tasks.get(stream_id) is completed:
            _embedding_generation_tasks.pop(stream_id, None)

    task.add_done_callback(remove_completed_task)
    try:
        success, message = await asyncio.wait_for(asyncio.shield(started), timeout=60.0)
    except TimeoutError:
        success, message = False, "RTVI-embed did not acknowledge live generation within 60 seconds"

    if not success:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    return success, message


_embedding_generation_tasks: dict[str, asyncio.Task[None]] = {}
_embedding_bootstrap_tasks: set[asyncio.Task[None]] = set()
_embedding_connected_streams: set[str] = set()
_live_analysis_runtime_steps: dict[str, dict[str, bool]] = {}
_cv_registered_streams: set[str] = set()


def get_live_analysis_runtime_steps(stream_id: str) -> dict[str, bool]:
    """Return the last proved runtime state for a live source.

    A managed embedding task is checked at read time so status never reports
    active merely because a source is registered in VST.
    """
    task = _embedding_generation_tasks.get(stream_id)
    steps = dict(_live_analysis_runtime_steps.get(stream_id, {}))
    steps["embedding"] = bool(task is not None and not task.done() and stream_id in _embedding_connected_streams)
    return steps


def clear_live_analysis_runtime(stream_id: str) -> None:
    _live_analysis_runtime_steps.pop(stream_id, None)
    _cv_registered_streams.discard(stream_id)


def set_live_analysis_runtime_steps(stream_id: str, steps: dict[str, bool]) -> None:
    _live_analysis_runtime_steps[stream_id] = dict(steps)


async def _supervise_embedding_generation(
    config: ServiceConfig,
    stream_id: str,
    started: asyncio.Future[tuple[bool, str]],
) -> None:
    """Consume RTVI-Embed's SSE response and reconnect after interruptions."""
    url = f"{config.rtvi_embed_url}/v1/generate_video_embeddings"
    payload = {
        "id": stream_id,
        "model": config.rtvi_embed_model,
        "stream": True,
        "chunk_duration": config.rtvi_embed_chunk_duration,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        # SDR routing key — pin to the worker that owns this stream.
        "x-stream-id": stream_id,
    }
    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)

    while True:
        _embedding_connected_streams.discard(stream_id)
        try:
            logger.info("Starting supervised embedding generation for stream %s", stream_id)
            async with (
                httpx.AsyncClient(timeout=timeout) as dedicated_client,
                dedicated_client.stream("POST", url, json=payload, headers=headers) as response,
            ):
                if response.status_code != 200:
                    error_body = (await response.aread()).decode(errors="replace")
                    error = f"RTVI-embed returned {response.status_code}: {error_body}"
                    retryable = response.status_code in (408, 429) or response.status_code >= 500
                    if not started.done() and not retryable:
                        started.set_result((False, error))
                        return
                    logger.warning("Live embedding reconnect failed for %s: %s", stream_id, scrub_log(error))
                else:
                    _embedding_connected_streams.add(stream_id)
                    if not started.done():
                        started.set_result((True, "OK"))
                    logger.info("Embedding generation active for stream %s", stream_id)
                    async for _line in response.aiter_lines():
                        # Consuming the SSE body is what keeps RTVI-Embed's
                        # live pipeline alive. Kafka remains the data path.
                        pass
                    _embedding_connected_streams.discard(stream_id)
                    logger.warning("Live embedding response ended for %s; reconnecting", stream_id)
        except asyncio.CancelledError:
            logger.info("Live embedding supervisor stopped for stream %s", stream_id)
            raise
        except Exception as exc:
            _embedding_connected_streams.discard(stream_id)
            logger.warning(
                "Live embedding connection failed for %s; reconnecting: %s",
                stream_id,
                scrub_log(str(exc)),
            )

        await asyncio.sleep(3)


async def stop_managed_embedding_generation(stream_id: str) -> None:
    """Stop this process from reconnecting a stream during explicit deletion."""
    _embedding_connected_streams.discard(stream_id)
    task = _embedding_generation_tasks.pop(stream_id, None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _registered_stream_ids(client: httpx.AsyncClient, base_url: str) -> set[str]:
    """Read an RTVI stream inventory and return valid resource IDs."""
    if not base_url:
        return set()
    response = await client.get(f"{base_url}/v1/streams/get-stream-info")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("RTVI stream inventory returned an unexpected response")
    return {
        stream["id"]
        for stream in payload
        if isinstance(stream, dict) and isinstance(stream.get("id"), str) and stream["id"]
    }


async def _registered_cv_stream_ids(client: httpx.AsyncClient, base_url: str) -> set[str]:
    """Read RTVI-CV's real stream inventory.

    RTVI-CV loses dynamic stream registrations whenever its container is
    replaced. The agent process can survive that restart, so an in-memory set
    is not authoritative for recovery.
    """
    return await registered_rtvi_cv_stream_ids(client, base_url)


async def _detector_inventories(
    client: httpx.AsyncClient,
    config: ServiceConfig,
) -> dict[str, set[str]]:
    """Read every configured detector independently so one worker may recover."""
    inventories: dict[str, set[str]] = {}
    for endpoint in configured_detector_endpoints(config):
        try:
            inventories[endpoint] = await _registered_cv_stream_ids(client, endpoint)
        except Exception:
            inventories[endpoint] = set()
            logger.warning("Detector inventory is unavailable at %s", scrub_log(endpoint), exc_info=True)
    return inventories


async def _reconcile_live_source(
    client: httpx.AsyncClient,
    config: ServiceConfig,
    stream_id: str,
    name: str,
    rtsp_url: str,
    cv_inventories: dict[str, set[str]],
    embed_inventory: set[str],
    vlm_inventory: set[str],
) -> dict[str, bool]:
    """Ensure one desired-active VST source exists in every live pipeline."""
    steps: dict[str, bool] = {}

    profile_id = get_source_analysis_profile(stream_id)
    selected_endpoint = detector_endpoint_for_profile(config, profile_id)

    # A source belongs to exactly one detector worker. Remove stale
    # registrations before adding it to a newly selected profile.
    for endpoint, inventory in cv_inventories.items():
        if endpoint != selected_endpoint and stream_id in inventory:
            cv_success, cv_message = await cleanup_rtvi_cv(
                client,
                config,
                stream_id,
                name,
                rtsp_url,
                base_url=endpoint,
            )
            if cv_success:
                inventory.discard(stream_id)
            else:
                logger.warning(
                    "Could not remove stale detector registration for %s: %s",
                    scrub_log(stream_id),
                    scrub_log(cv_message),
                )

    detection_enabled = is_source_detection_enabled(stream_id)
    selected_inventory = cv_inventories.get(selected_endpoint, set())
    if not detection_enabled:
        _cv_registered_streams.discard(stream_id)
        steps["detection"] = False
    elif not selected_endpoint:
        steps["detection"] = False
        logger.warning(
            "Detector profile %s is configured for %s but its worker URL is unavailable",
            scrub_log(profile_id),
            scrub_log(stream_id),
        )
    elif stream_id not in selected_inventory:
        cv_success, cv_message = await add_to_rtvi_cv(
            client,
            config,
            stream_id,
            name,
            rtsp_url,
            base_url=selected_endpoint,
        )
        steps["detection"] = cv_success
        if cv_success:
            selected_inventory.add(stream_id)
            cv_inventories[selected_endpoint] = selected_inventory
            _cv_registered_streams.add(stream_id)
        else:
            logger.warning(
                "Could not restore detection for %s: %s",
                scrub_log(stream_id),
                scrub_log(cv_message),
            )
    else:
        steps["detection"] = True
        _cv_registered_streams.add(stream_id)

    if config.rtvi_embed_url and stream_id not in embed_inventory:
        embed_success, embed_message, _ = await add_to_rtvi_embed(client, config, stream_id, name, rtsp_url)
        steps["embedding_resource"] = embed_success
        if embed_success:
            embed_inventory.add(stream_id)
        else:
            logger.warning(
                "Could not restore embedding resource for %s: %s",
                scrub_log(stream_id),
                scrub_log(embed_message),
            )
    else:
        steps["embedding_resource"] = True

    if steps["embedding_resource"]:
        embed_success, embed_message = await start_embedding_generation(None, config, stream_id)
        steps["embedding"] = embed_success
        if not embed_success:
            logger.warning(
                "Could not restore live embedding for %s: %s",
                scrub_log(stream_id),
                scrub_log(embed_message),
            )
    else:
        steps["embedding"] = False

    # RTVI-VLM registration is the resource prerequisite for on-demand live
    # captions. Caption generation itself remains controlled by the saved
    # source-history scenario in the UI/LVS path.
    if config.rtvi_vlm_url and stream_id not in vlm_inventory:
        vlm_success, vlm_message, _ = await add_to_rtvi_vlm(client, config, stream_id, name, rtsp_url)
        steps["caption_resource"] = vlm_success
        if vlm_success:
            vlm_inventory.add(stream_id)
        else:
            logger.warning(
                "Could not restore caption resource for %s: %s",
                scrub_log(stream_id),
                scrub_log(vlm_message),
            )
    else:
        steps["caption_resource"] = True

    _live_analysis_runtime_steps[stream_id] = steps
    return steps


async def reconcile_live_source_now(
    config: ServiceConfig,
    stream_id: str,
    name: str,
    rtsp_url: str,
) -> dict[str, bool]:
    """Synchronously reconcile one source for the operator resume action."""
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        cv_inventories = await _detector_inventories(client, config)
        embed_inventory = (
            await _registered_stream_ids(client, config.rtvi_embed_url) if config.rtvi_embed_url else set()
        )
        vlm_inventory = await _registered_stream_ids(client, config.rtvi_vlm_url) if config.rtvi_vlm_url else set()
        return await _reconcile_live_source(
            client,
            config,
            stream_id,
            name,
            rtsp_url,
            cv_inventories,
            embed_inventory,
            vlm_inventory,
        )


async def stop_all_managed_embedding_generation() -> None:
    """Close every supervised SSE response during agent shutdown."""
    bootstrap_tasks = list(_embedding_bootstrap_tasks)
    for task in bootstrap_tasks:
        task.cancel()
    if bootstrap_tasks:
        await asyncio.gather(*bootstrap_tasks, return_exceptions=True)
    _embedding_bootstrap_tasks.clear()

    stream_ids = list(_embedding_generation_tasks)
    await asyncio.gather(
        *(stop_managed_embedding_generation(stream_id) for stream_id in stream_ids),
        return_exceptions=True,
    )


async def resume_registered_embedding_generation(config: ServiceConfig) -> None:
    """Continuously reconcile desired-active VST sources after restarts.

    VST is the durable source catalog. RTVI-CV, RTVI-Embed and RTVI-VLM keep
    registrations in memory, so discovering only RTVI-Embed at agent startup
    loses every source when all containers reboot together. This loop waits
    through startup ordering, reconstructs missing resources from VST, and
    repairs a later RTVI service restart without user intervention.
    """
    retry_delay_seconds = 5.0
    healthy_poll_seconds = 45.0

    while True:
        try:
            await reconcile_registered_live_sources(config)
            await asyncio.sleep(healthy_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Live-analysis reconciliation is waiting for VST/RTVI services",
                exc_info=True,
            )
            await asyncio.sleep(retry_delay_seconds)


async def reconcile_registered_live_sources(
    config: ServiceConfig,
) -> tuple[int, int]:
    """Run one VST-to-RTVI reconciliation pass and return active/desired counts."""
    catalog_streams = await vst_get_streams_info(config.vst_url)
    streams = {
        stream_id: stream
        for stream_id, stream in catalog_streams.items()
        if _is_rtsp_url(stream.get("url", ""))
        and get_source_kind(stream_id) != "recorded"
        and not is_source_deleting(stream_id)
    }
    desired_stream_ids = set(streams)

    # Stop orphan supervisors if a source was removed outside the agent
    # lifecycle route. Do not delete downstream data here.
    for managed_id in set(_embedding_generation_tasks) - desired_stream_ids:
        await stop_managed_embedding_generation(managed_id)
        clear_live_analysis_runtime(managed_id)

    timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        cv_inventories = await _detector_inventories(client, config)
        embed_inventory = (
            await _registered_stream_ids(client, config.rtvi_embed_url) if config.rtvi_embed_url else set()
        )
        vlm_inventory = await _registered_stream_ids(client, config.rtvi_vlm_url) if config.rtvi_vlm_url else set()

        active_count = 0
        desired_count = 0
        for stream_id, stream in streams.items():
            # The catalog was fetched before the RTVI inventories.  A delete
            # can start during those network calls, so check the tombstone a
            # second time before acting on this stale snapshot.
            if is_source_deleting(stream_id):
                await stop_managed_embedding_generation(stream_id)
                clear_live_analysis_runtime(stream_id)
                continue

            if is_source_paused(stream_id):
                await stop_managed_embedding_generation(stream_id)
                # RTVI-CV's dynamic remove endpoint is not safely idempotent:
                # some builds can tear down the active source when asked to
                # remove an ID that is not registered in that worker. The
                # inventory read above is therefore the guard, not merely an
                # optimization. It also prevents paused cameras from sending
                # noisy remove calls during every healthy poll.
                for endpoint, inventory in cv_inventories.items():
                    if stream_id not in inventory:
                        continue
                    removed, message = await cleanup_rtvi_cv(
                        client,
                        config,
                        stream_id,
                        stream.get("name", ""),
                        stream.get("url", ""),
                        base_url=endpoint,
                    )
                    if removed:
                        inventory.discard(stream_id)
                    else:
                        logger.warning(
                            "Could not pause detection for %s at %s: %s",
                            scrub_log(stream_id),
                            scrub_log(endpoint),
                            scrub_log(message),
                        )
                _live_analysis_runtime_steps[stream_id] = {
                    "detection": False,
                    "embedding_resource": stream_id in embed_inventory,
                    "embedding": False,
                    "caption_resource": stream_id in vlm_inventory,
                }
                continue

            desired_count += 1
            name = stream.get("name", "")
            rtsp_url = stream.get("url", "")
            if not name or not rtsp_url:
                _live_analysis_runtime_steps[stream_id] = {
                    "detection": False,
                    "embedding_resource": False,
                    "embedding": False,
                    "caption_resource": False,
                }
                continue

            await _reconcile_live_source(
                client,
                config,
                stream_id,
                name,
                rtsp_url,
                cv_inventories,
                embed_inventory,
                vlm_inventory,
            )
            runtime = get_live_analysis_runtime_steps(stream_id)
            if (not is_source_detection_enabled(stream_id) or runtime.get("detection")) and runtime.get("embedding"):
                active_count += 1

    logger.info(
        "Live-analysis reconciliation complete: %d/%d desired sources active",
        active_count,
        desired_count,
    )
    return active_count, desired_count


# ============================================================================
# RTVI Cleanup Functions (used by ingest rollback + delete path)
# ============================================================================


def _is_missing_rtvi_resource(response: httpx.Response) -> bool:
    """Return whether an RTVI delete response means the resource is gone.

    RTVI currently reports an unknown stream as HTTP 400 with a
    ``No such resource`` message, while other implementations may use 404.
    Both are successful outcomes for an idempotent delete. Other 400-class
    responses remain failures so malformed requests are not hidden.
    """
    if response.status_code == 404:
        return True
    if response.status_code != 400:
        return False
    response_text = response.text.casefold()
    return "no such resource" in response_text or "resource not found" in response_text


async def cleanup_rtvi_cv(
    client: httpx.AsyncClient,
    config: ServiceConfig,
    sensor_id: str,
    name: str = "",
    sensor_url: str = "",
    *,
    base_url: str | None = None,
) -> tuple[bool, str]:
    """Remove stream from RTVI-CV."""
    endpoint = config.rtvi_cv_url if base_url is None else base_url.rstrip("/")
    if not endpoint:
        return True, "Skipped (not configured)"

    # Do not send an unknown remove to RTVI-CV. Some worker builds can tear
    # down an unrelated active DeepStream pipeline instead of treating that
    # request as an idempotent no-op.
    try:
        registered_ids = await _registered_cv_stream_ids(client, endpoint)
    except Exception:
        # Preserve cleanup compatibility when an older worker has no inventory
        # endpoint. The remove response remains the fallback source of truth.
        logger.warning(
            "Could not read RTVI-CV inventory at %s before removing %s; falling back to remove",
            scrub_log(endpoint),
            scrub_log(sensor_id),
            exc_info=True,
        )
    else:
        if sensor_id not in registered_ids:
            logger.info(
                "RTVI-CV stream %s is already absent from %s; skipping unsafe remove",
                scrub_log(sensor_id),
                scrub_log(endpoint),
            )
            return True, "Already absent"

    url = f"{endpoint}/api/v1/stream/remove"
    payload = {
        "key": "sensor",
        "value": {
            "camera_id": sensor_id,
            "camera_name": name,
            "camera_url": sensor_url,
            "change": "camera_remove",
            "metadata": {"resolution": "1920x1080", "codec": "h264", "framerate": 30},
        },
        "headers": {"source": "vst"},
    }

    logger.info(f"Removing from RTVI-CV: POST {url}")

    # SDR routing key — same stream-id used on the add path, ensures the
    # remove lands on the worker that holds this stream's state.
    try:
        response = await client.post(url, json=payload, headers={"x-stream-id": sensor_id})
        if response.status_code in (200, 201, 204) or _is_missing_rtvi_resource(response):
            logger.info(f"RTVI-CV stream removed: {sensor_id}")
            return True, "Already absent" if _is_missing_rtvi_resource(response) else "OK"
        return False, f"RTVI-CV returned {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)


async def cleanup_source_from_all_rtvi_cv(
    client: httpx.AsyncClient,
    config: ServiceConfig,
    sensor_id: str,
    name: str = "",
    sensor_url: str = "",
) -> tuple[bool, str]:
    """Remove a source from every VSS detector worker, idempotently."""
    results = [
        await cleanup_rtvi_cv(
            client,
            config,
            sensor_id,
            name,
            sensor_url,
            base_url=endpoint,
        )
        for endpoint in configured_detector_endpoints(config)
    ]
    if not results:
        return True, "Skipped (no detector workers configured)"
    failures = [message for success, message in results if not success]
    return (False, "; ".join(failures)) if failures else (True, "OK")


async def cleanup_rtvi_embed_stream(
    client: httpx.AsyncClient, config: ServiceConfig, stream_id: str | None
) -> tuple[bool, str]:
    """Remove stream from RTVI-embed."""
    if not config.rtvi_embed_url:
        return True, "Skipped (not configured)"

    url = f"{config.rtvi_embed_url}/v1/streams/delete/{stream_id}"
    logger.info(f"Removing from RTVI-embed: DELETE {url}")

    # SDR routing key — pin to the worker that owns this stream's state.
    headers = {"x-stream-id": stream_id} if stream_id else {}
    try:
        response = await client.delete(url, headers=headers)
        if response.status_code in (200, 204):
            logger.info(f"RTVI-embed stream removed: {stream_id}")
            return True, "OK"
        if _is_missing_rtvi_resource(response):
            logger.info("RTVI-embed stream already absent: %s", stream_id)
            return True, "Already absent"
        return False, f"RTVI-embed returned {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)


async def cleanup_rtvi_embed_generation(
    client: httpx.AsyncClient, config: ServiceConfig, stream_id: str | None
) -> tuple[bool, str]:
    """Stop embedding generation in RTVI-embed."""
    if not config.rtvi_embed_url:
        return True, "Skipped (not configured)"

    url = f"{config.rtvi_embed_url}/v1/generate_video_embeddings/{stream_id}"
    logger.info(f"Stopping embedding generation: DELETE {url}")

    # SDR routing key.
    headers = {"x-stream-id": stream_id} if stream_id else {}
    try:
        response = await client.delete(url, headers=headers)
        if response.status_code in (200, 204):
            logger.info(f"Embedding generation stopped: {stream_id}")
            return True, "OK"
        if _is_missing_rtvi_resource(response):
            logger.info("RTVI-embed generation already absent: %s", stream_id)
            return True, "Already absent"
        return False, f"RTVI-embed returned {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)


async def cleanup_rtvi_vlm_stream(
    client: httpx.AsyncClient, config: ServiceConfig, stream_id: str | None
) -> tuple[bool, str]:
    """Remove stream from RTVI-VLM."""
    if not config.rtvi_vlm_url:
        return True, "Skipped (not configured)"

    url = f"{config.rtvi_vlm_url}/v1/streams/delete/{stream_id}"
    logger.info(f"Removing from RTVI-VLM: DELETE {url}")

    # SDR routing key
    headers = {"x-stream-id": stream_id} if stream_id else {}
    try:
        response = await client.delete(url, headers=headers)
        if response.status_code in (200, 204):
            logger.info(f"RTVI-VLM stream removed: {stream_id}")
            return True, "OK"
        if _is_missing_rtvi_resource(response):
            logger.info("RTVI-VLM stream already absent: %s", stream_id)
            return True, "Already absent"
        return False, f"RTVI-VLM returned {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)


# ============================================================================
# Router Factory
# ============================================================================


def create_rtsp_ingest_router(config: ServiceConfig) -> APIRouter:
    """Create the router that handles ``POST /api/v1/rtsp-streams/add``."""

    router = APIRouter()

    @router.post(
        "/api/v1/rtsp-streams/add",
        response_model=AddStreamResponse,
        response_model_exclude_none=True,
        summary="Add an RTSP stream",
        description=(
            "Adds stream to VST. RTVI-CV, RTVI-embed, and embedding generation steps "
            "self-skip when their respective URLs are not configured."
        ),
        tags=["RTSP Streams"],
    )
    async def add_stream(request: AddStreamRequest) -> AddStreamResponse:
        """
        Add an RTSP stream.

        1. Add to VST → get sensor_id
        2. Add to RTVI-CV (skipped when ``rtvi_cv_base_url`` is empty)
        3. Add to RTVI-embed (skipped when ``rtvi_embed_base_url`` is empty)
        4. Start embedding generation (skipped when ``rtvi_embed_base_url`` is empty)

        On failure at any step, previous steps are rolled back. Steps that
        self-skip never fail and never need rollback.
        """
        sensor_id = None
        rtvi_embed_stream_id = None
        rtvi_cv_added = False
        rtvi_embed_added = False
        assert request.analysis_profile_id is not None
        profile = require_analysis_profile(request.analysis_profile_id)
        detector_endpoint = detector_endpoint_for_profile(config, profile.id)

        if profile.detection_enabled and not detector_endpoint:
            return AddStreamResponse(
                status="failure",
                message=f"The {profile.name} detector is not configured on this VSS appliance",
                error="Selected detector worker is unavailable",
                detection_enabled=True,
                analysis_profile_id=profile.id,
            )

        try:
            capacity_reservation = reserve_analysis_profile_capacity(profile.id)
        except AnalysisProfileCapacityError as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc

        logger.info("Adding stream '%s'", scrub_log(request.name))

        try:
            # Step 1: Add to VST and get RTSP URL (uses shared utils).
            # The reservation prevents parallel adds from both passing the
            # finite-profile check while VST is creating their sensor ids.
            with TimeMeasure("rtsp_stream: add to VST"):
                success, msg, sensor_id, rtsp_url = await add_to_vst(config, request)

            if not success:
                # Sensor creation may have succeeded before proxy activation
                # failed. Roll back both resources instead of leaking an offline
                # sensor and returning an unhandled retry exception.
                if sensor_id is not None:
                    await cleanup_vst_sensor(config, sensor_id)
                    if config.delete_vst_storage_on_stream_remove:
                        await cleanup_vst_storage(config, sensor_id)
                return AddStreamResponse(
                    status="failure",
                    message=f"Failed at VST: {msg}",
                    error=msg,
                    detection_enabled=profile.detection_enabled,
                    analysis_profile_id=profile.id,
                )
            logger.info(f"Added RTSP to VST: {sensor_id} {rtsp_url} successfully")
            # After successful VST add, sensor_id and rtsp_url are guaranteed to be set.
            assert sensor_id is not None, "sensor_id should be set after successful VST add"
            assert rtsp_url is not None, "rtsp_url should be set after successful VST add"
            # Persist this before resource calls so the background reconciler
            # cannot race a semantic-only add and register it with RTVI-CV.
            try:
                commit_analysis_profile_capacity_reservation(capacity_reservation, sensor_id)
            except AnalysisProfileCapacityError as exc:
                # A parallel non-profile-aware state writer should never make
                # this path reachable, but do not leak the just-created VST
                # source or turn the domain conflict into an unstructured 500.
                await cleanup_vst_sensor(config, sensor_id)
                if config.delete_vst_storage_on_stream_remove:
                    await cleanup_vst_storage(config, sensor_id)
                raise HTTPException(status_code=409, detail=exc.detail) from exc
        finally:
            release_analysis_profile_capacity_reservation(capacity_reservation)

        set_source_kind(sensor_id, "live")

        # Integrations are additive. A unified deployment registers the same
        # VST proxy with RTVI-VLM for live alerts/captioning and with
        # RTVI-CV/Embed for semantic search. Single-purpose profiles continue
        # to configure only the URLs they need.
        rtvi_vlm_added = False
        search_path_configured = bool(config.rtvi_embed_url or detector_endpoint)

        async with httpx.AsyncClient(timeout=60.0) as client:
            if config.rtvi_vlm_url:
                with TimeMeasure("rtsp_stream: add to RTVI-VLM"):
                    success, msg, _rtvi_vlm_stream_id = await add_to_rtvi_vlm(
                        client, config, sensor_id, request.name, rtsp_url
                    )
                if not success:
                    forget_source_analysis_state(sensor_id)
                    await cleanup_vst_sensor(config, sensor_id)
                    await cleanup_vst_storage(config, sensor_id)
                    return AddStreamResponse(
                        status="failure",
                        message=f"Failed at RTVI-VLM: {msg}",
                        error=msg,
                        detection_enabled=profile.detection_enabled,
                        analysis_profile_id=profile.id,
                    )
                rtvi_vlm_added = True

            if not search_path_configured:
                return AddStreamResponse(
                    status="success",
                    message=f"Stream '{request.name}' added successfully",
                    error=None,
                    sensor_id=sensor_id,
                    name=request.name,
                    detection_enabled=profile.detection_enabled,
                    analysis_profile_id=profile.id,
                )

            # Step 2: Add to RTVI-CV using RTSP URL from VST streams API
            if profile.detection_enabled:
                with TimeMeasure("rtsp_stream: add to RTVI-CV"):
                    success, msg = await add_to_rtvi_cv(
                        client,
                        config,
                        sensor_id,
                        request.name,
                        rtsp_url,
                        base_url=detector_endpoint,
                    )
                if not success:
                    # Rollback all integrations completed before the failure.
                    if rtvi_vlm_added:
                        await cleanup_rtvi_vlm_stream(client, config, sensor_id)
                    forget_source_analysis_state(sensor_id)
                    await cleanup_vst_sensor(config, sensor_id)
                    await cleanup_vst_storage(config, sensor_id)
                    return AddStreamResponse(
                        status="failure",
                        message=f"Failed at RTVI-CV: {msg}",
                        error=msg,
                        detection_enabled=profile.detection_enabled,
                        analysis_profile_id=profile.id,
                    )
                rtvi_cv_added = True

            # Step 3: Add to RTVI-embed using RTSP URL from VST streams API
            with TimeMeasure("rtsp_stream: add to RTVI-embed"):
                success, msg, rtvi_embed_stream_id = await add_to_rtvi_embed(
                    client, config, sensor_id, request.name, rtsp_url
                )
            if not success:
                # Rollback: cleanup RTVI-CV and VST (sensor + storage)
                if rtvi_cv_added:
                    await cleanup_rtvi_cv(
                        client,
                        config,
                        sensor_id,
                        request.name,
                        rtsp_url,
                        base_url=detector_endpoint,
                    )
                if rtvi_vlm_added:
                    await cleanup_rtvi_vlm_stream(client, config, sensor_id)
                forget_source_analysis_state(sensor_id)
                await cleanup_vst_sensor(config, sensor_id)
                await cleanup_vst_storage(config, sensor_id)
                return AddStreamResponse(
                    status="failure",
                    message=f"Failed at RTVI-embed: {msg}",
                    error=msg,
                    detection_enabled=profile.detection_enabled,
                    analysis_profile_id=profile.id,
                )
            rtvi_embed_added = config.rtvi_embed_url != ""

            # Step 4: Start embedding generation
            if rtvi_embed_stream_id is None:
                rtvi_embed_stream_id = sensor_id
            with TimeMeasure("rtsp_stream: start embedding generation"):
                success, msg = await start_embedding_generation(client, config, rtvi_embed_stream_id)
            if not success:
                # Rollback: cleanup RTVI-embed, RTVI-CV, and VST (sensor + storage)
                if rtvi_embed_added:
                    await cleanup_rtvi_embed_stream(client, config, rtvi_embed_stream_id)
                if rtvi_cv_added:
                    await cleanup_rtvi_cv(
                        client,
                        config,
                        sensor_id,
                        request.name,
                        rtsp_url,
                        base_url=detector_endpoint,
                    )
                if rtvi_vlm_added:
                    await cleanup_rtvi_vlm_stream(client, config, sensor_id)
                forget_source_analysis_state(sensor_id)
                await cleanup_vst_sensor(config, sensor_id)
                await cleanup_vst_storage(config, sensor_id)
                return AddStreamResponse(
                    status="failure",
                    message=f"Failed at embedding generation: {msg}",
                    error=msg,
                    detection_enabled=profile.detection_enabled,
                    analysis_profile_id=profile.id,
                )

        # Success
        return AddStreamResponse(
            status="success",
            message=f"Stream '{request.name}' added successfully",
            error=None,
            sensor_id=sensor_id,
            name=request.name,
            detection_enabled=profile.detection_enabled,
            analysis_profile_id=profile.id,
        )

    return router


# ============================================================================
# Registration Function
# ============================================================================


def register_rtsp_ingest_routes(app: FastAPI, config: Any) -> None:
    """Register ``POST /api/v1/rtsp-streams/add``.

    Reads configuration from ``general.front_end.streaming_ingest``. Only
    ``vst_internal_url`` is required; ``rtvi_*_base_url`` values are optional
    and unset URLs cause the corresponding RTVI step to self-skip at request
    time (each profile gets the same shape).
    """
    try:
        service_config = _resolve_service_config(config)
        app.include_router(create_rtsp_ingest_router(service_config))

        async def resume_live_embeddings() -> None:
            await resume_registered_embedding_generation(service_config)

        # NAT installs custom routes from within its own startup lifecycle, so
        # a newly added FastAPI startup handler would be too late in that
        # deployment. Schedule immediately when a loop is already running;
        # conventional pre-start registration still uses the app event.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            app.add_event_handler("startup", resume_live_embeddings)
        else:
            resume_task = running_loop.create_task(resume_live_embeddings(), name="resume-live-embeddings")
            _embedding_bootstrap_tasks.add(resume_task)
            resume_task.add_done_callback(_embedding_bootstrap_tasks.discard)
        app.add_event_handler("shutdown", stop_all_managed_embedding_generation)
        logger.info(
            "RTSP ingest route registered "
            f"(rtvi_embed={'on' if service_config.rtvi_embed_url else 'off'}, "
            f"rtvi_cv={'on' if service_config.rtvi_cv_url else 'off'}, "
            f"rtvi_vlm={'on' if service_config.rtvi_vlm_url else 'off'}, "
            f"direct_proxy={'on' if service_config.vst_streamprocessor_url else 'off'})"
        )
    except Exception as e:
        logger.error(f"Failed to register RTSP ingest route: {e}", exc_info=True)
        raise
