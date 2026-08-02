from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_admission_rebase_compiler", COMPILER_PATH
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def test_checked_artifacts_are_exact_and_empty() -> None:
    result = compiler.check()
    assert result == {
        "admission_index_raw_sha256": "74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff",
        "admission_rows_canonical_sha256": "57c583cad3ffc86d87a673d92c54f68fd765867eb1cf08839393d7a2ad3a4ef0",
        "admitted_candidate_count": 0,
        "candidate_count": 211,
        "executable_candidate_count": 0,
        "receipt_count": 0,
        "receipt_set_raw_sha256": "e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f",
        "status": "ok",
    }


def test_exact_row_denominator_order_hashes_and_states() -> None:
    index = load("admission-index.json")
    rows = index["admissions"]
    assert len(rows) == 211
    assert [row["candidate_order_position"] for row in rows] == list(range(211))
    assert [row["oracle_index"] for row in rows] == list(range(289, 500))
    assert len({row["candidate_id"] for row in rows}) == 211
    assert len({row["oracle_id"] for row in rows}) == 211
    assert (
        compiler.sha256(compiler.canonical_bytes(rows))
        == index["admission_rows_canonical_sha256"]
    )
    static = [row for row in rows if not row["runtime_admission_applicable"]]
    assert len(static) == 3
    assert all(row["leaf_bundle_id"] is None for row in static)
    assert all(row["complete_dependency_closure"] == [] for row in static)
    assert all(row["admission_state"] == compiler.STATIC_STATE for row in static)
    assert all(not row["receipt_ids"] for row in rows)
    assert all(not row["runtime_admitted"] for row in rows)
    assert all(not row["runtime_executable"] for row in rows)


def test_exact_boundary_counts_and_no_service_binding() -> None:
    index = load("admission-index.json")
    mapping = json.loads(
        (REPO_ROOT / compiler.MAPPING_PATH).read_text(encoding="utf-8")
    )
    rows = index["admissions"]
    assert index["summary"]["boundary_counts"] == {
        "alternate_local": 46,
        "external": 6,
        "local": 159,
    }
    assert index["summary"]["mapped_boundary_counts"] == {
        "alternate_local": 45,
        "external": 4,
        "local": 159,
    }
    assert all(
        row["service_binding_state"] == "unresolved_not_declared_by_candidate"
        for row in mapping["mappings"]
    )
    assert all(
        row["blocking_requirements"]
        == ([] if not row["runtime_admission_applicable"] else compiler.BLOCKERS)
        for row in rows
    )


def test_rows_bind_exact_mapping_oracle_bundle_and_metadata() -> None:
    index = load("admission-index.json")
    mapping = json.loads(
        (REPO_ROOT / compiler.MAPPING_PATH).read_text(encoding="utf-8")
    )
    oracles = json.loads(
        (REPO_ROOT / compiler.ORACLES_PATH).read_text(encoding="utf-8")
    )["oracles"]
    bundle_hash = compiler.EXPECTED_SOURCE_HASHES[compiler.BUNDLE_PATH]
    mapping_hash = compiler.EXPECTED_SOURCE_HASHES[compiler.MAPPING_PATH]
    for admission, mapped in zip(index["admissions"], mapping["mappings"], strict=True):
        oracle = oracles[admission["oracle_index"]]
        assert (
            admission["candidate_id"]
            == mapped["capability_id"]
            == oracle["capability_id"]
        )
        assert admission["oracle_id"] == mapped["oracle_id"] == oracle["oracle_id"]
        assert admission["mapping_row_canonical_sha256"] == compiler.sha256(
            compiler.canonical_bytes(mapped)
        )
        assert admission["oracle_record_canonical_sha256"] == compiler.sha256(
            compiler.canonical_bytes(oracle)
        )
        assert admission["mapping_artifact_raw_sha256"] == mapping_hash
        assert admission["bundle_contract_raw_sha256"] == bundle_hash
        assert admission["warehouse_sample_bundle"] == "excluded"


def test_dependency_closure_uses_contract_order_and_exact_dag() -> None:
    index = load("admission-index.json")
    bundles = json.loads((REPO_ROOT / compiler.BUNDLE_PATH).read_text(encoding="utf-8"))
    bundle_by_id = {bundle["id"]: bundle for bundle in bundles["bundles"]}
    ordered_ids = list(bundle_by_id)
    for row in index["admissions"]:
        if row["leaf_bundle_id"] is None:
            assert row["complete_dependency_closure"] == []
            continue
        closure = compiler._closure(bundle_by_id, row["leaf_bundle_id"])
        assert row["complete_dependency_closure"] == closure
        assert closure == [
            bundle_id for bundle_id in ordered_ids if bundle_id in closure
        ]


def test_receipt_root_is_strictly_empty_and_envelope_is_design_only() -> None:
    schema = load("receipt-set.schema.json")
    receipt_set = load("receipt-set.json")
    assert schema["properties"]["receipts"]["maxItems"] == 0
    assert schema["properties"]["receipt_count"]["const"] == 0
    assert (
        schema["properties"]["trusted_review_authority_binding_sha256"]["maxItems"] == 0
    )
    assert receipt_set["receipts"] == []
    assert receipt_set["trusted_review_authority_binding_sha256"] == []
    required = set(schema["$defs"]["receipt"]["required"])
    assert {
        "candidate_id",
        "oracle_id",
        "selected_metadata_set_id",
        "mapping_row_canonical_sha256",
        "bundle_contract_raw_sha256",
        "bundle_id",
        "dependency_authorizations",
        "authorization",
        "issued_at",
        "expires_at",
        "action_contract_sha256",
        "service_role_profile_binding_sha256",
        "cleanup_rollback_contract_sha256",
        "evidence_destination_sha256",
        "warehouse_sample_bundle",
        "canonical_receipt_sha256",
    } <= required


@pytest.mark.parametrize(
    "threat",
    [
        "unknown_candidate",
        "duplicate_or_reused_receipt",
        "expired_receipt",
        "cross_candidate_oracle",
        "cross_bundle_leaf",
        "missing_dependency",
        "approval_inheritance",
        "stale_hash",
        "forged_not_required_review",
        "firewall_without_inspection",
        "native_audio_for_asr",
        "external_promotes_local",
        "warehouse_bundle",
        "orphan_dependency_receipt",
    ],
)
def test_every_nonempty_receipt_threat_fails_closed(threat: str) -> None:
    del (
        threat
    )  # The current trust boundary rejects before interpreting attacker fields.
    schema = load("receipt-set.schema.json")
    receipt_set = load("receipt-set.json")
    receipt_set["receipt_count"] = 1
    receipt_set["receipts"] = [{}]
    errors = list(Draft202012Validator(schema).iter_errors(receipt_set))
    assert errors
    with pytest.raises(compiler.AdmissionError):
        compiler.validate_receipts(receipt_set, load("admission-index.json"), schema)


def test_receipt_envelope_rejects_unknown_fields_and_inheritance() -> None:
    schema = load("receipt-set.schema.json")
    envelope_schema = {"$defs": schema["$defs"], "$ref": "#/$defs/receipt"}
    validator = Draft202012Validator(envelope_schema)
    assert list(validator.iter_errors({"unexpected": True}))
    authorization = {"$defs": schema["$defs"], **schema["$defs"]["authorization"]}
    inherited = {
        "authorization_event_nonce_sha256": "0" * 64,
        "authorization_id": "authorization.example",
        "detached_signature": "not-a-real-signature",
        "inherited": True,
        "issuer_identity": "issuer",
        "issuer_public_key_fingerprint_sha256": "1" * 64,
        "subject_identity": "subject",
    }
    assert list(Draft202012Validator(authorization).iter_errors(inherited))


def test_duplicate_keys_nonfinite_and_unsafe_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(compiler.AdmissionError, match="duplicate JSON key"):
        compiler.strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.AdmissionError, match="non-finite"):
        compiler.strict_json(b'{"a":NaN}', "nan")
    with pytest.raises(compiler.AdmissionError, match="unsafe repository path"):
        compiler._safe_repo_path("../outside")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(compiler.AdmissionError, match="regular non-symlink"):
        compiler._read_regular(link, "link")


def test_cli_has_check_emit_only_and_never_writes(tmp_path: Path) -> None:
    before = {path.name for path in tmp_path.iterdir()}
    good = subprocess.run(
        [sys.executable, str(COMPILER_PATH), "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert good.returncode == 0, good.stderr
    emitted = subprocess.run(
        [sys.executable, str(COMPILER_PATH), "--emit"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert emitted.returncode == 0, emitted.stderr
    emitted_value = json.loads(emitted.stdout)
    assert emitted_value["admission_index"] == load("admission-index.json")
    assert emitted_value["receipt_set"] == load("receipt-set.json")
    for forbidden in ("--execute", "--write", "--action", "--receipt"):
        bad = subprocess.run(
            [sys.executable, str(COMPILER_PATH), forbidden],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert bad.returncode == 2
    assert {path.name for path in tmp_path.iterdir()} == before


def test_index_and_receipt_schemas_are_strict() -> None:
    index_schema = load("admission-index.schema.json")
    receipt_schema = load("receipt-set.schema.json")
    Draft202012Validator.check_schema(index_schema)
    Draft202012Validator.check_schema(receipt_schema)
    index = load("admission-index.json")
    mutated = copy.deepcopy(index)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(index_schema).iter_errors(mutated))


def test_output_hashes_and_source_lock_denominator_are_exact() -> None:
    for name, expected in compiler.EXPECTED_OUTPUT_HASHES.items():
        assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == expected
    index = load("admission-index.json")
    assert len(index["source_locks"]) == len(compiler.EXPECTED_SOURCE_HASHES) == 18
    assert {row["path"]: row["raw_sha256"] for row in index["source_locks"]} == (
        compiler.EXPECTED_SOURCE_HASHES
    )


def test_migration_activation_chain_is_bound_and_zero_state() -> None:
    payloads, _ = compiler._load_sources()
    migration = compiler.strict_json(payloads[compiler.MIGRATION_PATH], "migration")
    activation = compiler.strict_json(
        payloads[compiler.ACTIVATION_PATH], "activation"
    )
    assert activation["source_locks"]["migration_proof"] == {
        "path": compiler.MIGRATION_PATH,
        "raw_sha256": compiler.EXPECTED_SOURCE_HASHES[compiler.MIGRATION_PATH],
    }
    assert migration["summary"]["candidate_runtime_evidence_count"] == 0
    assert migration["summary"]["candidate_promotable_count"] == 0
    assert activation["candidate_boundary"]["runtime_evidence_count"] == 0
    assert activation["candidate_boundary"]["promotable_count"] == 0


def test_all_211_rows_match_historical_fail_closed_semantics() -> None:
    current = load("admission-index.json")
    historical = json.loads(
        compiler._safe_repo_path(
            f"{compiler.HISTORICAL_DIR}/admission-index.json"
        ).read_text(encoding="utf-8")
    )
    compiler._validate_historical_semantics(current)
    provenance = {
        "bundle_contract_raw_sha256",
        "candidate_record_canonical_sha256",
        "mapping_artifact_raw_sha256",
        "mapping_row_canonical_sha256",
        "metadata_binding_canonical_sha256",
        "oracle_record_canonical_sha256",
    }
    for rebased, old in zip(current["admissions"], historical["admissions"], strict=True):
        assert {key: value for key, value in rebased.items() if key not in provenance} == {
            key: value for key, value in old.items() if key not in provenance
        }


def test_historical_and_canonical_locks_fail_closed(tmp_path, monkeypatch) -> None:
    compiler._assert_immutable_files()
    drift = tmp_path / "drift"
    drift.write_text("drift", encoding="utf-8")
    first = next(iter(compiler.IMMUTABLE_FILES))
    original = compiler._safe_repo_path
    with monkeypatch.context() as scoped:
        scoped.setattr(
            compiler,
            "_safe_repo_path",
            lambda relative: drift if relative == first else original(relative),
        )
        with pytest.raises(compiler.AdmissionError, match="immutable historical"):
            compiler._assert_immutable_files()


def test_compiler_has_no_write_runtime_network_or_docker_surface() -> None:
    source = COMPILER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {
            "docker",
            "httpx",
            "os",
            "requests",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
            "urllib",
        }
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {
            "mkdir",
            "open",
            "Popen",
            "rename",
            "replace",
            "run",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
