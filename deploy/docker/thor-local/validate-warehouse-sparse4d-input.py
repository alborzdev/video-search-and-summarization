#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate a synchronized, operator-owned Sparse4D warehouse dataset."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import zlib

import numpy as np
import onnx


DATASET = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SAMPLE_DATASET = "warehouse-4cams-20mx20m-synthetic"
MODEL = "sparse4d_warehouse_v2.2.onnx"
ANCHOR = "_ov_kmeans900_v2.2.npy"
CAMERAS = ["Camera", "Camera_01", "Camera_02", "Camera_03"]
SUPPORTED_CODECS = {"h264", "hevc"}
MAX_TIMELINE_DRIFT_SECONDS = 0.10


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a custom four-camera Sparse4D input directory."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--model-dir")
    parser.add_argument("--video-dir")
    parser.add_argument("--calibration-dir")
    return parser.parse_args()


def regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{label} must be a regular, non-symlink file: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"{label} is empty: {path}")


def asset_directory(
    input_dir: Path, configured: str | None, default: Path, label: str
) -> Path:
    path = Path(configured) if configured is not None else input_dir / default
    if not path.is_absolute():
        raise SystemExit(f"--{label}-dir must be absolute")
    try:
        relative = path.relative_to(input_dir)
    except ValueError as error:
        raise SystemExit(f"{label} directory must remain inside --input-dir: {path}") from error
    if ".." in relative.parts:
        raise SystemExit(f"{label} directory must remain inside --input-dir: {path}")
    cursor = input_dir
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            raise SystemExit(f"{label} directory path must not contain symlinks: {cursor}")
    if not path.is_dir():
        raise SystemExit(f"{label} directory is missing: {path}")
    symlinks = [candidate for candidate in path.rglob("*") if candidate.is_symlink()]
    if symlinks:
        raise SystemExit(f"{label} asset tree must not contain symlinks: {symlinks[0]}")
    return path


def png_scanline_lengths(
    width: int, height: int, bit_depth: int, channels: int, interlace: int
) -> list[int]:
    if interlace == 0:
        return [((width * channels * bit_depth + 7) // 8) + 1] * height
    passes = (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    )
    lengths: list[int] = []
    for x_start, y_start, x_step, y_step in passes:
        pass_width = max(0, (width - x_start + x_step - 1) // x_step)
        pass_height = max(0, (height - y_start + y_step - 1) // y_step)
        if pass_width and pass_height:
            row_length = ((pass_width * channels * bit_depth + 7) // 8) + 1
            lengths.extend([row_length] * pass_height)
    return lengths


def validate_png(path: Path) -> None:
    regular_file(path, "top-view image")
    try:
        document = path.read_bytes()
    except OSError as error:
        raise SystemExit(f"top-view image cannot be read: {path}: {error}") from error
    if len(document) > 64 * 1024 * 1024:
        raise SystemExit(f"top-view image exceeds the 64 MiB validation limit: {path}")
    if not document.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit(f"top-view image is not a decodable PNG (bad signature): {path}")

    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(document):
        if len(document) - offset < 12:
            raise SystemExit(f"top-view image is not a decodable PNG (truncated chunk): {path}")
        length = struct.unpack(">I", document[offset : offset + 4])[0]
        chunk_type = document[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(document):
            raise SystemExit(f"top-view image is not a decodable PNG (truncated data): {path}")
        payload = document[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", document[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise SystemExit(f"top-view image is not a decodable PNG (bad CRC): {path}")
        chunks.append((chunk_type, payload))
        offset = end
        if chunk_type == b"IEND":
            break
    if offset != len(document) or not chunks or chunks[0][0] != b"IHDR":
        raise SystemExit(f"top-view image is not a decodable PNG (invalid chunk order): {path}")
    if chunks[-1] != (b"IEND", b""):
        raise SystemExit(f"top-view image is not a decodable PNG (missing IEND): {path}")
    if sum(chunk_type == b"IHDR" for chunk_type, _ in chunks) != 1:
        raise SystemExit(f"top-view image is not a decodable PNG (invalid IHDR): {path}")

    header = chunks[0][1]
    if len(header) != 13:
        raise SystemExit(f"top-view image is not a decodable PNG (invalid IHDR): {path}")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    formats = {
        0: ({1, 2, 4, 8, 16}, 1),
        2: ({8, 16}, 3),
        3: ({1, 2, 4, 8}, 1),
        4: ({8, 16}, 2),
        6: ({8, 16}, 4),
    }
    if (
        width == 0
        or height == 0
        or color_type not in formats
        or bit_depth not in formats[color_type][0]
        or compression != 0
        or filtering != 0
        or interlace not in (0, 1)
    ):
        raise SystemExit(f"top-view image is not a decodable PNG (unsupported IHDR): {path}")
    if color_type == 3 and not any(chunk_type == b"PLTE" for chunk_type, _ in chunks):
        raise SystemExit(f"top-view image is not a decodable PNG (missing palette): {path}")
    compressed = b"".join(payload for chunk_type, payload in chunks if chunk_type == b"IDAT")
    if not compressed:
        raise SystemExit(f"top-view image is not a decodable PNG (missing IDAT): {path}")
    row_lengths = png_scanline_lengths(
        width, height, bit_depth, formats[color_type][1], interlace
    )
    expected_size = sum(row_lengths)
    if expected_size > 256 * 1024 * 1024:
        raise SystemExit(f"top-view image decoded size exceeds 256 MiB: {path}")
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(compressed, expected_size + 1)
        if decompressor.unconsumed_tail or len(pixels) > expected_size:
            raise SystemExit(
                f"top-view image is not a decodable PNG (excess pixel data): {path}"
            )
        pixels += decompressor.flush(expected_size - len(pixels) + 1)
    except zlib.error as error:
        raise SystemExit(f"top-view image is not a decodable PNG (invalid IDAT): {path}") from error
    if not decompressor.eof or decompressor.unused_data or len(pixels) != expected_size:
        raise SystemExit(f"top-view image is not a decodable PNG (wrong pixel size): {path}")
    row_offset = 0
    for row_length in row_lengths:
        if pixels[row_offset] > 4:
            raise SystemExit(f"top-view image is not a decodable PNG (invalid filter): {path}")
        row_offset += row_length


def finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(finite_number(component) for component in value)
    )


def finite_matrix(value: object, rows: int, columns: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == rows
        and all(finite_vector(row, columns) for row in value)
    )


def finite_point(value: object, axes: tuple[str, ...]) -> bool:
    return (
        isinstance(value, dict)
        and all(axis in value and finite_number(value[axis]) for axis in axes)
    )


def validate_model(path: Path) -> None:
    regular_file(path, "Sparse4D ONNX")
    try:
        model = onnx.load(path, load_external_data=False)
        onnx.checker.check_model(model)
    except Exception as error:  # onnx exposes multiple protobuf/checker errors
        raise SystemExit(f"Sparse4D ONNX is not a valid self-contained ONNX model: {error}") from error
    if not model.graph.node or not model.graph.input or not model.graph.output:
        raise SystemExit("Sparse4D ONNX graph must have nodes, inputs, and outputs")
    external = [
        tensor.name
        for tensor in model.graph.initializer
        if tensor.data_location == onnx.TensorProto.EXTERNAL
    ]
    if external:
        raise SystemExit("Sparse4D ONNX uses unsupported external tensor data: " + ", ".join(external))


def validate_anchor(path: Path) -> None:
    regular_file(path, "Sparse4D kmeans anchor")
    try:
        anchor = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise SystemExit(f"Sparse4D kmeans anchor is not a safe NPY array: {error}") from error
    if anchor.shape != (900, 11):
        raise SystemExit(
            f"Sparse4D kmeans anchor shape must be (900, 11), got {anchor.shape}"
        )
    if anchor.dtype not in (np.dtype("float32"), np.dtype("float64")):
        raise SystemExit(f"Sparse4D kmeans anchor must be float32/float64, got {anchor.dtype}")
    if not np.isfinite(anchor).all():
        raise SystemExit("Sparse4D kmeans anchor contains non-finite values")


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
    if not math.isfinite(start) or not math.isfinite(duration):
        raise SystemExit(f"video has non-finite timeline metadata: {path}")
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
    baseline_id = CAMERAS[0]
    baseline = probes[baseline_id]
    for camera_id, probe in probes.items():
        for field in ("codec", "width", "height", "rate", "frames"):
            if probe[field] != baseline[field]:
                raise SystemExit(
                    f"videos are not synchronized: {camera_id} {field} {probe[field]} "
                    f"does not match {baseline_id} {field} {baseline[field]}"
                )
        if abs(float(probe["start"]) - float(baseline["start"])) > MAX_TIMELINE_DRIFT_SECONDS:
            raise SystemExit(f"videos are not synchronized: {camera_id} start time differs by >100 ms")
        if abs(float(probe["duration"]) - float(baseline["duration"])) > MAX_TIMELINE_DRIFT_SECONDS:
            raise SystemExit(f"videos are not synchronized: {camera_id} duration differs by >100 ms")


def validate_calibration(calibration: object, probes: dict[str, dict[str, object]]) -> None:
    if not isinstance(calibration, dict):
        raise SystemExit("calibration.json root must be an object")
    sensors = calibration.get("sensors")
    if not isinstance(sensors, list) or len(sensors) != 4:
        raise SystemExit("Sparse4D calibration.json must contain exactly four sensors")
    ids = [sensor.get("id") if isinstance(sensor, dict) else None for sensor in sensors]
    if ids != CAMERAS:
        raise SystemExit("calibration sensor IDs must be ordered exactly as " + ", ".join(CAMERAS))
    group_names: set[str] = set()
    for sensor in sensors:
        assert isinstance(sensor, dict)
        camera_id = str(sensor["id"])
        if sensor.get("type") != "camera":
            raise SystemExit(f"calibration sensor {camera_id} type must be camera")
        group = sensor.get("group")
        if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"]:
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty BEV group")
        group_names.add(group["name"])
        if group.get("type") != "bev":
            raise SystemExit(f"calibration sensor {camera_id} group.type must be bev")
        if not finite_vector(group.get("origin"), 2) or not finite_vector(group.get("dimensions"), 4):
            raise SystemExit(f"calibration sensor {camera_id} needs finite BEV group origin/dimensions")
        if not finite_point(sensor.get("coordinates"), ("x", "y")):
            raise SystemExit(f"calibration sensor {camera_id} needs finite coordinates.x/y")
        if not finite_point(sensor.get("translationToGlobalCoordinates"), ("x", "y")):
            raise SystemExit(
                f"calibration sensor {camera_id} needs finite translationToGlobalCoordinates.x/y"
            )
        if not finite_number(sensor.get("scaleFactor")) or float(sensor["scaleFactor"]) <= 0:
            raise SystemExit(f"calibration sensor {camera_id} needs a positive finite scaleFactor")
        if not finite_matrix(sensor.get("cameraMatrix"), 3, 4):
            raise SystemExit(f"calibration sensor {camera_id} needs finite cameraMatrix[3][4]")
        if not finite_matrix(sensor.get("intrinsicMatrix"), 3, 3):
            raise SystemExit(f"calibration sensor {camera_id} needs finite intrinsicMatrix[3][3]")
        if not finite_matrix(sensor.get("extrinsicMatrix"), 3, 4):
            raise SystemExit(f"calibration sensor {camera_id} needs finite extrinsicMatrix[3][4]")
        if not finite_matrix(sensor.get("homography"), 3, 3):
            raise SystemExit(f"calibration sensor {camera_id} needs finite homography[3][3]")
        image_coordinates = sensor.get("imageCoordinates")
        global_coordinates = sensor.get("globalCoordinates")
        if (
            not isinstance(image_coordinates, list)
            or len(image_coordinates) < 4
            or not all(finite_point(point, ("x", "y")) for point in image_coordinates)
        ):
            raise SystemExit(f"calibration sensor {camera_id} needs finite imageCoordinates")
        if (
            not isinstance(global_coordinates, list)
            or len(global_coordinates) != len(image_coordinates)
            or not all(finite_point(point, ("x", "y", "z")) for point in global_coordinates)
        ):
            raise SystemExit(
                f"calibration sensor {camera_id} needs matching finite globalCoordinates"
            )
        if not isinstance(sensor.get("region"), dict) or not sensor["region"]:
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty region")
        if not isinstance(sensor.get("place"), list) or not sensor["place"]:
            raise SystemExit(f"calibration sensor {camera_id} needs a non-empty place list")
        attributes = sensor.get("attributes")
        if not isinstance(attributes, list):
            raise SystemExit(f"calibration sensor {camera_id} needs attributes[]")
        values = {
            item.get("name"): item.get("value")
            for item in attributes
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        probe = probes[camera_id]
        expected = {
            "fps": str(int(probe["rate"])) if probe["rate"].denominator == 1 else str(probe["rate"]),
            "frameWidth": str(probe["width"]),
            "frameHeight": str(probe["height"]),
        }
        for key, value in expected.items():
            if str(values.get(key, "")) != value:
                raise SystemExit(
                    f"calibration sensor {camera_id} attribute {key} must match video ({value})"
                )
    if len(group_names) != 1:
        raise SystemExit("all four Sparse4D cameras must belong to one BEV group")


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

    model_dir = asset_directory(
        input_dir, args.model_dir, Path("models/sparse4d/ov"), "model"
    )
    validate_model(model_dir / MODEL)
    validate_anchor(model_dir / ANCHOR)

    video_dir = asset_directory(
        input_dir, args.video_dir, Path("videos") / args.dataset, "video"
    )
    videos = sorted(video_dir.glob("*.mp4"))
    if [path.stem for path in videos] != CAMERAS:
        raise SystemExit(
            "MP4 names must match the exact four-camera Sparse4D contract, with no extras: "
            + ", ".join(f"{camera}.mp4" for camera in CAMERAS)
        )
    probes: dict[str, dict[str, object]] = {}
    for camera_id, path in zip(CAMERAS, videos, strict=True):
        regular_file(path, f"video for {camera_id}")
        probes[camera_id] = probe_video(args.ffprobe, path)
    validate_sync(probes)

    calibration_dir = asset_directory(
        input_dir,
        args.calibration_dir,
        Path("calibration") / args.dataset,
        "calibration",
    )
    calibration_path = calibration_dir / "calibration.json"
    regular_file(calibration_path, "calibration.json")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid calibration JSON: {calibration_path}: {error}") from error
    validate_calibration(calibration, probes)

    images = calibration_dir / "images"
    validate_png(images / "Top.png")
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

    first = probes[CAMERAS[0]]
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "streams": 4,
                "sensor_ids": CAMERAS,
                "codec": first["codec"],
                "width": first["width"],
                "height": first["height"],
                "fps": str(first["rate"]),
                "frames": first["frames"],
                "duration_seconds": first["duration"],
                "agx_thor_cap": 7,
                "sparse4d_contract": "four synchronized cameras",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
