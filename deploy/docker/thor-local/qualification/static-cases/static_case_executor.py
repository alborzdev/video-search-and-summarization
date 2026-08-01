#!/usr/bin/env python3
"""Candidate-only, bounded, read-only static qualification observations.

This program has no activation mode.  It never opens a socket, invokes Docker,
spawns a process, or changes a service.  ``inspect`` creates one private
temporary directory for owned fixture copies and removes only that directory.
Its JSON is a static observation, deliberately not runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator


LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
INVENTORY_PATH = LANE / "inventory.json"
INVENTORY_SCHEMA_PATH = LANE / "inventory.schema.json"
RESULT_SCHEMA_PATH = LANE / "static-result.schema.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
DEADLINE_SECONDS = 10
EXPECTED_CAPABILITY_IDS = {
    "calibration.schema.vss-json",
    "prereq.warehouse.thor-platform",
    "configuration.warehouse.profile-hardware-matrix",
    "configuration.warehouse.broker-minimal-retention",
    "configuration.warehouse.rtdetr-deepstream",
    "configuration.warehouse.sparse4d-deepstream",
    "configuration.warehouse.mv3dt-deepstream",
    "behavior.warehouse.destructive-troubleshooting-boundaries",
    "performance.warehouse.profile-latency",
    "boundary.warehouse.sdg-toolchain",
    "boundary.warehouse.sdg-scene-calibration",
    "boundary.warehouse.sdg-postprocess",
    "boundary.warehouse.sim2real",
    "prereq.platform.validated-gpus",
    "prereq.platform.agx-thor-software",
    "prereq.platform.kernel-and-thor-runtime",
    "boundary.thor.fully-local-future",
    "tooling.agent-skills.catalog-16",
    "configuration.agent.file-llm-schema",
    "configuration.agent.mcp-client",
    "configuration.agent.knowledge-retrieval-backends",
    "configuration.agent.hierarchy",
    "configuration.rt-embed.model-source",
    "configuration.warehouse.behavior-analytics",
}
EXCLUDED_SAMPLE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)
HOST_FILES = {
    "model": Path("/proc/device-tree/model"),
    "bsp": Path("/etc/nv_tegra_release"),
    "driver": Path("/sys/module/nvidia/version"),
    "disable_ipv6": Path("/proc/sys/net/ipv6/conf/all/disable_ipv6"),
    "rmem_max": Path("/proc/sys/net/core/rmem_max"),
    "wmem_max": Path("/proc/sys/net/core/wmem_max"),
    "tcp_rmem": Path("/proc/sys/net/ipv4/tcp_rmem"),
    "tcp_wmem": Path("/proc/sys/net/ipv4/tcp_wmem"),
}


class StaticCaseError(RuntimeError):
    """Fail-closed package or admission error."""


class BoundError(StaticCaseError):
    """A byte, file, or time bound was exceeded."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _remove_object_key(value: Any, key: str) -> Any:
    """Return a JSON value with every object member named *key* removed."""
    if isinstance(value, dict):
        return {
            name: _remove_object_key(item, key)
            for name, item in value.items()
            if name != key
        }
    if isinstance(value, list):
        return [_remove_object_key(item, key) for item in value]
    return value


def _count_object_key(value: Any, key: str) -> int:
    if isinstance(value, dict):
        return int(key in value) + sum(
            _count_object_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return sum(_count_object_key(item, key) for item in value)
    return 0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _strict_json_bytes(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise StaticCaseError(f"{label}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StaticCaseError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _load_package_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise StaticCaseError(f"package JSON is not a regular non-symlink file: {path}")
    payload = path.read_bytes()
    if len(payload) > MAX_BYTES:
        raise StaticCaseError(f"package JSON exceeds {MAX_BYTES} bytes: {path}")
    return _strict_json_bytes(payload, str(path))


def _check_repo_components(path: Path) -> None:
    root = REPO_ROOT.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise StaticCaseError(f"path escapes repository: {path}") from exc
    cursor = root
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            raise StaticCaseError(f"repository path contains a symlink: {cursor}")


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        raise StaticCaseError(f"unsafe repository-relative path: {relative!r}")
    root = REPO_ROOT.resolve()
    path = root / candidate
    _check_repo_components(path)
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise StaticCaseError(f"source is unavailable: {relative}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise StaticCaseError(f"source is not a regular file: {relative}")
    return path


@dataclass
class Budget:
    started: float = field(default_factory=time.monotonic)
    bytes_read: int = 0
    files_read: int = 0
    hashes: dict[str, str] = field(default_factory=dict)

    def check_time(self) -> None:
        if time.monotonic() - self.started > DEADLINE_SECONDS:
            raise BoundError(f"static case exceeded {DEADLINE_SECONDS} seconds")

    def read_repo(self, relative: str) -> bytes:
        self.check_time()
        path = _repo_file(relative)
        return self._read(path, relative)

    def read_host(self, key: str) -> bytes | None:
        self.check_time()
        path = HOST_FILES[key]
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError:
            return None
        if not stat.S_ISREG(mode):
            return None
        return self._read(path, str(path))

    def _read(self, path: Path, label: str) -> bytes:
        if label in self.hashes:
            payload = path.read_bytes()
            if _sha_bytes(payload) != self.hashes[label]:
                raise StaticCaseError(f"source changed during observation: {label}")
            return payload
        if self.files_read >= MAX_FILES:
            raise BoundError(f"static case exceeds {MAX_FILES} source files")
        size = path.stat(follow_symlinks=False).st_size
        remaining = MAX_BYTES - self.bytes_read
        if label.startswith(("/proc/", "/sys/")):
            with path.open("rb") as stream:
                payload = stream.read(remaining + 1)
            if len(payload) > remaining:
                raise BoundError(f"static case exceeds {MAX_BYTES} source bytes")
        else:
            if size < 0 or size > remaining:
                raise BoundError(f"static case exceeds {MAX_BYTES} source bytes")
            payload = path.read_bytes()
            if len(payload) != size:
                raise StaticCaseError(f"source size changed while reading: {label}")
        self.bytes_read += len(payload)
        self.files_read += 1
        self.hashes[label] = _sha_bytes(payload)
        self.check_time()
        return payload

    def rehash(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for label in self.hashes:
            path = Path(label) if label.startswith("/") else _repo_file(label)
            payload = path.read_bytes()
            values[label] = _sha_bytes(payload)
        return values


def load_and_validate_inventory() -> dict[str, Any]:
    inventory = _load_package_json(INVENTORY_PATH)
    schema = _load_package_json(INVENTORY_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(inventory),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(error.message for error in errors[:5])
        raise StaticCaseError(f"inventory schema validation failed: {detail}")

    cases = inventory["cases"]
    case_ids = [item["case_id"] for item in cases]
    capability_ids = [item["capability_id"] for item in cases]
    if len(set(case_ids)) != len(case_ids):
        raise StaticCaseError("static case IDs are not unique")
    if len(set(capability_ids)) != len(capability_ids):
        raise StaticCaseError("static capability IDs are not unique")
    if set(capability_ids) != EXPECTED_CAPABILITY_IDS:
        missing = sorted(EXPECTED_CAPABILITY_IDS - set(capability_ids))
        extra = sorted(set(capability_ids) - EXPECTED_CAPABILITY_IDS)
        raise StaticCaseError(f"24-ID tranche drift: missing={missing}, extra={extra}")

    inventory_text = INVENTORY_PATH.read_text(encoding="utf-8")
    forbidden = [
        marker for marker in EXCLUDED_SAMPLE_MARKERS if marker in inventory_text
    ]
    if forbidden:
        raise StaticCaseError(
            f"excluded Warehouse sample marker in inventory: {forbidden}"
        )

    evidence = inventory["evidence_schema_binding"]
    evidence_path = _repo_file(evidence["path"])
    actual_evidence_sha = _sha_bytes(evidence_path.read_bytes())
    if actual_evidence_sha != evidence["sha256"]:
        raise StaticCaseError("runtime-evidence shape-reference binding changed")
    return inventory


def _binding(
    case: dict[str, Any], budget: Budget
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    binding = case["binding"]
    try:
        document = _strict_json_bytes(
            budget.read_repo(binding["path"]), binding["path"]
        )
    except StaticCaseError as exc:
        return None, {"id": "binding", "status": "blocked", "detail": str(exc)}
    collection = document.get(binding["collection"])
    if not isinstance(collection, list):
        return None, {
            "id": "binding",
            "status": "blocked",
            "detail": f"missing collection {binding['collection']}",
        }
    matches = [
        item
        for item in collection
        if isinstance(item, dict) and item.get("id") == binding["record_id"]
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("contract"), dict):
        return None, {
            "id": "binding",
            "status": "blocked",
            "detail": "bound capability is missing, duplicate, or has no contract",
        }
    record = matches[0]
    actual = _sha_json(record["contract"])
    return record, {
        "id": "binding_contract_sha256",
        "status": "match" if actual == binding["contract_sha256"] else "mismatch",
        "expected": binding["contract_sha256"],
        "observed": actual,
    }


def _source_assertions(case: dict[str, Any], budget: Budget) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for assertion in case["source_assertions"]:
        try:
            payload = budget.read_repo(assertion["path"])
            text = payload.decode("utf-8")
        except (StaticCaseError, UnicodeDecodeError) as exc:
            observations.append(
                {
                    "id": f"source:{assertion['path']}",
                    "status": "blocked",
                    "detail": str(exc),
                }
            )
            continue
        missing = [token for token in assertion["contains"] if token not in text]
        observations.append(
            {
                "id": f"source:{assertion['path']}",
                "status": "match" if not missing else "mismatch",
                "missing_tokens": missing,
            }
        )
    return observations


def _calibration_identity_observations(
    schema: dict[str, Any],
    contract: dict[str, Any],
    reference: dict[str, Any],
) -> list[dict[str, Any]]:
    official_hash = contract["canonical_schema_sha256"]
    reference_hash = reference["official_canonical_sha256"]
    local_canonical_hash = _sha_json(schema)
    annotation_key = "errorMessage"
    local_projection_hash = _sha_json(_remove_object_key(schema, annotation_key))
    return [
        {
            "id": "official_schema_reference_binding",
            "status": "match" if official_hash == reference_hash else "mismatch",
            "expected": official_hash,
            "observed": reference_hash,
            "source_url": reference["official_source_url"],
            "source_body_sha256": reference["official_source_body_sha256"],
        },
        {
            "id": "official_schema_identity",
            "status": "match" if local_canonical_hash == official_hash else "mismatch",
            "expected": official_hash,
            "observed": local_canonical_hash,
            "detail": (
                "canonical JSON document identity differs; this is not a raw "
                "serialization or key-order comparison"
            ),
        },
        {
            "id": "official_schema_validation_projection",
            "status": (
                "match"
                if local_projection_hash == reference["validation_projection_sha256"]
                else "mismatch"
            ),
            "expected": reference["validation_projection_sha256"],
            "observed": local_projection_hash,
            "projection_rule": reference["validation_projection_rule"],
            "official_error_message_count": reference["official_error_message_count"],
            "local_error_message_count": _count_object_key(schema, annotation_key),
            "detail": (
                "digest-equivalent after removing only errorMessage object members; "
                "Draft7Validator does not use that extension keyword for acceptance"
            ),
        },
    ]


def _calibration_source_lock_observation(
    reference: dict[str, Any], budget: Budget
) -> dict[str, Any]:
    path = reference["source_lock_path"]
    payload = budget.read_repo(path)
    file_hash = _sha_bytes(payload)
    source_lock = _strict_json_bytes(payload, path)
    records = source_lock.get("records") if isinstance(source_lock, dict) else None
    matches = (
        [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("url") == reference["official_source_url"]
        ]
        if isinstance(records, list)
        else []
    )
    observed_body_hash = matches[0].get("sha256") if len(matches) == 1 else None
    expected_file_hash = reference["source_lock_file_sha256"]
    expected_body_hash = reference["official_source_body_sha256"]
    return {
        "id": "official_schema_source_lock",
        "status": (
            "match"
            if file_hash == expected_file_hash
            and observed_body_hash == expected_body_hash
            else "mismatch"
        ),
        "source_lock_path": path,
        "expected_source_lock_file_sha256": expected_file_hash,
        "observed_source_lock_file_sha256": file_hash,
        "expected_source_body_sha256": expected_body_hash,
        "observed_source_body_sha256": observed_body_hash,
        "matching_record_count": len(matches),
    }


def _calibration_observations(
    case: dict[str, Any], record: dict[str, Any], budget: Budget, temporary_root: Path
) -> list[dict[str, Any]]:
    schema_path = "libs/analytics/spatialai-data-utils/spatialai_data_utils/schemas/calibration.json"
    schema = _strict_json_bytes(budget.read_repo(schema_path), schema_path)
    validator = Draft7Validator(schema)
    fixture_names = (
        "calibration-valid.json",
        "calibration-invalid-missing-field.json",
        "calibration-invalid-matrix-shape.json",
    )
    fixture_results: list[dict[str, Any]] = []
    for name in fixture_names:
        relative = (
            f"deploy/docker/thor-local/qualification/static-cases/fixtures/{name}"
        )
        payload = budget.read_repo(relative)
        if any(marker.encode() in payload for marker in EXCLUDED_SAMPLE_MARKERS):
            raise StaticCaseError(
                f"excluded Warehouse sample marker in fixture: {name}"
            )
        owned = temporary_root / name
        owned.write_bytes(payload)
        os.chmod(owned, 0o600)
        document = _strict_json_bytes(owned.read_bytes(), str(owned))
        errors = sorted(
            validator.iter_errors(document), key=lambda error: list(error.path)
        )
        expected_valid = name == "calibration-valid.json"
        fixture_results.append(
            {
                "fixture": name,
                "expected_valid": expected_valid,
                "error_count": len(errors),
                "status": "match" if (not errors) == expected_valid else "mismatch",
            }
        )

    return [
        _calibration_source_lock_observation(case["schema_reference"], budget),
        *_calibration_identity_observations(
            schema, record["contract"], case["schema_reference"]
        ),
        {
            "id": "generated_fixture_matrix",
            "status": "match"
            if all(item["status"] == "match" for item in fixture_results)
            else "mismatch",
            "fixtures": fixture_results,
        },
    ]


def _host_text(budget: Budget, key: str) -> str | None:
    payload = budget.read_host(key)
    return (
        None
        if payload is None
        else payload.decode("utf-8", errors="replace").strip("\x00\n ")
    )


def _platform_observations(
    capability_id: str, record: dict[str, Any], budget: Budget
) -> list[dict[str, Any]]:
    model = _host_text(budget, "model")
    bsp = _host_text(budget, "bsp")
    driver = _host_text(budget, "driver")
    observations: list[dict[str, Any]] = []
    if capability_id == "prereq.platform.validated-gpus":
        normalized = None
        if model:
            if "AGX Thor" in model:
                normalized = "AGX Thor"
            elif "IGX Thor" in model:
                normalized = "IGX Thor"
        observations.append(
            {
                "id": "host_platform",
                "status": "blocked"
                if normalized is None
                else (
                    "match"
                    if normalized in record["contract"]["validated"]
                    else "mismatch"
                ),
                "observed": normalized or "unavailable",
            }
        )
        return observations

    expected_platform = record["contract"].get("host_platform") or record[
        "contract"
    ].get("platform")
    expected_bsp = record["contract"].get("host_bsp") or record["contract"].get(
        "bsp_release"
    )
    expected_driver = record["contract"].get("official_driver") or record[
        "contract"
    ].get("driver")
    normalized_platform = None
    if model:
        if "AGX Thor" in model and "AGX" in expected_platform:
            normalized_platform = expected_platform
        elif "IGX Thor" in model and "IGX" in expected_platform:
            normalized_platform = expected_platform
        else:
            normalized_platform = model
    release_match = re.search(r"R(\d+).*?REVISION:\s*(\d+)(?:\.\d+)?", bsp or "")
    normalized_bsp = (
        f"{release_match.group(1)}.{release_match.group(2)}" if release_match else None
    )
    driver_match = re.search(r"(\d{3}\.\d{2})", driver or "")
    normalized_driver = driver_match.group(1) if driver_match else None
    for name, expected, observed in (
        ("platform", expected_platform, normalized_platform),
        ("bsp", expected_bsp, normalized_bsp),
        ("driver", expected_driver, normalized_driver),
    ):
        observations.append(
            {
                "id": f"host_{name}",
                "status": "blocked"
                if observed is None
                else ("match" if observed == expected else "mismatch"),
                "expected": expected,
                "observed": observed or "unavailable",
            }
        )
    if "official_platform" in record["contract"]:
        official_match = normalized_platform == record["contract"]["official_platform"]
        observations.append(
            {
                "id": "official_host_match_boundary",
                "status": "match"
                if official_match is record["contract"]["official_host_match"]
                else "mismatch",
                "expected": record["contract"]["official_host_match"],
                "observed": official_match,
            }
        )
    return observations


def _kernel_observations(
    record: dict[str, Any], budget: Budget
) -> list[dict[str, Any]]:
    contract = record["contract"]
    mapping = {
        "disable_ipv6": str(int(contract["sysctl"]["disable_ipv6"])),
        "rmem_max": str(contract["sysctl"]["rmem_max"]),
        "wmem_max": str(contract["sysctl"]["wmem_max"]),
        "tcp_rmem": contract["sysctl"]["tcp_rmem"],
        "tcp_wmem": contract["sysctl"]["tcp_wmem"],
    }
    observations: list[dict[str, Any]] = []
    for key, expected in mapping.items():
        observed = _host_text(budget, key)
        normalized = " ".join((observed or "").split()) or None
        observations.append(
            {
                "id": f"sysctl_{key}",
                "status": "blocked"
                if normalized is None
                else ("match" if normalized == expected else "mismatch"),
                "expected": expected,
                "observed": normalized or "unavailable",
            }
        )
    observations.append(
        {
            "id": "thor_runtime_controls",
            "status": "blocked",
            "detail": "current nvpmodel, jetson_clocks, and cache-cleaner state has no bounded file-only collector",
        }
    )
    return observations


def _skills_observations(
    record: dict[str, Any], budget: Budget
) -> list[dict[str, Any]]:
    expected = record["contract"]["skills"]
    observed: list[str] = []
    frontmatter_missing: list[str] = []
    for skill in expected:
        relative = f"skills/{skill}/SKILL.md"
        payload = budget.read_repo(relative)
        text = payload.decode("utf-8")
        observed.append(skill)
        if not text.startswith("---\n") or f"name: {skill}" not in text:
            frontmatter_missing.append(skill)
    return [
        {
            "id": "skill_catalog",
            "status": "match"
            if observed == expected and not frontmatter_missing
            else "mismatch",
            "expected_count": 16,
            "observed_count": len(observed),
            "frontmatter_missing": frontmatter_missing,
        }
    ]


def _derive_outcome(observations: list[dict[str, Any]], disposition: str) -> str:
    statuses = {item.get("status") for item in observations}
    if "blocked" in statuses:
        return "blocked"
    if "mismatch" in statuses:
        return "observed_mismatch"
    if disposition in {"external_boundary", "reference_boundary"}:
        return "not_applicable"
    return "observed_match"


def inspect_case(inventory: dict[str, Any], case_id: str) -> dict[str, Any]:
    cases = [item for item in inventory["cases"] if item["case_id"] == case_id]
    if len(cases) != 1:
        raise StaticCaseError(f"unknown or duplicate static case: {case_id}")
    case = cases[0]
    started_at = _utc_now()
    budget = Budget()
    temporary_path: Path | None = None
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    observations: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="vss-static-case-") as temporary_name:
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, 0o700)
        marker = temporary_path / "ownership.json"
        marker.write_text(
            json.dumps({"case_id": case_id, "owned": True}, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(marker, 0o600)

        record, binding_observation = _binding(case, budget)
        observations.append(binding_observation)
        observations.extend(_source_assertions(case, budget))
        if record is not None:
            adapter = case["adapter"]
            if adapter == "calibration_schema":
                observations.extend(
                    _calibration_observations(case, record, budget, temporary_path)
                )
            elif adapter == "host_platform":
                observations.extend(
                    _platform_observations(case["capability_id"], record, budget)
                )
            elif adapter == "host_kernel":
                observations.extend(_kernel_observations(record, budget))
            elif adapter == "skills_catalog":
                observations.extend(_skills_observations(record, budget))
            elif adapter in {"binding", "source_contract"}:
                observations.append(
                    {
                        "id": "adapter_scope",
                        "status": "match",
                        "detail": "bounded contract/source observation only",
                    }
                )
            else:
                raise StaticCaseError(f"unsupported adapter: {adapter}")

        budget.check_time()
        before = dict(budget.hashes)
        after = budget.rehash()
        if before != after:
            raise StaticCaseError(
                "one or more observed sources changed during inspection"
            )
        if stat.S_IMODE(temporary_path.stat().st_mode) != 0o700:
            raise StaticCaseError("private temporary root mode changed")

    assert temporary_path is not None
    if temporary_path.exists():
        raise StaticCaseError("owned temporary root was not removed")
    finished_at = _utc_now()
    result = {
        "schema_version": 1,
        "case_id": case["case_id"],
        "capability_id": case["capability_id"],
        "integration_state": "candidate_only",
        "executor_ready": False,
        "can_advance_capability": False,
        "evidence_class": "static_observation_not_runtime_evidence",
        "outcome": _derive_outcome(observations, case["disposition"]),
        "started_at": started_at,
        "finished_at": finished_at,
        "bounds": {
            "max_bytes": MAX_BYTES,
            "max_files": MAX_FILES,
            "deadline_seconds": DEADLINE_SECONDS,
            "bytes_read": budget.bytes_read,
            "files_read": budget.files_read,
        },
        "binding": case["binding"],
        "observations": observations,
        "source_hashes_before": before,
        "source_hashes_after": after,
        "ownership": {"temporary_root_private": True, "owned_paths_only": True},
        "cleanup": {"temporary_root_removed": True, "source_hashes_unchanged": True},
    }
    result_schema = _load_package_json(RESULT_SCHEMA_PATH)
    errors = list(Draft202012Validator(result_schema).iter_errors(result))
    if errors:
        raise StaticCaseError(f"result schema validation failed: {errors[0].message}")
    return result


def plan(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "candidate_only_plan",
        "executor_ready": False,
        "can_advance_capability": False,
        "network": "forbidden",
        "docker": "forbidden",
        "warehouse_sample_bundle": "excluded",
        "case_count": len(inventory["cases"]),
        "cases": [
            {
                "case_id": case["case_id"],
                "capability_id": case["capability_id"],
                "adapter": case["adapter"],
                "state": "candidate_only",
            }
            for case in inventory["cases"]
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("validate", help="validate the isolated package")
    subparsers.add_parser("plan", help="print the inert 24-case plan")
    inspect_parser = subparsers.add_parser(
        "inspect", help="run one bounded candidate-only static observation"
    )
    inspect_parser.add_argument("case_id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory = load_and_validate_inventory()
    if args.command in (None, "plan"):
        print(json.dumps(plan(inventory), indent=2, sort_keys=True))
    elif args.command == "validate":
        print(
            "VALID: 24 candidate-only static cases; no live integration, runtime evidence, "
            "network, Docker, lifecycle, or Warehouse sample"
        )
    elif args.command == "inspect":
        print(
            json.dumps(inspect_case(inventory, args.case_id), indent=2, sort_keys=True)
        )
    else:
        raise StaticCaseError(f"unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StaticCaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
