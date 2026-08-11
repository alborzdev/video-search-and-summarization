from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_analytics_2d_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [392, 393, 394, 395]


def test_full_replay_reconciles_with_decoded_outputs() -> None:
    receipt = verifier.verify()
    assert receipt["input"]["playback_frames"] == 20000
    assert receipt["input"]["playback_objects"] == 171436
    assert receipt["outputs"]["topic_counts"]["vss-oracle-ba-frames"] == 20000
    assert receipt["outputs"]["protobuf_decoded"] is True
    assert set(receipt["input"]["sensor_names"]) == {"Camera", "Camera_01", "Camera_02"}


def test_events_incidents_trajectories_and_occupancy_are_nontrivial() -> None:
    receipt = verifier.verify()
    outputs = receipt["outputs"]
    assert outputs["events"]["types"] == {
        "roi:ENTRY": 56,
        "roi:EXIT": 53,
        "tripwire:IN": 6,
        "tripwire:OUT": 6,
    }
    assert outputs["incidents"]["categories"]["Proximity Violation"] == 95
    assert outputs["trajectories"]["multi_point_count"] == 13084
    assert outputs["trajectories"]["max_points"] == 200
    assert outputs["occupancy"]["fov_positive_count_entries"] == 58323
    assert outputs["occupancy"]["roi_positive_count_entries"] == 32983


def test_proximity_clustering_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    assert receipt["outputs"]["proximity_and_clustering"] == {
        "proximity_detections": 426,
        "cluster_entries": 426,
    }
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
    assert receipt["policy"]["warehouse_sample_bundle"] == "excluded"
