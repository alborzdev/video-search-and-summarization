# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Adversarial tests for the isolated NvSchema JSON static candidate."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "systems_nvschema_json_static_executor", LANE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


@pytest.fixture(scope="module")
def result() -> dict:
    return EXECUTOR.execute()


def test_candidate_pass_is_deterministic_and_non_advancing(result: dict) -> None:
    assert result["result"] == "candidate_static_pass_non_advancing"
    assert result["determinism"] == {
        "independent_runs": 2,
        "byte_identical": True,
        "observation_sha256": "8a837a830f7436b125eced216b6564114a8095d7940c45be27a0654034fee6c8",
    }
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["confinement"] == {
        "private_temporary_roots": True,
        "cleanup_verified": True,
        "external_calls": 0,
        "warehouse_sample_bundle": "excluded",
        "counter_basis": "locked_source_and_import_boundary_audit",
        "import_state_restored": True,
    }


def test_binding_preserves_all_canonical_open_states(result: dict) -> None:
    assert result["binding"] == {
        "planning_requirement_id": "systems-nvschema-json",
        "capability_id": "protocol.nvschema.json-frame",
        "oracle_id": "oracle.protocol.nvschema.json-frame",
        "planning_materialized": False,
        "planning_executor_ready": False,
        "capability_thor_state": "partial",
        "capability_runtime_state": "not_qualified",
        "oracle_state": "open_unexecuted",
        "canonical_runtime_evidence": [],
    }


def test_real_product_observations_cover_legacy_modern_and_agent(result: dict) -> None:
    observations = result["observations"]
    legacy = observations["legacy_behavior_frame"]
    assert legacy["wire_roundtrip_byte_identical"] is True
    assert legacy["wire_sha256"] == (
        "66f311f8eb6a6c139fcd067f74f048fa982be8bfaa3e0a4611f767b0c56eaded"
    )
    assert legacy["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert legacy["pose_keypoints"] == 1
    assert legacy["embedding"] == [1.0, 2.0, 3.0]
    modern = observations["spatial_3d_frame"]
    assert modern["raw_custom_field"] == "preserved"
    assert modern["flat_location"] == [1, 2, 3]
    assert modern["flat_scale"] == [4, 5, 6]
    assert modern["flat_rotation"] == [0.1, 0.2, 0.3]
    assert observations["agent_incident_aliases"]["analyticsModule"] == (
        "behavior-analytics"
    )


def test_adjacent_negatives_are_exact_and_honest(result: dict) -> None:
    rows = result["observations"]["adjacent_negatives"]
    assert [row["id"] for row in rows] == EXECUTOR.EXPECTED_NEGATIVES
    assert [row["outcome"] for row in rows] == [
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "accepted_limited",
        "accepted_limited",
    ]
    assert result["limitations"] == [
        "illustrative_contract_has_no_complete_json_schema_validator",
        "documented_event_enum_is_not_enforced_by_the_executed_frame_converter",
        "spatial_iterator_does_not_project_the_official_legacy_at_timestamp_field",
        "legacy_2d_string_objects_and_modern_3d_dictionary_objects_use_distinct_consumers",
        "full_behavior_test_import_is_blocked_by_host_numpy2_matplotlib_numpy1_abi_mismatch",
        "no_deployed_service_or_broker_protocol_roundtrip_executed",
    ]


def test_contract_schema_rejects_unknown_fields() -> None:
    schema = json.loads((LANE / "contract.schema.json").read_text())
    value = json.loads((LANE / "contract.json").read_text())
    value["unbounded_escape_hatch"] = True
    assert list(Draft202012Validator(schema).iter_errors(value))


def test_result_schema_rejects_runtime_promotion(result: dict) -> None:
    schema = json.loads((LANE / "result.schema.json").read_text())
    promoted = deepcopy(result)
    promoted["runtime_evidence"] = ["invented"]
    promoted["official_capability_effect"] = "passed_current"
    assert list(Draft202012Validator(schema).iter_errors(promoted))


def test_result_schema_rejects_duplicate_or_mismatched_negative(result: dict) -> None:
    schema = json.loads((LANE / "result.schema.json").read_text())
    drifted = deepcopy(result)
    drifted["observations"]["adjacent_negatives"][1] = deepcopy(
        drifted["observations"]["adjacent_negatives"][0]
    )
    assert list(Draft202012Validator(schema).iter_errors(drifted))


def test_exact_source_lock_membership_substitution_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = EXECUTOR._strict_json

    def substitute(path: Path) -> dict:
        value = original(path)
        if path == LANE / "contract.json":
            value["source_locks"][0] = deepcopy(value["source_locks"][1])
        return value

    monkeypatch.setattr(EXECUTOR, "_strict_json", substitute)
    with pytest.raises(EXECUTOR.QualificationError, match="source-lock set drift"):
        EXECUTOR._load_contract()


def test_source_hash_tampering_fails_closed() -> None:
    contract = deepcopy(EXECUTOR._load_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.QualificationError, match="source lock mismatch"):
        EXECUTOR._verify_sources(contract)


def test_strict_json_rejects_duplicate_keys_and_symlinks(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(EXECUTOR.QualificationError, match="duplicate JSON key"):
        EXECUTOR._strict_json(duplicate)
    link = tmp_path / "link.json"
    link.symlink_to(duplicate)
    with pytest.raises(EXECUTOR.QualificationError, match="non-symlink"):
        EXECUTOR._strict_json(link)


def test_executor_has_no_network_or_process_imports() -> None:
    tree = ast.parse((LANE / "executor.py").read_text())
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imports.isdisjoint(
        {"docker", "requests", "httpx", "socket", "subprocess", "urllib"}
    )


def test_product_import_state_is_restored(tmp_path: Path) -> None:
    path_before = list(sys.path)
    modules_before = {
        name: module
        for name, module in sys.modules.items()
        if EXECUTOR._is_product_module(name)
    }
    EXECUTOR._observe(tmp_path)
    modules_after = {
        name: module
        for name, module in sys.modules.items()
        if EXECUTOR._is_product_module(name)
    }
    assert sys.path == path_before
    assert modules_after == modules_before
