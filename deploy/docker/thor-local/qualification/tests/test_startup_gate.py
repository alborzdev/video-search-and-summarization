# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for reboot-safe Thor service startup ordering."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
from threading import Thread


REPO_ROOT = Path(__file__).resolve().parents[5]
GATE = REPO_ROOT / "deploy/docker/thor-local/startup-gate.py"
THOR_COMPOSE = REPO_ROOT / "deploy/docker/thor-local/compose.yml"
EDGE_COMPOSE = REPO_ROOT / "deploy/docker/thor-local/official-edge/compose.yml"


class _ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReadyHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_http_gate_executes_command_after_dependency_is_ready() -> None:
    with _http_server() as port:
        result = subprocess.run(
            [
                "python3",
                str(GATE),
                "--http",
                f"http://127.0.0.1:{port}/ready",
                "--timeout-seconds",
                "2",
                "--",
                "python3",
                "-c",
                "print('model-started')",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
    assert result.returncode == 0
    assert "model-started" in result.stdout


def test_tcp_gate_times_out_fail_closed() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]
    result = subprocess.run(
        [
            "python3",
            str(GATE),
            "--tcp",
            f"127.0.0.1:{unused_port}",
            "--timeout-seconds",
            "0.1",
            "--",
            "python3",
            "-c",
            "raise SystemExit(99)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode == 75
    assert "timed out" in result.stderr


def test_compose_declares_reboot_safe_model_order() -> None:
    thor = THOR_COMPOSE.read_text(encoding="utf-8")
    edge = EDGE_COMPOSE.read_text(encoding="utf-8")
    assert "host.docker.internal:9092" in thor
    assert "command: [/opt/nvidia/rtvi/start_rtvi_vlm.sh]" in thor
    assert "http://127.0.0.1:8018/v1/health/ready" in edge
    assert "startup-gate.py:/usr/local/bin/thor-startup-gate.py:ro" in edge
    assert "condition: service_healthy" in edge
    assert 'VLLM_KV_CACHE_MEMORY_BYTES: "4294967296"' in edge
    assert 'VLLM_GPU_MEMORY_UTILIZATION: "0.30"' in edge
