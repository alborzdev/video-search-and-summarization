from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_approval_mapping_rebase_successor_compiler", COMPILER_PATH
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources():
    return compiler._load_locked_sources()


@pytest.fixture(scope="module")
def artifact():
    return compiler.compile_mapping()


def test_final_review_has_no_pending_locks_and_checked_outputs(capsys):
    report = compiler.review_scaffold()
    assert report["status"] == "final_activation_rebase_bound"
    assert report["pending_locks"] == compiler.pending_final_locks() == []
    assert report["preservation"] == {
        "mapping_row_count": 211,
        "predecessor_mapping_records_canonical_sha256": (
            "93791e8b9d7b8ec3368ba78c1f55217498260bdb1c3f9777f0d3f6e5ab11c60c"
        ),
        "rebased_mapping_records_canonical_sha256": (
            "9ec211afcabe645573a145c7a5e9dbaf5c030eab552da4add0698f15e33b2062"
        ),
        "classification_and_mapping_semantics_exact": True,
        "integrity_only_rebased_capability_ids": sorted(
            compiler.INTEGRITY_REBASE_IDS
        ),
        "integrity_only_rebased_fields": list(compiler.INTEGRITY_REBASE_FIELDS),
        "zero_approval_semantics_exact": True,
        "historical_package_mutation_authorized": False,
        "canonical_metadata_mutation_authorized": False,
    }
    assert compiler.main(["--review"]) == 0
    assert compiler.main(["--check"]) == 0
    assert capsys.readouterr().err == ""
    assert compiler.ARTIFACT_PATH.is_file()
    assert compiler.SCHEMA_PATH.is_file()


def test_invalid_final_pin_precedes_every_compile_source_read(monkeypatch):
    def forbidden_read(*_args, **_kwargs):
        raise AssertionError("pending compilation attempted a source read")

    monkeypatch.setattr(compiler, "read_regular", forbidden_read)
    monkeypatch.setitem(compiler.EXPECTED_OUTPUT_HASHES, "mapping", "PENDING")
    with pytest.raises(compiler.MappingError, match="remain pending"):
        compiler.compile_mapping()


def test_source_and_output_allowlists_are_exact():
    assert set(compiler.EXPECTED_SOURCE_HASHES) == {
        compiler.SELECTOR_PATH,
        compiler.SELECTOR_SCHEMA_PATH,
        compiler.DESCRIPTOR_PATH,
        compiler.DESCRIPTOR_SCHEMA_PATH,
        compiler.ORACLES_PATH,
        compiler.ORACLES_SCHEMA_PATH,
        compiler.ACTIVATION_RECEIPT_PATH,
        compiler.ACTIVATION_RECEIPT_SCHEMA_PATH,
        compiler.BUNDLES_PATH,
        compiler.BUNDLES_SCHEMA_PATH,
        compiler.WORKLOADS_PATH,
        compiler.WORKLOADS_SCHEMA_PATH,
        compiler.PROTOCOL_PATH,
        compiler.PROTOCOL_SCHEMA_PATH,
        compiler.PROTOCOL_COMPILER_PATH,
        compiler.PROTOCOL_TESTS_PATH,
    }
    assert compiler.ALLOWED_OUTPUT_NAMES == {"mapping.json", "mapping.schema.json"}
    assert set(compiler.EXPECTED_OUTPUT_HASHES) == {"mapping", "schema"}
    assert compiler.SELECTOR_PATH == (
        f"{compiler.ACTIVATION_REBASE_DIR}/projected-selector.json"
    )
    assert compiler.DESCRIPTOR_PATH == (
        f"{compiler.ACTIVATION_REBASE_DIR}/projected-live-ready-descriptor.json"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.SELECTOR_PATH] == (
        "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.DESCRIPTOR_PATH] == (
        "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca"
    )


def test_every_historical_and_canonical_byte_is_immutable():
    before = {
        path: (compiler.REPO_ROOT / path).read_bytes()
        for path in compiler.IMMUTABLE_FILES
    }
    assert compiler.assert_immutable_files() == dict(
        sorted(compiler.IMMUTABLE_FILES.items())
    )
    after = {
        path: (compiler.REPO_ROOT / path).read_bytes()
        for path in compiler.IMMUTABLE_FILES
    }
    assert after == before


def test_immutable_rollback_lock_drift_is_rejected(monkeypatch):
    locks = dict(compiler.IMMUTABLE_FILES)
    path = next(iter(locks))
    locks[path] = "0" * 64
    monkeypatch.setattr(compiler, "IMMUTABLE_FILES", locks)
    with pytest.raises(compiler.MappingError, match="immutable predecessor drift"):
        compiler.assert_immutable_files()


def test_predecessor_equivalence_accepts_only_integrity_locator_rebase(artifact):
    compiler._assert_predecessor_equivalence(artifact)

    row_attack = copy.deepcopy(artifact)
    row_attack["mappings"][0]["mapping_state"] = "static_nonactivating"
    with pytest.raises(compiler.MappingError, match="semantics"):
        compiler._assert_predecessor_equivalence(row_attack)

    approval_attack = copy.deepcopy(artifact)
    approval_attack["policy"]["approvals_granted"] = 1
    with pytest.raises(compiler.MappingError, match="policy"):
        compiler._assert_predecessor_equivalence(approval_attack)


def test_all_211_mapping_semantics_are_exact_and_only_two_integrity_rows_rebase(
    artifact,
):
    predecessor = _load(
        compiler.REPO_ROOT
        / "deploy/docker/thor-local/qualification/"
        "candidate-approval-mapping-successor/mapping.json"
    )
    changed_ids = set()
    for old_row, new_row in zip(
        predecessor["mappings"], artifact["mappings"], strict=True
    ):
        old_semantics = dict(old_row)
        new_semantics = dict(new_row)
        changed_fields = set()
        for field in compiler.INTEGRITY_REBASE_FIELDS:
            if old_semantics.pop(field) != new_semantics.pop(field):
                changed_fields.add(field)
        assert new_semantics == old_semantics
        if changed_fields:
            assert changed_fields == set(compiler.INTEGRITY_REBASE_FIELDS)
            changed_ids.add(new_row["capability_id"])
    assert changed_ids == set(compiler.INTEGRITY_REBASE_IDS)


def test_activation_receipt_pair_provenance_attacks_are_rejected(sources):
    attacked = copy.deepcopy(sources)
    attacked[compiler.ACTIVATION_RECEIPT_PATH]["artifacts"][
        "projected-selector.json"
    ]["raw_sha256"] = "0" * 64
    with pytest.raises(
        compiler.MappingError, match="schema violation|pair provenance drift"
    ):
        compiler.compile_mapping(attacked)


def test_checked_artifact_equals_fresh_compilation(artifact):
    assert artifact == _load(compiler.ARTIFACT_PATH)
    assert compiler.check_artifact() == artifact


def test_exact_denominator_states_and_direct_leaves(artifact):
    assert len(artifact["mappings"]) == 211
    assert artifact["summary"]["state_counts"] == {
        "mapped": 206,
        "static_nonactivating": 3,
        "unmapped_contract_conflict": 1,
        "unmapped_scope_gap": 1,
    }
    assert artifact["summary"]["direct_leaf_counts"] == {
        "host-prerequisite-evidence-collection": 0,
        "read-only-docker-runtime-inspection": 0,
        "cgroupfs-remediation": 0,
        "tiny-audio-fixture-generation": 0,
        "model-artifact-downloads": 0,
        "profile-lifecycle": 184,
        "search-scale-progressive-2-4-8-16": 1,
        "search-scale-100": 1,
        "mv3dt-custom-data": 9,
        "sparse4d-custom-data-models": 2,
        "audio-native-runtime": 3,
        "audio-asr-transcript-runtime": 2,
        "official-edge-staging": 0,
        "external-attestations": 4,
    }


def test_exact_candidate_order_and_mapping_payload_identity(artifact):
    rows = artifact["mappings"]
    assert [item["oracle_index"] for item in rows] == list(range(289, 500))
    ids = [item["capability_id"] for item in rows]
    assert len(set(ids)) == 211
    assert (
        compiler.sha256(compiler.canonical_bytes(ids))
        == compiler.EXPECTED_CANDIDATE_ORDER_SHA256
    )
    assert (
        compiler.sha256(compiler.canonical_bytes(rows))
        == artifact["mapping_records_canonical_sha256"]
    )


def test_exact_static_and_unmapped_cases(artifact):
    by_id = {item["capability_id"]: item for item in artifact["mappings"]}
    assert {
        capability_id
        for capability_id, item in by_id.items()
        if item["mapping_state"] == "static_nonactivating"
    } == compiler.STATIC_NONACTIVATING_IDS
    conflict = by_id[compiler.CONTRACT_CONFLICT_ID]
    assert conflict["mapping_state"] == "unmapped_contract_conflict"
    assert conflict["leaf_bundle_id"] is None
    assert conflict["suggested_bundle_id"] == "sparse4d-custom-data-models"
    gap = by_id[compiler.SCOPE_GAP_ID]
    assert gap["mapping_state"] == "unmapped_scope_gap"
    assert gap["leaf_bundle_id"] is None
    assert gap["suggested_bundle_id"] is None


def test_specialized_leaf_sets_are_exact(artifact):
    by_leaf: dict[str | None, set[str]] = {}
    for item in artifact["mappings"]:
        by_leaf.setdefault(item["leaf_bundle_id"], set()).add(item["capability_id"])
    assert by_leaf["audio-native-runtime"] == compiler.NATIVE_AUDIO_IDS
    assert by_leaf["audio-asr-transcript-runtime"] == compiler.ASR_IDS
    assert by_leaf["search-scale-100"] == {compiler.SEARCH_100_ID}
    assert by_leaf["search-scale-progressive-2-4-8-16"] == {
        compiler.SEARCH_PROGRESSIVE_ID
    }
    assert by_leaf["sparse4d-custom-data-models"] == {
        "manifest-entry.rt-cv-3d-sparse4d.00-sparse4d-multi-camera-3d-detection-and-tracking",
        "manifest-entry.rt-cv-3d-sparse4d.01-shared-rt-cv-lifecycle-health-metrics",
    }
    assert len(by_leaf["mv3dt-custom-data"]) == 9


def test_binding_denominators_and_hashes_are_exact(artifact):
    assert artifact["summary"]["binding_counts"] == {
        "workload": 60,
        "protocol": 23,
        "none": 128,
    }
    for item in artifact["mappings"]:
        if item["binding_kind"] == "workload":
            assert item["workload_binding_canonical_sha256"] is not None
            assert item["protocol_binding_canonical_sha256"] is None
        elif item["binding_kind"] == "protocol":
            assert item["workload_binding_canonical_sha256"] is None
            assert item["protocol_binding_canonical_sha256"] is not None
        else:
            assert item["workload_binding_canonical_sha256"] is None
            assert item["protocol_binding_canonical_sha256"] is None


def test_dependency_closure_is_unresolved_classification_only(artifact):
    assert artifact["policy"]["dependency_disposition"] == (
        "unresolved_until_separate_receipt_or_reviewed_not_required_determination"
    )
    assert artifact["summary"]["dependency_closure_link_counts"] == {
        "host-prerequisite-evidence-collection": 202,
        "read-only-docker-runtime-inspection": 202,
        "cgroupfs-remediation": 202,
        "tiny-audio-fixture-generation": 5,
        "model-artifact-downloads": 202,
        "profile-lifecycle": 202,
        "search-scale-progressive-2-4-8-16": 2,
        "search-scale-100": 1,
        "mv3dt-custom-data": 9,
        "sparse4d-custom-data-models": 2,
        "audio-native-runtime": 3,
        "audio-asr-transcript-runtime": 2,
        "official-edge-staging": 0,
        "external-attestations": 4,
    }
    for item in artifact["mappings"]:
        if item["mapping_state"] == "mapped":
            assert item["leaf_bundle_id"] in item["dependency_closure"]
        else:
            assert item["dependency_closure"] == []
    by_id = {item["capability_id"]: item for item in artifact["mappings"]}
    assert (
        "search-scale-progressive-2-4-8-16"
        in by_id[compiler.SEARCH_100_ID]["dependency_closure"]
    )


def test_zero_receipt_admission_and_execution_are_unconditional(artifact):
    policy = artifact["policy"]
    assert policy["receipt_consumer_present"] is False
    assert policy["receipts_present"] == 0
    assert policy["approvals_granted"] == 0
    assert policy["admitted_candidates"] == 0
    assert policy["executable_candidates"] == 0
    assert policy["commands_invented"] == 0
    assert policy["action_flag_vectors_invented"] == 0
    assert policy["service_roles_invented"] == 0
    assert policy["profile_ids_invented"] == 0
    assert policy["compose_paths_invented"] == 0
    for item in artifact["mappings"]:
        assert item["approval_state"] == "no_receipt_not_admitted_not_executable"
        assert item["service_binding_state"] == ("unresolved_not_declared_by_candidate")
        assert not any(
            forbidden in item
            for forbidden in {
                "authorized_command",
                "action_flags",
                "service_roles",
                "profile_ids",
                "compose_paths",
                "receipts",
            }
        )


def test_external_local_audio_and_warehouse_boundaries(artifact):
    for item in artifact["mappings"]:
        if item["leaf_bundle_id"] == "external-attestations":
            assert item["execution_boundary"] == "external"
        if (
            item["execution_boundary"] == "external"
            and item["mapping_state"] == "mapped"
        ):
            assert item["leaf_bundle_id"] == "external-attestations"
        assert item["required_cloud_inference"] is False
        assert item["warehouse_sample_bundle"] is False
    assert compiler.NATIVE_AUDIO_IDS.isdisjoint(compiler.ASR_IDS)


def test_schema_rejects_forged_admission_commands_roles_and_inheritance(artifact):
    schema = _load(compiler.SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    forged = copy.deepcopy(artifact)
    forged["policy"]["admitted_candidates"] = 1
    assert list(validator.iter_errors(forged))
    forged = copy.deepcopy(artifact)
    forged["mappings"][0]["authorized_command"] = "docker compose up"
    assert list(validator.iter_errors(forged))
    forged = copy.deepcopy(artifact)
    forged["mappings"][0]["service_roles"] = ["agent"]
    assert list(validator.iter_errors(forged))
    forged = copy.deepcopy(artifact)
    forged["policy"]["approval_inheritance"] = True
    assert list(validator.iter_errors(forged))


def test_reordered_deleted_or_promoted_candidate_is_rejected(sources):
    reordered = copy.deepcopy(sources)
    rows = reordered[compiler.ORACLES_PATH]["oracles"]
    rows[289], rows[290] = rows[290], rows[289]
    with pytest.raises(compiler.MappingError, match="candidate order"):
        compiler.compile_mapping(reordered)
    deleted = copy.deepcopy(sources)
    deleted[compiler.ORACLES_PATH]["oracles"].pop()
    with pytest.raises(
        compiler.MappingError,
        match="schema violation|denominator",
    ):
        compiler.compile_mapping(deleted)
    promoted = copy.deepcopy(sources)
    promoted[compiler.ORACLES_PATH]["oracles"][289]["runtime_state"] = "qualified"
    with pytest.raises(
        compiler.MappingError,
        match="schema violation|candidate order",
    ):
        compiler.compile_mapping(promoted)


def test_workload_protocol_and_bundle_policy_drift_are_rejected(sources):
    workload = copy.deepcopy(sources)
    workload[compiler.WORKLOADS_PATH]["workloads"][0]["max_actions"] += 1
    with pytest.raises(compiler.MappingError, match="workload binding drift"):
        compiler.compile_mapping(workload)
    protocol = copy.deepcopy(sources)
    candidate = next(
        item
        for item in protocol[compiler.PROTOCOL_PATH]["bindings"]
        if item["capability_id"].startswith("manifest-entry.")
    )
    candidate["boundary"] = "external"
    with pytest.raises(compiler.MappingError, match="protocol binding drift"):
        compiler.compile_mapping(protocol)
    inheritance = copy.deepcopy(sources)
    inheritance[compiler.BUNDLES_PATH]["approval_policy"]["approval_inheritance"] = True
    with pytest.raises(
        compiler.MappingError,
        match="schema violation|bundle identity or isolation",
    ):
        compiler.compile_mapping(inheritance)


def test_conflict_cannot_be_silently_mapped(artifact):
    forged = copy.deepcopy(artifact)
    item = next(
        row
        for row in forged["mappings"]
        if row["capability_id"] == compiler.CONTRACT_CONFLICT_ID
    )
    item["mapping_state"] = "mapped"
    item["leaf_bundle_id"] = "sparse4d-custom-data-models"
    item["suggested_bundle_id"] = None
    item["dependency_closure"] = ["sparse4d-custom-data-models"]
    schema = _load(compiler.SCHEMA_PATH)
    # The general schema describes safe shapes; deterministic equality and the
    # exact compiler rule provide the stronger semantic anti-forgery check.
    assert list(Draft202012Validator(schema).iter_errors(forged)) == []
    assert forged != compiler.compile_mapping()


def test_compiler_has_no_runtime_network_docker_or_subprocess_surface():
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
        }
    )
    assert "--execute" not in source


def test_output_hashes_are_exactly_pinned_and_checked(artifact):
    outputs = compiler._output_payloads(artifact)
    compiler._validate_output_pins(outputs)
    assert compiler.sha256(outputs[compiler.ARTIFACT_PATH]) == (
        "dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a"
    )
    assert compiler.sha256(outputs[compiler.SCHEMA_PATH]) == (
        "41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5"
    )


def test_wrong_pin_rejects_write_before_transaction(monkeypatch):
    called = False

    def unexpected_write(_outputs):
        nonlocal called
        called = True

    monkeypatch.setattr(compiler, "_transactional_write", unexpected_write)
    monkeypatch.setitem(compiler.EXPECTED_OUTPUT_HASHES, "mapping", "0" * 64)
    assert compiler.main(["--write"]) == 2
    assert called is False


def test_transactional_writer_rolls_back_both_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "HERE", tmp_path)
    outputs = {
        tmp_path / "mapping.json": b"new mapping\n",
        tmp_path / "mapping.schema.json": b"new schema\n",
    }
    before = {
        tmp_path / "mapping.json": b"old mapping\n",
        tmp_path / "mapping.schema.json": b"old schema\n",
    }
    for path, payload in before.items():
        path.write_bytes(payload)
    real_replace = compiler.os.replace
    commits = 0

    def fail_second_commit(source, target):
        nonlocal commits
        if ".stage." in Path(source).name:
            commits += 1
            if commits == 2:
                raise OSError("injected failure")
        return real_replace(source, target)

    monkeypatch.setattr(compiler.os, "replace", fail_second_commit)
    with pytest.raises(compiler.MappingError, match="prior state restored"):
        compiler._transactional_write(outputs)
    assert {path: path.read_bytes() for path in before} == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_output_preflight_rejects_historical_and_canonical_paths():
    for relative in (
        "deploy/docker/thor-local/qualification/"
        "candidate-approval-mapping-successor/mapping.json",
        compiler.HISTORICAL_SELECTOR_PATH,
        compiler.HISTORICAL_DESCRIPTOR_PATH,
    ):
        with pytest.raises(compiler.MappingError, match="non-allowlisted"):
            compiler._preflight_output(compiler.repo_path(relative))


def test_duplicate_json_and_unsafe_or_symlinked_path_are_rejected(
    tmp_path, monkeypatch
):
    with pytest.raises(compiler.MappingError, match="duplicate JSON key"):
        compiler.strict_json_bytes(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.MappingError, match="unsafe repository path"):
        compiler.repo_path("../outside")
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.json").write_text("{}", encoding="utf-8")
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(compiler, "REPO_ROOT", tmp_path)
    with pytest.raises(compiler.MappingError, match="contains a symlink"):
        compiler.repo_path("linked/source.json")
