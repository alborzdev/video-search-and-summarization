"""Focused tests for authoritative atomic metadata-set verification."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


PARITY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARITY))

import verify_metadata_set as verifier  # noqa: E402


class FakeSnapshot:
    def __init__(self, version: int = 1) -> None:
        self.set_id = "fake-set"
        self.descriptor_raw_sha256 = "a" * 64
        self.expected_counts = {
            "capabilities": 1,
            "oracles": 1,
            "feature_families": 1,
        }
        self._documents = {
            "manifest": {"features": [{"id": "family"}]},
            "official_capabilities": {
                "capabilities": [{"id": "cap", "feature_id": "family"}]
            },
            "capability_oracles": {
                "schema_version": version,
                "oracles": [{"capability_id": "cap"}],
            },
            "acceptance_inventory": {"scenarios": []},
        }
        self._schemas = {
            "capability_oracles_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema"
            }
        }

    def document(self, name: str) -> dict[str, Any]:
        return copy.deepcopy(self._documents[name])

    def schema(self, name: str) -> dict[str, Any]:
        return copy.deepcopy(self._schemas[name])


def _official_counts() -> dict[str, int]:
    return {
        "sources": 1,
        "capabilities": 1,
        "feature_families": 1,
        "discrepancies": 1,
    }


def _oracle_counts() -> dict[str, int]:
    return {"capabilities": 1, "oracles": 1}


def test_default_selected_500_set_is_authoritatively_validated() -> None:
    report = verifier.verify_metadata_set()
    assert report["set_id"] == (
        "thor-vss-3.2.1-current-event-transports-runtime-500"
    )
    assert report["oracle_schema_version"] == 2
    assert report["oracle_validator"] == "capability_oracles_v2"
    assert report["counts"] == {
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
    }
    assert report["official_validator_counts"]["feature_families"] == 55


def test_explicit_current_289_set_is_authoritatively_validated() -> None:
    report = verifier.verify_metadata_set(
        "thor-vss-3.2.1-current-event-transports-runtime-289"
    )
    assert report["set_id"] == (
        "thor-vss-3.2.1-current-event-transports-runtime-289"
    )
    assert report["oracle_schema_version"] == 1
    assert report["oracle_validator"] == "capability_oracles.v1"
    assert report["counts"] == {
        "capabilities": 289,
        "oracles": 289,
        "feature_families": 55,
    }


def test_v1_dispatch_uses_only_resolved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = FakeSnapshot(1)
    observed: dict[str, Any] = {}
    monkeypatch.setattr(verifier, "resolve_metadata_set", lambda set_id=None: snapshot)

    def official(**kwargs: Any) -> dict[str, int]:
        observed["official"] = kwargs
        return _official_counts()

    def oracle(**kwargs: Any) -> dict[str, int]:
        observed["oracle"] = kwargs
        return _oracle_counts()

    monkeypatch.setattr(verifier.verify_official_capabilities, "validate", official)
    monkeypatch.setattr(verifier.capability_oracles, "validate", oracle)
    report = verifier.verify_metadata_set()
    assert (
        observed["official"]["ledger"] == snapshot._documents["official_capabilities"]
    )
    assert observed["official"]["manifest"] == snapshot._documents["manifest"]
    assert (
        observed["official"]["acceptance"]
        == snapshot._documents["acceptance_inventory"]
    )
    assert (
        observed["official"]["oracle_plan"] == snapshot._documents["capability_oracles"]
    )
    assert (
        observed["official"]["oracle_schema"]
        == snapshot._schemas["capability_oracles_schema"]
    )
    assert observed["oracle"]["plan"] == snapshot._documents["capability_oracles"]
    assert observed["oracle"]["ledger"] == snapshot._documents["official_capabilities"]
    assert report["oracle_validator"] == "capability_oracles.v1"


def test_v2_dispatch_passes_snapshot_plan_ledger_acceptance_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = FakeSnapshot(2)
    observed: dict[str, Any] = {}
    monkeypatch.setattr(verifier, "resolve_metadata_set", lambda set_id=None: snapshot)
    monkeypatch.setattr(
        verifier.verify_official_capabilities,
        "validate",
        lambda **kwargs: _official_counts(),
    )

    def validate(plan, ledger, acceptance=None, schema=None):
        observed.update(
            plan=plan,
            ledger=ledger,
            acceptance=acceptance,
            schema=schema,
        )
        return _oracle_counts()

    monkeypatch.setattr(
        verifier,
        "_load_v2_validator",
        lambda: SimpleNamespace(validate=validate),
    )
    report = verifier.verify_metadata_set("fake-set")
    assert observed == {
        "plan": snapshot._documents["capability_oracles"],
        "ledger": snapshot._documents["official_capabilities"],
        "acceptance": snapshot._documents["acceptance_inventory"],
        "schema": snapshot._schemas["capability_oracles_schema"],
    }
    assert report["oracle_validator"] == "capability_oracles_v2"


def test_unknown_oracle_version_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = FakeSnapshot(999)
    monkeypatch.setattr(verifier, "resolve_metadata_set", lambda set_id=None: snapshot)
    monkeypatch.setattr(
        verifier.verify_official_capabilities,
        "validate",
        lambda **kwargs: _official_counts(),
    )
    with pytest.raises(
        verifier.MetadataSetVerificationError,
        match="unsupported capability-oracle schema_version",
    ):
        verifier.verify_metadata_set()


def test_missing_v2_validator_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str):
        raise ImportError(name)

    monkeypatch.setattr(verifier.importlib, "import_module", missing)
    with pytest.raises(
        verifier.MetadataSetVerificationError,
        match="v2 capability-oracle validator is unavailable",
    ):
        verifier._load_v2_validator()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda snapshot: snapshot.expected_counts.update({"oracles": 2}),
            "resolved snapshot count drift",
        ),
        (
            lambda snapshot: snapshot._documents["capability_oracles"].update(
                {
                    "projected_oracles": snapshot._documents["capability_oracles"].pop(
                        "oracles"
                    )
                }
            ),
            "oracles must be a list",
        ),
        (
            lambda snapshot: snapshot._documents["manifest"]["features"].append(
                "injected"
            ),
            "features must be a list of objects",
        ),
    ],
)
def test_mixed_or_injected_snapshots_fail_before_validation(
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    message: str,
) -> None:
    snapshot = FakeSnapshot(1)
    mutation(snapshot)
    monkeypatch.setattr(verifier, "resolve_metadata_set", lambda set_id=None: snapshot)
    with pytest.raises(verifier.MetadataSetVerificationError, match=message):
        verifier.verify_metadata_set()


@pytest.mark.parametrize(
    ("validator", "counts"),
    [
        ("official", {"capabilities": 2, "feature_families": 1}),
        ("oracle", {"capabilities": 1, "oracles": 2}),
        ("oracle", {"capabilities": True, "oracles": 1}),
    ],
)
def test_injected_validator_counts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    validator: str,
    counts: dict[str, int],
) -> None:
    snapshot = FakeSnapshot(1)
    monkeypatch.setattr(verifier, "resolve_metadata_set", lambda set_id=None: snapshot)
    monkeypatch.setattr(
        verifier.verify_official_capabilities,
        "validate",
        lambda **kwargs: counts if validator == "official" else _official_counts(),
    )
    monkeypatch.setattr(
        verifier.capability_oracles,
        "validate",
        lambda **kwargs: counts if validator == "oracle" else _oracle_counts(),
    )
    with pytest.raises(verifier.MetadataSetVerificationError):
        verifier.verify_metadata_set()


def test_cli_reports_exact_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    report = {
        "set_id": "set",
        "descriptor_raw_sha256": "a" * 64,
        "oracle_schema_version": 1,
        "oracle_validator": "capability_oracles.v1",
        "counts": {"capabilities": 1, "oracles": 1, "feature_families": 1},
        "official_validator_counts": {"capabilities": 1},
        "oracle_validator_counts": {"capabilities": 1, "oracles": 1},
    }
    monkeypatch.setattr(verifier, "verify_metadata_set", lambda set_id=None: report)
    assert verifier.main(["--set", "set", "--json"]) == 0
    assert '"set_id":"set"' in capsys.readouterr().out


def test_cli_reports_validator_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        verifier,
        "verify_metadata_set",
        lambda set_id=None: (_ for _ in ()).throw(ValueError("injected failure")),
    )
    assert verifier.main([]) == 1
    assert capsys.readouterr().err == "FAIL: injected failure\n"


def test_verifier_has_no_runtime_network_docker_or_host_surface() -> None:
    tree = ast.parse((PARITY / "verify_metadata_set.py").read_text())
    forbidden = {"requests", "urllib", "socket", "subprocess", "docker"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names
            if isinstance(node, ast.Import)
            else [ast.alias(name=node.module or "")]
        )
    }
    assert not imported & forbidden
