#!/usr/bin/env python3
"""Candidate-only, deterministic executors for eight literal advertised entries.

The executor reads digest-locked repository files and runs narrowly selected source
function/class bodies against in-memory adapters.  It performs no file writes and
does not use Docker, subprocesses, sockets, network clients, credentials, downloads,
or service lifecycle operations.  An ``observed_match`` is candidate evidence only.
"""

from __future__ import annotations

import argparse
import ast
import datetime as datetime_module
import hashlib
import io
import json
import logging
import math
import posixpath
import re
from abc import ABC, abstractmethod
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import cv2
import numpy as np
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from scipy.optimize import linear_sum_assignment


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 2_000_000

EXPECTED_CASE_BINDINGS = {
    "manifest-gap.rt-cv-3d-mv3dt.05-associated-skill": (
        "/features/15/advertised/5",
        "associated_skill_contract",
        {
            "skills/vss-deploy-detection-tracking-3d/SKILL.md",
            "skills/vss-deploy-detection-tracking-3d/references/configure-cameras.md",
            "skills/vss-deploy-detection-tracking-3d/references/deploy-rtvi-cv-3d-stack.md",
            "skills/vss-deploy-detection-tracking-3d/references/verify-and-view.md",
        },
    ),
    "manifest-gap.spatial-ai-utils.00-calibration-and-camera-grouping": (
        "/features/29/advertised/0",
        "calibration_grouping",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/cameras/group_utils.py"
        },
    ),
    "manifest-gap.spatial-ai-utils.01-3d-2d-geometry": (
        "/features/29/advertised/1",
        "geometry_3d_2d",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/boxes/box_3d.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/projection.py",
        },
    ),
    "manifest-gap.spatial-ai-utils.02-multiview-visualization": (
        "/features/29/advertised/2",
        "multiview_visualization",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/boxes/box_3d.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/projection.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/box_3d.py",
        },
    ),
    "manifest-gap.spatial-ai-utils.04-tracking-hota-clear-identity-count": (
        "/features/29/advertised/4",
        "tracking_metrics",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/_base_metric.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/hota.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/clear.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/identity.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/count.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/utils.py",
        },
    ),
    "manifest-gap.spatial-ai-utils.05-nvschema-conversion": (
        "/features/29/advertised/5",
        "nvschema_conversion",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/converters/nusc_results_to_nvschema.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/rotation.py",
        },
    ),
    "manifest-gap.spatial-ai-utils.06-video-frame-tools": (
        "/features/29/advertised/6",
        "video_frame_tools",
        {
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/video_utils/frame2video.py",
            "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/video_utils/video2frame.py",
        },
    ),
    "manifest-gap.synthetic-data-tools.01-dataset-checks": (
        "/features/30/advertised/1",
        "dataset_checks",
        {
            "tools/sdg-postprocessing/data_sanity_check/dataset_sanity_check_json.py",
            "tools/sdg-postprocessing/data_sanity_check/dataset_sanity_check_velocity.py",
        },
    ),
}


class QualificationError(RuntimeError):
    """Raised when a lock, contract, or semantic assertion does not match."""


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = REPO_ROOT / relative_path
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(f"source exceeds {max_bytes} bytes: {relative_path}")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        value: Dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _json_load(relative_path: str) -> Any:
    return _strict_json_bytes(_read_bytes(relative_path), relative_path)


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid JSON schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _verify_lock(lock: Dict[str, str]) -> bytes:
    raw = _read_bytes(lock["path"])
    actual = _sha256(raw)
    if actual != lock["sha256"]:
        raise QualificationError(
            f"source lock mismatch for {lock['path']}: {actual} != {lock['sha256']}"
        )
    return raw


def _extract_symbols(
    relative_path: str, names: Iterable[str], namespace: Dict[str, Any]
) -> Dict[str, Any]:
    """Compile only named, digest-gated definitions from a checked-in source file."""
    wanted = list(names)
    tree = ast.parse(_read_bytes(relative_path), filename=relative_path)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in wanted
    ]
    found = [node.name for node in selected]
    if len(found) != len(wanted) or set(found) != set(wanted):
        raise QualificationError(
            f"symbol allowlist mismatch for {relative_path}: wanted={wanted}, found={found}"
        )
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    scope.setdefault("__builtins__", __builtins__)
    exec(compile(module, relative_path, "exec"), scope)  # noqa: S102 - locked AST
    return {name: scope[name] for name in wanted}


def _load_and_validate_inventory() -> Tuple[Dict[str, Any], bytes]:
    raw = INVENTORY_PATH.read_bytes()
    inventory = _strict_json_bytes(raw, INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    expected_policy = {
        "candidate_only": True,
        "can_mark_passed_current": False,
        "live_acceptance_mutation_allowed": False,
        "live_oracle_mutation_allowed": False,
        "runtime_evidence": [],
        "network_allowed": False,
        "docker_allowed": False,
        "subprocess_allowed": False,
        "lifecycle_allowed": False,
        "downloads_allowed": False,
        "credentials_allowed": False,
        "file_writes_allowed": False,
    }
    if inventory.get("policy") != expected_policy:
        raise QualificationError("candidate-only policy is not exact")
    if inventory.get("denominator") != {
        "advertised_gap_entries": 87,
        "selected_candidate_entries": 8,
        "entries_left_open": 79,
    }:
        raise QualificationError("87/8/79 denominator is not exact")

    plan_spec = inventory["source_plan"]
    plan_raw = _read_bytes(plan_spec["path"])
    if _sha256(plan_raw) != plan_spec["raw_sha256"]:
        raise QualificationError("advertised-entry gap plan source lock mismatch")
    plan = _strict_json_bytes(plan_raw, plan_spec["path"])
    if plan.get("plan_payload_sha256") != plan_spec["plan_payload_sha256"]:
        raise QualificationError("gap plan payload identity mismatch")
    manifest_spec = inventory["source_manifest"]
    manifest_raw = _read_bytes(manifest_spec["path"])
    if _sha256(manifest_raw) != manifest_spec["raw_sha256"]:
        raise QualificationError("manifest source lock mismatch")
    manifest = _strict_json_bytes(manifest_raw, manifest_spec["path"])

    cases = inventory.get("cases", [])
    if len(cases) != 8 or len({case["entry_id"] for case in cases}) != 8:
        raise QualificationError("inventory must contain eight unique exact entries")
    if {case["entry_id"] for case in cases} != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError(
            "inventory entry-ID set differs from the bounded tranche"
        )
    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer = case["manifest_pointer"]
        expected_pointer, expected_adapter, expected_sources = EXPECTED_CASE_BINDINGS[
            case["entry_id"]
        ]
        if pointer != expected_pointer or case["adapter_id"] != expected_adapter:
            raise QualificationError(
                f"bounded adapter binding mismatch for {case['entry_id']}"
            )
        if {lock["path"] for lock in case["source_locks"]} != expected_sources:
            raise QualificationError(
                f"bounded source set mismatch for {case['entry_id']}"
            )
        if pointer not in plan_by_pointer:
            raise QualificationError(f"case pointer absent from source plan: {pointer}")
        gap = plan_by_pointer[pointer]
        comparisons = {
            "entry_id": gap["entry_id"],
            "proposed_capability_id": gap["proposed_capability"]["id"],
            "advertised": gap["advertised"],
            "advertised_utf8_sha256": gap["advertised_utf8_sha256"],
            "advertised_canonical_sha256": gap["advertised_canonical_sha256"],
        }
        for field, expected in comparisons.items():
            if case.get(field) != expected:
                raise QualificationError(f"{pointer} differs from gap plan at {field}")
        if _resolve_pointer(manifest, pointer) != case["advertised"]:
            raise QualificationError(f"{pointer} differs from manifest literal")
        if not case["evidence_scope"].startswith("subset:"):
            raise QualificationError(f"{pointer} lacks subset scope label")
        for lock in case["source_locks"]:
            _verify_lock(lock)
    return inventory, raw


def _skill_contract() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "required_frontmatter": {
            "name": "vss-deploy-detection-tracking-3d",
            "version": "3.2.1",
        },
        "required_routes": ["sample", "videos", "rtsp"],
    }
    skill_path = "skills/vss-deploy-detection-tracking-3d/SKILL.md"
    text = _read_bytes(skill_path).decode("utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise QualificationError("skill frontmatter is missing")
    frontmatter = parts[1]
    name_match = re.search(r"(?m)^name:\s*(.+)$", frontmatter)
    version_match = re.search(r'(?m)^\s*version:\s*"([^"]+)"$', frontmatter)
    routes = {
        "sample": "| `sample` |" in text,
        "videos": "| `videos` |" in text and "custom video files" in text,
        "rtsp": "| `rtsp` |" in text and "RTSP streams" in text,
    }
    references = {
        "configure": "references/configure-cameras.md" in text,
        "deploy": "references/deploy-rtvi-cv-3d-stack.md" in text,
        "verify": "references/verify-and-view.md" in text,
    }
    output = {
        "name": name_match.group(1).strip() if name_match else None,
        "version": version_match.group(1) if version_match else None,
        "mv3dt_mode": "`MODE=mv3dt`" in text,
        "calibrated_multicamera": "multiple calibrated cameras" in text,
        "routes": routes,
        "reference_routing": references,
        "sample_not_implied": "does\n**not** imply `sample`" in text,
    }
    if output != {
        "name": "vss-deploy-detection-tracking-3d",
        "version": "3.2.1",
        "mv3dt_mode": True,
        "calibrated_multicamera": True,
        "routes": {"sample": True, "videos": True, "rtsp": True},
        "reference_routing": {"configure": True, "deploy": True, "verify": True},
        "sample_not_implied": True,
    }:
        raise QualificationError("associated skill semantic contract did not match")
    return fixture, output


def _calibration_grouping() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "sensors": [
            {"id": "Camera", "group": {"name": "bev-sensor-1", "alias": "area-1"}},
            {"id": "Camera_01", "group": {"name": "bev-sensor-2", "alias": "area-2"}},
        ],
        "move": "Camera:bev-sensor-2",
        "malformed_move": "Camera",
    }
    source = "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/cameras/group_utils.py"
    symbols = _extract_symbols(
        source,
        ["parse_moves", "apply_group_reassignments"],
        {
            "List": List,
            "Tuple": Tuple,
            "Dict": Dict,
            "logger": logging.getLogger(__name__),
        },
    )
    calibration = {"sensors": json.loads(json.dumps(fixture["sensors"]))}
    moves = symbols["parse_moves"]([fixture["move"]])
    updated, warnings = symbols["apply_group_reassignments"](
        calibration, moves, strict=True
    )
    malformed_rejected = False
    try:
        symbols["parse_moves"]([fixture["malformed_move"]])
    except ValueError:
        malformed_rejected = True
    output = {
        "updated": updated,
        "warnings": warnings,
        "target_group": calibration["sensors"][0]["group"]["name"],
        "target_alias": calibration["sensors"][0]["group"]["alias"],
        "malformed_rejected": malformed_rejected,
    }
    if output != {
        "updated": 1,
        "warnings": [],
        "target_group": "bev-sensor-2",
        "target_alias": "area-2",
        "malformed_rejected": True,
    }:
        raise QualificationError("camera grouping semantic result did not match")
    return fixture, output


def _geometry_symbols() -> Tuple[Any, Any]:
    box_path = (
        "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/boxes/box_3d.py"
    )
    proj_path = "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/projection.py"
    box3d = _extract_symbols(box_path, ["box3d_to_corners"], {"np": np})[
        "box3d_to_corners"
    ]
    projection = _extract_symbols(
        proj_path,
        ["_to_homogeneous", "project_points_3d_to_image"],
        {"np": np},
    )
    projection["project_points_3d_to_image"].__globals__["_to_homogeneous"] = (
        projection["_to_homogeneous"]
    )
    return box3d, projection["project_points_3d_to_image"]


def _geometry_3d_2d() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "box": [[0.0, 0.0, 10.0, 2.0, 4.0, 2.0, 0.0, 0.0, 0.0]],
        "world2img": [
            [100.0, 0.0, 32.0, 0.0],
            [0.0, 100.0, 32.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
    }
    box3d, project = _geometry_symbols()
    corners = box3d(np.asarray(fixture["box"]))
    pixels, front = project(corners, np.asarray(fixture["world2img"]))
    legacy_rejected = False
    try:
        box3d(np.asarray([[0, 0, 10, 2, 4, 2, 0]], dtype=float))
    except ValueError:
        legacy_rejected = True
    output = {
        "corners_shape": list(corners.shape),
        "corner_min": corners.min(axis=1)[0].tolist(),
        "corner_max": corners.max(axis=1)[0].tolist(),
        "pixels_shape": list(pixels.shape),
        "all_in_front": bool(front.all()),
        "all_pixels_finite": bool(np.isfinite(pixels).all()),
        "legacy_7dof_rejected": legacy_rejected,
    }
    expected = {
        "corners_shape": [1, 8, 3],
        "corner_min": [-1.0, -2.0, 9.0],
        "corner_max": [1.0, 2.0, 11.0],
        "pixels_shape": [1, 8, 2],
        "all_in_front": True,
        "all_pixels_finite": True,
        "legacy_7dof_rejected": True,
    }
    if output != expected:
        raise QualificationError("3D/2D geometry semantic result did not match")
    return fixture, output


def _multiview_visualization() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "camera_count": 2,
        "image_shape": [64, 64, 3],
        "box": [[0.0, 0.0, 10.0, 2.0, 4.0, 2.0, 0.0, 0.0, 0.0]],
    }
    box3d, project = _geometry_symbols()
    source = "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/box_3d.py"
    names = [
        "_to_numpy",
        "draw_box3d_corners_on_img",
        "draw_bbox3d_on_img",
        "draw_bbox3d_on_bev",
        "draw_bbox3d_multicam",
    ]
    namespace = {
        "np": np,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "Union": Union,
        "BOX3D_BOTTOM_FACE": (0, 3, 4, 7),
        "BOX3D_EDGES": (
            (0, 1),
            (0, 3),
            (0, 4),
            (1, 2),
            (1, 5),
            (3, 2),
            (3, 7),
            (4, 5),
            (4, 7),
            (2, 6),
            (5, 6),
            (6, 7),
        ),
        "BOX3D_HEADING_FACE": (1, 5, 4, 0),
        "_DEFAULT_COLOR": (0, 255, 0),
        "_DEFAULT_THICKNESS": 1,
        "_DEFAULT_FONT_SCALE": 0.8,
        "_HEADING_ALPHA": 0.5,
        "box3d_to_corners": box3d,
        "project_points_3d_to_image": project,
        "import_cv2": lambda _purpose: cv2,
        "_build_world2img": lambda _calib: (_ for _ in ()).throw(
            QualificationError("unexpected calibration path")
        ),
    }
    symbols = _extract_symbols(source, names, namespace)
    for fn in symbols.values():
        fn.__globals__.update(symbols)
    images = [np.zeros(fixture["image_shape"], dtype=np.uint8) for _ in range(2)]
    originals = [image.copy() for image in images]
    projection = np.asarray(
        [[100, 0, 32, 0], [0, 100, 32, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        dtype=float,
    )
    composite = symbols["draw_bbox3d_multicam"](
        np.asarray(fixture["box"]), images, world2imgs=[projection, projection]
    )
    output = {
        "composite_shape": list(composite.shape),
        "bev_nonzero": int(np.count_nonzero(composite[:, :64])),
        "camera_0_nonzero": int(np.count_nonzero(composite[:, 64:128])),
        "camera_1_nonzero": int(np.count_nonzero(composite[:, 128:192])),
        "inputs_unchanged": all(
            np.array_equal(a, b) for a, b in zip(images, originals)
        ),
    }
    if output["composite_shape"] != [64, 192, 3]:
        raise QualificationError("multiview composite shape did not match")
    if (
        min(
            output["bev_nonzero"],
            output["camera_0_nonzero"],
            output["camera_1_nonzero"],
        )
        <= 0
    ):
        raise QualificationError("multiview source renderer did not draw every panel")
    if not output["inputs_unchanged"]:
        raise QualificationError("multiview renderer mutated fixture images")
    return fixture, output


class _TimingAdapter:
    @staticmethod
    def time(function):
        return function


class _TrackEvalException(Exception):
    pass


def _tracking_metrics() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "timesteps": 2,
        "gt_ids": [[0], [0]],
        "tracker_ids": [[0], [0]],
        "similarity_scores": [[[1.0]], [[1.0]]],
    }
    base_path = "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics/_base_metric.py"
    base = _extract_symbols(
        base_path,
        ["_BaseMetric"],
        {
            "np": np,
            "ABC": ABC,
            "abstractmethod": abstractmethod,
            "_timing": _TimingAdapter,
            "TrackEvalException": _TrackEvalException,
        },
    )["_BaseMetric"]
    utils_path = "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/utils.py"
    init_config = _extract_symbols(utils_path, ["init_config"], {})["init_config"]
    utils = SimpleNamespace(init_config=init_config)
    common = {
        "np": np,
        "_BaseMetric": base,
        "_timing": _TimingAdapter,
        "linear_sum_assignment": linear_sum_assignment,
        "utils": utils,
    }
    metric_root = "libs/analytics/spatialai-data-utils/spatialai_data_utils/eval/tracking/hota/metrics"
    metric_classes = {}
    for filename, class_name in (
        ("hota.py", "HOTA"),
        ("clear.py", "CLEAR"),
        ("identity.py", "Identity"),
        ("count.py", "Count"),
    ):
        metric_classes[class_name] = _extract_symbols(
            f"{metric_root}/{filename}", [class_name], common
        )[class_name]
    data = {
        "gt_ids": [np.asarray(ids, dtype=int) for ids in fixture["gt_ids"]],
        "tracker_ids": [np.asarray(ids, dtype=int) for ids in fixture["tracker_ids"]],
        "similarity_scores": [
            np.asarray(score, dtype=float) for score in fixture["similarity_scores"]
        ],
        "num_gt_dets": 2,
        "num_tracker_dets": 2,
        "num_gt_ids": 1,
        "num_tracker_ids": 1,
        "num_timesteps": 2,
    }
    hota = metric_classes["HOTA"]().eval_sequence(data)
    clear = metric_classes["CLEAR"](
        {"THRESHOLD": 0.5, "PRINT_CONFIG": False}
    ).eval_sequence(data)
    identity = metric_classes["Identity"](
        {"THRESHOLD": 0.5, "PRINT_CONFIG": False}
    ).eval_sequence(data)
    count = metric_classes["Count"]().eval_sequence(data)
    output = {
        "HOTA": float(np.mean(hota["HOTA"])),
        "DetA": float(np.mean(hota["DetA"])),
        "AssA": float(np.mean(hota["AssA"])),
        "MOTA": float(clear["MOTA"]),
        "MOTP": float(clear["MOTP"]),
        "IDF1": float(identity["IDF1"]),
        "IDR": float(identity["IDR"]),
        "IDP": float(identity["IDP"]),
        "Dets": int(count["Dets"]),
        "GT_Dets": int(count["GT_Dets"]),
        "IDs": int(count["IDs"]),
        "GT_IDs": int(count["GT_IDs"]),
    }
    expected = {
        key: 1.0
        for key in ("HOTA", "DetA", "AssA", "MOTA", "MOTP", "IDF1", "IDR", "IDP")
    }
    expected.update({"Dets": 2, "GT_Dets": 2, "IDs": 1, "GT_IDs": 1})
    if output != expected:
        raise QualificationError(
            f"tracking metric semantic result did not match: {output}"
        )
    return fixture, output


class _PersistentStringIO(io.StringIO):
    def close(self) -> None:
        pass


def _nvschema_conversion() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fixture = {
        "results": {
            "scene-a-0": [
                {
                    "translation": [1.0, 2.0, 3.0],
                    "size": [4.0, 5.0, 6.0],
                    "rotation": [1.0, 0.0, 0.0, 0.0],
                    "tracking_id": 7,
                    "tracking_name": "person",
                    "tracking_score": 0.875,
                    "reid_embedding": [0.1, 0.2],
                }
            ]
        }
    }
    rotation_path = "libs/analytics/spatialai-data-utils/spatialai_data_utils/core/geometry/rotation.py"
    euler = _extract_symbols(rotation_path, ["euler_from_quaternion"], {"math": math})[
        "euler_from_quaternion"
    ]
    captured: Dict[str, _PersistentStringIO] = {}

    def memory_open(path: str, mode: str = "r", *args, **kwargs):
        del args, kwargs
        if "r" in mode:
            return _PersistentStringIO(json.dumps(fixture))
        if "w" in mode:
            stream = _PersistentStringIO()
            captured[path] = stream
            return stream
        raise QualificationError(f"unsupported in-memory open mode: {mode}")

    class FixedDateTime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 31, 12, 0, tzinfo=tz)

    fake_datetime = SimpleNamespace(
        datetime=FixedDateTime,
        timezone=datetime_module.timezone,
        timedelta=datetime_module.timedelta,
    )
    fake_os = SimpleNamespace(
        path=SimpleNamespace(join=posixpath.join),
        makedirs=lambda *_args, **_kwargs: None,
    )
    source = "libs/analytics/spatialai-data-utils/spatialai_data_utils/converters/nusc_results_to_nvschema.py"
    symbols = _extract_symbols(
        source,
        ["FloatEncoder", "convert_sparse4d_to_nvschema"],
        {
            "json": json,
            "datetime": fake_datetime,
            "os": fake_os,
            "FPS": 30,
            "get_scene_info_from_token": lambda token: (
                token.rsplit("-", 1)[0],
                int(token.rsplit("-", 1)[1]),
            ),
            "euler_from_quaternion": euler,
            "open": memory_open,
            "print": lambda *_args, **_kwargs: None,
        },
    )
    symbols["convert_sparse4d_to_nvschema"].__globals__.update(symbols)
    symbols["convert_sparse4d_to_nvschema"](
        "input.json", "/virtual/out", {"person": "Person"}
    )
    output_path = "/virtual/out/scene-a.json"
    if set(captured) != {output_path}:
        raise QualificationError("NVSchema adapter output path did not match")
    record = json.loads(captured[output_path].getvalue().strip())
    obj = record["objects"][0]
    output = {
        "version": record["version"],
        "id": record["id"],
        "sensorId": record["sensorId"],
        "timestamp": record["timestamp"],
        "object_id": obj["id"],
        "object_type": obj["type"],
        "confidence": obj["confidence"],
        "bbox3d_coordinates": obj["bbox3d"]["coordinates"],
        "embedding": obj["bbox3d"]["embedding"],
    }
    expected = {
        "version": "4.0",
        "id": "0",
        "sensorId": "bev-sensor-1",
        "timestamp": "2026-07-31T12:00:00.000Z",
        "object_id": "7",
        "object_type": "Person",
        "confidence": 0.875,
        "bbox3d_coordinates": [1.0, 2.0, 3.0, 5.0, 4.0, 6.0, 0.0, 0.0, 0.0],
        "embedding": [{"vector": [0.1, 0.2]}],
    }
    if output != expected:
        raise QualificationError(f"NVSchema semantic result did not match: {output}")
    return fixture, output


class _FakeWriter:
    def __init__(self):
        self.frames: List[np.ndarray] = []
        self.released = False

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.released = True


class _FakeCapture:
    def __init__(self, frames):
        self.frames = [frame.copy() for frame in frames]
        self.index = 0
        self.released = False

    def isOpened(self):
        return not self.released and self.index < len(self.frames)

    def get(self, prop):
        values = {
            7: len(self.frames),
            5: 30.0,
            3: self.frames[0].shape[1],
            4: self.frames[0].shape[0],
        }
        return values[prop]

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index].copy()
        self.index += 1
        return True, frame

    def release(self):
        self.released = True


class _FakeProgress:
    def update(self, _amount):
        pass

    def close(self):
        pass


def _video_frame_tools() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    frame_paths = ["/frames/10.png", "/frames/2.png", "/frames/1.png"]
    frame_values = {
        path: np.full(
            (8, 8, 3), int(posixpath.basename(path).split(".")[0]), dtype=np.uint8
        )
        for path in frame_paths
    }
    fixture = {
        "input_frame_names": [posixpath.basename(path) for path in frame_paths],
        "frame_skip": 2,
    }
    created_dirs: List[str] = []
    writer = _FakeWriter()

    def glob_paths(pattern):
        suffix = pattern.rsplit("*", 1)[-1]
        return [path for path in frame_paths if path.endswith(suffix)]

    fake_path = SimpleNamespace(
        exists=lambda path: path in frame_values,
        join=posixpath.join,
        splitext=posixpath.splitext,
        basename=posixpath.basename,
        abspath=lambda path: path,
        dirname=posixpath.dirname,
        getsize=lambda _path: 1,
        isdir=lambda _path: False,
    )
    fake_os = SimpleNamespace(
        path=fake_path,
        makedirs=lambda path, exist_ok=True: created_dirs.append(path),
        listdir=lambda _path: [],
    )
    fake_glob = SimpleNamespace(glob=glob_paths)

    class FrameCV:
        @staticmethod
        def imread(path):
            return frame_values.get(path).copy() if path in frame_values else None

        @staticmethod
        def resize(frame, shape):
            return cv2.resize(frame, shape)

        @staticmethod
        def VideoWriter_fourcc(*_codec):
            return 0

        @staticmethod
        def VideoWriter(*_args):
            return writer

    frame_source = "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/video_utils/frame2video.py"
    frame_names = [
        "_filename_ts_to_int",
        "parse_frame_filename",
        "list_frame_paths",
        "frames_to_video",
    ]
    frame_symbols = _extract_symbols(
        frame_source,
        frame_names,
        {
            "os": fake_os,
            "glob": fake_glob,
            "re": re,
            "np": np,
            "Dict": Dict,
            "Iterable": Iterable,
            "List": List,
            "Optional": Optional,
            "Tuple": Tuple,
            "_FRAME_NAME_RE": re.compile(r"^(\d+)(?:_(.+))?$"),
            "_TS_DIGITS_RE": re.compile(r"\d+"),
            "DEFAULT_FPS": 30.0,
            "DEFAULT_CODEC": "mp4v",
            "DEFAULT_GLOB_PATTERNS": ("*.jpg", "*.jpeg", "*.png"),
            "STATUS_COMPLETED": "completed",
            "STATUS_SKIPPED": "skipped",
            "STATUS_NO_FRAMES_FOUND": "no_frames_found",
            "STATUS_READ_ERROR": "read_error",
            "STATUS_WRITE_ERROR": "write_error",
            "import_cv2": lambda _purpose: FrameCV,
            "plot_frame_label": lambda frame, _label: frame,
            "tqdm": SimpleNamespace(tqdm=lambda values, **_kwargs: values),
        },
    )
    for fn in frame_symbols.values():
        fn.__globals__.update(frame_symbols)
    sorted_paths = frame_symbols["list_frame_paths"]("/frames", ("*.png",))
    encode_status = frame_symbols["frames_to_video"](
        "/frames", "/virtual/out.mp4", down_sample=2, progress=False
    )

    extracted: Dict[str, np.ndarray] = {}
    source_frames = [np.full((8, 8, 3), value, dtype=np.uint8) for value in (3, 4, 5)]
    capture = _FakeCapture(source_frames)

    class VideoCV:
        CAP_PROP_FRAME_COUNT = 7
        CAP_PROP_FPS = 5
        CAP_PROP_FRAME_WIDTH = 3
        CAP_PROP_FRAME_HEIGHT = 4

        @staticmethod
        def VideoCapture(_path):
            return capture

        @staticmethod
        def imwrite(path, frame):
            extracted[path] = frame.copy()
            return True

    video_fake_path = SimpleNamespace(
        exists=lambda path: path == "/virtual/input.mp4",
        getsize=lambda _path: 1,
        splitext=posixpath.splitext,
        isdir=lambda _path: False,
        basename=posixpath.basename,
        join=posixpath.join,
    )
    video_fake_os = SimpleNamespace(
        path=video_fake_path,
        makedirs=lambda path, exist_ok=True: created_dirs.append(path),
        listdir=lambda _path: [],
    )
    video_source = "libs/analytics/spatialai-data-utils/spatialai_data_utils/visualization/video_utils/video2frame.py"
    video_fn = _extract_symbols(
        video_source,
        ["video_to_frames"],
        {
            "os": video_fake_os,
            "Optional": Optional,
            "DEFAULT_FRAME_PATTERN": "{frame_id}.png",
            "STATUS_COMPLETED": "completed",
            "STATUS_SKIPPED": "skipped",
            "STATUS_FILE_NOT_FOUND": "file_not_found",
            "STATUS_EMPTY_FILE": "empty_file",
            "STATUS_CANNOT_OPEN": "cannot_open",
            "STATUS_INVALID_PROPERTIES": "invalid_properties",
            "STATUS_NO_FRAMES_EXTRACTED": "no_frames_extracted",
            "STATUS_INCOMPLETE_EXTRACTION": "incomplete_extraction",
            "STATUS_WRITE_ERROR": "write_error",
            "_MAX_CONSECUTIVE_DECODE_FAILURES": 10,
            "_INCOMPLETE_EXTRACTION_RATIO": 0.8,
            "import_cv2": lambda _purpose: VideoCV,
            "tqdm": SimpleNamespace(tqdm=lambda **_kwargs: _FakeProgress()),
        },
    )["video_to_frames"]
    decode_status = video_fn(
        "/virtual/input.mp4", "/virtual/frames", frame_skip=2, overwrite=True
    )
    output = {
        "numeric_sort": [posixpath.basename(path) for path in sorted_paths],
        "encode_status": encode_status,
        "encoded_frame_values": [int(frame[0, 0, 0]) for frame in writer.frames],
        "encoded_shape": list(writer.frames[0].shape),
        "decode_status": decode_status,
        "decoded_names": sorted(posixpath.basename(path) for path in extracted),
        "decoded_frame_values": [
            int(extracted[path][0, 0, 0]) for path in sorted(extracted)
        ],
        "real_file_writes": 0,
    }
    expected = {
        "numeric_sort": ["1.png", "2.png", "10.png"],
        "encode_status": "completed",
        "encoded_frame_values": [1, 2, 10],
        "encoded_shape": [4, 4, 3],
        "decode_status": "completed",
        "decoded_names": ["0.png", "1.png"],
        "decoded_frame_values": [3, 5],
        "real_file_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"video/frame semantic result did not match: {output}")
    return fixture, output


def _dataset_checks() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    valid_bbox = {
        "obj": {
            "bbox": {
                "annotators": {
                    "bounding_box_3d_fast": {
                        "x_min": -1.0,
                        "x_max": 1.0,
                        "transform": [[1.0, 0.0], [0.0, 1.0]],
                    }
                }
            }
        }
    }
    overflow_bbox = json.loads(json.dumps(valid_bbox))
    overflow_bbox["obj"]["bbox"]["annotators"]["bounding_box_3d_fast"]["x_max"] = 1e11
    frames = {
        "0": [{"object name": "person-1", "3d location": [0.0, 0.0, 0.0]}],
        "1": [{"object name": "person-1", "3d location": [1.0, 0.0, 0.5]}],
        "2": [{"object name": "person-1", "3d location": [2.0, 0.0, 1.0]}],
    }
    fixture = {
        "valid_bbox": valid_bbox,
        "overflow_bbox": overflow_bbox,
        "frames": frames,
        "step": 2,
    }
    overflow_source = (
        "tools/sdg-postprocessing/data_sanity_check/dataset_sanity_check_json.py"
    )
    check = _extract_symbols(
        overflow_source,
        ["check_for_overflow"],
        {"Dict": Dict, "Any": Any, "math": math},
    )["check_for_overflow"]
    velocity_source = (
        "tools/sdg-postprocessing/data_sanity_check/dataset_sanity_check_velocity.py"
    )
    velocity = _extract_symbols(
        velocity_source,
        ["calculate_speed", "process_frames"],
        {"Dict": Dict, "List": List, "Any": Any, "math": math, "np": np},
    )
    velocity["process_frames"].__globals__["calculate_speed"] = velocity[
        "calculate_speed"
    ]
    speeds = velocity["process_frames"](frames, step=2)
    invalid_step_rejected = False
    try:
        velocity["process_frames"](frames, step=0)
    except ValueError:
        invalid_step_rejected = True
    output = {
        "valid_overflow": bool(check(valid_bbox)),
        "extreme_overflow": bool(check(overflow_bbox)),
        "speeds": speeds,
        "invalid_step_rejected": invalid_step_rejected,
    }
    expected = {
        "valid_overflow": False,
        "extreme_overflow": True,
        "speeds": {"Frame 0 -> Frame 2": {"person-1": [30.0, 15.0]}},
        "invalid_step_rejected": True,
    }
    if output != expected:
        raise QualificationError(
            f"dataset-check semantic result did not match: {output}"
        )
    return fixture, output


ADAPTERS = {
    "associated_skill_contract": _skill_contract,
    "calibration_grouping": _calibration_grouping,
    "geometry_3d_2d": _geometry_3d_2d,
    "multiview_visualization": _multiview_visualization,
    "tracking_metrics": _tracking_metrics,
    "nvschema_conversion": _nvschema_conversion,
    "video_frame_tools": _video_frame_tools,
    "dataset_checks": _dataset_checks,
}


def execute(case_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    inventory, inventory_raw = _load_and_validate_inventory()
    selected = set(case_ids or [])
    known = {case["entry_id"] for case in inventory["cases"]}
    unknown = selected - known
    if unknown:
        raise QualificationError(f"unknown case IDs: {sorted(unknown)}")
    results = []
    for case in inventory["cases"]:
        if selected and case["entry_id"] not in selected:
            continue
        adapter = ADAPTERS.get(case["adapter_id"])
        if adapter is None:
            raise QualificationError(f"unknown adapter: {case['adapter_id']}")
        fixture, semantic_output = adapter()
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": case["entry_id"],
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_match",
                "input_sha256": _sha256(_canonical_bytes(fixture)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )
    report = {
        "schema_version": 1,
        "mode": "candidate_only_file_executor_tranche",
        "candidate_only": True,
        "inventory_sha256": _sha256(inventory_raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(report, RESULT_SCHEMA_PATH, "result")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", action="append", default=[], help="exact gap entry_id; repeatable"
    )
    parser.add_argument(
        "--list", action="store_true", help="list exact runnable entry IDs"
    )
    args = parser.parse_args()
    if args.list:
        inventory, _raw = _load_and_validate_inventory()
        print("\n".join(case["entry_id"] for case in inventory["cases"]))
        return 0
    print(json.dumps(execute(args.case), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
