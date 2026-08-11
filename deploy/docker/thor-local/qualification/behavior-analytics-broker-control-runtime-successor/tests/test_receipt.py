from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_broker_control_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [396]


def test_all_three_brokers_ack_and_retain_distinct_versions() -> None:
    receipt = verifier.verify()
    assert set(receipt["backends"]) == {"kafka", "redis", "mqtt"}
    for name, backend in receipt["backends"].items():
        assert backend["ack_status"] == "success"
        assert backend["dynamic_calibration_version"] == f"qualification-{name}-2.0"
        assert [item["behavior_max_points"] for item in backend["checkpoint"]["config"]] == ["200", "3"]


def test_updates_apply_to_subsequent_frames_on_every_backend() -> None:
    receipt = verifier.verify()
    for backend in receipt["backends"].values():
        output = backend["post_update"]
        assert output["enhanced_frames"] > 0
        assert output["behaviors"] > 0
        assert output["max_behavior_points"] == 3
        assert output["frames_with_fov_metrics"] == output["enhanced_frames"]
        assert output["frames_with_roi_metrics"] == output["enhanced_frames"]


def test_exit_integrity_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    for backend in receipt["backends"].values():
        assert backend["container"]["exit_code"] == 0
        assert backend["container"]["oom_killed"] is False
        assert backend["container"]["restart_count"] == 0
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
