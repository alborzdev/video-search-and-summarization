from __future__ import annotations

import ast
from copy import deepcopy
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
        "sparse4d_entry_oracle_test", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()
SHA_A = "a" * 64
SHA_B = "b" * 64


def artifact(name: str, service: str = "vss-rtvi-cv") -> dict:
    return {
        "artifact_id": name,
        "sha256": SHA_A,
        "captured_at": "2026-08-01T12:00:00Z",
        "source_service": service,
    }


def model_pair(name: str, sha: str, prefix: str) -> dict:
    def event(kind: str, suffix: str, *, used: bool = False) -> dict:
        value = {
            "event": kind,
            "model_filename": name,
            "model_sha256": sha,
            "service": "vss-rtvi-cv",
            "capture": artifact(f"{prefix}-{suffix}"),
        }
        if used:
            value["inference_count"] = 4
            value["capture"]["captured_at"] = "2026-08-01T12:00:01Z"
        return value

    return {
        "model_filename": name,
        "model_sha256": sha,
        "loaded": event("model_loaded", "loaded"),
        "used": event("inference_used", "used", used=True),
    }


def valid_receipt() -> dict:
    observations = [
        {
            "camera_id": camera,
            "topic": "mdx-raw",
            "detections": [
                {
                    "track_id": f"local{index}",
                    "class_id": 0,
                    "confidence": 0.95,
                    "bbox": {"x": 1, "y": 2, "width": 10, "height": 20},
                }
            ],
            "capture": artifact(f"raw-{index}"),
        }
        for index, camera in enumerate(MODULE.CAMERAS)
    ]
    fused = []
    correlations = []
    for index, pair in enumerate((MODULE.CAMERAS[:2], MODULE.CAMERAS[2:])):
        fused.append(
            {
                "global_track_id": f"global{index}",
                "contributing_camera_ids": pair,
                "source_tracks": [
                    {
                        "camera_id": camera,
                        "track_id": f"local{MODULE.CAMERAS.index(camera)}",
                    }
                    for camera in pair
                ],
                "center_3d": {"x": index + 1, "y": 2, "z": 0},
                "dimensions_3d": {"length": 2, "width": 1, "height": 1},
                "yaw_radians": 0.1,
                "bev_position": {"x": index + 1, "y": 2, "z": 0},
                "capture": artifact(f"fused-{index}"),
            }
        )
        correlations.append(
            {
                "global_track_id": f"global{index}",
                "from_camera": pair[0],
                "to_camera": pair[1],
                "from_timestamp_ms": 1000,
                "to_timestamp_ms": 1010,
                "capture": artifact(f"correlation-{index}"),
            }
        )
    services = [
        {
            "service": service,
            "state": "running",
            "health": "healthy",
            "capture": artifact(f"health-{index}", "docker-inspect"),
        }
        for index, service in enumerate(sorted(MODULE.REQUIRED_SERVICES))
    ]
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
                {
                    "camera_id": camera,
                    "video_sha256": SHA_A,
                    "calibration_sensor_sha256": SHA_B,
                }
                for camera in MODULE.CAMERAS
            ],
            "calibration_sha256": SHA_A,
            "top_view_sha256": SHA_B,
            "custom_data_manifest_sha256": SHA_A,
            "rtdetr": {
                "filename": MODULE.RTDETR_MODEL,
                "sha256": SHA_A,
                "regular_non_symlink": True,
            },
            "sparse4d": {
                "filename": MODULE.SPARSE4D_MODEL,
                "sha256": SHA_B,
                "regular_non_symlink": True,
                "onnx_checked": True,
                "self_contained": True,
            },
            "anchor": {
                "filename": "_ov_kmeans900_v2.2.npy",
                "sha256": SHA_A,
                "regular_non_symlink": True,
                "shape": [900, 11],
                "dtype": "float32",
                "finite": True,
            },
            "validator": {
                "source_path": "deploy/docker/thor-local/validate-warehouse-sparse4d-input.py",
                "source_sha256": "ecbe1a4e43487a491547b8fd5b62fe542c19a2e90a6eb0c1d1108339b3cd02c3",
                "exit_code": 0,
                "streams": 4,
                "sensor_ids": list(MODULE.CAMERAS),
                "synchronized": True,
                "sparse4d_contract": "four synchronized cameras",
            },
            "prepare": {
                "lane_source_sha256": "c1174164a494263e62139e9507e15836b539b133cebae813ec99b5bbc5765f4c",
                "private_runtime_root": "/var/tmp/private-sparse4d-run",
                "asset_manifest_sha256": SHA_A,
                "deployment_snapshot_sha256": SHA_B,
                "copied_assets_revalidated": True,
            },
        },
        "preflight": {
            "passed": True,
            "profile": "minimal",
            "hardware": "AGX-THOR",
            "architecture": "aarch64",
            "memory_available_kib": 52428800,
            "disk_available_kib": 31457280,
            "gpu_conflicts": 0,
            "port_conflicts": 0,
            "missing_images": 0,
            "all_images_local_arm64": True,
            "capture": artifact("preflight", "thor-warehouse-sparse4d"),
        },
        "run": {
            "namespace": "sparse4d-run-1",
            "profile": "minimal",
            "started_at": "2026-08-01T11:59:00Z",
            "ended_at": "2026-08-01T12:01:00Z",
            "launcher_source_path": "deploy/docker/scripts/thor-warehouse-sparse4d.sh",
            "launcher_source_sha256": "c1174164a494263e62139e9507e15836b539b133cebae813ec99b5bbc5765f4c",
            "explicit_lifecycle_authorization_id": "approval-1",
        },
        "model_proof": {
            "rtdetr": model_pair(MODULE.RTDETR_MODEL, SHA_A, "rtdetr"),
            "sparse4d": model_pair(MODULE.SPARSE4D_MODEL, SHA_B, "sparse4d"),
            "anchor_sha256": SHA_A,
        },
        "oracle_evidence": [
            {
                "entry_id": "manifest-gap.rt-cv-3d-sparse4d.00-sparse4d-multi-camera-3d-detection-and-tracking",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-sparse4d.00",
                "candidate_observation": "observed_not_admitted",
                "per_camera_detections": observations,
                "topic": "mdx-bev",
                "fused_tracks": fused,
                "cross_camera_correlations": correlations,
                "cleanup_evidence_id": "cleanup-1",
            },
            {
                "entry_id": "manifest-gap.rt-cv-3d-sparse4d.01-shared-rt-cv-lifecycle-health-metrics",
                "oracle_id": "oracle.manifest-entry.rt-cv-3d-sparse4d.01",
                "candidate_observation": "observed_not_admitted",
                "services": services,
                "throughput": {
                    "fps": 20,
                    "sample_seconds": 10,
                    "frames_processed": 200,
                    "capture": artifact("throughput", "prometheus"),
                },
                "latency": {
                    "metric": "end_to_end_latency_ms",
                    "sample_count": 100,
                    "p50_ms": 10,
                    "p95_ms": 20,
                    "p99_ms": 30,
                    "capture": artifact("latency", "prometheus"),
                },
                "resources": {
                    "memory_peak_mib": 1024,
                    "gpu_peak_percent": 40,
                    "cpu_peak_percent": 80,
                    "disk_written_bytes": 1000,
                    "capture": artifact("resources", "docker-stats"),
                },
                "stream_growth": {
                    "mdx_bev_before": 0,
                    "mdx_bev_after": 10,
                    "mdx_behavior_after": 2,
                    "capture": artifact("stream-growth", "redis"),
                },
                "cleanup_evidence_id": "cleanup-1",
            },
        ],
        "cleanup": {
            "cleanup_evidence_id": "cleanup-1",
            "ownership_prefix": "sparse4d-run-1:",
            "created_resource_ids": [
                "sparse4d-run-1:stream-1",
                "sparse4d-run-1:output-1",
            ],
            "removed_resource_ids": [
                "sparse4d-run-1:output-1",
                "sparse4d-run-1:stream-1",
            ],
            "preexisting_resource_ids": ["operator-existing"],
            "preexisting_resources_unchanged": True,
            "broad_delete_used": False,
            "completed": True,
            "capture": artifact("cleanup", "operator-cleanup-recorder"),
        },
    }


def write_receipt(tmp_path: Path, receipt: dict) -> Path:
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_inert_plan_is_exact_sample_free_two_oracle_plan():
    result = MODULE.build_plan()
    assert len(result["source_checks"]) == 9
    assert len(result["oracle_plans"]) == 2
    assert result["current_blockers"] == MODULE.EXPECTED_BLOCKERS
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
    assert result["warehouse_sample_bundle"] == "excluded"


def test_schemas_raw_locks_and_live_oracles():
    instances = {
        "contract.schema.json": json.loads((HERE / "contract.json").read_text()),
        "plan.schema.json": MODULE.build_plan(),
        "evidence.schema.json": valid_receipt(),
    }
    for filename, instance in instances.items():
        schema = json.loads((HERE / filename).read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)
        assert (
            hashlib.sha256((HERE / filename).read_bytes()).hexdigest()
            == MODULE.EXPECTED_PACKAGE_HASHES[filename]
        )
    contract = MODULE._load_contract()
    assert all(item["sha256_match"] for item in MODULE._check_source_locks(contract))
    MODULE._verify_live_oracle_bindings(contract)


def test_valid_candidate_is_validated_but_never_admitted(tmp_path):
    result = MODULE.validate_evidence(write_receipt(tmp_path, valid_receipt()))
    assert result["validated"] is True
    assert result["candidate_status"] == "observed_not_admitted"
    assert result["live_ledger_mutation"] is False
    assert result["writes"] is False and result["subprocesses"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda r: r["admission"].update(input_root=str(MODULE.REPO_ROOT / "input")),
            "outside repository",
        ),
        (
            lambda r: r["admission"]["prepare"].update(
                private_runtime_root=r["admission"]["input_root"]
            ),
            "roots must differ",
        ),
        (lambda r: r["preflight"].update(profile="extended"), "profiles must match"),
        (
            lambda r: r["model_proof"]["rtdetr"].update(model_sha256=SHA_B),
            "hash differs",
        ),
        (lambda r: r["model_proof"].update(anchor_sha256=SHA_B), "anchor proof hash"),
        (
            lambda r: r["model_proof"]["sparse4d"]["used"].update(model_sha256=SHA_A),
            "load/use binding",
        ),
        (
            lambda r: r["model_proof"]["rtdetr"]["used"]["capture"].update(
                captured_at="2026-08-01T12:00:00Z"
            ),
            "must precede model-used",
        ),
        (
            lambda r: r["oracle_evidence"][0]["per_camera_detections"].reverse(),
            "exact ordered camera",
        ),
        (
            lambda r: r["oracle_evidence"][0]["fused_tracks"][0]["source_tracks"][
                0
            ].update(track_id="absent"),
            "absent from mdx-raw",
        ),
        (lambda r: r["oracle_evidence"][0]["fused_tracks"].pop(), "exact four cameras"),
        (
            lambda r: r["oracle_evidence"][0]["cross_camera_correlations"][0].update(
                to_camera="Camera"
            ),
            "cannot remain",
        ),
        (
            lambda r: r["oracle_evidence"][0]["cross_camera_correlations"][0].update(
                to_timestamp_ms=999
            ),
            "timestamps are reversed",
        ),
        (
            lambda r: r["oracle_evidence"][1]["services"][-1].update(
                service="optional-metrics-sidecar"
            ),
            "required Sparse4D lane",
        ),
        (
            lambda r: r["oracle_evidence"][1]["services"][0].update(health="none"),
            "every required Sparse4D lane service must be healthy",
        ),
        (
            lambda r: r["oracle_evidence"][1]["throughput"].update(
                frames_processed=150
            ),
            "exceed 5%/one-frame tolerance",
        ),
        (
            lambda r: r["oracle_evidence"][1]["latency"].update(p95_ms=9),
            "percentiles must be monotonic",
        ),
        (
            lambda r: r["oracle_evidence"][1]["stream_growth"].update(mdx_bev_after=0),
            "evidence schema violation",
        ),
        (
            lambda r: r["cleanup"].update(ownership_prefix="wrong:"),
            "namespace plus colon",
        ),
        (
            lambda r: r["cleanup"].update(
                removed_resource_ids=[
                    "sparse4d-run-1:output-1",
                    "sparse4d-run-1:stream-other",
                ]
            ),
            "exactly all created",
        ),
    ],
)
def test_cross_record_semantic_mutations_fail_closed(tmp_path, mutate, message):
    receipt = valid_receipt()
    mutate(receipt)
    with pytest.raises(MODULE.QualificationError, match=message):
        MODULE.validate_evidence(write_receipt(tmp_path, receipt))


def test_unknown_duplicate_nonfinite_path_symlink_and_drift_fail(tmp_path, monkeypatch):
    receipt = valid_receipt()
    receipt["unexpected"] = True
    with pytest.raises(MODULE.QualificationError, match="schema violation"):
        MODULE.validate_evidence(write_receipt(tmp_path, receipt))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(MODULE.QualificationError, match="duplicate JSON key"):
        MODULE._strict_json_path(duplicate, external=True)
    with pytest.raises(MODULE.QualificationError, match="non-finite"):
        MODULE._strict_json_bytes(b'{"value":NaN}', "nan")
    path = write_receipt(tmp_path, valid_receipt())
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(MODULE.QualificationError, match="non-symlink"):
        MODULE.validate_evidence(link)
    with pytest.raises(MODULE.QualificationError, match="outside repository"):
        MODULE.validate_evidence(HERE / "contract.json")
    with monkeypatch.context() as scoped:
        scoped.setitem(MODULE.EXPECTED_PACKAGE_HASHES, "contract.json", "0" * 64)
        with pytest.raises(MODULE.QualificationError, match="package identity drift"):
            MODULE.build_plan()


def test_oversized_sparse_receipt_is_rejected_before_unbounded_read(tmp_path):
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(MODULE.MAX_JSON_BYTES + 1)
    with pytest.raises(MODULE.QualificationError, match="exceeds bounded size"):
        MODULE.validate_evidence(oversized)


def test_each_source_lock_fails_closed(tmp_path, monkeypatch):
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


def test_executor_ast_has_no_action_or_write_facility():
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


def test_in_memory_numeric_semantics_reject_nonfinite():
    receipt = deepcopy(valid_receipt())
    receipt["oracle_evidence"][0]["fused_tracks"][0]["center_3d"]["x"] = math.inf
    with pytest.raises(MODULE.QualificationError, match="non-finite evidence"):
        MODULE._validate_evidence_semantics(receipt)
