# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for Thor-local RTVI-CV self-healing."""

from pathlib import Path
import os
import signal
import subprocess
import time


REPO_ROOT = Path(__file__).resolve().parents[5]
HEALTHCHECK = REPO_ROOT / "deploy/docker/thor-local/rtvi-cv-healthcheck.sh"
SUPERVISOR = REPO_ROOT / "deploy/docker/thor-local/rtvi-cv-supervisor.sh"
COMPOSE = REPO_ROOT / "deploy/docker/thor-local/compose.yml"


def _run_healthcheck(tmp_path: Path, curl_exit: int) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(f"#!/bin/sh\nexit {curl_exit}\n", encoding="utf-8")
    fake_curl.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "RTVI_CV_HEALTHCHECK_STATE_DIR": str(tmp_path / "state"),
            "RTVI_CV_HEALTHCHECK_RESTART_MARKER": str(tmp_path / "restart-requested"),
            "RTVI_CV_HEALTHCHECK_FAILURE_THRESHOLD": "3",
        }
    )
    return subprocess.run(
        ["bash", str(HEALTHCHECK)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_never_restarts_before_first_success(tmp_path: Path) -> None:
    for _ in range(4):
        assert _run_healthcheck(tmp_path, curl_exit=1).returncode == 1

    assert not (tmp_path / "restart-requested").exists()


def test_restarts_after_three_runtime_failures(tmp_path: Path) -> None:
    assert _run_healthcheck(tmp_path, curl_exit=0).returncode == 0
    assert (tmp_path / "state/ready-ever").exists()

    assert _run_healthcheck(tmp_path, curl_exit=1).returncode == 1
    assert _run_healthcheck(tmp_path, curl_exit=1).returncode == 1
    assert not (tmp_path / "restart-requested").exists()

    assert _run_healthcheck(tmp_path, curl_exit=1).returncode == 1
    assert (tmp_path / "restart-requested").exists()


def test_success_clears_runtime_failure_count(tmp_path: Path) -> None:
    assert _run_healthcheck(tmp_path, curl_exit=0).returncode == 0
    assert _run_healthcheck(tmp_path, curl_exit=1).returncode == 1
    assert (tmp_path / "state/failures").read_text(encoding="utf-8").strip() == "1"

    assert _run_healthcheck(tmp_path, curl_exit=0).returncode == 0
    assert not (tmp_path / "state/failures").exists()


def test_supervisor_turns_recovery_signal_into_restartable_exit() -> None:
    process = subprocess.Popen(
        [
            "bash",
            str(SUPERVISOR),
            "bash",
            "-c",
            "trap 'exit 0' TERM; while true; do sleep 0.1; done",
        ]
    )
    try:
        time.sleep(0.1)
        os.kill(process.pid, signal.SIGUSR1)
        assert process.wait(timeout=3) == 70
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


def test_compose_installs_self_healing_healthcheck() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    healthcheck = HEALTHCHECK.read_text(encoding="utf-8")
    assert (
        "${VSS_REPO_ROOT}/deploy/docker/thor-local/rtvi-cv-healthcheck.sh:"
        "/usr/local/bin/rtvi-cv-healthcheck:ro"
    ) in compose
    assert 'test: ["CMD", "/usr/local/bin/rtvi-cv-healthcheck"]' in compose
    assert "restart: unless-stopped" in compose
    assert "kill -USR1 1" in healthcheck
    assert 'entrypoint: ["/usr/local/bin/rtvi-cv-supervisor"]' in compose
    assert "/usr/local/bin/rtvi-cv-supervisor:ro" in compose
