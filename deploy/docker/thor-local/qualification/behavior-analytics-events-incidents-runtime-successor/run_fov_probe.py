#!/usr/bin/env python3
"""Generate and decode a deterministic FOV-count incident through Analytics2DApp."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "services/analytics/behavior-analytics/src"))
HELPER_PATH = REPO / "deploy/docker/thor-local/qualification/behavior-analytics-broker-control-runtime-successor/run_broker_probe.py"
SPEC = importlib.util.spec_from_file_location("behavior_broker_probe_helper", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

from mdx.analytics.core.schema.proto import ext_pb2  # noqa: E402


IMAGE = helper.IMAGE
IMAGE_ID = helper.IMAGE_ID
CONTAINER = "vss-behavior-fov-count-oracle"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _incidents(transport: Any) -> list[Any]:
    values = []
    for record in transport.records("incidents"):
        value = ext_pb2.Incident()
        try:
            value.ParseFromString(record["value"])
        except Exception:
            continue
        values.append(value)
    return values


def _fov_summary(transport: Any) -> dict[str, Any] | None:
    values = [value for value in _incidents(transport) if value.category == "FOV Count Violation"]
    if not values:
        return None
    return {
        "count": len(values),
        "categories": sorted({value.category for value in values}),
        "sensor_ids": sorted({value.sensorId for value in values}),
        "object_id_counts": [len(value.objectIds) for value in values],
        "all_start_before_or_equal_end": all(
            value.timestamp.ToMilliseconds() <= value.end.ToMilliseconds() for value in values
        ),
        "positive_time_bounds": all(
            value.timestamp.ToMilliseconds() > 0 and value.end.ToMilliseconds() > 0 for value in values
        ),
        "complete_count": sum(value.info.get("isComplete") == "true" for value in values),
    }


def run_probe(config_path: Path, calibration_path: Path, fixture_path: Path, frame_count: int) -> dict[str, Any]:
    baseline_config = helper._strict_json(config_path)
    config = json.loads(json.dumps(baseline_config))
    fov_entries = [
        {"name": "fovCountViolationIncidentEnable", "value": "true"},
        {"name": "fovCountViolationIncidentObjectThreshold", "value": "1"},
        {"name": "fovCountViolationIncidentThreshold", "value": "0.1"},
        {"name": "fovCountViolationIncidentExpirationWindow", "value": "0.1"},
        {"name": "fovCountViolationIncidentObjectType", "value": "Person"},
    ]
    by_name = {item["name"]: item for item in config["app"]}
    for item in fov_entries:
        by_name[item["name"]] = item
    config["app"] = list(by_name.values())
    tempdir = tempfile.TemporaryDirectory(prefix="vss-ba-fov-")
    runtime_config_path = Path(tempdir.name) / "fov-config.json"
    runtime_config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    mapping = helper._mapping(config, "kafka")
    transport = helper.KafkaTransport(mapping)
    state: dict[str, Any] = {}
    log_value = ""
    result: dict[str, Any] = {}
    try:
        helper._run("docker", "rm", "-f", CONTAINER, check=False)
        created = helper._run(
            "docker", "run", "-d", "--name", CONTAINER, "--network", "host", "--user", "nvs",
            "-v", f"{runtime_config_path}:/resources/fov-config.json:ro",
            "-v", f"{calibration_path.resolve()}:/resources/calibration.json:ro",
            IMAGE,
            "python3", "apps/analytics/main_analytics_2d_app.py",
            "--config", "/resources/fov-config.json",
            "--calibration", "/resources/calibration.json",
        )
        if not created.stdout.strip():
            raise RuntimeError("docker run returned no container ID")

        request_reference = helper._wait_request_reference(transport)
        transport.publish(
            "notification",
            b"behavior-analytics-config",
            json.dumps({"status": "success", "config": config, "error": None}, separators=(",", ":")).encode(),
            {"event.type": "upsert-all", "reference-id": request_reference},
        )
        helper._wait_log(CONTAINER, ("applied config from upsert-all-config-",), "bootstrap config apply")
        helper._wait_log_count(CONTAINER, "Task Ready for processing...", 2, "both 2D workers")
        helper._wait_log_count(
            CONTAINER,
            f"Group ID: {config['kafka']['group']} - {mapping['raw']} - Analytics2DApp.",
            2,
            "both Kafka raw assignments",
        )

        helper._publish_frames(transport, fixture_path, frame_count, 60)
        summary = helper._wait_for(
            lambda: _fov_summary(transport), "decoded FOV Count Violation", timeout=90
        )
        if not summary["all_start_before_or_equal_end"] or not summary["positive_time_bounds"]:
            raise RuntimeError(f"FOV incident time bounds drifted: {summary}")
        if not summary["sensor_ids"] or not all(count > 0 for count in summary["object_id_counts"]):
            raise RuntimeError(f"FOV incident identity drifted: {summary}")
        log_value = helper._container_logs(CONTAINER)
        result = {
            "bootstrap_reference_sha256": _sha_bytes(request_reference.encode()),
            "fov_config": {"app": fov_entries},
            "input_frames": frame_count,
            "incidents": summary,
        }
    finally:
        inspect = helper._run("docker", "inspect", CONTAINER, check=False)
        if inspect.returncode == 0:
            current = json.loads(inspect.stdout)[0]
            if current["State"]["Running"]:
                helper._run("docker", "stop", "-t", "30", CONTAINER, check=False)
            final = json.loads(helper._run("docker", "inspect", CONTAINER).stdout)[0]
            state = {
                "exit_code": final["State"]["ExitCode"],
                "oom_killed": final["State"]["OOMKilled"],
                "restart_count": final["RestartCount"],
                "image_id": final["Image"],
            }
            if not log_value:
                log_value = helper._container_logs(CONTAINER)
            helper._run("docker", "rm", CONTAINER, check=False)
        transport.cleanup()
        tempdir.cleanup()

    expected = {"exit_code": 0, "oom_killed": False, "restart_count": 0, "image_id": IMAGE_ID}
    if state != expected:
        raise RuntimeError(f"container exit integrity failed: {state}")
    remaining = set(transport.admin.list_topics(timeout=10).topics).intersection(mapping.values())
    result.update({
        "baseline_config_sha256": helper._sha_file(config_path),
        "runtime_config_sha256": _sha_bytes(
            (json.dumps(config, indent=2, sort_keys=True) + "\n").encode()
        ),
        "calibration_sha256": helper._sha_file(calibration_path),
        "fixture_sha256": helper._sha_file(fixture_path),
        "container": state,
        "log_sha256": _sha_bytes(log_value.encode()),
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
