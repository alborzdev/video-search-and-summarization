from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("activation_rebase_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def _load(relative: str) -> dict[str, Any]:
    return json.loads((compiler.REPO_ROOT / relative).read_text())


def _leaf_diffs(before: Any, after: Any, pointer: str = "") -> list[str]:
    if type(before) is not type(after):
        return [pointer]
    if isinstance(before, dict):
        if list(before) != list(after):
            return [pointer]
        result: list[str] = []
        for key in before:
            escaped = key.replace("~", "~0").replace("/", "~1")
            result.extend(_leaf_diffs(before[key], after[key], f"{pointer}/{escaped}"))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [pointer]
        result = []
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            result.extend(_leaf_diffs(left, right, f"{pointer}/{index}"))
        return result
    return [] if before == after else [pointer]


@pytest.fixture(scope="module")
def compiled() -> tuple[dict[str, Any], dict[str, Any], dict[Path, bytes]]:
    return compiler.compile_activation_rebase()


def test_checked_outputs_are_exact_and_fingerprint_locked(compiled) -> None:
    receipt, schema, outputs = compiled
    compiler.validate_activation(receipt, schema, outputs)
    expected = {
        compiler.DESCRIPTOR_OUTPUT: compiler.EXPECTED["descriptor"],
        compiler.SELECTOR_OUTPUT: compiler.EXPECTED["selector"],
        compiler.RECEIPT_OUTPUT: compiler.EXPECTED["receipt"],
        compiler.RECEIPT_SCHEMA_OUTPUT: compiler.EXPECTED["receipt_schema"],
    }
    for path, digest in expected.items():
        assert path.is_file() and not path.is_symlink()
        assert path.read_bytes() == outputs[path]
        assert compiler._sha(outputs[path]) == digest
    assert receipt["activation_payload_sha256"] == compiler.EXPECTED["receipt_payload"]


def test_cli_check_passes(capsys) -> None:
    assert compiler.main(["--check"]) == 0
    assert "canonical-writes=0" in capsys.readouterr().out


def test_all_source_and_output_locks_are_final() -> None:
    assert all(compiler.HEX64.fullmatch(digest) for _, digest in compiler.INPUTS.values())
    assert all(compiler.HEX64.fullmatch(digest) for digest in compiler.EXPECTED.values())
    source = (HERE / "compiler.py").read_text()
    assert "_".join(("TO", "BE", "PINNED")) not in source
    assert "PEND" + "ING" not in source
    assert "skip" not in source.lower()


def test_historical_and_canonical_bytes_are_unchanged_by_compile() -> None:
    before = {
        relative: (compiler.REPO_ROOT / relative).read_bytes()
        for relative in compiler.PRESERVED_FILES
    }
    compiler.compile_activation_rebase()
    after = {
        relative: (compiler.REPO_ROOT / relative).read_bytes()
        for relative in compiler.PRESERVED_FILES
    }
    assert after == before
    assert compiler.assert_preserved_bytes() == compiler.PRESERVED_FILES


def test_descriptor_projection_has_the_exact_reviewed_pointer_delta(compiled) -> None:
    receipt, _, outputs = compiled
    before = _load(compiler.CANONICAL_DESCRIPTOR_500)
    projected = json.loads(outputs[compiler.DESCRIPTOR_OUTPUT])
    expected = receipt["projection"]["descriptor"]["changed_json_pointers"]
    assert _leaf_diffs(before, projected) == expected
    assert projected["set_id"] == before["set_id"] == compiler.SET_ID_500
    assert projected["lifecycle"] == before["lifecycle"] == "live_ready"
    assert projected["target"] == before["target"]
    assert projected["mode"] == before["mode"]
    assert projected["expected_counts"] == before["expected_counts"] == {
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
    }


def test_selector_projection_changes_only_selected_500_row_path_and_hash(compiled) -> None:
    receipt, _, outputs = compiled
    before = _load(compiler.CANONICAL_SELECTOR)
    projected = json.loads(outputs[compiler.SELECTOR_OUTPUT])
    assert _leaf_diffs(before, projected) == receipt["projection"]["selector"][
        "changed_json_pointers"
    ]
    assert projected["selected_set"] == before["selected_set"] == compiler.SET_ID_500
    assert [row["set_id"] for row in projected["available_sets"]] == [
        compiler.SET_ID_289,
        compiler.SET_ID_500,
    ]
    assert projected["available_sets"][0] == before["available_sets"][0]


def test_immutable_descriptor_path_is_bound_to_migration_proof_hash(compiled) -> None:
    receipt, _, outputs = compiled
    migration_digest = compiler.INPUTS["migration_proof"][1]
    expected_path = f"{compiler.IMMUTABLE_DESCRIPTOR_PREFIX}{migration_digest}.json"
    assert receipt["projection"]["descriptor"]["immutable_target_path"] == expected_path
    selector = json.loads(outputs[compiler.SELECTOR_OUTPUT])
    assert selector["available_sets"][1]["descriptor_path"] == expected_path
    assert selector["available_sets"][1]["descriptor_raw_sha256"] == compiler.EXPECTED[
        "descriptor"
    ]


def test_authoritative_isolated_resolver_and_bundle_report_is_exact(compiled) -> None:
    receipt, _, _ = compiled
    assert receipt["authoritative_isolated_validation"] == {
        "set_id": compiler.SET_ID_500,
        "descriptor_raw_sha256": compiler.EXPECTED["descriptor"],
        "oracle_schema_version": 2,
        "oracle_validator": "capability_oracles_v2",
        "counts": {"capabilities": 500, "oracles": 500, "feature_families": 55},
        "official_validator_counts": {
            "sources": 126,
            "capabilities": 500,
            "feature_families": 55,
            "discrepancies": 47,
        },
        "oracle_validator_counts": {
            "capabilities": 500,
            "oracles": 500,
            "preserved_v1": 289,
            "candidates": 211,
            "candidate_evidence": 0,
            "candidate_executor_ready": 0,
            "candidate_protocol_bindings": 23,
            "candidate_workload_bindings": 60,
        },
    }


def test_candidate_boundary_is_nonadvancing(compiled) -> None:
    receipt, _, _ = compiled
    assert receipt["candidate_boundary"] == {
        "candidate_count": 211,
        "runtime_evidence_count": 0,
        "executor_ready_count": 0,
        "promotable_count": 0,
    }
    assert receipt["policy"]["candidate_runtime_promotion"] is False
    assert receipt["policy"]["warehouse_sample_bundle"] == "excluded"


def test_rollback_is_exact_hash_guarded_and_preserves_old_descriptor(compiled) -> None:
    receipt, _, outputs = compiled
    rollback = receipt["rollback"]
    assert rollback == {
        "strategy": "restore_selector_and_remove_exact_rebase_descriptor",
        "live_apply_authorized": False,
        "restore_selector_path": compiler.CANONICAL_SELECTOR,
        "restore_selector_raw_sha256": compiler.PRESERVED_FILES[
            compiler.CANONICAL_SELECTOR
        ],
        "preserve_predecessor_descriptor_path": compiler.CANONICAL_DESCRIPTOR_500,
        "preserve_predecessor_descriptor_raw_sha256": compiler.PRESERVED_FILES[
            compiler.CANONICAL_DESCRIPTOR_500
        ],
        "remove_only_descriptor_path": receipt["projection"]["descriptor"][
            "immutable_target_path"
        ],
        "remove_only_descriptor_raw_sha256": compiler._sha(
            outputs[compiler.DESCRIPTOR_OUTPUT]
        ),
        "requires_projected_selector_raw_sha256": compiler._sha(
            outputs[compiler.SELECTOR_OUTPUT]
        ),
        "partial_or_unknown_state": "rejected",
        "atomic_selector_and_descriptor_install_required": True,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("set_id", "replacement-set"),
        ("lifecycle", "validation_only"),
        ("expected_counts", {"capabilities": 499, "oracles": 500, "feature_families": 55}),
    ],
)
def test_descriptor_identity_lifecycle_or_count_drift_is_rejected(field, value) -> None:
    descriptor = _load(compiler.CANONICAL_DESCRIPTOR_500)
    descriptor[field] = value
    _, _, locks = compiler._load_inputs()
    with pytest.raises(compiler.RebaseActivationError, match="identity differs"):
        compiler.project_descriptor(descriptor, locks)


def test_descriptor_member_order_drift_is_rejected() -> None:
    descriptor = _load(compiler.CANONICAL_DESCRIPTOR_500)
    descriptor["documents"] = dict(reversed(list(descriptor["documents"].items())))
    _, _, locks = compiler._load_inputs()
    with pytest.raises(compiler.RebaseActivationError, match="identity differs"):
        compiler.project_descriptor(descriptor, locks)


@pytest.mark.parametrize("mutation", ["selected", "order", "duplicate", "289-row"])
def test_selector_identity_order_duplicate_and_289_drift_are_rejected(mutation) -> None:
    selector = _load(compiler.CANONICAL_SELECTOR)
    if mutation == "selected":
        selector["selected_set"] = compiler.SET_ID_289
    elif mutation == "order":
        selector["available_sets"].reverse()
    elif mutation == "duplicate":
        selector["available_sets"][1]["set_id"] = compiler.SET_ID_289
    else:
        selector["available_sets"][0]["descriptor_raw_sha256"] = "0" * 64
    with pytest.raises(compiler.RebaseActivationError):
        compiler.project_selector(
            selector,
            compiler._immutable_descriptor_path(compiler.INPUTS["migration_proof"][1]),
            "a" * 64,
        )


def test_migration_artifact_cross_binding_drift_is_rejected() -> None:
    documents, _, locks = compiler._load_inputs()
    documents = copy.deepcopy(documents)
    documents["migration_proof"]["artifacts"]["post-state-official-capabilities.json"][
        "raw_sha256"
    ] = "0" * 64
    with pytest.raises(
        compiler.RebaseActivationError, match="schema error|artifact binding differs"
    ):
        compiler._validate_migration(documents, locks)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("policy", "candidate_runtime_promotion", True),
        ("policy", "modifies_selector_or_descriptors", True),
        ("summary", "candidate_runtime_evidence_count", 1),
        ("summary", "candidate_promotable_count", 1),
        ("rollback", "selector_or_descriptor_change_included", True),
    ],
)
def test_migration_advancement_or_selector_ownership_drift_is_rejected(
    section, field, value
) -> None:
    documents, _, locks = compiler._load_inputs()
    documents = copy.deepcopy(documents)
    documents["migration_proof"][section][field] = value
    with pytest.raises(compiler.RebaseActivationError, match="schema error|boundary differs"):
        compiler._validate_migration(documents, locks)


def test_mutated_source_hash_lock_is_rejected(monkeypatch) -> None:
    inputs = copy.deepcopy(compiler.INPUTS)
    path, _ = inputs["migration_proof"]
    inputs["migration_proof"] = (path, "0" * 64)
    monkeypatch.setattr(compiler, "INPUTS", inputs)
    with pytest.raises(compiler.RebaseActivationError, match="input hash drift"):
        compiler._load_inputs()


def test_receipt_or_artifact_tamper_is_rejected(compiled) -> None:
    receipt, schema, outputs = compiled
    mutated_receipt = copy.deepcopy(receipt)
    mutated_receipt["rollback"]["live_apply_authorized"] = True
    with pytest.raises(compiler.RebaseActivationError, match="schema error"):
        compiler.validate_activation(mutated_receipt, schema, outputs)
    mutated_outputs = dict(outputs)
    mutated_outputs[compiler.SELECTOR_OUTPUT] += b"\n"
    with pytest.raises(compiler.RebaseActivationError, match="artifact binding differs"):
        compiler.validate_activation(receipt, schema, mutated_outputs)


def test_compiler_is_check_only_and_has_no_package_or_canonical_writer() -> None:
    source = (HERE / "compiler.py").read_text()
    assert '"--write"' not in source
    assert "_atomic_write" not in source
    assert "os.replace" not in source
    assert source.count("write_bytes(") == 1
    assert "target.write_bytes(payload)" in source
    assert "TemporaryDirectory" in source
    assert "DESCRIPTOR_OUTPUT.write" not in source
    assert "SELECTOR_OUTPUT.write" not in source
    assert "CANONICAL_SELECTOR).write" not in source
    assert "CANONICAL_DESCRIPTOR_500).write" not in source
