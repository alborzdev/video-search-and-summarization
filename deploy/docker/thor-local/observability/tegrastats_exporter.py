#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Expose bounded Jetson tegrastats samples in Prometheus text format."""

from __future__ import annotations

import argparse
import ipaddress
import math
import re
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import BinaryIO

BIND_ADDRESS = "127.0.0.1"
DEFAULT_TEGRSTATS_PATH = "/usr/local/bin/tegrastats"
DEFAULT_LOADER_PATH = "/opt/tegrastats-runtime/ld-linux-aarch64.so.1"
DEFAULT_LIBRARY_PATH = "/opt/tegrastats-runtime"
MAX_LINE_BYTES = 16 * 1024
MAX_CPU_CORES = 128
MAX_TEMPERATURES = 32
MAX_POWER_RAILS = 32
MAX_LABEL_LENGTH = 48
RESTART_BACKOFF_SECONDS = 5.0

_RAM_RE = re.compile(
    r"\bRAM\s+(?P<used>\d+)/(?P<total>\d+)MB"
    r"(?:\s+\(lfb\s+(?P<lfb_count>\d+)x(?P<lfb_size>\d+)MB\))?"
)
_SWAP_RE = re.compile(
    r"\bSWAP\s+(?P<used>\d+)/(?P<total>\d+)MB" r"(?:\s+\(cached\s+(?P<cached>\d+)MB\))?"
)
_CPU_RE = re.compile(r"\bCPU\s+\[(?P<cores>[^\]]*)\]")
_CPU_CORE_RE = re.compile(r"^(?P<util>\d+)%@(?P<mhz>\d+)$")
_GPU_RE = re.compile(
    r"\bGR3D_FREQ\s+(?P<util>\d+)%" r"(?:@(?P<frequency>\d+)(?:MHz)?)?"
)
_EMC_RE = re.compile(
    r"\bEMC(?:_FREQ)?\s+(?P<util>\d+)%" r"(?:@(?P<frequency>\d+)(?:MHz)?)?"
)
_TEMPERATURE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<zone>[A-Za-z][A-Za-z0-9_]*)@"
    r"(?P<value>-?\d+(?:\.\d+)?)C\b"
)
_POWER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<rail>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?P<current>\d+)mW/(?P<average>\d+)mW\b"
)
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_:]")


def _bounded_label(value: str) -> str:
    """Return a stable, Prometheus-safe label with bounded cardinality size."""

    return _SAFE_LABEL_RE.sub("_", value)[:MAX_LABEL_LENGTH]


def parse_tegrastats_line(line: str) -> dict[str, object]:
    """Parse one sample without assuming a particular JetPack field order."""

    if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
        raise ValueError("tegrastats sample exceeds the bounded line size")

    metrics: dict[str, object] = {}
    ram = _RAM_RE.search(line)
    if ram:
        metrics["ram_used_bytes"] = int(ram.group("used")) * 1024 * 1024
        metrics["ram_total_bytes"] = int(ram.group("total")) * 1024 * 1024
        if ram.group("lfb_count") is not None:
            metrics["ram_largest_free_block_count"] = int(ram.group("lfb_count"))
            metrics["ram_largest_free_block_bytes"] = (
                int(ram.group("lfb_size")) * 1024 * 1024
            )

    swap = _SWAP_RE.search(line)
    if swap:
        metrics["swap_used_bytes"] = int(swap.group("used")) * 1024 * 1024
        metrics["swap_total_bytes"] = int(swap.group("total")) * 1024 * 1024
        if swap.group("cached") is not None:
            metrics["swap_cached_bytes"] = int(swap.group("cached")) * 1024 * 1024

    cpu = _CPU_RE.search(line)
    if cpu:
        cores: list[dict[str, float]] = []
        for index, raw_core in enumerate(cpu.group("cores").split(",")[:MAX_CPU_CORES]):
            core = raw_core.strip()
            if core.lower() == "off":
                cores.append({"core": float(index), "online": 0.0})
                continue
            match = _CPU_CORE_RE.match(core)
            if match:
                cores.append(
                    {
                        "core": float(index),
                        "online": 1.0,
                        "utilization_ratio": min(int(match.group("util")), 100) / 100.0,
                        "frequency_hertz": int(match.group("mhz")) * 1_000_000.0,
                    }
                )
        if cores:
            metrics["cpu_cores"] = cores

    gpu = _GPU_RE.search(line)
    if gpu:
        metrics["gpu_utilization_ratio"] = min(int(gpu.group("util")), 100) / 100.0
        if gpu.group("frequency") is not None:
            metrics["gpu_frequency_hertz"] = int(gpu.group("frequency")) * 1_000_000.0

    emc = _EMC_RE.search(line)
    if emc:
        metrics["emc_utilization_ratio"] = min(int(emc.group("util")), 100) / 100.0
        if emc.group("frequency") is not None:
            metrics["emc_frequency_hertz"] = int(emc.group("frequency")) * 1_000_000.0

    temperatures: dict[str, float] = {}
    for match in _TEMPERATURE_RE.finditer(line):
        if len(temperatures) >= MAX_TEMPERATURES:
            break
        label = _bounded_label(match.group("zone"))
        if label:
            temperatures[label] = float(match.group("value"))
    if temperatures:
        metrics["temperatures_celsius"] = temperatures

    rails: dict[str, tuple[float, float]] = {}
    for match in _POWER_RE.finditer(line):
        if len(rails) >= MAX_POWER_RAILS:
            break
        label = _bounded_label(match.group("rail"))
        if label:
            rails[label] = (
                float(match.group("current")),
                float(match.group("average")),
            )
    if rails:
        metrics["power_milliwatts"] = rails

    if not metrics:
        raise ValueError("tegrastats sample contains no recognized metrics")
    return metrics


class ExporterState:
    """Thread-safe sample and exporter self-metric store."""

    def __init__(self, stale_after_seconds: float) -> None:
        self.stale_after_seconds = stale_after_seconds
        self._lock = threading.Lock()
        self._sample: dict[str, object] = {}
        self._sample_monotonic: float | None = None
        self.samples_total = 0
        self.parse_errors_total = 0
        self.lines_too_long_total = 0
        self.restarts_total = 0
        self.child_running = False

    def record_sample(self, sample: dict[str, object]) -> None:
        with self._lock:
            self._sample = sample
            self._sample_monotonic = time.monotonic()
            self.samples_total += 1

    def record_parse_error(self) -> None:
        with self._lock:
            self.parse_errors_total += 1

    def record_line_too_long(self) -> None:
        with self._lock:
            self.lines_too_long_total += 1

    def set_child_running(self, running: bool) -> None:
        with self._lock:
            self.child_running = running

    def record_restart(self) -> None:
        with self._lock:
            self.restarts_total += 1

    def snapshot(self) -> tuple[dict[str, object], dict[str, float], bool]:
        with self._lock:
            age = (
                math.inf
                if self._sample_monotonic is None
                else max(0.0, time.monotonic() - self._sample_monotonic)
            )
            self_metrics = {
                "sample_age_seconds": age,
                "samples_total": float(self.samples_total),
                "parse_errors_total": float(self.parse_errors_total),
                "lines_too_long_total": float(self.lines_too_long_total),
                "restarts_total": float(self.restarts_total),
                "child_running": 1.0 if self.child_running else 0.0,
            }
            ready = self.child_running and age <= self.stale_after_seconds
            return dict(self._sample), self_metrics, ready


def _format_value(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    if math.isinf(value):
        return "+Inf"
    return format(value, ".12g")


def render_metrics(state: ExporterState) -> tuple[bytes, bool]:
    sample, self_metrics, ready = state.snapshot()
    lines = [
        "# HELP jetson_tegrastats_up Whether tegrastats is running with a fresh parsed sample.",
        "# TYPE jetson_tegrastats_up gauge",
        f"jetson_tegrastats_up {1 if ready else 0}",
        "# HELP jetson_tegrastats_sample_age_seconds Age of the latest parsed sample.",
        "# TYPE jetson_tegrastats_sample_age_seconds gauge",
        f"jetson_tegrastats_sample_age_seconds {_format_value(self_metrics['sample_age_seconds'])}",
        "# HELP jetson_tegrastats_samples_total Successfully parsed samples.",
        "# TYPE jetson_tegrastats_samples_total counter",
        f"jetson_tegrastats_samples_total {_format_value(self_metrics['samples_total'])}",
        "# HELP jetson_tegrastats_parse_errors_total Samples rejected because no supported field could be parsed.",
        "# TYPE jetson_tegrastats_parse_errors_total counter",
        f"jetson_tegrastats_parse_errors_total {_format_value(self_metrics['parse_errors_total'])}",
        "# HELP jetson_tegrastats_lines_too_long_total Samples rejected at the input size bound.",
        "# TYPE jetson_tegrastats_lines_too_long_total counter",
        f"jetson_tegrastats_lines_too_long_total {_format_value(self_metrics['lines_too_long_total'])}",
        "# HELP jetson_tegrastats_restarts_total Collector subprocess restart attempts.",
        "# TYPE jetson_tegrastats_restarts_total counter",
        f"jetson_tegrastats_restarts_total {_format_value(self_metrics['restarts_total'])}",
        "# HELP jetson_tegrastats_process_running Whether the tegrastats subprocess is running.",
        "# TYPE jetson_tegrastats_process_running gauge",
        f"jetson_tegrastats_process_running {_format_value(self_metrics['child_running'])}",
    ]

    simple_metrics = {
        "ram_used_bytes": "gauge",
        "ram_total_bytes": "gauge",
        "ram_largest_free_block_count": "gauge",
        "ram_largest_free_block_bytes": "gauge",
        "swap_used_bytes": "gauge",
        "swap_total_bytes": "gauge",
        "swap_cached_bytes": "gauge",
        "gpu_utilization_ratio": "gauge",
        "gpu_frequency_hertz": "gauge",
        "emc_utilization_ratio": "gauge",
        "emc_frequency_hertz": "gauge",
    }
    for name, metric_type in simple_metrics.items():
        if name in sample:
            full_name = f"jetson_tegrastats_{name}"
            lines.extend(
                [
                    f"# TYPE {full_name} {metric_type}",
                    f"{full_name} {_format_value(sample[name])}",
                ]
            )

    cpu_cores = sample.get("cpu_cores", [])
    if isinstance(cpu_cores, list) and cpu_cores:
        lines.extend(
            [
                "# TYPE jetson_tegrastats_cpu_online gauge",
                "# TYPE jetson_tegrastats_cpu_utilization_ratio gauge",
                "# TYPE jetson_tegrastats_cpu_frequency_hertz gauge",
            ]
        )
        for core in cpu_cores:
            if not isinstance(core, dict):
                continue
            core_label = str(int(core["core"]))
            lines.append(
                f'jetson_tegrastats_cpu_online{{core="{core_label}"}} {_format_value(core["online"])}'
            )
            if "utilization_ratio" in core:
                lines.append(
                    f'jetson_tegrastats_cpu_utilization_ratio{{core="{core_label}"}} '
                    f'{_format_value(core["utilization_ratio"])}'
                )
            if "frequency_hertz" in core:
                lines.append(
                    f'jetson_tegrastats_cpu_frequency_hertz{{core="{core_label}"}} '
                    f'{_format_value(core["frequency_hertz"])}'
                )

    temperatures = sample.get("temperatures_celsius", {})
    if isinstance(temperatures, dict) and temperatures:
        lines.append("# TYPE jetson_tegrastats_temperature_celsius gauge")
        for zone, value in sorted(temperatures.items()):
            lines.append(
                f'jetson_tegrastats_temperature_celsius{{zone="{zone}"}} {_format_value(value)}'
            )

    power = sample.get("power_milliwatts", {})
    if isinstance(power, dict) and power:
        lines.append("# TYPE jetson_tegrastats_power_milliwatts gauge")
        for rail, values in sorted(power.items()):
            current, average = values
            lines.append(
                f'jetson_tegrastats_power_milliwatts{{rail="{rail}",aggregation="current"}} '
                f"{_format_value(current)}"
            )
            lines.append(
                f'jetson_tegrastats_power_milliwatts{{rail="{rail}",aggregation="average"}} '
                f"{_format_value(average)}"
            )

    return ("\n".join(lines) + "\n").encode("utf-8"), ready


def _discard_remainder(stream: BinaryIO) -> None:
    while True:
        chunk = stream.readline(MAX_LINE_BYTES + 1)
        if not chunk or chunk.endswith(b"\n"):
            return


def collector_command(
    executable: str, loader: str, library_path: str, interval_ms: int
) -> list[str]:
    """Build the shell-free command using the matching host runtime."""

    return [
        loader,
        "--library-path",
        library_path,
        executable,
        "--interval",
        str(interval_ms),
    ]


def collect_stream(
    stream: BinaryIO, state: ExporterState, stop_event: threading.Event
) -> None:
    """Read newline-delimited samples while bounding every allocation."""

    while not stop_event.is_set():
        raw = stream.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE_BYTES:
            if not raw.endswith(b"\n"):
                _discard_remainder(stream)
            state.record_line_too_long()
            continue
        try:
            state.record_sample(
                parse_tegrastats_line(raw.decode("utf-8", errors="replace"))
            )
        except ValueError:
            state.record_parse_error()


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "ThorTegrastatsExporter/1"
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/healthz":
            self._reply(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if self.path == "/readyz":
            _, _, ready = self.server.exporter_state.snapshot()  # type: ignore[attr-defined]
            self._reply(
                200 if ready else 503,
                b"ready\n" if ready else b"not ready\n",
                "text/plain; charset=utf-8",
            )
            return
        if self.path == "/metrics":
            body, ready = render_metrics(self.server.exporter_state)  # type: ignore[attr-defined]
            self._reply(
                200 if ready else 503, body, "text/plain; version=0.0.4; charset=utf-8"
            )
            return
        self._reply(404, b"not found\n", "text/plain; charset=utf-8")

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class ExporterServer(HTTPServer):
    allow_reuse_address = True

    def __init__(
        self, port: int, state: ExporterState, bind_address: str = BIND_ADDRESS
    ) -> None:
        super().__init__((bind_address, port), MetricsHandler)
        self.exporter_state = state


def collector_supervisor(
    executable: str,
    loader: str,
    library_path: str,
    interval_ms: int,
    state: ExporterState,
    stop_event: threading.Event,
    process_holder: list[subprocess.Popen[bytes] | None],
) -> None:
    while not stop_event.is_set():
        state.record_restart()
        try:
            process = subprocess.Popen(
                collector_command(executable, loader, library_path, interval_ms),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
        except OSError:
            state.set_child_running(False)
            stop_event.wait(RESTART_BACKOFF_SECONDS)
            continue
        process_holder[0] = process
        state.set_child_running(True)
        assert process.stdout is not None
        collect_stream(process.stdout, state, stop_event)
        state.set_child_running(False)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        process_holder[0] = None
        stop_event.wait(RESTART_BACKOFF_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-address", default=BIND_ADDRESS)
    parser.add_argument("--port", type=int, default=19101)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--tegrastats", default=DEFAULT_TEGRSTATS_PATH)
    parser.add_argument("--loader", default=DEFAULT_LOADER_PATH)
    parser.add_argument("--library-path", default=DEFAULT_LIBRARY_PATH)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        bind_address = ipaddress.ip_address(args.bind_address)
    except ValueError:
        parser.error("--bind-address must be a literal IPv4 address")
    if (
        bind_address.version != 4
        or bind_address.is_unspecified
        or not (bind_address.is_loopback or bind_address.is_private)
    ):
        parser.error("--bind-address must be a loopback or private IPv4 address")
    if not 250 <= args.interval_ms <= 60_000:
        parser.error("--interval-ms must be between 250 and 60000")
    for name in ("tegrastats", "loader", "library_path"):
        if not getattr(args, name).startswith("/"):
            parser.error(f"--{name.replace('_', '-')} must be an absolute path")
    return args


def main() -> int:
    args = parse_args()
    state = ExporterState(stale_after_seconds=max(5.0, args.interval_ms / 1000.0 * 3.0))
    stop_event = threading.Event()
    process_holder: list[subprocess.Popen[bytes] | None] = [None]
    server = ExporterServer(args.port, state, args.bind_address)

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()
        process = process_holder[0]
        if process is not None and process.poll() is None:
            process.terminate()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    collector = threading.Thread(
        target=collector_supervisor,
        args=(
            args.tegrastats,
            args.loader,
            args.library_path,
            args.interval_ms,
            state,
            stop_event,
            process_holder,
        ),
        name="tegrastats-collector",
        daemon=True,
    )
    collector.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop_event.set()
        process = process_holder[0]
        if process is not None and process.poll() is None:
            process.terminate()
        collector.join(timeout=4)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
