#!/usr/bin/env python3
"""Build exact non-advancing bindings for the ten static executor cases."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
INVENTORY_PATH = "deploy/docker/thor-local/qualification/executor-cases/inventory.json"
INVENTORY_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/executor-cases/inventory.schema.json"
)
EXECUTOR_PATH = "deploy/docker/thor-local/qualification/executor-cases/executor.py"
RESULT_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/executor-cases/result.schema.json"
)

# These are code-reviewed source locks, not values accepted from the live data
# being validated.  They are updated only when the executor package is reviewed
# as a new integration input.
INVENTORY_RAW_SHA256 = "3bafdeebb363503a416f3dd22d3277c11dfabbe55724b77a45fc7b534c93ed35"
INVENTORY_CANONICAL_SHA256 = (
    "d1b6347d4b7caaf1944a0b2eebf1db81d581fbabfd86407fd660d5f95144e256"
)
INVENTORY_SCHEMA_RAW_SHA256 = (
    "416bd7a2213736a000d2bbb7e72c7be2aea57a652cee8b721ea2d57e8bff117e"
)
EXECUTOR_RAW_SHA256 = "241e85bcd0f7d26b85518a355b34fc6093f74876c247c935199cec05952c5e47"
RESULT_SCHEMA_RAW_SHA256 = (
    "5b0403ee2a50424f0aace18d3e617306a60d196d7ece849acc4ad694e2b53af8"
)

EXPECTED_OUTCOMES = {
    "executor-case.alert-metrics-contract": "observed_match",
    "executor-case.rtvi-input-codec-surface": "observed_match",
    "executor-case.broker-profile-choice": "observed_match",
    "executor-case.nvschema-format-selection": "observed_match",
    "executor-case.nvschema-protobuf-fields": "observed_mismatch",
    "executor-case.elk-stack-config": "observed_match",
    "executor-case.logstash-dual-ingestion": "observed_match",
    "executor-case.vios-effective-upload-limit": "observed_match",
    "executor-case.lvs-custom-model-prompt-surface": "observed_match",
    "executor-case.alert-warmup-default": "observed_mismatch",
}


class LiveContractError(ValueError):
    """The reviewed static executor input or result contract drifted."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


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
    spec = importlib.util.spec_from_file_location("thor_static_live_executor", path)
    if spec is None or spec.loader is None:
        raise LiveContractError("cannot load the reviewed static executor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_bindings(*, execute: bool = True) -> dict[str, dict[str, Any]]:
    """Return one exact live binding per reviewed planning requirement."""
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
    if not isinstance(cases, list) or len(cases) != 10:
        raise LiveContractError("executor case denominator drift")
    if {case.get("case_id") for case in cases} != set(EXPECTED_OUTCOMES):
        raise LiveContractError("executor case identity drift")

    executor = _executor_module() if execute else None
    bindings: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases):
        requirement_id = case["planning_requirement_id"]
        if requirement_id in bindings:
            raise LiveContractError("duplicate planning requirement binding")
        expected_outcome = EXPECTED_OUTCOMES[case["case_id"]]
        if execute:
            result = executor.run_case(inventory, case["case_id"])
            result_errors = list(
                Draft202012Validator(result_schema).iter_errors(result)
            )
            if result_errors:
                raise LiveContractError(
                    f"executor result schema drift: {result_errors[0].message}"
                )
            if (
                result["outcome"] != expected_outcome
                or result["runtime_evidence"] != []
                or result["can_advance_capability"] is not False
                or result["can_mark_passed_current"] is not False
            ):
                raise LiveContractError(
                    f"non-advancing result contract drift: {case['case_id']}"
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
