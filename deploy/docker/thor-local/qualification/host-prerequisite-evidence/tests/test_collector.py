from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import jsonschema
import pytest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "host_prerequisite_collector", PACKAGE / "collector.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


class FixtureRunner:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.calls: list[collector.Probe] = []

    def run(self, probe: collector.Probe) -> collector.ProbeResult:
        self.calls.append(probe)
        if probe.id not in self.values:
            return collector.ProbeResult("unavailable", error="fixture_unavailable")
        return collector.ProbeResult("ok", stdout=self.values[probe.id])


class FixtureReader:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}
        self.calls: list[str] = []

    def read(self, key: str) -> collector.ProbeResult:
        self.calls.append(key)
        if key not in self.values:
            return collector.ProbeResult("unavailable", error="fixture_unavailable")
        return collector.ProbeResult("ok", stdout=self.values[key])


class FixtureNetwork:
    def __init__(
        self,
        *,
        qualifying: int = 1,
        maximum: int | None = 25000,
        active_speed: int | None = 360,
    ) -> None:
        self.qualifying = qualifying
        self.maximum = maximum
        self.active_speed = active_speed
        self.route_interfaces: list[str | None] = []

    def inspect(self, active_route_interface: str | None) -> dict[str, object]:
        self.route_interfaces.append(active_route_interface)
        return {
            "physical_interface_count": 6,
            "carrier_up_physical_interface_count": 5,
            "qualifying_physical_link_count": self.qualifying,
            "maximum_qualifying_speed_mbps": self.maximum,
            "active_route_interface_class": "physical",
            "active_route_reported_speed_mbps": self.active_speed,
            "active_route_meets_minimum": (
                self.active_speed >= 1000 if self.active_speed is not None else None
            ),
            "interface_identifiers_emitted": False,
        }


def complete_runner() -> FixtureRunner:
    block_devices = {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "type": "disk",
                "size": 1024209543168,
                "rota": False,
                "mountpoints": [None],
                "children": [
                    {
                        "name": "nvme0n1p2",
                        "type": "part",
                        "size": 1004976848896,
                        "rota": False,
                        "mountpoints": ["/"],
                    }
                ],
            }
        ]
    }
    return FixtureRunner(
        {
            "architecture": "aarch64\n",
            "gpu": "0, NVIDIA Thor, 580.00\n",
            "docker_version": "29.2.1|29.2.1\n",
            "compose_version": "5.0.2\n",
            "toolkit_version": "NVIDIA Container Toolkit CLI version 1.18.0\n",
            "ngc_version": "NGC CLI 4.10.0\n",
            "cpu_count": "14\n",
            "disk_root": ("1B-blocks Avail Mounted on\n1004976848896 64697282560 /\n"),
            "block_devices": json.dumps(block_devices),
            "active_route": json.dumps([{"dev": "wlP1p1s0", "prefsrc": "redacted"}]),
            "browser_port": "",
        }
    )


def complete_reader(*, available_kib: int = 32_000_000) -> FixtureReader:
    return FixtureReader(
        {
            "device_model": "NVIDIA Jetson AGX Thor Developer Kit\x00",
            "tegra_release": "# R38 (release), REVISION: 4.0\n",
            "meminfo": (
                f"MemTotal:       128790100 kB\nMemAvailable:   {available_kib} kB\n"
            ),
        }
    )


def collect(
    runner: FixtureRunner | None = None,
    reader: FixtureReader | None = None,
    network: FixtureNetwork | None = None,
) -> dict[str, object]:
    return collector.collect_evidence(
        collector.load_contract(),
        runner or complete_runner(),
        reader or complete_reader(),
        network or FixtureNetwork(),
    )


def test_default_plan_is_inert_and_schema_validated() -> None:
    with (
        mock.patch.object(
            collector.subprocess, "run", side_effect=AssertionError("executed")
        ),
        mock.patch.object(
            collector.Path, "lstat", side_effect=AssertionError("host stat")
        ),
    ):
        result = collector.build_plan(collector.load_contract())
    assert result["result"] == "inert_plan"
    assert result["safety"]["external_commands_executed"] == 0
    assert len(result["capability_pairs"]) == 4
    jsonschema.Draft202012Validator(
        json.loads((PACKAGE / "result.schema.json").read_text())
    ).validate(result)


def test_locked_result_schema_fails_closed_on_raw_byte_drift(monkeypatch) -> None:
    monkeypatch.setattr(collector, "EXPECTED_RESULT_SCHEMA_SHA256", "0" * 64)
    with pytest.raises(collector.EvidenceError, match="raw-byte identity drifted"):
        collector.build_plan(collector.load_contract())


def test_source_binding_covers_exactly_four_pairs_and_current_rows() -> None:
    contract = collector.load_contract()
    selected = collector.load_bound_oracles(contract)
    assert set(selected) == {
        "prereq.platform.validated-gpus",
        "prereq.platform.agx-thor-software",
        "prereq.platform.toolchain-versions",
        "prereq.platform.capacity-and-access",
    }
    assert len(contract["source"]["pairs"]) == 4


def test_source_binding_fails_closed_on_selected_oracle_drift() -> None:
    contract = deepcopy(collector.load_contract())
    contract["source"]["pairs"][0]["oracle_canonical_sha256"] = "0" * 64
    with pytest.raises(collector.EvidenceError, match="bound oracle drifted"):
        collector.load_bound_oracles(contract)


def test_command_surface_has_no_lifecycle_network_or_shell() -> None:
    rendered = [
        word
        for probe in collector.PROBES.values()
        for word in (probe.executable, *probe.argv)
    ]
    forbidden = {
        "run",
        "start",
        "stop",
        "restart",
        "exec",
        "pull",
        "build",
        "rm",
        "curl",
        "wget",
        "compose up",
        "compose down",
    }
    assert forbidden.isdisjoint(rendered)
    assert all(
        Path(probe.executable).is_absolute() for probe in collector.PROBES.values()
    )
    assert collector.PROBES["docker_version"].argv[0] == "version"
    assert collector.PROBES["compose_version"].argv == ("compose", "version", "--short")


def test_runner_rejects_any_argument_change_and_uses_sterile_environment() -> None:
    original = collector.PROBES["docker_version"]
    with pytest.raises(collector.EvidenceError, match="exact allowlisted"):
        collector.AllowlistedRunner().run(replace(original, argv=("ps",)))
    completed = subprocess.CompletedProcess([], 0, stdout="aarch64\n", stderr="")
    with mock.patch.object(collector.subprocess, "run", return_value=completed) as run:
        collector.AllowlistedRunner().run(collector.PROBES["architecture"])
    _, kwargs = run.call_args
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["cwd"] == "/"
    assert kwargs["env"]["HOME"] == "/nonexistent"
    assert "HF_TOKEN" not in kwargs["env"]
    assert "NGC_CLI_API_KEY" not in kwargs["env"]
    assert "shell" not in kwargs


def test_ngc_discovery_rejects_unsafe_and_non_system_candidates(monkeypatch) -> None:
    metadata = {
        Path("/usr/bin/ngc"): SimpleNamespace(st_mode=stat.S_IFREG | 0o775, st_uid=0),
        Path("/usr/local/bin/ngc"): SimpleNamespace(
            st_mode=stat.S_IFREG | 0o755, st_uid=1000
        ),
    }

    def fake_lstat(path: Path):
        return metadata[path]

    monkeypatch.setattr(collector.Path, "lstat", fake_lstat)
    assert (
        collector._ngc_executable(
            (
                Path("/home/nvidia/.local/bin/ngc"),
                Path("/usr/bin/ngc"),
                Path("/usr/local/bin/ngc"),
            )
        )
        == collector.UNAVAILABLE_NGC_EXECUTABLE
    )


@pytest.mark.parametrize(
    ("mode", "uid"),
    [
        (stat.S_IFLNK | 0o777, 0),
        (stat.S_IFREG | 0o775, 0),
        (stat.S_IFREG | 0o755, 1000),
        (stat.S_IFREG | 0o644, 0),
    ],
)
def test_ngc_discovery_rejects_each_unsafe_system_file_class(
    monkeypatch, mode: int, uid: int
) -> None:
    monkeypatch.setattr(
        collector.Path,
        "lstat",
        lambda path: SimpleNamespace(st_mode=mode, st_uid=uid),
    )
    assert (
        collector._ngc_executable((Path("/usr/local/bin/ngc"),))
        == collector.UNAVAILABLE_NGC_EXECUTABLE
    )


def test_ngc_discovery_accepts_only_safe_root_owned_system_binary(monkeypatch) -> None:
    def fake_lstat(path: Path):
        assert path == Path("/usr/local/bin/ngc")
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)

    monkeypatch.setattr(collector.Path, "lstat", fake_lstat)
    assert (
        collector._ngc_executable((Path("/usr/local/bin/ngc"),)) == "/usr/local/bin/ngc"
    )


def test_reader_rejects_arbitrary_paths() -> None:
    with pytest.raises(collector.EvidenceError, match="not allowlisted"):
        collector.AllowlistedReader().read("../../home/nvidia/.ngc/config")


def test_complete_contract_pass_is_independent_of_operational_headroom() -> None:
    result = collect()
    assert result["result"] == "pass"
    assert result["summary"]["contracts_passed"] == 4
    assert result["summary"]["operational_admission"] == "blocked_or_warning"
    admission = result["observations"]["operational_admission"]
    assert admission["model_start_memory_satisfied"] is False
    assert admission["stack_start_memory_satisfied"] is True
    assert admission["official_edge_memory_satisfied"] is False
    assert admission["free_disk_warning_satisfied"] is False
    assert result["summary"]["operational_admission_changes_contract_result"] is False


def test_physical_link_capacity_passes_when_active_route_is_slower() -> None:
    network = FixtureNetwork(qualifying=4, maximum=25000, active_speed=360)
    result = collect(network=network)
    capacity = next(
        item
        for item in result["capabilities"]
        if item["capability_id"] == "prereq.platform.capacity-and-access"
    )
    network_assertion = next(
        item for item in capacity["assertions"] if item["id"] == "network"
    )
    assert network_assertion["status"] == "pass"
    observed = result["observations"]["capacity"]["network"]
    assert observed["active_route_meets_minimum"] is False
    assert observed["interface_identifiers_emitted"] is False
    assert network.route_interfaces == ["wlP1p1s0"]


def test_no_qualifying_physical_link_fails_capacity_even_if_route_is_fast() -> None:
    result = collect(
        network=FixtureNetwork(qualifying=0, maximum=None, active_speed=2400)
    )
    assert result["result"] == "fail"
    capacity = next(
        item
        for item in result["capabilities"]
        if item["capability_id"].endswith("capacity-and-access")
    )
    assert capacity["contract_status"] == "fail"


def test_x86_cpu_minimum_is_not_applied_to_aarch64() -> None:
    runner = complete_runner()
    runner.values["cpu_count"] = "1\n"
    result = collect(runner=runner)
    capacity = next(
        item
        for item in result["capabilities"]
        if item["capability_id"].endswith("capacity-and-access")
    )
    cpu = next(item for item in capacity["assertions"] if item["id"] == "cpu")
    assert cpu["status"] == "pass"


def test_rotational_root_or_old_toolchain_fails_exact_contract() -> None:
    runner = complete_runner()
    runner.values["compose_version"] = "2.38.9\n"
    document = json.loads(runner.values["block_devices"])
    document["blockdevices"][0]["rota"] = True
    document["blockdevices"][0]["children"][0]["rota"] = True
    runner.values["block_devices"] = json.dumps(document)
    result = collect(runner=runner)
    assert result["result"] == "fail"
    assert result["summary"]["contracts_failed"] == 2


def test_missing_observation_is_unknown_not_false_pass() -> None:
    runner = complete_runner()
    del runner.values["ngc_version"]
    result = collect(runner=runner)
    assert result["result"] == "unknown"
    toolchain = next(
        item
        for item in result["capabilities"]
        if item["capability_id"].endswith("toolchain-versions")
    )
    assert toolchain["contract_satisfied"] is None


def test_untrusted_raw_output_is_not_echoed() -> None:
    runner = complete_runner()
    secret = "hf_abcdefghijklmnop"
    runner.values["gpu"] = f"0, token={secret}, 580.00\n"
    runner.values["ngc_version"] = f"NGC CLI 4.10.0 token={secret}\n"
    output = json.dumps(collect(runner=runner), sort_keys=True)
    assert secret not in output
    assert "token=" not in output

    runner.values["gpu"] = f"0, {secret}, 580.00\n"
    assert secret not in json.dumps(collect(runner=runner), sort_keys=True)


def test_evidence_is_deterministic_and_digest_covers_unsigned_payload() -> None:
    first = collect()
    second = collect()
    assert first == second
    digest = first.pop("evidence_sha256")
    canonical = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
    assert digest == hashlib.sha256(canonical).hexdigest()


def test_schema_rejects_extra_fields_and_false_runtime_claim() -> None:
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    extra = collect()
    extra["secret"] = "not admitted"
    assert list(validator.iter_errors(extra))
    false_claim = collect()
    false_claim["summary"]["runtime_feature_qualification_performed"] = True
    assert list(validator.iter_errors(false_claim))


def test_cli_inspect_requires_exact_acknowledgement_without_execution() -> None:
    with (
        mock.patch.object(
            collector, "collect_evidence", side_effect=AssertionError("collected")
        ),
        mock.patch.object(
            collector.Path, "lstat", side_effect=AssertionError("host stat")
        ),
    ):
        assert collector.main(["inspect"]) == 2
        assert collector.main(["inspect", "--acknowledgement", "wrong"]) == 2


def test_cli_validates_sources_before_ngc_candidate_stat(monkeypatch) -> None:
    monkeypatch.setattr(
        collector,
        "load_bound_oracles",
        mock.Mock(side_effect=collector.EvidenceError("source drift")),
    )
    with mock.patch.object(
        collector.Path, "lstat", side_effect=AssertionError("host stat")
    ):
        assert (
            collector.main(
                [
                    "inspect",
                    "--acknowledgement",
                    collector.EXPECTED_ACKNOWLEDGEMENT,
                ]
            )
            == 2
        )


def test_cli_validates_locked_schema_before_ngc_candidate_stat(monkeypatch) -> None:
    monkeypatch.setattr(collector, "EXPECTED_RESULT_SCHEMA_SHA256", "0" * 64)
    with mock.patch.object(
        collector.Path, "lstat", side_effect=AssertionError("host stat")
    ):
        assert (
            collector.main(
                [
                    "inspect",
                    "--acknowledgement",
                    collector.EXPECTED_ACKNOWLEDGEMENT,
                ]
            )
            == 2
        )
