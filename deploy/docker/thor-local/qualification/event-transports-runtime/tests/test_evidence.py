from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "event_transport_runtime_verify", HERE / "verify.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_retained_receipt_is_complete_bounded_and_clean() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(raw)
    assert receipt["status"] == "passed"
    assert receipt["semantic_action_count"] == 4
    assert receipt["forbidden_actions_observed"] == []
    assert receipt["runtime"]["kafka"]["positive"]["record_count"] == 1
    assert receipt["runtime"]["kafka"]["negative"]["record_published"] is False
    assert receipt["runtime"]["redis"]["positive"]["pending_after_xack"] == 0
    assert (
        receipt["runtime"]["redis"]["negative"]["entry_pending_before_cleanup"]
        == 1
    )
    assert receipt["cleanup"]["failures"] == []


def test_official_projections_are_reproducible_and_fail_closed() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["official_capability_count"] == 289
    assert result["capability_ids"] == [
        "protocol.kafka.nvschema",
        "protocol.redis.events",
    ]
