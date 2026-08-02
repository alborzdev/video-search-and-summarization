#!/usr/bin/env python3
"""Compile and verify the current 74-row advertised-entry executor successor."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
INVENTORY_PATH = LANE / "inventory.json"
INVENTORY_SCHEMA_PATH = LANE / "inventory.schema.json"
MIGRATION_PATH = LANE / "migration-map.json"
MIGRATION_SCHEMA_PATH = LANE / "migration-map.schema.json"
MAX_INPUT_BYTES = 16_000_000

SOURCE_PLAN = {
    "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "raw_sha256": "2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c",
    "payload_sha256": "93981c6e1f277932614694e532de1514c196551109e5850305d88daf740b3bb0",
}
SOURCE_MANIFEST = {
    "path": "deploy/docker/thor-local/parity/manifest.json",
    "raw_sha256": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
}
SOURCE_OFFICIAL = {
    "path": "deploy/docker/thor-local/parity/official-capabilities.json",
    "raw_sha256": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
}
SOURCE_ORACLES = {
    "path": "deploy/docker/thor-local/parity/capability-oracles.json",
    "raw_sha256": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
}

HISTORICAL_WAVES = (
    {
        "wave": 1,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors/inventory.json",
        "inventory_sha256": "91406a15ff1340b9b4dba988507470234971fa4905997bc52e64fb983fc12a18",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors/executor.py",
        "executor_sha256": "d0c35c267b23332672bc09a63d5bc7390f881b54c2ffad149bdf013909232222",
        "old_case_count": 8,
        "retained_case_count": 1,
    },
    {
        "wave": 2,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/inventory.json",
        "inventory_sha256": "2c14f8ae5ade22ccbc556a844b4fcb63661048826660073fb21c5f882047c5d2",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/executor.py",
        "executor_sha256": "fe361d69405a4a87268703445e4e62aa96a00aea562414963b76c799f59504e5",
        "old_case_count": 21,
        "retained_case_count": 18,
    },
    {
        "wave": 3,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/inventory.json",
        "inventory_sha256": "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/executor.py",
        "executor_sha256": "027b058973757c69855bd441aa6da13fb8f7adebcf1ae40dbb4a7837d744a524",
        "old_case_count": 23,
        "retained_case_count": 23,
    },
    {
        "wave": 4,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/inventory.json",
        "inventory_sha256": "1de6e9be3c93c349e45b192506e3081758553582dda6f73b79877bc4ff5155a6",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave4/executor.py",
        "executor_sha256": "017d24d15946c200c489bd423b59b5fe0bad12dc46091cbc0e682c6c0e35ff39",
        "old_case_count": 5,
        "retained_case_count": 5,
    },
    {
        "wave": 5,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/inventory.json",
        "inventory_sha256": "98876a18d628df644171cd1d0051753dadd904cca67a5fe0fa8696832cb08771",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave5/executor.py",
        "executor_sha256": "51653c790cb4460528d24f264c4eb3134397de49fd65bb5e8f2ae4c9f52f22f3",
        "old_case_count": 6,
        "retained_case_count": 5,
    },
    {
        "wave": 6,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave6/inventory.json",
        "inventory_sha256": "dbc1045b5d9e6b02ab152f2f0cc9007c0087e265692ef4e4aa911dc12f7935e3",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave6/executor.py",
        "executor_sha256": "b3ecd3298f6f903d0ca09e3136c35aad9ade91749e1c60c9a6efc952ee8095e1",
        "old_case_count": 8,
        "retained_case_count": 8,
    },
    {
        "wave": 7,
        "inventory_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.json",
        "inventory_sha256": "ebab232152429b866ffc283f2b3c761f11c679e7c26979b2adaa0c8f11b2739d",
        "executor_path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/executor.py",
        "executor_sha256": "bbb38f30bb687d142d932a69a0e1aab12517ecffd7c1f1babf0302e896b69ead",
        "old_case_count": 11,
        "retained_case_count": 11,
    },
)

DETECTION_MAP_ID = "manifest-gap.spatial-ai-utils.03-detection-map"
EXPECTED_BLOCKER_IDS = {
    "manifest-gap.alert-notifications-slack.00-slack-notification",
    "manifest-gap.enterprise-rag.00-rag-report-generation",
    "manifest-gap.enterprise-rag.01-frag-retrieval-integration",
}
EXPECTED_MIGRATED_IDS = {
    "manifest-gap.spatial-ai-utils.00-calibration-and-camera-grouping",
    "manifest-gap.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-gap.spatial-ai-utils.02-multiview-visualization",
    "manifest-gap.spatial-ai-utils.03-detection-map",
    "manifest-gap.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-gap.spatial-ai-utils.05-nvschema-conversion",
    "manifest-gap.spatial-ai-utils.06-video-frame-tools",
    "manifest-gap.spatial-ai-utils.07-aws-gcs-validation",
    "manifest-gap.synthetic-data-tools.00-semantic-label-helpers",
    "manifest-gap.synthetic-data-tools.01-dataset-checks",
    "manifest-gap.synthetic-data-tools.02-rgb-depth-video-conversion",
    "manifest-gap.synthetic-data-tools.03-ground-truth-conversion",
    "manifest-gap.vios-codecs-audio.05-cpu-multimedia-support",
}
EXPECTED_INVENTORY_RAW_SHA256 = (
    "a9774af207f612e6c07936637d1141f5bc8e77df607363cfbac33aa447e19cb7"
)
EXPECTED_MIGRATION_RAW_SHA256 = (
    "d2107c0cad790472896d194d4b9e704ecc9724678485788d3b94f6799bd4dc50"
)
EXPECTED_INVENTORY_SCHEMA_RAW_SHA256 = (
    "e0bad7baa44b288b49bc46118dc1aef92a7d809278b68e88f46e95234c6a8422"
)
EXPECTED_MIGRATION_SCHEMA_RAW_SHA256 = (
    "41d3cca41b0fead24b292c06827a3b0ac02267af1449a777be33619fb0c2b902"
)


class CompileError(RuntimeError):
    """A lock, schema, identity, set, or safety invariant failed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CompileError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise CompileError(f"{label}: non-finite JSON constant {value!r}")

    try:
        return json.loads(
            payload.decode(),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompileError(f"{label}: invalid UTF-8 JSON") from exc


def _repo_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise CompileError(f"unsafe repository path: {relative}")
    try:
        repository = REPO_ROOT.resolve(strict=True)
    except OSError as exc:
        raise CompileError("repository root is unavailable") from exc
    current = repository
    for index, part in enumerate(pure.parts):
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CompileError(f"repository input unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CompileError(f"repository input contains a symlink: {relative}")
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise CompileError(
                f"repository input parent is not a directory: {relative}"
            )
    if not stat.S_ISREG(metadata.st_mode):
        raise CompileError(f"repository input is not a regular file: {relative}")
    if metadata.st_size > MAX_INPUT_BYTES:
        raise CompileError(f"repository input exceeds size bound: {relative}")
    return current


def _read_repo_bytes(relative: str) -> bytes:
    path = _repo_file(relative)
    before = path.stat(follow_symlinks=False)
    payload = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or len(payload) != before.st_size:
        raise CompileError(f"repository input changed while reading: {relative}")
    if len(payload) > MAX_INPUT_BYTES:
        raise CompileError(f"repository input exceeds size bound: {relative}")
    return payload


def _read_package_bytes(path: Path) -> bytes:
    try:
        repository = REPO_ROOT.resolve(strict=True)
        relative = path.absolute().relative_to(repository).as_posix()
    except (OSError, ValueError) as exc:
        raise CompileError(f"package file is outside the repository: {path}") from exc
    return _read_repo_bytes(relative)


def _load_locked_json(lock: dict[str, Any], label: str) -> tuple[Any, bytes]:
    raw = _read_repo_bytes(lock["path"])
    observed = _sha_bytes(raw)
    if observed != lock["raw_sha256"]:
        raise CompileError(f"{label} raw digest drift: {observed}")
    return _strict_json(raw, lock["path"]), raw


def _validate_schema(value: Any, path: Path, label: str) -> None:
    schema = _strict_json(_read_package_bytes(path), str(path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CompileError(f"{label} schema is invalid") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.absolute_path)
        raise CompileError(f"{label} schema failed at {location}: {first.message}")


def _resolve_pointer(value: Any, pointer: str) -> Any:
    current = value
    try:
        for raw in pointer.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            current = (
                current[int(token)] if isinstance(current, list) else current[token]
            )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise CompileError(f"unresolved JSON pointer: {pointer}") from exc
    return current


def _payload(value: dict[str, Any], field: str) -> str:
    payload = dict(value)
    observed = payload.pop(field, None)
    calculated = _sha_json(payload)
    if observed != calculated:
        raise CompileError(f"{field} is internally inconsistent")
    return calculated


def _successor_id(entry_id: str) -> str:
    prefix = "manifest-gap."
    if not entry_id.startswith(prefix):
        raise CompileError(f"unexpected historical entry ID: {entry_id}")
    return "manifest-entry." + entry_id[len(prefix) :]


def _verify_plan_manifest_bindings(
    plan_entries: list[dict[str, Any]], manifest: dict[str, Any]
) -> None:
    for entry in plan_entries:
        entry_id = entry.get("entry_id")
        pointer = entry.get("manifest_pointer")
        advertised = entry.get("advertised")
        if not isinstance(pointer, str) or not isinstance(advertised, str):
            raise CompileError(f"current plan binding is malformed: {entry_id}")
        if _resolve_pointer(manifest, pointer) != advertised:
            raise CompileError(f"current plan/manifest literal mismatch: {entry_id}")


def compile_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    plan, _ = _load_locked_json(SOURCE_PLAN, "current gap plan")
    manifest, _ = _load_locked_json(SOURCE_MANIFEST, "current manifest")
    official, _ = _load_locked_json(SOURCE_OFFICIAL, "fixed official ledger")
    oracles, _ = _load_locked_json(SOURCE_ORACLES, "fixed oracle registry")
    if _payload(plan, "plan_payload_sha256") != SOURCE_PLAN["payload_sha256"]:
        raise CompileError("current plan payload identity drift")

    plan_entries = plan.get("entries")
    if not isinstance(plan_entries, list) or len(plan_entries) != 74:
        raise CompileError("current gap plan is not exactly 74 rows")
    plan_by_id = {row.get("entry_id"): row for row in plan_entries}
    if len(plan_by_id) != 74 or None in plan_by_id:
        raise CompileError("current gap entry IDs are not exactly unique")
    if len({row.get("manifest_pointer") for row in plan_entries}) != 74:
        raise CompileError("current gap pointers are not exactly unique")
    _verify_plan_manifest_bindings(plan_entries, manifest)

    official_rows = official.get("capabilities")
    oracle_rows = oracles.get("oracles")
    if not isinstance(official_rows, list) or not isinstance(oracle_rows, list):
        raise CompileError("fixed live predecessor documents are malformed")
    official_by_id = {row.get("id"): row for row in official_rows}
    oracle_by_id = {row.get("capability_id"): row for row in oracle_rows}
    if len(official_by_id) != len(official_rows) or len(oracle_by_id) != len(
        oracle_rows
    ):
        raise CompileError("fixed live predecessor identities are not unique")

    historical_inputs: list[dict[str, Any]] = []
    old_cases: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    wave7_inventory: dict[str, Any] | None = None
    for lock in HISTORICAL_WAVES:
        inventory_lock = {
            "path": lock["inventory_path"],
            "raw_sha256": lock["inventory_sha256"],
        }
        inventory, _ = _load_locked_json(
            inventory_lock, f"Wave {lock['wave']} inventory"
        )
        executor_raw = _read_repo_bytes(lock["executor_path"])
        if _sha_bytes(executor_raw) != lock["executor_sha256"]:
            raise CompileError(f"Wave {lock['wave']} executor digest drift")
        cases = inventory.get("cases")
        if not isinstance(cases, list) or len(cases) != lock["old_case_count"]:
            raise CompileError(f"Wave {lock['wave']} historical case denominator drift")
        retained = [row for row in cases if row.get("entry_id") in plan_by_id]
        if len(retained) != lock["retained_case_count"]:
            raise CompileError(f"Wave {lock['wave']} retained case denominator drift")
        historical_inputs.append(dict(lock))
        old_cases.extend((lock["wave"], row, lock) for row in cases)
        if lock["wave"] == 7:
            wave7_inventory = inventory

    if wave7_inventory is None:
        raise CompileError("Wave 7 inventory was not loaded")
    old_case_ids = [row[1].get("entry_id") for row in old_cases]
    if len(old_case_ids) != 82 or len(set(old_case_ids)) != 82:
        raise CompileError("historical wave case IDs are not exactly 82 unique IDs")
    old_blockers = wave7_inventory.get("blocked_entries")
    if not isinstance(old_blockers, list) or len(old_blockers) != 4:
        raise CompileError("historical Wave 7 blocker denominator drift")
    old_blocker_ids = [row.get("entry_id") for row in old_blockers]
    old_ids = set(old_case_ids) | set(old_blocker_ids) | {DETECTION_MAP_ID}
    if len(old_ids) != 87:
        raise CompileError("historical 87-row denominator is not an exact partition")

    plan_ids = set(plan_by_id)
    migrated_ids = old_ids - plan_ids
    if migrated_ids != EXPECTED_MIGRATED_IDS or plan_ids - old_ids:
        raise CompileError("87-to-74 identity rebase differs from the exact migration")
    blocker_ids = set(old_blocker_ids) & plan_ids
    if blocker_ids != EXPECTED_BLOCKER_IDS:
        raise CompileError("current external blocker identity drift")

    source_files: dict[str, str] = {}
    source_lock_references = 0
    candidates: list[dict[str, Any]] = []
    migration_owner: dict[str, str] = {DETECTION_MAP_ID: "separate_detection_map"}
    for wave, historical, lock in old_cases:
        entry_id = historical["entry_id"]
        if entry_id not in plan_by_id:
            migration_owner[entry_id] = f"wave{wave}"
            continue
        current = plan_by_id[entry_id]
        expected = {
            "manifest_pointer": current["manifest_pointer"],
            "entry_id": current["entry_id"],
            "proposed_capability_id": current["proposed_capability"]["id"],
            "advertised": current["advertised"],
            "advertised_utf8_sha256": current["advertised_utf8_sha256"],
            "advertised_canonical_sha256": current["advertised_canonical_sha256"],
        }
        if any(historical.get(key) != value for key, value in expected.items()):
            raise CompileError(f"current binding drift for {entry_id}")
        if (
            current.get("coverage_state") != "open_missing_entry_capability_and_oracle"
            or current.get("runtime_evidence") != []
            or current.get("required_oracle", {}).get("status") != "open_unexecuted"
            or current.get("required_oracle", {}).get("runtime_evidence") != []
        ):
            raise CompileError(f"current candidate is not open/unexecuted: {entry_id}")
        locks = historical.get("source_locks")
        if not isinstance(locks, list) or not locks:
            raise CompileError(f"candidate has no source locks: {entry_id}")
        for source_lock in locks:
            path = source_lock["path"]
            digest = source_lock["sha256"]
            observed = _sha_bytes(_read_repo_bytes(path))
            if observed != digest:
                raise CompileError(f"candidate source digest drift: {entry_id}: {path}")
            previous = source_files.setdefault(path, digest)
            if previous != digest:
                raise CompileError(f"inconsistent source digest across cases: {path}")
            source_lock_references += 1
        candidates.append(
            {
                **expected,
                "disposition": "candidate",
                "legacy_wave": wave,
                "legacy_inventory_path": lock["inventory_path"],
                "legacy_row_canonical_sha256": _sha_json(historical),
                "adapter_id": historical["adapter_id"],
                "source_lock_count": len(locks),
                "executor": "direct_historical_adapter",
                "dispatch_status": "implemented_phase_2",
                "runtime_evidence": [],
                "can_mark_passed_current": False,
            }
        )

    old_blocker_by_id = {row["entry_id"]: row for row in old_blockers}
    blockers: list[dict[str, Any]] = []
    for entry_id in sorted(blocker_ids):
        historical = old_blocker_by_id[entry_id]
        current = plan_by_id[entry_id]
        required_oracle = current.get("required_oracle", {})
        if (
            required_oracle.get("type") != "external_optional_boundary"
            or required_oracle.get("status") != "open_unexecuted"
            or required_oracle.get("runtime_evidence") != []
        ):
            raise CompileError(f"external blocker boundary drift: {entry_id}")
        blockers.append(
            {
                "entry_id": entry_id,
                "manifest_pointer": current["manifest_pointer"],
                "proposed_capability_id": current["proposed_capability"]["id"],
                "advertised": current["advertised"],
                "advertised_utf8_sha256": current["advertised_utf8_sha256"],
                "advertised_canonical_sha256": current["advertised_canonical_sha256"],
                "disposition": "external_blocker",
                "legacy_wave": 7,
                "legacy_inventory_path": HISTORICAL_WAVES[-1]["inventory_path"],
                "legacy_row_canonical_sha256": _sha_json(historical),
                "blocker_type": historical["blocker_type"],
                "reason": historical["reason"],
                "required_oracle_canonical_sha256": _sha_json(required_oracle),
                "executor": None,
                "candidate_materialized": False,
                "runtime_evidence": [],
                "can_mark_passed_current": False,
            }
        )

    candidates.sort(key=lambda row: (row["legacy_wave"], row["manifest_pointer"]))
    rows = candidates + blockers
    if len(candidates) != 71 or len(blockers) != 3 or len(rows) != 74:
        raise CompileError("successor row denominator drift")
    if {row["entry_id"] for row in rows} != plan_ids:
        raise CompileError("successor rows do not exactly cover the current plan")
    if source_lock_references != 182 or len(source_files) != 88:
        raise CompileError("retained candidate source-lock denominator drift")
    wave_counts = Counter(row["legacy_wave"] for row in candidates)
    if wave_counts != Counter({1: 1, 2: 18, 3: 23, 4: 5, 5: 5, 6: 8, 7: 11}):
        raise CompileError("retained per-wave denominator drift")

    proposed_ids = {row["proposed_capability"]["id"] for row in plan_entries}
    if proposed_ids & set(official_by_id) or proposed_ids & set(oracle_by_id):
        raise CompileError(
            "current gap identity was promoted into the fixed predecessor"
        )

    migration_owner["manifest-gap.spatial-ai-utils.07-aws-gcs-validation"] = (
        "wave7_blocker"
    )
    migrations: list[dict[str, Any]] = []
    for entry_id in sorted(migrated_ids):
        capability_id = _successor_id(entry_id)
        capability = official_by_id.get(capability_id)
        oracle = oracle_by_id.get(capability_id)
        if not isinstance(capability, dict) or not isinstance(oracle, dict):
            raise CompileError(f"migrated live predecessor missing: {entry_id}")
        if oracle.get("oracle_id") != f"oracle.{capability_id}":
            raise CompileError(f"migrated oracle identity drift: {entry_id}")
        if capability.get("title") != _resolve_pointer(
            manifest,
            next(
                row[1]["manifest_pointer"]
                for row in old_cases
                if row[1]["entry_id"] == entry_id
            )
            if entry_id not in {DETECTION_MAP_ID, *set(old_blocker_ids)}
            else next(
                row["manifest_pointer"]
                for row in (
                    old_blockers
                    + [
                        {
                            "entry_id": DETECTION_MAP_ID,
                            "manifest_pointer": "/features/29/advertised/3",
                        }
                    ]
                )
                if row["entry_id"] == entry_id
            ),
        ):
            raise CompileError(f"migrated capability title/manifest drift: {entry_id}")
        pointer = (
            next(
                row[1]["manifest_pointer"]
                for row in old_cases
                if row[1]["entry_id"] == entry_id
            )
            if entry_id not in {DETECTION_MAP_ID, *set(old_blocker_ids)}
            else next(
                row["manifest_pointer"]
                for row in old_blockers
                + [
                    {
                        "entry_id": DETECTION_MAP_ID,
                        "manifest_pointer": "/features/29/advertised/3",
                    }
                ]
                if row["entry_id"] == entry_id
            )
        )
        migrations.append(
            {
                "former_gap_entry_id": entry_id,
                "manifest_pointer": pointer,
                "legacy_owner": migration_owner[entry_id],
                "live_capability_id": capability_id,
                "live_oracle_id": oracle["oracle_id"],
                "title": capability["title"],
                "thor_state": capability["thor_state"],
                "runtime_state": capability["runtime_state"],
                "oracle_current_state": oracle["current_state"],
                "oracle_acceptance_classification": oracle["acceptance_readiness"][
                    "classification"
                ],
                "live_capability_canonical_sha256": _sha_json(capability),
                "live_oracle_canonical_sha256": _sha_json(oracle),
                "runtime_evidence": oracle.get("evidence", []),
            }
        )

    inventory: dict[str, Any] = {
        "schema_version": 1,
        "mode": "advertised_entry_executor_74_successor_phase2",
        "source_plan": SOURCE_PLAN,
        "source_manifest": SOURCE_MANIFEST,
        "source_official_capabilities": SOURCE_OFFICIAL,
        "source_capability_oracles": SOURCE_ORACLES,
        "historical_waves": historical_inputs,
        "policy": {
            "planning_only": True,
            "candidate_only": True,
            "dispatch_implemented": True,
            "can_mark_passed_current": False,
            "runtime_evidence": [],
            "network_allowed": False,
            "docker_allowed": False,
            "subprocess_allowed": False,
            "credentials_allowed": False,
            "lifecycle_allowed": False,
            "downloads_allowed": False,
            "host_inspection_allowed": False,
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "historical_gap_entries": 87,
            "current_gap_entries": 74,
            "candidate_entries": 71,
            "dispatchable_candidates": 71,
            "external_blockers": 3,
            "migrated_entries": 13,
            "source_lock_references": source_lock_references,
            "unique_source_paths": len(source_files),
            "unique_adapter_ids": len({row["adapter_id"] for row in candidates}),
            "per_wave_candidate_counts": {
                str(wave): wave_counts[wave] for wave in range(1, 8)
            },
        },
        "source_files": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(source_files.items())
        ],
        "rows": rows,
    }
    inventory["inventory_payload_sha256"] = _sha_json(inventory)

    migration: dict[str, Any] = {
        "schema_version": 1,
        "mode": "advertised_entry_87_to_74_live_predecessor_migration_map",
        "source_inventory_payload_sha256": inventory["inventory_payload_sha256"],
        "policy": {
            "migration_is_runtime_qualification": False,
            "can_mark_passed_current": False,
            "runtime_evidence": [],
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "former_gap_entries": 13,
            "live_capabilities": 13,
            "live_oracles": 13,
            "not_qualified": 12,
            "external_boundary": 1,
        },
        "migrations": migrations,
    }
    migration["migration_payload_sha256"] = _sha_json(migration)
    return inventory, migration


def check_checked_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    expected_inventory, expected_migration = compile_artifacts()
    inventory_raw = _read_package_bytes(INVENTORY_PATH)
    migration_raw = _read_package_bytes(MIGRATION_PATH)
    if (
        _sha_bytes(_read_package_bytes(INVENTORY_SCHEMA_PATH))
        != EXPECTED_INVENTORY_SCHEMA_RAW_SHA256
    ):
        raise CompileError("checked-in inventory schema raw digest drift")
    if (
        _sha_bytes(_read_package_bytes(MIGRATION_SCHEMA_PATH))
        != EXPECTED_MIGRATION_SCHEMA_RAW_SHA256
    ):
        raise CompileError("checked-in migration schema raw digest drift")
    inventory = _strict_json(inventory_raw, str(INVENTORY_PATH))
    migration = _strict_json(migration_raw, str(MIGRATION_PATH))
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    _validate_schema(migration, MIGRATION_SCHEMA_PATH, "migration map")
    _payload(inventory, "inventory_payload_sha256")
    _payload(migration, "migration_payload_sha256")
    if inventory != expected_inventory:
        raise CompileError("checked-in inventory differs from deterministic projection")
    if migration != expected_migration:
        raise CompileError(
            "checked-in migration map differs from deterministic projection"
        )
    if _sha_bytes(inventory_raw) != EXPECTED_INVENTORY_RAW_SHA256:
        raise CompileError("checked-in inventory raw digest drift")
    if _sha_bytes(migration_raw) != EXPECTED_MIGRATION_RAW_SHA256:
        raise CompileError("checked-in migration map raw digest drift")
    return inventory, migration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print-inventory", action="store_true")
    parser.add_argument("--print-migration", action="store_true")
    args = parser.parse_args()
    if args.print_inventory or args.print_migration:
        inventory, migration = compile_artifacts()
        value = migration if args.print_migration else inventory
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))
        return 0
    inventory, migration = check_checked_artifacts()
    print(
        "VALID: 74 rows = 71 candidates + 3 blockers; "
        f"13 migrated; inventory={inventory['inventory_payload_sha256']}; "
        f"migration={migration['migration_payload_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
