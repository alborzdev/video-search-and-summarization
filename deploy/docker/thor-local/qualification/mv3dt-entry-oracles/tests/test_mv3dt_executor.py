from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker
import pytest

HERE = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "mv3dt_entry_oracle_test", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()
SHA = "a" * 64


def artifact(name: str, service: str = "vss-rtvi-cv-mv3dt") -> dict:
    return {
        "artifact_id": name,
        "sha256": SHA,
        "captured_at": "2026-08-01T12:00:00Z",
        "source_service": service,
    }


def valid_receipt() -> dict:
    observations = []
    for index, camera in enumerate(MODULE.CAMERAS):
        observations.append(
            {
                "camera_id": camera,
                "topic": "mdx-raw",
                "frame_timestamp_ms": 1000,
                "detections": [
                    {
                        "track_id": f"local{index}",
                        "class_id": 0,
                        "confidence": 0.9,
                        "bbox": {"x": 1, "y": 2, "width": 10, "height": 20},
                    }
                ],
                "capture": artifact(f"raw{index}"),
            }
        )
    return {
        "schema_version": 1,
        "purpose": "candidate_runtime_evidence_for_review_only",
        "candidate_status": "observed_not_admitted",
        "live_ledger_mutation": False,
        "admission": {
            "dataset_slug": "operator-four-cam",
            "input_root": "/var/tmp/operator-four-cam",
            "warehouse_sample_bundle": False,
            "camera_count": 4,
            "camera_ids": list(MODULE.CAMERAS),
            "cameras": [
                {"camera_id": camera, "video_sha256": SHA, "cam_info_sha256": SHA}
                for camera in MODULE.CAMERAS
            ],
            "custom_data_manifest_sha256": SHA,
            "calibration_sha256": SHA,
            "topology_sha256": SHA,
            "detector_asset_sha256": SHA,
            "bodypose_asset_sha256": SHA,
            "validator": {
                "source_path": "deploy/docker/thor-local/validate-warehouse-mv3dt-input.py",
                "source_sha256": "09c3497f8cd7302d871cf528c09467273ac6a3717535f772e05d0eb2e63d6aff",
                "exit_code": 0,
                "streams": 4,
                "sensor_ids": list(MODULE.CAMERAS),
                "sync_validated": True,
            },
            "topology": {
                "camera_ids": list(MODULE.CAMERAS),
                "self_subscriptions": 0,
                "neighbor_edges": 4,
                "neighbor_pairs": [
                    {"from_camera": "Camera", "to_camera": "Camera_01"},
                    {"from_camera": "Camera_01", "to_camera": "Camera_02"},
                    {"from_camera": "Camera_02", "to_camera": "Camera_03"},
                    {"from_camera": "Camera_03", "to_camera": "Camera"},
                ],
                "generator_source_sha256": "bc64ddf385f717793d6683eb4b57989067462c6a0f638ee46e9d7243285288fc",
            },
        },
        "run": {
            "namespace": "mv3dt-run-1",
            "profile": "minimal",
            "started_at": "2026-08-01T11:59:00Z",
            "ended_at": "2026-08-01T12:01:00Z",
            "launcher_source_path": "deploy/docker/scripts/thor-warehouse-mv3dt.sh",
            "launcher_source_sha256": "e697a2a41a146bc84b701558918af1f24d10ba10cd4ffc05d9fd3d9818080499",
            "explicit_lifecycle_authorization_id": "approval-1",
        },
        "oracle_evidence": [
            {
                "entry_id": "manifest-gap.rt-cv-3d-mv3dt.00-per-camera-rt-detr",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-mv3dt.00",
                "candidate_observation": "observed_not_admitted",
                "camera_observations": observations,
                "cleanup_evidence_id": "cleanup-1",
            },
            {
                "entry_id": "manifest-gap.rt-cv-3d-mv3dt.01-mv3dt-bev-fusion",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-mv3dt.01",
                "candidate_observation": "observed_not_admitted",
                "topic": "mdx-bev",
                "fused_tracks": [
                    {
                        "global_track_id": "global1",
                        "contributing_camera_ids": ["Camera", "Camera_01"],
                        "source_tracks": [
                            {"camera_id": "Camera", "track_id": "local0"},
                            {"camera_id": "Camera_01", "track_id": "local1"},
                        ],
                        "world_position": {"x": 1, "y": 2, "z": 0},
                        "capture": artifact("bev1", "vss-rtvi-cv-bev-fusion"),
                    },
                    {
                        "global_track_id": "global2",
                        "contributing_camera_ids": ["Camera_02", "Camera_03"],
                        "source_tracks": [
                            {"camera_id": "Camera_02", "track_id": "local2"},
                            {"camera_id": "Camera_03", "track_id": "local3"},
                        ],
                        "world_position": {"x": 3, "y": 4, "z": 0},
                        "capture": artifact("bev2", "vss-rtvi-cv-bev-fusion"),
                    },
                ],
                "cleanup_evidence_id": "cleanup-1",
            },
            {
                "entry_id": "manifest-gap.rt-cv-3d-mv3dt.02-bodypose3dnet",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-mv3dt.02",
                "candidate_observation": "observed_not_admitted",
                "model_asset_sha256": SHA,
                "loaded": {
                    "event": "model_loaded",
                    "model_filename": "bodypose3dnet_accuracy.onnx",
                    "service": "vss-rtvi-cv-mv3dt",
                    "capture": artifact("body-loaded"),
                },
                "used": {
                    "event": "inference_used",
                    "model_filename": "bodypose3dnet_accuracy.onnx",
                    "service": "vss-rtvi-cv-mv3dt",
                    "capture": {
                        **artifact("body-used"),
                        "captured_at": "2026-08-01T12:00:01Z",
                    },
                    "pose_count": 1,
                },
                "cleanup_evidence_id": "cleanup-1",
            },
            {
                "entry_id": "manifest-gap.rt-cv-3d-mv3dt.03-four-camera-calibrated-multiview-tracking",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-mv3dt.03",
                "candidate_observation": "observed_not_admitted",
                "transitions": [
                    {
                        "global_track_id": "global1",
                        "from_camera": "Camera",
                        "to_camera": "Camera_01",
                        "last_seen_from_ms": 1000,
                        "first_seen_to_ms": 1010,
                        "capture": artifact("transition1", "vss-rtvi-cv-bev-fusion"),
                    },
                    {
                        "global_track_id": "global2",
                        "from_camera": "Camera_02",
                        "to_camera": "Camera_03",
                        "last_seen_from_ms": 1000,
                        "first_seen_to_ms": 1010,
                        "capture": artifact("transition2", "vss-rtvi-cv-bev-fusion"),
                    },
                ],
                "cleanup_evidence_id": "cleanup-1",
            },
        ],
        "cleanup": {
            "cleanup_evidence_id": "cleanup-1",
            "ownership_prefix": "mv3dt-run-1:",
            "created_resource_ids": ["mv3dt-run-1:stream-1", "mv3dt-run-1:output-1"],
            "removed_resource_ids": ["mv3dt-run-1:output-1", "mv3dt-run-1:stream-1"],
            "preexisting_resource_ids": ["operator-existing"],
            "preexisting_resources_unchanged": True,
            "broad_delete_used": False,
            "completed": True,
            "capture": artifact("cleanup", "operator-cleanup-recorder"),
        },
    }


def write_receipt(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "candidate-receipt.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_default_plan_is_exact_inert_four_oracle_plan(monkeypatch, capsys):
    monkeypatch.setattr(
        MODULE,
        "validate_evidence",
        lambda *_: pytest.fail("default invoked evidence validation"),
    )
    assert MODULE.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "inert_read_only_admission_plan"
    assert result["admission"]["camera_ids"] == MODULE.CAMERAS
    assert len(result["source_checks"]) == 9
    assert len(result["oracle_plans"]) == 4
    assert all(
        item["status"] == "open_unexecuted" and item["runtime_evidence"] == []
        for item in result["oracle_plans"]
    )
    assert all(
        result[key] is False
        for key in (
            "writes",
            "subprocesses",
            "docker",
            "network",
            "lifecycle",
            "model_load",
            "downloads",
        )
    )


def test_all_strict_schemas_and_raw_package_locks_validate():
    contract = json.loads((HERE / "contract.json").read_text())
    plan = MODULE.build_plan()
    receipt = valid_receipt()
    for filename, instance in (
        ("contract.schema.json", contract),
        ("plan.schema.json", plan),
        ("evidence.schema.json", receipt),
    ):
        schema = json.loads((HERE / filename).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)
        assert (
            hashlib.sha256((HERE / filename).read_bytes()).hexdigest()
            == MODULE.EXPECTED_PACKAGE_HASHES[filename]
        )
    assert (
        hashlib.sha256((HERE / "contract.json").read_bytes()).hexdigest()
        == MODULE.EXPECTED_PACKAGE_HASHES["contract.json"]
    )


def test_exact_existing_tool_locks_and_live_open_oracles():
    contract = MODULE._load_contract()
    checks = MODULE._check_source_locks(contract)
    assert {item["path"] for item in checks} == MODULE.EXPECTED_SOURCE_PATHS
    assert all(item["sha256_match"] for item in checks)
    MODULE._verify_live_oracle_bindings(contract)
    assert {item["entry_id"] for item in contract["advertised_oracles"]} == set(
        MODULE.EXPECTED_ORACLES
    )


def test_valid_external_candidate_receipt_is_validated_but_not_admitted(tmp_path):
    result = MODULE.validate_evidence(write_receipt(tmp_path, valid_receipt()))
    assert result["validated"] is True
    assert result["candidate_status"] == "observed_not_admitted"
    assert result["camera_ids"] == MODULE.CAMERAS
    assert result["artifact_count"] == 11
    assert result["live_ledger_mutation"] is False
    assert result["writes"] is False and result["subprocesses"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda r: r["admission"].update(dataset_slug=MODULE.SAMPLE_DATASET),
            "evidence schema violation",
        ),
        (
            lambda r: r["admission"].update(input_root=str(MODULE.REPO_ROOT / "data")),
            "outside repository",
        ),
        (
            lambda r: r["admission"]["topology"].update(
                neighbor_pairs=[
                    {"from_camera": "Camera", "to_camera": "Camera_01"},
                    {"from_camera": "Camera_01", "to_camera": "Camera"},
                    {"from_camera": "Camera_02", "to_camera": "Camera_03"},
                    {"from_camera": "Camera_03", "to_camera": "Camera_02"},
                ]
            ),
            "topology must be connected",
        ),
        (
            lambda r: r["oracle_evidence"][0]["camera_observations"][0].update(
                detections=[]
            ),
            "evidence schema violation",
        ),
        (
            lambda r: r["oracle_evidence"][0]["camera_observations"][0][
                "capture"
            ].update(source_service="wrong-service"),
            "perception service",
        ),
        (
            lambda r: r["oracle_evidence"][1]["fused_tracks"][0]["source_tracks"][
                0
            ].update(track_id="absent"),
            "absent from mdx-raw",
        ),
        (lambda r: r["oracle_evidence"][1]["fused_tracks"].pop(), "exact four cameras"),
        (
            lambda r: r["oracle_evidence"][2].update(model_asset_sha256="b" * 64),
            "not bound to admitted",
        ),
        (
            lambda r: r["oracle_evidence"][2]["loaded"]["capture"].update(
                captured_at="2026-08-01T13:00:00Z"
            ),
            "within the admitted run window",
        ),
        (
            lambda r: r["oracle_evidence"][2]["used"].update(
                capture=r["oracle_evidence"][2]["loaded"]["capture"]
            ),
            "globally unique",
        ),
        (
            lambda r: r["oracle_evidence"][2]["used"]["capture"].update(
                captured_at="2026-08-01T12:00:00Z"
            ),
            "must precede model-used",
        ),
        (
            lambda r: r["oracle_evidence"][3]["transitions"][0].update(
                first_seen_to_ms=999
            ),
            "timestamps are reversed",
        ),
        (
            lambda r: r["oracle_evidence"][3]["transitions"][0].update(
                to_camera="Camera"
            ),
            "cannot remain",
        ),
        (
            lambda r: r["oracle_evidence"][3]["transitions"][0].update(
                global_track_id="absent"
            ),
            "absent from mdx-bev",
        ),
        (
            lambda r: r["oracle_evidence"][3]["transitions"][0].update(
                from_camera="Camera_02", to_camera="Camera_03"
            ),
            "absent from the matching fused track",
        ),
        (
            lambda r: r["oracle_evidence"][3]["transitions"][0].update(
                from_camera="Camera_01", to_camera="Camera"
            ),
            "absent from admitted topology edges",
        ),
        (
            lambda r: r["cleanup"].update(ownership_prefix="wrong:"),
            "namespace plus colon",
        ),
        (lambda r: r["cleanup"]["removed_resource_ids"].pop(), "exactly all created"),
        (
            lambda r: (
                r["cleanup"]["created_resource_ids"].append("foreign-resource"),
                r["cleanup"]["removed_resource_ids"].append("foreign-resource"),
            ),
            "ownership prefix",
        ),
        (
            lambda r: r["cleanup"].update(
                created_resource_ids=["mv3dt-run-1:stream-1"],
                removed_resource_ids=["mv3dt-run-1:stream-1"],
            ),
            "stream and output",
        ),
    ],
)
def test_cross_record_semantic_mutations_fail_closed(tmp_path, mutate, message):
    receipt = valid_receipt()
    mutate(receipt)
    with pytest.raises(MODULE.QualificationError, match=message):
        MODULE.validate_evidence(write_receipt(tmp_path, receipt))


def test_unknown_fields_duplicate_json_nonfinite_and_schema_drift_fail_closed(
    tmp_path, monkeypatch
):
    receipt = valid_receipt()
    receipt["unexpected"] = True
    with pytest.raises(MODULE.QualificationError, match="evidence schema violation"):
        MODULE.validate_evidence(write_receipt(tmp_path, receipt))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(MODULE.QualificationError, match="duplicate JSON key"):
        MODULE._strict_json_path(duplicate, external=True)
    with pytest.raises(MODULE.QualificationError, match="non-finite"):
        MODULE._strict_json_bytes(b'{"value":NaN}', "nan")
    with monkeypatch.context() as scoped:
        scoped.setitem(MODULE.EXPECTED_PACKAGE_HASHES, "evidence.schema.json", "0" * 64)
        with pytest.raises(MODULE.QualificationError, match="package identity drift"):
            MODULE.build_plan()


def test_receipt_path_must_be_absolute_external_regular_and_not_symlink(tmp_path):
    path = write_receipt(tmp_path, valid_receipt())
    with pytest.raises(MODULE.QualificationError, match="must be absolute"):
        MODULE.validate_evidence(Path("relative.json"))
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(MODULE.QualificationError, match="non-symlink"):
        MODULE.validate_evidence(link)
    with pytest.raises(MODULE.QualificationError, match="outside repository"):
        MODULE.validate_evidence(HERE / "contract.json")


def test_oversized_sparse_receipt_is_rejected_before_unbounded_read(tmp_path):
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(MODULE.MAX_JSON_BYTES + 1)
    with pytest.raises(MODULE.QualificationError, match="exceeds bounded size"):
        MODULE.validate_evidence(oversized)


def test_each_source_lock_fails_closed_when_backing_bytes_drift(tmp_path, monkeypatch):
    contract = MODULE._load_contract()
    original = MODULE._repo_file
    bad = tmp_path / "bad-source"
    bad.write_text("drift", encoding="utf-8")
    for target in MODULE.EXPECTED_SOURCE_PATHS:
        with monkeypatch.context() as scoped:
            scoped.setattr(
                MODULE,
                "_repo_file",
                lambda relative, target=target: (
                    bad if relative == target else original(relative)
                ),
            )
            with pytest.raises(MODULE.QualificationError, match="source lock mismatch"):
                MODULE._check_source_locks(contract)


def test_executor_ast_has_no_subprocess_network_write_or_lifecycle_facility():
    tree = ast.parse((HERE / "executor.py").read_text())
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports.intersection(
        {
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "docker",
            "shutil",
            "tempfile",
        }
    )
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called.intersection({"open", "exec", "eval", "compile", "__import__"})
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "mkdir",
            "rmdir",
            "link",
            "symlink_to",
            "run",
            "Popen",
        }
    )


def test_numeric_semantics_reject_nonfinite_values_even_in_memory():
    receipt = valid_receipt()
    receipt["oracle_evidence"][1]["fused_tracks"][0]["world_position"]["x"] = math.inf
    with pytest.raises(MODULE.QualificationError, match="non-finite evidence"):
        MODULE._validate_evidence_semantics(receipt)
