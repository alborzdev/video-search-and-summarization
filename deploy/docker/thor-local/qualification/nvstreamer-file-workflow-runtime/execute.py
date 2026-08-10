#!/usr/bin/env python3
"""Qualify NvStreamer file inputs, RTSP/WebRTC outputs, and exact cleanup."""

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
import uuid


HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:31000/vst/api/v1"
UI_ENDPOINT = "http://127.0.0.1:31000"
CONTAINER = "vss-qual-nvstreamer-file-workflow"
IMAGE = "vss-vios-nvstreamer:3.2.1-thor-local"
CONFIG = HERE / "configs" / "vst_config.json"
STORAGE_CONFIG = HERE / "configs" / "vst_storage.json"
UI_HARNESS = HERE / "ui-harness.mjs"
MAX_RESPONSE = 16 * 1024 * 1024
CAPABILITY_ID = "runtime.nvstreamer.file-streaming"
TCP_PORTS = (31000, 31554)
UDP_PORTS = (31554, *range(32200, 32221))


class QualificationError(RuntimeError):
    """The bounded NvStreamer transaction did not satisfy its contract."""


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
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            timeout=timeout,
            env=env,
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
    process = _run(
        ["docker", "container", "inspect", CONTAINER],
        check=False,
    )
    return process.returncode == 0


def _port_free(protocol: str, port: int) -> bool:
    family = socket.AF_INET
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    with socket.socket(family, kind) as stream:
        stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            stream.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class Client:
    def __init__(self, base: str = BASE) -> None:
        if base != BASE:
            raise QualificationError("the NvStreamer qualifier is fixed to loopback port 31000")
        self.base = base
        self.receipts: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> tuple[int, bytes, str]:
        if not path.startswith("/") or "#" in path:
            raise QualificationError("unsafe HTTP path")
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers=headers or {},
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
            response_headers = response.headers
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE + 1)
            response_headers = exc.headers
        except (OSError, urllib.error.URLError) as exc:
            raise QualificationError(f"NvStreamer request failed: {method} {path}") from exc
        if len(raw) > MAX_RESPONSE:
            raise QualificationError(f"oversized NvStreamer response: {method} {path}")
        content_type = (response_headers.get("Content-Type") or "").split(";", 1)[0]
        self.receipts.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "content_type": content_type,
            }
        )
        return status, raw, content_type

    def json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] = {200},
        timeout: int = 20,
    ) -> tuple[int, Any]:
        status, raw, _ = self.request(method, path, body=body, headers=headers, timeout=timeout)
        if status not in expected:
            raise QualificationError(f"unexpected HTTP {status}: {method} {path}")
        return status, _strict_json(raw, f"{method} {path}")


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
            "testsrc2=size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-pix_fmt",
            "yuv420p",
            "-bf",
            "0",
            "-g",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(path),
        ],
        timeout=40,
    )
    probe = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,has_b_frames,r_frame_rate,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ]
        ).stdout,
        "fixture ffprobe",
    )
    fixture_streams = _validate_media_streams(probe, require_audio=True)
    if fixture_streams["video"].get("r_frame_rate") != "10/1":
        raise QualificationError("generated fixture frame rate differs from 10/1")
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": _sha(raw), "streams": probe["streams"]}


def _validate_media_streams(probe: Any, *, require_audio: bool) -> dict[str, Any]:
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list):
        raise QualificationError("ffprobe omitted streams")
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    if (
        len(videos) != 1
        or videos[0].get("codec_name") != "h264"
        or videos[0].get("width") != 320
        or videos[0].get("height") != 180
    ):
        raise QualificationError(f"H.264 fixture/RTSP video contract differs: {videos}")
    if require_audio and (
        len(audios) != 1
        or audios[0].get("codec_name") != "aac"
        or audios[0].get("sample_rate") != "48000"
        or audios[0].get("channels") != 1
    ):
        raise QualificationError(f"AAC fixture/RTSP audio contract differs: {audios}")
    return {"video": videos[0], "audio": audios[0] if audios else None}


def _multipart(filename: str, raw: bytes, token: str) -> tuple[bytes, str]:
    if not filename.endswith(".mp4") or any(char in filename for char in "\r\n/\\"):
        raise QualificationError("unsafe multipart filename")
    boundary = f"vss-nvstreamer-{token}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode() + raw + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _find_sensor(sensors: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(sensors, list):
        raise QualificationError("sensor list is not an array")
    matches = [item for item in sensors if isinstance(item, dict) and item.get("name") == name]
    if len(matches) > 1:
        raise QualificationError(f"duplicate sensor name: {name}")
    return matches[0] if matches else None


def _stream_for_sensor(streams: Any, sensor_id: str) -> dict[str, Any]:
    if not isinstance(streams, list):
        raise QualificationError("sensor streams is not an array")
    matches: list[dict[str, Any]] = []
    for entry in streams:
        if not isinstance(entry, dict):
            continue
        value = entry.get(sensor_id)
        if isinstance(value, list):
            matches.extend(item for item in value if isinstance(item, dict))
    if len(matches) != 1:
        raise QualificationError(f"expected one stream for sensor {sensor_id}")
    return matches[0]


def _wait_for_sensors(client: Client, names: set[str], timeout: int = 30) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, sensors = client.json("GET", "/sensor/list")
        found = {name: _find_sensor(sensors, name) for name in names}
        if all(sensor and sensor.get("state") == "online" for sensor in found.values()):
            return {name: sensor for name, sensor in found.items() if sensor is not None}
        time.sleep(0.5)
    raise QualificationError(f"sensors did not become online: {sorted(names)}")


def _wait_for_no_owned_sensors(client: Client, prefix: str, timeout: int = 20) -> Any:
    deadline = time.monotonic() + timeout
    latest: Any = None
    while time.monotonic() < deadline:
        _, latest = client.json("GET", "/sensor/list")
        owned = [
            item
            for item in latest
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].startswith(prefix)
        ]
        if not owned:
            return latest
        time.sleep(0.5)
    raise QualificationError("executor-owned sensors remain after delete")


def _api_upload(client: Client, path: Path, token: str) -> dict[str, Any]:
    raw = path.read_bytes()
    body, content_type = _multipart(path.name, raw, token)
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "nvstreamer-file-name": path.name,
    }
    _, value = client.json(
        "POST",
        "/storage/file",
        body=body,
        headers=headers,
        expected={200, 201},
        timeout=60,
    )
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(value.get("streamId"), str)
        or not value["streamId"]
        or value.get("filename") != path.stem
    ):
        detail = {
            "type": type(value).__name__,
            "keys": sorted(value) if isinstance(value, dict) else [],
            "filename": value.get("filename") if isinstance(value, dict) else None,
            "id_type": type(value.get("id")).__name__ if isinstance(value, dict) else None,
            "stream_id_type": type(value.get("streamId")).__name__ if isinstance(value, dict) else None,
        }
        raise QualificationError(f"direct multipart upload response contract differs: {detail}")
    return value


def _discover_playwright() -> Path:
    override = os.environ.get("VSS_PLAYWRIGHT_NODE_MODULES")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).resolve())
    candidates.extend(
        sorted((Path.home() / ".npm" / "_npx").glob("*/node_modules"), reverse=True)
    )
    for candidate in candidates:
        if (candidate / "playwright" / "package.json").is_file():
            return candidate
    raise QualificationError("Playwright is not available in the existing npm cache")


def _run_ui_harness(upload: Path, sensor_name: str, output: Path) -> dict[str, Any]:
    chromium = Path("/snap/bin/chromium")
    if not chromium.exists():
        raise QualificationError("system Chromium is absent at /snap/bin/chromium")
    environment = os.environ.copy()
    environment["NODE_PATH"] = str(_discover_playwright())
    _run(
        [
            "node",
            str(UI_HARNESS),
            "--endpoint",
            UI_ENDPOINT,
            "--upload",
            str(upload),
            "--sensor-name",
            sensor_name,
            "--output",
            str(output),
            "--chromium",
            str(chromium),
        ],
        timeout=60,
        env=environment,
    )
    value = _strict_json(output.read_bytes(), "UI harness receipt")
    if not isinstance(value, dict) or value.get("status") != "passed":
        raise QualificationError("UI harness did not pass")
    return value


def _start_container(root: Path) -> dict[str, Any]:
    media = root / "media"
    data = root / "data"
    media.mkdir(mode=0o777, exist_ok=True)
    data.mkdir(mode=0o777, exist_ok=True)
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
        "com.nvidia.vss.thor.qualifier=nvstreamer-file-workflow-runtime",
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
        "127.0.0.1:31000:31000/tcp",
        "--publish",
        "127.0.0.1:31554:31554/tcp",
        "--publish",
        "127.0.0.1:31554:31554/udp",
    ]
    for port in range(32200, 32221):
        command.extend(["--publish", f"127.0.0.1:{port}:{port}/udp"])
    command.extend(
        [
            "--env",
            "ADAPTOR=streamer",
            "--env",
            "HTTP_PORT=31000",
            "--env",
            "NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES=false",
            "--volume",
            f"{CONFIG}:/home/vst/vst_release/configs/vst_config.json:ro",
            "--volume",
            f"{STORAGE_CONFIG}:/home/vst/vst_release/configs/vst_storage.json:ro",
            "--volume",
            f"{media}:/home/vst/vst_release/streamer_videos",
            "--volume",
            f"{data}:/home/vst/vst_release/vst_data",
            IMAGE,
        ]
    )
    container_id = _run(command, timeout=45).stdout.decode().strip()
    if len(container_id) != 64:
        raise QualificationError("Docker did not return a full container ID")
    return {
        "container_id": container_id,
        "image_id": image[0].get("Id"),
        "image_repo_digests": image[0].get("RepoDigests") or [],
        "image_size_bytes": image[0].get("Size"),
        "image_architecture": image[0].get("Architecture"),
        "offline_runtime_install": labels.get("com.nvidia.vss.thor.vios-runtime-network-install"),
        "codec_package_set": labels.get("com.nvidia.vss.thor.vios-codec-package-set"),
    }


def _wait_for_version(client: Client, timeout: int = 60) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _, value = client.json("GET", "/sensor/version")
            if isinstance(value, dict) and value.get("type") == "streamer":
                return value
        except QualificationError:
            pass
        time.sleep(1)
    logs = _run(["docker", "logs", "--tail", "120", CONTAINER], check=False).stderr
    raise QualificationError(f"NvStreamer did not become ready: {logs.decode(errors='replace')[-1200:]}")


def _rtsp_probe(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "rtsp" or parsed.hostname != "127.0.0.1" or parsed.port != 31554:
        raise QualificationError("NvStreamer returned a non-loopback or unexpected RTSP endpoint")
    with_audio = url + ("&" if "?" in url else "?") + "includeAudio=true"
    value = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels",
                "-of",
                "json",
                with_audio,
            ],
            timeout=25,
        ).stdout,
        "RTSP ffprobe",
    )
    return _validate_media_streams(value, require_audio=True)


def _snapshot(client: Client, sensor_id: str, output: Path) -> dict[str, Any]:
    quoted = urllib.parse.quote(sensor_id, safe="")
    status, raw, content_type = client.request("GET", f"/live/stream/{quoted}/picture?frameId=0")
    if status != 200 or content_type != "image/jpeg" or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        raise QualificationError("live snapshot is not a valid JPEG response")
    output.write_bytes(raw)
    probe = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(output),
            ]
        ).stdout,
        "snapshot ffprobe",
    )
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if (
        not isinstance(streams, list)
        or len(streams) != 1
        or streams[0].get("codec_name") != "mjpeg"
        or streams[0].get("width") != 320
        or streams[0].get("height") != 180
    ):
        raise QualificationError("snapshot dimensions or codec differ")
    return {"bytes": len(raw), "sha256": _sha(raw), "codec": "mjpeg", "width": 320, "height": 180}


def _chmod_owned_mounts() -> None:
    _run(
        [
            "docker",
            "exec",
            CONTAINER,
            "/bin/sh",
            "-c",
            "find /home/vst/vst_release/vst_data /home/vst/vst_release/streamer_videos -exec chmod a+rwX {} +",
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
    if not all(path.is_file() and not path.is_symlink() for path in (CONFIG, STORAGE_CONFIG, UI_HARNESS)):
        raise QualificationError("qualification inputs are missing or symlinked")

    non_owned_all_before = _docker_ids(running=False)
    non_owned_running_before = _docker_ids(running=True)
    client = Client()
    cleanup: list[dict[str, Any]] = []
    container: dict[str, Any] | None = None
    primary_error: Exception | None = None
    result: dict[str, Any] | None = None
    prefix = f"vss_qual_nvstreamer_{uuid.uuid4().hex[:12]}"

    with tempfile.TemporaryDirectory(prefix="vss-nvstreamer-file-workflow-") as directory:
        root = Path(directory)
        media = root / "media"
        source = root / "fixture.mp4"
        fixture = _fixture(source)
        local_name = f"{prefix}_local_mount"
        api_name = f"{prefix}_api_upload"
        ui_name = f"{prefix}_ui_upload"
        local_path = media / f"{local_name}.mp4"
        api_path = root / f"{api_name}.mp4"
        ui_path = root / f"{ui_name}.mp4"
        invalid_path = root / f"{prefix}_invalid.mp4"
        ui_receipt_path = root / "ui-receipt.json"
        snapshot_path = root / "snapshot.jpg"
        owned_stream_ids: set[str] = set()
        try:
            media.mkdir(mode=0o777)
            shutil.copyfile(source, local_path)
            shutil.copyfile(source, api_path)
            shutil.copyfile(source, ui_path)
            invalid_path.write_bytes(b"not-an-mp4")
            container = _start_container(root)
            version = _wait_for_version(client)
            sensors = _wait_for_sensors(client, {local_name})
            local_sensor = sensors[local_name]
            local_sensor_id = local_sensor.get("sensorId")
            if not isinstance(local_sensor_id, str) or not local_sensor_id:
                raise QualificationError("local-mount sensor has no identity")
            owned_stream_ids.add(local_sensor_id)

            api_upload = _api_upload(client, api_path, uuid.uuid4().hex)
            owned_stream_ids.add(api_upload["streamId"])

            invalid_body, invalid_content_type = _multipart(invalid_path.name, invalid_path.read_bytes(), uuid.uuid4().hex)
            invalid_status, invalid_response, _ = client.request(
                "POST",
                "/storage/file",
                body=invalid_body,
                headers={
                    "Content-Type": invalid_content_type,
                    "Content-Length": str(len(invalid_body)),
                    "nvstreamer-file-name": invalid_path.name,
                },
                timeout=30,
            )
            if invalid_status != 400 or b"Failed to get media information" not in invalid_response:
                raise QualificationError("invalid-media adjacent negative did not return the expected HTTP 400")

            ui_receipt = _run_ui_harness(ui_path, local_name, ui_receipt_path)
            ui_stream_id = ui_receipt.get("upload", {}).get("stream_id")
            if not isinstance(ui_stream_id, str) or not ui_stream_id:
                raise QualificationError("UI upload receipt omitted stream ID")
            owned_stream_ids.add(ui_stream_id)

            sensors = _wait_for_sensors(client, {local_name, api_name, ui_name})
            if any(sensor.get("type") != "sensor_nvstream" for sensor in sensors.values()):
                raise QualificationError("an uploaded/local media sensor has the wrong type")
            if _find_sensor(list(sensors.values()), invalid_path.stem) is not None:
                raise QualificationError("invalid media unexpectedly created a sensor")

            _, streams = client.json("GET", "/sensor/streams")
            local_stream = _stream_for_sensor(streams, local_sensor_id)
            if (
                local_stream.get("streamId") != local_sensor_id
                or local_stream.get("type") != "Rtsp"
                or local_stream.get("metadata", {}).get("codec") != "h264"
                or local_stream.get("metadata", {}).get("resolution") != "320x180"
            ):
                raise QualificationError("automatic local-mount RTSP stream metadata differs")
            rtsp = _rtsp_probe(local_stream.get("url", ""))
            snapshot = _snapshot(client, local_sensor_id, snapshot_path)

            for stream_id in sorted(owned_stream_ids):
                quoted = urllib.parse.quote(stream_id, safe="")
                status, _ = client.json("DELETE", f"/storage/file/{quoted}", expected={200})
                cleanup.append({"operation": "owned-file-delete", "stream_id": stream_id, "status": status})
            post_sensor_list = _wait_for_no_owned_sensors(client, prefix)
            if any(path.name.startswith(prefix) for path in media.iterdir()):
                raise QualificationError("executor-owned media remains after API delete")

            result = {
                "schema_version": 1,
                "qualification_id": "thor-vss-3.2.1-nvstreamer-file-workflow-runtime",
                "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "status": "passed",
                "runtime_evidence": True,
                "target": {
                    "product_version": "3.2.1",
                    "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
                },
                "capability_results": {
                    CAPABILITY_ID: "passed_current",
                    "nvstreamer_upload_input": "passed_current",
                    "nvstreamer_ui_input": "passed_current",
                    "nvstreamer_local_mount_input": "passed_current",
                    "nvstreamer_rtsp_output": "passed_current",
                    "nvstreamer_webrtc_playback": "passed_current",
                    "nvstreamer_remove_supported": "passed_current",
                },
                "bounds": {
                    "http_endpoint": BASE,
                    "http_loopback_only": True,
                    "rtsp_loopback_only": True,
                    "browser_external_request_count": ui_receipt["network"]["external_request_count"],
                    "warehouse_sample_bundle_used": False,
                    "main_vios_sensor_added": False,
                    "rt_cv_stream_added": False,
                    "agent_generate_called": False,
                    "existing_container_count": len(non_owned_all_before),
                    "existing_running_container_count": len(non_owned_running_before),
                },
                "identity": {
                    "image": container,
                    "service_version": version,
                    "config_sha256": _sha_file(CONFIG),
                    "storage_config_sha256": _sha_file(STORAGE_CONFIG),
                    "executor_sha256": _sha_file(Path(__file__).resolve()),
                    "ui_harness_sha256": _sha_file(UI_HARNESS),
                },
                "fixture": fixture,
                "observations": {
                    "input_modes": ["upload", "ui", "local-mount"],
                    "automatic_output": "RTSP",
                    "playback": "WebRTC",
                    "remove_supported": True,
                    "sensor_names": sorted(sensors),
                    "sensor_states": {name: sensor.get("state") for name, sensor in sensors.items()},
                    "direct_upload": {
                        "status": next(
                            receipt["status"]
                            for receipt in client.receipts
                            if receipt["method"] == "POST" and receipt["path"] == "/storage/file"
                        ),
                        "id": api_upload["id"],
                        "stream_id": api_upload["streamId"],
                    },
                    "ui": ui_receipt,
                    "local_mount": {
                        "sensor_id": local_sensor_id,
                        "location_suffix": Path(local_sensor.get("location", "")).name,
                        "rtsp_url": local_stream["url"],
                    },
                    "rtsp_probe": rtsp,
                    "snapshot": snapshot,
                    "invalid_media_status": invalid_status,
                    "post_sensor_list_count": len(post_sensor_list),
                    "request_accounting": {
                        "executor_http_responses": len(client.receipts),
                        "browser_api_responses": ui_receipt["network"]["api_response_count"],
                        "browser_api_failures": ui_receipt["network"]["api_failure_count"],
                        "browser_websocket_frames_sent": ui_receipt["network"]["websocket"]["frames_sent"],
                    },
                },
                "cleanup": {
                    "result": "pending_container_cleanup",
                    "owned_stream_ids": sorted(owned_stream_ids),
                    "owned_sensors_absent": True,
                    "owned_media_absent": True,
                    "attempts": cleanup,
                },
                "requests": client.receipts,
            }
        except Exception as exc:
            primary_error = exc
        finally:
            if _container_exists():
                try:
                    _, current_sensors = client.json("GET", "/sensor/list")
                    remaining_stream_ids: set[str] = set()
                    for item in current_sensors if isinstance(current_sensors, list) else []:
                        name = item.get("name") if isinstance(item, dict) else None
                        sensor_id = item.get("sensorId") if isinstance(item, dict) else None
                        if isinstance(name, str) and name.startswith(prefix) and isinstance(sensor_id, str):
                            remaining_stream_ids.add(sensor_id)
                    for stream_id in sorted(remaining_stream_ids):
                        try:
                            status, _ = client.json(
                                "DELETE",
                                f"/storage/file/{urllib.parse.quote(stream_id, safe='')}",
                                expected={200, 404},
                            )
                            cleanup.append(
                                {"operation": "finally-owned-file-delete", "stream_id": stream_id, "status": status}
                            )
                        except Exception as exc:
                            cleanup.append(
                                {"operation": "finally-owned-file-delete", "stream_id": stream_id, "error": str(exc)}
                            )
                except Exception as exc:
                    cleanup.append({"operation": "finally-sensor-list", "error": str(exc)})
            _stop_remove_container(cleanup)

        non_owned_all_after = _docker_ids(running=False)
        non_owned_running_after = _docker_ids(running=True)
        ports_restored = all(
            _port_free(protocol, port)
            for protocol, ports in (("tcp", TCP_PORTS), ("udp", UDP_PORTS))
            for port in ports
        )
        restoration = {
            "exact_container_inventory_restored": non_owned_all_after == non_owned_all_before,
            "exact_running_set_restored": non_owned_running_after == non_owned_running_before,
            "all_reserved_ports_released": ports_restored,
        }
        if not all(restoration.values()):
            raise QualificationError(f"non-owned Docker/port state was not restored: {restoration}")
        if primary_error is not None:
            if isinstance(primary_error, QualificationError):
                raise primary_error
            raise QualificationError("NvStreamer runtime transaction failed") from primary_error
        if result is None:
            raise QualificationError("NvStreamer runtime transaction produced no result")
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
