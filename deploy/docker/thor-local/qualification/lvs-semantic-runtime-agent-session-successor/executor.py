#!/usr/bin/env python3
"""Concrete NAT WebSocket/session candidate for the selected LVS semantic row.

The default ``plan`` command is static and inert. ``execute-agent-session`` is
authorization-gated and admits only a numeric-loopback Agent origin. It uses
two real NAT WebSocket sessions, then reads/deletes only report object keys
returned by the completed Agent turns.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import sys
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
RUN_NAMESPACE = UUID("ee261fe6-bcec-4058-b049-d878b9a65f99")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SAFE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}\\]+")
RELATIVE_STATIC_RE = re.compile(r"(?<![A-Za-z0-9])(/static/[A-Za-z0-9_.~/-]+)")
REPORT_KEY_RE = re.compile(
    r"vss_report_([A-Za-z0-9][A-Za-z0-9_.-]{0,127})_"
    r"[0-9]{8}_[0-9]{6}\.(md|pdf)\Z"
)


class ExecutorError(RuntimeError):
    """Stable public error code; raw transport and model data stay private."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_manifest",
        "invalid_receipt",
        "invalid_response",
        "oracle_failed",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes


class Connection(Protocol):
    def send_json(self, value: Mapping[str, Any]) -> None: ...

    def receive_json(
        self, *, timeout_seconds: float, max_bytes: int
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class Transport(Protocol):
    proxies_enabled: bool
    redirects_enabled: bool

    def connect_websocket(
        self,
        *,
        origin: str,
        path: str,
        session_id: str,
        timeout_seconds: float,
        max_message_bytes: int,
    ) -> Connection: ...

    def request_http(
        self,
        *,
        method: str,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HTTPResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, fp, code, message, headers, new_url
        return None


class _WebSocketConnection:
    """Minimal direct RFC 6455 text client; no proxy or extension support."""

    def __init__(
        self, stream: socket.socket, max_message_bytes: int, initial: bytes = b""
    ) -> None:
        self._stream = stream
        self._max = max_message_bytes
        self._closed = False
        self._buffer = bytearray(initial)

    def _read_exact(self, count: int) -> bytes:
        pieces: list[bytes] = []
        total = 0
        if self._buffer:
            take = min(count, len(self._buffer))
            pieces.append(bytes(self._buffer[:take]))
            del self._buffer[:take]
            total += take
        while total < count:
            piece = self._stream.recv(count - total)
            if not piece:
                raise ExecutorError("transport_error")
            pieces.append(piece)
            total += len(piece)
        return b"".join(pieces)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise ExecutorError("transport_error")
        if len(payload) > self._max:
            raise ExecutorError("invalid_response")
        mask = os.urandom(4)
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = bytes((first, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((first, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 0x80 | 127)) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._stream.sendall(header + mask + masked)

    def send_json(self, value: Mapping[str, Any]) -> None:
        self._send_frame(0x1, _canonical(value))

    def receive_json(self, *, timeout_seconds: float, max_bytes: int) -> dict[str, Any]:
        self._stream.settimeout(timeout_seconds)
        fragments: list[bytes] = []
        total = 0
        started = False
        while True:
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            if first & 0x70 or second & 0x80:
                raise ExecutorError("invalid_response")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > max_bytes or total + length > max_bytes:
                raise ExecutorError("invalid_response")
            payload = self._read_exact(length)
            if opcode == 0x8:
                self._closed = True
                raise ExecutorError("transport_error")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x2:
                raise ExecutorError("invalid_response")
            if opcode == 0x1:
                if started:
                    raise ExecutorError("invalid_response")
                started = True
            elif opcode != 0x0 or not started:
                raise ExecutorError("invalid_response")
            fragments.append(payload)
            total += len(payload)
            if final:
                return _decode_json(b"".join(fragments), "invalid_response")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._send_frame(0x8, b"\x03\xe8")
        except (ExecutorError, OSError):
            pass
        self._closed = True
        try:
            self._stream.close()
        except OSError:
            pass


class LiveTransport:
    """Direct numeric-loopback WebSocket + proxy-disabled HTTP transport."""

    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def connect_websocket(
        self,
        *,
        origin: str,
        path: str,
        session_id: str,
        timeout_seconds: float,
        max_message_bytes: int,
    ) -> Connection:
        host, port = _numeric_loopback_origin(origin)
        if path != "/websocket" or not SAFE_RE.fullmatch(session_id):
            raise ExecutorError("configuration_error")
        stream: socket.socket | None = None
        try:
            stream = socket.create_connection((host, port), timeout=timeout_seconds)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            target = f"{path}?session={quote(session_id, safe='')}"
            host_header = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            request = (
                f"GET {target} HTTP/1.1\r\n"
                f"Host: {host_header}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            stream.sendall(request)
            raw = bytearray()
            while b"\r\n\r\n" not in raw:
                if len(raw) >= 32768:
                    raise ExecutorError("invalid_response")
                piece = stream.recv(min(4096, 32768 - len(raw)))
                if not piece:
                    raise ExecutorError("transport_error")
                raw.extend(piece)
            header, remainder = bytes(raw).split(b"\r\n\r\n", 1)
            lines = header.decode("iso-8859-1").split("\r\n")
            if lines[0] != "HTTP/1.1 101 Switching Protocols":
                raise ExecutorError("transport_error")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" not in line:
                    raise ExecutorError("invalid_response")
                name, value = line.split(":", 1)
                lowered = name.strip().lower()
                if lowered in headers:
                    raise ExecutorError("invalid_response")
                headers[lowered] = value.strip()
            expected = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii"),
                    usedforsecurity=False,
                ).digest()
            ).decode("ascii")
            if (
                headers.get("upgrade", "").lower() != "websocket"
                or "upgrade"
                not in {
                    item.strip().lower()
                    for item in headers.get("connection", "").split(",")
                }
                or headers.get("sec-websocket-accept") != expected
                or "sec-websocket-extensions" in headers
            ):
                raise ExecutorError("invalid_response")
            return _WebSocketConnection(stream, max_message_bytes, remainder)
        except ExecutorError:
            if stream is not None:
                stream.close()
            raise
        except (OSError, TimeoutError, UnicodeError) as exc:
            if stream is not None:
                stream.close()
            raise ExecutorError("transport_error") from exc

    def request_http(
        self,
        *,
        method: str,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HTTPResponse:
        request = Request(url, method=method)
        try:
            try:
                opened = self._opener.open(request, timeout=timeout_seconds)
            except HTTPError as response:
                opened = response
            with opened:
                raw = opened.read(max_response_bytes + 1)
                if len(raw) > max_response_bytes:
                    raise ExecutorError("invalid_response")
                return HTTPResponse(status=int(opened.status), body=raw)
        except ExecutorError:
            raise
        except (OSError, TimeoutError, URLError) as exc:
            raise ExecutorError("transport_error") from exc


class Budget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.requests = 0
        self.actions = 0

    def consume(self, count: int = 1) -> None:
        if (
            count < 1
            or self.requests + count > self.maximum
            or self.actions + count > self.maximum
        ):
            raise ExecutorError("oracle_failed")
        self.requests += count
        self.actions += count


def _read_regular(path: Path, maximum: int, code: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError(code) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ExecutorError(code)
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, item) != getattr(after, item) for item in stable
        ):
            raise ExecutorError(code)
        return raw
    finally:
        os.close(descriptor)


def _decode_json(raw: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ExecutorError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ExecutorError(code)),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(code) from exc
    if not isinstance(value, dict):
        raise ExecutorError(code)
    return value


def _json_file(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    return _decode_json(_read_regular(path, MAX_CONFIG_BYTES, code), code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_response") from exc


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _repo_path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise ExecutorError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ExecutorError("configuration_error")
        except ExecutorError:
            raise
        except OSError as exc:
            raise ExecutorError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc
    return current


def _validate_schema(value: Any, path: Path, code: str) -> None:
    try:
        schema = _json_file(path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ExecutorError(code)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc


def _contract() -> dict[str, Any]:
    return _json_file(CONTRACT_PATH)


def _one(rows: Sequence[Any], key: str, value: Any) -> dict[str, Any]:
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    return matches[0]


def compile_plan() -> dict[str, Any]:
    """Validate source locks and preserve the frozen selected-row boundary."""

    contract = _contract()
    workflow = contract.get("workflow", [])
    if (
        contract.get("schema_version") != 1
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("order") for row in workflow] != list(range(1, 20))
        or sum(row.get("request_cost", 0) for row in workflow) != 34
        or contract.get("execution_bounds", {}).get("max_requests") != 34
        or contract.get("execution_bounds", {}).get("max_actions") != 34
        or contract.get("evidence", {}).get("promotion_eligible") is not False
        or contract.get("evidence", {}).get("executor_ready") is not False
    ):
        raise ExecutorError("configuration_error")
    paths: set[str] = set()
    for lock in contract.get("source_locks", []):
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in paths
            or not SHA_RE.fullmatch(lock["sha256"])
        ):
            raise ExecutorError("configuration_error")
        paths.add(lock["path"])
        if (
            _sha(
                _read_regular(
                    _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
                )
            )
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")

    selected = _json_file(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
            "post-state-capability-oracles.json"
        )
    )
    if selected.get("schema_version") != 2 or len(selected.get("oracles", [])) != 500:
        raise ExecutorError("configuration_error")
    row = _one(selected["oracles"], "oracle_id", contract["oracle_id"])
    if (
        row.get("capability_id") != contract["capability_id"]
        or row.get("current_state") != "open_unexecuted"
        or row.get("evidence") != []
        or row.get("execution_bounds", {}).get("executor") is not None
        or row.get("execution_bounds", {}).get("max_requests") != 14
        or row.get("execution_bounds", {}).get("max_actions") != 14
        or row.get("cleanup", {}).get("executor") is not None
    ):
        raise ExecutorError("configuration_error")

    lvs_config = _read_regular(
        _repo_path(
            "deploy/docker/developer-profiles/dev-profile-lvs/vss-agent/configs/config.yml"
        ),
        MAX_CONFIG_BYTES,
        "configuration_error",
    ).decode("utf-8")
    required_config = (
        "- lvs_video_understanding",
        "- lvs_config_media",
        "- lvs_stream_understanding",
        "- lvs_caption_retrieval",
        "video_report_tool: video_report_gen",
        "hitl_enabled: true",
    )
    if any(fragment not in lvs_config for fragment in required_config):
        raise ExecutorError("configuration_error")
    lvs_source = _read_regular(
        _repo_path("services/agent/src/vss_agents/tools/lvs_video_understanding.py"),
        MAX_CONFIG_BYTES,
        "configuration_error",
    ).decode("utf-8")
    if any(
        fragment not in lvs_source
        for fragment in (
            "thread_id = ContextState.get().conversation_id.get()",
            "current_params = lvs_params_state.get(thread_id)",
            "lvs_params_state[thread_id] = (scenario, events_list, objects_of_interest)",
            "Supports parallel processing of multiple videos with shared HITL parameters.",
        )
    ):
        raise ExecutorError("configuration_error")
    report_source = _read_regular(
        _repo_path("services/agent/src/vss_agents/tools/video_report_gen.py"),
        MAX_CONFIG_BYTES,
        "configuration_error",
    ).decode("utf-8")
    if (
        'filename = f"vss_report_{safe_sensor_id}_{timestamp_str}.md"'
        not in report_source
        or "all_reports.append(report_metadata)" not in report_source
        or "lvs_video_length: int = Field(" not in report_source
        or "default=60," not in report_source
    ):
        raise ExecutorError("configuration_error")
    ui_source = _read_regular(
        _repo_path(
            "services/ui/packages/nemo-agent-toolkit-ui/components/Chat/Chat.tsx"
        ),
        MAX_CONFIG_BYTES,
        "configuration_error",
    ).decode("utf-8")
    if any(
        fragment not in ui_source
        for fragment in (
            "type: webSocketMessageTypes.userMessage",
            "conversation_id: selectedConversation.id",
            "type: webSocketMessageTypes.userInteractionMessage",
            "thread_id: interactionMessage?.thread_id",
            "parent_id: interactionMessage?.parent_id",
        )
    ):
        raise ExecutorError("configuration_error")
    expected = _json_file(
        _repo_path("deploy/docker/thor-local/qualification/expected/agent.json")
    )
    methods = {
        (item.get("method"), item.get("path"))
        for item in expected.get("operations", [])
        if isinstance(item, dict)
    }
    if not {
        ("GET", "/static/{file_path:path}"),
        ("DELETE", "/static/{file_path:path}"),
    }.issubset(methods):
        raise ExecutorError("configuration_error")
    Draft202012Validator.check_schema(_json_file(MANIFEST_SCHEMA_PATH))
    Draft202012Validator.check_schema(_json_file(RECEIPT_SCHEMA_PATH))
    coverage = contract["semantic_coverage"]
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_plan_valid",
        "runtime_activity_performed": False,
        "runtime_evidence_created": False,
        "canonical_selected_bound": False,
        "frozen_selected_request_bound": 14,
        "honest_successor_request_bound": 34,
        "concrete_complete_action_count": len(coverage["concrete_complete"]),
        "concrete_partial_action_count": len(coverage["concrete_partial"]),
        "residual_action_count": len(coverage["residual_adapter_required"]),
        "five_tool_declaration_source_locked": True,
        "five_tool_runtime_discovery": False,
        "promotion_eligible": False,
        "executor_ready": False,
        "warehouse_sample_bundle": "excluded",
    }


def _numeric_loopback_origin(value: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        address = ip_address(parsed.hostname or "")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_manifest") from exc
    if (
        parsed.scheme != "http"
        or not address.is_loopback
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutorError("invalid_manifest")
    return str(address), port


def _public_origin(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_manifest") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ExecutorError("invalid_manifest")
    return parsed.scheme, parsed.netloc.lower()


def _prompt_values(prompt: Mapping[str, Any]) -> list[str]:
    return [
        str(prompt["scenario"]),
        *map(str, prompt["events"]),
        *map(str, prompt["objects"]),
    ]


def _validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    _validate_schema(value, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    run_id = value["run_id"]
    _numeric_loopback_origin(value["agent_origin"])
    origins = {_public_origin(item) for item in value["public_report_origins"]}
    if len(origins) != len(value["public_report_origins"]):
        raise ExecutorError("invalid_manifest")
    fixtures = value["fixtures"]
    if (
        any(item["owner_run_id"] != run_id for item in fixtures)
        or len({item["sensor_name"] for item in fixtures}) != 2
        or len({item["media_sha256"] for item in fixtures}) != 2
        or any(
            token in item["sensor_name"].lower()
            for item in fixtures
            for token in ("report_agent", "video_report_gen")
        )
    ):
        raise ExecutorError("invalid_manifest")
    first = _prompt_values(value["first_prompt"])
    latest = _prompt_values(value["latest_prompt"])
    all_values = first + latest
    forbidden = ("/cancel", "report_agent", "video_report_gen", "http://", "https://")
    if (
        _canonical(value["first_prompt"]) == _canonical(value["latest_prompt"])
        or any(
            "\n" in item or "\r" in item or item != item.strip() for item in all_values
        )
        or any(any(token in item.lower() for token in forbidden) for item in all_values)
        or len(set(all_values)) != len(all_values)
    ):
        raise ExecutorError("invalid_manifest")
    return value


def _message_id(run_id: str, label: str) -> str:
    return str(uuid5(RUN_NAMESPACE, f"{run_id}:{label}"))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _user_message(
    run_id: str, label: str, conversation_id: str, text: str
) -> dict[str, Any]:
    return {
        "type": "user_message",
        "schema_type": "chat_stream",
        "id": _message_id(run_id, label),
        "conversation_id": conversation_id,
        "timestamp": _timestamp(),
        "content": {
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}]
        },
    }


def _interaction_message(
    run_id: str,
    label: str,
    conversation_id: str,
    interaction: Mapping[str, Any],
    text: str,
) -> dict[str, Any]:
    thread_id = interaction.get("thread_id")
    parent_id = interaction.get("parent_id")
    if (
        not isinstance(thread_id, str)
        or not thread_id
        or not isinstance(parent_id, str)
        or not parent_id
    ):
        raise ExecutorError("invalid_response")
    return {
        "type": "user_interaction_message",
        "id": _message_id(run_id, label),
        "conversation_id": conversation_id,
        "thread_id": thread_id,
        "parent_id": parent_id,
        "timestamp": _timestamp(),
        "content": {
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}]
        },
    }


def _receive_until(
    connection: Connection,
    *,
    conversation_id: str,
    terminal: str,
    contract: Mapping[str, Any],
    sink: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    maximum = contract["transport"]["max_websocket_messages_per_wait"]
    deadline = time.monotonic() + contract["transport"]["turn_timeout_seconds"]
    for frame_count in range(1, maximum + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutorError("transport_error")
        try:
            message = connection.receive_json(
                timeout_seconds=remaining,
                max_bytes=contract["transport"]["max_websocket_message_bytes"],
            )
        except ExecutorError:
            raise
        except Exception as exc:
            raise ExecutorError("transport_error") from exc
        if message.get("conversation_id") != conversation_id:
            raise ExecutorError("invalid_response")
        kind = message.get("type")
        if kind not in {
            "system_response_message",
            "system_intermediate_message",
            "system_interaction_message",
            "error",
        }:
            raise ExecutorError("invalid_response")
        if kind == "error":
            raise ExecutorError("oracle_failed")
        sink.append(message)
        if terminal == "interaction" and kind == "system_interaction_message":
            return message, frame_count
        if (
            terminal == "complete"
            and kind == "system_response_message"
            and message.get("status") == "complete"
        ):
            return message, frame_count
        if kind == "system_interaction_message" and terminal != "interaction":
            raise ExecutorError("invalid_response")
    raise ExecutorError("invalid_response")


def _interaction_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    text = content.get("text") if isinstance(content, Mapping) else None
    if not isinstance(text, str) or not text:
        raise ExecutorError("invalid_response")
    return text


def _assert_prompt_stage(text: str, stage: str) -> None:
    required = {
        "scenario": "Scenario (REQUIRED)",
        "events": "Events (REQUIRED)",
        "objects": "Objects of Interest (OPTIONAL",
        "confirm": "Type `/redo`",
    }[stage]
    if required not in text:
        raise ExecutorError("oracle_failed")


def _send(
    connection: Connection,
    value: Mapping[str, Any],
    budget: Budget,
) -> None:
    budget.consume()
    try:
        connection.send_json(value)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("transport_error") from exc


def _start_turn(
    connection: Connection,
    *,
    run_id: str,
    label: str,
    conversation_id: str,
    text: str,
    budget: Budget,
) -> None:
    _send(connection, _user_message(run_id, label, conversation_id, text), budget)


def _answer_interaction(
    connection: Connection,
    *,
    run_id: str,
    label: str,
    conversation_id: str,
    interaction: Mapping[str, Any],
    text: str,
    budget: Budget,
) -> None:
    _send(
        connection,
        _interaction_message(run_id, label, conversation_id, interaction, text),
        budget,
    )


def _transcript_bytes(messages: Sequence[Mapping[str, Any]]) -> bytes:
    return _canonical(list(messages))


def _contains_all(text: str, values: Sequence[str]) -> bool:
    return all(item in text for item in values)


def _extract_report_pairs(
    messages: Sequence[Mapping[str, Any]],
    expected_sensors: Sequence[str],
    allowed_origins: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """Return (sensor, md path, pdf path) pairs from a completed Agent turn."""

    correlated = _report_correlated_output(messages)
    if not correlated:
        raise ExecutorError("oracle_failed")
    text = _transcript_bytes(correlated).decode("utf-8")
    discovered = _discover_report_objects(messages, expected_sensors)
    paths = {path for _sensor, path in discovered}
    for match in URL_RE.finditer(text):
        parsed = urlsplit(match.group(0).rstrip(".,;:"))
        if parsed.query or parsed.fragment or not parsed.path.startswith("/static/"):
            continue
        key = parsed.path.removeprefix("/static/")
        if "%" not in key and "\\" not in key and REPORT_KEY_RE.fullmatch(key):
            matched = REPORT_KEY_RE.fullmatch(key)
            assert matched is not None
            if (
                matched.group(1) in expected_sensors
                and (parsed.scheme, parsed.netloc.lower()) not in allowed_origins
            ):
                raise ExecutorError("oracle_failed")
    by_sensor: dict[str, dict[str, str]] = {}
    for path in paths:
        matched = REPORT_KEY_RE.fullmatch(path.removeprefix("/static/"))
        assert matched is not None
        sensor, extension = matched.groups()
        if sensor not in expected_sensors:
            continue
        by_sensor.setdefault(sensor, {})[extension] = path
    if set(by_sensor) != set(expected_sensors):
        raise ExecutorError("oracle_failed")
    pairs: list[tuple[str, str, str]] = []
    for sensor in expected_sensors:
        values = by_sensor[sensor]
        if set(values) != {"md", "pdf"}:
            raise ExecutorError("oracle_failed")
        if values["md"].rsplit(".", 1)[0] != values["pdf"].rsplit(".", 1)[0]:
            raise ExecutorError("oracle_failed")
        pairs.append((sensor, values["md"], values["pdf"]))
    if len(paths) != 2 * len(expected_sensors):
        raise ExecutorError("oracle_failed")
    return pairs


def _is_report_agent_message(message: Mapping[str, Any]) -> bool:
    """Accept only the production report-agent intermediate envelope."""

    content = message.get("content")
    return (
        message.get("type") == "system_intermediate_message"
        and isinstance(content, Mapping)
        and content.get("name") == "report_agent"
    )


def _report_correlated_output(
    messages: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return the report-agent marker and later response frames, never HITL frames."""

    report_index = next(
        (
            index
            for index, message in enumerate(messages)
            if _is_report_agent_message(message)
        ),
        None,
    )
    if report_index is None:
        return []
    return [
        message
        for index, message in enumerate(messages)
        if index == report_index
        or (index > report_index and message.get("type") == "system_response_message")
    ]


def _discover_report_objects(
    messages: Sequence[Mapping[str, Any]], expected_sensors: Sequence[str]
) -> list[tuple[str, str]]:
    """Find strict report-agent-correlated keys safe enough for failure cleanup."""

    correlated = _report_correlated_output(messages)
    if not correlated:
        return []
    text = _transcript_bytes(correlated).decode("utf-8")
    paths: set[str] = set()
    for match in URL_RE.finditer(text):
        parsed = urlsplit(match.group(0).rstrip(".,;:"))
        if parsed.query or parsed.fragment or not parsed.path.startswith("/static/"):
            continue
        key = parsed.path.removeprefix("/static/")
        if "%" not in key and "\\" not in key and REPORT_KEY_RE.fullmatch(key):
            paths.add("/static/" + key)
    for match in RELATIVE_STATIC_RE.finditer(text):
        path = match.group(1).rstrip(".,;:")
        key = path.removeprefix("/static/")
        if "%" not in key and "\\" not in key and REPORT_KEY_RE.fullmatch(key):
            paths.add(path)
    found: list[tuple[str, str]] = []
    for path in sorted(paths):
        matched = REPORT_KEY_RE.fullmatch(path.removeprefix("/static/"))
        assert matched is not None
        if matched.group(1) in expected_sensors:
            found.append((matched.group(1), path))
    return found


def _agent_report_observed(messages: Sequence[Mapping[str, Any]]) -> bool:
    return any(_is_report_agent_message(message) for message in messages)


def _connect(
    transport: Transport,
    *,
    origin: str,
    session_id: str,
    contract: Mapping[str, Any],
    budget: Budget,
) -> Connection:
    budget.consume()
    try:
        return transport.connect_websocket(
            origin=origin,
            path=contract["transport"]["websocket_path"],
            session_id=session_id,
            timeout_seconds=contract["transport"]["connect_timeout_seconds"],
            max_message_bytes=contract["transport"]["max_websocket_message_bytes"],
        )
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("transport_error") from exc


def _http(
    transport: Transport,
    *,
    method: str,
    origin: str,
    path: str,
    contract: Mapping[str, Any],
    budget: Budget,
) -> HTTPResponse:
    if not path.startswith("/static/") or "%" in path or "\\" in path:
        raise ExecutorError("configuration_error")
    budget.consume()
    try:
        return transport.request_http(
            method=method,
            url=origin.rstrip("/") + path,
            timeout_seconds=contract["transport"]["artifact_timeout_seconds"],
            max_response_bytes=contract["transport"]["max_http_response_bytes"],
        )
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("transport_error") from exc


def execute_agent_session(
    *,
    manifest: dict[str, Any],
    acknowledgement: str,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Execute the maximal safe NAT Agent session subset and exact cleanup."""

    compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    manifest = _validate_manifest(manifest)
    if transport is None:
        transport = LiveTransport()
    if transport.proxies_enabled or transport.redirects_enabled:
        raise ExecutorError("configuration_error")

    run_id = manifest["run_id"]
    origin = manifest["agent_origin"].rstrip("/")
    allowed_report_origins = {
        _public_origin(value) for value in manifest["public_report_origins"]
    }
    fixtures = manifest["fixtures"]
    sensor_a, sensor_b = (item["sensor_name"] for item in fixtures)
    first = manifest["first_prompt"]
    latest = manifest["latest_prompt"]
    first_values = _prompt_values(first)
    latest_values = _prompt_values(latest)
    session_a = _message_id(run_id, "session-a")
    session_b = _message_id(run_id, "session-b")
    conversation_a = _message_id(run_id, "conversation-a")
    conversation_b = _message_id(run_id, "conversation-b")
    budget = Budget(34)
    inbound_messages = 0
    connections: list[Connection] = []
    registered: list[tuple[str, str]] = []
    artifact_rows: dict[str, dict[str, Any]] = {}
    observations = {
        "single_video_report": False,
        "multi_video_report": False,
        "first_prompt_written": False,
        "latest_prompt_overwrote_first": False,
        "latest_prompt_persisted": False,
        "cross_agent_prompt_isolation": False,
        "report_agent_observed": False,
        "video_report_artifacts_observed": False,
    }
    primary: ExecutorError | None = None
    single_transcript: list[dict[str, Any]] = []
    multi_transcript: list[dict[str, Any]] = []

    def wait(
        connection: Connection,
        conversation_id: str,
        terminal: str,
        sink: list[dict[str, Any]],
    ) -> dict[str, Any]:
        nonlocal inbound_messages
        last, count = _receive_until(
            connection,
            conversation_id=conversation_id,
            terminal=terminal,
            contract=contract,
            sink=sink,
        )
        inbound_messages += count
        if inbound_messages > 4096:
            raise ExecutorError("invalid_response")
        return last

    def register_pairs(pairs: Sequence[tuple[str, str, str]]) -> None:
        collision = False
        for sensor, markdown, pdf in pairs:
            for path in (markdown, pdf):
                if path in artifact_rows:
                    collision = True
                    continue
                registered.append((sensor, path))
                artifact_rows[path] = {
                    "extension": path.rsplit(".", 1)[1],
                    "path_sha256": _sha(path),
                    "stem_sha256": _sha(path.rsplit(".", 1)[0]),
                    "source_sensor_sha256": _sha(sensor),
                }
        if collision:
            raise ExecutorError("oracle_failed")

    def register_discovered(
        objects: Sequence[tuple[str, str]], *, collision_is_error: bool
    ) -> None:
        collision = False
        for sensor, path in objects:
            if path in artifact_rows:
                collision = True
                continue
            if len(registered) >= 6:
                raise ExecutorError("cleanup_failed")
            registered.append((sensor, path))
            artifact_rows[path] = {
                "extension": path.rsplit(".", 1)[1],
                "path_sha256": _sha(path),
                "stem_sha256": _sha(path.rsplit(".", 1)[0]),
                "source_sensor_sha256": _sha(sensor),
            }
        if collision and collision_is_error:
            raise ExecutorError("oracle_failed")

    try:
        agent_a = _connect(
            transport,
            origin=origin,
            session_id=session_a,
            contract=contract,
            budget=budget,
        )
        connections.append(agent_a)

        _start_turn(
            agent_a,
            run_id=run_id,
            label="single-report-turn",
            conversation_id=conversation_a,
            text=f"Generate a report for uploaded video {sensor_a}.",
            budget=budget,
        )
        for stage, response in (
            ("scenario", first["scenario"]),
            ("events", ", ".join(first["events"])),
            ("objects", ", ".join(first["objects"])),
            ("confirm", ""),
        ):
            interaction = wait(
                agent_a, conversation_a, "interaction", single_transcript
            )
            prompt_text = _interaction_text(interaction)
            _assert_prompt_stage(prompt_text, stage)
            if stage == "scenario" and (
                "DEFAULT" not in prompt_text
                or any(value in prompt_text for value in first_values + latest_values)
            ):
                raise ExecutorError("oracle_failed")
            _answer_interaction(
                agent_a,
                run_id=run_id,
                label=f"single-{stage}-first",
                conversation_id=conversation_a,
                interaction=interaction,
                text=response,
                budget=budget,
            )
        wait(agent_a, conversation_a, "complete", single_transcript)
        single_text = _transcript_bytes(single_transcript).decode("utf-8")
        if not _contains_all(single_text, [sensor_a, *first_values]):
            raise ExecutorError("oracle_failed")
        single_pairs = _extract_report_pairs(
            single_transcript, [sensor_a], allowed_report_origins
        )
        register_pairs(single_pairs)
        observations["single_video_report"] = True
        observations["first_prompt_written"] = True
        observations["report_agent_observed"] = _agent_report_observed(
            single_transcript
        )

        _start_turn(
            agent_a,
            run_id=run_id,
            label="multi-report-turn",
            conversation_id=conversation_a,
            text=(
                "Generate reports for uploaded videos "
                f"{sensor_a} and {sensor_b} in one report_agent call."
            ),
            budget=budget,
        )
        prior_by_stage = {
            "scenario": [first["scenario"]],
            "events": list(first["events"]),
            "objects": list(first["objects"]),
            "confirm": [],
        }
        latest_responses = {
            "scenario": latest["scenario"],
            "events": ", ".join(latest["events"]),
            "objects": ", ".join(latest["objects"]),
            "confirm": "",
        }
        for stage in ("scenario", "events", "objects", "confirm"):
            interaction = wait(agent_a, conversation_a, "interaction", multi_transcript)
            prompt_text = _interaction_text(interaction)
            _assert_prompt_stage(prompt_text, stage)
            if stage != "confirm" and (
                "CURRENTLY SET" not in prompt_text
                or not _contains_all(prompt_text, prior_by_stage[stage])
            ):
                raise ExecutorError("oracle_failed")
            _answer_interaction(
                agent_a,
                run_id=run_id,
                label=f"multi-{stage}-latest",
                conversation_id=conversation_a,
                interaction=interaction,
                text=latest_responses[stage],
                budget=budget,
            )
        wait(agent_a, conversation_a, "complete", multi_transcript)
        multi_text = _transcript_bytes(multi_transcript).decode("utf-8")
        if not _contains_all(multi_text, [sensor_a, sensor_b, *latest_values]):
            raise ExecutorError("oracle_failed")
        multi_pairs = _extract_report_pairs(
            multi_transcript, [sensor_a, sensor_b], allowed_report_origins
        )
        register_pairs(multi_pairs)
        observations["multi_video_report"] = True
        observations["latest_prompt_overwrote_first"] = True
        observations["report_agent_observed"] = observations[
            "report_agent_observed"
        ] and _agent_report_observed(multi_transcript)
        observations["video_report_artifacts_observed"] = len(registered) == 6

        _start_turn(
            agent_a,
            run_id=run_id,
            label="agent-a-latest-state-probe",
            conversation_id=conversation_a,
            text=f"Generate a report for uploaded video {sensor_a}.",
            budget=budget,
        )
        probe_transcript: list[dict[str, Any]] = []
        interaction = wait(agent_a, conversation_a, "interaction", probe_transcript)
        latest_probe = _interaction_text(interaction)
        _assert_prompt_stage(latest_probe, "scenario")
        if (
            "CURRENTLY SET" not in latest_probe
            or latest["scenario"] not in latest_probe
            or first["scenario"] in latest_probe
        ):
            raise ExecutorError("oracle_failed")
        _answer_interaction(
            agent_a,
            run_id=run_id,
            label="agent-a-cancel-state-probe",
            conversation_id=conversation_a,
            interaction=interaction,
            text="/cancel",
            budget=budget,
        )
        wait(agent_a, conversation_a, "complete", probe_transcript)
        observations["latest_prompt_persisted"] = True

        agent_b = _connect(
            transport,
            origin=origin,
            session_id=session_b,
            contract=contract,
            budget=budget,
        )
        connections.append(agent_b)
        _start_turn(
            agent_b,
            run_id=run_id,
            label="agent-b-isolation-probe",
            conversation_id=conversation_b,
            text=f"Generate a report for uploaded video {sensor_a}.",
            budget=budget,
        )
        isolation_transcript: list[dict[str, Any]] = []
        interaction = wait(agent_b, conversation_b, "interaction", isolation_transcript)
        isolated_probe = _interaction_text(interaction)
        _assert_prompt_stage(isolated_probe, "scenario")
        if (
            "DEFAULT" not in isolated_probe
            or first["scenario"] in isolated_probe
            or latest["scenario"] in isolated_probe
        ):
            raise ExecutorError("oracle_failed")
        _answer_interaction(
            agent_b,
            run_id=run_id,
            label="agent-b-cancel-isolation-probe",
            conversation_id=conversation_b,
            interaction=interaction,
            text="/cancel",
            budget=budget,
        )
        wait(agent_b, conversation_b, "complete", isolation_transcript)
        observations["cross_agent_prompt_isolation"] = True
        if not all(observations.values()):
            raise ExecutorError("oracle_failed")
    except ExecutorError as exc:
        primary = exc
    finally:
        for connection in reversed(connections):
            try:
                connection.close()
            except Exception:
                primary = primary or ExecutorError("transport_error")

        # A server can commit and announce a report object before a later
        # semantic or transport failure. Recover every strict expected-sensor
        # object key already present in either report transcript before cleanup.
        try:
            register_discovered(
                _discover_report_objects(single_transcript, [sensor_a]),
                collision_is_error=False,
            )
            register_discovered(
                _discover_report_objects(multi_transcript, [sensor_a, sensor_b]),
                collision_is_error=False,
            )
        except ExecutorError as exc:
            primary = primary or exc

        for sensor, path in reversed(registered):
            try:
                result = _http(
                    transport,
                    method="GET",
                    origin=origin,
                    path=path,
                    contract=contract,
                    budget=budget,
                )
                if not 200 <= result.status <= 299 or not result.body:
                    raise ExecutorError("oracle_failed")
                extension = artifact_rows[path]["extension"]
                if extension == "md":
                    try:
                        result.body.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ExecutorError("oracle_failed") from exc
                elif extension == "pdf":
                    if not result.body.startswith(b"%PDF-"):
                        raise ExecutorError("oracle_failed")
                else:
                    raise ExecutorError("configuration_error")
                artifact_rows[path].update(
                    read_status=result.status,
                    read_bytes=len(result.body),
                    read_sha256=_sha(result.body),
                )
            except ExecutorError as exc:
                primary = primary or exc
        for _sensor, path in reversed(registered):
            try:
                result = _http(
                    transport,
                    method="DELETE",
                    origin=origin,
                    path=path,
                    contract=contract,
                    budget=budget,
                )
                artifact_rows[path]["delete_status"] = result.status
                if result.status not in {200, 204}:
                    primary = primary or ExecutorError("cleanup_failed")
            except ExecutorError:
                primary = primary or ExecutorError("cleanup_failed")
        for _sensor, path in reversed(registered):
            try:
                result = _http(
                    transport,
                    method="GET",
                    origin=origin,
                    path=path,
                    contract=contract,
                    budget=budget,
                )
                artifact_rows[path]["post_status"] = result.status
                if result.status != 404:
                    primary = primary or ExecutorError("cleanup_failed")
            except ExecutorError:
                primary = primary or ExecutorError("cleanup_failed")

    if primary is not None:
        raise primary
    if (
        len(registered) != 6
        or len(artifact_rows) != 6
        or budget.requests != 34
        or budget.actions != 34
    ):
        raise ExecutorError("oracle_failed")
    stems = {row["stem_sha256"] for row in artifact_rows.values()}
    if len(stems) != 3:
        raise ExecutorError("oracle_failed")
    ordered_rows = [artifact_rows[path] for _sensor, path in registered]
    path_hashes = sorted(row["path_sha256"] for row in ordered_rows)
    coverage = contract["semantic_coverage"]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-nat-websocket-candidate",
        "status": "agent_session_subset_complete_non_promoting",
        "promotion_eligible": False,
        "executor_ready": False,
        "canonical_state_advanced": False,
        "contract_sha256": _sha(
            _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
        ),
        "manifest_sha256": _sha(_canonical(manifest)),
        "identity": {
            "authorization_id": contract["authorization"]["authorization_id"],
            "run_id_sha256": _sha(run_id),
        },
        "target": {
            "agent_origin_sha256": _sha(origin),
            "session_count": 2,
            "conversation_count": 2,
            "proxies_enabled": False,
            "redirects_enabled": False,
        },
        "budget": {
            "actions": budget.actions,
            "max_actions": budget.maximum,
            "requests": budget.requests,
            "max_requests": budget.maximum,
            "websocket_inbound_messages": inbound_messages,
        },
        "semantic_observations": observations,
        "coverage": {
            "concrete_complete": list(coverage["concrete_complete"]),
            "concrete_partial": sorted(coverage["concrete_partial"]),
            "residual_adapter_required": sorted(coverage["residual_adapter_required"]),
            "five_tool_runtime_discovery": False,
        },
        "artifacts": ordered_rows,
        "cleanup": {
            "semantics": "exact_object_key",
            "artifact_count": 6,
            "pair_count": 3,
            "artifact_set_sha256": _sha(_canonical(path_hashes)),
            "all_paths_from_completed_agent_responses": True,
            "delete_each_exact_key": True,
            "postcondition_each_404": True,
            "reverse_response_order": True,
            "namespace_delete_attempted": False,
            "recursive_delete_claimed": False,
            "foreign_resources_mutated": False,
            "fixture_cleanup_attempted": False,
            "preexisting_absence_proven": False,
        },
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "invalid_receipt")
    contract_digest = _sha(
        _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
    )
    if receipt["contract_sha256"] != contract_digest:
        raise ExecutorError("invalid_receipt")
    rows = receipt["artifacts"]
    if (
        len({row["path_sha256"] for row in rows}) != 6
        or len({row["stem_sha256"] for row in rows}) != 3
        or sorted(row["extension"] for row in rows) != ["md"] * 3 + ["pdf"] * 3
    ):
        raise ExecutorError("invalid_receipt")
    expected_set = _sha(_canonical(sorted(row["path_sha256"] for row in rows)))
    if receipt["cleanup"]["artifact_set_sha256"] != expected_set:
        raise ExecutorError("invalid_receipt")
    return {
        "schema_version": 1,
        "package_id": receipt["package_id"],
        "status": "candidate_receipt_valid_non_promoting",
        "promotion_eligible": False,
        "executor_ready": False,
        "canonical_state_advanced": False,
        "receipt_sha256": _sha(_canonical(receipt)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute-agent-session")
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--acknowledgement", required=True)
    validate = subparsers.add_parser("validate-receipt")
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "execute-agent-session":
            contract = _contract()
            if args.acknowledgement != contract["authorization"]["acknowledgement"]:
                raise ExecutorError("authorization_required")
            result = execute_agent_session(
                manifest=_json_file(args.manifest, "invalid_manifest"),
                acknowledgement=args.acknowledgement,
            )
        elif args.command == "validate-receipt":
            result = validate_receipt(_json_file(args.receipt, "invalid_receipt"))
        else:
            result = compile_plan()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
