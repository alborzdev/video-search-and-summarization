# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

import logging
from collections import OrderedDict
from threading import Event, Lock, Thread
import types
import sys
from unittest.mock import MagicMock


via_logger = types.ModuleType("via_logger")
via_logger.logger = logging.getLogger("rtvi-vlm-abort-test")
sys.modules.setdefault("via_logger", via_logger)

from rtvi_vlm_client import RtviVlmClient  # noqa: E402


def _client():
    client = object.__new__(RtviVlmClient)
    client._base_url = "http://rtvi.test"
    client._model_info = types.SimpleNamespace(id="model")
    client._session = MagicMock()
    client._active_caption_requests = {}
    client._active_caption_requests_lock = Lock()
    client._cancelled_caption_owners = OrderedDict()
    return client


def _response(request_id="rtvi-request-1", lines=()):
    response = MagicMock(status_code=200)
    response.headers = {"x-request-id": request_id}
    response.iter_lines.return_value = list(lines)
    return response


def test_stream_registers_exact_request_and_finally_closes_identity() -> None:
    client = _client()
    response = _response(
        lines=['data: {"id":"rtvi-request-1","chunk_responses":[]}', "data: [DONE]"]
    )
    client._session.post.return_value = response

    assert list(
        client.generate_captions_stream(
            owner_id="lvs-request-1", file_id="asset-1", prompt="describe"
        )
    ) == [{"id": "rtvi-request-1", "chunk_responses": []}]
    assert client._active_caption_requests == {}
    response.close.assert_called()


def test_abort_request_uses_nonconflicting_exact_route_and_is_idempotent() -> None:
    client = _client()
    response = _response()
    delete_response = MagicMock(status_code=200)
    client._session.delete.return_value = delete_response
    lease = client._begin_caption_request("lvs-request-1", "asset-shared")
    client._register_caption_response(lease, "rtvi-request-1", response)

    assert client.cancel_request("lvs-request-1") is True
    assert client.abort_request("lvs-request-1") is False
    client._session.delete.assert_called_once_with(
        "http://rtvi.test/v1/generate_captions/requests/rtvi-request-1",
        timeout=10,
        headers={"x-stream-id": "asset-shared"},
    )
    delete_response.close.assert_called_once_with()
    assert lease.terminal_event.is_set()


def test_cancel_during_blocking_post_aborts_immediately_after_registration() -> None:
    client = _client()
    post_started = Event()
    release_post = Event()
    response = _response(lines=["data: should-not-be-consumed"])

    def blocking_post(*_args, **_kwargs):
        post_started.set()
        release_post.wait(timeout=2)
        return response

    client._session.post.side_effect = blocking_post
    client._session.delete.return_value = MagicMock(status_code=200)
    result = []
    worker = Thread(
        target=lambda: result.extend(
            client.generate_captions_stream(
                owner_id="lvs-request-1", file_id="asset-shared", prompt="describe"
            )
        )
    )
    worker.start()
    assert post_started.wait(timeout=1)
    cancel_result = []
    canceller = Thread(target=lambda: cancel_result.append(client.cancel_request("lvs-request-1")))
    canceller.start()
    canceller.join(timeout=0.05)
    assert canceller.is_alive()
    release_post.set()
    worker.join(timeout=2)
    canceller.join(timeout=2)

    assert not worker.is_alive()
    assert not canceller.is_alive()
    assert cancel_result == [True]
    assert result == []
    response.iter_lines.assert_not_called()
    client._session.delete.assert_called_once()
    assert client._active_caption_requests == {}


def test_pre_generation_tombstone_is_consumed_and_storage_is_bounded() -> None:
    client = _client()
    assert client.cancel_request("future-owner") is True
    client._session.post.return_value = _response()
    client._session.delete.return_value = MagicMock(status_code=200)
    assert list(
        client.generate_captions_stream(
            owner_id="future-owner", file_id="asset", prompt="describe"
        )
    ) == []
    assert "future-owner" not in client._cancelled_caption_owners

    for index in range(1100):
        client.cancel_request(f"unused-{index}")
    assert len(client._cancelled_caption_owners) <= 1024


def test_stale_finally_cannot_remove_or_close_replacement_response() -> None:
    client = _client()
    old = client._begin_caption_request("owner", "asset")
    old.response = MagicMock()
    replacement = types.SimpleNamespace(response=MagicMock())
    with client._active_caption_requests_lock:
        client._active_caption_requests["owner"] = replacement

    client._finish_caption_request(old)

    assert client._active_caption_requests["owner"] is replacement
    replacement.response.close.assert_not_called()
