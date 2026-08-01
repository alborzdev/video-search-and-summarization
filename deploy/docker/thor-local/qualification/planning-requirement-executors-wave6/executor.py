#!/usr/bin/env python3
"""Deterministic, read-only Wave 6 Smart City source-contract checks."""

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
    "bdcaf973fddf291fc35a0d27ae7a7a9414e5d62367c9100fef6d80f39d86fec7"
)
EXPECTED_INVENTORY_SCHEMA_SHA256 = (
    "a138a02b8e14759327c3b8bd1792252fd6ffc227f130df6451d9cc810ff0288f"
)
EXPECTED_RESULT_SCHEMA_SHA256 = (
    "d5f3ed3fe430f9d86b8cf8ef0f1170821da2885d3d3f509d46aa4ea7d68f786c"
)
ACCEPTANCE_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
EXPECTED_ACCEPTANCE_PREDECESSOR_SHA256 = (
    "ce62d87cd705259e7d30e7a7b9987bee20303d1e34bd35f1eb32da7fe97a571f"
)
EXPECTED_ACCEPTANCE_SUCCESSOR_SHA256 = (
    "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5"
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
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/inventory.json",
)

EXPECTED_BASELINE_PATHS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
    "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/inventory.json",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/inventory.json",
}
EXPECTED_CASES = {
    "wave6-source-case.smartcity-version-lock": {
        "binding": (
            "smartcity-version-lock",
            "boundary.smart-city.version-skew",
            "documented_mismatch_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/EVIDENCE.md",
            "deploy/docker/thor-local/parity/evidence/2026-07-31-exact-model-artifact-locks.md",
            "deploy/docker/thor-local/models/artifacts.lock.json",
        },
        "assertions": {
            "three-version-statements",
            "version-lock-rule",
            "artifact-integrity-is-not-runtime-evidence",
        },
    },
    "wave6-source-case.smartcity-prereq-source": {
        "binding": (
            "smartcity-prereq-source",
            "prereq.smart-city.reference-platform",
            "documented_mismatch_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/EVIDENCE.md",
            "README.md",
        },
        "assertions": {
            "exact-x86-reference-platform",
            "official-thor-exclusion",
            "thor-lane-is-custom",
        },
    },
    "wave6-source-case.smartcity-reference-envelope": {
        "binding": (
            "smartcity-reference-envelope",
            "performance.smart-city.reference-stream-envelope",
            "documented_mismatch_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
        },
        "assertions": {
            "exact-reference-table",
            "reference-is-not-thor-pass-criterion",
            "no-thor-envelope",
        },
    },
    "wave6-source-case.smartcity-sdg-config": {
        "binding": (
            "smartcity-sdg-config",
            "tooling.smart-city.synthetic-data-pipeline",
            "external_optional_boundary_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/EVIDENCE.md",
            "deploy/docker/thor-local/parity/evidence/2026-07-31-sdg-thor-offline.md",
        },
        "assertions": {
            "exact-static-sdg-contract",
            "external-not-runtime-dependency",
            "local-tooling-evidence-does-not-imply-smartcity-runtime",
        },
    },
    "wave6-source-case.trafficcamnet-recipe": {
        "binding": (
            "trafficcamnet-recipe",
            "customization.smart-city.trafficcamnet-rtdetr",
            "documented_mismatch_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/EVIDENCE.md",
            "services/rtvi/rt-cv/README.md",
        },
        "assertions": {
            "exact-four-class-training-recipe",
            "local-five-class-runtime-surface-is-distinct",
            "vlm-fine-tuning-remains-forthcoming",
        },
    },
    "wave6-source-case.smartcity-limitations-oracle": {
        "binding": (
            "smartcity-limitations-oracle",
            "behavior.smart-city.known-limitations",
            "documented_mismatch_preserved",
        ),
        "sources": {
            "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
        },
        "assertions": {
            "exact-active-limitations",
            "exact-recovery-boundary",
            "must-not-claim-remediated",
        },
    },
}
EXPECTED_PRIOR_SELECTION_SHA256 = (
    "3a6e3e23bb918167eb2359988416ec84baed1b8402f0b28103c96c28cf93560f"
)
EXPECTED_WAVE5_REMAINING_SHA256 = (
    "69aba6737b9d1815112d7d8d44451d6fdf07d9eefe9b54a89d46850ddc1728b7"
)
EXPECTED_SELECTED_SHA256 = (
    "ebed5e3724ad9935e7068974e51b3c7fcdd0506e78e10077a95afc5752d6fcc8"
)
EXPECTED_AFTER_WAVE6_SHA256 = (
    "88ec60aa61ee86e93e9ee239c008e336c2e7cafbea3940e18e778580542485c6"
)
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


def _safe_repo_file(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {raw}")
    root = REPO_ROOT.resolve()
    unresolved = REPO_ROOT / path
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError(f"symlinked repository path: {raw}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"repository path escapes root: {raw}") from exc
    if not resolved.is_file():
        raise QualificationError(f"repository source is not a regular file: {raw}")
    return resolved


def _assert_unique(items: list[dict[str, Any]], key: str, label: str) -> None:
    values = [item[key] for item in items]
    if len(values) != len(set(values)):
        raise QualificationError(f"duplicate {label}")


def _load_inventory() -> dict[str, Any]:
    if file_sha256(INVENTORY_PATH) != EXPECTED_INVENTORY_SHA256:
        raise QualificationError("Wave 6 inventory identity drifted")
    if file_sha256(INVENTORY_SCHEMA_PATH) != EXPECTED_INVENTORY_SCHEMA_SHA256:
        raise QualificationError("Wave 6 inventory schema identity drifted")
    if file_sha256(RESULT_SCHEMA_PATH) != EXPECTED_RESULT_SCHEMA_SHA256:
        raise QualificationError("Wave 6 result schema identity drifted")
    inventory = _load(INVENTORY_PATH)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    _assert_unique(inventory["baseline_locks"], "path", "baseline lock path")
    if {
        item["path"] for item in inventory["baseline_locks"]
    } != EXPECTED_BASELINE_PATHS:
        raise QualificationError("seven-file Wave 6 baseline lock set drifted")
    cases = inventory["cases"]
    _assert_unique(cases, "case_id", "case_id")
    _assert_unique(cases, "planning_requirement_id", "planning_requirement_id")
    _assert_unique(cases, "capability_id", "capability_id")
    if set(EXPECTED_CASES) != {case["case_id"] for case in cases}:
        raise QualificationError("six-case Wave 6 case set drifted")
    for case in cases:
        expected = EXPECTED_CASES[case["case_id"]]
        observed_binding = (
            case["planning_requirement_id"],
            case["capability_id"],
            case["boundary_status"],
        )
        if observed_binding != expected["binding"]:
            raise QualificationError(f"binding set drift in {case['case_id']}")
        _assert_unique(case["source_locks"], "path", "source lock path")
        _assert_unique(case["assertions"], "assertion_id", "assertion_id")
        locked = {item["path"] for item in case["source_locks"]}
        if locked != expected["sources"]:
            raise QualificationError(f"source set drift in {case['case_id']}")
        assertion_ids = {item["assertion_id"] for item in case["assertions"]}
        if assertion_ids != expected["assertions"]:
            raise QualificationError(f"assertion set drift in {case['case_id']}")
        for assertion in case["assertions"]:
            if assertion["adapter"] != "text_contains_all":
                raise QualificationError(
                    f"unsupported assertion adapter in {case['case_id']}"
                )
            if not set(assertion["sources"]) <= locked:
                raise QualificationError(
                    f"assertion source is not locked in {case['case_id']}"
                )
        for lock in case["source_locks"]:
            _safe_repo_file(lock["path"])
    return inventory


def _check_file_locks(locks: list[dict[str, str]], label: str) -> list[dict[str, Any]]:
    checks = []
    for lock in locks:
        path = _safe_repo_file(lock["path"])
        actual_sha256 = file_sha256(path)
        matches = actual_sha256 == lock["sha256"]
        if path == ACCEPTANCE_PATH.resolve():
            matches = (
                lock["sha256"] == EXPECTED_ACCEPTANCE_PREDECESSOR_SHA256
                and actual_sha256 == EXPECTED_ACCEPTANCE_SUCCESSOR_SHA256
            )
        checks.append({"path": lock["path"], "sha256_match": matches})
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise QualificationError(f"{label} lock mismatch: {failed}")
    return checks


def _index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    _assert_unique(items, "id", f"{label} id")
    return {item["id"]: item for item in items}


def _classification(requirement: dict[str, Any], selected: set[str]) -> str:
    if requirement["id"] in selected:
        return "selected_source_contract"
    if requirement["id"] in EXISTING_STATIC_IDS:
        return "existing_static_or_external_boundary_lane_not_new"
    if requirement["package"] == "calibration-warehouse":
        return "requires_custom_media_and_runtime_qualification"
    if requirement["package"] == "agent-smartcity":
        return "requires_fixture_or_independent_source_semantics"
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
    if (
        len(prior_selected) != 44
        or canonical_sha256(sorted(prior_selected)) != EXPECTED_PRIOR_SELECTION_SHA256
    ):
        raise QualificationError("exact 44-case predecessor selection set drifted")
    if not prior_selected <= set(requirements):
        raise QualificationError("prior selection is absent from the live denominator")
    prior_materialized = {
        requirement_id
        for requirement_id in prior_selected
        if requirements[requirement_id]["materialized"] is True
    }
    prior_live_open = {
        requirement_id
        for requirement_id in prior_selected
        if requirements[requirement_id]["materialized"] is False
    }
    if (
        len(prior_materialized) != 26
        or len(prior_live_open) != 18
        or prior_materialized | prior_live_open != prior_selected
    ):
        raise QualificationError("prior 44 selection composition drifted")

    live_open = [item for item in all_requirements if item["materialized"] is False]
    materialized = [item for item in all_requirements if item["materialized"] is True]
    if len(all_requirements) != 110 or len(materialized) != 27 or len(live_open) != 83:
        raise QualificationError("live planning denominator drifted")
    remaining = [item for item in live_open if item["id"] not in prior_selected]
    remaining_ids = {item["id"] for item in remaining}
    if (
        len(remaining) != 65
        or canonical_sha256(sorted(remaining_ids)) != EXPECTED_WAVE5_REMAINING_SHA256
    ):
        raise QualificationError("exact 65-row Wave 5 remainder drifted")
    selected_ids = {case["planning_requirement_id"] for case in inventory["cases"]}
    if (
        not selected_ids <= remaining_ids
        or canonical_sha256(sorted(selected_ids)) != EXPECTED_SELECTED_SHA256
    ):
        raise QualificationError(
            "Wave 6 selected set is not the reviewed six-row subset"
        )
    after_ids = remaining_ids - selected_ids
    if (
        len(after_ids) != 59
        or canonical_sha256(sorted(after_ids)) != EXPECTED_AFTER_WAVE6_SHA256
    ):
        raise QualificationError("exact 59-row Wave 6 remainder drifted")

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
            lock["path"]: _safe_repo_file(lock["path"]).read_text(encoding="utf-8")
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
        if not matched:
            failed_assertions = [
                item["assertion_id"] for item in assertion_results if not item["passed"]
            ]
            raise QualificationError(
                f"source assertion mismatch in {case['case_id']}: {failed_assertions}"
            )
        results.append(
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "outcome": "observed_match" if matched else "observed_mismatch",
                "boundary_status": case["boundary_status"],
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
        "set_digests": {
            "prior_44": canonical_sha256(sorted(prior_selected)),
            "wave5_remaining_65": canonical_sha256(sorted(remaining_ids)),
            "wave6_selected_6": canonical_sha256(sorted(selected_ids)),
            "wave6_remaining_59": canonical_sha256(sorted(after_ids)),
        },
        "baseline_checks": baseline_checks,
        "counts": {
            "total_planning_requirements": 110,
            "integrated_materialized": 27,
            "live_open": 83,
            "prior_package_selections": 44,
            "prior_materialized_static_bindings": 26,
            "prior_live_open_candidate_selections": 18,
            "remaining_requirements_audited": 65,
            "cases": 6,
            "observed_match": matches,
            "observed_mismatch": 6 - matches,
            "documented_mismatches_preserved": sum(
                item["boundary_status"] == "documented_mismatch_preserved"
                for item in results
            ),
            "external_optional_boundaries_preserved": sum(
                item["boundary_status"] == "external_optional_boundary_preserved"
                for item in results
            ),
            "remaining_requirements_unselected": 59,
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
