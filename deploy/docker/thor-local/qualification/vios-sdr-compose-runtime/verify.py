#!/usr/bin/env python3
"""Verify the source contract and retained Thor VIOS SDR runtime receipt."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
COMPOSE_PATH = REPO_ROOT / "deploy/docker/thor-local/compose.yml"
CLUSTER_CONFIG_PATH = (
    REPO_ROOT / "deploy/docker/thor-local/vios/sdr/docker_cluster_config.json"
)
SCRIPT_PATH = REPO_ROOT / "deploy/docker/scripts/thor-local.sh"
EVIDENCE_PATH = HERE / "runtime-evidence.json"

SDR_IMAGE = (
    "nvcr.io/nvidia/vss-core/sdr:3.1.0@"
    "sha256:d9912bc9b412188b9beae5948f93a1be2a86affdb3df1a0e0c1933bb1c05d24d"
)
REDIS_IMAGE = (
    "redis:8.6.2-alpine@"
    "sha256:c5e375abb885e6b2021c0377879e4890bf76f9065b8922ffc113f2b226b9fc17"
)
GROUP = "sdr-streamprocessing-vios-cg"


class ContractError(RuntimeError):
    """Raised when a retained source or runtime contract drifts."""


class ComposeLoader(yaml.SafeLoader):
    """Safe YAML loader that preserves Compose's tagged override values."""


def _unknown_tag(loader: ComposeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


ComposeLoader.add_constructor(None, _unknown_tag)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def verify_evidence(evidence: dict[str, Any]) -> None:
    _require(evidence.get("schema_version") == 1, "evidence schema drift")
    _require(evidence.get("status") == "passed", "runtime receipt is not passed")
    fixture = evidence.get("fixture", {})
    _require(fixture.get("warehouse_sample_used") is False, "warehouse sample used")
    _require(fixture.get("external_camera_used") is False, "external camera used")
    assertions = evidence.get("assertions")
    _require(isinstance(assertions, list) and len(assertions) == 9, "assertion set drift")
    _require(all(item.get("passed") is True for item in assertions), "failed assertion")
    _require(
        len({item.get("id") for item in assertions}) == len(assertions),
        "duplicate assertion id",
    )
    cleanup = evidence.get("cleanup", {})
    expected_cleanup = {
        "sensor_delete": True,
        "proxy_count_after": 0,
        "sensor_count_after": 0,
        "recording_timeline_after": None,
        "owned_nvstreamer_container_removed": True,
        "owned_sdr_test_container_removed": True,
        "compose_sdr_remains_healthy": True,
        "redis_pending_after": 0,
        "redis_lag_after": 0,
    }
    for key, expected in expected_cleanup.items():
        _require(cleanup.get(key) == expected, f"cleanup drift: {key}")


def verify_compose(compose: dict[str, Any]) -> None:
    services = compose.get("services", {})
    for name in (
        "redis",
        "sensor-ms",
        "streamprocessing-ms",
        "sdr-streamprocessing-init",
        "sdr-streamprocessing",
    ):
        _require(name in services, f"missing Compose service: {name}")

    redis_command = services["redis"].get("command", [])
    _require("127.0.0.1" in redis_command, "Redis loopback bind missing")
    _require(
        "${THOR_LOCAL_MODEL_BIND_HOST:-127.0.0.1}" in redis_command,
        "Redis private-gateway bind missing",
    )
    protected_index = redis_command.index("--protected-mode")
    _require(redis_command[protected_index + 1] == "no", "Redis topology mode drift")

    init = services["sdr-streamprocessing-init"]
    _require(init.get("image") == REDIS_IMAGE, "SDR initializer image drift")
    _require(init.get("network_mode") == "host", "initializer network drift")
    command = " ".join(init.get("command", []))
    for token in ("XGROUP CREATE", "vst.event", GROUP, "MKSTREAM", "BUSYGROUP"):
        _require(token in command, f"initializer command missing: {token}")
    _require(init.get("cap_drop") == ["ALL"], "initializer capabilities drift")

    sdr = services["sdr-streamprocessing"]
    _require(sdr.get("image") == SDR_IMAGE, "SDR image drift")
    _require(sdr.get("container_name") == "vss-vios-sdr", "SDR name drift")
    _require(
        sdr.get("ports") == ["127.0.0.1:${SDR_STREAMPROCESSING_PORT:-4003}:4003"],
        "SDR listener is not loopback-only",
    )
    _require(sdr.get("cap_drop") == ["ALL"], "SDR capabilities drift")
    _require(
        "no-new-privileges:true" in sdr.get("security_opt", []),
        "SDR no-new-privileges missing",
    )
    _require(
        "sdr-controller-service.default.svc.cluster.local:127.0.0.1"
        in sdr.get("extra_hosts", []),
        "SDR controller sink missing",
    )
    environment = sdr.get("environment", {})
    expected_environment = {
        "WDM_MSG_KEY": "vst.event",
        "WDM_MSG_TOPIC": "vst.event",
        "WDM_CONSUMER_GRP_ID": GROUP,
        "WDM_WL_REDIS_SERVER": "host.docker.internal",
        "WDM_CLUSTER_TYPE": "docker",
        "WDM_RESTART_DS_ON_ADD_FAIL": "false",
        "WDM_INITIALIZE_FROM_VST": "false",
    }
    for key, expected in expected_environment.items():
        _require(environment.get(key) == expected, f"SDR environment drift: {key}")
    _require(
        sdr.get("depends_on", {}).get("sdr-streamprocessing-init", {}).get("condition")
        == "service_completed_successfully",
        "SDR initializer dependency drift",
    )
    for producer in ("sensor-ms", "streamprocessing-ms"):
        _require(
            services[producer]
            .get("depends_on", {})
            .get("sdr-streamprocessing-init", {})
            .get("condition")
            == "service_completed_successfully",
            f"producer startup ordering drift: {producer}",
        )


def verify_cluster_config(config: dict[str, Any]) -> None:
    _require(
        config
        == {
            "vss-vios-streamprocessing": {
                "provisioning_address": "host.docker.internal:30001",
                "process_type": "docker",
            }
        },
        "SDR Docker target config drift",
    )


def verify_script(script: str) -> None:
    required = (
        'export SDR_STREAMPROCESSING_PORT="${SDR_STREAMPROCESSING_PORT:-4003}"',
        'SDR_STREAMPROCESSING_PORT "${SDR_STREAMPROCESSING_PORT}"',
        'require_available_port "${SDR_STREAMPROCESSING_PORT}" vss-vios-sdr',
        '"vios-sdr|http://127.0.0.1:${SDR_STREAMPROCESSING_PORT}/healthz"',
        'doctor_http_status "VIOS SDR dispatcher"',
        '"${SDR_STREAMPROCESSING_PORT}"',
    )
    for token in required:
        _require(token in script, f"Thor operator contract missing: {token}")


def verify() -> dict[str, Any]:
    evidence = _load_json(EVIDENCE_PATH)
    compose = yaml.load(COMPOSE_PATH.read_text(encoding="utf-8"), Loader=ComposeLoader)
    cluster_config = _load_json(CLUSTER_CONFIG_PATH)
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    verify_evidence(evidence)
    verify_compose(compose)
    verify_cluster_config(cluster_config)
    verify_script(script)
    return {
        "status": "passed",
        "verifier_id": "vios-sdr-compose-runtime",
        "runtime_assertions": len(evidence["assertions"]),
        "cleanup_verified": True,
        "warehouse_sample_used": False,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), indent=2, sort_keys=True))
    except (ContractError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"vios-sdr-compose-runtime: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
