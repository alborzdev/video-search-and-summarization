#!/usr/bin/env python3
"""Deterministic, read-only Wave 7 static source qualification."""

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
    "d670829d85239bfb924737d32565eb3b87a0378df2520d225df72a75617122d9"
)
EXPECTED_INVENTORY_SCHEMA_SHA256 = (
    "dea47f9c4b5a3e6e610fa7105a6eca3ad5fe68ded53e38211fad0031f824e63a"
)
EXPECTED_RESULT_SCHEMA_SHA256 = (
    "ad05e722a829655b3f661c2538cd86f57dfbbe3319db0c742b91662df6cb3990"
)
ACCEPTANCE_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
CAPABILITY_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json"
)
ORACLE_PATH = REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json"
PRIOR_INVENTORY_PATHS = tuple(
    REPO_ROOT / path
    for path in (
        "deploy/docker/thor-local/qualification/executor-cases/inventory.json",
        "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave4/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave6/inventory.json",
    )
)
EXPECTED_BASELINE_PATHS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "deploy/docker/thor-local/parity/capability-oracles.json",
    *(str(path.relative_to(REPO_ROOT)) for path in PRIOR_INVENTORY_PATHS),
}
EXPECTED_CASES = {
    "wave7-source-case.ui-negative-oracle": (
        "ui-negative-oracle",
        "behavior.ui.known-issues",
        "static_negative_contract_preserved",
    ),
    "wave7-source-case.nemoclaw-env-matrix": (
        "nemoclaw-env-matrix",
        "configuration.nemoclaw.model-surface-boundary",
        "static_configuration_subset_only",
    ),
    "wave7-source-case.nemoclaw-recovery-oracle": (
        "nemoclaw-recovery-oracle",
        "behavior.nemoclaw.recovery-and-destructive-boundaries",
        "static_negative_contract_preserved",
    ),
    "wave7-source-case.agent-known-issues-oracle": (
        "agent-known-issues-oracle",
        "behavior.agent.known-issues",
        "static_negative_contract_preserved",
    ),
    "wave7-source-case.systems-nvstreamer-sync": (
        "systems-nvstreamer-sync",
        "configuration.nvstreamer.sync",
        "static_configuration_subset_only",
    ),
    "wave7-source-case.systems-nvschema-json": (
        "systems-nvschema-json",
        "protocol.nvschema.json-frame",
        "static_protocol_subset_only",
    ),
}
EXPECTED_PRIOR_SHA256 = (
    "d1eca2fd7439a268708ca39cb27e224fbcbbd644b145088030d72ec9c81a08a9"
)
EXPECTED_REMAINING_SHA256 = (
    "88ec60aa61ee86e93e9ee239c008e336c2e7cafbea3940e18e778580542485c6"
)
EXPECTED_SELECTED_SHA256 = (
    "9a3b857dfaff5ac163634dc123dec40967a0a04e63b70c7fb39b546e009a8c03"
)
EXPECTED_AFTER_SHA256 = (
    "154acf12f0b82772df8c54cefe7fa8721ab387163bd7304df33c628bd162c4ac"
)


class QualificationError(RuntimeError):
    """An identity, binding, schema, or source check failed."""


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
        if path.stat().st_size > 5_000_000:
            raise QualificationError(f"JSON input exceeds size limit: {path}")
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except QualificationError:
        raise
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
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError(f"symlinked repository path: {raw}")
    resolved = (REPO_ROOT / path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
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
    for path, expected, label in (
        (INVENTORY_PATH, EXPECTED_INVENTORY_SHA256, "inventory"),
        (INVENTORY_SCHEMA_PATH, EXPECTED_INVENTORY_SCHEMA_SHA256, "inventory schema"),
        (RESULT_SCHEMA_PATH, EXPECTED_RESULT_SCHEMA_SHA256, "result schema"),
    ):
        if file_sha256(path) != expected:
            raise QualificationError(f"Wave 7 {label} identity drifted")
    inventory = _load(INVENTORY_PATH)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    _assert_unique(inventory["baseline_locks"], "path", "baseline lock path")
    if {
        item["path"] for item in inventory["baseline_locks"]
    } != EXPECTED_BASELINE_PATHS:
        raise QualificationError("nine-file Wave 7 baseline lock set drifted")
    cases = inventory["cases"]
    for key in ("case_id", "planning_requirement_id", "capability_id"):
        _assert_unique(cases, key, key)
    if {case["case_id"] for case in cases} != set(EXPECTED_CASES):
        raise QualificationError("six-case Wave 7 case set drifted")
    for case in cases:
        binding = (
            case["planning_requirement_id"],
            case["capability_id"],
            case["evidence_class"],
        )
        if binding != EXPECTED_CASES[case["case_id"]]:
            raise QualificationError(f"binding set drift in {case['case_id']}")
        _assert_unique(case["source_locks"], "path", "source lock path")
        _assert_unique(case["assertions"], "assertion_id", "assertion_id")
        locked = {item["path"] for item in case["source_locks"]}
        asserted: set[str] = set()
        for assertion in case["assertions"]:
            sources = set(assertion["sources"])
            if not sources <= locked:
                raise QualificationError(
                    f"assertion source is not locked in {case['case_id']}"
                )
            asserted.update(sources)
        if asserted != locked:
            raise QualificationError(f"unasserted source lock in {case['case_id']}")
        for lock in case["source_locks"]:
            _safe_repo_file(lock["path"])
    return inventory


def _check_locks(locks: list[dict[str, str]], label: str) -> list[dict[str, Any]]:
    checks = [
        {
            "path": lock["path"],
            "sha256_match": file_sha256(_safe_repo_file(lock["path"]))
            == lock["sha256"],
        }
        for lock in locks
    ]
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise QualificationError(f"{label} lock mismatch: {failed}")
    return checks


def _index(
    items: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    _assert_unique(items, key, f"{label} {key}")
    return {item[key]: item for item in items}


def _classification(requirement: dict[str, Any], selected: dict[str, str]) -> str:
    evidence = selected.get(requirement["id"])
    if evidence == "static_negative_contract_preserved":
        return "selected_static_negative_contract"
    if evidence == "static_configuration_subset_only":
        return "selected_static_configuration_subset"
    if evidence == "static_protocol_subset_only":
        return "selected_static_protocol_subset"
    if requirement["package"] == "calibration-warehouse":
        return "requires_custom_media_and_runtime_qualification"
    if requirement["package"] == "agent-smartcity":
        return "requires_fixture_or_independent_source_semantics"
    return "requires_runtime_or_complete_independent_source_semantics"


def build_result() -> dict[str, Any]:
    inventory = _load_inventory()
    baseline_checks = _check_locks(inventory["baseline_locks"], "baseline")
    acceptance = _load(ACCEPTANCE_PATH)
    ledger = _load(CAPABILITY_PATH)
    oracle_doc = _load(ORACLE_PATH)
    all_requirements = acceptance["wave3_contracts"]["planning_requirements"]
    requirements = _index(all_requirements, "id", "planning requirement")
    capabilities = _index(ledger["capabilities"], "id", "capability")
    oracles = _index(oracle_doc["oracles"], "capability_id", "oracle")

    prior_selected: set[str] = set()
    for path in PRIOR_INVENTORY_PATHS:
        prior_ids = [item["planning_requirement_id"] for item in _load(path)["cases"]]
        if len(prior_ids) != len(set(prior_ids)) or prior_selected.intersection(
            prior_ids
        ):
            raise QualificationError("prior planning executor packages overlap")
        prior_selected.update(prior_ids)
    if (
        len(prior_selected) != 50
        or canonical_sha256(sorted(prior_selected)) != EXPECTED_PRIOR_SHA256
    ):
        raise QualificationError("exact 50-case predecessor selection set drifted")
    if not prior_selected <= set(requirements):
        raise QualificationError("prior selection absent from live denominator")
    prior_materialized = {
        item for item in prior_selected if requirements[item]["materialized"] is True
    }
    prior_open = prior_selected - prior_materialized
    if len(prior_materialized) != 26 or len(prior_open) != 24:
        raise QualificationError("prior 50 selection composition drifted")

    live_open = [item for item in all_requirements if item["materialized"] is False]
    if len(all_requirements) != 110 or len(live_open) != 83:
        raise QualificationError("live planning denominator drifted")
    remaining = [item for item in live_open if item["id"] not in prior_selected]
    remaining_ids = {item["id"] for item in remaining}
    if (
        len(remaining_ids) != 59
        or canonical_sha256(sorted(remaining_ids)) != EXPECTED_REMAINING_SHA256
    ):
        raise QualificationError("exact 59-row Wave 6 remainder drifted")
    selected = {
        case["planning_requirement_id"]: case["evidence_class"]
        for case in inventory["cases"]
    }
    if (
        not set(selected) <= remaining_ids
        or canonical_sha256(sorted(selected)) != EXPECTED_SELECTED_SHA256
    ):
        raise QualificationError("Wave 7 selected set drifted")
    after_ids = remaining_ids - set(selected)
    if (
        len(after_ids) != 53
        or canonical_sha256(sorted(after_ids)) != EXPECTED_AFTER_SHA256
    ):
        raise QualificationError("exact 53-row Wave 7 remainder drifted")

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
                "classification": _classification(requirement, selected),
            }
        )

    results = []
    for case in inventory["cases"]:
        requirement = requirements[case["planning_requirement_id"]]
        capability = capabilities[case["capability_id"]]
        oracle = oracles[case["capability_id"]]
        checks = {
            "requirement_payload_sha256": canonical_sha256(requirement["payload"])
            == case["planning_payload_sha256"],
            "capability_sha256": canonical_sha256(capability)
            == case["capability_sha256"],
            "contract_sha256": canonical_sha256(capability["contract"])
            == case["contract_sha256"],
            "oracle_sha256": canonical_sha256(oracle) == case["oracle_sha256"],
            "owner_binding": requirement["owner_id"] == case["capability_id"],
            "requirement_still_open": requirement["materialized"] is False
            and requirement["executor_ready"] is False
            and requirement["runtime_evidence"] == [],
            "oracle_still_open": oracle["current_state"] == "open_unexecuted"
            and oracle["evidence"] == [],
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise QualificationError(
                f"binding lock mismatch in {case['case_id']}: {failed}"
            )
        source_checks = _check_locks(
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
        if not all(item["passed"] for item in assertion_results):
            raise QualificationError(f"source assertion mismatch in {case['case_id']}")
        results.append(
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "outcome": "source_subset_match_candidate_only",
                "evidence_class": case["evidence_class"],
                "binding_checks": checks,
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
        "set_digests": {
            "prior_50": canonical_sha256(sorted(prior_selected)),
            "wave6_remaining_59": canonical_sha256(sorted(remaining_ids)),
            "wave7_selected_6": canonical_sha256(sorted(selected)),
            "wave7_remaining_53": canonical_sha256(sorted(after_ids)),
        },
        "baseline_checks": baseline_checks,
        "counts": {
            "total_planning_requirements": 110,
            "integrated_materialized": 27,
            "live_open": 83,
            "prior_package_selections": 50,
            "prior_materialized_static_bindings": 26,
            "prior_live_open_candidate_selections": 24,
            "remaining_requirements_audited": 59,
            "cases": 6,
            "observed_match": len(results),
            "observed_mismatch": 6 - len(results),
            "negative_contracts_preserved": sum(
                item["evidence_class"] == "static_negative_contract_preserved"
                for item in results
            ),
            "configuration_subsets": sum(
                item["evidence_class"] == "static_configuration_subset_only"
                for item in results
            ),
            "protocol_subsets": sum(
                item["evidence_class"] == "static_protocol_subset_only"
                for item in results
            ),
            "remaining_requirements_unselected": 53,
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
