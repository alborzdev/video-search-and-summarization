#!/usr/bin/env python3
"""Exercise both embedding downsamplers through the released Fusion Search app."""

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


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "services/analytics/behavior-analytics/src"))

from mdx.analytics.core.schema.proto import schema_pb2 as nv_schema  # noqa: E402


IMAGE = "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1"
IMAGE_ID = "sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6"
BROKER = "localhost:9092"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _topics(config: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["value"] for item in config["kafka"]["topics"]}


def _logs(container: str) -> str:
    result = _run("docker", "logs", container, check=False)
    return result.stdout + result.stderr


def _wait_for(predicate, description: str, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {description}")


def _wait_log(container: str, marker: str, count: int = 1) -> str:
    return _wait_for(
        lambda: (value if value.count(marker) >= count else None)
        if (value := _logs(container))
        else None,
        f"{count} occurrences of {marker!r}",
        timeout=75,
    )


def _embedding(index: int, sensor_id: str = "qualification-camera") -> nv_schema.VisionLLM:
    value = nv_schema.VisionLLM()
    base_ms = 1_750_000_000_000
    value.version = "1.0"
    value.timestamp.FromMilliseconds(base_ms + index * 1000)
    value.end.FromMilliseconds(base_ms + index * 1000)
    value.startFrameId = str(index)
    value.endFrameId = str(index)
    value.sensor.id = sensor_id
    vector = [1.0, 0.0, 0.0, 0.0] if index < 12 else [0.0, 1.0, 0.0, 0.0]
    value.llm.visionEmbeddings.add().vector.extend(vector)
    return value


def _consume(consumer: Consumer, timeout: float) -> list[nv_schema.VisionLLM]:
    deadline = time.monotonic() + timeout
    values: list[nv_schema.VisionLLM] = []
    seen: set[str] = set()
    while time.monotonic() < deadline:
        record = consumer.poll(0.25)
        if record is None or record.error():
            continue
        value = nv_schema.VisionLLM()
        value.ParseFromString(record.value())
        if value.endFrameId not in seen:
            values.append(value)
            seen.add(value.endFrameId)
    return values


def run_mode(mode: str, config_path: Path) -> dict[str, Any]:
    config = _load_config(config_path)
    topics = _topics(config)
    all_topics = sorted(topics.values())
    admin = AdminClient({"bootstrap.servers": BROKER})
    existing = set(admin.list_topics(timeout=10).topics).intersection(all_topics)
    if existing:
        for future in admin.delete_topics(sorted(existing), operation_timeout=20).values():
            future.result(timeout=25)
    for future in admin.create_topics(
        [NewTopic(topic, num_partitions=1, replication_factor=1) for topic in all_topics]
    ).values():
        future.result(timeout=25)

    consumer = Consumer(
        {
            "bootstrap.servers": BROKER,
            "group.id": f"vss-oracle-ba-embed-observer-{mode}-{int(time.time())}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topics["embedFiltered"]])
    producer = Producer({"bootstrap.servers": BROKER})
    container = f"vss-behavior-embed-{mode}-oracle"
    state: dict[str, Any] = {}
    values: list[nv_schema.VisionLLM] = []
    log_value = ""
    try:
        _run("docker", "rm", "-f", container, check=False)
        created = _run(
            "docker", "run", "-d", "--name", container, "--network", "host", "--user", "nvs",
            "-v", f"{config_path.resolve()}:/resources/downsampling-config.json:ro",
            IMAGE,
            "python3", "apps/fusion_search/main_fusion_search_analytics_app.py",
            "--config", "/resources/downsampling-config.json",
        )
        if not created.stdout.strip():
            raise RuntimeError("docker run returned no container ID")
        _wait_log(container, "Task Ready for processing...", count=2)
        _wait_log(container, "Embed filtering mode - enabled", count=2)

        for index in range(13):
            value = _embedding(index)
            producer.produce(
                topics["embed"],
                key=value.sensor.id.encode("utf-8"),
                value=value.SerializeToString(),
            )
        producer.flush(10)
        values.extend(_consume(consumer, 8))

        _run("docker", "stop", "-t", "30", container)
        values.extend(_consume(consumer, 5))
        by_id = {value.endFrameId: value for value in values}
        values = [by_id[key] for key in sorted(by_id, key=int)]
        log_value = _logs(container)
        if not 0 < len(values) < 13:
            raise RuntimeError(f"{mode} did not downsample 13 inputs: {len(values)} outputs")
        if "0" not in by_id or "12" not in by_id:
            raise RuntimeError(f"{mode} did not preserve first point and novel final transition")
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
            if not log_value:
                log_value = _logs(container)
            _run("docker", "rm", container, check=False)
        consumer.close()
        producer.flush(3)
        present = set(admin.list_topics(timeout=10).topics).intersection(all_topics)
        if present:
            for future in admin.delete_topics(sorted(present), operation_timeout=20).values():
                future.result(timeout=25)

    expected_state = {
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
        "image_id": IMAGE_ID,
    }
    if state != expected_state:
        raise RuntimeError(f"container exit integrity failed: {state}")
    remaining = set(admin.list_topics(timeout=10).topics).intersection(all_topics)
    return {
        "mode": mode,
        "config_sha256": _sha_file(config_path),
        "input_count": 13,
        "output_count": len(values),
        "output_frame_ids": [value.endFrameId for value in values],
        "first_point_preserved": values[0].endFrameId == "0",
        "novel_transition_preserved": values[-1].endFrameId == "12",
        "compression_observed": len(values) < 13,
        "sensor_ids": sorted({value.sensor.id for value in values}),
        "container": state,
        "log_sha256": _sha_bytes(log_value.encode("utf-8")),
        "topics_absent": not remaining,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("window", "sdt"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_mode(args.mode, args.config.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
