from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "alert_websocket_runtime_verify", HERE / "verify.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_retained_receipt_is_complete_bounded_and_clean() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(raw)
    assert receipt["status"] == "passed"
    assert receipt["semantic_action_count"] == 2
    assert receipt["forbidden_actions_observed"] == []
    assert receipt["runtime"]["positive"]["alert_frame_count"] == 1
    assert receipt["runtime"]["positive"]["pending_after_callback"] == 0
    assert receipt["runtime"]["negative"]["socket_remained_open"] is True
    assert receipt["runtime"]["connection_cleanup"]["connection_removed"] is True
    assert receipt["cleanup"]["failures"] == []


def test_official_projection_is_reproducible_and_fail_closed() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["official_capability_count"] == 289
    assert result["capability_id"] == "protocol.alert.websocket"
