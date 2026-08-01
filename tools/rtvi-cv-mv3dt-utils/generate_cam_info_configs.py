# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List


SAFE_SENSOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ModelInfoEntry:
    class_id: int
    height_raw: str
    radius_raw: str


def _parse_positive_float_token(token: str, field_name: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} value '{token}'. Must be numeric."
        ) from exc
    if not math.isfinite(value):
        raise ValueError(f"Invalid {field_name} value '{token}'. Must be finite.")
    if value <= 0:
        raise ValueError(f"Invalid {field_name} value '{token}'. Must be positive.")
    return value


def _validate_model_entries(
    model_entries: Iterable[ModelInfoEntry],
) -> List[ModelInfoEntry]:
    entries = list(model_entries)
    if not entries:
        raise ValueError("At least one object model class is required.")

    seen_class_ids: set[int] = set()
    for entry in entries:
        if (
            not isinstance(entry, ModelInfoEntry)
            or isinstance(entry.class_id, bool)
            or not isinstance(entry.class_id, int)
        ):
            raise ValueError("Each model entry must have an integer classID.")
        if entry.class_id < 0:
            raise ValueError("classID must be non-negative.")
        if entry.class_id in seen_class_ids:
            raise ValueError(f"Duplicate classID '{entry.class_id}'.")
        seen_class_ids.add(entry.class_id)
        _parse_positive_float_token(entry.height_raw, "height")
        _parse_positive_float_token(entry.radius_raw, "radius")
    return entries


def _parse_model_args(model_args: List[List[str]]) -> List[ModelInfoEntry]:
    entries: List[ModelInfoEntry] = []
    for triple in model_args:
        class_id_raw, height_raw, radius_raw = triple
        try:
            class_id = int(class_id_raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid classID value '{class_id_raw}'. classID must be an integer."
            ) from exc

        entries.append(
            ModelInfoEntry(
                class_id=class_id, height_raw=height_raw, radius_raw=radius_raw
            )
        )
    return _validate_model_entries(entries)


def _reject_symlinked_path_components(path: Path, field_name: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError(
                f"{field_name} must not be a symlink or contain a symlink component: {component}"
            )


def _format_number(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError(
            "Boolean value found where numeric projection matrix entry was expected."
        )
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite projection matrix entry is not allowed.")
        return repr(value)
    raise ValueError(
        f"Unsupported projection matrix entry type: {type(value).__name__}"
    )


def _flatten_camera_matrix(camera_matrix: Any, sensor_id: str) -> List[str]:
    if not isinstance(camera_matrix, list) or len(camera_matrix) != 3:
        raise ValueError(
            f"Sensor '{sensor_id}' has invalid cameraMatrix shape; expected 3x4."
        )

    flattened: List[str] = []
    for row in camera_matrix:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(
                f"Sensor '{sensor_id}' has invalid cameraMatrix shape; expected 3x4."
            )
        for value in row:
            flattened.append(_format_number(value))
    return flattened


def _render_cam_info_yaml(
    flattened_projection: Iterable[str], model_entries: List[ModelInfoEntry]
) -> str:
    lines = ["projectionMatrix_3x4_w2p:"]
    for value in flattened_projection:
        lines.append(f"- {value}")

    lines.append("")
    lines.append("modelInfo:")
    for entry in model_entries:
        lines.append(f"  - classID: {entry.class_id}")
        lines.append(f"    height: {entry.height_raw}")
        lines.append(f"    radius: {entry.radius_raw}")

    lines.append("")
    return "\n".join(lines)


def generate_cam_info_files(
    calibration_json: Path, output_dir: Path, model_entries: List[ModelInfoEntry]
) -> int:
    model_entries = _validate_model_entries(model_entries)
    with calibration_json.open("r", encoding="utf-8") as fh:
        calibration = json.load(fh)

    sensors = calibration.get("sensors")
    if not isinstance(sensors, list):
        raise ValueError("calibration.json does not contain a valid 'sensors' list.")

    prepared: List[tuple[str, str]] = []
    seen_sensor_ids: set[str] = set()
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        if sensor.get("type") != "camera":
            continue

        sensor_id = sensor.get("id")
        camera_matrix = sensor.get("cameraMatrix")
        if not isinstance(sensor_id, str) or not sensor_id:
            raise ValueError("Encountered camera sensor with missing/invalid 'id'.")
        if (
            sensor_id in {".", ".."}
            or not SAFE_SENSOR_ID.fullmatch(sensor_id)
            or "/" in sensor_id
            or "\\" in sensor_id
        ):
            raise ValueError(
                f"Sensor id '{sensor_id}' is unsafe; use letters, digits, '.', '_', or '-'."
            )
        if sensor_id in seen_sensor_ids:
            raise ValueError(f"Duplicate camera sensor id '{sensor_id}'.")
        seen_sensor_ids.add(sensor_id)
        if camera_matrix is None:
            raise ValueError(f"Sensor '{sensor_id}' is missing 'cameraMatrix'.")

        flattened_projection = _flatten_camera_matrix(camera_matrix, sensor_id)
        rendered_yaml = _render_cam_info_yaml(flattened_projection, model_entries)

        prepared.append((sensor_id, rendered_yaml))

    if not prepared:
        raise ValueError("No camera sensors found in calibration.json.")

    _reject_symlinked_path_components(output_dir, "Output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlinked_path_components(output_dir, "Output directory")
    output_paths = [output_dir / f"{sensor_id}.yml" for sensor_id, _ in prepared]
    for out_path in output_paths:
        if out_path.is_symlink():
            raise ValueError(f"Refusing to overwrite symlink output: {out_path}")
    for (_, rendered_yaml), out_path in zip(prepared, output_paths, strict=True):
        out_path.write_text(rendered_yaml, encoding="utf-8")

    return len(prepared)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate camInfo YAML files from calibration.json and repeated "
            "(classID height radius) model triples."
        )
    )
    parser.add_argument(
        "--calibration-json",
        type=Path,
        required=True,
        help="Path to input calibration.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where camera YAML files will be written.",
    )
    parser.add_argument(
        "--class",
        dest="class_args",
        action="append",
        nargs=3,
        metavar=("CLASS_ID", "HEIGHT", "RADIUS"),
        required=True,
        help=(
            "Class tuple: classID height radius. "
            "Repeat this argument for each object class."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_entries = _parse_model_args(args.class_args)
    generated_count = generate_cam_info_files(
        calibration_json=args.calibration_json,
        output_dir=args.output_dir,
        model_entries=model_entries,
    )
    print(f"Generated {generated_count} camInfo files in: {args.output_dir}")


if __name__ == "__main__":
    main()
