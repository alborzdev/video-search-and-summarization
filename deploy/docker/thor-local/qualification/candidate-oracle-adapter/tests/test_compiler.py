from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
REPO_ROOT = HERE.parents[6]
SPEC = importlib.util.spec_from_file_location(
    "candidate_oracle_adapter_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def artifact() -> dict:
    value = load(compiler.OUTPUT)
    compiler.validate_adapter(value)
    return value


@pytest.fixture(scope="module")
def candidate() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["candidate"]["path"])


@pytest.fixture(scope="module")
def ledger() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["official_capabilities"]["path"])


@pytest.fixture(scope="module")
def oracles() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["capability_oracles"]["path"])


def test_checked_adapter_is_exact_deterministic_compile(artifact: dict) -> None:
    compiled = compiler.compile_adapter()
    assert compiled == artifact
    assert compiler.OUTPUT.read_bytes() == compiler._encoded(compiled)
    assert compiler.main(["--check"]) == 0


def test_exact_211_candidate_key_partition(
    artifact: dict, candidate: dict, ledger: dict
) -> None:
    adapters = artifact["candidate_adapters_by_capability_id"]
    expected = {entry["proposed_capability"]["id"] for entry in candidate["entries"]}
    current = {capability["id"] for capability in ledger["capabilities"]}
    assert set(adapters) == expected
    assert len(adapters) == len(expected) == 211
    assert not expected & current
    assert len(expected | current) == 500
    assert all(key == row["capability_id"] for key, row in adapters.items())


def test_every_candidate_plan_is_exactly_bound_and_machine_translated(
    artifact: dict, candidate: dict
) -> None:
    adapters = artifact["candidate_adapters_by_capability_id"]
    for entry in candidate["entries"]:
        capability = entry["proposed_capability"]
        contract = capability["contract"]
        plan = entry["oracle_plan"]
        row = adapters[capability["id"]]
        assert row["oracle_id"] == f"oracle.{capability['id']}"
        assert row["profile_seed"].startswith("candidate-")
        assert row["mode_seed"] in {
            "static",
            "config",
            "runtime",
            "api",
            "protocol",
            "model",
            "deploy",
        }
        assert row["candidate_entry_sha256"] == compiler._sha_json(entry)
        assert row["candidate_oracle_plan"] == plan
        assert row["acceptance_class"] == capability["acceptance_class"]
        assert row["execution_boundary"] == plan["execution_boundary"]
        assert row["source_claims"] == capability["source_claims"]
        assert row["implementation_surfaces"] == contract["implementation_surfaces"]
        assert row["ledger_binding"] == {
            key: capability[key]
            for key in (
                "feature_id",
                "kind",
                "title",
                "source_claims",
                "acceptance_class",
                "thor_state",
                "runtime_state",
                "contract",
                "gap",
            )
        }
        assert row["reviewed_scenario_ids"] == [
            *capability["scenario_ids"],
            row["oracle_id"],
        ]
        assert row["fixture"]["id"] == f"fixture.{capability['id']}"
        assert row["fixture"]["strategy"] == plan["fixture_strategy"]
        assert row["fixture"]["materialization"] is None
        input_contract = row["fixture"]["input_contract"]
        assert input_contract["capability_id"] == capability["id"]
        assert input_contract["manifest_pointer"] == entry["manifest_pointer"]
        assert input_contract["advertised_literal"] == entry["advertised"]
        assert (
            input_contract["dependency_capability_ids"]
            == contract["dependency_capability_ids"]
        )
        assert (
            input_contract["implementation_surfaces"]
            == contract["implementation_surfaces"]
        )
        assert input_contract["required_semantics"] == contract["required_semantics"]
        assert input_contract["source_claims"] == capability["source_claims"]
        assert [item["description"] for item in row["expected_observations"]] == plan[
            "required_observations"
        ]
        assert [
            item["description"] for item in row["adjacent_negative_observations"]
        ] == plan["adjacent_negative"]
        observation_ids = {
            item["id"]
            for item in row["expected_observations"]
            + row["adjacent_negative_observations"]
        }
        assert {item["observation_id"] for item in row["assertions"]} == observation_ids
        assert row["cleanup"]["intent"] == plan["cleanup_boundary"]


def test_exact_74_authoritative_gap_requirements(
    artifact: dict, candidate: dict
) -> None:
    adapters = artifact["candidate_adapters_by_capability_id"]
    expected = {
        entry["proposed_capability"]["id"]: entry["gap_plan_binding"]
        for entry in candidate["entries"]
        if entry["prior_mapping_class"] == "explicit_missing_entry_gap"
    }
    actual = {
        capability_id: row["candidate_oracle_plan"]["authoritative_gap_requirement"]
        for capability_id, row in adapters.items()
        if "authoritative_gap_requirement" in row["candidate_oracle_plan"]
    }
    assert actual == expected
    assert len(actual) == 74


def test_candidates_are_unmaterialized_unexecuted_and_non_promoting(
    artifact: dict,
) -> None:
    rows = artifact["candidate_adapters_by_capability_id"].values()
    assert artifact["summary"]["candidate_executor_ready_count"] == 0
    assert artifact["summary"]["candidate_evidence_record_count"] == 0
    assert artifact["summary"]["candidate_promoted_count"] == 0
    for row in rows:
        assert row["fixture"]["materialization"] is None
        assert row["execution_bounds"]["executor"] is None
        assert row["execution_bounds"]["collectors"] is None
        assert row["execution_bounds"]["max_duration_seconds"] is None
        assert row["execution_bounds"]["max_requests"] is None
        assert row["execution_bounds"]["max_actions"] is None
        assert row["cleanup"]["executor"] is None
        assert row["cleanup"]["postcondition_collectors"] is None
        assert row["readiness"]["classification"] == "planning_index_only"
        assert row["readiness"]["fixture_materialized"] is False
        assert row["readiness"]["executor_ready"] is False
        assert row["current_state"].endswith("unexecuted")
        assert row["runtime_state"] in {"not_qualified", "not_applicable"}
        assert row["evidence"] == []
        assert row["can_promote_runtime_state"] is False


def test_all_289_current_oracle_states_and_evidence_are_preserved(
    artifact: dict, ledger: dict, oracles: dict
) -> None:
    capability_by_id = {
        capability["id"]: capability for capability in ledger["capabilities"]
    }
    oracle_by_id = {oracle["capability_id"]: oracle for oracle in oracles["oracles"]}
    preservation = artifact["current_oracle_preservation"]
    actual = preservation["by_capability_id"]
    assert set(actual) == set(capability_by_id) == set(oracle_by_id)
    assert len(actual) == 289
    for capability_id, row in actual.items():
        expected = {
            "oracle_id": oracle_by_id[capability_id]["oracle_id"],
            "current_state": oracle_by_id[capability_id]["current_state"],
            "ledger_runtime_state": capability_by_id[capability_id]["runtime_state"],
            "evidence": oracle_by_id[capability_id]["evidence"],
        }
        assert {key: row[key] for key in expected} == expected
        assert row["state_evidence_sha256"] == compiler._sha_json(
            {
                key: expected[key]
                for key in ("current_state", "ledger_runtime_state", "evidence")
            }
        )
    assert preservation["ledger_records_canonical_sha256"] == compiler._sha_json(
        ledger["capabilities"]
    )
    assert preservation["oracle_records_canonical_sha256"] == compiler._sha_json(
        oracles["oracles"]
    )
    assert preservation["state_evidence_projection_sha256"] == compiler._sha_json(
        actual
    )


def test_schema_is_strict_and_artifact_valid(artifact: dict) -> None:
    schema = load(compiler.SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(artifact))
    mutated = copy.deepcopy(artifact)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def _mutate_candidate_load(
    monkeypatch: pytest.MonkeyPatch,
    candidate: dict,
    mutator,
) -> None:
    mutated = copy.deepcopy(candidate)
    mutator(mutated)
    payload = dict(mutated)
    payload.pop("candidate_payload_sha256")
    mutated["candidate_payload_sha256"] = compiler._sha_json(payload)
    original = compiler._load_locked
    candidate_path = compiler.INPUTS["candidate"]["path"]

    def substitute(relative: str, expected_sha256: str):
        if relative == candidate_path:
            return mutated, "0" * 64
        return original(relative, expected_sha256)

    monkeypatch.setattr(compiler, "_load_locked", substitute)


def test_duplicate_candidate_capability_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate: dict
) -> None:
    def duplicate(value: dict) -> None:
        value["entries"][1]["proposed_capability"]["id"] = value["entries"][0][
            "proposed_capability"
        ]["id"]

    _mutate_candidate_load(monkeypatch, candidate, duplicate)
    with pytest.raises(compiler.AdapterError, match="duplicate|colliding"):
        compiler.compile_adapter()


def test_unknown_source_claim_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate: dict
) -> None:
    def drift(value: dict) -> None:
        value["entries"][0]["proposed_capability"]["source_claims"][0]["source_id"] = (
            "unknown-source"
        )

    _mutate_candidate_load(monkeypatch, candidate, drift)
    with pytest.raises(compiler.AdapterError, match="source claim drift"):
        compiler.compile_adapter()


def test_synthetic_advertised_locator_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate: dict
) -> None:
    def synthesize(value: dict) -> None:
        value["entries"][0]["proposed_capability"]["source_claims"][0]["locator"] = (
            "Advertised string copied from the manifest"
        )

    _mutate_candidate_load(monkeypatch, candidate, synthesize)
    with pytest.raises(compiler.AdapterError, match="synthetic advertised"):
        compiler.compile_adapter()


def test_absolute_implementation_surface_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate: dict
) -> None:
    def escape(value: dict) -> None:
        value["entries"][0]["proposed_capability"]["contract"][
            "implementation_surfaces"
        ] = ["/etc/passwd"]

    _mutate_candidate_load(monkeypatch, candidate, escape)
    with pytest.raises(compiler.AdapterError, match="implementation surface"):
        compiler.compile_adapter()


def test_authoritative_gap_contradiction_fails_closed(
    monkeypatch: pytest.MonkeyPatch, candidate: dict
) -> None:
    def contradict(value: dict) -> None:
        entry = next(
            row
            for row in value["entries"]
            if row["prior_mapping_class"] == "explicit_missing_entry_gap"
        )
        entry["oracle_plan"]["authoritative_gap_requirement"]["id"] += "-drift"

    _mutate_candidate_load(monkeypatch, candidate, contradict)
    with pytest.raises(compiler.AdapterError, match="authoritative gap requirement"):
        compiler.compile_adapter()


def test_duplicate_json_key_fails_closed() -> None:
    with pytest.raises(compiler.AdapterError, match="duplicate JSON key"):
        compiler._strict_json(b'{"same":1,"same":2}', "adversarial")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape.json", "x/../../y"])
def test_unsafe_repository_paths_fail_closed(relative: str) -> None:
    with pytest.raises(compiler.AdapterError, match="unsafe repository path"):
        compiler._repo_file(relative)


def test_symlink_repository_input_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked.json").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.AdapterError, match="symlink"):
        compiler._repo_file("linked.json")


def test_atomic_writer_rejects_existing_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"original\n")
    output = tmp_path / "adapter.json"
    output.symlink_to(victim)
    with pytest.raises(compiler.AdapterError, match="symlink output"):
        compiler._atomic_write_regular(output, b"replacement\n")
    assert victim.read_bytes() == b"original\n"


def test_compiler_ast_has_no_runtime_network_or_activation_primitives() -> None:
    tree = ast.parse((PACKAGE / "compiler.py").read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported & {
        "docker",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "urllib",
    }
