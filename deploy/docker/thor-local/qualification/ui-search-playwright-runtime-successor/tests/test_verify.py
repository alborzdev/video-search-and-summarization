from __future__ import annotations

import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ui_search_verify", HERE / "verify.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_retained_receipt_is_valid_partial_evidence() -> None:
    MODULE.verify()


def test_harness_is_default_inert_and_uses_isolated_playwright() -> None:
    source = (HERE / "harness.mjs").read_text(encoding="utf-8")
    assert "const mode = process.argv[2] || 'plan'" in source
    assert "chromium.launch" in source
    assert "browser.close" in source
    assert "connectOverCDP" not in source
    assert "/generate" not in source


def test_contract_cannot_promote_the_incomplete_image_path() -> None:
    contract = MODULE.load("contract.json")
    assert contract["evidence_scope"]["promotion_eligible"] is False
    assert contract["evidence_scope"]["canonical_state_advanced"] is False
    assert "selected-object-image-knn" in contract["open_facets"]
    assert contract["runtime_boundary"]["warehouse_sample_bundle"] == "excluded"


def test_receipt_retains_no_raw_query_prompt_ids_or_urls() -> None:
    receipt = MODULE.load("runtime-receipt.json")
    serialized = json.dumps(receipt, sort_keys=True).lower()
    for forbidden in (
        "request_id",
        "session_id",
        "conversation_id",
        "sensor_id",
        "screenshot_url",
        "raw_prompt",
        "raw_query",
        "http://",
        "https://",
        "ws://",
        "wss://",
    ):
        assert forbidden not in serialized
