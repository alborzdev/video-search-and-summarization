#!/usr/bin/env python3
"""Deterministic, fail-closed, read-only Wave 10 static-subset audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
EXPECTED_INVENTORY_SHA256 = (
    "6c5ad14ccc36600a9c2654bd57bd594fe478b689fad78336d45c8ae0a3eab2e0"
)
EXPECTED_INVENTORY_SCHEMA_SHA256 = (
    "1fb22786d33425de0a5cad72be3d83856566af0e60513be697cc019969a64702"
)
EXPECTED_RESULT_SCHEMA_SHA256 = (
    "754d2e217d6580acc3b41414c185e9946f2f7302e730e0089e2916732e363a8c"
)
MAX_BYTES = 5_000_000
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
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave7/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave8/inventory.json",
        "deploy/docker/thor-local/qualification/planning-requirement-executors-wave9/inventory.json",
    )
)
EXPECTED_BASELINE_PATHS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "deploy/docker/thor-local/parity/capability-oracles.json",
    *(str(path.relative_to(REPO_ROOT)) for path in PRIOR_INVENTORY_PATHS),
}
EXPECTED_CASES = {
    "wave10-source-case.agent-mode-routing": (
        "agent-mode-mocks",
        "runtime.agent.operational-modes",
        "static_protocol_subset_only",
    ),
    "wave10-source-case.ui-chat-static-surface": (
        "ui-chat-state",
        "runtime.ui.global-chat-sidebar",
        "static_protocol_subset_only",
    ),
    "wave10-source-case.smartcity-model-lock-gap": (
        "smartcity-model-locks",
        "model.smart-city.perception-options",
        "static_negative_contract_preserved",
    ),
    "wave10-source-case.smartcity-vios-config": (
        "smartcity-vios-boundary",
        "configuration.smart-city.vios-defaults",
        "static_configuration_subset_only",
    ),
    "wave10-source-case.nvstreamer-file-protocol": (
        "systems-nvstreamer-file",
        "runtime.nvstreamer.file-streaming",
        "static_protocol_subset_only",
    ),
    "wave10-source-case.va-library-surface": (
        "systems-va-query-library",
        "runtime.video-analytics.query-and-library-contract",
        "static_protocol_subset_only",
    ),
}
EXPECTED_PRIOR_SHA256 = (
    "843fde32fe7ee9f871451df0387326deff8e90a652b78d704c3d3581001f7d60"
)
EXPECTED_REMAINDER_SHA256 = (
    "5c6885d089e5d5af6e49d6cccb8a03dc829642174bc8f2ec660674d24df10672"
)
EXPECTED_SELECTED_SHA256 = (
    "a1041929edb70ab3d07ab5dd4e08cd64029e5b9365b91a26a3f252678e72cc98"
)
EXPECTED_AFTER_SHA256 = (
    "db6822446d2591213affcfa05d7d1b4f9b94ebc73ecf44c8bdb8265fac7ef33b"
)


class QualificationError(RuntimeError):
    """An identity, schema, binding, source, or boundary check failed."""


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _read_regular(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(f"cannot read {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(f"{label} must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_BYTES:
        raise QualificationError(f"{label} exceeds bounded size")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise QualificationError(f"cannot read {label}") from exc


def file_sha256(path: Path) -> str:
    return hashlib.sha256(_read_regular(path, str(path))).hexdigest()


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _load(path: Path, label: str | None = None) -> Any:
    return _strict_json(_read_regular(path, label or str(path)), label or str(path))


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _load(schema_path, f"{label} schema")
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
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise QualificationError(f"unsafe repository path: {raw}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise QualificationError(f"cannot resolve repository path: {raw}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise QualificationError(f"symlinked repository path: {raw}")
    _read_regular(current, f"repository source {raw}")
    return current


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
            raise QualificationError(f"Wave 10 {label} identity drifted")
    inventory = _load(INVENTORY_PATH, "inventory")
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    if any(inventory["policies"].values()):
        raise QualificationError("inert candidate-only policy drifted")
    _assert_unique(inventory["baseline_locks"], "path", "baseline lock path")
    if {row["path"] for row in inventory["baseline_locks"]} != EXPECTED_BASELINE_PATHS:
        raise QualificationError("twelve-file Wave 10 baseline lock set drifted")
    cases = inventory["cases"]
    for key in ("case_id", "planning_requirement_id", "capability_id"):
        _assert_unique(cases, key, key)
    if {case["case_id"] for case in cases} != set(EXPECTED_CASES):
        raise QualificationError("six-case Wave 10 case set drifted")
    for case in cases:
        binding = (
            case["planning_requirement_id"],
            case["capability_id"],
            case["evidence_class"],
        )
        if binding != EXPECTED_CASES[case["case_id"]]:
            raise QualificationError(f"binding set drift in {case['case_id']}")
        if case["runtime_evidence"] != []:
            raise QualificationError(f"runtime evidence forbidden in {case['case_id']}")
        _assert_unique(case["source_locks"], "path", "source lock path")
        _assert_unique(case["assertions"], "assertion_id", "assertion_id")
        locked = {row["path"] for row in case["source_locks"]}
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
    return inventory


def _check_locks(locks: list[dict[str, str]], label: str) -> list[dict[str, Any]]:
    checks = []
    for lock in locks:
        path = _safe_repo_file(lock["path"])
        checks.append(
            {"path": lock["path"], "sha256_match": file_sha256(path) == lock["sha256"]}
        )
    failed = [row["path"] for row in checks if not row["sha256_match"]]
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
        return "excluded_warehouse_requirement"
    return "requires_runtime_or_external_evidence"


def build_result() -> dict[str, Any]:
    inventory = _load_inventory()
    baseline_checks = _check_locks(inventory["baseline_locks"], "baseline")
    acceptance = _load(ACCEPTANCE_PATH, "live acceptance inventory")
    ledger = _load(CAPABILITY_PATH, "live capability ledger")
    oracle_doc = _load(ORACLE_PATH, "live oracle ledger")
    all_requirements = acceptance["wave3_contracts"]["planning_requirements"]
    requirements = _index(all_requirements, "id", "planning requirement")
    capabilities = _index(ledger["capabilities"], "id", "capability")
    oracles = _index(oracle_doc["oracles"], "capability_id", "oracle")

    prior_selected: set[str] = set()
    for path in PRIOR_INVENTORY_PATHS:
        prior_ids = [row["planning_requirement_id"] for row in _load(path)["cases"]]
        if len(prior_ids) != len(set(prior_ids)) or prior_selected.intersection(
            prior_ids
        ):
            raise QualificationError("prior planning executor packages overlap")
        prior_selected.update(prior_ids)
    if (
        len(prior_selected) != 68
        or canonical_sha256(sorted(prior_selected)) != EXPECTED_PRIOR_SHA256
    ):
        raise QualificationError("exact 68-case predecessor selection set drifted")
    if not prior_selected <= set(requirements):
        raise QualificationError("prior selection absent from live denominator")
    prior_materialized = {
        item for item in prior_selected if requirements[item]["materialized"] is True
    }
    prior_open = prior_selected - prior_materialized
    if len(prior_materialized) != 26 or len(prior_open) != 42:
        raise QualificationError("prior 68 selection composition drifted")

    live_open = [row for row in all_requirements if row["materialized"] is False]
    if len(all_requirements) != 110 or len(live_open) != 84:
        raise QualificationError("live planning denominator drifted")
    if any(
        row["executor_ready"] is not False or row["runtime_evidence"] != []
        for row in live_open
    ):
        raise QualificationError("all 84 live-open requirements must remain unpromoted")
    remainder = [row for row in live_open if row["id"] not in prior_selected]
    remainder_ids = {row["id"] for row in remainder}
    if (
        len(remainder_ids) != 42
        or canonical_sha256(sorted(remainder_ids)) != EXPECTED_REMAINDER_SHA256
    ):
        raise QualificationError("exact Wave 9 remainder42 drifted")
    selected = {
        case["planning_requirement_id"]: case["evidence_class"]
        for case in inventory["cases"]
    }
    if (
        not set(selected) <= remainder_ids
        or canonical_sha256(sorted(selected)) != EXPECTED_SELECTED_SHA256
    ):
        raise QualificationError("Wave 10 selected set drifted")
    if any(
        requirements[item]["package"] == "calibration-warehouse" for item in selected
    ):
        raise QualificationError("Warehouse selection is forbidden")
    after_ids = remainder_ids - set(selected)
    if (
        len(after_ids) != 36
        or canonical_sha256(sorted(after_ids)) != EXPECTED_AFTER_SHA256
    ):
        raise QualificationError("exact Wave 10 remainder-after set drifted")

    audit = []
    for requirement in remainder:
        capability = capabilities.get(requirement["owner_id"])
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
                    None
                    if capability is None
                    else canonical_sha256(capability["contract"])
                ),
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
        if not all(row["passed"] for row in assertion_results):
            raise QualificationError(f"source assertion mismatch in {case['case_id']}")
        results.append(
            {
                "case_id": case["case_id"],
                "planning_requirement_id": case["planning_requirement_id"],
                "capability_id": case["capability_id"],
                "outcome": "static_subset_match_candidate_only",
                "evidence_class": case["evidence_class"],
                "binding_checks": checks,
                "source_checks": source_checks,
                "assertions": assertion_results,
                "runtime_evidence": [],
                "qualification_boundary": (
                    "source/configuration subset only; requirement and oracle remain open"
                ),
            }
        )

    result = {
        "schema_version": 1,
        "scope": "isolated_candidate_only",
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "inventory_sha256": file_sha256(INVENTORY_PATH),
        "set_digests": {
            "prior_68": canonical_sha256(sorted(prior_selected)),
            "wave9_remaining_42": canonical_sha256(sorted(remainder_ids)),
            "wave10_selected_6": canonical_sha256(sorted(selected)),
            "wave10_remaining_36": canonical_sha256(sorted(after_ids)),
        },
        "baseline_checks": baseline_checks,
        "counts": {
            "total_planning_requirements": 110,
            "integrated_materialized": 26,
            "live_open": 84,
            "prior_package_selections": 68,
            "prior_materialized_static_bindings": 26,
            "prior_live_open_candidate_selections": 42,
            "remaining_requirements_audited": 42,
            "cases": 6,
            "observed_match": len(results),
            "observed_mismatch": 6 - len(results),
            "negative_contracts_preserved": sum(
                row["evidence_class"] == "static_negative_contract_preserved"
                for row in results
            ),
            "configuration_subsets": sum(
                row["evidence_class"] == "static_configuration_subset_only"
                for row in results
            ),
            "protocol_subsets": sum(
                row["evidence_class"] == "static_protocol_subset_only"
                for row in results
            ),
            "warehouse_cases_selected": 0,
            "remaining_requirements_unselected": 36,
        },
        "remaining_requirement_audit": audit,
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_result()
    except QualificationError as exc:
        print(f"ERROR: {exc}")
        return 1
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
