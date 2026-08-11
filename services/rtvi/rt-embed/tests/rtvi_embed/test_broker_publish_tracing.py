# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for request-correlated Kafka and Redis publication spans."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from threading import RLock

from server.rtvi_stream_handler import RequestInfo, RTVIStreamHandler
from utils.otel_helper import _service_resource_attributes


class _KafkaFuture:
    def __init__(self):
        self._failed = False

    def add_callback(self, callback):
        if not self._failed:
            callback(SimpleNamespace(topic="owned-embed-topic", partition=2, offset=17))
        return self

    def add_errback(self, callback):
        return self


def _bare_handler() -> RTVIStreamHandler:
    handler = object.__new__(RTVIStreamHandler)
    handler._lock = RLock()
    handler._stopping = False
    handler._kafka_topic = "owned-embed-topic"
    handler._kafka_error_topic = "owned-error-topic"
    handler._redis_error_channel = "owned-error-channel"
    handler._podname = "rtvi-embed-test"
    handler._submit_kafka_send = lambda _description, callback: (callback(), True)[1]
    handler._submit_redis_publish = lambda _description, callback: (callback(), True)[1]
    return handler


def _request_info() -> RequestInfo:
    req_info = RequestInfo(request_id="owned-request-id")
    req_info.assets = [SimpleNamespace(asset_id="owned-stream-id")]
    req_info._e2e_span = MagicMock(name="parent_e2e_span")
    return req_info


def test_kafka_publish_span_is_correlated_to_request_and_parent():
    handler = _bare_handler()
    producer = MagicMock()
    producer.config = {"bootstrap_servers": ["broker:9092"]}
    producer.send.return_value = _KafkaFuture()
    handler._kafka_producer = producer
    req_info = _request_info()
    chunk_result = SimpleNamespace(chunk=SimpleNamespace(chunkIdx=7))
    tracer = MagicMock()
    span = MagicMock()
    tracer.start_span.return_value = span

    with patch("server.rtvi_stream_handler.get_tracer", return_value=tracer):
        handler._send_protobuf_to_kafka(b"protobuf", chunk_result, req_info)

    tracer.start_span.assert_called_once()
    assert tracer.start_span.call_args.args[0] == "Kafka Publish"
    assert tracer.start_span.call_args.kwargs["context"] is not None
    span.set_attribute.assert_any_call("messaging.system", "kafka")
    span.set_attribute.assert_any_call("messaging.destination.name", "owned-embed-topic")
    span.set_attribute.assert_any_call("request_id", "owned-request-id")
    span.set_attribute.assert_any_call("stream_id", "owned-stream-id")
    span.set_attribute.assert_any_call("chunk_idx", 7)
    span.end.assert_called_once()


def test_redis_error_publish_span_is_correlated_to_request_and_parent():
    handler = _bare_handler()
    redis_client = MagicMock()
    redis_client.publish.return_value = 1
    handler._redis_client = redis_client
    req_info = _request_info()
    tracer = MagicMock()
    span = MagicMock()
    tracer.start_span.return_value = span

    with patch("server.rtvi_stream_handler.get_tracer", return_value=tracer):
        handler._send_error_message_to_redis(
            "owned test error",
            "owned-stream-id",
            req_info=req_info,
        )

    tracer.start_span.assert_called_once()
    assert tracer.start_span.call_args.args[0] == "Redis Error Publish"
    assert tracer.start_span.call_args.kwargs["context"] is not None
    span.set_attribute.assert_any_call("messaging.system", "redis")
    span.set_attribute.assert_any_call("messaging.destination.name", "owned-error-channel")
    span.set_attribute.assert_any_call("request_id", "owned-request-id")
    span.set_attribute.assert_any_call("stream_id", "owned-stream-id")
    span.end.assert_called_once()
    redis_client.publish.assert_called_once()


def test_api_request_context_correlates_pre_pipeline_acquisition_errors():
    tracer = MagicMock()
    parent_span = MagicMock()
    tracer.start_span.return_value = parent_span

    with patch("server.rtvi_stream_handler.get_tracer", return_value=tracer):
        req_info = RTVIStreamHandler._start_api_request_context(
            "owned-stream-id", "http"
        )
        error = RuntimeError("owned acquisition failure")
        RTVIStreamHandler._finish_api_request_context(req_info, exception=error)

    tracer.start_span.assert_called_once_with("Video Embeddings API Request")
    assert req_info._e2e_span is parent_span
    parent_span.set_attribute.assert_any_call("request_id", req_info.request_id)
    parent_span.set_attribute.assert_any_call("stream_id", "owned-stream-id")
    parent_span.set_attribute.assert_any_call("input_transport", "http")
    parent_span.record_exception.assert_called_once_with(error)
    parent_span.end.assert_called_once()


def test_otel_service_name_honors_standard_environment_override(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "owned-thor-service")

    assert _service_resource_attributes("fallback-service", "3.2.1") == {
        "service.name": "owned-thor-service",
        "service.version": "3.2.1",
    }


def test_otel_service_name_uses_call_site_fallback_when_unset(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    assert _service_resource_attributes("fallback-service", "3.2.1") == {
        "service.name": "fallback-service",
        "service.version": "3.2.1",
    }
