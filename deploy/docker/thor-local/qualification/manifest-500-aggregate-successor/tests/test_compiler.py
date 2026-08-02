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
    "manifest_500_aggregate_compiler", PACKAGE / "compiler.py"
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
def manifest() -> dict:
    return load(compiler.MANIFEST_OUTPUT)


@pytest.fixture(scope="module")
def base() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["ledger_500_manifest"]["path"])


@pytest.fixture(scope="module")
def ledger() -> dict:
    return load(REPO_ROOT / compiler.INPUTS["ledger_500_capabilities"]["path"])


def test_deterministic_checked_outputs(proof: dict, manifest: dict) -> None:
    compiled_proof, compiled_manifest = compiler.compile_projection()
    assert compiled_proof == proof
    assert compiled_manifest == manifest
    assert compiler.PROOF_OUTPUT.read_bytes() == compiler._encoded(proof)
    assert compiler.MANIFEST_OUTPUT.read_bytes() == compiler._encoded(manifest)
    assert compiler.main(["--check"]) == 0


def test_schemas_are_valid_exact_and_outputs_validate(
    proof: dict, manifest: dict
) -> None:
    proof_schema = load(compiler.PROOF_SCHEMA)
    manifest_schema = load(compiler.MANIFEST_SCHEMA)
    Draft202012Validator.check_schema(proof_schema)
    Draft202012Validator.check_schema(manifest_schema)
    assert not list(Draft202012Validator(proof_schema).iter_errors(proof))
    assert not list(Draft202012Validator(manifest_schema).iter_errors(manifest))
    mutated = copy.deepcopy(proof)
    mutated["aggregate_updates"][0]["feature_id"] = "wrong"
    assert list(Draft202012Validator(proof_schema).iter_errors(mutated))
    mutated = copy.deepcopy(proof)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(proof_schema).iter_errors(mutated))


@pytest.mark.parametrize(
    "mutation",
    [
        "feature_reorder",
        "feature_id_substitution",
        "skill_reorder",
        "skill_id_substitution",
        "capability_id_reorder",
        "valid_enum_scalar",
    ],
)
def test_exact_manifest_schema_rejects_identity_order_and_scalar_mutations(
    manifest: dict, mutation: str
) -> None:
    schema = load(compiler.MANIFEST_SCHEMA)
    mutated = copy.deepcopy(manifest)
    if mutation == "feature_reorder":
        mutated["features"][0], mutated["features"][1] = (
            mutated["features"][1],
            mutated["features"][0],
        )
    elif mutation == "feature_id_substitution":
        mutated["features"][0]["id"] = "substituted-feature"
    elif mutation == "skill_reorder":
        mutated["skills"][0], mutated["skills"][1] = (
            mutated["skills"][1],
            mutated["skills"][0],
        )
    elif mutation == "skill_id_substitution":
        mutated["skills"][0]["id"] = "substituted-skill"
    elif mutation == "capability_id_reorder":
        row = next(
            row
            for row in mutated["features"]
            if len(row["official_capability_ids"]) >= 2
        )
        row["official_capability_ids"][0], row["official_capability_ids"][1] = (
            row["official_capability_ids"][1],
            row["official_capability_ids"][0],
        )
    elif mutation == "valid_enum_scalar":
        mutated["features"][0]["thor_state"] = "wired"
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)
    assert list(Draft202012Validator(schema).iter_errors(mutated)), mutation


def test_exact_raw_nine_policy_three_and_applied_six(proof: dict) -> None:
    assert [
        (row["feature_index"], row["feature_id"], row["differing_fields"])
        for row in proof["raw_reducer_diagnostic"]
    ] == [
        (2, "video-summarization-live", ["thor_state"]),
        (7, "alert-notifications-slack", ["thor_state"]),
        (8, "rt-vlm-media", ["thor_state"]),
        (20, "vios-codecs-audio", ["thor_state"]),
        (21, "audio-understanding", ["runtime_state"]),
        (22, "vios-ui", ["thor_state"]),
        (27, "agent-and-mcp-apis", ["thor_state"]),
        (32, "helm", ["thor_state"]),
        (34, "enterprise-rag", ["thor_state"]),
    ]
    assert [row["feature_id"] for row in proof["external_policy_preservations"]] == [
        "alert-notifications-slack",
        "helm",
        "enterprise-rag",
    ]
    assert [row["feature_id"] for row in proof["aggregate_updates"]] == [
        "video-summarization-live",
        "rt-vlm-media",
        "vios-codecs-audio",
        "audio-understanding",
        "vios-ui",
        "agent-and-mcp-apis",
    ]
    assert (
        compiler._sha_json(proof["raw_reducer_diagnostic"])
        == "f629a11b2ef6934d2bbf6b4900659fe3e0f10d531c05884b3b8fc2290bea97ce"
    )


def test_only_exact_six_fields_change(base: dict, manifest: dict, proof: dict) -> None:
    compiler._assert_only_exact_updates(base, manifest, proof["aggregate_updates"])
    assert base["skills"] == manifest["skills"]
    assert [row["id"] for row in base["features"]] == [
        row["id"] for row in manifest["features"]
    ]
    assert [row["official_capability_ids"] for row in base["features"]] == [
        row["official_capability_ids"] for row in manifest["features"]
    ]
    mutated = copy.deepcopy(manifest)
    mutated["features"][0]["gap"] += " changed"
    with pytest.raises(compiler.ProjectionError, match="changed-field set drift"):
        compiler._assert_only_exact_updates(base, mutated, proof["aggregate_updates"])


def test_reducer_results_and_external_policy_partition(
    base: dict, manifest: dict, ledger: dict, proof: dict
) -> None:
    assert compiler._aggregate_drift(base, ledger) == proof["raw_reducer_diagnostic"]
    assert (
        compiler._aggregate_drift(base, ledger, preserve_external_family_policy=True)
        == proof["aggregate_updates"]
    )
    assert (
        compiler._aggregate_drift(manifest, ledger)
        == proof["external_policy_preservations"]
    )
    assert (
        compiler._aggregate_drift(
            manifest, ledger, preserve_external_family_policy=True
        )
        == []
    )


@pytest.mark.parametrize(
    ("classes", "thor", "runtime", "expected"),
    [
        (
            ["alternate_local_lane", "required_local"],
            ["wired", "wired"],
            ["static_only", "static_only"],
            ("required_local", "wired", "static_only"),
        ),
        (
            ["external_optional", "external_optional"],
            ["wired", "partial"],
            ["not_applicable", "not_applicable"],
            ("external_optional", "partial", "not_applicable"),
        ),
        (
            ["alternate_local_lane", "alternate_local_lane"],
            ["wired", "partial"],
            ["blocked", "static_only"],
            ("alternate_local_lane", "partial", "not_qualified"),
        ),
    ],
)
def test_live_reducer_semantics(
    classes: list[str],
    thor: list[str],
    runtime: list[str],
    expected: tuple[str, str, str],
) -> None:
    group = [
        {"acceptance_class": a, "thor_state": t, "runtime_state": r}
        for a, t, r in zip(classes, thor, runtime, strict=True)
    ]
    result = compiler._derive_status(group)
    assert tuple(result[field] for field in compiler.STATUS_FIELDS) == expected


def test_raw_nine_violates_external_rule_but_six_update_manifest_satisfies_it(
    base: dict, manifest: dict, proof: dict
) -> None:
    raw_nine = compiler._project(base, proof["raw_reducer_diagnostic"])

    def conflicts(value: dict) -> list[str]:
        return [
            row["id"]
            for row in value["features"]
            if row["acceptance_class"] == "external_optional"
            and (
                row["thor_state"] != "external_optional"
                or row["runtime_state"] != "not_applicable"
            )
        ]

    assert conflicts(raw_nine) == [
        "alert-notifications-slack",
        "helm",
        "enterprise-rag",
    ]
    assert conflicts(manifest) == []
    source = (REPO_ROOT / compiler.INPUTS["live_manifest_verifier"]["path"]).read_text(
        encoding="utf-8"
    )
    assert "external_optional must use thor_state=external_optional" in source


def test_locked_live_manifest_validator_rejects_raw_nine_and_accepts_policy_six(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: dict,
    manifest: dict,
    proof: dict,
) -> None:
    parity = REPO_ROOT / "deploy/docker/thor-local/parity"
    verifier_spec = importlib.util.spec_from_file_location(
        "aggregate_successor_live_manifest_verifier", parity / "verify_manifest.py"
    )
    assert verifier_spec is not None and verifier_spec.loader is not None
    sys.path.insert(0, str(parity))
    try:
        verifier = importlib.util.module_from_spec(verifier_spec)
        verifier_spec.loader.exec_module(verifier)
    finally:
        sys.path.remove(str(parity))
    monkeypatch.setattr(
        verifier, "git", lambda *args: type("Result", (), {"returncode": 0})()
    )
    monkeypatch.setattr(
        verifier, "validate_official_capabilities", lambda manifest: None
    )
    candidate = tmp_path / "manifest.json"
    monkeypatch.setattr(verifier, "MANIFEST", candidate)

    raw_nine = compiler._project(base, proof["raw_reducer_diagnostic"])
    candidate.write_text(json.dumps(raw_nine), encoding="utf-8")
    with pytest.raises(
        ValueError, match="external_optional must use thor_state=external_optional"
    ):
        verifier.validate()

    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    assert verifier.validate() == manifest


def test_acceptance_gaps_remain_exact_and_separate(proof: dict) -> None:
    assert proof["remaining_merge_readiness"]["acceptance_scenario_coverage_gaps"] == [
        {
            "feature_id": "rt-cv-2d",
            "missing_scenario_ids": ["official-capability-contracts"],
        },
        {
            "feature_id": "video-summarization-live",
            "missing_scenario_ids": ["mcp-tool-operation-matrix"],
        },
        {
            "feature_id": "search-scale",
            "missing_scenario_ids": ["official-capability-contracts"],
        },
        {
            "feature_id": "alert-notifications-slack",
            "missing_scenario_ids": ["openclaw-workflows"],
        },
        {
            "feature_id": "rt-vlm-media",
            "missing_scenario_ids": ["rest-api-operation-matrix"],
        },
        {
            "feature_id": "rt-vlm-models",
            "missing_scenario_ids": ["official-capability-contracts"],
        },
        {
            "feature_id": "rt-vlm-performance-observability",
            "missing_scenario_ids": ["official-capability-contracts"],
        },
        {
            "feature_id": "audio-understanding",
            "missing_scenario_ids": ["core-agent-workflows"],
        },
    ]
    assert proof["summary"]["policy_correct_aggregate_blocker_count_after"] == 0
    assert proof["summary"]["acceptance_coverage_gap_count"] == 8
    assert proof["summary"]["remaining_blocker_category_count"] == 1


def test_duplicate_and_nonfinite_json_are_rejected() -> None:
    with pytest.raises(compiler.ProjectionError, match="duplicate JSON key"):
        compiler._strict_json(b'{"x":1,"x":2}', "duplicate")
    with pytest.raises(compiler.ProjectionError, match="non-finite"):
        compiler._strict_json(b'{"x":NaN}', "nonfinite")


@pytest.mark.parametrize(
    "path", ["/absolute.json", "../escape.json", "x/../../escape.json", ""]
)
def test_unsafe_repository_paths_are_rejected(path: str) -> None:
    with pytest.raises(compiler.ProjectionError, match="unsafe repository path"):
        compiler._repo_file(path)


def test_repository_symlink_traversal_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value.json").write_text("{}", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(compiler, "REPO_ROOT", root)
    with pytest.raises(compiler.ProjectionError, match="traverses symlink"):
        compiler._repo_file("link/value.json")


def test_atomic_writer_rejects_symlink_target_and_parent(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    real = tmp_path / "real.json"
    real.write_text("old", encoding="utf-8")
    target.symlink_to(real)
    with pytest.raises(compiler.ProjectionError, match="unsafe output path"):
        compiler._atomic_write(target, b"new")
    real_dir = tmp_path / "real-dir"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(compiler.ProjectionError, match="unsafe output parent"):
        compiler._atomic_write(linked_dir / "value.json", b"new")


def test_compiler_has_no_runtime_network_docker_or_subprocess_calls(
    proof: dict,
) -> None:
    tree = ast.parse((PACKAGE / "compiler.py").read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not ({"requests", "urllib", "socket", "subprocess", "docker"} & imports)
    assert proof["policy"]["runtime_actions"] == []
    assert proof["policy"]["network_access"] is False
    assert proof["policy"]["docker_access"] is False
    assert proof["policy"]["warehouse_sample_bundle"] == "excluded"
    assert "warehouse-4cams-20mx20m-synthetic" not in json.dumps(proof)
    assert "warehouse-loading-dock-3cams-synthetic" not in json.dumps(proof)
