#!/usr/bin/env python3
"""Exercise the mounted NVIDIA NvSchema publication path against local Kafka."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time
import traceback

from confluent_kafka import Consumer
from confluent_kafka.admin import AdminClient, NewTopic


ALERT_ROOT = Path("/workspace/alert")
ALERT_SERVICE = ALERT_ROOT / "alert-agent-web/app/core/alert_service.py"
TOPIC = "vss-protocol-case-kafka-nvschema"
GROUP = "vss-protocol-case-kafka-nvschema-group"
BROKER = "localhost:9092"


def _load_alert_service():
    spec = importlib.util.spec_from_file_location(
        "vss_qualified_alert_service", ALERT_SERVICE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load mounted alert service")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run() -> dict[str, object]:
    module = _load_alert_service()
    from mdx.anomaly.kafka_message_broker import KafkaMessageBroker
    from mdx.anomaly.protobuf import Behavior

    admin = AdminClient({"bootstrap.servers": BROKER})
    admin.create_topics(
        [NewTopic(TOPIC, num_partitions=1, replication_factor=1)]
    )[TOPIC].result(timeout=20)

    consumer = Consumer(
        {
            "bootstrap.servers": BROKER,
            "group.id": GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([TOPIC])
    consumer.poll(1.0)

    broker = KafkaMessageBroker(
        {
            "kafka": {
                "bootstrap_servers": BROKER,
                "auto_offset_reset": "earliest",
                "enable_auto_commit": False,
                "max_poll_interval_ms": 300000,
                "session_timeout_ms": 45000,
                "heartbeat_interval_ms": 3000,
                "poll_timeout": 1000,
            }
        }
    )
    service = module.AlertSubmissionService.__new__(module.AlertSubmissionService)
    service.logger = logging.getLogger("vss-event-transport-qualifier")
    service.kafka_producer = broker.get_producer()
    service.kafka_alert_topic = TOPIC

    behavior = Behavior()
    behavior.id = "vss-protocol-case-kafka-001"
    behavior.timestamp.FromJsonString("2026-07-31T00:00:00Z")
    behavior.end.FromJsonString("2026-07-31T00:00:01Z")
    behavior.sensor.id = "vss-protocol-case-sensor"
    behavior.info["owner"] = "vss-protocol-case-kafka-001"
    payload = behavior.SerializeToString()

    positive_response, positive_status = (
        await service.submit_nvschema_alert_protobuf(payload)
    )
    if positive_status != 202 or positive_response.get("status") != "accepted":
        raise RuntimeError("production NvSchema submission path did not accept fixture")

    record = None
    deadline = time.monotonic() + 20
    total_records = 0
    while time.monotonic() < deadline:
        candidate = consumer.poll(0.5)
        if candidate is None:
            continue
        if candidate.error():
            raise RuntimeError(f"Kafka consumer error: {candidate.error()}")
        total_records += 1
        if candidate.key() == behavior.id.encode("utf-8"):
            record = candidate
            break
    if record is None:
        raise RuntimeError("owned Kafka record was not delivered within 20 seconds")

    decoded = Behavior()
    decoded.ParseFromString(record.value())
    semantic_match = (
        decoded.id == behavior.id
        and decoded.timestamp == behavior.timestamp
        and decoded.end == behavior.end
        and decoded.sensor.id == behavior.sensor.id
        and dict(decoded.info) == dict(behavior.info)
        and record.key().decode("utf-8") == behavior.id
    )
    if not semantic_match:
        raise RuntimeError("consumer-decoded NvSchema fields did not match fixture")
    consumer.commit(message=record, asynchronous=False)

    negative_response, negative_status = (
        await service.submit_nvschema_alert_protobuf(b"\xff")
    )
    if (
        negative_status != 400
        or negative_response.get("error") != "invalid_payload"
    ):
        raise RuntimeError("invalid protobuf did not take exact rejection path")

    unexpected = consumer.poll(2.0)
    if unexpected is not None and not unexpected.error():
        total_records += 1
        raise RuntimeError("invalid protobuf produced an unexpected Kafka record")

    consumer.close()
    service.kafka_producer.flush(5)
    return {
        "status": "passed",
        "source_sha256": hashlib.sha256(ALERT_SERVICE.read_bytes()).hexdigest(),
        "production_method": "AlertSubmissionService.submit_nvschema_alert_protobuf",
        "producer_factory": "KafkaMessageBroker.get_producer",
        "topic_created": True,
        "positive": {
            "vector_id": "kafka-one-nvschema-behavior",
            "http_semantic_status": positive_status,
            "accepted_id_match": positive_response.get("id") == behavior.id,
            "record_count": total_records,
            "key_match": True,
            "protobuf_decoded": True,
            "semantic_fields_match": semantic_match,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
        "negative": {
            "vector_id": "kafka-invalid-protobuf",
            "http_semantic_status": negative_status,
            "error_code": "invalid_payload",
            "record_published": False,
        },
    }


def main() -> int:
    started = time.monotonic()
    try:
        result = asyncio.run(_run())
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:  # retained by the host executor as a typed failure
        print(f"kafka runner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
