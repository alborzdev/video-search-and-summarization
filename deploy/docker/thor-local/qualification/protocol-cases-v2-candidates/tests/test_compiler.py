from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
REPO_ROOT = HERE.parents[6]
SPEC = importlib.util.spec_from_file_location(
    "protocol_cases_v2_candidate_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def checked() -> dict:
    document = load(compiler.OUTPUT)
    compiler.validate_candidate(document)
    return document


@pytest.fixture(scope="module")
def live() -> dict:
    return load(REPO_ROOT / compiler.SOURCE_PATHS["live_contract"])


@pytest.fixture(scope="module")
def candidate_input() -> dict:
    return load(REPO_ROOT / compiler.SOURCE_PATHS["candidate_input"])


def test_checked_output_is_exact_deterministic_compile(checked: dict) -> None:
    compiled = compiler.compile_candidate()
    assert compiled == checked
    assert compiler.OUTPUT.read_bytes() == compiler._encoded(compiled)
    assert compiler.main(["--check"]) == 0


def test_strict_schema_is_valid_and_rejects_unknown_keys(checked: dict) -> None:
    schema = load(compiler.SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(checked))
    mutated = copy.deepcopy(checked)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def test_exact_7_plus_23_denominator_is_derived_from_candidate_input(
    checked: dict, candidate_input: dict
) -> None:
    expected = {
        entry["proposed_capability"]["id"]
        for entry in candidate_input["entries"]
        if entry["proposed_capability"]["kind"] == "protocol"
    }
    legacy = [case for case in checked["cases"] if case["origin"] == "live_v1"]
    candidates = [
        case for case in checked["cases"] if case["origin"] == "candidate_manifest"
    ]
    assert len(legacy) == 7
    assert len(candidates) == len(expected) == 23
    assert {case["capability_id"] for case in candidates} == expected
    assert checked["summary"]["total_cases"] == 30


def test_live_cases_are_byte_semantically_preserved_and_reconstructable(
    checked: dict, live: dict
) -> None:
    wrappers = [case for case in checked["cases"] if case["origin"] == "live_v1"]
    assert [wrapper["legacy_case"] for wrapper in wrappers] == live["cases"]
    for wrapper, source in zip(wrappers, live["cases"], strict=True):
        assert compiler._canonical_bytes(
            wrapper["legacy_case"]
        ) == compiler._canonical_bytes(source)
        binding = next(
            item
            for item in checked["bindings"]
            if item["capability_id"] == wrapper["capability_id"]
        )
        assert binding["case_id"] == source["case_id"]
        assert binding["case_payload_sha256"] == compiler._sha_json(source)
        assert binding["vector_projection"] == {
            "kind": "executable_vectors",
            "positive_vector_id": source["positive_vector"]["id"],
            "adjacent_negative_vector_ids": [
                vector["id"] for vector in source["adjacent_negative_vectors"]
            ],
        }


def test_components_boundaries_and_readiness_are_explicit(checked: dict) -> None:
    assert checked["summary"]["boundary_counts"] == {
        "local": 27,
        "alternate_local": 1,
        "external": 2,
    }
    assert checked["summary"]["readiness_counts"] == {
        "planning_only": 23,
        "executor_ready": 5,
        "blocked": 2,
    }
    assert all(case["transport_components"] for case in checked["cases"])
    assert any(len(case["transport_components"]) >= 3 for case in checked["cases"])
    candidates = [
        case for case in checked["cases"] if case["origin"] == "candidate_manifest"
    ]
    assert all(
        case["readiness"] == "planning_only"
        and case["activation"]["supported"] is False
        and case["activation"]["executor_binding"] is None
        for case in candidates
    )


def test_external_cases_are_nonactivating_and_evidence_is_empty(checked: dict) -> None:
    external = [case for case in checked["cases"] if case["boundary"] == "external"]
    assert len(external) == 2
    assert all(case["activation"]["supported"] is False for case in external)
    assert all(case["runtime_evidence"] == [] for case in checked["cases"])
    assert checked["policy"]["runtime_evidence"] == []
    assert checked["policy"]["can_promote_runtime_state"] is False
    assert checked["summary"]["runtime_evidence_records"] == 0


def test_warehouse_sample_is_excluded_but_custom_data_plan_remains(
    checked: dict,
) -> None:
    warehouse = next(
        case
        for case in checked["cases"]
        if case["capability_id"]
        == "manifest-entry.warehouse-2d.01-kafka-and-redis-paths"
    )
    assert warehouse["boundary"] == "alternate_local"
    assert warehouse["readiness"] == "planning_only"
    assert warehouse["warehouse_sample_bundle"] == "excluded"
    assert checked["policy"]["warehouse_sample_bundle"] == "excluded"
    serialized = json.dumps(checked, sort_keys=True).lower()
    assert not any(
        marker in serialized for marker in compiler.EXCLUDED_WAREHOUSE_MARKERS
    )


def test_binding_projection_is_complete_stable_and_source_hashed(
    checked: dict,
) -> None:
    assert len(checked["bindings"]) == 30
    assert [binding["capability_id"] for binding in checked["bindings"]] == [
        case["capability_id"] for case in checked["cases"]
    ]
    for case, binding in zip(checked["cases"], checked["bindings"], strict=True):
        assert binding == compiler._binding(case)
        unhashed = copy.deepcopy(binding)
        claimed = unhashed.pop("binding_sha256")
        assert claimed == compiler._sha_json(unhashed)
        assert binding["source_hashes"]
        assert all(
            len(source["raw_sha256"]) == 64 for source in binding["source_hashes"]
        )
        if case["origin"] == "candidate_manifest":
            assert binding["vector_projection"]["kind"] == "planning_only"
            assert (
                binding["vector_projection"]["contract"]
                == case["candidate_contract"]["oracle_plan"]
            )


def test_all_source_locks_match_regular_checked_files(checked: dict) -> None:
    assert len(checked["source_locks"]) == 8
    assert {item["path"] for item in checked["source_locks"]} == set(
        compiler.SOURCE_PATHS.values()
    )
    for lock in checked["source_locks"]:
        path = REPO_ROOT / lock["path"]
        assert path.is_file() and not path.is_symlink()
        assert compiler._sha_bytes(path.read_bytes()) == lock["raw_sha256"]


def test_live_mutation_fails_closed(checked: dict) -> None:
    mutated = copy.deepcopy(checked)
    legacy = next(case for case in mutated["cases"] if case["origin"] == "live_v1")
    legacy["legacy_case"]["protocol"] = "changed"
    payload = copy.deepcopy(mutated)
    payload.pop("candidate_payload_sha256")
    mutated["candidate_payload_sha256"] = compiler._sha_json(payload)
    with pytest.raises(compiler.CandidateError, match="byte-semantically preserved"):
        compiler.validate_candidate(mutated)


def test_candidate_activation_overclaim_fails_closed(checked: dict) -> None:
    mutated = copy.deepcopy(checked)
    candidate = next(
        case for case in mutated["cases"] if case["origin"] == "candidate_manifest"
    )
    candidate["activation"]["supported"] = True
    candidate["activation"]["executor_binding"] = "invented-runner"
    payload = copy.deepcopy(mutated)
    payload.pop("candidate_payload_sha256")
    mutated["candidate_payload_sha256"] = compiler._sha_json(payload)
    with pytest.raises(compiler.CandidateError, match="activation overclaim"):
        compiler.validate_candidate(mutated)
