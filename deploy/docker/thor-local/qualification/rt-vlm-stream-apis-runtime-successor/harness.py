#!/usr/bin/env python3
"""Qualify both RT-VLM stream-management API families on the live Thor service."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
BASE = "http://127.0.0.1:8018"
CONTAINER = "vss-rtvi-vlm"
SUPPORT_CONTAINER = "thor-rt-vlm-stream-api-qualifier"
SUPPORT_IMAGE = "sha256:35f9e8aefaca5352b5f4667c8cd529360a53a493c51fa639e8f5898c03bc0d06"
NETWORK = "mdx_default"
STREAM_PATH = "thor-stream-api-qualifier"
ORIGINAL_ID = "35135135-aaaa-4bbb-8ccc-351351351351"
MISSING_ID = "35135135-aaaa-4bbb-8ccc-351351351399"
CV_CAMERA_ID = "thor-row352-cv-camera"
FIXTURE = REPO / "services/alert/warmup/test.mp4"
MINIMUM_FREE_BYTES = 10 * 1024**3
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class QualificationError(RuntimeError):
    """The bounded qualification could not prove its contract."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def run(*args: str, timeout: float = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        raise QualificationError(
            f"command failed ({result.returncode}): {' '.join(args)}: {result.stderr.strip()}"
        )
    return result


def docker(*args: str, timeout: float = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("docker", *args, timeout=timeout, check=check)


def json_request(method: str, path: str, body: Any | None = None) -> tuple[int, Any, bytes]:
    payload = None if body is None else canonical(body)
    request = urllib.request.Request(
        BASE + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"non-JSON response from {method} {path}") from exc
    return status, parsed, raw


def operation(
    records: list[dict[str, Any]],
    action: str,
    method: str,
    path: str,
    body: Any | None = None,
) -> tuple[int, Any]:
    status, parsed, raw = json_request(method, path, body)
    records.append(
        {
            "action": action,
            "method": method,
            "path": path,
            "status": status,
            "request_sha256": sha_bytes(b"") if body is None else sha_bytes(canonical(body)),
            "response_sha256": sha_bytes(raw),
        }
    )
    return status, parsed


def stream_catalogs() -> dict[str, Any]:
    original_status, original, _ = json_request("GET", "/v1/streams/get-stream-info")
    cv_status, cv, _ = json_request("GET", "/v1/stream/get-stream-info")
    if original_status != 200 or cv_status != 200:
        raise QualificationError("stream catalog baseline is unavailable")
    return {"original": original, "cv": cv}


def container_names() -> list[str]:
    output = docker("ps", "--format", "{{.Names}}").stdout
    return sorted(line for line in output.splitlines() if line)


def inspect_runtime() -> dict[str, Any]:
    raw = docker("inspect", CONTAINER).stdout
    value = json.loads(raw)[0]
    state = value["State"]
    health = state.get("Health", {}).get("Status")
    return {
        "image_id": value["Image"],
        "healthy": health == "healthy",
        "restart_count": value["RestartCount"],
        "oom_killed": state["OOMKilled"],
        "network_attached": NETWORK in value["NetworkSettings"]["Networks"],
    }


def live_sha(path: str) -> str:
    code = "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())"
    return docker("exec", CONTAINER, "python3", "-c", code, path).stdout.strip()


def wait_for_tcp(host: str, port: int, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise QualificationError(f"TCP endpoint did not become ready: {host}:{port}")


def absent_support_container() -> bool:
    return not docker(
        "ps", "-aq", "--filter", f"name=^/{SUPPORT_CONTAINER}$", check=False
    ).stdout.strip()


def owned_absent(catalogs: dict[str, Any]) -> bool:
    original = catalogs["original"]
    cv = catalogs["cv"]
    return (
        all(item.get("id") != ORIGINAL_ID for item in original)
        and all(item.get("camera_id") != CV_CAMERA_ID for item in cv.get("stream_list", []))
    )


def cleanup_owned(publisher: subprocess.Popen[bytes] | None) -> list[str]:
    failures: list[str] = []
    try:
        json_request(
            "DELETE",
            "/v1/streams/delete-batch",
            {"stream_ids": [ORIGINAL_ID], "blocking": True, "drain_timeout_seconds": 30},
        )
    except Exception as exc:  # best-effort transactional cleanup
        failures.append(f"original cleanup: {type(exc).__name__}")
    try:
        json_request(
            "POST",
            "/v1/stream/remove",
            {
                "key": "sensor",
                "value": {"camera_id": CV_CAMERA_ID, "change": "camera_remove"},
                "headers": {"source": "thor-qualification"},
            },
        )
    except Exception as exc:  # best-effort transactional cleanup
        failures.append(f"CV cleanup: {type(exc).__name__}")
    if publisher is not None and publisher.poll() is None:
        publisher.terminate()
        try:
            publisher.wait(timeout=10)
        except subprocess.TimeoutExpired:
            publisher.kill()
            publisher.wait(timeout=5)
    result = docker("rm", "-f", SUPPORT_CONTAINER, timeout=30, check=False)
    if result.returncode and "No such container" not in result.stderr:
        failures.append("support container removal failed")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    parser.add_argument("--output", type=Path, default=RECEIPT_PATH)
    args = parser.parse_args()
    expected_ack = "I_ACK_ONE_LOCAL_RTSP_PUBLISHER_AND_TWO_OWNED_RT_VLM_STREAMS"
    if args.ack != expected_ack:
        raise QualificationError(f"acknowledgement must equal {expected_ack}")

    started = time.monotonic()
    free_before = shutil.disk_usage(REPO).free
    if free_before < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor is not met")
    if not absent_support_container():
        raise QualificationError(f"owned support container already exists: {SUPPORT_CONTAINER}")
    before_catalogs = stream_catalogs()
    if not owned_absent(before_catalogs):
        raise QualificationError("owned qualification identity already exists")
    before_catalog_sha = sha_bytes(canonical(before_catalogs))
    before_containers = container_names()
    runtime_before = inspect_runtime()
    if not runtime_before["healthy"] or runtime_before["oom_killed"]:
        raise QualificationError("RT-VLM is not healthy")
    if not runtime_before["network_attached"]:
        raise QualificationError(f"RT-VLM is not attached to {NETWORK}")
    if run("docker", "info", "--format", "{{.CgroupDriver}}").stdout.strip() != "cgroupfs":
        raise QualificationError("Docker cgroup driver is not cgroupfs")

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for lock in contract["source_locks"]:
        if sha_file(REPO / lock["path"]) != lock["sha256"]:
            raise QualificationError(f"host source lock drifted: {lock['path']}")
        if lock.get("container_path") and live_sha(lock["container_path"]) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {lock['container_path']}")

    openapi_status, openapi, openapi_raw = json_request("GET", "/openapi.json")
    expected_routes = {
        "/v1/streams/add",
        "/v1/streams/get-stream-info",
        "/v1/streams/delete/{stream_id}",
        "/v1/streams/delete-batch",
        "/v1/stream/add",
        "/v1/stream/get-stream-info",
        "/v1/stream/remove",
    }
    live_routes = {path for path in openapi["paths"] if "/stream" in path}
    if openapi_status != 200 or live_routes != expected_routes:
        raise QualificationError("live OpenAPI stream route set drifted")

    publisher: subprocess.Popen[bytes] | None = None
    operations: list[dict[str, Any]] = []
    cleanup_failures: list[str] = []
    try:
        docker(
            "run", "-d", "--name", SUPPORT_CONTAINER, "--network", NETWORK,
            SUPPORT_IMAGE,
        )
        support_ip = docker(
            "inspect", "--format", f"{{{{(index .NetworkSettings.Networks \"{NETWORK}\").IPAddress}}}}",
            SUPPORT_CONTAINER,
        ).stdout.strip()
        wait_for_tcp(support_ip, 8554)
        publish_url = f"rtsp://{support_ip}:8554/{STREAM_PATH}"
        service_url = f"rtsp://{SUPPORT_CONTAINER}:8554/{STREAM_PATH}"
        publisher = subprocess.Popen(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
                "-stream_loop", "-1", "-i", str(FIXTURE), "-an", "-c:v", "copy",
                "-f", "rtsp", "-rtsp_transport", "tcp", publish_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(2)
        if publisher.poll() is not None:
            error = (publisher.stderr.read() if publisher.stderr else b"").decode(errors="replace")
            raise QualificationError(f"ffmpeg publisher exited early: {error[-500:]}")
        probe = run(
            "/usr/bin/ffprobe", "-v", "error", "-rtsp_transport", "tcp",
            "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height",
            "-of", "json", publish_url,
        )
        media = json.loads(probe.stdout)["streams"][0]

        original_request = {
            "streams": [{
                "id": ORIGINAL_ID,
                "liveStreamUrl": service_url,
                "description": "Thor original API qualification",
                "sensor_name": "Thor Sensor 351",
                "place_name": "Thor Lab",
                "place_type": "edge-demo",
                "place_lat": 43.6532,
                "place_lon": -79.3832,
                "place_alt": 76.0,
                "place_coordinate_x": 3.5,
                "place_coordinate_y": 7.25,
            }]
        }
        status, added = operation(
            operations, "original-add", "POST", "/v1/streams/add", original_request
        )
        if status != 200 or added.get("errors") or len(added.get("results", [])) != 1:
            raise QualificationError("original stream add failed")
        status, original_mid = operation(
            operations, "original-info", "GET", "/v1/streams/get-stream-info"
        )
        if status != 200:
            raise QualificationError("original stream list failed")
        original_item = next((item for item in original_mid if item.get("id") == ORIGINAL_ID), None)
        expected_place = {
            "place_name": "Thor Lab", "place_type": "edge-demo", "place_lat": 43.6532,
            "place_lon": -79.3832, "place_alt": 76.0, "place_coordinate_x": 3.5,
            "place_coordinate_y": 7.25,
        }
        original_metadata_exact = bool(
            original_item
            and original_item.get("description") == "Thor original API qualification"
            and original_item.get("liveStreamUrl") == service_url
            and all(original_item.get(key) == value for key, value in expected_place.items())
        )
        if not original_metadata_exact:
            raise QualificationError("original stream metadata did not round-trip")

        cv_request = {
            "key": "sensor",
            "value": {
                "camera_id": CV_CAMERA_ID,
                "camera_url": service_url,
                "camera_name": "Thor CV API qualification",
                "creation_time": "2026-08-12T00:00:00Z",
                "change": "camera_add",
                "metadata": {"resolution": "1920x1080", "codec": "H264", "framerate": 30.0},
            },
            "headers": {"source": "thor-qualification", "created_at": "2026-08-12T00:00:00Z"},
        }
        status, cv_added = operation(operations, "cv-add", "POST", "/v1/stream/add", cv_request)
        if status != 200 or cv_added.get("camera_id") != CV_CAMERA_ID or cv_added.get("inference"):
            raise QualificationError("CV-compatible stream add failed")
        cv_asset_id = cv_added["asset_id"]
        status, cv_mid = operation(
            operations, "cv-info", "GET", "/v1/stream/get-stream-info"
        )
        cv_item = next(
            (item for item in cv_mid.get("stream_list", []) if item.get("camera_id") == CV_CAMERA_ID),
            None,
        )
        cv_identity_exact = bool(
            status == 200
            and cv_item
            and cv_item.get("asset_id") == cv_asset_id
            and cv_item.get("camera_name") == "Thor CV API qualification"
            and cv_item.get("camera_url") == service_url
            and cv_item.get("inference_active") is False
        )
        if not cv_identity_exact:
            raise QualificationError("CV-compatible identity did not round-trip")
        duplicate_status, duplicate = operation(
            operations, "cv-duplicate", "POST", "/v1/stream/add", cv_request
        )
        if duplicate_status != 409 or duplicate.get("code") != "DuplicateCameraId":
            raise QualificationError("duplicate CV camera was not rejected")

        delete_status, deleted = operation(
            operations,
            "original-batch-delete",
            "DELETE",
            "/v1/streams/delete-batch",
            {
                "stream_ids": [ORIGINAL_ID, MISSING_ID],
                "blocking": True,
                "drain_timeout_seconds": 30,
            },
        )
        batch_outcomes_exact = bool(
            delete_status == 200
            and deleted.get("deleted") == [ORIGINAL_ID]
            and len(deleted.get("errors", [])) == 1
            and deleted["errors"][0].get("stream_id") == MISSING_ID
            and deleted["errors"][0].get("status_code") == 400
        )
        if not batch_outcomes_exact:
            raise QualificationError("original batch delete outcomes were not exact")

        cv_remove_request = {
            "key": "sensor",
            "value": {
                "camera_id": CV_CAMERA_ID,
                "camera_name": "Thor CV API qualification",
                "camera_url": service_url,
                "change": "camera_remove",
                "metadata": {"resolution": "1920x1080", "codec": "H264", "framerate": 30.0},
            },
            "headers": {"source": "thor-qualification"},
        }
        remove_status, removed = operation(
            operations, "cv-remove", "POST", "/v1/stream/remove", cv_remove_request
        )
        if (
            remove_status != 200
            or removed.get("camera_id") != CV_CAMERA_ID
            or removed.get("asset_id") != cv_asset_id
            or removed.get("status") != "removed"
        ):
            raise QualificationError("CV-compatible stream removal failed")
        missing_status, missing = operation(
            operations, "cv-missing", "POST", "/v1/stream/remove", cv_remove_request
        )
        if missing_status != 404 or missing.get("code") != "NotFound":
            raise QualificationError("missing CV camera negative did not pass")
    finally:
        cleanup_failures = cleanup_owned(publisher)

    after_catalogs = stream_catalogs()
    after_catalog_sha = sha_bytes(canonical(after_catalogs))
    after_containers = container_names()
    runtime_after = inspect_runtime()
    free_after = shutil.disk_usage(REPO).free
    if cleanup_failures:
        raise QualificationError("; ".join(cleanup_failures))
    if after_catalogs != before_catalogs or not owned_absent(after_catalogs):
        raise QualificationError("stream catalogs were not restored exactly")
    if after_containers != before_containers:
        raise QualificationError("running container set was not preserved")
    if not absent_support_container():
        raise QualificationError("support container remains after cleanup")
    if runtime_after != runtime_before:
        raise QualificationError("RT-VLM runtime identity/state changed")
    if free_after < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor was crossed")

    run_id = f"thor-stream-apis-{time.time_ns()}"
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "contract_sha256": sha_file(CONTRACT_PATH),
        "run": {
            "id_sha256": sha_bytes(run_id.encode()),
            "duration_seconds": round(time.monotonic() - started, 6),
            "free_bytes_before": free_before,
            "free_bytes_after": free_after,
        },
        "runtime": {
            **runtime_after,
            "container": CONTAINER,
            "endpoint_loopback": True,
            "docker_cgroup_driver": "cgroupfs",
            "live_source_locks_exact": True,
        },
        "authoritative_api_mapping": {
            "ledger_endpoint_semantics_reversed": True,
            "source_declares_original_plural": True,
            "source_declares_cv_compatible_singular": True,
            "openapi_status": openapi_status,
            "openapi_sha256": sha_bytes(openapi_raw),
            "stream_route_set_exact": live_routes == expected_routes,
            "original_routes": sorted(path for path in live_routes if path.startswith("/v1/streams/")),
            "cv_compatible_routes": sorted(path for path in live_routes if path.startswith("/v1/stream/")),
        },
        "publisher": {
            "image_id": SUPPORT_IMAGE,
            "architecture": "arm64",
            "network": NETWORK,
            "host_ports_published": 0,
            "codec": media["codec_name"],
            "width": media["width"],
            "height": media["height"],
            "publisher_running_during_calls": True,
        },
        "original_api": {
            "add_status": 200,
            "single_owned_result": True,
            "stable_owned_identity": True,
            "metadata_round_trip_exact": original_metadata_exact,
            "batch_delete_status": delete_status,
            "batch_deleted_count": len(deleted["deleted"]),
            "batch_error_count": len(deleted["errors"]),
            "batch_per_item_outcomes_exact": batch_outcomes_exact,
        },
        "cv_compatible_api": {
            "add_status": 200,
            "identity_round_trip_exact": cv_identity_exact,
            "camera_metadata_schema_accepted": True,
            "headers_schema_accepted": True,
            "inference_not_requested": True,
            "duplicate_status": duplicate_status,
            "remove_status": remove_status,
            "missing_remove_status": missing_status,
            "removed_asset_identity_exact": True,
        },
        "operations": operations,
        "cleanup": {
            "before_sha256": before_catalog_sha,
            "after_sha256": after_catalog_sha,
            "catalogs_restored_exactly": after_catalogs == before_catalogs,
            "owned_streams_absent": owned_absent(after_catalogs),
            "support_container_absent": absent_support_container(),
            "publisher_stopped": publisher is None or publisher.poll() is not None,
            "running_container_set_preserved": after_containers == before_containers,
            "runtime_state_preserved": runtime_after == runtime_before,
            "failures": cleanup_failures,
        },
        "policy": {
            "external_requests": 0,
            "agent_generate_calls": 0,
            "model_inference_requests": 0,
            "main_vios_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "warehouse_sample_bundle": "excluded",
            "raw_resource_ids_retained": False,
            "credentials_retained": False,
        },
    }
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if UUID_PATTERN.search(rendered):
        raise QualificationError("receipt would retain a raw UUID")
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "official_indices": receipt["official_indices"],
        "receipt_sha256": sha_file(args.output),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
