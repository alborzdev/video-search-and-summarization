#!/usr/bin/env python3
"""Run the isolated RT-VLM URL-security oracle and inspect the live API boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ASSET_MANAGER = REPO / "services/rtvi/rt-vlm/src/utils/asset_manager.py"
IMAGE = "nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1"
IMAGE_ID = "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504"
MAIN_CONTAINER = "vss-rtvi-vlm"
PROBE_CONTAINER = "vss-rt-vlm-url-security-oracle"
BASE_URL = "http://127.0.0.1:8018"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}"
        )
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def http_json(path: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def post_json(path: str, value: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(value).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def container_state(name: str) -> dict[str, Any]:
    value = json.loads(run("docker", "inspect", name).stdout)[0]
    return {
        "running": value["State"]["Running"],
        "oom_killed": value["State"]["OOMKilled"],
        "restart_count": value["RestartCount"],
        "image_id": value["Image"],
    }


def main() -> int:
    run("docker", "rm", "-f", PROBE_CONTAINER, check=False)
    main_before = container_state(MAIN_CONTAINER)
    if main_before != {
        "running": True,
        "oom_killed": False,
        "restart_count": 0,
        "image_id": IMAGE_ID,
    }:
        raise RuntimeError(f"main RT-VLM state is not exact: {main_before}")
    ready_status, ready = http_json("/v1/health/ready")
    assets_status, assets_before = http_json("/v1/assets/stats")
    if ready_status != 200 or ready.get("message") != "Service is ready.":
        raise RuntimeError(f"main RT-VLM is not ready: {ready_status} {ready}")
    if assets_status != 200:
        raise RuntimeError(f"cannot inspect pre-test asset state: {assets_status}")
    with urllib.request.urlopen(BASE_URL + "/openapi.json", timeout=10) as response:
        openapi = json.loads(response.read())
    query = openapi["components"]["schemas"]["VlmQuery"]
    required = query["required"]
    url_description = query["properties"]["url"]["description"]
    headers_description = query["properties"]["url_headers"]["description"]
    api_schema = {
        "generate_captions_present": "/v1/generate_captions" in openapi["paths"],
        "request_schema": "VlmQuery",
        "url_present": "url" in query["properties"],
        "url_headers_present": "url_headers" in query["properties"],
        "required_fields": required,
        "url_ssrf_documented": "SSRF" in url_description,
        "request_headers_override_documented": "Overrides" in headers_description,
    }
    api_status, api_error = post_json(
        "/v1/generate_captions",
        {
            "id": "00000000-0000-4000-8000-000000000060",
            "url": "http://127.0.0.1:9/blocked.mp4",
            "url_headers": {"Authorization": "Basic cXVhbGlmaWNhdGlvbjpvbmx5"},
            "prompt": "Qualification request rejected before inference.",
            "model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        },
    )
    if api_status != 422:
        raise RuntimeError(f"live API SSRF guard did not return 422: {api_status}")
    api_boundary = {
        "request_path": "/v1/generate_captions",
        "status_code": api_status,
        "error_shape": sorted(api_error),
        "loopback_rejected_before_download": True,
    }

    live_asset_sha = run(
        "docker",
        "exec",
        MAIN_CONTAINER,
        "sha256sum",
        "/opt/nvidia/rtvi/rtvi/utils/asset_manager.py",
    ).stdout.split()[0]
    if live_asset_sha != sha(ASSET_MANAGER):
        raise RuntimeError("live RT-VLM asset-manager source differs from current Thor source")

    probe_state: dict[str, Any] | None = None
    logs = ""
    with tempfile.TemporaryDirectory(prefix="vss-url-security-") as temp_name:
        tls_dir = Path(temp_name)
        tls_dir.chmod(0o755)
        cert = tls_dir / "cert.pem"
        key = tls_dir / "key.pem"
        run(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=auth.vss.test",
            "-addext",
            "subjectAltName=DNS:auth.vss.test,DNS:target.vss.test",
        )
        cert.chmod(0o644)
        key.chmod(0o644)
        created = run(
            "docker",
            "run",
            "-d",
            "--name",
            PROBE_CONTAINER,
            "--network",
            "host",
            "--user",
            "1001:1001",
            "--workdir",
            "/opt/nvidia/rtvi/rtvi",
            "--entrypoint",
            "python3",
            "--add-host",
            "auth.vss.test:127.0.0.1",
            "--add-host",
            "target.vss.test:127.0.0.1",
            "-v",
            f"{HERE}:/probe:ro",
            "-v",
            f"{tls_dir}:/tls:ro",
            "-v",
            f"{ASSET_MANAGER}:/opt/nvidia/rtvi/rtvi/utils/asset_manager.py:ro",
            IMAGE,
            "/probe/in_container_probe.py",
            "/tls/cert.pem",
            "/tls/key.pem",
        )
        if not created.stdout.strip():
            raise RuntimeError("probe container was not created")
        try:
            wait = run("docker", "wait", PROBE_CONTAINER)
            if wait.stdout.strip() != "0":
                failed_logs = run("docker", "logs", PROBE_CONTAINER, check=False)
                logs = failed_logs.stdout + failed_logs.stderr
                raise RuntimeError(f"probe failed: exit={wait.stdout.strip()} logs={logs[-4000:]}")
            logs_result = run("docker", "logs", PROBE_CONTAINER)
            logs = logs_result.stdout + logs_result.stderr
            inspected = json.loads(run("docker", "inspect", PROBE_CONTAINER).stdout)[0]
            probe_state = {
                "exit_code": inspected["State"]["ExitCode"],
                "oom_killed": inspected["State"]["OOMKilled"],
                "restart_count": inspected["RestartCount"],
                "image_id": inspected["Image"],
            }
        finally:
            run("docker", "rm", "-f", PROBE_CONTAINER, check=False)

    if probe_state != {
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
        "image_id": IMAGE_ID,
    }:
        raise RuntimeError(f"probe exit integrity drifted: {probe_state}")
    marker = next(
        (line.removeprefix("QUALIFICATION_JSON=") for line in logs.splitlines() if line.startswith("QUALIFICATION_JSON=")),
        None,
    )
    if marker is None:
        raise RuntimeError(f"probe emitted no result marker: {logs[-2000:]}")
    isolated = json.loads(marker)

    assets_after_status, assets_after = http_json("/v1/assets/stats")
    main_after = container_state(MAIN_CONTAINER)
    if assets_after_status != 200 or assets_after != assets_before:
        raise RuntimeError("main RT-VLM asset state changed")
    if main_after != main_before:
        raise RuntimeError("main RT-VLM container state changed")
    result = {
        "runtime": {
            "image": IMAGE,
            "image_id": IMAGE_ID,
            "asset_manager_sha256": live_asset_sha,
            "probe_container": probe_state,
            "probe_log_sha256": hashlib.sha256(logs.encode()).hexdigest(),
        },
        "live_api": {
            "ready": True,
            "schema": api_schema,
            "ssrf_boundary": api_boundary,
        },
        "isolated_runtime": isolated,
        "cleanup": {
            "probe_container_absent": run(
                "docker", "inspect", PROBE_CONTAINER, check=False
            ).returncode
            != 0,
            "main_container_exact": main_after == main_before,
            "main_asset_state_exact": assets_after == assets_before,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
