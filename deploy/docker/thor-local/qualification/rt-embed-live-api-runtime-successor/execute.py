#!/usr/bin/env python3
"""Fresh RT-Embed live/API proof using the source-locked comprehensive qualifier."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"


class QualificationError(RuntimeError):
    """A current-successor assertion failed."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(),
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON source: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _verify_file(path: Path, digest: str, byte_count: int | None = None) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"source is not a regular file: {path}")
    raw = path.read_bytes()
    if _sha(raw) != digest or (byte_count is not None and len(raw) != byte_count):
        raise QualificationError(f"source lock drifted: {path}")
    return raw


def _legacy_module(contract: dict[str, Any]) -> Any:
    executor = REPO / contract["reused_qualifier"]["executor_path"]
    spec = importlib.util.spec_from_file_location("rt_embed_comprehensive_executor", executor)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot import comprehensive RT-Embed qualifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _adapt_legacy_contract(
    contract: dict[str, Any], base: dict[str, Any]
) -> tuple[dict[str, Any], bytes]:
    adapted = copy.deepcopy(base)
    adapted["target"]["captured_on"] = contract["captured_on"]
    for overlay in contract["reused_qualifier"]["allowed_overlays"]:
        matches = [
            row for row in adapted["source_anchors"] if row["path"] == overlay["path"]
        ]
        if len(matches) != 1:
            raise QualificationError("legacy source anchor denominator drifted")
        matches[0]["bytes"] = overlay["bytes"]
        matches[0]["sha256"] = overlay["sha256"]
    adapted["service"]["image_id"] = contract["runtime"]["image_id"]
    raw = (json.dumps(adapted, indent=2, sort_keys=True) + "\n").encode()
    return adapted, raw


def _verify_static(contract: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    if contract["official_indices"] != [369, 373, 374]:
        raise QualificationError("official index contract drifted")
    reused = contract["reused_qualifier"]
    base_raw = _verify_file(
        REPO / reused["contract_path"], reused["contract_sha256"]
    )
    _verify_file(REPO / reused["executor_path"], reused["executor_sha256"])
    for overlay in reused["allowed_overlays"]:
        _verify_file(
            REPO / overlay["path"], overlay["sha256"], overlay["bytes"]
        )
    for lock in contract["additional_source_locks"]:
        _verify_file(REPO / lock["path"], lock["sha256"], lock["bytes"])
    ledger_lock = contract["ledger"]
    _verify_file(
        REPO / ledger_lock["path"], ledger_lock["sha256"], ledger_lock["bytes"]
    )
    base = json.loads(base_raw, object_pairs_hook=_reject_duplicates)
    adapted, adapted_raw = _adapt_legacy_contract(contract, base)
    for row in adapted["source_anchors"]:
        _verify_file(REPO / row["path"], row["sha256"], row["bytes"])
    ledger = _load(REPO / ledger_lock["path"])
    expected = (
        (369, "live RTSP"),
        (373, "original and CV-compatible stream APIs"),
        (374, "health/metadata/models/metrics"),
    )
    for index, literal in expected:
        row = ledger["capabilities"][index]
        if (
            row.get("id") not in contract["capability_ids"]
            or row.get("title") != literal
            or row.get("acceptance_class") != "required_local"
            or row.get("contract", {}).get("advertised_literal") != literal
        ):
            raise QualificationError(f"advertised capability row drifted: {index}")
    if adapted["service"]["image_id"] != contract["runtime"]["image_id"]:
        raise QualificationError("adapted RT-Embed image contract drifted")
    if shutil.disk_usage(REPO).free < contract["execution"]["min_free_bytes"]:
        raise QualificationError("free-space safety floor is not met")
    return adapted, adapted_raw


def _observation_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observations = receipt.get("observations")
    if not isinstance(observations, list) or len(observations) != 41:
        raise QualificationError("comprehensive HTTP observation denominator drifted")
    result = {}
    for row in observations:
        if not isinstance(row, dict) or not isinstance(row.get("action_id"), str):
            raise QualificationError("comprehensive HTTP observation drifted")
        if row["action_id"] in result:
            raise QualificationError("comprehensive HTTP action was duplicated")
        result[row["action_id"]] = row
    return result


def _require_actions(
    observations: dict[str, dict[str, Any]], expected: dict[str, tuple[str, str, int]]
) -> None:
    for action, (method, path, status) in expected.items():
        row = observations.get(action, {})
        if (
            row.get("method") != method
            or row.get("operation_path") != path
            or row.get("http_status") != status
        ):
            raise QualificationError(f"required live HTTP action drifted: {action}")


def _validate_legacy(
    contract: dict[str, Any], adapted: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("target") != adapted["target"]
        or receipt.get("source_anchors") != adapted["source_anchors"]
        or receipt.get("http_request_count") != 43
        or receipt.get("retained_observation_count") != 41
        or receipt.get("semantic_action_count") != 4
        or receipt.get("external_network_requests") != 0
        or receipt.get("image_pulls") != 0
        or receipt.get("image_builds") != 0
        or receipt.get("model_staging_actions") != 0
        or receipt.get("service_lifecycle_actions") != 0
        or receipt.get("disposable_helper_container_count") != 3
        or receipt.get("warehouse_sample_bundle") is not False
    ):
        raise QualificationError("comprehensive qualifier envelope failed")
    if not 0 < receipt.get("duration_seconds", 0) <= contract["execution"][
        "max_duration_seconds"
    ]:
        raise QualificationError("comprehensive qualifier duration drifted")
    identity = receipt.get("runtime_identity", {})
    if (
        identity.get("container") != contract["runtime"]["container"]
        or identity.get("image_id") != contract["runtime"]["image_id"]
        or identity.get("status") != "running"
        or identity.get("health") != "healthy"
        or identity.get("restart_count") != 0
        or identity.get("oom_killed") is not False
        or identity.get("loopback_publish_exact") is not True
        or identity.get("credential_values_blank") is not True
    ):
        raise QualificationError("fresh RT-Embed runtime identity failed")
    api = receipt.get("api_surface", {})
    if (
        api.get("path_count") != 22
        or api.get("operation_count") != 24
        or api.get("covered_operation_count") != 24
        or api.get("all_operations_exercised") is not True
        or api.get("swagger_reachable") is not True
    ):
        raise QualificationError("complete RT-Embed API surface failed")
    live = receipt.get("video_embeddings", {}).get("live_rtsp", {})
    if (
        live.get("chunk_count", 0) < 1
        or live.get("dimensions") != [contract["runtime"]["embedding_dimension"]]
        or live.get("model_exact") is not True
        or live.get("vectors_finite") is not True
    ):
        raise QualificationError("live RTSP embedding proof failed")
    helper = receipt.get("rtsp_helper", {})
    publisher = receipt.get("publisher", {})
    if (
        helper.get("bridge_gateway_only") is not True
        or helper.get("tcp_only") is not True
        or helper.get("pull_disabled") is not True
        or publisher.get("bridge_gateway_only") is not True
        or publisher.get("source_codec") != "h264"
        or publisher.get("rtsp_describe_status") != 200
    ):
        raise QualificationError("isolated RTSP helper boundary failed")
    observations = _observation_map(receipt)
    _require_actions(
        observations,
        {
            "read-metrics": ("GET", "/v1/metrics", 200),
            "read-readiness": ("GET", "/v1/ready", 200),
            "read-liveness": ("GET", "/v1/live", 200),
            "read-startup": ("GET", "/v1/startup", 200),
            "read-metadata": ("GET", "/v1/metadata", 200),
            "read-version": ("GET", "/v1/version", 200),
            "read-manifest": ("GET", "/v1/manifest", 200),
            "read-models-pre": ("GET", "/v1/models", 200),
            "add-cv-camera": ("POST", "/v1/stream/add", 200),
            "read-cv-camera-owned": ("GET", "/v1/stream/get-stream-info", 200),
            "remove-cv-camera": ("POST", "/v1/stream/remove", 200),
            "add-single-live-stream": ("POST", "/v1/streams/add", 200),
            "read-single-live-stream": ("GET", "/v1/streams/get-stream-info", 200),
            "generate-live-video-embedding": (
                "POST",
                "/v1/generate_video_embeddings",
                200,
            ),
            "stop-live-video-embedding": (
                "DELETE",
                "/v1/generate_video_embeddings/{stream_id}",
                200,
            ),
            "delete-single-live-stream": (
                "DELETE",
                "/v1/streams/delete/{stream_id}",
                200,
            ),
            "add-batch-live-streams": ("POST", "/v1/streams/add", 200),
            "delete-batch-live-streams": (
                "DELETE",
                "/v1/streams/delete-batch",
                200,
            ),
            "read-readiness-post": ("GET", "/v1/ready", 200),
            "read-models-post": ("GET", "/v1/models", 200),
        },
    )
    cleanup = receipt.get("cleanup", {})
    required_cleanup = (
        "owned_uuid_resources_absent",
        "owned_camera_absent",
        "complete_inventory_exact",
        "asset_statistics_exact",
        "model_identity_exact",
        "container_identity_exact",
        "paused_workloads_exact",
        "rtsp_path_absent",
        "publisher_absent",
        "helper_containers_absent",
    )
    if cleanup.get("failures") != [] or any(
        cleanup.get(key) is not True for key in required_cleanup
    ):
        raise QualificationError("comprehensive exact cleanup failed")
    return {
        "duration_seconds": receipt["duration_seconds"],
        "adapted_contract_sha256": receipt["contract_sha256"],
        "live": live,
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "status": "inert_rt_embed_live_api_plan_valid",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "http_requests": 0,
        "model_requests": 0,
        "helper_lifecycle_actions": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    adapted, adapted_raw = _verify_static(contract)
    legacy = _legacy_module(contract)
    legacy_receipt = legacy.execute(adapted, adapted_raw)
    proof = _validate_legacy(contract, adapted, legacy_receipt)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "adapted_qualifier_contract_sha256": proof["adapted_contract_sha256"],
        "duration_seconds": proof["duration_seconds"],
        "budget": {
            "http_requests": 43,
            "max_http_requests": contract["execution"]["max_http_requests"],
            "model_requests": 4,
            "max_model_requests": contract["execution"]["max_model_requests"],
            "disposable_helper_containers": 3,
            "max_disposable_helper_containers": contract["execution"][
                "max_disposable_helper_containers"
            ],
            "external_network_requests": 0,
            "max_external_network_requests": 0,
        },
        "runtime_identity": {
            "healthy": True,
            "image_exact": True,
            "restart_count": 0,
            "oom_killed": False,
            "loopback_binding_exact": True,
            "credentials_blank": True,
            "operator_paused_workloads_preserved": True,
        },
        "live_rtsp": {
            "registration_passed": True,
            "tcp_source_h264": True,
            "bridge_gateway_only": True,
            "sse_embedding_chunk_count": proof["live"]["chunk_count"],
            "embedding_dimension": contract["runtime"]["embedding_dimension"],
            "embedding_finite": True,
            "model_exact": True,
            "inference_stop_passed": True,
            "stream_delete_passed": True,
        },
        "stream_apis": {
            "original_batch_api_add_list_delete_passed": True,
            "cv_compatible_api_add_list_remove_passed": True,
            "live_inference_control_passed": True,
            "complete_path_count": 22,
            "complete_operation_count": 24,
            "all_operations_exercised": True,
        },
        "health_metadata_models_metrics": {
            "ready_http_200": True,
            "live_http_200": True,
            "startup_http_200": True,
            "metadata_http_200": True,
            "version_http_200": True,
            "manifest_http_200": True,
            "models_http_200": True,
            "metrics_http_200_and_prometheus": True,
            "model_catalog_preserved": True,
            "release_and_model_exact": True,
        },
        "cleanup": {
            "owned_files_and_streams_absent": True,
            "complete_inventories_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "rtsp_path_absent": True,
            "publisher_absent": True,
            "helper_containers_absent": True,
            "runtime_identity_preserved": True,
            "operator_paused_workloads_preserved": True,
        },
        "policy": contract["policy"],
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
