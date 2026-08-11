#!/usr/bin/env python3
"""Bounded current-Thor proof for one isolated RT-VLM RTSP stream."""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"


class QualificationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _load_fixture_helper(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_rtsp_fixture", path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load deterministic fixture helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> Any:
    if contract["official_indices"] != [341]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    ffmpeg = Path(contract["rtsp_support"]["ffmpeg_path"])
    if not ffmpeg.is_file() or ffmpeg.is_symlink() or _sha(ffmpeg.read_bytes()) != contract[
        "rtsp_support"
    ]["ffmpeg_sha256"]:
        raise QualificationError("host ffmpeg lock drifted")
    return _load_fixture_helper(REPO / contract["source_locks"][0]["path"])


def _http_raw(
    endpoint: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float,
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        endpoint + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("local RT-VLM request failed") from exc
    return status, raw


def _http_json(
    endpoint: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float,
) -> tuple[int, bytes, Any]:
    status, raw = _http_raw(
        endpoint, path, method=method, body=body, timeout=timeout
    )
    try:
        return status, raw, json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON HTTP {status}") from exc


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _catalog(value: Any) -> tuple[int, str, set[str]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise QualificationError("live stream catalog envelope invalid")
    identities = [row.get("id") for row in value]
    if not all(isinstance(item, str) for item in identities) or len(set(identities)) != len(
        identities
    ):
        raise QualificationError("live stream identities invalid")
    ordered = sorted(identities)
    return len(ordered), _sha(_canonical(ordered)), set(ordered)


def _model(value: Any, expected: str) -> str:
    rows = value.get("data") if isinstance(value, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or rows[0].get("id") != expected
        or value.get("audio_support") is not False
    ):
        raise QualificationError("model inventory mismatch")
    return _sha(_canonical(value))


def _docker(
    args: list[str], counter: list[int], *, check: bool = True, timeout: float = 30
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    try:
        return subprocess.run(
            ["docker", *args],
            check=check,
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise QualificationError("bounded Docker command failed") from exc


def _runtime_identity(contract: dict[str, Any], commands: list[int]) -> dict[str, Any]:
    container = contract["execution"]["container"]
    raw = _docker(["inspect", container], commands).stdout
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError("RT-VLM inspect JSON invalid") from exc
    if not isinstance(values, list) or len(values) != 1:
        raise QualificationError("RT-VLM inspect envelope invalid")
    row = values[0]
    state = row.get("State", {})
    if (
        state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or state.get("OOMKilled") is not False
        or row.get("RestartCount") != 0
        or row.get("Image") != contract["model"]["image_id"]
    ):
        raise QualificationError("RT-VLM runtime identity drifted")
    paths = [
        lock["container_path"]
        for lock in contract["source_locks"]
        if lock.get("container_path")
    ]
    hashes_raw = _docker(
        ["exec", container, "sha256sum", *paths], commands
    ).stdout.decode()
    live = {line.split()[1]: line.split()[0] for line in hashes_raw.splitlines() if line}
    for lock in contract["source_locks"]:
        destination = lock.get("container_path")
        if destination and live.get(destination) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {destination}")
    return {
        "container_name_exact": True,
        "image_id_exact": True,
        "healthy": True,
        "restart_count": 0,
        "oom_killed": False,
        "live_source_count": len(paths),
        "live_sources_match_locks": True,
    }


def _wait_port(host: str, port: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise QualificationError("owned MediaMTX RTSP port did not become ready")


def _probe_rtsp(url: str, contract: dict[str, Any]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-read_intervals",
                "%+1",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate",
                "-of",
                "json",
                url,
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        value = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        raise QualificationError("owned RTSP stream probe failed") from exc
    streams = value.get("streams") if isinstance(value, dict) else None
    if not isinstance(streams, list) or len(streams) != 1:
        raise QualificationError("owned RTSP stream inventory drifted")
    stream = streams[0]
    fixture = contract["fixture"]
    try:
        reported_rate = Fraction(stream.get("r_frame_rate", "0/1"))
    except (ValueError, ZeroDivisionError):
        reported_rate = Fraction(0, 1)
    if (
        stream.get("codec_name") != "h264"
        or stream.get("width") != fixture["width"]
        or stream.get("height") != fixture["height"]
        or reported_rate <= 0
    ):
        raise QualificationError(
            "owned RTSP media contract drifted: "
            f"codec={stream.get('codec_name')},"
            f"dimensions={stream.get('width')}x{stream.get('height')},"
            f"rate={stream.get('r_frame_rate')}"
        )
    return {
        "codec_h264": True,
        "width": stream["width"],
        "height": stream["height"],
        "fps": fixture["fps"],
        "reported_frame_rate_positive": True,
        "tcp_probe_passed": True,
    }


def _read_live_caption(
    endpoint: str, payload: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], int]:
    body = _canonical(payload)
    request = urllib.request.Request(
        endpoint + "/v1/generate_captions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("live caption SSE request failed") from exc
    data_events = 0
    json_events = 0
    ping_comments = 0
    semantic_hash: str | None = None
    model_exact = False
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    try:
        if response.status != 200 or content_type != "text/event-stream":
            raise QualificationError("live caption SSE response contract drifted")
        for raw_line in response:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith(":"):
                ping_comments += 1
                continue
            if not line.startswith("data:"):
                continue
            data_events += 1
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                value = json.loads(data)
            except json.JSONDecodeError:
                continue
            json_events += 1
            model_exact = value.get("model") == payload["model"]
            for text in _strings(value):
                lowered = text.casefold()
                positions = [lowered.find(marker) for marker in ("blue", "green", "red")]
                if all(position >= 0 for position in positions) and positions == sorted(
                    positions
                ):
                    semantic_hash = _sha(text)
                    break
            if semantic_hash is not None:
                break
    finally:
        response.close()
    if semantic_hash is None or not model_exact or ping_comments < 1:
        raise QualificationError("live RTSP semantic/SSE oracle failed")
    return {
        "http_status": 200,
        "content_type_exact": True,
        "data_event_count": data_events,
        "json_event_count": json_events,
        "ping_comment_count": ping_comments,
        "model_exact": True,
        "primary_markers_present": True,
        "markers_in_chronological_order": True,
        "semantic_output_sha256": semantic_hash,
        "request_sha256": _sha(body),
    }, 1


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "requires_acknowledgement": contract["execution"]["acknowledgement"],
        "support_container_lifecycle_actions": 2,
        "rt_vlm_stream_mutations": 3,
        "agent_generate_calls": 0,
        "main_vios_stream_mutations": 0,
        "rt_cv_stream_mutations": 0,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    helper = _verify_static(contract)
    execution = contract["execution"]
    support = contract["rtsp_support"]
    if endpoint != execution["endpoint"]:
        raise QualificationError("endpoint must be exactly http://127.0.0.1:8018")

    docker_commands = [0]
    runtime = _runtime_identity(contract, docker_commands)
    existing = _docker(
        ["ps", "-aq", "--filter", f"name=^/{support['container']}$"],
        docker_commands,
    ).stdout.strip()
    if existing:
        raise QualificationError("owned support container name already exists")
    image = _docker(["image", "inspect", support["image"]], docker_commands).stdout
    image_rows = json.loads(image)
    if (
        len(image_rows) != 1
        or image_rows[0].get("Id") != support["image_id"]
        or image_rows[0].get("Architecture") != support["architecture"]
    ):
        raise QualificationError("MediaMTX support image drifted")

    request_count = 0
    model_requests = 0

    def js(path: str, **kwargs: Any) -> tuple[int, bytes, Any]:
        nonlocal request_count
        request_count += 1
        return _http_json(endpoint, path, **kwargs)

    def raw(path: str, **kwargs: Any) -> tuple[int, bytes]:
        nonlocal request_count
        request_count += 1
        return _http_raw(endpoint, path, **kwargs)

    stream_status, _, streams = js("/v1/streams/get-stream-info", timeout=15)
    model_status, _, models = js("/v1/models", timeout=15)
    stats_status, _, stats = js("/v1/assets/stats", timeout=15)
    health_status, _, health = js("/v1/health/ready", timeout=15)
    if any(
        status != 200
        for status in (stream_status, model_status, stats_status, health_status)
    ):
        raise QualificationError("RT-VLM preflight failed")
    catalog_before = _catalog(streams)
    stream_id = support["stream_id"]
    if stream_id in catalog_before[2]:
        raise QualificationError("owned RTSP stream identity already exists")
    model = contract["model"]["id"]
    model_before_sha = _model(models, model)
    stats_before_sha = _sha(_canonical(stats))
    health_before_sha = _sha(_canonical(health))

    invalid_body = _canonical(
        {
            "streams": [
                {
                    "liveStreamUrl": "http://invalid.example/stream",
                    "description": "VSS RTSP qualifier invalid vector",
                }
            ]
        }
    )
    invalid_status, invalid_raw, invalid_value = js(
        "/v1/streams/add", method="POST", body=invalid_body, timeout=15
    )
    if invalid_status != 422 or not isinstance(invalid_value, dict):
        raise QualificationError("non-RTSP scheme was not rejected by schema")

    publisher: subprocess.Popen[bytes] | None = None
    support_started = False
    stream_add_attempted = False
    stream_added = False
    caption_started = False
    stop_status: int | None = None
    delete_status: int | None = None
    cleanup_failures: list[str] = []
    support_result: dict[str, Any] = {}
    add_result: dict[str, Any] = {}
    live_result: dict[str, Any] = {}
    fixture_bytes = b""
    temp_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="rt-vlm-rtsp-") as temp_dir:
        temp_path = Path(temp_dir)
        fixture_path = temp_path / "timeline.mp4"
        fixture_bytes = helper._generate_fixture(fixture_path, time.monotonic() + 60)
        if (
            len(fixture_bytes) != contract["fixture"]["bytes"]
            or _sha(fixture_bytes) != contract["fixture"]["sha256"]
        ):
            raise QualificationError("deterministic RTSP fixture drifted")
        try:
            run = _docker(
                [
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    support["container"],
                    "--network",
                    support["network"],
                    "--label",
                    "vss.thor.qualifier=rtsp-runtime",
                    support["image"],
                ],
                docker_commands,
            )
            support_started = True
            if len(run.stdout.decode().strip()) != 64:
                raise QualificationError("MediaMTX container identity invalid")
            support_inspect = json.loads(
                _docker(["inspect", support["container"]], docker_commands).stdout
            )[0]
            network = support_inspect.get("NetworkSettings", {}).get("Networks", {}).get(
                support["network"], {}
            )
            support_ip = network.get("IPAddress")
            if (
                support_inspect.get("State", {}).get("Status") != "running"
                or support_inspect.get("Image") != support["image_id"]
                or support_inspect.get("Config", {}).get("Labels", {}).get(
                    "vss.thor.qualifier"
                )
                != "rtsp-runtime"
                or not isinstance(support_ip, str)
                or not support_ip
            ):
                raise QualificationError("MediaMTX support runtime drifted")
            _wait_port(support_ip, support["port"], time.monotonic() + 10)
            publish_url = f"rtsp://{support_ip}:{support['port']}/{support['path']}"
            publisher = subprocess.Popen(
                [
                    support["ffmpeg_path"],
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-re",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(fixture_path),
                    "-an",
                    "-c:v",
                    "copy",
                    "-f",
                    "rtsp",
                    "-rtsp_transport",
                    "tcp",
                    publish_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            if publisher.poll() is not None:
                raise QualificationError("owned RTSP publisher exited early")
            probe = _probe_rtsp(publish_url, contract)
            published_ports = support_inspect.get("NetworkSettings", {}).get(
                "Ports", {}
            )
            no_host_ports_published = isinstance(published_ports, dict) and all(
                not bindings for bindings in published_ports.values()
            )
            support_result = {
                "image_id_exact": True,
                "architecture_exact": True,
                "network_exact": True,
                "no_host_ports_published": no_host_ports_published,
                "publisher_running": True,
                "ffmpeg_binary_exact": True,
                **probe,
            }

            stream_url = (
                f"rtsp://{support['container']}:{support['port']}/{support['path']}"
            )
            add_body = _canonical(
                {
                    "streams": [
                        {
                            "liveStreamUrl": stream_url,
                            "description": "VSS RTSP qualifier runtime",
                            "id": stream_id,
                            "sensor_name": "vss-rtsp-qualifier-runtime",
                        }
                    ]
                }
            )
            stream_add_attempted = True
            add_status, add_raw, add_value = js(
                "/v1/streams/add", method="POST", body=add_body, timeout=30
            )
            results = add_value.get("results") if isinstance(add_value, dict) else None
            if (
                add_status != 200
                or not isinstance(results, list)
                or len(results) != 1
                or results[0].get("id") != stream_id
                or add_value.get("errors") != []
            ):
                raise QualificationError("owned RTSP stream registration failed")
            stream_added = True
            listed_status, _, listed = js("/v1/streams/get-stream-info", timeout=15)
            after_add = _catalog(listed)
            owned_rows = [row for row in listed if row.get("id") == stream_id]
            if (
                listed_status != 200
                or after_add[0] != catalog_before[0] + 1
                or len(owned_rows) != 1
                or owned_rows[0].get("liveStreamUrl") != stream_url
                or owned_rows[0].get("description") != "VSS RTSP qualifier runtime"
            ):
                raise QualificationError("owned RTSP catalog entry drifted")
            add_result = {
                "http_status": 200,
                "single_result": True,
                "errors_empty": True,
                "owned_identity_exact": True,
                "catalog_count_delta": 1,
                "metadata_round_trip_exact": True,
                "request_sha256": _sha(add_body),
                "response_sha256": _sha(add_raw),
            }

            caption_payload = {
                "id": stream_id,
                "prompt": "List the three primary square colors in chronological order.",
                "model": model,
                "stream": True,
                "stream_options": {"include_usage": True},
                "chunk_duration": 9,
                "chunk_overlap_duration": 0,
                "max_tokens": 48,
                "temperature": 0.0,
                "seed": 7,
                "num_frames_per_second_or_fixed_frames_chunk": 9,
                "use_fps_for_chunking": False,
            }
            caption_started = True
            live_result, sse_requests = _read_live_caption(
                endpoint, caption_payload, timeout=75
            )
            request_count += sse_requests
            model_requests += 1
        finally:
            if stream_add_attempted or caption_started:
                try:
                    stop_status, _ = raw(
                        f"/v1/generate_captions/{stream_id}",
                        method="DELETE",
                        timeout=30,
                    )
                    if stop_status != 200:
                        cleanup_failures.append("live_caption_stop_failed")
                except QualificationError:
                    cleanup_failures.append("live_caption_stop_transport_failed")
            if stream_add_attempted:
                try:
                    delete_deadline = time.monotonic() + 10
                    while True:
                        delete_status, _ = raw(
                            f"/v1/streams/delete/{stream_id}",
                            method="DELETE",
                            timeout=30,
                        )
                        if (
                            delete_status != 409
                            or time.monotonic() >= delete_deadline
                            or request_count
                            >= execution["max_rt_vlm_http_requests"] - 4
                        ):
                            break
                        time.sleep(0.5)
                    if delete_status != 200:
                        cleanup_failures.append("owned_stream_delete_failed")
                except QualificationError:
                    cleanup_failures.append("owned_stream_delete_transport_failed")
            if publisher is not None:
                try:
                    publisher.send_signal(signal.SIGINT)
                    publisher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    publisher.terminate()
                    try:
                        publisher.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        publisher.kill()
                        publisher.wait(timeout=3)
                if publisher.poll() is None:
                    cleanup_failures.append("publisher_still_running")
            if support_started:
                stopped = _docker(
                    ["stop", "--timeout", "5", support["container"]],
                    docker_commands,
                    check=False,
                    timeout=15,
                )
                if stopped.returncode != 0:
                    cleanup_failures.append("support_container_stop_failed")

    time.sleep(0.5)
    final_stream_status, _, final_streams = js(
        "/v1/streams/get-stream-info", timeout=15
    )
    final_stats_status, _, final_stats = js("/v1/assets/stats", timeout=15)
    final_model_status, _, final_models = js("/v1/models", timeout=15)
    final_health_status, _, final_health = js("/v1/health/ready", timeout=15)
    support_remaining = _docker(
        ["ps", "-aq", "--filter", f"name=^/{support['container']}$"],
        docker_commands,
    ).stdout.strip()
    if final_stream_status != 200 or _catalog(final_streams) != catalog_before:
        cleanup_failures.append("stream_catalog_not_restored")
    if final_stats_status != 200 or _sha(_canonical(final_stats)) != stats_before_sha:
        cleanup_failures.append("asset_statistics_not_restored")
    if final_model_status != 200 or _model(final_models, model) != model_before_sha:
        cleanup_failures.append("model_inventory_not_restored")
    if final_health_status != 200 or _sha(_canonical(final_health)) != health_before_sha:
        cleanup_failures.append("health_contract_not_restored")
    if support_remaining:
        cleanup_failures.append("support_container_remains")
    if temp_path is None or temp_path.exists():
        cleanup_failures.append("temporary_fixture_root_remains")
    if cleanup_failures:
        raise QualificationError("cleanup failed: " + ",".join(cleanup_failures))
    if stop_status != 200 or delete_status != 200:
        raise QualificationError("owned live stream stop/delete did not pass")
    if request_count > execution["max_rt_vlm_http_requests"]:
        raise QualificationError("RT-VLM request budget exceeded")
    if model_requests != execution["max_model_requests"]:
        raise QualificationError("exact RT-VLM model request budget drifted")
    if docker_commands[0] > execution["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
    duration = time.monotonic() - started
    if not 0 < duration <= execution["max_duration_seconds"]:
        raise QualificationError("runtime duration bound exceeded")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(duration, 6),
        "budget": {
            "rt_vlm_http_requests": request_count,
            "max_rt_vlm_http_requests": execution["max_rt_vlm_http_requests"],
            "model_requests": model_requests,
            "max_model_requests": execution["max_model_requests"],
            "docker_commands": docker_commands[0],
            "max_docker_commands": execution["max_docker_commands"],
            "support_processes_peak": 2,
            "max_support_processes": execution["max_support_processes"],
            "support_container_lifecycle_actions": 2,
            "rt_vlm_stream_mutations": 3,
        },
        "runtime_identity": {
            **runtime,
            "endpoint_loopback_exact": True,
            "model_exact": True,
            "release_exact": contract["model"]["release"],
            "audio_support": False,
        },
        "fixture": {
            "byte_count": len(fixture_bytes),
            "content_sha256": _sha(fixture_bytes),
            "duration_seconds": contract["fixture"]["duration_seconds"],
            "primary_markers": contract["fixture"]["primary_markers"],
        },
        "rtsp_support": support_result,
        "non_rtsp_scheme_negative": {
            "http_status": invalid_status,
            "structured": True,
            "request_sha256": _sha(invalid_body),
            "response_sha256": _sha(invalid_raw),
            "stream_mutated": False,
        },
        "stream_add": add_result,
        "live_caption_sse": live_result,
        "cleanup": {
            "failures": [],
            "stop_caption_http_status": stop_status,
            "delete_stream_http_status": delete_status,
            "stream_catalog_before_count": catalog_before[0],
            "stream_catalog_after_count": _catalog(final_streams)[0],
            "stream_catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "model_inventory_restored_exactly": True,
            "health_contract_restored_exactly": True,
            "publisher_stopped": True,
            "support_container_absent": True,
            "temporary_fixture_root_absent": True,
            "owned_stream_absent": True,
        },
        "policy": {
            "agent_generate_calls": 0,
            "main_vios_stream_mutations": 0,
            "rt_cv_stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False,
            "raw_rtsp_url_retained": False,
            "credentials_retained": False,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_json(RECEIPT_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"), nargs="?", default="plan")
    parser.add_argument("--ack")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        if args.mode == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract, args.endpoint)
    except (QualificationError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
