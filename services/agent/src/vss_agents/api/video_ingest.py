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
Profile-agnostic video upload routes.

The chat upload flow is a three-step contract:

1. ``POST /api/v1/videos`` — the UI sends ``{filename}`` and gets back
   ``{url}`` (the VST nvstreamer upload endpoint). The agent owns URL
   resolution so the browser doesn't need to know where VST lives.
2. The UI POSTs the file in chunks directly to that URL (nvstreamer
   protocol; the agent is not in the upload data path). VST returns
   ``sensorId`` on the final-chunk response — that's the VST sensor id.
3. ``POST /api/v1/videos/{sensor_id}/complete`` — the UI calls this with
   VST's sensor id to trigger post-processing: timeline lookup, storage
   URL resolution, optional RTVI-CV register, optional embedding
   generation. Each step self-skips if its backing service isn't
   configured, so the same endpoint works on every profile.

Naming: this path uses ``{sensor_id}`` to mirror VST's API surface
(``/vst/api/v1/sensor/...``). For uploaded videos one sensor maps to a
single stream, so ``sensor_id`` is unambiguous as the video identifier
here. For live RTSP ingestion a single VST sensor can fan out to
multiple streams — that lifecycle is handled by ``rtsp_ingest.py`` /
``rtsp_delete.py``, not this module.
"""

import asyncio
import json
import logging
import math
import os
import re
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

from vss_agents.api.analysis_profile_capacity import AnalysisProfileCapacityError
from vss_agents.api.analysis_profile_capacity import claim_source_analysis_profile_capacity
from vss_agents.api.analysis_profile_capacity import commit_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import release_analysis_profile_capacity_reservation
from vss_agents.api.analysis_profile_capacity import reserve_analysis_profile_capacity
from vss_agents.api.analysis_profiles import ANALYSIS_PROFILES
from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import analysis_profile_endpoint
from vss_agents.api.analysis_profiles import require_analysis_profile
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.tools.vst.timeline import get_timeline
from vss_agents.tools.vst.utils import VSTError
from vss_agents.tools.vst.utils import get_sensor_id_from_stream_id
from vss_agents.utils.time_measure import TimeMeasure
from vss_agents.utils.url_translation import rewrite_url_host

logger = logging.getLogger(__name__)

DEFAULT_RTVI_CV_TIMEOUT_SECONDS = 60.0
DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS = 600.0
DEFAULT_VST_STORAGE_TIMEOUT_SECONDS = 60.0
DEFAULT_VST_UPLOAD_TIMEOUT_SECONDS = 300.0
DEFAULT_BEHAVIOR_ES_INDEX = "mdx-behavior-2025-01-01"
DEFAULT_RAW_ES_INDEX = "mdx-raw-2025-01-01"
CANCELLATION_ROLLBACK_TIMEOUT_SECONDS = 120.0

ENV_RTVI_CV_TIMEOUT_SECONDS = "VIDEO_INGEST_RTVI_CV_TIMEOUT_SECONDS"
ENV_RTVI_EMBED_TIMEOUT_SECONDS = "VIDEO_INGEST_RTVI_EMBED_TIMEOUT_SECONDS"
ENV_VST_STORAGE_TIMEOUT_SECONDS = "VIDEO_INGEST_VST_STORAGE_TIMEOUT_SECONDS"
ENV_VST_UPLOAD_TIMEOUT_SECONDS = "VIDEO_INGEST_VST_UPLOAD_TIMEOUT_SECONDS"

# Sensor ids arrive on the request path and flow into logs and the VST
# storage URL, so restrict them to an allowlist at the boundary.
_SENSOR_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")


async def _delete_detector_generated_data(
    elasticsearch_url: str,
    sensor_id: str,
    source_name: str,
) -> Any:
    """Lazily load ES cleanup so upload-only profiles keep a small import surface."""
    from vss_agents.api.source_cleanup import delete_generated_source_data

    return await delete_generated_source_data(
        elasticsearch_url,
        sensor_id,
        source_name,
        categories=("detections", "behavior", "incidents", "vlm_incidents"),
        delete_caption_collection=False,
    )


async def _remove_recording_from_detector(
    client: httpx.AsyncClient,
    endpoint: str,
    sensor_id: str,
    source_name: str,
) -> tuple[bool, str]:
    """Use the canonical idempotent RTVI-CV removal contract lazily."""
    from vss_agents.api.video_delete import _remove_from_rtvi_cv

    return await _remove_from_rtvi_cv(client, endpoint, sensor_id, source_name)


def _validate_sensor_id(sensor_id: str) -> str:
    if not sensor_id or not _SENSOR_ID_RE.match(sensor_id):
        raise HTTPException(status_code=400, detail="invalid sensor_id")
    # Belt-and-braces CR/LF strip for static-analysis taint trackers; the
    # allowlist above already excludes these chars, so it is a runtime no-op.
    return re.sub(r"[\r\n]", "", sensor_id)


def _parse_optional_http_url(url: str | None) -> urllib.parse.ParseResult | None:
    """
    Parse an optional HTTP(S) URL used to locate a downstream service.

    Returns the parsed URL if it has a hostname, otherwise None. Catches
    URLs like "", "http://", "http:", "http://host:" (no port body) —
    anything that wouldn't successfully connect — and classifies them as
    "not configured" so callers can skip the downstream step.

    A URL relying on the scheme's default port (e.g. "http://host") is
    considered valid: hostname alone is enough to connect.
    """
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # pragma: no cover — urlparse is extremely permissive
        return None
    if not parsed.hostname:
        return None
    # `http://host:` (trailing colon with empty port body) reaches us with a
    # valid hostname but no resolvable port — Python's urlparse leaves the
    # netloc as `host:` so calls would silently fall back to the scheme's
    # default port (80 / 443) and connect to nothing. Treat that as
    # misconfigured so callers skip the downstream step.
    if parsed.netloc.endswith(":"):
        return None
    return parsed


def _parse_timeout_seconds(raw_value: Any, *, setting_name: str) -> float | None:
    """Parse an optional timeout value to a positive finite float.

    Returns ``None`` if ``raw_value`` is unset, malformed, non-positive, or
    non-finite (NaN/Inf). The caller decides what to do on ``None`` — for
    YAML inputs that's "try the env-var fallback before defaulting", which
    matches the documented "YAML > env > default" precedence.

    Notable rejections (each logs a warning so misconfiguration is visible):

    - ``True``/``False`` — YAML coerces ``yes``/``no`` to bool, then ``float``
      happily turns them into 1.0 / 0.0. A typo like
      ``vst_upload_timeout_seconds: yes`` would silently become a 1-second
      timeout. Reject bool before the ``float()`` call.
    - ``"nan"``, ``"inf"``, ``float('inf')`` — accepted by ``float`` and pass
      ``> 0`` (NaN comparisons are always False; +Inf is positive). httpx's
      behaviour on these is undefined, so reject up front.
    """
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, bool):
        logger.warning("Invalid %s=%r; bool/YAML-yes/no isn't a timeout, skipping", setting_name, raw_value)
        return None
    try:
        timeout_seconds = float(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; not a number, skipping", setting_name, raw_value)
        return None
    if not math.isfinite(timeout_seconds):
        logger.warning("Invalid %s=%r; must be finite, skipping", setting_name, raw_value)
        return None
    if timeout_seconds <= 0:
        logger.warning("Invalid %s=%r; timeout must be > 0, skipping", setting_name, raw_value)
        return None
    return timeout_seconds


def _resolve_timeout_seconds(
    streaming_config: Any,
    *,
    attr_name: str,
    env_name: str,
    default: float,
) -> float:
    """Resolve a timeout value using ``YAML > env > default`` precedence.

    Each source is parsed via :func:`_parse_timeout_seconds`; a malformed
    value on one source falls through to the next. This matches operator
    intuition: setting the env var lets you recover from a typo in YAML
    without having to redeploy the chart.

    ``streaming_config`` is whatever pydantic produced from
    ``general.front_end.streaming_ingest`` — a model with attributes, or
    ``None`` when NAT stripped the section. Other callers (tests, dev
    harnesses) typically pass a ``SimpleNamespace``.
    """
    raw_yaml = getattr(streaming_config, attr_name, None) if streaming_config else None
    parsed = _parse_timeout_seconds(raw_yaml, setting_name=attr_name)
    if parsed is not None:
        return parsed
    raw_env = os.getenv(env_name, "")
    parsed = _parse_timeout_seconds(raw_env, setting_name=env_name)
    if parsed is not None:
        return parsed
    return default


class VideoIngestResponse(BaseModel):
    """Response for video ingest endpoint."""

    message: str = Field(..., description="Status message indicating completion")
    sensor_id: str = Field(..., description="VST sensor id for the uploaded video (matches the {sensor_id} path param)")
    filename: str = Field(..., description="The filename returned by VST after upload")
    chunks_processed: int = Field(default=0, description="Number of chunks processed")
    analysis_profile_id: str = Field(
        default=SEMANTIC_PROFILE_ID,
        alias="analysisProfileId",
        description="Applied VSS-owned source analysis profile",
    )

    model_config = ConfigDict(populate_by_name=True)


class RecordedAnalysisRequest(BaseModel):
    """Select and rerun detector analytics for an existing recording."""

    analysis_profile_id: str = Field(alias="analysisProfileId")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecordedAnalysisResponse(BaseModel):
    analysis_profile_id: str = Field(alias="analysisProfileId")
    previous_profile_id: str = Field(alias="previousProfileId")
    detection_enabled: bool = Field(alias="detectionEnabled")
    generated_data_deleted: int = Field(alias="generatedDataDeleted")
    message: str
    sensor_id: str = Field(alias="sensorId")
    state: Literal["ready"] = "ready"

    model_config = ConfigDict(populate_by_name=True)


class VideoUploadUrlInput(BaseModel):
    """Input for ``POST /api/v1/videos`` — the upload-URL handshake."""

    model_config = ConfigDict(extra="ignore")

    filename: str = Field(..., min_length=1, description="Video filename to upload")


class VideoUploadUrlResponse(BaseModel):
    """Response for ``POST /api/v1/videos``."""

    url: str = Field(..., description="VST nvstreamer endpoint to POST chunks to")


class VideoUploadCompleteInput(BaseModel):
    """Input for ``POST /api/v1/videos/{sensor_id}/complete``.

    The UI forwards the VST upload response as the request body so the
    schema stays loose against storage-API churn. Only ``filename`` is read
    today (used for the response message and RTVI ``camera_name``); the
    rest is ignored.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    filename: str | None = Field(
        default=None,
        description="Original filename returned by VST (used in the response message and RTVI camera_name)",
    )
    custom_params: dict[str, Any] | None = Field(
        default=None,
        description="Optional per-upload custom parameters forwarded by the UI",
    )
    analysis_profile_id: str = Field(
        default=SEMANTIC_PROFILE_ID,
        alias="analysisProfileId",
        description="Validated VSS-owned source analysis profile",
    )


class _VideoUploadConfig(BaseModel):
    """Resolved settings for the video upload routes.

    Built once at registration time from ``streaming_ingest`` (preferred) or
    environment variables (fallback for profiles where NAT strips the
    section). ``vst_internal_url`` is the only required field — the RTVI URLs
    are optional and downstream calls self-skip when their URL is empty.
    ``vst_external_url`` falls back to ``vst_internal_url`` when unset (works
    for in-cluster deployments where the URL the browser can hit is the same
    as the URL the agent uses server-to-server).
    """

    vst_internal_url: str
    vst_external_url: str = ""
    rtvi_embed_base_url: str = ""
    rtvi_cv_base_url: str = ""
    elasticsearch_url: str = ""
    rtvi_embed_es_index: str = "mdx-embed-filtered-2025-01-01"
    rtvi_embed_model: str = "cosmos-embed1-448p"
    rtvi_embed_chunk_duration: int = 5
    disable_audio: bool = True
    rtvi_cv_timeout_seconds: float = DEFAULT_RTVI_CV_TIMEOUT_SECONDS
    rtvi_embed_timeout_seconds: float = DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS
    vst_storage_timeout_seconds: float = DEFAULT_VST_STORAGE_TIMEOUT_SECONDS
    vst_upload_timeout_seconds: float = DEFAULT_VST_UPLOAD_TIMEOUT_SECONDS


def _resolve_video_upload_config(config: "Any") -> _VideoUploadConfig | None:
    """Read upload settings from YAML ``streaming_ingest`` with env-var fallback.

    Returns None when ``VST_INTERNAL_URL`` can't be resolved — the caller logs
    and skips registration so the agent boots without these routes.
    """
    streaming_config = getattr(getattr(config.general, "front_end", None), "streaming_ingest", None)

    if streaming_config:
        vst_internal_url = getattr(streaming_config, "vst_internal_url", None) or os.getenv("VST_INTERNAL_URL", "")
        vst_external_url = getattr(streaming_config, "vst_external_url", None) or os.getenv("VST_EXTERNAL_URL", "")
        rtvi_embed_base_url = getattr(streaming_config, "rtvi_embed_base_url", None) or ""
        rtvi_cv_base_url = getattr(streaming_config, "rtvi_cv_base_url", None) or ""
        elasticsearch_url = getattr(streaming_config, "elasticsearch_url", None) or ""
        rtvi_embed_es_index = getattr(streaming_config, "rtvi_embed_es_index", None) or "mdx-embed-filtered-2025-01-01"
        rtvi_embed_model = getattr(streaming_config, "rtvi_embed_model", "cosmos-embed1-448p")
        rtvi_embed_chunk_duration = getattr(streaming_config, "rtvi_embed_chunk_duration", 5)
        disable_audio = not bool(getattr(streaming_config, "enable_audio", False))
    else:
        # NAT may strip unknown config sections — fall back to env vars set by
        # the deploy template. Empty RTVI_*_PORT (base profile, where RTVI
        # isn't deployed) keeps the URL empty so the post-processing step
        # skips at request time instead of hanging on `http://host:`.
        vst_internal_url = os.getenv("VST_INTERNAL_URL", "")
        vst_external_url = os.getenv("VST_EXTERNAL_URL", "")
        host_ip = os.getenv("HOST_IP", "")
        rtvi_embed_port = os.getenv("RTVI_EMBED_PORT", "")
        rtvi_cv_port = os.getenv("RTVI_CV_PORT", "")
        rtvi_embed_base_url = f"http://{host_ip}:{rtvi_embed_port}" if host_ip and rtvi_embed_port else ""
        rtvi_cv_base_url = f"http://{host_ip}:{rtvi_cv_port}" if host_ip and rtvi_cv_port else ""
        elasticsearch_url = os.getenv("ELASTIC_SEARCH_ENDPOINT", "")
        rtvi_embed_es_index = os.getenv("ELASTIC_SEARCH_INDEX", "mdx-embed-filtered-2025-01-01")
        rtvi_embed_model = os.getenv("RTVI_EMBED_MODEL", "cosmos-embed1-448p")
        rtvi_embed_chunk_duration = 5
        disable_audio = os.getenv("ENABLE_AUDIO", "false").strip().lower() not in ("true", "1", "yes")

    if not vst_internal_url:
        return None

    rtvi_cv_timeout_seconds = _resolve_timeout_seconds(
        streaming_config,
        attr_name="rtvi_cv_timeout_seconds",
        env_name=ENV_RTVI_CV_TIMEOUT_SECONDS,
        default=DEFAULT_RTVI_CV_TIMEOUT_SECONDS,
    )
    rtvi_embed_timeout_seconds = _resolve_timeout_seconds(
        streaming_config,
        attr_name="rtvi_embed_timeout_seconds",
        env_name=ENV_RTVI_EMBED_TIMEOUT_SECONDS,
        default=DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS,
    )
    vst_storage_timeout_seconds = _resolve_timeout_seconds(
        streaming_config,
        attr_name="vst_storage_timeout_seconds",
        env_name=ENV_VST_STORAGE_TIMEOUT_SECONDS,
        default=DEFAULT_VST_STORAGE_TIMEOUT_SECONDS,
    )
    vst_upload_timeout_seconds = _resolve_timeout_seconds(
        streaming_config,
        attr_name="vst_upload_timeout_seconds",
        env_name=ENV_VST_UPLOAD_TIMEOUT_SECONDS,
        default=DEFAULT_VST_UPLOAD_TIMEOUT_SECONDS,
    )

    return _VideoUploadConfig(
        vst_internal_url=vst_internal_url,
        vst_external_url=vst_external_url or vst_internal_url,
        rtvi_embed_base_url=rtvi_embed_base_url,
        rtvi_cv_base_url=rtvi_cv_base_url,
        elasticsearch_url=elasticsearch_url,
        rtvi_embed_es_index=rtvi_embed_es_index,
        rtvi_embed_model=rtvi_embed_model,
        rtvi_embed_chunk_duration=rtvi_embed_chunk_duration,
        disable_audio=disable_audio,
        rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
        rtvi_embed_timeout_seconds=rtvi_embed_timeout_seconds,
        vst_storage_timeout_seconds=vst_storage_timeout_seconds,
        vst_upload_timeout_seconds=vst_upload_timeout_seconds,
    )


async def _register_with_rtvi_cv(
    *,
    rtvi_cv_base_url: str,
    sensor_id: str,
    camera_name: str,
    vst_file_path: str,
    start_timestamp: str,
    timeout_seconds: float = DEFAULT_RTVI_CV_TIMEOUT_SECONDS,
) -> None:
    """POST ``/api/v1/stream/add`` to RTVI-CV.

    URL absence is how profiles declare RTVI-CV optional.  Once a URL is
    configured, every transport or HTTP failure is fatal: returning a
    successful ``/complete`` response after a silent registration skip makes
    an uploaded Search source look ready even though attribute and fusion
    search cannot see it.
    """
    # `x-stream-id` is the routing key for SDR-fronted RTVI deployments: the
    # in-front-of-RTVI proxy (HAProxy Ingress or Envoy via SDR coordinator)
    # consistent-hashes this header to pin a stream to one worker pod.
    # Without it the proxy falls back to round-robin and subsequent
    # /add → /delete → /config calls for the same sensor can land on different
    # workers. See Projects/SDR/wiki.md for the routing contract.
    rtvi_cv_url = rtvi_cv_base_url.rstrip("/")
    rtvi_cv_add_url = f"{rtvi_cv_url}/api/v1/stream/add"
    rtvi_cv_payload = {
        "key": "sensor",
        "value": {
            "camera_id": sensor_id,
            "camera_name": camera_name,
            "camera_url": vst_file_path,
            "creation_time": start_timestamp,
            "change": "camera_add",
            "metadata": {"resolution": "1920x1080", "codec": "h264", "framerate": 30},
        },
        "headers": {"source": "vst", "created_at": start_timestamp},
    }

    logger.info(f"Adding video to RTVI-CV: POST {rtvi_cv_add_url}")

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            with TimeMeasure("video_ingest: register with RTVI-CV"):
                response = await client.post(
                    rtvi_cv_add_url,
                    json=rtvi_cv_payload,
                    headers={"x-stream-id": sensor_id},
                )
            if response.status_code not in (200, 201):
                error_msg = f"RTVI-CV returned {response.status_code}: {response.text}"
                logger.error(error_msg)
                raise HTTPException(status_code=502, detail=f"RTVI-CV add failed: {error_msg}")
            logger.info(f"RTVI-CV video added: {sensor_id}")
    except httpx.ConnectError as exc:
        logger.error("Configured RTVI-CV is not reachable at %s", rtvi_cv_add_url)
        raise HTTPException(status_code=502, detail="RTVI-CV add failed: service not reachable") from exc
    except httpx.TimeoutException as exc:
        logger.error("Configured RTVI-CV timed out at %s", rtvi_cv_add_url)
        raise HTTPException(status_code=502, detail="RTVI-CV add failed: request timed out") from exc
    except httpx.RequestError as exc:
        logger.error("Configured RTVI-CV request failed at %s: %s", rtvi_cv_add_url, exc)
        raise HTTPException(status_code=502, detail="RTVI-CV add failed: request error") from exc


async def _rollback_search_post_processing(
    *,
    sensor_id: str,
    camera_name: str,
    rtvi_cv_base_url: str,
    cv_may_be_registered: bool,
    embedding_may_have_written: bool,
    elasticsearch_url: str,
    rtvi_embed_es_index: str,
    rtvi_cv_timeout_seconds: float,
) -> list[str]:
    """Remove downstream state created before a failed embedding call.

    VST media is intentionally retained so an operator can safely retry the
    ``/complete`` step. Only state created by this post-processing attempt is
    rolled back, scoped by the VST-assigned sensor id.
    """
    # Imported lazily to keep the upload module usable in profiles that do not
    # instantiate the delete router until application registration.
    from vss_agents.api.video_delete import _delete_es_documents
    from vss_agents.api.video_delete import _remove_from_rtvi_cv

    failures: list[str] = []
    if cv_may_be_registered:
        async with httpx.AsyncClient(timeout=rtvi_cv_timeout_seconds) as client:
            success, message = await _remove_from_rtvi_cv(
                client,
                rtvi_cv_base_url.rstrip("/"),
                sensor_id,
                camera_name,
            )
        if not success:
            logger.error("RTVI-CV rollback failed for %s: %s", sensor_id, message)
            failures.append("rtvi-cv")

    es_targets: list[tuple[str, str, str, str]] = []
    if embedding_may_have_written:
        es_targets.append(("rtvi-embed", rtvi_embed_es_index, "sensor.id.keyword", sensor_id))
    if cv_may_be_registered:
        es_targets.extend(
            [
                ("behavior", DEFAULT_BEHAVIOR_ES_INDEX, "sensor.id.keyword", camera_name),
                ("raw", DEFAULT_RAW_ES_INDEX, "sensorId.keyword", camera_name),
            ]
        )
    if es_targets and not elasticsearch_url:
        logger.error("Search rollback is incomplete: Elasticsearch cleanup is not configured")
        failures.append("elasticsearch-cleanup-unconfigured")
    else:
        for label, index_name, id_field, id_value in es_targets:
            if not index_name:
                failures.append(f"{label}-index-unconfigured")
                continue
            success, message = await _delete_es_documents(
                elasticsearch_url,
                index_name,
                id_value,
                id_field,
            )
            if not success:
                logger.error("%s rollback failed for %s: %s", label, sensor_id, message)
                failures.append(label)
    return failures


async def _rollback_after_cancellation(**kwargs: Any) -> list[str]:
    """Run compensating cleanup despite request-task cancellation.

    The rollback is isolated in its own task and shielded from the cancellation
    already delivered to the request. A hard outer timeout prevents shutdown
    from waiting indefinitely on a downstream cleanup service.
    """

    rollback = asyncio.create_task(_rollback_search_post_processing(**kwargs))
    try:
        return await asyncio.wait_for(
            asyncio.shield(rollback),
            timeout=CANCELLATION_ROLLBACK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        rollback.cancel()
        await asyncio.gather(rollback, return_exceptions=True)
        return ["cancellation-rollback-timeout"]
    except Exception:
        logger.exception("Cancellation rollback raised unexpectedly")
        return ["cancellation-rollback-error"]


async def _run_rtvi_embedding(
    *,
    rtvi_embed_base_url: str,
    sensor_id: str,
    vst_url: str,
    vst_file_path: str,
    rtvi_embed_model: str,
    rtvi_embed_chunk_duration: int,
    start_timestamp: str,
    timeout_seconds: float = DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS,
) -> int:
    """POST ``/v1/generate_video_embeddings``. Returns ``total_chunks_processed``.

    The call is synchronous on the RTVI-Embed side — it blocks until the
    generation completes (up to the 600s client timeout). Any non-200 raises
    ``HTTPException(502)`` so the caller can surface the failure.
    """
    rtvi_embed_url = rtvi_embed_base_url.rstrip("/")
    embedding_url = f"{rtvi_embed_url}/v1/generate_video_embeddings"
    parsed_vst = urllib.parse.urlparse(f"http://{vst_url}" if "://" not in vst_url else vst_url)
    if not parsed_vst.hostname:
        raise HTTPException(status_code=500, detail=f"Invalid vst_url format: {vst_url}")
    translated_video_url = rewrite_url_host(vst_file_path, parsed_vst.hostname)
    logger.info(f"Using internal VST URL for RTVI: {translated_video_url}")

    embed_request = {
        "url": translated_video_url,
        "id": sensor_id,
        "model": rtvi_embed_model,
        "creation_time": start_timestamp,
        "chunk_duration": rtvi_embed_chunk_duration,
    }

    logger.info(f"Calling RTVI Embedding API: POST {embedding_url}")

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        with TimeMeasure("video_ingest: generate embeddings (RTVI)"):
            response = await client.post(
                embedding_url,
                json=embed_request,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    # SDR routing key — same rationale as RTVI-CV.
                    "x-stream-id": sensor_id,
                },
            )

        if response.status_code != 200:
            error_msg = f"Embedding generation failed with status {response.status_code}: {response.text}"
            logger.error(error_msg)
            raise HTTPException(status_code=502, detail=f"Embedding generation failed: {error_msg}")

        result = response.json()
        logger.info("RTVI Embedding generation successful")
        # `usage.total_chunks_processed` is the server-side count; coerce
        # explicitly so mypy keeps the helper's int return type intact.
        chunks_processed = int(result.get("usage", {}).get("total_chunks_processed", 0) or 0)
        if chunks_processed <= 0:
            raise HTTPException(status_code=502, detail="Embedding generation failed: no chunks processed")
        return chunks_processed


async def _run_post_upload_processing(
    camera_name: str,
    sensor_id: str,
    filename: str,
    vst_url: str,
    rtvi_embed_base_url: str,
    rtvi_cv_base_url: str = "",
    elasticsearch_url: str = "",
    rtvi_embed_es_index: str = "mdx-embed-filtered-2025-01-01",
    rtvi_embed_model: str = "cosmos-embed1-448p",
    rtvi_embed_chunk_duration: int = 5,
    disable_audio: bool = True,
    rtvi_cv_timeout_seconds: float = DEFAULT_RTVI_CV_TIMEOUT_SECONDS,
    rtvi_embed_timeout_seconds: float = DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS,
    vst_storage_timeout_seconds: float = DEFAULT_VST_STORAGE_TIMEOUT_SECONDS,
    analysis_profile_id: str = SEMANTIC_PROFILE_ID,
) -> VideoIngestResponse:
    """
    Run post-upload processing: get timeline, get video URL, add to RTVI-CV, generate embeddings.

    Called from the universal ``POST /api/v1/videos/{sensor_id}/complete``
    handler after the UI has uploaded chunks directly to VST.

    Args:
        camera_name: Identifier sent as RTVI-CV ``camera_name``. Callers should pass
            the filename without extension so the value is stable regardless of
            which upload path was used. Note this is distinct from ``sensor_id``;
            the returned ``VideoIngestResponse.sensor_id`` mirrors ``sensor_id``,
            not ``camera_name``.
        sensor_id: VST sensor id returned by VST after upload. Used for timeline
            lookup, storage URL resolution, and as ``VideoIngestResponse.sensor_id``
            in the response.
        filename: Original filename (with extension). Used only in the human-
            readable response message.
    """
    start_timestamp = "2025-01-01T00:00:00.000Z"

    # Resolve the name from VST's allocated sensor identity rather than trusting
    # the caller-forwarded filename. Behavior/raw indices are keyed by this
    # name, so compensating cleanup must never use an unproved caller scope.
    try:
        authoritative_camera_name = await get_sensor_id_from_stream_id(sensor_id, vst_url)
    except Exception as exc:
        logger.error("Could not resolve VST sensor name for %s: %s", sensor_id, exc)
        raise HTTPException(status_code=502, detail="VST sensor lookup failed") from exc
    if not authoritative_camera_name:
        raise HTTPException(status_code=502, detail="VST sensor lookup failed: empty sensor name")
    if authoritative_camera_name != camera_name:
        logger.info("Using VST-authoritative camera name for sensor %s", sensor_id)
    camera_name = authoritative_camera_name

    # Get timeline
    try:
        with TimeMeasure("video_ingest: get timeline from VST"):
            timeline_start_time, timeline_end_time = await get_timeline(sensor_id, vst_url)
    except VSTError as e:
        logger.error("Timelines API failed for stream %s: %s", sensor_id, e)
        raise HTTPException(status_code=502, detail=f"Timelines API failed: {e}") from e

    if not timeline_start_time or not timeline_end_time:
        error_msg = f"No valid timeline for stream {sensor_id}"
        logger.error(error_msg)
        raise HTTPException(status_code=502, detail=error_msg)

    logger.info(
        "Timeline for stream %s: start=%s, end=%s",
        sensor_id,
        timeline_start_time,
        timeline_end_time,
    )

    # Get video URL via storage API
    storage_url = f"{vst_url}/vst/api/v1/storage/file/{urllib.parse.quote(sensor_id, safe='')}/url"
    storage_params = {
        "startTime": timeline_start_time,
        "endTime": timeline_end_time,
        "container": "mp4",
        "configuration": json.dumps({"disableAudio": disable_audio}),
    }
    logger.info(f"Calling Storage API: GET {storage_url}")

    try:
        async with httpx.AsyncClient(timeout=vst_storage_timeout_seconds) as client:
            with TimeMeasure("video_ingest: get storage URL from VST"):
                storage_response = await client.get(storage_url, params=storage_params)

            if storage_response.status_code != 200:
                error_msg = f"Storage API failed with status {storage_response.status_code}: {storage_response.text}"
                logger.error(error_msg)
                raise HTTPException(status_code=502, detail=f"Storage API failed: {error_msg}")

            try:
                storage_result = storage_response.json()
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail="Storage API response invalid: malformed JSON") from exc
            vst_file_path = storage_result.get("videoUrl") if isinstance(storage_result, dict) else None
            if not vst_file_path:
                error_msg = f"Storage API response missing 'videoUrl' field: {storage_result}"
                logger.error(error_msg)
                raise HTTPException(status_code=502, detail=f"Storage API response invalid: {error_msg}")

            logger.info(f"VST video URL obtained: {vst_file_path}")
    except httpx.RequestError as exc:
        logger.error("VST storage request failed for %s: %s", sensor_id, exc)
        raise HTTPException(status_code=502, detail="Storage API request failed") from exc

    # Apply downstream writes in dependency order. If CV registration succeeds
    # but embedding fails, attempt to remove that registration and the
    # sensor-scoped documents already visible at rollback time before surfacing
    # the failure. Delayed pipeline writes still require the bounded
    # post-rollback absence check in the exact runtime qualification.
    parsed_cv = _parse_optional_http_url(rtvi_cv_base_url)
    parsed_embed = _parse_optional_http_url(rtvi_embed_base_url)
    if rtvi_cv_base_url and parsed_cv is None:
        raise HTTPException(status_code=502, detail="RTVI-CV configuration is invalid")
    if rtvi_embed_base_url and parsed_embed is None:
        raise HTTPException(status_code=502, detail="RTVI Embed configuration is invalid")
    cv_registered = False
    if parsed_cv is not None:
        try:
            await _register_with_rtvi_cv(
                rtvi_cv_base_url=rtvi_cv_base_url,
                sensor_id=sensor_id,
                camera_name=camera_name,
                vst_file_path=vst_file_path,
                start_timestamp=start_timestamp,
                timeout_seconds=rtvi_cv_timeout_seconds,
            )
        except asyncio.CancelledError:
            rollback_failures = await _rollback_after_cancellation(
                sensor_id=sensor_id,
                camera_name=camera_name,
                rtvi_cv_base_url=rtvi_cv_base_url,
                cv_may_be_registered=True,
                embedding_may_have_written=False,
                elasticsearch_url=elasticsearch_url,
                rtvi_embed_es_index=rtvi_embed_es_index,
                rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
            )
            if rollback_failures:
                logger.error(
                    "RTVI-CV cancellation rollback incomplete for %s: %s",
                    sensor_id,
                    ", ".join(rollback_failures),
                )
            raise
        except Exception as exc:
            rollback_failures = await _rollback_search_post_processing(
                sensor_id=sensor_id,
                camera_name=camera_name,
                rtvi_cv_base_url=rtvi_cv_base_url,
                cv_may_be_registered=True,
                embedding_may_have_written=False,
                elasticsearch_url=elasticsearch_url,
                rtvi_embed_es_index=rtvi_embed_es_index,
                rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
            )
            if rollback_failures:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "RTVI-CV add failed and downstream rollback was incomplete: " + ", ".join(rollback_failures)
                    ),
                ) from exc
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=502, detail="RTVI-CV add failed: request error") from exc
        cv_registered = True
    else:
        logger.info("RTVI-CV not configured, skipping")

    chunks_processed = 0
    if parsed_embed is not None:
        try:
            chunks_processed = await _run_rtvi_embedding(
                rtvi_embed_base_url=rtvi_embed_base_url,
                sensor_id=sensor_id,
                vst_url=vst_url,
                vst_file_path=vst_file_path,
                rtvi_embed_model=rtvi_embed_model,
                rtvi_embed_chunk_duration=rtvi_embed_chunk_duration,
                start_timestamp=start_timestamp,
                timeout_seconds=rtvi_embed_timeout_seconds,
            )
        except asyncio.CancelledError:
            rollback_failures = await _rollback_after_cancellation(
                sensor_id=sensor_id,
                camera_name=camera_name,
                rtvi_cv_base_url=rtvi_cv_base_url,
                cv_may_be_registered=cv_registered,
                embedding_may_have_written=True,
                elasticsearch_url=elasticsearch_url,
                rtvi_embed_es_index=rtvi_embed_es_index,
                rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
            )
            if rollback_failures:
                logger.error(
                    "Embedding cancellation rollback incomplete for %s: %s",
                    sensor_id,
                    ", ".join(rollback_failures),
                )
            raise
        except Exception as exc:
            rollback_failures = await _rollback_search_post_processing(
                sensor_id=sensor_id,
                camera_name=camera_name,
                rtvi_cv_base_url=rtvi_cv_base_url,
                cv_may_be_registered=cv_registered,
                embedding_may_have_written=True,
                elasticsearch_url=elasticsearch_url,
                rtvi_embed_es_index=rtvi_embed_es_index,
                rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
            )
            if rollback_failures:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Embedding generation failed and downstream rollback was incomplete: "
                        + ", ".join(rollback_failures)
                    ),
                ) from exc
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=502,
                detail="Embedding generation failed: request error",
            ) from exc
    else:
        logger.info("RTVI Embed not configured, skipping embedding generation")

    message = (
        f"Video {filename} successfully uploaded to VST and embeddings generated"
        if parsed_embed is not None
        else f"Video {filename} successfully uploaded to VST"
    )
    return VideoIngestResponse(
        message=message,
        sensor_id=sensor_id,
        filename=filename,
        chunks_processed=chunks_processed,
        analysis_profile_id=analysis_profile_id,
    )


def create_video_upload_router(vst_external_url: str) -> APIRouter:
    """Build the ``POST /api/v1/videos`` router (upload-URL handshake)."""
    router = APIRouter()

    @router.post(
        "/api/v1/videos",
        response_model=VideoUploadUrlResponse,
        summary="Get the VST upload URL for a new video",
        description=(
            "Returns the VST nvstreamer upload URL for the given filename. "
            "The UI POSTs file chunks directly to this URL, then calls "
            "``POST /api/v1/videos/{sensor_id}/complete`` to finalize."
        ),
        tags=["Video Ingest"],
    )
    async def get_upload_url(body: VideoUploadUrlInput) -> VideoUploadUrlResponse:
        filename = body.filename
        if re.search(r"\s", filename):
            raise HTTPException(
                status_code=400,
                detail="Filename cannot contain whitespace. Please rename the file and try again.",
            )

        # VST API is reachable at `/vst/api/...` via haproxy ingress; this is the
        # same path Video Management uses (NEXT_PUBLIC_VST_API_URL already includes
        # `/vst/api`, so its chunked-upload URL also resolves to `/vst/api/v1/storage/file`).
        url = f"{vst_external_url.rstrip('/')}/vst/api/v1/storage/file"
        logger.info("POST /api/v1/videos -> %s (filename=%s)", url, filename)
        return VideoUploadUrlResponse(url=url)

    return router


def create_video_upload_complete_router(
    vst_internal_url: str,
    rtvi_embed_base_url: str = "",
    rtvi_cv_base_url: str = "",
    elasticsearch_url: str = "",
    rtvi_embed_es_index: str = "mdx-embed-filtered-2025-01-01",
    rtvi_embed_model: str = "cosmos-embed1-448p",
    rtvi_embed_chunk_duration: int = 5,
    disable_audio: bool = True,
    rtvi_cv_timeout_seconds: float = DEFAULT_RTVI_CV_TIMEOUT_SECONDS,
    rtvi_embed_timeout_seconds: float = DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS,
    vst_storage_timeout_seconds: float = DEFAULT_VST_STORAGE_TIMEOUT_SECONDS,
) -> APIRouter:
    """Build the universal ``POST /api/v1/videos/{sensor_id}/complete`` router.

    ``sensor_id`` is VST's sensor id, returned on the final-chunk response as
    ``sensorId``. The body is the rest of that VST response forwarded
    verbatim by the UI — we only read ``filename`` (for the response message
    and RTVI ``camera_name``); other fields are ignored.
    """
    router = APIRouter()
    detector_urls = tuple(
        dict.fromkeys(
            endpoint
            for candidate in ANALYSIS_PROFILES
            if candidate.detection_enabled
            and (endpoint := analysis_profile_endpoint(rtvi_cv_base_url, candidate.id))
        )
    )

    @router.post(
        "/api/v1/videos/{sensor_id}/complete",
        response_model=VideoIngestResponse,
        summary="Complete a chunked video upload",
        description=(
            "Universal completion endpoint. Called by the UI after the last chunk "
            "lands, with VST's sensor id as the path param. Runs timeline lookup "
            "→ storage URL resolution → optional RTVI-CV register → optional "
            "embedding generation. Each step skips gracefully if its backing "
            "service isn't configured, so this works across profiles; for search "
            "profiles the RTVI-CV/embedding hooks drive ingestion."
        ),
        tags=["Video Ingest"],
    )
    async def upload_complete(sensor_id: str, body: VideoUploadCompleteInput) -> VideoIngestResponse:
        sensor_id = _validate_sensor_id(sensor_id)
        profile = require_analysis_profile(body.analysis_profile_id)
        selected_rtvi_cv_url = analysis_profile_endpoint(rtvi_cv_base_url, profile.id)
        if profile.detection_enabled and not selected_rtvi_cv_url:
            raise HTTPException(
                status_code=503,
                detail=f"The {profile.name} detector is not configured on this VSS appliance",
            )
        try:
            claim_source_analysis_profile_capacity(sensor_id, profile.id)
        except AnalysisProfileCapacityError as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc
        set_source_kind(sensor_id, "recorded")
        # ``filename`` comes from the VST upload response the UI forwards. Fall
        # back to ``sensor_id`` when missing so RTVI-CV's camera_name is at
        # least populated (lookups by sensor id keep working either way).
        filename = body.filename or sensor_id
        camera_name = filename.rsplit(".", 1)[0] if "." in filename else filename

        try:
            return await _run_post_upload_processing(
                camera_name=camera_name,
                sensor_id=sensor_id,
                filename=filename,
                vst_url=vst_internal_url,
                rtvi_embed_base_url=rtvi_embed_base_url,
                rtvi_cv_base_url=selected_rtvi_cv_url,
                elasticsearch_url=elasticsearch_url,
                rtvi_embed_es_index=rtvi_embed_es_index,
                rtvi_embed_model=rtvi_embed_model,
                rtvi_embed_chunk_duration=rtvi_embed_chunk_duration,
                disable_audio=disable_audio,
                rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
                rtvi_embed_timeout_seconds=rtvi_embed_timeout_seconds,
                vst_storage_timeout_seconds=vst_storage_timeout_seconds,
                analysis_profile_id=profile.id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("/complete failed for %s: %s", sensor_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Post-processing failed: {exc}") from exc

    @router.post(
        "/api/v1/videos/{sensor_id}/analysis",
        response_model=RecordedAnalysisResponse,
        summary="Reprocess an existing recording with a source analysis profile",
        description=(
            "Preserves the uploaded media and semantic-search index, removes stale "
            "detector-derived evidence, and reruns the recording through exactly one "
            "compatible VSS-owned DeepStream worker."
        ),
        tags=["Video Ingest"],
    )
    async def reprocess_recording(
        sensor_id: str,
        body: RecordedAnalysisRequest,
    ) -> RecordedAnalysisResponse:
        sensor_id = _validate_sensor_id(sensor_id)
        try:
            profile = require_analysis_profile(body.analysis_profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        selected_rtvi_cv_url = analysis_profile_endpoint(rtvi_cv_base_url, profile.id)
        if profile.detection_enabled and not selected_rtvi_cv_url:
            raise HTTPException(
                status_code=503,
                detail=f"The {profile.name} detector is not configured on this VSS appliance",
            )

        try:
            source_name = await get_sensor_id_from_stream_id(sensor_id, vst_internal_url)
        except Exception as exc:
            logger.error("Could not resolve recording %s for reprocessing", sensor_id, exc_info=True)
            raise HTTPException(status_code=502, detail="The recording could not be verified in VST") from exc
        if not source_name:
            raise HTTPException(status_code=404, detail="The recording no longer exists in VST")
        try:
            capacity_reservation = reserve_analysis_profile_capacity(
                profile.id,
                source_id=sensor_id,
            )
        except AnalysisProfileCapacityError as exc:
            raise HTTPException(status_code=409, detail=exc.detail) from exc

        try:
            # VST exposes uploaded MP4 playback through an RTSP URL too. Persist
            # the source kind before touching detector workers so the concurrent
            # live-camera reconciler can never claim this replay mid-transaction.
            set_source_kind(sensor_id, "recorded")

            previous_profile_id = get_source_analysis_profile(sensor_id)
            previous_profile = require_analysis_profile(previous_profile_id)
            if previous_profile.detection_enabled and not elasticsearch_url:
                raise HTTPException(
                    status_code=503,
                    detail="Detector-derived evidence cannot be safely replaced because Elasticsearch is unavailable",
                )

            # First stop every detector worker so none can publish new records
            # while the prior model's exact source-scoped output is being removed.
            async with httpx.AsyncClient(timeout=rtvi_cv_timeout_seconds) as client:
                removal_failures: list[str] = []
                for endpoint in detector_urls:
                    removed, message = await _remove_recording_from_detector(
                        client,
                        endpoint,
                        sensor_id,
                        source_name,
                    )
                    if not removed:
                        removal_failures.append(message)
            if removal_failures:
                raise HTTPException(
                    status_code=502,
                    detail="The previous detector could not be stopped; the recording was not reprocessed",
                )

            generated_data_deleted = 0
            if elasticsearch_url:
                cleanup = await _delete_detector_generated_data(
                    elasticsearch_url,
                    sensor_id,
                    source_name,
                )
                if not cleanup.success:
                    raise HTTPException(
                        status_code=502,
                        detail="Prior detector evidence could not be fully cleared; retry reprocessing",
                    )
                generated_data_deleted = cleanup.total_deleted

            if profile.detection_enabled:
                await _run_post_upload_processing(
                    camera_name=source_name.rsplit(".", 1)[0],
                    sensor_id=sensor_id,
                    filename=source_name,
                    vst_url=vst_internal_url,
                    rtvi_embed_base_url="",
                    rtvi_cv_base_url=selected_rtvi_cv_url,
                    disable_audio=disable_audio,
                    rtvi_cv_timeout_seconds=rtvi_cv_timeout_seconds,
                    rtvi_embed_timeout_seconds=rtvi_embed_timeout_seconds,
                    vst_storage_timeout_seconds=vst_storage_timeout_seconds,
                    analysis_profile_id=profile.id,
                )

            # Persist only after every destructive and runtime step succeeded.
            # The reservation made the target worker unavailable to parallel
            # reprocessing requests, so this commit cannot overbook it.
            try:
                commit_analysis_profile_capacity_reservation(capacity_reservation, sensor_id)
            except AnalysisProfileCapacityError as exc:
                raise HTTPException(status_code=409, detail=exc.detail) from exc
            return RecordedAnalysisResponse(
                analysis_profile_id=profile.id,
                previous_profile_id=previous_profile_id,
                detection_enabled=profile.detection_enabled,
                generated_data_deleted=generated_data_deleted,
                message=(
                    f"{profile.name} is reprocessing this recording"
                    if profile.detection_enabled
                    else "Detector analytics were cleared; semantic search and Vision Analyst remain available"
                ),
                sensor_id=sensor_id,
            )
        finally:
            release_analysis_profile_capacity_reservation(capacity_reservation)

    return router


def register_video_upload(app: "FastAPI", config: "Any") -> None:
    """Register ``POST /api/v1/videos`` — the upload-URL handshake.

    Returns a VST nvstreamer URL the browser POSTs chunks to. Skipped (with
    a warning) when VST isn't configured.
    """
    try:
        cfg = _resolve_video_upload_config(config)
        if cfg is None:
            logger.warning("VST_INTERNAL_URL not set — skipping POST /api/v1/videos")
            return

        app.include_router(create_video_upload_router(vst_external_url=cfg.vst_external_url))
        logger.info("Registered POST /api/v1/videos")
    except Exception as exc:
        logger.error("Failed to register video upload-URL route: %s", exc, exc_info=True)
        raise


def register_video_upload_complete(app: "FastAPI", config: "Any") -> None:
    """Register ``POST /api/v1/videos/{sensor_id}/complete``.

    Embedding and RTVI-CV URLs are passed through when configured and the
    handler self-skips downstream calls when they aren't — so base/alerts/lvs
    profiles get a working completion path that just doesn't register
    embeddings.
    """
    try:
        cfg = _resolve_video_upload_config(config)
        if cfg is None:
            logger.warning("VST_INTERNAL_URL not set — skipping POST /api/v1/videos/{sensor_id}/complete")
            return

        app.include_router(
            create_video_upload_complete_router(
                vst_internal_url=cfg.vst_internal_url,
                rtvi_embed_base_url=cfg.rtvi_embed_base_url,
                rtvi_cv_base_url=cfg.rtvi_cv_base_url,
                elasticsearch_url=cfg.elasticsearch_url,
                rtvi_embed_es_index=cfg.rtvi_embed_es_index,
                rtvi_embed_model=cfg.rtvi_embed_model,
                rtvi_embed_chunk_duration=cfg.rtvi_embed_chunk_duration,
                disable_audio=cfg.disable_audio,
                rtvi_cv_timeout_seconds=cfg.rtvi_cv_timeout_seconds,
                rtvi_embed_timeout_seconds=cfg.rtvi_embed_timeout_seconds,
                vst_storage_timeout_seconds=cfg.vst_storage_timeout_seconds,
            )
        )
        logger.info("Registered POST /api/v1/videos/{sensor_id}/complete")
    except Exception as exc:
        logger.error("Failed to register video upload-complete route: %s", exc, exc_info=True)
        raise
