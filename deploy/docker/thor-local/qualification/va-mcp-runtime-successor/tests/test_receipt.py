from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("va_mcp_runtime_harness", HERE / "harness.py")
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def test_receipt_is_schema_valid_and_contract_bound() -> None:
    receipt = harness._load(HERE / "runtime-receipt.json")
    harness._validate(receipt)


def test_complete_read_only_surface_was_exercised() -> None:
    receipt = harness._load(HERE / "runtime-receipt.json")
    assert receipt["tool_surface"]["tool_count"] == 9
    assert receipt["queries"]["unique_tool_count"] == 8
    assert receipt["queries"]["tool_call_count"] == 9
    assert receipt["queries"]["all_succeeded"] is True
    assert receipt["queries"]["incidents"]["count"] >= 1
    assert receipt["queries"]["specific_incident"]["matched_first_incident"] is True


def test_query_run_was_read_only() -> None:
    receipt = harness._load(HERE / "runtime-receipt.json")
    assert receipt["state"] == {
        "docker_running_set_exact": True,
        "vst_sensor_set_exact": True,
        "writes_observed": False,
    }
    assert receipt["policy"]["react_agent_calls"] == 0
    assert receipt["policy"]["agent_generate_calls"] == 0
