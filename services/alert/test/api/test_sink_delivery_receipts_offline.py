# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dependency-free receipt tests for the Elasticsearch and Kafka sinks."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock


def _load_sink_modules():
    root = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "mdx",
            "anomaly",
            "sink",
            "vlm_enhanced_sink",
        )
    )
    package_name = "_offline_receipt_sinks"
    package = types.ModuleType(package_name)
    package.__path__ = [root]
    sys.modules[package_name] = package

    stub_names = (
        "elastic",
        "elastic.elastic",
        "its_redis",
        "its_redis.redis_handler",
        "mdx.anomaly.kafka_message_broker",
        "models.responses",
        "utils.event_utils",
        "utils.schema_util",
    )
    saved = {name: sys.modules.get(name) for name in stub_names}
    try:
        for name in stub_names:
            sys.modules[name] = types.ModuleType(name)
        sys.modules["elastic"].__path__ = []
        sys.modules["its_redis"].__path__ = []
        sys.modules["elastic.elastic"].ElasticClient = MagicMock
        sys.modules["elastic.elastic"].ElasticConfig = MagicMock
        sys.modules["its_redis.redis_handler"].RedisHandler = MagicMock
        sys.modules["models.responses"].EnrichmentResponse = MagicMock
        sys.modules["utils.event_utils"].is_alert = lambda message: False
        sys.modules["mdx.anomaly.kafka_message_broker"].KafkaMessageBroker = MagicMock

        class _Proto:
            def SerializeToString(self):
                return b"payload"

        schema_stub = sys.modules["utils.schema_util"]
        schema_stub.convert_behavior_to_protobuf_behavior = lambda document: _Proto()
        schema_stub.convert_incident_to_protobuf_incident = lambda document: _Proto()
        schema_stub.get_nested_field = lambda document, path: None

        loaded = {}
        for module_name in ("sink_base", "sink_elastic", "sink_kafka"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{module_name}",
                os.path.join(root, f"{module_name}.py"),
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded[module_name] = module
        return loaded
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


_modules = _load_sink_modules()
VLMEnhancedElasticSink = _modules["sink_elastic"].VLMEnhancedElasticSink
VLMEnhancedKafkaSink = _modules["sink_kafka"].VLMEnhancedKafkaSink


def test_elastic_none_and_malformed_results_are_unconfirmed():
    assert VLMEnhancedElasticSink._delivery_receipt(None) == {
        "transport": "elastic",
        "outcome": "unconfirmed",
    }
    assert VLMEnhancedElasticSink._delivery_receipt({"result": "created"}) == {
        "transport": "elastic",
        "outcome": "unconfirmed",
    }
    assert VLMEnhancedElasticSink._delivery_receipt(
        {"result": "unexpected", "_id": "doc", "_index": "index"}
    ) == {"transport": "elastic", "outcome": "unconfirmed"}


def test_elastic_concrete_index_response_is_acknowledged():
    assert VLMEnhancedElasticSink._delivery_receipt(
        {"result": "created", "_id": "doc-1", "_index": "events-2026"}
    ) == {
        "transport": "elastic",
        "outcome": "acknowledged",
        "documentId": "doc-1",
        "index": "events-2026",
    }


class _DeliveredMessage:
    def topic(self):
        return "events"

    def partition(self):
        return 2

    def offset(self):
        return 17


class _Producer:
    def __init__(self, *, outcome="ack", remaining=0):
        self.outcome = outcome
        self.remaining = remaining

    def produce(self, **kwargs):
        callback = kwargs["on_delivery"]
        if self.outcome == "ack":
            callback(None, _DeliveredMessage())
        elif self.outcome == "error":
            callback(RuntimeError("broker rejected"), None)

    def flush(self):
        return self.remaining


def _kafka_sink(producer):
    return VLMEnhancedKafkaSink(
        producer=producer,
        incident_route={"topic": "events", "message_type": "incident"},
        alert_route={"topic": "alerts", "message_type": "alert"},
    )


def test_kafka_callback_acknowledgement_propagates_metadata():
    receipt = _kafka_sink(_Producer())._produce(
        "incident", {"id": "event-1", "category": "test"}
    )
    assert receipt == {
        "transport": "kafka",
        "outcome": "acknowledged",
        "topic": "events",
        "partition": 2,
        "offset": 17,
    }


def test_kafka_callback_error_is_failed():
    receipt = _kafka_sink(_Producer(outcome="error"))._produce(
        "incident", {"id": "event-1", "category": "test"}
    )
    assert receipt == {
        "transport": "kafka",
        "outcome": "failed",
        "topic": "events",
    }

def test_kafka_missing_callback_is_never_overclaimed():
    receipt = _kafka_sink(_Producer(outcome="none", remaining=0))._produce(
        "incident", {"id": "event-1", "category": "test"}
    )
    assert receipt == {
        "transport": "kafka",
        "outcome": "submitted_unconfirmed",
        "topic": "events",
    }


def test_kafka_undelivered_queue_is_failed():
    receipt = _kafka_sink(_Producer(outcome="none", remaining=1))._produce(
        "incident", {"id": "event-1", "category": "test"}
    )
    assert receipt == {
        "transport": "kafka",
        "outcome": "failed",
        "topic": "events",
    }
