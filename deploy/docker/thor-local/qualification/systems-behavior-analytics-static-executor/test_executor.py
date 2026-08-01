# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Adversarial tests for the candidate-static Behavior Analytics executor."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parent


def _load_executor():
    name = "thor_systems_behavior_analytics_static_executor"
    spec = importlib.util.spec_from_file_location(name, LANE / "executor.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_static_result_is_strict_and_non_advancing() -> None:
    executor = _load_executor()
    result = executor.execute()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result)
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["result"] == "candidate_static_pass_non_advancing"
    assert all(
        not binding["canonical_state_advanced"] for binding in result["bindings"]
    )
    assert {
        row["case_id"]: row["outcome"]
        for row in result["observations"]["adjacent_cases"]
    } == executor.EXPECTED_CASE_OUTCOMES


def test_contract_schema_rejects_unknown_property_and_promotion() -> None:
    contract = json.loads((LANE / "contract.json").read_text(encoding="utf-8"))
    schema = json.loads((LANE / "contract.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    unknown = deepcopy(contract)
    unknown["unexpected"] = True
    assert list(validator.iter_errors(unknown))
    promoted = deepcopy(contract)
    promoted["policy"]["can_mark_passed_current"] = True
    assert list(validator.iter_errors(promoted))


def test_source_lock_tamper_duplicate_and_path_escape_fail_closed() -> None:
    executor = _load_executor()
    contract = executor._load_contract()
    tampered = deepcopy(contract)
    tampered["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(executor.QualificationError, match="source lock mismatch"):
        executor._verify_source_locks(tampered)
    duplicate = deepcopy(contract)
    duplicate["source_locks"][1] = deepcopy(duplicate["source_locks"][0])
    with pytest.raises(executor.QualificationError, match="exactly 75 unique"):
        executor._verify_source_locks(duplicate)
    with pytest.raises(executor.QualificationError, match="unsafe repository path"):
        executor._repo_file("../escape")


def test_contract_source_membership_substitution_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _load_executor()
    original = executor._strict_json

    def substitute(path: Path) -> dict:
        value = original(path)
        if path == LANE / "contract.json":
            value["source_locks"][0] = deepcopy(value["source_locks"][1])
        return value

    monkeypatch.setattr(executor, "_strict_json", substitute)
    with pytest.raises(executor.QualificationError, match="source-lock set drift"):
        executor._load_contract()


def test_result_schema_rejects_runtime_evidence_and_overclaim() -> None:
    executor = _load_executor()
    result = executor.execute()
    schema = json.loads((LANE / "result.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    runtime = deepcopy(result)
    runtime["runtime_evidence"] = [{"invented": True}]
    assert list(validator.iter_errors(runtime))
    overclaim = deepcopy(result)
    overclaim["observations"]["pipeline_subset"]["full_pipeline_claimed"] = True
    assert list(validator.iter_errors(overclaim))
    promotion = deepcopy(result)
    promotion["result"] = "passed_current"
    assert list(validator.iter_errors(promotion))
    cross_mapped = deepcopy(result)
    cross_mapped["bindings"][0]["capability_id"] = "protocol.behavior.broker-sinks"
    cross_mapped["observations"]["adjacent_cases"][1] = deepcopy(
        cross_mapped["observations"]["adjacent_cases"][0]
    )
    assert list(validator.iter_errors(cross_mapped))


def test_executor_ast_has_no_forbidden_io_or_lifecycle_surface() -> None:
    tree = ast.parse((LANE / "executor.py").read_text(encoding="utf-8"))
    forbidden_imports = {
        "aiohttp",
        "docker",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert not (imported & forbidden_imports)
    assert not ({"Popen", "run", "system", "urlopen"} & called)
    assert "write_text" not in called
    assert "write_bytes" not in called


def test_lane_contract_path_is_not_replaceable() -> None:
    executor = _load_executor()
    with pytest.raises(executor.QualificationError, match="lane-owned contract"):
        executor._load_contract(LANE / "contract.schema.json")


def test_product_import_state_is_restored() -> None:
    executor = _load_executor()
    path_before = list(sys.path)
    modules_before = {
        name: module
        for name, module in sys.modules.items()
        if executor._is_isolated_module(name)
    }
    result = executor.execute()
    modules_after = {
        name: module
        for name, module in sys.modules.items()
        if executor._is_isolated_module(name)
    }
    assert result["confinement"]["product_and_stub_import_state_restored"] is True
    assert sys.path == path_before
    assert modules_after == modules_before


def test_every_loaded_repo_product_module_is_source_locked() -> None:
    executor = _load_executor()
    contract = executor._load_contract()
    with executor._isolated_product():
        assert executor._verify_loaded_product_closure(contract) == 54
        unlocked = deepcopy(contract)
        unlocked["source_locks"] = [
            row
            for row in unlocked["source_locks"]
            if not row["path"].endswith("calibration_e.py")
        ]
        with pytest.raises(
            executor.QualificationError, match="unlocked loaded product module"
        ):
            executor._verify_loaded_product_closure(unlocked)


def test_strict_json_rejects_symlink(tmp_path: Path) -> None:
    executor = _load_executor()
    target = tmp_path / "target.json"
    target.write_text('{"bounded":true}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(executor.QualificationError, match="non-symlink"):
        executor._strict_json(link)
