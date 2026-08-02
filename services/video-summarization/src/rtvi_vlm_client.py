# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
RTVI-VLM HTTP client.

Duck-types the VlmPipeline interface used by ViaStreamHandler, delegating
video chunking, frame extraction, and VLM inference to an external RTVI-VLM
microservice via REST API.
"""

import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Optional

import requests
from pydantic import BaseModel, Field

from via_logger import logger
from vlm_pipeline.vlm_types import VlmModelInfo


class RtviGenerateCaptionsRequest(BaseModel):
    """Mirrors RTVI-VLM's VlmQuery for POST /v1/generate_captions.

    Use model_dump(exclude_none=True) to build the JSON payload, which
    automatically omits unset optional fields.
    """

    id: str
    prompt: str = ""
    model: str = ""
    stream: bool = True
    chunk_duration: int = 0  # RTVI default: 0 (no chunking)
    chunk_overlap_duration: int = 0
    enable_reasoning: bool = False
    enable_audio: bool = False
    url: Optional[str] = None
    media_type: Optional[str] = None
    creation_time: Optional[str] = None
    system_prompt: Optional[str] = None
    api_type: Optional[str] = None
    max_tokens: Optional[int] = None
    min_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[float] = None
    seed: Optional[int] = None
    ignore_eos: Optional[bool] = None
    response_format: Optional[dict] = None
    stream_options: Optional[dict] = None
    media_info: Optional[dict] = None
    vlm_input_width: Optional[int] = Field(default=None, ge=0)
    vlm_input_height: Optional[int] = Field(default=None, ge=0)
    num_frames_per_second_or_fixed_frames_chunk: Optional[float] = None
    use_fps_for_chunking: Optional[bool] = None
    alert_category: Optional[str] = None
    mm_processor_kwargs: Optional[dict] = None
    # NOTE: collection_name and static_info fields used to live here to feed
    # downstream Logstash. They were removed because rtvi-microservices uses
    # CommonBaseModel(extra="forbid") on VlmQuery — sending unknown fields
    # would 422 the request. Logstash now derives the collection_name from
    # info[streamId] (= chunk.streamId = asset UUID when stream/add is
    # called with camera_id="") and the new live-stream Kafka path is fully
    # operator-driven via RTVI's auto-inference, not LVS.


class RtviError(Exception):
    """Error from RTVI-VLM with HTTP status code and error details."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"RTVI {status_code} {code}: {message}")


RTVI_HEALTH_TIMEOUT = 10
RTVI_HEALTH_RETRIES = int(os.environ.get("RTVI_HEALTH_RETRIES", 30))
RTVI_HEALTH_RETRY_INTERVAL = int(os.environ.get("RTVI_HEALTH_RETRY_INTERVAL", 5))


@dataclass
class _ActiveCaptionRequest:
    owner_id: str
    routing_id: str
    request_id: str | None = None
    response: object | None = None
    cancelled: bool = False
    abort_started: bool = False
    terminal_event: Event = field(default_factory=Event)


class RtviVlmClient:
    """HTTP client for RTVI-VLM microservice."""

    def __init__(self, args):
        self._base_url = os.environ.get("RTVI_VLM_URL", "http://localhost:8000")
        self._session = requests.Session()
        self._model_info = VlmModelInfo()
        self._live_stream_threads = {}
        self._live_stream_stop_events = {}
        self._rtvi_stream_id_map = {}
        self._active_caption_requests: dict[str, _ActiveCaptionRequest] = {}
        self._active_caption_requests_lock = Lock()
        self._cancelled_caption_owners: OrderedDict[str, float] = OrderedDict()

        # Health check — fail fast if RTVI-VLM is not reachable
        self._wait_for_ready()

        # Fetch model info from RTVI-VLM
        self._refresh_model_info()
        if not self._model_info.id:
            raise ConnectionError(
                f"RTVI-VLM at {self._base_url} is ready but returned no model info. "
                "Check that a VLM model is loaded on the RTVI-VLM service."
            )

        logger.info(
            "RtviVlmClient initialized, base_url=%s, model=%s",
            self._base_url,
            self._model_info.id,
        )

    def _wait_for_ready(self):
        """Check RTVI-VLM readiness, retry with backoff, fail if unreachable."""
        for attempt in range(1, RTVI_HEALTH_RETRIES + 1):
            try:
                resp = self._session.get(
                    f"{self._base_url}/v1/health/ready",
                    timeout=RTVI_HEALTH_TIMEOUT,
                )
                if resp.status_code == 200:
                    logger.info("RTVI-VLM health check passed at %s", self._base_url)
                    return
                elif resp.status_code == 503:
                    logger.warning(
                        "RTVI-VLM at %s not ready (503), attempt %d/%d",
                        self._base_url,
                        attempt,
                        RTVI_HEALTH_RETRIES,
                    )
                else:
                    logger.warning(
                        "RTVI-VLM health check returned %d, attempt %d/%d",
                        resp.status_code,
                        attempt,
                        RTVI_HEALTH_RETRIES,
                    )
            except requests.ConnectionError:
                logger.warning(
                    "Cannot connect to RTVI-VLM at %s, attempt %d/%d",
                    self._base_url,
                    attempt,
                    RTVI_HEALTH_RETRIES,
                )
            except Exception as ex:
                logger.warning(
                    "RTVI-VLM health check error: %s, attempt %d/%d",
                    ex,
                    attempt,
                    RTVI_HEALTH_RETRIES,
                )

            if attempt < RTVI_HEALTH_RETRIES:
                time.sleep(RTVI_HEALTH_RETRY_INTERVAL)

        raise ConnectionError(
            f"RTVI-VLM at {self._base_url} is not reachable after "
            f"{RTVI_HEALTH_RETRIES} attempts. Ensure RTVI-VLM is running "
            f"and RTVI_VLM_URL is correct."
        )

    def check_health(self, timeout: int = 3) -> bool:
        """Lightweight on-demand health probe for RTVI-VLM."""
        try:
            resp = self._session.get(f"{self._base_url}/v1/health/ready", timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def _refresh_model_info(self):
        """Fetch model info from RTVI-VLM GET /v1/models and cache it."""
        resp = self._session.get(f"{self._base_url}/v1/models", timeout=RTVI_HEALTH_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        if models:
            model = models[0]
            self._model_info.id = model.get("id", "")
            self._model_info.created = model.get("created", 0)
            self._model_info.owned_by = model.get("owned_by", "")
            self._model_info.api_type = model.get("api_type", "")
        logger.info(
            "RTVI-VLM model info: id=%s, api_type=%s",
            self._model_info.id,
            self._model_info.api_type,
        )

    def _raise_rtvi_error(self, operation: str, resp, error_text=None):
        """Parse RTVI error response and raise RtviError."""
        status_code = resp.status_code
        body = error_text if error_text is not None else resp.text
        try:
            error_json = json.loads(body)
            error_code = error_json.get("code", "UnknownError")
            error_message = error_json.get("message", body)
        except Exception:
            error_code = "UnknownError"
            error_message = body
        logger.error(
            "RTVI %s failed: status=%d, code=%s, message=%s",
            operation,
            status_code,
            error_code,
            error_message,
        )
        raise RtviError(status_code, error_code, error_message)

    def get_models_info(self):
        """Return cached model info. Refresh if not yet populated."""
        if not self._model_info.id:
            self._refresh_model_info()
        return self._model_info

    def upload_file(
        self,
        file_obj_or_path,
        purpose="vision",
        media_type="video",
        creation_time=None,
        file_id=None,
        sensor_name="",
        upload_filename=None,
    ):
        """Upload a file to RTVI-VLM via POST /v1/files (multipart).

        Accepts either a file object (UploadFile) or a local file path.
        Returns the RTVI response dict containing the remote asset ID.
        """
        data = {
            "purpose": purpose.value if hasattr(purpose, "value") else purpose,
            "media_type": media_type.value if hasattr(media_type, "value") else media_type,
        }
        if creation_time:
            data["creation_time"] = creation_time
        if file_id:
            data["id"] = str(file_id)
        if sensor_name:
            data["sensor_name"] = sensor_name

        # Sticky routing: file upload must land on the same RTVI replica that
        # later /v1/generate_captions calls for this asset will hit. NGINX
        # Ingress hashes by `x-stream-id` (see METLVSMS-500).
        sticky_headers = {"x-stream-id": str(file_id)} if file_id else {}
        if file_id:
            logger.info("RTVI upload_file: x-stream-id=%s", file_id)

        if hasattr(file_obj_or_path, "read"):
            # UploadFile-like object
            fname = upload_filename or getattr(file_obj_or_path, "filename", "upload")
            resp = self._session.post(
                f"{self._base_url}/v1/files",
                files={"file": (fname, file_obj_or_path)},
                data=data,
                timeout=300,
                headers=sticky_headers,
            )
        elif isinstance(file_obj_or_path, str) and file_obj_or_path.startswith(
            ("http://", "https://", "s3://")
        ):
            # URL string — RTVI fetches server-side via the `url` form field.
            url = file_obj_or_path
            fname = os.path.basename(url.split("?", 1)[0]) or "upload"
            resp = self._session.post(
                f"{self._base_url}/v1/files",
                data={**data, "url": url},
                timeout=300,
                headers=sticky_headers,
            )
        else:
            # Local file path
            fname = os.path.basename(file_obj_or_path)
            with open(file_obj_or_path, "rb") as f:
                resp = self._session.post(
                    f"{self._base_url}/v1/files",
                    files={"file": (fname, f)},
                    data=data,
                    timeout=300,
                    headers=sticky_headers,
                )

        if resp.status_code != 200:
            self._raise_rtvi_error("file upload", resp)
        result = resp.json()
        logger.info(
            "RTVI-VLM file uploaded: name=%s, rtvi_id=%s",
            fname,
            result.get("id"),
        )
        return result

    def list_files(self, purpose="vision"):
        """List files on RTVI-VLM via GET /v1/files."""
        resp = self._session.get(
            f"{self._base_url}/v1/files",
            params={"purpose": purpose},
            timeout=RTVI_HEALTH_TIMEOUT,
        )
        if resp.status_code != 200:
            self._raise_rtvi_error("list files", resp)
        return resp.json()

    def get_file_info(self, file_id):
        """Get file metadata from RTVI-VLM via GET /v1/files/{file_id}.

        Sticky-routed so the request reaches the same RTVI replica that owns
        the asset.
        """
        logger.info("RTVI get_file_info: x-stream-id=%s", file_id)
        resp = self._session.get(
            f"{self._base_url}/v1/files/{file_id}",
            timeout=RTVI_HEALTH_TIMEOUT,
            headers={"x-stream-id": str(file_id)},
        )
        if resp.status_code != 200:
            self._raise_rtvi_error("get file info", resp)
        return resp.json()

    def delete_file(self, file_id):
        """Delete a file on RTVI-VLM via DELETE /v1/files/{file_id}.

        Sticky-routed via `x-stream-id: <file_id>` so the delete hits the
        same RTVI replica that owns the asset.
        """
        logger.info("RTVI delete_file: x-stream-id=%s", file_id)
        resp = self._session.delete(
            f"{self._base_url}/v1/files/{file_id}",
            timeout=RTVI_HEALTH_TIMEOUT,
            headers={"x-stream-id": str(file_id)},
        )
        if resp.status_code != 200:
            self._raise_rtvi_error("delete file", resp)
        return resp.json()

    def _build_generate_captions_request(self, **kwargs) -> RtviGenerateCaptionsRequest:
        """Build a validated RtviGenerateCaptionsRequest from kwargs.

        file_id must always be provided — comes from RequestSource.source_id
        (synthetic UUID for files, source_id for live streams). The API layer
        is responsible for generating it via RequestSource.for_file() or
        RequestSource.for_stream().
        """
        file_id = kwargs.pop("file_id", None)
        if not file_id:
            raise ValueError("file_id is required — must come from RequestSource.source_id")

        # Remap file_id→id and apply defaults for model
        kwargs["id"] = file_id
        kwargs["model"] = kwargs.get("model") or self._model_info.id
        kwargs["stream"] = True

        return RtviGenerateCaptionsRequest(**kwargs)

    def generate_captions_stream(self, **kwargs):
        """Call RTVI /v1/generate_captions with stream=true, yield parsed SSE chunks.

        Each yielded dict has the shape of a VlmCaptionsCompletionResponse:
        {id, model, created, media_info, chunk_responses: [{chunk_id, start_time, end_time, content, ...}]}
        Terminates when [DONE] is received.
        """
        owner_id = kwargs.pop("owner_id", None)
        req = self._build_generate_captions_request(**kwargs)
        payload = req.model_dump(exclude_none=True)
        lease = (
            self._begin_caption_request(str(owner_id), str(req.id))
            if owner_id is not None
            else None
        )

        logger.info(
            "RTVI generate_captions_stream: url=%s, id=%s, model=%s, chunk_duration=%d",
            req.url,
            req.id,
            req.model,
            req.chunk_duration,
        )
        logger.info("RTVI generate_captions_stream: x-stream-id=%s", req.id)

        try:
            resp = self._session.post(
                f"{self._base_url}/v1/generate_captions",
                json=payload,
                stream=True,
                timeout=600,
                headers={"x-stream-id": str(req.id)},
            )
        except BaseException:
            if lease is not None:
                self._finish_caption_request(lease)
            raise
        if resp.status_code != 200:
            try:
                self._raise_rtvi_error("generate_captions", resp)
            finally:
                resp.close()
                if lease is not None:
                    self._finish_caption_request(lease)

        request_id = resp.headers.get("x-request-id")
        if lease is not None:
            if not request_id:
                resp.close()
                self._finish_caption_request(lease)
                raise RtviError(
                    502,
                    "MissingRequestId",
                    "RTVI streaming response did not identify its exact request",
                )
            if self._register_caption_response(lease, str(request_id), resp):
                self._abort_caption_request(lease)
                self._finish_caption_request(lease)
                return

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith(":") or line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                else:
                    logger.debug("RTVI SSE unexpected line: %s", line)
                    continue

                if not data or data == "ping" or data == ": ping":
                    continue
                if data == "[DONE]":
                    logger.info("RTVI generate_captions_stream: received [DONE]")
                    return

                try:
                    yield json.loads(data)
                except Exception as e:
                    logger.warning("RTVI SSE parse error: %s, line: %s", e, data)

            logger.info("RTVI generate_captions_stream: stream ended")
        finally:
            if lease is None:
                resp.close()
            else:
                self._finish_caption_request(lease)

    def _prune_cancel_tombstones_locked(self) -> None:
        cutoff = time.monotonic() - 600
        while self._cancelled_caption_owners:
            owner_id, created = next(iter(self._cancelled_caption_owners.items()))
            if created >= cutoff and len(self._cancelled_caption_owners) <= 1024:
                break
            self._cancelled_caption_owners.pop(owner_id, None)

    def _begin_caption_request(
        self, owner_id: str, routing_id: str
    ) -> _ActiveCaptionRequest:
        if not owner_id:
            raise ValueError("owner_id must be nonempty")
        with self._active_caption_requests_lock:
            self._prune_cancel_tombstones_locked()
            if owner_id in self._active_caption_requests:
                raise ValueError(f"owner_id {owner_id} already has an active request")
            cancelled = self._cancelled_caption_owners.pop(owner_id, None) is not None
            lease = _ActiveCaptionRequest(owner_id, routing_id, cancelled=cancelled)
            self._active_caption_requests[owner_id] = lease
        return lease

    def _register_caption_response(
        self, lease: _ActiveCaptionRequest, request_id: str, response
    ) -> bool:
        """Attach the exact response and report whether cancellation won the race."""
        if not request_id:
            raise ValueError("request_id must be nonempty")
        with self._active_caption_requests_lock:
            if self._active_caption_requests.get(lease.owner_id) is not lease:
                raise RuntimeError("caption request ownership changed before registration")
            lease.request_id = request_id
            lease.response = response
            return lease.cancelled

    def _abort_caption_request(self, lease: _ActiveCaptionRequest) -> None:
        with self._active_caption_requests_lock:
            if lease.abort_started:
                waiter = lease.terminal_event
                abort_owner = False
            else:
                lease.abort_started = True
                waiter = lease.terminal_event
                abort_owner = True
        if not abort_owner:
            waiter.wait()
            return

        delete_response = None
        try:
            if lease.request_id is not None:
                delete_response = self._session.delete(
                    f"{self._base_url}/v1/generate_captions/requests/{lease.request_id}",
                    timeout=RTVI_HEALTH_TIMEOUT,
                    headers={"x-stream-id": lease.routing_id},
                )
                if delete_response.status_code not in (200, 404):
                    logger.warning(
                        "RTVI exact request abort returned status=%d owner_id=%s request_id=%s",
                        delete_response.status_code,
                        lease.owner_id,
                        lease.request_id,
                    )
        except Exception:
            logger.warning(
                "RTVI exact request abort failed owner_id=%s request_id=%s",
                lease.owner_id,
                lease.request_id,
                exc_info=True,
            )
        finally:
            if delete_response is not None:
                delete_response.close()
            if lease.response is not None:
                lease.response.close()
            waiter.set()

    def _finish_caption_request(self, lease: _ActiveCaptionRequest) -> None:
        """Close and unregister only the exact response identity owned by ``lease``."""
        with self._active_caption_requests_lock:
            if self._active_caption_requests.get(lease.owner_id) is lease:
                self._active_caption_requests.pop(lease.owner_id, None)
        if lease.response is not None:
            lease.response.close()
        lease.terminal_event.set()

    def abort_request(self, owner_id: str) -> bool:
        """Abort the exact active RTVI request registered to an LVS owner."""
        with self._active_caption_requests_lock:
            self._prune_cancel_tombstones_locked()
            lease = self._active_caption_requests.get(str(owner_id))
            if lease is None:
                if str(owner_id) in self._cancelled_caption_owners:
                    return False
                self._cancelled_caption_owners[str(owner_id)] = time.monotonic()
                self._prune_cancel_tombstones_locked()
                return True
            first_caller = not lease.cancelled
            lease.cancelled = True
            registered = lease.request_id is not None
        if registered:
            self._abort_caption_request(lease)
        else:
            # The POST owns request identity discovery.  Do not acknowledge
            # cancellation until it registers and performs the exact abort (or
            # fails and retires the lease in its exception path).
            lease.terminal_event.wait()
        return first_caller

    def cancel_request(
        self, request_id: str, reason: str = "downstream_disconnect"
    ) -> bool:
        """LVS-facing alias for owner-scoped exact RTVI request cancellation."""
        logger.info("Cancelling RTVI request owner=%s reason=%s", request_id, reason)
        return self.abort_request(request_id)

    def start_captions(self, **kwargs):
        """Fire-and-forget kickoff for RTVI live-stream captioning.

        Opens the SSE stream by POSTing to /v1/generate_captions, validates
        the HTTP status, then immediately closes the connection. RTVI keeps
        captioning in the background and publishes raw_events to Kafka
        regardless of SSE consumer state.

        Status codes accepted as success:
          * 200 OK       - fresh start OR RTVI reconnect to an existing
                           PROCESSING request for the same stream_id
                           (rtvi_vlm_server.py:744-773 reconnect branch).
          * 409 Conflict - "Another client is already connected to live
                           stream". RTVI's 3-second single-active-SSE-client
                           gate (rtvi_vlm_server.py:1904-1909). Captioning
                           is already running for this stream_id; the
                           duplicate trigger is a no-op on the data plane.

        Any other status raises RtviError.
        """
        req = self._build_generate_captions_request(**kwargs)
        payload = req.model_dump(exclude_none=True)

        logger.info(
            "RTVI start_captions (fire-and-forget): id=%s, model=%s, " "chunk_duration=%d",
            req.id,
            req.model,
            req.chunk_duration,
        )
        logger.info("RTVI start_captions: x-stream-id=%s", req.id)

        resp = self._session.post(
            f"{self._base_url}/v1/generate_captions",
            json=payload,
            stream=True,
            timeout=(5, 30),
            headers={"x-stream-id": str(req.id)},
        )
        try:
            if resp.status_code in (200, 409):
                if resp.status_code == 409:
                    logger.info(
                        "RTVI start_captions: 409 Conflict for stream_id=%s "
                        "- captioning already running, treating as no-op",
                        req.id,
                    )
                return
            error_text = resp.text
            self._raise_rtvi_error("start_captions", resp, error_text=error_text)
        finally:
            resp.close()

    def abort_chunks(self, source_id):
        pass

    def abort_chunks_done(self, source_id):
        pass

    def remove_live_stream(self, source_id):
        """No-op — RTVI manages stream lifecycle internally."""
        logger.info("remove_live_stream called for %s (no-op in RTVI mode)", source_id)

    def stop(self, force=False):
        with self._active_caption_requests_lock:
            leases = list(self._active_caption_requests.values())
            self._active_caption_requests.clear()
            self._cancelled_caption_owners.clear()
        for lease in leases:
            if lease.response is not None:
                lease.response.close()
            lease.terminal_event.set()
        self._session.close()
