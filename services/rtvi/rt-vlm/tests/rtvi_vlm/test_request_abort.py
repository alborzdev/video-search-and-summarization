# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Dependency-free exact-request abort tests for source-tree verification."""

import ast
import asyncio
from pathlib import Path
from threading import Event, Lock, RLock, Thread
import time
from types import MethodType, SimpleNamespace
from typing import Callable, Optional
from unittest.mock import MagicMock, call

import pytest


SRC = Path(__file__).resolve().parents[2] / "src"


def _load_method(path: Path, class_name: str, method_name: str, globals_: dict):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = dict(globals_)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[method_name]


def _pipeline_method(name):
    request_params = SimpleNamespace(
        from_vlm_query=lambda _query: object(),
        from_text_embeddings_query=lambda _query: object(),
    )
    return _load_method(
        SRC / "vlm_pipeline" / "vlm_pipeline.py",
        "VlmPipeline",
        name,
        {
            "Callable": Callable,
            "ChunkInfo": object,
            "Event": Event,
            "logger": MagicMock(),
            "Optional": Optional,
            "PipelineChunkResult": object,
            "time": time,
            "TextEmbeddingsQuery": object,
            "VlmQuery": object,
            "VlmRequestParams": request_params,
        },
    )


def _handler_method(name):
    request_info = SimpleNamespace(Status=SimpleNamespace(FAILED="failed", SUCCESSFUL="successful"))
    return _load_method(
        SRC / "server" / "rtvi_stream_handler.py",
        "RTVIStreamHandler",
        name,
        {
            "RequestInfo": request_info,
            "PipelineChunkResult": object,
            "logger": MagicMock(),
            "time": time,
        },
    )


def test_pipeline_abort_waits_for_exact_chunks_then_clears_bounded_tombstone() -> None:
    pipeline = SimpleNamespace(
        _enqueue_lock=Lock(),
        _aborted_request_ids=set(),
        _request_enrollment_closed=set(),
        _chunk_callback_map={1: "callback-one", 2: "callback-two"},
        _chunk_request_map={1: "request-one", 2: "request-two"},
        _request_outstanding_chunks={"request-one": 1, "request-two": 1},
        _request_quiescent_events={},
        _decoder_procs=[MagicMock()],
        _vlm_procs=[MagicMock()],
        _asr_procs=[],
    )
    pipeline.wait_for_request_quiescent = MethodType(
        _pipeline_method("wait_for_request_quiescent"), pipeline
    )

    assert _pipeline_method("abort_request")(pipeline, "request-one") is True
    assert pipeline.wait_for_request_quiescent("request-one", timeout=0) is False
    assert pipeline._chunk_callback_map == {1: "callback-one", 2: "callback-two"}

    _pipeline_method("_finish_request_chunk")(pipeline, 1)
    assert pipeline.wait_for_request_quiescent("request-one", timeout=0) is True
    _pipeline_method("complete_request")(pipeline, "request-one")

    assert "request-one" not in pipeline._aborted_request_ids
    assert "request-one" not in pipeline._request_enrollment_closed
    assert "request-one" not in pipeline._request_quiescent_events
    assert pipeline._chunk_callback_map == {1: "callback-one", 2: "callback-two"}
    for process in pipeline._decoder_procs + pipeline._vlm_procs:
        assert process.send_command.call_args_list[0].args == ("drop-request",)
        assert process.send_command.call_args_list[1].args == ("clear-drop-request",)


def test_local_tombstones_are_bounded_even_if_one_worker_clear_fails() -> None:
    failed_process = MagicMock()
    failed_process.send_command.side_effect = RuntimeError("worker unavailable")
    healthy_process = MagicMock()
    quiescent = Event()
    quiescent.set()
    pipeline = SimpleNamespace(
        _enqueue_lock=Lock(),
        _aborted_request_ids={"request-one"},
        _request_enrollment_closed={"request-one"},
        _request_outstanding_chunks={"request-one": 0},
        _request_quiescent_events={"request-one": quiescent},
        _decoder_procs=[failed_process, healthy_process],
        _vlm_procs=[],
        _asr_procs=[],
    )
    pipeline.wait_for_request_quiescent = MethodType(
        _pipeline_method("wait_for_request_quiescent"), pipeline
    )

    with pytest.raises(RuntimeError, match="failed to clear request suppression"):
        _pipeline_method("complete_request")(pipeline, "request-one")

    healthy_process.send_command.assert_called_once_with(
        "clear-drop-request", request_id="request-one"
    )
    assert "request-one" not in pipeline._aborted_request_ids
    assert "request-one" not in pipeline._request_enrollment_closed
    assert "request-one" not in pipeline._request_outstanding_chunks
    assert "request-one" not in pipeline._request_quiescent_events


def test_abort_atomically_closes_enrollment_and_rejects_late_gpu_work() -> None:
    decoder = MagicMock()
    pipeline = SimpleNamespace(
        _enqueue_lock=Lock(),
        _aborted_request_ids=set(),
        _request_enrollment_closed=set(),
        _chunk_callback_map={},
        _chunk_request_map={},
        _request_outstanding_chunks={},
        _request_quiescent_events={},
        _chunk_counter=0,
        _decoder_procs=[decoder],
        _vlm_procs=[],
        _asr_procs=[],
        _args=SimpleNamespace(num_gpus=1),
    )
    pipeline.wait_for_request_quiescent = MethodType(
        _pipeline_method("wait_for_request_quiescent"), pipeline
    )

    assert _pipeline_method("abort_request")(pipeline, "request-one") is True
    assert pipeline.wait_for_request_quiescent("request-one", timeout=0) is True
    assert (
        _pipeline_method("enqueue_chunk")(
            pipeline,
            object(),
            lambda _response: None,
            object(),
            request_id="request-one",
        )
        is False
    )
    assert pipeline._request_outstanding_chunks.get("request-one", 0) == 0
    decoder.enqueue_chunk.assert_not_called()


def test_new_enrollment_clears_a_preexisting_quiescent_event() -> None:
    decoder = MagicMock()
    quiescent = Event()
    quiescent.set()
    pipeline = SimpleNamespace(
        _enqueue_lock=Lock(),
        _aborted_request_ids=set(),
        _request_enrollment_closed=set(),
        _chunk_callback_map={},
        _chunk_request_map={},
        _request_outstanding_chunks={},
        _request_quiescent_events={"request-one": quiescent},
        _chunk_counter=0,
        _decoder_procs=[decoder],
        _args=SimpleNamespace(num_gpus=1),
    )

    assert _pipeline_method("enqueue_chunk")(
        pipeline,
        object(),
        lambda _response: None,
        object(),
        request_id="request-one",
    )
    assert not quiescent.is_set()
    assert pipeline._request_outstanding_chunks["request-one"] == 1


def test_legacy_empty_request_id_does_not_create_unfinishable_state() -> None:
    decoder = MagicMock()
    pipeline = SimpleNamespace(
        _enqueue_lock=Lock(),
        _request_enrollment_closed=set(),
        _chunk_callback_map={},
        _chunk_request_map={},
        _request_outstanding_chunks={},
        _request_quiescent_events={},
        _chunk_counter=0,
        _decoder_procs=[decoder],
        _args=SimpleNamespace(num_gpus=1),
    )

    assert _pipeline_method("enqueue_chunk")(
        pipeline,
        object(),
        lambda _response: None,
        object(),
    )
    assert pipeline._chunk_request_map == {}
    assert pipeline._request_outstanding_chunks == {}
    assert pipeline._request_quiescent_events == {}


def _request(request_id, asset, *, is_live=False):
    return SimpleNamespace(
        request_id=request_id,
        finalized=False,
        finalization_started=False,
        abort_requested=False,
        abort_complete_event=Event(),
        status="processing",
        error_message="",
        error_status_code=500,
        end_time=None,
        is_live=is_live,
        pipeline_stream_id=f"pipeline-{request_id}",
        text_query=None,
        _monitor=None,
        _request_metrics=None,
        assets=[asset],
        vlm_pipeline_span=None,
        _e2e_span=None,
        status_event=Event(),
    )


def test_file_abort_proves_quiescence_before_asset_unlock_and_acknowledgement() -> None:
    asset = SimpleNamespace(use_count=2, unlock=MagicMock())
    first = _request("request-one", asset)
    sibling = _request("request-two", asset)
    pipeline = MagicMock()

    def wait_for_quiescence(request_id):
        assert request_id == first.request_id
        asset.unlock.assert_not_called()
        assert not first.abort_complete_event.is_set()
        return True

    pipeline.wait_for_request_quiescent.side_effect = wait_for_quiescence
    handler = SimpleNamespace(
        _lock=RLock(),
        _request_info_map={first.request_id: first, sibling.request_id: sibling},
        _vlm_pipeline=pipeline,
        _metrics=MagicMock(),
        stop_request_profiling=MagicMock(),
        _cleanup_request_files=MagicMock(),
    )

    assert _handler_method("abort_request")(handler, first.request_id) is True
    pipeline.abort_request.assert_called_once_with(first.request_id)
    pipeline.wait_for_request_quiescent.assert_called_once_with(first.request_id)
    pipeline.complete_request.assert_called_once_with(first.request_id)
    asset.unlock.assert_called_once_with()
    assert first.abort_complete_event.is_set()
    assert handler._request_info_map == {sibling.request_id: sibling}


def test_live_abort_removes_unique_pipeline_stream_and_preserves_asset_sibling() -> None:
    asset = SimpleNamespace(use_count=2, unlock=MagicMock())
    first = _request("request-one", asset, is_live=True)
    sibling = _request("request-two", asset, is_live=True)
    handler = SimpleNamespace(
        _lock=RLock(),
        _request_info_map={first.request_id: first, sibling.request_id: sibling},
        _vlm_pipeline=MagicMock(),
        _metrics=MagicMock(),
        stop_request_profiling=MagicMock(),
        _cleanup_request_files=MagicMock(),
    )
    handler._vlm_pipeline.abort_live_stream_exact.return_value = True

    assert _handler_method("abort_request")(handler, first.request_id) is True
    handler._vlm_pipeline.abort_live_stream_exact.assert_called_once_with(
        "pipeline-request-one"
    )
    handler._vlm_pipeline.abort_request.assert_not_called()
    assert handler._request_info_map[sibling.request_id] is sibling


def test_live_abort_does_not_unlock_until_exact_drain_can_be_proven() -> None:
    asset = SimpleNamespace(use_count=1, unlock=MagicMock())
    request = _request("request-one", asset, is_live=True)
    handler = SimpleNamespace(
        _lock=RLock(),
        _request_info_map={request.request_id: request},
        _vlm_pipeline=MagicMock(),
        _metrics=MagicMock(),
        stop_request_profiling=MagicMock(),
        _cleanup_request_files=MagicMock(),
    )
    handler._vlm_pipeline.abort_live_stream_exact.return_value = False
    abort_request = _handler_method("abort_request")

    assert abort_request(handler, request.request_id) is False
    assert handler._request_info_map[request.request_id] is request
    assert request.finalization_started is False
    assert request.finalized is False
    asset.unlock.assert_not_called()

    handler._vlm_pipeline.abort_live_stream_exact.return_value = True
    assert abort_request(handler, request.request_id) is True
    asset.unlock.assert_called_once_with()
    assert request.request_id not in handler._request_info_map


def test_exact_live_abort_timeout_keeps_drop_guards_and_ownership() -> None:
    decoder = MagicMock()
    vlm = MagicMock()
    stream_info = SimpleNamespace(gpu_id=0, all_chunks_processed=False)
    pipeline = SimpleNamespace(
        _live_stream_id_map={"pipeline-request": stream_info},
        _decoder_procs=[decoder],
        _vlm_procs=[vlm],
        _asr_procs=[],
    )
    abort_live = _pipeline_method("abort_live_stream_exact")

    assert abort_live(pipeline, "pipeline-request", timeout_sec=0) is False
    assert pipeline._live_stream_id_map["pipeline-request"] is stream_info
    assert vlm.send_command.call_args_list == [
        call("drop-chunks", stream_id="pipeline-request")
    ]

    stream_info.all_chunks_processed = True
    assert abort_live(pipeline, "pipeline-request", timeout_sec=0) is True
    assert "pipeline-request" not in pipeline._live_stream_id_map
    assert vlm.send_command.call_args_list[-1] == call(
        "stop-drop-chunks", stream_id="pipeline-request"
    )


def test_file_error_suppression_is_exact_and_teardown_is_deferred() -> None:
    executor = MagicMock()
    request = SimpleNamespace(request_id="request-one")
    handler = SimpleNamespace(
        _vlm_pipeline=MagicMock(),
        _cleanup_executor=executor,
        abort_request=MagicMock(),
    )

    _handler_method("_abort_failed_file_request")(handler, request)

    handler._vlm_pipeline.abort_request.assert_called_once_with("request-one")
    handler._vlm_pipeline.abort_chunks.assert_not_called()
    executor.submit.assert_called_once_with(handler.abort_request, "request-one")


def test_saved_response_publication_is_serialized_against_abort_claim() -> None:
    entered = Event()
    release = Event()
    request = SimpleNamespace(
        abort_requested=False,
        finalization_started=False,
        chunk_count=0,
    )

    def publish(_response, _request):
        entered.set()
        assert release.wait(timeout=1)

    handler = SimpleNamespace(
        _lock=RLock(),
        _on_vlm_chunk_response=MagicMock(side_effect=publish),
    )
    method = _handler_method("_publish_saved_response_if_active")
    worker = Thread(target=method, args=(handler, request, object()))
    worker.start()
    assert entered.wait(timeout=1)
    assert handler._lock.acquire(blocking=False) is False
    release.set()
    worker.join(timeout=1)

    assert request.chunk_count == 1
    request.abort_requested = True
    assert method(handler, request, object()) is False
    assert request.chunk_count == 1
    handler._on_vlm_chunk_response.assert_called_once()


def test_entered_callback_rechecks_abort_after_blocking_conversion() -> None:
    req = SimpleNamespace(request_id="request", abort_requested=False, finalized=False)
    handler = SimpleNamespace(_lock=RLock(), _kafka_enabled=True)

    def conversion(*_args):
        req.abort_requested = True
        return MagicMock(), MagicMock()

    handler._chunk_result_to_vision_llm = conversion
    handler._send_protobuf_to_kafka = MagicMock()
    chunk = SimpleNamespace(chunk=SimpleNamespace(chunkIdx=1))

    _handler_method("_on_vlm_chunk_response")(handler, chunk, req)
    handler._send_protobuf_to_kafka.assert_not_called()


def test_chunk_publication_linearizes_before_abort_can_set_terminal_flag() -> None:
    entered = Event()
    release = Event()
    request = SimpleNamespace(
        request_id="request-one",
        stream_id="asset-one",
        abort_requested=False,
        finalized=False,
    )
    chunk = SimpleNamespace(chunk=SimpleNamespace(chunkIdx=1))
    message = MagicMock()

    def serialize():
        entered.set()
        assert release.wait(timeout=1)
        return b"payload"

    message.SerializeToString.side_effect = serialize
    handler = SimpleNamespace(
        _lock=RLock(),
        _send_protobuf_to_kafka=MagicMock(),
        _send_error_message_to_kafka=MagicMock(),
        _kafka_incident_topic=None,
        _kafka_topic="topic",
    )
    method = _handler_method("_publish_chunk_messages_if_active")
    worker = Thread(target=method, args=(handler, chunk, request, message, None))
    worker.start()
    assert entered.wait(timeout=1)
    assert handler._lock.acquire(blocking=False) is False
    release.set()
    worker.join(timeout=1)

    handler._send_protobuf_to_kafka.assert_called_once_with(
        b"payload", chunk, request
    )
    request.abort_requested = True
    assert method(handler, chunk, request, message, None) is False
    message.SerializeToString.assert_called_once_with()


def test_event_source_constructor_failure_aborts_and_awaits_exact_request() -> None:
    class ServiceError(Exception):
        pass

    def broken_response(*_args, **_kwargs):
        raise RuntimeError("constructor failed")

    method = _load_method(
        SRC / "server" / "rtvi_vlm_server.py",
        "RTVIServer",
        "_create_caption_stream_response",
        {
            "EventSourceResponse": broken_response,
            "asyncio": asyncio,
            "VLM_CAPTIONS_ERROR_MESSAGE": "%s",
            "logger": MagicMock(),
            "ServiceException": ServiceError,
        },
    )
    handler = SimpleNamespace(
        abort_request=MagicMock(return_value=True),
        _send_error_message_to_kafka=MagicMock(),
    )
    server = SimpleNamespace(_async_executor=None, _stream_handler=handler)

    with pytest.raises(ServiceError):
        asyncio.run(method(server, iter(()), "request-one", "asset-one"))
    handler.abort_request.assert_called_once_with("request-one")


def test_routes_preserve_legacy_stream_delete_and_add_distinct_exact_delete() -> None:
    source = (SRC / "server" / "rtvi_vlm_server.py").read_text(encoding="utf-8")
    assert 'f"{API_PREFIX}/generate_captions/requests/{{request_id}}"' in source
    assert 'f"{API_PREFIX}/generate_captions/{{stream_id}}"' in source
    assert "self._stream_handler.remove_rtsp_stream, asset" in source
    assert 'headers={"x-request-id": request_id}' in source


def test_process_queue_drop_is_request_scoped_and_clearable() -> None:
    source = (SRC / "vlm_pipeline" / "process_base.py").read_text(encoding="utf-8")
    assert "item.get(\"request_id\") in self._drop_request_ids" in source
    assert 'self._drop_request_ids.add(cmd["request_id"])' in source
    assert 'self._drop_request_ids.discard(cmd["request_id"])' in source


def test_terminal_output_signals_status_in_finally() -> None:
    request = SimpleNamespace(
        request_id="request-one",
        is_live=False,
        assets=[],
        processed_chunk_list=[],
        response=[],
        vlm_testdata_file_handle=None,
        status="processing",
        end_time=None,
        start_time=time.time(),
        text_query=True,
        _e2e_span=None,
        vlm_pipeline_span=None,
        chunk_count=0,
        finalized=False,
        finalization_started=False,
        status_event=Event(),
        abort_complete_event=Event(),
    )
    handler = SimpleNamespace(
        _lock=RLock(),
        _args=SimpleNamespace(enable_dev_dc_gen=False),
        _metrics=MagicMock(),
        stop_request_profiling=MagicMock(side_effect=RuntimeError("profiling")),
        _cleanup_request_files=MagicMock(side_effect=RuntimeError("files")),
    )
    handler._metrics._queries_processed_counter.add.side_effect = RuntimeError("metrics")

    _handler_method("_process_output")(handler, request, False, [])

    assert request.status == "successful"
    assert request.finalized is True
    assert request.status_event.is_set()
    assert request.abort_complete_event.is_set()


def test_terminal_response_failure_marks_failed_but_still_cleans_once() -> None:
    class InvalidSortChunk:
        chunk_type = "text"

        @property
        def chunkIdx(self):
            raise ValueError("invalid chunk ordering")

    asset = SimpleNamespace(use_count=1, unlock=MagicMock())
    request = SimpleNamespace(
        request_id="request-one",
        is_live=False,
        assets=[asset],
        processed_chunk_list=[],
        response=[],
        vlm_testdata_file_handle=None,
        status="processing",
        error_message="",
        error_status_code=200,
        end_time=None,
        start_time=time.time(),
        text_query=True,
        _e2e_span=None,
        vlm_pipeline_span=None,
        chunk_count=1,
        finalized=False,
        finalization_started=False,
        status_event=Event(),
        abort_complete_event=Event(),
    )
    handler = SimpleNamespace(
        _lock=RLock(),
        _args=SimpleNamespace(enable_dev_dc_gen=False),
        _metrics=MagicMock(),
        stop_request_profiling=MagicMock(),
        _cleanup_request_files=MagicMock(),
    )
    response = SimpleNamespace(chunk=InvalidSortChunk())

    _handler_method("_process_output")(handler, request, False, [response])

    assert request.status == "failed"
    assert request.error_status_code == 500
    assert request.finalized is True
    handler.stop_request_profiling.assert_called_once_with(request, [response])
    handler._cleanup_request_files.assert_called_once_with(request)
    asset.unlock.assert_called_once_with()
    assert request.abort_complete_event.is_set()
