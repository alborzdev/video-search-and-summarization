from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_dynamic_control_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [204, 205]


def test_all_official_dynamic_configuration_scenarios_passed() -> None:
    config = verifier.verify()["dynamic_configuration"]
    assert config["official_driver_scenarios"] == config["passed"] == 24
    assert config["failed"] == 0
    assert set(config["ack_statuses"]) == {"success", "partial-success", "failure"}
    assert all(value == "passed" for value in config["startup_paths"].values())
    assert config["timeout_probe"]["fallback_marker_found"] is True


def test_all_official_dynamic_calibration_scenarios_and_types_passed() -> None:
    calibration = verifier.verify()["dynamic_calibration"]
    assert calibration["official_driver_scenarios"] == calibration["passed"] == 7
    assert calibration["failed"] == 0
    assert {name: probe["implementation"] for name, probe in calibration["type_selection"].items()} == {
        "image": "CalibrationI",
        "cartesian": "CalibrationE",
        "geo": "Calibration",
    }
    assert calibration["invalid_payload_changed_state"] is False
    assert calibration["stale_timestamp_changed_state"] is False


def test_existing_calibration_type_is_immutable_and_cleanup_is_exact() -> None:
    receipt = verifier.verify()
    boundary = receipt["dynamic_calibration"]["immutable_existing_type"]
    assert boundary["initial_implementation"] == boundary["delegated_to"] == "CalibrationE"
    assert boundary["update_payload_type"] == "image"
    assert boundary["type_switch_markers_after_update"] == 0
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
