#!/usr/bin/env python3
"""Bounded Thor proof of RT-VLM incident generation and category propagation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"


class QualificationError(RuntimeError):
    pass


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load source-locked helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> tuple[Any, Any]:
    if contract["official_indices"] != [343, 344]:
        raise QualificationError("official incident/category indices drifted")
    paths: dict[str, Path] = {}
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
        paths[lock["path"]] = path
    dense = _load_module(
        "_incident_dense_helper",
        paths[
            "deploy/docker/thor-local/qualification/"
            "rt-vlm-file-dense-captions-runtime-successor/execute.py"
        ],
    )
    _, fixture = dense._verify_static(dense._load_json(dense.CONTRACT_PATH))
    Draft202012Validator.check_schema(_load_json(RECEIPT_SCHEMA_PATH))
    return dense, fixture


def _docker(
    args: list[str], counter: list[int], *, timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    try:
        return subprocess.run(
            ["docker", *args], check=True, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _runtime_identity(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    rt_name = contract["execution"]["rt_vlm_container"]
    kafka_name = contract["kafka"]["container"]
    try:
        rt = json.loads(_docker(["inspect", rt_name], counter).stdout)[0]
        kafka = json.loads(_docker(["inspect", kafka_name], counter).stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError) as exc:
        raise QualificationError("runtime inspect envelope invalid") from exc
    for row, image_id, label in (
        (rt, contract["model"]["image_id"], "RT-VLM"),
        (kafka, contract["kafka"]["image_id"], "Kafka"),
    ):
        state = row.get("State", {})
        if (
            state.get("Status") != "running"
            or state.get("Health", {}).get("Status") != "healthy"
            or state.get("OOMKilled") is not False
            or row.get("RestartCount") != 0
            or row.get("Image") != image_id
        ):
            raise QualificationError(f"{label} runtime identity drifted")
    try:
        kafka_image = json.loads(
            _docker(["image", "inspect", contract["kafka"]["image_id"]], counter).stdout
        )[0]
    except (json.JSONDecodeError, IndexError) as exc:
        raise QualificationError("Kafka image inspect envelope invalid") from exc
    if kafka_image.get("Architecture") != contract["kafka"]["architecture"]:
        raise QualificationError("Kafka image architecture drifted")
    paths = [
        lock["container_path"]
        for lock in contract["source_locks"]
        if lock.get("container_path")
    ]
    raw = _docker(["exec", rt_name, "sha256sum", *paths], counter).stdout.decode()
    live = {line.split()[1]: line.split()[0] for line in raw.splitlines() if line}
    for lock in contract["source_locks"]:
        path = lock.get("container_path")
        if path and live.get(path) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {path}")
    return {
        "rt_vlm_healthy": True,
        "rt_vlm_image_exact": True,
        "rt_vlm_restart_count": 0,
        "rt_vlm_oom_killed": False,
        "kafka_healthy": True,
        "kafka_image_exact": True,
        "kafka_architecture_exact": True,
        "kafka_restart_count": 0,
        "kafka_oom_killed": False,
        "live_source_count": len(paths),
        "live_sources_match_locks": True,
    }


CONSUMER_CODE = r'''
import json
import os
import sys
import time

from kafka import KafkaConsumer, TopicPartition

sys.path.insert(0, "/opt/nvidia/rtvi/rtvi")
from server.protos import ext_pb2

category = sys.argv[1]
topic = os.environ["KAFKA_INCIDENT_TOPIC"]
consumer = KafkaConsumer(
    bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
    group_id=None,
    enable_auto_commit=False,
    consumer_timeout_ms=1000,
)
partitions = sorted(consumer.partitions_for_topic(topic) or [])
assigned = [TopicPartition(topic, partition) for partition in partitions]
consumer.assign(assigned)
for partition, offset in consumer.end_offsets(assigned).items():
    consumer.seek(partition, offset)
print(
    json.dumps(
        {"status": "ready", "partition_count": len(partitions), "child_pid": os.getpid()}
    ),
    flush=True,
)
deadline = time.monotonic() + 90
seen = 0
decode_failures = 0
while time.monotonic() < deadline:
    for records in consumer.poll(timeout_ms=1000, max_records=64).values():
        for record in records:
            seen += 1
            incident = ext_pb2.Incident()
            try:
                incident.ParseFromString(record.value)
            except Exception:
                decode_failures += 1
                continue
            if incident.category != category:
                continue
            info = incident.info
            queries = incident.llm.queries if incident.HasField("llm") else []
            result = {
                "status": "matched",
                "partition_count": len(partitions),
                "future_records_seen": seen,
                "decode_failures": decode_failures,
                "protobuf_decoded": True,
                "category_exact": True,
                "alert_category_info_exact": info.get("alertCategory") == category,
                "is_anomaly": incident.isAnomaly,
                "verdict_confirmed": info.get("verdict") == "confirmed",
                "positive_trigger_present": bool(info.get("triggerPhrase")),
                "request_identity_present": bool(info.get("requestId")),
                "chunk_identity_present": bool(info.get("chunkIdx")),
                "stream_identity_present": bool(info.get("streamId")),
                "llm_query_present": len(queries) >= 1,
                "llm_response_nonempty": any(bool(query.response.strip()) for query in queries),
            }
            print(json.dumps(result, sort_keys=True), flush=True)
            consumer.close()
            raise SystemExit(0)
consumer.close()
print(json.dumps({"status": "timed_out", "future_records_seen": seen}), flush=True)
raise SystemExit(2)
'''


def _start_consumer(
    contract: dict[str, Any], counter: list[int]
) -> tuple[subprocess.Popen[bytes], int, int]:
    counter[0] += 1
    try:
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                contract["execution"]["rt_vlm_container"],
                "timeout",
                "100",
                "python3",
                "-u",
                "-c",
                CONSUMER_CODE,
                contract["kafka"]["category"],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise QualificationError("cannot start bounded Kafka observer") from exc
    if process.stdout is None or not select.select([process.stdout], [], [], 15)[0]:
        process.terminate()
        process.wait(timeout=5)
        raise QualificationError("Kafka observer readiness timed out")
    try:
        ready = json.loads(process.stdout.readline())
    except json.JSONDecodeError as exc:
        process.terminate()
        process.wait(timeout=5)
        raise QualificationError("Kafka observer readiness invalid") from exc
    if (
        ready.get("status") != "ready"
        or ready.get("partition_count", 0) < 1
        or type(ready.get("child_pid")) is not int
        or ready["child_pid"] < 2
    ):
        process.terminate()
        process.wait(timeout=5)
        raise QualificationError("Kafka incident topic is unavailable")
    return process, ready["partition_count"], ready["child_pid"]


def _finish_consumer(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    try:
        stdout, stderr = process.communicate(timeout=100)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        process.wait(timeout=5)
        raise QualificationError("Kafka observer exceeded its bound") from exc
    try:
        lines = [line for line in stdout.decode().splitlines() if line.strip()]
        value = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError as exc:
        raise QualificationError("Kafka observer result invalid") from exc
    if process.returncode != 0 or not isinstance(value, dict) or value.get("status") != "matched":
        raise QualificationError("owned incident was not observed on local Kafka")
    if stderr.strip():
        raise QualificationError("Kafka observer emitted unexpected diagnostics")
    required_true = (
        "protobuf_decoded",
        "category_exact",
        "alert_category_info_exact",
        "is_anomaly",
        "verdict_confirmed",
        "positive_trigger_present",
        "request_identity_present",
        "chunk_identity_present",
        "stream_identity_present",
        "llm_query_present",
        "llm_response_nonempty",
    )
    if not all(value.get(key) is True for key in required_true):
        raise QualificationError("Kafka incident/category semantics drifted")
    return value


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "mode": "plan",
        "status": "ready",
        "requires_acknowledgement": contract["execution"]["acknowledgement"],
        "append_only_kafka_records": 1,
        "agent_generate_calls": 0,
        "stream_mutations": 0,
        "core_service_lifecycle_actions": 0,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    dense, fixture_helper = _verify_static(contract)
    endpoint = dense._validate_endpoint(endpoint, dense._load_json(dense.CONTRACT_PATH))
    docker_commands = [0]
    runtime = _runtime_identity(contract, docker_commands)
    request_count = 0
    model_requests = 0

    def js(path: str, **kwargs: Any) -> tuple[int, bytes, Any]:
        nonlocal request_count
        request_count += 1
        return dense._http_json(endpoint, path, **kwargs)

    files_status, _, files = js("/v1/files?purpose=vision", timeout=15)
    models_status, _, models = js("/v1/models", timeout=15)
    stats_status, _, stats = js("/v1/assets/stats", timeout=15)
    health_status, _, health = js("/v1/health/ready", timeout=15)
    if any(status != 200 for status in (files_status, models_status, stats_status, health_status)):
        raise QualificationError("RT-VLM preflight failed")
    files_before = dense._catalog(files)
    model, models_before = dense._model(models, contract["model"]["id"])
    stats_before = _sha(_canonical(stats))
    health_before = _sha(_canonical(health))

    observer: subprocess.Popen[bytes] | None = None
    observer_child_pid: int | None = None
    resource_id: str | None = None
    deleted = False
    fixture_bytes = b""
    kafka_result: dict[str, Any] = {}
    semantic_hash = ""
    temp_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="rt-vlm-incidents-") as temp_dir:
        temp_path = Path(temp_dir)
        fixture_bytes = fixture_helper._generate_fixture(
            temp_path / "incident.mp4", time.monotonic() + 60
        )
        if (
            len(fixture_bytes) != contract["fixture"]["bytes"]
            or _sha(fixture_bytes) != contract["fixture"]["sha256"]
        ):
            raise QualificationError("deterministic incident fixture drifted")
        try:
            observer, partition_count, observer_child_pid = _start_consumer(
                contract, docker_commands
            )
            upload_body, upload_type = dense._multipart(
                fixture_bytes, filename="incident_timeline.mp4"
            )
            upload_status, upload_raw, upload = js(
                "/v1/files",
                method="POST",
                body=upload_body,
                headers={"Content-Type": upload_type},
                timeout=30,
            )
            if upload_status != 200 or not isinstance(upload, dict):
                raise QualificationError("incident fixture upload failed")
            resource_id = upload.get("id")
            if not isinstance(resource_id, str) or not resource_id:
                raise QualificationError("incident fixture identity missing")

            payload = {
                "id": resource_id,
                "model": model,
                "system_prompt": (
                    "Follow the requested output format exactly. This is a trusted "
                    "synthetic visual qualification clip."
                ),
                "prompt": (
                    "Begin with YES. Then state the visible all-caps phase labels and "
                    "colored moving squares in chronological order."
                ),
                "alert_category": contract["kafka"]["category"],
                "stream": False,
                "chunk_duration": 0,
                "num_frames_per_second_or_fixed_frames_chunk": 12,
                "use_fps_for_chunking": False,
                "max_tokens": 64,
                "temperature": 0.0,
                "seed": 11,
            }
            caption_status, caption_raw, caption = js(
                "/v1/generate_captions",
                method="POST",
                body=_canonical(payload),
                headers={"Content-Type": "application/json"},
                timeout=120,
            )
            model_requests += 1
            chunks = caption.get("chunk_responses") if isinstance(caption, dict) else None
            if (
                caption_status != 200
                or not isinstance(caption, dict)
                or caption.get("model") != model
                or not isinstance(chunks, list)
                or len(chunks) != 1
                or not isinstance(chunks[0].get("content"), str)
            ):
                raise QualificationError("incident caption response invalid")
            semantic = chunks[0]["content"]
            lowered = semantic.casefold()
            marker_flags = [marker in lowered for marker in contract["fixture"]["primary_markers"]]
            if (
                re.search(r"\b(?:yes|true)\b", semantic, re.IGNORECASE) is None
                or marker_flags != [True, True, True]
            ):
                diagnostics = {
                    "characters": len(semantic),
                    "no": re.search(r"\bno\b", lowered) is not None,
                    "false": re.search(r"\bfalse\b", lowered) is not None,
                    "blue": "blue" in lowered,
                    "green": "green" in lowered,
                    "red": "red" in lowered,
                }
                raise QualificationError(
                    "model did not emit a visual positive incident verdict: "
                    + json.dumps(diagnostics, sort_keys=True)
                )
            semantic_hash = _sha(semantic)
            kafka_result = _finish_consumer(observer)
            observer = None
            observer_child_pid = None
            if kafka_result["partition_count"] != partition_count:
                raise QualificationError("Kafka partition inventory changed")

            delete_status, delete_raw, delete_value = js(
                f"/v1/files/{resource_id}", method="DELETE", timeout=30
            )
            if (
                delete_status != 200
                or not isinstance(delete_value, dict)
                or delete_value.get("deleted") is not True
            ):
                raise QualificationError("owned incident fixture deletion failed")
            deleted = True
        finally:
            if observer is not None and observer.poll() is None:
                if observer_child_pid is not None:
                    try:
                        _docker(
                            [
                                "exec",
                                contract["execution"]["rt_vlm_container"],
                                "kill",
                                "-TERM",
                                str(observer_child_pid),
                            ],
                            docker_commands,
                        )
                    except QualificationError:
                        pass
                try:
                    observer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    observer.terminate()
                    try:
                        observer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        observer.kill()
                        observer.wait(timeout=5)
            if resource_id and not deleted:
                try:
                    dense._http_json(
                        endpoint,
                        f"/v1/files/{resource_id}",
                        method="DELETE",
                        timeout=30,
                    )
                except dense.QualificationError:
                    pass

    final_files_status, _, final_files = js("/v1/files?purpose=vision", timeout=15)
    final_stats_status, _, final_stats = js("/v1/assets/stats", timeout=15)
    final_models_status, _, final_models = js("/v1/models", timeout=15)
    final_health_status, _, final_health = js("/v1/health/ready", timeout=15)
    if final_files_status != 200 or dense._catalog(final_files) != files_before:
        raise QualificationError("file catalog was not restored")
    if final_stats_status != 200 or _sha(_canonical(final_stats)) != stats_before:
        raise QualificationError("asset statistics were not restored")
    if final_models_status != 200 or dense._model(final_models, model)[1] != models_before:
        raise QualificationError("model inventory was not restored")
    if final_health_status != 200 or _sha(_canonical(final_health)) != health_before:
        raise QualificationError("health contract was not restored")
    if temp_path is None or temp_path.exists():
        raise QualificationError("temporary fixture root remains")
    if request_count != contract["execution"]["max_http_requests"]:
        raise QualificationError("exact HTTP request budget drifted")
    if model_requests != contract["execution"]["max_model_requests"]:
        raise QualificationError("exact model request budget drifted")
    if docker_commands[0] > contract["execution"]["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
    duration = time.monotonic() - started
    if duration > contract["execution"]["max_duration_seconds"]:
        raise QualificationError("runtime duration bound exceeded")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(duration, 6),
        "budget": {
            "http_requests": request_count,
            "max_http_requests": contract["execution"]["max_http_requests"],
            "model_requests": model_requests,
            "max_model_requests": contract["execution"]["max_model_requests"],
            "docker_commands": docker_commands[0],
            "max_docker_commands": contract["execution"]["max_docker_commands"],
            "support_processes_peak": 1,
            "max_support_processes": 1,
        },
        "runtime_identity": runtime,
        "fixture": {
            "byte_count": len(fixture_bytes),
            "content_sha256": _sha(fixture_bytes),
            "duration_seconds": contract["fixture"]["duration_seconds"],
            "primary_markers": contract["fixture"]["primary_markers"],
        },
        "caption": {
            "http_status": 200,
            "model_exact": True,
            "single_chunk": True,
            "positive_verdict_present": True,
            "primary_markers_present": [True, True, True],
            "request_sha256": _sha(_canonical(payload)),
            "response_sha256": _sha(caption_raw),
            "semantic_output_sha256": semantic_hash,
        },
        "kafka_incident": {
            **kafka_result,
            "topic_exact": True,
            "owned_matching_records": 1,
            "append_only_record_retained": True,
            "individual_record_deletion_supported": False,
            "category_sha256": _sha(contract["kafka"]["category"]),
        },
        "cleanup": {
            "owned_file_deleted": True,
            "file_catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "model_inventory_restored_exactly": True,
            "health_contract_restored_exactly": True,
            "observer_stopped": True,
            "temporary_fixture_root_absent": True,
            "append_only_kafka_record_count": 1,
        },
        "policy": {
            "agent_generate_calls": 0,
            "stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False,
            "raw_incident_payload_retained": False,
            "credentials_retained": False,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_json(RECEIPT_SCHEMA_PATH)
    Draft202012Validator(schema).validate(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"), nargs="?", default="plan")
    parser.add_argument("--ack")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        if args.mode == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract, args.endpoint)
    except (QualificationError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
