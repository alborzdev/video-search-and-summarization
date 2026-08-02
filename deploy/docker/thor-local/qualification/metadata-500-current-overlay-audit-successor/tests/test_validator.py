from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata500_current_overlay_audit", HERE / "validator.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text())


def test_exact_selected_metadata_and_overlay_audit_passes() -> None:
    assert MODULE.validate() == {
        "schema_version": 1,
        "status": "pass_selected_metadata_current_overlay_static_audit",
        "selected_set": "thor-vss-3.2.1-current-cancellation-search-500",
        "capabilities": 500,
        "oracles": 500,
        "candidate_rows": 211,
        "changed_agent_sources": 9,
        "changed_source_metadata_rows": 11,
        "current_source_rebased_rows": 32,
        "runtime_successor_packages": 4,
        "runtime_successor_canonical_rows": 5,
        "current_candidate_binding_rows": 10,
        "current_candidate_concrete_implementations": 10,
        "current_candidate_partial_implementations": 0,
        "runtime_evidence": 0,
        "canonical_state_advanced": False,
        "selector_mutated": False,
        "warehouse_sample_bundle": "excluded",
    }


def test_changed_agent_source_mapping_is_exact_and_complete() -> None:
    contract = _contract()
    rows = {row["path"]: row for row in contract["changed_agent_sources"]}
    assert set(rows) == set(MODULE.EXPECTED_CHANGED_ROWS)
    assert (
        len(
            {
                capability_id
                for row in rows.values()
                for capability_id in row["metadata_capability_ids"]
            }
        )
        == 11
    )
    assert {
        path: set(row["current_source_rebase_entry_ids"]) for path, row in rows.items()
    } == {path: value["rebase"] for path, value in MODULE.EXPECTED_CHANGED_ROWS.items()}


def test_conflating_official_provenance_with_local_hashes_fails_closed() -> None:
    contract = _contract()
    contract["metadata_boundary"]["local_python_hashes_are_metadata_source_claims"] = (
        True
    )
    with pytest.raises(MODULE.AuditError, match="metadata boundary"):
        MODULE.validate(contract)


def test_omitting_one_changed_source_row_fails_closed() -> None:
    contract = _contract()
    contract["changed_agent_sources"][0]["metadata_capability_ids"] = []
    with pytest.raises(MODULE.AuditError, match="source-to-row mapping"):
        MODULE.validate(contract)


def test_source_byte_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MODULE._read
    target = "services/agent/src/vss_agents/api/video_ingest.py"

    def changed(relative: str, **kwargs):
        payload = original(relative, **kwargs)
        return payload + b"\n" if relative == target else payload

    monkeypatch.setattr(MODULE, "_read", changed)
    with pytest.raises(MODULE.AuditError, match="source lock drift"):
        MODULE.validate(_contract())


def test_canonical_runtime_advancement_without_receipt_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = MODULE._strict_json

    def changed(payload: bytes, label: str):
        value = original(payload, label)
        if label == MODULE.ORACLES:
            value = copy.deepcopy(value)
            row = next(
                item
                for item in value["oracles"]
                if item["capability_id"] == "runtime.agent.search-profile"
            )
            row["current_state"] = "passed_current"
            row["evidence"] = [{"invented": True}]
        return value

    monkeypatch.setattr(MODULE, "_strict_json", changed)
    with pytest.raises(MODULE.AuditError, match="canonical runtime row advanced"):
        MODULE.validate(_contract())


def test_changed_source_candidate_promotion_without_receipt_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = MODULE._strict_json

    def changed(payload: bytes, label: str):
        value = original(payload, label)
        if label == MODULE.ORACLES:
            value = copy.deepcopy(value)
            row = next(
                item
                for item in value["oracles"]
                if item["capability_id"]
                == "manifest-entry.agent-and-mcp-apis.03-video-delete"
            )
            row["current_state"] = "passed_current"
            row["evidence"] = [{"invented": True}]
        return value

    monkeypatch.setattr(MODULE, "_strict_json", changed)
    with pytest.raises(MODULE.AuditError, match="promoted without evidence"):
        MODULE.validate(_contract())


def test_local_hash_inserted_into_official_source_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = MODULE._strict_json

    def changed(payload: bytes, label: str):
        value = original(payload, label)
        if label == MODULE.LEDGER:
            value = copy.deepcopy(value)
            source = next(
                item
                for item in value["sources"]
                if item["id"] == "tagged-repository-3.2.1"
            )
            source["raw_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(MODULE, "_strict_json", changed)
    with pytest.raises(MODULE.AuditError, match="conflated with local source bytes"):
        MODULE.validate(_contract())


def test_successor_self_promotion_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MODULE._strict_json
    target = (
        "deploy/docker/thor-local/qualification/"
        "base-semantic-owned-fixture-successor/contract.json"
    )

    def changed(payload: bytes, label: str):
        value = original(payload, label)
        if label == target:
            value = copy.deepcopy(value)
            value["promotion_eligible"] = True
        return value

    monkeypatch.setattr(MODULE, "_strict_json", changed)
    with pytest.raises(MODULE.AuditError, match="Base successor non-promotion"):
        MODULE.validate(_contract())


def test_candidate_binding_promotion_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = MODULE._strict_json

    def changed(payload: bytes, label: str):
        value = original(payload, label)
        if label == MODULE.BINDING_ARTIFACT:
            value = copy.deepcopy(value)
            value["rows"][0]["canonical_effect"]["promoted"] = True
        return value

    monkeypatch.setattr(MODULE, "_strict_json", changed)
    with pytest.raises(
        MODULE.AuditError,
        match="artifact is stale|advanced canonical state",
    ):
        MODULE.validate(_contract())


def test_static_auditor_has_no_runtime_or_write_surface() -> None:
    tree = ast.parse((HERE / "validator.py").read_text())
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
    assert not imported & {
        "docker",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr in {"write_bytes", "write_text", "unlink", "rename", "replace"}
        for node in ast.walk(tree)
    )
