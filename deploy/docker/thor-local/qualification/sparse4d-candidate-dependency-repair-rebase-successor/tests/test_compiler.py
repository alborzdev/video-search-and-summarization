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
    "sparse4d_candidate_dependency_repair_rebase_compiler", COMPILER_PATH
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources():
    return compiler._load_sources()[0]


@pytest.fixture(scope="module")
def artifact():
    return compiler.compile_repair()


def test_checked_artifact_is_exact_and_deterministic(artifact):
    assert compiler.check_artifact() == artifact
    assert artifact == _load(compiler.ARTIFACT_PATH)
    payload = copy.deepcopy(artifact)
    observed = payload.pop("repair_payload_sha256")
    assert observed == compiler.EXPECTED_ARTIFACT_PAYLOAD_SHA256
    assert compiler.sha256(compiler.canonical_bytes(payload)) == observed
    assert (
        compiler.sha256(compiler.ARTIFACT_PATH.read_bytes())
        == compiler.EXPECTED_ARTIFACT_RAW_SHA256
    )


def test_exact_one_field_repair_and_authoritative_dependency(artifact):
    repair = artifact["repair"]
    assert repair == {
        "capability_id": compiler.CANDIDATE_ID,
        "oracle_id": compiler.CANDIDATE_ORACLE_ID,
        "manifest_pointer": compiler.MANIFEST_POINTER,
        "advertised_literal": compiler.ADVERTISED,
        "field": "ledger_binding.contract.dependency_capability_ids",
        "before": [compiler.WRONG_DEPENDENCY_ID],
        "after": [compiler.CORRECT_DEPENDENCY_ID],
        "change_count": 1,
        "disposition": "replace_objectively_wrong_mv3dt_dependency_for_planning_classification",
        "candidate_capability_before_canonical_sha256": compiler.EXPECTED_RECORD_HASHES[
            "candidate_capability"
        ],
        "candidate_capability_after_canonical_sha256": compiler.EXPECTED_RECORD_HASHES[
            "corrected_candidate_capability"
        ],
        "candidate_oracle_record_canonical_sha256": compiler.EXPECTED_RECORD_HASHES[
            "candidate_oracle"
        ],
    }
    correct = artifact["semantic_proof"]["correct_dependency"]
    assert correct["capability_id"] == compiler.CORRECT_DEPENDENCY_ID
    assert correct["title"] == "Warehouse Sparse4D 3D pipeline"
    assert correct["perception"] == "Sparse4D"
    assert correct["source_topic"] == "mdx-bev"
    assert correct["synchronized_camera_timestamps"] is True


def test_mv3dt_is_objectively_rejected_and_service_identity_is_static(artifact):
    wrong = artifact["semantic_proof"]["wrong_dependency"]
    assert wrong["capability_id"] == compiler.WRONG_DEPENDENCY_ID
    assert wrong["title"] == "Warehouse RT-DETR plus MV3DT pipeline"
    assert wrong["detector"] == "RT-DETR"
    assert wrong["tracker"] == "MV3DT"
    assert "explicitly reject MV3DT behavior as proof" in wrong["objective_mismatch"]
    service = artifact["semantic_proof"]["static_service_identity"]
    assert service["binding_state"] == (
        "reviewed_static_identity_not_executable_service_binding"
    )
    assert service["source_compose_service"] == "perception-3d"
    assert service["extends_service"] == "perception"
    assert service["container_name"] == "vss-rtvi-cv"
    assert service["thor_profile"] == "bp_wh_redis_3d"
    assert service["mode"] == "3d"
    assert service["model_family"] == "sparse4d-warehouse"


def test_approval_is_scope_classification_only(artifact):
    approval = artifact["approval_classification"]
    assert approval["predecessor_state"] == "unmapped_contract_conflict"
    assert approval["leaf_bundle_id"] == "sparse4d-custom-data-models"
    assert approval["classification_state"] == "suggested_scope_only_not_approved"
    assert approval["approval_state"] == "no_receipt_not_admitted_not_executable"
    assert approval["dependency_disposition"] == (
        "unresolved_until_separate_exact_receipts"
    )


def test_runtime_metadata_and_warehouse_boundaries_are_unchanged(artifact):
    assert artifact["preservation"] == {
        "selected_metadata_files_modified": 0,
        "historical_package_files_modified": 0,
        "canonical_metadata_files_modified": 0,
        "candidate_runtime_state_before": "not_qualified",
        "candidate_runtime_state_after": "not_qualified",
        "candidate_evidence_records_before": 0,
        "candidate_evidence_records_after": 0,
        "candidate_executor_ready_before": False,
        "candidate_executor_ready_after": False,
        "operator_approval_gate_before": "unmet",
        "operator_approval_gate_after": "unmet",
        "runtime_receipts": 0,
        "runtime_qualification_claims": 0,
    }
    policy = artifact["policy"]
    assert policy["canonical_metadata_mutation"] is False
    assert policy["runtime_state_promotion"] is False
    assert policy["runtime_evidence_created"] == 0
    assert policy["receipt_consumer_present"] is False
    assert policy["approval_granted"] is False
    assert policy["executor_present"] is False
    assert policy["runtime_actions"] is False
    assert policy["warehouse_sample_bundle"] == "excluded"
    assert policy["required_cloud_inference"] is False
    assert policy["writer_scope"] == "package_repair_artifact_only"


def test_exact_source_lock_order_and_selected_set_binding(artifact):
    assert artifact["source_locks"] == [
        {"path": path, "raw_sha256": digest}
        for path, digest in compiler.EXPECTED_SOURCE_HASHES.items()
    ]
    assert artifact["selected_metadata_set"] == {
        "set_id": "thor-vss-3.2.1-metadata-500-staged",
        "selector_raw_sha256": compiler.EXPECTED_SOURCE_HASHES[compiler.SELECTOR_PATH],
        "descriptor_raw_sha256": compiler.EXPECTED_SOURCE_HASHES[
            compiler.DESCRIPTOR_PATH
        ],
        "candidate_oracle_index": 457,
    }


def test_exact_rebase_and_historical_provenance(artifact):
    assert artifact["rebase_provenance"] == {
        "mapping_raw_sha256": (
            "dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a"
        ),
        "mapping_schema_raw_sha256": (
            "41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5"
        ),
        "activation_receipt_raw_sha256": (
            "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e"
        ),
        "migration_receipt_raw_sha256": (
            "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c"
        ),
        "protocol_raw_sha256": (
            "cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7"
        ),
        "protocol_schema_raw_sha256": (
            "399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb"
        ),
    }
    historical = artifact["historical_predecessor"]
    assert historical["repair_raw_sha256"] == (
        "2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd"
    )
    assert historical["repair_payload_sha256"] == (
        "ef308921bd58ce44243692a46438d365cc4998cb733b877684d6bf1944deb84b"
    )
    assert historical["repair_git_blob_oid"] == (
        "388d4059c74d6eace59e63151e5c08a89a6ff7c2"
    )
    assert historical["semantic_record_hashes_preserved"] is True
    assert historical["immutable_locks"] == [
        {"path": path, "raw_sha256": digest}
        for path, digest in compiler.IMMUTABLE_HISTORICAL_HASHES.items()
    ]


def test_wrong_dependency_or_candidate_identity_drift_fails_closed(sources):
    changed = copy.deepcopy(sources)
    candidate = changed[compiler.LEDGER_PATH]["capabilities"][457]
    candidate["contract"]["dependency_capability_ids"] = [
        compiler.CORRECT_DEPENDENCY_ID
    ]
    with pytest.raises(compiler.RepairError, match="candidate_capability record drift"):
        compiler.compile_repair(changed)

    changed = copy.deepcopy(sources)
    changed[compiler.ORACLES_PATH]["oracles"][457]["advertised"] = "Sparse4D"
    with pytest.raises(compiler.RepairError, match="candidate_oracle record drift"):
        compiler.compile_repair(changed)


def test_authoritative_sparse4d_and_mv3dt_semantic_drift_fails_closed(sources):
    changed = copy.deepcopy(sources)
    changed[compiler.LEDGER_PATH]["capabilities"][267]["contract"]["perception"] = (
        "MV3DT"
    )
    with pytest.raises(compiler.RepairError, match="correct_capability record drift"):
        compiler.compile_repair(changed)

    changed = copy.deepcopy(sources)
    changed[compiler.LEDGER_PATH]["capabilities"][268]["contract"]["tracker"] = (
        "Sparse4D"
    )
    with pytest.raises(compiler.RepairError, match="wrong_capability record drift"):
        compiler.compile_repair(changed)


def test_compose_launcher_and_custom_data_contract_drift_fail_closed(sources):
    changed = copy.deepcopy(sources)
    changed[compiler.SOURCE_COMPOSE_PATH] = changed[
        compiler.SOURCE_COMPOSE_PATH
    ].replace("DS_MODEL_FAMILY: sparse4d-warehouse", "DS_MODEL_FAMILY: mv3dt")
    with pytest.raises(compiler.RepairError, match="source Compose"):
        compiler.compile_repair(changed)

    changed = copy.deepcopy(sources)
    changed[compiler.THOR_LAUNCHER_PATH] = changed[compiler.THOR_LAUNCHER_PATH].replace(
        "MODE=3d BP_PROFILE=bp_wh_redis", "MODE=mv3dt BP_PROFILE=bp_wh_redis"
    )
    with pytest.raises(compiler.RepairError, match="Thor Sparse4D launcher"):
        compiler.compile_repair(changed)

    changed = copy.deepcopy(sources)
    changed[compiler.SPARSE_CONTRACT_PATH]["admission"]["camera_count"] = 3
    with pytest.raises(
        compiler.RepairError, match="schema violation|admission boundary"
    ):
        compiler.compile_repair(changed)


def test_predecessor_conflict_and_approval_leaf_drift_fail_closed(sources):
    changed = copy.deepcopy(sources)
    row = next(
        item
        for item in changed[compiler.PREDECESSOR_MAPPING_PATH]["mappings"]
        if item["capability_id"] == compiler.CANDIDATE_ID
    )
    row["suggested_bundle_id"] = "mv3dt-custom-data"
    with pytest.raises(
        compiler.RepairError,
        match=(
            "mapping rebase schema violation|predecessor mapping schema violation|"
            "predecessor approval-mapping"
        ),
    ):
        compiler.compile_repair(changed)

    changed = copy.deepcopy(sources)
    bundle = next(
        item
        for item in changed[compiler.BUNDLES_PATH]["bundles"]
        if item["id"] == compiler.APPROVAL_LEAF_ID
    )
    bundle["depends_on"] = ["profile-lifecycle"]
    with pytest.raises(compiler.RepairError, match="approval leaf"):
        compiler.compile_repair(changed)


def test_schema_rejects_forged_promotion_approval_action_and_extra_field(artifact):
    validator = Draft202012Validator(_load(compiler.SCHEMA_PATH))
    for mutation in (
        lambda value: value["policy"].update(runtime_state_promotion=True),
        lambda value: value["policy"].update(approval_granted=True),
        lambda value: value["policy"].update(runtime_actions=True),
        lambda value: value["repair"].update(after=[compiler.WRONG_DEPENDENCY_ID]),
        lambda value: value.update(authorized_command="docker compose up"),
    ):
        forged = copy.deepcopy(artifact)
        mutation(forged)
        assert list(validator.iter_errors(forged))


def test_compiler_has_no_external_action_surface_and_only_fixed_writer():
    source = COMPILER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint({"subprocess", "socket", "requests", "urllib", "docker"})
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({"open", "exec", "eval", "compile"})
    assert "--write" in source
    assert "os.replace(temporary_path, ARTIFACT_PATH)" in source
    assert "subprocess" not in called_names


def test_check_is_read_only(capsys):
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in compiler.HERE.iterdir()
        if path.is_file()
    }
    assert compiler.main(["--check"]) == 0
    capsys.readouterr()
    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in compiler.HERE.iterdir()
        if path.is_file()
    }
    assert after == before


def test_writer_is_atomic_package_local_and_rejects_symlink(
    artifact, tmp_path, monkeypatch
):
    output = tmp_path / "repair.json"
    monkeypatch.setattr(compiler, "HERE", tmp_path)
    monkeypatch.setattr(compiler, "ARTIFACT_PATH", output)
    compiler.write_artifact(artifact)
    assert output.read_bytes() == compiler.encoded_artifact(artifact)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["repair.json"]
    output.unlink()
    output.symlink_to(tmp_path / "outside.json")
    with pytest.raises(compiler.RepairError, match="regular non-symlink"):
        compiler.write_artifact(artifact)
