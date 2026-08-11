from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ui_search_capability_evidence_builder",
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
    observations = {row["id"]: row["value"] for row in evidence["observations"]}
    assert observations["semantic_result"]["source_values"] == [
        "Video File",
        "RTSP",
    ]
    assert observations["semantic_result"]["critic_rendered_order"] == [
        "confirmed",
        "unverified",
        "rejected",
    ]
    assert observations["boundary_pair"]["below_minimum_top_k_clamped"] is True
    assert observations["boundary_pair"]["desktop_horizontal_overflow"] is False
    assert observations["boundary_pair"]["mobile_horizontal_overflow"] is False
    assert observations["boundary_pair"]["unexpected_browser_failures"] == 0
    assert evidence["cleanup"]["mutation"] == "read_only"
