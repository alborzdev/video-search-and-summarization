from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_content_type_capability_evidence_builder",
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
    assert observations["semantic_result"]["accepted_media_types"] == [
        "video/mp4",
        "video/x-matroska",
    ]
    assert observations["semantic_result"]["positive_statuses"] == [200, 200]
    assert observations["semantic_result"]["chunks_processed"] == [1, 1]
    assert observations["boundary_pair"]["missing_status"] == 400
    assert observations["boundary_pair"]["unsupported_status"] == 400
    assert observations["boundary_pair"]["inventory_restored"] is True
    assert observations["boundary_pair"]["runtime_unchanged"] is True
    assert evidence["cleanup"]["result"] == "pass"
