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

"""Unit tests for OnDemandVerificationService (prepare + process_and_publish)."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_web_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "alert-agent-web")
)
_repo_root = os.path.abspath(os.path.join(_web_root, ".."))

_saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "app" or k.startswith("app.")}
_saved_path = sys.path[:]
sys.path = [p for p in sys.path if os.path.abspath(p) != _repo_root and p != ""]
sys.path.insert(0, _web_root)
try:
    import app.main  # noqa: F401
    from app.service import ondemand_verification_service as _svc_mod
    from app.service.ondemand_verification_service import (
        AlertTypeNotFoundError,
        OnDemandVerificationService,
    )
finally:
    sys.path = _saved_path
    sys.modules.update(_saved)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_config(max_media_count=5, response_parser=None):
    vlm = {"model": "test-model", "vlm_media_source_using_base64": False}
    if response_parser is not None:
        vlm["response_parser"] = response_parser
    return {
        "vlm": vlm,
        "alert_agent": {
            "media_download": {
                "enabled": True,
                "max_media_count": max_media_count,
                "use_verdict": False,
            }
        },
        "vst_config": {"download_dir": "/tmp/test_media"},
        "elastic": {"enabled": False, "hosts": []},
        "vlm_enhanced_sink": {},
    }


def _make_payload(media_urls=None, media_type="video", category="collision", **extra):
    return {
        "category": category,
        "info": {
            "media_urls": media_urls or ["http://host/video.mp4"],
            "media_type": media_type,
        },
        **extra,
    }


class _ServiceContext:
    """Keeps patches active for the lifetime of a test."""

    def __init__(
        self,
        user_prompt="Detect collisions",
        system_prompt="Be concise",
        max_media_count=5,
        response_parser=None,
    ):
        self.prompt_mgr = MagicMock()
        self.prompt_mgr.get_prompts_for_message.return_value = (user_prompt, system_prompt)
        self.mock_handler = MagicMock()
        self.mock_sink = MagicMock()
        self.mock_parser = MagicMock()
        self.mock_parser_loader = MagicMock(return_value=self.mock_parser)

        self._patches = [
            patch.object(
                _svc_mod,
                "load_config",
                return_value=_stub_config(max_media_count, response_parser),
            ),
            patch.object(_svc_mod, "load_config_path", return_value="config.yaml"),
            patch.object(_svc_mod, "VLMClient"),
            patch.object(_svc_mod, "PromptManager", return_value=self.prompt_mgr),
            patch.object(_svc_mod, "build_vlm_enhanced_sink", return_value=self.mock_sink),
            patch.object(_svc_mod, "DirectMediaHandler", return_value=self.mock_handler),
            patch.object(
                _svc_mod,
                "load_response_parser",
                self.mock_parser_loader,
            ),
        ]

    def start(self):
        for p in self._patches:
            p.start()
        self.svc = OnDemandVerificationService()
        self.svc.prompt_manager = self.prompt_mgr
        return self

    def stop(self):
        for p in reversed(self._patches):
            p.stop()


@pytest.fixture()
def ctx():
    c = _ServiceContext().start()
    yield c
    c.stop()


# ---------------------------------------------------------------------------
# prepare() — message defaults
# ---------------------------------------------------------------------------

class TestPrepareDefaults:

    def test_auto_generates_id(self, ctx):
        msg, _, _ = ctx.svc.prepare(_make_payload())
        assert msg["id"].startswith("ondemand-")

    def test_default_sensorId(self, ctx):
        msg, _, _ = ctx.svc.prepare(_make_payload())
        assert msg["sensorId"] == "ondemand"

    def test_auto_generates_timestamps(self, ctx):
        msg, _, _ = ctx.svc.prepare(_make_payload())
        assert "timestamp" in msg
        assert "end" in msg

    def test_caller_id_preserved(self, ctx):
        msg, _, _ = ctx.svc.prepare(_make_payload(id="my-id"))
        assert msg["id"] == "my-id"

    def test_caller_sensorId_preserved(self, ctx):
        msg, _, _ = ctx.svc.prepare(_make_payload(sensorId="cam-01"))
        assert msg["sensorId"] == "cam-01"

    def test_caller_timestamp_preserved(self, ctx):
        ts = "2026-01-01T00:00:00Z"
        msg, _, _ = ctx.svc.prepare(_make_payload(timestamp=ts, end=ts))
        assert msg["timestamp"] == ts


# ---------------------------------------------------------------------------
# prepare() — prompt resolution
# ---------------------------------------------------------------------------

class TestPreparePrompts:

    def test_returns_prompts(self, ctx):
        _, user, system = ctx.svc.prepare(_make_payload())
        assert user == "Detect collisions"
        assert system == "Be concise"

    def test_no_prompt_raises_alert_type_not_found(self):
        c = _ServiceContext(user_prompt=None).start()
        try:
            with pytest.raises(AlertTypeNotFoundError, match="No prompt"):
                c.svc.prepare(_make_payload(category="nonexistent"))
        finally:
            c.stop()

    def test_prompt_manager_exception_raises_value_error(self):
        c = _ServiceContext().start()
        try:
            c.prompt_mgr.get_prompts_for_message.side_effect = RuntimeError("redis down")
            with pytest.raises(ValueError, match="redis down"):
                c.svc.prepare(_make_payload())
        finally:
            c.stop()


# ---------------------------------------------------------------------------
# prepare() — media_urls truncation
# ---------------------------------------------------------------------------

class TestPrepareTruncation:

    def test_excess_urls_truncated(self):
        c = _ServiceContext(max_media_count=2).start()
        try:
            urls = [f"http://host/{i}.jpg" for i in range(5)]
            msg, _, _ = c.svc.prepare(_make_payload(media_urls=urls, media_type="image"))
            assert len(msg["info"]["media_urls"]) == 2
        finally:
            c.stop()


# ---------------------------------------------------------------------------
# process_and_publish() — delegates to DirectMediaHandler
# ---------------------------------------------------------------------------

class TestProcessAndPublish:

    def test_calls_handler_evaluate(self, ctx):
        msg, user, system = ctx.svc.prepare(_make_payload())
        handle = ctx.svc.register()
        ctx.svc.process_and_publish(handle, msg, user, system)

        ctx.mock_handler.evaluate.assert_called_once()
        call_kwargs = ctx.mock_handler.evaluate.call_args.kwargs
        assert call_kwargs["worker_id"] == 0
        assert call_kwargs["message"] is msg
        assert call_kwargs["info_block"] == msg["info"]
        assert call_kwargs["user_prompt"] == user
        assert call_kwargs["system_prompt"] == system
        assert call_kwargs["config_overrides"]["model"] == "test-model"

    def test_runtime_vlm_params_override_global_parser_config(self, ctx):
        ctx.prompt_mgr.alert_config_loader = MagicMock()
        ctx.prompt_mgr.alert_config_loader.get_vlm_params_for_alert_type.return_value = None
        ctx.prompt_mgr.alert_config_store = MagicMock()
        ctx.prompt_mgr.alert_config_store.get.return_value = {
            "vlm_params": {
                "model": "local-qwen",
                "response_format": "json",
                "json_parser": {"verdict_field": "qualified"},
            }
        }
        msg, user, system = ctx.svc.prepare(_make_payload())
        handle = ctx.svc.register()

        ctx.svc.process_and_publish(handle, msg, user, system)

        overrides = ctx.mock_handler.evaluate.call_args.kwargs["config_overrides"]
        assert overrides["model"] == "local-qwen"
        assert overrides["response_format"] == "json"
        assert overrides["json_parser"] == {"verdict_field": "qualified"}

    def test_handler_receives_full_message(self, ctx):
        payload = _make_payload(id="test-123", sensorId="cam-77")
        msg, user, system = ctx.svc.prepare(payload)
        handle = ctx.svc.register()
        ctx.svc.process_and_publish(handle, msg, user, system)

        call_kwargs = ctx.mock_handler.evaluate.call_args.kwargs
        assert call_kwargs["message"]["id"] == "test-123"
        assert call_kwargs["message"]["sensorId"] == "cam-77"

    def test_cancel_before_background_start_skips_handler(self, ctx):
        msg, user, system = ctx.svc.prepare(_make_payload(id="cancelled"))
        handle = ctx.svc.register()
        cancellation = ctx.svc.cancel(handle.correlation_id)
        assert cancellation["cancellationAccepted"] is True

        ctx.svc.process_and_publish(handle, msg, user, system)

        ctx.mock_handler.evaluate.assert_not_called()
        assert ctx.svc.get_status(handle.correlation_id)["state"] == "cancelled"

    def test_failed_sink_receipt_sets_terminal_failed(self, ctx):
        ctx.mock_handler.evaluate.return_value = {
            "processingOutcome": "verified",
            "sinkDelivery": {"transport": "elastic", "outcome": "failed"},
        }
        msg, user, system = ctx.svc.prepare(_make_payload(id="sink-failed"))
        handle = ctx.svc.register()

        # The real handler invokes this at the exact sink boundary.
        assert ctx.svc.job_store.mark_running(handle) is True
        assert ctx.svc.job_store.begin_publish(handle) is True
        # Simulate the remainder of process_and_publish after the running
        # transition, since the direct handler is mocked in this unit test.
        result = ctx.mock_handler.evaluate.return_value
        assert ctx.svc.job_store.complete(handle, result) is True

        assert ctx.svc.get_status(handle.correlation_id)["state"] == "failed"


# ---------------------------------------------------------------------------
# __init__ — wiring
# ---------------------------------------------------------------------------

class TestInit:

    def test_sink_built(self, ctx):
        assert ctx.svc.vlm_enhanced_event_sink is ctx.mock_sink

    def test_handler_built_with_sink(self, ctx):
        _svc_mod.DirectMediaHandler.assert_called_once()
        call_kwargs = _svc_mod.DirectMediaHandler.call_args.kwargs
        assert call_kwargs["vlm_enhanced_event_sink"] is ctx.mock_sink

    def test_unconfigured_parser_is_not_loaded_or_passed(self, ctx):
        ctx.mock_parser_loader.assert_not_called()
        call_kwargs = _svc_mod.DirectMediaHandler.call_args.kwargs
        assert call_kwargs["pluggable_parser"] is None

    def test_configured_parser_is_loaded_and_passed_to_handler(self):
        dotted_path = "external_parsers.ppe.PPEClassifier"
        c = _ServiceContext(response_parser=dotted_path).start()
        try:
            c.mock_parser_loader.assert_called_once_with(dotted_path)
            call_kwargs = _svc_mod.DirectMediaHandler.call_args.kwargs
            assert call_kwargs["pluggable_parser"] is c.mock_parser
            assert c.svc.pluggable_parser is c.mock_parser
        finally:
            c.stop()
