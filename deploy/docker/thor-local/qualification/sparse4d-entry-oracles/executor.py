#!/usr/bin/env python3
"""Inert Sparse4D advertised-entry planner and candidate-evidence validator."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
EXPECTED_PACKAGE_HASHES = {
    "contract.json": "1a0a1f9749bd5572a35255ce7b38f6f5229b38e8b71980fa743267a4a09110f6",
    "contract.schema.json": "74b1690194c9409734f3775815f33432aad975a9e79314e83f705550faeba6fd",
    "evidence.schema.json": "e58bfc336686edda71e6f4eccf1dcd39202a928858a172f8b7d0420b23199cad",
    "plan.schema.json": "bd2fdcab22d8fa9cf13009f702fc7f79709bbde2a50c770cbbdfc8284dc1255d",
}
CAMERAS = ["Camera", "Camera_01", "Camera_02", "Camera_03"]
SAMPLE_DATASET = "warehouse-4cams-20mx20m-synthetic"
RTDETR_MODEL = "rtdetr_warehouse_v1.0.2.fp16.onnx"
SPARSE4D_MODEL = "sparse4d_warehouse_v2.2.onnx"
THROUGHPUT_REL_TOLERANCE = 0.05
MAX_JSON_BYTES = 2_000_000
EXPECTED_SOURCE_PATHS = {
    "deploy/docker/thor-local/validate-warehouse-sparse4d-input.py",
    "deploy/docker/scripts/thor-warehouse-sparse4d.sh",
    "deploy/docker/thor-local/render-warehouse-sparse4d-env.py",
    "deploy/docker/thor-local/patch-warehouse-sparse4d-offline.py",
    "deploy/docker/thor-local/warehouse-sparse4d.compose.yml",
    "deploy/docker/thor-local/warehouse-sparse4d-prometheus.yml",
    "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.json",
    "deploy/docker/thor-local/parity/manifest.json",
}
EXPECTED_ORACLES = {
    "manifest-gap.rt-cv-3d-sparse4d.00-sparse4d-multi-camera-3d-detection-and-tracking": (
        "Sparse4D multi-camera 3D detection and tracking",
        "oracle.manifest-entry.rt-cv-3d-sparse4d.00",
        "d4ed2d5abc7ecea15a101d2ed0fed97cf093dde973c348c8a2d0e12cc56dee74",
    ),
    "manifest-gap.rt-cv-3d-sparse4d.01-shared-rt-cv-lifecycle-health-metrics": (
        "shared RT-CV lifecycle/health/metrics",
        "oracle.manifest-entry.rt-cv-3d-sparse4d.01",
        "6f3f8d07014bf042dba7c52ae3a858b462fa92af01a48fcfdb17cac54a35d9b2",
    ),
}
EXPECTED_BLOCKERS = [
    "Sparse4D v2.2 ONNX is not staged locally",
    "Sparse4D (900,11) kmeans anchor is not staged locally",
    "matching operator-owned four-camera media and calibration are not admitted",
    "the existing Sparse4D validator does not independently admit the requested RT-DETR asset identity",
    "memory, disk, local ARM64 images, ports, and GPU-idle preflight have not passed for a prepared lane",
    "no authorized runtime model-use, semantic output, metrics, latency, or cleanup receipt exists",
]
REQUIRED_SERVICES = {
    "redis",
    "vss-configurator",
    "vss-vios-nvstreamer",
    "vss-vios-sensor",
    "vss-vios-streamprocessing",
    "vss-rtvi-cv",
    "vss-behavior-analytics",
}


class QualificationError(RuntimeError):
    """A static lock, admission binding, schema, or semantic check failed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _strict_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise QualificationError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {label}")
    return value


def _strict_json_path(path: Path, *, external: bool = False) -> dict[str, Any]:
    if not path.is_absolute():
        raise QualificationError("evidence receipt path must be absolute")
    if external:
        try:
            path.resolve(strict=True).relative_to(REPO_ROOT)
        except ValueError:
            pass
        else:
            raise QualificationError(
                "candidate runtime evidence must remain outside repository"
            )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if path.is_symlink():
            raise QualificationError(
                f"JSON must be a regular non-symlink file: {path}"
            ) from exc
        raise QualificationError(f"cannot read JSON: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise QualificationError(f"JSON must be a regular non-symlink file: {path}")
        if metadata.st_size > MAX_JSON_BYTES:
            raise QualificationError(f"JSON exceeds bounded size: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            data = stream.read(MAX_JSON_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _strict_json_bytes(data, str(path))


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError(f"symlinked repository path: {relative}")
    try:
        resolved = (REPO_ROOT / path).resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise QualificationError(
            f"repository path escaped or is absent: {relative}"
        ) from exc
    if not resolved.is_file():
        raise QualificationError(f"repository path is not a file: {relative}")
    return resolved


def _validate(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), str(schema_path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            instance
        ),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.absolute_path)
        raise QualificationError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _load_contract() -> dict[str, Any]:
    for name, expected in EXPECTED_PACKAGE_HASHES.items():
        actual = _sha256_bytes((HERE / name).read_bytes())
        if actual != expected:
            raise QualificationError(f"package identity drift: {name}")
    contract = _strict_json_bytes(CONTRACT_PATH.read_bytes(), str(CONTRACT_PATH))
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    locks = contract["source_locks"]
    if len({item["path"] for item in locks}) != len(locks):
        raise QualificationError("duplicate source lock path")
    if {item["path"] for item in locks} != EXPECTED_SOURCE_PATHS:
        raise QualificationError("exact source lock set drifted")
    oracles = contract["advertised_oracles"]
    if len({item["entry_id"] for item in oracles}) != 2:
        raise QualificationError("exact two unique advertised entries required")
    observed = {
        item["entry_id"]: (
            item["advertised"],
            item["oracle_id"],
            item["required_oracle_canonical_sha256"],
        )
        for item in oracles
    }
    if observed != EXPECTED_ORACLES:
        raise QualificationError("advertised oracle binding drift")
    if contract["current_blockers"] != EXPECTED_BLOCKERS:
        raise QualificationError("current blocker inventory drift")
    return contract


def _check_source_locks(contract: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for lock in contract["source_locks"]:
        actual = _sha256_bytes(_repo_file(lock["path"]).read_bytes())
        checks.append({"path": lock["path"], "sha256_match": actual == lock["sha256"]})
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise QualificationError(f"source lock mismatch: {failed}")
    return checks


def _verify_live_oracle_bindings(contract: dict[str, Any]) -> None:
    plan_lock = next(
        item
        for item in contract["source_locks"]
        if item["path"].endswith("advertised-entry-gaps/plan.json")
    )
    plan = _strict_json_bytes(
        _repo_file(plan_lock["path"]).read_bytes(), plan_lock["path"]
    )
    entries = {item["entry_id"]: item for item in plan["entries"]}
    for entry_id, (advertised, oracle_id, digest) in EXPECTED_ORACLES.items():
        entry = entries.get(entry_id)
        if entry is None or entry["advertised"] != advertised:
            raise QualificationError(f"live advertised entry drift: {entry_id}")
        oracle = entry["required_oracle"]
        if oracle["id"] != oracle_id or _canonical_sha256(oracle) != digest:
            raise QualificationError(f"live required oracle drift: {entry_id}")
        if (
            oracle["status"] != "open_unexecuted"
            or oracle["runtime_evidence"] != []
            or entry["runtime_evidence"] != []
            or entry["warehouse_scope"]["sample_bundle_required"] is not False
        ):
            raise QualificationError(
                f"live oracle is no longer open and sample-free: {entry_id}"
            )


def build_plan() -> dict[str, Any]:
    contract = _load_contract()
    source_checks = _check_source_locks(contract)
    _verify_live_oracle_bindings(contract)
    admission = contract["admission"]
    result = {
        "schema_version": 1,
        "mode": "inert_read_only_admission_plan",
        "writes": False,
        "subprocesses": False,
        "docker": False,
        "network": False,
        "lifecycle": False,
        "model_load": False,
        "downloads": False,
        "warehouse_sample_bundle": "excluded",
        "contract_sha256": _sha256_bytes(CONTRACT_PATH.read_bytes()),
        "source_checks": source_checks,
        "admission": {
            key: admission[key]
            for key in (
                "camera_count",
                "camera_ids",
                "dataset",
                "validator",
                "lane",
                "lane_stages",
                "sparse4d_model",
                "anchor",
                "anchor_shape",
                "rtdetr_model",
                "memory_floor_kib",
                "disk_floor_kib",
                "gpu_conflicts_allowed",
            )
        },
        "oracle_plans": [
            {
                "entry_id": item["entry_id"],
                "oracle_id": item["oracle_id"],
                "status": "open_unexecuted",
                "semantic_plan": item["semantic_plan"],
                "runtime_evidence": [],
            }
            for item in contract["advertised_oracles"]
        ],
        "current_blockers": contract["current_blockers"],
        "evidence_boundary": "schema_and_semantic_validator_only_no_runtime_receipt",
        "next_action": admission["next_action"],
    }
    _validate(result, PLAN_SCHEMA_PATH, "plan")
    return result


def _all_artifacts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if set(value) == {"artifact_id", "sha256", "captured_at", "source_service"}:
            found.append(value)
        for item in value.values():
            found.extend(_all_artifacts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_all_artifacts(item))
    return found


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise QualificationError(f"non-finite evidence number at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{path}/{index}")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _outside_repo(path_text: str, label: str) -> Path:
    path = Path(path_text).resolve(strict=False)
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return path
    raise QualificationError(f"{label} must remain outside repository")


def _validate_model_pair(
    pair: dict[str, Any], admitted: dict[str, Any], expected_filename: str
) -> None:
    if pair["model_filename"] != expected_filename:
        raise QualificationError(f"wrong model identity: {expected_filename}")
    if pair["model_sha256"] != admitted["sha256"]:
        raise QualificationError(
            f"model proof hash differs from admission: {expected_filename}"
        )
    for event in (pair["loaded"], pair["used"]):
        if (
            event["model_filename"] != expected_filename
            or event["model_sha256"] != pair["model_sha256"]
            or event["service"] != "vss-rtvi-cv"
            or event["capture"]["source_service"] != "vss-rtvi-cv"
        ):
            raise QualificationError(
                f"model load/use binding drift: {expected_filename}"
            )
    if (
        pair["loaded"]["capture"]["artifact_id"]
        == pair["used"]["capture"]["artifact_id"]
    ):
        raise QualificationError(
            f"loaded and used require distinct captures: {expected_filename}"
        )
    if _parse_time(pair["loaded"]["capture"]["captured_at"]) >= _parse_time(
        pair["used"]["capture"]["captured_at"]
    ):
        raise QualificationError(
            f"model-loaded capture must precede model-used: {expected_filename}"
        )


def _validate_evidence_semantics(receipt: dict[str, Any]) -> dict[str, Any]:
    _assert_finite(receipt)
    admission = receipt["admission"]
    preflight = receipt["preflight"]
    run = receipt["run"]
    input_root = _outside_repo(admission["input_root"], "operator input root")
    private_root = _outside_repo(
        admission["prepare"]["private_runtime_root"], "private runtime root"
    )
    if input_root == private_root:
        raise QualificationError("operator input and private runtime roots must differ")
    if admission["dataset_slug"] == SAMPLE_DATASET:
        raise QualificationError("Warehouse sample dataset is excluded")
    if preflight["profile"] != run["profile"]:
        raise QualificationError("preflight and run profiles must match")
    started_at = _parse_time(run["started_at"])
    ended_at = _parse_time(run["ended_at"])
    if ended_at <= started_at:
        raise QualificationError("run ended_at must be after started_at")

    artifacts = _all_artifacts(receipt)
    artifact_ids = [item["artifact_id"] for item in artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise QualificationError("capture artifact IDs must be globally unique")
    if any(
        not started_at <= _parse_time(item["captured_at"]) <= ended_at
        for item in artifacts
    ):
        raise QualificationError(
            "every capture must fall within the admitted run window"
        )

    proof = receipt["model_proof"]
    _validate_model_pair(proof["rtdetr"], admission["rtdetr"], RTDETR_MODEL)
    _validate_model_pair(proof["sparse4d"], admission["sparse4d"], SPARSE4D_MODEL)
    if proof["anchor_sha256"] != admission["anchor"]["sha256"]:
        raise QualificationError("anchor proof hash differs from admission")

    pipeline, health = receipt["oracle_evidence"]
    cleanup = receipt["cleanup"]
    cleanup_id = cleanup["cleanup_evidence_id"]
    if {item["cleanup_evidence_id"] for item in receipt["oracle_evidence"]} != {
        cleanup_id
    }:
        raise QualificationError("both oracles must bind the same cleanup evidence")

    observations = pipeline["per_camera_detections"]
    if [item["camera_id"] for item in observations] != CAMERAS:
        raise QualificationError(
            "per-camera evidence must use exact ordered camera set"
        )
    raw_tracks = {
        (observation["camera_id"], detection["track_id"])
        for observation in observations
        for detection in observation["detections"]
    }
    if len(raw_tracks) != sum(len(item["detections"]) for item in observations):
        raise QualificationError("per-camera track IDs must be unique within cameras")
    if any(item["capture"]["source_service"] != "vss-rtvi-cv" for item in observations):
        raise QualificationError("mdx-raw captures must originate from vss-rtvi-cv")

    fused_ids: set[str] = set()
    fused_contributors: dict[str, set[str]] = {}
    fused_coverage: set[str] = set()
    for track in pipeline["fused_tracks"]:
        global_id = track["global_track_id"]
        if global_id in fused_ids:
            raise QualificationError("duplicate fused global track ID")
        fused_ids.add(global_id)
        contributors = set(track["contributing_camera_ids"])
        fused_contributors[global_id] = contributors
        source_tracks = {
            (item["camera_id"], item["track_id"]) for item in track["source_tracks"]
        }
        if len(source_tracks) != len(track["source_tracks"]):
            raise QualificationError("duplicate fused source track binding")
        if {item[0] for item in source_tracks} != contributors:
            raise QualificationError(
                "fused contributors differ from source-track cameras"
            )
        if not source_tracks <= raw_tracks:
            raise QualificationError(
                "fused source track is absent from mdx-raw evidence"
            )
        if track["capture"]["source_service"] != "vss-rtvi-cv":
            raise QualificationError("mdx-bev captures must originate from vss-rtvi-cv")
        fused_coverage.update(contributors)
    if fused_coverage != set(CAMERAS):
        raise QualificationError(
            "aggregate fused evidence must cover exact four cameras"
        )

    correlation_coverage: set[str] = set()
    for correlation in pipeline["cross_camera_correlations"]:
        source = correlation["from_camera"]
        target = correlation["to_camera"]
        global_id = correlation["global_track_id"]
        if source == target:
            raise QualificationError(
                "cross-camera correlation cannot remain on one camera"
            )
        if correlation["to_timestamp_ms"] < correlation["from_timestamp_ms"]:
            raise QualificationError("cross-camera correlation timestamps are reversed")
        if global_id not in fused_ids:
            raise QualificationError(
                "correlation global track is absent from fused evidence"
            )
        if {source, target} - fused_contributors[global_id]:
            raise QualificationError(
                "correlation cameras are absent from matching fused track"
            )
        if correlation["capture"]["source_service"] != "vss-rtvi-cv":
            raise QualificationError(
                "correlation captures must originate from vss-rtvi-cv"
            )
        correlation_coverage.update((source, target))
    if correlation_coverage != set(CAMERAS):
        raise QualificationError(
            "cross-camera correlations must cover exact four cameras"
        )

    services = [item["service"] for item in health["services"]]
    if len(services) != len(set(services)):
        raise QualificationError("health service observations must be unique")
    if not REQUIRED_SERVICES <= set(services):
        raise QualificationError("required Sparse4D lane health services are missing")
    health_by_service = {item["service"]: item["health"] for item in health["services"]}
    if any(health_by_service[service] != "healthy" for service in REQUIRED_SERVICES):
        raise QualificationError("every required Sparse4D lane service must be healthy")
    throughput = health["throughput"]
    expected_frames = throughput["fps"] * throughput["sample_seconds"]
    tolerance = max(1.0, expected_frames * THROUGHPUT_REL_TOLERANCE)
    if abs(throughput["frames_processed"] - expected_frames) > tolerance:
        raise QualificationError(
            "throughput frames, sample duration, and fps exceed 5%/one-frame tolerance"
        )
    latency = health["latency"]
    if not latency["p50_ms"] <= latency["p95_ms"] <= latency["p99_ms"]:
        raise QualificationError("latency percentiles must be monotonic")
    stream_growth = health["stream_growth"]
    if stream_growth["mdx_bev_after"] <= stream_growth["mdx_bev_before"]:
        raise QualificationError("mdx-bev stream must grow during the run")

    prefix = cleanup["ownership_prefix"]
    if prefix != run["namespace"] + ":":
        raise QualificationError(
            "cleanup ownership prefix must equal namespace plus colon"
        )
    created = set(cleanup["created_resource_ids"])
    removed = set(cleanup["removed_resource_ids"])
    preexisting = set(cleanup["preexisting_resource_ids"])
    if created != removed:
        raise QualificationError("cleanup must remove exactly all created resources")
    if created & preexisting:
        raise QualificationError("created resources overlap preexisting resources")
    if any(not resource.startswith(prefix) for resource in created):
        raise QualificationError("created resource is outside cleanup ownership prefix")
    if not any(
        resource.startswith(prefix + "stream-") for resource in created
    ) or not any(resource.startswith(prefix + "output-") for resource in created):
        raise QualificationError(
            "cleanup ownership must include stream and output resources"
        )

    return {
        "schema_version": 1,
        "mode": "read_only_candidate_evidence_validation",
        "validated": True,
        "candidate_status": "observed_not_admitted",
        "oracle_ids": [item["oracle_id"] for item in receipt["oracle_evidence"]],
        "camera_ids": list(CAMERAS),
        "artifact_count": len(artifacts),
        "writes": False,
        "subprocesses": False,
        "live_ledger_mutation": False,
        "boundary": "candidate evidence is structurally and semantically valid but not admitted",
    }


def validate_evidence(path: Path) -> dict[str, Any]:
    contract = _load_contract()
    _check_source_locks(contract)
    _verify_live_oracle_bindings(contract)
    receipt = _strict_json_path(path, external=True)
    _validate(receipt, EVIDENCE_SCHEMA_PATH, "evidence")
    return _validate_evidence_semantics(receipt)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan", help="print the inert admission plan (default)")
    validate_parser = subparsers.add_parser(
        "validate-evidence",
        help="read-only validation of an external candidate receipt",
    )
    validate_parser.add_argument("--receipt", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = (
            validate_evidence(args.receipt)
            if args.command == "validate-evidence"
            else build_plan()
        )
    except QualificationError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
