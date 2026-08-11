from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import time

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sealed_receipt_verifies() -> None:
    result = _module("search_content_type_verify_test", "verify.py").verify()
    assert result == {
        "package_id": "thor-search-content-type-current-runtime-successor-v1",
        "status": "passed",
        "http_requests": 40,
        "persistent_mutations": 4,
        "positive_cases": 2,
        "negative_cases": 2,
        "promotion_eligible": True,
        "warehouse_sample_bundle": "excluded",
    }


def test_wrong_acknowledgement_fails_before_runtime() -> None:
    executor = _module("search_content_type_executor_ack_test", "executor.py")
    contract = executor._load_json(HERE / "contract.json")
    with pytest.raises(executor.QualificationError, match="authorization_required"):
        executor._execute(contract, "wrong")


def test_http_client_rejects_non_loopback_origin_before_transport() -> None:
    executor = _module("search_content_type_executor_origin_test", "executor.py")
    contract = executor._load_json(HERE / "contract.json")
    contract["targets"]["agent"] = "http://example.invalid:8100"
    client = executor.LocalHttp(contract, time.monotonic() + 1)
    with pytest.raises(executor.QualificationError, match="configuration_error"):
        client.call(
            operation="external_origin",
            target="agent",
            method="GET",
            path="/health",
        )


def test_receipt_retains_no_raw_runtime_identity_fields() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert not re.search(rb'"sensor_id"\s*:', raw)
    assert not re.search(rb'"request_id"\s*:', raw)
    assert not re.search(rb'"session_id"\s*:', raw)
    assert b"nvapi-" not in raw
