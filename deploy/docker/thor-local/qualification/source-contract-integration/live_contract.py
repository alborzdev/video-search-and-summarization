#!/usr/bin/env python3
"""Build exact bindings for the sixteen source-contract static cases.

Execution is always performed against a reconstructed predecessor state.  The
checked-in assertion sources are copied into a temporary repository and the
reviewed executor is redirected there for the duration of the run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
INVENTORY_PATH = (
    "deploy/docker/thor-local/qualification/source-contract-cases/inventory.json"
)
INVENTORY_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/source-contract-cases/"
    "inventory.schema.json"
)
EXECUTOR_PATH = (
    "deploy/docker/thor-local/qualification/source-contract-cases/executor.py"
)
RESULT_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/source-contract-cases/result.schema.json"
)
ACCEPTANCE_PATH = (
    "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
LEDGER_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"

INVENTORY_RAW_SHA256 = "e691a02128e60d3817474c9d19e0cda69da8cb238c86496fe2df1f658b25d079"
INVENTORY_CANONICAL_SHA256 = (
    "7c9d65fee42f0f6089ec705972ae900a001ab68eaafad23d3c983425b305fe7f"
)
INVENTORY_SCHEMA_RAW_SHA256 = (
    "8cf3261a8785d376af2d9bd1b9b5a4216e06f5408cb724af0db485ad2091f81f"
)
EXECUTOR_RAW_SHA256 = "f50fd59a9339a7a7bb35d74ce37bb15193dd7cbe8067b670043799d2d139811e"
RESULT_SCHEMA_RAW_SHA256 = (
    "ed542c6c39a2bcf9e754cada2d6b7d4114019dbeaa3a14789f907ca3c6d4fcd0"
)

EXPECTED_OUTCOMES = {
    "source-contract-case.performance-alert-verification": "observed_match",
    "source-contract-case.performance-lvs": "observed_match",
    "source-contract-case.performance-search": "observed_match",
    "source-contract-case.performance-rt-cv": "observed_match",
    "source-contract-case.performance-rt-vlm": "observed_match",
    "source-contract-case.performance-rt-embed": "observed_match",
    "source-contract-case.performance-vios": "observed_match",
    "source-contract-case.alert-parser": "observed_match",
    "source-contract-case.behavior-dynamic-config": "observed_match",
    "source-contract-case.rt-cv-compose": "observed_match",
    "source-contract-case.va-bootstrap": "observed_match",
    "source-contract-case.elk-indices": "observed_match",
    "source-contract-case.observability-stack": "observed_match",
    "source-contract-case.release-tags": "observed_match",
    "source-contract-case.nvstreamer-full-config": "observed_mismatch",
    "source-contract-case.vios-modules": "observed_match",
}


class LiveContractError(ValueError):
    """The reviewed input, predecessor state, or result contract drifted."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_load(relative: str) -> dict[str, Any]:
    path = REPO_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise LiveContractError(f"reviewed input is not a regular file: {relative}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LiveContractError(f"duplicate JSON key in {relative}: {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveContractError(f"invalid reviewed JSON: {relative}") from exc
    if not isinstance(value, dict):
        raise LiveContractError(f"reviewed JSON root is not an object: {relative}")
    return value


def _locked_path(relative: str, expected_sha256: str) -> Path:
    path = REPO_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise LiveContractError(f"reviewed input is not a regular file: {relative}")
    if raw_sha256(path) != expected_sha256:
        raise LiveContractError(f"reviewed input digest drift: {relative}")
    return path


def _executor_module() -> Any:
    path = _locked_path(EXECUTOR_PATH, EXECUTOR_RAW_SHA256)
    spec = importlib.util.spec_from_file_location(
        "source_contract_successor_executor", path
    )
    if spec is None or spec.loader is None:
        raise LiveContractError("cannot load the reviewed source-contract executor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_staged(root: Path, relative: str, payload: bytes) -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)


def _execute_predecessor(
    executor: Any,
    inventory: dict[str, Any],
    acceptance: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Execute all cases with the ten-case predecessor as their live view."""
    results: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="vss-source-contract-predecessor-") as name:
        root = Path(name)
        _write_staged(root, ACCEPTANCE_PATH, encoded(acceptance))
        _write_staged(root, LEDGER_PATH, encoded(ledger))
        source_locks: dict[str, str] = {}
        for case in inventory["cases"]:
            for source in case["source_locks"]:
                previous = source_locks.setdefault(source["path"], source["sha256"])
                if previous != source["sha256"]:
                    raise LiveContractError("inconsistent duplicate assertion source lock")
        for relative, expected in source_locks.items():
            source = REPO_ROOT / relative
            if source.is_symlink() or not source.is_file():
                raise LiveContractError(f"assertion source is unavailable: {relative}")
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != expected:
                raise LiveContractError(f"assertion source digest drift: {relative}")
            _write_staged(root, relative, payload)

        original_root = executor.REPO_ROOT
        executor.REPO_ROOT = root
        try:
            for case in inventory["cases"]:
                results[case["case_id"]] = executor.run_case(
                    inventory, case["case_id"]
                )
        finally:
            executor.REPO_ROOT = original_root
    return results


def build_bindings(
    predecessor_acceptance: dict[str, Any],
    predecessor_ledger: dict[str, Any],
    *,
    execute: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return one exact successor binding per reviewed planning requirement."""
    inventory_path = _locked_path(INVENTORY_PATH, INVENTORY_RAW_SHA256)
    _locked_path(INVENTORY_SCHEMA_PATH, INVENTORY_SCHEMA_RAW_SHA256)
    _locked_path(RESULT_SCHEMA_PATH, RESULT_SCHEMA_RAW_SHA256)
    inventory = _strict_load(INVENTORY_PATH)
    inventory_schema = _strict_load(INVENTORY_SCHEMA_PATH)
    result_schema = _strict_load(RESULT_SCHEMA_PATH)
    errors = list(Draft202012Validator(inventory_schema).iter_errors(inventory))
    if errors:
        raise LiveContractError(f"executor inventory schema drift: {errors[0].message}")
    if canonical_sha256(inventory) != INVENTORY_CANONICAL_SHA256:
        raise LiveContractError("executor inventory canonical digest drift")
    cases = inventory.get("cases")
    if not isinstance(cases, list) or len(cases) != 16:
        raise LiveContractError("executor case denominator drift")
    if {case.get("case_id") for case in cases} != set(EXPECTED_OUTCOMES):
        raise LiveContractError("executor case identity drift")

    results = (
        _execute_predecessor(
            _executor_module(), inventory, predecessor_acceptance, predecessor_ledger
        )
        if execute
        else {}
    )
    bindings: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases):
        requirement_id = case["planning_requirement_id"]
        if requirement_id in bindings:
            raise LiveContractError("duplicate planning requirement binding")
        expected_outcome = EXPECTED_OUTCOMES[case["case_id"]]
        if execute:
            result = results[case["case_id"]]
            result_errors = list(
                Draft202012Validator(result_schema).iter_errors(result)
            )
            if result_errors:
                raise LiveContractError(
                    f"executor result schema drift: {result_errors[0].message}"
                )
            if (
                result["outcome"] != expected_outcome
                or result["materialization_scope"] != "isolated_candidate_only"
                or result["runtime_evidence"] != []
                or result["can_advance_capability"] is not False
                or result["can_mark_passed_current"] is not False
            ):
                raise LiveContractError(
                    f"non-advancing predecessor result drift: {case['case_id']}"
                )
        bindings[requirement_id] = {
            "materialization": {
                "scope": "live_planning_requirement_static_contract",
                "inventory_path": INVENTORY_PATH,
                "case_json_pointer": f"/cases/{index}",
                "case_canonical_sha256": canonical_sha256(case),
            },
            "executor": {
                "path": EXECUTOR_PATH,
                "raw_sha256": EXECUTOR_RAW_SHA256,
                "inventory_path": INVENTORY_PATH,
                "inventory_raw_sha256": raw_sha256(inventory_path),
                "inventory_canonical_sha256": INVENTORY_CANONICAL_SHA256,
                "inventory_schema_path": INVENTORY_SCHEMA_PATH,
                "inventory_schema_raw_sha256": INVENTORY_SCHEMA_RAW_SHA256,
                "invocation": ["python3", EXECUTOR_PATH, "run", case["case_id"]],
            },
            "case": {
                "case_id": case["case_id"],
                "planning_requirement_id": requirement_id,
                "capability_id": case["capability_id"],
                "planning_payload_sha256": case["planning_payload_sha256"],
            },
            "result": {
                "schema_path": RESULT_SCHEMA_PATH,
                "schema_raw_sha256": RESULT_SCHEMA_RAW_SHA256,
                "expected_outcome": expected_outcome,
                "evidence_class": "deterministic_file_static_evidence_not_runtime",
                "can_advance_capability": False,
                "can_mark_passed_current": False,
                "runtime_evidence": [],
            },
        }
    return bindings
