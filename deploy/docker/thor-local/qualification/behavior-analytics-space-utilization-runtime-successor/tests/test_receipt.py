from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_space_utilization_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [209]


def test_every_advertised_metric_has_positive_runtime_values() -> None:
    outputs = verifier.verify()["outputs"]
    assert set(outputs["positive_records"]) == {
        "occupied", "free", "total", "ratio", "extra_pallets", "utilizable_free_space"
    }
    assert all(value > 0 for value in outputs["positive_records"].values())
    assert all(bounds[1] > 0 for bounds in outputs["ranges"].values())


def test_three_zones_layouts_and_arithmetic_are_proven() -> None:
    outputs = verifier.verify()["outputs"]
    assert outputs["zone_ids"] == ["buffer_zone_1", "buffer_zone_2", "buffer_zone_3"]
    assert outputs["free_layout_records"] == outputs["output_count"]
    assert outputs["utilizable_layout_records"] == outputs["output_count"]
    assert outputs["free_plus_occupied_max_error"] <= 0.02
    assert outputs["ratio_max_error"] <= 0.02


def test_exit_integrity_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    assert receipt["container"] == {"exit_code": 0, "oom_killed": False, "restart_count": 0}
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
