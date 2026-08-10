#!/usr/bin/env python3
"""Run bounded Kafka NvSchema and Redis Streams qualification on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
PROTOCOL_CASES = (
    REPO
    / "deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.json"
)


class QualificationError(RuntimeError):
    """A fail-closed event-transport qualification error."""


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise QualificationError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _command(
    args: list[str], *, timeout: float = 30, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise QualificationError(f"command failed ({args[0]}): {message[-1000:]}")
    return completed


def _docker_json(args: list[str], *, timeout: float = 30) -> Any:
    result = _command(["docker", *args], timeout=timeout)
    return json.loads(result.stdout)


def _container(container: str) -> dict[str, Any]:
    rows = _docker_json(["inspect", container])
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError(f"could not inspect exact container {container}")
    return rows[0]


def _image(reference: str) -> dict[str, Any]:
    rows = _docker_json(["image", "inspect", reference])
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError(f"could not inspect exact image {reference}")
    return rows[0]


def _kafka_topics() -> list[str]:
    result = _command(
        [
            "docker",
            "exec",
            "kafka",
            "kafka-topics",
            "--bootstrap-server",
            "localhost:9092",
            "--list",
        ]
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _kafka_groups() -> list[str]:
    result = _command(
        [
            "docker",
            "exec",
            "kafka",
            "kafka-consumer-groups",
            "--bootstrap-server",
            "localhost:9092",
            "--list",
        ]
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _redis_keys() -> list[str]:
    result = _command(
        ["docker", "exec", "redis", "redis-cli", "--scan", "--pattern", "*"],
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _health(container: dict[str, Any]) -> str:
    return str(container.get("State", {}).get("Health", {}).get("Status", ""))


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    source_hashes: dict[str, str] = {}
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        actual = _sha(path.read_bytes())
        if actual != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
        source_hashes[lock["path"]] = actual

    broker_path = REPO / contract["broker_contract"]["path"]
    broker_contract, broker_raw = _load_json(broker_path)
    if _sha(broker_raw) != contract["broker_contract"]["sha256"]:
        raise QualificationError("broker topic contract digest drifted")
    kafka_names = [row["name"] for row in broker_contract["kafka"]]
    redis_names = [row["name"] for row in broker_contract["redis"]]
    if (
        len(kafka_names) != contract["broker_contract"]["kafka_topic_count"]
        or len(redis_names) != contract["broker_contract"]["redis_stream_count"]
        or set(kafka_names) == set(redis_names)
        or broker_contract.get("must_not_claim_equivalent_topic_sets") is not True
    ):
        raise QualificationError("advertised broker topic/stream table drifted")

    protocol, _ = _load_json(PROTOCOL_CASES)
    cases_by_id = {row["case_id"]: row for row in protocol["cases"]}
    case_hashes: dict[str, str] = {}
    for lock in contract["protocol_cases"]:
        case = cases_by_id.get(lock["case_id"])
        if case is None or _canonical_sha(case) != lock["sha256"]:
            raise QualificationError(f"protocol case drifted: {lock['case_id']}")
        if (
            case["positive_vector"]["id"] != lock["positive_vector_id"]
            or [row["id"] for row in case["adjacent_negative_vectors"]]
            != [lock["negative_vector_id"]]
        ):
            raise QualificationError(f"protocol vector binding drifted: {lock['case_id']}")
        case_hashes[lock["case_id"]] = lock["sha256"]

    return {
        "source_hashes": source_hashes,
        "broker_contract": {
            "sha256": contract["broker_contract"]["sha256"],
            "kafka_topic_count": len(kafka_names),
            "redis_stream_count": len(redis_names),
            "topic_sets_distinct": set(kafka_names) != set(redis_names),
        },
        "protocol_case_hashes": case_hashes,
    }


def _verify_runtime_identity(contract: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for key in ("kafka_runner", "redis_runner"):
        expected = contract["runtime_images"][key]
        image = _image(expected["reference"])
        actual = {
            "reference": expected["reference"],
            "image_id": image["Id"],
            "architecture": image["Architecture"],
        }
        if actual != expected:
            raise QualificationError(f"runtime image identity drifted: {key}")
        results[key] = actual

    for key in ("kafka_broker", "redis_broker"):
        expected = contract["runtime_images"][key]
        container = _container(expected["container"])
        broker_image = _image(expected["reference"])
        if container["Image"] != expected["image_id"]:
            raise QualificationError(f"broker image identity drifted: {key}")
        if container.get("HostConfig", {}).get("NetworkMode") != "host":
            raise QualificationError(f"broker is not on expected host network: {key}")
        if _health(container) != "healthy":
            raise QualificationError(f"broker is not healthy: {key}")
        results[key] = {
            "container": expected["container"],
            "reference": expected["reference"],
            "image_id": container["Image"],
            "architecture": broker_image["Architecture"],
            "network_mode": "host",
            "health": "healthy",
        }
    return results


def _run_runner(
    *,
    name: str,
    image: str,
    source_mount: tuple[Path, str],
    script: Path,
    pythonpath: str,
) -> dict[str, Any]:
    result = _command(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "host",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,src={source_mount[0]},dst={source_mount[1]},readonly",
            "--mount",
            f"type=bind,src={script},dst=/runner.py,readonly",
            "--env",
            f"PYTHONPATH={pythonpath}",
            "--entrypoint",
            "python3",
            image,
            "/runner.py",
        ],
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise QualificationError(
            f"{name} failed: {(result.stderr.strip() or result.stdout.strip())[-1200:]}"
        )
    json_lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    if len(json_lines) != 1:
        raise QualificationError(f"{name} did not emit exactly one JSON result")
    value = json.loads(json_lines[0])
    if value.get("status") != "passed":
        raise QualificationError(f"{name} did not pass")
    return value


def _cleanup(contract: dict[str, Any]) -> dict[str, Any]:
    owned = contract["owned_resources"]
    failures: list[str] = []

    for name in (
        owned["kafka_runner_container"],
        owned["redis_runner_container"],
    ):
        result = _command(["docker", "rm", "-f", name], check=False)
        if result.returncode not in (0, 1):
            failures.append(f"remove_runner:{name}")

    _command(
        [
            "docker",
            "exec",
            "kafka",
            "kafka-consumer-groups",
            "--bootstrap-server",
            "localhost:9092",
            "--delete",
            "--group",
            owned["kafka_group"],
        ],
        check=False,
    )
    _command(
        [
            "docker",
            "exec",
            "kafka",
            "kafka-topics",
            "--bootstrap-server",
            "localhost:9092",
            "--delete",
            "--topic",
            owned["kafka_topic"],
        ],
        check=False,
    )
    _command(
        [
            "docker",
            "exec",
            "redis",
            "redis-cli",
            "XGROUP",
            "DESTROY",
            owned["redis_stream"],
            owned["redis_effective_group"],
        ],
        check=False,
    )
    _command(
        [
            "docker",
            "exec",
            "redis",
            "redis-cli",
            "DEL",
            owned["redis_stream"],
        ],
        check=False,
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        topics = _kafka_topics()
        groups = _kafka_groups()
        redis_keys = _redis_keys()
        if owned["kafka_group"] in groups:
            _command(
                [
                    "docker",
                    "exec",
                    "kafka",
                    "kafka-consumer-groups",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--delete",
                    "--group",
                    owned["kafka_group"],
                ],
                check=False,
            )
        if owned["kafka_topic"] in topics:
            _command(
                [
                    "docker",
                    "exec",
                    "kafka",
                    "kafka-topics",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--delete",
                    "--topic",
                    owned["kafka_topic"],
                ],
                check=False,
            )
        if owned["redis_stream"] in redis_keys:
            _command(
                [
                    "docker",
                    "exec",
                    "redis",
                    "redis-cli",
                    "XGROUP",
                    "DESTROY",
                    owned["redis_stream"],
                    owned["redis_effective_group"],
                ],
                check=False,
            )
            _command(
                [
                    "docker",
                    "exec",
                    "redis",
                    "redis-cli",
                    "DEL",
                    owned["redis_stream"],
                ],
                check=False,
            )
        if (
            owned["kafka_topic"] not in topics
            and owned["kafka_group"] not in groups
            and owned["redis_stream"] not in redis_keys
        ):
            break
        time.sleep(1)
    else:
        failures.append("owned_resources_still_present")
    return {"attempted": True, "failures": failures}


def execute() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    contract, contract_raw = _load_json(CONTRACT_PATH)
    owned = contract["owned_resources"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "status": "failed",
        "failure": None,
        "blockers": [],
        "captured_at": started.isoformat().replace("+00:00", "Z"),
        "contract_sha256": _sha(contract_raw),
        "target_release": contract["target_release"],
        "target_commit": contract["target_commit"],
        "network_scope": contract["network_scope"],
        "warehouse_sample_bundle": False,
        "forbidden_actions_observed": [],
        "semantic_action_count": 0,
        "writes_or_lifecycle_actions": False,
    }
    before: dict[str, Any] = {}
    mutation_started = False
    try:
        receipt["static_contract"] = _verify_static(contract)
        receipt["runtime_identity"] = _verify_runtime_identity(contract)
        before = {
            "kafka_topics": _kafka_topics(),
            "kafka_groups": _kafka_groups(),
            "redis_keys": _redis_keys(),
        }
        blockers = []
        if owned["kafka_topic"] in before["kafka_topics"]:
            blockers.append("owned Kafka topic was not absent at pre-state")
        if owned["kafka_group"] in before["kafka_groups"]:
            blockers.append("owned Kafka group was not absent at pre-state")
        if owned["redis_stream"] in before["redis_keys"]:
            blockers.append("owned Redis stream was not absent at pre-state")
        for runner in (
            owned["kafka_runner_container"],
            owned["redis_runner_container"],
        ):
            if _command(["docker", "inspect", runner], check=False).returncode == 0:
                blockers.append(f"owned runner container was not absent: {runner}")
        if blockers:
            receipt["blockers"] = blockers
            receipt["failure"] = "precondition_failed"
            return receipt

        receipt["pre_state"] = {
            "owned_resources_absent": True,
            "kafka_nonowned_topic_count": len(before["kafka_topics"]),
            "kafka_nonowned_topic_names_sha256": _canonical_sha(before["kafka_topics"]),
            "kafka_nonowned_group_count": len(before["kafka_groups"]),
            "redis_nonowned_key_count": len(before["redis_keys"]),
            "redis_nonowned_key_names_sha256": _canonical_sha(before["redis_keys"]),
        }
        mutation_started = True
        receipt["writes_or_lifecycle_actions"] = True

        kafka = _run_runner(
            name=owned["kafka_runner_container"],
            image=contract["runtime_images"]["kafka_runner"]["reference"],
            source_mount=(REPO / "services/alert", "/workspace/alert"),
            script=HERE / "kafka_runner.py",
            pythonpath="/workspace/alert:/workspace/alert/alert-agent-web",
        )
        receipt["semantic_action_count"] += 2
        redis = _run_runner(
            name=owned["redis_runner_container"],
            image=contract["runtime_images"]["redis_runner"]["reference"],
            source_mount=(
                REPO / "services/analytics/behavior-analytics/src",
                "/workspace/behavior/src",
            ),
            script=HERE / "redis_runner.py",
            pythonpath="/workspace/behavior/src",
        )
        receipt["semantic_action_count"] += 2
        receipt["runtime"] = {"kafka": kafka, "redis": redis}
    except (QualificationError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        receipt["failure"] = type(exc).__name__
        print(f"[event-transports] {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if mutation_started:
            cleanup = _cleanup(contract)
            after_topics = _kafka_topics()
            after_groups = _kafka_groups()
            after_redis = _redis_keys()
            cleanup.update(
                {
                    "owned_kafka_topic_absent": owned["kafka_topic"] not in after_topics,
                    "owned_kafka_group_absent": owned["kafka_group"] not in after_groups,
                    "owned_redis_stream_absent": owned["redis_stream"] not in after_redis,
                    "kafka_nonowned_topic_set_exact": after_topics
                    == before["kafka_topics"],
                    "redis_nonowned_key_set_exact": after_redis == before["redis_keys"],
                    "kafka_health_after": _health(_container("kafka")),
                    "redis_health_after": _health(_container("redis")),
                }
            )
            receipt["cleanup"] = cleanup
            cleanup_pass = (
                cleanup["failures"] == []
                and cleanup["owned_kafka_topic_absent"]
                and cleanup["owned_kafka_group_absent"]
                and cleanup["owned_redis_stream_absent"]
                and cleanup["kafka_nonowned_topic_set_exact"]
                and cleanup["redis_nonowned_key_set_exact"]
                and cleanup["kafka_health_after"] == "healthy"
                and cleanup["redis_health_after"] == "healthy"
            )
            if not cleanup_pass and receipt["failure"] is None:
                receipt["failure"] = "cleanup_postcondition_failed"

    passed = (
        receipt.get("runtime", {}).get("kafka", {}).get("status") == "passed"
        and receipt.get("runtime", {}).get("redis", {}).get("status") == "passed"
        and receipt.get("semantic_action_count") == 4
        and receipt.get("cleanup", {}).get("failures") == []
        and receipt.get("failure") is None
    )
    if passed:
        receipt["status"] = "passed"
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    receipt["duration_ms"] = round(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = execute()
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
