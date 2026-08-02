from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("offline_verifier_logdriver", HERE / "compiler.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_passes_and_changes_no_authority() -> None:
    result = MODULE.compile_contract()
    assert result["status"] == "static_safety_successor_verified"
    assert result["predecessor_bundle_count"] == 16
    assert result["approval_scope_changed"] is False
    assert result["runtime_activity_performed"] is False
    assert result["log_driver"] == "none"


def test_source_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MODULE._bytes

    def drift(relative: str) -> bytes:
        value = original(relative)
        if relative == "deploy/docker/scripts/thor-local.sh":
            return value + b"\n"
        return value

    monkeypatch.setattr(MODULE, "_bytes", drift)
    with pytest.raises(MODULE.ContractError, match="source lock mismatch"):
        MODULE.compile_contract()


def test_missing_log_driver_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MODULE._bytes

    def drift(relative: str) -> bytes:
        value = original(relative)
        if relative == "deploy/docker/scripts/thor-local.sh":
            return value.replace(b" --log-driver none", b"")
        return value

    monkeypatch.setattr(MODULE, "_bytes", drift)
    with pytest.raises(MODULE.ContractError, match="source lock mismatch"):
        MODULE.compile_contract()
