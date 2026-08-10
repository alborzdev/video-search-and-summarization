from __future__ import annotations

import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ui_dashboard_verify", HERE / "verify.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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
