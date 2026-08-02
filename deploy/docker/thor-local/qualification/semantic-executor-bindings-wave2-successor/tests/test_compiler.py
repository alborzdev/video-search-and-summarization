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
    "wave2_semantic_registry_compiler", PACKAGE / "compiler.py"
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


def test_published_selected_five_canonical_truth_remains_exact_zero() -> None:
    registry = compiler.compile_registry()
    assert [row["ordinal"] for row in registry["rows"]] == [1, 2, 3, 4, 5]
    for row in registry["rows"]:
        canonical = row["canonical"]
        assert canonical["executor"] is None
        assert canonical["collectors"] == []
        assert canonical["cleanup_executor"] is None
        assert canonical["postcondition_collectors"] == []
        assert canonical["fixture_materialized"] is False
        assert canonical["executor_ready"] is False
        assert canonical["fully_integrated"] is False
        assert canonical["runtime_evidence_count"] == 0
        assert canonical["promoted"] is False
        candidate = row["wave2_candidate"]
        assert candidate["canonical_bound"] is False
        assert candidate["executor_ready"] is False
        assert candidate["runtime_receipts"] == 0
        assert candidate["promotion_eligible"] is False


def test_base_corrected_full_envelopes_are_concrete_but_unbound() -> None:
    registry = compiler.compile_registry()
    expected = {
        "runtime.workflow.base-chat-report": (8, 11),
        "runtime.agent.base-hitl": (11, 12),
    }
    for capability, (canonical_bound, candidate_bound) in expected.items():
        row = _row(registry, capability)
        assert row["canonical"]["max_requests"] == canonical_bound
        candidate = row["wave2_candidate"]
        assert candidate["package_id"] == "base-semantic-full-envelope-successor"
        assert candidate["concrete_executor"] is True
        assert candidate["exact_full_envelope_candidate"] is True
        assert candidate["exact_owned_cleanup"] is True
        assert candidate["candidate_max_requests"] == candidate_bound
        assert candidate["candidate_max_actions"] == candidate_bound
        assert any(
            "preexisting absence is not proven" in reason
            for reason in candidate["unbound_reasons"]
        )


def test_lvs_agent_session_successor_remains_partial() -> None:
    row = _row(compiler.compile_registry(), "runtime.agent.lvs-profile")
    candidate = row["wave2_candidate"]
    assert candidate["concrete_executor"] is True
    assert candidate["partial_transport"] is True
    assert candidate["exact_full_envelope_candidate"] is False
    assert candidate["candidate_max_requests"] == 34
    assert candidate["candidate_max_actions"] == 34
    assert any("five-tool" in reason for reason in candidate["unbound_reasons"])
    assert any("live captions" in reason for reason in candidate["unbound_reasons"])
    assert any(
        "preexisting absence" in reason and "unrelated Agent state" in reason
        for reason in candidate["unbound_reasons"]
    )


def test_search_package_is_a_blocker_not_an_executor() -> None:
    row = _row(compiler.compile_registry(), "runtime.agent.search-profile")
    candidate = row["wave2_candidate"]
    assert candidate["classification"] == "static_exact_fixture_provisioning_blocker"
    assert candidate["transport_kind"] == "none"
    assert candidate["concrete_executor"] is False
    assert candidate["static_blocker_only"] is True
    assert candidate["candidate_max_requests"] is None
    assert any(
        "operator-preprovisioned fixture" in reason
        for reason in candidate["unbound_reasons"]
    )


def test_ui_browser_candidate_records_plugin_and_provenance_gaps() -> None:
    row = _row(compiler.compile_registry(), "runtime.ui.video-management-tab")
    candidate = row["wave2_candidate"]
    assert candidate["browser_executor"] is True
    assert candidate["concrete_executor"] is True
    assert candidate["candidate_max_actions"] == 40
    assert candidate["candidate_max_requests"] == 32
    assert any(
        "Browser plugin is absent" in reason for reason in candidate["unbound_reasons"]
    )
    assert any(
        "package trees are digest-pinned" in reason
        for reason in candidate["unbound_reasons"]
    )
    assert any(
        "rendered live runtime receipt" in reason
        for reason in candidate["unbound_reasons"]
    )


def test_summary_keeps_candidate_progress_separate() -> None:
    summary = compiler.compile_registry()["summary"]
    assert summary == {
        "canonical_row_count": 5,
        "canonical_executor_ready_count": 0,
        "canonical_fully_integrated_count": 0,
        "canonical_runtime_evidence_count": 0,
        "canonical_promotion_count": 0,
        "wave2_distinct_package_count": 4,
        "wave2_concrete_executor_package_count": 3,
        "wave2_rows_with_concrete_executor": 4,
        "wave2_rows_with_exact_full_envelope_candidate": 2,
        "wave2_rows_with_partial_transport": 1,
        "wave2_rows_with_browser_executor": 1,
        "wave2_rows_with_static_blocker_only": 1,
        "wave2_runtime_receipt_count": 0,
        "wave2_canonical_binding_count": 0,
        "wave2_promotion_count": 0,
    }


def test_published_canonical_execution_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    published_path = compiler._path(contract["published_registry"]["path"])
    published = compiler._json(published_path)
    changed = copy.deepcopy(published)
    changed["rows"][0]["canonical"]["executor"] = "not-admitted"
    original = compiler._json

    def altered(path: Path) -> dict:
        return changed if path == published_path else original(path)

    monkeypatch.setattr(compiler, "_json", altered)
    with pytest.raises(
        compiler.RegistryError, match="published canonical selected-five truth drift"
    ):
        compiler.compile_registry()


def test_source_lock_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    target = compiler._path(contract["source_locks"][4]["path"])
    original = compiler._read

    def altered(path: Path, maximum: int = compiler.MAX_BYTES) -> bytes:
        raw = original(path, maximum)
        return raw + b"\n" if path == target else raw

    monkeypatch.setattr(compiler, "_read", altered)
    with pytest.raises(compiler.RegistryError, match="source lock mismatch"):
        compiler.compile_registry()


def test_candidate_contract_truth_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    ui_lock = next(
        lock
        for lock in contract["source_locks"]
        if lock["path"].endswith(
            "ui-video-management-playwright-successor/contract.json"
        )
    )
    ui_path = compiler._path(ui_lock["path"])
    ui = compiler._json(ui_path)
    changed = copy.deepcopy(ui)
    changed["canonical_boundary"]["playwright_transitive_graph_pinned"] = False
    original = compiler._json

    def altered(path: Path) -> dict:
        return changed if path == ui_path else original(path)

    monkeypatch.setattr(compiler, "_json", altered)
    with pytest.raises(compiler.RegistryError, match="UI wave-2 candidate"):
        compiler.compile_registry()


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


def test_warehouse_remains_excluded() -> None:
    registry = compiler.compile_registry()
    assert registry["warehouse_sample_bundle"] == "excluded"
    contract = json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))
    assert contract["warehouse_sample_bundle"] == "excluded"
