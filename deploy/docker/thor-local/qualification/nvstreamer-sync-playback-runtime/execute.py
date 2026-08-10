#!/usr/bin/env python3
"""Qualify NvStreamer synchronized two-file RTSP playback on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
BASE = "http://127.0.0.1:31010/vst/api/v1"
CONTAINER = "vss-qual-nvstreamer-sync-playback"
IMAGE = "vss-vios-nvstreamer:3.2.1-thor-local"
BASE_CONFIG = (
    HERE.parent / "nvstreamer-file-workflow-runtime" / "configs" / "vst_config.json"
)
STORAGE_CONFIG = (
    HERE.parent / "nvstreamer-file-workflow-runtime" / "configs" / "vst_storage.json"
)
OVERRIDES = HERE / "config-overrides.json"
CAPABILITY_ID = "configuration.nvstreamer.sync"
TCP_PORTS = (31010, 31654)
UDP_PORTS = (31654,)
SYNC_COUNT = 2
HOLD_SECONDS = 3.0
MAX_RESPONSE = 2 * 1024 * 1024
SYNC_MARKER = "Starting to play all sources m_baseGstTime:"


class QualificationError(RuntimeError):
    """The bounded synchronized-playback transaction did not pass."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON in {label}: {value}")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON: {label}") from exc


def _run(
    command: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        detail = stderr.decode(errors="replace")[-1200:]
        raise QualificationError(f"command failed: {command[0]}: {detail}") from exc


def _docker_ids(*, running: bool) -> list[str]:
    command = ["docker", "ps", "--no-trunc", "--format", "{{.ID}}"]
    if not running:
        command.insert(2, "-a")
    return sorted(line for line in _run(command).stdout.decode().splitlines() if line)


def _container_exists() -> bool:
    return (
        _run(["docker", "container", "inspect", CONTAINER], check=False).returncode
        == 0
    )


def _port_free(protocol: str, port: int) -> bool:
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    with socket.socket(socket.AF_INET, kind) as stream:
        stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            stream.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class Client:
    def __init__(self, base: str = BASE) -> None:
        if base != BASE:
            raise QualificationError("sync qualifier endpoint must remain loopback-bound")
        self.base = base
        self.receipts: list[dict[str, Any]] = []

    def json(self, path: str, *, timeout: int = 5) -> Any:
        if not path.startswith("/") or "#" in path:
            raise QualificationError("unsafe HTTP path")
        request = urllib.request.Request(self.base + path, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0]
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE + 1)
            content_type = (exc.headers.get("Content-Type") or "").split(";", 1)[0]
        except (OSError, urllib.error.URLError) as exc:
            raise QualificationError(f"NvStreamer request failed: GET {path}") from exc
        if len(raw) > MAX_RESPONSE:
            raise QualificationError(f"oversized NvStreamer response: GET {path}")
        self.receipts.append(
            {
                "method": "GET",
                "path": path,
                "status": status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "content_type": content_type,
            }
        )
        if status != 200:
            raise QualificationError(f"unexpected HTTP {status}: GET {path}")
        return _strict_json(raw, f"GET {path}")


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if key not in base:
            raise QualificationError(f"config override references unknown key: {key}")
        if isinstance(value, dict):
            if not isinstance(base[key], dict):
                raise QualificationError(f"config override changes object type: {key}")
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _derived_config(output: Path) -> dict[str, Any]:
    base = _strict_json(BASE_CONFIG.read_bytes(), "base NvStreamer config")
    overrides = _strict_json(OVERRIDES.read_bytes(), "sync config overrides")
    if not isinstance(base, dict) or not isinstance(overrides, dict):
        raise QualificationError("NvStreamer config inputs must be JSON objects")
    value = _deep_merge(base, overrides)
    data = value.get("data", {})
    network = value.get("network", {})
    if (
        data.get("nv_streamer_sync_file_count") != SYNC_COUNT
        or data.get("nv_streamer_sync_playback") is not False
        or data.get("nv_streamer_loop_playback") is not True
        or network.get("http_port") != "31010"
        or network.get("rtsp_server_port") != 31654
        or network.get("rtsp_server_instances_count") != 1
        or network.get("server_domain_name") != "127.0.0.1"
    ):
        raise QualificationError("derived sync config differs from the exact contract")
    output.write_bytes(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
    return value


def _fixture(path: Path) -> dict[str, Any]:
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-bf",
            "0",
            "-g",
            "30",
            "-keyint_min",
            "30",
            "-sc_threshold",
            "0",
            "-an",
            "-movflags",
            "+faststart",
            str(path),
        ],
        timeout=45,
    )
    probe = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                (
                    "stream=codec_name,profile,width,height,has_b_frames,"
                    "r_frame_rate,avg_frame_rate,nb_frames:format=duration:frame=key_frame"
                ),
                "-show_frames",
                "-of",
                "json",
                str(path),
            ],
            timeout=30,
        ).stdout,
        "sync fixture ffprobe",
    )
    streams = probe.get("streams") if isinstance(probe, dict) else None
    frames = probe.get("frames") if isinstance(probe, dict) else None
    formats = probe.get("format") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(frames, list):
        raise QualificationError("sync fixture probe omitted its video stream or frames")
    video = streams[0]
    keyframes = [index for index, frame in enumerate(frames) if frame.get("key_frame") == 1]
    expected_keyframes = list(range(0, 240, 30))
    if (
        video.get("codec_name") != "h264"
        or video.get("profile") not in {"Baseline", "Constrained Baseline"}
        or video.get("width") != 320
        or video.get("height") != 180
        or video.get("has_b_frames") != 0
        or video.get("r_frame_rate") != "30/1"
        or video.get("avg_frame_rate") != "30/1"
        or video.get("nb_frames") != "240"
        or keyframes != expected_keyframes
        or not isinstance(formats, dict)
        or formats.get("duration") != "8.000000"
    ):
        raise QualificationError(
            f"sync fixture encoding differs: video={video}, keyframes={keyframes}, format={formats}"
        )
    raw = path.read_bytes()
    return {
        "bytes": len(raw),
        "sha256": _sha(raw),
        "codec": "h264",
        "profile": video["profile"],
        "width": 320,
        "height": 180,
        "frame_rate": "30/1",
        "frame_count": 240,
        "duration_seconds": 8,
        "b_frames": 0,
        "keyint": 30,
        "keyframe_indices": keyframes,
    }


def _start_container(root: Path, config: Path) -> dict[str, Any]:
    media = root / "media"
    data = root / "data"
    data.mkdir(mode=0o777)
    media.chmod(0o777)
    data.chmod(0o777)
    image = _strict_json(
        _run(["docker", "image", "inspect", IMAGE]).stdout,
        "Docker image inspect",
    )
    if not isinstance(image, list) or len(image) != 1 or image[0].get("Architecture") != "arm64":
        raise QualificationError("the exact Thor-local NvStreamer arm64 image is absent")
    labels = image[0].get("Config", {}).get("Labels", {})
    if labels.get("com.nvidia.vss.thor.vios-runtime-network-install") != "disabled":
        raise QualificationError("NvStreamer image is not the offline Thor-local derivative")
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        CONTAINER,
        "--label",
        "com.nvidia.vss.thor.qualifier=nvstreamer-sync-playback-runtime",
        "--runtime",
        "nvidia",
        "--memory",
        "4g",
        "--cpus",
        "4",
        "--pids-limit",
        "1024",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--network",
        "bridge",
        "--publish",
        "127.0.0.1:31010:31010/tcp",
        "--publish",
        "127.0.0.1:31654:31654/tcp",
        "--publish",
        "127.0.0.1:31654:31654/udp",
        "--env",
        "ADAPTOR=streamer",
        "--env",
        "HTTP_PORT=31010",
        "--env",
        "NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES=false",
        "--volume",
        f"{config}:/home/vst/vst_release/configs/vst_config.json:ro",
        "--volume",
        f"{STORAGE_CONFIG}:/home/vst/vst_release/configs/vst_storage.json:ro",
        "--volume",
        f"{media}:/home/vst/vst_release/streamer_videos",
        "--volume",
        f"{data}:/home/vst/vst_release/vst_data",
        IMAGE,
    ]
    container_id = _run(command, timeout=45).stdout.decode().strip()
    if len(container_id) != 64:
        raise QualificationError("Docker did not return a full container ID")
    container_ip = _run(
        [
            "docker",
            "container",
            "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            CONTAINER,
        ]
    ).stdout.decode().strip()
    try:
        socket.inet_aton(container_ip)
    except OSError as exc:
        raise QualificationError("NvStreamer bridge IP is absent or invalid") from exc
    return {
        "container_id": container_id,
        "container_ip": container_ip,
        "image_id": image[0].get("Id"),
        "image_repo_digests": image[0].get("RepoDigests") or [],
        "image_size_bytes": image[0].get("Size"),
        "image_architecture": image[0].get("Architecture"),
        "offline_runtime_install": labels.get(
            "com.nvidia.vss.thor.vios-runtime-network-install"
        ),
        "codec_package_set": labels.get("com.nvidia.vss.thor.vios-codec-package-set"),
    }


def _wait_for_version(client: Client, timeout: int = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = client.json("/sensor/version", timeout=2)
            if isinstance(value, dict) and value.get("type") == "streamer":
                return value
        except QualificationError:
            pass
        time.sleep(1)
    raise QualificationError("NvStreamer did not become ready")


def _wait_for_sensors(
    client: Client, names: set[str], timeout: int = 60
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    latest: Any = None
    while time.monotonic() < deadline:
        try:
            latest = client.json("/sensor/list", timeout=3)
        except QualificationError:
            time.sleep(0.5)
            continue
        if not isinstance(latest, list):
            raise QualificationError("NvStreamer sensor list is not an array")
        found: dict[str, dict[str, Any]] = {}
        for name in names:
            matches = [
                item
                for item in latest
                if isinstance(item, dict) and item.get("name") == name
            ]
            if len(matches) > 1:
                raise QualificationError(f"duplicate NvStreamer sensor name: {name}")
            if matches:
                found[name] = matches[0]
        if len(found) == len(names) and all(
            item.get("state") == "online"
            and item.get("type") == "sensor_nvstream"
            and isinstance(item.get("sensorId"), str)
            and item["sensorId"]
            for item in found.values()
        ):
            return found
        time.sleep(0.5)
    raise QualificationError(f"sync sensors did not become online: {sorted(names)}")


def _wait_for_rtsp_url(
    client: Client,
    sensor_id: str,
    filename: str,
    container_ip: str,
    timeout: int = 60,
) -> dict[str, str]:
    quoted = urllib.parse.quote(sensor_id, safe="")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = client.json(f"/sensor/{quoted}/streams", timeout=3)
        except QualificationError:
            time.sleep(0.5)
            continue
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            time.sleep(0.5)
            continue
        stream = value[0]
        raw_url = stream.get("url")
        metadata = stream.get("metadata")
        if not isinstance(raw_url, str) or not isinstance(metadata, dict):
            time.sleep(0.5)
            continue
        parsed = urllib.parse.urlparse(raw_url)
        expected_path = f"/nvstream/home/vst/vst_release/streamer_videos/{filename}"
        if (
            parsed.scheme != "rtsp"
            or parsed.hostname not in {container_ip, "127.0.0.1"}
            or parsed.port != 31654
            or parsed.path != expected_path
            or parsed.username is not None
            or parsed.password is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise QualificationError(f"NvStreamer returned an unsafe RTSP URL for {filename}")
        if (
            stream.get("streamId") != sensor_id
            or stream.get("type") != "Rtsp"
            or metadata.get("codec") != "h264"
            or metadata.get("resolution") != "320x180"
            or metadata.get("framerate") != "30.0"
        ):
            time.sleep(0.5)
            continue
        normalized = parsed._replace(netloc="127.0.0.1:31654").geturl()
        return {
            "url": normalized,
            "path": parsed.path,
            "raw_host_scope": (
                "loopback" if parsed.hostname == "127.0.0.1" else "container_bridge"
            ),
        }
    raise QualificationError(f"RTSP URL metadata did not become ready: {filename}")


def _container_logs() -> bytes:
    process = _run(["docker", "logs", CONTAINER], check=False)
    return process.stdout + process.stderr


def _ffmpeg_command(url: str) -> list[str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "rtsp" or parsed.hostname != "127.0.0.1" or parsed.port != 31654:
        raise QualificationError("ffmpeg RTSP target escaped the reserved loopback endpoint")
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ]


def _terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _exercise_barrier(urls: list[str]) -> dict[str, Any]:
    if len(urls) != SYNC_COUNT:
        raise QualificationError("sync barrier requires exactly two RTSP URLs")
    processes: list[subprocess.Popen[bytes] | None] = [None, None]
    started_ns = time.monotonic_ns()
    try:
        processes[0] = subprocess.Popen(
            _ffmpeg_command(urls[0]), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        time.sleep(HOLD_SECONDS)
        if processes[0].poll() is not None:
            _, stderr = processes[0].communicate()
            raise QualificationError(
                "first RTSP client received data before the configured barrier: "
                + stderr.decode(errors="replace")[-800:]
            )
        pre_logs = _container_logs()
        pre_sync_count = pre_logs.count(SYNC_MARKER.encode())
        if pre_sync_count != 0:
            raise QualificationError("shared playback started before the second client joined")

        second_started_ns = time.monotonic_ns()
        processes[1] = subprocess.Popen(
            _ffmpeg_command(urls[1]), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        completion_ns: list[int | None] = [None, None]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and any(value is None for value in completion_ns):
            for index, process in enumerate(processes):
                if completion_ns[index] is None and process is not None and process.poll() is not None:
                    completion_ns[index] = time.monotonic_ns()
            time.sleep(0.005)
        if any(value is None for value in completion_ns):
            raise QualificationError("both clients did not receive a synchronized first frame")

        stderr_values: list[str] = []
        return_codes: list[int] = []
        for process in processes:
            assert process is not None
            _, stderr = process.communicate()
            stderr_values.append(stderr.decode(errors="replace"))
            return_codes.append(process.returncode)
        if return_codes != [0, 0]:
            raise QualificationError(
                f"synchronized RTSP clients failed: codes={return_codes}, stderr={stderr_values}"
            )

        post_logs = _container_logs()
        marker_lines = [
            line
            for line in post_logs.decode(errors="replace").splitlines()
            if SYNC_MARKER in line
        ]
        if len(marker_lines) != 1:
            raise QualificationError(
                f"expected one shared-clock start marker, observed {len(marker_lines)}"
            )
        marker_suffix = marker_lines[0].split(SYNC_MARKER, 1)[1].strip()
        if not marker_suffix.isdigit() or int(marker_suffix) <= 0:
            raise QualificationError("shared GStreamer base time is absent or invalid")

        assert completion_ns[0] is not None and completion_ns[1] is not None
        barrier_hold_ms = (second_started_ns - started_ns) // 1_000_000
        completion_after_second_ms = [
            (value - second_started_ns) // 1_000_000 for value in completion_ns
        ]
        completion_skew_ms = abs(completion_ns[0] - completion_ns[1]) // 1_000_000
        if (
            barrier_hold_ms < 2900
            or any(value < 0 or value > 5000 for value in completion_after_second_ms)
            or completion_skew_ms > 250
        ):
            raise QualificationError(
                "synchronized first-frame timing differs: "
                f"hold={barrier_hold_ms}, after={completion_after_second_ms}, "
                f"skew={completion_skew_ms}"
            )
        return {
            "single_client_barrier_held": True,
            "barrier_hold_ms": barrier_hold_ms,
            "pre_barrier_sync_start_count": pre_sync_count,
            "pre_barrier_logs_sha256": _sha(pre_logs),
            "second_client_released_barrier": True,
            "first_frame_completion_after_second_ms": completion_after_second_ms,
            "first_frame_completion_skew_ms": completion_skew_ms,
            "decoded_frame_count_per_client": [1, 1],
            "client_return_codes": return_codes,
            "shared_clock_start_count": len(marker_lines),
            "shared_base_gst_time": int(marker_suffix),
            "shared_clock_marker_sha256": _sha(marker_lines[0].encode()),
            "post_barrier_logs_sha256": _sha(post_logs),
        }
    except OSError as exc:
        raise QualificationError("failed to start the local RTSP client") from exc
    finally:
        for process in processes:
            _terminate_process(process)


def _chmod_owned_mounts() -> None:
    _run(
        [
            "docker",
            "exec",
            CONTAINER,
            "/bin/sh",
            "-c",
            (
                "find /home/vst/vst_release/vst_data "
                "/home/vst/vst_release/streamer_videos -exec chmod a+rwX {} +"
            ),
        ],
        check=False,
    )


def _stop_remove_container(cleanup: list[dict[str, Any]]) -> None:
    if not _container_exists():
        return
    _chmod_owned_mounts()
    stop = _run(["docker", "stop", "--timeout", "20", CONTAINER], timeout=30, check=False)
    cleanup.append({"operation": "container-stop", "status": stop.returncode})
    remove = _run(["docker", "rm", CONTAINER], check=False)
    cleanup.append({"operation": "container-remove", "status": remove.returncode})


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise QualificationError("unsafe receipt output")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def execute() -> dict[str, Any]:
    if _container_exists():
        raise QualificationError(f"reserved qualifier container already exists: {CONTAINER}")
    occupied = [
        f"{protocol}/{port}"
        for protocol, ports in (("tcp", TCP_PORTS), ("udp", UDP_PORTS))
        for port in ports
        if not _port_free(protocol, port)
    ]
    if occupied:
        raise QualificationError(f"reserved qualifier ports are occupied: {occupied}")
    inputs = (BASE_CONFIG, STORAGE_CONFIG, OVERRIDES)
    if not all(path.is_file() and not path.is_symlink() for path in inputs):
        raise QualificationError("qualification inputs are missing or symlinked")

    non_owned_all_before = _docker_ids(running=False)
    non_owned_running_before = _docker_ids(running=True)
    cleanup: list[dict[str, Any]] = []
    primary_error: Exception | None = None
    result: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="vss-nvstreamer-sync-playback-") as directory:
        root = Path(directory)
        media = root / "media"
        media.mkdir(mode=0o777)
        source = root / "fixture.mp4"
        fixture = _fixture(source)
        names = ["vss_qual_sync_a", "vss_qual_sync_b"]
        paths = [media / f"{name}.mp4" for name in names]
        for path in paths:
            shutil.copyfile(source, path)
        if any(_sha_file(path) != fixture["sha256"] for path in paths):
            raise QualificationError("the two sync fixtures are not byte-identical")
        config_path = root / "vst_config.json"
        derived_config = _derived_config(config_path)
        client = Client()
        try:
            container = _start_container(root, config_path)
            version = _wait_for_version(client)
            sensors = _wait_for_sensors(client, set(names))
            sensor_ids = [sensors[name]["sensorId"] for name in names]
            if len(set(sensor_ids)) != SYNC_COUNT:
                raise QualificationError("NvStreamer assigned duplicate sync sensor IDs")
            rtsp = [
                _wait_for_rtsp_url(
                    client,
                    sensor_ids[index],
                    paths[index].name,
                    container["container_ip"],
                )
                for index in range(SYNC_COUNT)
            ]
            barrier = _exercise_barrier([item["url"] for item in rtsp])
            result = {
                "schema_version": 1,
                "qualification_id": "thor-vss-3.2.1-nvstreamer-sync-playback-runtime",
                "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "status": "passed",
                "runtime_evidence": True,
                "target": {
                    "product_version": "3.2.1",
                    "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                },
                "capability_results": {CAPABILITY_ID: "passed_current"},
                "bounds": {
                    "http_endpoint": BASE,
                    "http_loopback_only": True,
                    "rtsp_endpoint": "rtsp://127.0.0.1:31654",
                    "rtsp_loopback_only": True,
                    "external_downloads": False,
                    "runtime_package_installs": False,
                    "warehouse_sample_bundle_used": False,
                    "main_vios_sensor_added": False,
                    "rt_cv_stream_added": False,
                    "agent_generate_called": False,
                    "existing_container_count": len(non_owned_all_before),
                    "existing_running_container_count": len(non_owned_running_before),
                },
                "identity": {
                    "image": {
                        key: value
                        for key, value in container.items()
                        if key != "container_ip"
                    },
                    "service_version": version,
                    "base_config_sha256": _sha_file(BASE_CONFIG),
                    "storage_config_sha256": _sha_file(STORAGE_CONFIG),
                    "overrides_sha256": _sha_file(OVERRIDES),
                    "derived_config_sha256": _sha_file(config_path),
                    "derived_config_canonical_sha256": _sha(_canonical(derived_config)),
                    "executor_sha256": _sha_file(Path(__file__).resolve()),
                },
                "fixture": {
                    **fixture,
                    "file_count": SYNC_COUNT,
                    "files_byte_identical": True,
                    "file_sha256s": [_sha_file(path) for path in paths],
                },
                "observations": {
                    "config": {
                        "key": "nv_streamer_sync_file_count",
                        "value": SYNC_COUNT,
                        "nv_streamer_sync_playback": False,
                        "nv_streamer_loop_playback": True,
                    },
                    "sensor_names": names,
                    "sensor_ids": sensor_ids,
                    "sensor_states": [sensors[name]["state"] for name in names],
                    "rtsp_paths": [item["path"] for item in rtsp],
                    "rtsp_raw_host_scopes": [item["raw_host_scope"] for item in rtsp],
                    "barrier": barrier,
                    "request_accounting": {
                        "http_response_count": len(client.receipts),
                        "http_failure_count": sum(
                            1 for item in client.receipts if item["status"] != 200
                        ),
                    },
                },
                "cleanup": {
                    "result": "pending_container_cleanup",
                    "temporary_media_count": SYNC_COUNT,
                    "attempts": cleanup,
                },
                "requests": client.receipts,
            }
        except Exception as exc:
            primary_error = exc
        finally:
            _stop_remove_container(cleanup)

        non_owned_all_after = _docker_ids(running=False)
        non_owned_running_after = _docker_ids(running=True)
        restoration = {
            "exact_container_inventory_restored": non_owned_all_after == non_owned_all_before,
            "exact_running_set_restored": non_owned_running_after == non_owned_running_before,
            "all_reserved_ports_released": all(
                _port_free(protocol, port)
                for protocol, ports in (("tcp", TCP_PORTS), ("udp", UDP_PORTS))
                for port in ports
            ),
        }
        if not all(restoration.values()):
            raise QualificationError(f"non-owned Docker/port state was not restored: {restoration}")
        if primary_error is not None:
            if isinstance(primary_error, QualificationError):
                raise primary_error
            raise QualificationError("NvStreamer sync transaction failed") from primary_error
        if result is None:
            raise QualificationError("NvStreamer sync transaction produced no result")
        result["cleanup"].update(restoration)
        result["cleanup"]["result"] = "passed"
        result["cleanup"]["attempts"] = cleanup
        result["cleanup"]["temporary_tree_removed_by_context"] = True
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the bounded isolated mutation")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "failed", "error": "--execute is required"}))
        return 2
    try:
        receipt = execute()
        output = args.output.resolve()
        _write_receipt(output, receipt)
    except (OSError, QualificationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "output": str(output),
                "receipt_sha256": _sha(output.read_bytes()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
