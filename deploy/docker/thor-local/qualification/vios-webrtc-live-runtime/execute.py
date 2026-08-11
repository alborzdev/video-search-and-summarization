#!/usr/bin/env python3
"""Qualify live VIOS WebRTC against an isolated local RTSP fixture on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT = HERE / "fixture-contract.json"
HARNESS = HERE / "harness.mjs"
HELPER_PATH = (
    REPO
    / "deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/execute.py"
)
UI_ORIGIN = "http://127.0.0.1:31000"
NV_BASE = f"{UI_ORIGIN}/vst/api/v1"
MAIN_VIOS_BASE = "http://127.0.0.1:7777/vst/api/v1"
CHROMIUM_EXECUTABLE = Path("/snap/bin/chromium")
PLAYWRIGHT_MODULE = Path(
    "/home/nvidia/cti-saa-thor/scene-analyzer-agent/node_modules/.pnpm/"
    "playwright@1.61.1/node_modules/playwright/index.mjs"
)
ACK = "I_ACK_VIOS_WEBRTC_LIVE_EPHEMERAL_RUNTIME"
CAPABILITY_ID = "protocol.vios.webrtc-live"
ORACLE_PATTERN = r"^vss_qual_nvstreamer_[0-9a-f]{12}_api_upload$"
BOOTSTRAP_PATTERN = r"^vss_qual_nvstreamer_[0-9a-f]{12}_local_mount$"
MAX_RESPONSE = 2 * 1024 * 1024


class QualificationError(RuntimeError):
    """The bounded live-WebRTC transaction did not satisfy its contract."""


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
    command: list[str], *, timeout: int = 30, check: bool = True
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
        detail = stderr.decode(errors="replace")[-1600:]
        raise QualificationError(
            f"command failed: {command[0]}: {detail}"
        ) from exc


def _load_helper() -> Any:
    if not HELPER_PATH.is_file() or HELPER_PATH.is_symlink():
        raise QualificationError("pinned NvStreamer helper is absent or unsafe")
    spec = importlib.util.spec_from_file_location("vss_nvstreamer_fixture_helper", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load pinned NvStreamer helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise QualificationError("unsafe receipt output")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if len(raw) > MAX_RESPONSE:
        raise QualificationError("receipt exceeds output bound")
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


def _load_contract() -> tuple[dict[str, Any], bytes]:
    raw = CONTRACT.read_bytes()
    value = _strict_json(raw, "fixture contract")
    if (
        not isinstance(value, dict)
        or value.get("capability_id") != CAPABILITY_ID
        or value.get("acknowledgement") != ACK
        or value.get("contract") != {"mode": "live", "protocol": "webrtc"}
        or value.get("fixture", {}).get("sensor_name_pattern") != ORACLE_PATTERN
        or value.get("fixture", {}).get("bootstrap_sensor_name_pattern")
        != BOOTSTRAP_PATTERN
    ):
        raise QualificationError("fixture contract identity drifted")
    return value, raw


def _source_locks(contract: dict[str, Any]) -> list[dict[str, str]]:
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or not locks:
        raise QualificationError("source locks are absent")
    result: list[dict[str, str]] = []
    for lock in locks:
        relative = lock.get("path") if isinstance(lock, dict) else None
        expected = lock.get("sha256") if isinstance(lock, dict) else None
        if (
            not isinstance(relative, str)
            or not relative
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise QualificationError("invalid source lock")
        resolved = (REPO / relative).resolve()
        if not resolved.is_relative_to(REPO) or not resolved.is_file() or resolved.is_symlink():
            raise QualificationError(f"unsafe source lock: {relative}")
        observed = _sha_file(resolved)
        if observed != expected:
            raise QualificationError(f"source lock drifted: {relative}")
        result.append({"path": relative, "sha256": observed})
    return result


def _generated_fixture(helper: Any, contract: dict[str, Any], output: Path) -> dict[str, Any]:
    value = helper._fixture(output)
    expected = contract.get("fixture", {}).get("media", {})
    if (
        value.get("bytes") != expected.get("bytes")
        or value.get("sha256") != expected.get("sha256")
        or not output.is_file()
        or output.is_symlink()
    ):
        raise QualificationError("generated live fixture identity drifted")
    return value


def _http_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any = None,
    expected: set[int] = {200},
) -> tuple[int, Any, dict[str, Any]]:
    if base not in {MAIN_VIOS_BASE, NV_BASE} or not path.startswith("/") or "#" in path:
        raise QualificationError("unsafe HTTP target")
    body = None if payload is None else _canonical(payload)
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
        status = response.status
        raw = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read(MAX_RESPONSE + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise QualificationError(f"HTTP request failed: {method} {path}") from exc
    if len(raw) > MAX_RESPONSE or status not in expected:
        raise QualificationError(f"unexpected HTTP response: {method} {path}: {status}")
    value = _strict_json(raw, f"{method} {path}")
    receipt = {
        "method": method,
        "path": path,
        "status": status,
        "request_sha256": None if body is None else _sha(body),
        "response_bytes": len(raw),
        "response_sha256": _sha(raw),
    }
    return status, value, receipt


def _main_vios_state() -> dict[str, Any]:
    _, version, version_receipt = _http_json(MAIN_VIOS_BASE, "/sensor/version")
    _, sensors, sensors_receipt = _http_json(MAIN_VIOS_BASE, "/sensor/list")
    _, live_status, status_receipt = _http_json(MAIN_VIOS_BASE, "/live/stream/status")
    if not isinstance(version, dict) or version.get("type") != "vst":
        raise QualificationError("main VIOS is unavailable")
    if not isinstance(sensors, list):
        raise QualificationError("main VIOS sensor list is not an array")
    return {
        "sensor_count": len(sensors),
        "sensors_sha256": _sha(_canonical(sensors)),
        "aggregate_live_status_sha256": _sha(_canonical(live_status)),
        "version": version,
        "requests": [version_receipt, sensors_receipt, status_receipt],
    }


def _upload_fixture(
    helper: Any, client: Any, upload: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = helper._api_upload(client, upload, uuid.uuid4().hex)
    stream_id = value.get("streamId") if isinstance(value, dict) else None
    upload_id = value.get("id") if isinstance(value, dict) else None
    if (
        not isinstance(stream_id, str)
        or not stream_id
        or not isinstance(upload_id, str)
        or not upload_id
        or value.get("filename") != upload.stem
        or value.get("bytes") != upload.stat().st_size
    ):
        raise QualificationError("isolated NvStreamer upload identity drifted")
    request_receipt = next(
        (
            receipt
            for receipt in reversed(client.receipts)
            if receipt.get("method") == "POST" and receipt.get("path") == "/storage/file"
        ),
        None,
    )
    if not isinstance(request_receipt, dict) or request_receipt.get("status") not in {200, 201}:
        raise QualificationError("isolated NvStreamer upload request receipt is absent")
    receipt = {
        "method": "POST multipart single-request",
        "path": "/storage/file",
        "status": request_receipt["status"],
        "bytes": value["bytes"],
        "filename": value["filename"],
        "id_sha256": _sha(upload_id.encode()),
        "stream_id_sha256": _sha(stream_id.encode()),
    }
    return value, receipt


def _negative_missing_peer(stream_id: str) -> dict[str, Any]:
    payload = {
        "streamId": stream_id,
        "options": {"quality": "auto", "rtptransport": "udp", "timeout": 10},
        "sessionDescription": {"type": "offer", "sdp": "v=0"},
    }
    status, value, receipt = _http_json(
        NV_BASE,
        "/live/stream/start",
        method="POST",
        payload=payload,
        expected={400},
    )
    if status != 400 or not isinstance(value, dict) or value.get("error_code") != "InvalidParameterError":
        raise QualificationError("missing-peer vector was not rejected")
    _, aggregate, after_receipt = _http_json(NV_BASE, "/live/stream/status")
    if aggregate is not None:
        raise QualificationError("missing-peer vector retained a live peer")
    return {
        "id": "vios-live-missing-peer",
        "adjacent_mutation": {"operation": "remove", "path": "/peerId"},
        "error_code": value["error_code"],
        "no_peer_retained": True,
        "request": receipt,
        "status_after": after_receipt,
    }


def _wait_live_ready(client: Any, sensor_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    latest: Any = None
    while time.monotonic() < deadline:
        try:
            _, version = client.json("GET", "/live/version")
            _, streams = client.json(
                "GET", f"/sensor/{urllib.parse.quote(sensor_id, safe='')}/streams"
            )
            if not isinstance(streams, list) or len(streams) != 1:
                raise QualificationError("isolated sensor does not expose one stream")
            stream = streams[0]
            metadata = stream.get("metadata") if isinstance(stream, dict) else None
            if (
                isinstance(version, dict)
                and version.get("type") == "streamer"
                and isinstance(metadata, dict)
                and metadata.get("codec") == "h264"
                and metadata.get("resolution") == "320x180"
                and metadata.get("framerate") == "10.0"
            ):
                return {"version": version, "stream": stream}
            latest = {"version": version, "metadata": metadata}
        except Exception as exc:
            latest = {"error_type": type(exc).__name__, "error": str(exc)}
        time.sleep(0.5)
    raise QualificationError(f"isolated live service did not become ready: {latest}")


def _run_harness(
    sensor_name: str, stream_id: str, output: Path, run_id: str
) -> dict[str, Any]:
    if not CHROMIUM_EXECUTABLE.is_file():
        raise QualificationError("pinned Chromium executable is absent")
    if not PLAYWRIGHT_MODULE.is_file() or PLAYWRIGHT_MODULE.is_symlink():
        raise QualificationError("pinned Playwright module is absent or unsafe")
    completed = _run(
        [
            "node",
            str(HARNESS),
            "--ui-origin",
            UI_ORIGIN,
            "--chromium-executable",
            str(CHROMIUM_EXECUTABLE),
            "--playwright-module",
            str(PLAYWRIGHT_MODULE),
            "--sensor-name",
            sensor_name,
            "--stream-id-sha256",
            _sha(stream_id.encode()),
            "--output",
            str(output),
            "--run-id",
            run_id,
        ],
        timeout=120,
        check=False,
    )
    screenshot_path = Path(f"/tmp/vss-vios-webrtc-live-{run_id}.png")
    try:
        screenshot_path.unlink(missing_ok=True)
    except OSError as exc:
        raise QualificationError(
            f"browser screenshot cleanup failed: {type(exc).__name__}: {exc}"
        ) from exc
    summary = _strict_json(completed.stdout, "browser harness summary")
    value = _strict_json(output.read_bytes(), "browser runtime receipt")
    if (
        completed.returncode != 0
        or
        not isinstance(summary, dict)
        or summary.get("status") != "passed"
        or not isinstance(value, dict)
        or value.get("status") != "passed"
    ):
        detail = (
            {
                "errors": value.get("errors"),
                "diagnostic": value.get("diagnostic"),
                "network": value.get("network"),
            }
            if isinstance(value, dict)
            else None
        )
        raise QualificationError(f"browser harness did not pass: {detail}")
    return value


def _container_identity(helper: Any) -> dict[str, Any]:
    value = _strict_json(
        _run(["docker", "inspect", helper.CONTAINER]).stdout,
        "qualifier container inspect",
    )
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationError("qualifier container identity is ambiguous")
    item = value[0]
    if item.get("State", {}).get("Running") is not True:
        raise QualificationError("qualifier container is not running")
    return {
        "configured_image": item.get("Config", {}).get("Image"),
        "image_id": item.get("Image"),
        "network_mode": item.get("HostConfig", {}).get("NetworkMode"),
        "runtime": item.get("HostConfig", {}).get("Runtime"),
    }


def _container_bridge_ipv4(helper: Any) -> str:
    value = _strict_json(
        _run(["docker", "inspect", helper.CONTAINER]).stdout,
        "qualifier container network inspect",
    )
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationError("qualifier container network identity is ambiguous")
    networks = value[0].get("NetworkSettings", {}).get("Networks", {})
    addresses = [
        network.get("IPAddress")
        for network in networks.values()
        if isinstance(network, dict) and network.get("IPAddress")
    ]
    if len(addresses) != 1:
        raise QualificationError("qualifier container does not have one bridge IPv4")
    address = ipaddress.ip_address(addresses[0])
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise QualificationError("qualifier container bridge address is not private IPv4")
    return addresses[0]


def execute() -> dict[str, Any]:
    contract, contract_raw = _load_contract()
    locks = _source_locks(contract)
    helper = _load_helper()
    if helper._container_exists():
        raise QualificationError(f"reserved qualifier container already exists: {helper.CONTAINER}")
    occupied = [
        f"{protocol}/{port}"
        for protocol, ports in (("tcp", helper.TCP_PORTS), ("udp", helper.UDP_PORTS))
        for port in ports
        if not helper._port_free(protocol, port)
    ]
    if occupied:
        raise QualificationError(f"reserved qualifier ports are occupied: {occupied}")

    all_before = helper._docker_ids(running=False)
    running_before = helper._docker_ids(running=True)
    main_before = _main_vios_state()
    cleanup: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    primary_error: Exception | None = None
    run_id = uuid.uuid4().hex[:12]
    prefix = f"vss_qual_nvstreamer_{run_id}"
    oracle_name = f"{prefix}_api_upload"
    bootstrap_name = f"{prefix}_local_mount"

    with tempfile.TemporaryDirectory(prefix="vss-vios-webrtc-live-") as directory:
        root = Path(directory)
        media_dir = root / "media"
        media_dir.mkdir(mode=0o777)
        upload_dir = root / "upload"
        upload_dir.mkdir(mode=0o700)
        isolated_media = upload_dir / f"{oracle_name}.mp4"
        media = _generated_fixture(helper, contract, isolated_media)
        bootstrap_media = media_dir / f"{bootstrap_name}.mp4"
        shutil.copyfile(isolated_media, bootstrap_media)
        browser_receipt_path = root / "browser-receipt.json"
        try:
            image = helper._start_container(root)
            client = helper.Client()
            version = helper._wait_for_version(client, timeout=90)
            bootstrap_sensors = helper._wait_for_sensors(
                client, {bootstrap_name}, timeout=45
            )
            bootstrap_sensor_id = bootstrap_sensors[bootstrap_name].get("sensorId")
            if not isinstance(bootstrap_sensor_id, str) or not bootstrap_sensor_id:
                raise QualificationError("isolated bootstrap sensor identity is absent")
            _upload, upload_receipt = _upload_fixture(helper, client, isolated_media)
            sensors = helper._wait_for_sensors(client, {oracle_name}, timeout=45)
            sensor = sensors[oracle_name]
            sensor_id = sensor.get("sensorId")
            if not isinstance(sensor_id, str) or not sensor_id:
                raise QualificationError("isolated sensor identity is absent")
            readiness = _wait_live_ready(client, sensor_id)
            stream = readiness["stream"]
            stream_id = stream.get("streamId")
            rtsp_url = stream.get("url")
            parsed = urllib.parse.urlparse(rtsp_url) if isinstance(rtsp_url, str) else None
            bridge_ipv4 = _container_bridge_ipv4(helper)
            if (
                not isinstance(stream_id, str)
                or not stream_id
                or parsed is None
                or parsed.scheme != "rtsp"
                or parsed.hostname != bridge_ipv4
                or parsed.port not in range(31554, 31562)
                or parsed.username is not None
                or parsed.password is not None
            ):
                observed = {
                    "scheme": None if parsed is None else parsed.scheme,
                    "hostname": None if parsed is None else parsed.hostname,
                    "port": None if parsed is None else parsed.port,
                    "stream_id_present": isinstance(stream_id, str) and bool(stream_id),
                }
                raise QualificationError(
                    f"isolated RTSP stream escaped its contract: {observed}"
                )
            if upload_receipt["stream_id_sha256"] != _sha(stream_id.encode()):
                raise QualificationError("upload/API stream identity differs")
            negative = _negative_missing_peer(stream_id)
            browser_receipt = _run_harness(
                oracle_name, stream_id, browser_receipt_path, run_id
            )
            _, final_status = client.json("GET", "/live/stream/status")
            if final_status is not None:
                raise QualificationError("live peer remained after browser cleanup")
            result = {
                "schema_version": 1,
                "status": "passed",
                "qualification_id": contract["qualification_id"],
                "capability_id": CAPABILITY_ID,
                "oracle_id": contract["oracle_id"],
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "acknowledgement": ACK,
                "contract_sha256": _sha(contract_raw),
                "source_locks": locks,
                "fixture": {
                    **media,
                    "sensor_name": oracle_name,
                    "bootstrap_sensor_name": bootstrap_name,
                    "bootstrap_sensor_id_sha256": _sha(bootstrap_sensor_id.encode()),
                    "sensor_id_sha256": _sha(sensor_id.encode()),
                    "stream_id_sha256": _sha(stream_id.encode()),
                    "rtsp": {
                        "advertised_host_scope": "exact-owned-container-private-ipv4",
                        "host_publish": "127.0.0.1",
                        "advertised_port": parsed.port,
                        "advertised_port_range": [31554, 31561],
                        "host_published_port": 31554,
                        "scheme": "rtsp",
                    },
                    "warehouse_sample_bundle": False,
                },
                "runtime": {
                    "browser": browser_receipt,
                    "negative": negative,
                    "upload": upload_receipt,
                    "nvstreamer_version": version,
                    "container": _container_identity(helper),
                    "image": image,
                    "request_receipts": client.receipts,
                    "protocol_case": {
                        "case_id": "protocol-case.vios.webrtc-live",
                        "positive_vector_id": "vios-live-one-loopback-source",
                        "negative_vector_ids": ["vios-live-missing-peer"],
                    },
                },
                "privacy": contract["privacy"],
                "cleanup": {
                    "browser_session_stopped": browser_receipt["cleanup"]["stop_frame_observed"],
                    "browser_websocket_closed": browser_receipt["cleanup"]["websocket_closed"],
                    "isolated_aggregate_live_status_null": final_status is None,
                },
            }
        except Exception as exc:  # cleanup must run for every failure class
            primary_error = exc
        finally:
            helper._stop_remove_container(cleanup)

    all_after = helper._docker_ids(running=False)
    running_after = helper._docker_ids(running=True)
    main_after = _main_vios_state()
    ports_released = all(
        helper._port_free(protocol, port)
        for protocol, ports in (("tcp", helper.TCP_PORTS), ("udp", helper.UDP_PORTS))
        for port in ports
    )
    restoration = {
        "all_reserved_ports_released": ports_released,
        "exact_container_inventory_restored": all_after == all_before,
        "exact_running_set_restored": running_after == running_before,
        "main_vios_sensor_count_restored": main_after["sensor_count"] == main_before["sensor_count"],
        "main_vios_sensors_restored": main_after["sensors_sha256"] == main_before["sensors_sha256"],
        "main_vios_live_status_restored": (
            main_after["aggregate_live_status_sha256"]
            == main_before["aggregate_live_status_sha256"]
        ),
        "temporary_tree_removed": not Path(directory).exists(),
    }
    if primary_error is not None:
        if isinstance(primary_error, QualificationError):
            raise primary_error
        raise QualificationError(
            "live WebRTC runtime transaction failed: "
            f"{type(primary_error).__name__}: {primary_error}"
        ) from primary_error
    if result is None:
        raise QualificationError("live WebRTC runtime transaction produced no result")
    if not all(restoration.values()):
        raise QualificationError(f"host/main-VIOS state was not restored: {restoration}")
    result["cleanup"].update(restoration)
    result["cleanup"]["attempts"] = cleanup
    result["cleanup"]["main_vios_pre_state_sha256"] = _sha(_canonical(main_before))
    result["cleanup"]["main_vios_post_state_sha256"] = _sha(_canonical(main_after))
    return result


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "plan_only",
        "qualification_id": contract["qualification_id"],
        "capability_id": CAPABILITY_ID,
        "acknowledgement_required": ACK,
        "workflow": contract["workflow"],
        "bounds": contract["bounds"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract, _ = _load_contract()
        if args.execute:
            if args.ack != ACK:
                raise QualificationError(f"exact acknowledgement required: {ACK}")
            receipt = execute()
        else:
            receipt = _plan(contract)
        output = args.output.resolve()
        if output.parent != HERE or output.name not in {
            "runtime-receipt.json",
            "plan-receipt.json",
            "refresh-receipt.json",
        }:
            raise QualificationError("output must be a reserved package receipt path")
        _write_json(output, receipt)
    except (OSError, QualificationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": str(output),
                "receipt_sha256": _sha(output.read_bytes()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
