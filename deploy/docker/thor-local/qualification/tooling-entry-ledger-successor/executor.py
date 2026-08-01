#!/usr/bin/env python3
"""Read-only Git-object verifier for the 277/86 to 289/74 ledger transition."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import jsonschema


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[4]
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"
CONTRACT_SCHEMA_PATH = PACKAGE_ROOT / "contract.schema.json"
RESULT_SCHEMA_PATH = PACKAGE_ROOT / "result.schema.json"
CONTRACT_RAW_SHA256 = "530873511b175a3183abab7804a119ab2d68112c60cef70c4b4ac6b888461a77"
PREDECESSOR_COMMIT = "f638eb3421ec5620fe22609590c5e9d5872d33d0"
ALLOWED_GIT_COMMANDS = {"rev-parse", "cat-file", "show"}

PLAN_PATH = "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json"
MANIFEST_PATH = "deploy/docker/thor-local/parity/manifest.json"
CAPABILITIES_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
CORE_PATHS = [PLAN_PATH, MANIFEST_PATH, CAPABILITIES_PATH, ORACLES_PATH]

ENTRY_LITERALS = [
    (29, 0, "calibration and camera grouping", "spatial-ai-utils.00-calibration-and-camera-grouping"),
    (29, 1, "3D/2D geometry", "spatial-ai-utils.01-3d-2d-geometry"),
    (29, 2, "multiview visualization", "spatial-ai-utils.02-multiview-visualization"),
    (29, 3, "detection mAP", "spatial-ai-utils.03-detection-map"),
    (29, 4, "tracking HOTA/CLEAR/identity/count", "spatial-ai-utils.04-tracking-hota-clear-identity-count"),
    (29, 5, "NVSchema conversion", "spatial-ai-utils.05-nvschema-conversion"),
    (29, 6, "video/frame tools", "spatial-ai-utils.06-video-frame-tools"),
    (29, 7, "AWS/GCS validation", "spatial-ai-utils.07-aws-gcs-validation"),
    (30, 0, "semantic label helpers", "synthetic-data-tools.00-semantic-label-helpers"),
    (30, 1, "dataset checks", "synthetic-data-tools.01-dataset-checks"),
    (30, 2, "RGB/depth/video conversion", "synthetic-data-tools.02-rgb-depth-video-conversion"),
    (30, 3, "ground-truth conversion", "synthetic-data-tools.03-ground-truth-conversion"),
]

EXPECTED_FROZEN_IDS = [
    "advertised-entry-executors-wave8",
    "architecture-gap-contracts",
    "audio-entry-oracles",
    "cpu-multimedia-ledger-successor",
    "detection-map-static-executor",
    "external-entry-attestations",
    "fixed-topology-scaling-config",
    "mv3dt-entry-oracles",
    "runtime-execution-bounds-audit",
    "runtime-lanes",
    "search-documents-bboxes-runtime-evidence",
    "search-scale-qualification-plan",
    "service-binding-resolution",
    "sparse4d-entry-oracles",
    "systems-alert-completion-static-executor",
    "systems-behavior-analytics-static-executor",
    "systems-nvschema-json-static-executor",
    "systems-search-lvs-boundary-static-executor",
    "systems-vios-playback-remediation",
    "ui-runtime-contracts",
]


class QualificationError(RuntimeError):
    """Raised when a locked identity or transition invariant fails."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _json_bytes(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_key)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}: {exc}") from exc


def _schema(path: Path) -> dict[str, Any]:
    value = _json_bytes(path.read_bytes(), str(path))
    jsonschema.Draft202012Validator.check_schema(value)
    return value


def _validate(value: Any, schema_path: Path, label: str) -> None:
    errors = sorted(
        jsonschema.Draft202012Validator(_schema(schema_path)).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise QualificationError(f"{label} schema validation failed: {errors[0].message}")


def _safe_repo_path(relative: str) -> Path:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"current core path is not a regular file: {relative}")
    if REPO_ROOT not in path.resolve().parents:
        raise QualificationError(f"repository path escapes root: {relative}")
    return path


def _git(command: str, *args: str) -> bytes:
    if command not in ALLOWED_GIT_COMMANDS:
        raise QualificationError(f"prohibited git command: {command}")
    completed = subprocess.run(
        ["git", command, *args],
        cwd=REPO_ROOT,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise QualificationError(f"git {command} failed: {detail}")
    return completed.stdout


def _git_text(command: str, *args: str) -> str:
    return _git(command, *args).decode("ascii").strip()


def _git_json(commit: str, path: str) -> Any:
    return _json_bytes(_git("show", f"{commit}:{path}"), f"{commit}:{path}")


def _current_core(contract: dict[str, Any]) -> tuple[dict[str, bytes], dict[str, Any]]:
    expected = {row["path"]: row["sha256"] for row in contract["successor"]["current_objects"]}
    if list(expected) != CORE_PATHS:
        raise QualificationError("current core path/order drift")
    raw: dict[str, bytes] = {}
    parsed: dict[str, Any] = {}
    for path in CORE_PATHS:
        payload = _safe_repo_path(path).read_bytes()
        if _sha256(payload) != expected[path]:
            raise QualificationError(f"current core digest mismatch: {path}")
        raw[path] = payload
        parsed[path] = _json_bytes(payload, path)
    return raw, parsed


def _predecessor_core(contract: dict[str, Any]) -> dict[str, Any]:
    pred = contract["predecessor"]
    resolved = _git_text("rev-parse", "--verify", f"{PREDECESSOR_COMMIT}^{{commit}}")
    if resolved != PREDECESSOR_COMMIT or _git_text("cat-file", "-t", resolved) != "commit":
        raise QualificationError("predecessor commit identity mismatch")
    if _git_text("rev-parse", f"{resolved}^") != pred["parent_commit"]:
        raise QualificationError("predecessor parent identity mismatch")
    if _git_text("rev-parse", f"{resolved}^{{tree}}") != pred["root_tree_oid"]:
        raise QualificationError("predecessor root tree mismatch")
    expected = {row["path"]: row["sha256"] for row in pred["core_objects"]}
    if list(expected) != CORE_PATHS:
        raise QualificationError("predecessor core path/order drift")
    parsed: dict[str, Any] = {}
    for path in CORE_PATHS:
        if _git_text("cat-file", "-t", f"{resolved}:{path}") != "blob":
            raise QualificationError(f"predecessor core object is not a blob: {path}")
        raw = _git("show", f"{resolved}:{path}")
        if _sha256(raw) != expected[path]:
            raise QualificationError(f"predecessor core digest mismatch: {path}")
        parsed[path] = _json_bytes(raw, f"{resolved}:{path}")
    return parsed


def _expected_transition_rows() -> list[dict[str, str]]:
    rows = []
    for feature_index, advertised_index, literal, suffix in ENTRY_LITERALS:
        external = suffix == "spatial-ai-utils.07-aws-gcs-validation"
        rows.append(
            {
                "manifest_pointer": f"/features/{feature_index}/advertised/{advertised_index}",
                "advertised": literal,
                "gap_id": f"manifest-gap.{suffix}",
                "capability_id": f"manifest-entry.{suffix}",
                "oracle_id": f"oracle.manifest-entry.{suffix}",
                "kind": "evaluation" if suffix.startswith(("spatial-ai-utils.03-", "spatial-ai-utils.04-")) else "tooling",
                "acceptance_class": "external_optional" if external else "alternate_local_lane",
                "thor_state": "external_optional" if external else "wired",
                "runtime_state": "not_applicable" if external else "not_qualified",
                "oracle_current_state": "external_boundary_unexecuted" if external else "open_unexecuted",
            }
        )
    return rows


def _id_map(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise QualificationError(f"duplicate {label} IDs")
    return result


def _verify_transition(contract: dict[str, Any], old: dict[str, Any], new: dict[str, Any]) -> None:
    expected_rows = _expected_transition_rows()
    if contract["successor"]["transition_entries"] != expected_rows:
        raise QualificationError("transition contract identity/order drift")

    old_plan, new_plan = old[PLAN_PATH], new[PLAN_PATH]
    old_caps, new_caps = old[CAPABILITIES_PATH], new[CAPABILITIES_PATH]
    old_oracles, new_oracles = old[ORACLES_PATH], new[ORACLES_PATH]
    old_manifest, new_manifest = old[MANIFEST_PATH], new[MANIFEST_PATH]

    if (len(old_plan["entries"]), len(old_caps["capabilities"]), len(old_oracles["oracles"])) != (86, 277, 277):
        raise QualificationError("predecessor denominator mismatch")
    if (len(new_plan["entries"]), len(new_caps["capabilities"]), len(new_oracles["oracles"])) != (74, 289, 289):
        raise QualificationError("successor denominator mismatch")
    if old_plan["plan_payload_sha256"] != contract["predecessor"]["plan_payload_sha256"]:
        raise QualificationError("predecessor plan payload mismatch")
    if new_plan["plan_payload_sha256"] != contract["successor"]["plan_payload_sha256"]:
        raise QualificationError("successor plan payload mismatch")
    denominator = contract["successor"]["global_denominator"]
    for key, expected in denominator.items():
        if new_plan["summary"].get(key) != expected:
            raise QualificationError(f"successor global denominator mismatch: {key}")
    if new_plan["summary"].get("open_unverified_entries") != 74:
        raise QualificationError("successor scoped plan denominator mismatch")

    old_cap_map = _id_map(old_caps["capabilities"], "id", "predecessor capability")
    new_cap_map = _id_map(new_caps["capabilities"], "id", "successor capability")
    old_oracle_map = _id_map(old_oracles["oracles"], "oracle_id", "predecessor oracle")
    new_oracle_map = _id_map(new_oracles["oracles"], "oracle_id", "successor oracle")
    old_gap_map = _id_map(old_plan["entries"], "entry_id", "predecessor gap")
    new_gap_map = _id_map(new_plan["entries"], "entry_id", "successor gap")

    new_cap_ids = {row["capability_id"] for row in expected_rows}
    new_oracle_ids = {row["oracle_id"] for row in expected_rows}
    retired_gap_ids = {row["gap_id"] for row in expected_rows}
    if set(new_cap_map) - set(old_cap_map) != new_cap_ids or set(old_cap_map) - set(new_cap_map):
        raise QualificationError("capability set transition is not exactly the twelve tooling entries")
    if set(new_oracle_map) - set(old_oracle_map) != new_oracle_ids or set(old_oracle_map) - set(new_oracle_map):
        raise QualificationError("oracle set transition is not exactly the twelve tooling entries")
    if set(old_gap_map) - set(new_gap_map) != retired_gap_ids or set(new_gap_map) - set(old_gap_map):
        raise QualificationError("gap set transition is not exactly the twelve tooling entries")

    if any(old_cap_map[key] != new_cap_map[key] for key in old_cap_map):
        raise QualificationError("a predecessor capability record changed")
    if any(old_oracle_map[key] != new_oracle_map[key] for key in old_oracle_map):
        raise QualificationError("a predecessor oracle record changed")
    if any(old_gap_map[key] != new_gap_map[key] for key in new_gap_map):
        raise QualificationError("a surviving gap record changed")

    for row in expected_rows:
        cap = new_cap_map[row["capability_id"]]
        oracle = new_oracle_map[row["oracle_id"]]
        for key in ("kind", "acceptance_class", "thor_state", "runtime_state"):
            if cap[key] != row[key]:
                raise QualificationError(f"new capability state mismatch: {row['capability_id']}:{key}")
        if cap.get("evidence", []) != [] or oracle.get("evidence") != []:
            raise QualificationError(f"new entry has evidence: {row['capability_id']}")
        if oracle["capability_id"] != row["capability_id"] or oracle["current_state"] != row["oracle_current_state"]:
            raise QualificationError(f"new oracle binding/state mismatch: {row['oracle_id']}")
        if oracle["ledger_binding"]["runtime_state"] != row["runtime_state"]:
            raise QualificationError(f"new oracle ledger state mismatch: {row['oracle_id']}")
        if cap["contract"].get("warehouse_sample_bundle") != "excluded":
            raise QualificationError(f"Warehouse sample not excluded by capability: {row['capability_id']}")
        if oracle["ledger_binding"]["contract"].get("warehouse_sample_bundle") != "excluded":
            raise QualificationError(f"Warehouse sample not excluded by oracle binding: {row['oracle_id']}")
        if oracle["execution_bounds"].get("warehouse_sample_bundle") != "excluded":
            raise QualificationError(f"Warehouse sample not excluded by oracle bounds: {row['oracle_id']}")

    if new_plan["policy"].get("warehouse_sample_bundle") != "excluded":
        raise QualificationError("Warehouse sample is not excluded by gap-plan policy")
    external = [row for row in expected_rows if row["acceptance_class"] == "external_optional"]
    if [row["capability_id"] for row in external] != ["manifest-entry.spatial-ai-utils.07-aws-gcs-validation"]:
        raise QualificationError("AWS/GCS is not the sole new external boundary")

    for feature_index, feature_id, capability_ids in (
        (29, "spatial-ai-utils", [row["capability_id"] for row in expected_rows[:8]]),
        (30, "synthetic-data-tools", [row["capability_id"] for row in expected_rows[8:]]),
    ):
        old_feature = old_manifest["features"][feature_index]
        new_feature = new_manifest["features"][feature_index]
        if old_feature["id"] != feature_id or new_feature["id"] != feature_id:
            raise QualificationError(f"manifest feature index drift: {feature_id}")
        if new_feature["official_capability_ids"] != capability_ids:
            raise QualificationError(f"manifest capability IDs drift: {feature_id}")
        if new_feature["runtime_state"] != "not_qualified" or old_feature["runtime_state"] != "passed_current":
            raise QualificationError(f"family-level passed state was not conservatively retired: {feature_id}")
        if old_feature.get("evidence") != new_feature.get("evidence"):
            raise QualificationError(f"historical family evidence changed: {feature_id}")
        if new_feature["advertised"] != [
            row["advertised"] for row in expected_rows if row["manifest_pointer"].startswith(f"/features/{feature_index}/")
        ]:
            raise QualificationError(f"manifest advertised literal/order drift: {feature_id}")

    for index, (old_feature, new_feature) in enumerate(zip(old_manifest["features"], new_manifest["features"], strict=True)):
        if index not in {29, 30} and old_feature != new_feature:
            raise QualificationError(f"unrelated manifest feature changed: {index}")


def _verify_frozen_packages(contract: dict[str, Any]) -> list[dict[str, Any]]:
    packages = contract["frozen_direct_dependents"]
    if [item["id"] for item in packages] != EXPECTED_FROZEN_IDS:
        raise QualificationError("frozen direct-dependent package identity/order drift")
    markers = {
        row["sha256"].encode("ascii") for row in contract["predecessor"]["core_objects"]
    }
    markers.add(contract["predecessor"]["plan_payload_sha256"].encode("ascii"))
    checks = []
    for package in packages:
        expected_path = f"deploy/docker/thor-local/qualification/{package['id']}"
        if package["path"] != expected_path:
            raise QualificationError(f"frozen package path drift: {package['id']}")
        tree_oid = _git_text("rev-parse", f"{PREDECESSOR_COMMIT}:{package['path']}")
        if tree_oid != package["tree_oid"] or _git_text("cat-file", "-t", tree_oid) != "tree":
            raise QualificationError(f"frozen package tree mismatch: {package['id']}")
        for artifact in package["direct_core_artifacts"]:
            if not artifact["path"].startswith(package["path"] + "/"):
                raise QualificationError(f"artifact escapes frozen package: {artifact['path']}")
            raw = _git("show", f"{PREDECESSOR_COMMIT}:{artifact['path']}")
            if _sha256(raw) != artifact["sha256"]:
                raise QualificationError(f"frozen artifact digest mismatch: {artifact['path']}")
            if not any(marker in raw for marker in markers):
                raise QualificationError(f"artifact is not directly core-dependent: {artifact['path']}")
        checks.append(
            {
                "id": package["id"],
                "tree_oid": tree_oid,
                "direct_core_artifact_count": len(package["direct_core_artifacts"]),
                "execution_state": "identity_verified_not_reexecuted",
            }
        )
    return checks


def execute(contract_path: Path = CONTRACT_PATH, expected_raw_sha256: str | None = None) -> dict[str, Any]:
    raw_contract = contract_path.read_bytes()
    expected_digest = CONTRACT_RAW_SHA256 if expected_raw_sha256 is None else expected_raw_sha256
    if _sha256(raw_contract) != expected_digest:
        raise QualificationError("contract raw digest mismatch")
    contract = _json_bytes(raw_contract, str(contract_path))
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    if contract["policy"]["allowed_git_commands"] != sorted(ALLOWED_GIT_COMMANDS, key=("rev-parse", "cat-file", "show").index):
        raise QualificationError("allowed Git command policy drift")

    old = _predecessor_core(contract)
    _raw_new, new = _current_core(contract)
    _verify_transition(contract, old, new)
    frozen_checks = _verify_frozen_packages(contract)

    result = {
        "schema_version": 1,
        "mode": contract["mode"],
        "predecessor": {
            "commit": PREDECESSOR_COMMIT,
            "root_tree_oid": contract["predecessor"]["root_tree_oid"],
            "advertised_gap_count": 86,
            "official_capability_count": 277,
            "capability_oracle_count": 277,
        },
        "successor": {
            "advertised_gap_count": 74,
            "official_capability_count": 289,
            "capability_oracle_count": 289,
            "retired_gap_ids": [row["gap_id"] for row in contract["successor"]["transition_entries"]],
            "added_capability_ids": [row["capability_id"] for row in contract["successor"]["transition_entries"]],
            "added_oracle_ids": [row["oracle_id"] for row in contract["successor"]["transition_entries"]],
        },
        "transition": {
            "entry_count": 12,
            "local_open_count": 11,
            "external_boundary_count": 1,
            "common_capability_records_unchanged": 277,
            "common_oracle_records_unchanged": 277,
            "surviving_gap_records_unchanged": 74,
            "family_level_passed_evidence_promoted": False,
            "warehouse_sample_bundle": "excluded",
            "advertised_entries_without_entry_specific_capability_mapping": 487,
            "family_only_entries_outside_this_plan": 413,
        },
        "frozen_direct_dependents": {
            "package_count": len(frozen_checks),
            "direct_core_artifact_count": sum(item["direct_core_artifact_count"] for item in frozen_checks),
            "checks": frozen_checks,
            "execution_state": "identity_verified_not_reexecuted",
        },
        "effects": {
            "can_mark_passed_current": False,
            "runtime_evidence": [],
            "network_used": False,
            "docker_used": False,
            "runtime_used": False,
            "file_writes_used": False,
            "subprocess_used": True,
            "subprocess_scope": "read_only_local_git_objects_only",
            "git_commands": ["rev-parse", "cat-file", "show"],
        },
        "limitations": [
            "historical_packages_identity_verified_not_reexecuted",
            "family_evidence_retained_as_historical_corroboration_not_entry_qualification",
            "source_wiring_does_not_replace_capability_bound_runtime_evidence",
            "aws_gcs_requires_explicit_external_provider_attestation",
        ],
    }
    _validate(result, RESULT_SCHEMA_PATH, "result")
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and emit the deterministic result")
    parser.parse_args()
    try:
        sys.stdout.write(_canonical(execute()))
    except QualificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
