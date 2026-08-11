#!/usr/bin/env python3
"""Run the custom Sink probe inside the released Behavior Analytics image."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
IMAGE = "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1"
IMAGE_ID = "sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6"
CONTAINER = "vss-behavior-custom-sink-oracle"


def _run(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=timeout)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_probe() -> dict:
    state: dict = {}
    logs = ""
    result: dict = {}
    with tempfile.TemporaryDirectory(prefix="vss-custom-sink-") as temp_name:
        output_dir = Path(temp_name)
        os.chmod(output_dir, 0o777)
        try:
            _run("docker", "rm", "-f", CONTAINER, check=False)
            created = _run(
                "docker", "run", "-d", "--name", CONTAINER, "--user", "nvs",
                "-v", f"{HERE}:/probe:ro", "-v", f"{output_dir}:/output",
                IMAGE, "python3", "/probe/in_container_probe.py", "--output-dir", "/output",
            )
            if not created.stdout.strip():
                raise RuntimeError("docker run returned no container ID")
            _run("docker", "wait", CONTAINER, timeout=120)
            logs = _run("docker", "logs", CONTAINER).stdout
            inspected = json.loads(_run("docker", "inspect", CONTAINER).stdout)[0]
            state = {
                "exit_code": inspected["State"]["ExitCode"],
                "oom_killed": inspected["State"]["OOMKilled"],
                "restart_count": inspected["RestartCount"],
                "image_id": inspected["Image"],
            }
            if state != {
                "exit_code": 0,
                "oom_killed": False,
                "restart_count": 0,
                "image_id": IMAGE_ID,
            }:
                raise RuntimeError(f"container exit integrity failed: {state}")
            result = json.loads(logs)
        finally:
            _run("docker", "rm", CONTAINER, check=False)

    if _run("docker", "inspect", CONTAINER, check=False).returncode == 0:
        raise RuntimeError("disposable container cleanup failed")
    normal_containers = {}
    for name in ("vss-behavior-analytics", "vss-behavior-analytics-thor-candidates"):
        inspected = json.loads(_run("docker", "inspect", name).stdout)[0]
        normal_containers[name] = {
            "running": inspected["State"]["Running"],
            "oom_killed": inspected["State"]["OOMKilled"],
            "restart_count": inspected["RestartCount"],
        }
    if not all(
        value == {"running": True, "oom_killed": False, "restart_count": 0}
        for value in normal_containers.values()
    ):
        raise RuntimeError(f"normal Behavior Analytics containers drifted: {normal_containers}")
    return {
        "runtime": {"image": IMAGE, "container": state, "log_sha256": _sha_bytes(logs.encode())},
        "probe": result,
        "cleanup": {
            "disposable_container_absent": True,
            "normal_behavior_containers": normal_containers,
        },
    }


def main() -> int:
    try:
        print(json.dumps(run_probe(), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
