# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tegrastats_exporter.py"
SPEC = importlib.util.spec_from_file_location("tegrastats_exporter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


THOR_SAMPLE = (
    "07-31-2026 14:45:55 RAM 86905/125772MB (lfb 368x4MB) "
    "CPU [12%@972,10%@972,off,33%@1890] cpu@39.812C tj@39.906C "
    "soc012@38.812C gpu@39.906C soc345@38.625C "
    "VDD_GPU 3561mW/3561mW VDD_CPU_SOC_MSS 7910mW/7910mW "
    "VIN_SYS_5V0 7620mW/7620mW VIN 26686mW/26686mW"
)


class ParseTests(unittest.TestCase):
    def test_collector_uses_matching_host_loader_without_shell(self) -> None:
        self.assertEqual(
            EXPORTER.collector_command(
                "/usr/local/bin/tegrastats",
                "/opt/host/ld-linux-aarch64.so.1",
                "/opt/host",
                1000,
            ),
            [
                "/opt/host/ld-linux-aarch64.so.1",
                "--library-path",
                "/opt/host",
                "/usr/local/bin/tegrastats",
                "--interval",
                "1000",
            ],
        )

    def test_current_thor_format(self) -> None:
        parsed = EXPORTER.parse_tegrastats_line(THOR_SAMPLE)
        self.assertEqual(parsed["ram_used_bytes"], 86905 * 1024 * 1024)
        self.assertEqual(parsed["ram_total_bytes"], 125772 * 1024 * 1024)
        self.assertEqual(parsed["ram_largest_free_block_count"], 368)
        self.assertEqual(parsed["ram_largest_free_block_bytes"], 4 * 1024 * 1024)
        cores = parsed["cpu_cores"]
        self.assertEqual(len(cores), 4)
        self.assertEqual(cores[0]["utilization_ratio"], 0.12)
        self.assertEqual(cores[1]["frequency_hertz"], 972_000_000)
        self.assertEqual(cores[2], {"core": 2.0, "online": 0.0})
        self.assertEqual(parsed["temperatures_celsius"]["gpu"], 39.906)
        self.assertEqual(parsed["power_milliwatts"]["VDD_GPU"], (3561.0, 3561.0))

    def test_legacy_jetson_format(self) -> None:
        line = (
            "RAM 2201/3956MB (lfb 83x4MB) SWAP 12/1978MB (cached 3MB) "
            "CPU [0%@345,99%@2035] EMC_FREQ 12%@1600 GR3D_FREQ 77%@918 "
            "AO@42.5C GPU@43C VDD_IN 2340mW/2300mW"
        )
        parsed = EXPORTER.parse_tegrastats_line(line)
        self.assertEqual(parsed["swap_used_bytes"], 12 * 1024 * 1024)
        self.assertEqual(parsed["swap_cached_bytes"], 3 * 1024 * 1024)
        self.assertEqual(parsed["emc_utilization_ratio"], 0.12)
        self.assertEqual(parsed["emc_frequency_hertz"], 1_600_000_000)
        self.assertEqual(parsed["gpu_utilization_ratio"], 0.77)
        self.assertEqual(parsed["gpu_frequency_hertz"], 918_000_000)

    def test_rejects_unrecognized_and_oversized_lines(self) -> None:
        with self.assertRaises(ValueError):
            EXPORTER.parse_tegrastats_line("unrecognized output")
        with self.assertRaises(ValueError):
            EXPORTER.parse_tegrastats_line("x" * (EXPORTER.MAX_LINE_BYTES + 1))

    def test_label_count_and_length_are_bounded(self) -> None:
        zones = " ".join(f"zone{i}@{i}.5C" for i in range(100))
        rails = " ".join(f"RAIL_{i} {i}mW/{i}mW" for i in range(100))
        parsed = EXPORTER.parse_tegrastats_line(f"{zones} {rails}")
        self.assertEqual(len(parsed["temperatures_celsius"]), EXPORTER.MAX_TEMPERATURES)
        self.assertEqual(len(parsed["power_milliwatts"]), EXPORTER.MAX_POWER_RAILS)
        self.assertTrue(
            all(len(label) <= EXPORTER.MAX_LABEL_LENGTH for label in parsed["temperatures_celsius"])
        )


class StateAndRenderTests(unittest.TestCase):
    def test_fails_closed_until_fresh_sample(self) -> None:
        state = EXPORTER.ExporterState(stale_after_seconds=1.0)
        body, ready = EXPORTER.render_metrics(state)
        self.assertFalse(ready)
        self.assertIn(b"jetson_tegrastats_up 0", body)
        state.set_child_running(True)
        state.record_sample(EXPORTER.parse_tegrastats_line(THOR_SAMPLE))
        body, ready = EXPORTER.render_metrics(state)
        self.assertTrue(ready)
        self.assertIn(b"jetson_tegrastats_up 1", body)
        self.assertIn(b'jetson_tegrastats_temperature_celsius{zone="gpu"} 39.906', body)
        self.assertNotIn(THOR_SAMPLE.encode(), body)

    def test_stale_sample_fails_closed(self) -> None:
        state = EXPORTER.ExporterState(stale_after_seconds=0.001)
        state.set_child_running(True)
        state.record_sample(EXPORTER.parse_tegrastats_line(THOR_SAMPLE))
        time.sleep(0.01)
        _, ready = EXPORTER.render_metrics(state)
        self.assertFalse(ready)

    def test_stream_reader_counts_errors_and_oversize(self) -> None:
        state = EXPORTER.ExporterState(stale_after_seconds=5.0)
        stream = io.BytesIO(
            b"not metrics\n"
            + b"x" * (EXPORTER.MAX_LINE_BYTES + 50)
            + b"\n"
            + THOR_SAMPLE.encode()
            + b"\n"
        )
        EXPORTER.collect_stream(stream, state, EXPORTER.threading.Event())
        self.assertEqual(state.parse_errors_total, 1)
        self.assertEqual(state.lines_too_long_total, 1)
        self.assertEqual(state.samples_total, 1)

    def test_http_health_readiness_and_metrics_fail_closed(self) -> None:
        state = EXPORTER.ExporterState(stale_after_seconds=5.0)
        server = EXPORTER.ExporterServer(0, state)
        self.assertEqual(server.server_address[0], EXPORTER.BIND_ADDRESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(f"{origin}/healthz", timeout=1) as response:
                self.assertEqual(response.status, 200)
            for path in ("/readyz", "/metrics"):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(f"{origin}{path}", timeout=1)
                self.assertEqual(error.exception.code, 503)

            state.set_child_running(True)
            state.record_sample(EXPORTER.parse_tegrastats_line(THOR_SAMPLE))
            with urllib.request.urlopen(f"{origin}/readyz", timeout=1) as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(f"{origin}/metrics", timeout=1) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"jetson_tegrastats_up 1", response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
