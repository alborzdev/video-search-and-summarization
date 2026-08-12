#!/usr/bin/env python3
"""Qualify CV -> Behavior Analytics -> local VLM verification on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
VIOS = "http://127.0.0.1:30888/vst/api/v1"
RTCV = "http://127.0.0.1:9000/api/v1"
ALERT = "http://127.0.0.1:9080"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
MEDIA_MTX = "rtsp://127.0.0.1:8554"
ACK = "I_AUTHORIZE_OWNED_CV_BEHAVIOR_VLM_VERIFICATION"
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
TEMP_ROOT = "/home/vst/vst_release/webroot/temp_files"


class QualificationFailure(RuntimeError):
    """The current Thor runtime did not satisfy the qualification contract."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationFailure(f"expected JSON object: {path}")
    return value


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    data = canonical(body) if body is not None else None
    request_headers = dict(headers or {})
    if data is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url, data=data, method=method, headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if not raw.strip():
                return response.status, None
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed: Any = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationFailure(f"local request failed: {url}") from exc


def docker(*args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=timeout,
    )


def live_file_sha(container: str, path: str) -> str:
    script = "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())"
    for interpreter in ("/usr/local/bin/python", "python3", "python"):
        result = subprocess.run(
            ["docker", "exec", container, interpreter, "-c", script, path],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    raise QualificationFailure(f"cannot hash live source in container: {container}")


def running_containers() -> list[dict[str, str]]:
    result = docker("ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}")
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        container_id, name, image = line.split("\t", 2)
        rows.append({"id": container_id, "name": name, "image": image})
    return sorted(rows, key=lambda item: item["name"])


def alert_configs() -> list[dict[str, Any]]:
    status, body = request_json(f"{ALERT}/api/v1/verification/config")
    rows = body.get("configs") if isinstance(body, dict) else None
    if status != 200 or not isinstance(rows, list):
        raise QualificationFailure("Alert Bridge config snapshot failed")
    return sorted(rows, key=lambda item: str(item.get("alert_type", "")))


def realtime_rules() -> list[dict[str, Any]]:
    status, body = request_json(f"{ALERT}/api/v1/realtime")
    rows = body.get("rules") if isinstance(body, dict) else None
    if status != 200 or not isinstance(rows, list):
        raise QualificationFailure("Alert Bridge rule snapshot failed")
    return sorted(rows, key=lambda item: str(item.get("id", "")))


def rtvlm_streams() -> list[dict[str, Any]]:
    status, body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        rows = next(
            (
                body[key]
                for key in ("results", "streams", "items", "data")
                if isinstance(body.get(key), list)
            ),
            None,
        )
    else:
        rows = None
    if status != 200 or rows is None:
        raise QualificationFailure("RT-VLM stream snapshot failed")
    return sorted(rows, key=lambda item: canonical(item))


def rt_cv_streams() -> dict[str, Any]:
    status, body = request_json(f"{RTCV}/stream/get-stream-info")
    if status != 200 or not isinstance(body, dict):
        raise QualificationFailure("RT-CV stream snapshot failed")
    return body


def vios_active_sensors() -> list[dict[str, Any]]:
    status, body = request_json(f"{VIOS}/sensor/list")
    if status != 200 or not isinstance(body, list):
        raise QualificationFailure("VIOS sensor snapshot failed")
    keys = ("sensorId", "name", "state", "type", "isTimelinePresent")
    rows = [
        {key: item.get(key) for key in keys}
        for item in body
        if isinstance(item, dict) and item.get("state") != "removed"
    ]
    return sorted(rows, key=lambda item: str(item.get("sensorId", "")))


def vios_proxies() -> list[dict[str, Any]]:
    status, body = request_json(f"{VIOS}/proxy/streams")
    if status != 200 or not isinstance(body, list):
        raise QualificationFailure("VIOS proxy snapshot failed")
    return sorted(body, key=lambda item: str(item.get("sensorId", "")))


def snapshot() -> dict[str, Any]:
    return {
        "active_sensors": vios_active_sensors(),
        "alert_configs": alert_configs(),
        "proxies": vios_proxies(),
        "realtime_rules": realtime_rules(),
        "rtcv_streams": rt_cv_streams(),
        "rtvlm_streams": rtvlm_streams(),
        "running_containers": running_containers(),
    }


def stable_snapshot(*, attempts: int = 20, seconds: float = 1) -> dict[str, Any]:
    prior = snapshot()
    for _ in range(attempts - 1):
        time.sleep(seconds)
        current = snapshot()
        if canonical(current) == canonical(prior):
            return current
        prior = current
    raise QualificationFailure("live state did not reach a stable pre-run projection")


def wait_for_exact_snapshot(
    expected: dict[str, Any], *, attempts: int = 30, seconds: float = 1,
) -> dict[str, Any]:
    current = snapshot()
    for _ in range(attempts):
        if canonical(current) == canonical(expected):
            return current
        time.sleep(seconds)
        current = snapshot()
    return current


def snapshot_delta(before: dict[str, Any], after: dict[str, Any]) -> str:
    rows = []
    for key in sorted(before):
        if canonical(before[key]) == canonical(after.get(key)):
            continue
        rows.append(
            {
                "section": key,
                "before_sha256": sha(canonical(before[key])),
                "after_sha256": sha(canonical(after.get(key))),
            }
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def container_identity(name: str, expected_image: str) -> dict[str, Any]:
    rows = json.loads(docker("inspect", name).stdout)
    if len(rows) != 1:
        raise QualificationFailure(f"container identity missing: {name}")
    row = rows[0]
    state = row.get("State", {})
    if (
        row.get("Image") != expected_image
        or state.get("Status") != "running"
        or state.get("OOMKilled") is not False
    ):
        raise QualificationFailure(f"container identity drifted: {name}")
    return {
        "image_id": row["Image"],
        "running": True,
        "oom_killed": False,
        "restart_count": row.get("RestartCount"),
    }


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    free_bytes = shutil.disk_usage(REPO).free
    if free_bytes < contract["execution"]["minimum_free_bytes"]:
        raise QualificationFailure("disk safety floor not met")
    if docker("info", "--format", "{{.CgroupDriver}}").stdout.strip() != "cgroupfs":
        raise QualificationFailure("Docker cgroup driver is not cgroupfs")

    source_count = 0
    live_count = 0
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationFailure(f"source lock drifted: {lock['path']}")
        source_count += 1
        if lock.get("container") and lock.get("container_path"):
            if live_file_sha(lock["container"], lock["container_path"]) != lock["sha256"]:
                raise QualificationFailure(
                    f"live source lock drifted: {lock['container_path']}"
                )
            live_count += 1

    identities = {
        name: container_identity(name, value["image_id"])
        for name, value in contract["runtime"]["containers"].items()
    }
    for url in (
        f"{VIOS}/sensor/version",
        f"{RTCV}/stream/get-stream-info",
        f"{ALERT}/health",
        f"{RTVLM}/v1/health/ready",
    ):
        status, _ = request_json(url)
        if status != 200:
            raise QualificationFailure(f"runtime health failed: {url}")

    rows = json.loads(docker("inspect", "vss-alert-bridge").stdout)
    environment = rows[0].get("Config", {}).get("Env", [])
    required_env = {
        "ALERT_VLM_MEDIA_SOURCE_USING_BASE64=true",
        "ALERT_VERIFICATION_MEDIA_MODE=snapshots",
        "VLM_BASE_URL=http://127.0.0.1:8018",
    }
    if not required_env.issubset(set(environment)):
        raise QualificationFailure("Alert Bridge local snapshot transport is not exact")
    return {
        "containers": identities,
        "cgroup_driver": "cgroupfs",
        "free_bytes_before": free_bytes,
        "source_lock_count": source_count,
        "live_source_lock_count": live_count,
    }


SOURCE_FILTER = [
    "sensorId", "timestamp", "end", "id", "Id", "type", "category",
    "objectIds", "objects.id", "objects.type", "objects.confidence",
    "info.objectTimeline", "info.verdict", "info.reasoning",
    "info.verificationResponseCode", "info.verificationResponseStatus",
    "info.snapshotUrls", "info.videoSource", "analyticsModule.description",
]


def elastic_hits(index_pattern: str, sensor_name: str, *, size: int = 1000) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC}/{index_pattern}/_search?allow_no_indices=true&ignore_unavailable=true",
        method="POST",
        body={
            "size": size,
            "_source": SOURCE_FILTER,
            "query": {"term": {"sensorId.keyword": sensor_name}},
        },
    )
    hits = body.get("hits", {}).get("hits") if isinstance(body, dict) else None
    if status != 200 or not isinstance(hits, list):
        raise QualificationFailure(f"Elasticsearch query failed: {index_pattern}")
    return hits


def all_owned_hits(sensor_name: str) -> list[dict[str, Any]]:
    return elastic_hits("mdx-*", sensor_name, size=10000)


def poll_hit(
    index_pattern: str,
    sensor_name: str,
    predicate: Any,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    for attempt in range(contract["execution"]["poll_attempts"]):
        for hit in elastic_hits(index_pattern, sensor_name):
            if predicate(hit):
                return hit, round((time.monotonic() - started) * 1000)
        if attempt + 1 < contract["execution"]["poll_attempts"]:
            time.sleep(contract["execution"]["poll_seconds"])
    raise QualificationFailure(f"timed out waiting for {index_pattern}")


def source(hit: dict[str, Any]) -> dict[str, Any]:
    value = hit.get("_source")
    if not isinstance(value, dict):
        raise QualificationFailure("Elasticsearch hit has no object source")
    return value


def object_ids_from_raw(hit: dict[str, Any]) -> set[str]:
    objects = source(hit).get("objects")
    if not isinstance(objects, list):
        return set()
    return {
        str(item.get("id"))
        for item in objects
        if isinstance(item, dict)
        and str(item.get("type", "")).casefold() == "person"
        and item.get("id") is not None
    }


def add_vios_sensor(name: str) -> str:
    upstream = f"{MEDIA_MTX}/{name}"
    payload = {
        "sensorUrl": upstream,
        "username": "",
        "password": "",
        "name": name,
        "location": "thor-qualification",
        "tags": "thor-qualification",
    }
    status, body = request_json(f"{VIOS}/sensor/add", method="POST", body=payload, timeout=60)
    sensor_id = body.get("sensorId") if isinstance(body, dict) else None
    if status not in (200, 201) or not isinstance(sensor_id, str) or not sensor_id:
        raise QualificationFailure(f"VIOS sensor add failed with HTTP {status}")
    return sensor_id


def wait_for_vios_stream(sensor_id: str, contract: dict[str, Any]) -> str:
    for attempt in range(contract["execution"]["sensor_poll_attempts"]):
        status, streams = request_json(f"{VIOS}/proxy/streams")
        if status == 200 and isinstance(streams, list):
            stream = next(
                (
                    item for item in streams
                    if isinstance(item, dict)
                    and item.get("sensorId") == sensor_id
                    and str(item.get("proxyUrl", "")).startswith("rtsp://")
                ),
                None,
            )
            if stream is not None:
                return str(stream["proxyUrl"])
        if attempt + 1 < contract["execution"]["sensor_poll_attempts"]:
            time.sleep(contract["execution"]["sensor_poll_seconds"])
    raise QualificationFailure("VIOS sensor did not become an online proxied stream")


def rt_cv_payload(sensor_id: str, name: str, camera_url: str, change: str) -> dict[str, Any]:
    return {
        "key": "sensor",
        "value": {
            "camera_id": sensor_id,
            "camera_name": name,
            "camera_url": camera_url,
            "change": change,
            "metadata": {"resolution": "1920x1080", "codec": "h264", "framerate": 10},
        },
        "headers": {
            "source": "thor-qualification",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }


def mutate_rt_cv(sensor_id: str, name: str, camera_url: str, change: str) -> None:
    operation = "add" if change == "camera_add" else "remove"
    status, body = request_json(
        f"{RTCV}/stream/{operation}",
        method="POST",
        body=rt_cv_payload(sensor_id, name, camera_url, change),
        headers={"x-stream-id": sensor_id},
        timeout=60,
    )
    if status != 200:
        raise QualificationFailure(f"RT-CV stream {operation} failed: HTTP {status} {body}")


def timelines(sensor_id: str) -> list[dict[str, str]]:
    encoded = urllib.parse.quote(sensor_id, safe="-_.")
    status, body = request_json(f"{VIOS}/storage/{encoded}/timelines")
    if status == 404 or (status == 200 and body is None):
        return []
    if status != 200 or not isinstance(body, list):
        raise QualificationFailure("VIOS timeline snapshot failed")
    return [item for item in body if isinstance(item, dict)]


def delete_vios_sensor_and_storage(sensor_id: str) -> int:
    encoded = urllib.parse.quote(sensor_id, safe="-_.")
    ranges = timelines(sensor_id)
    status, _ = request_json(f"{VIOS}/sensor/{encoded}", method="DELETE", timeout=60)
    if status not in (200, 404):
        raise QualificationFailure(f"VIOS sensor cleanup failed: HTTP {status}")
    saved = 0
    for item in ranges:
        start = item.get("startTime")
        end = item.get("endTime")
        if not isinstance(start, str) or not isinstance(end, str):
            raise QualificationFailure("VIOS returned an invalid cleanup interval")
        query = urllib.parse.urlencode({"startTime": start, "endTime": end})
        delete_status, body = request_json(
            f"{VIOS}/storage/file/{encoded}?{query}", method="DELETE", timeout=90,
        )
        if delete_status not in (200, 404):
            raise QualificationFailure(f"VIOS storage cleanup failed: HTTP {delete_status}")
        if isinstance(body, dict) and isinstance(body.get("spaceSaved"), (int, float)):
            saved += int(body["spaceSaved"])
    return saved


def delete_owned_elastic(sensor_name: str) -> int:
    deleted = 0
    for hit in all_owned_hits(sensor_name):
        item_source = source(hit)
        if item_source.get("sensorId") != sensor_name:
            raise QualificationFailure("refused to delete a non-owned Elasticsearch document")
        index = urllib.parse.quote(str(hit.get("_index")), safe="-_.")
        document = urllib.parse.quote(str(hit.get("_id")), safe="-_.")
        status, body = request_json(f"{ELASTIC}/{index}/_doc/{document}", method="DELETE")
        if status != 200 or not isinstance(body, dict) or body.get("result") != "deleted":
            raise QualificationFailure("owned Elasticsearch cleanup failed")
        deleted += 1
    if deleted:
        status, _ = request_json(f"{ELASTIC}/_refresh", method="POST")
        if status != 200:
            raise QualificationFailure("Elasticsearch refresh failed")
    return deleted


def delete_owned_temp_files(sensor_name: str) -> int:
    pattern = f"{sensor_name}_*"
    result = subprocess.run(
        [
            "docker", "exec", "vss-vios-streamprocessing", "find", TEMP_ROOT,
            "-maxdepth", "1", "-type", "f", "-name", pattern, "-print0",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    paths = [item for item in result.stdout.split(b"\0") if item]
    expected_prefix = f"{sensor_name}_".encode("utf-8")
    if any(not os.path.basename(item).startswith(expected_prefix) for item in paths):
        raise QualificationFailure("refused to delete a non-owned VIOS temporary file")
    if paths:
        docker(
            "exec", "vss-vios-streamprocessing", "find", TEMP_ROOT,
            "-maxdepth", "1", "-type", "f", "-name", pattern, "-delete",
        )
    return len(paths)


def owned_temp_count(sensor_name: str) -> int:
    result = subprocess.run(
        [
            "docker", "exec", "vss-vios-streamprocessing", "find", TEMP_ROOT,
            "-maxdepth", "1", "-type", "f", "-name", f"{sensor_name}_*", "-print0",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return len([item for item in result.stdout.split(b"\0") if item])


def logs_since(container: str, since: str) -> str:
    result = docker("logs", "--since", since, container, timeout=60)
    return result.stdout + result.stderr


def terminate_publisher(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def execute(contract: dict[str, Any], contract_raw: bytes, run_id: str) -> dict[str, Any]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise QualificationFailure("invalid run ID")
    started = time.monotonic()
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    runtime = verify_runtime(contract)
    fixture = REPO / contract["fixture"]["path"]
    fixture_raw = fixture.read_bytes()
    if sha(fixture_raw) != contract["fixture"]["sha256"] or len(fixture_raw) != contract["fixture"]["bytes"]:
        raise QualificationFailure("fixture identity drifted")

    before = stable_snapshot()
    before_sha = sha(canonical(before))
    suffix = sha(run_id)[:16]
    sensor_name = f"thor-row321-{suffix}"
    if all_owned_hits(sensor_name):
        raise QualificationFailure("owned Elasticsearch namespace is not empty")
    if any(item.get("name") == sensor_name for item in before["active_sensors"]):
        raise QualificationFailure("owned VIOS namespace is not empty")

    publisher: subprocess.Popen[Any] | None = None
    sensor_id = ""
    proxy_url = ""
    rt_cv_registered = False
    deleted_documents = 0
    deleted_temp_files = 0
    space_saved_mb = 0
    primary: BaseException | None = None
    raw_hit: dict[str, Any] | None = None
    candidate_hit: dict[str, Any] | None = None
    final_hit: dict[str, Any] | None = None
    raw_observed_ms = 0
    candidate_observed_ms = 0
    final_observed_ms = 0
    try:
        publisher = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
                "-stream_loop", "-1", "-i", str(fixture), "-an", "-c:v", "copy",
                "-f", "rtsp", "-rtsp_transport", "tcp", f"{MEDIA_MTX}/{sensor_name}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        if publisher.poll() is not None:
            raise QualificationFailure("owned RTSP publisher exited before onboarding")

        sensor_id = add_vios_sensor(sensor_name)
        proxy_url = wait_for_vios_stream(sensor_id, contract)
        if not proxy_url.startswith("rtsp://") or sensor_id not in proxy_url:
            raise QualificationFailure("VIOS did not return the correlated local proxy URL")
        mutate_rt_cv(sensor_id, sensor_name, proxy_url, "camera_add")
        rt_cv_registered = True

        stage_started = time.monotonic()
        raw_hit, _ = poll_hit(
            "mdx-raw-*", sensor_name,
            lambda item: bool(object_ids_from_raw(item)), contract,
        )
        raw_observed_ms = round((time.monotonic() - stage_started) * 1000)
        candidate_hit, _ = poll_hit(
            "mdx-incidents-*", sensor_name,
            lambda item: source(item).get("category") == "FOV Count Violation",
            contract,
        )
        candidate_observed_ms = round((time.monotonic() - stage_started) * 1000)
        candidate = source(candidate_hit)
        candidate_id = candidate_hit.get("_id")
        final_hit, _ = poll_hit(
            "mdx-vlm-incidents-*", sensor_name,
            lambda item: item.get("_id") == candidate_id
            and source(item).get("info", {}).get("verdict") == "confirmed",
            contract,
        )
        final_observed_ms = round((time.monotonic() - stage_started) * 1000)

        final = source(final_hit)
        candidate_objects = {str(value) for value in candidate.get("objectIds", [])}
        correlated_raw = next(
            (
                item for item in elastic_hits("mdx-raw-*", sensor_name, size=1000)
                if object_ids_from_raw(item) & candidate_objects
                and str(candidate.get("timestamp")) <= str(source(item).get("timestamp"))
                <= str(candidate.get("end"))
            ),
            None,
        )
        info = final.get("info") if isinstance(final.get("info"), dict) else None
        if (
            correlated_raw is None
            or not candidate_objects
            or candidate_id != candidate.get("Id")
            or candidate_id != final_hit.get("_id")
            or candidate_id != final.get("Id")
            or candidate.get("sensorId") != sensor_name
            or final.get("sensorId") != sensor_name
            or final.get("timestamp") != candidate.get("timestamp")
            or final.get("end") != candidate.get("end")
            or {str(value) for value in final.get("objectIds", [])} != candidate_objects
            or not isinstance(info, dict)
            or info.get("objectTimeline") != candidate.get("info", {}).get("objectTimeline")
            or str(info.get("verificationResponseCode")) != "200"
            or info.get("verificationResponseStatus") != "OK"
            or info.get("verdict") != "confirmed"
            or not isinstance(info.get("reasoning"), str)
            or not info["reasoning"].strip()
        ):
            raise QualificationFailure("candidate identity or evidence interval was not preserved")

        snapshot_urls = json.loads(info.get("snapshotUrls", "[]"))
        if (
            not isinstance(snapshot_urls, list)
            or len(snapshot_urls) != contract["execution"]["expected_snapshot_count"]
            or any(sensor_name not in str(value) for value in snapshot_urls)
        ):
            raise QualificationFailure("VLM snapshot evidence was not correlated")

        alert_logs = logs_since("vss-alert-bridge", since)
        behavior_logs = logs_since("vss-behavior-analytics-thor-candidates", since)
        rt_cv_logs = logs_since("vss-rtvi-cv", since)
        rt_vlm_logs = logs_since("vss-rtvi-vlm", since)
        request_marker = f"VLM request sent (attempt 1/2, base64=True) [sensor={sensor_name}"
        response_marker = f"VLM response received [sensor={sensor_name}"
        if (
            sensor_name not in rt_cv_logs
            or f"Created 1 Thor candidate incident(s) for sensor {sensor_name}" not in behavior_logs
            or request_marker not in alert_logs
            or response_marker not in alert_logs
            or alert_logs.find(request_marker) >= alert_logs.find(response_marker)
            or "data:image/jpeg;base64," not in rt_vlm_logs
            or 'POST /v1/chat/completions HTTP/1.1' not in rt_vlm_logs
            or "200 OK" not in rt_vlm_logs
        ):
            raise QualificationFailure("ordered local pipeline logs were incomplete")
    except BaseException as exc:
        primary = exc
    finally:
        try:
            if rt_cv_registered:
                mutate_rt_cv(sensor_id, sensor_name, proxy_url, "camera_remove")
        except BaseException as exc:
            if primary is None:
                primary = exc
        terminate_publisher(publisher)
        try:
            if sensor_id:
                space_saved_mb = delete_vios_sensor_and_storage(sensor_id)
        except BaseException as exc:
            if primary is None:
                primary = exc
        try:
            quiet_polls = 0
            for _ in range(60):
                if sensor_id:
                    space_saved_mb += delete_vios_sensor_and_storage(sensor_id)
                deleted_documents += delete_owned_elastic(sensor_name)
                deleted_temp_files += delete_owned_temp_files(sensor_name)
                recording_ranges = timelines(sensor_id) if sensor_id else []
                if (
                    not recording_ranges
                    and not all_owned_hits(sensor_name)
                    and owned_temp_count(sensor_name) == 0
                ):
                    quiet_polls += 1
                else:
                    quiet_polls = 0
                if quiet_polls >= 15:
                    break
                time.sleep(1)
            if quiet_polls < 15:
                raise QualificationFailure("owned asynchronous artifacts did not quiesce")
        except BaseException as exc:
            if primary is None:
                primary = exc

    after = wait_for_exact_snapshot(before)
    after_sha = sha(canonical(after))
    owned_after = all_owned_hits(sensor_name)
    temp_after = owned_temp_count(sensor_name)
    if primary is not None:
        if before_sha != after_sha or owned_after or temp_after:
            raise QualificationFailure(
                f"primary error: {primary}; cleanup delta: {snapshot_delta(before, after)}"
            ) from primary
        if isinstance(primary, QualificationFailure):
            raise primary
        raise QualificationFailure("unexpected qualification failure") from primary
    if before_sha != after_sha or owned_after or temp_after:
        raise QualificationFailure(
            f"exact live state was not restored: {snapshot_delta(before, after)}"
        )
    if publisher is not None and publisher.poll() is None:
        raise QualificationFailure("owned RTSP publisher remains alive")
    duration = time.monotonic() - started
    if duration > contract["execution"]["maximum_duration_seconds"]:
        raise QualificationFailure("qualification exceeded its duration contract")

    assert raw_hit is not None and candidate_hit is not None and final_hit is not None
    candidate = source(candidate_hit)
    final = source(final_hit)
    final_info = final["info"]
    snapshots = json.loads(final_info["snapshotUrls"])
    candidate_id = str(candidate_hit["_id"])
    return {
        "schema_version": 1,
        "status": "passed",
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "contract_sha256": sha(contract_raw),
        "run": {
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "duration_ms": round(duration * 1000),
            "run_id_sha256": sha(run_id),
        },
        "runtime": {
            **runtime,
            "free_bytes_after": shutil.disk_usage(REPO).free,
            "model": contract["runtime"]["model"],
        },
        "pipeline": {
            "cv_raw_observed": True,
            "behavior_candidate_observed": True,
            "vlm_verification_observed": True,
            "observation_order": ["cv_raw", "behavior_candidate", "vlm_verification"],
            "observation_ms": [raw_observed_ms, candidate_observed_ms, final_observed_ms],
            "same_candidate_document_id": True,
            "same_source_id": True,
            "candidate_id_sha256": sha(candidate_id),
            "sensor_identity_preserved": True,
            "sensor_name_sha256": sha(sensor_name),
            "sensor_id_sha256": sha(sensor_id),
            "evidence_interval_preserved": True,
            "evidence_interval_sha256": sha(
                canonical([candidate.get("timestamp"), candidate.get("end")])
            ),
            "object_ids_preserved": True,
            "object_timeline_preserved": True,
            "candidate_category": "FOV Count Violation",
            "final_category": final.get("category"),
            "final_verdict": "confirmed",
            "verification_response_code": 200,
            "verification_response_status": "OK",
            "reasoning_present": True,
        },
        "transport": {
            "fixture_sha256": sha(fixture_raw),
            "fixture_bytes": len(fixture_raw),
            "viOS_proxy_rtsp": True,
            "snapshot_count": len(snapshots),
            "snapshot_urls_correlated": True,
            "alert_bridge_base64_enabled": True,
            "alert_bridge_base64_request_logged": True,
            "rtvlm_data_url_logged": True,
            "local_chat_completion_200": True,
        },
        "cleanup": {
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "exact_live_state_restored": True,
            "owned_elastic_documents_deleted": deleted_documents,
            "owned_elastic_documents_absent": True,
            "owned_temp_files_deleted": deleted_temp_files,
            "owned_temp_files_absent": True,
            "owned_publisher_stopped": True,
            "owned_sensor_absent_from_active_catalog": True,
            "owned_proxy_absent": True,
            "owned_recording_absent": True,
            "rtcv_stream_set_preserved": True,
            "running_container_set_preserved": True,
            "recording_space_saved_mb": space_saved_mb,
        },
        "policy": {
            "agent_generate_request_count": 0,
            "external_network_requests": 0,
            "numeric_local_endpoints_only": True,
            "warehouse_sample_bundle": "excluded",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=HERE / "contract.json")
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.acknowledgement != ACK:
            raise QualificationFailure("authorization acknowledgement mismatch")
        contract_raw = args.contract.read_bytes()
        contract = read_json(args.contract)
        if contract.get("execution", {}).get("acknowledgement") != ACK:
            raise QualificationFailure("contract acknowledgement drifted")
        receipt = execute(contract, contract_raw, args.run_id)
        encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except QualificationFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
