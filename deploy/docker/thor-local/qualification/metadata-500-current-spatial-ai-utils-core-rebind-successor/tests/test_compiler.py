from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "spatial_ai_core_rebind_projection", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


@pytest.fixture(scope="module")
def derivation() -> tuple[dict, dict, dict, dict, dict]:
    return compiler.derive()


def test_checked_outputs_are_exact_derivations(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    _, oracle_output, _, ledger_output, _ = derivation
    checked_oracle = compiler.ORACLE_OUTPUT.read_bytes()
    checked_ledger = compiler.LEDGER_OUTPUT.read_bytes()
    assert checked_oracle == compiler.encoded(oracle_output)
    assert checked_ledger == compiler.encoded(ledger_output)
    assert (
        hashlib.sha256(checked_oracle).hexdigest()
        == compiler.EXPECTED_ORACLE_OUTPUT_SHA256
    )
    assert (
        hashlib.sha256(checked_ledger).hexdigest()
        == compiler.EXPECTED_LEDGER_OUTPUT_SHA256
    )


def test_rebased_current_prefix_and_selected_suffix_are_exact(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, _, ledger_baseline, _, _ = derivation
    current_oracles = compiler.load_locked(compiler.CURRENT_ORACLES)
    selected_oracles = compiler.load_locked(compiler.SELECTED_ORACLES)
    current_ledger = compiler.load_locked(compiler.CURRENT_LEDGER)
    selected_ledger = compiler.load_locked(compiler.SELECTED_LEDGER)
    assert oracle_baseline["oracles"][:289] == current_oracles["oracles"]
    assert oracle_baseline["oracles"][289:] == selected_oracles["oracles"][289:]
    assert ledger_baseline["capabilities"][:289] == current_ledger["capabilities"]
    assert (
        ledger_baseline["capabilities"][289:] == selected_ledger["capabilities"][289:]
    )
    assert len(oracle_baseline["oracles"][289:]) == 211
    assert len(ledger_baseline["capabilities"][289:]) == 211


def test_rebind_preserves_every_oracle_and_ledger_row(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, ledger_baseline, ledger_output, bindings = (
        derivation
    )
    counts = compiler.validate(
        oracle_baseline,
        oracle_output,
        ledger_baseline,
        ledger_output,
        bindings,
    )
    assert counts == {
        "external_provider_rows_changed": 0,
        "ledger_rows": 500,
        "oracle_rows": 500,
        "preserved_ledger_rows": 500,
        "preserved_oracle_rows": 500,
        "projected_actions": 21,
        "retained_executor_ready": 3,
        "projected_product_calls": 34,
        "projected_requests": 21,
        "promoted_ledger_rows": 0,
        "runtime_evidence": 0,
        "selected_suffix": 211,
    }
    assert oracle_output == oracle_baseline
    assert ledger_output == ledger_baseline


def test_core_rows_bind_the_exact_rebound_runtime_producer(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, _, _, bindings = derivation
    before = {row["capability_id"]: row for row in oracle_baseline["oracles"]}
    after = {row["capability_id"]: row for row in oracle_output["oracles"]}
    interface, _ = compiler.load_interface()
    executor = interface["producer"]["executor"]["path"]
    assert (
        interface["producer"]["canonical_base_commit"] == compiler.CANONICAL_BASE_COMMIT
    )
    assert interface["producer"]["source_binding"] == ("raw_sha256_current_checkpoint")
    assert interface["projection"]["oracle_rows_changed"] == 0
    for capability_id in compiler.TARGET_IDS:
        old = before[capability_id]
        row = after[capability_id]
        binding = bindings[capability_id]
        assert row == compiler.expected_target(old, binding, executor)
        assert row["current_state"] == "open_unexecuted"
        assert row["evidence"] == []
        assert row["acceptance_readiness"] == {
            "blockers": [],
            "classification": "executor_ready",
        }
        assert row["fixture"]["materialization"] == {
            "generator": executor,
            **binding["fixture_manifest"],
        }
        assert row["fixture"]["input"]["namespace"] == binding["runtime_namespace"]
        assert row["cleanup"]["allowlist"] == [binding["runtime_namespace"]]
        assert row["cleanup"]["targets"] == [binding["runtime_namespace"]]
        assert row["cleanup"]["executor"] == executor
        assert row["cleanup"]["postcondition_collectors"] == [executor]
        assert row["execution_bounds"]["executor"] == executor
        assert row["execution_bounds"]["collectors"] == [executor]
        assert row["execution_bounds"]["max_actions"] == 7
        assert row["execution_bounds"]["max_requests"] == 7
        assert row["fixture"]["input"]["contract"] == row["ledger_binding"]["contract"]
        assert (
            row["ledger_binding"]["contract"]["source_controls"]
            == binding["runtime"]["source_controls"]
        )


def test_rebound_producer_file_locks_are_exact() -> None:
    interface, _ = compiler.load_interface()
    expected = {
        "contract": "7fa1c4070cc3089c3e7f30511cf89bbc0e50fe773ab408e702c6d5717e6470a8",
        "contract_schema": "beda5705dad3b6cdff0c9aa11ae3ecd716df1508e0f7042d503f3a87fde80553",
        "executor": "e736ff075c3494ab0a6a11208fa564a863588ee14608ba6d1016286a807f78e6",
        "result_schema": "469e3ee85e34481c6d55ca2d544a80bfdefc092f83b55fde28eea0ac6bff4571",
    }
    assert {
        name: interface["producer"][name]["sha256"] for name in expected
    } == expected
    for name, digest in expected.items():
        lock = interface["producer"][name]
        assert compiler.sha256(compiler.repo_file(lock["path"]).read_bytes()) == digest


def test_noncore_spatial_rows_and_external_entry_07_are_exactly_unchanged(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, ledger_baseline, ledger_output, _ = derivation
    oracle_before = {row["capability_id"]: row for row in oracle_baseline["oracles"]}
    oracle_after = {row["capability_id"]: row for row in oracle_output["oracles"]}
    ledger_before = {row["id"]: row for row in ledger_baseline["capabilities"]}
    ledger_after = {row["id"]: row for row in ledger_output["capabilities"]}
    untouched = set(compiler.SPATIAL_IDS) - set(compiler.TARGET_IDS)
    for capability_id in untouched:
        assert oracle_after[capability_id] == oracle_before[capability_id]
        assert ledger_after[capability_id] == ledger_before[capability_id]
    external = compiler.SPATIAL_IDS[7]
    assert oracle_after[external]["current_state"] == "external_boundary_unexecuted"
    assert oracle_after[external]["ledger_binding"]["thor_state"] == (
        "external_optional"
    )
    assert oracle_after[external]["ledger_binding"]["runtime_state"] == (
        "not_applicable"
    )


def test_contract_assertions_follow_projected_runtime_source_controls(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    _, oracle_output, _, _, _ = derivation
    rows = {row["capability_id"]: row for row in oracle_output["oracles"]}
    for capability_id in compiler.TARGET_IDS:
        row = rows[capability_id]
        contract = row["ledger_binding"]["contract"]
        for assertion in row["assertions"]:
            prefix = "contract_identity/contract/"
            if assertion["observation"].startswith(prefix):
                key = assertion["observation"].removeprefix(prefix)
                if key in contract:
                    assert assertion["expected"] == contract[key]


def test_undeclared_non_target_oracle_mutation_fails_closed(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, ledger_baseline, ledger_output, bindings = (
        derivation
    )
    mutated = copy.deepcopy(oracle_output)
    target = next(
        row
        for row in mutated["oracles"]
        if row["capability_id"] == compiler.SPATIAL_IDS[0]
    )
    target["mode"] = "runtime"
    with pytest.raises(compiler.ProjectionError, match="non-target oracle changed"):
        compiler.validate(
            oracle_baseline, mutated, ledger_baseline, ledger_output, bindings
        )


def test_forged_target_state_or_evidence_fails_closed(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, ledger_baseline, ledger_output, bindings = (
        derivation
    )
    mutated = copy.deepcopy(oracle_output)
    target = next(
        row
        for row in mutated["oracles"]
        if row["capability_id"] == compiler.TARGET_IDS[0]
    )
    target["current_state"] = "external_boundary_unexecuted"
    with pytest.raises(compiler.ProjectionError, match="undeclared change"):
        compiler.validate(
            oracle_baseline, mutated, ledger_baseline, ledger_output, bindings
        )


def test_any_ledger_promotion_fails_closed(
    derivation: tuple[dict, dict, dict, dict, dict],
) -> None:
    oracle_baseline, oracle_output, ledger_baseline, ledger_output, bindings = (
        derivation
    )
    mutated = copy.deepcopy(ledger_output)
    target = next(
        row for row in mutated["capabilities"] if row["id"] == compiler.TARGET_IDS[0]
    )
    target["runtime_state"] = "passed_current"
    with pytest.raises(compiler.ProjectionError, match="ledger"):
        compiler.validate(
            oracle_baseline, oracle_output, ledger_baseline, mutated, bindings
        )


def test_runtime_interface_schema_is_closed() -> None:
    interface = compiler.load_locked(compiler.INTERFACE)
    schema = compiler.load_locked(compiler.INTERFACE_SCHEMA)
    mutated = copy.deepcopy(interface)
    mutated["producer"]["forged"] = True
    with pytest.raises(compiler.ProjectionError, match="schema failure"):
        compiler.schema_validate(mutated, schema, "runtime interface")
