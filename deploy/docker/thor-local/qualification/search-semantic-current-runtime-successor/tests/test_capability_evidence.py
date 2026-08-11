from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_semantic_capability_evidence_builder",
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
    assert observations["semantic_result"]["canonical_routes_observed"] == [
        "/api/v1/search",
        "/api/v1/search/attribute",
        "/api/v1/search/fusion",
        "/api/v1/search/image",
    ]
    assert observations["semantic_result"]["selected_object_seed_excluded"] is True
    assert observations["boundary_pair"]["adjacent_invalid_status"] == 422
    assert observations["boundary_pair"]["owned_indices_absent_twice"] is True
    assert evidence["cleanup"]["result"] == "pass"
