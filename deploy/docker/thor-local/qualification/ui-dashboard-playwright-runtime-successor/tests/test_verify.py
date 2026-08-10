from __future__ import annotations

import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ui_dashboard_verify", HERE / "verify.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

EVIDENCE_SPEC = importlib.util.spec_from_file_location(
    "ui_dashboard_build_official_evidence", HERE / "build_official_evidence.py"
)
assert EVIDENCE_SPEC and EVIDENCE_SPEC.loader
EVIDENCE_MODULE = importlib.util.module_from_spec(EVIDENCE_SPEC)
EVIDENCE_SPEC.loader.exec_module(EVIDENCE_MODULE)


def test_retained_receipt_is_valid() -> None:
    MODULE.verify()


def test_harness_is_default_inert_and_never_launches_a_browser() -> None:
    source = (HERE / "harness.mjs").read_text(encoding="utf-8")
    assert 'argv[0] === "plan"' in source
    assert "connectOverCDP" in source
    assert ".launch(" not in source
    assert "browser.close(" not in source


def test_contract_is_read_only_and_warehouse_free() -> None:
    contract = MODULE.load("contract.json")
    boundary = contract["runtime_boundary"]
    assert boundary["persistent_mutation"] is False
    assert boundary["starts_or_stops_processes"] is False
    assert boundary["warehouse_sample_bundle"] == "excluded"


def test_official_evidence_projection_has_no_drift() -> None:
    expected = EVIDENCE_MODULE.build()
    retained = json.loads(
        (HERE / "official-runtime-evidence.json").read_text(encoding="utf-8")
    )
    assert retained == expected


def test_official_evidence_contains_no_raw_browser_payloads() -> None:
    retained = json.loads(
        (HERE / "official-runtime-evidence.json").read_text(encoding="utf-8")
    )
    serialized = json.dumps(retained, sort_keys=True)
    for forbidden in (
        "captured_at",
        "diagnostic_hashes",
        "response_status_counts",
        "console_error_count",
        "page_error_count",
        "/internal/security/user_profile",
    ):
        assert forbidden not in serialized
