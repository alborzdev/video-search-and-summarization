#!/usr/bin/env python3
"""Deterministically integrate the ten static cases into live planning records.

This successor overlay replays the immutable Wave 3 merge, applies the reviewed
executor-mismatch reconciliation, and then materializes exactly ten bounded
static planning requirements.  It never promotes a capability or a full
capability oracle and never creates runtime evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
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

WAVE3_MERGE = PARITY / "candidates/wave3/bundle/merge_live.py"
WAVE3_RECEIPT = PARITY / "candidates/wave3/bundle/merge-receipt.json"
RECONCILE = PARITY / "reconciliations/executor-mismatch-review/reconcile.py"
RECONCILIATION = PARITY / "reconciliations/executor-mismatch-review/reconciliation.json"
LIVE_CONTRACT = LANE / "live_contract.py"
CAPABILITY_ORACLES = PARITY / "capability_oracles.py"

WAVE3_CONTRACT_SHA256 = (
    "733ff41b1aa473f7a6e1a117d7162c981dca99034d080677ece7b4b4c220c46b"
)
WAVE3_OUTPUT_SHA256 = {
    "official-capabilities.json": "0dcd9aabc508b79d863da60c6b7ab592dd3f57032037dac750b160f72ff2f9b0",
    "manifest.json": "bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a",
    "acceptance_inventory.json": "ba7d1b6d81b511e525eaadb79aac54416711d2ed543984847ddb9e9a8df7cce6",
    "capability-oracles.json": "afaa785d6f7fb830b92042f61284e363915548573615cdc051e1ca8211a2b54b",
    "official-capabilities.schema.json": "6bbd5354db37f871a2a912a79a1bb45c477617ef65e54e1fb1a13f0269efad39",
}
ORACLE_SCHEMA_RAW_SHA256 = (
    "47563fa4b4a98c77dd33edc4de38c3a4f2e932a0d47c4a83ba672d9631f3db97"
)


class IntegrationError(ValueError):
    """The predecessor chain or live static integration is not exact."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _strict_load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IntegrationError(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrationError(f"JSON root is not an object: {path}")
    return value


def _predecessors() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    wave3 = _module("executor_live_wave3_merge", WAVE3_MERGE)
    reconcile = _module("executor_live_mismatch_reconcile", RECONCILE)
    base_ledger, manifest, acceptance, _oracles, expected_wave3_receipt = (
        wave3.build_unmerged(from_baseline=True)
    )
    if WAVE3_RECEIPT.read_bytes() != encoded(expected_wave3_receipt):
        raise IntegrationError("immutable Wave 3 receipt differs from baseline replay")
    if (
        expected_wave3_receipt.get("contract_sha256") != WAVE3_CONTRACT_SHA256
        or expected_wave3_receipt.get("outputs") != WAVE3_OUTPUT_SHA256
    ):
        raise IntegrationError("immutable Wave 3 predecessor binding drift")
    descriptor = reconcile.load_descriptor()
    reconcile.verify_evidence(descriptor, REPO_ROOT)
    reconciled_payload = reconcile.build_bytes(encoded(base_ledger), descriptor)
    ledger = reconcile.strict_loads(reconciled_payload, "expected reconciled ledger")
    reconcile.validate_payload(reconciled_payload, descriptor, repo_root=REPO_ROOT)
    return ledger, manifest, acceptance


def _receipt_core(
    bindings: dict[str, dict[str, Any]],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    reconciliation = _strict_load(RECONCILIATION)
    return {
        "schema_version": 1,
        "integration_id": "executor-cases-live-planning-2026-07-31",
        "predecessors": {
            "wave3": {
                "receipt_path": "deploy/docker/thor-local/parity/candidates/wave3/bundle/merge-receipt.json",
                "contract_sha256": WAVE3_CONTRACT_SHA256,
                "outputs": copy.deepcopy(WAVE3_OUTPUT_SHA256),
            },
            "executor_mismatch_reconciliation": {
                "descriptor_path": "deploy/docker/thor-local/parity/reconciliations/executor-mismatch-review/reconciliation.json",
                "descriptor_canonical_sha256": canonical_sha256(reconciliation),
                "ledger_output_raw_sha256": reconciliation["ledger"][
                    "output_raw_sha256"
                ],
                "record_ids": [item["id"] for item in reconciliation["records"]],
            },
        },
        "executor_inputs": {
            "inventory_path": next(iter(bindings.values()))["executor"][
                "inventory_path"
            ],
            "inventory_raw_sha256": next(iter(bindings.values()))["executor"][
                "inventory_raw_sha256"
            ],
            "inventory_canonical_sha256": next(iter(bindings.values()))["executor"][
                "inventory_canonical_sha256"
            ],
            "inventory_schema_path": next(iter(bindings.values()))["executor"][
                "inventory_schema_path"
            ],
            "inventory_schema_raw_sha256": next(iter(bindings.values()))[
                "executor"
            ]["inventory_schema_raw_sha256"],
            "executor_path": next(iter(bindings.values()))["executor"]["path"],
            "executor_raw_sha256": next(iter(bindings.values()))["executor"][
                "raw_sha256"
            ],
            "result_schema_path": next(iter(bindings.values()))["result"][
                "schema_path"
            ],
            "result_schema_raw_sha256": next(iter(bindings.values()))["result"][
                "schema_raw_sha256"
            ],
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
            "materialized_planning_requirements": 10,
            "executor_ready_planning_requirements": 10,
            "planning_index_only_oracles": len(ledger["capabilities"]),
            "full_executor_ready_oracles": 0,
            "runtime_evidence_records": 0,
            "observed_match": sum(
                binding["result"]["expected_outcome"] == "observed_match"
                for binding in bindings.values()
            ),
            "observed_mismatch": sum(
                binding["result"]["expected_outcome"] == "observed_mismatch"
                for binding in bindings.values()
            ),
        },
        "boundaries": {
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


def build_expected(*, execute: bool = True) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    if raw_sha256(ORACLE_SCHEMA.read_bytes()) != ORACLE_SCHEMA_RAW_SHA256:
        raise IntegrationError("reviewed capability oracle schema digest drift")
    ledger, manifest, acceptance = _predecessors()
    live_contract = _module("executor_live_contract", LIVE_CONTRACT)
    bindings = live_contract.build_bindings(execute=execute)
    if len(bindings) != 10:
        raise IntegrationError("exact ten-case binding denominator drift")
    receipt_core = _receipt_core(bindings, ledger)
    contract_sha = canonical_sha256(receipt_core)

    wave3 = acceptance.get("wave3_contracts")
    if not isinstance(wave3, dict):
        raise IntegrationError("Wave 3 acceptance predecessor is malformed")
    wave3["policies"] = {
        "planning_inventory": True,
        "materialized_fixtures_added": True,
        "executor_ready_added": True,
        "runtime_pass_evidence_added": False,
        "warehouse_sample_bundle": "excluded_optional",
    }
    wave3["static_executor_integration"] = {
        "receipt_path": "deploy/docker/thor-local/qualification/executor-cases/live-integration-receipt.json",
        "receipt_contract_sha256": contract_sha,
        "materialized_requirement_count": 10,
        "executor_ready_requirement_count": 10,
        "runtime_evidence_count": 0,
        "full_oracle_executor_ready_count": 0,
    }
    observed_ids: set[str] = set()
    for requirement in wave3["planning_requirements"]:
        requirement_id = requirement["id"]
        binding = bindings.get(requirement_id)
        if binding is None:
            continue
        requirement["materialized"] = True
        requirement["executor_ready"] = True
        requirement["static_executor_binding"] = copy.deepcopy(binding)
        observed_ids.add(requirement_id)
    if observed_ids != set(bindings):
        raise IntegrationError("planning requirement coverage differs from executor cases")

    oracle_module = _module("executor_live_capability_oracles", CAPABILITY_ORACLES)
    oracles = oracle_module.compile_plan(
        ledger, acceptance_document=acceptance
    )
    receipt = copy.deepcopy(receipt_core)
    receipt["contract_sha256"] = contract_sha
    receipt["outputs"] = {
        "official-capabilities.json": raw_sha256(encoded(ledger)),
        "manifest.json": raw_sha256(encoded(manifest)),
        "acceptance_inventory.json": raw_sha256(encoded(acceptance)),
        "capability-oracles.json": raw_sha256(encoded(oracles)),
        "capability-oracles.schema.json": ORACLE_SCHEMA_RAW_SHA256,
    }
    receipt["lifecycle"] = "live_planning_integrated"
    return ledger, manifest, acceptance, oracles, receipt


def validate_live(*, execute: bool = True) -> dict[str, Any]:
    ledger, manifest, acceptance, oracles, receipt = build_expected(execute=execute)
    if RECEIPT.read_bytes() != encoded(receipt):
        raise IntegrationError("live integration receipt differs from deterministic replay")
    expected = {
        LEDGER: ledger,
        MANIFEST: manifest,
        ACCEPTANCE: acceptance,
        ORACLES: oracles,
    }
    for path, value in expected.items():
        if path.read_bytes() != encoded(value):
            raise IntegrationError(f"partial or drifted live integration: {path.name}")
    if (
        receipt["outputs"]["capability-oracles.schema.json"]
        != ORACLE_SCHEMA_RAW_SHA256
        or raw_sha256(ORACLE_SCHEMA.read_bytes()) != ORACLE_SCHEMA_RAW_SHA256
    ):
        raise IntegrationError("capability oracle schema digest drift")
    return {
        "lifecycle": receipt["lifecycle"],
        **receipt["expected_counts"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "validate", "emit"))
    parser.add_argument(
        "artifact",
        nargs="?",
        choices=("official-capabilities", "manifest", "acceptance", "oracles", "receipt"),
    )
    args = parser.parse_args()
    try:
        if args.command == "validate":
            report = validate_live()
            print(json.dumps(report, sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_expected()
        if args.command == "plan":
            print(
                json.dumps(
                    {
                        "lifecycle": "prospective_live_planning_integrated",
                        **receipt["expected_counts"],
                        "contract_sha256": receipt["contract_sha256"],
                    },
                    sort_keys=True,
                )
            )
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
