#!/usr/bin/env python3
"""Failure-safe lifecycle runner for the Thor-local Qwen alternate qualifier.

Plan mode is inert. Execute mode is deliberately narrow: it may temporarily
stop two named, pre-existing workloads, start the one locked Qwen VLM
container, invoke the existing four-request qualifier, then restore lifecycle
state. It never creates, removes, restarts, pulls, downloads, or writes files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
# Plan and read-only identity modes must not create project-local bytecode as a
# side effect of importing the existing qualifier.
sys.dont_write_bytecode = True
QUALIFIER_PATH = HERE / "qualify.py"
QUALIFIER_SHA256 = "43942973ef07f4a16c4972c1086c486b716df2c32b8a66e689e7a8e2f481b8c3"
try:
    _qualifier_digest = hashlib.sha256(QUALIFIER_PATH.read_bytes()).hexdigest()
except OSError as exc:
    raise RuntimeError("qualifier_source_lock_unavailable") from exc
if _qualifier_digest != QUALIFIER_SHA256:
    raise RuntimeError("qualifier_source_lock_mismatch")
import qualify as qualifier  # noqa: E402


ACKNOWLEDGEMENT = (
    "I_AUTHORIZE_TEMPORARY_QWEN_VLM_LIFECYCLE_WITH_FAILURE_SAFE_RESTORATION"
)
VISION_CONTAINER = "ctai-vision-playground-api"
EMBEDDING_CONTAINER = "datasheet-embedding"
LLM_CONTAINER = "datasheet-vllm-30"
QWEN_CONTAINER = "cti-vss-qwen3-vl"
LLM_ENDPOINT = "http://172.17.0.1:8000"
VLM_ENDPOINT = "http://172.17.0.1:8003"
LLM_MODEL = "datasheet-chat"
VLM_MODEL = "datasheet-vision"
MINIMUM_AVAILABLE_KIB = 50 * 1024 * 1024
VISION_MEMORY_ATTEMPTS = 15
EMBEDDING_MEMORY_ATTEMPTS = 30
READINESS_ATTEMPTS = 90
READINESS_DEADLINE_SECONDS = 900
POLL_SECONDS = 2
READINESS_POLL_SECONDS = 5
PROVISIONER = qualifier.REPO_ROOT / "deploy/docker/thor-local/provision-local-models.sh"
PROVISIONER_SHA256 = "d842b91b870c47614c2e862e7e2444379375fed66a8ebbb57203c2fea265c39c"
THOR_LOCAL_SCRIPT = qualifier.REPO_ROOT / "deploy/docker/scripts/thor-local.sh"
THOR_LOCAL_SCRIPT_SHA256 = (
    "2b67c0b0ee25582ef5acd45ddf12dc02279700ffad065299e6577082fd189df5"
)
ARTIFACT_VERIFIER = (
    qualifier.REPO_ROOT / "deploy/docker/thor-local/models/verify_artifacts.py"
)
ARTIFACT_VERIFIER_SHA256 = (
    "fa8cbb9aeff45da151ae40990cf3c67be08014c464dcec17c952fac5d8b0ca53"
)
DOMAIN_PACK_TOOL = (
    qualifier.REPO_ROOT / "deploy/docker/thor-local/domain-packs/domain_pack.py"
)
DOMAIN_PACK_TOOL_SHA256 = (
    "d12e7e82a486d5f5fc2dfcfb986926d014ec999f3e6f0714061003746eb089f4"
)
SOURCE_LOCKS = {
    PROVISIONER: PROVISIONER_SHA256,
    THOR_LOCAL_SCRIPT: THOR_LOCAL_SCRIPT_SHA256,
    ARTIFACT_VERIFIER: ARTIFACT_VERIFIER_SHA256,
    DOMAIN_PACK_TOOL: DOMAIN_PACK_TOOL_SHA256,
    QUALIFIER_PATH: QUALIFIER_SHA256,
}
LEGACY_LLM_ENVIRONMENT_SHA256 = (
    "461377f86f4683ffb57169c4a7b9561e3596c0166ccdbf65469d6b0c5c8ab857"
)
CURRENT_PROVISIONER_ENVIRONMENT_SHA256 = (
    "68ce5c26d729608e17bcacc96ad5914db540c25a4e0001f906bbbe50ece854db"
)
EXPECTED_ENVIRONMENT_SHA256 = {
    "llm": {
        LEGACY_LLM_ENVIRONMENT_SHA256,
        CURRENT_PROVISIONER_ENVIRONMENT_SHA256,
    },
    "vlm": {CURRENT_PROVISIONER_ENVIRONMENT_SHA256},
}
EXPECTED_CONTAINER_CONFIG_PAIRS = {
    "llm": {
        (
            "19e24f6b5466c40f2179b3b18d5d330c9848a747b6935ab8f2986832a409de16",
            "29658154f0f36667641e5ddb30dfcd1c934ce32f9365e4b828a7e75c01d493a5",
        ),
        (
            "613fb2d0d98a44b357a08c1cd7fd56da66e6e7cb2e8f2502241443ef83641cc5",
            "237d9f9372f9acfdbf9dacb7d61b11a448a389bda5e868fe3e55b360b625fcbf",
        ),
    },
    "vlm": {
        (
            "35233928f628b1e1e40812c56890102cb741a66ea7f4a8b8a6116fa179d1dcfe",
            "237d9f9372f9acfdbf9dacb7d61b11a448a389bda5e868fe3e55b360b625fcbf",
        )
    },
}
MANAGED_SIGNALS = {signal.SIGINT, signal.SIGTERM}
HF_CACHE_TARGET = "/data/models/huggingface"
REQUIRED_OFFLINE_ENV = {
    "HF_HOME": HF_CACHE_TARGET,
    "HUGGINGFACE_HUB_CACHE": HF_CACHE_TARGET,
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "NVIDIA_VISIBLE_DEVICES": "all",
    "NVIDIA_DRIVER_CAPABILITIES": "all",
}
FORBIDDEN_CREDENTIAL_ENV = {
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "NGC_API_KEY",
    "NGC_CLI_API_KEY",
    "NVIDIA_API_KEY",
}


def _environment_sha256(environment: dict[str, str]) -> str:
    raw = json.dumps(
        environment, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _container_config_pair_sha256(
    config: dict[str, Any], host_config: dict[str, Any]
) -> tuple[str, str]:
    normalized_config = dict(config)
    # Docker assigns Hostname from the container ID at create time. It does not
    # affect the host-network model process and is the only normalized field.
    normalized_config["Hostname"] = "<docker-generated>"
    return (
        hashlib.sha256(
            json.dumps(
                normalized_config,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        hashlib.sha256(
            json.dumps(
                host_config,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
    )


def _expected_command(role: str) -> list[str]:
    if role == "llm":
        revision = qualifier.ARTIFACTS["qwen_llm"]["revision"]
        return [
            "vllm",
            "serve",
            qualifier.ARTIFACTS["qwen_llm"]["repository"],
            "--revision",
            revision,
            "--tokenizer-revision",
            revision,
            "--host",
            "172.17.0.1",
            "--port",
            "8000",
            "--served-model-name",
            LLM_MODEL,
            "--max-model-len",
            "32768",
            "--gpu-memory-utilization",
            "0.40",
            "--kv-cache-memory-bytes",
            "4G",
            "--max-num-seqs",
            "1",
            "--enforce-eager",
            "--reasoning-parser",
            "qwen3",
            "--language-model-only",
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            "qwen3_coder",
        ]
    if role == "vlm":
        revision = qualifier.ARTIFACTS["qwen_vlm"]["revision"]
        return [
            "vllm",
            "serve",
            qualifier.ARTIFACTS["qwen_vlm"]["repository"],
            "--revision",
            revision,
            "--tokenizer-revision",
            revision,
            "--host",
            "172.17.0.1",
            "--port",
            "8003",
            "--served-model-name",
            VLM_MODEL,
            "--max-model-len",
            "16384",
            "--gpu-memory-utilization",
            "0.18",
            "--max-num-seqs",
            "1",
            "--enforce-eager",
            "--limit-mm-per-prompt",
            '{"image":4,"video":0}',
        ]
    raise LifecycleError("invalid_model_role")


class LifecycleError(RuntimeError):
    """A redacted lifecycle failure suitable for controlled evidence."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _consume_pending_signal() -> int | None:
    pending = sorted(MANAGED_SIGNALS.intersection(signal.sigpending()))
    first: int | None = None
    for signum in pending:
        consumed = signal.sigwait({signum})
        if first is None:
            first = int(consumed)
    return first


def _raise_if_interrupted() -> None:
    signum = _consume_pending_signal()
    if signum is not None:
        raise LifecycleError(f"interrupted_by_signal_{signum}")


def _parse_direct_http_response(raw: bytes) -> qualifier.HttpResult:
    if len(raw) > qualifier.MAX_RESPONSE_BODY + 65_536:
        raise LifecycleError("readiness_response_too_large")
    try:
        header_raw, body = raw.split(b"\r\n\r\n", 1)
        header_text = header_raw.decode("iso-8859-1")
        lines = header_text.split("\r\n")
        protocol, status_text, _reason = lines[0].split(" ", 2)
        status = int(status_text)
    except (UnicodeError, ValueError) as exc:
        raise LifecycleError("readiness_http_invalid") from exc
    if protocol not in {"HTTP/1.0", "HTTP/1.1"}:
        raise LifecycleError("readiness_http_invalid")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise LifecycleError("readiness_http_invalid")
        key, content = line.split(":", 1)
        key = key.strip().lower()
        if key in headers:
            raise LifecycleError("readiness_http_duplicate_header")
        headers[key] = content.strip()
    if "transfer-encoding" in headers:
        raise LifecycleError("readiness_transfer_encoding_rejected")
    if "content-length" in headers:
        try:
            declared = int(headers["content-length"])
        except ValueError as exc:
            raise LifecycleError("readiness_content_length_invalid") from exc
        if declared < 0 or declared != len(body):
            raise LifecycleError("readiness_content_length_invalid")
    if len(body) > qualifier.MAX_RESPONSE_BODY:
        raise LifecycleError("readiness_response_too_large")
    return qualifier.HttpResult(status, headers.get("content-type", ""), body)


def _direct_model_response(role: str, timeout_seconds: float) -> qualifier.HttpResult:
    if role not in {"llm", "vlm"} or timeout_seconds <= 0:
        raise LifecycleError("readiness_request_invalid")
    host, port, _model = qualifier.ENDPOINTS[role]
    deadline = time.monotonic() + timeout_seconds
    connection: socket.socket | None = None
    try:
        connection = socket.create_connection((host, port), timeout=timeout_seconds)
        if time.monotonic() >= deadline:
            raise LifecycleError("readiness_request_deadline")
        connection.setblocking(False)
        request = memoryview(
            (
                f"GET /v1/models HTTP/1.1\r\nHost: {host}:{port}\r\n"
                "Accept: application/json\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
        )
        while request:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LifecycleError("readiness_request_deadline")
            _readable, writable, _errors = select.select(
                [], [connection], [], remaining
            )
            if not writable:
                raise LifecycleError("readiness_request_deadline")
            try:
                sent = connection.send(request)
            except BlockingIOError:
                continue
            if sent <= 0:
                raise LifecycleError("readiness_http_transport_error")
            request = request[sent:]

        raw = bytearray()
        maximum_raw = qualifier.MAX_RESPONSE_BODY + 65_536
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LifecycleError("readiness_request_deadline")
            readable, _writable, _errors = select.select(
                [connection], [], [], remaining
            )
            if not readable:
                raise LifecycleError("readiness_request_deadline")
            try:
                chunk = connection.recv(min(65_536, maximum_raw + 1 - len(raw)))
            except BlockingIOError:
                continue
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > maximum_raw:
                raise LifecycleError("readiness_response_too_large")
        return _parse_direct_http_response(bytes(raw))
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError("readiness_http_transport_error") from exc
    finally:
        if connection is not None:
            connection.close()


@dataclass(frozen=True)
class ContainerState:
    status: str
    running: bool
    oom_killed: bool = False


class Runtime(Protocol):
    def verify_identity(self) -> None: ...

    def container_state(
        self, name: str, timeout_seconds: float = 30
    ) -> ContainerState: ...

    def stop_container(self, name: str) -> None: ...

    def start_container(self, name: str) -> None: ...

    def available_memory_kib(self) -> int: ...

    def model_is_exact(self, role: str, timeout_seconds: float) -> bool: ...

    def run_qualifier(self) -> dict[str, Any]: ...

    def sleep(self, seconds: float) -> None: ...

    def monotonic(self) -> float: ...


class DockerRuntime:
    """Production runtime. Constructed only after the execute gate passes."""

    @staticmethod
    def _environment() -> dict[str, str]:
        # Do not let ambient model, endpoint, Docker-context, PATH, credential,
        # or cache variables redirect this exact local-host operation.
        return {
            "DOCKER_HOST": "unix:///var/run/docker.sock",
            "HOME": pwd.getpwuid(os.getuid()).pw_dir,
            "LANG": "C.UTF-8",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }

    @staticmethod
    def _run(
        command: list[str], error_code: str, timeout_seconds: float = 30
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                env=DockerRuntime._environment(),
                # Keep terminal Ctrl-C/SIGTERM on the parent lifecycle runner;
                # helper interruption must not punch through masked cleanup.
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LifecycleError(error_code) from exc
        if result.returncode != 0:
            raise LifecycleError(error_code)
        return result

    def verify_identity(self) -> None:
        for path, expected_digest in SOURCE_LOCKS.items():
            try:
                actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise LifecycleError("identity_source_lock_unavailable") from exc
            if actual_digest != expected_digest:
                raise LifecycleError("identity_source_lock_mismatch")
        self._run([str(PROVISIONER), "status"], "identity_gate_failed", 180)
        image_id = self._run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", qualifier.VLLM_IMAGE],
            "exact_vllm_image_unavailable",
        ).stdout.strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise LifecycleError("exact_vllm_image_id_invalid")
        self._verify_container_contract(LLM_CONTAINER, "llm", image_id)
        self._verify_container_contract(QWEN_CONTAINER, "vlm", image_id)

    def _verify_container_contract(
        self, name: str, role: str, expected_image_id: str
    ) -> None:
        result = self._run(
            ["docker", "inspect", "--format", "{{json .}}", name],
            f"container_contract_unavailable_{name}",
        )
        try:
            value = json.loads(result.stdout)
            config = value["Config"]
            host = value["HostConfig"]
            mounts = value["Mounts"]
            labels = config["Labels"]
            environment_items = config["Env"]
            restart = host["RestartPolicy"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LifecycleError(f"container_contract_invalid_{name}") from exc
        if not isinstance(environment_items, list) or not all(
            isinstance(item, str) and "=" in item for item in environment_items
        ):
            raise LifecycleError(f"container_environment_invalid_{name}")
        environment: dict[str, str] = {}
        for item in environment_items:
            key, content = item.split("=", 1)
            if key in environment:
                raise LifecycleError(f"container_environment_duplicate_{name}")
            environment[key] = content
        expected_label = "com.nvidia.vss.thor-local.model-role"
        expected_mount_source = str(
            Path(self._environment()["HOME"]) / ".cache/huggingface"
        )
        # Qwen is stopped and will be started by this runner, so every launch
        # guard must be exact. The LLM is a preserved, already-running legacy
        # container that this runner never lifecycle-targets; it predates only
        # the role label. Exact role-specific environment digests lock all
        # inherited image values and every explicit override without emitting
        # their contents (some image-build variables are credential-shaped).
        environment_digest = _environment_sha256(environment)
        config_pair_digest = _container_config_pair_sha256(config, host)
        role_label_matches = labels.get(expected_label) == role
        if role == "llm":
            role_label_matches = (
                environment_digest == LEGACY_LLM_ENVIRONMENT_SHA256
                and labels.get(expected_label) is None
            ) or (
                environment_digest == CURRENT_PROVISIONER_ENVIRONMENT_SHA256
                and labels.get(expected_label) == role
            )
        contract_matches = (
            value.get("Name") == f"/{name}"
            and value.get("Image") == expected_image_id
            and config.get("Image") == qualifier.VLLM_IMAGE
            and config.get("Cmd") == _expected_command(role)
            and config.get("Entrypoint") is None
            and config.get("WorkingDir") == "/"
            and config.get("User") == ""
            and isinstance(labels, dict)
            and role_label_matches
            and host.get("NetworkMode") == "host"
            and host.get("Runtime") == "nvidia"
            and host.get("Privileged") is False
            and host.get("PidMode") == ""
            and host.get("IpcMode") == "private"
            and host.get("UTSMode") == ""
            and host.get("UsernsMode") == ""
            and host.get("ReadonlyRootfs") is False
            and host.get("AutoRemove") is False
            and host.get("CapAdd") is None
            and host.get("CapDrop") is None
            and host.get("SecurityOpt") is None
            and host.get("Devices") == []
            and host.get("DeviceRequests") is None
            and host.get("ExtraHosts") is None
            and host.get("Links") is None
            and host.get("CgroupnsMode") == "private"
            and host.get("OomKillDisable") in {None, False}
            and isinstance(restart, dict)
            and restart.get("Name") == "no"
            and restart.get("MaximumRetryCount", 0) == 0
            and len(mounts) == 1
            and isinstance(mounts[0], dict)
            and mounts[0].get("Type") == "bind"
            and mounts[0].get("Source") == expected_mount_source
            and mounts[0].get("Destination") == HF_CACHE_TARGET
            and mounts[0].get("RW") is True
            and environment_digest in EXPECTED_ENVIRONMENT_SHA256[role]
            and config_pair_digest in EXPECTED_CONTAINER_CONFIG_PAIRS[role]
        )
        if not contract_matches:
            raise LifecycleError(f"container_contract_mismatch_{name}")

    def container_state(self, name: str, timeout_seconds: float = 30) -> ContainerState:
        result = self._run(
            ["docker", "inspect", "--format", "{{json .State}}", name],
            f"container_state_unavailable_{name}",
            timeout_seconds,
        )
        try:
            value = json.loads(result.stdout)
            status = value["Status"]
            running = value["Running"]
            oom_killed = value.get("OOMKilled", False)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LifecycleError(f"container_state_invalid_{name}") from exc
        if not isinstance(status, str) or not isinstance(running, bool):
            raise LifecycleError(f"container_state_invalid_{name}")
        if not isinstance(oom_killed, bool):
            raise LifecycleError(f"container_state_invalid_{name}")
        return ContainerState(status, running, oom_killed)

    def stop_container(self, name: str) -> None:
        self._run(
            ["docker", "stop", "--time", "30", name],
            f"container_stop_failed_{name}",
            45,
        )

    def start_container(self, name: str) -> None:
        self._run(["docker", "start", name], f"container_start_failed_{name}", 45)

    @staticmethod
    def available_memory_kib() -> int:
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[0] == "MemAvailable:":
                    value = int(fields[1])
                    if fields[2] != "kB" or value < 0:
                        break
                    return value
        except (OSError, UnicodeError, ValueError) as exc:
            raise LifecycleError("memory_read_failed") from exc
        raise LifecycleError("memory_read_failed")

    @staticmethod
    def model_is_exact(role: str, timeout_seconds: float) -> bool:
        try:
            result = _direct_model_response(role, timeout_seconds)
            value = qualifier._response_json(result)
            qualifier._validate_model_identity(
                value, LLM_MODEL if role == "llm" else VLM_MODEL
            )
            return True
        except (LifecycleError, qualifier.QualificationError):
            return False

    @staticmethod
    def run_qualifier() -> dict[str, Any]:
        return qualifier.execute(qualifier.DirectLocalTransport())

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()


@dataclass
class LifecycleTracker:
    stopped_by_runner: list[str] = field(default_factory=list)
    stop_attempted: list[str] = field(default_factory=list)
    qwen_start_attempted: bool = False
    readiness_requests: int = 0


def _state(runtime: Runtime, name: str, timeout_seconds: float = 30) -> ContainerState:
    return runtime.container_state(name, timeout_seconds)


def _is_running(state: ContainerState) -> bool:
    return state.running and state.status == "running"


def _qwen_is_active(state: ContainerState) -> bool:
    return state.running or state.status in {"running", "paused", "restarting"}


def _require_running(runtime: Runtime, name: str) -> None:
    state = _state(runtime, name)
    if not _is_running(state):
        raise LifecycleError(f"prestate_not_running_{name}")


def _require_qwen_stopped(runtime: Runtime) -> None:
    state = _state(runtime, QWEN_CONTAINER)
    if state.running or state.status not in {"created", "exited"}:
        raise LifecycleError("prestate_qwen_not_stopped")


def _stop_tracked(runtime: Runtime, tracker: LifecycleTracker, name: str) -> None:
    if name not in tracker.stop_attempted:
        tracker.stop_attempted.append(name)
    stop_error: LifecycleError | None = None
    try:
        runtime.stop_container(name)
    except LifecycleError as exc:
        stop_error = exc
    finally:
        state = _state(runtime, name)
        if not _is_running(state) and name not in tracker.stopped_by_runner:
            tracker.stopped_by_runner.append(name)
    if stop_error is not None:
        raise stop_error
    if _is_running(_state(runtime, name)):
        raise LifecycleError(f"container_still_running_{name}")


def _wait_for_memory(runtime: Runtime, attempts: int) -> bool:
    for attempt in range(attempts):
        _raise_if_interrupted()
        if runtime.available_memory_kib() >= MINIMUM_AVAILABLE_KIB:
            return True
        _raise_if_interrupted()
        if attempt + 1 < attempts:
            runtime.sleep(POLL_SECONDS)
    return False


def _wait_for_qwen(
    runtime: Runtime,
    tracker: LifecycleTracker,
    attempts: int,
    deadline_seconds: float,
) -> bool:
    deadline = runtime.monotonic() + deadline_seconds
    for attempt in range(attempts):
        _raise_if_interrupted()
        remaining = deadline - runtime.monotonic()
        if remaining <= 0:
            return False
        state = _state(runtime, QWEN_CONTAINER, min(5.0, remaining))
        if not _is_running(state):
            return False
        _raise_if_interrupted()
        remaining = deadline - runtime.monotonic()
        if remaining <= 0:
            return False
        tracker.readiness_requests += 1
        if runtime.model_is_exact("vlm", min(qualifier.TIMEOUT_SECONDS, remaining)):
            _raise_if_interrupted()
            return True
        _raise_if_interrupted()
        if attempt + 1 < attempts:
            remaining = deadline - runtime.monotonic()
            if remaining <= 0:
                return False
            runtime.sleep(min(float(READINESS_POLL_SECONDS), remaining))
    return False


def _cleanup(runtime: Runtime, tracker: LifecycleTracker) -> tuple[list[str], bool]:
    failures: list[str] = []
    qwen_confirmed_stopped = False

    # Always re-inspect Qwen before restoring memory-heavy workloads. If this
    # invocation attempted the start, it owns the stop. If an external actor
    # activated Qwen before our start attempt, do not stop their workload—but
    # also do not restore underneath it and risk unified-memory overcommit.
    try:
        if tracker.qwen_start_attempted:
            if _qwen_is_active(_state(runtime, QWEN_CONTAINER)):
                try:
                    runtime.stop_container(QWEN_CONTAINER)
                except LifecycleError:
                    pass
            if _qwen_is_active(_state(runtime, QWEN_CONTAINER)):
                failures.append("cleanup_qwen_still_running")
            else:
                qwen_confirmed_stopped = True
        elif _qwen_is_active(_state(runtime, QWEN_CONTAINER)):
            failures.append("cleanup_qwen_unexpected_external_activation")
        else:
            qwen_confirmed_stopped = True
    except LifecycleError:
        failures.append("cleanup_qwen_state_unavailable")

    if failures:
        # Never reintroduce the stopped memory-heavy workloads while Qwen may
        # still be resident. This is a cleanup failure requiring intervention.
        return failures, qwen_confirmed_stopped

    for name in tracker.stop_attempted:
        if name in tracker.stopped_by_runner:
            continue
        try:
            if not _is_running(_state(runtime, name)):
                tracker.stopped_by_runner.append(name)
        except LifecycleError:
            failures.append(f"cleanup_stop_reconciliation_failed_{name}")

    for name in reversed(tracker.stopped_by_runner):
        try:
            if not _is_running(_state(runtime, name)):
                try:
                    runtime.start_container(name)
                except LifecycleError:
                    pass
            if not _is_running(_state(runtime, name)):
                failures.append(f"cleanup_restore_failed_{name}")
        except LifecycleError:
            failures.append(f"cleanup_restore_state_unavailable_{name}")

    for name in (VISION_CONTAINER, EMBEDDING_CONTAINER):
        if name in tracker.stop_attempted:
            continue
        try:
            if not _is_running(_state(runtime, name)):
                failures.append(f"cleanup_untargeted_workload_not_running_{name}")
        except LifecycleError:
            failures.append(f"cleanup_untargeted_state_unavailable_{name}")

    try:
        if not _is_running(_state(runtime, LLM_CONTAINER)):
            failures.append("cleanup_llm_not_running")
    except LifecycleError:
        failures.append("cleanup_llm_state_unavailable")
    return failures, qwen_confirmed_stopped


def _plan() -> dict[str, Any]:
    underlying = qualifier.build_plan()
    return {
        "schema_version": 1,
        "lane": "non-official-local-alternate",
        "status": "planned",
        "writes_or_lifecycle_actions": False,
        "acknowledgement": ACKNOWLEDGEMENT,
        "memory_admission_kib": MINIMUM_AVAILABLE_KIB,
        "readiness": {
            "endpoint": VLM_ENDPOINT,
            "model": VLM_MODEL,
            "maximum_requests": READINESS_ATTEMPTS,
            "deadline_seconds": READINESS_DEADLINE_SECONDS,
            "request_timeout_seconds": qualifier.TIMEOUT_SECONDS,
            "proxies_allowed": False,
        },
        "lifecycle": [
            f"verify exact identity and prestate; preserve {LLM_CONTAINER}",
            f"temporarily stop {VISION_CONTAINER}",
            f"stop {EMBEDDING_CONTAINER} only if memory remains below 50 GiB",
            f"start and qualify only {QWEN_CONTAINER}",
            "finally stop Qwen before restoring only workloads stopped by this run",
        ],
        "qualifier": underlying,
    }


def execute_lifecycle(
    runtime: Runtime,
    *,
    vision_memory_attempts: int = VISION_MEMORY_ATTEMPTS,
    embedding_memory_attempts: int = EMBEDDING_MEMORY_ATTEMPTS,
    readiness_attempts: int = READINESS_ATTEMPTS,
    readiness_deadline_seconds: float = READINESS_DEADLINE_SECONDS,
) -> dict[str, Any]:
    if (
        min(
            vision_memory_attempts,
            embedding_memory_attempts,
            readiness_attempts,
            readiness_deadline_seconds,
        )
        < 1
        or readiness_attempts > READINESS_ATTEMPTS
        or readiness_deadline_seconds > READINESS_DEADLINE_SECONDS
    ):
        raise ValueError("attempt counts and readiness deadline exceed policy")

    tracker = LifecycleTracker()
    failure: str | None = None
    cleanup_failures: list[str] = []
    qwen_confirmed_stopped = False
    qualification: dict[str, Any] | None = None
    embedding_was_stopped = False

    # Block cancellation signals before the first preflight check and keep
    # them blocked until cleanup has completed. Explicit checkpoints consume
    # pending signals and enter the normal failure/cleanup path. A signal that
    # arrives during cleanup is consumed only after restoration is finished.
    # SIGKILL and process/power loss are inherently outside this guarantee.
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, MANAGED_SIGNALS)
    try:
        try:
            if (
                threading.current_thread() is not threading.main_thread()
                or len(threading.enumerate()) != 1
            ):
                raise LifecycleError("signal_safety_requires_single_thread")
            _raise_if_interrupted()
            runtime.verify_identity()
            _raise_if_interrupted()
            _require_running(runtime, VISION_CONTAINER)
            _require_running(runtime, EMBEDDING_CONTAINER)
            _require_running(runtime, LLM_CONTAINER)
            _require_qwen_stopped(runtime)
            if not runtime.model_is_exact("llm", qualifier.TIMEOUT_SECONDS):
                raise LifecycleError("preflight_llm_identity_not_exact")

            _raise_if_interrupted()
            _stop_tracked(runtime, tracker, VISION_CONTAINER)
            _raise_if_interrupted()
            if not _wait_for_memory(runtime, vision_memory_attempts):
                _raise_if_interrupted()
                _stop_tracked(runtime, tracker, EMBEDDING_CONTAINER)
                embedding_was_stopped = True
                _raise_if_interrupted()
                if not _wait_for_memory(runtime, embedding_memory_attempts):
                    raise LifecycleError("memory_below_50_gib_after_authorized_stops")

            _raise_if_interrupted()
            if runtime.available_memory_kib() < MINIMUM_AVAILABLE_KIB:
                raise LifecycleError("memory_below_50_gib_before_qwen_start")
            _require_running(runtime, LLM_CONTAINER)

            _raise_if_interrupted()
            tracker.qwen_start_attempted = True
            start_error: LifecycleError | None = None
            try:
                runtime.start_container(QWEN_CONTAINER)
            except LifecycleError as exc:
                start_error = exc
            if start_error is not None:
                raise start_error
            _raise_if_interrupted()
            if not _is_running(_state(runtime, QWEN_CONTAINER)):
                raise LifecycleError("qwen_not_running_after_start")

            ready = _wait_for_qwen(
                runtime, tracker, readiness_attempts, readiness_deadline_seconds
            )
            if not ready:
                state = _state(runtime, QWEN_CONTAINER)
                if state.oom_killed:
                    raise LifecycleError("qwen_oom_during_readiness")
                if not _is_running(state):
                    raise LifecycleError("qwen_exited_during_readiness")
                raise LifecycleError("qwen_readiness_timeout")

            _raise_if_interrupted()
            qualification = runtime.run_qualifier()
            _raise_if_interrupted()
            if (
                qualification.get("status") != "passed"
                or qualification.get("classification") != "non-official-local-alternate"
                or qualification.get("requests_attempted") != qualifier.MAX_REQUESTS
            ):
                raise LifecycleError("qwen_qualification_failed")
        except LifecycleError as exc:
            failure = exc.code
        except Exception:
            failure = "unexpected_runtime_error"
        finally:
            cleanup_failures, qwen_confirmed_stopped = _cleanup(runtime, tracker)

        cleanup_signal = _consume_pending_signal()
        if cleanup_signal is not None and failure is None:
            failure = f"interrupted_by_signal_{cleanup_signal}"

        passed = failure is None and not cleanup_failures
        return {
            "schema_version": 1,
            "lane": "non-official-local-alternate",
            "status": "passed" if passed else "failed",
            "official_capability_promotion_allowed": False,
            "failure": failure,
            "cleanup_failures": cleanup_failures,
            "memory_admission_kib": MINIMUM_AVAILABLE_KIB,
            "embedding_was_stopped": embedding_was_stopped,
            "readiness_requests": tracker.readiness_requests,
            "readiness_request_limit": readiness_attempts,
            "readiness_deadline_seconds": readiness_deadline_seconds,
            "qualification": qualification,
            "lifecycle": {
                "stop_attempted": tracker.stop_attempted,
                "stopped_by_runner": tracker.stopped_by_runner,
                "qwen_start_attempted": tracker.qwen_start_attempted,
                "qwen_stopped_before_restore": qwen_confirmed_stopped,
                "llm_was_lifecycle_targeted": False,
            },
        }
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or run failure-safe Thor-local Qwen VLM qualification."
    )
    parser.add_argument(
        "--execute", action="store_true", help="perform the gated lifecycle"
    )
    parser.add_argument("--ack", default=None, help="exact lifecycle acknowledgement")
    return parser


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.execute:
        if args.ack is not None:
            output = {
                "schema_version": 1,
                "lane": "non-official-local-alternate",
                "status": "failed",
                "failure": "acknowledgement_without_execute",
            }
        else:
            try:
                output = _plan()
            except (qualifier.QualificationError, OSError):
                output = {
                    "schema_version": 1,
                    "lane": "non-official-local-alternate",
                    "status": "failed",
                    "failure": "plan_contract_validation_failed",
                }
    elif args.ack != ACKNOWLEDGEMENT:
        output = {
            "schema_version": 1,
            "lane": "non-official-local-alternate",
            "status": "failed",
            "failure": "exact_acknowledgement_required",
        }
    else:
        output = execute_lifecycle(runtime or DockerRuntime())

    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0 if output["status"] in {"planned", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
