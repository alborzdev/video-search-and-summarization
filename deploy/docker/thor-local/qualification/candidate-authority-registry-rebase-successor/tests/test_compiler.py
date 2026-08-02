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
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_authority_rebase", COMPILER_PATH
)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def payload(kind: str = "authorization") -> dict:
    digest = "a" * 64
    specific = (
        {
            "kind": "authorization",
            "authorized_subject_identity": "operator:example",
            "completion_authorization_receipt_id": None,
            "completion_evidence_binding_sha256": None,
        }
        if kind == "authorization"
        else {
            "kind": "completion",
            "authorization_receipt_id": "authorization-1",
            "completion_evidence_binding_sha256": digest,
            "outcome": "successful",
        }
    )
    return {
        "schema_version": 1,
        "receipt_type": (
            "candidate_action_authorization"
            if kind == "authorization"
            else "candidate_action_completion"
        ),
        "identifiers": {
            "receipt_id": f"{kind}-1",
            "authorization_event_id": "event-1",
            "run_id": "run-1",
            "nonce_id": "nonce-1",
            "replay_domain_sha256": digest,
        },
        "authority_registry_binding": {
            "authority_registry_id": "future-registry",
            "registry_epoch": 1,
            "authority_registry_raw_sha256": digest,
            "previous_registry_raw_sha256": digest,
            "root_set_canonical_sha256": digest,
        },
        "authority_claim": {
            "scope_id": "candidate-action",
            "required_role": "operator",
            "eligible_key_set_canonical_sha256": digest,
            "threshold_policy_canonical_sha256": digest,
        },
        "candidate_binding": {
            "candidate_id": "manifest-entry.example.00-example",
            "candidate_record_canonical_sha256": digest,
            "oracle_id": "oracle.manifest-entry.example.00-example",
            "oracle_record_canonical_sha256": digest,
            "metadata_set_id": "metadata500",
            "metadata_oracle_raw_sha256": digest,
            "metadata_binding_canonical_sha256": digest,
            "mapping_artifact_raw_sha256": digest,
            "mapping_row_canonical_sha256": digest,
            "binding_registry_id": "future-bindings",
            "binding_registry_raw_sha256": digest,
            "binding_registry_row_canonical_sha256": digest,
            "admission_index_raw_sha256": digest,
        },
        "bundle_binding": {
            "bundle_contract_raw_sha256": digest,
            "leaf_bundle_id": "profile-lifecycle",
            "bundle_row_canonical_sha256": digest,
            "dependency_dag_canonical_sha256": digest,
            "complete_dependency_closure_canonical_sha256": digest,
            "dependency_edge_decisions_canonical_sha256": digest,
        },
        "action_binding": {
            "action_contract_sha256": digest,
            "executor_binding_sha256": digest,
            "service_role_binding_sha256": digest,
            "profile_binding_sha256": digest,
            "service_role_profile_binding_sha256": digest,
            "compose_binding_sha256": digest,
            "cleanup_executor_binding_sha256": digest,
            "cleanup_targets_canonical_sha256": digest,
            "cleanup_rollback_contract_sha256": digest,
            "postcondition_collectors_canonical_sha256": digest,
            "input_binding_sha256": digest,
            "model_artifact_binding_sha256": digest,
            "fixture_binding_sha256": digest,
            "evidence_destination_sha256": digest,
            "evidence_records_contract_sha256": digest,
        },
        "execution_boundary": "local",
        "validity": {
            "issued_at": "2030-01-01T00:00:00Z",
            "not_before": "2030-01-01T00:00:00Z",
            "expires_at": "2030-01-01T00:05:00Z",
            "max_ttl_policy_canonical_sha256": digest,
        },
        "one_time_status": "issued_unspent",
        "previous_receipt_digest_sha256": digest,
        "type_specific": specific,
        "warehouse_sample_bundle": "excluded",
    }


def payload_validator() -> Draft202012Validator:
    schema = load("signed-receipt-envelope.schema.json")
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/receipt_payload",
        }
    )


def test_checked_artifacts_have_exact_hashes() -> None:
    assert compiler.check() == {
        "authority_registry_raw_sha256": "954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4",
        "authorization_envelope_count": 0,
        "completion_receipt_envelope_count": 0,
        "signed_receipt_set_raw_sha256": "84ce0c682a49dc930f33fa2bb698e9a7f66a14902cf123e0cba060a8c0f8ed24",
        "status": "ok",
        "trusted_root_count": 0,
    }


def test_all_authority_policy_and_ledger_collections_are_exactly_empty() -> None:
    registry = load("authority-registry.json")
    assert all(registry[name] == [] for name in compiler.EMPTY_COLLECTIONS)
    assert registry["root_pinning"] == {
        "previous_registry_raw_sha256": None,
        "registry_epoch": 0,
        "root_set_canonical_sha256": None,
        "trusted_root_count": 0,
    }
    assert all(value == 0 for value in registry["summary"].values())


def test_receipts_are_exactly_empty_and_never_accepted_or_consumed() -> None:
    receipts = load("signed-receipt-set.json")
    compiler.validate_empty_receipt_set(receipts)
    assert receipts["authorization_envelopes"] == []
    assert receipts["completion_receipt_envelopes"] == []
    assert receipts["accepted_receipt_ids"] == []
    assert receipts["consumed_receipt_ids"] == []


def test_source_locks_cover_exact_published_registries() -> None:
    registry = load("authority-registry.json")
    locks = {row["path"]: row["raw_sha256"] for row in registry["source_locks"]}
    assert locks == compiler.EXPECTED_SOURCE_HASHES
    for relative, digest in locks.items():
        assert (
            compiler.sha256(
                compiler._read_regular(compiler._repo_path(relative), relative)
            )
            == digest
        )


def test_all_schemas_are_strict_and_valid() -> None:
    for name in (
        "authority-registry.schema.json",
        "signed-receipt-envelope.schema.json",
        "signed-receipt-set.schema.json",
    ):
        schema = load(name)
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("kind", ["authorization", "completion"])
def test_future_payload_contract_distinguishes_receipt_types(kind: str) -> None:
    assert list(payload_validator().iter_errors(payload(kind))) == []


def test_cross_type_payload_substitution_is_rejected() -> None:
    value = payload("authorization")
    value["type_specific"] = payload("completion")["type_specific"]
    assert list(payload_validator().iter_errors(value))


def test_payload_binds_every_authority_candidate_bundle_action_and_replay_domain() -> (
    None
):
    value = payload()
    for field in (
        "authority_registry_binding",
        "authority_claim",
        "candidate_binding",
        "bundle_binding",
        "action_binding",
        "identifiers",
    ):
        broken = copy.deepcopy(value)
        broken.pop(field)
        assert list(payload_validator().iter_errors(broken))


def test_envelope_has_fixed_payload_type_signature_shape_and_no_algorithm_field() -> (
    None
):
    schema = load("signed-receipt-envelope.schema.json")
    validator = Draft202012Validator(schema)
    envelope = {
        "payloadType": "application/vnd.nvidia.vss.candidate-receipt.v1+json",
        "payload": "e30=",
        "signatures": [{"keyid": "future-key", "sig": "A" * 86 + "=="}],
    }
    assert list(validator.iter_errors(envelope)) == []
    for mutation in (
        {**envelope, "algorithm": "Ed25519"},
        {**envelope, "payloadType": "application/other"},
        {**envelope, "payload": "not-base64***"},
        {**envelope, "signatures": [{"keyid": "future-key", "sig": "AA=="}]},
    ):
        assert list(validator.iter_errors(mutation))


def test_nonempty_registry_input_fails_before_it_can_be_trusted() -> None:
    registry = load("authority-registry.json")
    registry["active_keys"] = [{"self_declared": True}]
    with pytest.raises(compiler.AuthorityError, match="non-empty active_keys"):
        compiler.validate_empty_registry(registry)


def test_nonempty_receipt_inputs_fail_before_decoding_or_verification() -> None:
    receipts = load("signed-receipt-set.json")
    receipts["authorization_envelopes"] = [{"self_declared": True}]
    with pytest.raises(compiler.AuthorityError, match="authorization_envelopes"):
        compiler.validate_empty_receipt_set(receipts)


def test_integrity_hashes_are_not_authority_and_every_verifier_is_absent() -> None:
    registry = load("authority-registry.json")
    assert registry["limitations"] == {
        "candidate_authority_qualification_dependency_available": False,
        "canonical_jcs_implementation_available": False,
        "central_spent_ledger_available": False,
        "cryptographic_verification_dependency_available": False,
        "epoch_rollback_protection_available": False,
        "global_durable_atomic_spent_ledger_available": False,
        "model_signing_dependency_available": False,
        "revocation_mechanism_available": False,
        "root_key_available": False,
        "sha256_is_integrity_not_authority": True,
        "signature_verifier_available": False,
        "trusted_time_available": False,
    }


def test_warehouse_cloud_runtime_and_writes_remain_excluded() -> None:
    registry = load("authority-registry.json")
    policy = registry["policy"]
    assert policy["warehouse_sample_bundle"] == "excluded"
    assert policy["required_cloud_inference"] is False
    for capability in ("accept", "consume", "execute", "sign", "write"):
        assert policy[f"compiler_can_{capability}"] is False
    assert policy["compiler_can_verify_signatures"] is False


def test_strict_json_rejects_duplicates_nonfinite_and_nonobjects() -> None:
    with pytest.raises(compiler.AuthorityError, match="duplicate JSON key"):
        compiler.strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.AuthorityError, match="non-finite"):
        compiler.strict_json(b'{"a":NaN}', "nan")
    with pytest.raises(compiler.AuthorityError, match="root must be an object"):
        compiler.strict_json(b"[]", "array")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape", "a/../b"])
def test_unsafe_source_paths_are_rejected(relative: str) -> None:
    with pytest.raises(compiler.AuthorityError, match="unsafe repository path"):
        compiler._repo_path(relative)


def test_cli_is_check_only() -> None:
    good = subprocess.run(
        [sys.executable, str(COMPILER_PATH), "--check"],
        cwd=PACKAGE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0
    assert '"status": "ok"' in good.stdout
    for arguments in ([], ["--write"], ["--sign"], ["--verify"], ["--execute"]):
        bad = subprocess.run(
            [sys.executable, str(COMPILER_PATH), *arguments],
            cwd=PACKAGE,
            text=True,
            capture_output=True,
            check=False,
        )
        assert bad.returncode == 2


def test_output_hashes_and_exact_source_denominator() -> None:
    for name, expected in compiler.EXPECTED_OUTPUT_HASHES.items():
        assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == expected
    registry = load("authority-registry.json")
    assert len(registry["source_locks"]) == len(compiler.EXPECTED_SOURCE_HASHES) == 12


def test_execution_binding_and_admission_rebase_provenance_is_exact() -> None:
    locks = {
        row["path"]: row["raw_sha256"]
        for row in load("authority-registry.json")["source_locks"]
    }
    assert locks[compiler.BINDING_REGISTRY_PATH] == (
        "af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5"
    )
    assert locks[compiler.BINDING_LOCATORS_PATH] == (
        "d1882d4811bd661fd011f8cf91894951cc8af806c56968218ef0100b500b69a0"
    )
    assert locks[compiler.ADMISSION_INDEX_PATH] == (
        "74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff"
    )
    assert locks[compiler.ADMISSION_RECEIPTS_PATH] == (
        "e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f"
    )


def test_historical_semantics_and_canonical_locks_fail_closed(
    tmp_path, monkeypatch
) -> None:
    registry = load("authority-registry.json")
    compiler._validate_historical_registry_semantics(registry)
    compiler._assert_immutable_files()
    drift = tmp_path / "drift"
    drift.write_text("drift", encoding="utf-8")
    first = next(iter(compiler.IMMUTABLE_FILES))
    original = compiler._repo_path
    with monkeypatch.context() as scoped:
        scoped.setattr(
            compiler,
            "_repo_path",
            lambda relative: drift if relative == first else original(relative),
        )
        with pytest.raises(compiler.AuthorityError, match="immutable historical"):
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
            "rename",
            "replace",
            "run",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
