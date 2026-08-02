from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "successor_500_wave1_compiler", COMPILER_PATH
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


@pytest.fixture(scope="module")
def source_inputs():
    contract = compiler.load_contract()
    snapshot, document = compiler.load_selected_oracles(contract)
    wave8 = compiler.execute_wave8(contract)
    return contract, snapshot, document, wave8


@pytest.fixture(scope="module")
def outputs(source_inputs):
    return compiler.compile_outputs(*source_inputs)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_errors(value, path: Path):
    return list(Draft202012Validator(_load(path)).iter_errors(value))


def test_checked_artifacts_equal_fresh_execution(outputs):
    receipt, successor = outputs
    assert receipt == _load(compiler.RECEIPT_PATH)
    assert successor == _load(compiler.SUCCESSOR_PATH)


def test_exact_two_successor_capability_ids(outputs):
    receipt, successor = outputs
    assert tuple(item["capability_id"] for item in receipt["entries"]) == (
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
        "manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
    )
    assert [item["capability_id"] for item in successor["annotations"]] == [
        item["capability_id"] for item in receipt["entries"]
    ]
    assert successor["counts"] == {
        "oracles": 500,
        "annotated_rows": 2,
        "unannotated_rows": 498,
        "mutated_oracle_rows": 0,
        "runtime_promotions": 0,
    }


def test_oracle_document_is_selected_v2_document_byte_identical(source_inputs, outputs):
    _, snapshot, document, _ = source_inputs
    _, successor = outputs
    identity = successor["oracle_document"]
    assert snapshot.set_id == identity["set_id"]
    assert snapshot.descriptor_raw_sha256 == identity["descriptor_raw_sha256"]
    assert (
        compiler.sha256(compiler.canonical_bytes(document))
        == identity["canonical_sha256"]
    )
    assert identity["byte_identical_to_selected_metadata_set"] is True
    assert successor["global_invariants"]["canonical_metadata_mutated"] is False


def test_selected_v2_schema_still_validates_byte_identical_document(source_inputs):
    _, snapshot, document, _ = source_inputs
    errors = list(
        Draft202012Validator(snapshot.schema("capability_oracles_schema")).iter_errors(
            document
        )
    )
    assert errors == []


def test_all_498_unannotated_rows_are_digest_bound(source_inputs, outputs):
    _, _, document, _ = source_inputs
    _, successor = outputs
    indexes = {item["oracle_index"] for item in successor["annotations"]}
    partition = [
        {
            "index": index,
            "capability_id": row["capability_id"],
            "row_canonical_sha256": compiler.sha256(compiler.canonical_bytes(row)),
        }
        for index, row in enumerate(document["oracles"])
        if index not in indexes
    ]
    assert len(partition) == 498
    assert (
        compiler.sha256(compiler.canonical_bytes(partition))
        == successor["unannotated_partition"]["ordered_row_identity_canonical_sha256"]
    )
    assert successor["unannotated_partition"]["all_rows_byte_identical"] is True


@pytest.mark.parametrize(
    "field,expected",
    [
        ("current_state", "open_unexecuted"),
        ("runtime_state", "not_qualified"),
        ("evidence", []),
        ("can_promote_runtime_state", False),
    ],
)
def test_protected_selected_row_fields_unchanged(source_inputs, field, expected):
    contract, _, document, _ = source_inputs
    for binding in contract["bindings"]:
        row = document["oracles"][binding["oracle_index"]]
        assert row[field] == expected
        assert row["readiness"]["executor_ready"] is False
        gate = next(
            item for item in row["admission_gates"] if item["id"] == "operator-approval"
        )
        assert gate["status"] == "unmet"


def test_annotations_are_explicitly_non_promoting(outputs):
    receipt, successor = outputs
    assert receipt["runtime_evidence"] == []
    assert receipt["official_capability_effect"] == "none_candidate_only"
    for item in successor["annotations"]:
        assert item["runtime_evidence"] == []
        assert item["admission_effect"]["full_oracle_executor_ready"] is False
        assert item["admission_effect"]["operator_gate_satisfied"] is False
        assert item["retained_blockers"]
    assert all(
        value is False
        for key, value in successor["global_invariants"].items()
        if key.endswith("_changed")
    )


def test_execution_receipt_forbids_every_external_action(outputs):
    receipt, _ = outputs
    assert receipt["safety"]["temporary_files_cleaned"] is True
    assert all(
        value is False
        for key, value in receipt["safety"].items()
        if key != "temporary_files_cleaned"
    )


def test_unrelated_oracle_mutation_is_rejected(source_inputs):
    contract, snapshot, document, wave8 = source_inputs
    mutated = copy.deepcopy(document)
    mutated["oracles"][0]["current_state"] = "passed_current"
    with pytest.raises(
        compiler.CompilationError, match="oracle document canonical identity"
    ):
        compiler.compile_outputs(contract, snapshot, mutated, wave8)


def test_wave8_result_mutation_is_rejected(source_inputs):
    contract, snapshot, document, wave8 = source_inputs
    mutated = copy.deepcopy(wave8)
    mutated["entries"][0]["retained_blockers"].pop()
    with pytest.raises(
        compiler.CompilationError, match="Wave 8 result canonical identity"
    ):
        compiler.compile_outputs(contract, snapshot, document, mutated)


def test_nonpromotion_boundary_rejects_state_evidence_and_operator_changes(
    source_inputs,
):
    contract, _, document, _ = source_inputs
    row = copy.deepcopy(document["oracles"][contract["bindings"][0]["oracle_index"]])
    row["current_state"] = "passed_current"
    with pytest.raises(compiler.CompilationError, match="non-promotion boundary"):
        compiler.assert_oracle_boundary(row, contract["bindings"][0]["capability_id"])
    row = copy.deepcopy(document["oracles"][contract["bindings"][0]["oracle_index"]])
    row["evidence"] = [{"forged": True}]
    with pytest.raises(compiler.CompilationError, match="non-promotion boundary"):
        compiler.assert_oracle_boundary(row, contract["bindings"][0]["capability_id"])
    row = copy.deepcopy(document["oracles"][contract["bindings"][0]["oracle_index"]])
    next(item for item in row["admission_gates"] if item["id"] == "operator-approval")[
        "status"
    ] = "satisfied"
    with pytest.raises(compiler.CompilationError, match="operator gate changed"):
        compiler.assert_oracle_boundary(row, contract["bindings"][0]["capability_id"])


def test_successor_schema_rejects_promotion_and_runtime_evidence(outputs):
    _, successor = outputs
    promoted = copy.deepcopy(successor)
    promoted["annotations"][0]["admission_effect"]["full_oracle_executor_ready"] = True
    assert _schema_errors(promoted, compiler.SUCCESSOR_SCHEMA_PATH)
    evidenced = copy.deepcopy(successor)
    evidenced["annotations"][0]["runtime_evidence"] = [{"forged": True}]
    assert _schema_errors(evidenced, compiler.SUCCESSOR_SCHEMA_PATH)


def test_receipt_schema_rejects_external_action_and_extra_key(outputs):
    receipt, _ = outputs
    unsafe = copy.deepcopy(receipt)
    unsafe["safety"]["network_used"] = True
    assert _schema_errors(unsafe, compiler.RECEIPT_SCHEMA_PATH)
    extra = copy.deepcopy(receipt)
    extra["runtime_pass"] = True
    assert _schema_errors(extra, compiler.RECEIPT_SCHEMA_PATH)


def test_contract_rejects_reordered_or_extra_binding(tmp_path):
    contract = _load(compiler.CONTRACT_PATH)
    contract["bindings"].reverse()
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(compiler.CompilationError, match="binding order"):
        compiler.load_contract(path)
    contract = _load(compiler.CONTRACT_PATH)
    contract["bindings"].append(copy.deepcopy(contract["bindings"][0]))
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(compiler.CompilationError, match="schema violation"):
        compiler.load_contract(path)


def test_contract_rejects_source_hash_drift(tmp_path):
    contract = _load(compiler.CONTRACT_PATH)
    contract["source_locks"][0]["raw_sha256"] = "0" * 64
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(compiler.CompilationError, match="source lock mismatch"):
        compiler.load_contract(path)


def test_compiler_has_no_external_action_imports_or_process_calls():
    tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint({"socket", "subprocess", "requests", "urllib", "docker"})
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {"system", "popen", "run", "Popen", "connect", "bind", "listen"}
    )


def test_unsafe_repository_path_is_rejected():
    with pytest.raises(compiler.CompilationError, match="unsafe repository path"):
        compiler.repo_path("../outside")


def test_intermediate_repository_symlink_is_rejected(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.json").write_text("{}", encoding="utf-8")
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.CompilationError, match="contains a symlink"):
        compiler.repo_path("linked/source.json")
