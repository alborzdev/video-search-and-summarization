#!/usr/bin/env python3
"""Exercise Behavior Analytics dynamic control and post-update frames on Redis or MQTT."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

from google.protobuf.json_format import ParseDict
from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2
import redis

from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from paho.mqtt.client import Client, MQTTMessage
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties


IMAGE = "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1"
IMAGE_ID = "sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6"
LOGICAL_CHANNELS = ("raw", "behavior", "frames", "notification", "events", "incidents")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=60)


def _strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


class Transport:
    def publish(self, channel: str, key: bytes, value: bytes, headers: dict[str, str]) -> None:
        raise NotImplementedError

    def records(self, channel: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def cleanup(self) -> None:
        raise NotImplementedError


class KafkaTransport(Transport):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.admin = AdminClient({"bootstrap.servers": "localhost:9092"})
        existing = set(self.admin.list_topics(timeout=10).topics).intersection(mapping.values())
        if existing:
            for future in self.admin.delete_topics(sorted(existing), operation_timeout=20).values():
                future.result(timeout=30)
        for future in self.admin.create_topics([
            NewTopic(topic, num_partitions=1, replication_factor=1)
            for topic in mapping.values()
        ]).values():
            future.result(timeout=30)
        self.producer = Producer({"bootstrap.servers": "localhost:9092"})
        self.consumers: dict[str, Consumer] = {}
        self.messages: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for channel, topic in mapping.items():
            consumer = Consumer({
                "bootstrap.servers": "localhost:9092",
                "group.id": f"vss-ba-qualification-{os.getpid()}-{channel}",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            })
            consumer.subscribe([topic])
            self.consumers[channel] = consumer

    def publish(self, channel: str, key: bytes, value: bytes, headers: dict[str, str]) -> None:
        self.producer.produce(
            self.mapping[channel],
            key=key,
            value=value,
            headers=list(headers.items()),
        )
        if self.producer.flush(timeout=10):
            raise RuntimeError(f"Kafka publish did not complete: {channel}")

    def records(self, channel: str) -> list[dict[str, Any]]:
        consumer = self.consumers[channel]
        idle = 0
        while idle < 2:
            message = consumer.poll(0.05)
            if message is None:
                idle += 1
                continue
            if message.error():
                raise RuntimeError(str(message.error()))
            idle = 0
            headers = {
                name: (value or b"").decode("utf-8", errors="replace")
                for name, value in (message.headers() or [])
            }
            self.messages[channel].append({
                "id": f"{message.partition()}:{message.offset()}",
                "key": message.key() or b"",
                "value": message.value() or b"",
                "headers": headers,
            })
        return list(self.messages[channel])

    def cleanup(self) -> None:
        if hasattr(self, "consumers"):
            for consumer in self.consumers.values():
                consumer.close()
        if hasattr(self, "producer"):
            self.producer.flush(timeout=10)
        if hasattr(self, "admin"):
            current = set(self.admin.list_topics(timeout=10).topics).intersection(self.mapping.values())
            if current:
                for future in self.admin.delete_topics(sorted(current), operation_timeout=20).values():
                    future.result(timeout=30)


class RedisTransport(Transport):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.client = redis.Redis(host="localhost", port=6379, db=0)
        self.cleanup()

    def publish(self, channel: str, key: bytes, value: bytes, headers: dict[str, str]) -> None:
        self.client.xadd(self.mapping[channel], {
            b"key": key,
            b"value": value,
            b"headers": json.dumps(headers, separators=(",", ":")).encode("utf-8"),
        })

    def records(self, channel: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message_id, fields in self.client.xrange(self.mapping[channel]):
            raw_headers = fields.get(b"headers", b"{}")
            result.append({
                "id": message_id.decode("utf-8"),
                "key": fields.get(b"key", b""),
                "value": fields.get(b"value", b""),
                "headers": json.loads(raw_headers.decode("utf-8")),
            })
        return result

    def cleanup(self) -> None:
        self.client.delete(*(self.mapping.values()))


class MQTTTransport(Transport):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.messages: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.connected = threading.Event()
        self.client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"vss-ba-qualification-{os.getpid()}",
            protocol=MQTTProtocolVersion.MQTTv5,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect("localhost", 1883, keepalive=30, clean_start=True)
        self.client.loop_start()
        if not self.connected.wait(timeout=10):
            raise RuntimeError("MQTT qualifier did not connect")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.value != 0:
            raise RuntimeError(f"MQTT connect failed: {reason_code}")
        for topic in self.mapping.values():
            client.subscribe(topic, qos=1)
        self.connected.set()

    def _on_message(self, client, userdata, message: MQTTMessage) -> None:
        reverse = {topic: channel for channel, topic in self.mapping.items()}
        channel = reverse.get(message.topic)
        if channel is None:
            return
        user_properties = []
        if message.properties is not None:
            user_properties = message.properties.json().get("UserProperty", []) or []
        headers = {str(key): str(value) for key, value in user_properties}
        key = headers.pop("key", "").encode("utf-8")
        self.messages[channel].append({
            "id": str(message.mid),
            "key": key,
            "value": bytes(message.payload),
            "headers": headers,
        })

    def publish(self, channel: str, key: bytes, value: bytes, headers: dict[str, str]) -> None:
        properties = Properties(PacketTypes.PUBLISH)
        timestamp = headers.get("timestamp", str(int(time.time() * 1000)))
        properties.UserProperty = ("timestamp", timestamp)
        properties.UserProperty = ("key", key.decode("utf-8"))
        for name, item in headers.items():
            if name != "timestamp":
                properties.UserProperty = (name, item)
        info = self.client.publish(
            self.mapping[channel], payload=value, qos=1, retain=False, properties=properties
        )
        info.wait_for_publish(timeout=10)
        if not info.is_published():
            raise RuntimeError(f"MQTT publish did not complete: {channel}")

    def records(self, channel: str) -> list[dict[str, Any]]:
        return list(self.messages[channel])

    def cleanup(self) -> None:
        if hasattr(self, "client"):
            self.client.disconnect()
            self.client.loop_stop()


def _mapping(config: dict[str, Any], backend: str) -> dict[str, str]:
    if backend == "kafka":
        entries = config["kafka"]["topics"]
    elif backend == "redis":
        entries = config["redisStream"]["streams"]
    else:
        entries = config["mqtt"]["topics"]
    result = {entry["name"]: entry["value"] for entry in entries}
    if set(result) != set(LOGICAL_CHANNELS):
        raise ValueError("qualification config must map all six logical channels")
    return result


def _wait_for(predicate, description: str, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {description}")


def _notification_records(transport: Transport) -> list[dict[str, Any]]:
    result = []
    for record in transport.records("notification"):
        try:
            body = json.loads(record["value"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        result.append({**record, "body": body})
    return result


def _wait_request_reference(transport: Transport) -> str:
    def find() -> str | None:
        for record in _notification_records(transport):
            if (
                record["key"] == b"behavior-analytics-config"
                and record["headers"].get("event.type") == "request-config"
            ):
                return record["headers"].get("reference-id")
        return None

    return _wait_for(find, "request-config", timeout=45)


def _wait_success_ack(transport: Transport, direct_reference: str) -> dict[str, Any]:
    def find() -> dict[str, Any] | None:
        for record in reversed(_notification_records(transport)):
            reference = record["headers"].get("reference-id", "")
            if (
                record["key"] == b"behavior-analytics-config"
                and record["headers"].get("event.type") == "ack"
                and reference.startswith(f"{direct_reference}-")
                and record["body"].get("status") == "success"
            ):
                return record
        return None

    return _wait_for(find, "successful dynamic-config ack", timeout=45)


def _container_logs(container: str) -> str:
    return _run("docker", "logs", container, check=False).stdout + _run(
        "docker", "logs", container, check=False
    ).stderr


def _wait_log(container: str, markers: tuple[str, ...], description: str) -> str:
    def find() -> str | None:
        logs = _container_logs(container)
        return logs if all(marker in logs for marker in markers) else None

    return _wait_for(find, description, timeout=60)


def _wait_log_count(container: str, marker: str, count: int, description: str) -> str:
    def find() -> str | None:
        logs = _container_logs(container)
        return logs if logs.count(marker) >= count else None

    return _wait_for(find, description, timeout=60)


def _checkpoint_summary(container: str) -> dict[str, Any]:
    code = r'''
import hashlib, json
from pathlib import Path
result = {}
for label, directory in (("config", Path("/tmp/checkpoint/config")), ("calibration", Path("/tmp/checkpoint/calibration"))):
    rows = []
    for path in sorted(directory.glob("*.json")):
        body = json.loads(path.read_text())
        rows.append({
            "name_sha256": hashlib.sha256(path.name.encode()).hexdigest(),
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": body.get("version"),
            "behavior_max_points": next((x.get("value") for x in body.get("app", []) if x.get("name") == "behaviorMaxPoints"), None),
        })
    result[label] = rows
print(json.dumps(result, sort_keys=True))
'''
    proc = _run("docker", "exec", container, "python3", "-c", code)
    return json.loads(proc.stdout)


def _publish_frames(transport: Transport, fixture: Path, count: int, fps: int) -> None:
    base_ms = int(time.time() * 1000) - 1000
    published = 0
    with fixture.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            frame = ParseDict(json.loads(line), schema_pb2.Frame(), ignore_unknown_fields=False)
            frame.timestamp.FromMilliseconds(base_ms + int(published * 1000 / fps))
            transport.publish("raw", frame.sensorId.encode("utf-8"), frame.SerializeToString(), {})
            published += 1
            if published >= count:
                break
    if published != count:
        raise RuntimeError(f"fixture contained only {published} frames")


def _output_summary(transport: Transport) -> dict[str, Any]:
    frames = []
    for record in transport.records("frames"):
        value = schema_pb2.Frame()
        try:
            value.ParseFromString(record["value"])
        except Exception:
            continue
        frames.append(value)
    behaviors = []
    for record in transport.records("behavior"):
        value = ext_pb2.Behavior()
        try:
            value.ParseFromString(record["value"])
        except Exception:
            continue
        behaviors.append(value)
    return {
        "frames": len(frames),
        "behaviors": len(behaviors),
        "frame_sensors": sorted({value.sensorId for value in frames}),
        "behavior_sensors": sorted({value.sensor.id for value in behaviors}),
        "max_behavior_points": max((len(value.locations.coordinates) for value in behaviors), default=0),
        "frames_with_fov_metrics": sum(bool(value.fov) for value in frames),
        "frames_with_roi_metrics": sum(bool(value.rois) for value in frames),
    }


def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    config_path = args.config.resolve()
    calibration_path = args.calibration.resolve()
    fixture_path = args.fixture.resolve()
    config = _strict_json(config_path)
    calibration = _strict_json(calibration_path)
    mapping = _mapping(config, args.backend)
    transport: Transport
    if args.backend == "kafka":
        transport = KafkaTransport(mapping)
        direct_reference = "kafka"
    elif args.backend == "redis":
        transport = RedisTransport(mapping)
        direct_reference = "redis"
    else:
        transport = MQTTTransport(mapping)
        direct_reference = "mqtt"

    container = f"vss-behavior-{args.backend}-control-oracle"
    state: dict[str, Any] = {}
    checkpoint: dict[str, Any] = {}
    log_sha256 = ""
    try:
        _run("docker", "rm", "-f", container, check=False)
        created = _run(
            "docker", "run", "-d", "--name", container, "--network", "host", "--user", "nvs",
            "-v", f"{config_path}:/resources/broker-config.json:ro",
            "-v", f"{calibration_path}:/resources/calibration.json:ro",
            IMAGE,
            "python3", "apps/analytics/main_analytics_2d_app.py",
            "--config", "/resources/broker-config.json",
            "--calibration", "/resources/calibration.json",
        )
        if not created.stdout.strip():
            raise RuntimeError("docker run returned no container ID")

        request_reference = _wait_request_reference(transport)
        bootstrap_body = {"status": "success", "config": config, "error": None}
        transport.publish(
            "notification",
            b"behavior-analytics-config",
            json.dumps(bootstrap_body, separators=(",", ":")).encode("utf-8"),
            {"event.type": "upsert-all", "reference-id": request_reference},
        )
        _wait_log(container, ("applied config from upsert-all-config-",), "bootstrap config apply")
        _wait_log_count(container, "Task Ready for processing...", 2, "both processing workers")
        if args.backend == "kafka":
            _wait_log_count(
                container,
                f"Group ID: {config['kafka']['group']} - {mapping['raw']} - Analytics2DApp.",
                2,
                "both Kafka raw consumer assignments",
            )
        elif args.backend == "redis":
            assert isinstance(transport, RedisTransport)
            _wait_for(
                lambda: len(transport.client.xinfo_groups(mapping["raw"])) >= 2,
                "both Redis raw consumer groups",
                timeout=30,
            )
        else:
            _wait_log_count(
                container,
                f"to MQTT topic {mapping['raw']}",
                2,
                "both MQTT raw subscriptions",
            )

        patch_body = {
            "status": None,
            "config": {"app": [{"name": "behaviorMaxPoints", "value": "3"}]},
            "error": None,
        }
        transport.publish(
            "notification",
            b"behavior-analytics-config",
            json.dumps(patch_body, separators=(",", ":")).encode("utf-8"),
            {"event.type": "upsert", "reference-id": direct_reference},
        )
        ack = _wait_success_ack(transport, direct_reference)
        _wait_log_count(
            container,
            "applied config from upsert-config-",
            3,
            "incremental config apply in main and both workers",
        )

        dynamic_calibration = json.loads(json.dumps(calibration))
        dynamic_calibration["version"] = f"qualification-{args.backend}-2.0"
        calibration_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        transport.publish(
            "notification",
            b"calibration",
            json.dumps(dynamic_calibration, separators=(",", ":")).encode("utf-8"),
            {"event.type": "upsert-all", "timestamp": calibration_timestamp},
        )
        _wait_log_count(
            container,
            "Calibration file change detected, delegating to CalibrationE",
            3,
            "dynamic calibration reload in main and both workers",
        )

        checkpoint = _checkpoint_summary(container)
        _publish_frames(transport, fixture_path, args.frame_count, args.fps)

        def outputs_ready() -> dict[str, Any] | None:
            summary = _output_summary(transport)
            return summary if summary["frames"] > 0 and summary["behaviors"] > 0 else None

        try:
            outputs = _wait_for(
                outputs_ready,
                "post-update frame and behavior outputs",
                timeout=args.output_timeout,
            )
        except TimeoutError as exc:
            current_outputs = _output_summary(transport)
            logs = _container_logs(container)
            markers = {
                "read_raw": "Read a total of" in logs,
                "created_behaviors": "Created a total of" in logs,
                "worker_error": "Traceback (most recent call last)" in logs,
            }
            raise RuntimeError(
                f"post-update output timeout: outputs={current_outputs}, markers={markers}"
            ) from exc
        if outputs["max_behavior_points"] <= 0 or outputs["max_behavior_points"] > 3:
            raise RuntimeError(f"behaviorMaxPoints=3 was not reflected in output: {outputs}")
        if outputs["frames_with_fov_metrics"] <= 0 or outputs["frames_with_roi_metrics"] <= 0:
            raise RuntimeError(f"dynamic calibration was not reflected in enhanced frames: {outputs}")

        logs = _container_logs(container)
        log_sha256 = _sha_bytes(logs.encode("utf-8"))
        request_hash = _sha_bytes(request_reference.encode("utf-8"))
        ack_hash = _sha_bytes(ack["headers"]["reference-id"].encode("utf-8"))
        result = {
            "backend": args.backend,
            "request_reference_sha256": request_hash,
            "ack_reference_sha256": ack_hash,
            "ack_status": ack["body"]["status"],
            "source_config_sha256": _sha_file(config_path),
            "baseline_calibration_sha256": _sha_file(calibration_path),
            "dynamic_calibration_sha256": _sha_bytes(
                json.dumps(dynamic_calibration, separators=(",", ":")).encode("utf-8")
            ),
            "dynamic_calibration_version": dynamic_calibration["version"],
            "checkpoint": checkpoint,
            "input_frames": args.frame_count,
            "outputs": outputs,
            "container_log_sha256": log_sha256,
        }
    finally:
        inspect = _run("docker", "inspect", container, check=False)
        if inspect.returncode == 0:
            current = json.loads(inspect.stdout)[0]
            if current["State"]["Running"]:
                _run("docker", "stop", "-t", "30", container, check=False)
            final = json.loads(_run("docker", "inspect", container).stdout)[0]
            state = {
                "exit_code": final["State"]["ExitCode"],
                "oom_killed": final["State"]["OOMKilled"],
                "restart_count": final["RestartCount"],
                "image_id": final["Image"],
            }
            _run("docker", "rm", container, check=False)
        transport.cleanup()

    result["container"] = state
    if args.backend == "kafka":
        assert isinstance(transport, KafkaTransport)
        backend_records_absent = not set(
            transport.admin.list_topics(timeout=10).topics
        ).intersection(mapping.values())
    elif args.backend == "redis":
        backend_records_absent = all(
            not transport.records(channel) for channel in LOGICAL_CHANNELS
        )
    else:
        backend_records_absent = True
    result["cleanup"] = {
        "container_absent": _run("docker", "inspect", container, check=False).returncode != 0,
        "backend_records_absent": backend_records_absent,
    }
    if state != {"exit_code": 0, "oom_killed": False, "restart_count": 0, "image_id": IMAGE_ID}:
        raise RuntimeError(f"container exit integrity failed: {state}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("kafka", "redis", "mqtt"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=600)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--output-timeout", type=float, default=90)
    args = parser.parse_args()
    try:
        result = _run_probe(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
