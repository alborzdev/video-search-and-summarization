#!/usr/bin/env python3
"""Read-only successor verifier for the 87-to-86 advertised-gap transition."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[4]
CONTRACT_PATH = PACKAGE_ROOT / "contract.json"
CONTRACT_SCHEMA_PATH = PACKAGE_ROOT / "contract.schema.json"
RESULT_SCHEMA_PATH = PACKAGE_ROOT / "result.schema.json"

PREDECESSOR_COMMIT = "0c9a0a388900e1012b9fba68c6f2b17d6abb3c06"
CPU_GAP_ID = "manifest-gap.vios-codecs-audio.05-cpu-multimedia-support"
CPU_CAPABILITY_ID = "manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"
CPU_ORACLE_ID = "oracle.manifest-entry.vios-codecs-audio.05-cpu-multimedia-support"

PLAN_PATH = "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json"
MANIFEST_PATH = "deploy/docker/thor-local/parity/manifest.json"
CAPABILITIES_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"

WAVE_PATHS = [
    "deploy/docker/thor-local/qualification/advertised-entry-executors",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave5",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave6",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave8",
]
WAVE_CASE_COUNTS = [8, 21, 23, 5, 6, 8, 11, 2]
FROZEN_PACKAGE_PATHS = [
    "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity",
    "deploy/docker/thor-local/parity/candidates/wave3/systems",
    "deploy/docker/thor-local/parity/candidates/wave3/calibration-warehouse",
    "deploy/docker/thor-local/parity/candidates/wave3/bundle",
    "deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration",
    "deploy/docker/thor-local/qualification/calibration-schema-static-integration",
    "deploy/docker/thor-local/qualification/offline-mv3dt-tools",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave5",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave6",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave7",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave8",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave9",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave10",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave11",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave12",
    "deploy/docker/thor-local/parity/source-lock",
    "deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage",
]
FROZEN_PACKAGE_IDS = [
    "wave3-agent-smartcity",
    "wave3-systems",
    "wave3-calibration-warehouse",
    "wave3-bundle",
    "lvs-mcp-static-adapter-integration",
    "calibration-schema-static-integration",
    "offline-mv3dt-tools",
    "planning-requirement-executors-wave5",
    "planning-requirement-executors-wave6",
    "planning-requirement-executors-wave7",
    "planning-requirement-executors-wave8",
    "planning-requirement-executors-wave9",
    "planning-requirement-executors-wave10",
    "planning-requirement-executors-wave11",
    "planning-requirement-executors-wave12",
    "parity-source-lock",
    "wave3-recursive-coverage",
]
FROZEN_CATEGORIES = [
    "wave3_candidate",
    "wave3_candidate",
    "wave3_candidate",
    "wave3_candidate",
    "static_integration",
    "static_integration",
    "offline_tool_observation",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "planning_requirement_wave",
    "parity_source_lock",
    "recursive_coverage",
]
CORE_PATHS = [PLAN_PATH, MANIFEST_PATH, CAPABILITIES_PATH, ORACLES_PATH]
MAX_GIT_OBJECT_BYTES = 16 * 1024 * 1024


class QualificationError(RuntimeError):
    """Raised when the historical/current successor mapping is not exact."""


def _reject_constant(value: str) -> None:
    raise QualificationError(f"non-finite JSON constant is forbidden: {value}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON for {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} must be a JSON object")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _strict_json(schema_path.read_bytes(), schema_path.name)
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as exc:
        raise QualificationError(f"{label} schema violation: {exc.message}") from exc


def _safe_current_file(relative: str) -> Path:
    if not relative or relative.startswith("/"):
        raise QualificationError(f"unsafe repository path: {relative}")
    candidate = REPO_ROOT / relative
    if candidate.is_symlink():
        raise QualificationError(f"current source may not be a symlink: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (FileNotFoundError, ValueError) as exc:
        raise QualificationError(f"current source is outside repository: {relative}") from exc
    if not resolved.is_file():
        raise QualificationError(f"current source is not a regular file: {relative}")
    return resolved


def _git(args: list[str], *, binary: bool = True) -> bytes | str:
    allowed = {"cat-file", "rev-parse", "show"}
    if not args or args[0] not in allowed:
        raise QualificationError("only read-only local Git object commands are allowed")
    completed = subprocess.run(  # noqa: S603 - exact argv and read-only local git
        ["git", "-C", str(REPO_ROOT), *args],
        check=False,
        capture_output=True,
        shell=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise QualificationError(f"local Git object read failed: {args[0]}: {stderr}")
    if len(completed.stdout) > MAX_GIT_OBJECT_BYTES:
        raise QualificationError("local Git object exceeds bounded read size")
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8").strip()


def _git_blob(commit: str, relative: str) -> bytes:
    if commit != PREDECESSOR_COMMIT or relative.startswith("/") or ".." in Path(relative).parts:
        raise QualificationError("Git blob request is outside the exact predecessor boundary")
    return _git(["show", f"{commit}:{relative}"])  # type: ignore[return-value]


def _git_oid(commit: str, relative: str) -> str:
    if commit != PREDECESSOR_COMMIT or relative not in (
        WAVE_PATHS + FROZEN_PACKAGE_PATHS
    ):
        raise QualificationError("Git tree request is outside the exact package boundary")
    return _git(["rev-parse", f"{commit}:{relative}"], binary=False)  # type: ignore[return-value]


def _verify_commit(commit: str) -> None:
    if commit != PREDECESSOR_COMMIT:
        raise QualificationError("predecessor commit is not exact")
    resolved = _git(["rev-parse", f"{commit}^{{commit}}"], binary=False)
    if resolved != commit:
        raise QualificationError("predecessor commit object identity mismatch")
    object_type = _git(["cat-file", "-t", commit], binary=False)
    if object_type != "commit":
        raise QualificationError("predecessor object is not a commit")


def _lock_map(items: list[dict[str, Any]], expected_paths: list[str]) -> dict[str, str]:
    if [item.get("path") for item in items] != expected_paths:
        raise QualificationError("core source-lock path order drifted")
    return {item["path"]: item["sha256"] for item in items}


def _current_objects(contract: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    locks = _lock_map(contract["successor"]["current_objects"], CORE_PATHS)
    objects: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    for relative in CORE_PATHS:
        raw = _safe_current_file(relative).read_bytes()
        actual = _sha256(raw)
        if actual != locks[relative]:
            raise QualificationError(
                f"current source lock mismatch for {relative}: {actual}"
            )
        objects[relative] = _strict_json(raw, relative)
        digests[relative] = actual
    return objects, digests


def _predecessor_objects(
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    predecessor = contract["predecessor"]
    commit = predecessor["commit"]
    locks = _lock_map(predecessor["core_objects"], CORE_PATHS)
    objects: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    for relative in CORE_PATHS:
        raw = _git_blob(commit, relative)
        actual = _sha256(raw)
        if actual != locks[relative]:
            raise QualificationError(
                f"predecessor source lock mismatch for {relative}: {actual}"
            )
        objects[relative] = _strict_json(raw, f"{commit}:{relative}")
        digests[relative] = actual
    return objects, digests


def _walk_locks(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        path = value.get("path")
        digest = value.get("raw_sha256", value.get("sha256"))
        if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
            found.append((path, digest))
        for item in value.values():
            found.extend(_walk_locks(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_locks(item))
    return found


def _verify_inventory_source_locks(commit: str, inventories: list[dict[str, Any]]) -> int:
    unique: dict[str, str] = {}
    for inventory in inventories:
        for path, digest in _walk_locks(inventory):
            previous = unique.setdefault(path, digest)
            if previous != digest:
                raise QualificationError(f"historical lock conflict for {path}")
    for path, expected in sorted(unique.items()):
        actual = _sha256(_git_blob(commit, path))
        if actual != expected:
            raise QualificationError(f"historical inventory source mismatch for {path}")
    return len(unique)


def _verify_frozen_packages(contract: dict[str, Any]) -> dict[str, Any]:
    commit = contract["predecessor"]["commit"]
    packages = contract["frozen_packages"]
    if [item["id"] for item in packages] != FROZEN_PACKAGE_IDS:
        raise QualificationError("frozen package IDs or order drifted")
    if [item["path"] for item in packages] != FROZEN_PACKAGE_PATHS:
        raise QualificationError("frozen package paths or order drifted")
    if [item["category"] for item in packages] != FROZEN_CATEGORIES:
        raise QualificationError("frozen package categories or order drifted")

    checks: list[dict[str, Any]] = []
    total_embedded_locks = 0
    category_counts = {
        "wave3_candidate": 0,
        "static_integration": 0,
        "offline_tool_observation": 0,
        "planning_requirement_wave": 0,
        "parity_source_lock": 0,
        "recursive_coverage": 0,
    }
    for package in packages:
        tree_oid = _git_oid(commit, package["path"])
        if tree_oid != package["tree_oid"]:
            raise QualificationError(
                f"frozen package tree identity drifted: {package['id']}"
            )
        embedded: dict[str, str] = {}
        artifact_hashes: dict[str, str] = {}
        for artifact in package["key_artifacts"]:
            path = artifact["path"]
            if not path.startswith(f"{package['path']}/"):
                raise QualificationError(
                    f"frozen key artifact is outside package: {package['id']}"
                )
            raw = _git_blob(commit, path)
            actual = _sha256(raw)
            if actual != artifact["sha256"]:
                raise QualificationError(
                    f"frozen key artifact identity drifted: {path}"
                )
            artifact_hashes[path] = actual
            document = _strict_json(raw, f"{commit}:{path}")
            for source_path, digest in _walk_locks(document):
                if (
                    not source_path
                    or source_path.startswith("/")
                    or ".." in Path(source_path).parts
                ):
                    raise QualificationError(
                        f"unsafe embedded source lock in {package['id']}"
                    )
                prior = embedded.setdefault(source_path, digest)
                if prior != digest:
                    raise QualificationError(
                        f"conflicting embedded source lock in {package['id']}: "
                        f"{source_path}"
                    )
        if len(embedded) != package["embedded_source_lock_count"]:
            raise QualificationError(
                f"embedded source-lock denominator drifted: {package['id']}"
            )
        for source_path in sorted(embedded):
            _git_blob(commit, source_path)
        total_embedded_locks += len(embedded)
        category_counts[package["category"]] += 1
        checks.append(
            {
                "id": package["id"],
                "category": package["category"],
                "path": package["path"],
                "tree_oid": tree_oid,
                "key_artifact_sha256": artifact_hashes,
                "embedded_source_lock_count": len(embedded),
                "execution_state": "identity_verified_not_reexecuted",
            }
        )
    if category_counts != {
        "wave3_candidate": 4,
        "static_integration": 2,
        "offline_tool_observation": 1,
        "planning_requirement_wave": 8,
        "parity_source_lock": 1,
        "recursive_coverage": 1,
    }:
        raise QualificationError("frozen package category denominator drifted")
    if total_embedded_locks != 245:
        raise QualificationError("frozen embedded source-lock total drifted")
    return {
        "package_count": len(checks),
        "category_counts": category_counts,
        "embedded_source_lock_count": total_embedded_locks,
        "checks": checks,
        "execution_state": "identity_verified_not_reexecuted",
    }


def _verify_wave_chain(
    contract: dict[str, Any], predecessor: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    commit = contract["predecessor"]["commit"]
    waves = contract["predecessor"]["wave_packages"]
    if [item["wave"] for item in waves] != list(range(1, 9)):
        raise QualificationError("wave numbering is not exact 1 through 8")
    if [item["path"] for item in waves] != WAVE_PATHS:
        raise QualificationError("wave package paths are not exact")

    inventories: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    inventory_paths = [f"{path}/inventory.json" for path in WAVE_PATHS]
    inventory_digests = [item["inventory_sha256"] for item in waves]
    for index, item in enumerate(waves):
        tree_oid = _git_oid(commit, item["path"])
        if tree_oid != item["tree_oid"]:
            raise QualificationError(f"historical Wave {index + 1} tree identity drifted")
        raw = _git_blob(commit, inventory_paths[index])
        digest = _sha256(raw)
        if digest != item["inventory_sha256"]:
            raise QualificationError(f"historical Wave {index + 1} inventory drifted")
        inventory = _strict_json(raw, inventory_paths[index])
        if len(inventory.get("cases", [])) != WAVE_CASE_COUNTS[index]:
            raise QualificationError(f"historical Wave {index + 1} case count drifted")
        plan_lock = inventory.get("source_plan", {})
        manifest_lock = inventory.get("source_manifest", {})
        if (
            plan_lock.get("raw_sha256") != predecessor[PLAN_PATH]["raw_sha256"]
            or plan_lock.get("plan_payload_sha256")
            != contract["predecessor"]["plan_payload_sha256"]
            or manifest_lock.get("raw_sha256")
            != predecessor[MANIFEST_PATH]["raw_sha256"]
        ):
            raise QualificationError(f"historical Wave {index + 1} core binding drifted")
        inventories.append(inventory)
        checks.append(
            {
                "wave": index + 1,
                "path": item["path"],
                "tree_oid": tree_oid,
                "inventory_sha256": digest,
                "case_count": len(inventory["cases"]),
            }
        )

    wave2_previous = inventories[1].get("previous_candidate_inventory")
    if wave2_previous != {
        "path": inventory_paths[0],
        "raw_sha256": inventory_digests[0],
    }:
        raise QualificationError("historical Wave 2 predecessor binding drifted")
    for index in range(2, 7):
        expected = [
            {"path": inventory_paths[item], "raw_sha256": inventory_digests[item]}
            for item in range(index)
        ]
        if inventories[index].get("previous_candidate_inventories") != expected:
            raise QualificationError(
                f"historical Wave {index + 1} predecessor chain drifted"
            )
    expected_wave8 = [
        {
            "path": inventory_paths[2],
            "raw_sha256": inventory_digests[2],
            "role": "exact_original_source_candidates",
        },
        {
            "path": inventory_paths[6],
            "raw_sha256": inventory_digests[6],
            "role": "complete_pre_wave8_candidate_denominator",
        },
    ]
    if inventories[7].get("predecessors") != expected_wave8:
        raise QualificationError("historical Wave 8 predecessor chain drifted")

    for index in (6, 7):
        inventory = inventories[index]
        if (
            inventory.get("live_official_capabilities", {}).get("raw_sha256")
            != predecessor[CAPABILITIES_PATH]["raw_sha256"]
            or inventory.get("live_capability_oracles", {}).get("raw_sha256")
            != predecessor[ORACLES_PATH]["raw_sha256"]
        ):
            raise QualificationError(
                f"historical Wave {index + 1} live-ledger binding drifted"
            )

    lock_count = _verify_inventory_source_locks(commit, inventories)
    return inventories, checks, lock_count


def _entry_ids(plan: dict[str, Any], expected_count: int, label: str) -> set[str]:
    entries = plan.get("entries")
    if not isinstance(entries, list) or len(entries) != expected_count:
        raise QualificationError(f"{label} gap denominator drifted")
    ids = [item.get("entry_id") for item in entries if isinstance(item, dict)]
    if len(ids) != expected_count or any(not isinstance(item, str) for item in ids):
        raise QualificationError(f"{label} gap IDs are incomplete")
    if len(set(ids)) != expected_count:
        raise QualificationError(f"{label} gap IDs are not unique")
    return set(ids)


def _verify_partition(
    contract: dict[str, Any],
    inventories: list[dict[str, Any]],
    old_ids: set[str],
    current_ids: set[str],
) -> dict[str, Any]:
    candidates: set[str] = set()
    for inventory in inventories[:6]:
        candidates.update(case["entry_id"] for case in inventory["cases"])
    wave7 = inventories[6]
    candidates.add(wave7["separate_detection_map_candidate"]["entry_id"])
    candidates.update(case["entry_id"] for case in wave7["cases"])
    blockers = {item["entry_id"] for item in wave7["blocked_entries"]}
    wave8_upgrades = {case["entry_id"] for case in inventories[7]["cases"]}
    successor = contract["successor"]

    if len(candidates) != successor["historical_candidate_count"]:
        raise QualificationError("historical candidate denominator drifted")
    if len(blockers) != successor["external_blocker_count"]:
        raise QualificationError("historical external blocker denominator drifted")
    if candidates & blockers or candidates | blockers != old_ids:
        raise QualificationError("historical candidate/blocker partition is not exact")
    if len(wave8_upgrades) != 2 or not wave8_upgrades <= candidates:
        raise QualificationError("Wave 8 upgrade identity drifted")

    removed = old_ids - current_ids
    added = current_ids - old_ids
    if removed != {CPU_GAP_ID} or added:
        raise QualificationError("87-to-86 gap transition is not CPU-only")
    still_open = candidates & current_ids
    retired = candidates - current_ids
    if (
        len(still_open) != successor["still_open_historical_candidate_count"]
        or retired != {CPU_GAP_ID}
        or blockers - current_ids
        or still_open | blockers != current_ids
    ):
        raise QualificationError("successor candidate/blocker partition is not exact")
    return {
        "historical_candidate_count": len(candidates),
        "still_open_historical_candidate_count": len(still_open),
        "retired_to_canonical_ids": sorted(retired),
        "external_blocker_ids": sorted(blockers),
        "wave8_upgrade_ids": sorted(wave8_upgrades),
        "removed_gap_ids": sorted(removed),
        "added_gap_ids": sorted(added),
    }


def _verify_cpu_ledgers(
    contract: dict[str, Any], capabilities: dict[str, Any], oracles: dict[str, Any]
) -> dict[str, Any]:
    successor = contract["successor"]
    capability_rows = capabilities.get("capabilities")
    oracle_rows = oracles.get("oracles")
    if (
        not isinstance(capability_rows, list)
        or len(capability_rows) != successor["official_capability_count"]
    ):
        raise QualificationError("current official capability denominator drifted")
    if (
        not isinstance(oracle_rows, list)
        or len(oracle_rows) != successor["capability_oracle_count"]
    ):
        raise QualificationError("current capability oracle denominator drifted")

    matches = [row for row in capability_rows if row.get("id") == CPU_CAPABILITY_ID]
    if len(matches) != 1:
        raise QualificationError("canonical CPU capability identity is not unique")
    capability = matches[0]
    expected = successor["cpu_state"]
    for key in ("acceptance_class", "thor_state", "runtime_state"):
        if capability.get(key) != expected[key]:
            raise QualificationError(f"canonical CPU capability {key} drifted")

    oracle_matches = [
        row
        for row in oracle_rows
        if row.get("capability_id") == CPU_CAPABILITY_ID
        and row.get("oracle_id") == CPU_ORACLE_ID
    ]
    if len(oracle_matches) != 1:
        raise QualificationError("canonical CPU oracle identity is not unique")
    oracle = oracle_matches[0]
    if oracle.get("current_state") != expected["oracle_current_state"]:
        raise QualificationError("canonical CPU oracle state drifted")
    if oracle.get("evidence") != expected["evidence"]:
        raise QualificationError("canonical CPU oracle evidence must remain empty")
    binding = oracle.get("ledger_binding")
    if not isinstance(binding, dict):
        raise QualificationError("canonical CPU oracle ledger binding is absent")
    for key in ("acceptance_class", "thor_state", "runtime_state"):
        if binding.get(key) != capability.get(key):
            raise QualificationError(f"canonical CPU oracle {key} binding drifted")
    if binding.get("contract") != capability.get("contract"):
        raise QualificationError("canonical CPU capability/oracle contract binding drifted")
    return {
        "gap_id": CPU_GAP_ID,
        "capability_id": CPU_CAPABILITY_ID,
        "oracle_id": CPU_ORACLE_ID,
        "acceptance_class": capability["acceptance_class"],
        "thor_state": capability["thor_state"],
        "runtime_state": capability["runtime_state"],
        "oracle_current_state": oracle["current_state"],
        "evidence": oracle["evidence"],
    }


def execute(contract_path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = _strict_json(contract_path.read_bytes(), contract_path.name)
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    if contract["predecessor"]["commit"] != PREDECESSOR_COMMIT:
        raise QualificationError("contract predecessor commit drifted")
    if (
        contract["successor"]["cpu_gap_id"] != CPU_GAP_ID
        or contract["successor"]["cpu_capability_id"] != CPU_CAPABILITY_ID
        or contract["successor"]["cpu_oracle_id"] != CPU_ORACLE_ID
    ):
        raise QualificationError("contract CPU identity drifted")

    _verify_commit(PREDECESSOR_COMMIT)
    old_objects, old_digests = _predecessor_objects(contract)
    current_objects, current_digests = _current_objects(contract)
    old_core = {
        path: {"raw_sha256": digest} for path, digest in old_digests.items()
    }
    inventories, wave_checks, historical_lock_count = _verify_wave_chain(
        contract, old_core
    )
    frozen_packages = _verify_frozen_packages(contract)

    old_plan = old_objects[PLAN_PATH]
    current_plan = current_objects[PLAN_PATH]
    predecessor = contract["predecessor"]
    successor = contract["successor"]
    if old_plan.get("plan_payload_sha256") != predecessor["plan_payload_sha256"]:
        raise QualificationError("predecessor plan payload identity drifted")
    if current_plan.get("plan_payload_sha256") != successor["plan_payload_sha256"]:
        raise QualificationError("current plan payload identity drifted")
    if len(old_objects[CAPABILITIES_PATH].get("capabilities", [])) != predecessor[
        "official_capability_count"
    ]:
        raise QualificationError("predecessor official capability denominator drifted")
    if len(old_objects[ORACLES_PATH].get("oracles", [])) != predecessor[
        "capability_oracle_count"
    ]:
        raise QualificationError("predecessor capability oracle denominator drifted")
    if any(
        row.get("id") == CPU_CAPABILITY_ID
        for row in old_objects[CAPABILITIES_PATH]["capabilities"]
    ):
        raise QualificationError("CPU capability unexpectedly exists in predecessor ledger")
    if any(
        row.get("capability_id") == CPU_CAPABILITY_ID
        for row in old_objects[ORACLES_PATH]["oracles"]
    ):
        raise QualificationError("CPU oracle unexpectedly exists in predecessor ledger")

    old_ids = _entry_ids(old_plan, predecessor["advertised_gap_count"], "predecessor")
    current_ids = _entry_ids(
        current_plan, successor["advertised_gap_count"], "current"
    )
    partition = _verify_partition(contract, inventories, old_ids, current_ids)
    cpu = _verify_cpu_ledgers(
        contract,
        current_objects[CAPABILITIES_PATH],
        current_objects[ORACLES_PATH],
    )

    result = {
        "schema_version": 1,
        "mode": "read_only_cpu_multimedia_ledger_successor",
        "status": "successor_mapping_verified_non_advancing",
        "policy": contract["policy"],
        "predecessor": {
            "commit": PREDECESSOR_COMMIT,
            "commit_object_type": "commit",
            "advertised_gap_count": len(old_ids),
            "official_capability_count": len(
                old_objects[CAPABILITIES_PATH]["capabilities"]
            ),
            "capability_oracle_count": len(old_objects[ORACLES_PATH]["oracles"]),
            "plan_payload_sha256": old_plan["plan_payload_sha256"],
            "core_sha256": old_digests,
            "wave_checks": wave_checks,
            "historical_inventory_source_lock_count": historical_lock_count,
        },
        "successor": {
            "advertised_gap_count": len(current_ids),
            "official_capability_count": len(
                current_objects[CAPABILITIES_PATH]["capabilities"]
            ),
            "capability_oracle_count": len(current_objects[ORACLES_PATH]["oracles"]),
            "plan_payload_sha256": current_plan["plan_payload_sha256"],
            "core_sha256": current_digests,
            **partition,
        },
        "frozen_packages": frozen_packages,
        "cpu": cpu,
        "integrity": {
            "predecessor_commit_verified": True,
            "predecessor_core_objects_verified": True,
            "wave_package_trees_verified": True,
            "wave_inventories_verified": True,
            "predecessor_chain_verified": True,
            "historical_inventory_source_locks_verified": True,
            "frozen_package_trees_verified": True,
            "frozen_key_artifacts_verified": True,
            "frozen_embedded_source_locks_bound": True,
            "frozen_embedded_source_paths_present_in_predecessor": True,
            "current_core_verified": True,
            "exact_set_transition_verified": True,
            "candidate_partition_verified": True,
        },
        "effects": {
            "runtime_evidence": [],
            "official_capability_effect": "none_candidate_only",
            "network_used": False,
            "docker_used": False,
            "downloads_used": False,
            "runtime_used": False,
            "file_writes_used": False,
            "subprocess_used": True,
            "subprocess_scope": "read_only_local_git_objects_only",
        },
        "limitations": [
            "historical_wave_executors_not_reexecuted_from_exported_worktree",
            "frozen_candidate_integration_and_planning_executors_identity_verified_not_reexecuted",
            "frozen_offline_mv3dt_observation_identity_verified_not_reexecuted",
            "frozen_source_lock_and_recursive_coverage_validators_identity_verified_not_reexecuted",
            "embedded_historical_source_digests_are_bound_by_artifact_identity_not_rebased_to_predecessor_tip",
            "identity_and_partition_verification_does_not_replace_runtime_qualification",
        ],
    }
    _validate(result, RESULT_SCHEMA_PATH, "result")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute(args.contract), sort_keys=True, separators=(",", ":")))
    except QualificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
