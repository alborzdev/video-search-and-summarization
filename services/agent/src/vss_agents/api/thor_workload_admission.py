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

"""Agent-owned admission and exclusive leasing for Thor's local Cosmos lane."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger(__name__)

VisualWorkload = Literal["current_visual_question", "evidence_analysis"]


@dataclass(frozen=True, slots=True)
class CaptionSession:
    """The exact configuration needed to restore one suspended caption lane."""

    source_id: str
    events: tuple[str, ...]
    scenario: str


class ThorWorkloadAdmissionError(Exception):
    """A safe, structured refusal to run a local visual workload."""

    def __init__(self, status_code: Literal[409, 503], code: str, error: str, workload: VisualWorkload):
        super().__init__(error)
        self.status_code = status_code
        self.code = code
        self.error = error
        self.workload = workload

    def response_body(self) -> dict[str, object]:
        """Return the stable error envelope used by the UI admission proxy."""

        return {
            "admission": {
                "decision": "block",
                "reasonCode": self.code,
                "requiredAction": self.required_action,
                "workload": self.workload,
            },
            "code": self.code,
            "error": self.error,
        }

    @property
    def required_action(self) -> str:
        if self.status_code == 409:
            return "Remove the active live alert rule before requesting another visual workload."
        return "Wait for the local visual lane to become available and try again."


class ThorVisualWorkloadAdmission:
    """Serialize Agent visual work and yield live captions while it owns Cosmos.

    This boundary intentionally lives in the Agent rather than a UI process:
    HAProxy-exposed callers and same-origin UI callers therefore receive the
    same lease. The lock is process-local because one Thor Agent process owns
    the configured visual tools; deployment must not run multiple Agent workers
    against one local VLM without an external lease coordinator.
    """

    def __init__(
        self,
        rtvi_vlm_url: str | None = None,
        lvs_backend_url: str | None = None,
        history_directory: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self._rtvi_vlm_url = (
            rtvi_vlm_url or os.getenv("RTVI_VLM_URL") or os.getenv("RTVI_VLM_BASE_URL") or "http://127.0.0.1:8018"
        ).rstrip("/")
        self._lvs_backend_url = (lvs_backend_url or os.getenv("LVS_BACKEND_URL") or "http://127.0.0.1:38111").rstrip(
            "/"
        )
        directory = history_directory if history_directory is not None else os.getenv("VISION_HISTORY_DIR")
        self._history_directory = Path(directory) if directory else None
        self._model_name = model_name or os.getenv("LVS_VLM_MODEL") or os.getenv("VLM_NAME", "")
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def reserve(self, workload: VisualWorkload) -> AsyncIterator[None]:
        """Acquire the one local visual lane or fail without queuing hidden work."""

        if self._lock.locked():
            raise ThorWorkloadAdmissionError(
                503,
                "LOCAL_COSMOS_RESERVATION_ACTIVE",
                "Another visual workload is already using the local Cosmos lane.",
                workload,
            )
        await self._lock.acquire()
        suspended_sessions: list[CaptionSession] = []
        try:
            await self._ensure_vlm_ready(workload)
            await self._ensure_no_live_alert(workload)
            for session in await self._active_caption_sessions(workload):
                await self._suspend_captioning(session.source_id, workload)
                suspended_sessions.append(session)
            yield
        finally:
            try:
                await self._restore_captioning(suspended_sessions)
            finally:
                self._lock.release()

    async def _ensure_vlm_ready(self, workload: VisualWorkload) -> None:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self._rtvi_vlm_url}/v1/health/ready")
        except httpx.HTTPError as exc:
            raise ThorWorkloadAdmissionError(
                503,
                "VLM_STATUS_UNKNOWN",
                "Cosmos readiness could not be observed, so admission cannot safely claim capacity.",
                workload,
            ) from exc
        if not response.is_success:
            raise ThorWorkloadAdmissionError(
                503,
                "VLM_UNAVAILABLE",
                "The local Cosmos visual-reasoning service is not ready.",
                workload,
            )

    async def _active_caption_sessions(self, workload: VisualWorkload) -> list[CaptionSession]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self._rtvi_vlm_url}/v1/stream/get-stream-info")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ThorWorkloadAdmissionError(
                503,
                "LIVE_CAPTION_LANE_UNKNOWN",
                "Continuous-caption lane state could not be observed.",
                workload,
            ) from exc
        streams = payload.get("stream_list") if isinstance(payload, dict) else None
        if not isinstance(streams, list):
            raise ThorWorkloadAdmissionError(
                503,
                "LIVE_CAPTION_LANE_UNKNOWN",
                "Continuous-caption lane state could not be observed.",
                workload,
            )
        sessions: list[CaptionSession] = []
        seen_source_ids: set[str] = set()
        for stream in streams:
            if not isinstance(stream, dict) or not stream.get("inference_active"):
                continue
            source_id = str(stream.get("camera_id") or stream.get("asset_id") or "").strip()
            if not source_id or source_id in seen_source_ids:
                continue
            source_name = str(stream.get("camera_name") or source_id)
            sessions.append(self._caption_session(source_id, source_name))
            seen_source_ids.add(source_id)
        return sessions

    def _caption_session(self, source_id: str, source_name: str) -> CaptionSession:
        fallback = self._default_caption_session(source_id, source_name)
        if self._history_directory is None:
            return fallback

        # Source identifiers originate in the VLM stream registry, but never
        # allow one to escape the mounted history directory if that registry is
        # malformed or compromised.
        if Path(source_id).name != source_id:
            logger.warning("Ignoring an unsafe caption history source identifier")
            return fallback

        try:
            payload = json.loads((self._history_directory / f"{source_id}.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return fallback

        if not isinstance(payload, dict) or payload.get("sourceKind") != "live":
            return fallback
        scenario = payload.get("scenario")
        events = payload.get("events")
        if (
            not isinstance(scenario, str)
            or not scenario.strip()
            or not isinstance(events, list)
            or not events
            or not all(isinstance(event, str) and event.strip() for event in events)
        ):
            return fallback
        return CaptionSession(source_id=source_id, events=tuple(events), scenario=scenario)

    @staticmethod
    def _default_caption_session(source_id: str, source_name: str) -> CaptionSession:
        normalized_name = source_name.casefold()
        if any(term in normalized_name for term in ("traffic", "road", "intersection", "vehicle", "jaywalk")):
            return CaptionSession(
                source_id=source_id,
                events=(
                    "pedestrian crossing",
                    "stopped vehicle",
                    "near collision",
                    "unusual traffic activity",
                ),
                scenario="traffic monitoring",
            )
        if any(term in normalized_name for term in ("warehouse", "forklift", "loading", "dock", "aisle")):
            return CaptionSession(
                source_id=source_id,
                events=(
                    "person and vehicle proximity",
                    "restricted-zone entry",
                    "blocked aisle",
                    "unusual activity",
                ),
                scenario="warehouse monitoring",
            )
        return CaptionSession(
            source_id=source_id,
            events=("notable activity", "safety risk", "movement changes"),
            scenario="activity monitoring",
        )

    async def _ensure_no_live_alert(self, workload: VisualWorkload) -> None:
        if self._history_directory is None:
            return
        try:
            entries = list(self._history_directory.iterdir())
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ThorWorkloadAdmissionError(
                503,
                "LIVE_ALERT_RESERVATION_UNKNOWN",
                "Local live-alert reservation state could not be read.",
                workload,
            ) from exc
        for path in entries:
            if not path.name.startswith(".live-alert-") or path.suffix != ".json":
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ThorWorkloadAdmissionError(
                    503,
                    "LIVE_ALERT_RESERVATION_UNKNOWN",
                    "Local live-alert reservation state could not be read.",
                    workload,
                ) from exc
            if isinstance(value, dict) and str(value.get("sourceId", "")).strip():
                raise ThorWorkloadAdmissionError(
                    409,
                    "LIVE_ALERT_RESERVATION_ACTIVE",
                    "A continuous live VLM alert currently owns the exclusive Cosmos lane.",
                    workload,
                )

    async def _suspend_captioning(self, source_id: str, workload: VisualWorkload) -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(f"{self._rtvi_vlm_url}/v1/generate_captions/{quote(source_id, safe='')}")
        except httpx.HTTPError as exc:
            raise ThorWorkloadAdmissionError(
                503,
                "LIVE_CAPTION_LANE_ACTIVE",
                "Cosmos could not reserve the local visual model for this workload.",
                workload,
            ) from exc
        if response.status_code not in (200, 204, 404):
            raise ThorWorkloadAdmissionError(
                503,
                "LIVE_CAPTION_LANE_ACTIVE",
                "Cosmos could not reserve the local visual model for this workload.",
                workload,
            )

    async def _restore_captioning(self, sessions: list[CaptionSession]) -> None:
        for session in sessions:
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    response = await client.post(
                        f"{self._lvs_backend_url}/v1/generate_captions",
                        json={
                            "enable_qa": True,
                            "events": list(session.events),
                            "id": session.source_id,
                            "model": self._model_name,
                            "objects_of_interest": [],
                            "scenario": session.scenario,
                        },
                    )
                if not response.is_success:
                    logger.error(
                        "Failed to restore live captioning for %s: HTTP %s",
                        session.source_id,
                        response.status_code,
                    )
            except httpx.HTTPError:
                logger.exception("Failed to restore live captioning for %s", session.source_id)
