#!/usr/bin/env python3
"""Collect deterministic, read-only evidence for four Thor prerequisite oracles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

sys.dont_write_bytecode = True


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_CONTRACT = HERE / "contract.json"
DEFAULT_SCHEMA = HERE / "result.schema.json"
EXPECTED_RESULT_SCHEMA_SHA256 = (
    "a187f6023a65f38216c92fb79f5788bbebc346e84a921125c677504a2b91c0aa"
)
MAX_CAPTURE_BYTES = 1024 * 1024
EXPECTED_ACKNOWLEDGEMENT = "I_ACCEPT_READ_ONLY_HOST_PREREQUISITE_EVIDENCE"
SYSTEM_NGC_CANDIDATES = (Path("/usr/bin/ngc"), Path("/usr/local/bin/ngc"))
UNAVAILABLE_NGC_EXECUTABLE = "/nonexistent/vss-host-prerequisite-ngc"
INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
PRODUCT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+/-]{0,79}$")
DRIVER_RE = re.compile(r"^\d+\.\d+$")
SENSITIVE_PRODUCT_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|password|passwd|secret|authorization|cookie|credential|"
    r"nvapi-|hf_[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,})"
)


class EvidenceError(RuntimeError):
    """The evidence request, source contract, or observation is invalid."""


@dataclass(frozen=True)
class Probe:
    id: str
    executable: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ProbeResult:
    state: str
    stdout: str = ""
    error: str | None = None


def _probe(probe_id: str, executable: str, *argv: str) -> Probe:
    if not Path(executable).is_absolute():
        raise AssertionError(f"non-absolute probe executable: {probe_id}")
    return Probe(probe_id, executable, tuple(argv))


def _ngc_executable(candidates: tuple[Path, ...] = SYSTEM_NGC_CANDIDATES) -> str:
    """Select a fixed, root-owned system NGC executable after authorization."""

    for candidate in candidates:
        if candidate not in SYSTEM_NGC_CANDIDATES:
            continue
        try:
            metadata = candidate.lstat()
        except OSError:
            continue
        mode = metadata.st_mode
        if (
            not stat.S_ISREG(mode)
            or metadata.st_uid != 0
            or not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            or mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            continue
        return str(candidate)
    # A fixed nonexistent path yields a sanitized unavailable observation and
    # cannot accidentally execute a rejected candidate at a conventional path.
    return UNAVAILABLE_NGC_EXECUTABLE


def build_probes(
    ngc_executable: str = UNAVAILABLE_NGC_EXECUTABLE,
) -> Mapping[str, Probe]:
    probes = (
        _probe("architecture", "/usr/bin/uname", "-m"),
        _probe(
            "gpu",
            "/usr/sbin/nvidia-smi",
            "--query-gpu=index,name,driver_version",
            "--format=csv,noheader",
        ),
        _probe(
            "docker_version",
            "/usr/bin/docker",
            "version",
            "--format",
            "{{.Client.Version}}|{{.Server.Version}}",
        ),
        _probe(
            "compose_version",
            "/usr/bin/docker",
            "compose",
            "version",
            "--short",
        ),
        _probe("toolkit_version", "/usr/bin/nvidia-ctk", "--version"),
        _probe("ngc_version", ngc_executable, "--version"),
        _probe("cpu_count", "/usr/bin/getconf", "_NPROCESSORS_ONLN"),
        _probe(
            "disk_root",
            "/usr/bin/df",
            "-B1",
            "--output=size,avail,target",
            "/",
        ),
        _probe(
            "block_devices",
            "/usr/bin/lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,TYPE,SIZE,ROTA,MOUNTPOINTS",
        ),
        _probe("active_route", "/usr/sbin/ip", "-j", "route", "get", "1.1.1.1"),
        _probe(
            "browser_port",
            "/usr/bin/ss",
            "-H",
            "-ltn",
            "sport",
            "=",
            ":7777",
        ),
    )
    return MappingProxyType({probe.id: probe for probe in probes})


PROBES = build_probes()
HOST_FILES = MappingProxyType(
    {
        "device_model": Path("/proc/device-tree/model"),
        "tegra_release": Path("/etc/nv_tegra_release"),
        "meminfo": Path("/proc/meminfo"),
    }
)


class Runner(Protocol):
    def run(self, probe: Probe) -> ProbeResult: ...


class Reader(Protocol):
    def read(self, key: str) -> ProbeResult: ...


class NetworkInspector(Protocol):
    def inspect(self, active_route_interface: str | None) -> dict[str, Any]: ...


class AllowlistedRunner:
    """Execute only code-owned informational commands in a sterile environment."""

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

    def __init__(self, probes: Mapping[str, Probe] = PROBES) -> None:
        self._probes = probes

    def run(self, probe: Probe) -> ProbeResult:
        if self._probes.get(probe.id) != probe:
            raise EvidenceError(f"probe is not the exact allowlisted tuple: {probe.id}")
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
        except FileNotFoundError:
            return ProbeResult("unavailable", error="executable_unavailable")
        except (OSError, subprocess.TimeoutExpired):
            return ProbeResult("unavailable", error="probe_unavailable")
        stdout_bytes = completed.stdout.encode("utf-8", errors="replace")
        stderr_bytes = completed.stderr.encode("utf-8", errors="replace")
        if (
            len(stdout_bytes) > MAX_CAPTURE_BYTES
            or len(stderr_bytes) > MAX_CAPTURE_BYTES
        ):
            return ProbeResult("unavailable", error="output_limit_exceeded")
        if completed.returncode != 0:
            return ProbeResult("unavailable", error="nonzero_exit")
        return ProbeResult("ok", stdout=completed.stdout)


class AllowlistedReader:
    def read(self, key: str) -> ProbeResult:
        path = HOST_FILES.get(key)
        if path is None:
            raise EvidenceError(f"host file key is not allowlisted: {key}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ProbeResult("unavailable", error="host_file_unavailable")
        if len(content.encode("utf-8", errors="replace")) > MAX_CAPTURE_BYTES:
            return ProbeResult("unavailable", error="output_limit_exceeded")
        return ProbeResult("ok", stdout=content)


def _safe_sysfs_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeError):
        return None
    return value if len(value) <= 64 else None


class SysfsNetworkInspector:
    """Summarize link capacity without emitting names, addresses, MACs, or SSIDs."""

    root = Path("/sys/class/net")

    def _interface(self, name: str) -> dict[str, Any] | None:
        if not INTERFACE_RE.fullmatch(name):
            return None
        entry = self.root / name
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            return None
        if not str(resolved).startswith("/sys/devices/"):
            return None
        # A physical device and ARPHRD_ETHER type exclude Docker bridges,
        # veths, loopback, and CAN links.
        if not (entry / "device").exists() or _safe_sysfs_text(entry / "type") != "1":
            return None
        carrier = _safe_sysfs_text(entry / "carrier") == "1"
        speed_text = _safe_sysfs_text(entry / "speed")
        try:
            speed = int(speed_text) if speed_text is not None else None
        except ValueError:
            speed = None
        if speed is not None and speed <= 0:
            speed = None
        return {"carrier": carrier, "speed_mbps": speed}

    def inspect(self, active_route_interface: str | None) -> dict[str, Any]:
        physical: list[dict[str, Any]] = []
        try:
            entries = sorted(self.root.iterdir(), key=lambda item: item.name)
        except OSError:
            entries = []
        for entry in entries:
            observation = self._interface(entry.name)
            if observation is not None:
                physical.append(observation)
        qualifying = [
            item
            for item in physical
            if item["carrier"]
            and item["speed_mbps"] is not None
            and item["speed_mbps"] >= 1000
        ]
        active = self._interface(active_route_interface or "")
        active_speed = active["speed_mbps"] if active is not None else None
        return {
            "physical_interface_count": len(physical),
            "carrier_up_physical_interface_count": sum(
                1 for item in physical if item["carrier"]
            ),
            "qualifying_physical_link_count": len(qualifying),
            "maximum_qualifying_speed_mbps": max(
                (item["speed_mbps"] for item in qualifying), default=None
            ),
            "active_route_interface_class": (
                "physical" if active is not None else "virtual_or_unresolved"
            ),
            "active_route_reported_speed_mbps": active_speed,
            "active_route_meets_minimum": (
                active_speed >= 1000 if active_speed is not None else None
            ),
            "interface_identifiers_emitted": False,
        }


def _json_object(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key in {path.name}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot load JSON contract: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root is not an object: {path.name}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _json_object(path)
    if contract.get("schema_version") != 1 or contract.get("contract_id") != (
        "vss-3.2.1-thor-host-prerequisite-evidence"
    ):
        raise EvidenceError("unexpected host-prerequisite evidence contract")
    policy = contract.get("inspection_policy")
    if policy != {
        "default_mode": "plan",
        "acknowledgement": EXPECTED_ACKNOWLEDGEMENT,
        "network_requests_allowed": False,
        "credentials_allowed": False,
        "container_lifecycle_allowed": False,
        "docker_data_mutation_allowed": False,
        "host_mutation_allowed": False,
        "raw_probe_output_allowed": False,
    }:
        raise EvidenceError("inspection policy drifted")
    pairs = contract.get("source", {}).get("pairs")
    expected_ids = {
        "prereq.platform.validated-gpus",
        "prereq.platform.agx-thor-software",
        "prereq.platform.toolchain-versions",
        "prereq.platform.capacity-and-access",
    }
    if (
        not isinstance(pairs, list)
        or {item.get("capability_id") for item in pairs} != expected_ids
    ):
        raise EvidenceError("contract must bind exactly four prerequisite capabilities")
    return contract


def load_bound_oracles(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    relative = contract["source"]["path"]
    if relative != "deploy/docker/thor-local/parity/capability-oracles.json":
        raise EvidenceError("oracle source path drifted")
    source = _json_object(REPO_ROOT / relative)
    rows = source.get("oracles")
    if not isinstance(rows, list):
        raise EvidenceError("oracle source has no rows")
    by_id = {row.get("capability_id"): row for row in rows if isinstance(row, dict)}
    selected: dict[str, dict[str, Any]] = {}
    for binding in contract["source"]["pairs"]:
        capability_id = binding["capability_id"]
        row = by_id.get(capability_id)
        if not isinstance(row, dict):
            raise EvidenceError(f"bound oracle is absent: {capability_id}")
        ledger = row.get("ledger_binding")
        row_contract = ledger.get("contract") if isinstance(ledger, dict) else None
        if (
            row.get("oracle_id") != binding["oracle_id"]
            or row.get("profile") != binding["oracle_profile"]
            or row.get("mode") != binding["oracle_mode"]
            or _sha256(row) != binding["oracle_canonical_sha256"]
            or _sha256(row_contract) != binding["contract_canonical_sha256"]
        ):
            raise EvidenceError(f"bound oracle drifted: {capability_id}")
        selected[capability_id] = row
    return selected


def _result(value: ProbeResult) -> str | None:
    return value.stdout.strip() if value.state == "ok" else None


def _version(value: str | None) -> tuple[int, int, int] | None:
    match = VERSION_RE.search(value or "")
    return tuple(map(int, match.groups())) if match else None


def _version_text(value: tuple[int, int, int] | None) -> str | None:
    return ".".join(map(str, value)) if value is not None else None


def _status(condition: bool | None) -> str:
    if condition is None:
        return "unknown"
    return "pass" if condition else "fail"


def _assertion(
    assertion_id: str, expected: Any, observed: Any, condition: bool | None
) -> dict[str, Any]:
    return {
        "id": assertion_id,
        "expected": expected,
        "observed": observed,
        "status": _status(condition),
    }


def _capability(
    binding: dict[str, Any], assertions: list[dict[str, Any]]
) -> dict[str, Any]:
    statuses = {item["status"] for item in assertions}
    status = (
        "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    )
    return {
        "capability_id": binding["capability_id"],
        "oracle_id": binding["oracle_id"],
        "oracle_profile": binding["oracle_profile"],
        "oracle_mode": binding["oracle_mode"],
        "oracle_canonical_sha256": binding["oracle_canonical_sha256"],
        "contract_canonical_sha256": binding["contract_canonical_sha256"],
        "assertions": assertions,
        "contract_status": status,
        "contract_satisfied": (
            True if status == "pass" else False if status == "fail" else None
        ),
    }


def _meminfo(value: str | None) -> tuple[int | None, int | None]:
    parsed: dict[str, int] = {}
    for line in (value or "").splitlines():
        match = re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+)\s+kB", line.strip())
        if match:
            parsed[match.group(1)] = int(match.group(2)) * 1024
    return parsed.get("MemTotal"), parsed.get("MemAvailable")


def _disk(value: str | None) -> tuple[int | None, int | None]:
    lines = [line.split() for line in (value or "").splitlines() if line.strip()]
    if len(lines) != 2 or len(lines[1]) < 3 or lines[1][-1] != "/":
        return None, None
    try:
        return int(lines[1][0]), int(lines[1][1])
    except ValueError:
        return None, None


def _root_nonrotational(value: str | None) -> bool | None:
    try:
        document = json.loads(value or "")
    except json.JSONDecodeError:
        return None

    def visit(node: Any, inherited: bool | None = None) -> bool | None:
        if not isinstance(node, dict):
            return None
        rota = node.get("rota")
        current = rota if isinstance(rota, bool) else inherited
        mounts = node.get("mountpoints")
        if isinstance(mounts, list) and "/" in mounts:
            return None if current is None else not current
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                result = visit(child, current)
                if result is not None:
                    return result
        return None

    devices = document.get("blockdevices") if isinstance(document, dict) else None
    if not isinstance(devices, list):
        return None
    for device in devices:
        result = visit(device)
        if result is not None:
            return result
    return None


def _active_route_interface(value: str | None) -> str | None:
    try:
        document = json.loads(value or "")
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(document, list)
        or len(document) != 1
        or not isinstance(document[0], dict)
    ):
        return None
    interface = document[0].get("dev")
    return (
        interface
        if isinstance(interface, str) and INTERFACE_RE.fullmatch(interface)
        else None
    )


def _bsp(value: str | None) -> str | None:
    match = re.search(r"# R(\d+) \(release\), REVISION: (\d+)\.(\d+)", value or "")
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _platform(value: str | None) -> str | None:
    normalized = (value or "").replace("\x00", "").strip()
    if normalized == "NVIDIA Jetson AGX Thor Developer Kit":
        return "AGX Thor"
    if "IGX Thor" in normalized:
        return "IGX Thor"
    return "other" if normalized else None


def _architecture(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if normalized in {"aarch64", "x86_64"}:
        return normalized
    return "other" if normalized else None


def _gpu(value: str | None) -> tuple[list[str], list[str]]:
    names: list[str] = []
    drivers: list[str] = []
    for line in (value or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        # Emit only bounded, character-allowlisted identity fields. Arbitrary
        # command output, assignments, token-shaped values, and diagnostics
        # never cross this parser boundary.
        if (
            not PRODUCT_RE.fullmatch(parts[1])
            or SENSITIVE_PRODUCT_RE.search(parts[1])
            or not DRIVER_RE.fullmatch(parts[2])
        ):
            continue
        names.append(parts[1])
        drivers.append(parts[2])
    return names, drivers


def _observations(
    runner: Runner,
    reader: Reader,
    network: NetworkInspector,
    probes: Mapping[str, Probe],
) -> dict[str, Any]:
    command = {probe_id: runner.run(probe) for probe_id, probe in probes.items()}
    files = {key: reader.read(key) for key in HOST_FILES}
    gpu_names, gpu_drivers = _gpu(_result(command["gpu"]))
    docker = (_result(command["docker_version"]) or "").split("|")
    docker_client = _version(docker[0]) if len(docker) == 2 else None
    docker_server = _version(docker[1]) if len(docker) == 2 else None
    compose = _version(_result(command["compose_version"]))
    toolkit = _version(_result(command["toolkit_version"]))
    ngc = _version(_result(command["ngc_version"]))
    total_memory, available_memory = _meminfo(_result(files["meminfo"]))
    disk_total, disk_available = _disk(_result(command["disk_root"]))
    route_interface = _active_route_interface(_result(command["active_route"]))
    network_observation = network.inspect(route_interface)
    try:
        cpu_count = int(_result(command["cpu_count"]) or "")
    except ValueError:
        cpu_count = None
    return {
        "platform": {
            "architecture": _architecture(_result(command["architecture"])),
            "platform_class": _platform(_result(files["device_model"])),
            "bsp_release": _bsp(_result(files["tegra_release"])),
            "gpu_count": len(gpu_names) if command["gpu"].state == "ok" else None,
            "gpu_product_names": gpu_names,
            "gpu_driver_versions": sorted(set(gpu_drivers)),
        },
        "toolchain": {
            "docker_client": _version_text(docker_client),
            "docker_server": _version_text(docker_server),
            "docker_compose": _version_text(compose),
            "nvidia_container_toolkit": _version_text(toolkit),
            "ngc_cli": _version_text(ngc),
        },
        "capacity": {
            "online_cpu_count": cpu_count,
            "total_memory_bytes": total_memory,
            "root_filesystem_total_bytes": disk_total,
            "root_backing_device_nonrotational": _root_nonrotational(
                _result(command["block_devices"])
            ),
            "browser_tcp_port": 7777,
            "browser_tcp_port_available": (
                not bool((_result(command["browser_port"]) or "").strip())
                if command["browser_port"].state == "ok"
                else None
            ),
            "network": network_observation,
        },
        "operational_admission": {
            "available_memory_bytes": available_memory,
            "total_memory_bytes": total_memory,
            "available_memory_fraction": (
                f"{available_memory / total_memory:.6f}"
                if available_memory is not None and total_memory
                else None
            ),
            "model_start_minimum_available_memory_bytes": 53687091200,
            "model_start_memory_satisfied": (
                available_memory >= 53687091200
                if available_memory is not None
                else None
            ),
            "stack_start_minimum_available_memory_bytes": 21474836480,
            "stack_start_memory_satisfied": (
                available_memory >= 21474836480
                if available_memory is not None
                else None
            ),
            "official_edge_minimum_available_memory_fraction": "0.80",
            "official_edge_memory_satisfied": (
                available_memory * 100 >= total_memory * 80
                if available_memory is not None and total_memory
                else None
            ),
            "root_filesystem_available_bytes": disk_available,
            "free_disk_warning_bytes": 161061273600,
            "free_disk_warning_satisfied": (
                disk_available >= 161061273600 if disk_available is not None else None
            ),
            "contract_satisfaction_independent": True,
        },
    }


def _capabilities(
    contract: dict[str, Any], observed: dict[str, Any]
) -> list[dict[str, Any]]:
    bindings = {item["capability_id"]: item for item in contract["source"]["pairs"]}
    platform = observed["platform"]
    toolchain = observed["toolchain"]
    capacity = observed["capacity"]
    network = capacity["network"]

    validated = _capability(
        bindings["prereq.platform.validated-gpus"],
        [
            _assertion(
                "validated-platform",
                "AGX Thor",
                platform["platform_class"],
                (
                    platform["platform_class"] == "AGX Thor"
                    if platform["platform_class"]
                    else None
                ),
            )
        ],
    )
    software = _capability(
        bindings["prereq.platform.agx-thor-software"],
        [
            _assertion(
                "platform",
                "AGX Thor",
                platform["platform_class"],
                (
                    platform["platform_class"] == "AGX Thor"
                    if platform["platform_class"]
                    else None
                ),
            ),
            _assertion(
                "bsp-release",
                "38.4",
                platform["bsp_release"],
                platform["bsp_release"] == "38.4" if platform["bsp_release"] else None,
            ),
            _assertion(
                "driver",
                "580.00",
                platform["gpu_driver_versions"],
                (
                    all(item == "580.00" for item in platform["gpu_driver_versions"])
                    if platform["gpu_driver_versions"]
                    else None
                ),
            ),
        ],
    )
    parsed_versions = {key: _version(value) for key, value in toolchain.items()}
    toolchain_row = _capability(
        bindings["prereq.platform.toolchain-versions"],
        [
            _assertion(
                "docker",
                ">=28.3.3,<29.5.0",
                toolchain["docker_server"],
                (
                    (28, 3, 3) <= parsed_versions["docker_server"] < (29, 5, 0)
                    if parsed_versions["docker_server"]
                    else None
                ),
            ),
            _assertion(
                "docker-compose",
                ">=2.39.1",
                toolchain["docker_compose"],
                (
                    parsed_versions["docker_compose"] >= (2, 39, 1)
                    if parsed_versions["docker_compose"]
                    else None
                ),
            ),
            _assertion(
                "nvidia-container-toolkit",
                ">=1.17.8",
                toolchain["nvidia_container_toolkit"],
                (
                    parsed_versions["nvidia_container_toolkit"] >= (1, 17, 8)
                    if parsed_versions["nvidia_container_toolkit"]
                    else None
                ),
            ),
            _assertion(
                "ngc-cli",
                ">=4.10.0",
                toolchain["ngc_cli"],
                (
                    parsed_versions["ngc_cli"] >= (4, 10, 0)
                    if parsed_versions["ngc_cli"]
                    else None
                ),
            ),
            _assertion(
                "warehouse-docker",
                ">=28.3.3,<29.5.0",
                toolchain["docker_server"],
                (
                    (28, 3, 3) <= parsed_versions["docker_server"] < (29, 5, 0)
                    if parsed_versions["docker_server"]
                    else None
                ),
            ),
            _assertion(
                "warehouse-compose",
                ">=2.39.1",
                toolchain["docker_compose"],
                (
                    parsed_versions["docker_compose"] >= (2, 39, 1)
                    if parsed_versions["docker_compose"]
                    else None
                ),
            ),
            _assertion(
                "warehouse-ngc-cli",
                ">=4.10.0",
                toolchain["ngc_cli"],
                (
                    parsed_versions["ngc_cli"] >= (4, 10, 0)
                    if parsed_versions["ngc_cli"]
                    else None
                ),
            ),
        ],
    )
    architecture = platform["architecture"]
    cpu_condition = (
        True
        if architecture == "aarch64"
        else (
            capacity["online_cpu_count"] >= 18
            if isinstance(capacity["online_cpu_count"], int)
            else None
        )
    )
    memory_condition = (
        capacity["total_memory_bytes"] >= 128_000_000_000
        if capacity["total_memory_bytes"] is not None
        else None
    )
    storage_condition = (
        capacity["root_filesystem_total_bytes"] >= 1_000_000_000_000
        and capacity["root_backing_device_nonrotational"] is True
        if capacity["root_filesystem_total_bytes"] is not None
        and capacity["root_backing_device_nonrotational"] is not None
        else None
    )
    network_condition = network["qualifying_physical_link_count"] > 0
    gpu_condition = (
        platform["gpu_count"] in {1, 2} if platform["gpu_count"] is not None else None
    )
    capacity_row = _capability(
        bindings["prereq.platform.capacity-and-access"],
        [
            _assertion(
                "cpu",
                "18-online-cpus-x86-only",
                capacity["online_cpu_count"],
                cpu_condition,
            ),
            _assertion(
                "ram", 128_000_000_000, capacity["total_memory_bytes"], memory_condition
            ),
            _assertion(
                "ssd",
                {"minimum_bytes": 1_000_000_000_000, "nonrotational": True},
                {
                    "bytes": capacity["root_filesystem_total_bytes"],
                    "nonrotational": capacity["root_backing_device_nonrotational"],
                },
                storage_condition,
            ),
            _assertion(
                "network",
                {"minimum_mbps": 1000, "physical_link": True},
                {
                    "qualifying_links": network["qualifying_physical_link_count"],
                    "maximum_mbps": network["maximum_qualifying_speed_mbps"],
                },
                network_condition,
            ),
            _assertion(
                "recommended-gpus",
                "1_or_2_by_profile",
                platform["gpu_count"],
                gpu_condition,
            ),
            _assertion(
                "browser-port",
                {"port": 7777, "available": True},
                {"port": 7777, "available": capacity["browser_tcp_port_available"]},
                capacity["browser_tcp_port_available"],
            ),
            _assertion(
                "warehouse-ram",
                128_000_000_000,
                capacity["total_memory_bytes"],
                memory_condition,
            ),
            _assertion(
                "warehouse-ssd",
                {"minimum_bytes": 1_000_000_000_000, "nonrotational": True},
                {
                    "bytes": capacity["root_filesystem_total_bytes"],
                    "nonrotational": capacity["root_backing_device_nonrotational"],
                },
                storage_condition,
            ),
            _assertion(
                "warehouse-network",
                {"minimum_mbps": 1000, "physical_link": True},
                {
                    "qualifying_links": network["qualifying_physical_link_count"],
                    "maximum_mbps": network["maximum_qualifying_speed_mbps"],
                },
                network_condition,
            ),
        ],
    )
    return [validated, software, toolchain_row, capacity_row]


def _operational_status(observed: dict[str, Any]) -> str:
    admission = observed["operational_admission"]
    required = (
        admission["model_start_memory_satisfied"],
        admission["stack_start_memory_satisfied"],
        admission["official_edge_memory_satisfied"],
        admission["free_disk_warning_satisfied"],
    )
    if any(item is False for item in required):
        return "blocked_or_warning"
    if any(item is None for item in required):
        return "unknown"
    return "ready"


def _load_locked_result_schema(
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    if schema_path != DEFAULT_SCHEMA:
        raise EvidenceError("result schema path is not the locked package schema")
    try:
        schema_bytes = schema_path.read_bytes()
    except OSError as exc:
        raise EvidenceError("result schema is unavailable") from exc
    if hashlib.sha256(schema_bytes).hexdigest() != EXPECTED_RESULT_SCHEMA_SHA256:
        raise EvidenceError("result schema raw-byte identity drifted")
    schema = _json_object(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise EvidenceError("result schema is invalid") from exc
    return schema


def _validate(result: dict[str, Any], schema_path: Path = DEFAULT_SCHEMA) -> None:
    schema = _load_locked_result_schema(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise EvidenceError(
            f"result failed schema validation at {list(errors[0].absolute_path)}"
        )


def build_plan(contract: dict[str, Any]) -> dict[str, Any]:
    load_bound_oracles(contract)
    result = {
        "schema_version": 1,
        "package": "host-prerequisite-evidence",
        "mode": "plan",
        "result": "inert_plan",
        "capability_pairs": [
            {"capability_id": item["capability_id"], "oracle_id": item["oracle_id"]}
            for item in contract["source"]["pairs"]
        ],
        "safety": {
            "read_only": True,
            "network_requests": False,
            "credential_access": False,
            "container_lifecycle": False,
            "docker_data_mutation": False,
            "host_mutation": False,
            "raw_probe_output_emitted": False,
            "sensitive_identifiers_emitted": False,
            "external_commands_executed": 0,
            "host_files_read": 0,
        },
        "planned_probe_ids": list(PROBES),
        "planned_host_source_ids": [*HOST_FILES, "sysfs_network_summary"],
        "evidence_emitted": False,
    }
    _validate(result)
    return result


def collect_evidence(
    contract: dict[str, Any],
    runner: Runner,
    reader: Reader,
    network: NetworkInspector,
    probes: Mapping[str, Probe] = PROBES,
) -> dict[str, Any]:
    load_bound_oracles(contract)
    observed = _observations(runner, reader, network, probes)
    capabilities = _capabilities(contract, observed)
    statuses = [item["contract_status"] for item in capabilities]
    contract_result = (
        "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "package": "host-prerequisite-evidence",
        "mode": "inspect",
        "result": contract_result,
        "target": "VSS 3.2.1 Thor-local prerequisite oracles",
        "source_binding": {
            "path": contract["source"]["path"],
            "pair_count": 4,
            "selected_oracle_set_sha256": _sha256(
                [
                    item["oracle_canonical_sha256"]
                    for item in contract["source"]["pairs"]
                ]
            ),
        },
        "safety": {
            "read_only": True,
            "network_requests": False,
            "credential_access": False,
            "container_lifecycle": False,
            "docker_data_mutation": False,
            "host_mutation": False,
            "raw_probe_output_emitted": False,
            "sensitive_identifiers_emitted": False,
            "external_commands_executed": len(probes),
            "host_files_read": len(HOST_FILES),
        },
        "semantics": contract["interpretation"],
        "observations": observed,
        "capabilities": capabilities,
        "summary": {
            "contract_result": contract_result,
            "contracts_passed": statuses.count("pass"),
            "contracts_failed": statuses.count("fail"),
            "contracts_unknown": statuses.count("unknown"),
            "operational_admission": _operational_status(observed),
            "host_prerequisite_evidence_emitted": True,
            "runtime_feature_qualification_performed": False,
            "operational_admission_changes_contract_result": False,
        },
    }
    result["evidence_sha256"] = _sha256(result)
    _validate(result)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "inspect"), default="plan")
    parser.add_argument("--acknowledgement")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        contract = load_contract()
        if args.mode == "plan":
            result = build_plan(contract)
        else:
            if args.acknowledgement != EXPECTED_ACKNOWLEDGEMENT:
                raise EvidenceError(
                    "inspect requires the exact read-only acknowledgement"
                )
            # Validate every checked-in source binding before touching any NGC
            # candidate path. Import and rejected acknowledgements remain free
            # of host executable discovery and metadata inspection.
            load_bound_oracles(contract)
            _load_locked_result_schema()
            probes = build_probes(_ngc_executable())
            result = collect_evidence(
                contract,
                AllowlistedRunner(probes),
                AllowlistedReader(),
                SysfsNetworkInspector(),
                probes,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.mode == "plan" or result["result"] == "pass":
            return 0
        return 1 if result["result"] == "fail" else 2
    except EvidenceError as exc:
        print(json.dumps({"error": str(exc), "result": "invalid"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
