#!/usr/bin/env python3
"""Inert-by-default, read-only Thor host readiness inventory.

The default ``plan`` mode executes no external command and reads no host file.
The explicit ``inspect`` mode has a closed executable + argv allowlist. It does
not use a shell, ambient credentials, Docker lifecycle verbs, or network tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_CONTRACT = HERE / "contract.json"
OFFICIAL_EDGE_CONTRACT = (
    REPO_ROOT / "deploy/docker/thor-local/official-edge/contract.json"
)
OFFICIAL_EDGE_LOCK = (
    REPO_ROOT / "deploy/docker/thor-local/official-edge/artifacts.lock.json"
)

MAX_CAPTURE_BYTES = 1024 * 1024
REDACTED = "[REDACTED]"


class PreflightError(RuntimeError):
    """A malformed contract, unsafe request, or invalid probe result."""


@dataclass(frozen=True)
class Probe:
    id: str
    executable: str
    argv: tuple[str, ...]
    purpose: str


@dataclass(frozen=True)
class ProbeResult:
    state: str
    stdout: str = ""
    diagnostic: str = ""
    returncode: int | None = None


def _probe(
    probe_id: str, executable: str, argv: tuple[str, ...], purpose: str
) -> Probe:
    if not executable.startswith("/"):
        raise AssertionError(f"probe executable is not absolute: {executable}")
    return Probe(probe_id, executable, argv, purpose)


# This table is deliberately code-owned. A modified JSON contract cannot add a
# command. Every Docker verb below is informational; run/start/stop/exec/pull,
# Compose application commands, and image mutation verbs are absent.
_PROBES = {
    probe.id: probe
    for probe in (
        _probe("architecture", "/usr/bin/uname", ("-m",), "host architecture"),
        _probe("kernel", "/usr/bin/uname", ("-r",), "kernel release"),
        _probe(
            "l4t_package",
            "/usr/bin/dpkg-query",
            ("-W", "-f=${Version}", "nvidia-l4t-core"),
            "Jetson Linux BSP package version",
        ),
        _probe(
            "toolkit_package",
            "/usr/bin/dpkg-query",
            ("-W", "-f=${Version}", "nvidia-container-toolkit"),
            "NVIDIA Container Toolkit package version",
        ),
        _probe(
            "gpu",
            "/usr/sbin/nvidia-smi",
            (
                "--query-gpu=index,name,driver_version,memory.total",
                "--format=csv,noheader",
            ),
            "GPU and driver inventory",
        ),
        _probe(
            "docker_version",
            "/usr/bin/docker",
            ("version", "--format", "{{.Client.Version}}|{{.Server.Version}}"),
            "Docker client and daemon versions",
        ),
        _probe(
            "compose_version",
            "/usr/bin/docker",
            ("compose", "version", "--short"),
            "Docker Compose plugin version",
        ),
        _probe(
            "docker_cgroup",
            "/usr/bin/docker",
            ("info", "--format", "{{.CgroupDriver}}"),
            "Docker daemon cgroup driver",
        ),
        _probe(
            "docker_runtimes",
            "/usr/bin/docker",
            ("info", "--format", "{{json .Runtimes}}"),
            "Docker runtime names",
        ),
        _probe(
            "containers",
            "/usr/bin/docker",
            (
                "ps",
                "-a",
                "--no-trunc",
                "--format",
                '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}',
            ),
            "existing container name, image, status, port, and project conflicts",
        ),
        _probe(
            "images",
            "/usr/bin/docker",
            (
                "image",
                "ls",
                "--no-trunc",
                "--digests",
                "--format",
                "{{.Repository}}\t{{.Tag}}\t{{.Digest}}\t{{.ID}}",
            ),
            "local image identities; never pulls or inspects a container",
        ),
        _probe(
            "ports",
            "/usr/bin/ss",
            ("-H", "-ltn"),
            "listening TCP ports without process data",
        ),
        _probe(
            "disk_root",
            "/usr/bin/df",
            ("-B1", "--output=size,avail,pcent,target", "/"),
            "root filesystem capacity",
        ),
        _probe(
            "cache_cleaner",
            "/usr/bin/pgrep",
            ("-c", "-f", "^(/bin/bash )?/usr/local/bin/sys-cache-cleaner[.]sh$"),
            "count the exact Thor cache-cleaner command without exposing process arguments",
        ),
    )
}
PROBES: Mapping[str, Probe] = MappingProxyType(_PROBES)

HOST_FILES = MappingProxyType(
    {
        "meminfo": Path("/proc/meminfo"),
        "os_release": Path("/etc/os-release"),
        "tegra_release": Path("/etc/nv_tegra_release"),
        "device_model": Path("/proc/device-tree/model"),
        "docker_daemon": Path("/etc/docker/daemon.json"),
        "vm_max_map_count": Path("/proc/sys/vm/max_map_count"),
        "net_core_rmem_max": Path("/proc/sys/net/core/rmem_max"),
        "net_core_wmem_max": Path("/proc/sys/net/core/wmem_max"),
    }
)

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|token|password|passwd|secret|authorization|cookie|credential|credentials)$",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|cookie|credential)"
    r"\s*([:=])\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(
    r"\b(?:nvapi-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b"
)


def redact_text(value: str) -> str:
    value = _BEARER.sub(f"Bearer {REDACTED}", value)
    value = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", value
    )
    return _KNOWN_TOKEN.sub(REDACTED, value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class Runner(Protocol):
    def run(self, probe: Probe) -> ProbeResult: ...


class Reader(Protocol):
    def read(self, key: str) -> ProbeResult: ...


class AllowlistedRunner:
    """Run only an exact code-owned probe with a credential-free environment."""

    _environment = MappingProxyType(
        {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "HOME": "/nonexistent",
            "DOCKER_CONFIG": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
        }
    )

    def run(self, probe: Probe) -> ProbeResult:
        expected = PROBES.get(probe.id)
        if expected is None or probe != expected:
            raise PreflightError(
                f"probe is not an exact allowlisted executable+argv tuple: {probe.id!r}"
            )
        if not Path(probe.executable).is_absolute():  # defense in depth
            raise PreflightError(
                f"allowlisted executable is not absolute: {probe.executable!r}"
            )
        try:
            completed = subprocess.run(
                [probe.executable, *probe.argv],
                check=False,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                cwd="/",
                env=dict(self._environment),
                timeout=10,
                close_fds=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ProbeResult("unavailable", diagnostic=redact_text(str(exc)))
        stdout = completed.stdout
        stderr = completed.stderr
        if (
            len(stdout.encode("utf-8", errors="replace")) > MAX_CAPTURE_BYTES
            or len(stderr.encode("utf-8", errors="replace")) > MAX_CAPTURE_BYTES
        ):
            return ProbeResult(
                "error", diagnostic="probe output exceeded the 1 MiB safety limit"
            )
        if completed.returncode != 0:
            if (
                probe.id == "cache_cleaner"
                and completed.returncode == 1
                and stdout.strip() == "0"
            ):
                return ProbeResult("ok", stdout=stdout, returncode=1)
            diagnostic = (
                stderr.strip() or stdout.strip() or "command returned no diagnostic"
            )[:500]
            return ProbeResult(
                "unavailable",
                diagnostic=redact_text(diagnostic),
                returncode=completed.returncode,
            )
        return ProbeResult("ok", stdout=stdout, returncode=0)


class AllowlistedReader:
    """Read only the fixed host-file set; never follows a caller-provided path."""

    def read(self, key: str) -> ProbeResult:
        path = HOST_FILES.get(key)
        if path is None:
            raise PreflightError(f"host file key is not allowlisted: {key!r}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ProbeResult("unavailable", diagnostic=redact_text(str(exc)))
        if len(content.encode("utf-8", errors="replace")) > MAX_CAPTURE_BYTES:
            return ProbeResult(
                "error", diagnostic="host file exceeded the 1 MiB safety limit"
            )
        return ProbeResult("ok", stdout=content, returncode=0)


def _json_text_object(content: str, context: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (json.JSONDecodeError, ValueError) as exc:
        raise PreflightError(f"cannot load JSON {context}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"JSON root must be an object: {context}")
    return value


def _json_object(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreflightError(f"cannot load JSON {path}: {exc}") from exc
    return _json_text_object(content, str(path))


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _json_object(path)
    if contract.get("schema_version") != 1:
        raise PreflightError("host-preflight contract schema_version must be 1")
    if contract.get("contract_id") != "vss-3.2.1-thor-host-preflight":
        raise PreflightError("unexpected host-preflight contract_id")
    policy = contract.get("inspection_policy")
    required_policy = {
        "default_mode": "plan",
        "network_allowed": False,
        "credentials_allowed": False,
        "container_lifecycle_allowed": False,
        "host_mutation_allowed": False,
    }
    if policy != required_policy:
        raise PreflightError(
            "inspection policy must remain inert, offline, and credential-free"
        )
    required_requirements = {
        "architectures": ["aarch64"],
        "agx_thor_bsp_release": "38.4",
        "igx_thor_bsp_release": "38.5",
        "thor_driver_version": "580.00",
        "docker_minimum": "28.3.3",
        "docker_exclusive_maximum": "29.5.0",
        "compose_minimum": "2.39.1",
        "docker_cgroup_driver": "cgroupfs",
        "official_edge_minimum_available_memory_fraction": "0.80",
        "disk_warning_available_bytes": 161061273600,
        "kernel": {
            "vm.max_map_count": 262144,
            "net.core.rmem_max": 5242880,
            "net.core.wmem_max": 5242880,
        },
    }
    if contract.get("requirements") != required_requirements:
        raise PreflightError(
            "host readiness requirements drifted from the reviewed Thor contract"
        )
    expected_official_edge = {
        "contract_path": "deploy/docker/thor-local/official-edge/contract.json",
        "artifact_lock_path": "deploy/docker/thor-local/official-edge/artifacts.lock.json",
        "contract_id": "vss-3.2.1-thor-official-edge",
    }
    if contract.get("official_edge") != expected_official_edge:
        raise PreflightError("official-edge source routing drifted")
    ports = contract.get("ports")
    if not isinstance(ports, list) or not ports:
        raise PreflightError("contract.ports must be a non-empty list")
    port_values = [entry.get("port") for entry in ports if isinstance(entry, dict)]
    if len(port_values) != len(ports) or len(set(port_values)) != len(ports):
        raise PreflightError("contract ports must be unique objects")
    expected_ports = {
        3001: "thor-ui",
        7777: "public-ingress",
        8000: "alternate-local-llm",
        8001: "vios-mcp",
        8018: "official-edge-rt-vlm",
        9901: "video-analytics-mcp",
        30888: "vios-vst",
        30081: "official-edge-nemotron",
        31000: "nvstreamer",
    }
    if {entry["port"]: entry.get("role") for entry in ports} != expected_ports:
        raise PreflightError("Thor port inventory drifted")
    expected_conflicts = {
        "compose_projects": ["mdx", "vss", "vss-thor"],
        "name_prefixes": ["mdx-", "vss-"],
        "exact_names": [
            "cti-vss-qwen3-vl",
            "datasheet-embedding",
            "vss-nemotron-edge-4b",
        ],
    }
    if contract.get("container_conflicts") != expected_conflicts:
        raise PreflightError("container conflict inventory drifted")
    return contract


def _planned_probe(probe: Probe) -> dict[str, Any]:
    return {
        "id": probe.id,
        "executable": probe.executable,
        "argv": list(probe.argv),
        "purpose": probe.purpose,
    }


def build_plan(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool_id": "thor-host-preflight",
        "mode": "plan",
        "result": "inert_plan",
        "safety": {
            "external_commands_executed": 0,
            "host_files_read": 0,
            "network_allowed": False,
            "credentials_allowed": False,
            "docker_lifecycle_allowed": False,
            "host_mutation_allowed": False,
            "shell_allowed": False,
        },
        "inspect_plan": {
            "commands": [_planned_probe(probe) for probe in PROBES.values()],
            "host_files": [
                {"id": key, "path": str(path)} for key, path in HOST_FILES.items()
            ],
            "repository_files": [
                str(DEFAULT_CONTRACT.relative_to(REPO_ROOT)),
                contract["official_edge"]["contract_path"],
                contract["official_edge"]["artifact_lock_path"],
            ],
            "forbidden_operations": [
                "docker run/start/stop/restart/exec/pull/build/rm",
                "docker compose config/up/down/run/exec/pull/build and other application commands",
                "container creation or helper containers",
                "network requests or registry probes",
                "credential or ambient environment access",
                "host configuration writes",
                "artifact downloads or filesystem tree scans",
            ],
        },
    }


def _version(value: str) -> tuple[int, ...] | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(item or 0) for item in match.groups())


def _version_gate(
    value: str, minimum: str, exclusive_maximum: str | None = None
) -> dict[str, Any]:
    actual = _version(value)
    low = _version(minimum)
    high = _version(exclusive_maximum) if exclusive_maximum else None
    if actual is None or low is None:
        return {
            "value": value,
            "status": "unverified",
            "reason": "version could not be parsed",
        }
    passed = actual >= low and (high is None or actual < high)
    return {
        "value": value,
        "status": "pass" if passed else "blocker",
        "minimum": minimum,
        **({"exclusive_maximum": exclusive_maximum} if exclusive_maximum else {}),
    }


def _result_value(results: Mapping[str, ProbeResult], key: str) -> str | None:
    result = results[key]
    return result.stdout.strip() if result.state == "ok" else None


def _probe_evidence(results: Mapping[str, ProbeResult]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for key, result in results.items():
        entry: dict[str, Any] = {"state": result.state}
        if result.returncode is not None:
            entry["returncode"] = result.returncode
        if result.stdout:
            entry["stdout_sha256"] = hashlib.sha256(result.stdout.encode()).hexdigest()
        if result.diagnostic:
            entry["diagnostic"] = result.diagnostic
        evidence[key] = entry
    return evidence


def _read_all(reader: Reader) -> dict[str, ProbeResult]:
    return {key: reader.read(key) for key in HOST_FILES}


def _os_release(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if value is None:
        return result
    for line in value.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, raw = line.split("=", 1)
        if key in {"ID", "VERSION_ID", "PRETTY_NAME"}:
            result[key.lower()] = raw.strip().strip('"').strip("'")
    return result


def _bsp_gate(
    model: str | None, package_version: str | None, requirements: dict[str, Any]
) -> dict[str, Any]:
    normalized_model = (model or "").rstrip("\x00").strip()
    expected = None
    platform = "unknown_thor_variant"
    if "AGX Thor" in normalized_model:
        platform = "agx_thor"
        expected = requirements["agx_thor_bsp_release"]
    elif "IGX Thor" in normalized_model:
        platform = "igx_thor"
        expected = requirements["igx_thor_bsp_release"]
    actual = None
    if package_version:
        match = re.match(r"(\d+\.\d+)", package_version)
        actual = match.group(1) if match else None
    if expected is None or actual is None:
        status = "unverified"
    else:
        status = "pass" if actual == expected else "blocker"
    return {
        "device_model": normalized_model or None,
        "platform": platform,
        "l4t_package_version": package_version,
        "bsp_release": actual,
        "expected_bsp_release": expected,
        "status": status,
    }


def _gpu_inventory(result: ProbeResult, expected_driver: str) -> dict[str, Any]:
    if result.state != "ok":
        return {
            "status": "unverified",
            "devices": [],
            "expected_driver": expected_driver,
        }
    devices = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    drivers = []
    for line in devices:
        fields = [field.strip() for field in line.split(",")]
        if len(fields) >= 3:
            drivers.append(fields[-2])
    driver_status = (
        "pass"
        if devices and drivers and all(value == expected_driver for value in drivers)
        else "blocker"
    )
    return {
        "status": driver_status,
        "devices": devices,
        "drivers": drivers,
        "expected_driver": expected_driver,
    }


def _integer_file(result: ProbeResult) -> int | None:
    if result.state != "ok" or not re.fullmatch(r"\s*\d+\s*", result.stdout):
        return None
    return int(result.stdout.strip())


def _memory(value: str | None, required_fraction: str) -> dict[str, Any]:
    if value is None:
        return {"status": "unverified"}
    fields: dict[str, int] = {}
    for line in value.splitlines():
        match = re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+)\s+kB", line.strip())
        if match:
            fields[match.group(1)] = int(match.group(2)) * 1024
    if fields.keys() != {"MemTotal", "MemAvailable"} or fields["MemTotal"] <= 0:
        return {
            "status": "unverified",
            "reason": "MemTotal/MemAvailable missing or invalid",
        }
    fraction = fields["MemAvailable"] / fields["MemTotal"]
    required = float(required_fraction)
    return {
        "total_bytes": fields["MemTotal"],
        "available_bytes": fields["MemAvailable"],
        "available_fraction": round(fraction, 6),
        "required_available_fraction_for_official_edge": required_fraction,
        "status": "pass" if fraction >= required else "blocker",
    }


def _disk(value: str | None, warning_bytes: int) -> dict[str, Any]:
    if value is None:
        return {"status": "unverified"}
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return {"status": "unverified", "reason": "df returned no rows"}
    fields = lines[-1].split()
    if len(fields) != 4 or not fields[0].isdigit() or not fields[1].isdigit():
        return {"status": "unverified", "reason": "df row was malformed"}
    available = int(fields[1])
    return {
        "total_bytes": int(fields[0]),
        "available_bytes": available,
        "used_percent": fields[2],
        "mount": fields[3],
        "warning_below_available_bytes": warning_bytes,
        "status": "pass" if available >= warning_bytes else "warning",
    }


def _listening_ports(value: str | None) -> set[int] | None:
    if value is None:
        return None
    ports: set[int] = set()
    for line in value.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        endpoint = fields[3]
        match = re.search(r":(\d+)$", endpoint)
        if match:
            ports.add(int(match.group(1)))
    return ports


def _port_inventory(
    contract: dict[str, Any], value: str | None
) -> list[dict[str, Any]]:
    listening = _listening_ports(value)
    return [
        {
            "port": entry["port"],
            "role": entry["role"],
            "status": "unverified"
            if listening is None
            else ("occupied" if entry["port"] in listening else "free"),
        }
        for entry in contract["ports"]
    ]


def _container_conflicts(contract: dict[str, Any], value: str | None) -> dict[str, Any]:
    if value is None:
        return {"status": "unverified", "conflicts": []}
    rules = contract["container_conflicts"]
    conflicts: list[dict[str, str]] = []
    count = 0
    for line in value.splitlines():
        fields = line.split("\t")
        if len(fields) != 6:
            continue
        count += 1
        container_id, name, image, status, ports, project = fields
        matches = []
        if name in rules["exact_names"]:
            matches.append("exact_name")
        if any(name.startswith(prefix) for prefix in rules["name_prefixes"]):
            matches.append("name_prefix")
        if project in rules["compose_projects"]:
            matches.append("compose_project")
        if matches:
            conflicts.append(
                {
                    "id": container_id,
                    "name": name,
                    "image": image,
                    "status": status,
                    "ports": ports,
                    "compose_project": project,
                    "matched_by": ",".join(matches),
                }
            )
    return {
        "status": "conflict" if conflicts else "clear",
        "container_count": count,
        "conflicts": conflicts,
    }


def _image_rows(value: str | None) -> list[dict[str, str]] | None:
    if value is None:
        return None
    rows = []
    for line in value.splitlines():
        fields = line.split("\t")
        if len(fields) == 4:
            rows.append(
                dict(
                    zip(
                        ("repository", "tag", "digest", "image_id"), fields, strict=True
                    )
                )
            )
    return rows


def _exact_image(
    reference: str, image_id: str | None, rows: list[dict[str, str]] | None
) -> dict[str, Any]:
    if "@" not in reference:
        return {"reference": reference, "status": "invalid_contract"}
    repository, digest = reference.rsplit("@", 1)
    if rows is None:
        return {
            "reference": reference,
            "expected_image_id": image_id,
            "status": "unverified",
        }
    exact = [
        row
        for row in rows
        if row["repository"] == repository
        and row["digest"] == digest
        and (image_id is None or row["image_id"] == image_id)
    ]
    same_repository = [
        row for row in rows if row["repository"] == repository and row not in exact
    ]
    return {
        "reference": reference,
        "expected_image_id": image_id,
        "status": "present_exact" if exact else "missing_exact",
        "conflicting_same_repository": same_repository,
    }


def _official_edge(rows: list[dict[str, str]] | None) -> dict[str, Any]:
    contract = _json_object(OFFICIAL_EDGE_CONTRACT)
    lock = _json_object(OFFICIAL_EDGE_LOCK)
    if contract.get("contract_id") != "vss-3.2.1-thor-official-edge":
        raise PreflightError("unexpected official-edge contract identity")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PreflightError("official-edge lock lacks artifacts object")
    edge = artifacts.get("edge4b")
    cosmos = artifacts.get("cosmos3_nano_bf16")
    if not isinstance(edge, dict) or not isinstance(cosmos, dict):
        raise PreflightError("official-edge lock lacks exact Edge4B/Cosmos3 entries")
    try:
        expected_edge = contract["llm"]["repository"]
        expected_cosmos = contract["vlm"]["artifact_id"]
        contract_images = contract["images"]
    except (KeyError, TypeError) as exc:
        raise PreflightError(
            f"official-edge contract is structurally incomplete: {exc}"
        ) from exc
    if not isinstance(expected_edge, str) or not isinstance(expected_cosmos, str):
        raise PreflightError("official-edge model identities must be strings")
    if not isinstance(contract_images, dict) or not contract_images:
        raise PreflightError("official-edge images must be a non-empty object")
    edge_identity = edge.get("identity")
    cosmos_identity = cosmos.get("identity")
    identity_valid = (
        isinstance(edge_identity, dict)
        and isinstance(cosmos_identity, dict)
        and edge_identity.get("repository") == expected_edge
        and cosmos_identity.get("artifact_id") == expected_cosmos
    )
    lock_complete = (
        lock.get("lock_state") == "complete_exact"
        and edge.get("state") == "locked_exact"
        and cosmos.get("state") == "locked_exact"
        and isinstance(edge.get("tree"), dict)
        and isinstance(cosmos.get("tree"), dict)
        and identity_valid
    )
    images: dict[str, Any] = {}
    for name, entry in contract_images.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("reference"), str):
            raise PreflightError(f"official-edge image entry is malformed: {name!r}")
        image_id = entry.get("image_id")
        if image_id is not None and not isinstance(image_id, str):
            raise PreflightError(f"official-edge image_id is malformed: {name!r}")
        images[name] = _exact_image(entry["reference"], image_id, rows)
    images_exact = all(entry["status"] == "present_exact" for entry in images.values())
    blockers = []
    if not identity_valid:
        blockers.append("artifact identities do not match the official-edge contract")
    if not lock_complete:
        blockers.append(
            f"artifact lock is {lock.get('lock_state')!r}, not 'complete_exact'"
        )
    if not images_exact:
        blockers.append(
            "one or more exact digest-and-image identities are not locally verified"
        )
    blockers.append(
        "artifact filesystem trees were not scanned by this inert inventory; run official_edge.py audit only after reviewed paths exist"
    )
    return {
        "contract_id": contract["contract_id"],
        "contract_sha256": hashlib.sha256(
            OFFICIAL_EDGE_CONTRACT.read_bytes()
        ).hexdigest(),
        "artifact_lock_sha256": hashlib.sha256(
            OFFICIAL_EDGE_LOCK.read_bytes()
        ).hexdigest(),
        "lock_state": lock.get("lock_state"),
        "artifacts": {
            "edge4b": {"identity": edge_identity, "state": edge.get("state")},
            "cosmos3_nano_bf16": {
                "identity": cosmos_identity,
                "state": cosmos.get("state"),
            },
        },
        "images": images,
        "filesystem_trees_verified": False,
        "runtime_launch_ready": False,
        "status": "blocker",
        "blockers": blockers,
    }


def _daemon_config(result: ProbeResult) -> dict[str, Any]:
    if result.state != "ok":
        return {"status": "unverified"}
    try:
        value = _json_text_object(result.stdout, "/etc/docker/daemon.json")
    except PreflightError as exc:
        return {"status": "blocker", "reason": str(exc)}
    exec_opts = value.get("exec-opts", [])
    cgroup = isinstance(exec_opts, list) and "native.cgroupdriver=cgroupfs" in exec_opts
    features = value.get("features") if isinstance(value.get("features"), dict) else {}
    return {
        "cgroupfs_configured": cgroup,
        "containerd_snapshotter": features.get("containerd-snapshotter", "unspecified"),
        "status": "pass" if cgroup else "blocker",
    }


def inspect_host(
    contract: dict[str, Any], runner: Runner, reader: Reader
) -> dict[str, Any]:
    results = {key: runner.run(probe) for key, probe in PROBES.items()}
    files = _read_all(reader)
    requirements = contract["requirements"]
    architecture = _result_value(results, "architecture")
    l4t = _result_value(results, "l4t_package")
    device_model = (
        files["device_model"].stdout if files["device_model"].state == "ok" else None
    )
    docker_versions = (_result_value(results, "docker_version") or "|").split("|", 1)
    if len(docker_versions) != 2:
        docker_versions = ["", ""]
    compose = _result_value(results, "compose_version") or ""
    toolkit = _result_value(results, "toolkit_package")
    reported_cgroup = _result_value(results, "docker_cgroup")
    runtimes_raw = _result_value(results, "docker_runtimes")
    try:
        runtimes = sorted(json.loads(runtimes_raw).keys()) if runtimes_raw else []
    except (json.JSONDecodeError, AttributeError):
        runtimes = []
    rows = _image_rows(_result_value(results, "images"))
    kernel_values = {
        "vm.max_map_count": _integer_file(files["vm_max_map_count"]),
        "net.core.rmem_max": _integer_file(files["net_core_rmem_max"]),
        "net.core.wmem_max": _integer_file(files["net_core_wmem_max"]),
    }
    kernel_gates = {
        key: {
            "value": kernel_values[key],
            "required_minimum": required,
            "status": "unverified"
            if kernel_values[key] is None
            else ("pass" if kernel_values[key] >= required else "blocker"),
        }
        for key, required in requirements["kernel"].items()
    }
    daemon = _daemon_config(files["docker_daemon"])
    report: dict[str, Any] = {
        "schema_version": 1,
        "tool_id": "thor-host-preflight",
        "mode": "inspect",
        "safety": {
            "external_commands_executed": len(PROBES),
            "host_files_read": len(HOST_FILES),
            "network_allowed": False,
            "credentials_allowed": False,
            "docker_lifecycle_allowed": False,
            "host_mutation_allowed": False,
            "shell_allowed": False,
        },
        "platform": {
            "architecture": {
                "value": architecture,
                "status": "pass"
                if architecture in requirements["architectures"]
                else ("unverified" if architecture is None else "blocker"),
            },
            "kernel": _result_value(results, "kernel"),
            "os": _os_release(
                files["os_release"].stdout
                if files["os_release"].state == "ok"
                else None
            ),
            "tegra_release": files["tegra_release"].stdout.strip()
            if files["tegra_release"].state == "ok"
            else None,
            "bsp": _bsp_gate(device_model, l4t, requirements),
            "gpu": _gpu_inventory(results["gpu"], requirements["thor_driver_version"]),
        },
        "resources": {
            "memory": _memory(
                files["meminfo"].stdout if files["meminfo"].state == "ok" else None,
                requirements["official_edge_minimum_available_memory_fraction"],
            ),
            "disk_root": _disk(
                _result_value(results, "disk_root"),
                requirements["disk_warning_available_bytes"],
            ),
        },
        "software": {
            "docker_client": _version_gate(
                docker_versions[0],
                requirements["docker_minimum"],
                requirements["docker_exclusive_maximum"],
            ),
            "docker_server": _version_gate(
                docker_versions[1],
                requirements["docker_minimum"],
                requirements["docker_exclusive_maximum"],
            ),
            "compose": _version_gate(compose, requirements["compose_minimum"]),
            "nvidia_container_toolkit": {
                "value": toolkit,
                "status": "pass" if toolkit else "unverified",
            },
            "nvidia_runtime": {
                "runtimes": runtimes,
                "status": "pass"
                if "nvidia" in runtimes
                else (
                    "unverified"
                    if results["docker_runtimes"].state != "ok"
                    else "blocker"
                ),
            },
            "docker_cgroup": {
                "reported": {
                    "value": reported_cgroup,
                    "status": "pass"
                    if reported_cgroup == requirements["docker_cgroup_driver"]
                    else ("unverified" if reported_cgroup is None else "blocker"),
                },
                "daemon_config": daemon,
            },
        },
        "kernel_prerequisites": kernel_gates,
        "cache_cleaner": {
            "process_count": int(_result_value(results, "cache_cleaner") or 0)
            if (_result_value(results, "cache_cleaner") or "").isdigit()
            else None,
            "status": "pass"
            if (_result_value(results, "cache_cleaner") or "") not in {"", "0"}
            else (
                "unverified" if results["cache_cleaner"].state != "ok" else "blocker"
            ),
        },
        "ports": _port_inventory(contract, _result_value(results, "ports")),
        "containers": _container_conflicts(
            contract, _result_value(results, "containers")
        ),
        "official_edge": _official_edge(rows),
        "probe_evidence": _probe_evidence(results),
        "host_file_evidence": _probe_evidence(files),
    }
    statuses: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "status" and isinstance(item, str):
                    statuses.append(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(report)
    blockers = sum(
        status in {"blocker", "conflict", "missing_exact"} for status in statuses
    )
    unverified = sum(status == "unverified" for status in statuses)
    warnings = sum(status in {"warning", "occupied"} for status in statuses)
    report["summary"] = {
        "result": "blocker" if blockers else ("unverified" if unverified else "ready"),
        "blocker_count": blockers,
        "unverified_count": unverified,
        "warning_count": warnings,
        "runtime_qualification_started": False,
    }
    return redact(report)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "inspect"), default="plan")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        contract = load_contract()
        if args.mode == "plan":
            report = build_plan(contract)
        else:
            report = inspect_host(contract, AllowlistedRunner(), AllowlistedReader())
        print(json.dumps(redact(report), indent=2, sort_keys=True))
    except PreflightError as exc:
        print(
            json.dumps(
                {"result": "error", "error": redact_text(str(exc))}, sort_keys=True
            ),
            file=sys.stderr,
        )
        return 2
    if args.mode == "inspect" and report["summary"]["result"] == "blocker":
        return 1
    if args.mode == "inspect" and report["summary"]["result"] == "unverified":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
