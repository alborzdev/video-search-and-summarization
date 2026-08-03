from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]


def load_executor() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agent_evaluation_mechanics_executor", PACKAGE / "executor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def test_contract_and_inert_result_are_strict_schema_valid() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    contract_schema = EXECUTOR.strict_json(PACKAGE / "contract.schema.json")
    result_schema = EXECUTOR.strict_json(PACKAGE / "result.schema.json")
    Draft202012Validator(contract_schema).validate(contract)
    plan = EXECUTOR.build_result(contract, executed=False)
    Draft202012Validator(result_schema).validate(plan)
    assert plan["status"] == "plan-nonpromotable"
    assert plan["promotion"]["eligible_capability_ids"] == []
    assert plan["promotion"]["receipt_is_runtime_evidence"] is False
    assert plan["promotion"]["aggregate_is_promotable"] is False


def test_exact_source_config_fixture_and_nat_locks_match() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    EXECUTOR.verify_locks(contract)
    EXECUTOR.verify_product_contract_tokens()
    assert len(contract["source_locks"]) == 9
    assert len(contract["config_locks"]) == 3
    assert contract["nat_lock"]["version"] == "1.6.0"
    assert contract["nat_lock"]["image_digest"].startswith("sha256:b7f3246a")
    assert (
        contract["nat_lock"]["report_judge_profile"]["upstream_config_raw_sha256"]
        == "e89664e421bac7b8869b9dfa1e4149930e11b935bf6dc01351392a6557bb4c79"
    )
    assert contract["nat_lock"]["report_judge_profile"]["max_tokens"] == 4096
    assert "judge_defaults" not in json.dumps(contract)
    assert "judge_defaults" not in json.dumps(
        EXECUTOR.strict_json(PACKAGE / "fixture-spec.json")
    )
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"


def test_lock_and_policy_drift_fail_closed() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    bad_hash = copy.deepcopy(contract)
    bad_hash["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.EvidenceError, match="lock mismatch"):
        EXECUTOR.verify_locks(bad_hash)
    bad_policy = copy.deepcopy(contract)
    bad_policy["policy"]["models_allowed"] = True
    with pytest.raises(EXECUTOR.EvidenceError, match="policy changed"):
        EXECUTOR.verify_locks(bad_policy)


def test_generated_fixture_is_deterministic_tiny_and_self_contained(
    tmp_path: Path,
) -> None:
    spec = EXECUTOR.strict_json(PACKAGE / "fixture-spec.json")
    first = EXECUTOR.materialize(tmp_path / "first", spec)
    second = EXECUTOR.materialize(tmp_path / "second", spec)
    assert first == second
    assert set(first) == {
        "dataset.json",
        "nat-config-mechanics.yml",
        "reports/actual.json",
        "reports/adjacent-negative.json",
        "reports/reference.json",
        "results/workflow_output.json",
        "results/report_evaluator_output.json",
        "results/qa_evaluator_output.json",
        "results/trajectory_evaluator_output.json",
        "results/latency_summary.json",
    }
    assert (
        sum(
            path.stat().st_size
            for path in (tmp_path / "first").rglob("*")
            if path.is_file()
        )
        < 32_000
    )
    assert not any(
        "warehouse" in str(path).lower() for path in (tmp_path / "first").rglob("*")
    )


def test_all_five_mechanics_checks_and_adjacent_negatives() -> None:
    spec = EXECUTOR.strict_json(PACKAGE / "fixture-spec.json")
    assert EXECUTOR.check_report(spec)
    assert EXECUTOR.check_qa(spec)
    assert EXECUTOR.check_trajectory(spec)
    assert EXECUTOR.check_multi_turn(spec)

    broken = copy.deepcopy(spec)
    broken["report"]["actual"]["title"] = "mismatch"
    assert not EXECUTOR.check_report(broken)
    broken = copy.deepcopy(spec)
    broken["qa"] = broken["qa"][:-1]
    assert not EXECUTOR.check_qa(broken)
    broken = copy.deepcopy(spec)
    broken["trajectory"]["with_reference"]["trajectory_ground_truth"][1]["step"] = 2
    assert not EXECUTOR.check_trajectory(broken)
    broken = copy.deepcopy(spec)
    broken["multi_turn"]["result_ids"] = ["wrong"]
    assert not EXECUTOR.check_multi_turn(broken)


def test_execution_filter_artifact_and_video_precondition_negatives(
    tmp_path: Path,
) -> None:
    spec = EXECUTOR.strict_json(PACKAGE / "fixture-spec.json")
    EXECUTOR.materialize(tmp_path, spec)
    assert EXECUTOR.check_execution_contract(spec, tmp_path)
    broken = copy.deepcopy(spec)
    broken["execution"]["valid_filters"].append("all,qa")
    assert not EXECUTOR.check_execution_contract(broken, tmp_path)
    missing = tmp_path / "results" / "workflow_output.json"
    missing.unlink()
    assert not EXECUTOR.check_execution_contract(spec, tmp_path)


def test_full_local_run_is_schema_valid_cleaned_and_never_promotable() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    result = EXECUTOR.execute(contract)
    schema = EXECUTOR.strict_json(PACKAGE / "result.schema.json")
    Draft202012Validator(schema).validate(result)
    assert [
        row["capability_id"] for row in result["capability_results"]
    ] == EXECUTOR.EXPECTED_CAPABILITIES
    assert all(
        row["mechanics_status"] == "passed_local_stub"
        for row in result["capability_results"]
    )
    assert all(
        row["advertised_semantics_proven"] is False
        for row in result["capability_results"]
    )
    assert all(row["promotable"] is False for row in result["capability_results"])
    assert result["fixture_run"]["cleanup_passed"] is True
    assert result["confinement"] == {
        "network_calls": 0,
        "downloads": 0,
        "service_lifecycle_calls": 0,
        "model_accesses": 0,
        "docker_calls": 0,
        "product_subprocess_calls": 0,
        "warehouse_sample_accesses": 0,
        "install_proprietary_codecs": False,
    }


def test_cached_image_observation_is_discovery_only() -> None:
    observation = EXECUTOR.strict_json(PACKAGE / "discovery-observation.json")
    assert observation["confinement"]["network"] == "none"
    assert observation["confinement"]["service_started"] is False
    assert observation["confinement"]["model_started_or_accessed"] is False
    assert observation["promotion_value"] == "none"
    assert "nat eval --config_file execution" in observation["not_observed"]
    assert "semantic scores" in observation["not_observed"]


def test_package_contains_no_canonical_metadata_outputs() -> None:
    names = {path.name for path in PACKAGE.rglob("*") if path.is_file()}
    assert "official-capabilities.json" not in names
    assert "capability-oracles-500.json" not in names
    assert "selector.json" not in names
    contract = json.loads((PACKAGE / "contract.json").read_text())
    assert contract["policy"]["canonical_metadata_mutation_allowed"] is False
