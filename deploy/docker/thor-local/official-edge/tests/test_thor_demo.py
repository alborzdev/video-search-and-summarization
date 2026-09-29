from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import official_edge as oe  # noqa: E402
import thor_demo as td  # noqa: E402

from test_official_edge import make_edge_cache, make_runtime_env  # noqa: E402


class ThorDemoStaticTests(unittest.TestCase):
    def test_production_cli_has_no_meminfo_override(self) -> None:
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            td._parser().parse_args(["--meminfo", "/tmp/fabricated", "audit"])

    def test_thor_operator_wrapper_detects_and_protects_demo_lane(self) -> None:
        wrapper = (oe.DEPLOY_DOCKER / "scripts/thor-local.sh").read_text(
            encoding="utf-8"
        )
        for token in (
            'official_edge_llm_endpoint="http://127.0.0.1:30081"',
            'official_edge_vlm_endpoint="http://127.0.0.1:8018"',
            'official_edge_llm_model="nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"',
            'official_edge_vlm_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final"',
            "official_edge_demo_lane_is_deployed()",
            "com.docker.compose.project.config_files",
            "compose.thor-demo-memory.yml",
            "Active exact-model Thor demo lane detected.",
            "An exact-model Thor lane or stale exact-model container is present.",
            "require_periodic_cache_cleaner_stopped()",
            "Periodic cache cleaner: stopped (required for exact dual-model safety)",
            "stop_fail_closed_containers()",
            "docker update --restart=no",
            "Official Nemotron 3 LLM endpoint: ready",
            "Official Cosmos3 VLM endpoint: ready",
        ):
            self.assertIn(token, wrapper)

    def test_overlay_is_exact_and_official_defaults_remain_unchanged(self) -> None:
        contract = td.verify_static()
        self.assertEqual(contract["unified_memory"]["llm_fraction"], "0.25")
        self.assertEqual(contract["unified_memory"]["vlm_fraction"], "0.30")
        self.assertEqual(oe.EDGE_COMMAND[-4], "0.25")
        self.assertEqual(td.DEMO_EDGE_COMMAND[-4], "0.12")
        self.assertEqual(td.DEMO_EDGE_COMMAND.count("--enforce-eager"), 1)
        self.assertEqual(td.VLM_FRACTION, td.Decimal("0.30"))
        self.assertEqual(td.RESERVE_FRACTION, td.Decimal("0.28"))
        self.assertEqual(td.REQUIRED_AVAILABLE_FRACTION, td.Decimal("0.70"))

    def test_overlay_rejects_any_third_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            overlay = Path(temporary) / "overlay.yml"
            overlay.write_text(
                td.DEMO_COMPOSE.read_text(encoding="utf-8")
                + "\n    image: example.invalid/drift\n",
                encoding="utf-8",
            )
            with mock.patch.object(td, "DEMO_COMPOSE", overlay):
                with self.assertRaisesRegex(oe.ContractError, "change only command"):
                    td.verify_overlay_contract()

    def test_memory_gate_enforces_seventy_percent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            meminfo = Path(temporary) / "meminfo"
            meminfo.write_text(
                "MemTotal: 100000 kB\nMemAvailable: 70000 kB\n",
                encoding="utf-8",
            )
            td.verify_memory(meminfo)
            meminfo.write_text(
                "MemTotal: 100000 kB\nMemAvailable: 69999 kB\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(oe.ContractError, "0.12 Edge4B"):
                td.verify_memory(meminfo)

    def test_empirical_headroom_blocks_the_observed_128g_host_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            meminfo = Path(temporary) / "meminfo"
            meminfo.write_text(
                "MemTotal: 134217728 kB\nMemAvailable: 111149056 kB\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(oe.ContractError, "64 GiB post-load reserve"):
                td.verify_empirical_headroom(meminfo)
            meminfo.write_text(
                "MemTotal: 268435456 kB\nMemAvailable: 209715200 kB\n",
                encoding="utf-8",
            )
            td.verify_empirical_headroom(meminfo)

    def test_periodic_cache_cleaner_is_rejected_for_the_dual_model_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            process = proc / "123"
            process.mkdir()
            (process / "cmdline").write_bytes(
                b"/bin/bash\0/usr/local/bin/sys-cache-cleaner.sh\0"
            )
            with self.assertRaisesRegex(oe.ContractError, "periodic cache cleaner"):
                td.verify_periodic_cache_cleaner_stopped(proc)
            (process / "cmdline").write_bytes(b"/bin/bash\0unrelated.sh\0")
            td.verify_periodic_cache_cleaner_stopped(proc)

    def test_pull_free_renderer_includes_final_demo_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            edge, _ = make_edge_cache(Path(temporary))
            cosmos = Path("/verified") / oe.COSMOS_CACHE_DIRECTORY
            command = td.render_pull_free_command(
                oe.DEFAULT_RUNTIME_ENV, edge, cosmos, "172.17.0.1"
            )
        self.assertIn(str(td.DEMO_COMPOSE), command)
        self.assertIn("--no-build", command)
        self.assertIn("--pull never", command)
        self.assertIn("THOR_LOCAL_MODEL_BIND_HOST=172.17.0.1", command)
        self.assertNotIn("docker pull", command)
        self.assertTrue(
            command.endswith("up -d --no-build --pull never --force-recreate")
        )

    def test_resolved_graph_differs_only_in_edge_memory_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edge, _ = make_edge_cache(root)
            cosmos = root / "ngc" / oe.COSMOS_CACHE_DIRECTORY
            cosmos.mkdir(parents=True)
            tracked_env = make_runtime_env(root)
            with mock.patch.dict(
                os.environ,
                {
                    "VSS_APPS_DIR": str(oe.DEPLOY_DOCKER),
                    "VSS_DATA_DIR": str(oe.DEPLOY_DOCKER / "data-dir"),
                },
                clear=False,
            ):
                resolved = td.verify_resolved_compose(tracked_env, edge, cosmos)
        services = resolved["services"]
        self.assertEqual(services["nemotron-edge"]["command"], td.DEMO_EDGE_COMMAND)
        self.assertEqual(
            services["rtvi-vlm"]["environment"]["VLLM_GPU_MEMORY_UTILIZATION"],
            "0.30",
        )
        for service in (
            "nemotron-edge",
            "rtvi-vlm",
            "lvs-server",
            "rtvi-embed",
            "perception-2d-fusion",
            "perception-2d-smartcity-thor",
            "streamprocessing-ms",
            "sensor-ms",
            "vss-agent",
        ):
            with self.subTest(service=service):
                self.assertEqual(services[service]["restart"], "no")
        self.assertEqual(
            services["redis"]["command"],
            [
                "redis-server",
                "/config/redis.conf",
                "--bind",
                "127.0.0.1",
                "172.17.0.1",
                "--protected-mode",
                "no",
            ],
        )


class ThorDemoReadinessTests(unittest.TestCase):
    def test_runtime_verifier_requires_demo_memory_values(self) -> None:
        contract = oe._load_json(oe.DEFAULT_CONTRACT)
        with (
            mock.patch.object(oe, "_verify_running_container") as containers,
            mock.patch.object(oe, "_verify_running_environment"),
            mock.patch.object(oe, "_verify_fail_closed_runtime_container"),
            mock.patch.object(oe, "_verify_model_endpoint"),
            mock.patch.object(oe, "_get_json"),
            mock.patch.object(oe, "_edge_repository", return_value=Path("/hf")),
            mock.patch.object(td, "verify_empirical_headroom"),
        ):
            td.verify_readiness(
                contract,
                1.0,
                Path("/hf/snapshots/revision"),
                Path("/ngc") / oe.COSMOS_CACHE_DIRECTORY,
            )
        self.assertEqual(containers.call_args_list[0].args[3], td.DEMO_EDGE_COMMAND)
        self.assertEqual(
            containers.call_args_list[1].args[4]["VLLM_GPU_MEMORY_UTILIZATION"],
            "0.30",
        )


if __name__ == "__main__":
    unittest.main()
