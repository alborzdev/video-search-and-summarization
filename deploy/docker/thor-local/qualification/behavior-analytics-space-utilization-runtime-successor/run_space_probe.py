#!/usr/bin/env python3
"""Exercise all advertised space-utilization metrics through Analytics3DApp."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from google.protobuf.json_format import ParseDict


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "services/analytics/behavior-analytics/src"))

from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2  # noqa: E402


IMAGE = "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1"
IMAGE_ID = "sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6"
BROKER = "localhost:9092"
CONTAINER = "vss-behavior-space-utilization-oracle"
PALLET_COORDINATES = [
    -2.474609375, -12.3828125, 0.11590576171875,
    1.2077035903930664, 0.9993621706962585, 0.20879419147968292,
    0.0, 0.0, 0.009953939355909824,
    0.0007638931274414062, -0.0012664794921875, 0.0024356842041015625,
]


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _logs() -> str:
    result = _run("docker", "logs", CONTAINER, check=False)
    return result.stdout + result.stderr


def _wait_for(predicate, description: str, timeout: float = 90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {description}")


def _topics(config: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in config["kafka"]["topics"]}


def _consume_available(consumer: Consumer, values: list[ext_pb2.SpaceUtilization]) -> None:
    while True:
        record = consumer.poll(0.1)
        if record is None:
            return
        if record.error():
            continue
        value = ext_pb2.SpaceUtilization()
        value.ParseFromString(record.value())
        values.append(value)


def _ready(values: list[ext_pb2.SpaceUtilization]) -> bool:
    _consume_available(_ready.consumer, values)
    metrics = [value.metrics for value in values]
    return bool(
        len(values) >= 3
        and any(item.spaceOccupied > 0 for item in metrics)
        and any(item.freeSpace > 0 for item in metrics)
        and any(item.totalSpace > 0 for item in metrics)
        and any(item.spaceUtilization > 0 for item in metrics)
        and any(item.numExtraPallets > 0 for item in metrics)
        and any(item.utilizableFreeSpace > 0 for item in metrics)
    )


def _publish_frames(producer: Producer, topic: str, fixture: Path, count: int) -> dict[str, Any]:
    published = 0
    mutated = 0
    migrated = 0
    source_sensors: set[str] = set()
    base_ms = int(time.time() * 1000) - 1000
    with fixture.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            document = json.loads(line)
            migrated_this_frame = False
            for item in document.get("objects", []):
                bbox3d = item.get("bbox3d")
                if isinstance(bbox3d, dict) and "embedding" in bbox3d:
                    bbox3d["embeddings"] = bbox3d.pop("embedding")
                    migrated_this_frame = True
            if migrated_this_frame:
                migrated += 1
            frame = ParseDict(document, schema_pb2.Frame(), ignore_unknown_fields=False)
            frame.timestamp.FromMilliseconds(base_ms + published * 34)
            source_sensors.add(frame.sensorId)
            if frame.objects:
                frame.objects[0].type = "Pallet"
                del frame.objects[0].bbox3d.coordinates[:]
                frame.objects[0].bbox3d.coordinates.extend(PALLET_COORDINATES)
                frame.objects[0].bbox3d.confidence = 0.9795588254928589
                mutated += 1
            producer.produce(
                topic,
                key=frame.sensorId.encode("utf-8"),
                value=frame.SerializeToString(),
            )
            published += 1
            if published >= count:
                break
    producer.flush(15)
    if published != count or mutated == 0:
        raise RuntimeError(f"fixture publish incomplete: published={published} mutated={mutated}")
    return {
        "published": published,
        "pallet_frames": mutated,
        "synthetic_pallet_coordinates": PALLET_COORDINATES,
        "legacy_embedding_key_migrated_frames": migrated,
        "source_sensors": sorted(source_sensors),
    }


def _summary(values: list[ext_pb2.SpaceUtilization]) -> dict[str, Any]:
    metrics = [value.metrics for value in values]
    consistency_error = max(
        abs((item.spaceOccupied + item.freeSpace) - item.totalSpace)
        for item in metrics
    )
    ratio_error = max(
        abs(item.spaceUtilization - (item.spaceOccupied / item.totalSpace))
        for item in metrics if item.totalSpace > 0
    )
    return {
        "output_count": len(values),
        "zone_ids": sorted({value.id for value in values}),
        "positive_records": {
            "occupied": sum(item.spaceOccupied > 0 for item in metrics),
            "free": sum(item.freeSpace > 0 for item in metrics),
            "total": sum(item.totalSpace > 0 for item in metrics),
            "ratio": sum(item.spaceUtilization > 0 for item in metrics),
            "extra_pallets": sum(item.numExtraPallets > 0 for item in metrics),
            "utilizable_free_space": sum(item.utilizableFreeSpace > 0 for item in metrics),
        },
        "ranges": {
            "occupied": [min(item.spaceOccupied for item in metrics), max(item.spaceOccupied for item in metrics)],
            "free": [min(item.freeSpace for item in metrics), max(item.freeSpace for item in metrics)],
            "total": [min(item.totalSpace for item in metrics), max(item.totalSpace for item in metrics)],
            "ratio": [min(item.spaceUtilization for item in metrics), max(item.spaceUtilization for item in metrics)],
            "extra_pallets": [min(item.numExtraPallets for item in metrics), max(item.numExtraPallets for item in metrics)],
            "utilizable_free_space": [min(item.utilizableFreeSpace for item in metrics), max(item.utilizableFreeSpace for item in metrics)],
        },
        "free_plus_occupied_max_error": consistency_error,
        "ratio_max_error": ratio_error,
        "free_layout_records": sum(bool(value.layouts.freeSpace) for value in values),
        "utilizable_layout_records": sum(bool(value.layouts.utilizableFreeSpace) for value in values),
    }


def run_probe(config_path: Path, calibration_path: Path, fixture_path: Path, frame_count: int) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    topics = _topics(config)
    topic_names = sorted(topics.values())
    admin = AdminClient({"bootstrap.servers": BROKER})
    existing = set(admin.list_topics(timeout=10).topics).intersection(topic_names)
    if existing:
        for future in admin.delete_topics(sorted(existing), operation_timeout=20).values():
            future.result(timeout=25)
    for future in admin.create_topics(
        [NewTopic(topic, num_partitions=1, replication_factor=1) for topic in topic_names]
    ).values():
        future.result(timeout=25)

    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": f"vss-oracle-ba-space-observer-{int(time.time())}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([topics["spaceUtilization"]])
    _ready.consumer = consumer
    producer = Producer({"bootstrap.servers": BROKER})
    values: list[ext_pb2.SpaceUtilization] = []
    state: dict[str, Any] = {}
    log_value = ""
    result: dict[str, Any] = {}
    try:
        _run("docker", "rm", "-f", CONTAINER, check=False)
        created = _run(
            "docker", "run", "-d", "--name", CONTAINER, "--network", "host", "--user", "nvs",
            "-v", f"{config_path.resolve()}:/resources/space-config.json:ro",
            "-v", f"{calibration_path.resolve()}:/resources/calibration.json:ro",
            IMAGE,
            "python3", "apps/analytics/main_analytics_3d_app.py",
            "--config", "/resources/space-config.json",
            "--calibration", "/resources/calibration.json",
        )
        if not created.stdout.strip():
            raise RuntimeError("docker run returned no container ID")
        _wait_for(
            lambda: (_logs() if _logs().count("Task Ready for processing...") >= 3 else None),
            "three Analytics3DApp workers",
            timeout=75,
        )
        published = _publish_frames(producer, topics["raw"], fixture_path, frame_count)
        try:
            _wait_for(lambda: _ready(values), "all six positive space-utilization metrics", timeout=45)
        except TimeoutError as exc:
            logs = _logs()
            partial = _summary(values) if values else {"output_count": 0}
            markers = {
                "space_invocations": logs.count("Invoking space utilization."),
                "space_metric_blocks": logs.count("metrics for buffer zone:"),
                "worker_traceback": "Traceback (most recent call last)" in logs,
                "worker_fatal": "FATAL - Error in app" in logs,
            }
            raise RuntimeError(
                f"space-utilization gate timeout: partial={partial}, markers={markers}"
            ) from exc
        _run("docker", "stop", "-t", "30", CONTAINER)
        _consume_available(consumer, values)
        log_value = _logs()
        summary = _summary(values)
        if summary["free_plus_occupied_max_error"] > 0.02 or summary["ratio_max_error"] > 0.02:
            raise RuntimeError(f"space metric arithmetic drifted: {summary}")
        if summary["free_layout_records"] == 0 or summary["utilizable_layout_records"] == 0:
            raise RuntimeError(f"space layouts were not emitted: {summary}")
        result = {"input": published, "outputs": summary}
    finally:
        inspect = _run("docker", "inspect", CONTAINER, check=False)
        if inspect.returncode == 0:
            current = json.loads(inspect.stdout)[0]
            if current["State"]["Running"]:
                _run("docker", "stop", "-t", "30", CONTAINER, check=False)
            final = json.loads(_run("docker", "inspect", CONTAINER).stdout)[0]
            state = {
                "exit_code": final["State"]["ExitCode"],
                "oom_killed": final["State"]["OOMKilled"],
                "restart_count": final["RestartCount"],
                "image_id": final["Image"],
            }
            if not log_value:
                log_value = _logs()
            _run("docker", "rm", CONTAINER, check=False)
        consumer.close()
        producer.flush(3)
        present = set(admin.list_topics(timeout=10).topics).intersection(topic_names)
        if present:
            for future in admin.delete_topics(sorted(present), operation_timeout=20).values():
                future.result(timeout=25)

    expected = {"exit_code": 0, "oom_killed": False, "restart_count": 0, "image_id": IMAGE_ID}
    if state != expected:
        raise RuntimeError(f"container exit integrity failed: {state}")
    remaining = set(admin.list_topics(timeout=10).topics).intersection(topic_names)
    result.update({
        "config_sha256": _sha_file(config_path),
        "calibration_sha256": _sha_file(calibration_path),
        "fixture_sha256": _sha_file(fixture_path),
        "container": state,
        "log_sha256": _sha_bytes(log_value.encode("utf-8")),
        "topics_absent": not remaining,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=300)
    args = parser.parse_args()
    try:
        print(json.dumps(run_probe(
            args.config.resolve(), args.calibration.resolve(), args.fixture.resolve(), args.frame_count
        ), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
