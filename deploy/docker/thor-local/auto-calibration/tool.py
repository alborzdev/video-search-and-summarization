#!/usr/bin/env python3
"""Sample-free, pull-free Thor qualification for VSS AutoMagicCalib."""

from __future__ import annotations

import argparse
import fractions
import hashlib
import ipaddress
import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DOCKER_ROOT = HERE.parents[1]
INVENTORY_PATH = HERE / "artifact-inventory.json"
UPSTREAM_COMPOSE = DOCKER_ROOT / "services" / "auto-calibration" / "compose.yml"
THOR_COMPOSE = HERE / "compose.yml"
CAMERA_RE = re.compile(r"^cam_(\d{2})\.mp4$")
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
        raise Unavailable(f"required executable is not installed: {command[0]}") from exc
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
        raise ValidationError(f"docker returned malformed inspect data for {reference}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_inventory(data_root: Path) -> dict[str, Any]:
    declared = _load_json(INVENTORY_PATH)
    result: dict[str, Any] = {
        "schema_version": declared["schema_version"],
        "vss_release": declared["vss_release"],
        "required_platform": declared["platform"],
        "host_architecture": platform.machine(),
        "images": {},
        "models": {},
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
    return result


def _parse_rate(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(fractions.Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValidationError(f"invalid frame-rate value from ffprobe: {value}") from exc


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
            "frames": int(stream["nb_frames"]) if stream.get("nb_frames", "N/A") != "N/A" else None,
            "duration_seconds": duration,
            "start_time_seconds": start_time,
        }
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValidationError(f"ffprobe returned incomplete video metadata for {path.name}") from exc


def validate_video_dir(video_dir: Path) -> dict[str, Any]:
    if not video_dir.is_dir():
        raise ValidationError(f"video directory does not exist: {video_dir}")
    candidates = sorted(path for path in video_dir.iterdir() if path.suffix.lower() == ".mp4")
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
        raise ValidationError("MP4 names must be cam_00.mp4, cam_01.mp4, ...; invalid: " + ", ".join(unexpected))
    expected_indices = list(range(len(names)))
    actual_indices = [index for index, _ in names]
    if actual_indices != expected_indices:
        raise ValidationError(f"camera indices must be contiguous from 00; got {actual_indices}")

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
            errors.append(f"{path.name} duration differs from cam_00.mp4 by more than 100 ms")
        if abs(current["start_time_seconds"] - baseline["start_time_seconds"]) > 0.1:
            errors.append(f"{path.name} container start time differs from cam_00.mp4 by more than 100 ms")
    if errors:
        raise ValidationError("; ".join(errors))

    warnings: list[str] = []
    if (baseline["width"], baseline["height"]) != (1920, 1080):
        warnings.append("1920x1080 is recommended for a calibration run")
    if baseline["duration_seconds"] < 120:
        warnings.append("2-3 minutes of moving objects is recommended for a calibration run")
    warnings.append("matching container timing does not prove physical camera synchronization")

    scan_dirs = [video_dir, video_dir.parent]
    attachment_names = {
        "settings": ["calibration_settings.json", "settings.json", "config.json", "calibration_config.json"],
        "alignment": ["alignment_data.json"],
        "layout": ["layout.png"],
    }
    attachments: dict[str, list[str]] = {}
    for label, filenames in attachment_names.items():
        hits = sorted({str(directory / filename) for directory in scan_dirs for filename in filenames if (directory / filename).is_file()})
        attachments[label] = hits
    for label in ("settings", "alignment"):
        for raw_path in attachments[label]:
            value = _load_json(Path(raw_path))
            if not isinstance(value, dict):
                raise ValidationError(f"{label} JSON must contain an object: {raw_path}")
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
        "api_upload_ready": len(attachments["alignment"]) == 1 and len(attachments["layout"]) == 1,
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
            raise ValidationError(f"stream {name} must use a valid rtsp:// or rtsps:// URL")
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
                "credentials_present": parsed.username is not None or parsed.password is not None,
                "sensor_id_present": stream.get("sensor_id") is not None,
            }
        )
    attachments: dict[str, str | None] = {}
    for key, kind in (("settings_json", "json"), ("alignment_json", "json"), ("layout_png", "png")):
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
            if not isinstance(value, dict):
                raise ValidationError(f"{key} must contain a JSON object: {attachment}")
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
        "api_upload_ready": attachments["alignment_json"] is not None and attachments["layout_png"] is not None,
        "warnings": ["URL credentials are intentionally redacted", "reachability is checked only during GET-only qualification"],
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
            raise Unavailable(f"ffmpeg could not create {target.name}: {result.stderr.strip()}")
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
    (output / "fixture.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"fixture_dir": str(output.resolve()), **metadata}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, file_pointer: Any, code: int, message: str, headers: Any, new_url: str) -> None:
        return None


def _local_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _get_json(url: str, label: str, timeout: float) -> tuple[int, Any]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
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
        raise ValidationError(f"{label} must be a valid numeric loopback origin") from exc
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
        available.setdefault(normalized, set()).update(str(method).lower() for method in methods)
    missing = []
    for path, method in REQUIRED_OPENAPI.items():
        if method not in available.get(_normalized_openapi_path(path), set()):
            missing.append(f"{method.upper()} {path}")
    return missing


def qualify_runtime(backend_url: str, ui_url: str, vios_url: str | None, timeout: float) -> dict[str, Any]:
    backend_origin = _numeric_loopback_origin(backend_url, "AMC backend origin", {"", "/", "/v1", "/v1/"})
    ui_origin = _numeric_loopback_origin(ui_url, "AMC UI origin", {"", "/"})
    vios_origin = (
        _numeric_loopback_origin(vios_url, "VIOS origin", {"", "/"}) if vios_url is not None else None
    )
    backend = f"{backend_origin}/v1"
    ready_status, ready = _get_json(f"{backend}/ready", "AMC readiness endpoint", timeout)
    if ready_status != 200 or not isinstance(ready, dict) or ready.get("code") != 0:
        raise ValidationError("AMC readiness contract did not return code 0")
    openapi_status, openapi = _get_json(f"{backend_origin}/openapi.json", "AMC OpenAPI endpoint", timeout)
    if openapi_status != 200 or not isinstance(openapi, dict) or not isinstance(openapi.get("paths"), dict):
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
            f"{vios_origin}/vst/api/v1/sensor/list", "VIOS sensor-list endpoint", timeout
        )
        if vios_status != 200:
            raise ValidationError(f"VIOS sensor list returned HTTP {vios_status}")
        result["vios_sensor_list_reachable"] = isinstance(sensors, (dict, list))
    return result


def _assert_base_artifacts(inventory: dict[str, Any], require_vggt: bool) -> None:
    if inventory["host_architecture"] not in {"aarch64", "arm64"}:
        raise ValidationError(f"Thor lane requires ARM64; host is {inventory['host_architecture']}")
    bad = [name for name, item in inventory["images"].items() if item["required"] and item["state"] != "locked"]
    if bad:
        raise Unavailable("required images are not staged and content-locked: " + ", ".join(bad))
    if require_vggt and inventory["models"]["vggt"]["state"] != "locked":
        raise Unavailable("VGGT refinement requested but vggt_1B_commercial.pt is not content-locked")


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    inventory = inspect_inventory(args.data_root)
    inputs = validate_video_dir(args.input) if args.mode == "videos" else validate_rtsp_plan(args.input)
    _assert_base_artifacts(inventory, args.require_vggt)
    projects = args.projects_dir
    if not projects.is_dir():
        raise Unavailable(f"projects directory is absent: {projects}")
    if not os.access(projects, os.W_OK | os.X_OK):
        raise Unavailable(f"projects directory is not writable by the current user: {projects}")
    if not inputs["api_upload_ready"]:
        raise Unavailable("input is valid, but alignment_data.json and layout.png are required before API upload")
    return {
        "inventory": inventory,
        "inputs": inputs,
        "projects_dir": str(projects.resolve()),
        "warnings": ["current-user writability does not replace the post-start container UID 1000 write test"],
        "state": "ready_for_user_authorized_launch",
    }


def print_plan(data_root: Path) -> dict[str, Any]:
    inventory = inspect_inventory(data_root)
    backend = inventory["images"]["backend"]
    ui = inventory["images"]["ui"]
    return {
        "scope": "standalone AMC backend and UI; no warehouse sample bundle",
        "compose_files": [str(UPSTREAM_COMPOSE), str(THOR_COMPOSE)],
        "backend_image": backend,
        "ui_image": ui,
        "base_modes": ["custom synchronized MP4", "RTSP capture through VIOS"],
        "base_amc_requires_vggt": False,
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="inspect declared artifacts without network access")
    subparsers.add_parser("plan", help="show the sample-free standalone lane")

    videos = subparsers.add_parser("validate-videos", help="validate custom synchronized MP4 containers")
    videos.add_argument("input", type=Path)
    rtsp = subparsers.add_parser("validate-rtsp", help="validate and redact a custom RTSP JSON plan")
    rtsp.add_argument("input", type=Path)

    fixture = subparsers.add_parser("fixture", help="create a tiny media-contract-only fixture")
    fixture.add_argument("output", type=Path)
    fixture.add_argument("--seconds", type=int, default=6)
    fixture.add_argument("--size", default="640x360")
    fixture.add_argument("--fps", type=int, default=15)

    pf = subparsers.add_parser("preflight", help="fail closed before any operator-authorized launch")
    pf.add_argument("--mode", choices=("videos", "rtsp"), required=True)
    pf.add_argument("--input", type=Path, required=True)
    pf.add_argument("--projects-dir", type=Path, default=DOCKER_ROOT / "services" / "auto-calibration" / "projects")
    pf.add_argument("--require-vggt", action="store_true")

    qualify = subparsers.add_parser("qualify", help="run GET-only readiness and API-contract probes")
    qualify.add_argument("--backend-url", default="http://127.0.0.1:8010/v1")
    qualify.add_argument("--ui-url", default="http://127.0.0.1:5000")
    qualify.add_argument("--vios-url", help="also verify VIOS sensor-list reachability for RTSP mode")
    qualify.add_argument("--timeout", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            payload = inspect_inventory(args.data_root)
        elif args.command == "plan":
            payload = print_plan(args.data_root)
        elif args.command == "validate-videos":
            payload = validate_video_dir(args.input)
        elif args.command == "validate-rtsp":
            payload = validate_rtsp_plan(args.input)
        elif args.command == "fixture":
            payload = create_fixture(args.output, args.seconds, args.size, args.fps)
        elif args.command == "preflight":
            payload = preflight(args)
        elif args.command == "qualify":
            payload = qualify_runtime(args.backend_url, args.ui_url, args.vios_url, args.timeout)
        else:  # pragma: no cover
            raise AssertionError(args.command)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Unavailable as exc:
        print(json.dumps({"state": "unavailable", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(json.dumps({"state": "failed", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
