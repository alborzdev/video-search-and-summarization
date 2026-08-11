from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_rest_current_runtime_capability_evidence_builder",
    HERE / "build_capability_evidence.py",
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def test_canonical_projection_is_byte_exact_and_semantically_bound() -> None:
    evidence = builder.build()
    raw = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    assert raw == builder.OUTPUT_PATH.read_bytes()
    values = {row["id"]: row["value"] for row in evidence["observations"]}
    assert values["semantic_result"]["operation_count"] == 18
    assert values["semantic_result"]["operation_set_exact"] is True
    assert values["semantic_result"]["all_positive_semantic_pass"] is True
    assert len(values["semantic_result"]["adjacent_negatives"]) == 6
    assert values["semantic_result"]["recorded_video"]["graph_qa"] is True
    assert values["semantic_result"]["live_video"]["stream_summary"] is True
    assert values["api_contract"]["auth"]["declared"] == "bearer"
    assert values["api_contract"]["auth"]["enforced_by_lvs"] is False
    assert all(values["api_contract"]["cleanup"].values())
    assert evidence["cleanup"]["result"] == "pass"
