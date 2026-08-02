from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
VALIDATOR = PACKAGE / "validator.py"
WRAPPER = PACKAGE.parents[2] / "test-scripts" / "test-thor-static-parity-milestone.sh"
SPEC = importlib.util.spec_from_file_location("advertised_74_drift_observer", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def test_immutable_receipt_and_historical_waves_are_preserved_without_replay():
    result = validator.observe()
    assert result["status"] == "pass_immutable_snapshot_not_replayed"
    assert result["guarded_observer_receipt_raw_sha256"] == (
        "acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c"
    )
    assert result["historical_waves_verified"] == 7
    assert result["immutable_source_locks"] == 88
    assert result["historical_dispatch_executed"] is False
    assert result["current_source_match_required"] is False
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["currently_drifted_sources"] > 0
    assert "services/video-summarization/src/lvs_mcp.py" in result["drifted_paths"]


def test_current_source_drift_is_observed_not_rejected(monkeypatch):
    original = validator._read

    def drift(relative: str) -> bytes:
        payload = original(relative)
        if relative == "services/video-summarization/src/rtvi_vlm_client.py":
            return payload + b"\n"
        return payload

    baseline = validator.observe()
    monkeypatch.setattr(validator, "_read", drift)
    observed = validator.observe()
    assert (
        observed["currently_drifted_sources"] >= baseline["currently_drifted_sources"]
    )
    assert observed["current_source_match_required"] is False


def test_immutable_receipt_drift_fails_closed(monkeypatch):
    original = validator._read

    def drift(relative: str) -> bytes:
        payload = original(relative)
        if relative == validator.RECEIPT_PATH:
            return payload + b"\n"
        return payload

    monkeypatch.setattr(validator, "_read", drift)
    with pytest.raises(validator.ObservationError, match="immutable 74-successor"):
        validator.observe()


def test_validator_has_no_historical_import_or_external_action_surface():
    tree = ast.parse(VALIDATOR.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {"importlib", "runpy", "socket", "subprocess", "requests", "urllib", "docker"}
    )
    source = VALIDATOR.read_text(encoding="utf-8")
    assert "advertised-entry-executors-74-successor/compiler" not in source
    assert "advertised-entry-executors-74-successor/executor" not in source


def test_live_static_wrapper_uses_observer_not_historical_replay():
    source = WRAPPER.read_text(encoding="utf-8")
    assert (
        "advertised-entry-executors-74-drift-observation-successor/validator.py"
        in source
    )
    assert "advertised-entry-executors-74-successor/compiler.py" not in source
    assert "advertised-entry-executors-74-successor/executor.py" not in source
    assert "advertised-entry-executors-74-successor/tests" not in source


def test_unsafe_path_fails_closed():
    with pytest.raises(validator.ObservationError, match="unsafe repository path"):
        validator._repo_file("../outside")
