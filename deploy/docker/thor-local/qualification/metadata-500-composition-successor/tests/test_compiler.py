from __future__ import annotations

import ast
import copy
import hashlib
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
    "metadata_500_composition_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def composition() -> dict:
    return load(compiler.OUTPUT)


@pytest.fixture(scope="module")
def schema() -> dict:
    return load(compiler.SCHEMA)


@pytest.fixture(scope="module")
def documents() -> dict[str, dict]:
    return {
        source_id: load(REPO_ROOT / specification["path"])
        for source_id, specification in compiler.INPUTS.items()
        if specification["json"]
    }


def test_checked_outputs_are_exact_deterministic_composition(
    composition: dict, schema: dict
) -> None:
    compiled, compiled_schema = compiler.compile_composition()
    assert compiled == composition
    assert compiled_schema == schema
    assert compiler.OUTPUT.read_bytes() == compiler._encoded(compiled)
    assert compiler.SCHEMA.read_bytes() == compiler._encoded(compiled_schema)
    assert compiler.main(["--check"]) == 0


def test_schema_is_exact_and_rejects_any_identity_order_or_status_drift(
    composition: dict, schema: dict
) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(composition))
    for mutate in (
        lambda value: value["remaining_blockers"].reverse(),
        lambda value: value["source_locks"].__setitem__(
            "ledger", value["source_locks"]["oracle_proof"]
        ),
        lambda value: value["summary"].__setitem__("capability_count", 499),
        lambda value: value["authoritative_validation"].__setitem__("result", "failed"),
    ):
        changed = copy.deepcopy(composition)
        mutate(changed)
        assert list(validator.iter_errors(changed))


def test_authoritative_official_validation_is_exact(
    composition: dict, documents: dict[str, dict]
) -> None:
    assert compiler._authoritative_validate(
        documents["ledger"],
        documents["aggregate_manifest"],
        documents["acceptance"],
    ) == {
        "sources": 126,
        "capabilities": 500,
        "feature_families": 55,
        "discrepancies": 47,
    }
    assert composition["authoritative_validation"] == {
        "verifier_source_id": "official_verifier",
        "result": "passed",
        "sources": 126,
        "capabilities": 500,
        "feature_families": 55,
        "discrepancies": 47,
        "policy_aggregate_drift": [],
        "acceptance_scenario_coverage_gaps": [],
    }


def test_policy_aggregate_and_acceptance_gap_reducers_are_zero(
    documents: dict[str, dict],
) -> None:
    assert (
        compiler._policy_aggregate_drift(
            documents["aggregate_manifest"], documents["ledger"]
        )
        == []
    )
    assert compiler._acceptance_gaps(documents["ledger"], documents["acceptance"]) == []


def test_projected_ledger_oracle_identity_order_and_bindings_are_exact(
    composition: dict, documents: dict[str, dict]
) -> None:
    capability_ids = [row["id"] for row in documents["ledger"]["capabilities"]]
    oracles = documents["oracle_proof"]["projected_oracles"]
    oracle_ids = [row["capability_id"] for row in oracles]
    assert len(capability_ids) == len(set(capability_ids)) == 500
    assert oracle_ids == capability_ids
    assert composition["identity_order"]["orders_equal"] is True
    assert composition["identity_order"][
        "projected_capability_order_sha256"
    ] == compiler._sha_json(capability_ids)
    assert composition["identity_order"][
        "projected_oracle_order_sha256"
    ] == compiler._sha_json(oracle_ids)
    for capability, oracle in zip(
        documents["ledger"]["capabilities"], oracles, strict=True
    ):
        assert oracle["ledger_binding"] == {
            key: capability[key]
            for key in (
                "title",
                "feature_id",
                "kind",
                "thor_state",
                "acceptance_class",
                "runtime_state",
                "source_claims",
                "gap",
                "contract",
            )
        }


def test_live_files_remain_exact_289_predecessors(
    composition: dict, documents: dict[str, dict]
) -> None:
    predecessor = compiler._validate_live_predecessor(documents)
    assert predecessor == composition["live_predecessor"]
    assert predecessor["capability_count"] == predecessor["oracle_count"] == 289
    assert predecessor["feature_count"] == 55
    assert predecessor["acceptance_feature_count"] == 55
    assert (
        predecessor["live_capability_order_sha256"]
        == predecessor["live_oracle_order_sha256"]
    )


def test_all_211_candidate_oracles_are_non_executable_and_unevidenced(
    composition: dict, documents: dict[str, dict]
) -> None:
    boundary = compiler._candidate_boundary(documents)
    assert boundary == composition["candidate_oracle_boundary"]
    assert boundary == {
        "candidate_oracle_count": 211,
        "candidate_executor_ready_count": 0,
        "candidate_evidence_record_count": 0,
        "candidate_promotable_count": 0,
        "candidate_fixture_materialized_count": 0,
        "historical_live_oracle_migration_pending": True,
    }


def test_remaining_blockers_are_honest_and_exact(composition: dict) -> None:
    assert [row["id"] for row in composition["remaining_blockers"]] == [
        "live-metadata-merge-pending",
        "candidate-oracle-execution-pending",
        "historical-live-oracle-migration-pending",
    ]
    assert composition["policy"]["live_merge_ready"] is False
    assert composition["summary"]["remaining_blocker_count"] == 3
    assert composition["summary"]["candidate_evidence_record_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("ledger_order", "identity-order"),
        ("oracle_order", "identity-order"),
        ("manifest_status", "aggregate/acceptance drift"),
        ("scenario_remove", "aggregate/acceptance drift"),
        ("aggregate_cross_swap", "aggregate/acceptance drift"),
        ("oracle_binding", "oracle ledger binding"),
    ],
)
def test_cross_swap_order_status_scenario_mutations_fail_closed(
    documents: dict[str, dict], mutation: str, message: str
) -> None:
    value = copy.deepcopy(documents)
    if mutation == "ledger_order":
        value["ledger"]["capabilities"][0], value["ledger"]["capabilities"][1] = (
            value["ledger"]["capabilities"][1],
            value["ledger"]["capabilities"][0],
        )
        value["ledger_proof"]["artifacts"]["projected_official_capabilities"][
            "canonical_sha256"
        ] = compiler._sha_json(value["ledger"])
    elif mutation == "oracle_order":
        rows = value["oracle_proof"]["projected_oracles"]
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "manifest_status":
        value["aggregate_manifest"]["features"][0]["thor_state"] = "source_only"
        value["aggregate_proof"]["artifacts"]["projected_manifest"][
            "canonical_sha256"
        ] = compiler._sha_json(value["aggregate_manifest"])
    elif mutation == "scenario_remove":
        feature = next(
            row
            for row in value["acceptance"]["coverage"]["features"]
            if row["feature_id"] == "rt-cv-2d"
        )
        feature["scenario_ids"].remove("official-capability-contracts")
    elif mutation == "aggregate_cross_swap":
        value["aggregate_manifest"] = copy.deepcopy(value["ledger_manifest"])
        value["aggregate_proof"]["artifacts"]["projected_manifest"] = {
            "path": compiler.INPUTS["aggregate_manifest"]["path"],
            "raw_sha256": compiler.INPUTS["aggregate_manifest"]["raw_sha256"],
            "canonical_sha256": compiler._sha_json(value["aggregate_manifest"]),
        }
    elif mutation == "oracle_binding":
        value["oracle_proof"]["projected_oracles"][0]["ledger_binding"]["title"] += (
            " drift"
        )
    else:  # pragma: no cover
        raise AssertionError(mutation)
    with pytest.raises(compiler.CompositionError, match=message):
        compiler._validate_cross_bindings(value)


def test_candidate_evidence_or_activation_mutation_fails_closed(
    documents: dict[str, dict],
) -> None:
    value = copy.deepcopy(documents)
    candidate = value["oracle_proof"]["projected_oracles"][289]
    candidate["evidence"] = [{"invented": True}]
    with pytest.raises(compiler.CompositionError, match="executable/evidence"):
        compiler._candidate_boundary(value)
    value = copy.deepcopy(documents)
    candidate = next(
        row
        for row in value["oracle_proof"]["projected_oracles"][289:]
        if row["protocol_v2_binding"] is not None
    )
    candidate["protocol_v2_binding"]["activation_supported"] = True
    with pytest.raises(compiler.CompositionError, match="executable/evidence"):
        compiler._candidate_boundary(value)


def test_all_source_locks_match_exact_safe_files(composition: dict) -> None:
    assert set(composition["source_locks"]) == set(compiler.INPUTS)
    for source_id, lock in composition["source_locks"].items():
        assert lock == {
            "path": compiler.INPUTS[source_id]["path"],
            "raw_sha256": compiler.INPUTS[source_id]["raw_sha256"],
        }
        path = REPO_ROOT / lock["path"]
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == lock["raw_sha256"]


def test_duplicate_and_nonfinite_json_fail_closed() -> None:
    with pytest.raises(compiler.CompositionError, match="duplicate JSON key"):
        compiler._strict_json(b'{"same":1,"same":2}', "adversarial")
    with pytest.raises(compiler.CompositionError, match="non-finite"):
        compiler._strict_json(b'{"value":NaN}', "adversarial")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape", "x/../../y"])
def test_unsafe_repository_paths_fail_closed(relative: str) -> None:
    with pytest.raises(compiler.CompositionError, match="unsafe repository path"):
        compiler._repo_file(relative)


def test_symlink_repository_input_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked.json").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.CompositionError, match="symlink"):
        compiler._repo_file("linked.json")


def test_atomic_writer_rejects_existing_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"original\n")
    output = tmp_path / "composition.json"
    output.symlink_to(victim)
    with pytest.raises(compiler.CompositionError, match="unsafe output path"):
        compiler._atomic_write(output, b"replacement\n")
    assert victim.read_bytes() == b"original\n"


def test_compiler_has_no_runtime_network_docker_host_or_model_activation(
    composition: dict,
) -> None:
    text = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "TO_BE_PINNED" not in text
    tree = ast.parse(text)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {
        "docker",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "urllib",
    }
    assert composition["policy"] == {
        "candidate_only": True,
        "modifies_live_files": False,
        "live_merge_ready": False,
        "runtime_execution": "forbidden",
        "network_access": False,
        "docker_access": False,
        "host_inspection": False,
        "model_execution": False,
        "required_cloud_inference": False,
        "warehouse_sample_bundle": "excluded",
    }
