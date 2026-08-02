"""Adversarial tests for the request-cancellation static rebase compiler."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("request_cancellation_compiler", PACKAGE / "compiler.py")
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def contract():
    return compiler.load_and_validate(compiler.CONTRACT_PATH, compiler.SCHEMA_PATH)


def test_current_package_passes_fail_closed_check() -> None:
    result = compiler.check()

    assert result["status"] == "passed"
    assert result["production_source_count"] == 8
    assert result["test_source_count"] == 5
    assert result["current_contract_counts"] == {"lvs-mcp": 13, "lvs": 18, "rt-vlm": 28}
    assert result["runtime_evidence"] == []
    assert result["passed_current_promotions"] == 0
    assert result["warehouse_sample_bundle"] == "excluded"


def test_source_hash_tampering_fails() -> None:
    mutated = copy.deepcopy(contract())
    mutated["source_locks"][0]["raw_sha256"] = "0" * 64

    with pytest.raises(compiler.QualificationError, match="source raw hash drift"):
        compiler.verify_source_locks(mutated)


def test_predecessor_tree_tampering_fails() -> None:
    mutated = copy.deepcopy(contract())
    mutated["predecessor_packages"][0]["tree_sha256"] = "0" * 64

    with pytest.raises(compiler.QualificationError, match="predecessor package identity drift"):
        compiler.verify_predecessors(mutated)


def test_static_invocation_expansion_fails() -> None:
    mutated = copy.deepcopy(contract())
    mutated["test_policy"]["allowed_invocations"][0].append("--collect-only")

    with pytest.raises(compiler.QualificationError, match="static test invocation drift"):
        compiler.verify_policy(mutated)


def test_runtime_evidence_or_promotion_claim_fails() -> None:
    mutated = copy.deepcopy(contract())
    mutated["qualification_state"]["runtime_evidence"] = ["invented-runtime-receipt"]
    mutated["qualification_state"]["passed_current_promotions"] = 1

    with pytest.raises(compiler.QualificationError, match="boundary drift"):
        compiler.verify_policy(mutated)


def test_current_contract_count_tampering_fails() -> None:
    mutated = copy.deepcopy(contract())
    mutated["current_contracts"][2]["current_count"] = 27
    source_hashes = compiler.verify_source_locks(mutated)

    with pytest.raises(compiler.QualificationError, match="count policy drift"):
        compiler.verify_current_contracts(mutated, source_hashes)


def test_warehouse_boundary_is_schema_const() -> None:
    mutated = copy.deepcopy(contract())
    mutated["qualification_state"]["warehouse_sample_bundle"] = "included"
    schema = compiler.strict_json(compiler.SCHEMA_PATH.read_bytes(), "schema")
    errors = list(compiler.Draft202012Validator(schema).iter_errors(mutated))

    assert any(error.validator == "const" for error in errors)


def test_rt_local_extension_denominator_tampering_fails() -> None:
    mutated = copy.deepcopy(compiler.RT_LOCAL_EXTENSION_CONTRACT)
    mutated["documented_operation_count"] = 28

    with pytest.raises(compiler.QualificationError, match="27/28 extension drift"):
        compiler.verify_rt_local_extension(mutated, "adversarial")
