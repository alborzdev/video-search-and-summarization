#!/usr/bin/env python3
"""Observe all seven output families through one released built-in broker sink."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "services/analytics/behavior-analytics/src"))
HELPER_PATH = REPO / "deploy/docker/thor-local/qualification/behavior-analytics-broker-control-runtime-successor/run_broker_probe.py"
SPEC = importlib.util.spec_from_file_location("behavior_sink_matrix_helper", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2  # noqa: E402


IMAGE = helper.IMAGE
IMAGE_ID = helper.IMAGE_ID
MQTT_IMAGE = "eclipse-mosquitto:2.0"
MQTT_IMAGE_ID = "sha256:6852da90a65dfff7aa3a1c8b249e92bb83c17ea8bbcce56bedff8707332a1a29"
FAMILIES = {
    "frames": ("frames", schema_pb2.Frame),
    "behaviors": ("behavior", ext_pb2.Behavior),
    "events": ("events", ext_pb2.Behavior),
    "incidents": ("incidents", ext_pb2.Incident),
    "anomalies": ("anomaly", ext_pb2.Behavior),
    "cluster": ("behaviorPlus", ext_pb2.Behavior),
    "space-utilization": ("spaceUtilization", ext_pb2.SpaceUtilization),
}


def _mapping(backend: str) -> dict[str, str]:
    prefix = f"vss-sink-matrix-{backend}"
    if backend == "mqtt":
        return {dest: f"vss/sink/matrix/{dest}" for dest, _ in FAMILIES.values()}
    return {dest: f"{prefix}-{dest}" for dest, _ in FAMILIES.values()}


def _wait_container(container: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        inspected = json.loads(helper._run("docker", "inspect", container).stdout)[0]
        if not inspected["State"]["Running"]:
            return
        time.sleep(0.2)
    raise TimeoutError(f"container did not exit: {container}")


def _wait_records(transport: Any, timeout: float = 30) -> dict[str, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = {family: transport.records(dest) for family, (dest, _) in FAMILIES.items()}
        if all(len(values) == 1 for values in records.values()):
            return records
        time.sleep(0.2)
    counts = {family: len(transport.records(dest)) for family, (dest, _) in FAMILIES.items()}
    raise TimeoutError(f"broker records incomplete: {counts}")


def _identity(family: str, value: Any) -> dict[str, Any]:
    if family == "frames":
        return {"id": value.id, "sensor": value.sensorId, "objects": len(value.objects)}
    if family == "incidents":
        return {"sensor": value.sensorId, "category": value.category, "objects": len(value.objectIds)}
    if family == "space-utilization":
        return {"id": value.id, "sensors": list(value.sensors), "total_space": value.metrics.totalSpace}
    result = {"id": value.id, "sensor": value.sensor.id, "object": value.object.id}
    if family == "events":
        result["event"] = f"{value.event.info.get('class', '')}:{value.event.type}"
    elif family == "anomalies":
        result["anomaly_type"] = value.info.get("anomaly.type")
    elif family == "cluster":
        result["cluster_index"] = value.info.get("cluster.index")
    return result


def run(backend: str) -> dict[str, Any]:
    mapping = _mapping(backend)
    broker_container = "vss-sink-matrix-mosquitto"
    probe_container = f"vss-behavior-sink-{backend.lower()}-oracle"
    broker_state: dict[str, Any] | None = None
    probe_state: dict[str, Any] = {}
    logs = ""
    transport: Any = None
    try:
        helper._run("docker", "rm", "-f", probe_container, check=False)
        if backend == "mqtt":
            helper._run("docker", "rm", "-f", broker_container, check=False)
            helper._run(
                "docker", "run", "-d", "--name", broker_container, "--network", "host",
                "-v", f"{HERE / 'mosquitto.conf'}:/mosquitto/config/mosquitto.conf:ro",
                MQTT_IMAGE,
            )
            helper._wait_for(
                lambda: "mosquitto version" if "mosquitto version" in helper._container_logs(broker_container) else None,
                "Mosquitto startup",
                timeout=20,
            )
        if backend == "kafka":
            transport = helper.KafkaTransport(mapping)
        elif backend == "redisStream":
            transport = helper.RedisTransport(mapping)
        else:
            transport = helper.MQTTTransport(mapping)

        created = helper._run(
            "docker", "run", "-d", "--name", probe_container, "--network", "host", "--user", "nvs",
            "-v", f"{HERE}:/probe:ro", IMAGE,
            "python3", "/probe/in_container_sink_probe.py", backend,
        )
        if not created.stdout.strip():
            raise RuntimeError("docker run returned no container ID")
        _wait_container(probe_container)
        logs = helper._container_logs(probe_container)
        inspected = json.loads(helper._run("docker", "inspect", probe_container).stdout)[0]
        probe_state = {
            "exit_code": inspected["State"]["ExitCode"],
            "oom_killed": inspected["State"]["OOMKilled"],
            "restart_count": inspected["RestartCount"],
            "image_id": inspected["Image"],
        }
        if probe_state != {"exit_code": 0, "oom_killed": False, "restart_count": 0, "image_id": IMAGE_ID}:
            raise RuntimeError(f"probe container exit integrity failed: {probe_state}; logs={logs}")
        manifest = json.loads(logs)
        records = _wait_records(transport)
        observed = {}
        for family, values in records.items():
            record = values[0]
            _, message_class = FAMILIES[family]
            value = message_class()
            value.ParseFromString(record["value"])
            digest = hashlib.sha256(record["value"]).hexdigest()
            if digest != manifest["families"][family]["payload_sha256"]:
                raise RuntimeError(f"payload drifted for {backend}/{family}")
            expected_key = manifest["families"][family]["key"].encode()
            if record["key"] != expected_key:
                raise RuntimeError(f"key drifted for {backend}/{family}")
            if record["headers"].get("family") != family or record["headers"].get("backend") != backend:
                raise RuntimeError(f"headers drifted for {backend}/{family}: {record['headers']}")
            observed[family] = {
                "destination_key": manifest["families"][family]["destination_key"],
                "broker_destination": manifest["families"][family]["broker_destination"],
                "key": expected_key.decode(),
                "payload_sha256": digest,
                "payload_bytes": len(record["value"]),
                "decoded_identity": _identity(family, value),
                "headers_preserved": True,
            }
        if set(observed) != set(FAMILIES):
            raise RuntimeError("output family coverage drifted")
    finally:
        if transport is not None:
            transport.cleanup()
        helper._run("docker", "rm", "-f", probe_container, check=False)
        if backend == "mqtt":
            inspected = helper._run("docker", "inspect", broker_container, check=False)
            if inspected.returncode == 0:
                state = json.loads(inspected.stdout)[0]
                if state["State"]["Running"]:
                    helper._run("docker", "stop", "-t", "10", broker_container, check=False)
                final = json.loads(helper._run("docker", "inspect", broker_container).stdout)[0]
                broker_state = {
                    "exit_code": final["State"]["ExitCode"],
                    "oom_killed": final["State"]["OOMKilled"],
                    "restart_count": final["RestartCount"],
                    "image_id": final["Image"],
                }
                helper._run("docker", "rm", broker_container, check=False)

    if backend == "kafka":
        records_absent = not set(transport.admin.list_topics(timeout=10).topics).intersection(mapping.values())
    elif backend == "redisStream":
        records_absent = all(not transport.client.exists(value) for value in mapping.values())
    else:
        records_absent = True
        if broker_state != {"exit_code": 0, "oom_killed": False, "restart_count": 0, "image_id": MQTT_IMAGE_ID}:
            raise RuntimeError(f"MQTT broker exit integrity failed: {broker_state}")
    normal = {}
    for name in ("vss-behavior-analytics", "vss-behavior-analytics-thor-candidates"):
        inspected = json.loads(helper._run("docker", "inspect", name).stdout)[0]
        normal[name] = {
            "running": inspected["State"]["Running"],
            "oom_killed": inspected["State"]["OOMKilled"],
            "restart_count": inspected["RestartCount"],
        }
    expected_normal = {"running": True, "oom_killed": False, "restart_count": 0}
    if not all(value == expected_normal for value in normal.values()):
        raise RuntimeError(f"normal Behavior Analytics containers drifted: {normal}")
    return {
        "backend": backend,
        "factory_class": manifest["factory_class"],
        "family_count": len(observed),
        "families": observed,
        "runtime": {"container": probe_state, "log_sha256": hashlib.sha256(logs.encode()).hexdigest()},
        "mqtt_broker": broker_state,
        "cleanup": {
            "probe_container_absent": helper._run("docker", "inspect", probe_container, check=False).returncode != 0,
            "broker_records_absent": records_absent,
            "mqtt_broker_absent": helper._run("docker", "inspect", broker_container, check=False).returncode != 0,
            "normal_behavior_containers": normal,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("kafka", "redisStream", "mqtt"))
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.backend), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
