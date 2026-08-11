#!/usr/bin/env python3
"""Qualify RT-CV on-demand SigLIP2 image embeddings on Thor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CORE_PATH = HERE.parent / "rt-cv-2d-core-runtime-successor" / "executor.py"

SPEC = importlib.util.spec_from_file_location("rt_cv_2d_core_runtime_executor", CORE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load the RT-CV core qualification helpers")
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


class QualificationError(RuntimeError):
    """A runtime, safety, cleanup, or evidence assertion failed."""


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON token: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _verify_static(contract: dict[str, Any]) -> None:
    if contract.get("package_id") != "rt-cv-image-embedding-runtime-successor":
        raise QualificationError("package identity drifted")
    if contract.get("official_indices") != [379]:
        raise QualificationError("official index binding drifted")
    if contract.get("capability_ids") != [
        "manifest-entry.rt-cv-2d.04-on-demand-image-embedding"
    ]:
        raise QualificationError("capability binding drifted")
    if contract.get("policy", {}).get("warehouse_sample_bundle") != "excluded":
        raise QualificationError("Warehouse sample policy drifted")
    for lock in contract.get("source_locks", []):
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink():
            raise QualificationError(f"locked source is not a regular file: {lock['path']}")
        if _sha_file(path) != lock["sha256"]:
            raise QualificationError(f"locked source drifted: {lock['path']}")
    for asset in contract["assets"].values():
        path = REPO / asset["path"]
        if not path.is_file() or path.is_symlink():
            raise QualificationError(f"model artifact absent: {asset['path']}")
        if path.stat().st_size != asset["bytes"] or _sha_file(path) != asset["sha256"]:
            raise QualificationError(f"model artifact drifted: {asset['path']}")


def _ppm(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(rgb) * (width * height)


def _stage_configs(contract: dict[str, Any], destination: Path) -> None:
    core._stage_configs(contract, destination)
    main = destination / "ds-main-config.txt"
    text = main.read_text(encoding="utf-8")
    text = core._replace_section_key(text, "sink1", "enable", "0")
    main.write_text(text, encoding="utf-8")


def _ini_value(text: str, section: str, key: str) -> str:
    match = re.search(
        rf"^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise QualificationError(f"effective section missing: {section}")
    values = re.findall(rf"^{re.escape(key)}=(.*)$", match.group(1), re.MULTILINE)
    if len(values) != 1:
        raise QualificationError(f"effective key ambiguous: {section}.{key}")
    return values[0].strip()


def _config_oracle(contract: dict[str, Any], docker_commands: list[int]) -> dict[str, Any]:
    name = contract["execution"]["container"]
    app = "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs"
    raw = core._docker(["exec", name, "cat", f"{app}/ds-main-config.txt"], docker_commands).stdout
    text = raw.decode("utf-8")
    expected = contract["execution"]
    result = {
        "text_model_name": _ini_value(text, "text-embedder", "model-name"),
        "text_onnx": _ini_value(text, "text-embedder", "onnx-model-path"),
        "text_tokenizer": _ini_value(text, "text-embedder", "tokenizer-dir"),
        "vision_backend": _ini_value(text, "visionencoder", "backend"),
        "vision_engine": _ini_value(text, "visionencoder", "tensorrt-engine"),
        "vision_onnx": _ini_value(text, "visionencoder", "onnx-model"),
        "http_port": int(_ini_value(text, "source-list", "http-port")),
        "sink_enabled": int(_ini_value(text, "sink1", "enable")),
        "main_config_sha256": _sha_bytes(raw),
    }
    required = {
        "text_model_name": expected["model_name"],
        "text_onnx": "/opt/storage/siglip_v2_v1.1.onnx",
        "text_tokenizer": "/opt/storage/siglip_v2_v1.1_tokenizer/",
        "vision_backend": "tensorrt",
        "vision_engine": "/opt/storage/siglip_v2_v1.1.onnx_batch16.plan",
        "vision_onnx": "/opt/storage/siglip_v2_v1.1.onnx",
        "http_port": expected["port"],
        "sink_enabled": 0,
    }
    if any(result[key] != value for key, value in required.items()):
        raise QualificationError("effective image-embedding configuration drifted")
    result["effective_configuration_exact"] = True
    return result


def _embedding_call(
    contract: dict[str, Any],
    image_path: str,
    http_requests: list[int],
) -> tuple[list[float], dict[str, Any]]:
    execution = contract["execution"]
    body = _canonical({"image_path": image_path, "model": execution["model_name"]})
    status, raw = core._http(
        execution["endpoint"],
        "/api/v1/generate_image_embeddings",
        http_requests,
        method="POST",
        body=body,
        timeout=120,
    )
    value = core._json_response(status, raw, "image embedding")
    if status != 200:
        raise QualificationError(f"image embedding returned HTTP {status}")
    data = value.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise QualificationError("image embedding data envelope drifted")
    embedding = data[0].get("embedding")
    if (
        not isinstance(embedding, list)
        or len(embedding) != execution["embedding_dimension"]
        or not all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            for item in embedding
        )
    ):
        raise QualificationError("image embedding vector is invalid")
    vector = [float(item) for item in embedding]
    if not any(item != 0.0 for item in vector):
        raise QualificationError("image embedding vector is all zero")
    if (
        value.get("model") != execution["model_name"]
        or not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(value.get("created"), int)
        or value["created"] <= 0
        or data[0].get("index") != 0
        or data[0].get("object") != "embedding"
    ):
        raise QualificationError("image embedding response correlation drifted")
    proof = {
        "http_status": status,
        "model_exact": True,
        "request_id_nonempty": True,
        "created_positive": True,
        "object_exact": True,
        "index": 0,
        "dimension": len(vector),
        "finite": True,
        "nonzero": True,
        "l2_norm": math.sqrt(sum(item * item for item in vector)),
        "vector_sha256": _sha_bytes(_canonical(vector)),
        "request_sha256": _sha_bytes(body),
        "response_sha256": _sha_bytes(raw),
    }
    return vector, proof


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(
        sum(item * item for item in left) * sum(item * item for item in right)
    )
    if denominator == 0:
        raise QualificationError("embedding cosine denominator is zero")
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    execution = contract["execution"]
    docker_commands = [0]
    http_requests = [0]
    cleanup_failures: list[str] = []

    if shutil.disk_usage(REPO).free < execution["minimum_free_bytes"]:
        raise QualificationError("free-space safety margin is below 10 GiB")
    driver = core._docker(["info", "--format", "{{.CgroupDriver}}"], docker_commands).stdout.decode().strip()
    if driver != "cgroupfs":
        raise QualificationError("Docker cgroup driver must be cgroupfs on Thor")
    if not core._container_absent(execution["container"], docker_commands):
        raise QualificationError("owned image-embedding qualifier container already exists")

    image = core._image_identity(
        contract["images"]["rt_cv"]["ref"],
        contract["images"]["rt_cv"]["id"],
        docker_commands,
    )
    main_before = core._snapshot_main(contract, docker_commands, http_requests)
    if main_before["stream_count"] != 0:
        raise QualificationError("main RT-CV must have zero streams for independent proof")
    paused_before = core._paused_snapshot(contract, docker_commands)
    red = _ppm(execution["fixture_width"], execution["fixture_height"], (255, 0, 0))
    green = _ppm(execution["fixture_width"], execution["fixture_height"], (0, 255, 0))

    red_first: list[float] = []
    red_repeat: list[float] = []
    green_vector: list[float] = []
    red_first_proof: dict[str, Any] = {}
    red_repeat_proof: dict[str, Any] = {}
    green_proof: dict[str, Any] = {}
    configuration: dict[str, Any] = {}
    isolated_started_at = ""
    isolated_log_sha256 = ""
    stream_count_before = -1
    stream_count_after = -1
    negative_status = -1
    negative_error_exact = False

    with tempfile.TemporaryDirectory(prefix="rt-cv-image-embedding-") as temp_dir:
        temp = Path(temp_dir)
        configs = temp / "configs"
        fixtures = temp / "fixtures"
        fixtures.mkdir()
        (fixtures / "primary.ppm").write_bytes(red)
        (fixtures / "contrast.ppm").write_bytes(green)
        _stage_configs(contract, configs)
        try:
            result = core._docker(
                [
                    "run",
                    "-d",
                    "--name",
                    execution["container"],
                    "--network",
                    "host",
                    "--runtime",
                    "nvidia",
                    "--gpus",
                    "device=0",
                    "--entrypoint",
                    "/bin/bash",
                    "--label",
                    "vss.thor.qualifier=rt-cv-image-embedding",
                    "-e",
                    "DS_MESSAGE_RATE=1",
                    "-e",
                    "DS_SHOW_SENSOR_ID=false",
                    "-e",
                    "VISION_ENCODER_MODEL=siglip_v2",
                    "-e",
                    "VISION_ENCODER_VERSION=v1.1",
                    "-e",
                    "TRANSFORMERS_OFFLINE=1",
                    "-e",
                    "HF_HUB_OFFLINE=1",
                    "-e",
                    "OTEL_SDK_DISABLED=true",
                    "-e",
                    "GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS=1",
                    "-e",
                    "DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION=1",
                    "-e",
                    "HARDWARE_PROFILE=AGX-THOR",
                    "-e",
                    "STREAM_TYPE=kafka",
                    "-e",
                    "DS_TRACKER_REID=true",
                    "-e",
                    "DS_MODEL_FAMILY=rtdetr-warehouse",
                    "-e",
                    "DS_MODE_FLAG=1",
                    "-e",
                    "GST_PLUGIN_PATH=/opt/nvidia/deepstream/deepstream/sources/gst-plugins/gst-nvdstextembedder",
                    "-v",
                    f"{REPO / execution['search_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh:ro",
                    "-v",
                    f"{REPO / execution['shared_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh:ro",
                    "-v",
                    f"{REPO / execution['models_dir']}:/opt/storage:ro",
                    "-v",
                    f"{fixtures}:/opt/fixtures:ro",
                    "-v",
                    f"{configs}:/opt/ds-configs-ro:ro",
                    contract["images"]["rt_cv"]["ref"],
                    "-c",
                    "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh",
                ],
                docker_commands,
                timeout=40,
            )
            if len(result.stdout.decode().strip()) != 64:
                raise QualificationError("isolated RT-CV container identity invalid")
            core._wait_http(execution["endpoint"], "/api/v1/ready", http_requests, time.monotonic() + 180)
            row = core._inspect_container(execution["container"], docker_commands)
            state = row.get("State", {})
            if (
                row.get("Image") != contract["images"]["rt_cv"]["id"]
                or state.get("Running") is not True
                or state.get("OOMKilled") is not False
                or row.get("RestartCount") != 0
            ):
                raise QualificationError("isolated image-embedding runtime identity drifted")
            isolated_started_at = str(state.get("StartedAt"))
            configuration = _config_oracle(contract, docker_commands)
            stream_count_before = core._metric_snapshot(execution["endpoint"], http_requests).get("stream-count")
            if stream_count_before != 0:
                raise QualificationError("isolated image-embedding service unexpectedly has streams")

            red_first, red_first_proof = _embedding_call(
                contract, "/opt/fixtures/primary.ppm", http_requests
            )
            red_repeat, red_repeat_proof = _embedding_call(
                contract, "/opt/fixtures/primary.ppm", http_requests
            )
            green_vector, green_proof = _embedding_call(
                contract, "/opt/fixtures/contrast.ppm", http_requests
            )
            if red_first != red_repeat:
                raise QualificationError("same-image embedding is not repeatable")
            if red_first == green_vector:
                raise QualificationError("different images returned an identical embedding")
            different_cosine = _cosine(red_first, green_vector)
            if not math.isfinite(different_cosine) or different_cosine >= execution["different_image_max_cosine"]:
                raise QualificationError("different-image embedding discrimination failed")

            missing_body = _canonical(
                {"image_path": "/opt/fixtures/absent.ppm", "model": execution["model_name"]}
            )
            negative_status, negative_raw = core._http(
                execution["endpoint"],
                "/api/v1/generate_image_embeddings",
                http_requests,
                method="POST",
                body=missing_body,
                timeout=120,
            )
            negative = core._json_response(negative_status, negative_raw, "missing image")
            negative_error_exact = (
                negative_status == 500
                and negative.get("code") == "ErrorCode"
                and negative.get("message") == "Image embedding query not handled by downstream elements"
            )
            if not negative_error_exact:
                raise QualificationError("missing-image request did not fail closed")
            stream_count_after = core._metric_snapshot(execution["endpoint"], http_requests).get("stream-count")
            if stream_count_after != 0:
                raise QualificationError("on-demand inference created a stream")
            logs = core._docker(
                ["logs", "--since", isolated_started_at, execution["container"]],
                docker_commands,
            ).stdout
            if b"VPI_ERROR" in logs:
                raise QualificationError("isolated image-embedding runtime emitted VPI_ERROR")
            isolated_log_sha256 = _sha_bytes(logs)
        finally:
            core._remove_owned_container(execution["container"], docker_commands, cleanup_failures)

    time.sleep(1)
    main_after = core._snapshot_main(contract, docker_commands, http_requests)
    paused_after = core._paused_snapshot(contract, docker_commands)
    owned_absent = core._container_absent(execution["container"], docker_commands)
    if cleanup_failures or not owned_absent:
        raise QualificationError(f"exact cleanup failed: {cleanup_failures}")
    if main_after != main_before:
        raise QualificationError("main RT-CV snapshot changed during isolated proof")
    if paused_after != paused_before:
        raise QualificationError("paused workload state changed during isolated proof")
    if docker_commands[0] > execution["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
    if http_requests[0] > execution["max_http_requests"]:
        raise QualificationError("HTTP request budget exceeded")
    duration = time.monotonic() - started
    if duration > execution["max_duration_seconds"]:
        raise QualificationError("runtime duration budget exceeded")

    different_cosine = _cosine(red_first, green_vector)
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha_file(CONTRACT_PATH),
        "runtime": {
            "duration_seconds": duration,
            "docker_cgroup_driver": driver,
            "docker_commands": docker_commands[0],
            "http_requests": http_requests[0],
            "free_bytes_after": shutil.disk_usage(REPO).free,
        },
        "image": image,
        "model": {
            "name": execution["model_name"],
            "embedding_dimension": execution["embedding_dimension"],
            "onnx_sha256": contract["assets"]["siglip_onnx"]["sha256"],
            "engine_sha256": contract["assets"]["siglip_engine"]["sha256"],
            "configuration": configuration,
        },
        "fixtures": {
            "format": "P6_PPM",
            "width": execution["fixture_width"],
            "height": execution["fixture_height"],
            "primary_sha256": _sha_bytes(red),
            "contrast_sha256": _sha_bytes(green),
            "different_content": red != green,
        },
        "on_demand_image_embedding": {
            "endpoint_http_status": 200,
            "active_streams_before": stream_count_before,
            "active_streams_after": stream_count_after,
            "independent_of_continuous_streaming": True,
            "primary_first": red_first_proof,
            "primary_repeat": red_repeat_proof,
            "contrast": green_proof,
            "same_image_vector_exact": red_first == red_repeat,
            "same_image_vector_sha_equal": red_first_proof["vector_sha256"]
            == red_repeat_proof["vector_sha256"],
            "different_image_vector_distinct": red_first != green_vector,
            "different_image_vector_sha_distinct": red_first_proof["vector_sha256"]
            != green_proof["vector_sha256"],
            "different_image_cosine": different_cosine,
            "different_image_cosine_below_limit": different_cosine
            < execution["different_image_max_cosine"],
            "raw_vectors_retained": False,
            "raw_request_ids_retained": False,
            "raw_image_paths_retained": False,
        },
        "negative_path_validation": {
            "http_status": negative_status,
            "error_exact": negative_error_exact,
            "no_embedding_returned": True,
        },
        "container": {
            "running_during_proof": True,
            "oom_killed": False,
            "restart_count": 0,
            "isolated_log_sha256": isolated_log_sha256,
        },
        "cleanup": {
            "owned_container_absent": owned_absent,
            "main_rt_cv_preserved_exactly": main_after == main_before,
            "main_rt_cv_stream_count": main_after["stream_count"],
            "paused_workloads_preserved_exactly": paused_after == paused_before,
            "temporary_directory_removed": True,
            "cleanup_failures": cleanup_failures,
        },
        "policy": contract["policy"],
    }
    return receipt


def _validate_receipt(receipt: dict[str, Any]) -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        raise QualificationError(f"receipt schema validation failed: {errors[0].message}")
    raw = json.dumps(receipt, sort_keys=True)
    if re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", raw, re.I):
        raise QualificationError("receipt retained a raw request UUID")
    if "rtsp://" in raw or "file:///" in raw or "nvapi-" in raw:
        raise QualificationError("receipt retained a forbidden URL or credential")


def _write_receipt(receipt: dict[str, Any]) -> None:
    rendered = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=HERE, prefix=".runtime-receipt.", delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, RECEIPT_PATH)


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    execution = contract["execution"]
    free = shutil.disk_usage(REPO).free
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready" if free >= execution["minimum_free_bytes"] else "blocked",
        "blockers": [] if free >= execution["minimum_free_bytes"] else ["free_space_below_10_gib"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "cached_assets_exact": True,
        "owned_container_absent": core._container_absent(execution["container"], [0]),
        "free_bytes": free,
        "minimum_free_bytes": execution["minimum_free_bytes"],
        "writes_or_lifecycle_actions": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--ack", default="")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = _load_json(CONTRACT_PATH)
        if args.mode == "plan":
            print(json.dumps(_plan(contract), indent=2, sort_keys=True))
            return 0
        if args.ack != contract["execution"]["acknowledgement"]:
            raise QualificationError("exact runtime acknowledgement is required")
        receipt = _execute(contract)
        _validate_receipt(receipt)
        if args.write_receipt:
            _write_receipt(receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
