#!/usr/bin/env python3
"""Integrate the calibration-schema static executor as the fourth successor.

The predecessor and candidate receipt are replayed and digest-checked.  The
only canonical delta marks one global-vector planning requirement as having a
bounded static executor and attaches one non-advancing binding to the selected
schema capability oracle.  No runtime evidence or capability promotion occurs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
QUALIFICATION = REPO_ROOT / "deploy/docker/thor-local/qualification"
LEDGER = PARITY / "official-capabilities.json"
MANIFEST = PARITY / "manifest.json"
ORACLES = PARITY / "capability-oracles.json"
ORACLE_SCHEMA = PARITY / "capability-oracles.schema.json"
ORACLE_COMPILER = PARITY / "capability_oracles.py"
ACCEPTANCE = QUALIFICATION / "acceptance_inventory.json"
RECEIPT = LANE / "live-integration-receipt.json"
EXECUTION_RECEIPT = LANE / "execution-receipt.json"

PREDECESSOR = QUALIFICATION / "lvs-mcp-static-adapter-integration/integrate_live.py"
PREDECESSOR_RECEIPT = (
    QUALIFICATION / "lvs-mcp-static-adapter-integration/live-integration-receipt.json"
)
PREDECESSOR_RAW_SHA256 = (
    "17460d7798264a2c7c3de787e2a870a43771705a5c8ac71a90ed484798c84f03"
)
PREDECESSOR_RECEIPT_RAW_SHA256 = (
    "e3cc6000d28a8d56f30ccdab20631813b639e7519e11ffc9375da72661ec69fc"
)
PREDECESSOR_RECEIPT_CANONICAL_SHA256 = (
    "326103b4682c095ba5b199e6f8d9ce859dda65cc0f0f3bd39b17df55df7d67a4"
)
PREDECESSOR_CONTRACT_SHA256 = (
    "8015432ecaa593d58bc21c7ac3d6d91dddc8773c19fb8bbeb533fd0671cebc12"
)
PREDECESSOR_OUTPUTS = {
    "official-capabilities.json": "53670839f97b50238580741e71ae54a28ef50a7259ee1a847ebc66fc7a26c47d",
    "manifest.json": "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127",
    "acceptance_inventory.json": "ce62d87cd705259e7d30e7a7b9987bee20303d1e34bd35f1eb32da7fe97a571f",
    "capability-oracles.json": "c85729f691377f6f3d7e4080458789a9df3d9c394762c5ab20ee81b72a3451c3",
}

ORACLE_COMPILER_RAW_SHA256 = (
    "7a1c96055dbdb1d26463f9f4c6952a0f29af2a05ab3ac003dfad82911c14e60f"
)
ORACLE_SCHEMA_RAW_SHA256 = (
    "a1af2cd99d4df2e6bdec9afdee851b717ce7b0c931718fb1d727bd8090ddcbf5"
)
EXECUTION_RECEIPT_RAW_SHA256 = (
    "7050c8e513e59fa3393cc3ca747f445ca7a883974c0faa1efc9cc2372f5ef6fb"
)
EXECUTION_RECEIPT_CANONICAL_SHA256 = (
    "290dbdb08439e4d0b726d7047dcda49aacf010002636b027af497339cf340eb9"
)

EXECUTOR_ROOT = (
    "deploy/docker/thor-local/qualification/calibration-schema-static-executor"
)
EXECUTOR_FILES = {
    f"{EXECUTOR_ROOT}/EVIDENCE.md": "da8c84447fd59cd578925fcd35ae5eca45352cfeb2748f0eda28b327a8f798ef",
    f"{EXECUTOR_ROOT}/README.md": "bfdf756782a2d8469ce00b2c446dac86a84585c3a4708c2dd35c03627982f964",
    f"{EXECUTOR_ROOT}/contract.json": "4e18a42bed2d307214b08ad81ef5edf5028fbc983e3e3c1c7446429b0737d584",
    f"{EXECUTOR_ROOT}/contract.schema.json": "7e506f5b155bd10f53c81e55d664ce396d91e0795ddf16f52bddd36b784a822b",
    f"{EXECUTOR_ROOT}/executor.py": "420b936e7476ad137cadf1f27dc672dd3bb79ba7c679aded3be6dbbf5bb531fe",
    f"{EXECUTOR_ROOT}/result.schema.json": "849e4517acb4d1b3288164c34ad0689de011ca899da7e2f575c0ada067deffea",
    f"{EXECUTOR_ROOT}/tests/test_executor.py": "267d14e72abef5f268f9168fd09f5ceee58ce3e4e945ece83d2f9580d6cf3821",
}

PLANNING_REQUIREMENT_ID = "calibration-schema-static"
CAPABILITY_ID = "calibration.schema.vss-json"
ORACLE_ID = "oracle.calibration.schema.vss-json"
PLANNING_PAYLOAD_SHA256 = (
    "3e54d36b3e1895ad69fda05e458d3c80809507e31e975c210fdab56f446ce791"
)
CONTRACT_BINDING_CANONICAL_SHA256 = (
    "136dce0e50ee49c8608801737ceac0fd26b44c497b04910dd769feb6683c30ed"
)
APPLICABLE_RECORD_IDS = [
    "calibration.camera-positioning.installation-contract",
    CAPABILITY_ID,
    "behavior.auto-calibration.failure-recovery",
    "behavior.auto-calibration.result-verification",
    "calibration.auto.alignment-schema",
    "calibration.auto.workflow-six-step",
    "behavior.auto-calibration.known-limitations",
]
UNCOVERED_RECORD_IDS = [
    record_id for record_id in APPLICABLE_RECORD_IDS if record_id != CAPABILITY_ID
]


class IntegrationError(ValueError):
    """The predecessor, static candidate, or exact successor delta drifted."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


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


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise IntegrationError(f"duplicate JSON key: {path}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                IntegrationError(f"non-finite JSON value {token}: {path}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrationError(f"JSON root is not an object: {path}")
    return value


def _one(rows: Any, key: str, value: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise IntegrationError(f"record collection is not an array: {value}")
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise IntegrationError(f"expected one exact record: {value}")
    return matches[0]


def _predecessor() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Replay the third successor under the reviewed non-output compiler change."""
    _locked(PREDECESSOR, PREDECESSOR_RAW_SHA256)
    _locked(PREDECESSOR_RECEIPT, PREDECESSOR_RECEIPT_RAW_SHA256)
    predecessor_receipt = _strict_json(PREDECESSOR_RECEIPT)
    if (
        canonical_sha256(predecessor_receipt) != PREDECESSOR_RECEIPT_CANONICAL_SHA256
        or predecessor_receipt.get("contract_sha256") != PREDECESSOR_CONTRACT_SHA256
        or predecessor_receipt.get("outputs") != PREDECESSOR_OUTPUTS
        or predecessor_receipt.get("lifecycle")
        != "third_static_adapter_successor_integrated"
    ):
        raise IntegrationError("third-successor receipt binding drift")

    predecessor = _module("calibration_schema_predecessor", PREDECESSOR)
    # The fourth successor adds one dormant global-vector selection branch. At
    # the unmodified third-successor acceptance state it must be output-neutral.
    predecessor.ORACLE_COMPILER_RAW_SHA256 = ORACLE_COMPILER_RAW_SHA256
    predecessor.LIVE_ORACLE_SCHEMA_RAW_SHA256 = ORACLE_SCHEMA_RAW_SHA256
    values = predecessor.build_expected(execute=False)
    if values[4] != predecessor_receipt:
        raise IntegrationError("third-successor replay receipt differs")
    for name, value in zip(
        (
            "official-capabilities.json",
            "manifest.json",
            "acceptance_inventory.json",
            "capability-oracles.json",
        ),
        values[:4],
        strict=True,
    ):
        if raw_sha256(encoded(value)) != PREDECESSOR_OUTPUTS[name]:
            raise IntegrationError(f"third-successor replay output drift: {name}")
    return values


def _candidate_receipt() -> dict[str, Any]:
    for relative, digest in EXECUTOR_FILES.items():
        _locked(REPO_ROOT / relative, digest)
    _locked(EXECUTION_RECEIPT, EXECUTION_RECEIPT_RAW_SHA256)
    result = _strict_json(EXECUTION_RECEIPT)
    if canonical_sha256(result) != EXECUTION_RECEIPT_CANONICAL_SHA256:
        raise IntegrationError("calibration execution receipt canonical digest drift")
    schema_path = REPO_ROOT / f"{EXECUTOR_ROOT}/result.schema.json"
    schema = _strict_json(schema_path)
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise IntegrationError(
            f"calibration execution receipt schema violation: {errors[0].message}"
        )
    binding = result.get("binding", {})
    if (
        result.get("result") != "candidate_static_pass_non_advancing"
        or result.get("official_capability_effect") != "none_candidate_only"
        or result.get("runtime_evidence") != []
        or result.get("policy", {}).get("advances_live_acceptance") is not False
        or binding.get("planning_owner_type") != "global_acceptance_vector"
        or binding.get("capability_id") != CAPABILITY_ID
        or binding.get("not_evaluated_record_ids") != UNCOVERED_RECORD_IDS
        or binding.get("canonical_state_advanced") is not False
    ):
        raise IntegrationError("calibration candidate boundary drift")
    if result.get("binding_hashes") != {
        "planning_requirement_sha256": "20c14ca4a593a7d02246b0716b82d41f9387b76415df513d7465c2b57a46707a",
        "planning_payload_sha256": PLANNING_PAYLOAD_SHA256,
        "capability_sha256": "0245eb6e05f847e2c1a3c529634a1645c2186ce4c7c2f2ae33467a841ba257a8",
        "oracle_sha256": "6e4ededd81f30c6313ea376b899dd943b5fc739dee302e73886dfb850aee1c53",
    }:
        raise IntegrationError("candidate normalized canonical binding drift")
    return result


def _static_binding() -> dict[str, Any]:
    contract_path = f"{EXECUTOR_ROOT}/contract.json"
    contract_schema_path = f"{EXECUTOR_ROOT}/contract.schema.json"
    executor_path = f"{EXECUTOR_ROOT}/executor.py"
    result_schema_path = f"{EXECUTOR_ROOT}/result.schema.json"
    return {
        "materialization": {
            "scope": "live_planning_requirement_static_contract",
            "inventory_path": contract_path,
            "case_json_pointer": "/binding",
            "case_canonical_sha256": CONTRACT_BINDING_CANONICAL_SHA256,
        },
        "executor": {
            "path": executor_path,
            "raw_sha256": EXECUTOR_FILES[executor_path],
            "inventory_path": contract_path,
            "inventory_raw_sha256": EXECUTOR_FILES[contract_path],
            "inventory_canonical_sha256": canonical_sha256(
                _strict_json(REPO_ROOT / contract_path)
            ),
            "inventory_schema_path": contract_schema_path,
            "inventory_schema_raw_sha256": EXECUTOR_FILES[contract_schema_path],
            "invocation": ["python3", executor_path, "--json"],
        },
        "case": {
            "case_id": "calibration-schema-static.vss-json",
            "planning_requirement_id": PLANNING_REQUIREMENT_ID,
            "capability_id": CAPABILITY_ID,
            "planning_payload_sha256": PLANNING_PAYLOAD_SHA256,
            "planning_owner_type": "global_acceptance_vector",
            "planning_owner_id": PLANNING_REQUIREMENT_ID,
            "applicable_record_ids": copy.deepcopy(APPLICABLE_RECORD_IDS),
            "uncovered_applicable_record_ids": copy.deepcopy(UNCOVERED_RECORD_IDS),
        },
        "result": {
            "schema_path": result_schema_path,
            "schema_raw_sha256": EXECUTOR_FILES[result_schema_path],
            "execution_receipt_path": "deploy/docker/thor-local/qualification/calibration-schema-static-integration/execution-receipt.json",
            "execution_receipt_raw_sha256": EXECUTION_RECEIPT_RAW_SHA256,
            "execution_receipt_canonical_sha256": EXECUTION_RECEIPT_CANONICAL_SHA256,
            "expected_outcome": "observed_match",
            "evidence_class": "deterministic_file_static_evidence_not_runtime",
            "can_advance_capability": False,
            "can_mark_passed_current": False,
            "runtime_evidence": [],
        },
    }


def _apply_delta(acceptance: dict[str, Any]) -> None:
    requirement = _one(
        acceptance["wave3_contracts"]["planning_requirements"],
        "id",
        PLANNING_REQUIREMENT_ID,
    )
    if (
        requirement.get("owner_type") != "global_acceptance_vector"
        or requirement.get("owner_id") != PLANNING_REQUIREMENT_ID
        or requirement.get("payload_canonical_sha256") != PLANNING_PAYLOAD_SHA256
        or requirement.get("applicable_record_ids") != APPLICABLE_RECORD_IDS
        or requirement.get("materialized") is not False
        or requirement.get("executor_ready") is not False
        or requirement.get("runtime_evidence") != []
        or "static_executor_binding" in requirement
    ):
        raise IntegrationError("calibration global-vector predecessor state drift")
    requirement["materialized"] = True
    requirement["executor_ready"] = True
    requirement["static_executor_binding"] = _static_binding()


def _validate_successor(
    predecessor: tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ],
    ledger: dict[str, Any],
    manifest: dict[str, Any],
    acceptance: dict[str, Any],
    oracles: dict[str, Any],
) -> None:
    old_ledger, old_manifest, old_acceptance, old_oracles, _old_receipt = predecessor
    if encoded(ledger) != encoded(old_ledger) or encoded(manifest) != encoded(
        old_manifest
    ):
        raise IntegrationError("fourth successor changed ledger or manifest")
    old_requirements = old_acceptance["wave3_contracts"]["planning_requirements"]
    requirements = acceptance["wave3_contracts"]["planning_requirements"]
    changed = [
        new.get("id")
        for old, new in zip(old_requirements, requirements, strict=True)
        if old != new
    ]
    if changed != [PLANNING_REQUIREMENT_ID]:
        raise IntegrationError("fourth successor planning delta is not singular")
    requirement = _one(requirements, "id", PLANNING_REQUIREMENT_ID)
    if (
        requirement.get("owner_type") != "global_acceptance_vector"
        or requirement.get("owner_id") != PLANNING_REQUIREMENT_ID
        or requirement.get("applicable_record_ids") != APPLICABLE_RECORD_IDS
        or requirement.get("runtime_evidence") != []
    ):
        raise IntegrationError("global-vector ownership changed")

    old_by_id = {row["capability_id"]: row for row in old_oracles["oracles"]}
    new_by_id = {row["capability_id"]: row for row in oracles["oracles"]}
    changed_oracles = [
        capability_id
        for capability_id in old_by_id
        if old_by_id[capability_id] != new_by_id[capability_id]
    ]
    if changed_oracles != [CAPABILITY_ID]:
        raise IntegrationError("fourth successor oracle delta is not singular")
    target = new_by_id[CAPABILITY_ID]
    bindings = target.get("planning_executor_bindings")
    if (
        not isinstance(bindings, list)
        or len(bindings) != 1
        or bindings[0].get("planning_requirement_id") != PLANNING_REQUIREMENT_ID
        or bindings[0].get("can_advance_capability") is not False
        or bindings[0].get("can_mark_passed_current") is not False
        or bindings[0].get("runtime_evidence") != []
    ):
        raise IntegrationError("exact non-advancing oracle binding differs")
    if any(
        any(
            binding.get("planning_requirement_id") == PLANNING_REQUIREMENT_ID
            for binding in new_by_id[record_id].get("planning_executor_bindings", [])
        )
        for record_id in UNCOVERED_RECORD_IDS
    ):
        raise IntegrationError("an explicitly uncovered global-vector record was bound")
    if (
        target.get("current_state") != "open_unexecuted"
        or target.get("evidence") != []
        or any(row.get("runtime_evidence") for row in requirements)
        or any(
            row.get("current_state") == "passed_current" for row in oracles["oracles"]
        )
    ):
        raise IntegrationError("runtime evidence or promotion entered the successor")
    schema = _strict_json(ORACLE_SCHEMA)
    errors = list(Draft202012Validator(schema).iter_errors(oracles))
    if errors:
        raise IntegrationError(
            f"fourth-successor oracle schema violation: {errors[0].message}"
        )


def build_expected(*, execute: bool = False) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    del execute
    _locked(ORACLE_COMPILER, ORACLE_COMPILER_RAW_SHA256)
    _locked(ORACLE_SCHEMA, ORACLE_SCHEMA_RAW_SHA256)
    _candidate_receipt()
    predecessor = _predecessor()
    ledger, manifest, acceptance = copy.deepcopy(predecessor[:3])
    _apply_delta(acceptance)
    compiler = _module("calibration_schema_oracle_compiler", ORACLE_COMPILER)
    oracles = compiler.compile_plan(
        ledger,
        acceptance_document=acceptance,
        include_local_runtime_bounds=True,
    )
    _validate_successor(predecessor, ledger, manifest, acceptance, oracles)
    receipt_core = {
        "schema_version": 1,
        "integration_id": "calibration-schema-static-fourth-successor-2026-08-01",
        "predecessor": {
            "integrator_path": "deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py",
            "integrator_raw_sha256": PREDECESSOR_RAW_SHA256,
            "receipt_path": "deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/live-integration-receipt.json",
            "receipt_raw_sha256": PREDECESSOR_RECEIPT_RAW_SHA256,
            "receipt_canonical_sha256": PREDECESSOR_RECEIPT_CANONICAL_SHA256,
            "contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "outputs": copy.deepcopy(PREDECESSOR_OUTPUTS),
            "compiler_change_output_neutral_at_predecessor": True,
        },
        "reviewed_inputs": [
            {"path": path, "raw_sha256": digest}
            for path, digest in sorted(EXECUTOR_FILES.items())
        ]
        + [
            {
                "path": "deploy/docker/thor-local/qualification/calibration-schema-static-integration/execution-receipt.json",
                "raw_sha256": EXECUTION_RECEIPT_RAW_SHA256,
                "canonical_sha256": EXECUTION_RECEIPT_CANONICAL_SHA256,
            },
            {
                "path": "deploy/docker/thor-local/parity/capability_oracles.py",
                "raw_sha256": ORACLE_COMPILER_RAW_SHA256,
            },
            {
                "path": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
                "raw_sha256": ORACLE_SCHEMA_RAW_SHA256,
            },
        ],
        "delta": {
            "planning_requirement_id": PLANNING_REQUIREMENT_ID,
            "planning_owner_type": "global_acceptance_vector",
            "planning_owner_id": PLANNING_REQUIREMENT_ID,
            "capability_id": CAPABILITY_ID,
            "oracle_id": ORACLE_ID,
            "applicable_record_ids": copy.deepcopy(APPLICABLE_RECORD_IDS),
            "uncovered_applicable_record_ids": copy.deepcopy(UNCOVERED_RECORD_IDS),
            "new_planning_executor_bindings": 1,
        },
        "expected_counts": {
            "capabilities": 276,
            "oracles": 276,
            "planning_requirements": 110,
            "materialized_planning_requirements": 27,
            "open_planning_requirements": 83,
            "planning_executor_bindings": 27,
            "offline_tool_observation_bindings": 2,
            "static_subset_oracle_bindings": 29,
            "runtime_evidence_records": 0,
            "passed_current_promotions": 0,
            "new_calibration_schema_bindings": 1,
            "explicitly_uncovered_applicable_records": 6,
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
        },
    }
    receipt = copy.deepcopy(receipt_core)
    receipt["contract_sha256"] = canonical_sha256(receipt_core)
    receipt["outputs"] = {
        "official-capabilities.json": raw_sha256(encoded(ledger)),
        "manifest.json": raw_sha256(encoded(manifest)),
        "acceptance_inventory.json": raw_sha256(encoded(acceptance)),
        "capability-oracles.json": raw_sha256(encoded(oracles)),
    }
    receipt["lifecycle"] = "fourth_calibration_schema_static_successor_integrated"
    return ledger, manifest, acceptance, oracles, receipt


def validate_predecessor() -> dict[str, Any]:
    values = _predecessor()
    return {
        "lifecycle": values[4]["lifecycle"],
        **values[4]["expected_counts"],
    }


def validate_live() -> dict[str, Any]:
    ledger, manifest, acceptance, oracles, receipt = build_expected()
    if RECEIPT.read_bytes() != encoded(receipt):
        raise IntegrationError("fourth-successor receipt differs from replay")
    for path, value in {
        LEDGER: ledger,
        MANIFEST: manifest,
        ACCEPTANCE: acceptance,
        ORACLES: oracles,
    }.items():
        if path.read_bytes() != encoded(value):
            raise IntegrationError(f"partial or drifted fourth successor: {path.name}")
    return {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "validate-predecessor", "validate", "write")
    )
    args = parser.parse_args()
    try:
        if args.command == "validate-predecessor":
            print(json.dumps(validate_predecessor(), sort_keys=True))
            return 0
        if args.command == "validate":
            print(json.dumps(validate_live(), sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_expected()
        if args.command == "plan":
            print(
                json.dumps(
                    {
                        "lifecycle": "prospective_fourth_calibration_schema_static_successor",
                        **receipt["expected_counts"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        for path, value in {
            ACCEPTANCE: acceptance,
            ORACLES: oracles,
            RECEIPT: receipt,
        }.items():
            path.write_bytes(encoded(value))
        print(
            json.dumps(
                {"lifecycle": receipt["lifecycle"], **receipt["expected_counts"]},
                sort_keys=True,
            )
        )
        return 0
    except (IntegrationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
