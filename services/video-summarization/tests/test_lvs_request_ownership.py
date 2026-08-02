# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Focused regressions for exact LVS request ownership and cancellation."""

import asyncio
import concurrent.futures
import logging
from pathlib import Path
import sys
import time
import types
from contextlib import nullcontext
from threading import Barrier, Condition, Event, RLock, Thread
from unittest.mock import MagicMock

import pytest


via_logger_module = types.ModuleType("via_logger")
via_logger_module.logger = logging.getLogger("lvs-request-ownership-test")
via_logger_module.LOG_PERF_LEVEL = 15
via_logger_module.TimeMeasure = lambda *_args, **_kwargs: nullcontext()
via_logger_module.patch_logger_handlers = lambda *_args, **_kwargs: None
via_logger_module.safe_log = lambda *_args, **_kwargs: None
sys.modules["via_logger"] = via_logger_module

json_repair_module = types.ModuleType("json_repair")
json_repair_module.loads = lambda value: value
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

from via_server import ViaServer  # noqa: E402
from via_stream_handler import RequestInfo, ViaStreamHandler  # noqa: E402


def _handler() -> ViaStreamHandler:
    handler = ViaStreamHandler.__new__(ViaStreamHandler)
    handler._lock = RLock()
    handler._source_cleanup_condition = Condition(handler._lock)
    handler._source_cleanup_in_progress = set()
    handler._source_teardown_in_progress = set()
    handler._deferred_source_cleanup = {}
    handler._initial_db_reset_condition = Condition(handler._lock)
    handler._initial_db_reset_state = "pending"
    handler._initial_db_reset_error = None
    handler._request_info_map = {}
    handler._live_stream_info_map = {}
    handler._ctx_mgr_pool = []
    handler._qa_ctx_mgr_pool = []
    handler._metrics = MagicMock()
    handler._vlm_pipeline = MagicMock()
    handler._running = True
    handler._end_vlm_pipeline_span = MagicMock()
    handler._end_e2e_span = MagicMock()
    handler.drop_collection_for_asset = MagicMock(return_value={"acknowledged": True})
    return handler


def test_reserved_request_can_be_cancelled_before_worker_claim() -> None:
    handler = _handler()
    request_id = handler.reserve_request("asset-shared")

    assert handler.cancel_request(request_id, "caller_cancelled") is True
    request = handler._request_info_map[request_id]
    assert request.status is RequestInfo.Status.CANCELLED
    assert request.terminal_event.is_set()
    assert request.quiescent_event.is_set()
    assert handler.wait_for_request_terminal(request_id, timeout=0)
    assert handler.wait_for_request_quiescent(request_id, timeout=0)
    handler._vlm_pipeline.cancel_request.assert_not_called()

    late_worker_claim = handler._claim_request(request_id, "asset-shared")
    assert late_worker_claim is request
    # An unqueued stale claim cannot revoke already-published quiescence.
    assert request.quiescent_event.is_set()
    handler._request_operation_finished(request)
    assert request.quiescent_event.is_set()

    assert handler.cleanup_request(request_id) is True
    assert request_id not in handler._request_info_map


def _assert_reserved_request_gets_real_context_manager(summarize: bool) -> None:
    handler = _handler()
    context_manager = MagicMock()
    handler._ctx_mgr_pool = [context_manager]
    request_id = handler.reserve_request("asset-shared")
    request = handler._request_info_map[request_id]
    request.summarize = summarize

    acquired = handler.get_ctx_mgr(
        "asset-shared",
        exclude_request_id=request_id,
    )

    assert acquired is context_manager
    assert handler._ctx_mgr_pool == []
    context_manager.reset.assert_not_called()


def test_reserved_non_summarize_request_does_not_select_itself_as_context_owner() -> None:
    _assert_reserved_request_gets_real_context_manager(summarize=False)


def test_reserved_summarize_request_does_not_reset_null_current_context() -> None:
    _assert_reserved_request_gets_real_context_manager(summarize=True)


def test_via_server_cancel_waits_for_queued_worker_handoff() -> None:
    handler = _handler()
    request_id = handler.reserve_request("asset-shared")
    worker_blocked = Event()
    release_worker = Event()
    worker_claimed = Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def occupy_executor():
        worker_blocked.set()
        release_worker.wait(timeout=5)

    blocker = executor.submit(occupy_executor)
    assert worker_blocked.wait(timeout=1)

    def summarize(source, _query, claimed_request_id):
        request = handler._claim_request(claimed_request_id, source.source_id)
        worker_claimed.set()
        try:
            if request.cancel_event.is_set():
                handler._mark_request_cancelled(request)
            return claimed_request_id
        finally:
            handler._request_operation_finished(request)

    handler.summarize = summarize
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler
    server._async_executor = executor

    async def cancel_while_queued():
        task = asyncio.create_task(
            server._run_reserved_summarize(
                types.SimpleNamespace(source_id="asset-shared"),
                object(),
                request_id,
            )
        )
        request = handler._request_info_map[request_id]
        while not request.submission_queued:
            await asyncio.sleep(0)

        task.cancel()
        await asyncio.sleep(0)
        assert request.cancel_event.is_set()
        assert request.active_operations == 1
        assert not request.quiescent_event.is_set()
        assert handler.cleanup_request(request_id) is False

        release_worker.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled submission task unexpectedly completed")

    try:
        asyncio.run(cancel_while_queued())
        assert worker_claimed.wait(timeout=1)
        assert request_id not in handler._request_info_map
    finally:
        release_worker.set()
        blocker.result(timeout=1)
        executor.shutdown(wait=True)


def test_blocked_downstream_cancel_does_not_block_event_loop() -> None:
    cancel_started = Event()
    release_cancel = Event()
    calls = []

    def cancel_request(request_id, reason):
        calls.append(("cancel", request_id, reason))
        cancel_started.set()
        release_cancel.wait(timeout=2)
        return True

    handler = types.SimpleNamespace(
        cancel_request=cancel_request,
        wait_for_request_quiescent=lambda request_id: calls.append(
            ("quiescent", request_id)
        )
        or True,
        cleanup_request=lambda request_id: (
            calls.append(("cleanup", request_id)) or True
        ),
    )
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler
    server._async_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def exercise():
        cancel_task = asyncio.create_task(
            server._cancel_wait_and_cleanup_request("request-one", "disconnect")
        )
        while not cancel_started.is_set():
            await asyncio.sleep(0)

        # A timer must run while downstream cancellation is blocked in a worker.
        ticked = Event()

        async def ticker():
            await asyncio.sleep(0.01)
            ticked.set()

        await asyncio.wait_for(ticker(), timeout=0.2)
        assert ticked.is_set()
        release_cancel.set()
        await asyncio.wait_for(cancel_task, timeout=1)

    try:
        asyncio.run(exercise())
        assert calls == [
            ("cancel", "request-one", "disconnect"),
            ("quiescent", "request-one"),
            ("cleanup", "request-one"),
        ]
    finally:
        release_cancel.set()
        server._async_executor.shutdown(wait=True)


def test_blocked_reserve_keeps_loop_live_and_cancel_cleans_lease() -> None:
    reserve_started = Event()
    release_reserve = Event()
    calls = []

    def reserve_request(source_id):
        calls.append(("reserve", source_id))
        reserve_started.set()
        release_reserve.wait(timeout=2)
        return "reserved-request"

    handler = types.SimpleNamespace(
        reserve_request=reserve_request,
        cancel_request=lambda request_id, reason: (
            calls.append(("cancel", request_id, reason)) or True
        ),
        wait_for_request_quiescent=lambda request_id: (
            calls.append(("quiescent", request_id)) or True
        ),
        cleanup_request=lambda request_id: (
            calls.append(("cleanup", request_id)) or True
        ),
    )
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler

    async def exercise():
        reserve_task = asyncio.create_task(server._reserve_request("asset-shared"))
        while not reserve_started.is_set():
            await asyncio.sleep(0)

        ticked = Event()

        async def ticker():
            await asyncio.sleep(0.01)
            ticked.set()

        await asyncio.wait_for(ticker(), timeout=0.2)
        assert ticked.is_set()

        reserve_task.cancel()
        await asyncio.sleep(0)
        assert not reserve_task.done()

        release_reserve.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(reserve_task, timeout=1)

    try:
        asyncio.run(exercise())
        assert calls == [
            ("reserve", "asset-shared"),
            (
                "cancel",
                "reserved-request",
                "request_cancelled_during_reservation",
            ),
            ("quiescent", "reserved-request"),
            ("cleanup", "reserved-request"),
        ]
    finally:
        release_reserve.set()


def test_caption_and_summarize_routes_reserve_through_control_plane_helper() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "via_server.py").read_text()

    assert source.count("request_id = await self._reserve_request(videoId)") == 2
    assert "request_id = self._stream_handler.reserve_request(videoId)" not in source


def test_nonstream_caption_cancellation_exactly_cancels_quiesces_and_cleans() -> None:
    wait_started = Event()
    release_wait = Event()
    calls = []

    def wait_for_request_done(request_id):
        calls.append(("wait", request_id))
        wait_started.set()
        release_wait.wait(timeout=2)

    def cancel_request(request_id, reason):
        calls.append(("cancel", request_id, reason))
        release_wait.set()
        return True

    handler = types.SimpleNamespace(
        wait_for_request_done=wait_for_request_done,
        cancel_request=cancel_request,
        wait_for_request_quiescent=lambda request_id: calls.append(
            ("quiescent", request_id)
        )
        or True,
        cleanup_request=lambda request_id: (
            calls.append(("cleanup", request_id)) or True
        ),
    )
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler
    server._async_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def exercise():
        task = asyncio.create_task(
            server._wait_for_nonstream_request("caption-request")
        )
        while not wait_started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled caption wait unexpectedly completed")

    try:
        asyncio.run(exercise())
        assert calls == [
            ("wait", "caption-request"),
            ("cancel", "caption-request", "nonstream_client_disconnected"),
            ("quiescent", "caption-request"),
            ("cleanup", "caption-request"),
        ]
    finally:
        release_wait.set()
        server._async_executor.shutdown(wait=True)


def test_both_sse_routes_force_disconnect_to_incomplete_finalization() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "via_server.py").read_text()
    assert 'caption_disconnect["received"] = True' in source
    assert 'completed and not caption_disconnect["received"]' in source
    assert 'summarize_disconnect["received"] = True' in source
    assert 'completed and not summarize_disconnect["received"]' in source


def test_caption_sse_conflict_is_claimed_before_second_request_dispatch() -> None:
    handler = _handler()
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler
    server._sse_active_clients = {}
    server._async_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    first_id = handler.reserve_request("asset-shared")
    second_id = handler.reserve_request("asset-shared")

    try:
        assert server._claim_sse_client("asset-shared", first_id) is True
        assert server._claim_sse_client("asset-shared", second_id) is False

        asyncio.run(
            server._cancel_wait_and_cleanup_request(second_id, "sse_client_conflict")
        )

        assert first_id in handler._request_info_map
        assert second_id not in handler._request_info_map
        assert server._sse_active_clients["asset-shared"][0] == first_id
        handler._vlm_pipeline.cancel_request.assert_not_called()
    finally:
        handler.cancel_request(first_id, "test_cleanup")
        handler.cleanup_request(first_id)
        server._async_executor.shutdown(wait=True)


def test_caption_sse_disconnect_cancels_only_its_exact_same_source_request() -> None:
    handler = _handler()
    server = ViaServer.__new__(ViaServer)
    server._stream_handler = handler
    server._sse_active_clients = {}
    server._async_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    disconnected_id = handler.reserve_request("asset-shared")
    sibling_id = handler.reserve_request("asset-shared")
    handler._claim_request(disconnected_id, "asset-shared")
    sibling = handler._claim_request(sibling_id, "asset-shared")
    server._touch_sse_client("asset-shared", disconnected_id)

    def finish_exact_cancel(request_id, _reason):
        request = handler._request_info_map[request_id]
        handler._mark_request_cancelled(request)
        handler._request_operation_finished(request)
        return True

    handler._vlm_pipeline.cancel_request.side_effect = finish_exact_cancel

    try:
        asyncio.run(
            server._finalize_sse_request(
                "asset-shared",
                disconnected_id,
                completed=False,
            )
        )

        handler._vlm_pipeline.cancel_request.assert_called_once_with(
            disconnected_id,
            "sse_client_disconnected",
        )
        assert disconnected_id not in handler._request_info_map
        assert sibling_id in handler._request_info_map
        assert not sibling.cancel_event.is_set()
        assert sibling.active_operations == 1
        assert server._sse_active_clients == {}
    finally:
        if sibling_id in handler._request_info_map:
            handler._mark_request_cancelled(sibling)
            handler._request_operation_finished(sibling)
            handler.cleanup_request(sibling_id)
        server._async_executor.shutdown(wait=True)


def test_active_cancel_is_exact_idempotent_and_waits_for_quiescence() -> None:
    handler = _handler()
    request_id = handler.reserve_request("asset-shared")
    request = handler._claim_request(request_id, "asset-shared")

    assert handler.cancel_request(request_id, "sse_disconnect") is True
    assert handler.cancel_request(request_id, "duplicate") is False
    handler._vlm_pipeline.cancel_request.assert_called_once_with(
        request_id, "sse_disconnect"
    )
    assert not request.terminal_event.is_set()
    assert handler.cleanup_request(request_id) is False

    handler._mark_request_cancelled(request)
    assert request.terminal_event.is_set()
    assert not request.quiescent_event.is_set()
    handler._request_operation_finished(request)
    assert request.quiescent_event.is_set()
    assert handler.cleanup_request(request_id) is True


def test_same_source_context_leases_are_distinct_and_cleaned_in_source_order() -> None:
    calls = []
    handler = _handler()

    class RecordingPool(list):
        def append(self, value):
            calls.append(("return", value.name))
            super().append(value)

    first_available = MagicMock(name="first_available_ctx")
    first_available.name = "first"
    first_available._process_index = 1
    second_available = MagicMock(name="second_available_ctx")
    second_available.name = "second"
    second_available._process_index = 2
    unrelated_available = MagicMock(name="unrelated_available_ctx")
    unrelated_available.name = "unrelated"
    unrelated_available._process_index = 3
    handler._ctx_mgr_pool = RecordingPool(
        [unrelated_available, second_available, first_available]
    )
    handler.drop_collection_for_asset.side_effect = lambda source_id, **_kwargs: (
        calls.append(("drop", source_id)) or {"acknowledged": True}
    )

    first_id = handler.reserve_request("asset-shared")
    second_id = handler.reserve_request("asset-shared")
    first = handler._request_info_map[first_id]
    second = handler._request_info_map[second_id]
    first._ctx_mgr = handler.get_ctx_mgr(
        "asset-shared",
        exclude_request_id=first_id,
    )
    second._ctx_mgr = handler.get_ctx_mgr(
        "asset-shared",
        exclude_request_id=second_id,
    )
    assert first._ctx_mgr is first_available
    assert second._ctx_mgr is second_available
    assert first._ctx_mgr is not second._ctx_mgr
    assert handler._ctx_mgr_pool == [unrelated_available]

    first_config = {"context_manager": {"uuid": "asset-shared"}, "query": "first"}
    second_config = {"context_manager": {"uuid": "asset-shared"}, "query": "second"}
    first._ctx_mgr.configure(config=first_config)
    second._ctx_mgr.configure(config=second_config)
    first._ctx_mgr.configure.assert_called_once_with(config=first_config)
    second._ctx_mgr.configure.assert_called_once_with(config=second_config)

    handler.cancel_request(first_id, "first_done")
    assert handler.cleanup_request(first_id) is True
    assert second_id in handler._request_info_map
    assert calls == []
    second_available.reset.assert_not_called()
    first_available.reset.assert_not_called()
    handler.drop_collection_for_asset.assert_not_called()

    unrelated_id = handler.reserve_request("asset-unrelated")
    unrelated = handler._request_info_map[unrelated_id]
    unrelated._ctx_mgr = handler.get_ctx_mgr(
        "asset-unrelated",
        exclude_request_id=unrelated_id,
    )
    assert unrelated._ctx_mgr is unrelated_available
    assert unrelated._ctx_mgr is not second._ctx_mgr
    unrelated_config = {
        "context_manager": {"uuid": "asset-unrelated"},
        "query": "unrelated",
    }
    unrelated._ctx_mgr.configure(config=unrelated_config)
    second._ctx_mgr.configure.assert_called_once_with(config=second_config)

    handler.cancel_request(second_id, "second_done")
    assert handler.cleanup_request(second_id) is True
    assert handler.cleanup_request(second_id) is False
    first_available.reset.assert_called_once_with(
        {
            "summarization": {"uuid": "asset-shared"},
            "delete_external_collection": False,
        }
    )
    handler.drop_collection_for_asset.assert_called_once_with(
        "asset-shared",
        force_legacy=True,
        ctx_mgr=first_available,
    )

    # One source manager is retained for the deferred reset. The final source
    # cleanup returns both the retained and current managers exactly once.
    assert calls == [
        ("drop", "asset-shared"),
        ("return", "second"),
        ("return", "first"),
    ]
    assert handler._ctx_mgr_pool == [second_available, first_available]
    assert len({id(ctx_mgr) for ctx_mgr in handler._ctx_mgr_pool}) == len(
        handler._ctx_mgr_pool
    )

    handler.cancel_request(unrelated_id, "test_cleanup")
    assert handler.cleanup_request(unrelated_id) is True
    assert handler._ctx_mgr_pool == [
        second_available,
        first_available,
        unrelated_available,
    ]
    assert len({id(ctx_mgr) for ctx_mgr in handler._ctx_mgr_pool}) == 3


@pytest.mark.parametrize("manager_first", [True, False])
def test_mixed_same_source_cleanup_uses_deferred_manager_in_either_order(
    manager_first,
) -> None:
    handler = _handler()
    manager = MagicMock()
    manager._process_index = 1

    rag_id = handler.reserve_request("asset-mixed")
    caption_id = handler.reserve_request("asset-mixed")
    rag = handler._request_info_map[rag_id]
    caption = handler._request_info_map[caption_id]
    rag._ctx_mgr = manager
    rag.delete_external_collection = False
    caption.delete_external_collection = True
    for request_id in (rag_id, caption_id):
        handler.cancel_request(request_id, "request_done")

    first_id, final_id = (
        (rag_id, caption_id) if manager_first else (caption_id, rag_id)
    )
    assert handler.cleanup_request(first_id) is True
    manager.reset.assert_not_called()
    handler.drop_collection_for_asset.assert_not_called()

    assert handler.cleanup_request(final_id) is True
    manager.reset.assert_called_once_with(
        {
            "summarization": {"uuid": "asset-mixed"},
            "delete_external_collection": True,
        }
    )
    handler.drop_collection_for_asset.assert_called_once_with(
        "asset-mixed",
        force_legacy=True,
        ctx_mgr=manager,
    )
    assert handler._ctx_mgr_pool == [manager]
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()


def test_deferred_cleanup_reuses_retained_manager_when_pool_is_exhausted() -> None:
    handler = _handler()
    del handler.drop_collection_for_asset
    handler._kafka_enabled = True
    handler._args = types.SimpleNamespace(disable_ca_rag=False)
    handler._ca_rag_config = {"context_manager": {"functions": []}}
    handler.num_ctx_mgr = 1
    handler.MAX_STREAMS = 1
    handler._create_ctx_mgr_pool = MagicMock()

    manager = MagicMock()
    manager._process_index = 1
    manager.drop_collection.return_value = {"acknowledged": True}
    rag_id = handler.reserve_request("asset-exhausted")
    caption_id = handler.reserve_request("asset-exhausted")
    handler._request_info_map[rag_id]._ctx_mgr = manager
    for request_id in (rag_id, caption_id):
        handler.cancel_request(request_id, "request_done")

    assert handler.cleanup_request(rag_id) is True
    assert handler._ctx_mgr_pool == []
    assert handler.cleanup_request(caption_id) is True

    handler._create_ctx_mgr_pool.assert_not_called()
    manager.configure.assert_called_once_with(
        config={
            "context_manager": {
                "functions": [],
                "uuid": "asset-exhausted",
            }
        }
    )
    manager.drop_collection.assert_called_once_with()
    assert handler._ctx_mgr_pool == [manager]


def test_multiple_same_source_managers_defer_one_and_return_each_once() -> None:
    handler = _handler()
    first_manager = MagicMock()
    first_manager._process_index = 1
    second_manager = MagicMock()
    second_manager._process_index = 2

    first_id = handler.reserve_request("asset-multi")
    second_id = handler.reserve_request("asset-multi")
    caption_id = handler.reserve_request("asset-multi")
    handler._request_info_map[first_id]._ctx_mgr = first_manager
    handler._request_info_map[second_id]._ctx_mgr = second_manager
    for request_id in (first_id, second_id, caption_id):
        handler.cancel_request(request_id, "request_done")

    assert handler.cleanup_request(first_id) is True
    assert handler._ctx_mgr_pool == []
    assert handler.cleanup_request(second_id) is True
    assert handler._ctx_mgr_pool == [second_manager]
    assert handler.cleanup_request(caption_id) is True

    first_manager.reset.assert_called_once()
    second_manager.reset.assert_not_called()
    handler.drop_collection_for_asset.assert_called_once_with(
        "asset-multi",
        force_legacy=True,
        ctx_mgr=first_manager,
    )
    assert handler._ctx_mgr_pool == [second_manager, first_manager]
    assert len({id(manager) for manager in handler._ctx_mgr_pool}) == 2
    assert handler._deferred_source_cleanup == {}


def test_concurrent_same_source_cleanup_starters_reset_once_and_return_unique_pool() -> None:
    handler = _handler()
    managers = [MagicMock() for _ in range(3)]
    request_ids = [handler.reserve_request("asset-concurrent") for _ in managers]
    for index, (request_id, manager) in enumerate(zip(request_ids, managers)):
        manager._process_index = index
        handler._request_info_map[request_id]._ctx_mgr = manager
        handler.cancel_request(request_id, "request_done")

    start = Barrier(len(request_ids))
    results = []

    def cleanup(request_id):
        start.wait(timeout=2)
        results.append(handler.cleanup_request(request_id))

    threads = [Thread(target=cleanup, args=(request_id,)) for request_id in request_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert results == [True, True, True]
    assert sum(manager.reset.call_count for manager in managers) == 1
    handler.drop_collection_for_asset.assert_called_once()
    drop_args, drop_kwargs = handler.drop_collection_for_asset.call_args
    assert drop_args == ("asset-concurrent",)
    assert drop_kwargs["force_legacy"] is True
    assert drop_kwargs["ctx_mgr"] in managers
    assert len(handler._ctx_mgr_pool) == 3
    assert {id(manager) for manager in handler._ctx_mgr_pool} == {
        id(manager) for manager in managers
    }
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()


def test_same_source_cleanup_reset_disabled_does_not_retain_managers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LVS_DISABLE_DB_RESET_ON_REQUEST_DONE", "true")
    handler = _handler()
    managers = [MagicMock(), MagicMock()]
    for index, manager in enumerate(managers):
        manager._process_index = index

    request_ids = [handler.reserve_request("asset-no-reset") for _ in managers]
    for request_id, manager in zip(request_ids, managers):
        handler._request_info_map[request_id]._ctx_mgr = manager
        handler.cancel_request(request_id, "request_done")

    for request_id in request_ids:
        assert handler.cleanup_request(request_id) is True

    for manager in managers:
        manager.reset.assert_not_called()
    handler.drop_collection_for_asset.assert_not_called()
    assert handler._ctx_mgr_pool == managers
    assert handler._deferred_source_cleanup == {}


def test_deferred_cleanup_reset_exception_releases_barrier_and_managers() -> None:
    handler = _handler()
    manager = MagicMock()
    manager._process_index = 1
    manager.reset.side_effect = RuntimeError("reset failed")

    rag_id = handler.reserve_request("asset-reset-error")
    caption_id = handler.reserve_request("asset-reset-error")
    handler._request_info_map[rag_id]._ctx_mgr = manager
    for request_id in (rag_id, caption_id):
        handler.cancel_request(request_id, "request_done")

    assert handler.cleanup_request(rag_id) is True
    assert handler.cleanup_request(caption_id) is True

    replacement_id = handler.reserve_request("asset-reset-error")
    assert replacement_id in handler._request_info_map
    assert handler._ctx_mgr_pool == [manager]
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()
    handler.cancel_request(replacement_id, "test_cleanup")
    assert handler.cleanup_request(replacement_id) is True


def test_deferred_cleanup_base_exception_still_returns_manager_and_clears_barrier() -> None:
    class FatalReset(BaseException):
        pass

    handler = _handler()
    manager = MagicMock()
    manager._process_index = 1
    manager.reset.side_effect = FatalReset("fatal reset")

    rag_id = handler.reserve_request("asset-fatal-reset")
    caption_id = handler.reserve_request("asset-fatal-reset")
    handler._request_info_map[rag_id]._ctx_mgr = manager
    for request_id in (rag_id, caption_id):
        handler.cancel_request(request_id, "request_done")

    assert handler.cleanup_request(rag_id) is True
    with pytest.raises(FatalReset, match="fatal reset"):
        handler.cleanup_request(caption_id)

    assert handler._ctx_mgr_pool == [manager]
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()
    replacement_id = handler.reserve_request("asset-fatal-reset")
    handler.cancel_request(replacement_id, "test_cleanup")
    assert handler.cleanup_request(replacement_id) is True


def test_remove_rtsp_stream_waits_for_quiescence_and_reconciles_deferred_manager() -> None:
    handler = _handler()
    source_id = "stream-deferred"
    handler._live_stream_info_map[source_id] = types.SimpleNamespace(
        source_id=source_id,
        stop=False,
    )
    manager = MagicMock()
    manager._process_index = 1

    rag_id = handler.reserve_request(source_id)
    active_id = handler.reserve_request(source_id)
    rag = handler._request_info_map[rag_id]
    active = handler._request_info_map[active_id]
    rag._ctx_mgr = manager
    rag.is_live = False
    active.is_live = True
    handler.cancel_request(rag_id, "rag_done")
    assert handler.cleanup_request(rag_id) is True
    assert handler._deferred_source_cleanup[source_id].ctx_mgr is manager
    handler._claim_request(active_id, source_id)

    cancel_sent = Event()
    handler._vlm_pipeline.cancel_request.side_effect = (
        lambda *_args, **_kwargs: cancel_sent.set()
    )
    result = []
    removal_thread = Thread(
        target=lambda: result.append(handler.remove_rtsp_stream(source_id))
    )
    removal_thread.start()
    assert cancel_sent.wait(timeout=1)
    assert handler._vlm_pipeline.remove_live_stream.called
    assert removal_thread.is_alive()
    assert active_id in handler._request_info_map
    assert handler._ctx_mgr_pool == []
    assert source_id in handler._source_teardown_in_progress

    handler._mark_request_cancelled(active)
    handler._request_operation_finished(active)
    removal_thread.join(timeout=2)
    assert not removal_thread.is_alive()
    assert result == [None]

    manager.reset.assert_called_once_with(
        {
            "summarization": {"uuid": source_id},
            "delete_external_collection": False,
        }
    )
    handler.drop_collection_for_asset.assert_called_once_with(
        source_id,
        force_legacy=True,
        ctx_mgr=manager,
    )
    assert handler._ctx_mgr_pool == [manager]
    assert active_id not in handler._request_info_map
    assert active.cleanup_complete
    assert active.cleanup_event.is_set()
    assert source_id not in handler._live_stream_info_map
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()
    assert handler._source_teardown_in_progress == set()


def test_remove_barrier_outlives_preexisting_cleanup_and_blocks_same_source_reserve() -> None:
    handler = _handler()
    source_id = "stream-interleaved"
    handler._live_stream_info_map[source_id] = types.SimpleNamespace(
        source_id=source_id,
        stop=False,
    )
    cleanup_blocked = Event()
    allow_cleanup = Event()

    class BlockingQaManager:
        @property
        def _process_index(self):
            cleanup_blocked.set()
            assert allow_cleanup.wait(timeout=2)
            return 1

    cleanup_id = handler.reserve_request(source_id)
    sibling_id = handler.reserve_request(source_id)
    cleanup_request = handler._request_info_map[cleanup_id]
    cleanup_request._qa_ctx_mgr = BlockingQaManager()
    handler.cancel_request(cleanup_id, "cleanup_started")

    cleanup_result = []
    cleanup_thread = Thread(
        target=lambda: cleanup_result.append(handler.cleanup_request(cleanup_id))
    )
    cleanup_thread.start()
    assert cleanup_blocked.wait(timeout=1)

    removal_result = []
    removal_thread = Thread(
        target=lambda: removal_result.append(handler.remove_rtsp_stream(source_id))
    )
    removal_thread.start()
    deadline = time.monotonic() + 1
    while source_id not in handler._source_teardown_in_progress:
        assert time.monotonic() < deadline
    assert removal_thread.is_alive()

    same_source_reserved = Event()
    reserved_ids = []

    def reserve_same_source():
        reserved_ids.append(handler.reserve_request(source_id))
        same_source_reserved.set()

    reserve_thread = Thread(target=reserve_same_source)
    reserve_thread.start()
    assert not same_source_reserved.wait(timeout=0.05)
    unrelated_id = handler.reserve_request("stream-unrelated")
    assert unrelated_id in handler._request_info_map

    allow_cleanup.set()
    cleanup_thread.join(timeout=2)
    removal_thread.join(timeout=2)
    reserve_thread.join(timeout=2)
    assert not cleanup_thread.is_alive()
    assert not removal_thread.is_alive()
    assert not reserve_thread.is_alive()
    assert cleanup_result == [True]
    assert removal_result == [None]
    assert same_source_reserved.is_set()
    assert sibling_id not in handler._request_info_map
    assert handler._source_cleanup_in_progress == set()
    assert handler._source_teardown_in_progress == set()

    for request_id in (reserved_ids[0], unrelated_id):
        handler.cancel_request(request_id, "test_cleanup")
        assert handler.cleanup_request(request_id) is True


def test_stop_waits_for_active_file_quiescence_and_terminates_unique_managers(
    monkeypatch,
) -> None:
    monkeypatch.setitem(
        ViaStreamHandler.stop.__globals__,
        "safe_log",
        lambda *_args, **_kwargs: None,
    )
    handler = _handler()
    calls = []
    deferred_manager = MagicMock()
    deferred_manager._process_index = 1
    active_manager = MagicMock()
    active_manager._process_index = 2
    pooled_manager = MagicMock()
    pooled_manager._process_index = 3
    qa_manager = MagicMock()
    qa_manager._process_index = 4
    deferred_manager.reset.side_effect = lambda *_args, **_kwargs: calls.append(
        "deferred_reset"
    )
    active_manager.reset.side_effect = lambda *_args, **_kwargs: calls.append(
        "active_reset"
    )
    handler.drop_collection_for_asset.side_effect = (
        lambda *_args, **_kwargs: calls.append("drop")
        or {"acknowledged": True}
    )
    for name, manager in (
        ("deferred", deferred_manager),
        ("active", active_manager),
        ("pooled", pooled_manager),
        ("qa", qa_manager),
    ):
        manager.process.kill.side_effect = lambda name=name: calls.append(
            f"kill_{name}"
        )

    rag_id = handler.reserve_request("file-deferred")
    caption_id = handler.reserve_request("file-deferred")
    handler._request_info_map[rag_id]._ctx_mgr = deferred_manager
    handler.cancel_request(rag_id, "rag_done")
    assert handler.cleanup_request(rag_id) is True
    caption = handler._claim_request(caption_id, "file-deferred")

    active_id = handler.reserve_request("file-active")
    active = handler._claim_request(active_id, "file-active")
    active._ctx_mgr = active_manager
    active._qa_ctx_mgr = qa_manager
    # Deliberately duplicate identities across ownership locations to prove
    # shutdown terminates by identity, not by container membership.
    handler._ctx_mgr_pool = [pooled_manager, active_manager]
    handler._qa_ctx_mgr_pool = [qa_manager]

    all_cancelled = Event()
    cancelled_ids = set()

    def observe_cancel(request_id, _reason):
        cancelled_ids.add(request_id)
        if cancelled_ids == {caption_id, active_id}:
            all_cancelled.set()

    handler._vlm_pipeline.cancel_request.side_effect = observe_cancel
    stop_errors = []

    def run_stop():
        try:
            handler.stop()
        except BaseException as ex:
            stop_errors.append(ex)

    stop_thread = Thread(target=run_stop)
    stop_thread.start()
    assert all_cancelled.wait(timeout=2), (
        cancelled_ids,
        stop_thread.is_alive(),
        stop_errors,
        handler._source_cleanup_in_progress,
        handler._source_teardown_in_progress,
    )
    assert stop_thread.is_alive()
    for manager in (
        deferred_manager,
        active_manager,
        pooled_manager,
        qa_manager,
    ):
        manager.process.kill.assert_not_called()

    for request in (caption, active):
        handler._mark_request_cancelled(request)
        handler._request_operation_finished(request)
    stop_thread.join(timeout=2)
    assert not stop_thread.is_alive()

    for manager in (
        deferred_manager,
        active_manager,
        pooled_manager,
        qa_manager,
    ):
        manager.process.kill.assert_called_once_with()
        manager.process.join.assert_called_once_with(timeout=2)
    deferred_manager.reset.assert_called_once()
    active_manager.reset.assert_called_once()
    assert handler.drop_collection_for_asset.call_count == 2
    first_kill_index = min(
        index for index, call in enumerate(calls) if call.startswith("kill_")
    )
    assert all(index < first_kill_index for index, call in enumerate(calls) if call == "drop")
    handler._vlm_pipeline.stop.assert_called_once_with(force=True)
    assert active._ctx_mgr is None
    assert active._qa_ctx_mgr is None
    assert handler._ctx_mgr_pool == []
    assert handler._qa_ctx_mgr_pool == []
    assert handler._request_info_map == {}
    assert handler._deferred_source_cleanup == {}
    assert handler._source_cleanup_in_progress == set()
    assert handler._source_teardown_in_progress == set()
    assert caption.cleanup_complete and caption.cleanup_event.is_set()
    assert active.cleanup_complete and active.cleanup_event.is_set()


def test_source_cleanup_barrier_blocks_same_source_reserve_only() -> None:
    handler = _handler()
    calls = []
    reset_started = Event()
    allow_reset = Event()
    same_source_reserve_started = Event()
    same_source_reserved = Event()
    cleanup_finished = Event()

    ctx_mgr = MagicMock()
    ctx_mgr._process_index = 1

    def reset(_config):
        calls.append("reset_started")
        reset_started.set()
        assert allow_reset.wait(timeout=2)
        calls.append("reset_finished")

    ctx_mgr.reset.side_effect = reset
    handler.drop_collection_for_asset.side_effect = lambda *_args, **_kwargs: (
        calls.append("drop_finished") or {"acknowledged": True}
    )

    request_id = handler.reserve_request("asset-shared")
    request = handler._request_info_map[request_id]
    request._ctx_mgr = ctx_mgr
    handler.cancel_request(request_id, "request_done")

    def clean_request():
        assert handler.cleanup_request(request_id) is True
        cleanup_finished.set()

    cleanup_thread = Thread(target=clean_request)
    cleanup_thread.start()
    assert reset_started.wait(timeout=1)

    reserved_ids = []

    def reserve_same_source():
        same_source_reserve_started.set()
        reserved_ids.append(handler.reserve_request("asset-shared"))
        calls.append("same_source_reserved")
        same_source_reserved.set()

    reserve_thread = Thread(target=reserve_same_source)
    reserve_thread.start()
    assert same_source_reserve_started.wait(timeout=1)
    assert not same_source_reserved.wait(timeout=0.05)

    unrelated_id = handler.reserve_request("asset-unrelated")
    assert unrelated_id in handler._request_info_map
    assert not cleanup_finished.is_set()

    allow_reset.set()
    cleanup_thread.join(timeout=2)
    reserve_thread.join(timeout=2)
    assert not cleanup_thread.is_alive()
    assert not reserve_thread.is_alive()
    assert calls == [
        "reset_started",
        "reset_finished",
        "drop_finished",
        "same_source_reserved",
    ]
    assert reserved_ids[0] in handler._request_info_map
    assert handler._source_cleanup_in_progress == set()

    for pending_id in (reserved_ids[0], unrelated_id):
        handler.cancel_request(pending_id, "test_cleanup")
        assert handler.cleanup_request(pending_id) is True


def test_initial_db_reset_blocks_concurrent_configuration_until_winner_finishes(
    monkeypatch,
) -> None:
    monkeypatch.delenv("VSS_DISABLE_DB_RESET_ON_INIT", raising=False)
    handler = _handler()
    handler.first_init = True
    managers = [MagicMock(), MagicMock()]
    reset_started = Event()
    allow_reset = Event()
    loser_started = Event()
    loser_finished = Event()
    calls = []

    def reset(_config):
        calls.append("winner_reset_started")
        reset_started.set()
        assert allow_reset.wait(timeout=2)
        calls.append("winner_reset_finished")

    managers[0].reset.side_effect = reset

    def initialize_winner():
        handler._configure_ctx_mgr_with_initial_reset(managers[0], {"request": 0})

    def initialize_loser():
        loser_started.set()
        handler._configure_ctx_mgr_with_initial_reset(managers[1], {"request": 1})
        calls.append("loser_configured")
        loser_finished.set()

    winner = Thread(target=initialize_winner)
    winner.start()
    assert reset_started.wait(timeout=1)
    loser = Thread(target=initialize_loser)
    loser.start()
    assert loser_started.wait(timeout=1)
    assert not loser_finished.wait(timeout=0.05)
    managers[1].configure.assert_not_called()

    allow_reset.set()
    winner.join(timeout=2)
    loser.join(timeout=2)
    assert not winner.is_alive()
    assert not loser.is_alive()

    managers[0].configure.assert_called_once_with(config={"request": 0})
    managers[1].configure.assert_called_once_with(config={"request": 1})
    assert sum(manager.reset.call_count for manager in managers) == 1
    assert calls == [
        "winner_reset_started",
        "winner_reset_finished",
        "loser_configured",
    ]
    assert handler._initial_db_reset_state == "succeeded"
    assert handler.first_init is False


def test_initial_db_reset_failure_is_sticky_and_fails_waiters_closed(monkeypatch) -> None:
    monkeypatch.delenv("VSS_DISABLE_DB_RESET_ON_INIT", raising=False)
    handler = _handler()
    handler.first_init = True
    winner_manager = MagicMock()
    loser_manager = MagicMock()
    failure = RuntimeError("erase failed")
    winner_manager.reset.side_effect = failure

    with pytest.raises(RuntimeError, match="erase failed"):
        handler._configure_ctx_mgr_with_initial_reset(
            winner_manager,
            {"request": "winner"},
        )
    with pytest.raises(RuntimeError, match="Initial CA-RAG database reset failed") as exc:
        handler._configure_ctx_mgr_with_initial_reset(
            loser_manager,
            {"request": "loser"},
        )

    assert exc.value.__cause__ is failure
    loser_manager.configure.assert_not_called()
    loser_manager.reset.assert_not_called()
    assert handler._initial_db_reset_state == "failed"
    assert handler._initial_db_reset_error is failure


def test_post_init_configure_does_not_hold_handler_lock(monkeypatch) -> None:
    monkeypatch.delenv("VSS_DISABLE_DB_RESET_ON_INIT", raising=False)
    handler = _handler()
    handler.first_init = False
    handler._initial_db_reset_state = "succeeded"
    manager = MagicMock()
    configure_started = Event()
    allow_configure = Event()
    reserve_finished = Event()
    reserved_ids = []

    def configure(*, config):
        configure_started.set()
        assert allow_configure.wait(timeout=2)

    manager.configure.side_effect = configure

    configure_thread = Thread(
        target=handler._configure_ctx_mgr_with_initial_reset,
        args=(manager, {"request": "post-init"}),
    )
    configure_thread.start()
    assert configure_started.wait(timeout=1)

    def reserve_unrelated():
        reserved_ids.append(handler.reserve_request("asset-unrelated"))
        reserve_finished.set()

    reserve_thread = Thread(target=reserve_unrelated)
    reserve_thread.start()
    reserve_completed_while_configure_blocked = reserve_finished.wait(timeout=0.1)
    allow_configure.set()
    configure_thread.join(timeout=2)
    reserve_thread.join(timeout=2)

    assert reserve_completed_while_configure_blocked
    assert not configure_thread.is_alive()
    assert not reserve_thread.is_alive()
    assert reserved_ids[0] in handler._request_info_map
    handler.cancel_request(reserved_ids[0], "test_cleanup")
    assert handler.cleanup_request(reserved_ids[0]) is True


def test_rtvi_generation_and_cancel_share_exact_owner_id() -> None:
    handler = _handler()
    request_id = handler.reserve_request("asset-shared")
    request = handler._claim_request(request_id, "asset-shared")
    request._ctx_mgr = None
    request._output_process_thread_pool = None
    request.source_url = "https://example.invalid/video.mp4"
    observed = {}

    def generate(**kwargs):
        observed.update(kwargs)
        handler.cancel_request(request_id, "disconnect_during_rtvi")
        yield {"chunk_responses": []}

    handler._vlm_pipeline.generate_captions_stream.side_effect = generate
    handler._vlm_pipeline.get_models_info.return_value = types.SimpleNamespace(
        id="model"
    )

    handler._trigger_query(request)

    assert observed["owner_id"] == request_id
    handler._vlm_pipeline.cancel_request.assert_called_once_with(
        request_id, "disconnect_during_rtvi"
    )
    assert request.status is RequestInfo.Status.CANCELLED
    handler._request_operation_finished(request)
    assert request.quiescent_event.is_set()


def test_sse_client_removal_is_identity_safe() -> None:
    server = ViaServer.__new__(ViaServer)
    server._sse_active_clients = {}
    server._touch_sse_client("asset-shared", "old-request")
    server._touch_sse_client("asset-shared", "replacement-request")

    assert server._remove_sse_client("asset-shared", "old-request") is False
    assert server._sse_active_clients["asset-shared"][0] == "replacement-request"
    assert server._remove_sse_client("asset-shared", "replacement-request") is True
    assert server._sse_active_clients == {}
