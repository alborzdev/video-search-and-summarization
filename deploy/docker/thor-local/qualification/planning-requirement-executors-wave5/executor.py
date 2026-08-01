#!/usr/bin/env python3
"""Deterministic, read-only Wave 5 Smart City planning source checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
EXPECTED_INVENTORY_SHA256 = (
    "d10a511c482d80e6167b8ac3a7ed97070d758ea709a4635f3a97526c803ef942"
)
ACCEPTANCE_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
CAPABILITY_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json"
)
PRIOR_INVENTORY_PATHS = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/inventory.json",
)

EXPECTED_BINDINGS = {
    "wave5-source-case.smartcity-compose-surface": (
        "smartcity-compose-surface",
        "deployment.smart-city.bp-smc-surface",
    ),
    "wave5-source-case.smartcity-minimal-map": (
        "smartcity-minimal-map",
        "runtime.smart-city.map-ui",
    ),
    "wave5-source-case.smartcity-behavior-config": (
        "smartcity-behavior-config",
        "configuration.smart-city.behavior-rules",
    ),
    "wave5-source-case.smartcity-verification-config": (
        "smartcity-verification-config",
        "configuration.smart-city.alert-verification",
    ),
    "wave5-source-case.smartcity-custom-location": (
        "smartcity-custom-location",
        "configuration.smart-city.custom-location",
    ),
    "wave5-source-case.maps-secret-presence": (
        "maps-secret-presence",
        "boundary.smart-city.google-maps-dependency",
    ),
}
EXPECTED_BASELINE_PATHS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
    "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/inventory.json",
}
EXISTING_STATIC_IDS = {
    "calibration-schema-static",
    "warehouse-static-dry-run",
    "simulation-external-boundary",
}


class QualificationError(RuntimeError):
    """An inventory, schema, binding, or source-integrity check failed."""


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot load JSON {path}: {exc}") from exc


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _load(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _safe_repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {raw}")
    resolved = (REPO_ROOT / path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise QualificationError(f"repository path escapes root: {raw}") from exc
    return resolved


def _assert_unique(items: list[dict[str, Any]], key: str, label: str) -> None:
    values = [item[key] for item in items]
    if len(values) != len(set(values)):
        raise QualificationError(f"duplicate {label}")


def _load_inventory() -> dict[str, Any]:
    if file_sha256(INVENTORY_PATH) != EXPECTED_INVENTORY_SHA256:
        raise QualificationError("Wave 5 inventory identity drifted")
    inventory = _load(INVENTORY_PATH)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    _assert_unique(inventory["baseline_locks"], "path", "baseline lock path")
    if {
        item["path"] for item in inventory["baseline_locks"]
    } != EXPECTED_BASELINE_PATHS:
        raise QualificationError("six-file Wave 5 baseline lock set drifted")
    cases = inventory["cases"]
    _assert_unique(cases, "case_id", "case_id")
    _assert_unique(cases, "planning_requirement_id", "planning_requirement_id")
    _assert_unique(cases, "capability_id", "capability_id")
    observed = {
        case["case_id"]: (case["planning_requirement_id"], case["capability_id"])
        for case in cases
    }
    if observed != EXPECTED_BINDINGS:
        raise QualificationError("six-case Wave 5 planning binding set drifted")
    for case in cases:
        _assert_unique(
            case["source_locks"], "path", f"source lock in {case['case_id']}"
        )
        _assert_unique(
            case["assertions"], "assertion_id", f"assertion_id in {case['case_id']}"
        )
        locked = {item["path"] for item in case["source_locks"]}
        for assertion in case["assertions"]:
            if not set(assertion["sources"]) <= locked:
                raise QualificationError(
                    f"assertion source is not locked in {case['case_id']}"
                )
        for lock in case["source_locks"]:
            _safe_repo_path(lock["path"])
    return inventory


def _check_file_locks(locks: list[dict[str, str]], label: str) -> list[dict[str, Any]]:
    checks = []
    for lock in locks:
        path = _safe_repo_path(lock["path"])
        checks.append(
            {
                "path": lock["path"],
                "sha256_match": path.is_file() and file_sha256(path) == lock["sha256"],
            }
        )
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise QualificationError(f"{label} lock mismatch: {failed}")
    return checks


def _index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    _assert_unique(items, "id", f"{label} id")
    return {item["id"]: item for item in items}


def _classification(requirement: dict[str, Any], selected: set[str]) -> str:
    if requirement["id"] in selected:
        return "selected_source_executor"
    if requirement["id"] in EXISTING_STATIC_IDS:
        return "existing_static_or_external_boundary_lane_not_new"
    if requirement["package"] == "calibration-warehouse":
        return "requires_custom_media_and_runtime_qualification"
    if requirement["package"] == "agent-smartcity":
        return "requires_unmaterialized_fixture_or_independent_source_evidence"
    return "requires_runtime_or_complete_independent_source_semantics"


def build_result() -> dict[str, Any]:
    inventory = _load_inventory()
    baseline_checks = _check_file_locks(inventory["baseline_locks"], "baseline")
    acceptance = _load(ACCEPTANCE_PATH)
    ledger = _load(CAPABILITY_PATH)
    all_requirements = acceptance["wave3_contracts"]["planning_requirements"]
    requirements = _index(all_requirements, "planning requirement")
    capabilities = _index(ledger["capabilities"], "capability")

    prior_selected: set[str] = set()
    for path in PRIOR_INVENTORY_PATHS:
        prior_ids = [item["planning_requirement_id"] for item in _load(path)["cases"]]
        if len(prior_ids) != len(set(prior_ids)) or prior_selected.intersection(
            prior_ids
        ):
            raise QualificationError("prior planning executor packages overlap")
        prior_selected.update(prior_ids)
    if len(prior_selected) != 38:
        raise QualificationError("prior planning case denominator is not 38")

    live_open = [item for item in all_requirements if item["materialized"] is False]
    if len(all_requirements) != 110 or len(live_open) != 84:
        raise QualificationError("live planning denominator drifted")
    remaining = [item for item in live_open if item["id"] not in prior_selected]
    if len(remaining) != 72:
        raise QualificationError("Wave 5 remaining planning denominator is not 72")
    selected_ids = {case["planning_requirement_id"] for case in inventory["cases"]}
    if not selected_ids <= {item["id"] for item in remaining}:
        raise QualificationError(
            "Wave 5 selected requirement is not in the 72-row baseline"
        )

    audit = []
    for requirement in remaining:
        capability = capabilities.get(requirement["owner_id"])
        audit.append(
            {
                "planning_requirement_id": requirement["id"],
                "owner_id": requirement["owner_id"],
                "package": requirement["package"],
                "planning_payload_sha256": canonical_sha256(requirement["payload"]),
                "capability_sha256": None
                if capability is None
                else canonical_sha256(capability),
                "contract_sha256": None
                if capability is None
                else canonical_sha256(capability["contract"]),
                "classification": _classification(requirement, selected_ids),
            }
        )

    results = []
    for case in inventory["cases"]:
        requirement = requirements[case["planning_requirement_id"]]
        capability = capabilities[case["capability_id"]]
        binding_checks = {
            "requirement_payload_sha256": canonical_sha256(requirement["payload"])
            == case["planning_payload_sha256"],
            "capability_sha256": canonical_sha256(capability)
            == case["capability_sha256"],
            "contract_sha256": canonical_sha256(capability["contract"])
            == case["contract_sha256"],
            "owner_binding": requirement["owner_id"] == case["capability_id"],
            "requirement_still_open": requirement["materialized"] is False
            and requirement["executor_ready"] is False
            and requirement["runtime_evidence"] == [],
        }
        failed = [name for name, passed in binding_checks.items() if not passed]
        if failed:
            raise QualificationError(
                f"binding lock mismatch in {case['case_id']}: {failed}"
            )
        source_checks = _check_file_locks(
            case["source_locks"], f"source for {case['case_id']}"
        )
        texts = {
            lock["path"]: _safe_repo_path(lock["path"]).read_text(encoding="utf-8")
            for lock in case["source_locks"]
        }
        assertion_results = []
        for assertion in case["assertions"]:
            combined = "\n".join(texts[path] for path in assertion["sources"])
            missing = [
                token for token in assertion["expected"] if token not in combined
            ]
            assertion_results.append(
                {
                    "assertion_id": assertion["assertion_id"],
                    "passed": not missing,
                    "detail": "missing="
                    + json.dumps(missing, separators=(",", ":"), ensure_ascii=False),
                }
            )
        matched = all(item["passed"] for item in assertion_results)
        results.append(
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "outcome": "observed_match" if matched else "observed_mismatch",
                "binding_checks": binding_checks,
                "source_checks": source_checks,
                "assertions": assertion_results,
                "runtime_evidence": [],
            }
        )

    matches = sum(item["outcome"] == "observed_match" for item in results)
    result = {
        "schema_version": 1,
        "scope": "isolated_candidate_only",
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "inventory_sha256": file_sha256(INVENTORY_PATH),
        "baseline_checks": baseline_checks,
        "counts": {
            "total_planning_requirements": 110,
            "integrated_materialized": 26,
            "live_open": 84,
            "prior_candidate_selections": 12,
            "remaining_requirements_audited": 72,
            "cases": 6,
            "observed_match": matches,
            "observed_mismatch": 6 - matches,
            "remaining_requirements_unselected": 66,
        },
        "remaining_requirement_audit": audit,
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_result()
    print(
        json.dumps(
            result,
            sort_keys=args.json,
            separators=(",", ":") if args.json else None,
            indent=None if args.json else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
