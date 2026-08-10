from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_websocket_runtime_verify", HERE / "verify.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def _load(name: str) -> dict:
    value = json.loads((HERE / name).read_text())
    assert isinstance(value, dict)
    return value


def test_retained_receipt_is_complete_bounded_and_content_free() -> None:
    receipt_raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(receipt_raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(receipt_raw)
    positive = receipt["runtime"]["positive"]
    negative = receipt["runtime"]["adjacent_negative"]
    assert receipt["status"] == "passed"
    assert receipt["semantic_action_count"] == 2
    assert receipt["forbidden_actions_observed"] == []
    assert positive["handshake_http_status"] == 101
    assert positive["complete_terminal_count"] == 1
    assert positive["frames"][-1]["status"] == "complete"
    assert negative["missing_conversation_rejected"] is True
    assert receipt["cleanup"]["failures"] == []
    VERIFY._verify_retention_boundary(
        (HERE / "contract.json").read_bytes(),
        receipt_raw,
        (HERE / "official-runtime-evidence.json").read_bytes(),
    )


def test_receipt_schema_rejects_raw_response_content() -> None:
    receipt = _load("runtime-receipt.json")
    schema = _load("receipt.schema.json")
    mutated = copy.deepcopy(receipt)
    mutated["runtime"]["positive"]["raw_text"] = "not-retainable"
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_receipt_schema_rejects_false_cleanup() -> None:
    receipt = _load("runtime-receipt.json")
    schema = _load("receipt.schema.json")
    mutated = copy.deepcopy(receipt)
    mutated["cleanup"]["related_runtime_exact"] = False
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_official_projection_and_current_bindings_are_reproducible() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["official_capability_count"] == 289
    assert result["oracle_count"] == 289
    assert result["capability_id"] == "protocol.agent.websocket"
