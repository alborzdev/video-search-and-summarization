#!/usr/bin/env python3
"""Deterministic, read-only Wave 3 planning-requirement source checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
CANDIDATE_PATH = REPO_ROOT / "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json"

EXPECTED_BINDINGS = {
    "wave3-source-case.behavior-embedding-downsampling": (
        "systems-behavior-embedding-downsampling",
        "runtime.behavior.embedding-downsampling",
    ),
    "wave3-source-case.behavior-broker-sinks": (
        "systems-behavior-sinks",
        "protocol.behavior.broker-sinks",
    ),
    "wave3-source-case.behavior-space-utilization": (
        "systems-space-utilization",
        "runtime.behavior.space-utilization",
    ),
    "wave3-source-case.custom-behavior-sink": (
        "systems-custom-behavior-sink",
        "customization.behavior.sink-extension",
    ),
    "wave3-source-case.behavior-events-incidents": (
        "systems-behavior-events",
        "runtime.behavior.events-incidents",
    ),
    "wave3-source-case.search-upload-content-type": (
        "systems-search-content-type",
        "behavior.search-upload.content-type",
    ),
}


class QualificationError(RuntimeError):
    """An inventory, schema, binding, or source-integrity check failed."""


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
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


def _load_inventory() -> dict[str, Any]:
    inventory = _load(INVENTORY_PATH)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    cases = inventory["cases"]
    case_ids = [case["case_id"] for case in cases]
    requirement_ids = [case["planning_requirement_id"] for case in cases]
    capability_ids = [case["capability_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise QualificationError("duplicate case_id")
    if len(requirement_ids) != len(set(requirement_ids)):
        raise QualificationError("duplicate planning_requirement_id")
    if len(capability_ids) != len(set(capability_ids)):
        raise QualificationError("duplicate capability_id")
    observed_bindings = {
        case["case_id"]: (
            case["planning_requirement_id"],
            case["capability_id"],
        )
        for case in cases
    }
    if observed_bindings != EXPECTED_BINDINGS:
        raise QualificationError("six-case planning binding set drifted")
    for case in cases:
        lock_paths = [lock["path"] for lock in case["source_locks"]]
        if len(lock_paths) != len(set(lock_paths)):
            raise QualificationError(f"duplicate source lock in {case['case_id']}")
        assertion_ids = [item["assertion_id"] for item in case["assertions"]]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise QualificationError(f"duplicate assertion_id in {case['case_id']}")
        for assertion in case["assertions"]:
            if not set(assertion["sources"]) <= set(lock_paths):
                raise QualificationError(
                    f"assertion source is not locked in {case['case_id']}"
                )
    return inventory


def _assert_safe_relative_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe source path: {raw}")
    resolved = (REPO_ROOT / path).resolve()
    resolved.relative_to(REPO_ROOT.resolve())
    return resolved


def _evaluate(assertion: dict[str, Any], texts: dict[str, str]) -> tuple[bool, str]:
    combined = "\n".join(texts[path] for path in assertion["sources"])
    if assertion["adapter"] == "text_contains_all":
        missing = [token for token in assertion["expected"] if token not in combined]
        return not missing, "missing=" + json.dumps(missing, separators=(",", ":"))
    if assertion["adapter"] == "regex_group_equals":
        match = re.search(assertion["pattern"], combined, flags=re.DOTALL)
        observed = None if match is None else match.group(assertion.get("group", 1))
        return observed == assertion["expected"], f"observed={observed!r}"
    raise ValueError(f"unsupported adapter: {assertion['adapter']}")


def build_result() -> dict[str, Any]:
    inventory = _load_inventory()
    acceptance = _load(ACCEPTANCE_PATH)
    candidate = _load(CANDIDATE_PATH)
    requirements = {item["id"]: item for item in acceptance["wave3_contracts"]["planning_requirements"]}
    capabilities = {item["id"]: item for item in candidate["proposed_capabilities"]}
    results: list[dict[str, Any]] = []
    selected_ids = {case["planning_requirement_id"] for case in inventory["cases"]}

    for case in inventory["cases"]:
        requirement = requirements[case["planning_requirement_id"]]
        capability = capabilities[case["capability_id"]]
        binding_checks = {
            "requirement_payload_sha256": canonical_sha256(requirement["payload"])
            == case["planning_payload_sha256"],
            "capability_sha256": canonical_sha256(capability) == case["capability_sha256"],
            "contract_sha256": canonical_sha256(capability["contract"]) == case["contract_sha256"],
            "owner_binding": requirement["owner_id"] == case["capability_id"],
            "requirement_still_open": requirement["materialized"] is False
            and requirement["executor_ready"] is False
            and requirement["runtime_evidence"] == [],
        }
        texts: dict[str, str] = {}
        source_checks: list[dict[str, Any]] = []
        for lock in case["source_locks"]:
            path = _assert_safe_relative_path(lock["path"])
            digest = file_sha256(path)
            source_checks.append({"path": lock["path"], "sha256_match": digest == lock["sha256"]})
            texts[lock["path"]] = path.read_text(encoding="utf-8")

        assertion_results = []
        for assertion in case["assertions"]:
            passed, detail = _evaluate(assertion, texts)
            assertion_results.append(
                {"assertion_id": assertion["assertion_id"], "passed": passed, "detail": detail}
            )
        passed = (
            all(binding_checks.values())
            and all(item["sha256_match"] for item in source_checks)
            and all(item["passed"] for item in assertion_results)
        )
        results.append(
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "outcome": "observed_match" if passed else "observed_mismatch",
                "binding_checks": binding_checks,
                "source_checks": source_checks,
                "assertions": assertion_results,
                "runtime_evidence": [],
            }
        )

    open_requirements = [
        item
        for item in acceptance["wave3_contracts"]["planning_requirements"]
        if item["materialized"] is False
    ]
    existing_static_ids = {
        "calibration-schema-static",
        "warehouse-static-dry-run",
        "simulation-external-boundary",
    }
    audit = []
    for requirement in open_requirements:
        requirement_id = requirement["id"]
        if requirement_id in selected_ids:
            classification = "selected_source_executor"
        elif requirement_id in existing_static_ids:
            classification = "existing_static_or_external_boundary_lane_not_new"
        elif requirement["package"] == "calibration-warehouse":
            classification = "requires_custom_media_and_runtime_qualification"
        elif requirement["package"] == "agent-smartcity":
            classification = "requires_unmaterialized_fixture_or_independent_source_evidence"
        else:
            classification = "requires_runtime_or_complete_independent_source_semantics"
        audit.append(
            {
                "planning_requirement_id": requirement_id,
                "package": requirement["package"],
                "classification": classification,
            }
        )

    result = {
        "schema_version": 1,
        "scope": "isolated_candidate_only",
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "inventory_sha256": file_sha256(INVENTORY_PATH),
        "counts": {
            "cases": len(results),
            "observed_match": sum(item["outcome"] == "observed_match" for item in results),
            "observed_mismatch": sum(item["outcome"] == "observed_mismatch" for item in results),
            "open_requirements_audited": len(audit),
            "open_requirements_unselected": len(audit) - len(results),
        },
        "open_requirement_audit": audit,
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit the deterministic candidate result")
    args = parser.parse_args()
    result = build_result()
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    # A source/contract mismatch is a first-class audit result, not an executor
    # failure. Structural errors and unsafe paths still raise and exit nonzero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
