#!/usr/bin/env python3
"""Qualify native VIOS WebRTC archive replay against a retained local clip."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT = HERE / "fixture-contract.json"
HARNESS = HERE / "harness.mjs"
BASE = "http://127.0.0.1:7777/vst/api/v1"
UI_ORIGIN = "http://127.0.0.1:7777"
CDP_ORIGIN = "http://127.0.0.1:9223"
PLAYWRIGHT_MODULE = Path(
    "/home/nvidia/cti-saa-thor/scene-analyzer-agent/node_modules/.pnpm/"
    "playwright@1.61.1/node_modules/playwright/index.mjs"
)
ACK = "I_ACK_VIOS_WEBRTC_REPLAY_EPHEMERAL_RUNTIME"
CAPABILITY_ID = "protocol.vios.webrtc-replay"
MAX_RESPONSE = 2 * 1024 * 1024
CONTAINERS = (
    "vss-vios-ingress",
    "vss-vios-streamprocessing",
    "vss-vios-sensor",
)


class QualificationError(RuntimeError):
    """The bounded replay transaction did not satisfy its contract."""


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
        detail = stderr.decode(errors="replace")[-1200:]
        raise QualificationError(f"command failed: {command[0]}: {detail}") from exc


def _docker_ids(*, running: bool) -> list[str]:
    command = ["docker", "ps", "--no-trunc", "--format", "{{.ID}}"]
    if not running:
        command.insert(2, "-a")
    return sorted(line for line in _run(command).stdout.decode().splitlines() if line)


def _docker_identity(name: str) -> dict[str, Any]:
    value = _strict_json(
        _run(["docker", "inspect", name], timeout=10).stdout,
        f"Docker inspect {name}",
    )
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationError(f"Docker identity is ambiguous: {name}")
    item = value[0]
    image_id = item.get("Image")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise QualificationError(f"Docker image identity is absent: {name}")
    health = item.get("State", {}).get("Health", {}).get("Status")
    if item.get("State", {}).get("Running") is not True or health not in (None, "healthy"):
        raise QualificationError(f"required container is not healthy: {name}")
    return {
        "configured_image": item.get("Config", {}).get("Image"),
        "health": health or "running-no-healthcheck",
        "image_id": image_id,
        "name": name,
        "network_mode": item.get("HostConfig", {}).get("NetworkMode"),
    }


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


class Client:
    def __init__(self) -> None:
        self.receipts: list[dict[str, Any]] = []

    def json(
        self,
        path: str,
        *,
        label: str,
        headers: dict[str, str] | None = None,
        expected: set[int] = {200},
    ) -> Any:
        if not path.startswith("/") or "#" in path:
            raise QualificationError("unsafe API path")
        request = urllib.request.Request(BASE + path, headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=10)
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise QualificationError(f"VIOS request failed: {label}") from exc
        if len(raw) > MAX_RESPONSE:
            raise QualificationError(f"oversized VIOS response: {label}")
        self.receipts.append(
            {
                "label": label,
                "method": "GET",
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "status": status,
            }
        )
        if status not in expected:
            raise QualificationError(f"unexpected HTTP {status}: {label}")
        return _strict_json(raw, label)


def _load_contract() -> tuple[dict[str, Any], bytes]:
    raw = CONTRACT.read_bytes()
    value = _strict_json(raw, "fixture contract")
    if (
        not isinstance(value, dict)
        or value.get("capability_id") != CAPABILITY_ID
        or value.get("acknowledgement") != ACK
        or value.get("contract") != {"mode": "replay", "protocol": "webrtc"}
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


def _media_identity(contract: dict[str, Any]) -> dict[str, Any]:
    media = contract.get("fixture", {}).get("media", {})
    relative = media.get("path")
    if not isinstance(relative, str):
        raise QualificationError("fixture media path is absent")
    path = (REPO / relative).resolve()
    if not path.is_relative_to(REPO) or not path.is_file() or path.is_symlink():
        raise QualificationError("fixture media is absent or unsafe")
    raw_sha = _sha_file(path)
    if raw_sha != media.get("sha256") or path.stat().st_size != media.get("bytes"):
        raise QualificationError("fixture media identity drifted")
    probe = _strict_json(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size,format_name",
                "-show_entries",
                "stream=index,codec_name,codec_type,width,height,r_frame_rate,has_b_frames",
                "-of",
                "json",
                str(path),
            ]
        ).stdout,
        "fixture ffprobe",
    )
    streams = probe.get("streams", [])
    video = [item for item in streams if item.get("codec_type") == "video"]
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    if (
        len(video) != 1
        or video[0].get("codec_name") != "h264"
        or video[0].get("width") != 1280
        or video[0].get("height") != 720
        or video[0].get("has_b_frames") != 0
        or video[0].get("r_frame_rate") != "60/1"
        or len(audio) != 1
        or audio[0].get("codec_name") != "aac"
        or probe.get("format", {}).get("duration") != "19.209000"
    ):
        raise QualificationError("fixture media contract drifted")
    return {
        "bytes": path.stat().st_size,
        "duration_seconds": 19.209,
        "path": relative,
        "sha256": raw_sha,
        "streams": streams,
    }


def _find_fixture(client: Client, sensor_name: str) -> dict[str, Any]:
    sensors = client.json("/sensor/list", label="sensor-list")
    if not isinstance(sensors, list):
        raise QualificationError("sensor list is not an array")
    matches = [item for item in sensors if item.get("name") == sensor_name]
    if len(matches) != 1:
        raise QualificationError("retained replay fixture sensor is absent or ambiguous")
    sensor = matches[0]
    sensor_id = sensor.get("sensorId")
    if (
        not isinstance(sensor_id, str)
        or not sensor_id
        or sensor.get("state") != "online"
        or sensor.get("type") != "sensor_file"
        or sensor.get("isTimelinePresent") is not True
    ):
        raise QualificationError("retained replay fixture sensor is not ready")
    streams = client.json(
        f"/sensor/{urllib.parse.quote(sensor_id, safe='')}/streams",
        label="fixture-sensor-streams",
    )
    if not isinstance(streams, list):
        raise QualificationError("fixture streams are not an array")
    mains = [item for item in streams if item.get("isMain") is True]
    selected = mains[0] if len(mains) == 1 else streams[0] if len(streams) == 1 else None
    stream_id = selected.get("streamId") if isinstance(selected, dict) else None
    if not isinstance(stream_id, str) or not stream_id:
        raise QualificationError("fixture main stream is absent or ambiguous")
    timelines = client.json(
        f"/storage/{urllib.parse.quote(stream_id, safe='')}/timelines",
        label="fixture-timelines",
    )
    if not isinstance(timelines, list) or not timelines:
        raise QualificationError("fixture timeline is absent")
    replay_streams = client.json("/replay/streams", label="replay-streams")
    if not isinstance(replay_streams, list):
        raise QualificationError("replay stream list is not an array")
    return {
        "sensor_id": sensor_id,
        "stream_id": stream_id,
        "sensor": sensor,
        "streams": streams,
        "timelines": timelines,
        "replay_streams": replay_streams,
    }


def _state_projection(value: dict[str, Any]) -> dict[str, Any]:
    sensor = value["sensor"]
    return {
        "replay_streams_sha256": _sha(_canonical(value["replay_streams"])),
        "sensor": {
            "id_sha256": _sha(value["sensor_id"].encode()),
            "is_timeline_present": sensor.get("isTimelinePresent"),
            "name": sensor.get("name"),
            "state": sensor.get("state"),
            "type": sensor.get("type"),
        },
        "streams_sha256": _sha(_canonical(value["streams"])),
        "stream_id_sha256": _sha(value["stream_id"].encode()),
        "timelines": value["timelines"],
        "timelines_sha256": _sha(_canonical(value["timelines"])),
    }


def _run_harness(stream_id: str, sensor_name: str, run_id: str, output: Path) -> dict[str, Any]:
    result = _run(
        [
            "node",
            str(HARNESS),
            "--ui-origin",
            UI_ORIGIN,
            "--cdp-origin",
            CDP_ORIGIN,
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
        timeout=130,
    )
    summary = _strict_json(result.stdout, "browser harness summary")
    value = _strict_json(output.read_bytes(), "browser harness receipt")
    if summary.get("status") != "passed" or value.get("status") != "passed":
        raise QualificationError("browser replay transaction did not pass")
    return value


def execute(run_id: str) -> dict[str, Any]:
    contract, contract_raw = _load_contract()
    source_locks = _source_locks(contract)
    media = _media_identity(contract)
    if not HARNESS.is_file() or HARNESS.is_symlink() or not PLAYWRIGHT_MODULE.is_file():
        raise QualificationError("browser qualification prerequisites are absent")

    all_before = _docker_ids(running=False)
    running_before = _docker_ids(running=True)
    containers_before = [_docker_identity(name) for name in CONTAINERS]
    client = Client()
    sensor_name = contract["fixture"]["sensor_name"]
    sensor_version = client.json("/sensor/version", label="sensor-version")
    replay_version = client.json("/replay/version", label="replay-version")
    replay_configuration = client.json(
        "/replay/configuration", label="replay-configuration"
    )
    if (
        sensor_version.get("type") != "vst"
        or sensor_version.get("version") != contract["target"]["service_version"]
        or replay_version != sensor_version
        or replay_configuration.get("stunUrlList") != ["127.0.0.1:3478"]
        or replay_configuration.get("useTwilioStunTurn") is not False
        or replay_configuration.get("useReverseProxy") is not False
    ):
        raise QualificationError("VIOS identity or offline WebRTC configuration drifted")
    pre = _find_fixture(client, sensor_name)
    pre_projection = _state_projection(pre)
    pre_status = client.json(
        "/replay/stream/status",
        label="pre-replay-status",
        headers={"streamId": pre["stream_id"]},
    )
    if pre_status is not None:
        raise QualificationError("an unrelated replay session is already active")

    ingress_source = REPO / "deploy/docker/services/vios/configs/nginx-vst-direct.conf"
    ingress_runtime = _run(
        ["docker", "exec", "vss-vios-ingress", "cat", "/etc/nginx/nginx.conf"],
        timeout=10,
    ).stdout
    if _sha(ingress_runtime) != _sha_file(ingress_source):
        raise QualificationError("running ingress configuration differs from the source lock")

    with tempfile.TemporaryDirectory(prefix="vss-vios-webrtc-replay-") as directory:
        browser_output = Path(directory) / "browser-receipt.json"
        browser = _run_harness(pre["stream_id"], sensor_name, run_id, browser_output)

    post = _find_fixture(client, sensor_name)
    post_projection = _state_projection(post)
    post_status = client.json(
        "/replay/stream/status",
        label="post-replay-status",
        headers={"streamId": post["stream_id"]},
    )
    all_after = _docker_ids(running=False)
    running_after = _docker_ids(running=True)
    containers_after = [_docker_identity(name) for name in CONTAINERS]
    restoration = {
        "container_inventory_restored": all_after == all_before,
        "fixture_state_restored": post_projection == pre_projection,
        "no_replay_session_before": pre_status is None,
        "no_replay_session_after": post_status is None,
        "required_container_identities_restored": containers_after == containers_before,
        "running_set_restored": running_after == running_before,
    }
    if not all(restoration.values()):
        raise QualificationError(f"replay postconditions failed: {restoration}")

    target_commit = _run(["git", "rev-parse", "HEAD"], timeout=10).stdout.decode().strip()
    return {
        "schema_version": 1,
        "qualification_id": "thor-vss-3.2.1-vios-webrtc-replay-runtime",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "passed",
        "runtime_evidence": True,
        "capability_results": {CAPABILITY_ID: "passed_current"},
        "target": {
            "product_version": contract["target"]["product_version"],
            "service_version": sensor_version["version"],
            "target_commit": target_commit,
            "upstream_main_commit": contract["target"]["upstream_main_commit"],
        },
        "bounds": {
            "agent_generate_called": False,
            "browser_external_request_count": browser["network"]["external_requests"],
            "browser_http_response_count": browser["network"]["http_response_count"],
            "browser_websocket_frame_count": browser["network"]["websocket_frame_count"],
            "docker_lifecycle_actions": 0,
            "http_loopback_only": True,
            "main_vios_sensor_added": False,
            "persistent_mutations": 0,
            "rt_cv_stream_added": False,
            "warehouse_sample_bundle_used": False,
        },
        "identity": {
            "containers": containers_before,
            "contract_sha256": _sha(contract_raw),
            "executor_sha256": _sha_file(Path(__file__).resolve()),
            "harness_sha256": _sha_file(HARNESS),
            "ingress_runtime_config_sha256": _sha(ingress_runtime),
            "playwright_module_sha256": _sha_file(PLAYWRIGHT_MODULE),
            "replay_configuration_sha256": _sha(_canonical(replay_configuration)),
            "source_locks": source_locks,
        },
        "fixture": media
        | {
            "sensor_name": sensor_name,
            "sensor_id_sha256": pre_projection["sensor"]["id_sha256"],
            "stream_id_sha256": pre_projection["stream_id_sha256"],
            "timeline": pre_projection["timelines"],
        },
        "observations": {
            "browser": browser,
            "contract": contract["contract"],
            "semantic_result": {
                "decoded_frames_before_seek": browser["webrtc"]["first_sample"]["decoded_frames"],
                "decoded_frames_after_seek": browser["webrtc"]["final_sample"]["decoded_frames"],
                "height": browser["webrtc"]["final_sample"]["video_height"],
                "live_unmuted_video_track": any(
                    track.get("ready_state") == "live" and track.get("muted") is False
                    for track in browser["webrtc"]["final_sample"]["tracks"]
                ),
                "ready_state": browser["webrtc"]["final_sample"]["ready_state"],
                "width": browser["webrtc"]["final_sample"]["video_width"],
            },
            "wire_contract": {
                "get_position_without_action_status": browser["controls"]["position_lookup"]["status"],
                "invalid_action_error_code": browser["controls"]["invalid_action"]["error_code"],
                "invalid_action_status": browser["controls"]["invalid_action"]["status"],
                "positive_seek_status": browser["controls"]["positive_relative_seek"]["status"],
                "signaling_complete": browser["webrtc"]["signaling_complete"],
                "stop_frame_observed": browser["cleanup"]["stop_frame_observed"],
                "ui_seek_status": browser["controls"]["ui_seek_forward"]["status"],
                "websocket_closed": browser["cleanup"]["websocket_closed"],
                "websocket_path": browser["webrtc"]["websocket_path"],
            },
        },
        "pre_state": pre_projection,
        "post_state": post_projection,
        "cleanup": restoration | {"result": "passed"},
        "requests": client.receipts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id", default="official")
    args = parser.parse_args()
    if not args.execute:
        contract, _ = _load_contract()
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "plan",
                    "default_execution_enabled": False,
                    "acknowledgement": ACK,
                    "bounds": contract["bounds"],
                    "persistent_mutation": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.ack != ACK or args.output is None:
        print(json.dumps({"status": "failed", "error": "authorization_required"}))
        return 2
    if not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.run_id):
        print(json.dumps({"status": "failed", "error": "invalid_run_id"}))
        return 2
    try:
        receipt = execute(args.run_id)
        output = args.output.resolve()
        _write_json(output, receipt)
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
