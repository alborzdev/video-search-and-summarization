"""Adversarial tests for the isolated live metadata 500 migration set."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "live_metadata_500_migration_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


@pytest.fixture(scope="module")
def compiled():
    documents, payloads, locks = compiler._load_sources()
    proof, proof_schema, outputs = compiler.compile_migration()
    registry = json.loads(outputs[compiler.ORACLE_OUTPUT])
    oracle_schema = json.loads(outputs[compiler.ORACLE_SCHEMA_OUTPUT])
    return (
        documents,
        payloads,
        locks,
        proof,
        proof_schema,
        outputs,
        registry,
        oracle_schema,
    )


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _blob(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def test_checked_outputs_are_deterministic_and_hash_locked(compiled):
    _, _, _, proof, proof_schema, outputs, _, _ = compiled
    compiler.validate_migration(proof, proof_schema, outputs)
    assert compiler.main(["--check"]) == 0
    for path, payload in outputs.items():
        assert path.parent == PACKAGE
        assert path.read_bytes() == payload
    key_by_path = {
        compiler.LEDGER_OUTPUT: "ledger",
        compiler.MANIFEST_OUTPUT: "manifest",
        compiler.ACCEPTANCE_OUTPUT: "acceptance",
        compiler.ORACLE_OUTPUT: "oracles",
        compiler.ORACLE_SCHEMA_OUTPUT: "oracle_schema",
        compiler.PROOF_OUTPUT: "proof",
        compiler.PROOF_SCHEMA_OUTPUT: "proof_schema",
    }
    assert {_sha(outputs[path]) for path in key_by_path} == {
        compiler.EXPECTED[key] for key in key_by_path.values()
    }
    assert proof["migration_payload_sha256"] == compiler.EXPECTED["proof_payload"]


def test_three_successor_files_are_exact_byte_copies(compiled):
    _, payloads, _, _, _, outputs, _, _ = compiled
    assert outputs[compiler.LEDGER_OUTPUT] == payloads["projected_ledger"]
    assert outputs[compiler.MANIFEST_OUTPUT] == payloads["projected_manifest"]
    assert outputs[compiler.ACCEPTANCE_OUTPUT] == payloads["projected_acceptance"]


def test_exact_oracle_order_prefix_and_bindings(compiled):
    documents, _, _, proof, _, _, registry, _ = compiled
    capabilities = documents["projected_ledger"]["capabilities"]
    projected = documents["projected_oracle_successor"]["projected_oracles"]
    assert registry == {
        "schema_version": 2,
        "target": documents["live_oracles"]["target"],
        "policy": documents["live_oracles"]["policy"],
        "oracles": projected,
    }
    assert registry["oracles"][:289] == documents["live_oracles"]["oracles"]
    assert [row["capability_id"] for row in registry["oracles"]] == [
        row["id"] for row in capabilities
    ]
    assert (
        proof["identity_order"]["capability_ids_sha256"]
        == proof["identity_order"]["oracle_capability_ids_sha256"]
    )


def test_zero_gap_and_candidate_non_activation_summary(compiled):
    _, _, _, proof, _, _, _, _ = compiled
    summary = proof["summary"]
    assert (
        summary["aggregate_drift_count"]
        == summary["acceptance_coverage_gap_count"]
        == 0
    )
    assert summary["candidate_runtime_evidence_count"] == 0
    assert summary["candidate_executor_count"] == 0
    assert summary["candidate_materialization_count"] == 0
    assert summary["candidate_promotable_count"] == 0
    assert summary["candidate_acceptance_class_counts"] == {
        "alternate_local_lane": 46,
        "external_optional": 6,
        "required_local": 159,
    }
    assert summary["candidate_runtime_state_counts"] == {
        "not_applicable": 6,
        "not_qualified": 205,
    }
    assert summary["candidate_protocol_binding_count"] == 23
    assert summary["candidate_workload_binding_count"] == 60


def test_compact_oracle_schema_is_strict_and_discriminated(compiled):
    _, _, _, _, _, _, registry, schema = compiled
    Draft202012Validator.check_schema(schema)
    assert len(json.dumps(schema)) < 100_000
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(registry))

    def rejected(mutator):
        value = copy.deepcopy(registry)
        mutator(value)
        assert list(validator.iter_errors(value))

    rejected(lambda value: value.__setitem__("successor_id", "proof-wrapper-key"))
    rejected(
        lambda value: value["oracles"][0].__setitem__("successor_schema_version", 1)
    )
    rejected(lambda value: value["oracles"][289].pop("successor_schema_version"))
    rejected(lambda value: value["oracles"][289]["fixture"].__setitem__("loose", True))


def test_order_duplicate_and_binding_attacks_fail_semantics(compiled):
    documents, _, _, _, _, _, registry, _ = compiled

    def rejected(mutator):
        value = copy.deepcopy(registry)
        mutator(value)
        with pytest.raises(compiler.MigrationError):
            compiler._validate_post_state(documents, value)

    rejected(
        lambda value: value["oracles"].__setitem__(
            slice(289, 291), reversed(value["oracles"][289:291])
        )
    )
    rejected(
        lambda value: value["oracles"].__setitem__(
            290, copy.deepcopy(value["oracles"][289])
        )
    )
    rejected(
        lambda value: value["oracles"][289]["ledger_binding"].__setitem__(
            "title", "substituted"
        )
    )
    rejected(
        lambda value: value["oracles"][289].__setitem__(
            "oracle_id", "oracle.substituted"
        )
    )
    rejected(
        lambda value: value["oracles"][289]["fixture"].__setitem__("namespace", "wrong")
    )


@pytest.mark.parametrize(
    "path,value",
    [
        (("evidence",), [{"invented": True}]),
        (("can_promote_runtime_state",), True),
        (("fixture", "materialization"), {}),
        (("execution_bounds", "executor"), "invented"),
        (("execution_bounds", "collectors"), []),
        (("execution_bounds", "max_actions"), 1),
        (("cleanup", "targets"), []),
        (("readiness", "executor_ready"), True),
    ],
)
def test_candidate_activation_injections_fail(compiled, path, value):
    documents, _, _, _, _, _, registry, _ = compiled
    mutated = copy.deepcopy(registry)
    target = mutated["oracles"][289]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(compiler.MigrationError):
        compiler._validate_post_state(documents, mutated)


def test_external_boundary_and_operator_gate_attacks_fail(compiled):
    documents, _, _, _, _, _, registry, _ = compiled
    external_index = next(
        index
        for index, row in enumerate(registry["oracles"])
        if index >= 289 and row["acceptance_class"] == "external_optional"
    )
    for mutator in (
        lambda row: row.__setitem__("execution_boundary", "local"),
        lambda row: row["execution_bounds"].__setitem__(
            "network_scope", "loopback_or_compose_internal"
        ),
        lambda row: next(
            g for g in row["admission_gates"] if g["id"] == "operator-approval"
        ).__setitem__("status", "met"),
    ):
        mutated = copy.deepcopy(registry)
        mutator(mutated["oracles"][external_index])
        with pytest.raises(compiler.MigrationError):
            compiler._validate_post_state(documents, mutated)


def test_protocol_workload_and_assertion_attacks_fail(compiled):
    documents, _, _, _, _, _, registry, _ = compiled
    protocol_index = next(
        index
        for index, row in enumerate(registry["oracles"])
        if row.get("protocol_v2_binding")
    )
    workload_index = next(
        index
        for index, row in enumerate(registry["oracles"])
        if row.get("workload_binding")
    )
    attacks = [
        (
            protocol_index,
            lambda row: row["protocol_v2_binding"].__setitem__(
                "activation_supported", True
            ),
        ),
        (
            protocol_index,
            lambda row: row["protocol_v2_binding"].__setitem__("readiness", "ready"),
        ),
        (
            workload_index,
            lambda row: row["workload_binding"].__setitem__(
                "candidate_id", "substituted"
            ),
        ),
        (
            289,
            lambda row: row["assertions"][0].__setitem__("observation_id", "dangling"),
        ),
    ]
    for index, mutator in attacks:
        mutated = copy.deepcopy(registry)
        mutator(mutated["oracles"][index])
        with pytest.raises(compiler.MigrationError):
            compiler._validate_post_state(documents, mutated)


def test_aggregate_and_acceptance_gap_attacks_fail(compiled):
    documents, _, _, _, _, _, registry, _ = compiled
    manifest_attack = copy.deepcopy(documents)
    manifest_attack["projected_manifest"]["features"][0]["runtime_state"] = "passed"
    with pytest.raises(compiler.MigrationError):
        compiler._validate_post_state(manifest_attack, registry)
    coverage_attack = copy.deepcopy(documents)
    coverage_attack["projected_acceptance"]["coverage"]["features"][0][
        "scenario_ids"
    ] = []
    with pytest.raises(compiler.MigrationError):
        compiler._validate_post_state(coverage_attack, registry)


def test_journal_before_after_hashes_and_reverse_rollback(compiled):
    documents, _, _, proof, _, _, _, _ = compiled
    del documents
    journal = proof["migration_journal"]
    for row in journal:
        before = compiler._repo_file(row["live_path"]).read_bytes()
        after = compiler._repo_file(row["staged_path"]).read_bytes()
        assert row["before"]["raw_sha256"] == _sha(before)
        assert row["after"]["raw_sha256"] == _sha(after)
        assert row["before"]["git_blob_oid"] == _blob(before)
        assert row["after"]["git_blob_oid"] == _blob(after)
        assert row["before"]["canonical_sha256"] == compiler._sha_json(
            compiler._strict_json(before, "before")
        )
        assert row["after"]["canonical_sha256"] == compiler._sha_json(
            compiler._strict_json(after, "after")
        )
    assert [row["live_path"] for row in proof["rollback"]["reverse_targets"]] == [
        row["live_path"] for row in reversed(journal)
    ]


def test_exact_proof_schema_rejects_nested_substitution(compiled):
    _, _, _, proof, proof_schema, _, _, _ = compiled
    mutated = copy.deepcopy(proof)
    mutated["summary"]["candidate_promotable_count"] = 1
    assert list(Draft202012Validator(proof_schema).iter_errors(mutated))


@pytest.mark.parametrize(
    "payload", [b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}']
)
def test_strict_json_rejects_duplicate_and_nonfinite(payload):
    with pytest.raises(compiler.MigrationError):
        compiler._strict_json(payload, "attack")


@pytest.mark.parametrize("path", ["", "/tmp/absolute", "../escape", "a/../../escape"])
def test_repo_path_rejects_unsafe_names(path):
    with pytest.raises(compiler.MigrationError):
        compiler._repo_file(path)


def test_atomic_writer_is_package_bounded_and_rejects_symlinks(tmp_path, monkeypatch):
    with pytest.raises(compiler.MigrationError):
        compiler._atomic_write(tmp_path / compiler.PROOF_OUTPUT.name, b"x")
    monkeypatch.setattr(compiler, "PACKAGE", tmp_path)
    target = tmp_path / compiler.PROOF_OUTPUT.name
    compiler._atomic_write(target, b"safe")
    assert target.read_bytes() == b"safe"
    target.unlink()
    target.symlink_to(tmp_path / "missing")
    with pytest.raises(compiler.MigrationError):
        compiler._atomic_write(target, b"blocked")


def test_compiler_has_no_runtime_network_docker_or_subprocess_surface():
    tree = ast.parse((PACKAGE / "compiler.py").read_text())
    forbidden = {"requests", "urllib", "socket", "subprocess", "docker"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names
            if isinstance(node, ast.Import)
            else [ast.alias(name=node.module or "")]
        )
    }
    assert not imported & forbidden


def test_policy_excludes_warehouse_and_live_apply(compiled):
    _, _, _, proof, _, _, _, _ = compiled
    assert proof["policy"]["warehouse_sample_bundle"] == "excluded"
    assert proof["policy"]["modifies_live_files"] is False
    assert proof["policy"]["creates_git_patch"] is False
    assert proof["rollback"]["live_apply_authorized"] is False
    assert (
        proof["known_application_blocker"]["id"]
        == "live-v2-oracle-validator-adapter-not-included"
    )
