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
Direct Media Handler - Mode 3: Direct Media URL Processing

Orchestrates media download and VLM evaluation for direct URL processing.
Bypasses VST - no sensor mapping, no time window calculation.
"""

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Dict, List, Optional

from openai import APITimeoutError, APIConnectionError, InternalServerError, UnprocessableEntityError, BadRequestError

from models.responses import AlertBridgeResponse, VLMResponse, merge_info_with_response
from models.pluggable_parser_runtime import (
    ERROR_SOURCE_MEDIA_DOWNLOAD,
    ERROR_SOURCE_PLUGGABLE_PARSER,
    ERROR_SOURCE_VLM_API,
    ERROR_SOURCE_VLM_SCHEMA,
    apply_pluggable_parser_error as _apply_pluggable_parser_error,
    apply_pluggable_parser_output as _apply_pluggable_parser_output,
)
from .media_downloader import MediaDownloader, DownloadConfig
from .media_analyzer import analyze_single_media, analyze_multiple_images

# The pluggable-parser helpers above are the single source of truth for the
# output shape used by every ingestion mode (VST, local file, direct media).
# They live in :mod:`models.pluggable_parser_runtime` so we can import them
# at module load time instead of lazy-importing from the orchestrator on
# every VLM response (previous revisions had a circular import with
# ``enhance_alert_with_vlm``).

logger = logging.getLogger(__name__)

_VLM_ERROR_MAP = {
    APITimeoutError: (504, "VLM service timeout"),
    APIConnectionError: (503, "Failed to connect to VLM service"),
    InternalServerError: (500, "VLM service internal error"),
    UnprocessableEntityError: (422, "VLM request invalid"),
    BadRequestError: (400, "VLM bad request"),
}


def _merge_media_metadata_into_info(
    info: Dict[str, Any], media_metadata: Optional[Dict[str, Any]]
) -> None:
    """Merge direct-media metadata (``media_urls``, ``images_processed``…)
    into ``info`` with map<string,string> coercion.

    Direct-media builds this dict with native ``int`` / ``list`` / ``None``
    values for Python ergonomics, but the Kafka/ES wire schema is
    ``map<string,string>`` (nvschema alignment). Previously the success tail
    coerced inline while the pluggable-parser error tail copy-pasted
    the same loop without coercion — so an image ``TypeError`` in the
    custom parser would ship ``info["images_processed"] = 3`` (int)
    instead of ``"3"``, failing ES ingestion. Extracting one helper eliminates the drift.

    Uses ``setdefault`` semantics (won't overwrite existing info keys,
    matching the legacy behavior of both tails).
    """
    if not media_metadata:
        return
    for k, v in media_metadata.items():
        if k in info:
            continue
        if isinstance(v, (dict, list)):
            info[k] = json.dumps(v, separators=(',', ':'))
        elif v is None:
            info[k] = ''
        elif not isinstance(v, str):
            info[k] = str(v)
        else:
            info[k] = v


def merge_vlm_result(
    message: Dict[str, Any],
    response_content: str,
    *,
    model_name: str,
    use_verdict: bool,
    media_type: str,
    response_format: str = "auto",
    json_config: Optional[Dict[str, Any]] = None,
    media_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Parse VLM response and merge verification results into message['info'].

    Shared by DirectMediaHandler (pipeline) and OnDemandVerificationService (HTTP).
    """
    media_urls = message.get('info', {}).get('media_urls', [])
    media_source = media_urls[0] if len(media_urls) == 1 else None

    if use_verdict:
        try:
            vlm_data = VLMResponse.model_validate_text(
                response_content,
                model_name=model_name,
                response_format=response_format,
                json_config=json_config,
            )
            merge_info_with_response(
                message,
                AlertBridgeResponse(
                    vlm_response=vlm_data,
                    video_source=media_source,
                    verification_response_code=200,
                    verification_response_status="OK",
                ),
            )
        except Exception as e:
            logger.warning(
                "VLM response parsing failed",
                extra={
                    "id": message.get('id'),
                    "sensorId": message.get('sensorId'),
                    "error": str(e),
                },
            )
            merge_info_with_response(
                message,
                AlertBridgeResponse(
                    vlm_response=None,
                    video_source=media_source,
                    verification_response_code=500,
                    verification_response_status=f"VLM response parsing failed: {e}",
                    verdict="verification-failed",
                    error_source=ERROR_SOURCE_VLM_SCHEMA,
                ),
            )
    else:
        merge_info_with_response(
            message,
            AlertBridgeResponse(
                vlm_response=None,
                verification_response_code=200,
                verification_response_status="OK",
                verdict=None,
            ),
        )
        if 'info' not in message:
            message['info'] = {}
        message['info']['reasoning'] = response_content

    if 'info' not in message:
        message['info'] = {}
    message['info']['media_type'] = media_type
    _merge_media_metadata_into_info(message['info'], media_metadata)


class DirectMediaHandler:
    """
    Orchestrator for Mode 3: Direct Media URL evaluation.
    
    Coordinates:
    1. Input validation
    2. Media download (via MediaDownloader)
    3. VLM evaluation
    4. Response publishing
    """
    
    def __init__(
        self,
        vlm_client,
        vlm_enhanced_event_sink,
        config: Dict[str, Any],
        pluggable_parser=None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        self.vlm_client = vlm_client
        self.vlm_enhanced_event_sink = vlm_enhanced_event_sink
        self.config = config
        # Shared pluggable parser instance from AnomalyEnhancer.  When the
        # operator sets ``vlm.response_parser`` in config.yaml, Mode-3 routes
        # VLM output through the same ``_apply_pluggable_parser_*`` helpers
        # as Mode-2 / Mode-VST so all three ingestion paths produce identical
        # info shape.
        self._pluggable_parser = pluggable_parser
        # Optional atomic admission hook used by the on-demand HTTP service.
        # Existing Kafka/VST callers omit it and retain prior behavior.
        self._before_publish = before_publish
        
        media_config = config.get('alert_agent', {}).get('media_download', {})
        self.enabled = media_config.get('enabled', True)
        # Thor's local JSON-verification lane opts into verdict parsing without
        # mutating NVIDIA's shared profile template. Invalid environment values
        # fail startup instead of silently degrading to freestyle output.
        use_verdict_env = os.getenv('ALERT_DIRECT_MEDIA_USE_VERDICT')
        if use_verdict_env is None:
            self.use_verdict = media_config.get('use_verdict', False)
        elif use_verdict_env.lower() in ('1', 'true', 'yes'):
            self.use_verdict = True
        elif use_verdict_env.lower() in ('0', 'false', 'no'):
            self.use_verdict = False
        else:
            raise ValueError(
                "ALERT_DIRECT_MEDIA_USE_VERDICT must be a boolean value"
            )
        self.max_media_count = media_config.get('max_media_count', 5)
        self.model_name = config.get('vlm', {}).get('model', '')
        
        # Reuse vlm_media_source_using_base64 from vlm config.  Thor's local
        # OpenAI-compatible endpoint deliberately refuses to fetch loopback or
        # private URLs, so the local profile can force the safe download +
        # inline-data path without modifying NVIDIA's shared profile config.
        # Invalid values fail startup instead of silently selecting the wrong
        # media transport.
        base64_env = os.getenv('ALERT_VLM_MEDIA_SOURCE_USING_BASE64')
        if base64_env is None:
            self.vlm_media_source_using_base64 = config.get(
                'vlm', {}
            ).get('vlm_media_source_using_base64', False)
        elif base64_env.lower() in ('1', 'true', 'yes'):
            self.vlm_media_source_using_base64 = True
        elif base64_env.lower() in ('0', 'false', 'no'):
            self.vlm_media_source_using_base64 = False
        else:
            raise ValueError(
                'ALERT_VLM_MEDIA_SOURCE_USING_BASE64 must be a boolean value'
            )
        
        self.downloader = MediaDownloader(DownloadConfig(
            download_dir=config.get('vst_config', {}).get('download_dir', '/tmp/alert_bridge_media'),
            timeout_seconds=media_config.get('timeout_seconds', 30),
            max_size_mb=media_config.get('max_size_mb', 50),
            allow_private_urls=media_config.get('allow_private_urls', False),
        ))

    def evaluate(
        self,
        worker_id: int,
        message: Dict[str, Any],
        info_block: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
        config_overrides: Optional[Dict[str, Any]] = None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate media from direct URL(s).
        
        Supports both single media_url and multiple media_urls (list).
        Single media_url is normalized to media_urls for unified processing.
        """
        media_type = (info_block.get('media_type') or '').lower()
        media_urls = self._get_media_urls(info_block)
        
        if not media_urls:
            return self._publish_error(
                message, user_prompt, system_prompt,
                code=400,
                status="media_urls is required and must be a non-empty list",
                error_source=ERROR_SOURCE_MEDIA_DOWNLOAD,
                before_publish=before_publish,
            )
        
        if media_type == 'video':
            if len(media_urls) > 1:
                logger.warning("Multiple videos not supported, using first URL only")
            return self._evaluate_video(
                worker_id, message, media_urls[0], user_prompt, system_prompt,
                config_overrides=config_overrides,
                before_publish=before_publish,
            )

        return self._evaluate_images(
            worker_id, message, media_urls, user_prompt, system_prompt,
            config_overrides=config_overrides,
            before_publish=before_publish,
        )

    def _get_media_urls(self, info_block: Dict[str, Any]) -> List[str]:
        """Extract and validate media_urls from info block."""
        media_urls = info_block.get('media_urls')
        
        if isinstance(media_urls, str):
            try:
                media_urls = json.loads(media_urls)
            except json.JSONDecodeError:
                logger.warning("Failed to parse media_urls as JSON: %s", media_urls[:100] if media_urls else "")
                return []
        
        if media_urls and isinstance(media_urls, list) and len(media_urls) > 0:
            valid_urls = [url for url in media_urls if url]
            if len(valid_urls) > self.max_media_count:
                logger.warning(
                    "Media URLs count (%d) exceeds limit (%d), truncating",
                    len(valid_urls), self.max_media_count
                )
                return valid_urls[:self.max_media_count]
            return valid_urls
        return []

    # ── Evaluate methods ───────────────────────────────────────────────

    def _evaluate_video(
        self,
        worker_id: int,
        message: Dict[str, Any],
        video_url: str,
        user_prompt: str,
        system_prompt: str,
        config_overrides: Optional[Dict[str, Any]] = None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a single video URL via shared media analyzer."""
        try:
            start_time = time.time()
            vlm_response = analyze_single_media(
                vlm_client=self.vlm_client,
                downloader=self.downloader,
                media_path=video_url,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                use_base64=self.vlm_media_source_using_base64,
                config_overrides=config_overrides,
            )

            duration = round(time.time() - start_time, 3)
            response_content = vlm_response.content
            logger.info("VLM response received (direct video) [sensor=%s category=%s] duration=%.3fs",
                       message.get('sensorId', 'N/A'), message.get('category', 'N/A'), duration)

            if os.getenv('LOG_VERBOSE_VLM_RESPONSE', 'false').lower() in ('1', 'true', 'yes'):
                logger.debug("Raw VLM response: %s", response_content)

            return self._publish_success(
                message, user_prompt, system_prompt, response_content,
                media_type='video',
                config_overrides=config_overrides,
                before_publish=before_publish,
            )

        except ValueError as e:
            return self._publish_error(
                message, user_prompt, system_prompt,
                code=502, status=str(e),
                before_publish=before_publish,
            )
        except Exception as e:
            return self._handle_vlm_error(
                e, message, user_prompt, system_prompt,
                before_publish=before_publish,
            )

    def _evaluate_images(
        self,
        worker_id: int,
        message: Dict[str, Any],
        media_urls: List[str],
        user_prompt: str,
        system_prompt: str,
        config_overrides: Optional[Dict[str, Any]] = None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Evaluate image(s) from URL(s) via shared media analyzer."""
        try:
            logger.info("Processing %d image(s) [sensor=%s category=%s]",
                       len(media_urls),
                       message.get('sensorId', 'N/A'), message.get('category', 'N/A'))

            start_time = time.time()

            vlm_response = analyze_multiple_images(
                vlm_client=self.vlm_client,
                downloader=self.downloader,
                media_urls=media_urls,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                use_base64=self.vlm_media_source_using_base64,
                config_overrides=config_overrides,
            )

            duration = round(time.time() - start_time, 3)
            response_content = vlm_response.content
            logger.info("VLM response received (%d image(s)) [sensor=%s category=%s] duration=%.3fs",
                       len(media_urls),
                       message.get('sensorId', 'N/A'), message.get('category', 'N/A'), duration)

            if os.getenv('LOG_VERBOSE_VLM_RESPONSE', 'false').lower() in ('1', 'true', 'yes'):
                logger.debug("Raw VLM response: %s", response_content)

            return self._publish_success(
                message, user_prompt, system_prompt, response_content,
                media_type='image' if len(media_urls) == 1 else 'images',
                media_metadata={
                    'media_urls': media_urls,
                    'images_processed': len(media_urls),
                    'images_total': len(media_urls),
                },
                config_overrides=config_overrides,
                before_publish=before_publish,
            )

        except ValueError as e:
            return self._publish_error(
                message, user_prompt, system_prompt,
                code=502, status=str(e),
                before_publish=before_publish,
            )
        except Exception as e:
            return self._handle_vlm_error(
                e, message, user_prompt, system_prompt,
                before_publish=before_publish,
            )

    # ── Publish helpers ────────────────────────────────────────────────

    def _publish_success(
        self,
        message: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
        response_content: str,
        media_type: str,
        media_metadata: Optional[Dict[str, Any]] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Parse VLM response, merge into message, set metadata, and publish.

        Precedence (Mode-3 parity with VST / local):

        1. ``vlm.response_parser`` (pluggable) — replaces the built-in parser
           entirely and writes parser output into ``info["vlm_response"]``.
        2. ``alert_agent.media_download.use_verdict: true`` — legacy
           verdict-mode path using :class:`VLMResponse.model_validate_text`;
           writes free-form text into ``info["reasoning"]``.
        3. Default — raw VLM text is written to ``info["reasoning"]``.

        Paths 2 and 3 delegate to :func:`merge_vlm_result` (the shared
        public helper also used by OnDemandVerificationService).

        Pluggable-parser ``parse()`` failures emit an explicit
        ``verification-failed`` error event via the shared
        ``_apply_pluggable_parser_error`` helper so Mode-3 operators see
        exactly the same error contract as Mode-2 / VST operators.
        """
        if self._pluggable_parser is not None:
            media_urls = message.get('info', {}).get('media_urls', [])
            media_source = media_urls[0] if len(media_urls) == 1 else None
            try:
                parsed = self._pluggable_parser.parse(response_content)
                if not isinstance(parsed, dict):
                    raise TypeError(
                        f"Pluggable parser must return a dict, got "
                        f"{type(parsed).__name__}"
                    )
                _apply_pluggable_parser_output(
                    message,
                    parsed,
                    video_source=media_source,
                )
            except Exception as e:
                _apply_pluggable_parser_error(
                    message,
                    e,
                    video_source=media_source,
                )
                if 'info' not in message:
                    message['info'] = {}
                message['info']['media_type'] = media_type
                _merge_media_metadata_into_info(message['info'], media_metadata)
                return self._publish_to_sink(
                    "error",
                    message,
                    user_prompt,
                    system_prompt,
                    {
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "errorSource": ERROR_SOURCE_PLUGGABLE_PARSER,
                    },
                    before_publish=before_publish,
                )
            if 'info' not in message:
                message['info'] = {}
            message['info']['media_type'] = media_type
            _merge_media_metadata_into_info(message['info'], media_metadata)
        else:
            effective_vlm_cfg = {
                **self.config.get('vlm', {}),
                **(config_overrides or {}),
            }
            merge_vlm_result(
                message,
                response_content,
                model_name=effective_vlm_cfg.get('model', self.model_name),
                use_verdict=self.use_verdict,
                response_format=effective_vlm_cfg.get('response_format', 'auto'),
                json_config=effective_vlm_cfg.get('json_parser'),
                media_type=media_type,
                media_metadata=media_metadata,
            )

        return self._publish_to_sink(
            "success",
            message,
            user_prompt,
            system_prompt,
            response_content,
            before_publish=before_publish,
        )

    def _publish_error(
        self,
        message: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
        code: int,
        status: str,
        error_source: Optional[str] = None,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Publish error response.

        ``error_source`` is the structured bucket from
        :mod:`models.pluggable_parser_runtime` (``ERROR_SOURCE_*``) so
        downstream consumers can classify without substring-matching
        ``verificationResponseStatus``.
        """
        merge_info_with_response(
            message,
            AlertBridgeResponse(
                vlm_response=None,
                verification_response_code=code,
                verification_response_status=status,
                verdict="verification-failed",
                error_source=error_source,
            ),
        )
        return self._publish_to_sink(
            "error",
            message,
            user_prompt,
            system_prompt,
            {},
            before_publish=before_publish,
        )

    def _publish_to_sink(
        self,
        publish_kind: str,
        message: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
        payload: Any,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Apply the cancellation gate and return a sanitized sink result.

        The hook and cancellation endpoint use the same lock in the on-demand
        job store.  Once the hook returns true, publication owns the job and a
        later cancellation request is rejected rather than falsely accepted.
        """

        publish_gate = before_publish or self._before_publish
        if publish_gate is not None:
            try:
                allowed = publish_gate(message) is True
            except Exception:
                logger.exception(
                    "Pre-publish admission hook failed; suppressing sink call",
                    extra={"id": message.get("id")},
                )
                allowed = False
            if not allowed:
                logger.info(
                    "Sink publish suppressed by pre-publish admission hook",
                    extra={"id": message.get("id")},
                )
                return self._processing_result(
                    message,
                    {
                        "transport": self._configured_sink_type(),
                        "outcome": "unconfirmed",
                    },
                    processing_outcome="unknown",
                )

        try:
            if publish_kind == "success":
                raw_receipt = self.vlm_enhanced_event_sink.publish_success(
                    message, user_prompt, system_prompt, payload
                )
            else:
                raw_receipt = self.vlm_enhanced_event_sink.publish_error(
                    message, user_prompt, system_prompt, payload
                )
        except Exception:
            # Admission already moved the job to ``publishing``.  Do not let
            # the outer VLM try/except reinterpret a sink failure as a VLM
            # failure and attempt a second publish.
            logger.exception(
                "Direct-media sink publish failed",
                extra={"id": message.get("id"), "publish_kind": publish_kind},
            )
            return self._processing_result(
                message,
                {
                    "transport": self._configured_sink_type(),
                    "outcome": "failed",
                },
            )
        return self._processing_result(
            message,
            self._normalize_sink_receipt(raw_receipt),
        )

    def _configured_sink_type(self) -> str:
        sink_type = str(
            (self.config.get("vlm_enhanced_sink", {}) or {}).get(
                "type", "elastic"
            )
        ).strip().lower()
        return sink_type if sink_type in {"elastic", "kafka"} else "unknown"

    def _normalize_sink_receipt(self, value: Any) -> Dict[str, Any]:
        """Normalize new receipt-aware sinks and older ``None`` sinks."""

        if not isinstance(value, Mapping):
            return {
                "transport": self._configured_sink_type(),
                "outcome": "unconfirmed",
            }
        receipt = dict(value)
        receipt.setdefault("transport", self._configured_sink_type())
        receipt.setdefault("outcome", "unconfirmed")
        return receipt

    @staticmethod
    def _processing_result(
        message: Dict[str, Any],
        sink_delivery: Dict[str, Any],
        *,
        processing_outcome: Optional[str] = None,
    ) -> Dict[str, Any]:
        info = message.get("info") if isinstance(message.get("info"), dict) else {}
        verdict = info.get("verdict")
        response_code = info.get("verificationResponseCode")
        numeric_response_code: Optional[int] = None
        if isinstance(response_code, int) and not isinstance(response_code, bool):
            numeric_response_code = response_code
        elif isinstance(response_code, str) and response_code.isdigit():
            numeric_response_code = int(response_code)
        if processing_outcome is None:
            processing_outcome = (
                "verification_failed"
                if verdict == "verification-failed"
                or (
                    numeric_response_code is not None
                    and numeric_response_code >= 400
                )
                else "verified"
            )
        result: Dict[str, Any] = {
            "processingOutcome": processing_outcome,
            "sinkDelivery": sink_delivery,
        }
        if verdict is not None:
            result["verdict"] = verdict
        if numeric_response_code is not None:
            result["verificationResponseCode"] = numeric_response_code
        error_source = info.get("errorSource")
        if error_source is not None:
            result["errorSource"] = error_source
        return result

    def _handle_vlm_error(
        self,
        error: Exception,
        message: Dict[str, Any],
        user_prompt: str,
        system_prompt: str,
        before_publish: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Dict[str, Any]:
        """Map VLM/OpenAI exceptions to HTTP error codes and publish."""
        for exc_type, (code, default_status) in _VLM_ERROR_MAP.items():
            if isinstance(error, exc_type):
                logger.error("VLM error during direct media evaluation: %s", error, exc_info=True)
                status = f"{default_status}: {error}" if code in (400, 422) else default_status
                return self._publish_error(
                    message, user_prompt, system_prompt,
                    code=code, status=status,
                    error_source=ERROR_SOURCE_VLM_API,
                    before_publish=before_publish,
                )

        logger.error("Unexpected error during direct media evaluation: %s", error, exc_info=True)
        return self._publish_error(
            message, user_prompt, system_prompt,
            code=500, status=f"Evaluation error: {error}",
            error_source=ERROR_SOURCE_VLM_API,
            before_publish=before_publish,
        )
