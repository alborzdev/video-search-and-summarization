# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest


TOOL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOL_DIR.parents[1]
sys.path.insert(0, str(TOOL_DIR))

_missing_module = object()
_original_confluent_kafka = sys.modules.get("confluent_kafka", _missing_module)
_original_redis = sys.modules.get("redis", _missing_module)

# The host qualification environment intentionally does not need live broker
# client packages. Supply their import contracts before loading the utilities.
fake_confluent_kafka = ModuleType("confluent_kafka")


class FakeKafkaErrorType:
    _PARTITION_EOF = -191


fake_confluent_kafka.KafkaError = FakeKafkaErrorType
fake_confluent_kafka.Consumer = Mock
sys.modules["confluent_kafka"] = fake_confluent_kafka

fake_redis = ModuleType("redis")
fake_redis.Redis = Mock
fake_redis.ResponseError = type("ResponseError", (Exception,), {})
sys.modules["redis"] = fake_redis

import base_consumer  # noqa: E402
import kafka_to_file  # noqa: E402
import redis_to_file  # noqa: E402

if _original_confluent_kafka is _missing_module:
    del sys.modules["confluent_kafka"]
else:
    sys.modules["confluent_kafka"] = _original_confluent_kafka
if _original_redis is _missing_module:
    del sys.modules["redis"]
else:
    sys.modules["redis"] = _original_redis


class InMemoryConsumer(base_consumer.BaseMessageConsumer):
    def __init__(self, args, payloads):
        super().__init__(args)
        self.payloads = payloads
        self.consume_calls = []
        self.closed = False

    def get_consumer_type(self):
        return "memory"

    def get_source_names(self):
        return ["mdx-raw"]

    def create_connection(self, source_name, consumer_group, **kwargs):
        return object()

    def consume_messages(self, connection, source_name, consumer_group, **kwargs):
        self.consume_calls.append(kwargs)
        limit = kwargs.get("max_messages") or len(self.payloads)
        for index, payload in enumerate(self.payloads[:limit]):
            yield f"{index}-0", payload
        self.payloads = self.payloads[limit:]

    def acknowledge_messages(self, connection, source_name, consumer_group, message_ids):
        return None

    def close_connection(self, connection):
        self.closed = True

    def get_connection_info(self):
        return "in-memory"

    def get_process_args(self, source_name):
        raise NotImplementedError


class EmptyConsumer(InMemoryConsumer):
    def consume_messages(self, connection, source_name, consumer_group, **kwargs):
        self.consume_calls.append(kwargs)
        return iter(())


class AdvancingClock:
    def __init__(self, step=0.3):
        self.value = 0.0
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


class KafkaMessage:
    def __init__(self, value=None, error=None):
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error


class KafkaMessageError:
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def __str__(self):
        return "redacted test error"


def make_args(**overrides):
    values = {
        "max_messages": 0,
        "timeout_seconds": 0.0,
        "poll_timeout_seconds": 1.0,
        "kafka_broker": "localhost:9092",
        "redis_host": "localhost",
        "redis_port": 6379,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_source_defined_protobuf_and_json_decoders():
    vision = base_consumer.schema_pb2.VisionLLM(version="test-vlm")
    incident = base_consumer.ext_pb2.Incident(sensorId="camera-1", category="entry")

    assert base_consumer.BaseMessageConsumer.decode_message(
        "mdx-vlm-captions", vision.SerializeToString()
    )["version"] == "test-vlm"
    assert base_consumer.BaseMessageConsumer.decode_message(
        "vision-llm-events-incidents", incident.SerializeToString()
    )["sensorId"] == "camera-1"
    assert base_consumer.BaseMessageConsumer.decode_message(
        "vision-llm-errors", b'{"event":"model unavailable"}'
    ) == {"event": "model unavailable"}


def test_newly_mapped_local_topic_decoders():
    frame = base_consumer.schema_pb2.Frame(id="rtls-frame")
    vision = base_consumer.schema_pb2.VisionLLM(version="embed-v1")

    for topic in ("mdx-rtls", "mdx-rtls-region-1"):
        assert base_consumer.BaseMessageConsumer.decode_message(
            topic, frame.SerializeToString()
        )["id"] == "rtls-frame"
    for topic in ("mdx-embed", "mdx-embed-filtered"):
        assert base_consumer.BaseMessageConsumer.decode_message(
            topic, vision.SerializeToString()
        )["version"] == "embed-v1"
    for topic in ("mdx-mtmc", "mdx-amr"):
        assert base_consumer.BaseMessageConsumer.decode_message(
            topic, b'{"id":"json-event"}'
        ) == {"id": "json-event"}


def test_every_infra_provisioned_topic_has_authoritative_wire_mapping():
    compose_path = REPO_ROOT / "deploy/docker/services/infra/compose.yml"
    provisioned_topics = set(
        re.findall(r'\{"name": "(mdx-[^"]+)"', compose_path.read_text())
    )

    expected_wire_types = {
        "mdx-alerts": "Behavior",
        "mdx-amr": "json",
        "mdx-behavior": "Behavior",
        "mdx-behavior-plus": "Behavior",
        "mdx-bev": "Frame",
        "mdx-embed": "VisionLLM",
        "mdx-embed-filtered": "VisionLLM",
        "mdx-events": "Behavior",
        "mdx-frames": "Frame",
        "mdx-incidents": "Incident",
        "mdx-mtmc": "json",
        "mdx-notification": "json",
        "mdx-raw": "Frame",
        "mdx-rtls": "Frame",
        "mdx-rtls-region-1": "Frame",
        "mdx-space-utilization": "SpaceUtilization",
        "mdx-structured-events-summary": "VisionLLM",
        "mdx-vlm": "VisionLLM",
        "mdx-vlm-alerts": "Behavior",
        "mdx-vlm-captions": "VisionLLM",
        "mdx-vlm-incidents": "Incident",
    }

    assert provisioned_topics == set(expected_wire_types)
    assert provisioned_topics == set(base_consumer.LOCAL_PROVISIONED_SOURCES)
    assert not provisioned_topics.difference(base_consumer.SUPPORTED_SOURCES)
    for topic, wire_type in expected_wire_types.items():
        if wire_type == "json":
            assert topic in base_consumer.JSON_SOURCES
        else:
            assert base_consumer.PROTOBUF_SOURCE_TYPES[topic].__name__ == wire_type


def test_original_decoder_name_remains_compatible():
    frame = base_consumer.schema_pb2.Frame(id="frame-1")
    assert base_consumer.BaseMessageConsumer.decode_protobuf_message(
        "mdx-raw", frame.SerializeToString()
    )["id"] == "frame-1"


def test_unknown_or_malformed_source_does_not_emit_payload(caplog):
    assert base_consumer.BaseMessageConsumer.decode_message("unknown", b"secret") is None
    assert base_consumer.BaseMessageConsumer.decode_message("mdx-notification", b"not-json") is None
    assert "secret" not in caplog.text
    assert "not-json" not in caplog.text


def test_message_limit_is_exact_and_passed_to_broker(tmp_path):
    payloads = [
        base_consumer.schema_pb2.Frame(id=f"frame-{index}").SerializeToString()
        for index in range(4)
    ]
    consumer = InMemoryConsumer(make_args(max_messages=2), payloads)
    output_path = tmp_path / "frames.jsonl"

    with patch.object(base_consumer.signal, "signal"):
        stats = consumer.process_source("mdx-raw", output_path, "test-group")

    assert stats == {"read": 2, "written": 2, "errors": 0}
    assert consumer.consume_calls[0]["max_messages"] == 2
    assert [json.loads(line)["id"] for line in output_path.read_text().splitlines()] == [
        "frame-0",
        "frame-1",
    ]
    assert consumer.closed


def test_timeout_bounds_empty_source_and_shortens_poll(tmp_path):
    consumer = EmptyConsumer(
        make_args(timeout_seconds=0.5, poll_timeout_seconds=10.0),
        [],
    )

    with (
        patch.object(base_consumer.signal, "signal"),
        patch.object(base_consumer.time, "monotonic", side_effect=AdvancingClock()),
        patch.object(base_consumer.time, "sleep"),
    ):
        stats = consumer.process_source("mdx-raw", tmp_path / "empty.jsonl", "test-group")

    assert stats == {"read": 0, "written": 0, "errors": 0}
    assert len(consumer.consume_calls) == 1
    assert 0 < consumer.consume_calls[0]["poll_timeout_seconds"] <= 0.5
    assert consumer.closed


def test_decode_failure_is_counted_for_acceptance(tmp_path):
    consumer = InMemoryConsumer(make_args(max_messages=1), [b"not-a-frame"])

    with patch.object(base_consumer.signal, "signal"):
        stats = consumer.process_source("mdx-raw", tmp_path / "bad.jsonl", "test-group")

    assert stats == {"read": 1, "written": 0, "errors": 1}


def test_child_entrypoint_exposes_errors_as_nonzero_exit():
    consumer = InMemoryConsumer(make_args(), [])
    with (
        patch.object(
            consumer,
            "process_source",
            return_value={"read": 1, "written": 0, "errors": 1},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        consumer.process_source_entrypoint("mdx-raw", "unused", "test-group")

    assert exc_info.value.code == 1


def test_kafka_partition_eof_uses_kafka_error_constant():
    connection = Mock()
    connection.poll.return_value = KafkaMessage(
        error=KafkaMessageError(kafka_to_file.KafkaError._PARTITION_EOF)
    )
    consumer = kafka_to_file.KafkaMessageConsumer(make_args())

    assert list(consumer.consume_messages(
        connection,
        "mdx-raw",
        "test-group",
        poll_timeout_seconds=0.25,
    )) == []
    connection.poll.assert_called_once_with(timeout=0.25)


def test_kafka_connection_disables_automatic_offsets():
    connection = Mock()
    consumer = kafka_to_file.KafkaMessageConsumer(make_args())

    with patch.object(kafka_to_file, "Consumer", return_value=connection) as factory:
        assert consumer.create_connection("mdx-raw", "test-group") is connection

    config = factory.call_args.args[0]
    assert config["enable.auto.commit"] is False
    assert config["enable.auto.offset.store"] is False
    connection.subscribe.assert_called_once_with(["mdx-raw"])


def test_kafka_commits_only_after_successful_output(tmp_path):
    frame = base_consumer.schema_pb2.Frame(id="frame-1")
    message = KafkaMessage(value=frame.SerializeToString())
    connection = Mock()
    connection.poll.return_value = message
    consumer = kafka_to_file.KafkaMessageConsumer(make_args(max_messages=1))

    with (
        patch.object(base_consumer.signal, "signal"),
        patch.object(consumer, "create_connection", return_value=connection),
    ):
        stats = consumer.process_source(
            "mdx-raw",
            tmp_path / "kafka.jsonl",
            "test-group",
        )

    assert stats == {"read": 1, "written": 1, "errors": 0}
    connection.commit.assert_called_once_with(message=message, asynchronous=False)


def test_kafka_does_not_commit_decode_failure(tmp_path):
    connection = Mock()
    connection.poll.return_value = KafkaMessage(value=b"not-a-frame")
    consumer = kafka_to_file.KafkaMessageConsumer(make_args(max_messages=1))

    with (
        patch.object(base_consumer.signal, "signal"),
        patch.object(consumer, "create_connection", return_value=connection),
    ):
        stats = consumer.process_source(
            "mdx-raw",
            tmp_path / "kafka-bad.jsonl",
            "test-group",
        )

    assert stats == {"read": 1, "written": 0, "errors": 1}
    connection.commit.assert_not_called()


@pytest.mark.parametrize("payload", [b"", None])
def test_kafka_empty_or_tombstone_payload_fails_without_commit(tmp_path, payload):
    connection = Mock()
    connection.poll.return_value = KafkaMessage(value=payload)
    consumer = kafka_to_file.KafkaMessageConsumer(make_args(max_messages=5))

    with (
        patch.object(base_consumer.signal, "signal"),
        patch.object(consumer, "create_connection", return_value=connection),
    ):
        stats = consumer.process_source(
            "mdx-raw",
            tmp_path / "kafka-empty.jsonl",
            "test-group",
        )

    assert stats == {"read": 1, "written": 0, "errors": 1}
    connection.poll.assert_called_once()
    connection.commit.assert_not_called()


def test_kafka_real_error_is_countable_marker():
    connection = Mock()
    connection.poll.return_value = KafkaMessage(error=KafkaMessageError(123))
    consumer = kafka_to_file.KafkaMessageConsumer(make_args())

    assert list(consumer.consume_messages(connection, "mdx-raw", "test-group")) == [
        ("__kafka_error__", None)
    ]


def test_bounded_kafka_capture_fails_fast_without_commit(tmp_path):
    connection = Mock()
    connection.poll.return_value = KafkaMessage(error=KafkaMessageError(123))
    consumer = kafka_to_file.KafkaMessageConsumer(make_args(max_messages=5))

    with (
        patch.object(base_consumer.signal, "signal"),
        patch.object(consumer, "create_connection", return_value=connection),
    ):
        stats = consumer.process_source(
            "mdx-raw",
            tmp_path / "kafka-error.jsonl",
            "test-group",
        )

    assert stats == {"read": 0, "written": 0, "errors": 1}
    connection.poll.assert_called_once()
    connection.commit.assert_not_called()


def test_redis_read_is_bounded_by_remaining_messages_and_poll_timeout():
    connection = Mock()
    connection.xreadgroup.return_value = [
        (b"mdx-raw", [(b"1-0", {b"value": b"payload"})])
    ]
    consumer = redis_to_file.RedisMessageConsumer(make_args())

    assert list(consumer.consume_messages(
        connection,
        "mdx-raw",
        "test-group",
        max_messages=3,
        poll_timeout_seconds=0.125,
    )) == [(b"1-0", b"payload")]
    connection.xreadgroup.assert_called_once_with(
        "test-group",
        connection.xreadgroup.call_args.args[1],
        {"mdx-raw": ">"},
        count=3,
        block=125,
    )


@pytest.mark.parametrize(
    ("consumer", "raw_value"),
    [
        (kafka_to_file.KafkaMessageConsumer, "mdx-raw,"),
        (redis_to_file.RedisMessageConsumer, ",mdx-raw"),
    ],
)
def test_empty_source_names_are_rejected(consumer, raw_value):
    args = make_args()
    if consumer is kafka_to_file.KafkaMessageConsumer:
        args.topics = raw_value
    else:
        args.streams = raw_value

    with pytest.raises(ValueError, match="empty name"):
        consumer(args).get_source_names()


@pytest.mark.parametrize(
    ("parser", "valid", "invalid"),
    [
        (base_consumer.non_negative_int_arg, "0", "-1"),
        (base_consumer.non_negative_float_arg, "0.5", "nan"),
        (base_consumer.positive_float_arg, "0.001", "0"),
    ],
)
def test_bound_argument_validation(parser, valid, invalid):
    assert parser(valid) >= 0
    with pytest.raises(ValueError):
        parser(invalid)
