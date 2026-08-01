#!/usr/bin/env python3
"""Inert MV3DT advertised-entry admission plan and read-only evidence validator."""

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
    "contract.json": "0a83b86212d4be4c93824822a4270f602272b37d72760719af6db26dd86d04e6",
    "contract.schema.json": "b41b030f78f3a227312be60625e4ec2c4adce63b0ec2ea54cac4008f195235b3",
    "evidence.schema.json": "8a2d12539ff3c0ecb27cd327b37fddeee7a2426bfb8a06053cba88647fe18784",
    "plan.schema.json": "95193c7c89fb6dc1077ffdeb9053a833c009ef5d25f8c8a5df9e5e90abaef424",
}
CAMERAS = ["Camera", "Camera_01", "Camera_02", "Camera_03"]
SAMPLE_DATASET = "warehouse-4cams-20mx20m-synthetic"
MAX_JSON_BYTES = 2_000_000
EXPECTED_SOURCE_PATHS = {
    "deploy/docker/thor-local/validate-warehouse-mv3dt-input.py",
    "deploy/docker/scripts/thor-warehouse-mv3dt.sh",
    "tools/rtvi-cv-mv3dt-utils/generate_cam_info_configs.py",
    "tools/rtvi-cv-mv3dt-utils/generate_pub_sub_configs.py",
    "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "deploy/docker/thor-local/parity/manifest.json",
    "deploy/docker/thor-local/warehouse-mv3dt.compose.yml",
    "deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/deepstream/configs/ds-mv3dt-tracker-config.yml",
    "deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/deepstream/configs/ds-main-config-mv3dt.txt",
}
EXPECTED_ORACLES = {
    "manifest-gap.rt-cv-3d-mv3dt.00-per-camera-rt-detr": (
        "per-camera RT-DETR",
        "oracle.manifest-entry.rt-cv-3d-mv3dt.00",
        "1798e84b80e393992b1758cd77fbf742400d3c7fff8e55b19df77495e0eb1cc4",
    ),
    "manifest-gap.rt-cv-3d-mv3dt.01-mv3dt-bev-fusion": (
        "MV3DT BEV fusion",
        "oracle.manifest-entry.rt-cv-3d-mv3dt.01",
        "854d88ed7605fa63fedd37d549d042142487c285570e1b5e787a4d8ca181c59e",
    ),
    "manifest-gap.rt-cv-3d-mv3dt.02-bodypose3dnet": (
        "BodyPose3DNet",
        "oracle.manifest-entry.rt-cv-3d-mv3dt.02",
        "9c92f0849f6bdcbb6356d7956801d0431f85fc6ce0f1b2f1f0ee03fcf385813d",
    ),
    "manifest-gap.rt-cv-3d-mv3dt.03-four-camera-calibrated-multiview-tracking": (
        "four-camera calibrated multiview tracking",
        "oracle.manifest-entry.rt-cv-3d-mv3dt.03",
        "e138ec6f480d0d53382caaa443675bc7ff74b53a99c6e285fd67d31640a694ee",
    ),
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
    if len({item["entry_id"] for item in oracles}) != 4:
        raise QualificationError("exact four unique advertised entries required")
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
            "camera_count": admission["camera_count"],
            "camera_ids": admission["camera_ids"],
            "dataset": admission["dataset"],
            "validator": admission["required_existing_validator"],
            "launcher": admission["required_existing_launcher"],
            "cam_info_tool": admission["required_offline_cam_info_tool"],
            "topology_tool": admission["required_offline_topology_tool"],
            "required_topics": admission["required_topics"],
            "cleanup_policy": admission["required_cleanup_policy"],
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


def _validate_evidence_semantics(receipt: dict[str, Any]) -> dict[str, Any]:
    _assert_finite(receipt)
    admission = receipt["admission"]
    run = receipt["run"]
    try:
        input_root = Path(admission["input_root"]).resolve(strict=False)
        input_root.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise QualificationError("operator input root must remain outside repository")
    if admission["dataset_slug"] == SAMPLE_DATASET:
        raise QualificationError("Warehouse sample dataset is excluded")
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

    topology = admission["topology"]
    pairs = [
        (item["from_camera"], item["to_camera"]) for item in topology["neighbor_pairs"]
    ]
    if len(pairs) != topology["neighbor_edges"] or len(pairs) != len(set(pairs)):
        raise QualificationError("topology edge count or uniqueness drift")
    if any(source == target for source, target in pairs):
        raise QualificationError("topology cannot contain self-subscriptions")
    adjacency = {camera: set() for camera in CAMERAS}
    for source, target in pairs:
        adjacency[source].add(target)
        adjacency[target].add(source)
    reached = {CAMERAS[0]}
    pending = [CAMERAS[0]]
    while pending:
        for neighbor in adjacency[pending.pop()]:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    if reached != set(CAMERAS):
        raise QualificationError("four-camera topology must be connected")

    raw, bev, bodypose, continuity = receipt["oracle_evidence"]
    cleanup = receipt["cleanup"]
    cleanup_id = cleanup["cleanup_evidence_id"]
    if {item["cleanup_evidence_id"] for item in receipt["oracle_evidence"]} != {
        cleanup_id
    }:
        raise QualificationError("all four oracles must bind the same cleanup evidence")

    raw_tracks = {
        (observation["camera_id"], detection["track_id"])
        for observation in raw["camera_observations"]
        for detection in observation["detections"]
    }
    if any(
        observation["capture"]["source_service"] != "vss-rtvi-cv-mv3dt"
        for observation in raw["camera_observations"]
    ):
        raise QualificationError(
            "mdx-raw captures must originate from perception service"
        )
    fused_ids: set[str] = set()
    fused_contributors: dict[str, set[str]] = {}
    bev_camera_coverage: set[str] = set()
    for track in bev["fused_tracks"]:
        global_id = track["global_track_id"]
        if global_id in fused_ids:
            raise QualificationError("duplicate BEV global track ID")
        fused_ids.add(global_id)
        contributors = set(track["contributing_camera_ids"])
        fused_contributors[global_id] = contributors
        source_tracks = {
            (item["camera_id"], item["track_id"]) for item in track["source_tracks"]
        }
        if len(source_tracks) != len(track["source_tracks"]):
            raise QualificationError("duplicate BEV source track binding")
        if {item[0] for item in source_tracks} != contributors:
            raise QualificationError(
                "BEV contributors differ from source-track cameras"
            )
        if not source_tracks <= raw_tracks:
            raise QualificationError("BEV source track is absent from mdx-raw evidence")
        bev_camera_coverage.update(contributors)
        if track["capture"]["source_service"] != "vss-rtvi-cv-bev-fusion":
            raise QualificationError(
                "mdx-bev captures must originate from fusion service"
            )
    if bev_camera_coverage != set(CAMERAS):
        raise QualificationError(
            "aggregate mdx-bev evidence must cover exact four cameras"
        )

    if bodypose["model_asset_sha256"] != admission["bodypose_asset_sha256"]:
        raise QualificationError(
            "BodyPose evidence is not bound to admitted model asset"
        )
    if (
        bodypose["loaded"]["capture"]["artifact_id"]
        == bodypose["used"]["capture"]["artifact_id"]
    ):
        raise QualificationError("BodyPose loaded and used require distinct captures")
    if _parse_time(bodypose["loaded"]["capture"]["captured_at"]) >= _parse_time(
        bodypose["used"]["capture"]["captured_at"]
    ):
        raise QualificationError(
            "BodyPose model-loaded capture must precede model-used"
        )
    if {
        bodypose["loaded"]["capture"]["source_service"],
        bodypose["used"]["capture"]["source_service"],
    } != {"vss-rtvi-cv-mv3dt"}:
        raise QualificationError(
            "BodyPose captures must originate from perception service"
        )

    continuity_coverage: set[str] = set()
    for transition in continuity["transitions"]:
        source = transition["from_camera"]
        target = transition["to_camera"]
        if source == target:
            raise QualificationError(
                "cross-camera transition cannot remain on one camera"
            )
        if (source, target) not in set(pairs):
            raise QualificationError(
                "cross-camera transition is absent from admitted topology edges"
            )
        if transition["first_seen_to_ms"] < transition["last_seen_from_ms"]:
            raise QualificationError("cross-camera transition timestamps are reversed")
        if transition["global_track_id"] not in fused_ids:
            raise QualificationError(
                "continuity global track is absent from mdx-bev evidence"
            )
        if {source, target} - fused_contributors[transition["global_track_id"]]:
            raise QualificationError(
                "continuity cameras are absent from the matching fused track"
            )
        if transition["capture"]["source_service"] != "vss-rtvi-cv-bev-fusion":
            raise QualificationError(
                "continuity captures must originate from fusion service"
            )
        continuity_coverage.update((source, target))
    if continuity_coverage != set(CAMERAS):
        raise QualificationError(
            "cross-camera transitions must cover exact four cameras"
        )

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
