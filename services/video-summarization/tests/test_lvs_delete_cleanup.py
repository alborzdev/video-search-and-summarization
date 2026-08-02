# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for strict LVS file and Elasticsearch deletion."""

import argparse
import logging
import sys
import types
from contextlib import nullcontext
from threading import Condition, RLock
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# A plain source checkout does not install image-only LVS dependencies.  Stub
# only their import surfaces; these deletion tests use the real FastAPI app,
# production route, ViaException, and ViaStreamHandler cleanup method.
via_logger_module = types.ModuleType("via_logger")
via_logger_module.logger = logging.getLogger("lvs-delete-cleanup-test")
via_logger_module.logger.setLevel(logging.INFO)
via_logger_module.LOG_PERF_LEVEL = 15
via_logger_module.TimeMeasure = lambda *_args, **_kwargs: nullcontext()
via_logger_module.patch_logger_handlers = lambda *_args, **_kwargs: None
via_logger_module.safe_log = lambda value: value
# Replace any narrower test stub installed during collection by
# test_lvs_mcp.py. Production modules import the attributes directly, so this
# keeps the suites order-independent without changing their imported objects.
sys.modules["via_logger"] = via_logger_module

json_repair_module = types.ModuleType("json_repair")
json_repair_module.repair_json = lambda value: value
sys.modules.setdefault("json_repair", json_repair_module)

pyaml_env_module = types.ModuleType("pyaml_env")
pyaml_env_module.parse_config = lambda *_args, **_kwargs: {}
sys.modules.setdefault("pyaml_env", pyaml_env_module)

sse_starlette_module = types.ModuleType("sse_starlette")
sse_module = types.ModuleType("sse_starlette.sse")
sse_module.EventSourceResponse = type("EventSourceResponse", (), {})
sse_starlette_module.sse = sse_module
sys.modules.setdefault("sse_starlette", sse_starlette_module)
sys.modules.setdefault("sse_starlette.sse", sse_module)

from rtvi_vlm_client import RtviError  # noqa: E402
from via_exception import ViaException  # noqa: E402
from via_server import API_PREFIX, ViaServer  # noqa: E402
from via_stream_handler import RequestInfo, ViaStreamHandler  # noqa: E402

FILE_ID = "a1b2c3d4-e5f6-4890-abcd-ef1234567890"


@pytest.fixture
def via_server(monkeypatch):
    monkeypatch.setenv("VIA_DEV_API", "true")
    monkeypatch.delenv("VIA_FILE_API_LOOPBACK_ONLY", raising=False)
    args = argparse.Namespace(host="127.0.0.1", port="8000", max_live_streams=1)
    server = ViaServer(args)
    server._stream_handler = MagicMock()
    server._stream_handler._vlm_pipeline.delete_file.return_value = {
        "id": FILE_ID,
        "object": "file",
        "deleted": True,
    }
    yield server
    server._async_executor.shutdown(wait=True)


@pytest.fixture
def client(via_server):
    with TestClient(via_server._app, raise_server_exceptions=False) as test_client:
        yield test_client


class TestDeleteVideoFileCleanup:
    def test_success_deletes_file_before_dropping_collection(self, via_server, client):
        calls = []

        def drop_collection(file_id):
            calls.append(("drop_collection", file_id))
            return {"acknowledged": True}

        def delete_file(file_id):
            calls.append(("delete_file", file_id))
            return {"id": file_id, "object": "file", "deleted": True}

        via_server._stream_handler.drop_collection_for_asset.side_effect = drop_collection
        via_server._stream_handler._vlm_pipeline.delete_file.side_effect = delete_file

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 200
        assert response.json() == {
            "id": FILE_ID,
            "object": "file",
            "deleted": True,
        }
        assert calls == [
            ("delete_file", FILE_ID),
            ("drop_collection", FILE_ID),
        ]

    @pytest.mark.parametrize(
        "drop_result",
        [
            {"error": "connection refused"},
            {"acknowledged": True, "error": "connection refused"},
        ],
    )
    def test_returned_collection_failure_is_truthful_after_file_deletion(
        self, via_server, client, drop_result
    ):
        via_server._stream_handler.drop_collection_for_asset.return_value = drop_result

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 503
        assert response.json() == {
            "code": "DependencyError",
            "message": (
                "Service temporarily unavailable: Elasticsearch collection deletion "
                "was not acknowledged. See server logs for details."
            ),
        }
        via_server._stream_handler._vlm_pipeline.delete_file.assert_called_once_with(FILE_ID)
        via_server._stream_handler.drop_collection_for_asset.assert_called_once_with(FILE_ID)

    def test_collection_exception_is_truthful_after_file_deletion(self, via_server, client):
        via_server._stream_handler.drop_collection_for_asset.side_effect = RuntimeError(
            "Elasticsearch unavailable"
        )

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 500
        assert response.json() == {
            "code": "DependencyError",
            "message": "Internal server error. See server logs for details.",
        }
        via_server._stream_handler._vlm_pipeline.delete_file.assert_called_once_with(FILE_ID)
        via_server._stream_handler.drop_collection_for_asset.assert_called_once_with(FILE_ID)

    @pytest.mark.parametrize("reason", ["KAFKA_ENABLED=false", "ca-rag disabled"])
    def test_explicit_non_owning_skip_still_deletes_file(self, via_server, client, reason):
        via_server._stream_handler.drop_collection_for_asset.return_value = {
            "skipped": True,
            "reason": reason,
        }

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 200
        via_server._stream_handler._vlm_pipeline.delete_file.assert_called_once_with(FILE_ID)

    def test_unknown_skip_reason_does_not_claim_cleanup(self, via_server, client):
        via_server._stream_handler.drop_collection_for_asset.return_value = {
            "skipped": True,
            "reason": "unknown",
        }

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 503
        via_server._stream_handler._vlm_pipeline.delete_file.assert_called_once_with(FILE_ID)

    def test_rtvi_busy_failure_preserves_collection(self, via_server, client):
        via_server._stream_handler._vlm_pipeline.delete_file.side_effect = RtviError(
            409,
            "Conflict",
            "File is in use",
        )

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 409
        via_server._stream_handler._vlm_pipeline.delete_file.assert_called_once_with(FILE_ID)
        via_server._stream_handler.drop_collection_for_asset.assert_not_called()

    @pytest.mark.parametrize(
        "result",
        [
            None,
            {"id": FILE_ID, "object": "file", "deleted": False},
            {"id": FILE_ID, "object": "asset", "deleted": True},
            {"id": "00000000-0000-4000-8000-000000000000", "object": "file", "deleted": True},
        ],
    )
    def test_invalid_rtvi_success_confirmation_preserves_collection(
        self, via_server, client, result
    ):
        via_server._stream_handler._vlm_pipeline.delete_file.return_value = result

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 500
        via_server._stream_handler.drop_collection_for_asset.assert_not_called()

    @pytest.mark.parametrize(
        "message",
        [
            f"No such resource {FILE_ID}",
            f"{FILE_ID} already deleted because of age out policy",
        ],
    )
    def test_exact_absent_file_response_continues_collection_cleanup(
        self, via_server, client, message
    ):
        via_server._stream_handler._vlm_pipeline.delete_file.side_effect = RtviError(
            400,
            "BadParameter",
            message,
        )
        via_server._stream_handler.drop_collection_for_asset.return_value = {"acknowledged": True}

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 200
        via_server._stream_handler.drop_collection_for_asset.assert_called_once_with(FILE_ID)

    def test_live_stream_not_a_file_response_preserves_collection(self, via_server, client):
        via_server._stream_handler._vlm_pipeline.delete_file.side_effect = RtviError(
            400,
            "BadParameter",
            f"No such file {FILE_ID}",
        )

        response = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert response.status_code == 400
        via_server._stream_handler.drop_collection_for_asset.assert_not_called()

    def test_cleanup_failure_can_be_retried_after_exact_absent_response(self, via_server, client):
        success = {"id": FILE_ID, "object": "file", "deleted": True}
        already_absent = RtviError(
            400,
            "BadParameter",
            f"No such resource {FILE_ID}",
        )
        via_server._stream_handler._vlm_pipeline.delete_file.side_effect = [
            success,
            already_absent,
        ]
        via_server._stream_handler.drop_collection_for_asset.side_effect = [
            {"error": "connection refused"},
            {"acknowledged": True},
        ]

        first = client.delete(f"{API_PREFIX}/files/{FILE_ID}")
        second = client.delete(f"{API_PREFIX}/files/{FILE_ID}")

        assert first.status_code == 503
        assert second.status_code == 200
        assert via_server._stream_handler._vlm_pipeline.delete_file.call_count == 2
        assert via_server._stream_handler.drop_collection_for_asset.call_count == 2


def _stream_handler_with_context_manager(ctx_mgr):
    handler = ViaStreamHandler.__new__(ViaStreamHandler)
    handler._kafka_enabled = True
    handler._args = argparse.Namespace(disable_ca_rag=False)
    handler._lock = RLock()
    handler._source_cleanup_condition = Condition(handler._lock)
    handler._source_cleanup_in_progress = set()
    handler._ca_rag_config = {"context_manager": {"functions": []}}
    handler._ctx_mgr_pool = [ctx_mgr]
    handler._create_ctx_mgr_pool = MagicMock()
    return handler


class TestDropCollectionForAsset:
    @pytest.mark.parametrize(
        ("kafka_enabled", "disable_ca_rag", "reason"),
        [
            (False, False, "KAFKA_ENABLED=false"),
            (True, True, "ca-rag disabled"),
        ],
    )
    def test_source_owned_non_owning_skips_are_exact(self, kafka_enabled, disable_ca_rag, reason):
        handler = _stream_handler_with_context_manager(MagicMock())
        handler._kafka_enabled = kafka_enabled
        handler._args.disable_ca_rag = disable_ca_rag

        assert handler.drop_collection_for_asset(FILE_ID) == {
            "skipped": True,
            "reason": reason,
        }

    def test_success_is_returned_and_context_manager_is_restored(self):
        ctx_mgr = MagicMock()
        ctx_mgr.drop_collection.return_value = {"acknowledged": True}
        handler = _stream_handler_with_context_manager(ctx_mgr)

        result = handler.drop_collection_for_asset(FILE_ID)

        assert result == {"acknowledged": True}
        ctx_mgr.configure.assert_called_once_with(
            config={
                "context_manager": {
                    "functions": [],
                    "uuid": FILE_ID,
                }
            }
        )
        assert handler._ctx_mgr_pool == [ctx_mgr]
    def test_exception_is_observable_and_context_manager_is_restored(self):
        ctx_mgr = MagicMock()
        ctx_mgr.drop_collection.side_effect = RuntimeError("connection refused")
        handler = _stream_handler_with_context_manager(ctx_mgr)

        with pytest.raises(ViaException) as exc_info:
            handler.drop_collection_for_asset(FILE_ID)

        assert exc_info.value.code == "DependencyError"
        assert exc_info.value.status_code == 500
        assert exc_info.value.message == "Internal server error. See server logs for details."
        assert handler._ctx_mgr_pool == [ctx_mgr]

    @pytest.mark.parametrize(
        "drop_result",
        [
            {"error": "connection refused"},
            {"acknowledged": True, "error": "connection refused"},
        ],
    )
    def test_returned_failure_is_observable_and_context_manager_is_restored(self, drop_result):
        ctx_mgr = MagicMock()
        ctx_mgr.drop_collection.return_value = drop_result
        handler = _stream_handler_with_context_manager(ctx_mgr)

        with pytest.raises(ViaException, match="connection refused") as exc_info:
            handler.drop_collection_for_asset(FILE_ID)

        assert exc_info.value.code == "DependencyError"
        assert exc_info.value.status_code == 503
        assert handler._ctx_mgr_pool == [ctx_mgr]

    def test_empty_context_manager_pool_is_an_observable_dependency_failure(self):
        handler = _stream_handler_with_context_manager(MagicMock())
        handler._ctx_mgr_pool = []

        with pytest.raises(ViaException) as exc_info:
            handler.drop_collection_for_asset(FILE_ID)

        assert exc_info.value.code == "DependencyUnavailable"
        assert exc_info.value.status_code == 503


def test_failed_file_request_reaches_terminal_cleanup_gate():
    handler = ViaStreamHandler.__new__(ViaStreamHandler)
    handler._lock = RLock()
    handler._source_cleanup_condition = Condition(handler._lock)
    handler._source_cleanup_in_progress = set()
    handler._request_info_map = {}
    handler._live_stream_info_map = {}
    handler._metrics = MagicMock()
    handler._update_completion_metrics = MagicMock()
    handler._end_e2e_span = MagicMock()

    request = RequestInfo()
    request.is_live = False
    request.status = RequestInfo.Status.FAILED
    request.progress = 37
    request.start_time = 1.0
    request._ctx_mgr = None
    request._qa_ctx_mgr = None
    handler._request_info_map[request.request_id] = request

    handler._process_output(request, False, [])

    assert request.status is RequestInfo.Status.FAILED
    assert request.progress == 100
    assert request.end_time is not None
    assert request.status_event.is_set()
    handler.check_status_remove_req_id(request.request_id)
    assert request.request_id not in handler._request_info_map
