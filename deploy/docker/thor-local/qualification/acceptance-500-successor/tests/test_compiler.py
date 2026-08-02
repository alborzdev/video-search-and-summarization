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
    "acceptance_500_successor_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def proof() -> dict:
    return load(compiler.PROOF_OUTPUT)


@pytest.fixture(scope="module")
def proof_schema() -> dict:
    return load(compiler.PROOF_SCHEMA_OUTPUT)


@pytest.fixture(scope="module")
def projected() -> dict:
    return load(compiler.INVENTORY_OUTPUT)


@pytest.fixture(scope="module")
def projected_schema() -> dict:
    return load(compiler.INVENTORY_SCHEMA_OUTPUT)


@pytest.fixture(scope="module")
def current() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["acceptance_inventory"]["path"])


@pytest.fixture(scope="module")
def manifest() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["projected_manifest"]["path"])


@pytest.fixture(scope="module")
def ledger() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["projected_ledger"]["path"])


@pytest.fixture(scope="module")
def ledger_proof() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["ledger_projection_proof"]["path"])


def test_checked_outputs_are_exact_deterministic_compile(
    proof: dict,
    proof_schema: dict,
    projected: dict,
    projected_schema: dict,
) -> None:
    compiled = compiler.compile_projection()
    assert compiled == (proof, proof_schema, projected, projected_schema)
    assert compiler.PROOF_OUTPUT.read_bytes() == compiler._encoded(proof)
    assert compiler.PROOF_SCHEMA_OUTPUT.read_bytes() == compiler._encoded(proof_schema)
    assert compiler.INVENTORY_OUTPUT.read_bytes() == compiler._inventory_output_bytes(
        projected
    )
    assert compiler.INVENTORY_SCHEMA_OUTPUT.read_bytes() == compiler._encoded(
        projected_schema
    )
    assert compiler.main(["--check"]) == 0


def test_generated_schemas_are_valid_exact_and_outputs_validate(
    proof: dict,
    proof_schema: dict,
    projected: dict,
    projected_schema: dict,
) -> None:
    for schema, value in (
        (proof_schema, proof),
        (projected_schema, projected),
    ):
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        assert not list(validator.iter_errors(value))
        mutated = copy.deepcopy(value)
        mutated["unexpected"] = True
        assert list(validator.iter_errors(mutated))


def test_only_exact_eight_scenario_suffixes_change(
    current: dict, projected: dict, proof: dict
) -> None:
    assert current.keys() == projected.keys()
    for key in current:
        if key != "coverage":
            assert projected[key] == current[key]
    assert projected["coverage"]["skills"] == current["coverage"]["skills"]
    assert projected["coverage"]["api_surfaces"] == current["coverage"]["api_surfaces"]
    expected = set(compiler.EXPECTED_ADDITIONS)
    observed = set()
    for before, after in zip(
        current["coverage"]["features"],
        projected["coverage"]["features"],
        strict=True,
    ):
        assert before["feature_id"] == after["feature_id"]
        assert {
            key: value for key, value in after.items() if key != "scenario_ids"
        } == {key: value for key, value in before.items() if key != "scenario_ids"}
        if before["scenario_ids"] != after["scenario_ids"]:
            assert after["scenario_ids"][:-1] == before["scenario_ids"]
            assert len(after["scenario_ids"]) == len(before["scenario_ids"]) + 1
            observed.add((after["feature_id"], after["scenario_ids"][-1]))
    assert observed == expected
    assert len(proof["scenario_additions"]) == len(observed) == 8


def test_removing_eight_replacement_blocks_restores_live_bytes_exactly(
    current: dict, projected: dict
) -> None:
    source = (REPO_ROOT / compiler.INPUTS["acceptance_inventory"]["path"]).read_bytes()
    output = compiler.INVENTORY_OUTPUT.read_bytes()
    assert output == compiler._surgical_inventory_bytes(source, current, projected)

    def feature_block(row: dict) -> str:
        rendered = json.dumps(row, ensure_ascii=True, indent=2, sort_keys=True)
        return "\n".join(f"      {line}" for line in rendered.splitlines())

    restored = output.decode("utf-8")
    replacements = 0
    for before, after in zip(
        current["coverage"]["features"],
        projected["coverage"]["features"],
        strict=True,
    ):
        if before == after:
            continue
        new = feature_block(after)
        old = feature_block(before)
        assert restored.count(new) == 1
        restored = restored.replace(new, old, 1)
        replacements += 1
    assert replacements == 8
    assert restored.encode("utf-8") == source


def test_eight_ledger_coverage_gaps_become_zero_and_family_blockers_remain_separate(
    current: dict,
    projected: dict,
    ledger: dict,
    ledger_proof: dict,
    proof: dict,
) -> None:
    expected = [
        {"feature_id": feature_id, "missing_scenario_ids": [scenario_id]}
        for feature_id, scenario_id in compiler.EXPECTED_ADDITIONS
    ]
    assert compiler._coverage_gaps(ledger, current) == expected
    assert compiler._coverage_gaps(ledger, projected) == []
    assert (
        ledger_proof["merge_readiness"]["blockers"]["acceptance_scenario_coverage_gaps"]
        == expected
    )
    assert proof["remaining_blockers"]["acceptance_scenario_coverage_gaps"] == []
    family = proof["remaining_blockers"]["family_status_aggregate_drift"]
    assert tuple(row["feature_id"] for row in family) == (
        compiler.EXPECTED_FAMILY_BLOCKERS
    )
    assert proof["summary"]["family_aggregate_blocker_count"] == 9
    assert proof["summary"]["live_merge_ready"] is False


def test_projected_inventory_retains_acceptance_verifier_semantics(
    projected: dict, manifest: dict
) -> None:
    compiler._validate_inventory_semantics(projected, manifest)
    scenario_ids = {row["id"] for row in projected["scenarios"]}
    assert all(
        set(row["scenario_ids"]) <= scenario_ids
        for row in projected["coverage"]["features"]
    )


def test_locked_official_verifier_accepts_after_separate_family_normalization(
    projected: dict, manifest: dict, ledger: dict
) -> None:
    parity = REPO_ROOT / "deploy/docker/thor-local/parity"
    specification = importlib.util.spec_from_file_location(
        "acceptance_500_official_verifier",
        parity / "verify_official_capabilities.py",
    )
    assert specification is not None and specification.loader is not None
    verifier = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(parity))
    try:
        specification.loader.exec_module(verifier)
    finally:
        sys.path.pop(0)

    normalized_manifest = copy.deepcopy(manifest)
    changed = []
    for feature in normalized_manifest["features"]:
        group = [
            capability
            for capability in ledger["capabilities"]
            if capability["feature_id"] == feature["id"]
        ]
        classes = {row["acceptance_class"] for row in group}
        expected_class = (
            "required_local"
            if "required_local" in classes
            else "external_optional"
            if classes == {"external_optional"}
            else "alternate_local_lane"
        )
        thor_states = {row["thor_state"] for row in group}
        expected_thor = next(iter(thor_states)) if len(thor_states) == 1 else "partial"
        runtime_states = {row["runtime_state"] for row in group}
        expected_runtime = (
            next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
        )
        before = (
            feature["acceptance_class"],
            feature["thor_state"],
            feature["runtime_state"],
        )
        after = (expected_class, expected_thor, expected_runtime)
        if before != after:
            changed.append(feature["id"])
        feature["acceptance_class"] = expected_class
        feature["thor_state"] = expected_thor
        feature["runtime_state"] = expected_runtime
    assert tuple(changed) == compiler.EXPECTED_FAMILY_BLOCKERS
    assert verifier.validate(
        ledger=ledger,
        manifest=normalized_manifest,
        acceptance=projected,
        repo_root=REPO_ROOT,
    ) == {
        "sources": 126,
        "capabilities": 500,
        "feature_families": 55,
        "discrepancies": 47,
    }


def test_projection_is_static_nonadvancing_and_adds_no_warehouse_sample(
    current: dict, projected: dict, proof: dict
) -> None:
    assert projected["execution_enabled"] is current["execution_enabled"] is False
    assert proof["policy"] == {
        "candidate_only": True,
        "modifies_live_files": False,
        "runtime_execution": "forbidden",
        "runtime_evidence_added": False,
        "required_cloud_inference": False,
        "warehouse_sample_bundle": "excluded",
        "custom_data_warehouse_capability": "preserved",
    }
    additions = json.dumps(proof["scenario_additions"], sort_keys=True).lower()
    assert "warehouse" not in additions
    assert projected["blockers"] == current["blockers"]
    assert projected["scenarios"] == current["scenarios"]


def test_all_source_and_artifact_hashes_are_exact(
    proof: dict, projected: dict, projected_schema: dict
) -> None:
    for source_id, lock in proof["source_locks"].items():
        path = REPO_ROOT / lock["path"]
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == lock["raw_sha256"]
        assert lock == {
            "path": compiler.INPUTS[source_id]["path"],
            "raw_sha256": compiler.INPUTS[source_id]["raw_sha256"],
        }
    assert proof["artifacts"]["projected_acceptance_inventory"][
        "raw_sha256"
    ] == compiler._sha_bytes(compiler._inventory_output_bytes(projected))
    assert proof["artifacts"]["projected_acceptance_inventory_schema"][
        "raw_sha256"
    ] == compiler._sha_bytes(compiler._encoded(projected_schema))


@pytest.mark.parametrize(
    "mutation",
    [
        "non_target_field",
        "replace_instead_of_append",
        "extra_scenario",
        "feature_reorder",
        "top_level",
    ],
)
def test_nonminimal_inventory_mutations_fail_closed(
    current: dict, projected: dict, proof: dict, mutation: str
) -> None:
    value = copy.deepcopy(projected)
    if mutation == "non_target_field":
        value["coverage"]["features"][0]["disposition"] = "external-optional"
    elif mutation == "replace_instead_of_append":
        row = next(
            row
            for row in value["coverage"]["features"]
            if row["feature_id"] == compiler.EXPECTED_ADDITIONS[0][0]
        )
        row["scenario_ids"] = row["scenario_ids"][1:]
    elif mutation == "extra_scenario":
        value["coverage"]["features"][0]["scenario_ids"].append(
            "official-capability-contracts"
        )
    elif mutation == "feature_reorder":
        value["coverage"]["features"][0], value["coverage"]["features"][1] = (
            value["coverage"]["features"][1],
            value["coverage"]["features"][0],
        )
    elif mutation == "top_level":
        value["mode"] += "-drift"
    else:  # pragma: no cover
        raise AssertionError(mutation)
    with pytest.raises(compiler.ProjectionError):
        compiler._verify_projection(current, value, proof["scenario_additions"])


def test_ledger_requirement_or_proof_gap_drift_fails_closed(
    current: dict, ledger: dict, manifest: dict, ledger_proof: dict
) -> None:
    mutated_ledger = copy.deepcopy(ledger)
    for capability in mutated_ledger["capabilities"]:
        if (
            capability["feature_id"] == "rt-cv-2d"
            and "official-capability-contracts" in capability["scenario_ids"]
        ):
            capability["scenario_ids"].remove("official-capability-contracts")
    with pytest.raises(compiler.ProjectionError, match="exact eight"):
        compiler._project_inventory(current, mutated_ledger, manifest, ledger_proof)
    mutated_proof = copy.deepcopy(ledger_proof)
    mutated_proof["merge_readiness"]["blockers"]
    gaps = mutated_proof["merge_readiness"]["blockers"][
        "acceptance_scenario_coverage_gaps"
    ]
    gaps.reverse()
    with pytest.raises(compiler.ProjectionError, match="exact eight"):
        compiler._project_inventory(current, ledger, manifest, mutated_proof)


def test_duplicate_and_nonfinite_json_fail_closed() -> None:
    with pytest.raises(compiler.ProjectionError, match="duplicate JSON key"):
        compiler._strict_json(b'{"same":1,"same":2}', "adversarial")
    with pytest.raises(compiler.ProjectionError, match="non-finite"):
        compiler._strict_json(b'{"value":NaN}', "adversarial")


@pytest.mark.parametrize("relative", ["/etc/passwd", "../escape", "x/../../y"])
def test_unsafe_repository_paths_fail_closed(relative: str) -> None:
    with pytest.raises(compiler.ProjectionError, match="unsafe repository path"):
        compiler._repo_file(relative)


def test_symlink_repository_input_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked.json").symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.ProjectionError, match="symlink"):
        compiler._repo_file("linked.json")


def test_atomic_writer_rejects_existing_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"original\n")
    output = tmp_path / "projection.json"
    output.symlink_to(victim)
    with pytest.raises(compiler.ProjectionError, match="unsafe output path"):
        compiler._atomic_write(output, b"replacement\n")
    assert victim.read_bytes() == b"original\n"


def test_compiler_is_static_and_integrity_locks_are_pinned() -> None:
    text = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "TO_BE_PINNED" not in text
    for name in (
        "EXPECTED_INVENTORY_RAW_SHA256",
        "EXPECTED_INVENTORY_SCHEMA_RAW_SHA256",
        "EXPECTED_PROOF_RAW_SHA256",
        "EXPECTED_PROOF_SCHEMA_RAW_SHA256",
        "EXPECTED_PROOF_PAYLOAD_SHA256",
    ):
        assert len(getattr(compiler, name)) == 64
        int(getattr(compiler, name), 16)
    tree = ast.parse(text)
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
