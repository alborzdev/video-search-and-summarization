from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("alert_websocket_manifest_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_compiled_receipt_is_exactly_checked_in() -> None:
    assert compiler._load(HERE / "runtime-receipt.json") == compiler.build_receipt()


def test_receipt_is_schema_valid_and_bound_to_two_rows() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    schema = compiler._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == compiler._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [53, 333]


def test_websocket_delivery_and_adjacent_negative_are_real() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert receipt["delivery"]["frames"] == ["pong", "alert", "status"]
    assert receipt["delivery"]["alert_frame_count"] == 1
    assert receipt["delivery"]["pending_after_callback"] == 0
    assert receipt["negative"]["application_response_observed"] is False
    assert receipt["negative"]["socket_remained_open"] is True


def test_cleanup_and_exclusions_are_exact() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert receipt["cleanup"]["active_connections_after_close"] == 0
    assert all(
        value is True
        for key, value in receipt["cleanup"].items()
        if key != "active_connections_after_close"
    )
    assert receipt["policy"]["agent_generate_calls"] == 0
    assert receipt["policy"]["slack_dependency"] == "excluded"
