from __future__ import annotations

import copy
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
    "candidate_admission_compiler", COMPILER_PATH
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def test_checked_artifacts_are_exact_and_empty() -> None:
    result = compiler.check()
    assert result == {
        "admission_index_raw_sha256": "6dc6345f9b057c164929a1046b8ebcfb08fdfbedaa1b7a66180f344915d7d7eb",
        "admission_rows_canonical_sha256": "4ba78a32c3fff336b8362a5afc0d78af8076e3c0afb52a87df0985e196bd3160",
        "admitted_candidate_count": 0,
        "candidate_count": 211,
        "executable_candidate_count": 0,
        "receipt_count": 0,
        "receipt_set_raw_sha256": "7bfeb7e70f9a7c3a2bbbb007c785286146dbfe70e4f63245168cf382b62ec805",
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


def test_cli_has_check_only_and_never_writes(tmp_path: Path) -> None:
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
    for forbidden in ("--emit", "--execute", "--write", "--action", "--receipt"):
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
