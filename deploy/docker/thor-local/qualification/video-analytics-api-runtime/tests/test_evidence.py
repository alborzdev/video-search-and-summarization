from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "video_analytics_runtime_verify", HERE / "verify.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_retained_receipt_is_complete_and_bounded() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(raw)
    assert receipt["status"] == "passed"
    assert receipt["request_counts"] == {
        "total": 71,
        "positive": 60,
        "negative": 8,
        "status_5xx": 0,
    }
    assert receipt["operations"]["get"]["exercised"] == 48
    assert receipt["operations"]["post"]["exercised"] == 8
    assert receipt["operations"]["post_negatives"]["exercised"] == 8
    assert receipt["operations"]["brokerless"]["livez_http_status"] == 200
    assert receipt["cleanup"]["failures"] == []


def test_official_projections_are_fail_closed() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["official_capability_count"] == 289
    assert result["capability_ids"] == [
        "behavior.video-analytics.optional-kafka",
        "runtime.video-analytics.query-and-library-contract",
    ]
