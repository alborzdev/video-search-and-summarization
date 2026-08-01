from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_bounds_compiler", PACKAGE / "compiler.py"
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load_json(name: str):
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


@pytest.fixture()
def inputs():
    contract = load_json("contract.json")
    canonical = json.loads(
        (compiler.REPO_ROOT / contract["canonical_source"]["path"]).read_text()
    )
    return contract, canonical


def test_cli_check_is_byte_deterministic(capsys):
    assert compiler.main(["--check"]) == 0
    assert "PASS: exact 20" in capsys.readouterr().out


def test_exact_denominator_and_budgets(inputs):
    result = compiler.compile_audit(*inputs)
    actual = {
        case["planning_requirement_id"]: (
            case["minimum_request_budget"],
            case["minimum_action_budget"],
        )
        for case in result["cases"]
    }
    assert actual == compiler.EXPECTED_BUDGETS
    assert list(actual) == compiler.EXPECTED_IDS
    assert result["summary"] == {
        "case_count": 20,
        "current_two_request_cases": 20,
        "two_request_inadequate_cases": 20,
        "minimum_request_budget_total": 202,
        "minimum_action_budget_total": 207,
    }


def test_all_twos_are_constructively_proved_inadequate(inputs):
    result = compiler.compile_audit(*inputs)
    for case in result["cases"]:
        assert case["current_max_requests"] == 2
        assert case["minimum_request_budget"] > case["current_max_requests"]
        assert case["max_requests_2_inadequate"] is True
        assert (
            case["proposed_override"]["max_requests"] == case["minimum_request_budget"]
        )


def test_override_targets_only_execution_bounds(inputs):
    result = compiler.compile_audit(*inputs)
    for case in result["cases"]:
        assert case["override_target"].endswith("/execution_bounds")
        assert "state" not in case["override_target"]
        assert "evidence" not in case["override_target"]
        assert set(case["proposed_override"]) == {"max_requests", "workload"}


def test_workload_arithmetic_is_exact(inputs):
    result = compiler.compile_audit(*inputs)
    for case in result["cases"]:
        workload = case["proposed_override"]["workload"]
        assert (
            workload["units"] * workload["requests_per_unit"]
            + workload["overhead_requests"]
            == workload["calculated_max_requests"]
        )
        assert workload["calculated_max_requests"] == case["minimum_request_budget"]
        assert workload["phases"] == compiler.PHASES


def test_every_workflow_step_resolves_to_locked_canonical_input(inputs):
    contract, canonical = inputs
    for case in contract["cases"]:
        oracle = canonical["oracles"][case["canonical_oracle_index"]]
        expanded = compiler._expanded_steps(contract, case)
        assert (
            len(expanded)
            == compiler.EXPECTED_BUDGETS[case["planning_requirement_id"]][1]
        )
        for sequence, step in enumerate(expanded, start=1):
            assert step["sequence"] == sequence
            for pointer in step["canonical_basis"]:
                assert compiler._resolve_pointer(oracle, pointer) is not None


def test_official_oracles_remain_open_and_unmaterialized(inputs):
    contract, canonical = inputs
    result = compiler.compile_audit(contract, canonical)
    assert result["official_states_preserved"] is True
    for case in contract["cases"]:
        oracle = canonical["oracles"][case["canonical_oracle_index"]]
        assert oracle["current_state"] == "open_unexecuted"
        assert oracle["evidence"] == []
        assert oracle["execution_bounds"]["executor"] is None
        assert oracle["execution_bounds"]["collectors"] == []


def test_canonical_oracle_digest_drift_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    canonical["oracles"][162]["execution_bounds"]["max_duration_seconds"] += 1
    with pytest.raises(compiler.AuditError, match="canonical oracle digest drift"):
        compiler.compile_audit(contract, canonical)


def test_closed_state_is_rejected_even_when_digest_is_rebased(inputs):
    contract, canonical = copy.deepcopy(inputs)
    case = contract["cases"][0]
    oracle = canonical["oracles"][case["canonical_oracle_index"]]
    oracle["current_state"] = "verified"
    case["canonical_oracle_sha256"] = compiler._sha256(
        compiler._canonical_bytes(oracle)
    )
    with pytest.raises(compiler.AuditError, match="must remain open"):
        compiler.compile_audit(contract, canonical)


def test_materialized_executor_baseline_is_rejected_even_when_rebased(inputs):
    contract, canonical = copy.deepcopy(inputs)
    case = contract["cases"][0]
    oracle = canonical["oracles"][case["canonical_oracle_index"]]
    oracle["execution_bounds"]["executor"] = "unsafe.py"
    case["canonical_oracle_sha256"] = compiler._sha256(
        compiler._canonical_bytes(oracle)
    )
    with pytest.raises(compiler.AuditError, match="generic unimplemented"):
        compiler.compile_audit(contract, canonical)


def test_two_request_baseline_change_is_rejected_even_when_rebased(inputs):
    contract, canonical = copy.deepcopy(inputs)
    case = contract["cases"][0]
    oracle = canonical["oracles"][case["canonical_oracle_index"]]
    oracle["execution_bounds"]["max_requests"] = 8
    oracle["execution_bounds"]["workload"]["calculated_max_requests"] = 8
    case["canonical_oracle_sha256"] = compiler._sha256(
        compiler._canonical_bytes(oracle)
    )
    with pytest.raises(compiler.AuditError, match="two-request baseline"):
        compiler.compile_audit(contract, canonical)


def test_missing_canonical_basis_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    contract["cases"][0]["positive_steps"][0]["canonical_basis"] = [
        "/fixture/input/contract/not-real"
    ]
    with pytest.raises(compiler.AuditError, match="does not resolve"):
        compiler.compile_audit(contract, canonical)


def test_request_cost_understatement_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    contract["cases"][0]["positive_steps"][0]["request_cost"] = 0
    with pytest.raises(compiler.AuditError, match="derived budget drift"):
        compiler.compile_audit(contract, canonical)


def test_removed_action_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    contract["cases"][2]["positive_steps"].pop()
    with pytest.raises(compiler.AuditError, match="derived budget drift"):
        compiler.compile_audit(contract, canonical)


def test_duplicate_workflow_step_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    contract["cases"][0]["positive_steps"][1]["id"] = "qa-mp4"
    with pytest.raises(compiler.AuditError, match="step IDs must be unique"):
        compiler.compile_audit(contract, canonical)


def test_case_reordering_is_rejected(inputs):
    contract, canonical = copy.deepcopy(inputs)
    contract["cases"][0], contract["cases"][1] = (
        contract["cases"][1],
        contract["cases"][0],
    )
    with pytest.raises(compiler.AuditError, match="ordered 20-case denominator"):
        compiler.compile_audit(contract, canonical)


def test_warehouse_fixture_is_rejected_even_when_digest_is_rebased(inputs):
    contract, canonical = copy.deepcopy(inputs)
    case = contract["cases"][0]
    oracle = canonical["oracles"][case["canonical_oracle_index"]]
    oracle["fixture"]["warehouse_sample_bundle"] = True
    case["canonical_oracle_sha256"] = compiler._sha256(
        compiler._canonical_bytes(oracle)
    )
    with pytest.raises(compiler.AuditError, match="Warehouse fixture"):
        compiler.compile_audit(contract, canonical)


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers():
    with pytest.raises(compiler.AuditError, match="duplicate JSON key"):
        compiler._strict_json_bytes(b'{"a":1,"a":2}', "adversarial")
    with pytest.raises(compiler.AuditError, match="non-finite"):
        compiler._strict_json_bytes(b'{"a":NaN}', "adversarial")


def test_contract_and_result_schemas_are_strict(inputs):
    contract, canonical = inputs
    contract_schema = load_json("contract.schema.json")
    result_schema = load_json("result.schema.json")
    Draft202012Validator.check_schema(contract_schema)
    Draft202012Validator.check_schema(result_schema)
    assert not list(Draft202012Validator(contract_schema).iter_errors(contract))
    result = compiler.compile_audit(contract, canonical)
    assert not list(Draft202012Validator(result_schema).iter_errors(result))
    bad = copy.deepcopy(contract)
    bad["unexpected"] = True
    assert list(Draft202012Validator(contract_schema).iter_errors(bad))


def test_committed_artifact_matches_compilation(inputs):
    expected = compiler._canonical_bytes(compiler.compile_audit(*inputs)) + b"\n"
    assert (PACKAGE / "proposed-overrides.json").read_bytes() == expected


def test_compiler_imports_are_static_only():
    tree = ast.parse((PACKAGE / "compiler.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "pathlib",
        "stat",
        "sys",
        "typing",
        "jsonschema",
    }
    assert imported.isdisjoint({"subprocess", "socket", "urllib", "requests", "docker"})


def test_unsafe_repo_paths_are_rejected():
    with pytest.raises(compiler.AuditError, match="unsafe repository path"):
        compiler._repo_file("../outside.json")
