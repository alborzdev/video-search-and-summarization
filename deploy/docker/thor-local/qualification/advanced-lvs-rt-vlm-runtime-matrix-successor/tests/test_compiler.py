from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("advanced_runtime_matrix_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_matrix_is_exactly_checked_in() -> None:
    value = compiler.build_matrix()
    assert compiler.MATRIX_PATH.read_bytes() == compiler._render(value)


def test_matrix_validates_against_strict_schema() -> None:
    value = compiler.build_matrix()
    schema = json.loads(compiler.MATRIX_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_seven_exact_official_rows_have_current_runtime_evidence() -> None:
    matrix = compiler.build_matrix()
    assert [row["official_index"] for row in matrix["rows"]] == [
        299, 300, 302, 336, 342, 345, 367
    ]
    assert all(row["overlay_runtime_state"] == "passed_current_thor" for row in matrix["rows"])
    assert all(row["runtime_evidence"]["receipt_sha256"] for row in matrix["rows"])


def test_overlay_does_not_falsify_canonical_admission() -> None:
    matrix = compiler.build_matrix()
    assert matrix["summary"]["canonical_promotions"] == 0
    assert matrix["matrix_semantics"]["canonical_admission_claimed"] is False
    assert all(row["canonical_runtime_state"] == "not_qualified" for row in matrix["rows"])
    assert all(row["canonical_state_advanced"] is False for row in matrix["rows"])


def test_receipts_are_source_locked_schema_valid_and_privacy_safe() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    for entry in contract["entries"]:
        receipt = compiler._validate_receipt(entry)
        assert receipt["contract_sha256"] == entry["contract_sha256"]


def test_multi_capability_receipt_is_bound_to_both_exact_rows() -> None:
    contract = compiler._load_json(compiler.CONTRACT_PATH)
    entries = [
        entry
        for entry in contract["entries"]
        if entry["package_id"] == "rt-vlm-file-dense-captions-runtime-successor"
    ]
    assert [entry["official_index"] for entry in entries] == [336, 342]
    for entry in entries:
        receipt = compiler._validate_receipt(entry)
        assert entry["capability_id"] in receipt["capability_ids"]


def test_policy_excludes_agent_generate_and_warehouse_sample() -> None:
    matrix = compiler.build_matrix()
    assert matrix["summary"]["agent_generate_calls"] == 0
    assert matrix["summary"]["warehouse_sample_bundle"] == "excluded"
    assert all(row["warehouse_sample_bundle"] == "excluded" for row in matrix["rows"])
