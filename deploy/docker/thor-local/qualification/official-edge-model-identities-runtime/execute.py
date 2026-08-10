#!/usr/bin/env python3
"""Bounded semantic qualification for the exact VSS 3.2.1 Thor models."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
import zlib


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
COMMON_PATH = HERE.parent / "runtime-evidence-common" / "common.py"
ACKNOWLEDGEMENT = "I_ACK_OFFICIAL_EDGE_MODEL_IDENTITIES_AND_NO_STATE_CHANGE"
MAX_JSON_BYTES = 8 * 1024 * 1024
READINESS_STDOUT = b"PASS exact-model Thor demo runtime identity/readiness contract\n"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class QualificationError(RuntimeError):
    """Stable, sanitized qualification failure."""

    ALLOWED = {
        "acknowledgement_required",
        "budget_exceeded",
        "configuration_error",
        "disk_admission_failed",
        "http_contract_failed",
        "identity_mismatch",
        "invalid_response",
        "readiness_failed",
        "runtime_state_changed",
        "source_lock_mismatch",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.ALLOWED else "configuration_error"
        super().__init__(self.code)


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load_module(COMMON_PATH, "official_edge_model_runtime_common")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise QualificationError("configuration_error")
    return raw


def _digest_value(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _read_regular(path: Path, maximum: int = MAX_JSON_BYTES) -> bytes:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise QualificationError("configuration_error")
        if before.st_size < 1 or before.st_size > maximum:
            raise QualificationError("configuration_error")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
            ) != (before.st_dev, before.st_ino):
                raise QualificationError("configuration_error")
            raw = bytearray()
            while len(raw) <= maximum:
                block = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
        finally:
            os.close(descriptor)
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    if len(raw) != before.st_size or len(raw) > maximum:
        raise QualificationError("configuration_error")
    return bytes(raw)


def _strict_json(raw: bytes, code: str = "configuration_error") -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise QualificationError(code)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                QualificationError(code)
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(code) from exc
    if not isinstance(value, dict):
        raise QualificationError(code)
    return value


def _source_path(path_text: str) -> Path:
    candidate = Path(path_text)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != path_text
    ):
        raise QualificationError("source_lock_mismatch")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError("source_lock_mismatch")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise QualificationError("source_lock_mismatch") from exc
    return resolved


def _load_contract() -> dict[str, Any]:
    contract = _strict_json(_read_regular(CONTRACT_PATH))
    if (
        contract.get("schema_version") != 1
        or contract.get("tool_id")
        != "thor-official-edge-model-identities-runtime"
        or contract.get("capability_ids")
        != [
            "model.edge.nemotron-3-nano-4b-fp8",
            "model.edge.cosmos3-nano-served-id",
        ]
        or contract.get("acknowledgement") != ACKNOWLEDGEMENT
        or contract.get("default_execution_enabled") is not False
    ):
        raise QualificationError("configuration_error")
    bounds = contract.get("execution_bounds")
    if bounds != {
        "max_duration_seconds": 240,
        "max_http_requests": 6,
        "max_semantic_actions": 2,
        "max_request_bytes": 262144,
        "max_response_bytes": 1048576,
        "request_timeout_seconds": 45,
        "readiness_timeout_seconds": 120,
        "min_free_bytes": 10737418240,
        "network_scope": "numeric-loopback-only",
        "model_staging": "forbidden",
        "service_lifecycle": "forbidden",
        "warehouse_sample_bundle": "excluded",
    }:
        raise QualificationError("configuration_error")
    workload = contract.get("http_workload")
    expected_workload = [
        (1, "llm", "GET", "/v1/models"),
        (2, "vlm", "GET", "/v1/models"),
        (3, "vlm", "GET", "/v1/assets/stats"),
        (4, "llm", "POST", "/v1/chat/completions"),
        (5, "vlm", "POST", "/v1/chat/completions"),
        (6, "vlm", "GET", "/v1/assets/stats"),
    ]
    if not isinstance(workload, list) or [
        (row.get("order"), row.get("role"), row.get("method"), row.get("path"))
        for row in workload
        if isinstance(row, dict)
    ] != expected_workload:
        raise QualificationError("configuration_error")
    anchors = contract.get("source_anchors")
    if not isinstance(anchors, list) or len(anchors) != 9:
        raise QualificationError("source_lock_mismatch")
    seen: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or set(anchor) != {"path", "bytes", "sha256"}:
            raise QualificationError("source_lock_mismatch")
        path_text = anchor.get("path")
        byte_count = anchor.get("bytes")
        digest = anchor.get("sha256")
        if (
            not isinstance(path_text, str)
            or path_text in seen
            or type(byte_count) is not int
            or byte_count < 1
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
        ):
            raise QualificationError("source_lock_mismatch")
        raw = _read_regular(_source_path(path_text))
        if len(raw) != byte_count or not hmac.compare_digest(
            _sha256_bytes(raw), digest
        ):
            raise QualificationError("source_lock_mismatch")
        seen.add(path_text)
    models = contract.get("models")
    if not isinstance(models, dict) or set(models) != {"llm", "vlm"}:
        raise QualificationError("configuration_error")
    for role, paths in {
        "llm": ("/v1/models", "/v1/chat/completions"),
        "vlm": ("/v1/models", "/v1/assets/stats", "/v1/chat/completions"),
    }.items():
        model = models[role]
        try:
            common.LoopbackTarget.admit(model["origin"], paths)
        except Exception as exc:
            raise QualificationError("configuration_error") from exc
    if (
        contract.get("official_contract", {}).get("cloud_inference_required")
        is not False
        or contract.get("cleanup", {}).get("mutation") != "none"
    ):
        raise QualificationError("configuration_error")
    return contract


def _free_bytes() -> int:
    stats = os.statvfs(REPO_ROOT)
    return stats.f_bavail * stats.f_frsize


def _docker_inspect(name: str) -> dict[str, Any]:
    if name not in {"vss-nemotron-edge-4b", "vss-rtvi-vlm"}:
        raise QualificationError("configuration_error")
    try:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", name],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("identity_mismatch") from exc
    if result.returncode != 0 or not result.stdout or len(result.stdout) > MAX_JSON_BYTES:
        raise QualificationError("identity_mismatch")
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("identity_mismatch") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise QualificationError("identity_mismatch")
    return cast(dict[str, Any], value[0])


def _env_map(values: Any) -> dict[str, str]:
    if not isinstance(values, list):
        raise QualificationError("identity_mismatch")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, str) or "=" not in row:
            raise QualificationError("identity_mismatch")
        key, value = row.split("=", 1)
        if not key or key in result:
            raise QualificationError("identity_mismatch")
        result[key] = value
    return result


def _mount_map(values: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        raise QualificationError("identity_mismatch")
    result: dict[str, dict[str, Any]] = {}
    for row in values:
        if not isinstance(row, dict):
            raise QualificationError("identity_mismatch")
        destination = row.get("Destination")
        if not isinstance(destination, str) or destination in result:
            raise QualificationError("identity_mismatch")
        result[destination] = row
    return result


def _absolute_mount_source(row: Mapping[str, Any], *, read_only: bool) -> Path:
    source = row.get("Source")
    if (
        row.get("Type") != "bind"
        or row.get("RW") is not (not read_only)
        or not isinstance(source, str)
        or not Path(source).is_absolute()
        or "\n" in source
        or "\r" in source
    ):
        raise QualificationError("identity_mismatch")
    return Path(source)


def _capture_runtime(
    contract: Mapping[str, Any],
    inspector: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, Any], Path, Path]:
    projections: dict[str, Any] = {}
    private_paths: dict[str, Path] = {}
    for role in ("llm", "vlm"):
        expected = contract["models"][role]
        document = inspector(expected["container"])
        state = document.get("State")
        config = document.get("Config")
        if not isinstance(state, dict) or not isinstance(config, dict):
            raise QualificationError("identity_mismatch")
        health = state.get("Health")
        health_status = health.get("Status") if isinstance(health, dict) else None
        if (
            document.get("Name") != f"/{expected['container']}"
            or document.get("Image") != expected["image_id"]
            or config.get("Image") != expected["image_reference"]
            or state.get("Running") is not True
            or health_status != "healthy"
            or state.get("OOMKilled") is not False
            or document.get("RestartCount") != 0
            or not isinstance(document.get("Id"), str)
            or not isinstance(state.get("StartedAt"), str)
        ):
            raise QualificationError("identity_mismatch")
        mounts = _mount_map(document.get("Mounts"))
        if role == "llm":
            if config.get("Cmd") != expected["command"]:
                raise QualificationError("identity_mismatch")
            model_source = _absolute_mount_source(
                mounts.get(expected["model_mount_destination"], {}), read_only=True
            )
            blob_source = _absolute_mount_source(
                mounts.get(expected["blob_mount_destination"], {}), read_only=True
            )
            if (
                model_source.name != expected["artifact_revision"]
                or model_source.parent.name != "snapshots"
                or model_source.parent.parent / "blobs" != blob_source
            ):
                raise QualificationError("identity_mismatch")
            private_paths["edge_snapshot"] = model_source
            mount_projection = {
                "model_source_sha256": _sha256_bytes(str(model_source).encode()),
                "blob_source_sha256": _sha256_bytes(str(blob_source).encode()),
                "both_read_only": True,
            }
            config_projection = {
                "command_sha256": _digest_value(config["Cmd"]),
                "served_model_id": expected["served_model_id"],
                "gpu_memory_utilization": expected["gpu_memory_utilization"],
                "tool_call_parser": expected["tool_call_parser"],
            }
        else:
            environment = _env_map(config.get("Env"))
            if any(environment.get(key) != value for key, value in expected["environment"].items()):
                raise QualificationError("identity_mismatch")
            cache_source = _absolute_mount_source(
                mounts.get(expected["ngc_cache_mount_destination"], {}),
                read_only=False,
            )
            model_path = cache_source / expected["served_model_id"]
            private_paths["cosmos_model"] = model_path
            mount_projection = {
                "cache_source_sha256": _sha256_bytes(str(cache_source).encode()),
                "writable_runtime_cache": True,
            }
            config_projection = {
                "environment_sha256": _digest_value(
                    {key: environment[key] for key in sorted(expected["environment"])}
                ),
                "artifact_id": expected["artifact_id"],
                "served_model_id": expected["served_model_id"],
                "selector": expected["selector"],
            }
        projections[role] = {
            "container_id_sha256": _sha256_bytes(document["Id"].encode()),
            "image_id": document["Image"],
            "image_reference": config["Image"],
            "started_at_sha256": _sha256_bytes(state["StartedAt"].encode()),
            "health": health_status,
            "running": True,
            "restart_count": 0,
            "oom_killed": False,
            "mounts": mount_projection,
            "configuration": config_projection,
        }
    return projections, private_paths["edge_snapshot"], private_paths["cosmos_model"]


def _run_readiness(edge_snapshot: Path, cosmos_model: Path, timeout: int) -> dict[str, Any]:
    for path in (edge_snapshot, cosmos_model):
        if not path.is_absolute() or "\n" in str(path) or "\r" in str(path):
            raise QualificationError("readiness_failed")
    command = [
        sys.executable,
        str(REPO_ROOT / "deploy/docker/thor-local/official-edge/thor_demo.py"),
        "--edge4b-snapshot",
        str(edge_snapshot),
        "--cosmos3-cache",
        str(cosmos_model),
        "readiness",
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("readiness_failed") from exc
    duration = time.monotonic() - started
    if (
        result.returncode != 0
        or result.stdout != READINESS_STDOUT
        or result.stderr not in {b"", None}
    ):
        raise QualificationError("readiness_failed")
    return {
        "passed": True,
        "duration_seconds": round(duration, 6),
        "stdout_sha256": _sha256_bytes(result.stdout),
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class LiveOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, request: Request, timeout: float) -> Any:
        return self._opener.open(request, timeout=timeout)


def _validate_origin(origin: str) -> str:
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise QualificationError("configuration_error") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or port is None
    ):
        raise QualificationError("configuration_error")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise QualificationError("configuration_error") from exc
    if not address.is_loopback or address.version != 4:
        raise QualificationError("configuration_error")
    return f"http://{address.compressed}:{port}"


def _http_request(
    *,
    origin: str,
    allowed_paths: set[str],
    opener: Any,
    method: str,
    path: str,
    body: bytes,
    timeout: int,
    max_request_bytes: int,
    max_response_bytes: int,
) -> tuple[int, str, bytes]:
    origin = _validate_origin(origin)
    if (
        path not in allowed_paths
        or method not in {"GET", "POST"}
        or len(body) > max_request_bytes
        or getattr(opener, "proxies_enabled", None) is not False
        or getattr(opener, "redirects_enabled", None) is not False
    ):
        raise QualificationError("http_contract_failed")
    url = origin + path
    headers = {"Accept": "application/json", "Content-Length": str(len(body))}
    if body:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body or None, method=method, headers=headers)
    response: Any = None
    try:
        try:
            response = opener.open(request, timeout=float(timeout))
        except HTTPError as exc:
            response = exc
        status = response.status
        final_url = response.geturl()
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        raw = response.read(max_response_bytes + 1)
    except QualificationError:
        raise
    except Exception as exc:
        raise QualificationError("transport_error") from exc
    finally:
        if response is not None:
            response.close()
    if (
        status != 200
        or final_url != url
        or media_type != "application/json"
        or not isinstance(raw, bytes)
        or len(raw) > max_response_bytes
    ):
        raise QualificationError("invalid_response")
    return status, media_type, raw


def _model_id(value: Mapping[str, Any], expected: str) -> None:
    data = value.get("data")
    if (
        not isinstance(data, list)
        or len(data) != 1
        or not isinstance(data[0], dict)
        or data[0].get("id") != expected
    ):
        raise QualificationError("identity_mismatch")


def _composite_png(
    panels: list[tuple[int, int, int]], panel_width: int, height: int
) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    if not panels or panel_width < 1 or height < 1:
        raise QualificationError("configuration_error")
    width = panel_width * len(panels)
    row = b"".join(bytes(rgb) * panel_width for rgb in panels)
    scanlines = b"".join(b"\x00" + row for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def _llm_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    semantic = contract["semantic_contract"]
    tool_name = semantic["llm_tool_name"]
    message = semantic["llm_tool_message"]
    return {
        "model": contract["models"]["llm"]["served_model_id"],
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Call the {tool_name} tool exactly once with message {message}. "
                    "Do not answer with text."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Return a bounded local qualification ping.",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["message"],
                        "properties": {"message": {"type": "string"}},
                    },
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "temperature": 0,
        "max_tokens": 64,
        "chat_template_kwargs": {
            "enable_thinking": semantic["llm_enable_thinking"]
        },
    }


def _vlm_payload(contract: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    semantic = contract["semantic_contract"]
    fixture = semantic["vlm_composite_image"]
    panels: list[tuple[int, int, int]] = []
    for row in fixture["panels"]:
        rgb = tuple(row["rgb"])
        if len(rgb) != 3 or any(type(value) is not int for value in rgb):
            raise QualificationError("configuration_error")
        panels.append(cast(tuple[int, int, int], rgb))
    raw = _composite_png(panels, fixture["panel_width"], fixture["height"])
    if len(panels) * fixture["panel_width"] != fixture["width"]:
        raise QualificationError("configuration_error")
    digest = _sha256_bytes(raw)
    if digest != fixture["sha256"]:
        raise QualificationError("source_lock_mismatch")
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "This image contains four vertical solid-color panels. Identify "
                "their colors from left to right. Respond using the four basic "
                "color names only."
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
            },
        },
    ]
    return (
        {
            "model": contract["models"]["vlm"]["served_model_id"],
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": 64,
            "vlm_input_width": fixture["width"],
            "vlm_input_height": fixture["height"],
        },
        digest,
    )


def _llm_proof(value: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    try:
        choice = value["choices"][0]
        message = choice["message"]
        calls = message["tool_calls"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("invalid_response") from exc
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        raise QualificationError("invalid_response")
    function = calls[0].get("function")
    if not isinstance(function, dict):
        raise QualificationError("invalid_response")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise QualificationError("invalid_response")
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise QualificationError("invalid_response") from exc
    semantic = contract["semantic_contract"]
    expected_arguments = {"message": semantic["llm_tool_message"]}
    if (
        function.get("name") != semantic["llm_tool_name"]
        or decoded != expected_arguments
        or value.get("model") not in {
            None,
            contract["models"]["llm"]["served_model_id"],
        }
    ):
        raise QualificationError("invalid_response")
    return {
        "tool_call_count": 1,
        "tool_name_exact": True,
        "tool_arguments_exact": True,
        "thinking_disabled": True,
        "response_model_exact": value.get("model")
        == contract["models"]["llm"]["served_model_id"],
        "arguments_sha256": _digest_value(decoded),
    }


def _vlm_proof(value: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content = value["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QualificationError("invalid_response") from exc
    if not isinstance(content, str):
        raise QualificationError("invalid_response")
    tokens = re.findall(r"[a-z]+", content.lower())
    expected = contract["semantic_contract"]["vlm_expected_color_tokens"]
    if tokens != expected:
        raise QualificationError("invalid_response")
    return {
        "visual_answer_exact": True,
        "ordered_image_count": 1,
        "ordered_panel_count": 4,
        "normalized_answer_sha256": _digest_value(tokens),
        "response_model_exact": value.get("model")
        in {None, contract["models"]["vlm"]["served_model_id"]},
    }


def _observation(
    order: int,
    role: str,
    method: str,
    path: str,
    request_body: bytes,
    response_body: bytes,
) -> dict[str, Any]:
    return {
        "order": order,
        "role": role,
        "method": method,
        "path_template": path,
        "http_status": 200,
        "request_bytes": len(request_body),
        "request_sha256": _sha256_bytes(request_body),
        "response_bytes": len(response_body),
        "response_sha256": _sha256_bytes(response_body),
    }


def plan() -> dict[str, Any]:
    contract = _load_contract()
    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "plan",
        "status": "passed",
        "runtime_activity_performed": False,
        "http_request_count": 0,
        "writes_or_lifecycle_actions": False,
        "warehouse_sample_bundle": False,
        "capability_ids": contract["capability_ids"],
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "execution_requires_acknowledgement": ACKNOWLEDGEMENT,
    }


def execute(
    *,
    acknowledgement: str,
    inspector: Callable[[str], dict[str, Any]] = _docker_inspect,
    readiness_runner: Callable[[Path, Path, int], dict[str, Any]] = _run_readiness,
    opener_factory: Callable[[str], Any] = lambda _role: LiveOpener(),
    free_bytes_provider: Callable[[], int] = _free_bytes,
    monotonic: Callable[[], float] = time.monotonic,
    utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    if acknowledgement != ACKNOWLEDGEMENT:
        raise QualificationError("acknowledgement_required")
    contract = _load_contract()
    bounds = contract["execution_bounds"]
    free_bytes = free_bytes_provider()
    if type(free_bytes) is not int or free_bytes < bounds["min_free_bytes"]:
        raise QualificationError("disk_admission_failed")
    started_at = utcnow()
    started = monotonic()
    pre_state, edge_snapshot, cosmos_model = _capture_runtime(contract, inspector)
    readiness = readiness_runner(
        edge_snapshot, cosmos_model, bounds["readiness_timeout_seconds"]
    )
    if readiness.get("passed") is not True:
        raise QualificationError("readiness_failed")
    targets = {
        role: contract["models"][role]["origin"] for role in ("llm", "vlm")
    }
    openers = {role: opener_factory(role) for role in ("llm", "vlm")}
    allowed_paths = {
        "llm": {"/v1/models", "/v1/chat/completions"},
        "vlm": {"/v1/models", "/v1/assets/stats", "/v1/chat/completions"},
    }
    observations: list[dict[str, Any]] = []
    request_count = 0

    def request(role: str, method: str, path: str, body: bytes = b"") -> bytes:
        nonlocal request_count
        request_count += 1
        if request_count > bounds["max_http_requests"]:
            raise QualificationError("budget_exceeded")
        status, _media_type, raw = _http_request(
            origin=targets[role],
            allowed_paths=allowed_paths[role],
            opener=openers[role],
            method=method,
            path=path,
            body=body,
            timeout=bounds["request_timeout_seconds"],
            max_request_bytes=bounds["max_request_bytes"],
            max_response_bytes=bounds["max_response_bytes"],
        )
        if status != 200:
            raise QualificationError("invalid_response")
        observations.append(
            _observation(request_count, role, method, path, body, raw)
        )
        return raw

    llm_models_raw = request("llm", "GET", "/v1/models")
    llm_models = _strict_json(llm_models_raw, "invalid_response")
    _model_id(llm_models, contract["models"]["llm"]["served_model_id"])

    vlm_models_raw = request("vlm", "GET", "/v1/models")
    vlm_models = _strict_json(vlm_models_raw, "invalid_response")
    _model_id(vlm_models, contract["models"]["vlm"]["served_model_id"])

    assets_pre_raw = request("vlm", "GET", "/v1/assets/stats")
    assets_pre = _strict_json(assets_pre_raw, "invalid_response")

    llm_request = _canonical_bytes(_llm_payload(contract))
    llm_response_raw = request(
        "llm", "POST", "/v1/chat/completions", llm_request
    )
    llm_response = _strict_json(llm_response_raw, "invalid_response")
    llm_proof = _llm_proof(llm_response, contract)

    vlm_payload, image_digest = _vlm_payload(contract)
    vlm_request = _canonical_bytes(vlm_payload)
    vlm_response_raw = request(
        "vlm", "POST", "/v1/chat/completions", vlm_request
    )
    vlm_response = _strict_json(vlm_response_raw, "invalid_response")
    vlm_proof = _vlm_proof(vlm_response, contract)

    assets_post_raw = request("vlm", "GET", "/v1/assets/stats")
    assets_post = _strict_json(assets_post_raw, "invalid_response")
    assets_pre_sha = _digest_value(assets_pre)
    assets_post_sha = _digest_value(assets_post)
    if not hmac.compare_digest(assets_pre_sha, assets_post_sha):
        raise QualificationError("runtime_state_changed")

    post_state, post_edge_snapshot, post_cosmos_model = _capture_runtime(
        contract, inspector
    )
    if (
        pre_state != post_state
        or edge_snapshot != post_edge_snapshot
        or cosmos_model != post_cosmos_model
    ):
        raise QualificationError("runtime_state_changed")
    duration = monotonic() - started
    if (
        request_count != bounds["max_http_requests"]
        or duration < 0
        or duration > bounds["max_duration_seconds"]
    ):
        raise QualificationError("budget_exceeded")
    completed_at = utcnow()
    receipt = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "execute",
        "status": "passed",
        "failure": None,
        "capability_ids": contract["capability_ids"],
        "target": contract["target"],
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "duration_seconds": round(duration, 6),
        "http_request_count": request_count,
        "semantic_action_count": 2,
        "network_scope": "numeric-loopback-only",
        "writes_or_lifecycle_actions": False,
        "warehouse_sample_bundle": False,
        "forbidden_actions_observed": [],
        "source_projection_sha256": _digest_value(
            {
                row["path"]: row["sha256"]
                for row in contract["source_anchors"]
            }
        ),
        "readiness": readiness,
        "runtime_identity": {
            "pre": pre_state,
            "post": post_state,
            "exact": True,
        },
        "observations": observations,
        "llm_proof": {
            "served_model_id": contract["models"]["llm"]["served_model_id"],
            "artifact_revision": contract["models"]["llm"]["artifact_revision"],
            "model_identity_exact": True,
            "model_response_sha256": _sha256_bytes(llm_models_raw),
            "semantic_response_sha256": _sha256_bytes(llm_response_raw),
            "semantic_response_bytes": len(llm_response_raw),
            **llm_proof,
        },
        "vlm_proof": {
            "artifact_id": contract["models"]["vlm"]["artifact_id"],
            "served_model_id": contract["models"]["vlm"]["served_model_id"],
            "selector": contract["models"]["vlm"]["selector"],
            "model_identity_exact": True,
            "model_response_sha256": _sha256_bytes(vlm_models_raw),
            "semantic_response_sha256": _sha256_bytes(vlm_response_raw),
            "semantic_response_bytes": len(vlm_response_raw),
            "fixture_image_sha256": image_digest,
            **vlm_proof,
        },
        "cleanup": {
            "mutation": "none",
            "asset_statistics_pre_sha256": assets_pre_sha,
            "asset_statistics_post_sha256": assets_post_sha,
            "asset_statistics_exact": True,
            "container_identity_exact": True,
            "owned_resource_count": 0,
            "failures": [],
        },
        "sanitization": {
            "raw_prompts_included": False,
            "response_bodies_included": False,
            "credential_values_included": False,
            "dynamic_identifiers_included": False,
            "local_paths_included": False,
        },
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    contract = _load_contract()
    if (
        receipt.get("schema_version") != 1
        or receipt.get("tool_id") != contract["tool_id"]
        or receipt.get("mode") != "execute"
        or receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("capability_ids") != contract["capability_ids"]
        or receipt.get("contract_sha256") != _sha256_file(CONTRACT_PATH)
        or receipt.get("http_request_count") != 6
        or receipt.get("semantic_action_count") != 2
        or receipt.get("network_scope") != "numeric-loopback-only"
        or receipt.get("writes_or_lifecycle_actions") is not False
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("forbidden_actions_observed") != []
    ):
        raise QualificationError("configuration_error")
    observations = receipt.get("observations")
    if not isinstance(observations, list) or [
        (row.get("order"), row.get("role"), row.get("method"), row.get("path_template"))
        for row in observations
        if isinstance(row, dict)
    ] != [
        (row["order"], row["role"], row["method"], row["path"])
        for row in contract["http_workload"]
    ]:
        raise QualificationError("configuration_error")
    if any(row.get("http_status") != 200 for row in observations):
        raise QualificationError("configuration_error")
    llm = receipt.get("llm_proof")
    vlm = receipt.get("vlm_proof")
    cleanup = receipt.get("cleanup")
    identity = receipt.get("runtime_identity")
    if (
        not isinstance(llm, dict)
        or llm.get("served_model_id") != contract["models"]["llm"]["served_model_id"]
        or llm.get("model_identity_exact") is not True
        or llm.get("tool_call_count") != 1
        or llm.get("tool_name_exact") is not True
        or llm.get("tool_arguments_exact") is not True
        or llm.get("thinking_disabled") is not True
        or not isinstance(vlm, dict)
        or vlm.get("artifact_id") != contract["models"]["vlm"]["artifact_id"]
        or vlm.get("served_model_id") != contract["models"]["vlm"]["served_model_id"]
        or vlm.get("model_identity_exact") is not True
        or vlm.get("visual_answer_exact") is not True
        or vlm.get("ordered_image_count") != 1
        or vlm.get("ordered_panel_count") != 4
        or not isinstance(cleanup, dict)
        or cleanup.get("mutation") != "none"
        or cleanup.get("asset_statistics_exact") is not True
        or cleanup.get("container_identity_exact") is not True
        or cleanup.get("owned_resource_count") != 0
        or cleanup.get("failures") != []
        or not isinstance(identity, dict)
        or identity.get("exact") is not True
        or identity.get("pre") != identity.get("post")
        or receipt.get("readiness", {}).get("passed") is not True
    ):
        raise QualificationError("configuration_error")
    serialized = _canonical_bytes(receipt).decode("ascii").lower()
    forbidden_literals = [
        "nvapi-",
        "bearer ",
        "authorization\"",
        "request_id",
        "session_id",
        "data:image/",
        "http://127.0.0.1",
        "/home/nvidia/",
        "call the thor_contract_ping",
    ]
    if any(literal in serialized for literal in forbidden_literals):
        raise QualificationError("configuration_error")


def _retain(receipt: Mapping[str, Any]) -> None:
    raw = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True).encode("ascii") + b"\n"
    temporary = HERE / f".runtime-receipt.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o644)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise QualificationError("configuration_error")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, RECEIPT_PATH)
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--ack", required=True)
    execute_parser.add_argument("--retain", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {None, "plan"}:
            result = plan()
        else:
            result = execute(acknowledgement=args.ack)
            if args.retain:
                _retain(result)
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
