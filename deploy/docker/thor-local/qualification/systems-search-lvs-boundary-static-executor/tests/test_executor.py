# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Adversarial checks for the isolated Search/LVS boundary executor."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_lvs_boundary_executor", LANE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


def test_full_candidate_is_mismatch_visible_and_non_advancing() -> None:
    result = EXECUTOR.run()
    assert result["result"] == "candidate_executable_mismatch_non_advancing"
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"
    assert all(not row["canonical_state_advanced"] for row in result["bindings"])
    assert result["confinement"] == {
        "external_calls": 0,
        "network_calls": 0,
        "subprocess_calls": 0,
        "filesystem_writes": 0,
        "docker_calls": 0,
        "service_lifecycle_calls": 0,
        "model_calls": 0,
        "warehouse_sample_bundle": "excluded",
        "counter_basis": "locked_source_and_replaced_transport_boundary_audit",
    }


def test_search_transport_patch_is_restored() -> None:
    before = httpx.AsyncClient
    EXECUTOR._exercise_search_upload()
    assert httpx.AsyncClient is before


def test_search_mismatch_is_not_normalized_away() -> None:
    observed = EXECUTOR.run()["observations"]["search_upload"]
    assert observed["observed_missing_status"] == 400
    assert observed["observed_unsupported_status"] == 415
    assert observed["canonical_match"] is False
    assert [case["fake_upload_calls"] for case in observed["cases"]] == [
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    ]


def test_lvs_handler_concurrency_does_not_overclaim_downstream() -> None:
    observed = EXECUTOR.run()["observations"]["lvs_queue"]
    assert observed["initial_statuses"] == ["queued", "queued"]
    assert observed["statuses_at_pipeline_entry"] == ["processing", "processing"]
    assert observed["peak_concurrent_fake_pipeline_calls"] == 2
    assert observed["lvs_handler_serialization_match"] is False
    assert (
        observed["end_to_end_contract_status"]
        == "unqualified_downstream_rtvi_may_queue"
    )


def test_format_gap_remains_unqualified_not_claimed_failed() -> None:
    observed = EXECUTOR.run()["observations"]["lvs_formats"]
    assert observed["ui_default_admitted_formats"] == ["MP4", "MKV"]
    assert observed["ui_default_missing_advertised_formats"] == ["AVI", "MOV", "WebM"]
    assert (
        observed["capability_status"]
        == "not_proven_ui_surface_narrower_than_advertised_contract"
    )
    assert observed["live_decode_matrix_executed"] is False


def test_contract_source_lock_tamper_fails_closed() -> None:
    contract = copy.deepcopy(EXECUTOR._load_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.QualificationError, match="source lock mismatch"):
        EXECUTOR._verify_source_locks(contract)


def test_contract_source_lock_membership_substitution_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = EXECUTOR._strict_json

    def substitute(path: Path) -> dict:
        value = original(path)
        if path == LANE / "contract.json":
            value["source_locks"][0] = copy.deepcopy(value["source_locks"][1])
        return value

    monkeypatch.setattr(EXECUTOR, "_strict_json", substitute)
    with pytest.raises(EXECUTOR.QualificationError, match="source-lock set drift"):
        EXECUTOR._load_contract()


def test_canonical_binding_digest_tamper_fails_closed() -> None:
    contract = copy.deepcopy(EXECUTOR._load_contract())
    contract["bindings"][0]["capability_sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.QualificationError, match="capability digest drift"):
        EXECUTOR._verify_bindings(contract)


def test_duplicate_json_key_and_path_traversal_are_rejected() -> None:
    with pytest.raises(EXECUTOR.QualificationError, match="duplicate JSON key"):
        EXECUTOR._strict_object([("a", 1), ("a", 2)])
    with pytest.raises(EXECUTOR.QualificationError, match="unsafe repository path"):
        EXECUTOR._repo_file("../outside")


def test_strict_json_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"bounded": True}), encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(EXECUTOR.QualificationError, match="non-symlink"):
        EXECUTOR._strict_json(link)


def test_ui_validator_parser_fails_closed_on_broadened_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePath:
        @staticmethod
        def read_text(*, encoding: str) -> str:
            assert encoding == "utf-8"
            return "const DEFAULT_ACCEPT = '*/*';"

    monkeypatch.setattr(EXECUTOR, "_repo_file", lambda _path: _FakePath())
    with pytest.raises(EXECUTOR.QualificationError, match="validator expression drift"):
        EXECUTOR._parse_ui_default_validator()


def test_result_schema_rejects_unknown_fields() -> None:
    result = EXECUTOR.run()
    result["unexpected"] = True
    schema = EXECUTOR._strict_json(LANE / "result.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(result))
    assert errors
    assert "Additional properties are not allowed" in errors[0].message


def test_result_schema_rejects_cross_mapping_and_duplicate_negatives() -> None:
    result = EXECUTOR.run()
    schema = EXECUTOR._strict_json(LANE / "result.schema.json")
    result["bindings"][0]["capability_id"] = "runtime.lvs.supported-formats"
    result["observations"]["adjacent_negatives"][1] = copy.deepcopy(
        result["observations"]["adjacent_negatives"][0]
    )
    assert list(Draft202012Validator(schema).iter_errors(result))


def test_executor_imports_no_external_transport_or_process_module() -> None:
    tree = ast.parse((LANE / "executor.py").read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports.isdisjoint({"socket", "subprocess", "requests", "httpx", "docker"})
