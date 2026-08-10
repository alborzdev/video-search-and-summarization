#!/usr/bin/env python3
"""Qualify the exact NVIDIA alert WebSocket contract in an owned namespace."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

import websockets


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"


class QualificationError(RuntimeError):
    """The isolated WebSocket qualification failed closed."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise QualificationError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _command(
    args: list[str], *, timeout: float = 30, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise QualificationError(f"command failed ({args[0]}): {message[-800:]}")
    return completed


def _docker_json(args: list[str]) -> Any:
    return json.loads(_command(["docker", *args]).stdout)


def _container(name: str) -> dict[str, Any]:
    rows = _docker_json(["inspect", name])
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError(f"could not inspect exact container {name}")
    return rows[0]


def _image(reference: str) -> dict[str, Any]:
    rows = _docker_json(["image", "inspect", reference])
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError(f"could not inspect exact image {reference}")
    return rows[0]


def _http_json(url: str, *, timeout: float = 5) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise QualificationError(f"unexpected HTTP status from {url}")
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise QualificationError(f"non-object JSON from {url}")
    return value


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _redis_keys() -> list[str]:
    result = _command(
        ["docker", "exec", "redis", "redis-cli", "--scan", "--pattern", "*"],
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _redis_groups(stream: str) -> list[dict[str, Any]]:
    result = _command(
        [
            "docker",
            "exec",
            "redis",
            "redis-cli",
            "--json",
            "XINFO",
            "GROUPS",
            stream,
        ]
    )
    value = json.loads(result.stdout)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise QualificationError("Redis XINFO GROUPS did not return object rows")
    return value


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    source_hashes: dict[str, str] = {}
    for lock in contract["source_locks"]:
        actual = _sha((REPO / lock["path"]).read_bytes())
        if actual != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
        source_hashes[lock["path"]] = actual

    fixture = contract["fixture"]
    for path_key, hash_key in (
        ("config_path", "config_sha256"),
        ("server_path", "server_sha256"),
    ):
        if _sha((REPO / fixture[path_key]).read_bytes()) != fixture[hash_key]:
            raise QualificationError(f"fixture lock drifted: {fixture[path_key]}")

    protocol_lock = contract["protocol_case"]
    protocol, protocol_raw = _load(REPO / protocol_lock["path"])
    if _sha(protocol_raw) != protocol_lock["file_sha256"]:
        raise QualificationError("protocol-case file digest drifted")
    if protocol["contract_set_sha256"] != protocol_lock["contract_set_sha256"]:
        raise QualificationError("protocol-case set digest drifted")
    case = next(
        row for row in protocol["cases"] if row["case_id"] == protocol_lock["case_id"]
    )
    if _canonical_sha(case) != protocol_lock["case_sha256"]:
        raise QualificationError("alert WebSocket protocol case drifted")
    if case["positive_vector"]["id"] != protocol_lock["positive_vector_id"] or [
        row["id"] for row in case["adjacent_negative_vectors"]
    ] != [protocol_lock["negative_vector_id"]]:
        raise QualificationError("alert WebSocket vector binding drifted")
    return {
        "source_hashes": source_hashes,
        "fixture_hashes": {
            fixture["config_path"]: fixture["config_sha256"],
            fixture["server_path"]: fixture["server_sha256"],
        },
        "protocol_case_sha256": protocol_lock["case_sha256"],
    }


def _verify_runtime_identity(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract["runtime"]
    image = _image(runtime["image"])
    if (
        image["Id"] != runtime["image_id"]
        or image["Architecture"] != runtime["architecture"]
    ):
        raise QualificationError("alert runtime image identity drifted")
    redis = _container(runtime["redis"]["container"])
    if (
        redis["Image"] != runtime["redis"]["image_id"]
        or redis.get("State", {}).get("Health", {}).get("Status") != "healthy"
    ):
        raise QualificationError("Redis broker identity/health drifted")
    main = _container(runtime["main_service"]["container"])
    if main["Image"] != runtime["image_id"] or main["State"]["Running"] is not True:
        raise QualificationError("normal alert service identity/health drifted")
    return {
        "image": runtime["image"],
        "image_id": image["Id"],
        "architecture": image["Architecture"],
        "redis_image_id": redis["Image"],
        "redis_health": "healthy",
        "main_service_running": True,
    }


def _normal_health_contract(value: dict[str, Any]) -> dict[str, Any]:
    consumer = value.get("redis_consumer", {})
    return {
        "status": value.get("status"),
        "service": value.get("service"),
        "active_connections": value.get("active_connections"),
        "consumer_running": consumer.get("is_running"),
        "streams": consumer.get("streams"),
    }


def _start_isolated(contract: dict[str, Any]) -> None:
    runtime = contract["runtime"]
    source = REPO / "services/alert/alert-agent-web"
    config = REPO / contract["fixture"]["config_path"]
    server = REPO / contract["fixture"]["server_path"]
    _command(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            runtime["container"],
            "--network",
            "host",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,src={source},dst=/app/alert-agent-web,readonly",
            "--mount",
            f"type=bind,src={config},dst=/fixture/config.yaml,readonly",
            "--mount",
            f"type=bind,src={server},dst=/server.py,readonly",
            "--env",
            "CONFIG_PATH=/fixture/config.yaml",
            "--entrypoint",
            "python3",
            runtime["image"],
            "/server.py",
        ],
        timeout=30,
    )


def _wait_ready(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract["runtime"]
    url = f"http://127.0.0.1:{runtime['port']}/ws/health"
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = _http_json(url, timeout=1)
            consumer = health.get("redis_consumer", {})
            expected_streams = [
                contract["owned_resources"]["input_stream"],
                contract["owned_resources"]["enhanced_stream"],
            ]
            if (
                health.get("status") == "healthy"
                and health.get("active_connections") == 0
                and consumer.get("is_running") is True
                and consumer.get("streams") == expected_streams
            ):
                return health
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise QualificationError(f"isolated WebSocket did not become ready: {last_error}")


def _redis_xadd(stream: str, fields: dict[str, str]) -> str:
    args = ["docker", "exec", "redis", "redis-cli", "XADD", stream, "*"]
    for key, value in fields.items():
        args.extend([key, value])
    message_id = _command(args).stdout.strip()
    if not message_id or "-" not in message_id:
        raise QualificationError("Redis did not return an owned message ID")
    return message_id


async def _exercise(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract["runtime"]
    owned = contract["owned_resources"]
    uri = f"ws://127.0.0.1:{runtime['port']}{runtime['path']}"
    frames: list[str] = []
    async with websockets.connect(
        uri,
        proxy=None,
        open_timeout=5,
        close_timeout=5,
        ping_interval=None,
        max_size=1024 * 1024,
    ) as websocket:
        await websocket.send(json.dumps(contract["positive"]["client_frame"]))
        pong = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        if pong.get("type") != "pong" or not str(pong.get("timestamp", "")).endswith(
            "Z"
        ):
            raise QualificationError("exact pong frame was not observed")
        frames.append("pong")

        await websocket.send(contract["adjacent_negative"]["client_frame"])
        negative_silent = False
        try:
            await asyncio.wait_for(
                websocket.recv(),
                timeout=contract["adjacent_negative"]["observation_seconds"],
            )
        except TimeoutError:
            negative_silent = True
        if not negative_silent:
            raise QualificationError("non-JSON adjacent negative received a frame")

        message_id = await asyncio.to_thread(
            _redis_xadd,
            owned["input_stream"],
            contract["positive"]["redis_fields"],
        )
        alert = json.loads(await asyncio.wait_for(websocket.recv(), timeout=15))
        expected_data = contract["positive"]["redis_fields"]
        if (
            alert.get("type") != "alert"
            or alert.get("alert_type") != "original"
            or alert.get("stream_name") != owned["input_stream"]
            or alert.get("message_id") != message_id
            or alert.get("data") != expected_data
            or not str(alert.get("timestamp", "")).endswith("Z")
        ):
            raise QualificationError(
                "alert delivery frame differed from owned Redis entry"
            )
        frames.append("alert")

        await websocket.send(json.dumps({"type": "get_status"}))
        status = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        if (
            status.get("type") != "status"
            or status.get("total_connections") != 1
            or not str(status.get("timestamp", "")).endswith("Z")
        ):
            raise QualificationError("exact status frame was not observed")
        frames.append("status")

        groups = await asyncio.to_thread(_redis_groups, owned["input_stream"])
        if (
            len(groups) != 1
            or not str(groups[0].get("name", "")).startswith(
                owned["consumer_group_prefix"] + "_"
            )
            or groups[0].get("pending") != 0
            or groups[0].get("consumers") != 1
        ):
            raise QualificationError("Redis callback-before-XACK contract differed")

    return {
        "status": "passed",
        "positive": {
            "vector_id": contract["protocol_case"]["positive_vector_id"],
            "handshake": "HTTP Upgrade to WebSocket",
            "pong_observed": True,
            "alert_frame_count": 1,
            "redis_fields_preserved": True,
            "message_id_match": True,
            "alert_type": "original",
            "status_connections": 1,
            "frames": frames,
            "pending_after_callback": 0,
        },
        "negative": {
            "vector_id": contract["protocol_case"]["negative_vector_id"],
            "frame": "non-json",
            "application_response_observed": False,
            "socket_remained_open": True,
        },
    }


def _cleanup(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract["runtime"]
    owned = contract["owned_resources"]
    failures: list[str] = []
    result = _command(["docker", "rm", "-f", runtime["container"]], check=False)
    if result.returncode not in (0, 1):
        failures.append("isolated_container_remove_failed")
    for stream in (owned["input_stream"], owned["enhanced_stream"]):
        result = _command(
            ["docker", "exec", "redis", "redis-cli", "DEL", stream],
            check=False,
        )
        if result.returncode != 0:
            failures.append(f"owned_stream_delete_failed:{stream}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        container_absent = (
            _command(
                ["docker", "inspect", runtime["container"]], check=False
            ).returncode
            != 0
        )
        streams_absent = all(
            stream not in _redis_keys()
            for stream in (owned["input_stream"], owned["enhanced_stream"])
        )
        if container_absent and streams_absent and not _port_open(runtime["port"]):
            break
        time.sleep(0.25)
    else:
        failures.append("owned_resources_still_present")
    return {"attempted": True, "failures": failures}


def execute() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    contract, contract_raw = _load(CONTRACT_PATH)
    runtime = contract["runtime"]
    owned = contract["owned_resources"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "status": "failed",
        "failure": None,
        "blockers": [],
        "captured_at": started.isoformat().replace("+00:00", "Z"),
        "contract_sha256": _sha(contract_raw),
        "target_release": contract["target_release"],
        "target_commit": contract["target_commit"],
        "network_scope": contract["network_scope"],
        "warehouse_sample_bundle": False,
        "semantic_action_count": 0,
        "forbidden_actions_observed": [],
        "writes_or_lifecycle_actions": False,
    }
    mutation_started = False
    before_keys: list[str] = []
    normal_before: dict[str, Any] = {}
    try:
        receipt["static_contract"] = _verify_static(contract)
        receipt["runtime_identity"] = _verify_runtime_identity(contract)
        before_keys = _redis_keys()
        normal_before = _normal_health_contract(
            _http_json(runtime["main_service"]["health_url"])
        )
        blockers: list[str] = []
        if not (
            normal_before.get("status") == "healthy"
            and normal_before.get("consumer_running") is True
        ):
            blockers.append("normal alert WebSocket service was not healthy")
        if _port_open(runtime["port"]):
            blockers.append("isolated loopback port was already in use")
        if (
            _command(
                ["docker", "inspect", runtime["container"]], check=False
            ).returncode
            == 0
        ):
            blockers.append("isolated container name was already present")
        for stream in (owned["input_stream"], owned["enhanced_stream"]):
            if stream in before_keys:
                blockers.append(f"owned Redis stream was already present: {stream}")
        if blockers:
            receipt["blockers"] = blockers
            receipt["failure"] = "precondition_failed"
            return receipt

        receipt["pre_state"] = {
            "owned_resources_absent": True,
            "normal_service_healthy": True,
            "normal_active_connections": normal_before["active_connections"],
            "redis_nonowned_key_count": len(before_keys),
            "redis_nonowned_key_names_sha256": _canonical_sha(before_keys),
        }
        mutation_started = True
        receipt["writes_or_lifecycle_actions"] = True
        _start_isolated(contract)
        isolated_health = _wait_ready(contract)
        receipt["isolated_service"] = {
            "health_status": isolated_health["status"],
            "consumer_running": isolated_health["redis_consumer"]["is_running"],
            "owned_streams_exact": isolated_health["redis_consumer"]["streams"]
            == [owned["input_stream"], owned["enhanced_stream"]],
            "source_mount_read_only": any(
                mount.get("Destination") == "/app/alert-agent-web"
                and mount.get("RW") is False
                for mount in _container(runtime["container"])["Mounts"]
            ),
        }
        receipt["runtime"] = asyncio.run(_exercise(contract))
        receipt["semantic_action_count"] = 2
        after_socket_health = _http_json(
            f"http://127.0.0.1:{runtime['port']}/ws/health"
        )
        receipt["runtime"]["connection_cleanup"] = {
            "active_connections_after_close": after_socket_health["active_connections"],
            "connection_removed": after_socket_health["active_connections"] == 0,
        }
        if after_socket_health["active_connections"] != 0:
            raise QualificationError("WebSocket connection remained registered")
    except (
        QualificationError,
        OSError,
        KeyError,
        StopIteration,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        websockets.WebSocketException,
    ) as exc:
        receipt["failure"] = type(exc).__name__
        print(f"[alert-websocket] {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if mutation_started:
            cleanup = _cleanup(contract)
            after_keys = _redis_keys()
            normal_after = _normal_health_contract(
                _http_json(runtime["main_service"]["health_url"])
            )
            redis_after = _container(runtime["redis"]["container"])
            cleanup.update(
                {
                    "isolated_container_absent": _command(
                        ["docker", "inspect", runtime["container"]], check=False
                    ).returncode
                    != 0,
                    "isolated_listener_absent": not _port_open(runtime["port"]),
                    "owned_input_stream_absent": owned["input_stream"]
                    not in after_keys,
                    "owned_enhanced_stream_absent": owned["enhanced_stream"]
                    not in after_keys,
                    "redis_nonowned_key_set_exact": after_keys == before_keys,
                    "normal_service_state_exact": normal_after == normal_before,
                    "redis_health_after": redis_after.get("State", {})
                    .get("Health", {})
                    .get("Status"),
                }
            )
            receipt["cleanup"] = cleanup
            cleanup_pass = (
                cleanup["failures"] == []
                and cleanup["isolated_container_absent"]
                and cleanup["isolated_listener_absent"]
                and cleanup["owned_input_stream_absent"]
                and cleanup["owned_enhanced_stream_absent"]
                and cleanup["redis_nonowned_key_set_exact"]
                and cleanup["normal_service_state_exact"]
                and cleanup["redis_health_after"] == "healthy"
            )
            if not cleanup_pass and receipt["failure"] is None:
                receipt["failure"] = "cleanup_postcondition_failed"

    passed = (
        receipt.get("runtime", {}).get("status") == "passed"
        and receipt.get("semantic_action_count") == 2
        and receipt.get("cleanup", {}).get("failures") == []
        and receipt.get("failure") is None
    )
    if passed:
        receipt["status"] = "passed"
    receipt["completed_at"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    receipt["duration_ms"] = round(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = execute()
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
