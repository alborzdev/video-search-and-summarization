#!/usr/bin/env python3
"""Bounded, isolated Thor runtime proof for core RT-CV 2D capabilities."""

from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


class QualificationError(RuntimeError):
    """A runtime, safety, cleanup, or evidence assertion failed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _run(
    args: list[str],
    *,
    check: bool = True,
    timeout: float = 30,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            check=check,
            capture_output=True,
            input=input_bytes,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise QualificationError(f"bounded command failed: {args[0]}") from exc


def _docker(
    args: list[str],
    counter: list[int],
    *,
    check: bool = True,
    timeout: float = 30,
) -> subprocess.CompletedProcess[bytes]:
    counter[0] += 1
    return _run(["docker", *args], check=check, timeout=timeout)


def _http(
    endpoint: str,
    path: str,
    counter: list[int],
    *,
    method: str = "GET",
    body: bytes | None = None,
    accept: str = "application/json",
    timeout: float = 15,
) -> tuple[int, bytes]:
    counter[0] += 1
    headers = {"Accept": accept}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        endpoint + path, data=body, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("isolated RT-CV HTTP request failed") from exc


def _json_response(status: int, raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"{label} returned non-JSON HTTP {status}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} returned a non-object envelope")
    return value


def _verify_static(contract: dict[str, Any]) -> None:
    if contract["official_indices"] != [375, 380, 381, 382]:
        raise QualificationError("official index binding drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if (
            not path.is_file()
            or path.is_symlink()
            or _sha(path.read_bytes()) != lock["sha256"]
        ):
            raise QualificationError(f"source lock drifted: {lock['path']}")
    for key in ("fixture", "detector_onnx", "detector_engine", "siglip_onnx", "siglip_engine"):
        item = contract["assets"][key]
        path = REPO / item["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"]:
            raise QualificationError(f"asset size/type drifted: {item['path']}")
        if _sha(path.read_bytes()) != item["sha256"]:
            raise QualificationError(f"asset digest drifted: {item['path']}")
    weights = contract["assets"]["siglip_weights"]
    weights_path = REPO / weights["path"]
    if (
        not weights_path.is_file()
        or weights_path.is_symlink()
        or weights_path.stat().st_size != weights["bytes"]
    ):
        raise QualificationError("SigLIP2 weights identity drifted")
    ffmpeg = Path(contract["support"]["ffmpeg_path"])
    if not ffmpeg.is_file() or ffmpeg.is_symlink() or _sha(ffmpeg.read_bytes()) != contract[
        "support"
    ]["ffmpeg_sha256"]:
        raise QualificationError("host ffmpeg identity drifted")


def _image_identity(ref: str, expected_id: str, counter: list[int]) -> dict[str, Any]:
    raw = _docker(["image", "inspect", ref], counter).stdout
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError("Docker image inspect JSON invalid") from exc
    if (
        not isinstance(values, list)
        or len(values) != 1
        or values[0].get("Id") != expected_id
        or values[0].get("Architecture") != "arm64"
    ):
        raise QualificationError(f"image identity drifted: {ref}")
    return {"image_id_exact": True, "architecture": "arm64"}


def _inspect_container(name: str, counter: list[int]) -> dict[str, Any]:
    raw = _docker(["inspect", name], counter).stdout
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"container inspect JSON invalid: {name}") from exc
    if not isinstance(rows, list) or len(rows) != 1:
        raise QualificationError(f"container inspect envelope invalid: {name}")
    return rows[0]


def _container_absent(name: str, counter: list[int]) -> bool:
    result = _docker(
        ["ps", "-aq", "--filter", f"name=^/{name}$"], counter, check=False
    )
    return result.returncode == 0 and not result.stdout.strip()


def _snapshot_main(contract: dict[str, Any], counter: list[int], http: list[int]) -> dict[str, Any]:
    name = contract["execution"]["main_container"]
    row = _inspect_container(name, counter)
    state = row.get("State", {})
    status, raw = _http(contract["execution"]["main_endpoint"], "/api/v1/metrics", http)
    metrics = _json_response(status, raw, "main RT-CV metrics")
    stream_count = metrics.get("metrics-info", {}).get("stream-count")
    snapshot = {
        "container_id": row.get("Id"),
        "image_id": row.get("Image"),
        "running": state.get("Running"),
        "health": state.get("Health", {}).get("Status"),
        "oom_killed": state.get("OOMKilled"),
        "restart_count": row.get("RestartCount"),
        "started_at": state.get("StartedAt"),
        "stream_count": stream_count,
    }
    if (
        snapshot["running"] is not True
        or snapshot["health"] != "healthy"
        or snapshot["oom_killed"] is not False
        or not isinstance(snapshot["restart_count"], int)
        or not isinstance(stream_count, int)
    ):
        raise QualificationError("main RT-CV service is not healthy before isolation")
    return snapshot


def _paused_snapshot(contract: dict[str, Any], counter: list[int]) -> dict[str, str]:
    states: dict[str, str] = {}
    for name in contract["execution"]["paused_workloads"]:
        row = _inspect_container(name, counter)
        status = row.get("State", {}).get("Status")
        if status == "running":
            raise QualificationError(f"paused workload unexpectedly running: {name}")
        states[name] = str(status)
    return states


def _replace_section_key(text: str, section: str, key: str, value: str) -> str:
    pattern = re.compile(
        rf"(^\[{re.escape(section)}\]\n)(.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    if match is None:
        raise QualificationError(f"missing config section [{section}]")
    body = match.group(2)
    key_pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if len(key_pattern.findall(body)) != 1:
        raise QualificationError(f"expected one active [{section}] {key}")
    body = key_pattern.sub(f"{key}={value}", body)
    return text[: match.start(2)] + body + text[match.end(2) :]


def _stage_configs(contract: dict[str, Any], destination: Path) -> None:
    source = REPO / contract["execution"]["config_source"]
    shutil.copytree(source, destination)
    main = destination / "ds-main-config.txt"
    text = main.read_text()
    text = _replace_section_key(text, "source-list", "http-port", str(contract["execution"]["port"]))
    text = _replace_section_key(text, "sink1", "msg-broker-conn-str", f"localhost;9092;{contract['execution']['topic']}")
    text = _replace_section_key(text, "sink1", "topic", contract["execution"]["topic"])
    text = _replace_section_key(text, "tests", "file-loop", "0")
    main.write_text(text)


def _wait_http(endpoint: str, path: str, http: list[int], deadline: float) -> dict[str, Any]:
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, raw = _http(endpoint, path, http, timeout=3)
            if status == 200:
                return _json_response(status, raw, path)
        except QualificationError as exc:
            last = exc
        time.sleep(1)
    raise QualificationError(f"timed out waiting for {path}") from last


def _metric_snapshot(endpoint: str, http: list[int]) -> dict[str, Any]:
    status, raw = _http(endpoint, "/api/v1/metrics", http)
    value = _json_response(status, raw, "RT-CV metrics")
    info = value.get("metrics-info")
    if status != 200 or not isinstance(info, dict):
        raise QualificationError("RT-CV metrics envelope drifted")
    return info


def _wait_active_metrics(endpoint: str, http: list[int], deadline: float) -> dict[str, Any]:
    while time.monotonic() < deadline:
        info = _metric_snapshot(endpoint, http)
        rows = info.get("stream-stats")
        if (
            info.get("stream-count") == 1
            and isinstance(rows, list)
            and len(rows) == 1
            and float(rows[0].get("frame_number", 0)) > 0
            and float(rows[0].get("fps", 0)) > 0
            and math.isfinite(float(rows[0].get("latency_ms", math.nan)))
        ):
            return {
                "stream_count": 1,
                "frame_number_positive": True,
                "fps_positive": True,
                "latency_finite": True,
            }
        time.sleep(0.5)
    raise QualificationError("active RT-CV metrics did not become truthful")


def _wait_stream_count(endpoint: str, expected: int, http: list[int], deadline: float) -> None:
    while time.monotonic() < deadline:
        if _metric_snapshot(endpoint, http).get("stream-count") == expected:
            return
        time.sleep(0.5)
    raise QualificationError(f"RT-CV stream count did not become {expected}")


CONSUMER_CODE = r'''
import json, math, os, time
from collections import Counter
from confluent_kafka import Consumer
from schema_pb2 import Frame

topic=os.environ["QUAL_TOPIC"]
group=os.environ["QUAL_GROUP"]
sensor=os.environ["QUAL_SENSOR"]
consumer=Consumer({
    "bootstrap.servers":"127.0.0.1:9092",
    "group.id":group,
    "auto.offset.reset":"latest",
    "enable.auto.commit":False,
})
consumer.subscribe([topic])
consumer.poll(1.0)
print(json.dumps({"state":"ready"},sort_keys=True),flush=True)
frames=[]
deadline=time.monotonic()+90
while len(frames)<8 and time.monotonic()<deadline:
    message=consumer.poll(2.0)
    if message is None or message.error():
        continue
    frame=Frame()
    frame.ParseFromString(message.value())
    frames.append(frame)
consumer.close()
objects=[obj for frame in frames for obj in frame.objects]
ids=Counter(str(obj.id) for obj in objects)
dims=sorted(set(len(obj.embedding.vector) for obj in objects if len(obj.embedding.vector)))
result={
    "state":"complete",
    "frames":len(frames),
    "objects":len(objects),
    "minimum_objects_per_frame":min((len(frame.objects) for frame in frames),default=0),
    "maximum_objects_per_frame":max((len(frame.objects) for frame in frames),default=0),
    "types":sorted(set(obj.type for obj in objects)),
    "unique_track_ids":len(ids),
    "repeated_track_ids":sum(1 for count in ids.values() if count>1),
    "embedding_dimensions":dims,
    "finite_bboxes":all(math.isfinite(value) for obj in objects for value in (obj.bbox.leftX,obj.bbox.topY,obj.bbox.rightX,obj.bbox.bottomY)),
    "finite_confidences":all(math.isfinite(obj.confidence) for obj in objects),
    "finite_embeddings":all(math.isfinite(value) for obj in objects for value in obj.embedding.vector),
    "single_sensor_value":bool(frames) and len(set(frame.sensorId for frame in frames))==1,
    "sensor_value_present":bool(frames) and all(bool(frame.sensorId) for frame in frames),
}
print(json.dumps(result,sort_keys=True),flush=True)
passed=(
    result["frames"]==8
    and result["objects"]>0
    and set(result["types"]) >= {"Person","Pallet"}
    and result["repeated_track_ids"]>0
    and result["embedding_dimensions"]==[1152]
    and result["finite_bboxes"]
    and result["finite_confidences"]
    and result["finite_embeddings"]
    and result["single_sensor_value"]
    and result["sensor_value_present"]
)
raise SystemExit(0 if passed else 7)
'''


def _start_consumer(
    contract: dict[str, Any],
    name: str,
    group: str,
    sensor: str,
    counter: list[int],
) -> None:
    if not _container_absent(name, counter):
        raise QualificationError(f"owned consumer container already exists: {name}")
    support = contract["support"]
    run = _docker(
        [
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "host",
            "--label",
            "vss.thor.qualifier=rt-cv-2d-core",
            "-e",
            f"QUAL_TOPIC={contract['execution']['topic']}",
            "-e",
            f"QUAL_GROUP={group}",
            "-e",
            f"QUAL_SENSOR={sensor}",
            "-v",
            f"{REPO / 'tools/message-broker-consumers'}:/work:ro",
            "-w",
            "/work",
            support["consumer_image"],
            "python3",
            "-c",
            CONSUMER_CODE,
        ],
        counter,
        timeout=30,
    )
    if len(run.stdout.decode().strip()) != 64:
        raise QualificationError("consumer container identity invalid")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        logs = _docker(["logs", name], counter, check=False).stdout.decode(errors="replace")
        if '"state": "ready"' in logs:
            return
        row = _inspect_container(name, counter)
        if row.get("State", {}).get("Running") is not True:
            raise QualificationError("consumer exited before assignment")
        time.sleep(0.5)
    raise QualificationError("consumer did not become ready")


def _finish_consumer(name: str, counter: list[int]) -> dict[str, Any]:
    wait = _docker(["wait", name], counter, check=False, timeout=110)
    logs = _docker(["logs", name], counter).stdout.decode(errors="replace")
    results = []
    for line in logs.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("state") == "complete":
            results.append(value)
    if wait.returncode != 0 or wait.stdout.decode().strip() != "0":
        summary = results[0] if len(results) == 1 else {"log_sha256": _sha(logs)}
        raise QualificationError(
            "consumer aggregate oracle failed: " + _canonical(summary).decode()
        )
    if len(results) != 1:
        raise QualificationError("consumer did not emit one sanitized result")
    result = results[0]
    required_true = (
        "finite_bboxes",
        "finite_confidences",
        "finite_embeddings",
        "single_sensor_value",
        "sensor_value_present",
    )
    if (
        result.get("frames") != 8
        or int(result.get("objects", 0)) <= 0
        or not {"Person", "Pallet"}.issubset(set(result.get("types", [])))
        or int(result.get("repeated_track_ids", 0)) <= 0
        or result.get("embedding_dimensions") != [1152]
        or not all(result.get(key) is True for key in required_true)
    ):
        raise QualificationError("sanitized detection/tracking oracle failed")
    _docker(["rm", name], counter)
    result.pop("state", None)
    return result


def _stream_payload(sensor: str, name: str, url: str, change: str) -> bytes:
    return _canonical(
        {
            "key": "sensor",
            "value": {
                "camera_id": sensor,
                "camera_name": name,
                "camera_url": url,
                "change": change,
                "metadata": {},
            },
        }
    )


def _stream_call(
    endpoint: str,
    operation: str,
    sensor: str,
    name: str,
    url: str,
    http: list[int],
) -> dict[str, Any]:
    body = _stream_payload(sensor, name, url, f"camera_{operation}")
    status, raw = _http(
        endpoint,
        f"/api/v1/stream/{operation}",
        http,
        method="POST",
        body=body,
        timeout=20,
    )
    value = _json_response(status, raw, f"stream {operation}")
    if status != 200 or value.get("status") != "HTTP/1.1 200 OK":
        raise QualificationError(f"RT-CV stream {operation} failed")
    return {
        "http_status": status,
        "request_sha256": _sha(body),
        "response_sha256": _sha(raw),
    }


def _config_oracle(contract: dict[str, Any], counter: list[int]) -> dict[str, Any]:
    name = contract["execution"]["container"]
    app = "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/configs"
    main_raw = _docker(["exec", name, "cat", f"{app}/ds-main-config.txt"], counter).stdout
    tracker_raw = _docker(
        ["exec", name, "cat", f"{app}/ds-nvdcf-accuracy-tracker-config.yml"], counter
    ).stdout
    main = main_raw.decode()
    tracker = tracker_raw.decode()

    def ini(section: str, key: str) -> str:
        pattern = re.compile(
            rf"^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL
        )
        match = pattern.search(main)
        if match is None:
            raise QualificationError(f"effective section missing: {section}")
        values = re.findall(rf"^{re.escape(key)}=(.*)$", match.group(1), re.MULTILINE)
        if len(values) != 1:
            raise QualificationError(f"effective key ambiguous: {section}.{key}")
        return values[0].strip()

    def yaml(key: str) -> int:
        values = re.findall(rf"^[ ]*{re.escape(key)}:[ ]*([0-9]+)[ ]*$", tracker, re.MULTILINE)
        if len(values) != 1:
            raise QualificationError(f"effective tracker key ambiguous: {key}")
        return int(values[0])

    result = {
        "hardware_profile": "AGX-THOR",
        "compute_hw": int(ini("tracker", "compute-hw")),
        "low_latency_mode": int(ini("source-list", "low-latency-mode")),
        "max_batch_size": int(ini("source-list", "max-batch-size")),
        "max_targets_per_stream": yaml("maxTargetsPerStream"),
        "visual_tracker_type": yaml("visualTrackerType"),
        "vpi_backend_4dcf_tracker": yaml("vpiBackend4DcfTracker"),
        "main_config_sha256": _sha(main_raw),
        "tracker_config_sha256": _sha(tracker_raw),
    }
    result["capacity_product"] = result["max_batch_size"] * result["max_targets_per_stream"]
    expected = {
        "compute_hw": 2,
        "low_latency_mode": 0,
        "max_batch_size": 16,
        "max_targets_per_stream": 32,
        "visual_tracker_type": 2,
        "vpi_backend_4dcf_tracker": 2,
        "capacity_product": 512,
    }
    if any(result[key] != value for key, value in expected.items()):
        raise QualificationError("effective Thor VPI tracker configuration drifted")
    return result


def _prometheus(endpoint: str, http: list[int]) -> dict[str, Any]:
    status, raw = _http(
        endpoint,
        "/api/v1/metrics",
        http,
        accept="text/plain; version=0.0.4",
    )
    text = raw.decode(errors="replace")
    families = sorted(set(re.findall(r"^# TYPE ([A-Za-z_:][A-Za-z0-9_:]*) ", text, re.MULTILINE)))
    required = {
        "fps_metrics",
        "frame_number_metrics",
        "latency_metrics",
        "memory_metrics",
        "stream_count",
        "utilization_metrics",
    }
    if status != 200 or not required.issubset(families):
        raise QualificationError("RT-CV Prometheus metric families drifted")
    return {
        "http_status": 200,
        "required_metric_families_present": True,
        "metric_families": families,
        "body_sha256": _sha(raw),
    }


def _wait_port(port: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise QualificationError(f"loopback port {port} did not become ready")


def _probe_media(
    path_or_url: str, *, rtsp: bool, expected_duration: int | None = None
) -> dict[str, Any]:
    args = ["ffprobe", "-v", "error"]
    if rtsp:
        args.extend(["-rtsp_transport", "tcp", "-read_intervals", "%+1"])
    args.extend(
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            path_or_url,
        ]
    )
    result = _run(args, timeout=20)
    try:
        value = json.loads(result.stdout)
        stream = value["streams"][0]
        rate = Fraction(stream["r_frame_rate"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, ZeroDivisionError) as exc:
        raise QualificationError("media probe envelope invalid") from exc
    if (
        stream.get("codec_name") != "h264"
        or stream.get("width") != 1920
        or stream.get("height") != 1080
        or rate != 10
    ):
        raise QualificationError("media codec/dimensions/rate drifted")
    duration = value.get("format", {}).get("duration")
    if not rtsp and (
        expected_duration is None or float(duration or 0) != float(expected_duration)
    ):
        raise QualificationError("finite fixture duration drifted")
    return {
        "codec_h264": True,
        "width": 1920,
        "height": 1080,
        "fps": 10,
        "duration_seconds": None if rtsp else expected_duration,
        "tcp_probe_passed": rtsp,
    }


def _generate_runtime_file(contract: dict[str, Any], destination: Path) -> bytes:
    execution = contract["execution"]
    source = REPO / contract["assets"]["fixture"]["path"]
    _run(
        [
            contract["support"]["ffmpeg_path"],
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            str(execution["runtime_file_repetitions"] - 1),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "copy",
            "-t",
            str(execution["runtime_file_duration_seconds"]),
            str(destination),
        ],
        timeout=40,
    )
    data = destination.read_bytes()
    if not data or destination.is_symlink():
        raise QualificationError("bounded runtime file generation failed")
    return data


def _remove_owned_container(name: str, counter: list[int], failures: list[str]) -> None:
    if _container_absent(name, counter):
        return
    stop = _docker(["stop", "--timeout", "10", name], counter, check=False, timeout=20)
    if stop.returncode != 0:
        failures.append(f"{name}_stop_failed")
    remove = _docker(["rm", name], counter, check=False, timeout=20)
    if remove.returncode != 0:
        failures.append(f"{name}_remove_failed")


def _topic_list(counter: list[int]) -> set[str]:
    result = _docker(
        ["exec", "kafka", "kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
        counter,
    )
    return set(result.stdout.decode().splitlines())


def _delete_group(group: str, counter: list[int]) -> None:
    _docker(
        [
            "exec",
            "kafka",
            "kafka-consumer-groups",
            "--bootstrap-server",
            "localhost:9092",
            "--delete",
            "--group",
            group,
        ],
        counter,
        check=False,
    )


def _execute(contract: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    _verify_static(contract)
    execution = contract["execution"]
    endpoint = execution["endpoint"]
    docker_commands = [0]
    http_requests = [0]
    cleanup_failures: list[str] = []
    publisher: subprocess.Popen[bytes] | None = None
    temp_path: Path | None = None
    file_added = False
    rtsp_added = False

    if shutil.disk_usage(REPO).free < execution["minimum_free_bytes"]:
        raise QualificationError("free-space safety margin is below 10 GiB")
    driver = _docker(["info", "--format", "{{.CgroupDriver}}"], docker_commands).stdout.decode().strip()
    if driver != "cgroupfs":
        raise QualificationError("Docker cgroup driver must be cgroupfs on Thor")
    for name in (execution["container"], execution["file_consumer"], execution["rtsp_consumer"], execution["mediamtx_container"]):
        if not _container_absent(name, docker_commands):
            raise QualificationError(f"owned runtime name already exists: {name}")
    if execution["topic"] in _topic_list(docker_commands):
        raise QualificationError("owned Kafka topic already exists")

    rt_cv_image = _image_identity(contract["images"]["rt_cv"]["ref"], contract["images"]["rt_cv"]["id"], docker_commands)
    consumer_image = _image_identity(contract["images"]["consumer"]["ref"], contract["images"]["consumer"]["id"], docker_commands)
    mediamtx_image = _image_identity(contract["images"]["mediamtx"]["ref"], contract["images"]["mediamtx"]["id"], docker_commands)
    main_before = _snapshot_main(contract, docker_commands, http_requests)
    paused_before = _paused_snapshot(contract, docker_commands)
    fixture_probe = _probe_media(
        str(REPO / contract["assets"]["fixture"]["path"]),
        rtsp=False,
        expected_duration=10,
    )

    file_result: dict[str, Any] = {}
    rtsp_result: dict[str, Any] = {}
    lifecycle: dict[str, Any] = {}
    health_metrics: dict[str, Any] = {}
    configuration: dict[str, Any] = {}
    container_started_at = ""
    isolated_log_sha256 = ""
    vpi_error_count = -1

    with tempfile.TemporaryDirectory(prefix="rt-cv-2d-core-") as temp_dir:
        temp_path = Path(temp_dir)
        configs = temp_path / "configs"
        _stage_configs(contract, configs)
        runtime_file = temp_path / "warehouse-runtime.mp4"
        runtime_file_bytes = _generate_runtime_file(contract, runtime_file)
        runtime_file_probe = _probe_media(
            str(runtime_file),
            rtsp=False,
            expected_duration=execution["runtime_file_duration_seconds"],
        )
        try:
            create = _docker(
                [
                    "exec",
                    "kafka",
                    "kafka-topics",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--create",
                    "--topic",
                    execution["topic"],
                    "--partitions",
                    "1",
                    "--replication-factor",
                    "1",
                ],
                docker_commands,
            )
            if b"Created topic" not in create.stdout and b"Created topic" not in create.stderr:
                raise QualificationError("owned Kafka topic creation was not acknowledged")

            run = _docker(
                [
                    "run",
                    "-d",
                    "--name",
                    execution["container"],
                    "--network",
                    "host",
                    "--runtime",
                    "nvidia",
                    "--gpus",
                    "device=0",
                    "--label",
                    "vss.thor.qualifier=rt-cv-2d-core",
                    "-e",
                    "DS_MESSAGE_RATE=1",
                    "-e",
                    "DS_SHOW_SENSOR_ID=false",
                    "-e",
                    "VISION_ENCODER_MODEL=siglip_v2",
                    "-e",
                    "VISION_ENCODER_VERSION=v1.1",
                    "-e",
                    "TRANSFORMERS_OFFLINE=1",
                    "-e",
                    "HF_HUB_OFFLINE=1",
                    "-e",
                    "OTEL_SDK_DISABLED=true",
                    "-e",
                    "GST_ENABLE_CUSTOM_PARSER_MODIFICATIONS=1",
                    "-e",
                    "DEEPSTREAM_ENABLE_SENSOR_ID_EXTRACTION=1",
                    "-e",
                    "HARDWARE_PROFILE=AGX-THOR",
                    "-e",
                    "STREAM_TYPE=kafka",
                    "-e",
                    "DS_TRACKER_REID=true",
                    "-e",
                    "DS_MODEL_FAMILY=rtdetr-warehouse",
                    "-e",
                    "DS_MODE_FLAG=1",
                    "-e",
                    "GST_PLUGIN_PATH=/opt/nvidia/deepstream/deepstream/sources/gst-plugins/gst-nvdstextembedder",
                    "-v",
                    f"{REPO / execution['search_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh:ro",
                    "-v",
                    f"{REPO / execution['shared_start']}:/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-start.sh:ro",
                    "-v",
                    f"{REPO / execution['models_dir']}:/opt/storage:ro",
                    "-v",
                    f"{runtime_file}:/opt/fixtures/test.mp4:ro",
                    "-v",
                    f"{configs}:/opt/ds-configs-ro:ro",
                    contract["images"]["rt_cv"]["ref"],
                    "bash",
                    "-c",
                    "/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app/ds-search-start.sh",
                ],
                docker_commands,
                timeout=40,
            )
            if len(run.stdout.decode().strip()) != 64:
                raise QualificationError("isolated RT-CV container identity invalid")
            _wait_http(endpoint, "/api/v1/ready", http_requests, time.monotonic() + 180)
            for path in ("/api/v1/live", "/api/v1/ready", "/api/v1/startup", "/api/v1/metadata"):
                status, raw = _http(endpoint, path, http_requests)
                if status != 200 or not isinstance(json.loads(raw), dict):
                    raise QualificationError(f"health endpoint failed: {path}")
            row = _inspect_container(execution["container"], docker_commands)
            state = row.get("State", {})
            if (
                row.get("Image") != contract["images"]["rt_cv"]["id"]
                or state.get("Running") is not True
                or state.get("OOMKilled") is not False
                or row.get("RestartCount") != 0
            ):
                raise QualificationError("isolated RT-CV runtime identity drifted")
            container_started_at = str(state.get("StartedAt"))
            configuration = _config_oracle(contract, docker_commands)

            file_sensor = "rtcv-runtime-file"
            file_name = "RTCV Runtime File"
            file_url = "file:///opt/fixtures/test.mp4"
            _start_consumer(contract, execution["file_consumer"], execution["file_group"], file_sensor, docker_commands)
            file_add = _stream_call(endpoint, "add", file_sensor, file_name, file_url, http_requests)
            file_added = True
            file_metrics = _wait_active_metrics(endpoint, http_requests, time.monotonic() + 45)
            file_detection = _finish_consumer(execution["file_consumer"], docker_commands)
            file_remove = _stream_call(endpoint, "remove", file_sensor, file_name, file_url, http_requests)
            file_added = False
            _wait_stream_count(endpoint, 0, http_requests, time.monotonic() + 30)
            file_result = {
                "input_type": "finite_local_file",
                "source_replay_until_explicit_remove": False,
                "runtime_fixture": {
                    "generation_method_exact": True,
                    "source_repetitions": execution["runtime_file_repetitions"],
                    "content_sha256": _sha(runtime_file_bytes),
                    "byte_count": len(runtime_file_bytes),
                    **runtime_file_probe,
                },
                "add": file_add,
                "active_metrics": file_metrics,
                "detection_tracking": file_detection,
                "remove": file_remove,
                "terminated_cleanly": True,
            }

            stopped = _docker(
                ["stop", "--timeout", "15", execution["container"]],
                docker_commands,
                check=False,
                timeout=30,
            )
            started_again = _docker(
                ["start", execution["container"]],
                docker_commands,
                check=False,
                timeout=30,
            )
            if stopped.returncode != 0 or started_again.returncode != 0:
                raise QualificationError("planned isolated pipeline restart failed")
            _wait_http(endpoint, "/api/v1/ready", http_requests, time.monotonic() + 180)
            restarted_row = _inspect_container(execution["container"], docker_commands)
            restarted_state = restarted_row.get("State", {})
            if (
                restarted_state.get("Running") is not True
                or restarted_state.get("OOMKilled") is not False
                or restarted_row.get("RestartCount") != 0
            ):
                raise QualificationError("planned isolated pipeline restart was not clean")
            container_started_at = str(restarted_state.get("StartedAt"))
            if _config_oracle(contract, docker_commands) != configuration:
                raise QualificationError("Thor VPI config changed across planned restart")

            mediamtx = _docker(
                [
                    "run",
                    "-d",
                    "--name",
                    execution["mediamtx_container"],
                    "--label",
                    "vss.thor.qualifier=rt-cv-2d-core",
                    "-p",
                    f"127.0.0.1:{execution['rtsp_port']}:8554",
                    contract["images"]["mediamtx"]["ref"],
                ],
                docker_commands,
            )
            if len(mediamtx.stdout.decode().strip()) != 64:
                raise QualificationError("MediaMTX container identity invalid")
            _wait_port(execution["rtsp_port"], time.monotonic() + 15)
            rtsp_url = f"rtsp://127.0.0.1:{execution['rtsp_port']}/rtcv-runtime"
            publisher = subprocess.Popen(
                [
                    contract["support"]["ffmpeg_path"],
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-re",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(REPO / contract["assets"]["fixture"]["path"]),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-c:v",
                    "copy",
                    "-f",
                    "rtsp",
                    "-rtsp_transport",
                    "tcp",
                    rtsp_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
            if publisher.poll() is not None:
                raise QualificationError("loopback RTSP publisher exited early")
            probe_deadline = time.monotonic() + 15
            while True:
                try:
                    rtsp_probe = _probe_media(rtsp_url, rtsp=True)
                    break
                except QualificationError:
                    if time.monotonic() >= probe_deadline:
                        raise
                    time.sleep(1)
            rtsp_sensor = "rtcv-runtime-rtsp"
            rtsp_name = "RTCV Runtime RTSP"
            _start_consumer(contract, execution["rtsp_consumer"], execution["rtsp_group"], rtsp_sensor, docker_commands)
            rtsp_add = _stream_call(endpoint, "add", rtsp_sensor, rtsp_name, rtsp_url, http_requests)
            rtsp_added = True
            rtsp_metrics = _wait_active_metrics(endpoint, http_requests, time.monotonic() + 45)
            rtsp_detection = _finish_consumer(execution["rtsp_consumer"], docker_commands)
            prometheus = _prometheus(endpoint, http_requests)
            rtsp_remove = _stream_call(endpoint, "remove", rtsp_sensor, rtsp_name, rtsp_url, http_requests)
            rtsp_added = False
            _wait_stream_count(endpoint, 0, http_requests, time.monotonic() + 30)
            rtsp_result = {
                "input_type": "loopback_rtsp",
                "support_image_exact": True,
                "publisher_running": publisher.poll() is None,
                "media_probe": rtsp_probe,
                "add": rtsp_add,
                "active_metrics": rtsp_metrics,
                "detection_tracking": rtsp_detection,
                "remove": rtsp_remove,
                "terminated_cleanly": True,
            }
            lifecycle = {
                "file_add_http_status": file_add["http_status"],
                "file_remove_http_status": file_remove["http_status"],
                "rtsp_add_http_status": rtsp_add["http_status"],
                "rtsp_remove_http_status": rtsp_remove["http_status"],
                "active_state_observed_for_each": True,
                "terminal_state_observed_for_each": True,
                "final_stream_count": 0,
                "pre_existing_streams_touched": 0,
                "planned_pipeline_restart_between_input_lanes": True,
            }
            health_metrics = {
                "live_http_status": 200,
                "ready_http_status": 200,
                "startup_http_status": 200,
                "metadata_http_status": 200,
                "file_frame_metric_correlated": True,
                "file_detection_metric_correlated": file_detection["objects"] > 0,
                "rtsp_frame_metric_correlated": True,
                "rtsp_detection_metric_correlated": rtsp_detection["objects"] > 0,
                "prometheus": prometheus,
            }
            isolated_logs = _docker(
                ["logs", "--since", container_started_at, execution["container"]],
                docker_commands,
            ).stdout
            vpi_error_count = isolated_logs.count(b"VPI_ERROR")
            if vpi_error_count != 0:
                raise QualificationError("clean isolated run emitted a VPI error")
            isolated_log_sha256 = _sha(isolated_logs)
        finally:
            if rtsp_added:
                try:
                    _stream_call(endpoint, "remove", "rtcv-runtime-rtsp", "RTCV Runtime RTSP", f"rtsp://127.0.0.1:{execution['rtsp_port']}/rtcv-runtime", http_requests)
                    rtsp_added = False
                except QualificationError:
                    cleanup_failures.append("rtsp_stream_remove_failed")
            if file_added:
                try:
                    _stream_call(endpoint, "remove", "rtcv-runtime-file", "RTCV Runtime File", "file:///opt/fixtures/test.mp4", http_requests)
                    file_added = False
                except QualificationError:
                    cleanup_failures.append("file_stream_remove_failed")
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
            for name in (
                execution["file_consumer"],
                execution["rtsp_consumer"],
                execution["mediamtx_container"],
                execution["container"],
            ):
                _remove_owned_container(name, docker_commands, cleanup_failures)
            for group in (execution["file_group"], execution["rtsp_group"]):
                _delete_group(group, docker_commands)
            if execution["topic"] in _topic_list(docker_commands):
                delete = _docker(
                    [
                        "exec",
                        "kafka",
                        "kafka-topics",
                        "--bootstrap-server",
                        "localhost:9092",
                        "--delete",
                        "--topic",
                        execution["topic"],
                    ],
                    docker_commands,
                    check=False,
                )
                if delete.returncode != 0:
                    cleanup_failures.append("topic_delete_failed")

    time.sleep(1)
    for name in (execution["container"], execution["file_consumer"], execution["rtsp_consumer"], execution["mediamtx_container"]):
        if not _container_absent(name, docker_commands):
            cleanup_failures.append(f"{name}_remains")
    if execution["topic"] in _topic_list(docker_commands):
        cleanup_failures.append("topic_remains")
    main_after = _snapshot_main(contract, docker_commands, http_requests)
    paused_after = _paused_snapshot(contract, docker_commands)
    if main_after != main_before:
        cleanup_failures.append("main_rt_cv_state_changed")
    if paused_after != paused_before:
        cleanup_failures.append("paused_workload_state_changed")
    if temp_path is None or temp_path.exists():
        cleanup_failures.append("temporary_root_remains")
    if cleanup_failures:
        raise QualificationError("cleanup failed: " + ",".join(cleanup_failures))
    if not file_result or not rtsp_result or not lifecycle or not health_metrics:
        raise QualificationError("runtime evidence is incomplete")

    duration = time.monotonic() - started
    if not 0 < duration <= execution["max_duration_seconds"]:
        raise QualificationError("qualification duration bound exceeded")
    if docker_commands[0] > execution["max_docker_commands"]:
        raise QualificationError("Docker command budget exceeded")
    if http_requests[0] > execution["max_http_requests"]:
        raise QualificationError("HTTP request budget exceeded")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(duration, 6),
        "budget": {
            "docker_commands": docker_commands[0],
            "max_docker_commands": execution["max_docker_commands"],
            "http_requests": http_requests[0],
            "max_http_requests": execution["max_http_requests"],
            "support_processes_peak": 4,
            "stream_mutations": 4,
        },
        "runtime_identity": {
            "docker_cgroup_driver": driver,
            "rt_cv_image": rt_cv_image,
            "consumer_image": consumer_image,
            "mediamtx_image": mediamtx_image,
            "main_rt_cv_preserved_exactly": True,
            "main_rt_cv_stream_count": main_after["stream_count"],
            "paused_workloads_preserved_exactly": True,
        },
        "configuration": configuration,
        "fixture": {
            "byte_count": contract["assets"]["fixture"]["bytes"],
            "content_sha256": contract["assets"]["fixture"]["sha256"],
            **fixture_probe,
            "warehouse_sample_bundle": "excluded",
        },
        "file_detection_tracking": file_result,
        "rtsp_detection_tracking": rtsp_result,
        "dynamic_stream_lifecycle": lifecycle,
        "health_metrics": health_metrics,
        "thor_vpi_tracker": {
            "effective_configuration_exact": True,
            "stable_tracks_file": file_result["detection_tracking"]["repeated_track_ids"] > 0,
            "stable_tracks_rtsp": rtsp_result["detection_tracking"]["repeated_track_ids"] > 0,
            "vpi_error_count_after_clean_start": vpi_error_count,
            "isolated_log_sha256": isolated_log_sha256,
            "oom_killed": False,
            "restart_count": 0,
        },
        "cleanup": {
            "failures": [],
            "owned_containers_absent": True,
            "owned_topic_absent": True,
            "owned_consumer_groups_delete_attempted": True,
            "publisher_stopped": True,
            "temporary_root_absent": True,
            "main_rt_cv_preserved_exactly": True,
            "paused_workloads_preserved_exactly": True,
        },
        "policy": {
            "agent_generate_calls": 0,
            "main_rt_cv_stream_mutations": 0,
            "main_vios_stream_mutations": 0,
            "warehouse_sample_bundle": "excluded",
            "network_downloads": 0,
            "raw_camera_ids_retained": False,
            "raw_stream_urls_retained": False,
            "raw_embeddings_retained": False,
            "raw_broker_messages_retained": False,
            "credentials_retained": False,
        },
    }
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    return receipt


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
        "warehouse_sample_bundle": "excluded",
        "network_downloads": 0,
        "main_rt_cv_stream_mutations": 0,
        "main_vios_stream_mutations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"), nargs="?", default="plan")
    parser.add_argument("--ack")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        if args.mode == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract)
            if args.write_receipt:
                temporary = RECEIPT_PATH.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
                os.replace(temporary, RECEIPT_PATH)
    except (QualificationError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
