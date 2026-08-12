#!/usr/bin/env python3
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
On-demand verification service aligned with DirectMedia handler flow.

Accepts the same Incident payload that DirectMedia receives from Kafka.
Prompts are resolved via PromptManager.get_prompts_for_message() (Redis-backed).
VLM processing and sink publishing are delegated to DirectMediaHandler so the
full pipeline (VLM call, merge, publish to Kafka/ES) runs identically to the
Kafka-driven path.

The route calls ``prepare()`` synchronously (prompt resolution, validation),
then dispatches ``process_and_publish()`` as a background task and returns
HTTP 202 immediately.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from handlers.direct_media.direct_media_handler import DirectMediaHandler
from handlers.prompt_handler.prompt_manager import PromptManager
from mdx.anomaly.sink.vlm_enhanced_sink import build_vlm_enhanced_sink
from models.base_response_parser import load_response_parser
from vlm.vlm_client import VLMClient

from ..core.dependencies import load_config, load_config_path
from .terminal_job_store import JobHandle, TerminalJobStore


class AlertTypeNotFoundError(Exception):
    """Raised when category has no prompt configured."""


class OnDemandVerificationService:
    """Process on-demand verification requests using DirectMedia-aligned flow.

    ``prepare()`` validates the request and resolves prompts (fast, sync).
    ``process_and_publish()`` runs VLM + merge + publish via DirectMediaHandler
    (blocking, intended to run in a background task).
    """

    def __init__(self, job_store: Optional[TerminalJobStore] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_file = load_config_path()
        self.config = load_config()

        job_config = (
            self.config.get("alert_agent", {}).get("ondemand_jobs", {}) or {}
        )
        self.job_store = job_store or TerminalJobStore(
            capacity=job_config.get("capacity", 1000),
            ttl_seconds=job_config.get("ttl_seconds", 3600),
        )

        self.vlm_client = VLMClient(self.config.get("vlm", {}))
        self.prompt_manager = PromptManager(self.config_file)

        # The FastAPI process constructs its own DirectMediaHandler rather
        # than reusing the handler owned by the Kafka worker process.  Load
        # the configured parser here as well so on-demand REST requests obey
        # the same ``vlm.response_parser`` contract as Kafka/VST traffic.
        parser_path = self.config.get("vlm", {}).get("response_parser")
        self.pluggable_parser = (
            load_response_parser(parser_path) if parser_path else None
        )
        if parser_path:
            self.logger.info(
                "On-demand pluggable response parser active: '%s'", parser_path
            )

        # Pass the PromptManager's AlertConfigStore so the sink resolves
        # ``output_category`` from Redis on each publish (hot-reload of
        # PUT /verification/config edits) rather than the file-loaded
        # mapping cached at startup.
        self.vlm_enhanced_event_sink = build_vlm_enhanced_sink(
            self.config,
            alert_config_store=getattr(self.prompt_manager, "alert_config_store", None),
        )
        self.direct_media_handler = DirectMediaHandler(
            vlm_client=self.vlm_client,
            vlm_enhanced_event_sink=self.vlm_enhanced_event_sink,
            config=self.config,
            pluggable_parser=self.pluggable_parser,
        )

        self.max_media_count = (
            self.config.get("alert_agent", {})
            .get("media_download", {})
            .get("max_media_count", 5)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(
        self, request_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], str, str]:
        """Build the Incident message and resolve prompts.

        Fast and synchronous — safe to call before returning HTTP 202.

        Returns:
            ``(message, user_prompt, system_prompt)``

        Raises:
            AlertTypeNotFoundError: category has no configured prompt.
            ValueError: prompt manager failure or other validation issue.
        """
        message = dict(request_data)

        now = datetime.now(timezone.utc).isoformat()
        requested_id = message.get("id")
        if requested_id is None:
            message["id"] = f"ondemand-{uuid.uuid4()}"
        elif not isinstance(requested_id, str):
            raise ValueError("id must be a string when provided")
        message.setdefault("sensorId", "ondemand")
        message.setdefault("timestamp", now)
        message.setdefault("end", now)

        info_block = message.get("info", {})
        media_urls = info_block.get("media_urls", [])

        if len(media_urls) > self.max_media_count:
            self.logger.warning(
                "media_urls count (%d) exceeds limit (%d), truncating",
                len(media_urls),
                self.max_media_count,
            )
            media_urls = media_urls[: self.max_media_count]
            message["info"]["media_urls"] = media_urls

        try:
            user_prompt, system_prompt = (
                self.prompt_manager.get_prompts_for_message(message)
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc

        if not user_prompt:
            raise AlertTypeNotFoundError(
                f"No prompt configuration found for category "
                f"'{message.get('category')}'"
            )

        return message, user_prompt, system_prompt

    def register(self) -> JobHandle:
        """Create a server-keyed job before background dispatch."""

        return self.job_store.register()

    def get_status(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """Return a sanitized process-local status snapshot, if retained."""

        TerminalJobStore.validate_correlation_id(correlation_id)
        return self.job_store.get(correlation_id)

    def cancel(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """Request cancellation while the job is still pre-publish."""

        TerminalJobStore.validate_correlation_id(correlation_id)
        return self.job_store.cancel(correlation_id)

    def process_and_publish(
        self,
        job_handle: JobHandle,
        message: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
    ) -> None:
        """Run VLM evaluation and publish results to Kafka/ES.

        Delegates entirely to :class:`DirectMediaHandler` so the processing
        pipeline is identical to the Kafka-driven path.  This method is
        blocking (synchronous) and is intended to run inside a background task.
        """
        correlation_id = job_handle.correlation_id
        if not self.job_store.mark_running(job_handle):
            # Cancellation can win between HTTP 202 creation and background
            # task startup.  In that case no VLM or sink work is started.
            return

        try:
            info_block = message.get("info", {})
            config_overrides = self._get_merged_vlm_config(
                message.get("category", "")
            )
            result = self.direct_media_handler.evaluate(
                worker_id=0,
                message=message,
                info_block=info_block,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                config_overrides=config_overrides,
                before_publish=lambda _message: self.job_store.begin_publish(
                    job_handle
                ),
            )
            # ``complete`` intentionally succeeds only after the handler's
            # atomic pre-publish hook moved the state to ``publishing``.  A
            # handler cancelled at that gate leaves the existing cancelled
            # terminal record untouched.
            completed = self.job_store.complete(job_handle, result)
            if not completed:
                snapshot = self.job_store.get(correlation_id)
                if snapshot is not None and snapshot.get("state") != "cancelled":
                    self.job_store.fail(
                        job_handle, "publish_transition_missing"
                    )
        except Exception:
            self.logger.exception(
                "On-demand verification background processing failed",
                extra={"correlation_id": correlation_id},
            )
            # Keep the public error bounded and non-secret; details stay in
            # server logs.
            self.job_store.fail(job_handle, "processing_failed")

    def _get_merged_vlm_config(self, category: str) -> Dict[str, Any]:
        """Resolve the same per-category VLM overrides as Kafka ingestion.

        Runtime API values win over the checked-in alert-type file, which wins
        over the global ``vlm`` block. This keeps on-demand and Kafka-backed
        direct-media parsing identical, including ``response_format`` and
        ``json_parser``.
        """
        merged = dict(self.config.get("vlm", {}))
        loader = getattr(self.prompt_manager, "alert_config_loader", None)
        if loader is not None:
            file_params = loader.get_vlm_params_for_alert_type(category)
            if file_params:
                file_values = file_params.model_dump(exclude_none=True)
                if isinstance(file_values, dict):
                    merged.update(file_values)

        store = getattr(self.prompt_manager, "alert_config_store", None)
        if store is not None:
            try:
                runtime_config = store.get(category)
            except Exception:
                self.logger.warning(
                    "Failed to read runtime VLM config for category %s",
                    category,
                    exc_info=True,
                )
            else:
                runtime_values = (
                    runtime_config.get("vlm_params")
                    if isinstance(runtime_config, dict)
                    else None
                )
                if isinstance(runtime_values, dict):
                    merged.update(
                        {
                            key: value
                            for key, value in runtime_values.items()
                            if value is not None
                        }
                    )
        return merged
