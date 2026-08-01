#!/usr/bin/env python3
"""Integrate the sixteen source-contract cases after the immutable ten-case state."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
ACCEPTANCE = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
LEDGER = PARITY / "official-capabilities.json"
MANIFEST = PARITY / "manifest.json"
ORACLES = PARITY / "capability-oracles.json"
ORACLE_SCHEMA = PARITY / "capability-oracles.schema.json"
RECEIPT = LANE / "live-integration-receipt.json"

PREDECESSOR_LANE = REPO_ROOT / "deploy/docker/thor-local/qualification/executor-cases"
PREDECESSOR_INTEGRATOR = PREDECESSOR_LANE / "integrate_live.py"
PREDECESSOR_CONTRACT = PREDECESSOR_LANE / "live_contract.py"
PREDECESSOR_RECEIPT = PREDECESSOR_LANE / "live-integration-receipt.json"
LIVE_CONTRACT = LANE / "live_contract.py"
CAPABILITY_ORACLES = PARITY / "capability_oracles.py"

PREDECESSOR_INTEGRATOR_RAW_SHA256 = (
    "de4f65b147db5dc8ef840cb8a054b05f1fb0713122b5cff2a7f738794b2f328b"
)
PREDECESSOR_CONTRACT_RAW_SHA256 = (
    "891b85bddcb2f49302c13d733acd58a7c85a8b1ea8a3863a64021da0e9528ee0"
)
PREDECESSOR_RECEIPT_RAW_SHA256 = (
    "1548dd1ca0871a24dd0adba231001ee5757e19ddfa6314d4d883656b9e8d432d"
)
PREDECESSOR_RECEIPT_CANONICAL_SHA256 = (
    "ae0d9ac206018b79d84203bfa8af5c574cbb83ca7a7af8cb3a4e17f82898aaa0"
)
PREDECESSOR_CONTRACT_SHA256 = (
    "2eb1812f8854ef0f03334f68ceadcda64ffbfd166422da253f48c52ec8cdab71"
)
PREDECESSOR_OUTPUTS = {
    "official-capabilities.json": "32befd108b8e4f3eb10c066c3a28a936b277ff68d2b4940cf9e1ef40107e1873",
    "manifest.json": "bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a",
    "acceptance_inventory.json": "d9b76c528cb47300fc9c8fa14805fcf7598764a359ba66d7066842141b5e53c4",
    "capability-oracles.json": "363107069757bf6d87d7fc7b6c8810604494c09f6d127ff6c06d2e780f3a0990",
    "capability-oracles.schema.json": "47563fa4b4a98c77dd33edc4de38c3a4f2e932a0d47c4a83ba672d9631f3db97",
}
LIVE_CONTRACT_RAW_SHA256 = (
    "86df3c3e2159978c0e1b2a1deaa9d555fed4ea3728e6858eb0b017891d88b073"
)
CAPABILITY_ORACLES_RAW_SHA256 = (
    "bf029e8f1b3e50401368b77021d0b2b3373cb98ac9dafe7ffcd4f87e2bafd034"
)
ORACLE_SCHEMA_RAW_SHA256 = (
    "d3f86870fcca6bdb80eacb92bd402a88f34bacd68c42e52ac3408d05e0437498"
)


class IntegrationError(ValueError):
    """The predecessor chain or second static successor is not exact."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _locked(path: Path, expected: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise IntegrationError(f"reviewed input is unavailable: {path}")
    if raw_sha256(path.read_bytes()) != expected:
        raise IntegrationError(f"reviewed input digest drift: {path}")


def _module(name: str, path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise IntegrationError(f"reviewed module is unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise IntegrationError(f"cannot load reviewed module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _predecessor() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    _locked(PREDECESSOR_INTEGRATOR, PREDECESSOR_INTEGRATOR_RAW_SHA256)
    _locked(PREDECESSOR_CONTRACT, PREDECESSOR_CONTRACT_RAW_SHA256)
    _locked(PREDECESSOR_RECEIPT, PREDECESSOR_RECEIPT_RAW_SHA256)
    predecessor = _module(
        "source_contract_predecessor_integrator", PREDECESSOR_INTEGRATOR
    )
    ledger, manifest, acceptance, oracles, receipt = predecessor.build_expected(
        execute=False
    )
    receipt_payload = PREDECESSOR_RECEIPT.read_bytes()
    if receipt_payload != encoded(receipt):
        raise IntegrationError("immutable ten-case receipt differs from replay")
    if (
        canonical_sha256(receipt) != PREDECESSOR_RECEIPT_CANONICAL_SHA256
        or receipt.get("contract_sha256") != PREDECESSOR_CONTRACT_SHA256
        or receipt.get("outputs") != PREDECESSOR_OUTPUTS
    ):
        raise IntegrationError("immutable ten-case receipt binding drift")
    values = {
        "official-capabilities.json": ledger,
        "manifest.json": manifest,
        "acceptance_inventory.json": acceptance,
        "capability-oracles.json": oracles,
    }
    for name, value in values.items():
        if raw_sha256(encoded(value)) != PREDECESSOR_OUTPUTS[name]:
            raise IntegrationError(f"ten-case predecessor output drift: {name}")
    return ledger, manifest, acceptance, oracles, receipt


def _receipt_core(
    bindings: dict[str, dict[str, Any]], ledger: dict[str, Any]
) -> dict[str, Any]:
    first = next(iter(bindings.values()))
    return {
        "schema_version": 1,
        "integration_id": "source-contract-cases-live-planning-2026-07-31",
        "predecessor": {
            "receipt_path": "deploy/docker/thor-local/qualification/executor-cases/live-integration-receipt.json",
            "receipt_raw_sha256": PREDECESSOR_RECEIPT_RAW_SHA256,
            "receipt_canonical_sha256": PREDECESSOR_RECEIPT_CANONICAL_SHA256,
            "contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "integrator_path": "deploy/docker/thor-local/qualification/executor-cases/integrate_live.py",
            "integrator_raw_sha256": PREDECESSOR_INTEGRATOR_RAW_SHA256,
            "live_contract_path": "deploy/docker/thor-local/qualification/executor-cases/live_contract.py",
            "live_contract_raw_sha256": PREDECESSOR_CONTRACT_RAW_SHA256,
            "outputs": copy.deepcopy(PREDECESSOR_OUTPUTS),
        },
        "executor_inputs": {
            "inventory_path": first["executor"]["inventory_path"],
            "inventory_raw_sha256": first["executor"]["inventory_raw_sha256"],
            "inventory_canonical_sha256": first["executor"][
                "inventory_canonical_sha256"
            ],
            "inventory_schema_path": first["executor"]["inventory_schema_path"],
            "inventory_schema_raw_sha256": first["executor"][
                "inventory_schema_raw_sha256"
            ],
            "executor_path": first["executor"]["path"],
            "executor_raw_sha256": first["executor"]["raw_sha256"],
            "result_schema_path": first["result"]["schema_path"],
            "result_schema_raw_sha256": first["result"]["schema_raw_sha256"],
            "live_contract_path": "deploy/docker/thor-local/qualification/source-contract-integration/live_contract.py",
            "live_contract_raw_sha256": LIVE_CONTRACT_RAW_SHA256,
            "capability_oracles_path": "deploy/docker/thor-local/parity/capability_oracles.py",
            "capability_oracles_raw_sha256": CAPABILITY_ORACLES_RAW_SHA256,
            "capability_oracle_schema_path": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
            "capability_oracle_schema_raw_sha256": ORACLE_SCHEMA_RAW_SHA256,
        },
        "cases": [
            {
                **copy.deepcopy(binding["case"]),
                "case_canonical_sha256": binding["materialization"][
                    "case_canonical_sha256"
                ],
                "expected_outcome": binding["result"]["expected_outcome"],
            }
            for binding in bindings.values()
        ],
        "expected_counts": {
            "capabilities": len(ledger["capabilities"]),
            "discrepancies": len(ledger["source_discrepancies"]),
            "planning_requirements": 110,
            "materialized_planning_requirements": 26,
            "executor_ready_planning_requirements": 26,
            "open_planning_requirements": 84,
            "planning_index_only_oracles": len(ledger["capabilities"]),
            "static_subset_oracle_bindings": 26,
            "full_executor_ready_oracles": 0,
            "runtime_evidence_records": 0,
            "passed_current_promotions": 0,
            "new_observed_match": sum(
                binding["result"]["expected_outcome"] == "observed_match"
                for binding in bindings.values()
            ),
            "new_observed_mismatch": sum(
                binding["result"]["expected_outcome"] == "observed_mismatch"
                for binding in bindings.values()
            ),
            "cumulative_observed_match": 8
            + sum(
                binding["result"]["expected_outcome"] == "observed_match"
                for binding in bindings.values()
            ),
            "cumulative_observed_mismatch": 2
            + sum(
                binding["result"]["expected_outcome"] == "observed_mismatch"
                for binding in bindings.values()
            ),
        },
        "boundaries": {
            "execution_state": "reconstructed_ten_case_predecessor",
            "evidence_class": "deterministic_file_static_evidence_not_runtime",
            "capability_runtime_state_changed": False,
            "capability_oracle_promoted": False,
            "runtime_evidence_added": False,
            "warehouse_sample_bundle": "excluded",
            "network": "forbidden",
            "docker": "forbidden",
            "subprocess": "forbidden",
            "environment_mutation": "forbidden",
        },
    }


def _validate_semantics(
    predecessor_ledger: dict[str, Any],
    ledger: dict[str, Any],
    acceptance: dict[str, Any],
    oracles: dict[str, Any],
) -> None:
    if encoded(ledger) != encoded(predecessor_ledger):
        raise IntegrationError("static successor changed the official ledger")
    requirements = acceptance["wave3_contracts"]["planning_requirements"]
    if len(requirements) != 110:
        raise IntegrationError("planning requirement denominator drift")
    ready = [
        item
        for item in requirements
        if item.get("materialized") is True and item.get("executor_ready") is True
    ]
    open_items = [
        item
        for item in requirements
        if item.get("materialized") is False and item.get("executor_ready") is False
    ]
    if len(ready) != 26 or len(open_items) != 84:
        raise IntegrationError("exact 26/84 planning state drift")
    if any(item.get("runtime_evidence") != [] for item in requirements):
        raise IntegrationError("planning runtime evidence is not empty")
    if any(not isinstance(item.get("static_executor_binding"), dict) for item in ready):
        raise IntegrationError("materialized planning requirement lacks static binding")
    if any("static_executor_binding" in item for item in open_items):
        raise IntegrationError("open planning requirement has a static binding")

    rows = oracles.get("oracles", [])
    if len(rows) != 276 or any(
        row.get("acceptance_readiness", {}).get("classification")
        != "planning_index_only"
        for row in rows
    ):
        raise IntegrationError("full capability oracle classification drift")
    if any(row.get("executor") is not None for row in rows):
        raise IntegrationError("a full capability oracle gained an executor")
    binding_count = sum(len(row.get("planning_executor_bindings", [])) for row in rows)
    if binding_count != 26:
        raise IntegrationError("static subset oracle binding denominator drift")
    bindings = [
        binding
        for row in rows
        for binding in row.get("planning_executor_bindings", [])
    ]
    if any(
        binding.get("scope") != "bounded_static_assertion_subset_only"
        or binding.get("runtime_evidence") != []
        or binding.get("can_advance_capability") is not False
        or binding.get("can_mark_passed_current") is not False
        for binding in bindings
    ):
        raise IntegrationError("static subset oracle boundary drift")


def build_expected(*, execute: bool = True) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    _locked(LIVE_CONTRACT, LIVE_CONTRACT_RAW_SHA256)
    _locked(CAPABILITY_ORACLES, CAPABILITY_ORACLES_RAW_SHA256)
    _locked(ORACLE_SCHEMA, ORACLE_SCHEMA_RAW_SHA256)
    ledger, manifest, acceptance, _old_oracles, _old_receipt = _predecessor()
    predecessor_ledger = copy.deepcopy(ledger)
    live_contract = _module("source_contract_successor_contract", LIVE_CONTRACT)
    bindings = live_contract.build_bindings(
        acceptance, ledger, execute=execute
    )
    if len(bindings) != 16:
        raise IntegrationError("exact sixteen-case binding denominator drift")
    if set(bindings) & {
        item["id"]
        for item in acceptance["wave3_contracts"]["planning_requirements"]
        if item.get("materialized") is True
    }:
        raise IntegrationError("second successor overlaps predecessor bindings")

    receipt_core = _receipt_core(bindings, ledger)
    contract_sha = canonical_sha256(receipt_core)
    integration = {
        "receipt_path": "deploy/docker/thor-local/qualification/source-contract-integration/live-integration-receipt.json",
        "receipt_contract_sha256": contract_sha,
        "predecessor_receipt_path": "deploy/docker/thor-local/qualification/executor-cases/live-integration-receipt.json",
        "predecessor_receipt_raw_sha256": PREDECESSOR_RECEIPT_RAW_SHA256,
        "predecessor_contract_sha256": PREDECESSOR_CONTRACT_SHA256,
        "new_materialized_requirement_count": 16,
        "new_executor_ready_requirement_count": 16,
        "materialized_requirement_count": 26,
        "executor_ready_requirement_count": 26,
        "open_requirement_count": 84,
        "static_subset_oracle_binding_count": 26,
        "runtime_evidence_count": 0,
        "full_oracle_executor_ready_count": 0,
        "passed_current_promotion_count": 0,
    }
    acceptance["wave3_contracts"]["static_executor_integration"] = integration
    observed: set[str] = set()
    for requirement in acceptance["wave3_contracts"]["planning_requirements"]:
        binding = bindings.get(requirement["id"])
        if binding is None:
            continue
        if (
            requirement.get("materialized") is not False
            or requirement.get("executor_ready") is not False
            or requirement.get("runtime_evidence") != []
            or "static_executor_binding" in requirement
        ):
            raise IntegrationError("source-contract predecessor state drift")
        requirement["materialized"] = True
        requirement["executor_ready"] = True
        requirement["static_executor_binding"] = copy.deepcopy(binding)
        observed.add(requirement["id"])
    if observed != set(bindings):
        raise IntegrationError("planning requirement coverage differs from cases")

    oracle_module = _module("source_contract_successor_oracles", CAPABILITY_ORACLES)
    oracles = oracle_module.compile_plan(ledger, acceptance_document=acceptance)
    _validate_semantics(predecessor_ledger, ledger, acceptance, oracles)
    receipt = copy.deepcopy(receipt_core)
    receipt["contract_sha256"] = contract_sha
    receipt["outputs"] = {
        "official-capabilities.json": raw_sha256(encoded(ledger)),
        "manifest.json": raw_sha256(encoded(manifest)),
        "acceptance_inventory.json": raw_sha256(encoded(acceptance)),
        "capability-oracles.json": raw_sha256(encoded(oracles)),
        "capability-oracles.schema.json": ORACLE_SCHEMA_RAW_SHA256,
    }
    receipt["lifecycle"] = "second_live_planning_successor_integrated"
    return ledger, manifest, acceptance, oracles, receipt


def validate_live(*, execute: bool = True) -> dict[str, Any]:
    ledger, manifest, acceptance, oracles, receipt = build_expected(execute=execute)
    if RECEIPT.read_bytes() != encoded(receipt):
        raise IntegrationError("second successor receipt differs from replay")
    expected = {
        LEDGER: ledger,
        MANIFEST: manifest,
        ACCEPTANCE: acceptance,
        ORACLES: oracles,
    }
    for path, value in expected.items():
        if path.read_bytes() != encoded(value):
            raise IntegrationError(f"partial or drifted second successor: {path.name}")
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def validate_predecessor() -> dict[str, Any]:
    """Replay the historical receipt without requiring it to remain live."""
    _ledger, _manifest, _acceptance, _oracles, receipt = _predecessor()
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "validate", "validate-predecessor", "emit", "write")
    )
    parser.add_argument(
        "artifact",
        nargs="?",
        choices=("official-capabilities", "manifest", "acceptance", "oracles", "receipt"),
    )
    args = parser.parse_args()
    try:
        if args.command == "validate":
            print(json.dumps(validate_live(), sort_keys=True))
            return 0
        if args.command == "validate-predecessor":
            print(json.dumps(validate_predecessor(), sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_expected()
        if args.command == "plan":
            print(
                json.dumps(
                    {
                        "lifecycle": "prospective_second_live_planning_successor",
                        **receipt["expected_counts"],
                        "contract_sha256": receipt["contract_sha256"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "write":
            outputs = {
                LEDGER: ledger,
                MANIFEST: manifest,
                ACCEPTANCE: acceptance,
                ORACLES: oracles,
                RECEIPT: receipt,
            }
            for path, value in outputs.items():
                path.write_bytes(encoded(value))
            print(json.dumps({"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}, sort_keys=True))
            return 0
        if args.artifact is None:
            raise IntegrationError("emit requires an artifact name")
        values = {
            "official-capabilities": ledger,
            "manifest": manifest,
            "acceptance": acceptance,
            "oracles": oracles,
            "receipt": receipt,
        }
        sys.stdout.buffer.write(encoded(values[args.artifact]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
