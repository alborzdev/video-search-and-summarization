# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Offline integration tests for cancel/publish ownership at the sink edge."""

import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock


try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    openai_stub = types.ModuleType("openai")
    for exception_name in (
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "UnprocessableEntityError",
        "BadRequestError",
    ):
        setattr(openai_stub, exception_name, type(exception_name, (Exception,), {}))
    openai_types_stub = types.ModuleType("openai.types")
    openai_chat_stub = types.ModuleType("openai.types.chat")
    openai_chat_stub.ChatCompletionMessage = type(
        "ChatCompletionMessage", (), {}
    )
    openai_types_stub.chat = openai_chat_stub
    openai_stub.types = openai_types_stub
    sys.modules.update(
        {
            "openai": openai_stub,
            "openai.types": openai_types_stub,
            "openai.types.chat": openai_chat_stub,
        }
    )


def _load_terminal_store():
    path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "alert-agent-web",
            "app",
            "service",
            "terminal_job_store.py",
        )
    )
    spec = importlib.util.spec_from_file_location("_publish_gate_store", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.TerminalJobStore


def _load_direct_media_handler():
    root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    handler_path = os.path.join(
        root, "handlers", "direct_media", "direct_media_handler.py"
    )
    downloader_path = os.path.join(
        root, "handlers", "direct_media", "media_downloader.py"
    )
    pkg_name = "_terminal_gate_dmh"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [os.path.dirname(handler_path)]
    sys.modules[pkg_name] = pkg

    downloader_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.media_downloader", downloader_path
    )
    downloader_module = importlib.util.module_from_spec(downloader_spec)
    sys.modules[downloader_spec.name] = downloader_module
    downloader_spec.loader.exec_module(downloader_module)

    handler_spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.direct_media_handler", handler_path
    )
    handler_module = importlib.util.module_from_spec(handler_spec)
    sys.modules[handler_spec.name] = handler_module
    handler_spec.loader.exec_module(handler_module)
    return handler_module.DirectMediaHandler


TerminalJobStore = _load_terminal_store()
DirectMediaHandler = _load_direct_media_handler()


def _handler(sink: MagicMock) -> DirectMediaHandler:
    return DirectMediaHandler(
        vlm_client=MagicMock(),
        vlm_enhanced_event_sink=sink,
        config={
            "vlm": {},
            "alert_agent": {"media_download": {}},
            "vst_config": {"download_dir": "/tmp/alert-bridge-test-media"},
            "vlm_enhanced_sink": {"type": "elastic"},
        },
    )


def test_accepted_cancellation_causes_zero_sink_calls():
    store = TerminalJobStore()
    sink = MagicMock()
    handler = _handler(sink)
    message = {"id": "caller-event-id", "info": {"verdict": "confirmed"}}

    handle = store.register()
    store.mark_running(handle)
    assert store.cancel(handle.correlation_id)["cancellationAccepted"] is True

    result = handler._publish_to_sink(
        "success",
        message,
        "prompt",
        "system",
        "yes",
        before_publish=lambda _message: store.begin_publish(handle),
    )

    sink.publish_success.assert_not_called()
    sink.publish_error.assert_not_called()
    assert result["sinkDelivery"]["outcome"] == "unconfirmed"
    assert store.get(handle.correlation_id)["state"] == "cancelled"


def test_post_admission_sink_exception_is_failed_without_second_publish():
    store = TerminalJobStore()
    sink = MagicMock()
    sink.publish_success.side_effect = RuntimeError("simulated sink failure")
    handler = _handler(sink)
    message = {"id": "caller-event-id", "info": {"verdict": "confirmed"}}

    handle = store.register()
    store.mark_running(handle)
    result = handler._publish_to_sink(
        "success",
        message,
        "prompt",
        "system",
        "yes",
        before_publish=lambda _message: store.begin_publish(handle),
    )
    assert store.complete(handle, result) is True

    sink.publish_success.assert_called_once()
    sink.publish_error.assert_not_called()
    assert result["sinkDelivery"] == {
        "transport": "elastic",
        "outcome": "failed",
    }
    assert store.get(handle.correlation_id)["state"] == "failed"


def test_legacy_sink_without_receipt_is_explicitly_unconfirmed():
    store = TerminalJobStore()
    sink = MagicMock()
    sink.publish_success.return_value = None
    handler = _handler(sink)
    message = {"id": "caller-event-id", "info": {"verdict": "confirmed"}}

    handle = store.register()
    store.mark_running(handle)
    result = handler._publish_to_sink(
        "success",
        message,
        "prompt",
        "system",
        "yes",
        before_publish=lambda _message: store.begin_publish(handle),
    )
    store.complete(handle, result)

    status = store.get(handle.correlation_id)
    assert status["state"] == "completed"
    assert status["result"]["sinkDelivery"] == {
        "transport": "elastic",
        "outcome": "unconfirmed",
    }
