#!/usr/bin/env python3
"""Bounded current-runtime qualification for VSS RT-Embed on Thor."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
ACKNOWLEDGEMENT = "I_ACK_RT_EMBED_CURRENT_RUNTIME_AND_EXACT_REVERSIBLE_CLEANUP"
EXPECTED_CONTRACT_SHA256 = (
    "ff00f1cb91045a9f758c3dc23223fc6bc562b9a1819735e8c97d790c96ca2494"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
MAX_JSON_BYTES = 8 * 1024 * 1024
PAUSED_WORKLOADS = (
    "datasheet-vllm-30",
    "datasheet-embedding",
    "ctai-vision-playground-api",
)


class QualificationError(RuntimeError):
    """Stable, non-sensitive qualifier failure."""

    ALLOWED = {
        "acknowledgement_required",
        "api_contract_failed",
        "artifact_contract_failed",
        "budget_exceeded",
        "cleanup_failed",
        "configuration_error",
        "disk_admission_failed",
        "duplicate_contract_failed",
        "embedding_contract_failed",
        "fixture_contract_failed",
        "helper_contract_failed",
        "http_contract_failed",
        "runtime_identity_failed",
        "runtime_state_changed",
        "source_lock_mismatch",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.ALLOWED else "configuration_error"
        super().__init__(self.code)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
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


def _digest(value: Any) -> str:
    return _sha256(_canonical(value))


def _strict_json(raw: bytes, code: str = "configuration_error") -> Any:
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
        return json.loads(
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


def _read_regular(path: Path, maximum: int = MAX_JSON_BYTES) -> bytes:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise QualificationError("configuration_error")
        if before.st_size < 1 or before.st_size > maximum:
            raise QualificationError("configuration_error")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
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


def _source_path(relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise QualificationError("source_lock_mismatch")
    current = REPO
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError("source_lock_mismatch")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(REPO.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise QualificationError("source_lock_mismatch") from exc
    return resolved


def _load_contract() -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(CONTRACT_PATH)
    if _sha256(raw) != EXPECTED_CONTRACT_SHA256:
        raise QualificationError("configuration_error")
    contract = _strict_json(raw)
    if not isinstance(contract, dict):
        raise QualificationError("configuration_error")
    if (
        contract.get("schema_version") != 1
        or contract.get("tool_id") != "thor-rt-embed-current-runtime"
        or contract.get("acknowledgement") != ACKNOWLEDGEMENT
        or contract.get("default_execution_enabled") is not False
        or contract.get("capability_ids")
        != [
            "model.rt-embed.cosmos-embed1-448p-anomaly",
            "behavior.rt-embed.base64-data-url",
            "behavior.rt-embed.duplicate-id-409",
            "api.core.rt-embed-24",
        ]
    ):
        raise QualificationError("configuration_error")
    bounds = contract.get("execution_bounds")
    if not isinstance(bounds, dict) or bounds != {
        "max_duration_seconds": 900,
        "max_http_requests": 50,
        "max_semantic_actions": 4,
        "max_request_bytes": 4194304,
        "max_response_bytes": 4194304,
        "request_timeout_seconds": 90,
        "min_free_bytes": 10737418240,
        "network_scope": "numeric-loopback-http-and-local-docker-bridge-rtsp-only",
        "external_network": "forbidden",
        "image_pull": "forbidden",
        "image_build": "forbidden",
        "model_staging": "forbidden",
        "service_lifecycle": "forbidden",
        "disposable_helper_containers": 3,
        "warehouse_sample_bundle": "excluded",
    }:
        raise QualificationError("configuration_error")
    anchors = contract.get("source_anchors")
    if not isinstance(anchors, list) or len(anchors) != 9:
        raise QualificationError("source_lock_mismatch")
    seen: set[str] = set()
    for row in anchors:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise QualificationError("source_lock_mismatch")
        path_text = row.get("path")
        byte_count = row.get("bytes")
        expected_sha = row.get("sha256")
        if (
            not isinstance(path_text, str)
            or path_text in seen
            or type(byte_count) is not int
            or byte_count < 1
            or not isinstance(expected_sha, str)
            or SHA256_RE.fullmatch(expected_sha) is None
        ):
            raise QualificationError("source_lock_mismatch")
        seen.add(path_text)
        path = _source_path(path_text)
        actual = _read_regular(path, max(byte_count, MAX_JSON_BYTES))
        if len(actual) != byte_count or _sha256(actual) != expected_sha:
            raise QualificationError("source_lock_mismatch")
    return contract, raw


def _run(
    command: list[str],
    *,
    timeout: float,
    maximum: int = 1024 * 1024,
) -> tuple[int, bytes, bytes]:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("transport_error") from exc
    if len(completed.stdout) > maximum or len(completed.stderr) > maximum:
        raise QualificationError("transport_error")
    return completed.returncode, completed.stdout, completed.stderr


def _docker_object(name: str) -> dict[str, Any] | None:
    code, stdout, _stderr = _run(["docker", "inspect", name], timeout=15)
    if code != 0:
        return None
    value = _strict_json(stdout, "runtime_identity_failed")
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise QualificationError("runtime_identity_failed")
    return value[0]


def _container_projection(name: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    row = _docker_object(name)
    if row is None:
        raise QualificationError("runtime_identity_failed")
    state = row.get("State")
    config = row.get("Config")
    host = row.get("HostConfig")
    mounts = row.get("Mounts")
    network = row.get("NetworkSettings")
    if not all(isinstance(value, dict) for value in (state, config, host, network)):
        raise QualificationError("runtime_identity_failed")
    if not isinstance(mounts, list):
        raise QualificationError("runtime_identity_failed")
    env: dict[str, str] = {}
    for item in config.get("Env", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    safe_env = {
        key: env.get(key)
        for key in (
            "MODEL_PATH",
            "VLM_BATCH_SIZE",
            "RTVI_OFFLINE",
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
        )
    }
    if safe_env != {
        "MODEL_PATH": contract["service"]["model_source"],
        "VLM_BATCH_SIZE": str(contract["service"]["batch_size"]),
        "RTVI_OFFLINE": "true",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }:
        raise QualificationError("runtime_identity_failed")
    credential_names = ("NGC_CLI_API_KEY", "NGC_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN")
    if any(env.get(key, "") != "" for key in credential_names):
        raise QualificationError("runtime_identity_failed")
    mount_projection = sorted(
        (
            {
                "name": item.get("Name"),
                "destination": item.get("Destination"),
                "type": item.get("Type"),
                "rw": item.get("RW"),
            }
            for item in mounts
            if item.get("Destination")
            in {"/opt/nvidia/rtvi/.rtvi/ngc_model_cache", "/tmp/triton_model_repo"}
        ),
        key=lambda item: str(item["destination"]),
    )
    expected_mounts = sorted(
        [
            {
                "name": contract["artifact_contract"]["model"]["volume"],
                "destination": "/opt/nvidia/rtvi/.rtvi/ngc_model_cache",
                "type": "volume",
                "rw": True,
            },
            {
                "name": contract["artifact_contract"]["triton"]["volume"],
                "destination": "/tmp/triton_model_repo",
                "type": "volume",
                "rw": True,
            },
        ],
        key=lambda item: item["destination"],
    )
    if mount_projection != expected_mounts:
        raise QualificationError("runtime_identity_failed")
    health = state.get("Health", {})
    ports = network.get("Ports", {}).get("8000/tcp")
    if ports != [{"HostIp": "127.0.0.1", "HostPort": "8017"}]:
        raise QualificationError("runtime_identity_failed")
    projection = {
        "container": name,
        "image_reference": config.get("Image"),
        "image_id": row.get("Image"),
        "status": state.get("Status"),
        "health": health.get("Status") if isinstance(health, dict) else None,
        "started_at": state.get("StartedAt"),
        "restart_count": row.get("RestartCount"),
        "oom_killed": state.get("OOMKilled"),
        "runtime": host.get("Runtime"),
        "loopback_publish_exact": True,
        "safe_environment": safe_env,
        "credential_values_blank": True,
        "model_mounts": mount_projection,
    }
    if (
        projection["image_reference"] != contract["service"]["image_reference"]
        or projection["image_id"] != contract["service"]["image_id"]
        or projection["status"] != "running"
        or projection["health"] != "healthy"
        or projection["restart_count"] != 0
        or projection["oom_killed"] is not False
    ):
        raise QualificationError("runtime_identity_failed")
    return projection


def _bridge_gateway(container: str) -> tuple[str, str]:
    row = _docker_object(container)
    if row is None:
        raise QualificationError("runtime_identity_failed")
    networks = row.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(networks, dict) or len(networks) != 1:
        raise QualificationError("runtime_identity_failed")
    network_name, membership = next(iter(networks.items()))
    if not isinstance(network_name, str) or not isinstance(membership, dict):
        raise QualificationError("runtime_identity_failed")
    code, stdout, _stderr = _run(
        ["docker", "network", "inspect", network_name], timeout=15
    )
    if code != 0:
        raise QualificationError("runtime_identity_failed")
    value = _strict_json(stdout, "runtime_identity_failed")
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationError("runtime_identity_failed")
    configs = value[0].get("IPAM", {}).get("Config", [])
    if not isinstance(configs, list):
        raise QualificationError("runtime_identity_failed")
    gateways = [row.get("Gateway") for row in configs if isinstance(row, dict)]
    gateways = [value for value in gateways if isinstance(value, str) and value]
    if len(gateways) != 1:
        raise QualificationError("runtime_identity_failed")
    try:
        address = ipaddress.ip_address(gateways[0])
    except ValueError as exc:
        raise QualificationError("runtime_identity_failed") from exc
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise QualificationError("runtime_identity_failed")
    return network_name, str(address)


def _paused_projection() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in PAUSED_WORKLOADS:
        row = _docker_object(name)
        result[name] = (
            "absent" if row is None else str(row.get("State", {}).get("Status"))
        )
    if any(
        value not in {"absent", "exited", "created", "dead"}
        for value in result.values()
    ):
        raise QualificationError("runtime_state_changed")
    return result


def _disk_free(path: Path) -> int:
    try:
        return os.statvfs(path).f_bavail * os.statvfs(path).f_frsize
    except OSError as exc:
        raise QualificationError("disk_admission_failed") from exc


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class Runtime:
    def __init__(self, contract: dict[str, Any], contract_sha: str) -> None:
        self.contract = contract
        self.contract_sha = contract_sha
        self.bounds = contract["execution_bounds"]
        parsed = urlsplit(contract["service"]["origin"])
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 8017
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise QualificationError("configuration_error")
        self.origin = contract["service"]["origin"]
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.observations: list[dict[str, Any]] = []
        self.http_requests = 0
        self.semantic_actions = 0
        self.publisher: subprocess.Popen[bytes] | None = None
        self.sse_connection: http.client.HTTPConnection | None = None
        self.sse_response: http.client.HTTPResponse | None = None
        self.mediamtx_started = False
        self.owned_file_ids: set[str] = set()
        self.owned_stream_ids: set[str] = set()
        self.camera_owned = False
        self.cleanup_failures: list[str] = []
        self.bridge_network = ""
        self.bridge_gateway = ""
        self.multipart_content_type = ""

    def _consume_http_request(self) -> None:
        self.http_requests += 1
        if self.http_requests > self.bounds["max_http_requests"]:
            raise QualificationError("budget_exceeded")

    def _record(
        self,
        *,
        action_id: str,
        method: str,
        operation_path: str,
        status: int,
        response: bytes,
        content_type: str | None,
    ) -> None:
        if len(self.observations) >= self.bounds["max_http_requests"]:
            raise QualificationError("budget_exceeded")
        self.observations.append(
            {
                "order": len(self.observations) + 1,
                "action_id": action_id,
                "method": method,
                "operation_path": operation_path,
                "http_status": status,
                "response_bytes": len(response),
                "response_sha256": _sha256(response),
                "content_type": (content_type or "").split(";", 1)[0],
            }
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        action_id: str,
        operation_path: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float | None = None,
        record: bool = True,
    ) -> tuple[int, bytes, str | None]:
        if body is not None and len(body) > self.bounds["max_request_bytes"]:
            raise QualificationError("budget_exceeded")
        self._consume_http_request()
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(self.origin + path, data=body, method=method, headers=headers)
        status: int
        response_headers: Mapping[str, str]
        try:
            with self.opener.open(
                request, timeout=timeout or self.bounds["request_timeout_seconds"]
            ) as opened:
                status = opened.status
                response_headers = opened.headers
                raw = opened.read(self.bounds["max_response_bytes"] + 1)
        except HTTPError as exc:
            status = exc.code
            response_headers = exc.headers
            raw = exc.read(self.bounds["max_response_bytes"] + 1)
        except (OSError, URLError, TimeoutError) as exc:
            raise QualificationError("transport_error") from exc
        if len(raw) > self.bounds["max_response_bytes"]:
            raise QualificationError("budget_exceeded")
        response_type = response_headers.get("Content-Type")
        if record:
            self._record(
                action_id=action_id,
                method=method,
                operation_path=operation_path or path.split("?", 1)[0],
                status=status,
                response=raw,
                content_type=response_type,
            )
        return status, raw, response_type

    def json_request(
        self,
        method: str,
        path: str,
        *,
        action_id: str,
        operation_path: str | None = None,
        value: Any | None = None,
        timeout: float | None = None,
        record: bool = True,
    ) -> tuple[int, Any]:
        body = None if value is None else _canonical(value)
        status, raw, _content_type = self.request(
            method,
            path,
            action_id=action_id,
            operation_path=operation_path,
            body=body,
            content_type="application/json" if body is not None else None,
            timeout=timeout,
            record=record,
        )
        parsed = None if not raw else _strict_json(raw, "http_contract_failed")
        return status, parsed

    def _helper_absent(self, name: str) -> bool:
        return _docker_object(name) is None

    def verify_artifact(self, key: str, helper_name: str) -> dict[str, Any]:
        artifact_contract = self.contract["artifact_contract"]
        item = artifact_contract[key]
        if not self._helper_absent(helper_name):
            raise QualificationError("helper_contract_failed")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            helper_name,
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--log-driver",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "/bin/tar",
            "--mount",
            f"type=volume,src={item['volume']},dst=/artifact,readonly,volume-nocopy",
            artifact_contract["runtime_helper_image"],
            "-C",
            "/artifact",
            "-cf",
            "-",
            item["archive_root"],
        ]
        verify_command = [
            sys.executable,
            str(_source_path(artifact_contract["verifier_path"])),
            "verify-tar",
            "--lock",
            str(_source_path(artifact_contract["lock_path"])),
            "--artifact",
            item["artifact"],
            "--source-spec",
            artifact_contract["source_spec"],
            "--image",
            artifact_contract["service_image"],
            "--container-path",
            item["container_path"],
            "--batch-size",
            str(self.contract["service"]["batch_size"]),
        ]
        docker_process: subprocess.Popen[bytes] | None = None
        verifier_process: subprocess.Popen[bytes] | None = None
        try:
            docker_process = subprocess.Popen(
                docker_command,
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if docker_process.stdout is None:
                raise QualificationError("artifact_contract_failed")
            verifier_process = subprocess.Popen(
                verify_command,
                cwd=REPO,
                stdin=docker_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            docker_process.stdout.close()
            verifier_stdout, verifier_stderr = verifier_process.communicate(timeout=300)
            docker_stderr = (
                docker_process.stderr.read(1024 * 1024)
                if docker_process.stderr
                else b""
            )
            docker_code = docker_process.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._stop_container(helper_name)
            if verifier_process is not None:
                verifier_process.kill()
            if docker_process is not None:
                docker_process.kill()
            raise QualificationError("artifact_contract_failed") from exc
        expected_stdout = (
            f"[OK] Exact locked artifact verified: {item['artifact']}\n".encode()
        )
        if (
            verifier_process.returncode != 0
            or docker_code != 0
            or verifier_stdout != expected_stdout
            or verifier_stderr
            or docker_stderr
            or not self._helper_absent(helper_name)
        ):
            raise QualificationError("artifact_contract_failed")
        return {
            "artifact": item["artifact"],
            "archive_root": item["archive_root"],
            "file_count": item["file_count"],
            "directory_count": item["directory_count"],
            "bytes": item["bytes"],
            "verifier_stdout_sha256": _sha256(verifier_stdout),
            "exact_locked_tree": True,
            "helper_removed": True,
        }

    def _stop_container(self, name: str) -> None:
        if self._helper_absent(name):
            return
        code, _stdout, _stderr = _run(
            ["docker", "stop", "--time", "5", name], timeout=15
        )
        if code != 0:
            self.cleanup_failures.append("helper_stop_failed")
            return
        for _ in range(50):
            if self._helper_absent(name):
                return
            time.sleep(0.1)
        self.cleanup_failures.append("helper_persisted")

    def start_mediamtx(self) -> dict[str, Any]:
        helper = self.contract["owned_resources"]["mediamtx_container"]
        helper_contract = self.contract["rtsp_helper"]
        if not self._helper_absent(helper):
            raise QualificationError("helper_contract_failed")
        port = self.contract["owned_resources"]["rtsp_port"]
        try:
            probe = socket.create_connection((self.bridge_gateway, port), timeout=0.3)
        except OSError:
            probe = None
        if probe is not None:
            probe.close()
            raise QualificationError("helper_contract_failed")
        command = [
            "docker",
            "run",
            "--rm",
            "--detach",
            "--name",
            helper,
            "--pull",
            "never",
            "--network",
            "host",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "-e",
            f"MTX_RTSPADDRESS={self.bridge_gateway}:{port}",
            "-e",
            "MTX_RTSPTRANSPORTS=tcp",
            "-e",
            "MTX_RTMP=no",
            "-e",
            "MTX_HLS=no",
            "-e",
            "MTX_WEBRTC=no",
            "-e",
            "MTX_SRT=no",
            "-e",
            "MTX_MOQ=no",
            helper_contract["image_reference"],
        ]
        code, stdout, stderr = _run(command, timeout=30)
        if code != 0 or stderr or not stdout.strip():
            raise QualificationError("helper_contract_failed")
        self.mediamtx_started = True
        deadline = time.monotonic() + 15
        row: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            row = _docker_object(helper)
            if row and row.get("State", {}).get("Status") == "running":
                try:
                    probe = socket.create_connection(
                        (self.bridge_gateway, port), timeout=0.5
                    )
                    probe.close()
                    break
                except OSError:
                    pass
            time.sleep(0.2)
        else:
            raise QualificationError("helper_contract_failed")
        assert row is not None
        if (
            row.get("Image") != helper_contract["image_id"]
            or row.get("Config", {}).get("Image") != helper_contract["image_reference"]
            or row.get("HostConfig", {}).get("NetworkMode") != "host"
            or row.get("HostConfig", {}).get("ReadonlyRootfs") is not True
            or row.get("HostConfig", {}).get("CapDrop") != ["ALL"]
        ):
            raise QualificationError("helper_contract_failed")
        return {
            "image_id": helper_contract["image_id"],
            "network_mode": "host",
            "bridge_gateway_only": True,
            "tcp_only": True,
            "read_only_rootfs": True,
            "capabilities_dropped": True,
            "pull_disabled": True,
        }

    def _rtsp_describe(self) -> tuple[int, bytes]:
        port = self.contract["owned_resources"]["rtsp_port"]
        path = self.contract["owned_resources"]["rtsp_path"]
        request = (
            f"DESCRIBE rtsp://{self.bridge_gateway}:{port}/{path} RTSP/1.0\r\n"
            "CSeq: 1\r\nAccept: application/sdp\r\n"
            "User-Agent: thor-vss-rt-embed-qualifier\r\n\r\n"
        ).encode("ascii")
        try:
            with socket.create_connection(
                (self.bridge_gateway, port), timeout=2
            ) as stream:
                stream.settimeout(2)
                stream.sendall(request)
                raw = bytearray()
                while len(raw) < 65536:
                    try:
                        block = stream.recv(4096)
                    except socket.timeout:
                        break
                    if not block:
                        break
                    raw.extend(block)
                    if b"\r\n\r\n" in raw:
                        header, body = bytes(raw).split(b"\r\n\r\n", 1)
                        match = re.search(rb"(?im)^Content-Length:\s*(\d+)\s*$", header)
                        if match is None or len(body) >= int(match.group(1)):
                            break
        except OSError as exc:
            raise QualificationError("transport_error") from exc
        if len(raw) >= 65536:
            raise QualificationError("transport_error")
        first = bytes(raw).split(b"\r\n", 1)[0]
        match = re.fullmatch(rb"RTSP/1\.0\s+(\d{3}).*", first)
        if match is None:
            raise QualificationError("transport_error")
        return int(match.group(1)), bytes(raw)

    def start_publisher(self) -> dict[str, Any]:
        path = self.contract["owned_resources"]["rtsp_path"]
        port = self.contract["owned_resources"]["rtsp_port"]
        status, _raw = self._rtsp_describe()
        if status != 404:
            raise QualificationError("helper_contract_failed")
        fixture = _source_path(self.contract["fixture"]["path"])
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            str(fixture),
            "-an",
            "-c:v",
            "copy",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            f"rtsp://{self.bridge_gateway}:{port}/{path}",
        ]
        try:
            self.publisher = subprocess.Popen(
                command,
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise QualificationError("helper_contract_failed") from exc
        deadline = time.monotonic() + 20
        raw = b""
        while time.monotonic() < deadline:
            if self.publisher.poll() is not None:
                raise QualificationError("helper_contract_failed")
            status, raw = self._rtsp_describe()
            if status == 200:
                break
            time.sleep(0.2)
        else:
            raise QualificationError("helper_contract_failed")
        if b"H264" not in raw.upper() and b"H264" not in raw:
            raise QualificationError("helper_contract_failed")
        return {
            "fixture_sha256": self.contract["fixture"]["sha256"],
            "source_codec": self.contract["fixture"]["codec"],
            "rtsp_describe_status": 200,
            "bridge_gateway_only": True,
            "transport": "tcp",
            "namespace_sha256": _sha256(path.encode("ascii")),
        }

    def stop_publisher(self) -> None:
        if self.publisher is None:
            return
        if self.publisher.poll() is None:
            self.publisher.terminate()
            try:
                self.publisher.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.publisher.kill()
                self.publisher.wait(timeout=5)
        self.publisher = None

    def stop_mediamtx(self) -> None:
        helper = self.contract["owned_resources"]["mediamtx_container"]
        if self.mediamtx_started or not self._helper_absent(helper):
            self._stop_container(helper)
        self.mediamtx_started = False

    def cleanup_resources(self) -> None:
        resources = self.contract["owned_resources"]
        for stream_id in sorted(self.owned_stream_ids):
            try:
                self.request(
                    "DELETE",
                    f"/v1/generate_video_embeddings/{stream_id}",
                    action_id="cleanup-stop-live",
                    operation_path="/v1/generate_video_embeddings/{stream_id}",
                    timeout=10,
                    record=False,
                )
            except QualificationError:
                pass
            try:
                status, _raw, _ctype = self.request(
                    "DELETE",
                    f"/v1/streams/delete/{stream_id}",
                    action_id="cleanup-delete-stream",
                    operation_path="/v1/streams/delete/{stream_id}",
                    timeout=15,
                    record=False,
                )
                if status not in {200, 400}:
                    self.cleanup_failures.append("stream_cleanup_failed")
            except QualificationError:
                self.cleanup_failures.append("stream_cleanup_failed")
        self.owned_stream_ids.clear()
        if self.camera_owned:
            try:
                status, _value = self.json_request(
                    "POST",
                    "/v1/stream/remove",
                    action_id="cleanup-remove-camera",
                    value={
                        "key": "sensor",
                        "value": {
                            "camera_id": resources["camera_id"],
                            "change": "camera_remove",
                        },
                    },
                    timeout=15,
                    record=False,
                )
                if status not in {200, 404}:
                    self.cleanup_failures.append("camera_cleanup_failed")
            except QualificationError:
                self.cleanup_failures.append("camera_cleanup_failed")
            self.camera_owned = False
        for file_id in sorted(self.owned_file_ids):
            try:
                status, _raw, _ctype = self.request(
                    "DELETE",
                    f"/v1/files/{file_id}",
                    action_id="cleanup-delete-file",
                    operation_path="/v1/files/{file_id}",
                    timeout=15,
                    record=False,
                )
                if status not in {200, 400}:
                    self.cleanup_failures.append("file_cleanup_failed")
            except QualificationError:
                self.cleanup_failures.append("file_cleanup_failed")
        self.owned_file_ids.clear()
        if self.sse_response is not None:
            self.sse_response.close()
            self.sse_response = None
        if self.sse_connection is not None:
            self.sse_connection.close()
            self.sse_connection = None
        self.stop_publisher()
        self.stop_mediamtx()
        for helper in resources["artifact_helper_containers"]:
            self._stop_container(helper)

    def multipart_fixture(self) -> bytes:
        fixture = _read_regular(
            _source_path(self.contract["fixture"]["path"]),
            self.bounds["max_request_bytes"],
        )
        boundary = "----thor-vss-rt-embed-runtime-boundary"
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        field("purpose", "vision")
        field("media_type", "video")
        field("id", self.contract["owned_resources"]["file_id"])
        field("creation_time", self.contract["fixture"]["creation_time"])
        field("sensor_name", "vss-oracle-rt-embed-runtime")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="file"; filename="vss-rt-embed-runtime.mp4"\r\n',
                b"Content-Type: video/mp4\r\n\r\n",
                fixture,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        body = b"".join(chunks)
        if len(body) > self.bounds["max_request_bytes"]:
            raise QualificationError("budget_exceeded")
        self.multipart_content_type = f"multipart/form-data; boundary={boundary}"
        return body

    def semantic_action(self) -> None:
        self.semantic_actions += 1
        if self.semantic_actions > self.bounds["max_semantic_actions"]:
            raise QualificationError("budget_exceeded")

    def live_sse(self, stream_id: str) -> dict[str, Any]:
        self._consume_http_request()
        payload = _canonical(
            {
                "id": stream_id,
                "model": self.contract["service"]["model_id"],
                "stream": True,
                "stream_options": {"include_usage": True},
                "chunk_duration": self.contract["semantic_contract"][
                    "live_chunk_duration"
                ],
                "chunk_overlap_duration": 0,
            }
        )
        self.semantic_action()
        connection = http.client.HTTPConnection(
            "127.0.0.1", 8017, timeout=self.bounds["request_timeout_seconds"]
        )
        self.sse_connection = connection
        try:
            connection.request(
                "POST",
                "/v1/generate_video_embeddings",
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            )
            response = connection.getresponse()
            self.sse_response = response
            response_type = (response.getheader("Content-Type") or "").split(";", 1)[0]
            if response_type != "text/event-stream":
                raise QualificationError("embedding_contract_failed")
            consumed = bytearray()
            proof: dict[str, Any] | None = None
            for _ in range(500):
                line = response.readline()
                if not line:
                    break
                consumed.extend(line)
                if len(consumed) > self.bounds["max_response_bytes"]:
                    raise QualificationError("budget_exceeded")
                stripped = line.strip()
                if not stripped.startswith(b"data: ") or stripped == b"data: [DONE]":
                    continue
                event = _strict_json(stripped[6:], "embedding_contract_failed")
                if not isinstance(event, dict):
                    raise QualificationError("embedding_contract_failed")
                chunks = event.get("chunk_responses") or []
                if not isinstance(chunks, list):
                    raise QualificationError("embedding_contract_failed")
                if chunks:
                    dimensions = []
                    vector_digests = []
                    for chunk in chunks:
                        if not isinstance(chunk, dict):
                            raise QualificationError("embedding_contract_failed")
                        vector = chunk.get("embeddings")
                        _validate_vector(
                            vector, self.contract["service"]["embedding_dimension"]
                        )
                        dimensions.append(len(vector))
                        vector_digests.append(_digest(vector))
                    proof = {
                        "chunk_count": len(chunks),
                        "dimensions": dimensions,
                        "vectors_finite": True,
                        "vector_sha256": vector_digests,
                        "model_exact": event.get("model")
                        == self.contract["service"]["model_id"],
                    }
                    break
            raw = bytes(consumed)
            self._record(
                action_id="generate-live-video-embedding",
                method="POST",
                operation_path="/v1/generate_video_embeddings",
                status=response.status,
                response=raw,
                content_type=response_type,
            )
            if (
                response.status != 200
                or proof is None
                or proof["chunk_count"]
                < self.contract["semantic_contract"]["minimum_live_chunk_count"]
                or not proof["model_exact"]
            ):
                raise QualificationError("embedding_contract_failed")
            return proof
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("transport_error") from exc


def _validate_vector(value: Any, dimension: int) -> list[float | int]:
    if (
        not isinstance(value, list)
        or len(value) != dimension
        or any(
            type(item) not in {int, float} or not math.isfinite(float(item))
            for item in value
        )
    ):
        raise QualificationError("embedding_contract_failed")
    return value


def _video_projection(
    value: Any, contract: Mapping[str, Any]
) -> tuple[dict[str, Any], list[list[float | int]]]:
    if not isinstance(value, dict):
        raise QualificationError("embedding_contract_failed")
    chunks = value.get("chunk_responses")
    usage = value.get("usage")
    if not isinstance(chunks, list) or not isinstance(usage, dict):
        raise QualificationError("embedding_contract_failed")
    vectors: list[list[float | int]] = []
    ranges: list[dict[str, str]] = []
    dimensions: list[int] = []
    vector_hashes: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise QualificationError("embedding_contract_failed")
        vector = _validate_vector(
            chunk.get("embeddings"), contract["service"]["embedding_dimension"]
        )
        vectors.append(vector)
        dimensions.append(len(vector))
        vector_hashes.append(_digest(vector))
        start = chunk.get("start_time")
        end = chunk.get("end_time")
        if not isinstance(start, str) or not isinstance(end, str):
            raise QualificationError("embedding_contract_failed")
        ranges.append({"start_time": start, "end_time": end})
    return (
        {
            "model_exact": value.get("model") == contract["service"]["model_id"],
            "chunk_count": len(chunks),
            "dimensions": dimensions,
            "ranges": ranges,
            "vectors_finite": True,
            "vector_sha256": vector_hashes,
            "usage_chunk_count": usage.get("total_chunks_processed"),
        },
        vectors,
    )


def _cosine(left: list[float | int], right: list[float | int]) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(float(item) ** 2 for item in right))
    if left_norm == 0 or right_norm == 0:
        raise QualificationError("embedding_contract_failed")
    return dot / (left_norm * right_norm)


def _inventory_projection(
    files: Any, streams: Any, cv_streams: Any, stats: Any
) -> dict[str, Any]:
    if (
        not isinstance(files, dict)
        or not isinstance(files.get("data"), list)
        or not isinstance(streams, list)
        or not isinstance(cv_streams, dict)
        or not isinstance(cv_streams.get("stream_list"), list)
        or not isinstance(stats, dict)
    ):
        raise QualificationError("http_contract_failed")
    file_ids = sorted(
        str(row.get("id")) for row in files["data"] if isinstance(row, dict)
    )
    stream_ids = sorted(str(row.get("id")) for row in streams if isinstance(row, dict))
    cameras = sorted(
        str(row.get("camera_id"))
        for row in cv_streams["stream_list"]
        if isinstance(row, dict)
    )
    return {
        "file_count": len(file_ids),
        "file_ids_sha256": _digest(file_ids),
        "stream_count": len(stream_ids),
        "stream_ids_sha256": _digest(stream_ids),
        "camera_count": len(cameras),
        "camera_ids_sha256": _digest(cameras),
        "asset_statistics": stats,
        "asset_statistics_sha256": _digest(stats),
    }


def _expected_operations(manifest: Any) -> list[dict[str, str]]:
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("operations"), list
    ):
        raise QualificationError("api_contract_failed")
    operations = []
    for row in manifest["operations"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("method"), str)
            or not isinstance(row.get("path"), str)
        ):
            raise QualificationError("api_contract_failed")
        operations.append({"method": row["method"], "path": row["path"]})
    return sorted(operations, key=lambda item: (item["path"], item["method"]))


def _openapi_operations(value: Any) -> tuple[list[dict[str, str]], int]:
    if not isinstance(value, dict) or not isinstance(value.get("paths"), dict):
        raise QualificationError("api_contract_failed")
    operations: list[dict[str, str]] = []
    allowed = {"get", "post", "put", "patch", "delete", "options", "head"}
    for path, row in value["paths"].items():
        if not isinstance(path, str) or not isinstance(row, dict):
            raise QualificationError("api_contract_failed")
        for method in row:
            if method in allowed:
                operations.append({"method": method.upper(), "path": path})
    return sorted(operations, key=lambda item: (item["path"], item["method"])), len(
        value["paths"]
    )


def _json_code(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    code = value.get("code") or value.get("error_code")
    return code if isinstance(code, str) else None


def execute(contract: dict[str, Any], contract_raw: bytes) -> dict[str, Any]:
    started = time.monotonic()
    contract_sha = _sha256(contract_raw)
    runtime = Runtime(contract, contract_sha)
    failure: str | None = None
    blockers: list[str] = []
    result: dict[str, Any] = {}
    artifact_proof: dict[str, Any] = {}
    pre_state: dict[str, Any] = {}
    post_state: dict[str, Any] = {}
    cleanup: dict[str, Any] = {}
    try:
        free_before = _disk_free(REPO)
        if free_before < contract["execution_bounds"]["min_free_bytes"]:
            raise QualificationError("disk_admission_failed")
        fixture = _source_path(contract["fixture"]["path"])
        fixture_raw = _read_regular(
            fixture, contract["execution_bounds"]["max_request_bytes"]
        )
        if (
            len(fixture_raw) != contract["fixture"]["bytes"]
            or _sha256(fixture_raw) != contract["fixture"]["sha256"]
        ):
            raise QualificationError("fixture_contract_failed")
        container_pre = _container_projection(
            contract["service"]["container"], contract
        )
        paused_pre = _paused_projection()
        runtime.bridge_network, runtime.bridge_gateway = _bridge_gateway(
            contract["service"]["container"]
        )
        resource_ids = [
            contract["owned_resources"]["file_id"],
            contract["owned_resources"]["data_url_id"],
            contract["owned_resources"]["denied_file_url_id"],
            contract["owned_resources"]["single_stream_id"],
            *contract["owned_resources"]["batch_stream_ids"],
        ]
        if len(resource_ids) != len(set(resource_ids)) or any(
            UUID_RE.fullmatch(value) is None for value in resource_ids
        ):
            raise QualificationError("configuration_error")

        helpers = contract["owned_resources"]["artifact_helper_containers"]
        artifact_proof = {
            "lock_sha256": contract["artifact_contract"]["lock_sha256"],
            "model": runtime.verify_artifact("model", helpers[0]),
            "triton": runtime.verify_artifact("triton", helpers[1]),
            "repository": contract["artifact_contract"]["repository"],
            "revision": contract["artifact_contract"]["revision"],
            "source_spec_exact": True,
            "batch_size": contract["service"]["batch_size"],
            "precision": contract["artifact_contract"]["triton"]["precision"],
            "target_hardware": contract["artifact_contract"]["triton"][
                "target_hardware"
            ],
        }

        status, openapi = runtime.json_request(
            "GET",
            "/openapi.json",
            action_id="discover-openapi",
            operation_path="/openapi.json",
        )
        if status != 200:
            raise QualificationError("api_contract_failed")
        status, docs_raw, _ctype = runtime.request(
            "GET", "/docs", action_id="discover-swagger", operation_path="/docs"
        )
        if status != 200 or b"swagger" not in docs_raw.lower():
            raise QualificationError("api_contract_failed")
        expected_manifest_raw = _read_regular(
            _source_path(contract["api_contract"]["expected_manifest"])
        )
        if (
            _sha256(expected_manifest_raw)
            != contract["api_contract"]["expected_manifest_sha256"]
        ):
            raise QualificationError("api_contract_failed")
        expected_manifest = _strict_json(expected_manifest_raw, "api_contract_failed")
        expected_operations = _expected_operations(expected_manifest)
        live_operations, path_count = _openapi_operations(openapi)
        if (
            live_operations != expected_operations
            or len(live_operations) != contract["api_contract"]["operation_count"]
            or path_count != contract["api_contract"]["path_count"]
        ):
            raise QualificationError("api_contract_failed")

        simple_gets = (
            ("/v1/metrics", "read-metrics"),
            ("/v1/ready", "read-readiness"),
            ("/v1/live", "read-liveness"),
            ("/v1/startup", "read-startup"),
            ("/v1/metadata", "read-metadata"),
            ("/v1/version", "read-version"),
            ("/v1/manifest", "read-manifest"),
        )
        simple_values: dict[str, Any] = {}
        simple_raw: dict[str, bytes] = {}
        simple_types: dict[str, str] = {}
        for path, action in simple_gets:
            status, raw, content_type = runtime.request(
                "GET", path, action_id=action, operation_path=path
            )
            if status != 200:
                raise QualificationError("http_contract_failed")
            simple_raw[path] = raw
            simple_types[path] = (content_type or "").split(";", 1)[0]
            if "json" in (content_type or ""):
                simple_values[path] = _strict_json(raw, "http_contract_failed")
        version = simple_values.get("/v1/version")
        metadata = simple_values.get("/v1/metadata")
        manifest = simple_values.get("/v1/manifest")
        if (
            version
            != {
                "release": contract["service"]["release"],
                "api": contract["service"]["api_version"],
            }
            or metadata != {"version": contract["service"]["release"]}
            or manifest
            != {
                "version": contract["service"]["release"],
                "model": contract["service"]["model_id"],
            }
            or simple_types["/v1/metrics"] != "text/plain"
            or not simple_raw["/v1/metrics"].startswith(b"# HELP target_info ")
            or simple_raw["/v1/ready"] != b"Service is healthy"
            or simple_raw["/v1/live"] != b"Service is healthy"
            or simple_raw["/v1/startup"] != b"Service is ready to serve requests."
        ):
            raise QualificationError("runtime_identity_failed")

        status, models_pre = runtime.json_request(
            "GET",
            "/v1/models",
            action_id="read-models-pre",
            operation_path="/v1/models",
        )
        if (
            status != 200
            or not isinstance(models_pre, dict)
            or models_pre.get("audio_support") is not False
            or not isinstance(models_pre.get("data"), list)
            or [
                row.get("id")
                for row in models_pre.get("data", [])
                if isinstance(row, dict)
            ]
            != [contract["service"]["model_id"]]
        ):
            raise QualificationError("runtime_identity_failed")
        status, files_pre = runtime.json_request(
            "GET",
            "/v1/files?purpose=vision",
            action_id="read-files-pre",
            operation_path="/v1/files",
        )
        status_streams, streams_pre = runtime.json_request(
            "GET",
            "/v1/streams/get-stream-info",
            action_id="read-streams-pre",
            operation_path="/v1/streams/get-stream-info",
        )
        status_cv, cv_pre = runtime.json_request(
            "GET",
            "/v1/stream/get-stream-info",
            action_id="read-cv-streams-pre",
            operation_path="/v1/stream/get-stream-info",
        )
        status_stats, stats_pre = runtime.json_request(
            "GET",
            "/v1/assets/stats",
            action_id="read-assets-pre",
            operation_path="/v1/assets/stats",
        )
        if {status, status_streams, status_cv, status_stats} != {200}:
            raise QualificationError("http_contract_failed")
        pre_state = _inventory_projection(files_pre, streams_pre, cv_pre, stats_pre)
        owned_set = set(resource_ids)
        if any(
            value in owned_set
            for collection in (
                [
                    row.get("id")
                    for row in files_pre.get("data", [])
                    if isinstance(row, dict)
                ],
                [row.get("id") for row in streams_pre if isinstance(row, dict)],
            )
            for value in collection
        ):
            raise QualificationError("runtime_state_changed")
        if contract["owned_resources"]["camera_id"] in {
            row.get("camera_id")
            for row in cv_pre.get("stream_list", [])
            if isinstance(row, dict)
        }:
            raise QualificationError("runtime_state_changed")

        helper_proof = runtime.start_mediamtx()
        publisher_proof = runtime.start_publisher()
        stream_url = (
            f"rtsp://{runtime.bridge_gateway}:{contract['owned_resources']['rtsp_port']}/"
            f"{contract['owned_resources']['rtsp_path']}"
        )

        upload_body = runtime.multipart_fixture()
        file_id = contract["owned_resources"]["file_id"]
        runtime.owned_file_ids.add(file_id)
        status, upload_raw, _ctype = runtime.request(
            "POST",
            "/v1/files",
            action_id="upload-owned-file",
            operation_path="/v1/files",
            body=upload_body,
            content_type=runtime.multipart_content_type,
            timeout=60,
        )
        upload = _strict_json(upload_raw, "http_contract_failed")
        if status != 200 or not isinstance(upload, dict) or upload.get("id") != file_id:
            raise QualificationError("http_contract_failed")
        status, files_owned = runtime.json_request(
            "GET",
            "/v1/files?purpose=vision",
            action_id="read-files-owned",
            operation_path="/v1/files",
        )
        if (
            status != 200
            or not isinstance(files_owned, dict)
            or not isinstance(files_owned.get("data"), list)
            or file_id
            not in {
                row.get("id")
                for row in files_owned.get("data", [])
                if isinstance(row, dict)
            }
        ):
            raise QualificationError("http_contract_failed")
        status, file_info = runtime.json_request(
            "GET",
            f"/v1/files/{file_id}",
            action_id="read-owned-file-info",
            operation_path="/v1/files/{file_id}",
        )
        if (
            status != 200
            or not isinstance(file_info, dict)
            or file_info.get("id") != file_id
            or file_info.get("bytes") != contract["fixture"]["bytes"]
        ):
            raise QualificationError("http_contract_failed")
        status, content, _ctype = runtime.request(
            "GET",
            f"/v1/files/{file_id}/content",
            action_id="read-owned-file-content",
            operation_path="/v1/files/{file_id}/content",
        )
        if status != 200 or _sha256(content) != contract["fixture"]["sha256"]:
            raise QualificationError("http_contract_failed")

        text_inputs = [
            "a white car driving on a road",
            "a person walking near a building",
        ]
        runtime.semantic_action()
        status, text_value = runtime.json_request(
            "POST",
            "/v1/generate_text_embeddings",
            action_id="generate-text-embeddings",
            operation_path="/v1/generate_text_embeddings",
            value={"text_input": text_inputs, "model": contract["service"]["model_id"]},
            timeout=90,
        )
        if status != 200 or not isinstance(text_value, dict):
            raise QualificationError("embedding_contract_failed")
        text_rows = text_value.get("data")
        if not isinstance(text_rows, list) or len(text_rows) != len(text_inputs):
            raise QualificationError("embedding_contract_failed")
        text_hashes = []
        for row in text_rows:
            if not isinstance(row, dict):
                raise QualificationError("embedding_contract_failed")
            vector = _validate_vector(
                row.get("embeddings"), contract["service"]["embedding_dimension"]
            )
            text_hashes.append(_digest(vector))
        text_proof = {
            "input_count": len(text_inputs),
            "input_projection_sha256": _digest(
                [
                    {"bytes": len(item.encode()), "sha256": _sha256(item.encode())}
                    for item in text_inputs
                ]
            ),
            "model_exact": text_value.get("model") == contract["service"]["model_id"],
            "dimensions": [len(row["embeddings"]) for row in text_rows],
            "vectors_finite": True,
            "vector_sha256": text_hashes,
        }
        if not text_proof["model_exact"]:
            raise QualificationError("embedding_contract_failed")

        video_query = {
            "id": file_id,
            "model": contract["service"]["model_id"],
            "stream": False,
            "chunk_duration": contract["semantic_contract"]["file_chunk_duration"],
            "chunk_overlap_duration": contract["semantic_contract"][
                "file_chunk_overlap_duration"
            ],
        }
        runtime.semantic_action()
        status, file_video = runtime.json_request(
            "POST",
            "/v1/generate_video_embeddings",
            action_id="generate-uploaded-file-embeddings",
            operation_path="/v1/generate_video_embeddings",
            value=video_query,
            timeout=90,
        )
        if status != 200:
            raise QualificationError("embedding_contract_failed")
        file_video_proof, file_vectors = _video_projection(file_video, contract)
        if (
            file_video_proof["chunk_count"]
            != contract["semantic_contract"]["expected_file_chunk_count"]
            or file_video_proof["usage_chunk_count"]
            != contract["semantic_contract"]["expected_file_chunk_count"]
            or not file_video_proof["model_exact"]
        ):
            raise QualificationError("embedding_contract_failed")

        data_id = contract["owned_resources"]["data_url_id"]
        runtime.owned_file_ids.add(data_id)
        data_url = b"data:video/mp4;base64," + base64.b64encode(fixture_raw)
        data_query = {
            "id": data_id,
            "url": data_url.decode("ascii"),
            "media_type": "video",
            "creation_time": contract["fixture"]["creation_time"],
            "model": contract["service"]["model_id"],
            "stream": False,
            "chunk_duration": contract["semantic_contract"]["file_chunk_duration"],
            "chunk_overlap_duration": contract["semantic_contract"][
                "file_chunk_overlap_duration"
            ],
        }
        runtime.semantic_action()
        status, data_video = runtime.json_request(
            "POST",
            "/v1/generate_video_embeddings",
            action_id="generate-rfc2397-embeddings",
            operation_path="/v1/generate_video_embeddings",
            value=data_query,
            timeout=90,
        )
        if status != 200:
            raise QualificationError("embedding_contract_failed")
        data_video_proof, data_vectors = _video_projection(data_video, contract)
        if (
            data_video_proof["chunk_count"] != file_video_proof["chunk_count"]
            or data_video_proof["dimensions"] != file_video_proof["dimensions"]
            or data_video_proof["ranges"] != file_video_proof["ranges"]
            or not data_video_proof["model_exact"]
        ):
            raise QualificationError("embedding_contract_failed")
        cosine = [
            _cosine(left, right)
            for left, right in zip(file_vectors, data_vectors, strict=True)
        ]
        if min(cosine) < 0.999:
            raise QualificationError("embedding_contract_failed")
        base64_proof = {
            "rfc2397_scheme": True,
            "serialized_bytes": len(data_url),
            "decoded_fixture_sha256": contract["fixture"]["sha256"],
            "uploaded_file": file_video_proof,
            "data_url": data_video_proof,
            "shape_and_ranges_exact": True,
            "vector_sha256_exact": data_video_proof["vector_sha256"]
            == file_video_proof["vector_sha256"],
            "minimum_pairwise_cosine": round(min(cosine), 6),
            "transient_asset_removed": True,
        }

        denied_id = contract["owned_resources"]["denied_file_url_id"]
        runtime.owned_file_ids.add(denied_id)
        status, denied = runtime.json_request(
            "POST",
            "/v1/generate_video_embeddings",
            action_id="reject-file-url-without-allowlist",
            operation_path="/v1/generate_video_embeddings",
            value={
                "id": denied_id,
                "url": "file:///etc/hosts",
                "media_type": "video",
                "model": contract["service"]["model_id"],
            },
        )
        if (
            status != contract["semantic_contract"]["file_url_unset_status"]
            or _json_code(denied)
            != contract["semantic_contract"]["file_url_unset_code"]
        ):
            raise QualificationError("api_contract_failed")

        status, _raw, _ctype = runtime.request(
            "DELETE",
            f"/v1/files/{file_id}",
            action_id="delete-owned-file",
            operation_path="/v1/files/{file_id}",
        )
        if status != 200:
            raise QualificationError("http_contract_failed")
        runtime.owned_file_ids.discard(file_id)

        camera_id = contract["owned_resources"]["camera_id"]
        camera_body = {
            "key": "sensor",
            "value": {
                "camera_id": camera_id,
                "camera_url": stream_url,
                "change": "camera_add",
            },
        }
        runtime.camera_owned = True
        status, camera_added = runtime.json_request(
            "POST",
            "/v1/stream/add",
            action_id="add-cv-camera",
            operation_path="/v1/stream/add",
            value=camera_body,
        )
        if (
            status != 200
            or not isinstance(camera_added, dict)
            or camera_added.get("camera_id") != camera_id
        ):
            raise QualificationError("duplicate_contract_failed")
        status, cv_owned = runtime.json_request(
            "GET",
            "/v1/stream/get-stream-info",
            action_id="read-cv-camera-owned",
            operation_path="/v1/stream/get-stream-info",
        )
        if (
            status != 200
            or not isinstance(cv_owned, dict)
            or not isinstance(cv_owned.get("stream_list"), list)
            or camera_id
            not in {
                row.get("camera_id")
                for row in cv_owned.get("stream_list", [])
                if isinstance(row, dict)
            }
        ):
            raise QualificationError("duplicate_contract_failed")
        status, camera_duplicate = runtime.json_request(
            "POST",
            "/v1/stream/add",
            action_id="reject-duplicate-camera-id",
            operation_path="/v1/stream/add",
            value=camera_body,
        )
        if status != 409 or _json_code(camera_duplicate) != "DuplicateCameraId":
            raise QualificationError("duplicate_contract_failed")
        status, camera_removed = runtime.json_request(
            "POST",
            "/v1/stream/remove",
            action_id="remove-cv-camera",
            operation_path="/v1/stream/remove",
            value={
                "key": "sensor",
                "value": {"camera_id": camera_id, "change": "camera_remove"},
            },
        )
        if (
            status != 200
            or not isinstance(camera_removed, dict)
            or camera_removed.get("camera_id") != camera_id
        ):
            raise QualificationError("duplicate_contract_failed")
        runtime.camera_owned = False

        single_id = contract["owned_resources"]["single_stream_id"]
        single_body = {
            "streams": [
                {
                    "id": single_id,
                    "liveStreamUrl": stream_url,
                    "description": "bounded RT-Embed live runtime fixture",
                }
            ]
        }
        runtime.owned_stream_ids.add(single_id)
        status, stream_added = runtime.json_request(
            "POST",
            "/v1/streams/add",
            action_id="add-single-live-stream",
            operation_path="/v1/streams/add",
            value=single_body,
            timeout=45,
        )
        if (
            status != 200
            or not isinstance(stream_added, dict)
            or stream_added.get("results") != [{"id": single_id}]
            or stream_added.get("errors") != []
        ):
            raise QualificationError("duplicate_contract_failed")
        status, streams_owned = runtime.json_request(
            "GET",
            "/v1/streams/get-stream-info",
            action_id="read-single-live-stream",
            operation_path="/v1/streams/get-stream-info",
        )
        if (
            status != 200
            or not isinstance(streams_owned, list)
            or single_id
            not in {row.get("id") for row in streams_owned if isinstance(row, dict)}
        ):
            raise QualificationError("duplicate_contract_failed")
        status, stream_duplicate = runtime.json_request(
            "POST",
            "/v1/streams/add",
            action_id="reject-duplicate-stream-id",
            operation_path="/v1/streams/add",
            value=single_body,
            timeout=45,
        )
        errors = (
            stream_duplicate.get("errors", [])
            if isinstance(stream_duplicate, dict)
            else []
        )
        if (
            status != 200
            or not isinstance(stream_duplicate, dict)
            or stream_duplicate.get("results") != []
            or len(errors) != 1
            or errors[0].get("error_code") != "DuplicateStreamId"
            or errors[0].get("status_code") != 409
        ):
            raise QualificationError("duplicate_contract_failed")

        live_proof = runtime.live_sse(single_id)
        status, _raw, _ctype = runtime.request(
            "DELETE",
            f"/v1/generate_video_embeddings/{single_id}",
            action_id="stop-live-video-embedding",
            operation_path="/v1/generate_video_embeddings/{stream_id}",
            timeout=45,
        )
        if status != 200:
            raise QualificationError("embedding_contract_failed")
        if runtime.sse_response is not None:
            runtime.sse_response.close()
            runtime.sse_response = None
        if runtime.sse_connection is not None:
            runtime.sse_connection.close()
            runtime.sse_connection = None
        status, _raw, _ctype = runtime.request(
            "DELETE",
            f"/v1/streams/delete/{single_id}",
            action_id="delete-single-live-stream",
            operation_path="/v1/streams/delete/{stream_id}",
            timeout=45,
        )
        if status != 200:
            raise QualificationError("http_contract_failed")
        runtime.owned_stream_ids.discard(single_id)

        batch_ids = contract["owned_resources"]["batch_stream_ids"]
        batch_body = {
            "streams": [
                {
                    "id": stream_id,
                    "liveStreamUrl": stream_url,
                    "description": "bounded RT-Embed batch cleanup fixture",
                }
                for stream_id in batch_ids
            ]
        }
        runtime.owned_stream_ids.update(batch_ids)
        status, batch_added = runtime.json_request(
            "POST",
            "/v1/streams/add",
            action_id="add-batch-live-streams",
            operation_path="/v1/streams/add",
            value=batch_body,
            timeout=60,
        )
        if (
            status != 200
            or not isinstance(batch_added, dict)
            or {
                row.get("id")
                for row in batch_added.get("results", [])
                if isinstance(row, dict)
            }
            != set(batch_ids)
            or batch_added.get("errors") != []
        ):
            raise QualificationError("api_contract_failed")
        status, batch_deleted = runtime.json_request(
            "DELETE",
            "/v1/streams/delete-batch",
            action_id="delete-batch-live-streams",
            operation_path="/v1/streams/delete-batch",
            value={
                "stream_ids": batch_ids,
                "blocking": True,
                "drain_timeout_seconds": 30,
            },
            timeout=60,
        )
        if (
            status != 200
            or not isinstance(batch_deleted, dict)
            or set(batch_deleted.get("deleted", [])) != set(batch_ids)
            or batch_deleted.get("errors") != []
        ):
            raise QualificationError("api_contract_failed")
        runtime.owned_stream_ids.difference_update(batch_ids)

        status, files_post = runtime.json_request(
            "GET",
            "/v1/files?purpose=vision",
            action_id="read-files-post",
            operation_path="/v1/files",
        )
        status_streams, streams_post = runtime.json_request(
            "GET",
            "/v1/streams/get-stream-info",
            action_id="read-streams-post",
            operation_path="/v1/streams/get-stream-info",
        )
        status_cv, cv_post = runtime.json_request(
            "GET",
            "/v1/stream/get-stream-info",
            action_id="read-cv-streams-post",
            operation_path="/v1/stream/get-stream-info",
        )
        status_stats, stats_post = runtime.json_request(
            "GET",
            "/v1/assets/stats",
            action_id="read-assets-post",
            operation_path="/v1/assets/stats",
        )
        status_models, models_post = runtime.json_request(
            "GET",
            "/v1/models",
            action_id="read-models-post",
            operation_path="/v1/models",
        )
        status_ready, _ready_raw, _ready_type = runtime.request(
            "GET",
            "/v1/ready",
            action_id="read-readiness-post",
            operation_path="/v1/ready",
        )
        if {
            status,
            status_streams,
            status_cv,
            status_stats,
            status_models,
            status_ready,
        } != {200}:
            raise QualificationError("http_contract_failed")
        post_state = _inventory_projection(
            files_post, streams_post, cv_post, stats_post
        )
        if post_state != pre_state or models_post != models_pre:
            raise QualificationError("runtime_state_changed")

        runtime.stop_publisher()
        rtsp_status, rtsp_raw = runtime._rtsp_describe()
        if rtsp_status != 404:
            raise QualificationError("cleanup_failed")
        runtime.stop_mediamtx()
        if runtime.cleanup_failures:
            raise QualificationError("cleanup_failed")
        container_post = _container_projection(
            contract["service"]["container"], contract
        )
        paused_post = _paused_projection()
        if container_post != container_pre or paused_post != paused_pre:
            raise QualificationError("runtime_state_changed")
        if any(
            not runtime._helper_absent(name)
            for name in [
                contract["owned_resources"]["mediamtx_container"],
                *contract["owned_resources"]["artifact_helper_containers"],
            ]
        ):
            raise QualificationError("cleanup_failed")
        covered_operations = sorted(
            {
                (row["method"], row["operation_path"])
                for row in runtime.observations
                if row["operation_path"].startswith("/v1/")
            }
        )
        expected_pairs = sorted(
            (row["method"], row["path"]) for row in expected_operations
        )
        if covered_operations != expected_pairs:
            raise QualificationError("api_contract_failed")
        cleanup = {
            "failures": [],
            "owned_uuid_count": len(resource_ids),
            "owned_uuid_resources_absent": True,
            "owned_camera_absent": True,
            "complete_inventory_exact": True,
            "asset_statistics_exact": True,
            "model_identity_exact": True,
            "container_identity_exact": True,
            "paused_workloads_exact": True,
            "rtsp_path_absent": True,
            "rtsp_absence_response_sha256": _sha256(rtsp_raw),
            "publisher_absent": True,
            "helper_containers_absent": True,
        }
        result = {
            "artifact_proof": artifact_proof,
            "runtime_identity": container_pre,
            "bridge_scope": {
                "network_name_sha256": _sha256(runtime.bridge_network.encode()),
                "gateway_private_ipv4": True,
                "rtsp_listener_gateway_only": True,
            },
            "rtsp_helper": helper_proof,
            "publisher": publisher_proof,
            "api_surface": {
                "expected_manifest_sha256": contract["api_contract"][
                    "expected_manifest_sha256"
                ],
                "openapi_sha256": runtime.observations[0]["response_sha256"],
                "swagger_reachable": True,
                "path_count": path_count,
                "operation_count": len(live_operations),
                "operation_set_sha256": _digest(live_operations),
                "all_operations_exercised": True,
                "covered_operation_count": len(covered_operations),
            },
            "text_embeddings": text_proof,
            "video_embeddings": {
                "uploaded_file": file_video_proof,
                "rfc2397": base64_proof,
                "live_rtsp": live_proof,
            },
            "duplicate_ids": {
                "camera_transport_status": 409,
                "camera_error_code": "DuplicateCameraId",
                "stream_batch_transport_status": 200,
                "stream_error_status": 409,
                "stream_error_code": "DuplicateStreamId",
                "both_existing_resources_preserved_until_owned_cleanup": True,
            },
            "file_url_negative": {
                "allowlist_unset": True,
                "http_status": contract["semantic_contract"]["file_url_unset_status"],
                "error_code": contract["semantic_contract"]["file_url_unset_code"],
                "asset_created": False,
            },
            "pre_state": pre_state,
            "post_state": post_state,
            "cleanup": cleanup,
            "disk": {
                "free_bytes_before": free_before,
                "free_bytes_after": _disk_free(REPO),
                "minimum_free_bytes": contract["execution_bounds"]["min_free_bytes"],
            },
        }
    except QualificationError as exc:
        failure = exc.code
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ):
        failure = "configuration_error"
    finally:
        runtime.cleanup_resources()
        if runtime.cleanup_failures and failure is None:
            failure = "cleanup_failed"
    duration = round(time.monotonic() - started, 3)
    if (
        duration > contract["execution_bounds"]["max_duration_seconds"]
        and failure is None
    ):
        failure = "budget_exceeded"
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "execute",
        "status": "passed" if failure is None else "failed",
        "failure": failure,
        "blockers": blockers,
        "capability_ids": contract["capability_ids"],
        "target": contract["target"],
        "contract_sha256": contract_sha,
        "duration_seconds": duration,
        "http_request_count": runtime.http_requests,
        "retained_observation_count": len(runtime.observations),
        "semantic_action_count": runtime.semantic_actions,
        "network_scope": contract["execution_bounds"]["network_scope"],
        "external_network_requests": 0,
        "image_pulls": 0,
        "image_builds": 0,
        "model_staging_actions": 0,
        "service_lifecycle_actions": 0,
        "disposable_helper_container_count": 3,
        "warehouse_sample_bundle": False,
        "writes_or_lifecycle_actions": True,
        "sanitization": {
            "credential_values_included": False,
            "dynamic_identifiers_included": False,
            "local_paths_included": False,
            "raw_embedding_vectors_included": False,
            "raw_prompts_included": False,
            "response_bodies_included": False,
            "rtsp_urls_included": False,
        },
        "source_anchors": [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in contract["source_anchors"]
        ],
        "observations": runtime.observations,
        **result,
    }
    if failure is not None:
        receipt["cleanup"] = {
            "failures": sorted(set(runtime.cleanup_failures)),
            "best_effort_attempted": True,
        }
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack")
    parser.add_argument("--output", type=Path, default=RECEIPT_PATH)
    args = parser.parse_args(argv)
    try:
        contract, contract_raw = _load_contract()
        if args.ack != ACKNOWLEDGEMENT:
            raise QualificationError("acknowledgement_required")
        output = args.output.resolve()
        if output != RECEIPT_PATH.resolve():
            raise QualificationError("configuration_error")
        receipt = execute(contract, contract_raw)
        _atomic_json(output, receipt)
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": exc.code}, sort_keys=True))
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    signal.signal(
        signal.SIGTERM,
        lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    raise SystemExit(main())
