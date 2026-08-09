#!/usr/bin/env python3
"""Deterministic, read-only Wave 4 planning-requirement source checks."""

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
ACCEPTANCE_PATH = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
EXPECTED_ACCEPTANCE_PREDECESSOR_SHA256 = (
    "ce62d87cd705259e7d30e7a7b9987bee20303d1e34bd35f1eb32da7fe97a571f"
)
EXPECTED_ACCEPTANCE_REQUIREMENTS_SHA256 = (
    "c0c7dca1bbbf5ec8e0c77799e3769b41e5a284c7030688c6ea525ec9b027fb8a"
)
EXPECTED_ALERT_README_PREDECESSOR_SHA256 = (
    "6635f452ae16057166e6d12fe7e91607f4c82f66565c81e2308cd08d7ed42ab9"
)
EXPECTED_ALERT_README_SUCCESSOR_SHA256 = (
    "47a754d86a96094afc79ddeacba3ff80f295b07d98d48871b6ef1ee8e9f6882d"
)
EXPECTED_ALERT_CONFIG_PREDECESSOR_SHA256 = (
    "846e1a71aaf9765b55e20ba36a7d0da0e208a08037c1a6d78d8d675d9d6550b3"
)
EXPECTED_ALERT_CONFIG_SUCCESSOR_SHA256 = (
    "46d131768244706deda72b30fb394d6aedf2d91f73a0e74ab9a0dab0e6d1784b"
)
CANDIDATE_PATH = REPO_ROOT / "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json"
PRIOR_INVENTORY_PATHS = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
    REPO_ROOT / "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
    REPO_ROOT / "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
)

EXPECTED_BINDINGS = {
    "wave4-source-case.alert-vlm-backends": (
        "systems-alert-vlm-backends",
        "model.alerts.vlm-backends",
    ),
    "wave4-source-case.alert-nvschema-ingestion": (
        "systems-alert-nvschema",
        "protocol.alerts.nvschema-ingestion",
    ),
    "wave4-source-case.behavior-dynamic-calibration": (
        "systems-behavior-calibration",
        "calibration.behavior.dynamic",
    ),
    "wave4-source-case.rt-cv-model-pipelines": (
        "systems-rt-cv-model-pipelines",
        "runtime.rt-cv.model-pipelines",
    ),
    "wave4-source-case.bridge-firewall-boundary": (
        "systems-bridge-firewall",
        "deployment.network.bridge-firewall",
    ),
    "wave4-source-case.docker-ngc-29-5-boundary": (
        "systems-docker-ngc-29-5",
        "behavior.docker.ngc-pull-29-5",
    ),
}

EXPECTED_BASELINE_PATHS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json",
    "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
    "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
}

EXISTING_STATIC_IDS = {
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
    inventory = _load(INVENTORY_PATH)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")

    baseline_locks = inventory["baseline_locks"]
    _assert_unique(baseline_locks, "path", "baseline lock path")
    if {item["path"] for item in baseline_locks} != EXPECTED_BASELINE_PATHS:
        raise QualificationError("five-file Wave 4 baseline lock set drifted")

    cases = inventory["cases"]
    _assert_unique(cases, "case_id", "case_id")
    _assert_unique(cases, "planning_requirement_id", "planning_requirement_id")
    _assert_unique(cases, "capability_id", "capability_id")
    observed_bindings = {
        case["case_id"]: (
            case["planning_requirement_id"],
            case["capability_id"],
        )
        for case in cases
    }
    if observed_bindings != EXPECTED_BINDINGS:
        raise QualificationError("six-case Wave 4 planning binding set drifted")

    for case in cases:
        _assert_unique(case["source_locks"], "path", f"source lock in {case['case_id']}")
        _assert_unique(case["assertions"], "assertion_id", f"assertion_id in {case['case_id']}")
        locked_paths = {item["path"] for item in case["source_locks"]}
        for assertion in case["assertions"]:
            if not set(assertion["sources"]) <= locked_paths:
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
        actual_sha256 = file_sha256(path) if path.is_file() else None
        matches = actual_sha256 == lock["sha256"]
        if path == ACCEPTANCE_PATH.resolve():
            matches = (
                lock["sha256"] == EXPECTED_ACCEPTANCE_PREDECESSOR_SHA256
                and canonical_sha256(
                    _load(ACCEPTANCE_PATH)["wave3_contracts"]["planning_requirements"]
                )
                == EXPECTED_ACCEPTANCE_REQUIREMENTS_SHA256
            )
        if lock["path"] == "services/alert/README.md":
            matches = (
                lock["sha256"] == EXPECTED_ALERT_README_PREDECESSOR_SHA256
                and actual_sha256 == EXPECTED_ALERT_README_SUCCESSOR_SHA256
            )
        if lock["path"] == "services/alert/config.yaml":
            matches = (
                lock["sha256"] == EXPECTED_ALERT_CONFIG_PREDECESSOR_SHA256
                and actual_sha256 == EXPECTED_ALERT_CONFIG_SUCCESSOR_SHA256
            )
        checks.append({"path": lock["path"], "sha256_match": matches})
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise QualificationError(f"{label} lock mismatch: {failed}")
    return checks


def _unique_index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    _assert_unique(items, "id", f"{label} id")
    return {item["id"]: item for item in items}


def _classify_requirement(
    requirement: dict[str, Any], selected_ids: set[str]
) -> str:
    requirement_id = requirement["id"]
    if requirement_id in selected_ids:
        return "selected_source_executor"
    if requirement_id in EXISTING_STATIC_IDS:
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
    candidate = _load(CANDIDATE_PATH)
    all_requirements = acceptance["wave3_contracts"]["planning_requirements"]
    requirements = _unique_index(all_requirements, "planning requirement")
    capabilities = _unique_index(candidate["proposed_capabilities"], "capability")

    prior_selected: set[str] = set()
    for path in PRIOR_INVENTORY_PATHS:
        prior = _load(path)
        prior_ids = [item["planning_requirement_id"] for item in prior["cases"]]
        if len(prior_ids) != len(set(prior_ids)):
            raise QualificationError(f"duplicate prior planning binding in {path}")
        if prior_selected.intersection(prior_ids):
            raise QualificationError("prior planning executor packages overlap")
        prior_selected.update(prior_ids)
    if len(prior_selected) != 32:
        raise QualificationError("prior planning case denominator is not 32")

    remaining = [
        item
        for item in all_requirements
        if item["materialized"] is False and item["id"] not in prior_selected
    ]
    live_open = [item for item in all_requirements if item["materialized"] is False]
    materialized = [item for item in all_requirements if item["materialized"] is True]
    if len(all_requirements) != 110 or len(materialized) != 27 or len(live_open) != 83:
        raise QualificationError("canonical fourth-successor denominator drifted")
    if len(remaining) != 77:
        raise QualificationError("Wave 4 remaining planning denominator is not 77")

    selected_ids = {case["planning_requirement_id"] for case in inventory["cases"]}
    remaining_ids = {item["id"] for item in remaining}
    if not selected_ids <= remaining_ids:
        raise QualificationError("Wave 4 selected requirement is not in the 77-row baseline")

    audit = []
    for requirement in remaining:
        capability = capabilities.get(requirement["owner_id"])
        contract = None if capability is None else capability.get("contract")
        audit.append(
            {
                "planning_requirement_id": requirement["id"],
                "owner_id": requirement["owner_id"],
                "package": requirement["package"],
                "planning_payload_sha256": canonical_sha256(requirement["payload"]),
                "capability_sha256": (
                    None if capability is None else canonical_sha256(capability)
                ),
                "contract_sha256": (
                    None if contract is None else canonical_sha256(contract)
                ),
                "classification": _classify_requirement(requirement, selected_ids),
            }
        )

    results = []
    for case in inventory["cases"]:
        requirement = requirements.get(case["planning_requirement_id"])
        capability = capabilities.get(case["capability_id"])
        if requirement is None or capability is None:
            raise QualificationError(f"missing bound ledger entry for {case['case_id']}")
        binding_checks = {
            "requirement_payload_sha256": canonical_sha256(requirement["payload"])
            == case["planning_payload_sha256"],
            "capability_sha256": canonical_sha256(capability)
            == case["capability_sha256"],
            "contract_sha256": canonical_sha256(capability.get("contract"))
            == case["contract_sha256"],
            "owner_binding": requirement["owner_id"] == case["capability_id"],
            "requirement_still_open": requirement["materialized"] is False
            and requirement["executor_ready"] is False
            and requirement["runtime_evidence"] == [],
        }
        failed_bindings = [key for key, passed in binding_checks.items() if not passed]
        if failed_bindings:
            raise QualificationError(
                f"binding lock mismatch in {case['case_id']}: {failed_bindings}"
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
            missing = [token for token in assertion["expected"] if token not in combined]
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

    result = {
        "schema_version": 1,
        "scope": "isolated_candidate_only",
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "inventory_sha256": file_sha256(INVENTORY_PATH),
        "baseline_checks": baseline_checks,
        "counts": {
            "total_planning_requirements": len(all_requirements),
            "integrated_materialized": len(materialized),
            "live_open": len(live_open),
            "cases": len(results),
            "observed_match": sum(
                item["outcome"] == "observed_match" for item in results
            ),
            "observed_mismatch": sum(
                item["outcome"] == "observed_mismatch" for item in results
            ),
            "remaining_requirements_audited": len(audit),
            "remaining_requirements_unselected": len(audit) - len(results),
        },
        "remaining_requirement_audit": audit,
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json", action="store_true", help="emit the deterministic candidate result"
    )
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
