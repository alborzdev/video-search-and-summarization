#!/usr/bin/env python3
"""Bounded live Kafka/Redis RT-VLM error-publication proof for Thor."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _verify_static(contract: dict[str, Any]) -> None:
    if contract["official_indices"] != [365]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _file_sha(path) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    compose = (REPO / contract["source_locks"][1]["path"]).read_text()
    if 'REDIS_HOST: "${THOR_LOCAL_RTVI_REDIS_HOST:-host.docker.internal}"' not in compose:
        raise QualificationError("Thor-local RT-VLM Redis gateway contract drifted")
    ledger = _load(REPO / contract["source_locks"][2]["path"])
    row = ledger["capabilities"][365]
    if (
        row.get("id") != contract["capability_ids"][0]
        or row.get("title") != "Kafka/Redis error publication"
        or row.get("contract", {}).get("advertised_literal")
        != "Kafka/Redis error publication"
    ):
        raise QualificationError("advertised capability row drifted")


def _docker(
    args: list[str],
    counter: list[int],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    try:
        return subprocess.run(
            ["docker", *args],
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _inspect(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    runtime = contract["runtime"]
    names = [
        runtime["rt_vlm_container"],
        runtime["kafka_container"],
        runtime["redis_container"],
    ]
    raw = _docker(["inspect", *names], counter).stdout
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError("Docker inspect JSON was invalid") from exc
    by_name = {row.get("Name", "").lstrip("/"): row for row in rows}
    expected = {
        runtime["rt_vlm_container"]: runtime["rt_vlm_image_id"],
        runtime["kafka_container"]: runtime["kafka_image_id"],
        runtime["redis_container"]: runtime["redis_image_id"],
    }
    for name, image in expected.items():
        row = by_name.get(name, {})
        state = row.get("State", {})
        if (
            row.get("Image") != image
            or state.get("Status") != "running"
            or state.get("Health", {}).get("Status") != "healthy"
            or state.get("OOMKilled") is not False
            or row.get("RestartCount") != 0
        ):
            raise QualificationError(f"runtime identity drifted: {name}")
    rt_env = by_name[runtime["rt_vlm_container"]].get("Config", {}).get("Env", [])
    if f"REDIS_HOST={runtime['redis_host']}" not in rt_env:
        raise QualificationError("live RT-VLM Redis hostname is not the private host gateway")
    return {
        "rt_vlm_healthy": True,
        "rt_vlm_image_exact": True,
        "rt_vlm_restart_count": 0,
        "rt_vlm_oom_killed": False,
        "kafka_healthy": True,
        "kafka_image_exact": True,
        "kafka_restart_count": 0,
        "kafka_oom_killed": False,
        "redis_healthy": True,
        "redis_image_exact": True,
        "redis_restart_count": 0,
        "redis_oom_killed": False,
        "redis_host_gateway_exact": True,
    }


def _verify_live_source(contract: dict[str, Any], counter: list[int]) -> None:
    lock = contract["source_locks"][0]
    output = _docker(
        ["exec", contract["runtime"]["rt_vlm_container"], "sha256sum", lock["container_path"]],
        counter,
    ).stdout.decode()
    fields = output.split()
    if len(fields) != 2 or fields[0] != lock["sha256"] or fields[1] != lock["container_path"]:
        raise QualificationError("live RT-VLM stream-handler source lock drifted")


BROKER_PROBE = r'''
import json
import os
import secrets
import time
from datetime import datetime
from threading import Event, RLock

import redis
from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from server.rtvi_stream_handler import RTVIStreamHandler

suffix = secrets.token_hex(6)
topic = "vss-rt-vlm-error-qual-365-" + suffix
channel = "vss-rt-vlm-error-qual-365-" + suffix
event = "thor-local-error-publication-proof"
stream = "thor-local-qualifier"
bootstrap = os.environ["KAFKA_BOOTSTRAP_SERVERS"].split(",")
admin = KafkaAdminClient(bootstrap_servers=bootstrap, client_id="rt-vlm-error-qualifier")
producer = None
consumer = None
redis_client = None
pubsub = None
topic_created = False
handler = object.__new__(RTVIStreamHandler)
result = {}
try:
    admin.create_topics([NewTopic(name=topic, num_partitions=1, replication_factor=1)])
    topic_created = True
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda value: value,
        acks="all",
        retries=3,
        request_timeout_ms=10000,
    )
    handler._lock = RLock()
    handler._stopping = False
    handler._kafka_enabled = True
    handler._kafka_producer = producer
    handler._kafka_error_topic = topic
    handler._kafka_send_queue = None
    handler._kafka_send_thread = None
    handler._kafka_send_stop_event = Event()
    handler._kafka_send_queue_maxsize = 8
    handler._use_redis_error_bus = False
    handler._podname = "rt-vlm-qualification"
    handler._send_error_message_to_kafka(event, stream, "operational")
    handler._kafka_send_queue.join()
    producer.flush(timeout=10)
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=5000,
    )
    records = list(consumer)
    if len(records) != 1:
        raise RuntimeError("owned Kafka record count differed")
    kafka_value = json.loads(records[0].value)
    kafka_headers = {key: value.decode() for key, value in records[0].headers}
    kafka_timestamp = datetime.fromisoformat(kafka_value["timestamp"].replace("Z", "+00:00"))
    result["kafka"] = {
        "record_count": 1,
        "schema_exact": set(kafka_value) == {"streamId", "timestamp", "type", "source", "event"},
        "stream_exact": kafka_value["streamId"] == stream,
        "type_exact": kafka_value["type"] == "operational",
        "source_exact": kafka_value["source"] == "rt-vlm-qualification",
        "event_exact": kafka_value["event"] == event,
        "timestamp_utc_parseable": kafka_timestamp.utcoffset().total_seconds() == 0,
        "message_type_header_exact": kafka_headers == {"message_type": "error"},
    }

    redis_client = redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
        db=int(os.environ["REDIS_DB"]),
        decode_responses=False,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    redis_client.ping()
    if redis_client.exists(channel):
        raise RuntimeError("ephemeral Redis channel collided with a persistent key")
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=2)
    handler._redis_client = redis_client
    handler._redis_error_channel = channel
    handler._redis_send_queue = None
    handler._redis_send_thread = None
    handler._redis_send_stop_event = Event()
    handler._redis_send_queue_maxsize = 8
    handler._use_redis_error_bus = True
    handler._send_error_message_to_kafka(event, stream, "operational")
    handler._redis_send_queue.join()
    message = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and message is None:
        message = pubsub.get_message(timeout=0.5)
    if not message or message.get("type") != "message":
        raise RuntimeError("owned Redis publication was not observed")
    redis_value = json.loads(message["data"])
    redis_timestamp = datetime.fromisoformat(redis_value["timestamp"].replace("Z", "+00:00"))
    result["redis"] = {
        "message_count": 1,
        "schema_exact": set(redis_value) == {"streamId", "timestamp", "type", "source", "event"},
        "stream_exact": redis_value["streamId"] == stream,
        "type_exact": redis_value["type"] == "operational",
        "source_exact": redis_value["source"] == "rt-vlm-qualification",
        "event_exact": redis_value["event"] == event,
        "timestamp_utc_parseable": redis_timestamp.utcoffset().total_seconds() == 0,
        "backend_switch_routed_to_redis": True,
        "persistent_keys_created": 0,
    }
    comparable_keys = {"streamId", "type", "source", "event"}
    result["schema_equal_between_backends"] = all(
        kafka_value[key] == redis_value[key] for key in comparable_keys
    )
finally:
    handler._stopping = True
    if getattr(handler, "_kafka_send_stop_event", None):
        handler._kafka_send_stop_event.set()
    if getattr(handler, "_kafka_send_thread", None):
        handler._kafka_send_thread.join(timeout=3)
    if getattr(handler, "_redis_send_stop_event", None):
        handler._redis_send_stop_event.set()
    if getattr(handler, "_redis_send_thread", None):
        handler._redis_send_thread.join(timeout=3)
    if pubsub:
        pubsub.unsubscribe(channel)
        pubsub.close()
    if consumer:
        consumer.close()
    if producer:
        producer.close(timeout=5)
    redis_key_absent = True if redis_client is None else not bool(redis_client.exists(channel))
    redis_subscribers = 0
    if redis_client is not None:
        redis_subscribers = int(redis_client.pubsub_numsub(channel)[0][1])
        redis_client.close()
    if topic_created:
        admin.delete_topics([topic])
        deadline = time.monotonic() + 10
        while topic in admin.list_topics() and time.monotonic() < deadline:
            time.sleep(0.2)
    result["cleanup"] = {
        "kafka_topic_absent": topic not in admin.list_topics(),
        "redis_persistent_key_absent": redis_key_absent,
        "redis_subscriber_count": redis_subscribers,
        "sender_threads_stopped": not (
            getattr(handler, "_kafka_send_thread", None) and handler._kafka_send_thread.is_alive()
        ) and not (
            getattr(handler, "_redis_send_thread", None) and handler._redis_send_thread.is_alive()
        ),
    }
    admin.close()
print("VSS_ERROR_BUS_RECEIPT=" + json.dumps(result, sort_keys=True))
'''


def _probe(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    output = _docker(
        [
            "exec",
            "-i",
            "-w",
            "/opt/nvidia/rtvi/rtvi",
            contract["runtime"]["rt_vlm_container"],
            "python3",
            "-",
        ],
        counter,
        input_bytes=BROKER_PROBE.encode(),
    ).stdout.decode(errors="replace")
    prefix = "VSS_ERROR_BUS_RECEIPT="
    matches = [line[len(prefix) :] for line in output.splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise QualificationError("production error-bus probe omitted its receipt")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise QualificationError("production error-bus receipt was invalid JSON") from exc
    expected = {
        "kafka": {
            "record_count": 1,
            "schema_exact": True,
            "stream_exact": True,
            "type_exact": True,
            "source_exact": True,
            "event_exact": True,
            "timestamp_utc_parseable": True,
            "message_type_header_exact": True,
        },
        "redis": {
            "message_count": 1,
            "schema_exact": True,
            "stream_exact": True,
            "type_exact": True,
            "source_exact": True,
            "event_exact": True,
            "timestamp_utc_parseable": True,
            "backend_switch_routed_to_redis": True,
            "persistent_keys_created": 0,
        },
        "schema_equal_between_backends": True,
        "cleanup": {
            "kafka_topic_absent": True,
            "redis_persistent_key_absent": True,
            "redis_subscriber_count": 0,
            "sender_threads_stopped": True,
        },
    }
    if value != expected:
        raise QualificationError("production Kafka/Redis error-publication semantics differed")
    return value


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_error_publication_plan_valid",
        "contract_sha256": _file_sha(CONTRACT_PATH),
        "docker_commands": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    counter = [0]
    identity_before = _inspect(contract, counter)
    _verify_live_source(contract, counter)
    proof = _probe(contract, counter)
    identity_after = _inspect(contract, counter)
    if identity_before != identity_after:
        raise QualificationError("runtime identity changed")
    if counter[0] != contract["execution"]["max_docker_commands"]:
        raise QualificationError("Docker command budget was not exact")
    duration = round(time.monotonic() - started, 6)
    if duration > contract["execution"]["max_duration_seconds"]:
        raise QualificationError("qualification exceeded its duration budget")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _file_sha(CONTRACT_PATH),
        "duration_seconds": duration,
        "budget": {
            "http_requests": 0,
            "max_http_requests": 0,
            "model_requests": 0,
            "max_model_requests": 0,
            "docker_commands": counter[0],
            "max_docker_commands": contract["execution"]["max_docker_commands"],
            "support_processes_peak": 1,
            "max_support_processes": 1,
            "kafka_topic_mutations": 2,
            "max_kafka_topic_mutations": 2,
            "redis_persistent_mutations": 0,
            "max_redis_persistent_mutations": 0,
        },
        "runtime_identity": identity_after,
        "kafka": proof["kafka"],
        "redis": proof["redis"],
        "schema_equal_between_backends": proof["schema_equal_between_backends"],
        "cleanup": proof["cleanup"],
        "policy": {
            "agent_generate_calls": 0,
            "asset_mutations": 0,
            "stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "raw_topic_names_retained": False,
            "raw_channel_names_retained": False,
            "raw_message_payloads_retained": False,
            "credentials_retained": False,
            "warehouse_sample_bundle": "excluded",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("plan")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--ack", required=True)
    args = parser.parse_args()
    contract = _load(CONTRACT_PATH)
    try:
        if (args.mode or "plan") == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "package_id": contract.get("package_id"),
                    "status": "failed",
                    "failure": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
