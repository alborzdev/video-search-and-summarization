# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_fixture_blocker_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_plan_is_inert_and_preserves_the_open_selected_row() -> None:
    plan = compiler.compile_plan()
    assert plan["status"] == "inert_source_locked_blocker_valid"
    assert plan["runtime_requests"] == 0
    assert plan["runtime_actions"] == 0
    assert plan["runtime_transport_implemented"] is False
    assert plan["selected_metadata_rows"] == 500
    assert plan["selected_search_state"] == "open_unexecuted_null_bound"
    assert plan["predecessor_preserved"] is True


def test_plan_does_not_overclaim_fixture_closure_or_promotion() -> None:
    plan = compiler.compile_plan()
    assert plan["safe_exact_full_fixture_creation_proven"] is False
    assert plan["operator_preprovisioned_fixture_gap_closed"] is False
    assert plan["predecessor_executor_binding_permitted"] is False
    assert plan["promotion_eligible"] is False
    assert plan["canonical_state_advanced"] is False
    assert plan["warehouse_sample_bundle"] == "excluded"


def test_maximal_adapter_and_blockers_are_exact_and_ordered() -> None:
    contract = compiler._json(compiler.CONTRACT_PATH)
    assert contract["maximal_public_api_adapter"]["planned_action_count"] == 9
    assert [
        row["order"] for row in contract["maximal_public_api_adapter"]["actions"]
    ] == list(range(1, 10))
    assert compiler.compile_plan()["blocking_finding_ids"] == [
        "sensor-identity-not-requestable",
        "selected-object-identity-fixed",
        "rtvi-cv-registration-best-effort",
        "attribute-vst-enrichment-required",
        "model-vectors-not-in-search-input",
        "profile-index-binding-mismatch",
        "delete-is-best-effort",
        "fixed-envelope-has-no-setup",
    ]
    assert compiler.compile_plan()["maximal_adapter_planned_action_count"] == 9


def test_elasticsearch_only_subset_is_explicitly_insufficient() -> None:
    contract = compiler._json(compiler.CONTRACT_PATH)
    subset = contract["implementable_exact_subset"]
    assert subset["scope"] == "Elasticsearch document lifecycle only"
    assert subset["sufficient_for_full_search_fixture"] is False
    assert subset["steps"] == [
        "preflight exact _mget absence",
        "bulk create with op_type=create",
        "exact source-digest readback",
        "reverse-order exact document delete",
        "delayed exact absence and sentinel check",
    ]


def test_source_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = compiler._json(compiler.CONTRACT_PATH)
    original = compiler._read

    def tampered(path: Path, maximum: int = compiler.MAX_BYTES) -> bytes:
        raw = original(path, maximum)
        if path.name == "video_ingest.py":
            return raw + b"\n# drift\n"
        return raw

    monkeypatch.setattr(compiler, "_read", tampered)
    with pytest.raises(compiler.ContractError, match="source_drift"):
        compiler._locked_sources(contract)


def test_missing_production_semantic_fails_closed() -> None:
    contract = compiler._json(compiler.CONTRACT_PATH)
    sources = compiler._locked_sources(contract)
    altered = dict(sources)
    path = "services/agent/src/vss_agents/tools/search.py"
    altered[path] = altered[path].replace(
        b'model_config = ConfigDict(extra="forbid")',
        b'model_config = ConfigDict(extra="ignore")',
    )
    with pytest.raises(compiler.ContractError, match="contract_mismatch"):
        compiler._production_semantics(altered)


def test_compiler_has_no_live_or_write_capability() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(
        {"aiohttp", "docker", "httpx", "requests", "socket", "subprocess", "urllib"}
    )
    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "execute" not in function_names
    assert "execute_http" not in function_names
    assert "open" not in function_names


def test_cli_rejects_execute_mode_without_side_effects(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert compiler.main(["execute-http"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "error",
        "code": "configuration_error",
    }
