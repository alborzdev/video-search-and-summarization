from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
FUTURE_ORACLES = (
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/post-state-capability-oracles.json"
)


def load_executor() -> ModuleType:
    path = PACKAGE / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "synthetic_data_runtime_executor", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def test_contract_schema_and_exact_four_capability_bindings() -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text())
    schema = json.loads((PACKAGE / "contract.schema.json").read_text())
    Draft202012Validator(schema).validate(contract)
    assert [
        row["capability_id"] for row in contract["capabilities"]
    ] == EXECUTOR.EXPECTED_CAPABILITIES
    assert len({row["generated_input_sha256"] for row in contract["capabilities"]}) == 4
    assert (
        len({row["fixture_manifest"]["sha256"] for row in contract["capabilities"]})
        == 4
    )
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"
    assert contract["policy"]["network_allowed"] is False


def test_inert_plan_is_schema_valid_and_nonpromoting() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    result = EXECUTOR.plan(contract)
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    assert result["status"] == "plan"
    assert len(result["capability_results"]) == 4
    assert result["promotion"]["ledger_mutation_performed"] is False
    assert result["confinement"]["network_calls"] == 0


def test_current_planning_rows_cannot_authorize_promotable_receipt() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    with pytest.raises(EXECUTOR.EvidenceError, match="not exact executor-ready"):
        EXECUTOR.verify_bindings(
            contract,
            require_clean=False,
            require_executor_ready=True,
        )


def test_future_rows_are_exact_executor_ready_receipt_authority() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    bindings = EXECUTOR.verify_bindings(
        contract,
        require_clean=False,
        oracle_document=FUTURE_ORACLES,
        require_executor_ready=True,
    )
    assert bindings["execution_oracles_executor_ready"] is True
    assert bindings["execution_oracle_fixture_sha256"] == {
        row["capability_id"]: row["fixture_manifest"]["sha256"]
        for row in contract["capabilities"]
    }


def test_all_locked_sources_match_current_checkout() -> None:
    contract = EXECUTOR.strict_json(PACKAGE / "contract.json")
    for capability in contract["capabilities"]:
        for lock in capability["source_controls"]:
            assert EXECUTOR.sha_file(REPO_ROOT / lock["path"]) == lock["sha256"]
        fixture_lock = capability["fixture_manifest"]
        assert (
            EXECUTOR.sha_file(REPO_ROOT / fixture_lock["path"])
            == fixture_lock["sha256"]
        )


@pytest.mark.skipif(
    os.environ.get("VSS_RUN_SDG_RUNTIME_EVIDENCE") != "1",
    reason="explicit native runtime evidence opt-in required",
)
def test_full_nonpromoting_native_execution(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            "python3",
            str(PACKAGE / "executor.py"),
            "--execute",
            "--allow-dirty-development",
            "--oracle-document",
            str(FUTURE_ORACLES),
            "--acknowledge",
            EXECUTOR.ACK,
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text())
    future = json.loads(FUTURE_ORACLES.read_text())
    future_by_id = {row["capability_id"]: row for row in future["oracles"]}
    assert receipt["status"] == "pass"
    assert receipt["promotion"]["receipt_is_runtime_evidence"] is False
    assert [row["status"] for row in receipt["capability_results"]] == ["pass"] * 4
    assert all(row["deterministic_output"] for row in receipt["capability_results"])
    assert all(
        row["cleanup"]["namespace"]
        == future_by_id[row["capability_id"]]["cleanup"]["targets"][0]
        for row in receipt["capability_results"]
    )
