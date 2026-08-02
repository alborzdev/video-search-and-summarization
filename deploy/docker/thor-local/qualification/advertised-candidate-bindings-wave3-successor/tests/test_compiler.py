from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wave3_binding_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


EXPECTED_IDS = [
    "manifest-entry.base-agent-workflow.01-visual-question-answering",
    "manifest-entry.base-agent-workflow.02-vlm-report-generation",
    "manifest-entry.video-summarization-file.02-multi-video-report",
    "manifest-entry.video-summarization-file.04-object-event-scenario-focus",
    "manifest-entry.semantic-search.00-natural-language-action-event-search",
    "manifest-entry.semantic-search.01-cv-attribute-search",
    "manifest-entry.semantic-search.02-multi-embedding-fusion",
    "manifest-entry.semantic-search.03-search-by-image",
    "manifest-entry.semantic-search.07-file-and-rtsp-archive-management",
    "manifest-entry.main-ui.05-chunked-upload-and-rtsp-management",
]


def _contract() -> dict:
    return json.loads((PACKAGE / "contract.json").read_text(encoding="utf-8"))


def _compile_modified(tmp_path: Path, value: dict) -> dict:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return compiler.compile_overlay(path)


def test_checked_overlay_is_reproducible() -> None:
    assert compiler.compile_overlay() == json.loads(
        (PACKAGE / "binding-overlay.json").read_text(encoding="utf-8")
    )
    assert compiler.main(["check"]) == 0


def test_exact_ten_row_identity_and_order() -> None:
    result = compiler.compile_overlay()
    assert [row["capability_id"] for row in result["rows"]] == EXPECTED_IDS
    assert (
        len({row["candidate_record_canonical_sha256"] for row in result["rows"]}) == 10
    )
    assert all(len(row["required_semantics"]) == 2 for row in result["rows"])
    assert all(row["adjacent_negative"] for row in result["rows"])


def test_strength_split_is_five_five_zero() -> None:
    result = compiler.compile_overlay()
    assert result["summary"]["partial_executor_link_count"] == 5
    assert result["summary"]["static_blocker_link_count"] == 5
    assert result["summary"]["concrete_full_binding_count"] == 0


def test_blockers_have_no_executor_and_are_not_positive_proof() -> None:
    blockers = [
        row
        for row in compiler.compile_overlay()["rows"]
        if row["binding_strength"] == "blocker"
    ]
    assert len(blockers) == 5
    assert all(row["relationship_kind"] == "static_blocker_link" for row in blockers)
    assert all(row["executor_reference"] is None for row in blockers)
    assert all(
        row["coverage_status"] == "incomplete_no_live_receipt" for row in blockers
    )


def test_partial_links_remain_not_ready() -> None:
    partial = [
        row
        for row in compiler.compile_overlay()["rows"]
        if row["binding_strength"] == "partial"
    ]
    assert len(partial) == 5
    assert all(row["executor_reference"]["executor_ready"] is False for row in partial)
    assert all(
        row["executor_reference"]["authorization_gated"] is True for row in partial
    )


def test_canonical_effect_is_empty_for_every_row() -> None:
    result = compiler.compile_overlay()
    assert result["canonical_mapping_mutated"] is False
    for row in result["rows"]:
        assert row["canonical_effect"] == {
            "admitted": False,
            "binding_kind_changed": False,
            "executable": False,
            "promoted": False,
            "runtime_evidence": [],
        }
    assert all(
        result["summary"][key] == 0
        for key in (
            "canonical_binding_change_count",
            "admitted_count",
            "executable_count",
            "runtime_receipt_count",
            "promotion_count",
        )
    )


def test_unproven_neighbor_rows_are_not_linked() -> None:
    ids = set(EXPECTED_IDS)
    excluded = {
        "manifest-entry.base-agent-workflow.00-short-video-retrieval",
        "manifest-entry.base-agent-workflow.03-templated-reports",
        "manifest-entry.base-agent-workflow.06-public-media-url-rewriting",
        "manifest-entry.video-summarization-file.01-file-summarization",
        "manifest-entry.video-summarization-file.05-reasoning",
        "manifest-entry.semantic-search.04-follow-up-q-a",
        "manifest-entry.main-ui.00-streaming-agent-chat",
    }
    assert ids.isdisjoint(excluded)


def test_source_lock_drift_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(compiler.BindingError, match="source lock mismatch"):
        _compile_modified(tmp_path, contract)


def test_candidate_identity_drift_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["bindings"][0]["candidate_record_canonical_sha256"] = "0" * 64
    with pytest.raises(
        compiler.BindingError, match="candidate mapping or advertised contract drift"
    ):
        _compile_modified(tmp_path, contract)


def test_blocker_executor_injection_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    blocker = next(
        row for row in contract["bindings"] if row["binding_strength"] == "blocker"
    )
    blocker["executor_reference"] = {
        "package_id": "unsafe",
        "path": "unsafe",
        "authorization_gated": True,
        "executor_ready": False,
    }
    with pytest.raises(compiler.BindingError, match="binding relationship drift"):
        _compile_modified(tmp_path, contract)


def test_compiler_surface_is_inert() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    for forbidden in (
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib",
        "import httpx",
        "docker.from_env",
    ):
        assert forbidden not in source.lower()
    assert 'choices=("compile", "check")' in source


def test_warehouse_and_cloud_boundaries() -> None:
    result = compiler.compile_overlay()
    assert result["warehouse_sample_bundle"] == "excluded"
    assert result["default_execution_enabled"] is False
