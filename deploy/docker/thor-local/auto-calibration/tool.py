#!/usr/bin/env python3
"""Warehouse-bundle-free Thor qualification for VSS AutoMagicCalib."""

from __future__ import annotations

import argparse
import fractions
import hashlib
import io
import ipaddress
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
DOCKER_ROOT = HERE.parents[1]
INVENTORY_PATH = HERE / "artifact-inventory.json"
UPSTREAM_COMPOSE = DOCKER_ROOT / "services" / "auto-calibration" / "compose.yml"
THOR_COMPOSE = HERE / "compose.yml"
CAMERA_RE = re.compile(r"^cam_(\d{2})\.mp4$")
DEFAULT_FIXTURE_CACHE_ROOT = Path(
    os.environ.get("VSS_AMC_FIXTURE_CACHE_ROOT")
    or os.environ.get("XDG_CACHE_HOME")
    or Path.home() / ".cache"
)
DEFAULT_FIXTURE_FREE_RESERVE_BYTES = 512 * 1024 * 1024
REQUIRED_OPENAPI: dict[str, str] = {
    "/v1/ready": "get",
    "/v1/create_project": "post",
    "/v1/upload_video_files/{project_id}": "post",
    "/v1/config/{project_id}": "post",
    "/v1/upload_alignment/{project_id}": "post",
    "/v1/upload_layout/{project_id}": "post",
    "/v1/upload_gt_file/{project_id}": "post",
    "/v1/upload_focal_length/{project_id}": "post",
    "/v1/verify_project/{project_id}": "post",
    "/v1/calibrate/{project_id}": "post",
    "/v1/stop_calibration/{id}": "post",
    "/v1/get_project_info/{project_id}": "get",
    "/v1/result/{project_id}/evaluation_statistics": "get",
    "/v1/result/{project_id}/overlay_image": "get",
    "/v1/amc/calibrate/{project_id}/log": "get",
    "/v1/calibrate/{project_id}/log/{type}/stream": "get",
    "/v1/vggt/calibrate/{project_id}": "post",
    "/v1/vggt_results/{project_id}/evaluation_statistics": "get",
    "/v1/result/{project_id}/mv3dt_result": "get",
    "/v1/rtsp/capture/{project_id}": "post",
    "/v1/rtsp/capture/{project_id}/{session_id}": "get",
    "/v1/rtsp/capture/{project_id}/{session_id}/ingest": "post",
    "/v1/rtsp/capture/{project_id}/{session_id}/stop": "post",
    "/v1/rtsp/sessions/{project_id}": "get",
    "/v1/rtsp/session/{project_id}/{session_id}": "delete",
    "/v1/delete_project/{id}": "delete",
}


class ValidationError(RuntimeError):
    pass


class Unavailable(RuntimeError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read valid JSON from {path}: {exc}") from exc


def _run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise Unavailable(
            f"required executable is not installed: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise Unavailable(f"command timed out: {command[0]}") from exc


def _docker_inspect(reference: str) -> dict[str, Any] | None:
    result = _run(["docker", "image", "inspect", reference], timeout=20)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        return payload[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise ValidationError(
            f"docker returned malformed inspect data for {reference}"
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_fixture_declaration() -> dict[str, Any]:
    declared = _load_json(INVENTORY_PATH)
    try:
        fixture = declared["fixtures"]["official_amc"]
    except (KeyError, TypeError) as exc:
        raise ValidationError("official AMC fixture declaration is absent") from exc
    required_strings = (
        "repository",
        "commit",
        "repository_path",
        "canonical_url",
        "download_url",
        "filename",
        "cache_relative_path",
        "expected_sha256",
    )
    if any(
        not isinstance(fixture.get(key), str) or not fixture[key]
        for key in required_strings
    ):
        raise ValidationError(
            "official AMC fixture declaration has an empty identity field"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", fixture["commit"]):
        raise ValidationError("official AMC fixture commit is not a full Git commit")
    if not re.fullmatch(r"[0-9a-f]{64}", fixture["expected_sha256"]):
        raise ValidationError("official AMC fixture SHA-256 is invalid")
    if (
        not isinstance(fixture.get("expected_size_bytes"), int)
        or fixture["expected_size_bytes"] <= 0
    ):
        raise ValidationError("official AMC fixture size is invalid")
    if not fixture.get("required_for_base_amc_acceptance"):
        raise ValidationError(
            "official AMC fixture must be required for base AMC acceptance"
        )
    if fixture.get("required_for_service_start"):
        raise ValidationError(
            "official AMC fixture must not be required merely to start AMC"
        )
    expected_download = (
        "https://media.githubusercontent.com/media/"
        f"{fixture['repository']}/{fixture['commit']}/{fixture['repository_path']}"
    )
    if fixture["download_url"] != expected_download:
        raise ValidationError(
            "official AMC fixture download URL is not commit-addressed"
        )
    return fixture


def _official_fixture_path(cache_root: Path, fixture: dict[str, Any]) -> Path:
    relative = Path(fixture["cache_relative_path"])
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValidationError(
            "official AMC fixture cache path must be a safe relative path"
        )
    root = cache_root.expanduser().resolve()
    return root / relative


def _safe_zip_name(info: ZipInfo, label: str) -> None:
    name = info.filename
    pure = PurePosixPath(name)
    path_segments = name[:-1].split("/") if name.endswith("/") else name.split("/")
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in path_segments)
        or (pure.parts and ":" in pure.parts[0])
    ):
        raise ValidationError(f"{label} contains an unsafe member path")
    if info.flag_bits & 0x1:
        raise ValidationError(f"{label} contains an encrypted member")
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        raise ValidationError(f"{label} contains a symbolic-link member")
    if info.is_dir() != name.endswith("/"):
        raise ValidationError(f"{label} contains an ambiguous directory member")
    if info.is_dir() and mode and not stat.S_ISDIR(mode):
        raise ValidationError(f"{label} directory metadata has a non-directory mode")
    if not info.is_dir() and mode and not stat.S_ISREG(mode):
        raise ValidationError(f"{label} file metadata has a non-file mode")


def _zip_member_sha256(archive: ZipFile, info: ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_zip_members(
    archive: ZipFile,
    expected_members: list[dict[str, Any]],
    *,
    label: str,
    expected_count: int,
    expected_uncompressed: int,
    expected_compressed: int,
) -> list[dict[str, Any]]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValidationError(f"{label} contains duplicate member names")
    if len(infos) != expected_count or len(expected_members) != expected_count:
        raise ValidationError(f"{label} member count differs from the content lock")
    if names != [item.get("path") for item in expected_members]:
        raise ValidationError(
            f"{label} membership or member order differs from the content lock"
        )
    if sum(info.file_size for info in infos) != expected_uncompressed:
        raise ValidationError(
            f"{label} uncompressed byte total differs from the content lock"
        )
    if sum(info.compress_size for info in infos) != expected_compressed:
        raise ValidationError(
            f"{label} compressed byte total differs from the content lock"
        )

    observed: list[dict[str, Any]] = []
    for info, expected in zip(infos, expected_members, strict=True):
        _safe_zip_name(info, label)
        kind = "directory" if info.is_dir() else "file"
        mode = f"{((info.external_attr >> 16) & 0xFFFF):06o}"
        crc32 = f"{info.CRC:08x}"
        checks = {
            "kind": kind,
            "size_bytes": info.file_size,
            "compressed_size_bytes": info.compress_size,
            "crc32": crc32,
            "compression_method": info.compress_type,
            "unix_mode": mode,
        }
        for key, actual in checks.items():
            if expected.get(key) != actual:
                raise ValidationError(
                    f"{label} member metadata differs for {info.filename}"
                )
        member_sha256 = _zip_member_sha256(archive, info)
        if expected.get("sha256") != member_sha256:
            raise ValidationError(f"{label} member digest differs for {info.filename}")
        observed.append({"path": info.filename, **checks, "sha256": member_sha256})
    return observed


def _read_bounded_member(
    archive: ZipFile, path: str, maximum: int, label: str
) -> bytes:
    try:
        info = archive.getinfo(path)
    except KeyError as exc:
        raise ValidationError(f"{label} content-oracle member is absent") from exc
    if info.file_size > maximum:
        raise ValidationError(f"{label} content-oracle member exceeds its read bound")
    with archive.open(info, "r") as handle:
        payload = handle.read(maximum + 1)
    if len(payload) > maximum:
        raise ValidationError(f"{label} content-oracle member exceeds its read bound")
    return payload


def _read_member_prefix(archive: ZipFile, path: str, length: int, label: str) -> bytes:
    try:
        info = archive.getinfo(path)
    except KeyError as exc:
        raise ValidationError(f"{label} content-oracle member is absent") from exc
    if info.is_dir() or info.file_size < length:
        raise ValidationError(f"{label} content-oracle member is too short")
    with archive.open(info, "r") as handle:
        return handle.read(length)


def _verify_fixture_content(
    archive: ZipFile, fixture: dict[str, Any]
) -> dict[str, Any]:
    oracle = fixture["archive"]["content_oracle"]

    alignment_oracle = oracle["alignment"]
    alignment_bytes = _read_bounded_member(
        archive, alignment_oracle["path"], 1024 * 1024, "alignment"
    )
    try:
        alignment = json.loads(alignment_bytes)
    except json.JSONDecodeError as exc:
        raise ValidationError("official AMC alignment is not valid JSON") from exc
    if alignment_oracle["json_type"] != "array" or not isinstance(alignment, list):
        raise ValidationError(
            "official AMC alignment root differs from the content oracle"
        )
    if len(alignment) != alignment_oracle["camera_count"]:
        raise ValidationError(
            "official AMC alignment camera count differs from the content oracle"
        )
    points_per_camera = alignment_oracle["points_per_camera"]
    if any(
        not isinstance(points, list)
        or len(points) != points_per_camera
        or any(
            not isinstance(point, list)
            or len(point) != 2
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in point
            )
            for point in points
        )
        for points in alignment
    ):
        raise ValidationError(
            "official AMC alignment point structure differs from the content oracle"
        )

    layout_oracle = oracle["layout"]
    layout_head = _read_member_prefix(archive, layout_oracle["path"], 32, "layout")
    if (
        len(layout_head) < 24
        or layout_head[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    ):
        raise ValidationError("official AMC layout is not a canonical PNG")
    width, height = struct.unpack(">II", layout_head[16:24])
    if (width, height) != (layout_oracle["width"], layout_oracle["height"]):
        raise ValidationError(
            "official AMC layout dimensions differ from the content oracle"
        )

    video_oracle = oracle["videos"]
    if len(video_oracle["paths"]) != video_oracle["count"]:
        raise ValidationError("official AMC video declaration count is inconsistent")
    expected_brand = video_oracle["iso_base_media_brand"].encode("ascii")
    for path in video_oracle["paths"]:
        head = _read_member_prefix(archive, path, 32, "video")
        if len(head) < 12 or head[4:8] != b"ftyp" or head[8:12] != expected_brand:
            raise ValidationError(
                "official AMC video container signature differs from the content oracle"
            )

    ground_truth_oracle = oracle["ground_truth"]
    ground_truth_bytes = _read_bounded_member(
        archive,
        ground_truth_oracle["path"],
        ground_truth_oracle["max_buffer_bytes"],
        "ground-truth ZIP",
    )
    try:
        with ZipFile(io.BytesIO(ground_truth_bytes), "r") as ground_truth:
            ground_truth_members = _verify_zip_members(
                ground_truth,
                ground_truth_oracle["members"],
                label="nested ground-truth ZIP",
                expected_count=ground_truth_oracle["member_count"],
                expected_uncompressed=ground_truth_oracle["total_uncompressed_bytes"],
                expected_compressed=ground_truth_oracle["total_compressed_bytes"],
            )
    except (BadZipFile, LargeZipFile) as exc:
        raise ValidationError(
            "official AMC ground-truth member is not a safe ZIP"
        ) from exc

    return {
        "alignment_camera_count": len(alignment),
        "alignment_points_per_camera": points_per_camera,
        "layout_width": width,
        "layout_height": height,
        "video_count": len(video_oracle["paths"]),
        "video_brand": video_oracle["iso_base_media_brand"],
        "ground_truth_members": ground_truth_members,
    }


def verify_official_fixture(
    cache_root: Path, *, fixture_path: Path | None = None
) -> dict[str, Any]:
    fixture = _official_fixture_declaration()
    target = fixture_path or _official_fixture_path(cache_root, fixture)
    if target.is_symlink():
        raise ValidationError(
            "official AMC fixture cache target must not be a symbolic link"
        )
    if not target.is_file():
        raise Unavailable(f"official AMC fixture is absent: {target}")
    size = target.stat().st_size
    if size != fixture["expected_size_bytes"]:
        raise ValidationError("official AMC fixture size differs from the content lock")
    archive_sha256 = _sha256(target)
    if archive_sha256 != fixture["expected_sha256"]:
        raise ValidationError(
            "official AMC fixture digest differs from the content lock"
        )
    archive_oracle = fixture["archive"]
    try:
        with ZipFile(target, "r") as archive:
            members = _verify_zip_members(
                archive,
                archive_oracle["members"],
                label="official AMC fixture ZIP",
                expected_count=archive_oracle["member_count"],
                expected_uncompressed=archive_oracle["total_uncompressed_bytes"],
                expected_compressed=archive_oracle["total_compressed_bytes"],
            )
            content = _verify_fixture_content(archive, fixture)
    except (BadZipFile, LargeZipFile) as exc:
        raise ValidationError("official AMC fixture is not a safe ZIP") from exc
    return {
        "state": "locked",
        "path": str(target.resolve()),
        "repository": fixture["repository"],
        "commit": fixture["commit"],
        "repository_path": fixture["repository_path"],
        "canonical_url": fixture["canonical_url"],
        "size_bytes": size,
        "sha256": archive_sha256,
        "archive": {
            "member_count": len(members),
            "total_uncompressed_bytes": sum(item["size_bytes"] for item in members),
            "total_compressed_bytes": sum(
                item["compressed_size_bytes"] for item in members
            ),
            "members": members,
        },
        "content": content,
        "extracted": False,
    }


def _download_official_fixture(url: str, target: Path) -> None:
    result = _run(
        [
            "curl",
            "--fail-with-body",
            "--proto",
            "=https",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "20",
            "--max-time",
            "900",
            "--speed-limit",
            "1024",
            "--speed-time",
            "60",
            "--output",
            str(target),
            "--write-out",
            "%{url_effective}\n%{http_code}",
            url,
        ],
        timeout=930,
    )
    if result.returncode != 0:
        raise Unavailable("official AMC fixture download failed")
    output = result.stdout.strip().splitlines()
    if output != [url, "200"]:
        raise ValidationError(
            "official AMC fixture download left the commit-addressed origin"
        )


def stage_official_fixture(
    cache_root: Path, minimum_free_after_bytes: int
) -> dict[str, Any]:
    if minimum_free_after_bytes < 0:
        raise ValidationError("minimum free space after staging cannot be negative")
    fixture = _official_fixture_declaration()
    target = _official_fixture_path(cache_root, fixture)
    if target.is_symlink():
        raise ValidationError(
            "official AMC fixture cache target must not be a symbolic link"
        )
    if target.exists():
        verified = verify_official_fixture(cache_root, fixture_path=target)
        verified["publish_state"] = "already_staged"
        verified["network_used"] = False
        return verified

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    free_before = shutil.disk_usage(target.parent).free
    required_free = fixture["expected_size_bytes"] + minimum_free_after_bytes
    if free_before < required_free:
        raise Unavailable(
            "insufficient free space for atomic official AMC fixture staging: "
            f"need {required_free} bytes, have {free_before}"
        )

    descriptor, temporary_raw = tempfile.mkstemp(
        prefix=f".{fixture['filename']}.", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_raw)
    try:
        _download_official_fixture(fixture["download_url"], temporary)
        verified_temporary = verify_official_fixture(cache_root, fixture_path=temporary)
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, target)
        directory_descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        verified = verify_official_fixture(cache_root, fixture_path=target)
        if verified["sha256"] != verified_temporary["sha256"]:
            raise ValidationError(
                "published official AMC fixture changed after atomic rename"
            )
        verified.update(
            publish_state="downloaded_verified_and_published",
            network_used=True,
            free_bytes_before=free_before,
            minimum_free_after_bytes=minimum_free_after_bytes,
        )
        return verified
    finally:
        temporary.unlink(missing_ok=True)


def inspect_inventory(
    data_root: Path, fixture_cache_root: Path = DEFAULT_FIXTURE_CACHE_ROOT
) -> dict[str, Any]:
    declared = _load_json(INVENTORY_PATH)
    result: dict[str, Any] = {
        "schema_version": declared["schema_version"],
        "vss_release": declared["vss_release"],
        "required_platform": declared["platform"],
        "host_architecture": platform.machine(),
        "images": {},
        "models": {},
        "fixtures": {},
    }
    for name, item in declared["images"].items():
        immutable_ref = item.get("immutable_ref")
        inspect_ref = immutable_ref or item["source_ref"]
        inspected = _docker_inspect(inspect_ref)
        state = "unstaged"
        details: dict[str, Any] = {
            "source_ref": item["source_ref"],
            "immutable_ref": immutable_ref,
            "required": item["required"],
        }
        if inspected is not None:
            details.update(
                image_id=inspected.get("Id"),
                architecture=inspected.get("Architecture"),
                repo_digests=inspected.get("RepoDigests") or [],
                size_bytes=inspected.get("Size"),
            )
            if inspected.get("Architecture") != "arm64":
                state = "wrong_architecture"
            elif not immutable_ref or not item.get("expected_image_id"):
                state = "present_unlocked"
            elif inspected.get("Id") != item["expected_image_id"]:
                state = "digest_mismatch"
            else:
                state = "locked"
        elif immutable_ref is None:
            state = "unstaged_unlocked"
        details["state"] = state
        result["images"][name] = details

    for name, item in declared["models"].items():
        path = data_root / item["relative_path"]
        expected = item.get("expected_sha256")
        details = {
            "path": str(path),
            "required_for_base_amc": item["required_for_base_amc"],
            "required_for_vggt_refinement": item["required_for_vggt_refinement"],
            "expected_sha256": expected,
        }
        if not path.is_file():
            details["state"] = "absent"
        elif expected is None:
            details.update(
                state="present_unlocked",
                actual_sha256=_sha256(path),
                size_bytes=path.stat().st_size,
            )
        else:
            actual = _sha256(path)
            details.update(
                state="locked" if actual == expected else "digest_mismatch",
                actual_sha256=actual,
                size_bytes=path.stat().st_size,
            )
        result["models"][name] = details

    fixture = _official_fixture_declaration()
    fixture_path = _official_fixture_path(fixture_cache_root, fixture)
    fixture_details: dict[str, Any] = {
        "path": str(fixture_path),
        "repository": fixture["repository"],
        "commit": fixture["commit"],
        "repository_path": fixture["repository_path"],
        "expected_size_bytes": fixture["expected_size_bytes"],
        "expected_sha256": fixture["expected_sha256"],
        "required_for_service_start": fixture["required_for_service_start"],
        "required_for_base_amc_acceptance": fixture["required_for_base_amc_acceptance"],
    }
    if not fixture_path.exists() and not fixture_path.is_symlink():
        fixture_details["state"] = "absent"
    else:
        try:
            verified = verify_official_fixture(
                fixture_cache_root, fixture_path=fixture_path
            )
            fixture_details.update(
                state="locked",
                size_bytes=verified["size_bytes"],
                sha256=verified["sha256"],
                member_count=verified["archive"]["member_count"],
            )
        except (Unavailable, ValidationError) as exc:
            fixture_details.update(state="verification_failed", reason=str(exc))
    result["fixtures"]["official_amc"] = fixture_details
    return result


def _parse_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(fractions.Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValidationError(
            f"invalid frame-rate value from ffprobe: {value}"
        ) from exc


def _probe_video(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_frames,start_time,duration:format=start_time,duration",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        raise ValidationError(f"ffprobe rejected {path.name}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        container = payload.get("format", {})
        duration = float(stream.get("duration") or container.get("duration") or 0)
        start_time = float(stream.get("start_time") or container.get("start_time") or 0)
        return {
            "codec": stream.get("codec_name"),
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "fps": _parse_rate(stream.get("avg_frame_rate")),
            "frames": int(stream["nb_frames"])
            if stream.get("nb_frames", "N/A") != "N/A"
            else None,
            "duration_seconds": duration,
            "start_time_seconds": start_time,
        }
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValidationError(
            f"ffprobe returned incomplete video metadata for {path.name}"
        ) from exc


def validate_video_dir(video_dir: Path) -> dict[str, Any]:
    if not video_dir.is_dir():
        raise ValidationError(f"video directory does not exist: {video_dir}")
    candidates = sorted(
        path for path in video_dir.iterdir() if path.suffix.lower() == ".mp4"
    )
    if not candidates:
        raise ValidationError(f"no MP4 files found in {video_dir}")
    names: list[tuple[int, Path]] = []
    unexpected: list[str] = []
    for path in candidates:
        match = CAMERA_RE.match(path.name)
        if match:
            names.append((int(match.group(1)), path))
        else:
            unexpected.append(path.name)
    if unexpected:
        raise ValidationError(
            "MP4 names must be cam_00.mp4, cam_01.mp4, ...; invalid: "
            + ", ".join(unexpected)
        )
    expected_indices = list(range(len(names)))
    actual_indices = [index for index, _ in names]
    if actual_indices != expected_indices:
        raise ValidationError(
            f"camera indices must be contiguous from 00; got {actual_indices}"
        )

    probes = {path.name: _probe_video(path) for _, path in names}
    baseline = probes[names[0][1].name]
    errors: list[str] = []
    for _, path in names[1:]:
        current = probes[path.name]
        for field in ("width", "height"):
            if current[field] != baseline[field]:
                errors.append(f"{path.name} {field} differs from cam_00.mp4")
        if abs(current["fps"] - baseline["fps"]) > 0.01:
            errors.append(f"{path.name} frame rate differs from cam_00.mp4")
        if abs(current["duration_seconds"] - baseline["duration_seconds"]) > 0.1:
            errors.append(
                f"{path.name} duration differs from cam_00.mp4 by more than 100 ms"
            )
        if abs(current["start_time_seconds"] - baseline["start_time_seconds"]) > 0.1:
            errors.append(
                f"{path.name} container start time differs from cam_00.mp4 by more than 100 ms"
            )
    if errors:
        raise ValidationError("; ".join(errors))

    warnings: list[str] = []
    if (baseline["width"], baseline["height"]) != (1920, 1080):
        warnings.append("1920x1080 is recommended for a calibration run")
    if baseline["duration_seconds"] < 120:
        warnings.append(
            "2-3 minutes of moving objects is recommended for a calibration run"
        )
    warnings.append(
        "matching container timing does not prove physical camera synchronization"
    )

    scan_dirs = [video_dir, video_dir.parent]
    attachment_names = {
        "settings": [
            "calibration_settings.json",
            "settings.json",
            "config.json",
            "calibration_config.json",
        ],
        "alignment": ["alignment_data.json"],
        "layout": ["layout.png"],
    }
    attachments: dict[str, list[str]] = {}
    for label, filenames in attachment_names.items():
        hits = sorted(
            {
                str(directory / filename)
                for directory in scan_dirs
                for filename in filenames
                if (directory / filename).is_file()
            }
        )
        attachments[label] = hits
    for raw_path in attachments["settings"]:
        value = _load_json(Path(raw_path))
        if not isinstance(value, dict):
            raise ValidationError(f"settings JSON must contain an object: {raw_path}")
    for raw_path in attachments["alignment"]:
        value = _load_json(Path(raw_path))
        if not isinstance(value, (dict, list)) or not value:
            raise ValidationError(
                f"alignment JSON must contain a non-empty object or array: {raw_path}"
            )
    for raw_path in attachments["layout"]:
        with Path(raw_path).open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValidationError(f"layout is not a PNG: {raw_path}")
    return {
        "mode": "videos",
        "video_dir": str(video_dir.resolve()),
        "camera_count": len(names),
        "videos": probes,
        "attachments": attachments,
        "api_upload_ready": len(attachments["alignment"]) == 1
        and len(attachments["layout"]) == 1,
        "warnings": warnings,
    }


def validate_rtsp_plan(path: Path) -> dict[str, Any]:
    plan = _load_json(path)
    if not isinstance(plan, dict):
        raise ValidationError("RTSP plan must be a JSON object")
    streams = plan.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ValidationError("RTSP plan streams must be a non-empty list")
    duration = plan.get("duration_seconds")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 60:
        raise ValidationError("duration_seconds must be an integer of at least 60")
    names: set[str] = set()
    safe_streams: list[dict[str, Any]] = []
    for index, stream in enumerate(streams):
        if not isinstance(stream, dict):
            raise ValidationError(f"stream {index} must be an object")
        name = stream.get("camera_name")
        raw_url = stream.get("rtsp_url")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"stream {index} has no camera_name")
        if name in names:
            raise ValidationError(f"duplicate camera_name: {name}")
        names.add(name)
        if not isinstance(raw_url, str):
            raise ValidationError(f"stream {name} has no rtsp_url")
        try:
            parsed = urllib.parse.urlsplit(raw_url)
            hostname = parsed.hostname
        except ValueError as exc:
            raise ValidationError(f"stream {name} must use a valid RTSP URL") from exc
        if parsed.scheme not in {"rtsp", "rtsps"} or not hostname:
            raise ValidationError(
                f"stream {name} must use a valid rtsp:// or rtsps:// URL"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValidationError(f"stream {name} has an invalid RTSP port") from exc
        safe_streams.append(
            {
                "camera_name": name,
                "scheme": parsed.scheme,
                "host_present": True,
                "port": port,
                "credentials_present": parsed.username is not None
                or parsed.password is not None,
                "sensor_id_present": stream.get("sensor_id") is not None,
            }
        )
    attachments: dict[str, str | None] = {}
    for key, kind in (
        ("settings_json", "json"),
        ("alignment_json", "json"),
        ("layout_png", "png"),
    ):
        raw_path = plan.get(key)
        if raw_path is None:
            attachments[key] = None
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValidationError(f"{key} must be a non-empty local path")
        attachment = Path(raw_path).expanduser()
        if not attachment.is_absolute():
            attachment = path.parent / attachment
        if not attachment.is_file():
            raise ValidationError(f"{key} does not exist: {attachment}")
        if kind == "json":
            value = _load_json(attachment)
            if key == "settings_json" and not isinstance(value, dict):
                raise ValidationError(f"{key} must contain a JSON object: {attachment}")
            if key == "alignment_json" and (
                not isinstance(value, (dict, list)) or not value
            ):
                raise ValidationError(
                    f"{key} must contain a non-empty JSON object or array: {attachment}"
                )
        else:
            with attachment.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValidationError(f"{key} is not a PNG: {attachment}")
        attachments[key] = str(attachment.resolve())
    return {
        "mode": "rtsp",
        "plan": str(path.resolve()),
        "duration_seconds": duration,
        "camera_count": len(streams),
        "streams": safe_streams,
        "attachments": attachments,
        "api_upload_ready": attachments["alignment_json"] is not None
        and attachments["layout_png"] is not None,
        "warnings": [
            "URL credentials are intentionally redacted",
            "reachability is checked only during GET-only qualification",
        ],
    }


def create_fixture(output: Path, seconds: int, size: str, fps: int) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValidationError(f"fixture output must be absent or empty: {output}")
    if seconds < 1 or seconds > 30:
        raise ValidationError("fixture duration must be between 1 and 30 seconds")
    if not re.fullmatch(r"\d{2,4}x\d{2,4}", size):
        raise ValidationError("fixture size must look like WIDTHxHEIGHT")
    output.mkdir(parents=True, exist_ok=True)
    for index, hue in enumerate((0, 60)):
        target = output / f"cam_{index:02d}.mp4"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={size}:rate={fps}:duration={seconds}",
            "-vf",
            f"hue=h={hue}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(target),
        ]
        result = _run(command, timeout=90)
        if result.returncode != 0:
            raise Unavailable(
                f"ffmpeg could not create {target.name}: {result.stderr.strip()}"
            )
    metadata = {
        "scope": "media-contract preflight only; not an AMC accuracy or completion fixture",
        "camera_count": 2,
        "duration_seconds": seconds,
        "resolution": size,
        "fps": fps,
        "limitations": [
            "too short for calibration",
            "no real multi-view parallax",
            "no alignment_data.json or layout.png",
        ],
    }
    (output / "fixture.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return {"fixture_dir": str(output.resolve()), **metadata}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _local_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _get_json(url: str, label: str, timeout: float) -> tuple[int, Any]:
    request = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json"}
    )
    try:
        with _local_opener().open(request, timeout=timeout) as response:
            body = response.read(8 * 1024 * 1024)
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        raise ValidationError(f"{label} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Unavailable(f"{label} is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} did not return JSON") from exc


def _get_status(url: str, label: str, timeout: float) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with _local_opener().open(request, timeout=timeout) as response:
            response.read(1024)
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Unavailable(f"{label} is unavailable") from exc


def _numeric_loopback_origin(raw: str, label: str, allowed_paths: set[str]) -> str:
    """Return a sanitized origin or fail before any network request.

    Error text intentionally never contains ``raw`` because it may include a
    password even when URL parsing itself fails.
    """
    if (
        not isinstance(raw, str)
        or not raw
        or raw.strip() != raw
        or any(ord(char) < 33 or ord(char) == 127 for char in raw)
    ):
        raise ValidationError(f"{label} must be a valid numeric loopback origin")
    try:
        parsed = urllib.parse.urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{label} must be a valid numeric loopback origin"
        ) from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError(f"{label} must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(f"{label} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValidationError(f"{label} must not contain a query or fragment")
    if parsed.path not in allowed_paths:
        raise ValidationError(f"{label} contains an unsupported path")
    if hostname is None or "%" in hostname:
        raise ValidationError(f"{label} must use a numeric loopback address")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ValidationError(f"{label} must use a numeric loopback address") from exc
    if not address.is_loopback:
        raise ValidationError(f"{label} must use a numeric loopback address")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    authority = f"{host}:{port}" if port is not None else host
    return f"{parsed.scheme}://{authority}"


def _normalized_openapi_path(path: str) -> str:
    return re.sub(r"\{[^{}]+\}", "{}", path.rstrip("/"))


def _missing_openapi_operations(openapi_paths: dict[str, Any]) -> list[str]:
    available: dict[str, set[str]] = {}
    for path, methods in openapi_paths.items():
        if not isinstance(path, str) or not isinstance(methods, dict):
            continue
        normalized = _normalized_openapi_path(path)
        available.setdefault(normalized, set()).update(
            str(method).lower() for method in methods
        )
    missing = []
    for path, method in REQUIRED_OPENAPI.items():
        if method not in available.get(_normalized_openapi_path(path), set()):
            missing.append(f"{method.upper()} {path}")
    return missing


def qualify_runtime(
    backend_url: str, ui_url: str, vios_url: str | None, timeout: float
) -> dict[str, Any]:
    backend_origin = _numeric_loopback_origin(
        backend_url, "AMC backend origin", {"", "/", "/v1", "/v1/"}
    )
    ui_origin = _numeric_loopback_origin(ui_url, "AMC UI origin", {"", "/"})
    vios_origin = (
        _numeric_loopback_origin(vios_url, "VIOS origin", {"", "/"})
        if vios_url is not None
        else None
    )
    backend = f"{backend_origin}/v1"
    ready_status, ready = _get_json(
        f"{backend}/ready", "AMC readiness endpoint", timeout
    )
    if ready_status != 200 or not isinstance(ready, dict) or ready.get("code") != 0:
        raise ValidationError("AMC readiness contract did not return code 0")
    openapi_status, openapi = _get_json(
        f"{backend_origin}/openapi.json", "AMC OpenAPI endpoint", timeout
    )
    if (
        openapi_status != 200
        or not isinstance(openapi, dict)
        or not isinstance(openapi.get("paths"), dict)
    ):
        raise ValidationError("AMC OpenAPI document is missing paths")
    missing = _missing_openapi_operations(openapi["paths"])
    if missing:
        raise ValidationError("AMC OpenAPI contract is missing: " + ", ".join(missing))
    ui_status = _get_status(f"{ui_origin}/", "AMC UI endpoint", timeout)
    if ui_status != 200:
        raise ValidationError(f"AMC UI returned HTTP {ui_status}")
    result: dict[str, Any] = {
        "backend_ready": True,
        "openapi_required_operations": len(REQUIRED_OPENAPI),
        "ui_http_status": ui_status,
        "method": "GET-only",
    }
    if vios_origin:
        vios_status, sensors = _get_json(
            f"{vios_origin}/vst/api/v1/sensor/list",
            "VIOS sensor-list endpoint",
            timeout,
        )
        if vios_status != 200:
            raise ValidationError(f"VIOS sensor list returned HTTP {vios_status}")
        result["vios_sensor_list_reachable"] = isinstance(sensors, (dict, list))
    return result


def _assert_base_artifacts(inventory: dict[str, Any], require_vggt: bool) -> None:
    if inventory["host_architecture"] not in {"aarch64", "arm64"}:
        raise ValidationError(
            f"Thor lane requires ARM64; host is {inventory['host_architecture']}"
        )
    bad = [
        name
        for name, item in inventory["images"].items()
        if item["required"] and item["state"] != "locked"
    ]
    if bad:
        raise Unavailable(
            "required images are not staged and content-locked: " + ", ".join(bad)
        )
    if require_vggt and inventory["models"]["vggt"]["state"] != "locked":
        raise Unavailable(
            "VGGT refinement requested but vggt_1B_commercial.pt is not content-locked"
        )


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    inventory = inspect_inventory(args.data_root, args.fixture_cache_root)
    inputs = (
        validate_video_dir(args.input)
        if args.mode == "videos"
        else validate_rtsp_plan(args.input)
    )
    _assert_base_artifacts(inventory, args.require_vggt)
    projects = args.projects_dir
    if not projects.is_dir():
        raise Unavailable(f"projects directory is absent: {projects}")
    if not os.access(projects, os.W_OK | os.X_OK):
        raise Unavailable(
            f"projects directory is not writable by the current user: {projects}"
        )
    if not inputs["api_upload_ready"]:
        raise Unavailable(
            "input is valid, but alignment_data.json and layout.png are required before API upload"
        )
    return {
        "inventory": inventory,
        "inputs": inputs,
        "projects_dir": str(projects.resolve()),
        "warnings": [
            "current-user writability does not replace the post-start container UID 1000 write test"
        ],
        "state": "ready_for_user_authorized_launch",
    }


def print_plan(data_root: Path, fixture_cache_root: Path) -> dict[str, Any]:
    inventory = inspect_inventory(data_root, fixture_cache_root)
    backend = inventory["images"]["backend"]
    ui = inventory["images"]["ui"]
    official_fixture = inventory["fixtures"]["official_amc"]
    return {
        "scope": "standalone AMC backend and UI; no warehouse sample bundle",
        "compose_files": [str(UPSTREAM_COMPOSE), str(THOR_COMPOSE)],
        "backend_image": backend,
        "ui_image": ui,
        "official_fixture": official_fixture,
        "base_modes": ["custom synchronized MP4", "RTSP capture through VIOS"],
        "base_amc_requires_vggt": False,
        "official_fixture_requires_warehouse_bundle": False,
        "launch_policy": "no lifecycle action is performed; preflight must pass before an operator runs compose with --pull never --no-build",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("VSS_DATA_DIR", DOCKER_ROOT / "data-dir")),
        help="VSS data root (default: VSS_DATA_DIR or deploy/docker/data-dir)",
    )
    parser.add_argument(
        "--fixture-cache-root",
        type=Path,
        default=DEFAULT_FIXTURE_CACHE_ROOT,
        help="external cache root for the content-locked official AMC fixture",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "inventory", help="inspect declared artifacts without network access"
    )
    subparsers.add_parser("plan", help="show the warehouse-bundle-free standalone lane")
    subparsers.add_parser(
        "verify-official-fixture",
        help="offline verification of the content-locked official AMC fixture",
    )
    stage_fixture = subparsers.add_parser(
        "stage-official-fixture",
        help="download, verify, and atomically publish the commit-addressed official AMC fixture",
    )
    stage_fixture.add_argument(
        "--minimum-free-after-bytes",
        type=int,
        default=DEFAULT_FIXTURE_FREE_RESERVE_BYTES,
        help="minimum bytes that must remain free after the atomic fixture download",
    )

    videos = subparsers.add_parser(
        "validate-videos", help="validate custom synchronized MP4 containers"
    )
    videos.add_argument("input", type=Path)
    rtsp = subparsers.add_parser(
        "validate-rtsp", help="validate and redact a custom RTSP JSON plan"
    )
    rtsp.add_argument("input", type=Path)

    fixture = subparsers.add_parser(
        "fixture", help="create a tiny media-contract-only fixture"
    )
    fixture.add_argument("output", type=Path)
    fixture.add_argument("--seconds", type=int, default=6)
    fixture.add_argument("--size", default="640x360")
    fixture.add_argument("--fps", type=int, default=15)

    pf = subparsers.add_parser(
        "preflight", help="fail closed before any operator-authorized launch"
    )
    pf.add_argument("--mode", choices=("videos", "rtsp"), required=True)
    pf.add_argument("--input", type=Path, required=True)
    pf.add_argument(
        "--projects-dir",
        type=Path,
        default=DOCKER_ROOT / "services" / "auto-calibration" / "projects",
    )
    pf.add_argument("--require-vggt", action="store_true")

    qualify = subparsers.add_parser(
        "qualify", help="run GET-only readiness and API-contract probes"
    )
    qualify.add_argument("--backend-url", default="http://127.0.0.1:8010/v1")
    qualify.add_argument("--ui-url", default="http://127.0.0.1:5000")
    qualify.add_argument(
        "--vios-url", help="also verify VIOS sensor-list reachability for RTSP mode"
    )
    qualify.add_argument("--timeout", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            payload = inspect_inventory(args.data_root, args.fixture_cache_root)
        elif args.command == "plan":
            payload = print_plan(args.data_root, args.fixture_cache_root)
        elif args.command == "verify-official-fixture":
            payload = verify_official_fixture(args.fixture_cache_root)
        elif args.command == "stage-official-fixture":
            payload = stage_official_fixture(
                args.fixture_cache_root, args.minimum_free_after_bytes
            )
        elif args.command == "validate-videos":
            payload = validate_video_dir(args.input)
        elif args.command == "validate-rtsp":
            payload = validate_rtsp_plan(args.input)
        elif args.command == "fixture":
            payload = create_fixture(args.output, args.seconds, args.size, args.fps)
        elif args.command == "preflight":
            payload = preflight(args)
        elif args.command == "qualify":
            payload = qualify_runtime(
                args.backend_url, args.ui_url, args.vios_url, args.timeout
            )
        else:  # pragma: no cover
            raise AssertionError(args.command)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Unavailable as exc:
        print(
            json.dumps({"state": "unavailable", "reason": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2
    except ValidationError as exc:
        print(
            json.dumps({"state": "failed", "reason": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
