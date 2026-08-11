from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_pipeline_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [203]


def test_every_object_carries_all_three_advertised_inputs() -> None:
    pipeline_input = verifier.verify()["input"]
    assert pipeline_input["objects"] == 4417
    assert pipeline_input["bbox_objects"] == pipeline_input["objects"]
    assert pipeline_input["tracking_id_objects"] == pipeline_input["objects"]
    assert pipeline_input["embedded_objects"] == pipeline_input["objects"]
    assert pipeline_input["embedding_dimensions"] == [4]


def test_all_six_advertised_stages_and_output_continuity_are_proven() -> None:
    receipt = verifier.verify()
    assert all(receipt["stage_coverage"].values())
    assert receipt["outputs"]["frames"] == receipt["input"]["frames"] == 600
    assert receipt["outputs"]["behaviors_with_embeddings"] == receipt["outputs"]["behaviors"]
    assert receipt["outputs"]["behaviors_with_locations"] == receipt["outputs"]["behaviors"]
    assert receipt["outputs"]["positive_roi_metric_entries"] > 0
    assert receipt["outputs"]["positive_fov_metric_entries"] > 0


def test_dynamic_control_exit_integrity_and_cleanup_are_exact() -> None:
    receipt = verifier.verify()
    assert receipt["control"]["ack_status"] == "success"
    assert receipt["outputs"]["max_behavior_points"] == 3
    assert receipt["runtime"]["container"] == {
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
    }
    assert receipt["cleanup"]["container_absent"] is True
    assert receipt["cleanup"]["backend_records_absent"] is True
    assert receipt["cleanup"]["failures"] == []
