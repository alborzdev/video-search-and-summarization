from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "thor_architecture_gap_validator", LANE / "validator.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def _contract() -> dict:
    return json.loads((LANE / "contract.json").read_text(encoding="utf-8"))


def _decision(contract: dict) -> dict:
    rows = []
    for row in contract["rows"]:
        required = row["required_design"]
        rows.append(
            {
                "id": row["id"],
                "selected_design_id": required["design_id"],
                "planned_changes": required["required_changes"],
                "acknowledged_forbidden_shortcuts": required["forbidden_shortcuts"],
                "runtime_evidence": [],
                "can_claim_runtime_qualified": False,
            }
        )
    return {
        "schema_version": 1,
        "package_id": "thor-architecture-gap-contracts-v1",
        "record_type": "implementation_decision",
        "decision_id": "thor-gap-decision.test-v1",
        "target_commit": "a" * 40,
        "rows": rows,
        "can_claim_runtime_qualified": False,
    }


def _write_temp_json(value: dict) -> Path:
    temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    with temporary:
        json.dump(value, temporary)
    return Path(temporary.name)


def test_static_contract_and_all_ten_source_locks_pass() -> None:
    result = validator.check()
    assert result == {
        "valid": True,
        "package_id": "thor-architecture-gap-contracts-v1",
        "row_count": 4,
        "source_lock_count": 10,
        "runtime_actions_performed": False,
        "can_claim_runtime_qualified": False,
    }


def test_rejects_amc_as_manual_legacy_substitute() -> None:
    contract = _contract()
    manual = contract["rows"][0]
    manual["required_design"]["implementation_kind"] = "amc"
    manual["required_design"]["forbidden_shortcuts"].remove(
        "claim_AMC_is_the_legacy_manual_calibration_toolkit"
    )
    with pytest.raises(validator.ContractError, match="AMC/legacy|native legacy"):
        validator._validate_contract_semantics(contract)


def test_rejects_svg_as_official_google_maps_parity() -> None:
    contract = _contract()
    gis = contract["rows"][1]
    gis["required_design"]["forbidden_shortcuts"].remove(
        "claim_provider_free_SVG_is_the_official_Google_Maps_UI"
    )
    with pytest.raises(validator.ContractError, match="Google Maps/provider-free"):
        validator._validate_contract_semantics(contract)


def test_rejects_static_or_single_process_alert_scaling_design() -> None:
    contract = _contract()
    alerts = contract["rows"][2]
    alerts["required_design"]["required_changes"].remove(
        "move_scaled_workers_off_shared_host_networking"
    )
    alerts["acceptance"]["minimum_runtime_replicas"] = 1
    with pytest.raises(
        validator.ContractError, match="alert replica topology|two runtime"
    ):
        validator._validate_contract_semantics(contract)


def test_rejects_vios_design_that_keeps_name_port_or_scales_sensor() -> None:
    contract = _contract()
    vios = contract["rows"][3]
    vios["required_design"]["required_changes"].remove(
        "keep_exactly_one_sensor_service_instance"
    )
    with pytest.raises(validator.ContractError, match="VIOS topology"):
        validator._validate_contract_semantics(contract)


def test_valid_planning_decision_remains_non_promoting() -> None:
    contract = _contract()
    path = _write_temp_json(_decision(contract))
    try:
        result = validator.validate_decision(path)
    finally:
        path.unlink()
    assert result["valid"] is True
    assert result["runtime_evidence_count"] == 0
    assert result["can_claim_runtime_qualified"] is False
    assert result["status_effect"] == "none"


def test_decision_cannot_select_amc_or_keep_only_static_compose() -> None:
    contract = _contract()
    decision = _decision(contract)
    decision["rows"][0]["selected_design_id"] = "reuse-amc-v1"
    decision["rows"][2]["planned_changes"] = [
        "increase_num_workers_in_static_config",
        *decision["rows"][2]["planned_changes"][1:],
    ]
    path = _write_temp_json(decision)
    try:
        with pytest.raises(
            validator.ContractError, match="unapproved implementation design"
        ):
            validator.validate_decision(path)
    finally:
        path.unlink()


def test_acceptance_schema_rejects_static_only_receipt() -> None:
    _, _, acceptance_schema = validator._load_static()
    receipt = {
        "schema_version": 1,
        "package_id": "thor-architecture-gap-contracts-v1",
        "record_type": "authorized_runtime_acceptance",
        "receipt_id": "static-only.invalid",
        "authorization_id": "AUTH:test:0001",
        "implementation_commit": "b" * 40,
        "started_at": "2026-08-01T10:00:00Z",
        "finished_at": "2026-08-01T10:01:00Z",
        "warehouse_sample_used": False,
        "rows": [],
    }
    with pytest.raises(validator.ContractError, match="schema violation"):
        validator._validate_schema(receipt, acceptance_schema, "test receipt")


def test_validator_has_no_live_action_imports() -> None:
    source = (LANE / "validator.py").read_text(encoding="utf-8")
    for forbidden in (
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib",
        "import docker",
        "os.system",
    ):
        assert forbidden not in source


def test_duplicate_json_keys_and_nonfinite_numbers_fail_closed() -> None:
    with pytest.raises(validator.ContractError, match="duplicate JSON key"):
        validator._strict_json(b'{"id": 1, "id": 2}', "duplicate")
    with pytest.raises(validator.ContractError, match="non-finite"):
        validator._strict_json(b'{"value": NaN}', "nonfinite")
