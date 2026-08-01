#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Provider-free legacy manual/GIS calibration core for Thor.

This clean-room slice implements bounded project validation, a 3x3 planar
homography solve, ROI/tripwire/road-link validation, and deterministic export.
It is not the proprietary legacy UI and never contacts a map provider.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

MAX_INPUT_BYTES = 1_048_576
MAX_POINTS = 256
MIN_ROI_POINTS = 8
EPSILON = 1e-10
LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[3]
CALIBRATION_SCHEMAS = (
    REPO_ROOT
    / "libs/analytics/spatialai-data-utils/spatialai_data_utils/schemas/calibration.json",
    REPO_ROOT
    / "services/analytics/behavior-analytics/src/mdx/analytics/core/transform/calibration/schemas/calibration.schema.json",
)
ROAD_NETWORK_SCHEMA = (
    REPO_ROOT
    / "services/analytics/video-analytics-api/src/web-api-core/schemas/ajv/roadNetwork.json"
)
ALLOWED_TOP_COMMON = {
    "schema_version",
    "project_id",
    "project_type",
    "provider",
    "calibration_type",
    "osm_url",
    "road_city",
    "road_intersection",
    "rois",
    "tripwires",
    "road_links",
}
ALLOWED_CAMERA = {
    "id",
    "image_size",
    "correspondences",
    "origin",
    "geo_location",
    "coordinates",
    "scale_factor",
    "attributes",
    "place",
}
ALLOWED_CORRESPONDENCE = {"image", "world"}
ALLOWED_GEOMETRY = {"id", "points"}
ALLOWED_TRIPWIRE = {"id", "points", "direction"}
ALLOWED_ROAD_LINK = {"id", "direction", "points"}
CARDINAL_DIRECTIONS = {"E", "W", "N", "S"}


class CalibrationError(ValueError):
    """The project is unsafe, incomplete, or geometrically unsolvable."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CalibrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_project(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CalibrationError("project input must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise CalibrationError("project input exceeds the one MiB bound")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                CalibrationError(f"non-finite JSON number: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationError("project input is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CalibrationError("project root must be an object")
    return value


def _plain_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 64):
        raise CalibrationError(f"{label} must be a bounded string")
    if not value[0].isalnum() or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise CalibrationError(f"{label} must be a plain identifier")
    return value


def _bounded_text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    minimum = 0 if allow_empty else 1
    if not isinstance(value, str) or not (minimum <= len(value) <= 10_000):
        raise CalibrationError(f"{label} must be a bounded string")
    return value


def _finite_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise CalibrationError(f"{label} must be a finite number")
    return float(value)


def _exact_coordinates(
    value: Any,
    label: str,
    first: str,
    second: str,
    *,
    first_bounds: tuple[float, float] | None = None,
    second_bounds: tuple[float, float] | None = None,
) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {first, second}:
        raise CalibrationError(f"{label} must contain exactly {first} and {second}")
    result = {
        first: _finite_number(value[first], f"{label}.{first}"),
        second: _finite_number(value[second], f"{label}.{second}"),
    }
    for key, bounds in ((first, first_bounds), (second, second_bounds)):
        if bounds is not None and not bounds[0] <= result[key] <= bounds[1]:
            raise CalibrationError(f"{label}.{key} is outside its allowed range")
    return result


def _name_value_rows(
    value: Any, label: str, *, allow_empty_value: bool
) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 64:
        raise CalibrationError(f"{label} must be a bounded array")
    result = []
    names: set[str] = set()
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {"name", "value"}:
            raise CalibrationError(f"{label}[{index}] has unknown or missing fields")
        name = _bounded_text(row["name"], f"{label}[{index}].name")
        item_value = _bounded_text(
            row["value"],
            f"{label}[{index}].value",
            allow_empty=allow_empty_value,
        )
        if name in names:
            raise CalibrationError(f"duplicate {label} name: {name}")
        names.add(name)
        result.append({"name": name, "value": item_value})
    return result


def _point(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise CalibrationError(f"{label} must contain exactly two coordinates")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in value
    ):
        raise CalibrationError(f"{label} coordinates must be finite numbers")
    return float(value[0]), float(value[1])


def _geometry(rows: Any, label: str, minimum: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 64:
        raise CalibrationError(f"{label} must be a bounded array")
    seen: set[str] = set()
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != ALLOWED_GEOMETRY:
            raise CalibrationError(f"{label}[{index}] has unknown or missing fields")
        identifier = _plain_id(row["id"], f"{label}[{index}].id")
        points = row["points"]
        if not isinstance(points, list) or not (minimum <= len(points) <= MAX_POINTS):
            raise CalibrationError(
                f"{label}[{index}] needs {minimum}..{MAX_POINTS} points"
            )
        normalized = [_point(point, f"{label}[{index}].points") for point in points]
        if identifier in seen:
            raise CalibrationError(f"duplicate {label} id: {identifier}")
        if len(set(normalized)) < minimum:
            raise CalibrationError(f"{label}[{index}] points must be distinct")
        seen.add(identifier)
        result.append({"id": identifier, "points": [[x, y] for x, y in normalized]})
    return result


def _tripwires(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 64:
        raise CalibrationError("tripwires must be a bounded array")
    seen: set[str] = set()
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != ALLOWED_TRIPWIRE:
            raise CalibrationError(f"tripwires[{index}] has unknown or missing fields")
        identifier = _plain_id(row["id"], f"tripwires[{index}].id")
        points = row["points"]
        if not isinstance(points, list) or not (2 <= len(points) <= MAX_POINTS):
            raise CalibrationError(f"tripwires[{index}] needs 2..{MAX_POINTS} points")
        normalized = [_point(point, f"tripwires[{index}].points") for point in points]
        direction = row["direction"]
        if not isinstance(direction, list) or len(direction) != 2:
            raise CalibrationError(
                f"tripwires[{index}].direction needs exactly two points"
            )
        normalized_direction = [
            _point(point, f"tripwires[{index}].direction") for point in direction
        ]
        if identifier in seen:
            raise CalibrationError(f"duplicate tripwires id: {identifier}")
        if len(set(normalized)) < 2 or len(set(normalized_direction)) < 2:
            raise CalibrationError(
                f"tripwires[{index}] line and direction points must be distinct"
            )
        seen.add(identifier)
        result.append(
            {
                "id": identifier,
                "points": [[x, y] for x, y in normalized],
                "direction": [[x, y] for x, y in normalized_direction],
            }
        )
    return result


def _road_links(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > 64:
        raise CalibrationError("road_links must be a bounded array")
    seen: set[str] = set()
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != ALLOWED_ROAD_LINK:
            raise CalibrationError(f"road_links[{index}] has unknown or missing fields")
        identifier = _plain_id(row["id"], f"road_links[{index}].id")
        direction = row["direction"]
        if direction not in CARDINAL_DIRECTIONS:
            raise CalibrationError(
                f"road_links[{index}].direction must be E, W, N, or S"
            )
        points = row["points"]
        if not isinstance(points, list) or not (2 <= len(points) <= MAX_POINTS):
            raise CalibrationError(f"road_links[{index}] needs 2..{MAX_POINTS} points")
        normalized = []
        for point_index, point in enumerate(points):
            if not isinstance(point, dict) or set(point) != {"lat", "lon", "alt"}:
                raise CalibrationError(
                    f"road_links[{index}].points[{point_index}] must contain lat, lon, and alt"
                )
            normalized.append(
                {
                    **_exact_coordinates(
                        {"lat": point["lat"], "lon": point["lon"]},
                        f"road_links[{index}].points[{point_index}]",
                        "lat",
                        "lon",
                        first_bounds=(-90, 90),
                        second_bounds=(-180, 180),
                    ),
                    "alt": _finite_number(
                        point["alt"], f"road_links[{index}].points[{point_index}].alt"
                    ),
                }
            )
        coordinates = {
            (point["lat"], point["lon"], point["alt"]) for point in normalized
        }
        if len(coordinates) < 2:
            raise CalibrationError(f"road_links[{index}] points must be distinct")
        if identifier in seen:
            raise CalibrationError(f"duplicate road_links id: {identifier}")
        seen.add(identifier)
        result.append({"id": identifier, "direction": direction, "points": normalized})
    return result


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= EPSILON:
            raise CalibrationError("correspondences do not define a unique homography")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * selected
                for current, selected in zip(
                    augmented[row], augmented[column], strict=True
                )
            ]
    return [augmented[row][-1] for row in range(size)]


def solve_homography(
    correspondences: list[dict[str, Any]],
) -> tuple[list[list[float]], float]:
    if not (4 <= len(correspondences) <= MAX_POINTS):
        raise CalibrationError("homography needs 4..256 correspondences")
    rows: list[list[float]] = []
    values: list[float] = []
    normalized: list[tuple[float, float, float, float]] = []
    for index, item in enumerate(correspondences):
        if not isinstance(item, dict) or set(item) != ALLOWED_CORRESPONDENCE:
            raise CalibrationError(
                f"correspondence[{index}] has unknown or missing fields"
            )
        x, y = _point(item["image"], f"correspondence[{index}].image")
        world_x, world_y = _point(item["world"], f"correspondence[{index}].world")
        rows.extend(
            [
                [x, y, 1.0, 0.0, 0.0, 0.0, -world_x * x, -world_x * y],
                [0.0, 0.0, 0.0, x, y, 1.0, -world_y * x, -world_y * y],
            ]
        )
        values.extend([world_x, world_y])
        normalized.append((x, y, world_x, world_y))
    # Least squares via normal equations. The bounded project size and pivot
    # checks make this deterministic and fail closed for degenerate inputs.
    normal = [
        [sum(row[i] * row[j] for row in rows) for j in range(8)] for i in range(8)
    ]
    rhs = [
        sum(row[i] * value for row, value in zip(rows, values, strict=True))
        for i in range(8)
    ]
    solution = _solve_linear(normal, rhs)
    homography = [solution[0:3], solution[3:6], [solution[6], solution[7], 1.0]]
    squared_errors = []
    for x, y, expected_x, expected_y in normalized:
        denominator = homography[2][0] * x + homography[2][1] * y + 1.0
        if abs(denominator) <= EPSILON:
            raise CalibrationError("homography projects a correspondence to infinity")
        actual_x = (
            homography[0][0] * x + homography[0][1] * y + homography[0][2]
        ) / denominator
        actual_y = (
            homography[1][0] * x + homography[1][1] * y + homography[1][2]
        ) / denominator
        squared_errors.append(
            (actual_x - expected_x) ** 2 + (actual_y - expected_y) ** 2
        )
    rms = math.sqrt(sum(squared_errors) / len(squared_errors))
    if not math.isfinite(rms) or rms > 1e-5:
        raise CalibrationError(
            "homography reprojection error exceeds the clean-room bound"
        )
    return [[round(value, 12) for value in row] for row in homography], rms


def _compile_camera(
    camera: Any,
    rois: list[dict[str, Any]],
    tripwires: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(camera, dict) or set(camera) != ALLOWED_CAMERA:
        raise CalibrationError("camera has unknown or missing fields")
    camera_id = _plain_id(camera["id"], "camera.id")
    size = camera["image_size"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            isinstance(item, bool)
            or not isinstance(item, int)
            or item <= 0
            or item > 16384
            for item in size
        )
    ):
        raise CalibrationError(
            "camera.image_size must contain two bounded positive integers"
        )
    homography, rms = solve_homography(camera["correspondences"])
    origin = _exact_coordinates(
        camera["origin"],
        "camera.origin",
        "lat",
        "lng",
        first_bounds=(-90, 90),
        second_bounds=(-180, 180),
    )
    geo_location = _exact_coordinates(
        camera["geo_location"],
        "camera.geo_location",
        "lat",
        "lng",
        first_bounds=(-90, 90),
        second_bounds=(-180, 180),
    )
    coordinates = _exact_coordinates(
        camera["coordinates"], "camera.coordinates", "x", "y"
    )
    if any(abs(value) > 999_999 for value in coordinates.values()):
        raise CalibrationError(
            "camera.coordinates must be within the VSS schema bounds"
        )
    scale_factor = _finite_number(camera["scale_factor"], "camera.scale_factor")
    if scale_factor <= 0:
        raise CalibrationError("camera.scale_factor must be positive")
    attributes = _name_value_rows(
        camera["attributes"], "camera.attributes", allow_empty_value=True
    )
    reserved_attributes = {
        "frameWidth": str(size[0]),
        "frameHeight": str(size[1]),
        "providerAlternateIdentity": "thor-clean-room-provider-free-v1",
        "reprojectionRms": format(rms, ".12g"),
    }
    if set(reserved_attributes).intersection(item["name"] for item in attributes):
        raise CalibrationError("camera.attributes uses a reserved clean-room name")
    attributes.extend(
        {"name": name, "value": value} for name, value in reserved_attributes.items()
    )
    place = _name_value_rows(camera["place"], "camera.place", allow_empty_value=False)

    output_rois = [
        {
            "id": roi["id"],
            "roiCoordinates": [
                {"x": point[0], "y": point[1]} for point in roi["points"]
            ],
        }
        for roi in rois
    ]
    output_tripwires = []
    for tripwire in tripwires:
        output_tripwires.append(
            {
                "id": tripwire["id"],
                "wire": {
                    f"p{index}": {"x": point[0], "y": point[1]}
                    for index, point in enumerate(tripwire["points"], start=1)
                },
                "direction": {
                    f"p{index}": {"x": point[0], "y": point[1]}
                    for index, point in enumerate(tripwire["direction"], start=1)
                },
            }
        )
    return {
        "id": camera_id,
        "type": "camera",
        "origin": origin,
        "geoLocation": geo_location,
        "coordinates": coordinates,
        "scaleFactor": scale_factor,
        "attributes": attributes,
        "place": place,
        "homography": homography,
        "imageCoordinates": [
            {"x": item["image"][0], "y": item["image"][1]}
            for item in camera["correspondences"]
        ],
        "globalCoordinates": [
            {"x": item["world"][0], "y": item["world"][1]}
            for item in camera["correspondences"]
        ],
        "rois": output_rois,
        "tripwires": output_tripwires,
    }


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot load locked VSS schema: {path}") from exc
    Draft7Validator.check_schema(schema)
    return schema


def _validate_output(value: dict[str, Any], path: Path, label: str) -> None:
    errors = sorted(
        Draft7Validator(_load_schema(path)).iter_errors(value),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        location = "/".join(str(part) for part in errors[0].absolute_path) or "$"
        raise CalibrationError(
            f"{label} violates the locked VSS schema at {location}: {errors[0].message}"
        )


def compile_project(project: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    project_type = project.get("project_type")
    normalized_type = {"manual": "cartesian", "gis": "geo"}.get(
        project_type, project_type
    )
    if normalized_type not in {"cartesian", "image", "geo", "mtmc"}:
        raise CalibrationError("project_type must be cartesian, image, geo, or mtmc")
    camera_key = "cameras" if normalized_type == "mtmc" else "camera"
    if set(project) != ALLOWED_TOP_COMMON | {camera_key}:
        raise CalibrationError("project has unknown or missing fields")
    if project["schema_version"] != 1:
        raise CalibrationError("unsupported project schema version")
    _plain_id(project["project_id"], "project_id")
    if project["provider"] != "local_coordinate_plane":
        raise CalibrationError(
            "only the provider-free local coordinate plane is allowed"
        )
    calibration_type = project["calibration_type"]
    if calibration_type not in {"cartesian", "image", "geo"}:
        raise CalibrationError("calibration_type must be cartesian, image, or geo")
    if normalized_type != "mtmc" and calibration_type != normalized_type:
        raise CalibrationError(
            "calibration_type must match the single-camera project type"
        )
    osm_url = _bounded_text(project["osm_url"], "osm_url", allow_empty=True)
    road_city = _bounded_text(project["road_city"], "road_city")
    road_intersection = _bounded_text(project["road_intersection"], "road_intersection")
    rois = _geometry(project["rois"], "rois", MIN_ROI_POINTS)
    tripwires = _tripwires(project["tripwires"])
    road_links = _road_links(project["road_links"])
    if calibration_type == "geo" and (not rois or not road_links):
        raise CalibrationError("GIS projects need at least one ROI and road link")
    if calibration_type != "geo" and road_links:
        raise CalibrationError("only GIS projects may contain road links")

    if normalized_type == "mtmc":
        cameras = project["cameras"]
        if not isinstance(cameras, list) or not (2 <= len(cameras) <= 16):
            raise CalibrationError("mtmc projects need 2..16 cameras")
    else:
        cameras = [project["camera"]]
    sensors = [_compile_camera(camera, rois, tripwires) for camera in cameras]
    sensor_ids = [sensor["id"] for sensor in sensors]
    if len(sensor_ids) != len(set(sensor_ids)):
        raise CalibrationError("camera ids must be unique")

    calibration = {
        "version": "1.0",
        "osmURL": osm_url,
        "calibrationType": calibration_type,
        "sensors": sensors,
    }
    road_network = {
        "city": road_city,
        "docType": "roadNetwork",
        "intersections": [
            {
                "name": road_intersection,
                "segments": [
                    {
                        "id": link["id"],
                        "direction": link["direction"],
                        "start": link["points"][0],
                        "end": link["points"][-1],
                        "points": link["points"],
                    }
                    for link in road_links
                ],
            }
        ],
    }
    for schema_path in CALIBRATION_SCHEMAS:
        _validate_output(calibration, schema_path, "calibration.json")
    _validate_output(road_network, ROAD_NETWORK_SCHEMA, "road-network.json")
    return calibration, road_network


def export_project(project: dict[str, Any], output_root: Path) -> dict[str, Any]:
    calibration, road_network = compile_project(project)
    if output_root.is_symlink():
        raise CalibrationError("output root must not be a symlink")
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    project_dir = output_root / project["project_id"]
    try:
        project_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CalibrationError(
            "project output already exists; overwrite is forbidden"
        ) from exc
    outputs = {"calibration.json": calibration, "road-network.json": road_network}
    for name, value in outputs.items():
        path = project_dir / name
        encoded = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    readback = {name: load_project(project_dir / name) for name in outputs}
    if readback != outputs:
        raise CalibrationError("export readback differs from compiled project")
    return {"project_dir": str(project_dir), "outputs": readback}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = export_project(load_project(args.project), args.output_root)
    except (CalibrationError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
