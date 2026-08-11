from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("video_analytics_va_mcp_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_compiled_receipt_is_exactly_checked_in() -> None:
    assert compiler._load(HERE / "runtime-receipt.json") == compiler.build_receipt()


def test_receipt_is_schema_valid_and_bound_to_nine_rows() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    schema = compiler._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == compiler._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [397, 398, 399, 400, 401, 402, 403, 404, 467]


def test_complete_http_and_read_only_mcp_surfaces_are_proven() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert receipt["video_analytics_api"]["openapi_operations"] == 56
    assert receipt["video_analytics_api"]["data_bearing_gets_nonempty"] == 40
    assert receipt["video_analytics_api"]["http_5xx"] == 0
    assert receipt["va_mcp"]["tool_count"] == 9
    assert receipt["va_mcp"]["read_only_unique_tools"] == 8
    assert receipt["va_mcp"]["all_succeeded"] is True


def test_cleanup_and_policy_are_exact() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert all(receipt["cleanup"].values())
    assert receipt["policy"]["agent_generate_calls"] == 0
    assert receipt["policy"]["react_agent_calls"] == 0
    assert receipt["policy"]["warehouse_sample_bundle"] == "excluded"
