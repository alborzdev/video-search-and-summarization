#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Explicit Phase-1 executor for the owned RTVI file-lifecycle canary."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

import acceptance


sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PHASE1_INVENTORY = SCRIPT_DIR / "acceptance_phase1_inventory.json"
MAX_LEDGER_V2_BYTES = 8 * 1024 * 1024
MAX_LEDGER_V2_RECORD_BYTES = 16 * 1024
CLIENT_UUID_NAMESPACE = uuid.UUID("d988a84a-81f4-4d32-a3d1-d26f1fc63682")
LEDGER_V2_EVENTS = {
    "cleanup-failed",
    "cleanup-started",
    "cleanup-succeeded",
    "create-confirmed",
    "create-intent",
    "run-finished",
    "run-started",
}


class ExecutionError(RuntimeError):
    """Fail-closed execution error carrying only a stable public code."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if code
            in {
                "approval_required",
                "configuration_error",
                "content_mismatch",
                "fixture_error",
                "http_error",
                "invalid_json",
                "invalid_response",
                "ledger_error",
                "preexisting_resource",
                "response_too_large",
                "timeout",
                "transport_error",
            }
            else "invalid_response"
        )
        super().__init__(self.code)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _phase1_source_sha(spec: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(spec)).hexdigest()


def _resource_uuid(run_id: str, scenario_id: str, resource_id: str) -> str:
    return str(
        uuid.uuid5(CLIENT_UUID_NAMESPACE, f"{run_id}:{scenario_id}:{resource_id}")
    )


def _target_sha(target: str) -> str:
    return hashlib.sha256(target.encode()).hexdigest()


def _load_phase1(path: Path) -> dict[str, Any]:
    spec = acceptance.load_json(path)
    scenario = spec.get("scenario")
    if (
        spec.get("schema_version") != 1
        or spec.get("mode") != "explicit-stateful-canary"
        or spec.get("default_execution_enabled") is not False
        or not isinstance(scenario, dict)
        or scenario.get("id") != "rtvi-file-lifecycle"
    ):
        raise ExecutionError("configuration_error")
    policy = scenario.get("policy")
    if policy != {
        "approval_token": "rtvi-file-lifecycle",
        "client_addressed_ids": True,
        "concurrency": 1,
        "cleanup": "strict-lifo-stop-on-top-failure",
        "follow_redirects": False,
        "loopback_only": True,
        "max_request_bytes": 2097152,
        "max_response_bytes": 1048576,
        "proxies": False,
    }:
        raise ExecutionError("configuration_error")
    services = scenario.get("services")
    if not isinstance(services, list) or [item.get("id") for item in services] != [
        "rt-vlm",
        "rt-embed",
    ]:
        raise ExecutionError("configuration_error")

    api_inventory = acceptance.load_json(acceptance.DEFAULT_API_INVENTORY)
    runtime_inventory = acceptance.load_json(acceptance.DEFAULT_RUNTIME_INVENTORY)
    bindings = acceptance._build_operation_bindings(
        api_inventory, runtime_inventory, acceptance.DEFAULT_EXPECTED_DIR
    )
    expected = {
        "create": ("POST", "/v1/files"),
        "inspect": ("GET", "/v1/files/{file_id}"),
        "content": ("GET", "/v1/files/{file_id}/content"),
        "delete": ("DELETE", "/v1/files/{file_id}"),
    }
    seen_resources: set[str] = set()
    for service in services:
        if not isinstance(service, dict) or set(service) != {
            "default_origin",
            "id",
            "operations",
            "resource_id",
        }:
            raise ExecutionError("configuration_error")
        acceptance.validate_origin(service.get("default_origin"))
        resource_id = service.get("resource_id")
        if (
            not isinstance(resource_id, str)
            or not acceptance.PLAIN_ID_RE.fullmatch(resource_id)
            or resource_id in seen_resources
        ):
            raise ExecutionError("configuration_error")
        seen_resources.add(resource_id)
        operations = service.get("operations")
        if not isinstance(operations, dict) or set(operations) != set(expected):
            raise ExecutionError("configuration_error")
        for role, method_path in expected.items():
            operation_ref = operations.get(role)
            if (
                not isinstance(operation_ref, str)
                or bindings.get(operation_ref) != method_path
            ):
                raise ExecutionError("configuration_error")
            if not operation_ref.startswith(f"rest:{service['id']}:"):
                raise ExecutionError("configuration_error")
    return spec


def _private_directory(path: Path) -> Path:
    path = Path(path)
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise ExecutionError("configuration_error") from exc
    if (
        resolved != path.absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise ExecutionError("configuration_error")
    return resolved


def _atomic_private_json(path: Path, value: dict[str, Any]) -> None:
    parent = _private_directory(path.parent)
    temporary = parent / f".{path.name}.tmp-{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            body = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
            offset = 0
            while offset < len(body):
                written = os.write(descriptor, body[offset:])
                if written <= 0:
                    raise ExecutionError("configuration_error")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except OSError as exc:
            raise ExecutionError("configuration_error") from exc
        temporary.unlink()
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _ledger_record_template(
    *,
    run_id: str,
    namespace: str,
    scenario_sha256: str,
    source_fingerprint: str,
    execution_fingerprint: str,
    event: str,
    action_id: str,
    resource_id: str = "run",
    target_sha256: str = "0" * 64,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "event": event,
        "execution_fingerprint": execution_fingerprint,
        "namespace": namespace,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resource_id": resource_id,
        "run_id": run_id,
        "scenario_id": "rtvi-file-lifecycle",
        "scenario_sha256": scenario_sha256,
        "schema_version": 2,
        "source_fingerprint": source_fingerprint,
        "target_sha256": target_sha256,
    }


def _validate_ledger_v2(
    raw: bytes,
    *,
    spec: dict[str, Any],
    run_id: str,
    namespace: str,
    source_fingerprint: str,
    execution_fingerprint: str,
) -> dict[str, Any]:
    if len(raw) > MAX_LEDGER_V2_BYTES:
        raise ExecutionError("ledger_error")
    scenario = spec["scenario"]
    scenario_sha = _phase1_source_sha(spec)
    services = scenario["services"]
    resources = [item["resource_id"] for item in services]
    target_hashes = {
        item["resource_id"]: _target_sha(
            _resource_uuid(run_id, scenario["id"], item["resource_id"])
        )
        for item in services
    }
    if not raw:
        return {
            "active": [],
            "cleanup_started": None,
            "confirmed": set(),
            "finished": False,
            "sequence": 0,
            "sha": "0" * 64,
        }
    if not raw.endswith(b"\n"):
        raise ExecutionError("ledger_error")
    active: list[str] = []
    confirmed: set[str] = set()
    ever_intended: list[str] = []
    cleanup_started: str | None = None
    previous = "0" * 64
    sequence = 0
    finished = False
    for line in raw.splitlines():
        if not line or len(line) > MAX_LEDGER_V2_RECORD_BYTES:
            raise ExecutionError("ledger_error")
        try:
            record = json.loads(
                line, object_pairs_hook=acceptance._reject_duplicate_keys
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise ExecutionError("ledger_error") from exc
        required = {
            "action_id",
            "event",
            "execution_fingerprint",
            "namespace",
            "previous_sha256",
            "record_sha256",
            "recorded_at",
            "resource_id",
            "run_id",
            "scenario_id",
            "scenario_sha256",
            "schema_version",
            "sequence",
            "source_fingerprint",
            "target_sha256",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise ExecutionError("ledger_error")
        unsigned = dict(record)
        digest = unsigned.pop("record_sha256", None)
        if (
            record.get("schema_version") != 2
            or isinstance(record.get("sequence"), bool)
            or record.get("sequence") != sequence + 1
            or record.get("previous_sha256") != previous
            or not isinstance(digest, str)
            or not acceptance.SHA256_RE.fullmatch(digest)
            or hashlib.sha256(_canonical(unsigned)).hexdigest() != digest
            or record.get("run_id") != run_id
            or record.get("namespace") != namespace
            or record.get("scenario_id") != scenario["id"]
            or record.get("scenario_sha256") != scenario_sha
            or record.get("source_fingerprint") != source_fingerprint
            or record.get("execution_fingerprint") != execution_fingerprint
            or not acceptance.SHA256_RE.fullmatch(str(record.get("target_sha256", "")))
            or not acceptance.UTC_RE.fullmatch(str(record.get("recorded_at", "")))
            or record.get("event") not in LEDGER_V2_EVENTS
            or finished
        ):
            raise ExecutionError("ledger_error")
        event = record["event"]
        resource = record["resource_id"]
        target = record["target_sha256"]
        if sequence == 0:
            if (
                event != "run-started"
                or record.get("action_id") != "begin-run"
                or resource != "run"
                or target != "0" * 64
            ):
                raise ExecutionError("ledger_error")
        elif event == "run-started":
            raise ExecutionError("ledger_error")
        elif event == "run-finished":
            if (
                active
                or cleanup_started is not None
                or record.get("action_id") != "finish-run"
                or resource != "run"
                or target != "0" * 64
            ):
                raise ExecutionError("ledger_error")
            finished = True
        else:
            if resource not in target_hashes or target != target_hashes[resource]:
                raise ExecutionError("ledger_error")
            create_action = f"{services[resources.index(resource)]['id']}-upload-file"
            cleanup_action = f"{services[resources.index(resource)]['id']}-delete-file"
            if event == "create-intent":
                if (
                    record["action_id"] != create_action
                    or resource in ever_intended
                    or len(ever_intended) >= len(resources)
                    or resources[len(ever_intended)] != resource
                    or cleanup_started is not None
                ):
                    raise ExecutionError("ledger_error")
                ever_intended.append(resource)
                active.append(resource)
            elif event == "create-confirmed":
                if (
                    record["action_id"] != create_action
                    or resource not in active
                    or resource in confirmed
                ):
                    raise ExecutionError("ledger_error")
                confirmed.add(resource)
            elif event == "cleanup-started":
                if (
                    record["action_id"] != cleanup_action
                    or not active
                    or active[-1] != resource
                    or cleanup_started is not None
                ):
                    raise ExecutionError("ledger_error")
                cleanup_started = resource
            elif event == "cleanup-failed":
                if record["action_id"] != cleanup_action or cleanup_started != resource:
                    raise ExecutionError("ledger_error")
                cleanup_started = None
            elif event == "cleanup-succeeded":
                if record["action_id"] != cleanup_action or cleanup_started != resource:
                    raise ExecutionError("ledger_error")
                cleanup_started = None
                active.pop()
                confirmed.discard(resource)
        previous = digest
        sequence += 1
    return {
        "active": active,
        "cleanup_started": cleanup_started,
        "confirmed": confirmed,
        "finished": finished,
        "sequence": sequence,
        "sha": previous,
    }


def _append_ledger_v2(
    path: Path,
    record: dict[str, Any],
    *,
    spec: dict[str, Any],
    run_id: str,
    namespace: str,
    source_fingerprint: str,
    execution_fingerprint: str,
) -> dict[str, Any]:
    parent = _private_directory(path.parent)
    flags = (
        os.O_RDWR
        | os.O_APPEND
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    created = False
    try:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutionError("ledger_error") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_size > MAX_LEDGER_V2_BYTES
        ):
            raise ExecutionError("ledger_error")
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = b""
        while len(raw) < metadata.st_size:
            chunk = os.read(descriptor, min(65536, metadata.st_size - len(raw)))
            if not chunk:
                raise ExecutionError("ledger_error")
            raw += chunk
        state = _validate_ledger_v2(
            raw,
            spec=spec,
            run_id=run_id,
            namespace=namespace,
            source_fingerprint=source_fingerprint,
            execution_fingerprint=execution_fingerprint,
        )
        record = dict(record)
        record["sequence"] = state["sequence"] + 1
        record["previous_sha256"] = state["sha"]
        record["record_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
        line = _canonical(record) + b"\n"
        if len(line) > MAX_LEDGER_V2_RECORD_BYTES:
            raise ExecutionError("ledger_error")
        _validate_ledger_v2(
            raw + line,
            spec=spec,
            run_id=run_id,
            namespace=namespace,
            source_fingerprint=source_fingerprint,
            execution_fingerprint=execution_fingerprint,
        )
        offset = 0
        while offset < len(line):
            written = os.write(descriptor, line[offset:])
            if written <= 0:
                raise ExecutionError("ledger_error")
            offset += written
        os.fsync(descriptor)
        if created:
            directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return record
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


class LoopbackHTTP:
    def __init__(self, origin: str, *, timeout: float, max_response_bytes: int) -> None:
        self.origin = acceptance.validate_origin(origin)
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.opener = acceptance.build_safe_opener()

    def request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str, bytes]:
        if not isinstance(path, str) or not acceptance.SAFE_PATH_RE.fullmatch(path):
            raise ExecutionError("configuration_error")
        request = Request(
            f"{self.origin}{path}",
            data=data,
            headers={"User-Agent": "vss-thor-acceptance-phase1/1", **(headers or {})},
            method=method,
        )
        response: Any = None
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                if 300 <= exc.code < 400:
                    raise ExecutionError("transport_error") from exc
                response = exc
            body = acceptance.read_bounded(response, self.max_response_bytes)
            return (
                int(response.status),
                response.headers.get_content_type().lower(),
                body,
            )
        except ExecutionError:
            raise
        except acceptance.ResponseBoundError as exc:
            raise ExecutionError("response_too_large") from exc
        except (TimeoutError, OSError, URLError) as exc:
            raise ExecutionError(
                "timeout" if isinstance(exc, TimeoutError) else "transport_error"
            ) from exc
        finally:
            if response is not None:
                response.close()


def _multipart(
    *,
    fixture: bytes,
    filename: str,
    file_id: str,
    sensor_name: str,
    boundary: str,
    maximum: int,
) -> tuple[bytes, str]:
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": file_id,
        "sensor_name": sensor_name,
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    )
    chunks.extend((fixture, b"\r\n", f"--{boundary}--\r\n".encode()))
    body = b"".join(chunks)
    if len(body) > maximum:
        raise ExecutionError("configuration_error")
    return body, f"multipart/form-data; boundary={boundary}"


def _json_object(body: bytes, media_type: str) -> dict[str, Any]:
    if media_type != "application/json":
        raise ExecutionError("invalid_response")
    try:
        value = json.loads(body, object_pairs_hook=acceptance._reject_duplicate_keys)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        acceptance.AcceptanceConfigError,
    ) as exc:
        raise ExecutionError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ExecutionError("invalid_response")
    return value


def _action_record(
    *,
    action_id: str,
    service: str,
    started: float,
    status: str,
    http_status: int | None = None,
    body: bytes | None = None,
    oracle: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "action_id": action_id,
        "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
        "service": service,
        "status": status,
    }
    if http_status is not None:
        record["http_status"] = http_status
    if body is not None:
        record["response_bytes"] = len(body)
        record["response_sha256"] = hashlib.sha256(body).hexdigest()
    if oracle is not None:
        record["oracle"] = oracle
    if error is not None:
        record["error"] = error
    return record


def _materialize_fixture(
    fixture_catalog: dict[str, Any],
    fixture_id: str,
    evidence_dir: Path,
    run_id: str,
) -> tuple[Path, bytes, dict[str, Any]]:
    fixtures = acceptance.validate_fixture_catalog(fixture_catalog)
    fixture = fixtures.get(fixture_id)
    if fixture is None:
        raise ExecutionError("fixture_error")
    body = base64.b64decode(fixture["content_base64"], validate=True)
    directory = evidence_dir / f"{run_id}-fixtures"
    try:
        os.mkdir(directory, 0o700)
        path = directory / fixture["file_name"]
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            offset = 0
            while offset < len(body):
                written = os.write(descriptor, body[offset:])
                if written <= 0:
                    raise ExecutionError("fixture_error")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture["sha256"]:
            raise ExecutionError("fixture_error")
        completed = subprocess.run(
            [
                "/usr/bin/ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                "--",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
        if completed.returncode != 0 or len(completed.stdout) > 1024 * 1024:
            raise ExecutionError("fixture_error")
        probe = json.loads(completed.stdout)
        streams = probe.get("streams") if isinstance(probe, dict) else None
        expected_streams = fixture["ffprobe_oracle"]["streams"]
        if not isinstance(streams, list) or [
            item.get("codec_name") for item in streams
        ] != [item["codec_name"] for item in expected_streams]:
            raise ExecutionError("fixture_error")
        return path, body, fixture
    except BaseException:
        try:
            path.unlink()
        except (FileNotFoundError, UnboundLocalError):
            pass
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


class CanaryRunner:
    def __init__(
        self,
        *,
        spec: dict[str, Any],
        run_id: str,
        source_fingerprint: str,
        evidence_dir: Path,
        endpoints: dict[str, str],
        timeout: float,
    ) -> None:
        self.spec = spec
        self.run_id = run_id
        self.namespace = acceptance.build_namespace(run_id)
        self.source_fingerprint = source_fingerprint
        self.scenario_sha = _phase1_source_sha(spec)
        self.evidence_dir = evidence_dir
        self.ledger_path = evidence_dir / f"{run_id}-ledger-v2.jsonl"
        self.services = spec["scenario"]["services"]
        self.clients = {
            item["id"]: LoopbackHTTP(
                endpoints.get(item["id"], item["default_origin"]),
                timeout=timeout,
                max_response_bytes=spec["scenario"]["policy"]["max_response_bytes"],
            )
            for item in self.services
        }
        self.execution_fingerprint = hashlib.sha256(
            _canonical(
                {
                    "scenario_sha256": self.scenario_sha,
                    "service_origins": {
                        service_id: client.origin
                        for service_id, client in sorted(self.clients.items())
                    },
                    "source_fingerprint": self.source_fingerprint,
                }
            )
        ).hexdigest()
        self.actions: list[dict[str, Any]] = []

    def ledger(
        self, event: str, action_id: str, service: dict[str, Any] | None = None
    ) -> None:
        resource_id = service["resource_id"] if service else "run"
        target = (
            _target_sha(
                _resource_uuid(self.run_id, self.spec["scenario"]["id"], resource_id)
            )
            if service
            else "0" * 64
        )
        record = _ledger_record_template(
            run_id=self.run_id,
            namespace=self.namespace,
            scenario_sha256=self.scenario_sha,
            source_fingerprint=self.source_fingerprint,
            execution_fingerprint=self.execution_fingerprint,
            event=event,
            action_id=action_id,
            resource_id=resource_id,
            target_sha256=target,
        )
        _append_ledger_v2(
            self.ledger_path,
            record,
            spec=self.spec,
            run_id=self.run_id,
            namespace=self.namespace,
            source_fingerprint=self.source_fingerprint,
            execution_fingerprint=self.execution_fingerprint,
        )

    def _absence(self, service: dict[str, Any], file_id: str, action_id: str) -> None:
        started = time.monotonic()
        status: int | None = None
        body: bytes | None = None
        try:
            status, _, body = self.clients[service["id"]].request(
                "GET", f"/v1/files/{quote(file_id, safe='')}"
            )
            if status not in {400, 404}:
                raise ExecutionError("preexisting_resource")
        except ExecutionError as exc:
            self.actions.append(
                _action_record(
                    action_id=action_id,
                    service=service["id"],
                    started=started,
                    status="fail",
                    http_status=status,
                    body=body,
                    error=exc.code,
                )
            )
            raise
        self.actions.append(
            _action_record(
                action_id=action_id,
                service=service["id"],
                started=started,
                status="pass",
                http_status=status,
                body=body,
                oracle="exact-id-absent",
            )
        )

    def create_and_verify(
        self, service: dict[str, Any], fixture: bytes, fixture_meta: dict[str, Any]
    ) -> None:
        service_id = service["id"]
        resource_id = service["resource_id"]
        file_id = _resource_uuid(self.run_id, self.spec["scenario"]["id"], resource_id)
        sensor_name = f"{self.namespace}-{resource_id}"
        filename = f"{self.namespace}-{service_id}.mp4"
        self._absence(service, file_id, f"{service_id}-preflight-absence")
        self.ledger("create-intent", f"{service_id}-upload-file", service)
        boundary = (
            "vss-accept-"
            + hashlib.sha256(f"{self.run_id}:{service_id}".encode()).hexdigest()[:24]
        )
        request_body, content_type = _multipart(
            fixture=fixture,
            filename=filename,
            file_id=file_id,
            sensor_name=sensor_name,
            boundary=boundary,
            maximum=self.spec["scenario"]["policy"]["max_request_bytes"],
        )
        started = time.monotonic()
        status: int | None = None
        body: bytes | None = None
        try:
            status, media_type, body = self.clients[service_id].request(
                "POST",
                "/v1/files",
                data=request_body,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(request_body)),
                },
            )
            response = _json_object(body, media_type)
            if status not in {200, 201} or any(
                (
                    response.get("id") != file_id,
                    response.get("bytes") != fixture_meta["byte_length"],
                    response.get("filename") != filename,
                    response.get("purpose") != "vision",
                    response.get("media_type") != "video",
                    response.get("sensor_name") != sensor_name,
                )
            ):
                raise ExecutionError("invalid_response")
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-upload-file",
                    service=service_id,
                    started=started,
                    status="pass",
                    http_status=status,
                    body=body,
                    oracle="client-id-and-owned-fields-echoed",
                )
            )
            self.ledger("create-confirmed", f"{service_id}-upload-file", service)
        except ExecutionError as exc:
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-upload-file",
                    service=service_id,
                    started=started,
                    status="fail",
                    http_status=status,
                    body=body,
                    error=exc.code,
                )
            )
            raise

        started = time.monotonic()
        try:
            status, media_type, body = self.clients[service_id].request(
                "GET", f"/v1/files/{quote(file_id, safe='')}"
            )
            response = _json_object(body, media_type)
            if (
                status != 200
                or response.get("id") != file_id
                or response.get("sensor_name") != sensor_name
            ):
                raise ExecutionError("invalid_response")
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-inspect-file",
                    service=service_id,
                    started=started,
                    status="pass",
                    http_status=status,
                    body=body,
                    oracle="exact-owned-file-visible",
                )
            )
        except ExecutionError as exc:
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-inspect-file",
                    service=service_id,
                    started=started,
                    status="fail",
                    error=exc.code,
                )
            )
            raise

        started = time.monotonic()
        try:
            status, _, body = self.clients[service_id].request(
                "GET", f"/v1/files/{quote(file_id, safe='')}/content"
            )
            if (
                status != 200
                or hashlib.sha256(body).hexdigest() != fixture_meta["sha256"]
            ):
                raise ExecutionError("content_mismatch")
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-download-file",
                    service=service_id,
                    started=started,
                    status="pass",
                    http_status=status,
                    body=body,
                    oracle="fixture-sha256-matches",
                )
            )
        except ExecutionError as exc:
            self.actions.append(
                _action_record(
                    action_id=f"{service_id}-download-file",
                    service=service_id,
                    started=started,
                    status="fail",
                    error=exc.code,
                )
            )
            raise

    def cleanup_one(
        self, service: dict[str, Any], *, resume_started: bool = False
    ) -> bool:
        service_id = service["id"]
        file_id = _resource_uuid(
            self.run_id, self.spec["scenario"]["id"], service["resource_id"]
        )
        action_id = f"{service_id}-delete-file"
        if not resume_started:
            self.ledger("cleanup-started", action_id, service)
        started = time.monotonic()
        try:
            status, media_type, body = self.clients[service_id].request(
                "DELETE", f"/v1/files/{quote(file_id, safe='')}"
            )
            if status in {200, 204}:
                if body:
                    response = _json_object(body, media_type)
                    if (
                        response.get("id") != file_id
                        or response.get("deleted") is not True
                    ):
                        raise ExecutionError("invalid_response")
            elif status not in {400, 404}:
                raise ExecutionError("http_error")
            absence_status, _, absence_body = self.clients[service_id].request(
                "GET", f"/v1/files/{quote(file_id, safe='')}"
            )
            if absence_status not in {400, 404}:
                raise ExecutionError("invalid_response")
            self.actions.append(
                _action_record(
                    action_id=action_id,
                    service=service_id,
                    started=started,
                    status="pass",
                    http_status=status,
                    body=body,
                    oracle="exact-id-deleted-and-absent",
                )
            )
            self.ledger("cleanup-succeeded", action_id, service)
            return True
        except ExecutionError as exc:
            self.actions.append(
                _action_record(
                    action_id=action_id,
                    service=service_id,
                    started=started,
                    status="fail",
                    error=exc.code,
                )
            )
            self.ledger("cleanup-failed", action_id, service)
            return False

    def ledger_state(self) -> dict[str, Any]:
        raw = self.ledger_path.read_bytes() if self.ledger_path.exists() else b""
        return _validate_ledger_v2(
            raw,
            spec=self.spec,
            run_id=self.run_id,
            namespace=self.namespace,
            source_fingerprint=self.source_fingerprint,
            execution_fingerprint=self.execution_fingerprint,
        )

    def active_services(self) -> list[dict[str, Any]]:
        state = self.ledger_state()
        by_resource = {item["resource_id"]: item for item in self.services}
        return [by_resource[item] for item in state["active"]]

    def cleanup(self) -> bool:
        while True:
            state = self.ledger_state()
            active_resources = state["active"]
            if not active_resources:
                return True
            by_resource = {item["resource_id"]: item for item in self.services}
            top_resource = active_resources[-1]
            cleanup_started = state["cleanup_started"]
            if cleanup_started not in {None, top_resource}:
                raise ExecutionError("ledger_error")
            if not self.cleanup_one(
                by_resource[top_resource],
                resume_started=cleanup_started == top_resource,
            ):
                return False


def _endpoint_overrides(values: list[str], services: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        service, separator, origin = value.partition("=")
        if not separator or service not in services or service in result:
            raise ExecutionError("configuration_error")
        result[service] = acceptance.validate_origin(origin)
    return result


def _report_path(directory: Path, run_id: str, recovery: bool) -> Path:
    if not recovery:
        return directory / f"{run_id}-report.json"
    for number in range(1, 1000):
        candidate = directory / f"{run_id}-recovery-{number:03d}.json"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ExecutionError("configuration_error")


def _install_interrupt_handler() -> Any:
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    return previous


def _run(args: argparse.Namespace, *, recovery: bool) -> tuple[dict[str, Any], int]:
    spec = _load_phase1(args.phase1_inventory)
    scenario = spec["scenario"]
    if (
        args.scenario != scenario["id"]
        or args.confirm_stateful != scenario["policy"]["approval_token"]
    ):
        raise ExecutionError("approval_required")
    evidence_dir = _private_directory(args.evidence_dir)
    source_fingerprint = acceptance.compile_plan(
        run_id=args.run_id, phase1_inventory_path=args.phase1_inventory
    )["source_fingerprint"]
    if not recovery and args.ack_source_fingerprint != source_fingerprint:
        raise ExecutionError("approval_required")
    if not 0 < args.timeout <= 60:
        raise ExecutionError("configuration_error")
    endpoints = _endpoint_overrides(
        args.endpoint, {item["id"] for item in scenario["services"]}
    )
    runner = CanaryRunner(
        spec=spec,
        run_id=args.run_id,
        source_fingerprint=source_fingerprint,
        evidence_dir=evidence_dir,
        endpoints=endpoints,
        timeout=args.timeout,
    )
    if recovery:
        if not runner.ledger_path.is_file():
            raise ExecutionError("ledger_error")
    elif runner.ledger_path.exists() or runner.ledger_path.is_symlink():
        raise ExecutionError("ledger_error")

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    primary_error: str | None = None
    fixture_path: Path | None = None
    fixture_directory: Path | None = None
    previous_handler = _install_interrupt_handler()
    try:
        if recovery:
            cleanup_ok = runner.cleanup()
        else:
            runner.ledger("run-started", "begin-run")
            fixture_catalog = acceptance.load_json(acceptance.DEFAULT_FIXTURES)
            fixture_path, fixture_body, fixture_meta = _materialize_fixture(
                fixture_catalog, scenario["fixture_id"], evidence_dir, args.run_id
            )
            fixture_directory = fixture_path.parent
            try:
                for service in scenario["services"]:
                    runner.create_and_verify(service, fixture_body, fixture_meta)
            except (ExecutionError, KeyboardInterrupt) as exc:
                primary_error = (
                    exc.code if isinstance(exc, ExecutionError) else "transport_error"
                )
            cleanup_ok = runner.cleanup()
        if cleanup_ok and not runner.active_services():
            state_raw = runner.ledger_path.read_bytes()
            state = _validate_ledger_v2(
                state_raw,
                spec=spec,
                run_id=args.run_id,
                namespace=runner.namespace,
                source_fingerprint=source_fingerprint,
                execution_fingerprint=runner.execution_fingerprint,
            )
            if not state["finished"]:
                runner.ledger("run-finished", "finish-run")
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        if fixture_path is not None:
            try:
                fixture_path.unlink()
            except FileNotFoundError:
                pass
        if fixture_directory is not None:
            try:
                fixture_directory.rmdir()
            except OSError:
                pass

    active = runner.active_services()
    result = "cleanup-incomplete" if active else ("fail" if primary_error else "pass")
    ledger_state = _validate_ledger_v2(
        runner.ledger_path.read_bytes(),
        spec=spec,
        run_id=args.run_id,
        namespace=runner.namespace,
        source_fingerprint=source_fingerprint,
        execution_fingerprint=runner.execution_fingerprint,
    )
    report = {
        "actions": runner.actions,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "execution_opt_in": True,
        "execution_fingerprint": runner.execution_fingerprint,
        "fixture": {
            "id": scenario["fixture_id"],
            "sha256": acceptance.validate_fixture_catalog(
                acceptance.load_json(acceptance.DEFAULT_FIXTURES)
            )[scenario["fixture_id"]]["sha256"],
        },
        "ledger": {
            "final_record_sha256": ledger_state["sha"],
            "schema_version": 2,
            "sequence": ledger_state["sequence"],
        },
        "namespace": runner.namespace,
        "network_scope": "numeric-loopback-only",
        "primary_error": primary_error,
        "recovery": recovery,
        "residual_resource_count": len(active),
        "result": result,
        "run_id": args.run_id,
        "scenario": scenario["id"],
        "scenario_sha256": _phase1_source_sha(spec),
        "schema_version": 1,
        "source_fingerprint": source_fingerprint,
        "started_at": started_at,
        "tier": "stateful-acceptance-phase1",
    }
    _atomic_private_json(_report_path(evidence_dir, args.run_id, recovery), report)
    return report, {"pass": 0, "fail": 1, "cleanup-incomplete": 3}[result]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("execute", "recover"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "--phase1-inventory", type=Path, default=DEFAULT_PHASE1_INVENTORY
        )
        subparser.add_argument("--scenario", required=True)
        subparser.add_argument("--run-id", required=True)
        subparser.add_argument("--confirm-stateful", required=True)
        subparser.add_argument("--evidence-dir", type=Path, required=True)
        subparser.add_argument(
            "--endpoint", action="append", default=[], metavar="SERVICE=ORIGIN"
        )
        subparser.add_argument("--timeout", type=float, default=10.0)
        if command == "execute":
            subparser.add_argument("--ack-source-fingerprint", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        report, status = _run(args, recovery=args.command == "recover")
    except (
        ExecutionError,
        acceptance.AcceptanceConfigError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        code = exc.code if isinstance(exc, ExecutionError) else "configuration_error"
        report = {
            "error": code,
            "execution_opt_in": True,
            "result": "fail",
            "schema_version": 1,
            "tier": "stateful-acceptance-phase1",
        }
        status = 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
