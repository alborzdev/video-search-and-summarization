from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "current_semantic_binding_compiler", PACKAGE / "compiler.py"
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


def test_exact_ten_advertised_identities_and_semantics() -> None:
    rows = compiler.compile_overlay()["rows"]
    assert [row["capability_id"] for row in rows] == EXPECTED_IDS
    assert len({row["candidate_record_canonical_sha256"] for row in rows}) == 10
    assert all(len(row["required_semantics"]) == 2 for row in rows)
    assert all(len(row["adjacent_negative"]) == 1 for row in rows)
    assert all(row["required_cloud_inference"] is False for row in rows)
    assert all(row["warehouse_sample_bundle"] is False for row in rows)


def test_concrete_partial_and_readiness_are_distinct() -> None:
    result = compiler.compile_overlay()
    concrete = [
        row for row in result["rows"] if row["implementation_state"] == "concrete"
    ]
    partial = [
        row for row in result["rows"] if row["implementation_state"] == "partial"
    ]
    assert len(concrete) == 4
    assert len(partial) == 6
    assert all(
        row["relationship_kind"] == "concrete_executor_candidate" for row in concrete
    )
    assert all(
        row["relationship_kind"] == "partial_executor_candidate" for row in partial
    )
    assert all(row["executor_ready"] is False for row in result["rows"])
    assert result["summary"]["executor_ready_count"] == 0
    assert result["summary"]["concrete_full_binding_count"] == 0


def test_search_composition_gap_is_explicit() -> None:
    rows = {row["capability_id"]: row for row in compiler.compile_overlay()["rows"]}
    semantic = [rows[capability_id] for capability_id in EXPECTED_IDS[4:8]]
    assert all(len(row["executor_references"]) == 2 for row in semantic)
    assert all(
        any("adapter" in gap for gap in row["retained_gaps"]) for row in semantic
    )
    archive = rows[EXPECTED_IDS[8]]
    assert len(archive["executor_references"]) == 2
    assert archive["implementation_state"] == "concrete"
    assert any(
        ref["package_id"] == "search-rtsp-archive-lifecycle-successor"
        for ref in archive["executor_references"]
    )
    assert any("No live Thor receipt" in gap for gap in archive["retained_gaps"])


def test_lvs_and_ui_retained_boundaries_are_explicit() -> None:
    rows = {row["capability_id"]: row for row in compiler.compile_overlay()["rows"]}
    assert any("attributed" in gap for gap in rows[EXPECTED_IDS[2]]["retained_gaps"])
    assert any(
        "one caption set" in gap for gap in rows[EXPECTED_IDS[3]]["retained_gaps"]
    )
    assert any(
        "40-browser-action" in gap for gap in rows[EXPECTED_IDS[9]]["retained_gaps"]
    )


def test_canonical_effect_is_exactly_empty() -> None:
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
    zero_keys = (
        "executor_ready_count",
        "required_cloud_inference_count",
        "warehouse_sample_dependency_count",
        "concrete_full_binding_count",
        "canonical_binding_change_count",
        "admitted_count",
        "executable_count",
        "runtime_receipt_count",
        "promotion_count",
    )
    assert all(result["summary"][key] == 0 for key in zero_keys)


def test_all_direct_executor_and_contract_inputs_are_locked() -> None:
    contract = _contract()
    locked = {row["path"] for row in contract["source_locks"]}
    assert locked == compiler.EXPECTED_LOCK_PATHS
    for binding in contract["bindings"]:
        for reference in binding["executor_references"]:
            assert reference["path"] in locked
            contract_path = str(Path(reference["path"]).with_name("contract.json"))
            assert contract_path in locked


def test_source_lock_drift_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(compiler.BindingError, match="source lock mismatch"):
        _compile_modified(tmp_path, contract)


def test_classification_upgrade_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["bindings"][2]["implementation_state"] = "concrete"
    contract["bindings"][2]["relationship_kind"] = "concrete_executor_candidate"
    with pytest.raises(compiler.BindingError, match="candidate classification drift"):
        _compile_modified(tmp_path, contract)


def test_executor_ready_injection_fails_closed(tmp_path: Path) -> None:
    contract = copy.deepcopy(_contract())
    contract["bindings"][0]["executor_ready"] = True
    contract["bindings"][0]["executor_references"][0]["executor_ready"] = True
    with pytest.raises(compiler.BindingError, match="contract schema failure"):
        _compile_modified(tmp_path, contract)


def test_source_package_boundary_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = compiler._json

    def changed(path: Path) -> dict:
        value = original(path)
        if path.as_posix().endswith(
            "base-semantic-owned-fixture-successor/contract.json"
        ):
            value = copy.deepcopy(value)
            value["promotion_eligible"] = True
        return value

    monkeypatch.setattr(compiler, "_json", changed)
    with pytest.raises(compiler.BindingError, match="Base candidate boundary drift"):
        compiler.compile_overlay()


def test_ui_irreversible_warning_boundary_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = compiler._json

    def changed(path: Path) -> dict:
        value = original(path)
        if path.as_posix().endswith(
            "ui-video-management-playwright-successor/contract.json"
        ):
            value = copy.deepcopy(value)
            value["ownership"]["destructive_dialog_irreversible_warning_observed"] = (
                False
            )
        return value

    monkeypatch.setattr(compiler, "_json", changed)
    with pytest.raises(compiler.BindingError, match="UI candidate boundary drift"):
        compiler.compile_overlay()


def test_no_receipt_or_admission_input_and_warehouse_excluded() -> None:
    contract = _contract()
    result = compiler.compile_overlay()
    assert contract["runtime_evidence_inputs"] == []
    assert contract["admission_inputs"] == []
    assert result["warehouse_sample_bundle"] == "excluded"
    assert result["default_execution_enabled"] is False


def test_compiler_surface_is_inert() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib",
        "import httpx",
        "docker.from_env",
    ):
        assert forbidden not in source
    assert 'choices=("compile", "check")' in source
