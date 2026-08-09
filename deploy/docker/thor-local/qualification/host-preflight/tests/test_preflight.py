from __future__ import annotations

import json
import subprocess
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import preflight as pf  # noqa: E402


class FixtureRunner:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.calls: list[pf.Probe] = []
        self.values = values or {}

    def run(self, probe: pf.Probe) -> pf.ProbeResult:
        self.calls.append(probe)
        value = self.values.get(probe.id)
        if value is None:
            return pf.ProbeResult("unavailable", diagnostic="fixture unavailable")
        return pf.ProbeResult("ok", stdout=value, returncode=0)


class FixtureReader:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.calls: list[str] = []
        self.values = values or {}

    def read(self, key: str) -> pf.ProbeResult:
        self.calls.append(key)
        value = self.values.get(key)
        if value is None:
            return pf.ProbeResult("unavailable", diagnostic="fixture unavailable")
        return pf.ProbeResult("ok", stdout=value, returncode=0)


def complete_runner() -> FixtureRunner:
    return FixtureRunner(
        {
            "architecture": "aarch64\n",
            "kernel": "6.8.12-tegra\n",
            "l4t_package": "38.4.0-20260701000000\n",
            "toolkit_package": "1.18.0-1\n",
            "gpu": "0, NVIDIA Thor, 580.00, 122880 MiB\n",
            "docker_version": "29.2.1|29.2.1\n",
            "compose_version": "2.40.0\n",
            "docker_cgroup": "cgroupfs\n",
            "docker_runtimes": '{"io.containerd.runc.v2":{},"nvidia":{},"runc":{}}\n',
            "containers": "",
            "images": (
                "nvcr.io/nvidia/vss-core/vss-rt-vlm\t<none>\t"
                "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504\t"
                "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504\n"
            ),
            "ports": "LISTEN 0 4096 127.0.0.1:22 0.0.0.0:*\n",
            "disk_root": "1B-blocks Avail Use% Mounted on\n1000000000000 200000000000 80% /\n",
            "cache_cleaner": "1\n",
        }
    )


def complete_reader() -> FixtureReader:
    return FixtureReader(
        {
            "meminfo": "MemTotal:       100000 kB\nMemAvailable:    80000 kB\n",
            "os_release": 'ID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04"\n',
            "tegra_release": "# R38 (release), REVISION: 4.0\n",
            "device_model": "NVIDIA Jetson AGX Thor Developer Kit\x00",
            "docker_daemon": '{"exec-opts":["native.cgroupdriver=cgroupfs"]}\n',
            "vm_max_map_count": "262144\n",
            "net_core_rmem_max": "5242880\n",
            "net_core_wmem_max": "5242880\n",
        }
    )


class PlanSafetyTests(unittest.TestCase):
    def test_default_cli_mode_is_plan(self) -> None:
        self.assertEqual(pf.parse_args([]).mode, "plan")

    def test_plan_is_inert_and_lists_every_exact_probe(self) -> None:
        contract = pf.load_contract()
        with mock.patch.object(
            pf.subprocess, "run", side_effect=AssertionError("executed")
        ):
            plan = pf.build_plan(contract)
        self.assertEqual(plan["result"], "inert_plan")
        self.assertEqual(plan["safety"]["external_commands_executed"], 0)
        self.assertEqual(plan["safety"]["host_files_read"], 0)
        self.assertEqual(len(plan["inspect_plan"]["commands"]), len(pf.PROBES))
        self.assertIn(
            "container creation or helper containers",
            plan["inspect_plan"]["forbidden_operations"],
        )

    def test_command_surface_contains_no_lifecycle_or_network_verb(self) -> None:
        rendered = [
            item
            for probe in pf.PROBES.values()
            for item in (probe.executable, *probe.argv)
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
        }
        self.assertTrue(forbidden.isdisjoint(rendered))
        self.assertTrue(
            all(Path(probe.executable).is_absolute() for probe in pf.PROBES.values())
        )
        compose = pf.PROBES["compose_version"]
        self.assertEqual(compose.argv, ("compose", "version", "--short"))
        self.assertEqual(pf.PROBES["gpu"].executable, "/usr/sbin/nvidia-smi")


class AllowlistTests(unittest.TestCase):
    def test_runner_rejects_added_argument(self) -> None:
        original = pf.PROBES["containers"]
        with self.assertRaisesRegex(pf.PreflightError, "exact allowlisted"):
            pf.AllowlistedRunner().run(
                replace(original, argv=(*original.argv, "--quiet"))
            )

    def test_runner_rejects_changed_executable(self) -> None:
        original = pf.PROBES["ports"]
        with self.assertRaisesRegex(pf.PreflightError, "exact allowlisted"):
            pf.AllowlistedRunner().run(replace(original, executable="/bin/sh"))

    def test_runner_uses_no_shell_and_drops_ambient_environment(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="aarch64\n", stderr="")
        with mock.patch.object(pf.subprocess, "run", return_value=completed) as run:
            result = pf.AllowlistedRunner().run(pf.PROBES["architecture"])
        self.assertEqual(result.state, "ok")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/uname", "-m"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["env"]["HOME"], "/nonexistent")
        self.assertNotIn("NGC_API_KEY", kwargs["env"])
        self.assertNotIn("HF_TOKEN", kwargs["env"])

    def test_reader_rejects_arbitrary_path_key(self) -> None:
        with self.assertRaisesRegex(pf.PreflightError, "not allowlisted"):
            pf.AllowlistedReader().read("../../home/nvidia/.ngc/config")

    def test_runner_caps_output(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0, stdout="x" * (pf.MAX_CAPTURE_BYTES + 1), stderr=""
        )
        with mock.patch.object(pf.subprocess, "run", return_value=completed):
            result = pf.AllowlistedRunner().run(pf.PROBES["architecture"])
        self.assertEqual(result.state, "error")
        self.assertEqual(result.stdout, "")

    def test_cache_cleaner_zero_count_is_a_valid_read_only_observation(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="0\n", stderr="")
        with mock.patch.object(pf.subprocess, "run", return_value=completed):
            result = pf.AllowlistedRunner().run(pf.PROBES["cache_cleaner"])
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.returncode, 1)


class RedactionTests(unittest.TestCase):
    def test_recursive_and_token_redaction(self) -> None:
        value = {
            "NVIDIA_API_KEY": "nvapi-supersecretvalue",
            "message": "Authorization: Bearer abc.def and HF_TOKEN=hf_abcdefghijklmnop",
            "nested": [{"password": "do-not-print"}],
        }
        output = json.dumps(pf.redact(value))
        self.assertNotIn("supersecret", output)
        self.assertNotIn("abc.def", output)
        self.assertNotIn("abcdefghijklmnop", output)
        self.assertNotIn("do-not-print", output)
        self.assertIn(pf.REDACTED, output)

    def test_failed_probe_diagnostic_is_redacted(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="token=hf_abcdefghijklmnop"
        )
        with mock.patch.object(pf.subprocess, "run", return_value=completed):
            result = pf.AllowlistedRunner().run(pf.PROBES["architecture"])
        self.assertNotIn("abcdefghijklmnop", result.diagnostic)


class InspectionTests(unittest.TestCase):
    def test_requirement_drift_fails_closed(self) -> None:
        contract = deepcopy(pf._json_object(pf.DEFAULT_CONTRACT))
        contract["requirements"]["docker_minimum"] = "1.0.0"
        with mock.patch.object(pf, "_json_object", return_value=contract):
            with self.assertRaisesRegex(pf.PreflightError, "requirements drifted"):
                pf.load_contract()

    def test_mocked_inspection_calls_only_complete_catalog(self) -> None:
        runner = complete_runner()
        reader = complete_reader()
        report = pf.inspect_host(pf.load_contract(), runner, reader)
        self.assertEqual(runner.calls, list(pf.PROBES.values()))
        self.assertEqual(reader.calls, list(pf.HOST_FILES))
        self.assertFalse(report["summary"]["runtime_qualification_started"])
        self.assertEqual(report["resources"]["memory"]["status"], "pass")
        self.assertEqual(report["software"]["docker_server"]["status"], "pass")
        self.assertEqual(report["platform"]["bsp"]["status"], "pass")
        self.assertEqual(report["platform"]["gpu"]["status"], "pass")

    def test_memory_boundary_is_exactly_eighty_percent(self) -> None:
        passing = pf._memory("MemTotal: 100 kB\nMemAvailable: 80 kB\n", "0.80")
        failing = pf._memory("MemTotal: 100 kB\nMemAvailable: 79 kB\n", "0.80")
        self.assertEqual(passing["status"], "pass")
        self.assertEqual(failing["status"], "blocker")

    def test_architecture_mismatch_contributes_to_summary_blocker(self) -> None:
        runner = complete_runner()
        runner.values["architecture"] = "x86_64\n"
        with mock.patch.object(
            pf,
            "_official_edge",
            return_value={"status": "pass", "runtime_launch_ready": False},
        ):
            report = pf.inspect_host(pf.load_contract(), runner, complete_reader())
        self.assertEqual(report["platform"]["architecture"]["status"], "blocker")
        self.assertEqual(report["summary"]["result"], "blocker")

    def test_ports_and_existing_vss_container_are_reported_not_mutated(self) -> None:
        runner = complete_runner()
        runner.values["ports"] = "LISTEN 0 4096 0.0.0.0:7777 0.0.0.0:*\n"
        runner.values["containers"] = (
            "deadbeef\tvss-agent\tnvcr.io/nvidia/vss-agent:3.2.1\tUp 1 hour\t0.0.0.0:7777->7777/tcp\tmdx\n"
        )
        report = pf.inspect_host(pf.load_contract(), runner, complete_reader())
        ingress = next(item for item in report["ports"] if item["port"] == 7777)
        self.assertEqual(ingress["status"], "occupied")
        self.assertEqual(report["containers"]["status"], "conflict")
        self.assertEqual(report["containers"]["conflicts"][0]["name"], "vss-agent")

    def test_wrong_digest_is_an_image_conflict_not_exact_readiness(self) -> None:
        runner = complete_runner()
        runner.values["images"] = (
            "nvcr.io/nvidia/vss-core/vss-rt-vlm\t3.2.1\tsha256:wrong\tsha256:wrong-id\n"
        )
        report = pf.inspect_host(pf.load_contract(), runner, complete_reader())
        image = report["official_edge"]["images"]["rt_vlm"]
        self.assertEqual(image["status"], "missing_exact")
        self.assertEqual(len(image["conflicting_same_repository"]), 1)

    def test_current_official_edge_lock_is_complete_but_scan_remains_required(
        self,
    ) -> None:
        report = pf.inspect_host(
            pf.load_contract(), complete_runner(), complete_reader()
        )
        edge = report["official_edge"]
        self.assertEqual(edge["lock_state"], "complete_exact")
        self.assertFalse(edge["filesystem_trees_verified"])
        self.assertFalse(edge["runtime_launch_ready"])
        self.assertEqual(edge["status"], "blocker")
        self.assertFalse(any("not 'complete_exact'" in item for item in edge["blockers"]))
        self.assertTrue(any("not scanned" in item for item in edge["blockers"]))

    def test_daemon_json_is_summarized_without_echoing_unknown_keys(self) -> None:
        reader = complete_reader()
        reader.values["docker_daemon"] = (
            '{"exec-opts":["native.cgroupdriver=cgroupfs"],"registry-password":"never-echo"}'
        )
        report = pf.inspect_host(pf.load_contract(), complete_runner(), reader)
        output = json.dumps(report)
        self.assertNotIn("registry-password", output)
        self.assertNotIn("never-echo", output)
        self.assertTrue(
            report["software"]["docker_cgroup"]["daemon_config"]["cgroupfs_configured"]
        )

    def test_duplicate_daemon_json_key_is_a_blocker(self) -> None:
        reader = complete_reader()
        reader.values["docker_daemon"] = (
            '{"exec-opts":[],"exec-opts":["native.cgroupdriver=cgroupfs"]}'
        )
        report = pf.inspect_host(pf.load_contract(), complete_runner(), reader)
        daemon = report["software"]["docker_cgroup"]["daemon_config"]
        self.assertEqual(daemon["status"], "blocker")
        self.assertIn("duplicate object key", daemon["reason"])


if __name__ == "__main__":
    unittest.main()
