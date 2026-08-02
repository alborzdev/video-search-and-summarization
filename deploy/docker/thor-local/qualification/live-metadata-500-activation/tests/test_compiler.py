from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "live_metadata_500_activation_compiler", HERE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_control_overlay(
    root: Path, selector_payload: bytes, descriptor_payload: bytes
) -> None:
    for relative, payload in (
        (compiler.CANONICAL_SELECTOR_PATH, selector_payload),
        (compiler.CANONICAL_DESCRIPTOR_PATH, descriptor_payload),
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


@pytest.fixture(scope="module")
def compiled() -> tuple[dict[str, Any], dict[str, Any], dict[Path, bytes], str]:
    return compiler.compile_activation()


def test_checked_outputs_are_deterministic_and_hash_locked(compiled) -> None:
    receipt, schema, outputs, observed_state = compiled
    assert observed_state in {"pre_activation", "applied"}
    compiler.validate_activation(receipt, schema, outputs)
    expected = {
        compiler.DESCRIPTOR_OUTPUT: compiler.EXPECTED["descriptor"],
        compiler.SELECTOR_OUTPUT: compiler.EXPECTED["selector"],
        compiler.RECEIPT_OUTPUT: compiler.EXPECTED["receipt"],
        compiler.RECEIPT_SCHEMA_OUTPUT: compiler.EXPECTED["receipt_schema"],
    }
    for path, digest in expected.items():
        assert path.read_bytes() == outputs[path]
        assert _sha(outputs[path]) == digest
    assert receipt["activation_payload_sha256"] == compiler.EXPECTED["receipt_payload"]


def test_pre_activation_snapshots_are_exact_regular_byte_copies() -> None:
    expected = {
        "pre_activation_selector": (
            compiler.CANONICAL_SELECTOR_PATH,
            compiler.PRE_SELECTOR_SHA256,
        ),
        "pre_activation_descriptor_500": (
            compiler.CANONICAL_DESCRIPTOR_PATH,
            compiler.PRE_DESCRIPTOR_SHA256,
        ),
    }
    for input_id, (canonical_relative, digest) in expected.items():
        snapshot = compiler.REPO_ROOT / compiler.INPUTS[input_id][0]
        assert snapshot.is_file() and not snapshot.is_symlink()
        assert _sha(snapshot.read_bytes()) == digest
        assert canonical_relative not in compiler.INPUTS[input_id][0]


def test_pre_and_applied_states_generate_identical_artifacts(
    compiled, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, schema, outputs, observed = compiled
    assert observed in {"pre_activation", "applied"}
    inspect = compiler._inspect_live_state
    monkeypatch.setattr(
        compiler,
        "_inspect_live_state",
        lambda selector, descriptor: inspect(selector, descriptor, repo_root=tmp_path),
    )

    snapshot_selector = (
        compiler.REPO_ROOT / compiler.INPUTS["pre_activation_selector"][0]
    ).read_bytes()
    snapshot_descriptor = (
        compiler.REPO_ROOT / compiler.INPUTS["pre_activation_descriptor_500"][0]
    ).read_bytes()
    _write_control_overlay(tmp_path, snapshot_selector, snapshot_descriptor)
    pre_receipt, pre_schema, pre_outputs, pre_observed = compiler.compile_activation()

    _write_control_overlay(
        tmp_path,
        outputs[compiler.SELECTOR_OUTPUT],
        outputs[compiler.DESCRIPTOR_OUTPUT],
    )
    applied_receipt, applied_schema, applied_outputs, applied_observed = (
        compiler.compile_activation()
    )
    assert pre_observed == "pre_activation"
    assert applied_observed == "applied"
    assert pre_receipt == receipt
    assert pre_schema == schema
    assert pre_outputs == outputs
    assert applied_receipt == receipt
    assert applied_schema == schema
    assert applied_outputs == outputs


@pytest.mark.parametrize("selector_applied", [False, True])
def test_mixed_control_overlay_is_rejected(
    compiled, tmp_path: Path, selector_applied: bool
) -> None:
    _, _, outputs, _ = compiled
    snapshot_selector = (
        compiler.REPO_ROOT / compiler.INPUTS["pre_activation_selector"][0]
    ).read_bytes()
    snapshot_descriptor = (
        compiler.REPO_ROOT / compiler.INPUTS["pre_activation_descriptor_500"][0]
    ).read_bytes()
    selector_payload = (
        outputs[compiler.SELECTOR_OUTPUT] if selector_applied else snapshot_selector
    )
    descriptor_payload = (
        snapshot_descriptor if selector_applied else outputs[compiler.DESCRIPTOR_OUTPUT]
    )
    _write_control_overlay(tmp_path, selector_payload, descriptor_payload)
    with pytest.raises(compiler.ActivationError, match="mixed/partial"):
        compiler._inspect_live_state(
            outputs[compiler.SELECTOR_OUTPUT],
            outputs[compiler.DESCRIPTOR_OUTPUT],
            repo_root=tmp_path,
        )


def test_unknown_control_overlay_is_rejected(compiled, tmp_path: Path) -> None:
    _, _, outputs, _ = compiled
    _write_control_overlay(tmp_path, b"{}\n", b"{}\n")
    with pytest.raises(compiler.ActivationError, match="unknown"):
        compiler._inspect_live_state(
            outputs[compiler.SELECTOR_OUTPUT],
            outputs[compiler.DESCRIPTOR_OUTPUT],
            repo_root=tmp_path,
        )


def test_descriptor_projection_changes_only_lifecycle(compiled) -> None:
    _, _, outputs, _ = compiled
    projected = json.loads(outputs[compiler.DESCRIPTOR_OUTPUT])
    staged = json.loads(
        (
            compiler.REPO_ROOT / compiler.INPUTS["pre_activation_descriptor_500"][0]
        ).read_text()
    )
    assert staged["lifecycle"] == "validation_only"
    assert projected["lifecycle"] == "live_ready"
    projected["lifecycle"] = "validation_only"
    assert projected == staged
    assert _sha(outputs[compiler.DESCRIPTOR_OUTPUT]) == (
        "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9"
    )


def test_selector_projection_changes_only_default_and_descriptor_hash(compiled) -> None:
    _, _, outputs, _ = compiled
    projected = json.loads(outputs[compiler.SELECTOR_OUTPUT])
    current = json.loads(
        (compiler.REPO_ROOT / compiler.INPUTS["pre_activation_selector"][0]).read_text()
    )
    assert projected["selected_set"] == compiler.SET_ID_500
    assert (
        projected["available_sets"][1]["descriptor_path"]
        == (current["available_sets"][1]["descriptor_path"])
    )
    assert (
        projected["available_sets"][1]["descriptor_raw_sha256"]
        == (compiler.EXPECTED["descriptor"])
    )
    projected["selected_set"] = compiler.SET_ID_289
    projected["available_sets"][1]["descriptor_raw_sha256"] = current["available_sets"][
        1
    ]["descriptor_raw_sha256"]
    assert projected == current
    assert _sha(outputs[compiler.SELECTOR_OUTPUT]) == (
        "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec"
    )


def test_authoritative_isolated_default_report_is_exact(compiled) -> None:
    receipt, _, _, _ = compiled
    report = receipt["authoritative_isolated_validation"]
    assert report["set_id"] == compiler.SET_ID_500
    assert report["descriptor_raw_sha256"] == compiler.EXPECTED["descriptor"]
    assert report["oracle_schema_version"] == 2
    assert report["oracle_validator"] == "capability_oracles_v2"
    assert report["counts"] == {
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
    }
    assert report["official_validator_counts"] == {
        "sources": 126,
        "capabilities": 500,
        "feature_families": 55,
        "discrepancies": 47,
    }
    assert report["oracle_validator_counts"]["candidate_evidence"] == 0
    assert report["oracle_validator_counts"]["candidate_executor_ready"] == 0


def test_candidate_and_fixed_legacy_boundaries_are_nonadvancing(compiled) -> None:
    receipt, _, _, _ = compiled
    assert receipt["candidate_boundary"] == {
        "candidate_count": 211,
        "runtime_evidence_count": 0,
        "executor_ready_count": 0,
        "promotable_count": 0,
    }
    assert receipt["fixed_legacy_files"]["changed_paths"] == []
    assert set(receipt["fixed_legacy_files"]["unchanged_raw_sha256_by_path"]) == {
        "deploy/docker/thor-local/parity/manifest.json",
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    }
    assert receipt["policy"]["modifies_fixed_legacy_files"] is False
    assert receipt["policy"]["candidate_runtime_promotion"] is False


def test_source_locks_cover_required_authorities_and_tests(compiled) -> None:
    receipt, _, _, _ = compiled
    assert set(receipt["source_locks"]) == set(compiler.INPUTS)
    required = {
        "pre_activation_selector",
        "descriptor_289",
        "pre_activation_descriptor_500",
        "migration_proof",
        "manifest_500",
        "ledger_500",
        "acceptance_500",
        "oracles_500",
        "oracle_schema_500",
        "resolver",
        "resolver_tests",
        "v2_validator",
        "v2_validator_tests",
        "bundle_verifier",
        "bundle_verifier_tests",
    }
    assert required <= set(receipt["source_locks"])
    for input_id, lock in receipt["source_locks"].items():
        path = compiler.REPO_ROOT / lock["path"]
        assert path.is_file() and not path.is_symlink()
        assert _sha(path.read_bytes()) == compiler.INPUTS[input_id][1]


def test_transition_journal_retains_canonical_pair_and_exact_states(compiled) -> None:
    receipt, _, outputs, _ = compiled
    journal = receipt["transition_journal"]
    assert journal["canonical_selector_path"] == compiler.CANONICAL_SELECTOR_PATH
    assert journal["canonical_descriptor_path"] == (compiler.CANONICAL_DESCRIPTOR_PATH)
    assert journal["accepted_repository_states"] == {
        "pre_activation": {
            "selector_raw_sha256": compiler.PRE_SELECTOR_SHA256,
            "descriptor_raw_sha256": compiler.PRE_DESCRIPTOR_SHA256,
        },
        "applied": {
            "selector_raw_sha256": _sha(outputs[compiler.SELECTOR_OUTPUT]),
            "descriptor_raw_sha256": _sha(outputs[compiler.DESCRIPTOR_OUTPUT]),
        },
    }
    assert journal["partial_or_unknown_state"] == "rejected"
    assert journal["atomic_pair_transition_required"] is True
    assert journal["observed_state_in_generated_artifacts"] is False


def test_receipt_schema_and_artifact_bindings_are_exact(compiled) -> None:
    receipt, schema, outputs, _ = compiled
    assert list(Draft202012Validator(schema).iter_errors(receipt)) == []
    mutated = copy.deepcopy(receipt)
    mutated["policy"]["modifies_current_selector"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))
    for path in (compiler.DESCRIPTOR_OUTPUT, compiler.SELECTOR_OUTPUT):
        assert receipt["artifacts"][path.name]["raw_sha256"] == _sha(outputs[path])


def test_rollback_restores_exact_current_selector_and_descriptor(compiled) -> None:
    receipt, _, _, _ = compiled
    rollback = receipt["rollback"]
    assert rollback == {
        "strategy": "restore_selector_and_validation_only_descriptor",
        "live_apply_authorized": False,
        "restore_selected_set": compiler.SET_ID_289,
        "restore_selector_raw_sha256": compiler.PRE_SELECTOR_SHA256,
        "restore_descriptor_raw_sha256": compiler.PRE_DESCRIPTOR_SHA256,
        "partial_activation_forbidden": True,
    }
    assert receipt["execution_boundary"]["id"] == (
        "canonical-transition-outside-package"
    )


def test_descriptor_projection_rejects_extra_mutation() -> None:
    staged = json.loads(
        (
            compiler.REPO_ROOT / compiler.INPUTS["pre_activation_descriptor_500"][0]
        ).read_text()
    )
    staged["lifecycle"] = "live_ready"
    with pytest.raises(compiler.ActivationError, match="lifecycle"):
        compiler._project_descriptor(staged)


def test_selector_projection_rejects_wrong_current_default() -> None:
    selector = json.loads(
        (compiler.REPO_ROOT / compiler.INPUTS["pre_activation_selector"][0]).read_text()
    )
    selector["selected_set"] = compiler.SET_ID_500
    with pytest.raises(compiler.ActivationError, match="289"):
        compiler._project_selector(selector, "0" * 64)


def test_validation_only_descriptor_cannot_resolve_as_default(compiled) -> None:
    _, _, outputs, _ = compiled
    descriptor = json.loads(outputs[compiler.DESCRIPTOR_OUTPUT])
    descriptor["lifecycle"] = "validation_only"
    descriptor_payload = compiler._encoded(descriptor)
    selector = json.loads(outputs[compiler.SELECTOR_OUTPUT])
    selector["available_sets"][1]["descriptor_raw_sha256"] = _sha(descriptor_payload)
    _, payloads, _ = compiler._load_inputs()
    with pytest.raises(
        compiler.metadata_resolver.MetadataSetError, match="not live-ready"
    ):
        compiler._isolated_verify(
            descriptor,
            descriptor_payload,
            compiler._encoded(selector),
            payloads,
        )


def test_wrong_projected_descriptor_hash_fails_isolated_resolution(compiled) -> None:
    _, _, outputs, _ = compiled
    descriptor = json.loads(outputs[compiler.DESCRIPTOR_OUTPUT])
    selector = json.loads(outputs[compiler.SELECTOR_OUTPUT])
    selector["available_sets"][1]["descriptor_raw_sha256"] = "0" * 64
    _, payloads, _ = compiler._load_inputs()
    with pytest.raises(
        compiler.metadata_resolver.MetadataSetError, match="raw hash differs"
    ):
        compiler._isolated_verify(
            descriptor,
            outputs[compiler.DESCRIPTOR_OUTPUT],
            compiler._encoded(selector),
            payloads,
        )


@pytest.mark.parametrize(
    "payload",
    [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'],
)
def test_strict_json_rejects_duplicate_and_nonfinite(payload: bytes) -> None:
    with pytest.raises(compiler.ActivationError):
        compiler._strict_json(payload, "test")


@pytest.mark.parametrize("path", ["../x", "/tmp/x", "deploy/../x"])
def test_repo_path_rejects_unsafe_names(path: str) -> None:
    with pytest.raises(compiler.ActivationError, match="unsafe"):
        compiler._repo_file(path)


def test_atomic_writer_is_package_bounded_and_rejects_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compiler, "PACKAGE", tmp_path)
    allowed = tmp_path / compiler.DESCRIPTOR_OUTPUT.name
    compiler._atomic_write(allowed, b"{}\n")
    assert allowed.read_bytes() == b"{}\n"
    with pytest.raises(compiler.ActivationError, match="unsafe"):
        compiler._atomic_write(tmp_path / "other.json", b"{}\n")
    allowed.unlink()
    allowed.symlink_to(tmp_path / "target")
    with pytest.raises(compiler.ActivationError, match="unsafe"):
        compiler._atomic_write(allowed, b"{}\n")


def test_compiler_has_no_runtime_network_docker_or_subprocess_surface() -> None:
    tree = ast.parse((HERE / "compiler.py").read_text())
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


def test_policy_excludes_runtime_warehouse_and_live_apply(compiled) -> None:
    receipt, _, _, _ = compiled
    policy = receipt["policy"]
    assert policy["runtime_execution"] == "forbidden"
    assert policy["network_access"] is False
    assert policy["docker_access"] is False
    assert policy["host_inspection"] is False
    assert policy["warehouse_sample_bundle"] == "excluded"
    assert policy["modifies_current_selector"] is False
    assert policy["modifies_current_descriptors"] is False
