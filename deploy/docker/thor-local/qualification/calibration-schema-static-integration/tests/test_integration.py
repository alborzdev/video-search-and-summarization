from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
REPO_ROOT = LANE.parents[4]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


integration = load_module(
    "calibration_schema_static_integration", LANE / "integrate_live.py"
)


def test_third_successor_semantics_remain_covered_by_replay() -> None:
    ledger, _manifest, _acceptance, oracles, receipt = integration._predecessor()
    capability = integration._one(
        ledger["capabilities"], "id", "api.core.lvs-mcp-doc-13-repo-9"
    )
    assert capability["thor_state"] == "wired"
    assert capability["runtime_state"] == "static_only"
    assert capability["contract"]["repository_tool_count"] == 13
    assert capability["contract"]["upstream_repository_tool_count"] == 9
    assert capability["contract"]["thor_local_adapter_tools"] == [
        "add_file",
        "list_files",
        "get_file_info",
        "delete_file",
    ]
    discrepancy = integration._one(
        ledger["source_discrepancies"],
        "id",
        "lvs-mcp-doc-13-vs-repository-9",
    )
    assert "pinned upstream repository" in discrepancy["resolution"]
    assert "live file lifecycle" in discrepancy["must_not_claim"]

    offline = {
        row["capability_id"]: row["offline_tool_observation_bindings"][0]
        for row in oracles["oracles"]
        if row.get("offline_tool_observation_bindings")
    }
    assert set(offline) == {
        "tool.mv3dt.cam-info-generator",
        "tool.mv3dt.pub-sub-generator",
    }
    assert all(
        binding["can_advance_capability"] is False
        and binding["can_mark_passed_current"] is False
        and binding["runtime_evidence"] == []
        for binding in offline.values()
    )
    assert receipt["expected_counts"]["static_subset_oracle_bindings"] == 28
    assert receipt["expected_counts"]["offline_tool_observation_bindings"] == 2
    assert receipt["expected_counts"]["runtime_evidence_records"] == 0
    assert receipt["expected_counts"]["passed_current_promotions"] == 0


def test_fourth_successor_is_exactly_one_non_advancing_binding() -> None:
    ledger, manifest, acceptance, oracles, receipt = integration.build_expected()
    assert receipt["expected_counts"] == {
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
    }
    assert (
        integration.raw_sha256(integration.encoded(ledger))
        == integration.PREDECESSOR_OUTPUTS["official-capabilities.json"]
    )
    assert (
        integration.raw_sha256(integration.encoded(manifest))
        == integration.PREDECESSOR_OUTPUTS["manifest.json"]
    )
    requirement = integration._one(
        acceptance["wave3_contracts"]["planning_requirements"],
        "id",
        integration.PLANNING_REQUIREMENT_ID,
    )
    assert requirement["owner_type"] == "global_acceptance_vector"
    assert requirement["owner_id"] == integration.PLANNING_REQUIREMENT_ID
    assert requirement["applicable_record_ids"] == integration.APPLICABLE_RECORD_IDS
    assert requirement["runtime_evidence"] == []

    target = next(
        row
        for row in oracles["oracles"]
        if row["capability_id"] == integration.CAPABILITY_ID
    )
    assert target["current_state"] == "open_unexecuted"
    assert target["evidence"] == []
    assert len(target["planning_executor_bindings"]) == 1
    binding = target["planning_executor_bindings"][0]
    assert (
        binding["case"]["uncovered_applicable_record_ids"]
        == integration.UNCOVERED_RECORD_IDS
    )
    assert binding["can_advance_capability"] is False
    assert binding["can_mark_passed_current"] is False
    assert binding["runtime_evidence"] == []


def test_all_six_other_global_vector_records_remain_uncovered() -> None:
    _, _, _, oracles, _ = integration.build_expected()
    by_id = {row["capability_id"]: row for row in oracles["oracles"]}
    for record_id in integration.UNCOVERED_RECORD_IDS:
        assert all(
            binding.get("planning_requirement_id")
            != integration.PLANNING_REQUIREMENT_ID
            for binding in by_id[record_id].get("planning_executor_bindings", [])
        )


def test_final_oracle_document_passes_the_additive_schema() -> None:
    _, _, _, oracles, _ = integration.build_expected()
    schema = json.loads(integration.ORACLE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(oracles)) == []


def test_existing_generic_binding_alternative_remains_valid() -> None:
    _, _, acceptance, oracles, _ = integration._predecessor()
    requirement = next(
        row
        for row in acceptance["wave3_contracts"]["planning_requirements"]
        if row.get("owner_type") == "capability" and row.get("materialized") is True
    )
    oracle = next(
        row
        for row in oracles["oracles"]
        if row["capability_id"] == requirement["owner_id"]
    )
    assert len(oracle["planning_executor_bindings"]) == 1
    schema = json.loads(integration.ORACLE_SCHEMA.read_text(encoding="utf-8"))
    binding_schema = schema["$defs"]["planningExecutorBinding"]
    validator = Draft202012Validator(schema)
    assert (
        list(
            validator.evolve(schema=binding_schema).iter_errors(
                oracle["planning_executor_bindings"][0]
            )
        )
        == []
    )


def test_global_vector_target_rejects_incomplete_uncovered_partition() -> None:
    _, _, acceptance, _, _ = integration.build_expected()
    requirement = integration._one(
        acceptance["wave3_contracts"]["planning_requirements"],
        "id",
        integration.PLANNING_REQUIREMENT_ID,
    )
    requirement["static_executor_binding"]["case"][
        "uncovered_applicable_record_ids"
    ] = integration.UNCOVERED_RECORD_IDS[:-1]
    compiler = load_module(
        "calibration_schema_partition_test", integration.ORACLE_COMPILER
    )
    with pytest.raises(
        compiler.OracleContractError,
        match="global planning executor target or uncovered partition differs",
    ):
        compiler._planning_executor_bindings(acceptance)


def test_executor_is_runnable_against_final_integrated_documents(monkeypatch) -> None:
    _, _, acceptance, oracles, _ = integration.build_expected()
    executor = load_module(
        "calibration_schema_post_integration_executor",
        REPO_ROOT
        / "deploy/docker/thor-local/qualification/calibration-schema-static-executor/executor.py",
    )
    acceptance_path = executor._repo_file(executor.ACCEPTANCE_PATH)
    oracle_path = executor._repo_file(executor.ORACLE_PATH)
    original = executor._strict_json

    def final_document(path: Path):
        if path == acceptance_path:
            return copy.deepcopy(acceptance)
        if path == oracle_path:
            return copy.deepcopy(oracles)
        return original(path)

    monkeypatch.setattr(executor, "_strict_json", final_document)
    result = executor.execute()
    assert result["result"] == "candidate_static_pass_non_advancing"
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"


def test_integrator_has_no_runtime_adapter() -> None:
    source = (LANE / "integrate_live.py").read_text(encoding="utf-8")
    forbidden = (
        "import socket",
        "import requests",
        "import subprocess",
        "import docker",
        "urllib",
        "http.client",
    )
    assert all(token not in source for token in forbidden)
