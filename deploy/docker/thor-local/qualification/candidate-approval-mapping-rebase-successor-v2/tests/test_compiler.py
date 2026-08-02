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


PACKAGE = Path(__file__).resolve().parents[1]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_approval_mapping_rebase_successor_v2_compiler", COMPILER_PATH
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_json(source, path, value):
    changed = dict(source)
    changed[path] = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return changed


@pytest.fixture(scope="module")
def sources():
    return compiler._load_locked_sources()


@pytest.fixture(scope="module")
def artifact():
    return compiler.compile_mapping()


def test_checked_artifact_equals_fresh_compilation(artifact):
    assert artifact == _load(compiler.ARTIFACT_PATH)
    assert compiler.check_artifact() == artifact


def test_exact_209_predecessor_rows_are_preserved_byte_for_byte(artifact):
    predecessor = _load(compiler.repo_path(compiler.V1_MAPPING_PATH))
    before = {
        row["capability_id"]: row
        for row in predecessor["mappings"]
        if row["capability_id"] not in compiler.RESOLVED_IDS
    }
    after = {
        row["capability_id"]: row
        for row in artifact["mappings"]
        if row["capability_id"] not in compiler.RESOLVED_IDS
    }
    assert len(before) == len(after) == 209
    assert before == after
    for capability_id in before:
        assert compiler.canonical_bytes(
            before[capability_id]
        ) == compiler.canonical_bytes(after[capability_id])
        assert (
            json.dumps(before[capability_id], indent=2, sort_keys=True).encode()
            == json.dumps(after[capability_id], indent=2, sort_keys=True).encode()
        )
    assert (
        compiler.sha256(compiler.canonical_bytes(list(after.values())))
        == compiler.EXPECTED_UNAFFECTED_ROWS_SHA256
    )


def test_exact_two_resolutions_are_narrow_and_reviewed(artifact):
    predecessor = _load(compiler.repo_path(compiler.V1_MAPPING_PATH))
    before = {row["capability_id"]: row for row in predecessor["mappings"]}
    after = {row["capability_id"]: row for row in artifact["mappings"]}
    changed = {
        capability_id
        for capability_id in before
        if before[capability_id] != after[capability_id]
    }
    assert changed == compiler.RESOLVED_IDS

    sparse = after[compiler.SPARSE_ID]
    assert sparse["mapping_state"] == "mapped"
    assert sparse["leaf_bundle_id"] == compiler.SPARSE_LEAF
    assert sparse["suggested_bundle_id"] is None
    assert sparse["reason_code"] == "sparse4d_dependency_repaired_custom_data_scope"
    assert sparse["dependency_closure"] == [
        "host-prerequisite-evidence-collection",
        "read-only-docker-runtime-inspection",
        "cgroupfs-remediation",
        "model-artifact-downloads",
        "profile-lifecycle",
        compiler.SPARSE_LEAF,
    ]

    firewall = after[compiler.FIREWALL_ID]
    assert firewall["mapping_state"] == "mapped"
    assert firewall["leaf_bundle_id"] == compiler.FIREWALL_CONFIGURATION
    assert firewall["suggested_bundle_id"] is None
    assert firewall["reason_code"] == "physical_interface_firewall_bounded_bundle_scope"
    assert firewall["dependency_closure"] == [
        compiler.FIREWALL_INSPECTION,
        compiler.FIREWALL_CONFIGURATION,
    ]


def test_exact_counts_bindings_and_closures(artifact):
    assert artifact["summary"] == {
        "candidate_count": 211,
        "state_counts": compiler.EXPECTED_STATE_COUNTS,
        "direct_leaf_counts": compiler.EXPECTED_DIRECT_COUNTS,
        "dependency_closure_link_counts": compiler.EXPECTED_CLOSURE_COUNTS,
        "binding_counts": {"workload": 60, "protocol": 23, "none": 128},
        "preserved_mapping_count": 209,
        "resolved_mapping_count": 2,
        "receipt_count": 0,
        "approvals_granted": 0,
        "admitted_candidates": 0,
        "executable_candidates": 0,
    }
    assert artifact["mapping_records_canonical_sha256"] == (
        compiler.EXPECTED_MAPPING_ROWS_SHA256
    )


def test_exact_source_lock_denominator_and_dependency_provenance(artifact):
    assert artifact["source_locks"] == [
        {"path": path, "raw_sha256": digest}
        for path, digest in compiler.EXPECTED_SOURCE_HASHES.items()
    ]
    assert len(artifact["source_locks"]) == 14
    provenance = artifact["resolution_provenance"]
    assert provenance["resolved_capability_ids"] == [
        compiler.SPARSE_ID,
        compiler.FIREWALL_ID,
    ]
    assert provenance["sparse4d_dependency_before"] == [compiler.WRONG_DEPENDENCY]
    assert provenance["sparse4d_dependency_after"] == [compiler.CORRECT_DEPENDENCY]
    assert (
        provenance["sparse4d_corrected_candidate_capability_canonical_sha256"]
        == compiler.CORRECTED_SPARSE_CAPABILITY_SHA256
    )
    assert provenance["firewall_exact_closure"] == [
        compiler.FIREWALL_INSPECTION,
        compiler.FIREWALL_CONFIGURATION,
    ]


def test_zero_activation_is_unconditional(artifact):
    policy = artifact["policy"]
    assert policy["receipt_consumer_present"] is False
    assert policy["receipts_present"] == 0
    assert policy["approvals_granted"] == 0
    assert policy["admitted_candidates"] == 0
    assert policy["executable_candidates"] == 0
    assert policy["approval_inheritance"] is False
    assert policy["required_cloud_inference"] is False
    assert policy["warehouse_sample_bundle"] == "excluded"
    for row in artifact["mappings"]:
        assert row["approval_state"] == "no_receipt_not_admitted_not_executable"
        assert row["required_cloud_inference"] is False
        assert row["warehouse_sample_bundle"] is False
        assert not any(
            key in row
            for key in {
                "authorized_command",
                "action_flags",
                "service_roles",
                "profile_ids",
                "compose_paths",
                "receipts",
            }
        )


def test_schema_rejects_activation_and_unknown_fields(artifact):
    validator = Draft202012Validator(_load(compiler.SCHEMA_PATH))
    for path, value in (
        (("policy", "receipts_present"), 1),
        (("summary", "approvals_granted"), 1),
        (("summary", "admitted_candidates"), 1),
        (("summary", "executable_candidates"), 1),
    ):
        forged = copy.deepcopy(artifact)
        forged[path[0]][path[1]] = value
        assert list(validator.iter_errors(forged))
    forged = copy.deepcopy(artifact)
    forged["mappings"][0]["authorized_command"] = "docker compose up"
    assert list(validator.iter_errors(forged))


def test_unaffected_predecessor_drift_is_rejected(sources):
    predecessor = compiler.strict_json(sources[compiler.V1_MAPPING_PATH], "v1")
    changed = copy.deepcopy(predecessor)
    changed["mappings"][0]["reason_code"] = "native_audio_scope"
    with pytest.raises(compiler.MappingV2Error, match="mapping-record identity drift"):
        compiler.compile_mapping(
            _replace_json(sources, compiler.V1_MAPPING_PATH, changed)
        )


def test_raw_source_lock_drift_is_rejected(monkeypatch):
    changed = dict(compiler.EXPECTED_SOURCE_HASHES)
    changed[compiler.BUNDLES_COMPILER_PATH] = "0" * 64
    monkeypatch.setattr(compiler, "EXPECTED_SOURCE_HASHES", changed)
    with pytest.raises(compiler.MappingV2Error, match="source lock mismatch"):
        compiler._load_locked_sources()


def test_conflict_and_scope_gap_forgery_are_rejected(sources):
    predecessor = compiler.strict_json(sources[compiler.V1_MAPPING_PATH], "v1")
    for capability_id, leaf in (
        (compiler.SPARSE_ID, compiler.SPARSE_LEAF),
        (compiler.FIREWALL_ID, "profile-lifecycle"),
    ):
        changed = copy.deepcopy(predecessor)
        row = next(
            item
            for item in changed["mappings"]
            if item["capability_id"] == capability_id
        )
        row["mapping_state"] = "mapped"
        row["leaf_bundle_id"] = leaf
        row["suggested_bundle_id"] = None
        row["dependency_closure"] = [leaf]
        with pytest.raises(
            compiler.MappingV2Error, match="mapping-record identity drift"
        ):
            compiler.compile_mapping(
                _replace_json(sources, compiler.V1_MAPPING_PATH, changed)
            )


def test_sparse4d_repair_drift_is_rejected(sources):
    repair = compiler.strict_json(sources[compiler.REPAIR_PATH], "repair")
    changed = copy.deepcopy(repair)
    changed["repair"]["after"] = [compiler.WRONG_DEPENDENCY]
    with pytest.raises(
        compiler.MappingV2Error,
        match="schema violation|repair identity",
    ):
        compiler.compile_mapping(_replace_json(sources, compiler.REPAIR_PATH, changed))


def test_firewall_dependency_and_bundle_denominator_drift_are_rejected(sources):
    bundles = compiler.strict_json(sources[compiler.BUNDLES_PATH], "bundles")
    changed = copy.deepcopy(bundles)
    configuration = next(
        item
        for item in changed["bundles"]
        if item["id"] == compiler.FIREWALL_CONFIGURATION
    )
    configuration["depends_on"] = []
    with pytest.raises(
        compiler.MappingV2Error,
        match="schema violation|firewall bundle scope",
    ):
        compiler.compile_mapping(_replace_json(sources, compiler.BUNDLES_PATH, changed))

    deleted = copy.deepcopy(bundles)
    deleted["bundles"].pop()
    deleted["bundle_count"] = 15
    with pytest.raises(
        compiler.MappingV2Error,
        match="schema violation|16-bundle successor",
    ):
        compiler.compile_mapping(_replace_json(sources, compiler.BUNDLES_PATH, deleted))


def test_compiler_has_bounded_writer_and_no_runtime_action_surface():
    source = COMPILER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {"socket", "subprocess", "requests", "urllib", "docker", "shutil"}
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {
            "system",
            "popen",
            "run",
            "Popen",
            "connect",
            "bind",
            "listen",
            "unlink",
            "mkdir",
            "rename",
            "replace",
        }
    )
    assert "--execute" not in source
    assert '"--check"' in source
    assert '"--emit"' in source
    assert '"--write"' in source


def test_duplicate_json_and_unsafe_or_symlinked_path_are_rejected(
    tmp_path, monkeypatch
):
    with pytest.raises(compiler.MappingV2Error, match="duplicate JSON key"):
        compiler.strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.MappingV2Error, match="unsafe repository path"):
        compiler.repo_path("../outside")
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.json").write_text("{}", encoding="utf-8")
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.MappingV2Error, match="contains a symlink"):
        compiler.repo_path("linked/source.json")


def test_check_emit_and_output_hashes_are_deterministic(capsys):
    assert compiler.main(["--check"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert summary["preserved_mapping_count"] == 209
    assert summary["resolved_mapping_count"] == 2
    assert summary["receipt_count"] == 0
    assert summary["admitted_candidates"] == 0
    assert summary["executable_candidates"] == 0
    assert compiler.main(["--emit"]) == 0
    assert json.loads(capsys.readouterr().out) == _load(compiler.ARTIFACT_PATH)
    for name, expected in compiler.EXPECTED_OUTPUT_HASHES.items():
        assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == expected


def test_sparse4d_rebase_four_file_provenance_is_exact(artifact):
    lock_map = {
        item["path"]: item["raw_sha256"] for item in artifact["source_locks"]
    }
    assert lock_map[compiler.REPAIR_PATH] == (
        "099b89d6e0b75b01e768b71ebaa6b0a719153185cf7aba5e6d0e5eb50e3247d7"
    )
    assert lock_map[compiler.REPAIR_SCHEMA_PATH] == (
        "162e203bd62efbfacf3fda95e43a43a14bad9a23753dca9e1c53edc33bd22e87"
    )
    assert lock_map[compiler.REPAIR_COMPILER_PATH] == (
        "49274a7cc3843097099fedcabe4bc879c79a4b8e45d2f67b1ff2a08fadacb294"
    )
    assert lock_map[compiler.REPAIR_TESTS_PATH] == (
        "f288992eec5520c78984e8bcf202def71d42c943a2348740d76f607f1ad65524"
    )


def test_historical_v2_delta_is_only_rebased_integrity_provenance(artifact):
    historical_path = compiler.repo_path(f"{compiler.HISTORICAL_DIR}/mapping.json")
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    before = {row["capability_id"]: row for row in historical["mappings"]}
    after = {row["capability_id"]: row for row in artifact["mappings"]}
    changed = {capability_id for capability_id in before if before[capability_id] != after[capability_id]}
    assert changed == {
        "manifest-entry.video-summarization-file.03-structured-output",
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
    }
    for capability_id in set(before) - changed:
        assert before[capability_id] == after[capability_id]


def test_historical_and_canonical_locks_fail_closed(tmp_path, monkeypatch):
    compiler._assert_immutable_historical_and_canonical_files()
    drift = tmp_path / "drift"
    drift.write_text("drift", encoding="utf-8")
    first = next(iter(compiler.IMMUTABLE_HISTORICAL_HASHES))
    original = compiler.repo_path
    with monkeypatch.context() as scoped:
        scoped.setattr(
            compiler,
            "repo_path",
            lambda relative: drift if relative == first else original(relative),
        )
        with pytest.raises(compiler.MappingV2Error, match="immutable historical"):
            compiler._assert_immutable_historical_and_canonical_files()


def test_bounded_writer_is_idempotent_and_refuses_overwrite(tmp_path, monkeypatch):
    output = tmp_path / "mapping.json"
    monkeypatch.setattr(compiler, "ARTIFACT_PATH", output)
    expected = compiler.write_artifact()
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    original = output.read_bytes()
    assert compiler.write_artifact() == expected
    assert output.read_bytes() == original
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(compiler.MappingV2Error, match="refusing to overwrite"):
        compiler.write_artifact()
