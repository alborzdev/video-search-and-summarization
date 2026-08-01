#!/usr/bin/env python3
"""Execute a bounded, non-advancing LVS MCP candidate subset.

The production ``LvsMCPServer`` implementation is imported with registration-only
MCP type stubs. Its real tool catalog and in-process ASGI dispatch execute against
a deterministic FastAPI backend. No transport, socket, subprocess, Docker command,
service lifecycle, model, credential, download, or Warehouse path is available.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path, PurePosixPath
import socket
import stat
import subprocess
import sys
import tempfile
import types
from typing import Any, Iterator
from unittest import mock
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_INPUT_BYTES = 4_000_000
EXPECTED_ENTRIES = (
    "manifest-gap.video-summarization-live.05-sse-mcp-server",
    "manifest-gap.agent-and-mcp-apis.06-lvs-mcp",
)
EXPECTED_TOOLS = (
    "add_file",
    "delete_file",
    "generate_captions",
    "generate_vlm_captions",
    "get_file_info",
    "get_metrics",
    "get_recommended_config",
    "health_live",
    "health_ready",
    "list_files",
    "list_models",
    "stream_summarize",
    "summarize_video",
)
EXPECTED_OPERATIONS = (
    "file_add",
    "file_delete",
    "file_info",
    "file_list",
    "file_rejection_matrix",
    "health_error_propagation",
    "health_live",
    "health_ready",
    "rollback_after_invalid_metadata",
    "sanitized_file_error",
    "tool_registration",
)


class QualificationError(RuntimeError):
    """A source lock, boundary, or semantic assertion did not match."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _repo_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(f"repository input unavailable: {relative}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative}"
        )
    resolved = path.resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise QualificationError(f"repository input escaped root: {relative}")
    if metadata.st_size > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return path


def _read_repo_bytes(relative: str) -> bytes:
    data = _repo_file(relative).read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise QualificationError(f"repository input exceeds size bound: {relative}")
    return data


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise QualificationError(f"invalid JSON pointer: {pointer}")
    value = document
    try:
        for raw in pointer.split("/")[1:]:
            token = raw.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise QualificationError(f"unresolved JSON pointer: {pointer}") from exc
    return value


def _load_lock(lock: dict[str, str], digests: dict[str, str]) -> Any:
    raw = _read_repo_bytes(lock["path"])
    actual = _sha256(raw)
    expected = lock.get("raw_sha256", lock.get("sha256"))
    if actual != expected:
        raise QualificationError(f"source lock mismatch: {lock['path']}")
    digests[lock["path"]] = actual
    return _strict_json_bytes(raw, lock["path"])


def _load_inventory() -> tuple[dict[str, Any], dict[str, str]]:
    inventory = _strict_json_bytes(INVENTORY_PATH.read_bytes(), INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    digests: dict[str, str] = {}

    plan = _load_lock(inventory["source_plan"], digests)
    if (
        plan.get("plan_payload_sha256")
        != inventory["source_plan"]["plan_payload_sha256"]
    ):
        raise QualificationError("gap-plan payload identity mismatch")
    manifest = _load_lock(inventory["source_manifest"], digests)
    official = _load_lock(inventory["live_official_capabilities"], digests)
    oracles = _load_lock(inventory["live_capability_oracles"], digests)

    predecessors = {
        item["role"]: (item, _load_lock(item, digests))
        for item in inventory["predecessors"]
    }
    wave3 = predecessors["exact_original_source_candidates"][1]
    wave7 = predecessors["complete_pre_wave8_candidate_denominator"][1]
    if wave7.get("denominator") != {
        "advertised_gap_entries": 87,
        "previous_wave_candidates": 71,
        "separate_detection_map_candidates": 1,
        "pre_wave7_candidates": 72,
        "wave7_remaining_entries": 15,
        "selected_source_candidates": 11,
        "external_attestation_blockers": 4,
        "post_wave7_candidates": 83,
        "entries_without_candidate": 4,
        "official_open_entries": 87,
    }:
        raise QualificationError("pre-Wave-8 denominator drift")
    wave3_lock = predecessors["exact_original_source_candidates"][0]
    if not any(
        item.get("path") == wave3_lock["path"]
        and item.get("raw_sha256") == wave3_lock["raw_sha256"]
        for item in wave7.get("previous_candidate_inventories", [])
    ):
        raise QualificationError("Wave 7 no longer binds the Wave 3 predecessor")

    cases = inventory["cases"]
    if tuple(item["entry_id"] for item in cases) != EXPECTED_ENTRIES:
        raise QualificationError("selected entry order or identity drift")
    plan_by_id = {item["entry_id"]: item for item in plan.get("entries", [])}
    wave3_by_id = {item["entry_id"]: item for item in wave3.get("cases", [])}
    official_ids = {item.get("id") for item in official.get("capabilities", [])}
    oracle_capability_ids = {
        item.get("capability_id") for item in oracles.get("oracles", [])
    }
    oracle_ids = {item.get("oracle_id") for item in oracles.get("oracles", [])}

    for case in cases:
        entry_id = case["entry_id"]
        if _resolve_pointer(manifest, case["manifest_pointer"]) != case["advertised"]:
            raise QualificationError(f"manifest literal drift: {entry_id}")
        if (
            _sha256(case["advertised"].encode("utf-8"))
            != case["advertised_utf8_sha256"]
        ):
            raise QualificationError(f"advertised UTF-8 identity drift: {entry_id}")
        if (
            _sha256(_canonical_bytes(case["advertised"]))
            != case["advertised_canonical_sha256"]
        ):
            raise QualificationError(f"advertised canonical identity drift: {entry_id}")
        predecessor = wave3_by_id.get(entry_id)
        if (
            predecessor is None
            or _sha256(_canonical_bytes(predecessor))
            != case["predecessor_case_canonical_sha256"]
        ):
            raise QualificationError(f"Wave 3 candidate identity drift: {entry_id}")
        plan_entry = plan_by_id.get(entry_id)
        if (
            plan_entry is None
            or plan_entry.get("coverage_state")
            != "open_missing_entry_capability_and_oracle"
            or plan_entry.get("runtime_evidence") != []
            or plan_entry.get("proposed_capability", {}).get("id")
            != case["proposed_capability_id"]
            or plan_entry.get("required_oracle", {}).get("id") != case["oracle_id"]
            or plan_entry.get("required_oracle", {}).get("status") != "open_unexecuted"
            or plan_entry.get("required_oracle", {}).get("runtime_evidence") != []
        ):
            raise QualificationError(f"gap-plan open boundary drift: {entry_id}")
        if case["proposed_capability_id"] in official_ids | oracle_capability_ids:
            raise QualificationError(
                f"candidate unexpectedly entered live ledgers: {entry_id}"
            )
        if case["oracle_id"] in oracle_ids:
            raise QualificationError(
                f"candidate oracle unexpectedly entered live ledger: {entry_id}"
            )

    expected_source_paths = {
        "services/video-summarization/src/lvs_mcp.py",
        "services/video-summarization/src/via_server.py",
        "services/video-summarization/src/rtvi_vlm_client.py",
        "services/video-summarization/tests/test_lvs_mcp.py",
        "deploy/docker/services/video-summarization/compose.yml",
    }
    if {item["path"] for item in inventory["source_locks"]} != expected_source_paths:
        raise QualificationError("source-lock path set drift")
    for lock in inventory["source_locks"]:
        raw = _read_repo_bytes(lock["path"])
        actual = _sha256(raw)
        if actual != lock["sha256"]:
            raise QualificationError(f"source lock mismatch: {lock['path']}")
        digests[lock["path"]] = actual

    fixture = inventory["fixture"]
    fixture_bytes = fixture["content_utf8"].encode("utf-8")
    if (
        len(fixture_bytes) > fixture["max_bytes"]
        or _sha256(fixture_bytes) != fixture["sha256"]
    ):
        raise QualificationError("fixture identity or size drift")
    return inventory, digests


class _Record:
    def __init__(self, *_args: Any, **values: Any):
        self.__dict__.update(values)


class _RegistrationServer:
    """Minimal import-only stand-in for MCP registration types."""

    def __init__(self, name: str):
        if name != "lvs-engine":
            raise QualificationError("production MCP server identity drift")
        self.list_handler = None
        self.call_handler = None

    def list_tools(self):
        def decorator(function):
            self.list_handler = function
            return function

        return decorator

    def call_tool(self):
        def decorator(function):
            self.call_handler = function
            return function

        return decorator

    async def run(self, *_args: Any, **_kwargs: Any) -> None:
        raise QualificationError("MCP transport execution is prohibited")

    def create_initialization_options(self) -> None:
        raise QualificationError("MCP handshake execution is prohibited")


class _ForbiddenTransport:
    def __init__(self, *_args: Any, **_kwargs: Any):
        raise QualificationError("MCP transport construction is prohibited")


@contextmanager
def _registration_import_stubs() -> Iterator[None]:
    names = (
        "mcp",
        "mcp.server",
        "mcp.server.sse",
        "mcp.server.stdio",
        "mcp.types",
        "via_logger",
    )
    prior = {name: sys.modules.get(name) for name in names}
    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    sse = types.ModuleType("mcp.server.sse")
    stdio = types.ModuleType("mcp.server.stdio")
    mcp_types = types.ModuleType("mcp.types")
    via_logger = types.ModuleType("via_logger")
    server.Server = _RegistrationServer
    sse.SseServerTransport = _ForbiddenTransport

    def forbidden_stdio():
        raise QualificationError("MCP stdio transport is prohibited")

    stdio.stdio_server = forbidden_stdio
    mcp_types.TextContent = _Record
    mcp_types.Tool = _Record
    quiet_logger = logging.getLogger("wave8-lvs-mcp")
    quiet_logger.propagate = False
    quiet_logger.setLevel(logging.CRITICAL + 1)
    quiet_logger.handlers[:] = [logging.NullHandler()]
    via_logger.logger = quiet_logger
    mcp.server = server
    sys.modules.update(
        {
            "mcp": mcp,
            "mcp.server": server,
            "mcp.server.sse": sse,
            "mcp.server.stdio": stdio,
            "mcp.types": mcp_types,
            "via_logger": via_logger,
        }
    )
    try:
        yield
    finally:
        for name, module in prior.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_production_module():
    source = _repo_file("services/video-summarization/src/lvs_mcp.py")
    name = "wave8_digest_locked_lvs_mcp"
    sys.modules.pop(name, None)
    prior_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        with (
            _registration_import_stubs(),
            mock.patch.dict(os.environ, {"VSS_API_ENABLE_VERSIONING": ""}, clear=False),
        ):
            spec = importlib.util.spec_from_file_location(name, source)
            if spec is None or spec.loader is None:
                raise QualificationError("could not create production import spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior_dont_write_bytecode
    return module


class _FakeLvsBackend:
    """Deterministic ASGI backend; it never opens a socket or invokes a callback."""

    def __init__(self):
        self._app = FastAPI()
        self.assets: dict[str, dict[str, Any]] = {}
        self.ready_error = False
        self.invalid_upload_identity = False
        self.delete_calls: list[str] = []
        self._register_routes()

    def _register_routes(self) -> None:
        @self._app.get("/v1/ready")
        async def ready():
            if self.ready_error:
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "DependencyUnavailable",
                        "message": "deterministic readiness failure",
                    },
                )
            return Response(status_code=200)

        @self._app.get("/v1/live")
        async def live():
            return Response(status_code=200)

        @self._app.get("/models")
        async def models():
            return {"object": "list", "data": []}

        @self._app.post("/files")
        async def add_file(request: Request):
            form = await request.form()
            upload = form["file"]
            content = await upload.read()
            await upload.close()
            file_id = str(form["id"])
            metadata: dict[str, Any] = {
                "id": file_id,
                "bytes": len(content),
                "filename": upload.filename,
                "purpose": str(form["purpose"]),
                "media_type": str(form["media_type"]),
                "sensor_name": str(form.get("sensor_name", "")),
            }
            if form.get("creation_time") is not None:
                metadata["creation_time"] = str(form["creation_time"])
            self.assets[file_id] = metadata
            if self.invalid_upload_identity:
                returned = dict(metadata)
                returned["id"] = str(uuid4())
                return returned
            return metadata

        @self._app.get("/files")
        async def list_files(request: Request):
            if request.query_params.get("purpose") != "vision":
                return JSONResponse(status_code=400, content={"code": "BadPurpose"})
            return {"object": "list", "data": list(self.assets.values())}

        @self._app.get("/files/{file_id}")
        async def file_info(file_id: str):
            value = self.assets.get(file_id)
            if value is None:
                return JSONResponse(
                    status_code=404,
                    content={"code": "NotFound", "message": "asset missing"},
                )
            return value

        @self._app.delete("/files/{file_id}")
        async def delete_file(file_id: str):
            self.delete_calls.append(file_id)
            self.assets.pop(file_id, None)
            return {"id": file_id, "object": "file", "deleted": True}


def _expect_value_error(awaitable, fragment: str) -> None:
    try:
        asyncio.run(awaitable)
    except ValueError as exc:
        if fragment not in str(exc):
            raise QualificationError(
                f"expected error containing {fragment!r}, got {str(exc)!r}"
            ) from exc
    else:
        raise QualificationError(f"expected ValueError containing {fragment!r}")


@contextmanager
def _deny_external_execution() -> Iterator[None]:
    def denied(*_args: Any, **_kwargs: Any):
        raise QualificationError("external execution path is prohibited")

    with (
        mock.patch.object(socket, "create_connection", denied),
        mock.patch.object(socket.socket, "connect", denied),
        mock.patch.object(socket.socket, "connect_ex", denied),
        mock.patch.object(socket.socket, "bind", denied),
        mock.patch.object(socket.socket, "listen", denied),
        mock.patch.object(socket.socket, "accept", denied),
        mock.patch.object(socket.socket, "sendto", denied),
        mock.patch.object(subprocess, "Popen", denied),
        mock.patch.object(subprocess, "run", denied),
        mock.patch.object(subprocess, "check_call", denied),
        mock.patch.object(subprocess, "check_output", denied),
        mock.patch.object(os, "system", denied),
        mock.patch.object(os, "popen", denied),
    ):
        yield


def _run_semantic_probe(inventory: dict[str, Any]) -> dict[str, Any]:
    module = _load_production_module()
    fixture = inventory["fixture"]
    fixture_bytes = fixture["content_utf8"].encode("utf-8")
    temporary_path: Path | None = None

    with tempfile.TemporaryDirectory(prefix="vss-wave8-lvs-") as temporary:
        temporary_path = Path(temporary)
        if stat.S_IMODE(temporary_path.stat().st_mode) != 0o700:
            raise QualificationError("private temporary directory is not mode 0700")
        media = temporary_path / fixture["filename"]
        media.write_bytes(fixture_bytes)
        symlink = temporary_path / "escape.mp4"
        symlink.symlink_to(media)
        directory = temporary_path / "nested"
        directory.mkdir(mode=0o700)
        directory_symlink = temporary_path / "linked-dir"
        directory_symlink.symlink_to(directory, target_is_directory=True)
        (directory / "nested.mp4").write_bytes(fixture_bytes)

        environment = {
            "LVS_MCP_MEDIA_ROOT": str(temporary_path),
            "LVS_MCP_MAX_FILE_BYTES": str(fixture["max_bytes"]),
        }
        with (
            mock.patch.dict(os.environ, environment, clear=False),
            _deny_external_execution(),
        ):
            backend = _FakeLvsBackend()
            server = module.LvsMCPServer(backend)
            tools = asyncio.run(server._list_tools_handler())
            tool_names = tuple(sorted(tool.name for tool in tools))
            if tool_names != EXPECTED_TOOLS or len({tool.name for tool in tools}) != 13:
                raise QualificationError("production 13-tool registration drift")
            file_schemas = {
                tool.name: tool.inputSchema
                for tool in tools
                if tool.name
                in {"add_file", "list_files", "get_file_info", "delete_file"}
            }
            if set(file_schemas) != {
                "add_file",
                "list_files",
                "get_file_info",
                "delete_file",
            } or any(
                schema.get("additionalProperties") is not False
                for schema in file_schemas.values()
            ):
                raise QualificationError("file-tool fail-closed schemas drift")

            if asyncio.run(server._handle_tool_call("health_ready", {})) != {
                "status": "ready",
                "code": 200,
            }:
                raise QualificationError("readiness dispatch mismatch")
            if asyncio.run(server._handle_tool_call("health_live", {})) != {
                "status": "alive",
                "code": 200,
            }:
                raise QualificationError("liveness dispatch mismatch")
            backend.ready_error = True
            _expect_value_error(
                server._handle_tool_call("health_ready", {}),
                "deterministic readiness failure",
            )
            backend.ready_error = False

            creation_time = "2026-08-01T12:00:00.000Z"
            added = asyncio.run(
                server._handle_tool_call(
                    "add_file",
                    {
                        "path": fixture["filename"],
                        "creation_time": creation_time,
                        "sensor_name": "wave8-sensor",
                    },
                )
            )
            file_id = added["id"]
            if (
                added.get("bytes") != len(fixture_bytes)
                or added.get("filename") != fixture["filename"]
                or added.get("purpose") != "vision"
                or added.get("media_type") != "video"
                or added.get("creation_time") != creation_time
                or added.get("sensor_name") != "wave8-sensor"
            ):
                raise QualificationError("file add semantic mismatch")
            listing = asyncio.run(server._handle_tool_call("list_files", {}))
            if listing != {"object": "list", "data": [added]}:
                raise QualificationError("file listing semantic mismatch")
            info = asyncio.run(
                server._handle_tool_call("get_file_info", {"file_id": file_id})
            )
            if info != added:
                raise QualificationError("file info semantic mismatch")
            confirmation = asyncio.run(
                server._handle_tool_call(
                    "delete_file",
                    {"file_id": file_id, "confirm_file_id": file_id},
                )
            )
            if confirmation != {"id": file_id, "object": "file", "deleted": True}:
                raise QualificationError("file deletion confirmation mismatch")
            if backend.assets:
                raise QualificationError("file deletion did not remove the fake asset")

            for path_value, error in (
                ("", "non-empty string"),
                (str(media), "normalized relative path"),
                ("../wave8-fixture.mp4", "normalized relative path"),
                (symlink.name, "symlink components"),
                ("linked-dir/nested.mp4", "symlink components"),
                ("missing.mp4", "existing file"),
            ):
                _expect_value_error(
                    server._handle_tool_call("add_file", {"path": path_value}), error
                )
            with mock.patch.dict(os.environ, {"LVS_MCP_MAX_FILE_BYTES": "4"}):
                _expect_value_error(
                    server._handle_tool_call("add_file", {"path": fixture["filename"]}),
                    "exceeds LVS_MCP_MAX_FILE_BYTES",
                )
            _expect_value_error(
                server._handle_tool_call(
                    "get_file_info",
                    {"file_id": "00000000-0000-0000-0000-000000000000"},
                ),
                "non-nil UUID",
            )
            first = str(uuid4())
            second = str(uuid4())
            _expect_value_error(
                server._handle_tool_call(
                    "delete_file",
                    {"file_id": first, "confirm_file_id": second},
                ),
                "exactly match",
            )
            _expect_value_error(
                server._handle_tool_call("list_files", {"unexpected": "rejected"}),
                "unsupported arguments",
            )

            sanitized = asyncio.run(
                server._invoke_call_tool(
                    "get_file_info", {"file_id": "/sensitive/operator/path"}
                )
            )
            sanitized_payload = json.loads(sanitized[0].text)
            if sanitized_payload != {
                "error": "get_file_info failed; see the LVS service log for details"
            }:
                raise QualificationError("file-tool error sanitization mismatch")

            backend.invalid_upload_identity = True
            deletes_before = len(backend.delete_calls)
            _expect_value_error(
                server._handle_tool_call("add_file", {"path": fixture["filename"]}),
                "unexpected asset identity",
            )
            backend.invalid_upload_identity = False
            if len(backend.delete_calls) != deletes_before + 1 or backend.assets:
                raise QualificationError("invalid upload metadata did not roll back")

    if temporary_path is None or temporary_path.exists():
        raise QualificationError("executor-owned temporary files were not cleaned")
    return {
        "production_module_imported": True,
        "registered_tool_count": 13,
        "registered_tools": list(EXPECTED_TOOLS),
        "fixture_sha256": fixture["sha256"],
        "operations": list(EXPECTED_OPERATIONS),
    }


def build_result(selected: str | None = None) -> dict[str, Any]:
    inventory, digests = _load_inventory()
    if selected is not None and selected not in EXPECTED_ENTRIES:
        raise QualificationError(f"unknown Wave 8 entry: {selected}")
    execution = _run_semantic_probe(inventory)
    entries = []
    for case in inventory["cases"]:
        if selected is not None and case["entry_id"] != selected:
            continue
        shared = [
            "production_lvs_mcp_module_imported",
            "exact_13_tool_registration_executed",
            "in_process_asgi_health_dispatch_executed",
            "external_execution_guards_active",
        ]
        if case["adapter_id"] == "lvs_tool_dispatch_and_file_lifecycle":
            shared.extend(
                [
                    "bounded_file_add_list_info_delete_executed",
                    "path_size_symlink_uuid_rejections_executed",
                    "invalid_metadata_rollback_executed",
                    "file_error_sanitization_executed",
                ]
            )
        else:
            shared.append("shared_server_dispatch_subset_executed")
        entries.append(
            {
                "entry_id": case["entry_id"],
                "candidate_state": "candidate_executable_subset_non_advancing",
                "evidence_scope": case["evidence_scope"],
                "retained_blockers": case["retained_blockers"],
                "matched_assertions": shared,
            }
        )
    result = {
        "schema_version": 1,
        "mode": "candidate_executable_subset_non_advancing",
        "outcome": "observed_match_candidate_only",
        "official_capability_effect": "none_candidate_only",
        "runtime_evidence": [],
        "entries": entries,
        "execution": execution,
        "safety": {
            "network_used": False,
            "socket_used": False,
            "subprocess_used": False,
            "docker_used": False,
            "service_lifecycle_used": False,
            "downloads_used": False,
            "credentials_used": False,
            "caller_supplied_callback_used": False,
            "warehouse_sample_used": False,
            "temporary_files_cleaned": True,
            "live_sse_connection": False,
            "mcp_transport_handshake": False,
            "deployed_lvs": False,
            "vlm_inference": False,
            "thor_runtime_readiness": False,
        },
        "source_digests": dict(sorted(digests.items())),
    }
    if selected is None:
        _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    else:
        # The checked schema fixes the complete two-entry receipt. A selected run is
        # intentionally human-facing and retains every safety/source check.
        if len(result["entries"]) != 1:
            raise QualificationError("selected result cardinality drift")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="execute both exact candidates"
    )
    parser.add_argument(
        "--list", action="store_true", help="list exact supported entries"
    )
    parser.add_argument("--case", choices=EXPECTED_ENTRIES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print("\n".join(EXPECTED_ENTRIES))
        return 0
    try:
        result = build_result(args.case)
    except QualificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
