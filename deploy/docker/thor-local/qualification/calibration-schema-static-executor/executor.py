#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Execute the bounded, non-advancing Thor calibration-schema candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import stat
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
CONTRACT_PATH = LANE / "contract.json"
CONTRACT_SCHEMA_PATH = LANE / "contract.schema.json"
RESULT_SCHEMA_PATH = LANE / "result.schema.json"
BACKEND_PATH = "deploy/docker/thor-local/legacy-calibration/backend.py"
ACCEPTANCE_PATH = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
CAPABILITY_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLE_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
SCHEMA_PATHS = {
    "strict_spatialai_calibration": (
        "libs/analytics/spatialai-data-utils/spatialai_data_utils/schemas/calibration.json"
    ),
    "strict_video_api_calibration": (
        "services/analytics/video-analytics-api/src/web-api-core/schemas/ajv/calibration.json"
    ),
    "behavior_calibration": (
        "services/analytics/behavior-analytics/src/mdx/analytics/core/transform/"
        "calibration/schemas/calibration.schema.json"
    ),
    "road_network": (
        "services/analytics/video-analytics-api/src/web-api-core/schemas/ajv/roadNetwork.json"
    ),
}
FIXTURE_TYPES = ("geo", "cartesian", "image", "mtmc")
EXPECTED_POLICY = {
    "candidate_only": True,
    "advances_live_acceptance": False,
    "can_mark_passed_current": False,
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "service_lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "warehouse_sample_bundle": "excluded",
    "writes": "executor_owned_private_temporary_directory_only",
}


class QualificationError(RuntimeError):
    """The source contract or an offline observation failed closed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    unresolved = root / candidate
    if unresolved.is_symlink():
        raise QualificationError(f"repository path is a symlink: {relative}")
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QualificationError(
            f"repository path escaped or is absent: {relative}"
        ) from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise QualificationError(f"repository path is not a regular file: {relative}")
    return resolved


def _load_backend() -> Any:
    path = _repo_file(BACKEND_PATH)
    spec = importlib.util.spec_from_file_location(
        "thor_schema_calibration_backend", path
    )
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load the provider-free calibration backend")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _find_one(rows: Any, key: str, expected: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise QualificationError(f"{expected} is not an array")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get(key) == expected
    ]
    if len(matches) != 1:
        raise QualificationError(f"expected exactly one {key}={expected}")
    return matches[0]


def _load_contract() -> dict[str, Any]:
    schema = _strict_json(CONTRACT_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    contract = _strict_json(CONTRACT_PATH)
    errors = list(Draft202012Validator(schema).iter_errors(contract))
    if errors:
        raise QualificationError(f"invalid contract: {errors[0].message}")
    if contract.get("mode") != "candidate_only_calibration_schema_static":
        raise QualificationError("contract mode drift")
    if contract.get("policy") != EXPECTED_POLICY:
        raise QualificationError("candidate-only safety policy drift")
    return contract


def _verify_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    expected_paths = {
        BACKEND_PATH,
        ACCEPTANCE_PATH,
        CAPABILITY_PATH,
        ORACLE_PATH,
        *SCHEMA_PATHS.values(),
    }
    locks = contract.get("source_locks")
    if (
        not isinstance(locks, list)
        or {row.get("path") for row in locks} != expected_paths
    ):
        raise QualificationError("source-lock path denominator drift")
    observed: dict[str, str] = {}
    for row in locks:
        path = row["path"]
        digest = _sha256(_repo_file(path).read_bytes())
        if digest != row.get("sha256"):
            raise QualificationError(f"source lock mismatch: {path}")
        observed[path] = digest
    if (
        observed[SCHEMA_PATHS["strict_spatialai_calibration"]]
        != observed[SCHEMA_PATHS["strict_video_api_calibration"]]
    ):
        raise QualificationError(
            "the two checked-in strict calibration copies diverged"
        )
    return observed


def _verify_binding(contract: dict[str, Any]) -> dict[str, str]:
    binding = contract["binding"]
    acceptance = _strict_json(_repo_file(ACCEPTANCE_PATH))
    planning = _find_one(
        acceptance["wave3_contracts"]["planning_requirements"],
        "id",
        binding["planning_requirement_id"],
    )
    if planning.get("owner_type") != "global_acceptance_vector":
        raise QualificationError(
            "planning owner is not the exact global acceptance vector"
        )
    if planning.get("owner_id") != binding["planning_requirement_id"]:
        raise QualificationError("planning owner identity drift")
    if _sha256(_canonical_bytes(planning)) != binding["planning_requirement_sha256"]:
        raise QualificationError("planning requirement digest drift")
    if planning.get("payload_canonical_sha256") != binding["planning_payload_sha256"]:
        raise QualificationError("planning payload digest drift")
    if (
        planning.get("materialized") is not False
        or planning.get("executor_ready") is not False
    ):
        raise QualificationError(
            "canonical planning state advanced outside this package"
        )
    if planning.get("runtime_evidence") != []:
        raise QualificationError("canonical planning requirement has runtime evidence")
    applicable = planning.get("applicable_record_ids")
    if (
        not isinstance(applicable, list)
        or len(applicable) != binding["planning_applicable_record_count"]
    ):
        raise QualificationError("planning applicable-record denominator drift")
    if binding["capability_id"] not in applicable:
        raise QualificationError(
            "evaluated capability is not owned by the planning row"
        )
    if [row for row in applicable if row != binding["capability_id"]] != binding[
        "not_evaluated_record_ids"
    ]:
        raise QualificationError("explicit non-evaluated capability set drift")

    official = _strict_json(_repo_file(CAPABILITY_PATH))
    capability = _find_one(official["capabilities"], "id", binding["capability_id"])
    if _sha256(_canonical_bytes(capability)) != binding["capability_sha256"]:
        raise QualificationError("capability digest drift")
    if capability.get("acceptance_class") != "alternate_local_lane":
        raise QualificationError("capability acceptance class drift")
    wave = capability.get("contract", {}).get("wave3_acceptance", {})
    if wave.get("planning_requirement_ids") != [binding["planning_requirement_id"]]:
        raise QualificationError("capability planning binding drift")

    oracle_set = _strict_json(_repo_file(ORACLE_PATH))
    oracle = _find_one(oracle_set["oracles"], "oracle_id", binding["oracle_id"])
    if oracle.get("capability_id") != binding["capability_id"]:
        raise QualificationError("oracle capability identity drift")
    if _sha256(_canonical_bytes(oracle)) != binding["oracle_sha256"]:
        raise QualificationError("oracle digest drift")
    if oracle.get("current_state") != "open_unexecuted" or oracle.get("evidence") != []:
        raise QualificationError(
            "canonical oracle state is not open and evidence-empty"
        )
    return {
        "planning_requirement_sha256": binding["planning_requirement_sha256"],
        "planning_payload_sha256": binding["planning_payload_sha256"],
        "capability_sha256": binding["capability_sha256"],
        "oracle_sha256": binding["oracle_sha256"],
    }


def _camera(identifier: str, x_offset: int = 0) -> dict[str, Any]:
    image_points = (
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
        [50, 0],
        [100, 50],
        [50, 100],
        [0, 50],
    )
    return {
        "id": identifier,
        "image_size": [160, 120],
        "correspondences": [
            {
                "image": list(point),
                "world": [point[0] + 10 + x_offset, point[1] - 5],
            }
            for point in image_points
        ],
        "origin": {"lat": 0, "lng": 0},
        "geo_location": {"lat": 43.65, "lng": -79.38},
        "coordinates": {"x": x_offset, "y": 0},
        "scale_factor": 1,
        "attributes": [{"name": "source", "value": "tiny-operator-custom"}],
        "place": [{"name": "site", "value": "Operator Test Site"}],
    }


def generated_fixture(project_type: str) -> dict[str, Any]:
    """Return one deterministic, in-memory, operator-style tiny project."""
    if project_type not in FIXTURE_TYPES:
        raise QualificationError(f"unknown fixture type: {project_type}")
    calibration_type = "cartesian" if project_type == "mtmc" else project_type
    value: dict[str, Any] = {
        "schema_version": 1,
        "project_id": f"schema-{project_type}",
        "project_type": project_type,
        "provider": "local_coordinate_plane",
        "calibration_type": calibration_type,
        "osm_url": "",
        "road_city": "Operator City",
        "road_intersection": "Operator Intersection",
        "camera": _camera(f"operator-{project_type}-01"),
        "rois": [
            {
                "id": "operator-roi-01",
                "points": [
                    [0, 0],
                    [25, 0],
                    [50, 0],
                    [50, 25],
                    [50, 50],
                    [25, 50],
                    [0, 50],
                    [0, 25],
                ],
            }
        ],
        "tripwires": [
            {
                "id": "operator-tripwire-01",
                "points": [[10, 10], [40, 40]],
                "direction": [[20, 10], [20, 40]],
            }
        ],
        "road_links": [],
    }
    if project_type == "geo":
        value["road_links"] = [
            {
                "id": "operator-road-01",
                "direction": "E",
                "points": [
                    {"lat": 43.65, "lon": -79.39, "alt": 0},
                    {"lat": 43.65, "lon": -79.38, "alt": 0},
                ],
            }
        ]
    if project_type == "mtmc":
        value["cameras"] = [
            value.pop("camera"),
            _camera("operator-mtmc-02", x_offset=100),
        ]
    return value


def _matrix_shape(schema: dict[str, Any], property_name: str) -> list[int]:
    matches: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and property_name in properties:
                candidate = properties[property_name]
                if isinstance(candidate, dict):
                    matches.append(candidate)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    if len(matches) != 1:
        raise QualificationError(
            f"schema has {len(matches)} definitions for {property_name}"
        )
    outer = matches[0]
    inner = outer.get("items")
    if not isinstance(inner, dict):
        raise QualificationError(f"{property_name} has no inner array")
    shape = [outer.get("minItems"), inner.get("minItems")]
    if outer.get("maxItems") != shape[0] or inner.get("maxItems") != shape[1]:
        raise QualificationError(f"{property_name} is not fixed-shape")
    if any(not isinstance(value, int) for value in shape):
        raise QualificationError(f"{property_name} shape is not integral")
    return shape


def _schema_contract(schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    strict = schemas["strict_spatialai_calibration"]
    duplicate = schemas["strict_video_api_calibration"]
    behavior = schemas["behavior_calibration"]
    if strict != duplicate:
        raise QualificationError(
            "strict SpatialAI and Video API schemas differ semantically"
        )
    expected_required = ["version", "osmURL", "calibrationType", "sensors"]
    expected_sensor_required = [
        "type",
        "id",
        "origin",
        "geoLocation",
        "coordinates",
        "scaleFactor",
        "attributes",
        "place",
        "imageCoordinates",
        "globalCoordinates",
    ]
    for label, schema in (("strict", strict), ("behavior", behavior)):
        if schema.get("required") != expected_required:
            raise QualificationError(f"{label} top-level required fields drift")
        sensors = schema.get("properties", {}).get("sensors", {})
        if sensors.get("items", {}).get("required") != expected_sensor_required:
            raise QualificationError(f"{label} sensor required fields drift")
        enum = schema.get("properties", {}).get("calibrationType", {}).get("enum")
        if enum != ["geo", "cartesian", "image"]:
            raise QualificationError(f"{label} calibration type enum drift")
    matrix_shapes = {
        "intrinsic": _matrix_shape(strict, "intrinsicMatrix"),
        "extrinsic": _matrix_shape(strict, "extrinsicMatrix"),
        "camera": _matrix_shape(strict, "cameraMatrix"),
        "homography": _matrix_shape(strict, "homography"),
    }
    return {
        "top_required": expected_required,
        "sensor_required": expected_sensor_required,
        "calibration_types": ["geo", "cartesian", "image"],
        "matrix_shapes": matrix_shapes,
        "strict_calibration_additional_properties": strict.get("additionalProperties"),
        "behavior_calibration_additional_properties": behavior.get(
            "additionalProperties"
        ),
        "road_required": schemas["road_network"].get("required"),
    }


def _validate_document(
    value: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    errors = sorted(
        Draft7Validator(schema).iter_errors(value),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        raise QualificationError(
            f"{label} schema rejection at {list(errors[0].absolute_path)}"
        )


def _regular_tree(root: Path) -> tuple[str, dict[str, str]]:
    if root.is_symlink() or not root.is_dir():
        raise QualificationError("execution output root is not a real directory")
    records: list[dict[str, str]] = []
    files: dict[str, str] = {}
    resolved_root = root.resolve(strict=True)
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise QualificationError(f"unexpected output file type: {path}")
        try:
            path.resolve(strict=True).relative_to(resolved_root)
        except ValueError as exc:
            raise QualificationError(
                f"output escaped the private root: {path}"
            ) from exc
        relative = path.relative_to(root).as_posix()
        digest = _sha256(path.read_bytes())
        files[relative] = digest
        records.append({"path": relative, "sha256": digest})
    return _sha256(_canonical_bytes(records)), files


def _run_positive(
    backend: Any,
    schemas: dict[str, dict[str, Any]],
    output_root: Path,
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    observations: list[dict[str, Any]] = []
    for project_type in FIXTURE_TYPES:
        fixture = generated_fixture(project_type)
        result = backend.export_project(fixture, output_root)
        project_dir = Path(result["project_dir"])
        try:
            project_dir.resolve(strict=True).relative_to(
                output_root.resolve(strict=True)
            )
        except ValueError as exc:
            raise QualificationError("backend output escaped its private root") from exc
        calibration = result["outputs"]["calibration.json"]
        road = result["outputs"]["road-network.json"]
        for role in (
            "strict_spatialai_calibration",
            "strict_video_api_calibration",
            "behavior_calibration",
        ):
            _validate_document(calibration, schemas[role], role)
        _validate_document(road, schemas["road_network"], "road_network")
        for value in (calibration, road):
            if not all(
                not isinstance(item, float) or math.isfinite(item)
                for item in _walk_scalars(value)
            ):
                raise QualificationError("output contains a non-finite number")
        input_ids = (
            [camera["id"] for camera in fixture["cameras"]]
            if project_type == "mtmc"
            else [fixture["camera"]["id"]]
        )
        output_ids = [sensor["id"] for sensor in calibration["sensors"]]
        if input_ids != output_ids:
            raise QualificationError("sensor IDs do not match generated operator input")
        calibration_path = project_dir / "calibration.json"
        road_path = project_dir / "road-network.json"
        if (
            _strict_json(calibration_path) != calibration
            or _strict_json(road_path) != road
        ):
            raise QualificationError("strict readback differs from the compiled output")
        pair_records = [
            {
                "path": "calibration.json",
                "sha256": _sha256(calibration_path.read_bytes()),
            },
            {"path": "road-network.json", "sha256": _sha256(road_path.read_bytes())},
        ]
        observations.append(
            {
                "fixture_id": f"generated-operator-{project_type}-v1",
                "project_type": project_type,
                "legal_output_calibration_type": fixture["calibration_type"],
                "input_sha256": _sha256(_canonical_bytes(fixture)),
                "calibration_sha256": pair_records[0]["sha256"],
                "road_network_sha256": pair_records[1]["sha256"],
                "output_pair_sha256": _sha256(_canonical_bytes(pair_records)),
                "sensor_ids": output_ids,
                "schema_roles_passed": sorted(SCHEMA_PATHS),
                "strict_readback": True,
                "provider_identity": "thor-clean-room-provider-free-v1",
            }
        )
    tree_sha256, files = _regular_tree(output_root)
    return observations, tree_sha256, files


def _walk_scalars(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _walk_scalars(child)]
    if isinstance(value, list):
        return [item for child in value for item in _walk_scalars(child)]
    return [value]


def _run_adjacent_negatives(
    backend: Any, schemas: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    cases: list[tuple[str, dict[str, Any], str]] = []
    roi = generated_fixture("geo")
    roi["rois"][0]["points"] = roi["rois"][0]["points"][:7]
    cases.append(("geo-seven-point-roi", roi, "needs 8"))
    provider = generated_fixture("cartesian")
    provider["provider"] = "google_maps"
    cases.append(("external-provider-rejected", provider, "provider-free"))
    traversal = generated_fixture("image")
    traversal["project_id"] = "../escape"
    cases.append(("traversal-project-id-rejected", traversal, "plain identifier"))
    illegal_mtmc = generated_fixture("mtmc")
    illegal_mtmc["calibration_type"] = "mtmc"
    cases.append(("mtmc-illegal-output-type", illegal_mtmc, "cartesian, image, or geo"))
    duplicate = generated_fixture("mtmc")
    duplicate["cameras"][1]["id"] = duplicate["cameras"][0]["id"]
    cases.append(("mtmc-duplicate-sensor-id", duplicate, "camera ids must be unique"))

    observed: list[dict[str, Any]] = []
    for case_id, fixture, message in cases:
        try:
            backend.compile_project(fixture)
        except backend.CalibrationError as exc:
            if message not in str(exc):
                raise QualificationError(f"unexpected rejection for {case_id}") from exc
        else:
            raise QualificationError(f"adjacent invalid case was accepted: {case_id}")
        observed.append({"case_id": case_id, "rejected": True})

    calibration, road = backend.compile_project(generated_fixture("geo"))
    missing = deepcopy(calibration)
    del missing["version"]
    rejected_by = []
    for role in (
        "strict_spatialai_calibration",
        "strict_video_api_calibration",
        "behavior_calibration",
    ):
        if list(Draft7Validator(schemas[role]).iter_errors(missing)):
            rejected_by.append(role)
    if len(rejected_by) != 3:
        raise QualificationError(
            "missing calibration field was not rejected by all schemas"
        )
    observed.append(
        {
            "case_id": "calibration-missing-required-version",
            "rejected": True,
            "rejected_by": rejected_by,
        }
    )
    bad_road = deepcopy(road)
    bad_road["warehouse_sample_bundle"] = True
    if not list(Draft7Validator(schemas["road_network"]).iter_errors(bad_road)):
        raise QualificationError("strict road schema accepted an unknown field")
    observed.append(
        {
            "case_id": "road-network-unknown-field",
            "rejected": True,
            "rejected_by": ["road_network"],
        }
    )
    return observed


def execute() -> dict[str, Any]:
    contract = _load_contract()
    source_hashes = _verify_source_locks(contract)
    binding_hashes = _verify_binding(contract)
    schemas = {
        role: _strict_json(_repo_file(path)) for role, path in SCHEMA_PATHS.items()
    }
    for schema in schemas.values():
        Draft7Validator.check_schema(schema)
    schema_contract = _schema_contract(schemas)
    if schema_contract != contract["schema_contract"]:
        raise QualificationError("schema semantic contract drift")
    backend = _load_backend()

    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="vss-calibration-schema-static-") as raw:
        temporary_path = Path(raw)
        if (
            temporary_path.is_symlink()
            or stat.S_IMODE(temporary_path.stat().st_mode) & 0o077
        ):
            raise QualificationError("temporary root is not private")
        first, first_tree, first_files = _run_positive(
            backend, schemas, temporary_path / "run-a"
        )
        second, second_tree, second_files = _run_positive(
            backend, schemas, temporary_path / "run-b"
        )
        if first != second or first_tree != second_tree or first_files != second_files:
            raise QualificationError("two independent executions are not deterministic")
        if (
            first != contract["fixture_locks"]
            or first_tree != contract["run_tree_sha256"]
        ):
            raise QualificationError("deterministic fixture/output lock drift")
        negatives = _run_adjacent_negatives(backend, schemas)
        if [row["case_id"] for row in negatives] != contract["adjacent_negative_ids"]:
            raise QualificationError("adjacent-negative denominator drift")
        exact_file_count = len(first_files) + len(second_files)
        if exact_file_count != 16:
            raise QualificationError("unexpected output file count")
    if temporary_path is None or temporary_path.exists():
        raise QualificationError("executor-owned temporary root was not removed")

    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": contract["mode"],
        "policy": contract["policy"],
        "binding": {
            **contract["binding"],
            "owner_type_observed": "global_acceptance_vector",
            "canonical_state_advanced": False,
        },
        "source_hashes": source_hashes,
        "binding_hashes": binding_hashes,
        "schema_contract": schema_contract,
        "fixtures": first,
        "adjacent_negatives": negatives,
        "determinism": {
            "independent_runs": 2,
            "run_tree_sha256": first_tree,
            "byte_identical": True,
        },
        "confinement": {
            "generated_inputs_in_memory": True,
            "private_temporary_root": True,
            "exact_regular_output_files": exact_file_count,
            "symlinks_observed": 0,
            "cleanup_verified": True,
        },
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "result": "candidate_static_pass_non_advancing",
    }
    result_schema = _strict_json(RESULT_SCHEMA_PATH)
    Draft202012Validator.check_schema(result_schema)
    errors = list(Draft202012Validator(result_schema).iter_errors(result))
    if errors:
        raise QualificationError(f"result schema rejection: {errors[0].message}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit compact JSON")
    args = parser.parse_args(argv)
    try:
        result = execute()
    except (QualificationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
