from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "headline_cosmos_smartcity_executor", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def _write_contract(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_default_execution_passes_without_runtime_promotion() -> None:
    result = executor.execute()
    assert result["status"] == "pass"
    assert result["scope"] == "static_only"
    assert result["runtime_evidence_created"] is False
    assert result["runtime_state_promoted"] is False
    assert result["warehouse_sample_required"] is False
    assert {item["runtime_state"] for item in result["results"]} == {
        "not_qualified",
        "passed_prior",
    }


def test_execution_is_deterministic() -> None:
    assert executor.execute() == executor.execute()


def test_contract_binds_exact_canonical_ids() -> None:
    contract = _contract()
    assert {item["capability_id"] for item in contract["bindings"]} == (
        executor.CAPABILITY_IDS
    )


def test_schemas_reject_duplicate_or_cross_mapped_rows() -> None:
    contract = _contract()
    contract_schema = executor._load_json(HERE / "contract.schema.json")
    duplicate_contract = copy.deepcopy(contract)
    duplicate_contract["bindings"] = [
        copy.deepcopy(contract["bindings"][0]) for _ in range(3)
    ]
    assert list(
        Draft202012Validator(contract_schema).iter_errors(duplicate_contract)
    )

    result = executor.execute()
    result_schema = executor._load_json(HERE / "result.schema.json")
    duplicate_result = copy.deepcopy(result)
    duplicate_result["results"] = [copy.deepcopy(result["results"][0]) for _ in range(3)]
    assert list(Draft202012Validator(result_schema).iter_errors(duplicate_result))
    assert all(
        item["oracle_id"] == f"oracle.{item['capability_id']}"
        for item in contract["bindings"]
    )


def test_policy_forbids_external_and_runtime_actions() -> None:
    policy = _contract()["policy"]
    assert set(policy.values()) == {False}


def test_selected_static_checks_do_not_spawn_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("subprocess execution is forbidden in this static subset")

    monkeypatch.setattr(subprocess, "run", reject)
    assert executor.execute()["status"] == "pass"


def test_cross_mapped_oracle_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["bindings"][0]["oracle_id"] = (
        "oracle.model.edge.cosmos3-nano-served-id"
    )
    with pytest.raises(executor.QualificationError, match="contract schema validation"):
        executor.execute(_write_contract(tmp_path, contract))


def test_source_digest_drift_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(executor.QualificationError, match="source lock drift"):
        executor.execute(_write_contract(tmp_path, contract))


def test_duplicate_source_lock_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["source_locks"][1] = copy.deepcopy(contract["source_locks"][0])
    with pytest.raises(executor.QualificationError, match="duplicate source lock"):
        executor.execute(_write_contract(tmp_path, contract))


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._load_json(path)


def test_future_evidence_preserves_exact_open_boundaries() -> None:
    blockers = _contract()["future_runtime_evidence"]
    assert len(blockers) == 5
    assert any("/v1/models" in blocker for blocker in blockers)
    assert any("semantic video inference" in blocker for blocker in blockers)
    assert any("component image and artifact versions" in blocker for blocker in blockers)
    assert any("no Warehouse sample bundle required" in blocker for blocker in blockers)


def test_exact_wave6_planning_row_is_bound_and_nonmaterialized() -> None:
    inventory = executor._load_json(executor.WAVE6_INVENTORY)
    row = next(
        item
        for item in inventory["cases"]
        if item["case_id"] == "wave6-source-case.smartcity-version-lock"
    )
    assert row["planning_requirement_id"] == "smartcity-version-lock"
    assert row["capability_id"] == "boundary.smart-city.version-skew"
    assert row["boundary_status"] == "documented_mismatch_preserved"
    assert row["runtime_evidence"] == []
