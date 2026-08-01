#!/usr/bin/env python3
"""Fail-closed static validator for the optional Thor scaling topology."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
EXPECTED_CONTRACT_SHA256 = (
    "27dacb96bbd3ff7d6fee5d3a25952492feff363b259be06f09b256ed7d8213aa"
)
MAX_BYTES = 5_000_000
EXPECTED_SOURCE_PATHS = {
    "deploy/docker/compose.yml",
    "deploy/docker/thor-local/scaling/compose.yml",
    "deploy/docker/thor-local/scaling/alert-scale-config.yml",
    "deploy/docker/thor-local/scaling/vios-scale-nginx.conf",
    "deploy/docker/thor-local/scaling/README.md",
    "deploy/docker/thor-local/generated.env",
    "deploy/docker/services/alert/scripts/env-substitute.py",
    "deploy/docker/thor-local/qualification/architecture-gap-contracts/contract.json",
    "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    "deploy/docker/thor-local/parity/official-capabilities.json",
    "services/alert/enhance_alert_with_vlm.py",
    "services/alert/metrics/prometheus_metrics.py",
    "services/vios/src/framework/utilities/config.cpp",
    "deploy/docker/services/vios/configs/vst_config.json",
}
EXPECTED_BINDINGS = [
    (
        "systems-alert-worker-scaling",
        "performance.alerts.worker-scaling",
        "alert-worker",
        "thor-alert-scale",
    ),
    (
        "systems-vios-scaling",
        "deployment.vios.horizontal-scaling",
        "vios-streamprocessor",
        "thor-vios-scale",
    ),
]
EXPECTED_SERVICES = {
    "alert-worker",
    "vios-scale-db",
    "vios-scale-redis",
    "vios-sensor-singleton",
    "vios-streamprocessor",
    "vios-scale-ingress",
}
EXPECTED_SINGLETONS = {
    "vios-scale-db",
    "vios-scale-redis",
    "vios-sensor-singleton",
    "vios-scale-ingress",
}


class ScalingConfigError(RuntimeError):
    """A source identity, topology invariant, or canonical binding failed."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256(raw)


def _read_regular(path: Path, expected: str | None, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScalingConfigError(f"cannot read {label}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ScalingConfigError(f"{label} must be a regular non-symlink file")
        if before.st_size <= 0 or before.st_size > MAX_BYTES:
            raise ScalingConfigError(f"{label} exceeds bounded size")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_BYTES + 1 - total))
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
            getattr(before, field) != getattr(after, field) for field in stable
        ):
            raise ScalingConfigError(f"{label} changed while being read")
    finally:
        os.close(descriptor)
    if expected is not None and _sha256(raw) != expected:
        raise ScalingConfigError(f"{label} raw SHA-256 mismatch")
    return raw


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ScalingConfigError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ScalingConfigError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except ScalingConfigError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScalingConfigError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise ScalingConfigError(f"JSON root must be an object in {label}")
    return value


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ScalingConfigError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _strict_yaml(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)
    except ScalingConfigError:
        raise
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ScalingConfigError(f"invalid YAML in {label}") from exc
    if not isinstance(value, dict):
        raise ScalingConfigError(f"YAML root must be an object in {label}")
    return value


def _repo_file(root: Path, relative: str, expected: str) -> bytes:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ScalingConfigError(f"unsafe source path: {relative}")
    root = root.resolve(strict=True)
    current = root
    for part in candidate.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ScalingConfigError(f"cannot resolve source: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise ScalingConfigError(f"symlinked source: {relative}")
    return _read_regular(current, expected, f"source {relative}")


def _find_unique(value: Any, key: str, expected: str, label: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get(key) == expected:
                matches.append(item)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    if len(matches) != 1:
        raise ScalingConfigError(f"expected one {label}, found {len(matches)}")
    return matches[0]


def _require_fragments(raw: bytes, fragments: list[str], label: str) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScalingConfigError(f"non-text source: {label}") from exc
    for fragment in fragments:
        if fragment not in text:
            raise ScalingConfigError(
                f"required source fragment missing in {label}: {fragment}"
            )


def _assert_contract(contract: dict[str, Any]) -> None:
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id") != "thor-fixed-topology-scaling-config-v1"
    ):
        raise ScalingConfigError("contract identity drifted")
    policy = contract["policy"]
    if policy["default_inert"] is not True:
        raise ScalingConfigError("default-inert policy drifted")
    if any(
        policy[key] is not False
        for key in (
            "docker",
            "network",
            "subprocess",
            "process_lifecycle",
            "writes",
            "can_mark_runtime_qualified",
        )
    ):
        raise ScalingConfigError("static no-action policy drifted")
    if (
        policy["runtime_evidence"] != []
        or contract["current_state"]["runtime_evidence"] != []
    ):
        raise ScalingConfigError("static package must not contain runtime evidence")
    if contract["current_state"]["live_state_advanced"] is not False:
        raise ScalingConfigError("static package must not advance live state")
    locks = contract["source_locks"]
    if len(locks) != 14 or {row["path"] for row in locks} != EXPECTED_SOURCE_PATHS:
        raise ScalingConfigError("exact fourteen-source lock set drifted")
    rows = contract["rows"]
    identities = [
        (
            row["planning_requirement_id"],
            row["capability_id"],
            row["service_id"],
            row["profile"],
        )
        for row in rows
    ]
    if identities != EXPECTED_BINDINGS:
        raise ScalingConfigError("exact ordered two-row binding drifted")
    for row in rows:
        if (
            row["default_replicas"] != 1
            or row["future_minimum_qualification_replicas"] != 2
        ):
            raise ScalingConfigError(
                "single-default/two-replica qualification boundary drifted"
            )
        if len(row["remaining_runtime_constraints"]) != 3:
            raise ScalingConfigError("explicit remaining runtime constraints drifted")


def _assert_compose(compose: dict[str, Any], alert_config: dict[str, Any]) -> None:
    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != EXPECTED_SERVICES:
        raise ScalingConfigError("exact six-service topology drifted")
    for service_id, service in services.items():
        if "container_name" in service or service.get("network_mode") == "host":
            raise ScalingConfigError(f"fixed/host topology returned in {service_id}")
        expected_profile = (
            ["thor-alert-scale"]
            if service_id == "alert-worker"
            else ["thor-vios-scale"]
        )
        if service.get("profiles") != expected_profile:
            raise ScalingConfigError(f"opt-in profile drifted in {service_id}")
        if service.get("deploy", {}).get("replicas") != 1:
            raise ScalingConfigError(f"single-instance default drifted in {service_id}")
    if (
        compose.get("networks", {}).get("thor-alert-scale", {}).get("driver")
        != "bridge"
    ):
        raise ScalingConfigError("alert bridge network drifted")
    if compose.get("networks", {}).get("thor-vios-scale", {}) != {
        "driver": "bridge",
        "internal": False,
    }:
        raise ScalingConfigError("VIOS egress-capable bridge network drifted")

    alert = services["alert-worker"]
    if (
        alert.get("image")
        != "${THOR_LOCAL_ALERT_BRIDGE_IMAGE:-cti-vss-alert-bridge:thor-local}"
    ):
        raise ScalingConfigError("Thor-local Alert derivative default drifted")
    if "ports" in alert or alert.get("expose") != ["9080", "9081"]:
        raise ScalingConfigError("alert replica listener boundary drifted")
    if alert.get("labels", {}).get("com.nvidia.vss.scaling-role") != "replica":
        raise ScalingConfigError("alert replica role drifted")
    if alert.get("extra_hosts") != ["host.docker.internal:host-gateway"]:
        raise ScalingConfigError("alert host-gateway boundary drifted")
    environment = alert["environment"]
    if (
        environment.get("PROMETHEUS_METRICS_ENABLED") != "true"
        or environment.get("PROMETHEUS_PORT") != "9081"
    ):
        raise ScalingConfigError("per-replica alert metrics boundary drifted")
    if (
        environment.get("VLM_BASE_URL")
        != ("${VLM_BASE_URL:-http://host.docker.internal:8003}")
        or environment.get("VLM_NAME") != "${VLM_NAME:-datasheet-vision}"
    ):
        raise ScalingConfigError("Thor-local Alert VLM environment drifted")
    if alert.get("volumes") != [
        "./alert-scale-config.yml:/app/configs/config.yml:ro",
        "../../services/alert/scripts/env-substitute.py:/app/env-substitute.py:ro",
    ]:
        raise ScalingConfigError("Alert standalone bind-path contract drifted")
    if alert.get("tmpfs") != ["/app/runtime:mode=1777,size=10M"]:
        raise ScalingConfigError("Alert rendered-config tmpfs drifted")
    if alert.get("entrypoint") != [
        "/usr/local/bin/python",
        "/app/env-substitute.py",
        "--source",
        "/app/configs/config.yml",
        "--output",
        "/app/runtime/config.yml",
        "--",
    ] or alert.get("command") != [
        "/usr/local/bin/python",
        "enhance_alert_with_vlm.py",
        "--config",
        "/app/runtime/config.yml",
    ]:
        raise ScalingConfigError("Alert config-render command drifted")
    if alert_config.get("vlm", {}).get("base_url") != "${VLM_BASE_URL}/v1" or (
        alert_config.get("vlm", {}).get("model") != "${VLM_NAME}"
    ):
        raise ScalingConfigError("Alert generated VLM config substitution drifted")
    if (
        alert_config["alert_agent"]["num_workers"] != 1
        or alert_config["alert_agent"]["chunk_size"] != 1
    ):
        raise ScalingConfigError("alert single-worker/chunk default drifted")
    if (
        alert_config["event_bridge"]["kafka_source"]["group_id"]
        != "alert-bridge-vlm-group"
    ):
        raise ScalingConfigError("shared alert Kafka group drifted")
    endpoint_values = [
        alert_config["vst_config"]["base_url"],
        alert_config["kafka"]["bootstrap_servers"],
        alert_config["event_bridge"]["redis_source"]["host"],
        alert_config["elastic"]["hosts"][0],
    ]
    if not all("host.docker.internal" in value for value in endpoint_values):
        raise ScalingConfigError(
            "alert bridge dependency endpoint drifted to localhost"
        )

    sensor = services["vios-sensor-singleton"]
    stream = services["vios-streamprocessor"]
    ingress = services["vios-scale-ingress"]
    if sensor["labels"]["com.nvidia.vss.scaling-role"] != "singleton":
        raise ScalingConfigError("VIOS Sensor singleton boundary drifted")
    if (
        sensor["environment"]["STREAM_PROCESSOR_MODULE_ENDPOINT"]
        != "http://vios-streamprocessor:30001"
    ):
        raise ScalingConfigError("Sensor-to-replica service routing drifted")
    if stream["labels"]["com.nvidia.vss.scaling-role"] != "replica":
        raise ScalingConfigError("VIOS stream replica role drifted")
    if "ports" in stream or stream.get("expose") != ["30001", "30554"]:
        raise ScalingConfigError("VIOS per-replica listener boundary drifted")
    entrypoint = " ".join(stream["entrypoint"])
    if 'export CONTAINER_NAME="$${HOSTNAME}"' not in entrypoint:
        raise ScalingConfigError("VIOS generated replica identity drifted")
    if '"vios-scale-redis:6379"' not in entrypoint:
        raise ScalingConfigError("VIOS per-replica Redis rewrite drifted")
    anonymous = {
        value
        for value in stream["volumes"]
        if isinstance(value, str) and ":" not in value
    }
    expected_anonymous = {
        "/home/vst/vst_release/configs",
        "/home/vst/vst_release/vst_data",
        "/home/vst/vst_release/vst_video",
        "/home/vst/vst_release/streamer_videos",
        "/home/vst/vst_release/webroot/temp_files",
    }
    if anonymous != expected_anonymous:
        raise ScalingConfigError("VIOS per-replica anonymous storage boundary drifted")
    if (
        stream["environment"]["CENTRALIZE_DB_HOSTADDR"] != "vios-scale-db"
        or stream["environment"]["SENSOR_MODULE_ENDPOINT"]
        != "http://vios-sensor-singleton:30000"
    ):
        raise ScalingConfigError("VIOS internal dependency routing drifted")
    if ingress.get("ports") != [
        "127.0.0.1:${THOR_VIOS_SCALE_INGRESS_PORT:-31888}:30888"
    ]:
        raise ScalingConfigError("VIOS singleton ingress loopback bind drifted")
    if ingress["labels"]["com.nvidia.vss.scaling-role"] != "singleton-router":
        raise ScalingConfigError("VIOS singleton router role drifted")
    if set(
        row["labels"]["com.nvidia.vss.scaling-role"]
        for row in (services[key] for key in EXPECTED_SINGLETONS)
    ) != {"singleton", "singleton-router"}:
        raise ScalingConfigError("VIOS fixed singleton set drifted")


def check(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Validate configuration and canonical bindings without taking actions."""
    contract = _strict_json(
        _read_regular(CONTRACT_PATH, EXPECTED_CONTRACT_SHA256, "contract"), "contract"
    )
    _assert_contract(contract)
    raw_sources = {
        lock["path"]: _repo_file(root, lock["path"], lock["sha256"])
        for lock in contract["source_locks"]
    }
    compose = _strict_yaml(
        raw_sources["deploy/docker/thor-local/scaling/compose.yml"], "compose"
    )
    default_compose = _strict_yaml(
        raw_sources["deploy/docker/compose.yml"], "default compose"
    )
    if "thor-local/scaling" in json.dumps(default_compose, sort_keys=True):
        raise ScalingConfigError("opt-in scaling topology leaked into default compose")
    alert_config = _strict_yaml(
        raw_sources["deploy/docker/thor-local/scaling/alert-scale-config.yml"],
        "alert config",
    )
    _assert_compose(compose, alert_config)
    nginx = raw_sources["deploy/docker/thor-local/scaling/vios-scale-nginx.conf"]
    _require_fragments(
        nginx,
        [
            "resolver 127.0.0.11 ipv6=off valid=5s;",
            "http://vios-sensor-singleton:30000",
            "http://vios-streamprocessor:30001",
            "proxy_pass $sensor_backend;",
            "proxy_pass $stream_backend;",
        ],
        "VIOS scale ingress",
    )
    _require_fragments(
        raw_sources["deploy/docker/thor-local/generated.env"],
        [
            "VLM_NAME=datasheet-vision",
            "VLM_BASE_URL=http://172.17.0.1:8003",
            "THOR_LOCAL_ALERT_BRIDGE_IMAGE=cti-vss-alert-bridge:thor-local",
        ],
        "Thor generated environment",
    )
    _require_fragments(
        raw_sources["deploy/docker/services/alert/scripts/env-substitute.py"],
        [
            "pattern = r'\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}'",
            "os.execvp(command_args[0], command_args)",
        ],
        "Alert environment substitution entrypoint",
    )
    _require_fragments(
        raw_sources["deploy/docker/thor-local/scaling/README.md"],
        [
            "--project-directory deploy/docker/thor-local/scaling",
            "-f deploy/docker/thor-local/scaling/compose.yml",
            "--env-file deploy/docker/thor-local/generated.env",
            "standalone Compose source",
            "only renders configuration",
        ],
        "scaling Compose path contract",
    )
    _require_fragments(
        raw_sources["services/alert/enhance_alert_with_vlm.py"],
        [
            "self.worker_queue = Queue(maxsize=self.num_workers)",
            "ThreadPoolExecutor(max_workers=self.num_workers",
            "self.worker_queue.get(timeout=5)",
        ],
        "Alert worker source",
    )
    _require_fragments(
        raw_sources["services/alert/metrics/prometheus_metrics.py"],
        [
            "alert_bridge_worker_queue_wait_duration_seconds",
            "alert_bridge_worker_processing_seconds",
        ],
        "Alert worker metrics source",
    )
    _require_fragments(
        raw_sources["services/vios/src/framework/utilities/config.cpp"],
        [
            'getenv("CENTRALIZE_DB_HOSTADDR")',
            'getenv("CENTRALIZE_DB_PORT")',
            'getenv("CENTRALIZE_DB_LOCAL")',
            'getenv("HTTP_PORT")',
            'getenv("RTSP_SERVER_PORT")',
        ],
        "VIOS environment source",
    )
    _require_fragments(
        raw_sources["deploy/docker/services/vios/configs/vst_config.json"],
        ['"redis_server_env_var": "localhost:6379"'],
        "VIOS seed config",
    )

    acceptance = _strict_json(
        raw_sources["deploy/docker/thor-local/qualification/acceptance_inventory.json"],
        "acceptance inventory",
    )
    capabilities = _strict_json(
        raw_sources["deploy/docker/thor-local/parity/official-capabilities.json"],
        "official capabilities",
    )
    architecture = _strict_json(
        raw_sources[
            "deploy/docker/thor-local/qualification/architecture-gap-contracts/contract.json"
        ],
        "architecture contract",
    )
    planning_rows = acceptance["wave3_contracts"]["planning_requirements"]
    architecture_rows = {row["id"]: row for row in architecture["rows"]}
    for row in contract["rows"]:
        planning_matches = [
            item
            for item in planning_rows
            if item.get("id") == row["planning_requirement_id"]
        ]
        if len(planning_matches) != 1:
            raise ScalingConfigError("planning requirement denominator drifted")
        planning = planning_matches[0]
        if (
            canonical_sha256(planning) != row["planning_requirement_sha256"]
            or planning["payload_canonical_sha256"] != row["planning_payload_sha256"]
        ):
            raise ScalingConfigError("planning requirement canonical identity drifted")
        if (
            planning["owner_id"] != row["capability_id"]
            or planning["runtime_evidence"] != []
        ):
            raise ScalingConfigError("planning requirement binding/state drifted")
        capability = _find_unique(
            capabilities,
            "id",
            row["capability_id"],
            f"capability {row['capability_id']}",
        )
        if (
            canonical_sha256(capability) != row["capability_sha256"]
            or canonical_sha256(capability["contract"])
            != row["capability_contract_sha256"]
        ):
            raise ScalingConfigError("capability canonical identity drifted")
        if (
            capability["thor_state"] != "partial"
            or capability["runtime_state"] != "not_qualified"
        ):
            raise ScalingConfigError("capability no longer partial/not-qualified")
        architecture_row = architecture_rows[row["planning_requirement_id"]]
        if (
            architecture_row["current_state"] != "runtime_unqualified"
            or architecture_row["acceptance"]["minimum_runtime_replicas"] != 2
        ):
            raise ScalingConfigError("architecture runtime gate drifted")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "valid": True,
        "source_lock_count": len(contract["source_locks"]),
        "capability_count": len(contract["rows"]),
        "service_count": len(compose["services"]),
        "default_replicas": 1,
        "future_minimum_qualification_replicas": 2,
        "runtime_actions_performed": False,
        "runtime_evidence": [],
        "can_mark_runtime_qualified": False,
        "remaining_blocker": contract["current_state"]["remaining_blocker"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Statically validate the optional Thor scaling topology"
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check()
    except ScalingConfigError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
