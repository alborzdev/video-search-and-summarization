#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate operator-owned, synchronized MV3DT inputs without changing them."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import subprocess

import yaml


DATASET = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SAMPLE_DATASET = "warehouse-4cams-20mx20m-synthetic"
DETECTOR_MODEL = "rtdetr_warehouse_v1.0.2.fp16.onnx"
BODYPOSE_MODEL = "bodypose3dnet_accuracy.onnx"
SUPPORTED_CODECS = {"h264", "hevc"}
MAX_DURATION_DRIFT_SECONDS = 0.10
MAX_START_DRIFT_SECONDS = 0.10


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a custom 2-7 camera MV3DT input directory."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser.parse_args()


def regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{label} must be a regular, non-symlink file: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"{label} is empty: {path}")


def expected_camera_ids(count: int) -> list[str]:
    return ["Camera", *(f"Camera_{index:02d}" for index in range(1, count))]


def finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(finite_number(component) for component in value)
    )


def finite_point(value: object, axes: tuple[str, ...]) -> bool:
    return (
        isinstance(value, dict)
        and all(axis in value and finite_number(value[axis]) for axis in axes)
    )


def probe_video(ffprobe: str, path: Path) -> dict[str, object]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,nb_frames:format=start_time,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        document = json.loads(result.stdout)
    except FileNotFoundError as error:
        raise SystemExit(f"ffprobe command is missing: {ffprobe}") from error
    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise SystemExit(f"ffprobe failed for {path}: {detail.strip()}") from error

    streams = document.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise SystemExit(f"expected exactly one primary video stream: {path}")
    stream = streams[0]
    media_format = document.get("format", {})
    try:
        codec = str(stream["codec_name"])
        width = int(stream["width"])
        height = int(stream["height"])
        rate = Fraction(str(stream["avg_frame_rate"]))
        frames = int(stream["nb_frames"])
        start = float(media_format["start_time"])
        duration = float(media_format["duration"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise SystemExit(
            f"video lacks deterministic fps/frame-count/timeline metadata: {path}"
        ) from error
    if codec not in SUPPORTED_CODECS:
        raise SystemExit(f"unsupported video codec {codec!r} in {path}; use H.264 or H.265/HEVC")
    if min(width, height, frames, duration, float(rate)) <= 0:
        raise SystemExit(f"invalid video geometry or timeline metadata: {path}")
    return {
        "codec": codec,
        "width": width,
        "height": height,
        "rate": rate,
        "frames": frames,
        "start": start,
        "duration": duration,
    }


def validate_sync(probes: dict[str, dict[str, object]]) -> None:
    first_id = next(iter(probes))
    baseline = probes[first_id]
    for camera_id, probe in probes.items():
        if probe["rate"] != baseline["rate"]:
            raise SystemExit(
                f"videos are not synchronized: {camera_id} fps {probe['rate']} "
                f"does not match {first_id} fps {baseline['rate']}"
            )
        if probe["frames"] != baseline["frames"]:
            raise SystemExit(
                f"videos are not synchronized: {camera_id} frame count {probe['frames']} "
                f"does not match {first_id} frame count {baseline['frames']}"
            )
        if abs(float(probe["start"]) - float(baseline["start"])) > MAX_START_DRIFT_SECONDS:
            raise SystemExit(f"videos are not synchronized: {camera_id} start time differs by >100 ms")
        if abs(float(probe["duration"]) - float(baseline["duration"])) > MAX_DURATION_DRIFT_SECONDS:
            raise SystemExit(f"videos are not synchronized: {camera_id} duration differs by >100 ms")


def main() -> int:
    args = arguments()
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        raise SystemExit("--input-dir must be absolute")
    if input_dir.is_symlink() or not input_dir.is_dir():
        raise SystemExit(f"input directory must be a non-symlink directory: {input_dir}")
    if not DATASET.fullmatch(args.dataset):
        raise SystemExit("--dataset must be a 1-63 character lowercase kebab-case slug")
    if args.dataset == SAMPLE_DATASET:
        raise SystemExit(
            f"the bundled sample slug {SAMPLE_DATASET!r} is excluded; use an operator dataset slug"
        )

    detector = input_dir / "models/mtmc" / DETECTOR_MODEL
    bodypose = input_dir / "models/mv3dt/BodyPose3DNet" / BODYPOSE_MODEL
    regular_file(detector, "RT-DETR ONNX")
    regular_file(bodypose, "BodyPose3DNet ONNX")

    calibration_dir = input_dir / "calibration" / args.dataset
    calibration_path = calibration_dir / "calibration.json"
    regular_file(calibration_path, "calibration.json")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid calibration JSON: {calibration_path}: {error}") from error
    sensors = calibration.get("sensors")
    if not isinstance(sensors, list) or not 2 <= len(sensors) <= 7:
        raise SystemExit("calibration.json sensors[] must contain 2-7 cameras for AGX-THOR MV3DT")
    sensor_ids = [sensor.get("id") if isinstance(sensor, dict) else None for sensor in sensors]
    expected_ids = expected_camera_ids(len(sensors))
    if sensor_ids != expected_ids:
        raise SystemExit(
            "calibration sensor IDs must be ordered exactly as " + ", ".join(expected_ids)
        )
    for sensor in sensors:
        assert isinstance(sensor, dict)
        camera_id = str(sensor["id"])
        group = sensor.get("group")
        region = sensor.get("region")
        place = sensor.get("place")
        coordinates = sensor.get("coordinates")
        image_coordinates = sensor.get("imageCoordinates")
        if not isinstance(group, dict) or not group.get("name"):
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty group")
        if not finite_vector(group.get("origin"), 2):
            raise SystemExit(f"calibration sensor {camera_id} needs finite group.origin [x,y]")
        if not finite_vector(group.get("dimensions"), 4):
            raise SystemExit(
                f"calibration sensor {camera_id} needs four finite group.dimensions values"
            )
        if not isinstance(region, dict) or not region:
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty region")
        if not isinstance(place, list) or not place:
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty place list")
        if not finite_point(coordinates, ("x", "y")):
            raise SystemExit(f"calibration sensor {camera_id} needs finite coordinates.x/y")
        if (
            not isinstance(image_coordinates, list)
            or len(image_coordinates) < 4
            or not all(finite_point(point, ("x", "y")) for point in image_coordinates)
        ):
            raise SystemExit(
                f"calibration sensor {camera_id} needs at least four finite imageCoordinates x/y"
            )
        global_coordinates = sensor.get("globalCoordinates")
        if (
            not isinstance(global_coordinates, list)
            or not global_coordinates
            or not all(finite_point(point, ("x", "y", "z")) for point in global_coordinates)
        ):
            raise SystemExit(
                f"calibration sensor {camera_id} needs non-empty finite globalCoordinates x/y/z"
            )

    video_dir = input_dir / "videos" / args.dataset
    if video_dir.is_symlink() or not video_dir.is_dir():
        raise SystemExit(f"video directory is missing or is a symlink: {video_dir}")
    videos = sorted(video_dir.glob("*.mp4"))
    if [path.stem for path in videos] != expected_ids:
        raise SystemExit(
            "MP4 names must match calibration sensors exactly, with no extras: "
            + ", ".join(f"{camera}.mp4" for camera in expected_ids)
        )
    probes: dict[str, dict[str, object]] = {}
    for camera_id, path in zip(expected_ids, videos, strict=True):
        regular_file(path, f"video for {camera_id}")
        probes[camera_id] = probe_video(args.ffprobe, path)
    validate_sync(probes)

    caminfo_dir = calibration_dir / "camInfo"
    if caminfo_dir.is_symlink() or not caminfo_dir.is_dir():
        raise SystemExit(f"camInfo directory is missing or is a symlink: {caminfo_dir}")
    caminfo_files = sorted((*caminfo_dir.glob("*.yml"), *caminfo_dir.glob("*.yaml")))
    if sorted(path.stem for path in caminfo_files) != sorted(expected_ids):
        raise SystemExit(
            "camInfo names must match calibration sensors exactly, with one YAML per camera"
        )
    for path in caminfo_files:
        regular_file(path, f"camInfo for {path.stem}")
        try:
            caminfo = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise SystemExit(f"invalid camInfo YAML for {path.stem}: {path}: {error}") from error
        if not isinstance(caminfo, dict):
            raise SystemExit(f"camInfo for {path.stem} must be a YAML mapping: {path}")
        if not finite_vector(caminfo.get("projectionMatrix_3x4_w2p"), 12):
            raise SystemExit(
                f"camInfo for {path.stem} needs finite projectionMatrix_3x4_w2p[12]: {path}"
            )

    images = calibration_dir / "images"
    regular_file(images / "Top.png", "top-view image")
    metadata_path = images / "imageMetadata.json"
    regular_file(metadata_path, "top-view image metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid top-view image metadata JSON: {metadata_path}: {error}") from error
    if not isinstance(metadata, dict) or not isinstance(metadata.get("images"), list):
        raise SystemExit(f"top-view image metadata must contain images[]: {metadata_path}")
    if not any(
        isinstance(image, dict)
        and image.get("fileName") == "Top.png"
        and image.get("view") == "plan-view"
        for image in metadata["images"]
    ):
        raise SystemExit("imageMetadata.json must declare Top.png as a plan-view image")

    first = probes[expected_ids[0]]
    summary = {
        "dataset": args.dataset,
        "streams": len(expected_ids),
        "sensor_ids": expected_ids,
        "codec": first["codec"],
        "fps": str(first["rate"]),
        "frames": first["frames"],
        "duration_seconds": first["duration"],
        "agx_thor_cap": 7,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
