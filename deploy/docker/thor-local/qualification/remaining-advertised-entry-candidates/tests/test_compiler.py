from __future__ import annotations

import ast
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
    "remaining_advertised_entry_candidate_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def candidate() -> dict:
    value = load(compiler.OUTPUT)
    compiler.validate_candidate(value)
    return value


@pytest.fixture(scope="module")
def coverage() -> dict:
    return load(REPO_ROOT / compiler.SOURCE_PATHS["advertised_entry_coverage"])


@pytest.fixture(scope="module")
def gap_plan() -> dict:
    return load(REPO_ROOT / compiler.SOURCE_PATHS["advertised_gap_plan"])


def test_checked_candidate_is_exact_deterministic_compile(candidate: dict) -> None:
    compiled = compiler.compile_candidate()
    assert compiled == candidate
    assert compiler.OUTPUT.read_bytes() == compiler._encoded(compiled)
    assert compiler.main(["--check"]) == 0


def test_exact_211_partition_and_denominators(
    candidate: dict, coverage: dict
) -> None:
    assert candidate["summary"] == {
        "candidate_entries": 211,
        "candidate_merged_capabilities": 500,
        "candidate_exact_mappings": 500,
        "candidate_missing_exact_mappings": 0,
        "explicit_missing_entry_gap": 74,
        "family_only_unreviewed": 137,
        "gap_plan_bindings": 74,
        "acceptance_class_counts": {
            "alternate_local_lane": 46,
            "external_optional": 6,
            "required_local": 159,
        },
        "candidate_runtime_evidence_records": 0,
        "warehouse_sample_bundle_entries": 0,
    }
    expected = {
        item["manifest_pointer"]
        for item in coverage["entries"]
        if item["mapping_class"] in compiler.EXPECTED_PRIOR_COUNTS
    }
    actual = {item["manifest_pointer"] for item in candidate["entries"]}
    assert len(expected) == len(actual) == 211
    assert actual == expected
    assert 289 + len(actual) == 500


def test_every_candidate_is_exact_title_feature_pointer_and_identity(
    candidate: dict,
) -> None:
    capability_ids: set[str] = set()
    for item in candidate["entries"]:
        capability = item["proposed_capability"]
        expected_id = compiler._candidate_id(
            item["feature_id"], item["advertised_index"], item["advertised"]
        )
        assert capability["id"] == expected_id
        assert capability["id"] not in capability_ids
        capability_ids.add(capability["id"])
        assert capability["feature_id"] == item["feature_id"]
        assert capability["title"] == item["advertised"]
        assert capability["contract"]["manifest_pointer"] == item["manifest_pointer"]
        assert capability["contract"]["advertised_literal"] == item["advertised"]
        assert item["manifest_pointer"] == (
            f"/features/{item['feature_index']}/advertised/{item['advertised_index']}"
        )


def test_all_74_gap_bindings_are_byte_exact_and_open(
    candidate: dict, gap_plan: dict
) -> None:
    expected = {
        item["manifest_pointer"]: item["required_oracle"]
        for item in gap_plan["entries"]
    }
    actual = {
        item["manifest_pointer"]: item["gap_plan_binding"]
        for item in candidate["entries"]
        if "gap_plan_binding" in item
    }
    assert actual == expected
    assert len(actual) == 74
    assert all(item["status"] == "open_unexecuted" for item in actual.values())
    assert all(item["runtime_evidence"] == [] for item in actual.values())
    for item in candidate["entries"]:
        oracle = item["oracle_plan"]
        if item["prior_mapping_class"] == "explicit_missing_entry_gap":
            assert oracle["authoritative_gap_requirement"] == expected[
                item["manifest_pointer"]
            ]
        else:
            assert "authoritative_gap_requirement" not in oracle


def test_external_locality_and_runtime_states_are_fail_closed(candidate: dict) -> None:
    external = [
        item
        for item in candidate["entries"]
        if item["proposed_capability"]["acceptance_class"] == "external_optional"
    ]
    local = [item for item in candidate["entries"] if item not in external]
    assert len(external) == 6
    assert all(
        item["proposed_capability"]["runtime_state"] == "not_applicable"
        and item["oracle_plan"]["execution_boundary"] == "external"
        for item in external
    )
    assert all(
        item["proposed_capability"]["runtime_state"] == "not_qualified"
        and item["oracle_plan"]["execution_boundary"]
        == (
            "local"
            if item["proposed_capability"]["acceptance_class"] == "required_local"
            else "alternate_local"
        )
        for item in local
    )


def test_semantic_contracts_are_specific_and_source_bound(candidate: dict) -> None:
    for item in candidate["entries"]:
        capability = item["proposed_capability"]
        contract = capability["contract"]
        oracle = item["oracle_plan"]
        assert len(contract["implementation_surfaces"]) >= 1
        assert len(contract["required_semantics"]) >= 2
        assert len(capability["source_claims"]) >= 1
        assert len(capability["scenario_ids"]) >= 1
        assert len(oracle["required_observations"]) >= 2
        assert len(oracle["adjacent_negative"]) >= 1
        assert contract["warehouse_sample_bundle"] == "excluded"
        assert capability["gap"]


def test_no_runtime_evidence_promotion_cloud_requirement_or_warehouse_sample(
    candidate: dict,
) -> None:
    serialized = json.dumps(candidate, sort_keys=True).lower()
    assert candidate["policy"]["candidate_only"] is True
    assert candidate["policy"]["can_promote_runtime_state"] is False
    assert candidate["policy"]["runtime_evidence"] == []
    assert candidate["policy"]["required_cloud_inference"] is False
    assert candidate["policy"]["warehouse_sample_bundle"] == "excluded"
    assert "passed_current" not in serialized
    assert not any(marker in serialized for marker in compiler.EXCLUDED_WAREHOUSE_MARKERS)


def test_schema_is_strict_and_checked_output_is_valid(candidate: dict) -> None:
    schema = load(compiler.SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(candidate))
    mutated = copy.deepcopy(candidate)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))


def mutate_tranche(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutator,
) -> None:
    specifications = copy.deepcopy(compiler.TRANCHES)
    tranche_id = "features-00-09"
    source = REPO_ROOT / specifications[tranche_id]["path"]
    value = load(source)
    mutator(value)
    destination = tmp_path / "mutated-tranche.json"
    destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    specifications[tranche_id]["path"] = str(destination)
    specifications[tranche_id]["raw_sha256"] = "TO_BE_PINNED"
    monkeypatch.setattr(compiler, "TRANCHES", specifications)


def test_duplicate_or_missing_pointer_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def duplicate(value: dict) -> None:
        value["entries"][1] = copy.deepcopy(value["entries"][0])

    mutate_tranche(monkeypatch, tmp_path, duplicate)
    with pytest.raises(compiler.CandidateError, match="partition|duplicate"):
        compiler.compile_candidate()


def test_unknown_source_and_dependency_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unknown(value: dict) -> None:
        value["entries"][0]["proposed_capability"]["source_claims"][0][
            "source_id"
        ] = "unknown-source"

    mutate_tranche(monkeypatch, tmp_path, unknown)
    with pytest.raises(compiler.CandidateError, match="unknown source"):
        compiler.compile_candidate()


def test_external_boundary_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def localize_external(value: dict) -> None:
        item = next(
            entry
            for entry in value["entries"]
            if entry["proposed_capability"]["acceptance_class"]
            == "external_optional"
        )
        item["oracle_plan"]["execution_boundary"] = "local"

    mutate_tranche(monkeypatch, tmp_path, localize_external)
    with pytest.raises(compiler.CandidateError, match="execution boundary"):
        compiler.compile_candidate()


def test_source_locator_masquerading_as_local_surface_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def remove_local_surface(value: dict) -> None:
        item = next(
            entry
            for entry in value["entries"]
            if entry["proposed_capability"]["thor_state"] == "wired"
        )
        claim = item["proposed_capability"]["source_claims"][0]
        item["proposed_capability"]["contract"]["implementation_surfaces"] = [
            claim["locator"]
        ]

    mutate_tranche(monkeypatch, tmp_path, remove_local_surface)
    with pytest.raises(compiler.CandidateError, match="implementation surface"):
        compiler.compile_candidate()


def test_explicit_gap_missing_authoritative_requirement_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def remove_requirement(value: dict) -> None:
        item = next(
            entry
            for entry in value["entries"]
            if entry["prior_mapping_class"] == "explicit_missing_entry_gap"
        )
        item["oracle_plan"].pop("authoritative_gap_requirement")

    mutate_tranche(monkeypatch, tmp_path, remove_requirement)
    with pytest.raises(compiler.CandidateError, match="entry schema error"):
        compiler.compile_candidate()


def test_explicit_gap_contradicted_authoritative_requirement_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def contradict_requirement(value: dict) -> None:
        item = next(
            entry
            for entry in value["entries"]
            if entry["prior_mapping_class"] == "explicit_missing_entry_gap"
        )
        item["oracle_plan"]["authoritative_gap_requirement"]["id"] += "-drift"

    mutate_tranche(monkeypatch, tmp_path, contradict_requirement)
    with pytest.raises(
        compiler.CandidateError, match="authoritative gap requirement drift"
    ):
        compiler.compile_candidate()


def test_family_only_authoritative_requirement_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def add_requirement(value: dict) -> None:
        explicit = next(
            entry
            for entry in value["entries"]
            if entry["prior_mapping_class"] == "explicit_missing_entry_gap"
        )
        family_only = next(
            entry
            for entry in value["entries"]
            if entry["prior_mapping_class"] == "family_only_unreviewed"
        )
        family_only["oracle_plan"]["authoritative_gap_requirement"] = copy.deepcopy(
            explicit["oracle_plan"]["authoritative_gap_requirement"]
        )

    mutate_tranche(monkeypatch, tmp_path, add_requirement)
    with pytest.raises(compiler.CandidateError, match="entry schema error"):
        compiler.compile_candidate()


def test_synthetic_advertised_source_locator_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def synthesize_locator(value: dict) -> None:
        value["entries"][0]["proposed_capability"]["source_claims"][0][
            "locator"
        ] = "Advertised literal copied from the manifest"

    mutate_tranche(monkeypatch, tmp_path, synthesize_locator)
    with pytest.raises(compiler.CandidateError, match="synthetic advertised source locator"):
        compiler.compile_candidate()


def _surface_entry(surface: str) -> dict:
    return {
        "manifest_pointer": "/features/0/advertised/0",
        "proposed_capability": {
            "contract": {"implementation_surfaces": [surface]}
        },
    }


@pytest.mark.parametrize(
    "surface",
    [
        "/etc/passwd",
        "../outside.py",
        "deploy/docker/thor-local",
    ],
)
def test_non_repository_regular_file_surfaces_fail_closed(surface: str) -> None:
    with pytest.raises(compiler.CandidateError, match="implementation surface"):
        compiler._validate_surface(_surface_entry(surface))


def test_surface_fragment_is_allowed() -> None:
    compiler._validate_surface(
        _surface_entry(
            "deploy/docker/thor-local/qualification/"
            "remaining-advertised-entry-candidates/compiler.py#_validate_surface"
        )
    )


def test_symlink_surface_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.py"
    real.write_text("pass\n", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.CandidateError, match="symlink"):
        compiler._validate_surface(_surface_entry("linked.py#symbol"))


def test_atomic_writer_rejects_existing_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"original\n")
    output = tmp_path / "candidate.json"
    output.symlink_to(victim)
    with pytest.raises(compiler.CandidateError, match="symlink output"):
        compiler._atomic_write_regular(output, b"replacement\n")
    assert output.is_symlink()
    assert victim.read_bytes() == b"original\n"


def test_atomic_writer_replaces_with_regular_file(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    output.write_bytes(b"old\n")
    compiler._atomic_write_regular(output, b"new\n")
    assert output.read_bytes() == b"new\n"
    assert output.is_file()
    assert not output.is_symlink()


def test_raw_source_tamper_fails_before_semantic_compile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = REPO_ROOT / compiler.SOURCE_PATHS["manifest"]
    tampered = tmp_path / "manifest.json"
    tampered.write_bytes(manifest.read_bytes() + b"\n")
    source_paths = copy.deepcopy(compiler.SOURCE_PATHS)
    source_paths["manifest"] = str(tampered)
    monkeypatch.setattr(compiler, "SOURCE_PATHS", source_paths)
    with pytest.raises(compiler.CandidateError, match="raw digest drift"):
        compiler.compile_candidate()


def test_compiler_ast_has_no_activation_or_network_primitives() -> None:
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
