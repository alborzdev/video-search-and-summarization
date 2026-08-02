from __future__ import annotations

import ast
import copy
import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "metadata500_current", HERE / "compiler.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_checked_successor_is_exact_and_inert() -> None:
    summary = MODULE.check()
    assert summary == {
        "available_sets": 2,
        "capabilities": 500,
        "candidate_evidence": 0,
        "candidate_executor_ready": 0,
        "candidates": 211,
        "collectors": 0,
        "discrepancies": 47,
        "executors": 0,
        "external_boundary_unexecuted": 36,
        "historical_admissions": 0,
        "historical_artifacts_locked": 5,
        "historical_authorities": 0,
        "historical_candidate_ids_aligned": 211,
        "open_unexecuted": 464,
        "oracles": 500,
        "promotable": 0,
        "runtime_evidence": 0,
        "selected_set": "thor-vss-3.2.1-current-cancellation-search-500",
        "sources": 126,
    }


def test_current_prefix_and_candidate_suffix_are_exact() -> None:
    ledger, oracles, source = MODULE.derive()
    assert ledger["capabilities"][:289] == source["current_ledger"]["capabilities"]
    assert oracles["oracles"][:289] == source["current_oracles"]["oracles"]
    assert ledger["capabilities"][289:] == source["base_ledger"]["capabilities"][289:]
    assert oracles["oracles"][289:] == source["base_oracles"]["oracles"][289:]


def test_five_historical_artifacts_are_exactly_locked_and_aligned() -> None:
    ledger, oracles, _source = MODULE.derive()
    assert MODULE._validate_historical_lineage(ledger, oracles) == {
        "historical_admissions": 0,
        "historical_artifacts_locked": 5,
        "historical_authorities": 0,
        "historical_candidate_ids_aligned": 211,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda _ledger, oracles: oracles["oracles"][0]["evidence"].append({}),
            "evidence, execution, or promotion",
        ),
        (
            lambda _ledger, oracles: oracles["oracles"][289]["execution_bounds"].update(
                {"executor": "invented"}
            ),
            "evidence, execution, or promotion",
        ),
        (
            lambda _ledger, oracles: oracles["oracles"][289].update(
                {"can_promote_runtime_state": True}
            ),
            "evidence, execution, or promotion",
        ),
    ],
)
def test_false_runtime_advancement_fails(mutation, message: str) -> None:
    ledger, oracles, source = MODULE.derive()
    mutation(ledger, oracles)
    with pytest.raises(
        MODULE.SuccessorError,
        match=f"schema failure|{message}",
    ):
        MODULE._validate_invariants(ledger, oracles, source)


def test_candidate_suffix_substitution_fails() -> None:
    original = MODULE._load_locked

    def mutated(entries):
        source = original(entries)
        if entries is MODULE.SOURCES:
            source = copy.deepcopy(source)
            source["base_oracles"]["oracles"][-1]["evidence"] = [{}]
        return source

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(MODULE, "_load_locked", mutated)
        ledger, oracles, source = MODULE.derive()
        with pytest.raises(MODULE.SuccessorError, match="evidence"):
            MODULE._validate_invariants(ledger, oracles, source)


def test_compiler_has_no_runtime_or_mutating_surface() -> None:
    tree = ast.parse((HERE / "compiler.py").read_text())
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
    assert not imported & {"requests", "urllib", "socket", "subprocess", "docker"}
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"write_bytes", "write_text"}
        for node in ast.walk(tree)
    )
