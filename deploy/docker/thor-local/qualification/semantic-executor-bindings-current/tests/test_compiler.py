# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "semantic_executor_registry_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def _row(registry: dict, capability_id: str) -> dict:
    matches = [row for row in registry["rows"] if row["capability_id"] == capability_id]
    assert len(matches) == 1
    return matches[0]


def test_compiler_reproduces_checked_registry() -> None:
    compiled = compiler.compile_registry()
    checked = json.loads(
        (PACKAGE / "execution-status-registry.json").read_text(encoding="utf-8")
    )
    assert compiled == checked
    assert (
        compiler.check_artifact()["status"] == "checked_artifact_current_non_promoting"
    )


def test_canonical_selected_500_status_remains_all_zero() -> None:
    registry = compiler.compile_registry()
    assert [row["ordinal"] for row in registry["rows"]] == [1, 2, 3, 4, 5]
    assert (
        registry["summary"]
        | {
            "canonical_row_count": 5,
            "canonical_executor_ready_count": 0,
            "canonical_fully_integrated_count": 0,
            "canonical_runtime_evidence_count": 0,
            "canonical_promotion_count": 0,
        }
        == registry["summary"]
    )
    for row in registry["rows"]:
        assert row["canonical"]["executor"] is None
        assert row["canonical"]["collectors"] == []
        assert row["canonical"]["cleanup_executor"] is None
        assert row["canonical"]["postcondition_collectors"] == []
        assert row["canonical"]["executor_ready"] is False
        assert row["canonical"]["fully_integrated"] is False
        assert row["canonical"]["runtime_evidence_count"] == 0
        assert row["canonical"]["promoted"] is False


def test_base_rows_distinguish_invalid_predecessor_cleanup_from_partial_fix() -> None:
    registry = compiler.compile_registry()
    expected = {
        "runtime.workflow.base-chat-report": (8, 11),
        "runtime.agent.base-hitl": (11, 12),
    }
    for capability, (frozen, corrected) in expected.items():
        row = _row(registry, capability)
        assert row["candidate"]["invalid_full_workflow_cleanup"] is True
        assert row["candidate"]["partial_exact_cleanup_transport"] is True
        assert row["candidate"]["exact_full_envelope_transport"] is False
        predecessor, successor = row["candidate"]["layers"]
        assert predecessor["declared_request_bound"] == frozen
        assert predecessor["exact_cleanup"] is False
        assert successor["declared_request_bound"] == 7
        assert successor["corrected_full_envelope_requests"] == corrected
        assert successor["scope"] == "partial_exact_cleanup_slice"
        assert successor["canonical_bound"] is False


def test_search_is_exact_transport_but_operator_fixture_unbound() -> None:
    row = _row(compiler.compile_registry(), "runtime.agent.search-profile")
    assert row["candidate"]["any_concrete_http_transport"] is True
    assert row["candidate"]["exact_full_envelope_transport"] is True
    assert row["candidate"]["operator_preprovisioned_fixture"] is True
    assert row["candidate"]["canonical_bound"] is False
    assert row["candidate"]["runtime_receipts"] == 0
    assert row["candidate"]["promotion_eligible"] is False


def test_lvs_core_and_reviewed_concrete_partial_http_successor_are_separate() -> None:
    registry = compiler.compile_registry()
    row = _row(registry, "runtime.agent.lvs-profile")
    assert row["candidate"]["injected_adapter_only"] is False
    assert row["candidate"]["injected_adapter_core"] is True
    assert row["candidate"]["concrete_partial_lvs_http_transport"] is True
    assert row["candidate"]["any_concrete_http_transport"] is True
    assert row["candidate"]["partial_exact_cleanup_transport"] is True
    assert row["candidate"]["exact_full_envelope_transport"] is False
    assert [layer["transport_kind"] for layer in row["candidate"]["layers"]] == [
        "injected_semantic_adapter",
        "numeric_loopback_http",
    ]
    assert row["candidate"]["layers"][1]["scope"] == "partial_http_action_slice"
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    successor_locks = [
        lock
        for lock in contract["source_locks"]
        if "lvs-semantic-runtime-http-successor" in lock["path"]
    ]
    assert len(successor_locks) == 4


def test_ui_is_manual_receipt_only_without_browser_executor() -> None:
    row = _row(compiler.compile_registry(), "runtime.ui.video-management-tab")
    assert row["candidate"]["manual_receipt_only"] is True
    assert row["candidate"]["browser_executor"] is False
    assert row["candidate"]["any_concrete_http_transport"] is False
    assert [layer["transport_kind"] for layer in row["candidate"]["layers"]] == [
        "manual_receipt",
        "receipt_validator_only",
    ]


def test_selected_row_evidence_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    selected_path = compiler._path(contract["selected_metadata"]["path"])
    selected = compiler._json(selected_path)
    changed = copy.deepcopy(selected)
    target = next(
        row
        for row in changed["oracles"]
        if row["oracle_id"] == "oracle.runtime.agent.search-profile"
    )
    target["evidence"] = [{"not": "admitted"}]
    original = compiler._json

    def altered(path: Path) -> dict:
        return changed if path == selected_path else original(path)

    monkeypatch.setattr(compiler, "_json", altered)
    with pytest.raises(
        compiler.RegistryError, match="canonical row execution status drift"
    ):
        compiler._verify_selected(contract)


def test_source_lock_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    target = compiler._path(contract["source_locks"][1]["path"])
    original = compiler._read

    def altered(path: Path, maximum: int = compiler.MAX_BYTES) -> bytes:
        raw = original(path, maximum)
        return raw + b"\n" if path == target else raw

    monkeypatch.setattr(compiler, "_read", altered)
    with pytest.raises(compiler.RegistryError, match="source lock mismatch"):
        compiler._verify_source_locks(contract)


def test_compiler_has_no_runtime_or_write_adapter() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    forbidden = [
        "import urllib",
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
        "import docker",
        ".write_text(",
        ".write_bytes(",
        "urlopen(",
    ]
    assert not any(token in source for token in forbidden)


def test_summary_candidate_counts_are_separate_from_canonical_counts() -> None:
    summary = compiler.compile_registry()["summary"]
    assert summary["candidate_rows_with_any_concrete_http_transport"] == 4
    assert summary["candidate_rows_with_invalid_full_workflow_cleanup"] == 2
    assert summary["candidate_rows_with_partial_exact_cleanup_transport"] == 3
    assert summary["candidate_rows_with_exact_full_envelope_transport"] == 1
    assert summary["candidate_rows_with_injected_adapter_only"] == 0
    assert summary["candidate_rows_with_injected_adapter_core"] == 1
    assert summary["candidate_rows_with_concrete_partial_lvs_http_transport"] == 1
    assert summary["candidate_rows_with_manual_receipt_only"] == 1
    assert summary["candidate_rows_with_browser_executor"] == 0
    assert summary["candidate_runtime_receipt_count"] == 0
    assert summary["candidate_promotion_count"] == 0
    assert summary["concrete_http_executor_package_count"] == 4
