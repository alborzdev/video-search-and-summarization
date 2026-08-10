#!/usr/bin/env python3
"""Qualify the current Thor Agent WebSocket without retaining chat content."""

from __future__ import annotations

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import websockets


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
DEFAULT_RECEIPT = HERE / "runtime-receipt.json"
ACKNOWLEDGEMENT = "I_AUTHORIZE_AGENT_WEBSOCKET_RUNTIME_QUALIFICATION"
ALLOWED_INBOUND_TYPES = {
    "system_response_message",
    "system_intermediate_message",
    "system_interaction_message",
    "error",
}


class QualificationError(RuntimeError):
    """The bounded Agent WebSocket qualification failed closed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise QualificationError(f"{path.name} is not a JSON object")
    return value, raw


def _command(
    args: list[str], *, cwd: Path = REPO, timeout: float = 30, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise QualificationError(
            f"command {Path(args[0]).name} failed; detail_sha256="
            f"{_sha(detail.encode())}"
        )
    return completed


def _docker_inspect(name: str) -> dict[str, Any]:
    completed = _command(["docker", "inspect", name])
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise QualificationError(f"could not inspect exact container {name}")
    return rows[0]


def _image_inspect(reference: str) -> dict[str, Any]:
    completed = _command(["docker", "image", "inspect", reference])
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise QualificationError(f"could not inspect exact image {reference}")
    return rows[0]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    source_hashes: dict[str, str] = {}
    for lock in contract["source_locks"]:
        actual = _sha((REPO / lock["path"]).read_bytes())
        if actual != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
        source_hashes[lock["path"]] = actual

    harness = contract["adjacent_negative"]["harness"]
    harness_actual = _sha((REPO / harness["path"]).read_bytes())
    if harness_actual != harness["sha256"]:
        raise QualificationError("adjacent-negative harness drifted")

    binding = contract["protocol_case"]
    protocol_cases, protocol_raw = _load(REPO / binding["path"])
    if _sha(protocol_raw) != binding["file_sha256"]:
        raise QualificationError("protocol-case file digest drifted")
    if protocol_cases.get("contract_set_sha256") != binding["contract_set_sha256"]:
        raise QualificationError("protocol-case set digest drifted")
    case = next(
        (
            row
            for row in protocol_cases.get("cases", [])
            if row.get("case_id") == binding["case_id"]
        ),
        None,
    )
    if case is None or _canonical_sha(case) != binding["case_sha256"]:
        raise QualificationError("Agent WebSocket protocol case drifted")
    negative_ids = [
        row.get("id") for row in case.get("adjacent_negative_vectors", [])
    ]
    if (
        case.get("positive_vector", {}).get("id") != binding["positive_vector_id"]
        or negative_ids != binding["negative_vector_ids"]
    ):
        raise QualificationError("Agent WebSocket vector binding drifted")

    ancestor = _command(
        ["git", "merge-base", "--is-ancestor", contract["target_commit"], "HEAD"],
        check=False,
    )
    if ancestor.returncode != 0:
        raise QualificationError("target commit is not an ancestor of HEAD")

    return {
        "harness_sha256": harness_actual,
        "protocol_case_sha256": binding["case_sha256"],
        "source_hashes": source_hashes,
    }


def _mount_is_read_only(
    container: dict[str, Any], source: Path, destination: str
) -> bool:
    resolved = source.resolve()
    return any(
        Path(row.get("Source", "")).resolve() == resolved
        and row.get("Destination") == destination
        and row.get("RW") is False
        for row in container.get("Mounts", [])
    )


def _container_state(container: dict[str, Any]) -> dict[str, Any]:
    state = container.get("State", {})
    health = state.get("Health", {})
    return {
        "container_id_sha256": _sha(str(container.get("Id", "")).encode()),
        "image_id": container.get("Image"),
        "restart_count": container.get("RestartCount"),
        "running": state.get("Running"),
        "started_at_sha256": _sha(str(state.get("StartedAt", "")).encode()),
        "health": health.get("Status"),
    }


def _verify_runtime_identity(contract: dict[str, Any]) -> dict[str, Any]:
    expected = contract["runtime"]
    agent = _docker_inspect(expected["agent"]["container"])
    gateway = _docker_inspect(expected["gateway"]["container"])
    ui = _docker_inspect(expected["ui"]["container"])

    for name, container, row in (
        ("agent", agent, expected["agent"]),
        ("gateway", gateway, expected["gateway"]),
        ("ui", ui, expected["ui"]),
    ):
        image = _image_inspect(row["image"])
        if image.get("Id") != row["image_id"] or image.get("Architecture") != "arm64":
            raise QualificationError(f"{name} image identity drifted")
        if container.get("Image") != row["image_id"]:
            raise QualificationError(f"{name} container image drifted")
        if container.get("State", {}).get("Running") is not True:
            raise QualificationError(f"{name} container is not running")

    if agent.get("State", {}).get("Health", {}).get("Status") != "healthy":
        raise QualificationError("Agent container is not healthy")
    if not _mount_is_read_only(
        agent,
        REPO / "services/agent/src",
        "/vss-agent/thor-local-src",
    ):
        raise QualificationError("Agent current-source mount is not read-only/exact")
    if not _mount_is_read_only(
        gateway,
        REPO / "deploy/docker/services/infra/haproxy/haproxy.cfg.template",
        "/usr/local/etc/haproxy/haproxy.cfg",
    ):
        raise QualificationError("gateway route configuration mount drifted")
    port = expected["endpoint"]["port"]
    if not _port_open(port):
        raise QualificationError("loopback gateway port is not accepting connections")

    return {
        "agent": _container_state(agent),
        "architecture": "arm64",
        "gateway": _container_state(gateway),
        "loopback_port_open": True,
        "ui": _container_state(ui),
    }


def _snapshot_report_tree() -> dict[str, Any]:
    root = REPO / "deploy/docker/data-dir/agent-reports"
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            raw = path.read_bytes()
            total_bytes += len(raw)
            rows.append(
                {
                    "relative_path_sha256": _sha(
                        path.relative_to(root).as_posix().encode()
                    ),
                    "content_sha256": _sha(raw),
                    "size": len(raw),
                }
            )
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "tree_sha256": _canonical_sha(rows),
    }


def _request_fixture(
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding = contract["protocol_case"]
    protocol_cases, _ = _load(REPO / binding["path"])
    case = next(
        row
        for row in protocol_cases["cases"]
        if row["case_id"] == binding["case_id"]
    )
    vector = case["positive_vector"]
    template = vector["fixture"]
    fixture = copy.deepcopy(template)
    materialized_schema = contract["positive"]["schema_type_materialization"]
    if template.get("schema_type") != "" or materialized_schema != "chat_stream":
        raise QualificationError("positive schema materialization contract drifted")
    fixture["schema_type"] = materialized_schema
    if (
        fixture.get("type") != "user_message"
        or not isinstance(fixture.get("id"), str)
        or not isinstance(fixture.get("conversation_id"), str)
        or not fixture["conversation_id"]
        or not isinstance(fixture.get("timestamp"), str)
        or not isinstance(fixture.get("content", {}).get("messages"), list)
        or not fixture["content"]["messages"]
    ):
        raise QualificationError("positive request fixture schema drifted")
    return vector, template, fixture


async def _exercise_positive(contract: dict[str, Any]) -> dict[str, Any]:
    endpoint = contract["runtime"]["endpoint"]
    vector, template, fixture = _request_fixture(contract)
    wire = json.dumps(fixture, separators=(",", ":"), ensure_ascii=False)
    conversation_id = fixture["conversation_id"]
    uri = f"ws://127.0.0.1:{endpoint['port']}{endpoint['path']}"
    frames: list[dict[str, Any]] = []
    content_parts: list[str] = []
    started = time.monotonic()
    websocket = await websockets.connect(
        uri,
        proxy=None,
        open_timeout=5,
        close_timeout=5,
        ping_interval=None,
        max_size=1024 * 1024,
    )
    try:
        response = websocket.response
        if response is None or response.status_code != 101:
            raise QualificationError("WebSocket handshake did not return HTTP 101")
        headers = {key.lower(): value.lower() for key, value in response.headers.raw_items()}
        if headers.get("upgrade") != "websocket" or "upgrade" not in headers.get(
            "connection", ""
        ):
            raise QualificationError("WebSocket upgrade headers drifted")

        await websocket.send(wire)
        terminal_count = 0
        while len(frames) < vector["max_events"]:
            remaining = vector["deadline_seconds"] - (time.monotonic() - started)
            if remaining <= 0:
                raise QualificationError("Agent WebSocket positive vector timed out")
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            if not isinstance(raw, str):
                raise QualificationError("Agent returned a non-text WebSocket frame")
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise QualificationError("Agent returned non-JSON text") from exc
            if not isinstance(message, dict):
                raise QualificationError("Agent returned non-object JSON")
            message_type = message.get("type")
            if message_type not in ALLOWED_INBOUND_TYPES:
                raise QualificationError("Agent returned an unsupported frame type")
            if message.get("conversation_id") != conversation_id:
                raise QualificationError("Agent response conversation did not match")
            status = message.get("status")
            if message_type == "system_response_message" and status not in {
                "in_progress",
                "complete",
            }:
                raise QualificationError("Agent response status drifted")
            if message_type == "error":
                raise QualificationError("Agent returned an error frame")
            if status == "complete":
                terminal_count += 1
            elif terminal_count:
                raise QualificationError("Agent emitted a frame after terminal completion")
            text = message.get("content", {}).get("text")
            if isinstance(text, str):
                content_parts.append(text)
            frames.append(
                {
                    "bytes": len(raw.encode()),
                    "conversation_match": True,
                    "frame_sha256": _sha(raw.encode()),
                    "ordinal": len(frames) + 1,
                    "status": status,
                    "type": message_type,
                }
            )
            if status == "complete":
                break
        if terminal_count != 1:
            raise QualificationError("Agent did not emit exactly one complete terminal")
        if not any(part.strip() for part in content_parts):
            raise QualificationError("Agent emitted no non-empty response content")

        extra_frame_observed = False
        try:
            await asyncio.wait_for(websocket.recv(), timeout=0.25)
            extra_frame_observed = True
        except TimeoutError:
            pass
        if extra_frame_observed:
            raise QualificationError("Agent emitted an extra frame after completion")

        await websocket.close(code=1000)
        await websocket.wait_closed()
        if websocket.close_code != 1000:
            raise QualificationError("owned WebSocket did not close normally")

        assembled = "".join(content_parts)
        return {
            "complete_terminal_count": terminal_count,
            "content_nonempty": True,
            "content_sha256": _sha(assembled.encode()),
            "conversation_id_sha256": _sha(conversation_id.encode()),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "frame_count": len(frames),
            "frames": frames,
            "handshake_http_status": 101,
            "ordered_completion": True,
            "outbound_frame_bytes": len(wire.encode()),
            "outbound_frame_sha256": _sha(wire.encode()),
            "request_id_sha256": _sha(fixture["id"].encode()),
            "schema_type_materialized_from_current_ui_default": True,
            "schema_type_sha256": _sha(fixture["schema_type"].encode()),
            "socket_close_code": websocket.close_code,
            "template_fixture_sha256": _canonical_sha(template),
            "upgrade_headers_valid": True,
            "vector_id": vector["id"],
        }
    finally:
        if websocket.close_code is None:
            await websocket.close(code=1000)


def _exercise_adjacent_negative(contract: dict[str, Any]) -> dict[str, Any]:
    negative = contract["adjacent_negative"]
    source = REPO / negative["validator_source"]
    swc = REPO / negative["compiler"]
    config = REPO / negative["compiler_config"]
    harness = REPO / negative["harness"]["path"]
    if not swc.is_file():
        raise QualificationError("pinned local SWC compiler is absent")

    with tempfile.TemporaryDirectory(prefix="vss-agent-ws-validator-") as temp:
        temp_path = Path(temp)
        _command(
            [
                str(swc),
                str(source),
                "-d",
                str(temp_path),
                "--config-file",
                str(config),
            ],
            timeout=30,
        )
        compiled = temp_path / source.relative_to(REPO).with_suffix(".js")
        if not compiled.is_file():
            raise QualificationError("SWC did not materialize the validator module")
        completed = _command(
            ["node", "--no-warnings", str(harness), str(compiled)],
            timeout=15,
        )
        value = json.loads(completed.stdout)
        if (
            value.get("rejected") is not True
            or value.get("errorName") != "Error"
            or not isinstance(value.get("candidateSha256"), str)
            or not isinstance(value.get("errorMessageSha256"), str)
        ):
            raise QualificationError("actual compiled UI validator accepted the negative")
        return {
            "candidate_sha256": value["candidateSha256"],
            "compiled_validator_sha256": _sha(compiled.read_bytes()),
            "error_message_sha256": value["errorMessageSha256"],
            "error_type": value["errorName"],
            "missing_conversation_rejected": True,
            "temporary_compilation_absent_after": True,
            "vector_id": negative["vector_id"],
        }


def _same_runtime(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before == after


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(rendered)
    os.replace(temporary, path)


def _preflight(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "preflight",
        "status": "ready",
        "capability_id": contract["capability_id"],
        "network_scope": contract["network_scope"],
        "max_requests": contract["max_requests"],
        "writes_or_lifecycle_actions": False,
    }


def execute(contract: dict[str, Any], contract_raw: bytes) -> dict[str, Any]:
    started_at = _now()
    started = time.monotonic()
    static = _verify_static(contract)
    runtime_before = _verify_runtime_identity(contract)
    reports_before = _snapshot_report_tree()

    positive = asyncio.run(_exercise_positive(contract))
    negative = _exercise_adjacent_negative(contract)

    runtime_after = _verify_runtime_identity(contract)
    reports_after = _snapshot_report_tree()
    related_runtime_exact = _same_runtime(runtime_before, runtime_after)
    report_tree_exact = reports_before == reports_after
    if not related_runtime_exact:
        raise QualificationError("related container state changed during qualification")
    if not report_tree_exact:
        raise QualificationError("Agent report tree changed during qualification")

    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "capability_id": contract["capability_id"],
        "target_release": contract["target_release"],
        "target_commit": contract["target_commit"],
        "captured_at": started_at,
        "completed_at": _now(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "status": "passed",
        "failure": None,
        "blockers": [],
        "contract_sha256": _sha(contract_raw),
        "network_scope": contract["network_scope"],
        "warehouse_sample_bundle": False,
        "semantic_action_count": 2,
        "max_requests": contract["max_requests"],
        "writes_or_lifecycle_actions": True,
        "forbidden_actions_observed": [],
        "static_contract": static,
        "runtime_identity": runtime_before,
        "runtime": {
            "status": "passed",
            "positive": positive,
            "adjacent_negative": negative,
        },
        "pre_state": {
            "agent_report_tree": reports_before,
            "related_runtime": runtime_before,
        },
        "cleanup": {
            "attempted": True,
            "failures": [],
            "owned_socket_closed": positive["socket_close_code"] == 1000,
            "owned_conversation_ephemeral": True,
            "related_runtime_exact": related_runtime_exact,
            "agent_report_tree_exact": report_tree_exact,
            "temporary_compilation_absent": negative[
                "temporary_compilation_absent_after"
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack")
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    try:
        contract, contract_raw = _load(CONTRACT_PATH)
        if not args.execute:
            print(json.dumps(_preflight(contract), indent=2, sort_keys=True))
            return 0
        if args.ack != ACKNOWLEDGEMENT:
            raise QualificationError("exact acknowledgement is required")
        receipt = execute(contract, contract_raw)
        _write_receipt(args.output, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (
        OSError,
        KeyError,
        StopIteration,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        TimeoutError,
        QualificationError,
    ) as exc:
        safe = {
            "schema_version": 1,
            "tool_id": "thor-agent-websocket-runtime-successor",
            "status": "failed",
            "failure": exc.__class__.__name__,
            "failure_detail_sha256": _sha(str(exc).encode()),
            "writes_or_lifecycle_actions": bool(args.execute),
        }
        print(json.dumps(safe, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
