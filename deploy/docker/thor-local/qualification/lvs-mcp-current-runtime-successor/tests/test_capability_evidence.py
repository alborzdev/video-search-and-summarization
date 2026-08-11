from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lvs_mcp_current_runtime_capability_evidence_builder",
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
    assert observations["contract_identity"]["contract"]["docs_tool_count"] == 13
    assert (
        observations["contract_identity"]["contract"]["upstream_repository_tool_count"]
        == 9
    )
    assert observations["semantic_result"]["tool_count"] == 13
    assert observations["semantic_result"]["all_tools_have_schemas"] is True
    assert observations["semantic_result"]["inference_tool_calls"] == 0
    assert observations["api_contract"]["list_after_add_exact"] is True
    assert observations["api_contract"]["get_info_exact"] is True
    assert observations["api_contract"]["delete_confirmation_exact"] is True
    assert observations["api_contract"]["mcp_catalog_restored"] is True
    assert observations["api_contract"]["rest_catalog_restored"] is True
    assert observations["api_contract"]["media_root_restored"] is True
    assert evidence["cleanup"]["result"] == "pass"
