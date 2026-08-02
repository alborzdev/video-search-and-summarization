#!/usr/bin/env python3
"""Produce target-bound, sample-free runtime evidence for SDG post-processing.

The default is an inert plan. ``--execute`` re-execs this file with the pinned
Thor SDG interpreter, creates one temporary tree, invokes only digest-locked
local tools, emits a receipt, and removes the tree before returning.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
SDG_ROOT = REPO_ROOT / "tools/sdg-postprocessing"
THOR_ENV = SDG_ROOT / "thor/.thor-env"
PINNED_PYTHON = THOR_ENV / "bin/python"
ACK = "I_ACKNOWLEDGE_OFFLINE_SDG_RUNTIME_EVIDENCE"
MAX_OUTPUT = 200_000
EXPECTED_CAPABILITIES = [
    "manifest-entry.synthetic-data-tools.00-semantic-label-helpers",
    "manifest-entry.synthetic-data-tools.01-dataset-checks",
    "manifest-entry.synthetic-data-tools.02-rgb-depth-video-conversion",
    "manifest-entry.synthetic-data-tools.03-ground-truth-conversion",
]


class EvidenceError(RuntimeError):
    """A source binding, tool execution, or semantic assertion failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def strict_json(path: Path) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise EvidenceError(f"duplicate key in {path}: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise EvidenceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_bindings(
    contract: dict[str, Any],
    *,
    require_clean: bool,
    oracle_document: Path | None = None,
    require_executor_ready: bool = False,
) -> dict[str, Any]:
    if (
        contract.get("package_id")
        != "thor-synthetic-data-runtime-evidence-successor-v1"
    ):
        raise EvidenceError("package identity drift")
    capabilities = contract.get("capabilities", [])
    if [row.get("capability_id") for row in capabilities] != EXPECTED_CAPABILITIES:
        raise EvidenceError("four-capability identity/order drift")
    for row in capabilities:
        if row.get("oracle_id") != f"oracle.{row['capability_id']}":
            raise EvidenceError(f"oracle identity drift: {row['capability_id']}")
        for lock in row["source_controls"]:
            path = REPO_ROOT / lock["path"]
            if (
                not path.is_file()
                or path.is_symlink()
                or sha_file(path) != lock["sha256"]
            ):
                raise EvidenceError(f"source lock mismatch: {lock['path']}")
        fixture_lock = row["fixture_manifest"]
        fixture_path = REPO_ROOT / fixture_lock["path"]
        if (
            not fixture_path.is_file()
            or fixture_path.is_symlink()
            or sha_file(fixture_path) != fixture_lock["sha256"]
        ):
            raise EvidenceError(
                f"fixture manifest lock mismatch: {row['capability_id']}"
            )
        fixture_manifest = strict_json(fixture_path)
        if (
            fixture_manifest.get("capability_id") != row["capability_id"]
            or fixture_manifest.get("fixture_id") != f"fixture.{row['capability_id']}"
            or fixture_manifest.get("generated_input_sha256")
            != row["generated_input_sha256"]
            or fixture_manifest.get("warehouse_sample_bundle") != "excluded"
        ):
            raise EvidenceError(
                f"fixture manifest semantics drift: {row['capability_id']}"
            )
    for section in ("selected_oracle_document", "selected_manifest_document"):
        lock = contract["target"][section]
        path = REPO_ROOT / lock["path"]
        if sha_file(path) != lock["sha256"]:
            raise EvidenceError(f"target document lock mismatch: {lock['path']}")

    selected = strict_json(
        REPO_ROOT / contract["target"]["selected_oracle_document"]["path"]
    )
    selected_by_id = {row["capability_id"]: row for row in selected["oracles"]}
    for row in capabilities:
        observed = sha_bytes(canonical_bytes(selected_by_id[row["capability_id"]]))
        if observed != row["selected_oracle_sha256"]:
            raise EvidenceError(f"selected oracle row drift: {row['capability_id']}")
    manifest = strict_json(
        REPO_ROOT / contract["target"]["selected_manifest_document"]["path"]
    )
    feature = next(
        row
        for row in manifest["features"]
        if row["id"] == contract["target"]["selected_manifest_document"]["feature_id"]
    )
    if (
        sha_bytes(canonical_bytes(feature))
        != contract["target"]["selected_manifest_document"]["feature_sha256"]
    ):
        raise EvidenceError("selected manifest feature drift")
    for lock_id in ("conda_lock", "pip_requirements", "wheel_lock"):
        lock = contract["environment"][lock_id]
        if sha_file(REPO_ROOT / lock["path"]) != lock["sha256"]:
            raise EvidenceError(f"environment source lock mismatch: {lock_id}")

    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=all")
    checkout_clean = status == ""
    if require_clean and not checkout_clean:
        raise EvidenceError("checkout is not fully clean; refusing promotable receipt")
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            contract["target"]["upstream_commit"],
            "HEAD",
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    if ancestor.returncode:
        raise EvidenceError("upstream target commit is not an ancestor of HEAD")
    if oracle_document is None:
        execution_oracle_path = (
            REPO_ROOT / contract["target"]["selected_oracle_document"]["path"]
        )
    else:
        execution_oracle_path = (
            oracle_document
            if oracle_document.is_absolute()
            else REPO_ROOT / oracle_document
        )
    try:
        execution_oracle_relative = str(
            execution_oracle_path.resolve(strict=True).relative_to(REPO_ROOT)
        )
    except (OSError, ValueError) as exc:
        raise EvidenceError(
            "execution oracle document must be a regular repository file"
        ) from exc
    if execution_oracle_path.is_symlink() or not execution_oracle_path.is_file():
        raise EvidenceError(
            "execution oracle document must be a non-symlink regular file"
        )
    execution_registry = strict_json(execution_oracle_path)
    execution_rows = {
        row["capability_id"]: row for row in execution_registry["oracles"]
    }
    executor_relative = str(Path(__file__).resolve().relative_to(REPO_ROOT))
    oracle_row_hashes: dict[str, str] = {}
    oracle_assertion_ids: dict[str, list[str]] = {}
    oracle_observation_ids: dict[str, list[str]] = {}
    oracle_fixture_sha256: dict[str, str | None] = {}
    executor_ready = True
    for capability_id in EXPECTED_CAPABILITIES:
        row = execution_rows.get(capability_id)
        if row is None or row.get("oracle_id") != f"oracle.{capability_id}":
            raise EvidenceError(
                f"execution oracle row missing or misbound: {capability_id}"
            )
        oracle_row_hashes[capability_id] = sha_bytes(canonical_bytes(row))
        oracle_assertion_ids[capability_id] = [item["id"] for item in row["assertions"]]
        oracle_observation_ids[capability_id] = [
            item["id"] for item in row["expected_observations"]
        ]
        materialization = row.get("fixture", {}).get("materialization", {})
        oracle_fixture_sha256[capability_id] = materialization.get("sha256")
        readiness = row.get("acceptance_readiness", {})
        row_ready = (
            row.get("execution_bounds", {}).get("executor") == executor_relative
            and executor_relative
            in row.get("execution_bounds", {}).get("collectors", [])
            and row.get("cleanup", {}).get("executor") == executor_relative
            and executor_relative
            in row.get("cleanup", {}).get("postcondition_collectors", [])
            and materialization.get("generator") == executor_relative
            and isinstance(materialization.get("path"), str)
            and bool(materialization.get("path"))
            and isinstance(materialization.get("sha256"), str)
            and len(materialization.get("sha256")) == 64
            and readiness.get("classification") == "executor_ready"
            and readiness.get("blockers") == []
        )
        executor_ready &= row_ready
    if require_executor_ready and not executor_ready:
        raise EvidenceError(
            "execution oracle rows are not exact executor-ready successor rows; "
            "current planning-only rows are lineage, not receipt authority"
        )
    return {
        "checkout_head": head,
        "checkout_tree": git("rev-parse", "HEAD^{tree}"),
        "upstream_commit": contract["target"]["upstream_commit"],
        "product_version": contract["target"]["product_version"],
        "selected_metadata_set": contract["target"]["selected_metadata_set"],
        "selected_oracle_document_sha256": contract["target"][
            "selected_oracle_document"
        ]["sha256"],
        "execution_oracle_document_path": execution_oracle_relative,
        "execution_oracle_document_sha256": sha_file(execution_oracle_path),
        "execution_oracle_row_sha256": oracle_row_hashes,
        "execution_oracle_assertion_ids": oracle_assertion_ids,
        "execution_oracle_observation_ids": oracle_observation_ids,
        "execution_oracle_fixture_sha256": oracle_fixture_sha256,
        "execution_oracles_executor_ready": executor_ready,
        "checkout_clean": checkout_clean,
        "contract_sha256": sha_file(CONTRACT_PATH),
        "executor_sha256": sha_file(Path(__file__)),
    }


class CommandRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict[str, Any]] = []
        self.env = os.environ.copy()
        for key in (
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "all_proxy",
            "FTP_PROXY",
            "ftp_proxy",
        ):
            self.env.pop(key, None)
        self.env.update(
            {
                "PATH": f"{THOR_ENV / 'bin'}:/usr/bin:/bin",
                "NO_PROXY": "*",
                "no_proxy": "*",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": str(root / "mpl-cache"),
            }
        )

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        expected: int | set[int] = 0,
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        allowed = expected if isinstance(expected, set) else {expected}
        result = subprocess.run(
            command,
            cwd=cwd or REPO_ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        self.calls.append(
            {
                "program": Path(command[0]).name,
                "argument_count": len(command) - 1,
                "returncode": result.returncode,
            }
        )
        if len(result.stdout) + len(result.stderr) > MAX_OUTPUT:
            raise EvidenceError("tool output exceeded bounded capture")
        if result.returncode not in allowed:
            raise EvidenceError(
                f"command failed ({result.returncode}): {command[:2]}\n{result.stderr[-2000:]}"
            )
        return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def artifact_hashes(paths: list[Path]) -> dict[str, str]:
    return {path.name: sha_file(path) for path in sorted(paths)}


def normalized_text_sha(path: Path, root: Path) -> str:
    return sha_bytes(
        path.read_text(encoding="utf-8").replace(str(root), "$RUN").encode()
    )


def tiny_detection_payload(*, overflow: bool = False) -> dict[str, Any]:
    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    extreme = 1.0e11 if overflow else 1.0
    return {
        "boxes": {
            "/World/CustomBox": {
                "label": {"class": "box"},
                "annotators": {
                    "bounding_box_2d_tight_fast": {
                        "x_min": 20,
                        "y_min": 20,
                        "x_max": 80,
                        "y_max": 80,
                        "semanticId": 1,
                        "occlusionRatio": 0.0,
                    },
                    "bounding_box_2d_loose_fast": {
                        "x_min": 18,
                        "y_min": 18,
                        "x_max": 82,
                        "y_max": 82,
                        "semanticId": 1,
                        "occlusionRatio": 0.0,
                    },
                    "bounding_box_3d_fast": {
                        "x_min": -extreme,
                        "x_max": extreme,
                        "y_min": -1.0,
                        "y_max": 1.0,
                        "z_min": 5.0,
                        "z_max": 7.0,
                        "transform": identity,
                        "semanticId": 1,
                        "occlusionRatio": 0.0,
                    },
                },
            }
        }
    }


def make_media_fixture(root: Path, *, frames: int = 8) -> dict[str, Any]:
    import cv2
    import numpy as np

    camera = root / "_World_Cameras_Camera"
    for name in (
        "rgb",
        "distance_to_image_plane",
        "distance_to_image_plane_png",
        "object_detection",
        "instance_id_segmentation_fast",
    ):
        (camera / name).mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = np.full((128, 128, 3), 40 + index * 10, dtype=np.uint8)
        cv2.putText(
            image,
            str(index),
            (30, 75),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
        )
        if not cv2.imwrite(str(camera / "rgb" / f"rgb_{index:05d}.jpg"), image):
            raise EvidenceError("failed to write generated RGB fixture")
        np.save(
            camera
            / "distance_to_image_plane"
            / f"distance_to_image_plane_{index:05d}.npy",
            np.full((16, 16), 1.25 + index / 100, dtype=np.float32),
        )
        if not cv2.imwrite(
            str(
                camera
                / "distance_to_image_plane_png"
                / f"distance_to_image_plane_{index:05d}.png"
            ),
            np.full((16, 16), 1250 + index * 10, dtype=np.uint16),
        ):
            raise EvidenceError("failed to write generated PNG fixture")
        write_json(
            camera / "object_detection" / f"object_detection_{index:05d}.json",
            tiny_detection_payload(),
        )
        write_json(
            camera
            / "instance_id_segmentation_fast"
            / f"instance_id_segmentation_mapping_{index:05d}.json",
            {"1": "/World/CustomBox"},
        )
        cv2.imwrite(
            str(
                camera
                / "instance_id_segmentation_fast"
                / f"instance_id_segmentation_{index:05d}.png"
            ),
            np.ones((16, 16), dtype=np.uint16),
        )
    return {"camera": camera, "frames": frames, "depth_mm_first": 1250}


def make_calibration_fixture(root: Path) -> tuple[Path, Path]:
    import cv2
    import numpy as np

    camera = root / "Camera"
    for name in ("rgb", "object_detection", "camera_params"):
        (camera / name).mkdir(parents=True, exist_ok=True)
    image = np.full((128, 128, 3), 96, dtype=np.uint8)
    cv2.imwrite(str(camera / "rgb/rgb_00000.jpg"), image)
    cv2.imwrite(str(root / "Camera.png"), image)
    cv2.imwrite(str(root / "Top.png"), image)
    write_json(
        camera / "object_detection/object_detection_00000.json",
        tiny_detection_payload(),
    )
    identity = np.eye(4, dtype=float).reshape(-1).tolist()
    write_json(
        camera / "camera_params/camera_params_00000.json",
        {
            "cameraViewTransform": identity,
            "cameraProjection": identity,
            "renderProductResolution": [128, 128],
        },
    )
    world = [
        (0, 0, 0),
        (1, 0, 0),
        (0, 1, 0),
        (1, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (0, 1, 1),
        (1, 1, 1),
    ]
    image_points = [
        {"x": 64 + 100 * x / (z + 5), "y": 64 + 100 * y / (z + 5)} for x, y, z in world
    ]
    sensor = {
        "id": "Camera",
        "intrinsicMatrix": [[100.0, 0.0, 64.0], [0.0, 100.0, 64.0], [0.0, 0.0, 1.0]],
        "extrinsicMatrix": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 5.0],
        ],
        "cameraMatrix": [
            [100.0, 0.0, 64.0, 320.0],
            [0.0, 100.0, 64.0, 320.0],
            [0.0, 0.0, 1.0, 5.0],
        ],
        "homography": [[20.0, 0.0, 64.0], [0.0, 20.0, 64.0], [0.0, 0.0, 1.0]],
        "imageCoordinates": image_points,
        "globalCoordinates": [{"x": x, "y": y, "z": z} for x, y, z in world],
        "scaleFactor": 1.0,
        "translationToGlobalCoordinates": {"x": 0.0, "y": 0.0},
    }
    calibration = root / "calibration.json"
    write_json(calibration, {"sensors": [sensor]})
    return camera, calibration


def run_semantic(root: Path, runner: CommandRunner) -> dict[str, Any]:
    from pxr import Usd, UsdGeom, UsdSemantics

    stage_path = root / "scene.usda"
    stage = Usd.Stage.CreateNew(str(stage_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    world.AddRotateXYZOp().Set((10.0, 20.0, 30.0))
    UsdGeom.Mesh.Define(stage, "/World/FlatBox_body")
    hidden = UsdGeom.Xform.Define(stage, "/World/Hidden")
    hidden.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    UsdGeom.Mesh.Define(stage, "/World/Hidden/CardBox")
    stage.GetRootLayer().Save()
    fixture_sha = sha_file(stage_path)
    report = root / "boxes.txt"
    xforms = root / "xforms.json"
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "semantic_labeling/box_check.py"),
            "--stage",
            str(stage_path),
            "--output",
            str(report),
            "--apply",
        ]
    )
    labelled = Usd.Stage.Open(str(stage_path))
    labelled.GetRootLayer().Reload()
    prim = labelled.GetPrimAtPath("/World/FlatBox_body")
    labels = list(UsdSemantics.LabelsAPI.Get(prim, "class").GetLabelsAttr().Get())
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "utils/export_xform_semantics.py"),
            "--stage",
            str(stage_path),
            "--output",
            str(xforms),
        ]
    )
    exported = strict_json(xforms)
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "semantic_labeling/remove_label.py"),
            "--stage",
            str(stage_path),
        ]
    )
    removed_stage = Usd.Stage.Open(str(stage_path))
    removed_stage.GetRootLayer().Reload()
    removed = removed_stage.GetPrimAtPath("/World/FlatBox_body")
    remaining = list(UsdSemantics.LabelsAPI.GetDirectTaxonomies(removed))
    negative = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "semantic_labeling/box_check.py"),
            "--stage",
            str(root / "missing.usda"),
            "--output",
            str(root / "missing.txt"),
        ],
        expected={1},
    )
    if (
        labels != ["flatbox"]
        or remaining
        or exported.get("/World/FlatBox_body", {}).get("rotate") != [10.0, 20.0, 30.0]
    ):
        raise EvidenceError("semantic-label round trip mismatch")
    return {
        "fixture_sha256": fixture_sha,
        "positive": {
            "labels": labels,
            "hidden_reported": "/World/Hidden/CardBox" in report.read_text(),
            "xform": exported["/World/FlatBox_body"],
            "labels_removed": not remaining,
            "artifacts": artifact_hashes([report, xforms]),
        },
        "negatives": [
            {
                "tool": "box_check",
                "case": "missing_stage",
                "rejected": negative.returncode != 0,
                "artifact_absent": not (root / "missing.txt").exists(),
            }
        ],
    }


def run_conversion(root: Path, runner: CommandRunner) -> dict[str, Any]:
    import cv2
    import h5py

    fixture = make_media_fixture(root / "dataset", frames=8)
    dataset = root / "dataset"
    camera = fixture["camera"]
    fixture_sha = sha_bytes(
        canonical_bytes({"kind": "tiny_media", "frames": 8, "depth_mm_first": 1250})
    )
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_conversion/convert_npy_to_png_depthmap.py"),
            str(dataset),
        ]
    )
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_conversion/convert_single_camera_rgb_depth_to_h5.py"),
            "--input",
            str(camera),
        ]
    )
    runner.run(
        [
            "bash",
            str(SDG_ROOT / "data_conversion/convert_images_to_videos_no_bframes.sh"),
            str(dataset),
        ],
        timeout=180,
    )
    png = camera / "distance_to_image_plane_png/distance_to_image_plane_00000.png"
    h5 = dataset / "_World_Cameras_Camera.h5"
    video = camera / "video.mp4"
    depth = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
    with h5py.File(h5, "r") as archive:
        h5_observation = {
            "groups": sorted(archive.keys()),
            "rgb_dtype": str(archive["rgb/rgb_00000.jpg"].dtype),
            "depth_dtype": str(
                archive[
                    "distance_to_image_plane_png/distance_to_image_plane_00000.png"
                ].dtype
            ),
            "rgb_compression": archive["rgb/rgb_00000.jpg"].compression,
            "depth_compression": archive[
                "distance_to_image_plane_png/distance_to_image_plane_00000.png"
            ].compression,
        }
    probe = runner.run(
        [
            str(THOR_ENV / "bin/ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,has_b_frames",
            "-of",
            "json",
            str(video),
        ]
    )
    stream = json.loads(probe.stdout)["streams"][0]
    if depth is None or depth.dtype.name != "uint16" or int(depth[0, 0]) != 1250:
        raise EvidenceError("depth conversion semantic mismatch")
    if (
        h5_observation["groups"] != ["distance_to_image_plane_png", "rgb"]
        or h5_observation["rgb_compression"] != "gzip"
        or h5_observation["depth_compression"] != "gzip"
    ):
        raise EvidenceError("HDF5 conversion semantic mismatch")
    if stream != {"codec_name": "h264", "has_b_frames": 0}:
        raise EvidenceError(f"video conversion semantic mismatch: {stream}")
    missing = root / "missing"
    neg_depth = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_conversion/convert_npy_to_png_depthmap.py"),
            str(missing),
        ]
    )
    empty_camera = root / "empty-camera"
    empty_camera.mkdir()
    neg_h5 = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_conversion/convert_single_camera_rgb_depth_to_h5.py"),
            "--input",
            str(empty_camera),
        ]
    )
    neg_video = runner.run(
        [
            "bash",
            str(SDG_ROOT / "data_conversion/convert_images_to_videos_no_bframes.sh"),
            str(missing),
        ],
        expected={1},
    )
    return {
        "fixture_sha256": fixture_sha,
        "positive": {
            "depth": {"dtype": depth.dtype.name, "millimetres": int(depth[0, 0])},
            "hdf5": h5_observation,
            "video": stream,
            "artifacts": artifact_hashes([png, h5, video]),
        },
        "negatives": [
            {
                "tool": "depth_to_png",
                "case": "missing_base_yields_no_artifact",
                "rejected": neg_depth.returncode == 0 and not missing.exists(),
            },
            {
                "tool": "rgb_depth_to_hdf5",
                "case": "missing_subdirectories",
                "rejected": neg_h5.returncode == 0
                and not (root / "empty-camera.h5").exists(),
            },
            {
                "tool": "images_to_video",
                "case": "missing_base",
                "rejected": neg_video.returncode != 0,
            },
        ],
    }


def run_ground_truth(root: Path, runner: CommandRunner) -> dict[str, Any]:
    input_root = root / "custom-ground-truth"
    annotations = input_root / "_World_Cameras_Camera/object_detection"
    annotations.mkdir(parents=True)
    write_json(annotations / "object_detection_00000.json", tiny_detection_payload())
    xform = root / "xform.json"
    write_json(xform, {"/World/CustomBox": {"rotate": [10.0, 20.0, 30.0]}})
    before = sha_bytes(
        canonical_bytes(
            {
                str(p.relative_to(input_root)): sha_file(p)
                for p in sorted(input_root.rglob("*"))
                if p.is_file()
            }
        )
    )
    all_artifacts: dict[str, dict[str, str]] = {}
    semantic: dict[str, Any] = {}
    for mode, extra in (("absent", []), ("non_null", ["--xform_info", str(xform)])):
        output = root / f"output-{mode}"
        runner.run(
            [
                str(PINNED_PYTHON),
                str(SDG_ROOT / "data_conversion/convert_ground_truth.py"),
                str(input_root),
                "--output",
                str(output),
                "--skip-visualization",
                *extra,
            ]
        )
        expected = [
            output / name
            for name in (
                "ground_truth.json",
                "bounding_boxes.json",
                "rotation_keys_with_rot.json",
                "corners_comparison_dict.json",
            )
        ]
        if not all(path.is_file() for path in expected):
            raise EvidenceError("ground-truth output set incomplete")
        all_artifacts[mode] = artifact_hashes(expected)
        gt = strict_json(output / "ground_truth.json")
        semantic[mode] = {
            "object_name": gt["0"][0]["object name"],
            "location": gt["0"][0]["3d location"],
            "scale": gt["0"][0]["3d bounding box scale"],
        }
    after = sha_bytes(
        canonical_bytes(
            {
                str(p.relative_to(input_root)): sha_file(p)
                for p in sorted(input_root.rglob("*"))
                if p.is_file()
            }
        )
    )
    negative = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_conversion/convert_ground_truth.py"),
            str(input_root),
            "--output",
            str(root / "negative-output"),
        ],
        expected={2},
    )
    if before != after or any(
        value["object_name"] != "/World/CustomBox" for value in semantic.values()
    ):
        raise EvidenceError("ground-truth semantics or input immutability mismatch")
    return {
        "fixture_sha256": before,
        "positive": {
            "modes": semantic,
            "input_tree_unchanged": True,
            "artifacts": all_artifacts,
        },
        "negatives": [
            {
                "tool": "convert_ground_truth",
                "case": "visualization_without_calibration",
                "rejected": negative.returncode == 2,
                "artifact_absent": not (root / "negative-output").exists(),
            }
        ],
    }


def run_dataset_checks(root: Path, runner: CommandRunner) -> dict[str, Any]:
    dataset = root / "dataset"
    fixture = make_media_fixture(dataset, frames=8)
    camera = fixture["camera"]
    # The native zero-B-frame converter supplies the positive video checker input.
    runner.run(
        [
            "bash",
            str(SDG_ROOT / "data_conversion/convert_images_to_videos_no_bframes.sh"),
            str(dataset),
        ],
        timeout=180,
    )
    logs = root / "logs"
    logs.mkdir()
    checks: list[dict[str, Any]] = []
    simple: list[tuple[str, str, list[str]]] = [
        ("rgb", "dataset_sanity_check_rgb.py", []),
        ("npy_depth", "dataset_sanity_check_npy.py", []),
        ("png_depth", "dataset_sanity_check_png.py", []),
        ("object_detection_json", "dataset_sanity_check_json.py", []),
        ("instance_id_json", "dataset_sanity_check_instance_id_json.py", []),
        ("instance_id_png", "dataset_sanity_check_instance_id_png.py", []),
    ]
    for check_id, script, extra in simple:
        positive_log = logs / f"{check_id}-positive.log"
        negative_log = logs / f"{check_id}-negative.log"
        base = [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check" / script),
            "--base_dir",
            str(dataset),
            "--output_log",
        ]
        runner.run([*base, str(positive_log), "--total_frames", "8", *extra])
        runner.run([*base, str(negative_log), "--total_frames", "9", *extra])
        positive_text = positive_log.read_text()
        negative_text = negative_log.read_text()
        if (
            "[MISSING]" in positive_text
            or "[UNREADABLE]" in positive_text
            or "[OVERFLOW]" in positive_text
        ):
            raise EvidenceError(f"positive checker reported failure: {check_id}")
        if "[MISSING]" not in negative_text:
            raise EvidenceError(f"adjacent missing-frame case not detected: {check_id}")
        checks.append(
            {
                "tool": check_id,
                "positive": True,
                "adjacent_negative": "missing_frame_detected",
                "positive_log_sha256": normalized_text_sha(positive_log, root),
            }
        )

    # Explicit overflow is the object-detection checker's second nearest negative.
    overflow_root = root / "overflow"
    overflow_camera = overflow_root / "_World_Cameras_Camera/object_detection"
    overflow_camera.mkdir(parents=True)
    write_json(
        overflow_camera / "object_detection_00000.json",
        tiny_detection_payload(overflow=True),
    )
    overflow_log = logs / "object-overflow.log"
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_json.py"),
            "--base_dir",
            str(overflow_root),
            "--total_frames",
            "1",
            "--output_log",
            str(overflow_log),
        ]
    )
    if "[OVERFLOW]" not in overflow_log.read_text():
        raise EvidenceError("object overflow case not detected")

    # Velocity positive and invalid-step negative.
    gt = root / "ground_truth.json"
    write_json(
        gt,
        {
            "0": [{"object name": "obj", "3d location": [0.0, 0.0, 0.0]}],
            "1": [{"object name": "obj", "3d location": [1.0, 0.0, 0.5]}],
            "2": [{"object name": "obj", "3d location": [2.0, 0.0, 1.0]}],
        },
    )
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_velocity.py"),
            "--gt_dir",
            str(gt),
            "--step",
            "2",
        ]
    )
    speeds = strict_json(root / "character_speeds_2.json")
    velocity_negative = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_velocity.py"),
            "--gt_dir",
            str(gt),
            "--step",
            "0",
        ],
        expected={1},
    )
    if speeds != {"Frame 0 -> Frame 2": {"obj": [30.0, 15.0]}}:
        raise EvidenceError(f"velocity semantic mismatch: {speeds}")
    checks.append(
        {
            "tool": "velocity",
            "positive": speeds,
            "adjacent_negative": "zero_step_rejected",
            "negative_returncode": velocity_negative.returncode,
        }
    )

    # Calibration and bbox-direction checkers use a separate canonical Camera tree.
    calibration_root = root / "calibration-dataset"
    _, calibration = make_calibration_fixture(calibration_root)
    calibration_output = root / "calibration-output"
    calibration_output.mkdir()
    runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_calibration.py"),
            "--base_dir",
            str(calibration_root),
            "--calibration",
            str(calibration),
            "--output_dir",
            str(calibration_output),
        ],
        timeout=180,
    )
    calibration_pngs = sorted(calibration_output.glob("*.png"))
    if len(calibration_pngs) != 7:
        raise EvidenceError(
            f"calibration checker produced {len(calibration_pngs)} outputs, expected 7"
        )
    bad_calibration = root / "bad-calibration.json"
    write_json(bad_calibration, {"sensors": []})
    bad_calibration_output = root / "bad-calibration-output"
    bad_calibration_output.mkdir()
    calibration_negative = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_calibration.py"),
            "--base_dir",
            str(calibration_root),
            "--calibration",
            str(bad_calibration),
            "--output_dir",
            str(bad_calibration_output),
        ]
    )
    if list(bad_calibration_output.iterdir()):
        raise EvidenceError(
            "empty calibration unexpectedly produced validation artifacts"
        )
    checks.append(
        {
            "tool": "calibration",
            "positive_outputs": artifact_hashes(calibration_pngs),
            "adjacent_negative": "empty_sensor_set_yields_no_artifacts",
            "negative_returncode": calibration_negative.returncode,
        }
    )

    bbox_save = root / "bbox-save"
    seed_wrapper = (
        "import random,runpy,sys;random.seed(0);"
        f"sys.argv={json.dumps(['dataset_sanity_check_bbox_direction.py', '--root_dir', str(calibration_root), '--calibration', str(calibration), '--save_path', str(bbox_save), '--frame_idx_list', '0'])};"
        f"runpy.run_path({str(SDG_ROOT / 'data_sanity_check/dataset_sanity_check_bbox_direction.py')!r},run_name='__main__')"
    )
    runner.run([str(PINNED_PYTHON), "-c", seed_wrapper], timeout=180)
    bbox_jsons = [
        calibration_root / name
        for name in (
            "bbox_3d_nan.json",
            "bbox_3d_direction_rotation.json",
            "bbox_3d_corners_comparison.json",
        )
    ]
    if not all(path.is_file() for path in bbox_jsons):
        raise EvidenceError("bbox checker output set incomplete")
    bad_bbox_calibration = root / "bad-bbox-calibration.json"
    write_json(bad_bbox_calibration, {"sensors": [{"id": "Other"}]})
    bad_wrapper = seed_wrapper.replace(
        str(calibration), str(bad_bbox_calibration)
    ).replace(str(bbox_save), str(root / "bad-bbox-save"))
    bbox_negative = runner.run(
        [str(PINNED_PYTHON), "-c", bad_wrapper], expected={1}, timeout=180
    )
    checks.append(
        {
            "tool": "bbox_direction",
            "positive_outputs": artifact_hashes(bbox_jsons),
            "adjacent_negative": "camera_calibration_mismatch_rejected",
            "negative_returncode": bbox_negative.returncode,
        }
    )

    video_report = dataset / "bframes_check_results.txt"
    runner.run(
        [
            "bash",
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_videos.sh"),
            str(dataset),
        ]
    )
    if "No B-frames found" not in video_report.read_text():
        raise EvidenceError("positive video checker did not report zero B-frames")
    bframe_root = root / "bframe-dataset/Camera"
    (bframe_root / "rgb").mkdir(parents=True)
    for image in sorted((camera / "rgb").glob("*.jpg")):
        shutil.copy2(image, bframe_root / "rgb" / image.name)
    runner.run(
        [
            str(THOR_ENV / "bin/ffmpeg"),
            "-y",
            "-framerate",
            "30",
            "-i",
            str(bframe_root / "rgb/rgb_%05d.jpg"),
            "-c:v",
            "libx264",
            "-bf",
            "2",
            "-g",
            "30",
            "-pix_fmt",
            "yuv420p",
            str(bframe_root / "video.mp4"),
        ],
        timeout=180,
    )
    runner.run(
        [
            "bash",
            str(SDG_ROOT / "data_sanity_check/dataset_sanity_check_videos.sh"),
            str(root / "bframe-dataset"),
        ]
    )
    bframe_report = root / "bframe-dataset/bframes_check_results.txt"
    if "B-frames detected" not in bframe_report.read_text():
        raise EvidenceError("adjacent B-frame case not detected")
    checks.append(
        {
            "tool": "video_b_frames",
            "positive": "zero_b_frames",
            "adjacent_negative": "b_frames_detected",
            "positive_log_sha256": normalized_text_sha(video_report, root),
        }
    )
    return {
        "fixture_sha256": sha_bytes(
            canonical_bytes(
                {
                    "kind": "tiny_custom_dataset",
                    "frames": 8,
                    "camera_ids": ["_World_Cameras_Camera", "Camera"],
                }
            )
        ),
        "positive": {"checker_count": 10, "checks": checks, "overflow_detected": True},
        "negatives": [
            {"tool": row["tool"], "case": row["adjacent_negative"], "rejected": True}
            for row in checks
        ],
    }


ADAPTERS: dict[str, Callable[[Path, CommandRunner], dict[str, Any]]] = {
    "semantic_label_helpers": run_semantic,
    "dataset_checks": run_dataset_checks,
    "rgb_depth_video_conversion": run_conversion,
    "ground_truth_conversion": run_ground_truth,
}


def verify_environment(
    contract: dict[str, Any], runner: CommandRunner
) -> dict[str, Any]:
    if (
        platform.machine() != "aarch64"
        or sys.version.split()[0] != contract["environment"]["python"]
    ):
        raise EvidenceError(
            "executor is not running in the pinned Thor Python environment"
        )
    from pxr import Usd

    versions = {
        name: importlib.metadata.version(name)
        for name in contract["environment"]["expected_distributions"]
    }
    if versions != contract["environment"]["expected_distributions"]:
        raise EvidenceError("installed distribution versions differ from contract")
    if Usd.GetVersion() != (0, 26, 5):
        raise EvidenceError("OpenUSD version differs from 26.05")
    cache = SDG_ROOT / "thor/offline-cache"
    cache_check = runner.run(
        [
            str(PINNED_PYTHON),
            str(SDG_ROOT / "thor/verify_offline_cache.py"),
            str(cache),
            str(REPO_ROOT / contract["environment"]["conda_lock"]["path"]),
            str(REPO_ROOT / contract["environment"]["pip_requirements"]["path"]),
            str(REPO_ROOT / contract["environment"]["wheel_lock"]["path"]),
        ],
        timeout=300,
    )
    return {
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "openusd": ".".join(map(str, Usd.GetVersion()[1:])),
        "distributions": versions,
        "offline_cache_verified": "178 conda packages, 21 Python wheels"
        in cache_check.stdout,
    }


def execute(
    contract: dict[str, Any],
    *,
    oracle_document: Path | None,
    development: bool,
) -> dict[str, Any]:
    bindings = verify_bindings(
        contract,
        require_clean=not development,
        oracle_document=oracle_document,
        require_executor_ready=not development,
    )
    temporary_parent = Path(tempfile.mkdtemp(prefix="vss-sdg-runtime-evidence-"))
    temporary = temporary_parent / "workspace"
    temporary.mkdir()
    runner = CommandRunner(temporary)
    capability_results: list[dict[str, Any]] = []
    try:
        environment = verify_environment(contract, runner)
        for capability in contract["capabilities"]:
            observations = []
            for index in range(2):
                run_root = temporary / capability["adapter"] / f"run-{index + 1}"
                run_root.mkdir(parents=True)
                observations.append(ADAPTERS[capability["adapter"]](run_root, runner))
            first, second = observations
            if first["fixture_sha256"] != capability["generated_input_sha256"]:
                raise EvidenceError(
                    f"generated fixture identity drift: {capability['capability_id']}"
                )
            if (
                bindings["execution_oracles_executor_ready"]
                and bindings["execution_oracle_fixture_sha256"][
                    capability["capability_id"]
                ]
                != capability["fixture_manifest"]["sha256"]
            ):
                raise EvidenceError(
                    f"executor-ready oracle fixture digest drift: {capability['capability_id']}"
                )
            if canonical_bytes(first) != canonical_bytes(second):
                raise EvidenceError(
                    f"independent output drift: {capability['capability_id']}"
                )
            if not first["negatives"] or not all(
                row["rejected"] for row in first["negatives"]
            ):
                raise EvidenceError(
                    f"adjacent negative did not fail closed: {capability['capability_id']}"
                )
            digest = sha_bytes(canonical_bytes(first))
            capability_results.append(
                {
                    "capability_id": capability["capability_id"],
                    "oracle_id": capability["oracle_id"],
                    "status": "pass",
                    "independent_runs": 2,
                    "deterministic_output": True,
                    "fixture_sha256": capability["fixture_manifest"]["sha256"],
                    "generated_input_sha256": first["fixture_sha256"],
                    "run_output_sha256": [digest, digest],
                    "positive_observations": first["positive"],
                    "adjacent_negatives": first["negatives"],
                    "expected_observation_results": [
                        {"observation_id": item, "passed": True}
                        for item in bindings["execution_oracle_observation_ids"][
                            capability["capability_id"]
                        ]
                    ],
                    "assertion_results": [
                        {"assertion_id": item, "passed": True}
                        for item in bindings["execution_oracle_assertion_ids"][
                            capability["capability_id"]
                        ]
                    ],
                    "cleanup": {
                        "namespace": capability["adapter"],
                        "temporary_files_only": True,
                    },
                }
            )
    finally:
        shutil.rmtree(temporary)
    if temporary.exists() or list(temporary_parent.iterdir()):
        raise EvidenceError(
            "temporary namespace cleanup failed or owned sibling changed"
        )
    temporary_parent.rmdir()
    if temporary_parent.exists():
        raise EvidenceError("temporary parent cleanup failed")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "target_bound_offline_runtime_evidence",
        "status": "pass",
        "captured_at_utc": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "bindings": bindings,
        "environment": environment,
        "capability_results": capability_results,
        "cleanup": {
            "root_removed": True,
            "sibling_names_unchanged": True,
            "repository_mutations": 0,
        },
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "model_accesses": 0,
            "downloads": 0,
            "warehouse_sample_accesses": 0,
            "command_count": len(runner.calls),
            "command_trace": runner.calls,
            "network_boundary": "proxy-free digest-locked local command allowlist; tools contain no network operation",
        },
        "promotion": {
            "receipt_is_runtime_evidence": not development,
            "eligible_capability_ids": EXPECTED_CAPABILITIES,
            "family_id": "synthetic-data-tools",
            "ledger_mutation_performed": False,
            "requires_separate_reviewed_metadata_integration": True,
            "development_smoke_only": development,
        },
    }


def plan(
    contract: dict[str, Any], oracle_document: Path | None = None
) -> dict[str, Any]:
    bindings = verify_bindings(
        contract, require_clean=False, oracle_document=oracle_document
    )
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "plan",
        "captured_at_utc": None,
        "bindings": bindings,
        "environment": {
            "required_path": contract["environment"]["environment_path"],
            "execution_performed": False,
        },
        "capability_results": [
            {
                "capability_id": row["capability_id"],
                "oracle_id": row["oracle_id"],
                "status": "plan",
                "independent_runs": 0,
                "deterministic_output": False,
                "fixture_sha256": row["fixture_manifest"]["sha256"],
                "generated_input_sha256": row["generated_input_sha256"],
                "run_output_sha256": [],
                "positive_observations": {},
                "adjacent_negatives": [],
                "cleanup": {"temporary_files_only": True},
            }
            for row in contract["capabilities"]
        ],
        "cleanup": {"execution_performed": False},
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "downloads": 0,
        },
        "promotion": {
            "ledger_mutation_performed": False,
            "requires_separate_reviewed_metadata_integration": True,
        },
    }


def reexec_if_needed(argv: list[str]) -> None:
    if "--execute" not in argv:
        return
    if Path(sys.prefix).resolve() == THOR_ENV.resolve():
        return
    if not PINNED_PYTHON.is_file():
        raise EvidenceError(f"pinned environment absent: {THOR_ENV}")
    os.execve(
        str(PINNED_PYTHON),
        [str(PINNED_PYTHON), str(Path(__file__)), *argv],
        os.environ.copy(),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        reexec_if_needed(arguments)
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--acknowledge", default="")
        parser.add_argument("--output", type=Path)
        parser.add_argument(
            "--oracle-document",
            type=Path,
            help="repository oracle registry containing future executor-ready rows",
        )
        parser.add_argument(
            "--allow-dirty-development",
            action="store_true",
            help="run a non-promoting smoke execution against lineage rows",
        )
        args = parser.parse_args(arguments)
        if args.execute and not args.allow_dirty_development and args.output:
            resolved_output = args.output.resolve(strict=False)
            if resolved_output.exists():
                raise EvidenceError("promotable output path must not already exist")
            try:
                resolved_output.relative_to(REPO_ROOT)
            except ValueError:
                pass
            else:
                raise EvidenceError(
                    "promotable receipt output must be outside the repository"
                )
        contract = strict_json(args.contract)
        if args.execute:
            if args.acknowledge != ACK:
                raise EvidenceError(f"--execute requires --acknowledge {ACK}")
            result = execute(
                contract,
                oracle_document=args.oracle_document,
                development=args.allow_dirty_development,
            )
        else:
            result = plan(contract, args.oracle_document)
        rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (
        EvidenceError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
