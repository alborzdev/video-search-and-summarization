from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_embedding_downsampling_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [207]


def test_both_advertised_modes_compress_real_protobuf_input() -> None:
    receipt = verifier.verify()
    assert set(receipt["modes"]) == {"sdt", "window"}
    assert receipt["modes"]["sdt"]["output_count"] == 3
    assert receipt["modes"]["window"]["output_count"] == 4
    assert all(mode["output_count"] < mode["input_count"] for mode in receipt["modes"].values())


def test_first_and_novel_transition_are_preserved() -> None:
    receipt = verifier.verify()
    for mode in receipt["modes"].values():
        assert mode["first_point_preserved"] is True
        assert mode["novel_transition_preserved"] is True
        assert mode["output_frame_ids"][0] == "0"
        assert mode["output_frame_ids"][-1] == "12"


def test_exit_integrity_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    assert all(mode["container"]["exit_code"] == 0 for mode in receipt["modes"].values())
    assert all(mode["container"]["oom_killed"] is False for mode in receipt["modes"].values())
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
