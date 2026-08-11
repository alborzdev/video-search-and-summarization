from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_events_incidents_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [206]


def test_tripwire_and_roi_directional_events_are_observed() -> None:
    events = verifier.verify()["base_2d_evidence"]["events"]
    assert events["types"] == {
        "roi:ENTRY": 56,
        "roi:EXIT": 53,
        "tripwire:IN": 6,
        "tripwire:OUT": 6,
    }
    assert sum(events["types"].values()) == events["total"] == 121


def test_all_four_advertised_violation_classes_are_observed() -> None:
    receipt = verifier.verify()
    categories = set(receipt["base_2d_evidence"]["incidents"]["categories"])
    categories.update(receipt["fov_runtime"]["incidents"]["categories"])
    assert categories == {
        "Confined Area Violation",
        "FOV Count Violation",
        "Proximity Violation",
        "Restricted Area Violation",
    }
    assert receipt["fov_runtime"]["incidents"]["count"] > 0


def test_fov_identity_exit_integrity_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    fov = receipt["fov_runtime"]
    assert fov["incidents"]["count"] == len(fov["incidents"]["object_id_counts"])
    assert fov["incidents"]["all_start_before_or_equal_end"] is True
    assert fov["incidents"]["positive_time_bounds"] is True
    assert fov["incidents"]["observation_state"] == "ongoing_at_capture"
    assert fov["container"] == {"exit_code": 0, "oom_killed": False, "restart_count": 0}
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["warehouse_sample_bundle"] == "excluded"
