"""Side-effect-free adversarial tests for optional Thor scaling config."""

from __future__ import annotations

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fixed_topology_scaling_validator", LANE / "validator.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def load_sources() -> tuple[dict, dict]:
    compose = validator._strict_yaml(
        (
            validator.REPO_ROOT / "deploy/docker/thor-local/scaling/compose.yml"
        ).read_bytes(),
        "compose",
    )
    alert = validator._strict_yaml(
        (
            validator.REPO_ROOT
            / "deploy/docker/thor-local/scaling/alert-scale-config.yml"
        ).read_bytes(),
        "alert config",
    )
    return compose, alert


def rejects(compose: dict, alert: dict, message: str) -> None:
    with pytest.raises(validator.ScalingConfigError, match=message):
        validator._assert_compose(compose, alert)


def test_complete_static_topology_and_canonical_bindings_pass() -> None:
    result = validator.check()
    assert result["valid"] is True
    assert result["source_lock_count"] == 14
    assert result["capability_count"] == 2
    assert result["service_count"] == 6
    assert result["default_replicas"] == 1
    assert result["future_minimum_qualification_replicas"] == 2
    assert result["runtime_actions_performed"] is False
    assert result["runtime_evidence"] == []
    assert result["can_mark_runtime_qualified"] is False


def test_contract_preserves_exact_remaining_runtime_constraints() -> None:
    contract = json.loads((LANE / "contract.json").read_text())
    assert [row["planning_requirement_id"] for row in contract["rows"]] == [
        "systems-alert-worker-scaling",
        "systems-vios-scaling",
    ]
    assert all(
        len(row["remaining_runtime_constraints"]) == 3 for row in contract["rows"]
    )
    assert "RTSP" in " ".join(contract["rows"][1]["remaining_runtime_constraints"])
    assert "partition" in " ".join(contract["rows"][0]["remaining_runtime_constraints"])


def test_new_topology_is_not_included_by_default_compose() -> None:
    default = validator._strict_yaml(
        (validator.REPO_ROOT / "deploy/docker/compose.yml").read_bytes(), "default"
    )
    assert "thor-local/scaling" not in json.dumps(default, sort_keys=True)


def test_validator_has_no_live_action_clients_or_execute_mode() -> None:
    source = (LANE / "validator.py").read_text()
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"docker", "requests", "httpx", "socket", "subprocess"}
    assert "os.system" not in source
    assert "os.popen" not in source


def test_source_lock_drift_fails_closed(tmp_path: Path) -> None:
    contract = json.loads((LANE / "contract.json").read_text())
    for lock in contract["source_locks"]:
        source = validator.REPO_ROOT / lock["path"]
        target = tmp_path / lock["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target = tmp_path / "deploy/docker/thor-local/scaling/compose.yml"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(validator.ScalingConfigError, match="raw SHA-256 mismatch"):
        validator.check(tmp_path)


def test_strict_parsers_reject_duplicate_and_nonfinite_values() -> None:
    with pytest.raises(validator.ScalingConfigError, match="duplicate JSON key"):
        validator._strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(validator.ScalingConfigError, match="non-finite"):
        validator._strict_json(b'{"a":NaN}', "nonfinite")
    with pytest.raises(validator.ScalingConfigError, match="duplicate YAML key"):
        validator._strict_yaml(b"a: 1\na: 2\n", "duplicate")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "container_name", "fixed"
            ),
            "fixed/host",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "network_mode", "host"
            ),
            "fixed/host",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "profiles", ["default"]
            ),
            "opt-in profile",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"]["deploy"].__setitem__(
                "replicas", 2
            ),
            "single-instance default",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "ports", ["9080:9080"]
            ),
            "listener boundary",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "image", "nvcr.io/nvidia/vss-core/vss-alert-verification:3.2.0"
            ),
            "Thor-local Alert derivative",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"]["environment"].__setitem__(
                "VLM_BASE_URL", "http://host.docker.internal:8002"
            ),
            "Thor-local Alert VLM environment",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "volumes", ["./wrong.yml:/app/config.yaml:ro"]
            ),
            "bind-path contract",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"].__setitem__(
                "entrypoint", ["/usr/local/bin/python", "enhance_alert_with_vlm.py"]
            ),
            "config-render command",
        ),
        (
            lambda _c, a: a["vlm"].__setitem__(
                "base_url", "http://host.docker.internal:8002/v1"
            ),
            "generated VLM config substitution",
        ),
        (
            lambda c, _a: c["services"]["alert-worker"]["environment"].__setitem__(
                "PROMETHEUS_METRICS_ENABLED", "false"
            ),
            "metrics boundary",
        ),
        (
            lambda _c, a: a["alert_agent"].__setitem__("num_workers", 2),
            "single-worker/chunk",
        ),
        (
            lambda _c, a: a["alert_agent"].__setitem__("chunk_size", 2),
            "single-worker/chunk",
        ),
        (
            lambda _c, a: a["event_bridge"]["kafka_source"].__setitem__(
                "group_id", "unique-per-replica"
            ),
            "shared alert Kafka",
        ),
        (
            lambda _c, a: a["kafka"].__setitem__("bootstrap_servers", "localhost:9092"),
            "dependency endpoint",
        ),
        (
            lambda c, _a: c["services"]["vios-sensor-singleton"]["deploy"].__setitem__(
                "replicas", 2
            ),
            "single-instance default",
        ),
        (
            lambda c, _a: c["services"]["vios-sensor-singleton"]["labels"].__setitem__(
                "com.nvidia.vss.scaling-role", "replica"
            ),
            "Sensor singleton",
        ),
        (
            lambda c, _a: c["services"]["vios-streamprocessor"].__setitem__(
                "ports", ["30001:30001"]
            ),
            "listener boundary",
        ),
        (
            lambda c, _a: c["services"]["vios-streamprocessor"].__setitem__(
                "entrypoint", ["launch_vst"]
            ),
            "generated replica identity",
        ),
        (
            lambda c, _a: c["services"]["vios-streamprocessor"]["volumes"].remove(
                "/home/vst/vst_release/vst_video"
            ),
            "anonymous storage",
        ),
        (
            lambda c, _a: c["services"]["vios-streamprocessor"][
                "environment"
            ].__setitem__("SENSOR_MODULE_ENDPOINT", "http://localhost:30000"),
            "internal dependency routing",
        ),
        (
            lambda c, _a: c["services"]["vios-scale-ingress"].__setitem__(
                "ports", ["31888:30888"]
            ),
            "loopback bind",
        ),
        (
            lambda c, _a: c["networks"]["thor-vios-scale"].__setitem__(
                "internal", True
            ),
            "egress-capable bridge",
        ),
    ],
)
def test_adversarial_topology_mutations_fail_closed(mutation, message: str) -> None:
    compose, alert = load_sources()
    compose = deepcopy(compose)
    alert = deepcopy(alert)
    mutation(compose, alert)
    rejects(compose, alert, message)
