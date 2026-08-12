#!/usr/bin/env python3
"""Qualify Alert Bridge non-blocking multithreaded execution on Thor."""

from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ALERT_BASE = "http://127.0.0.1:19086"
METRICS_URL = "http://127.0.0.1:19087/metrics"
MAIN_ALERT = "http://127.0.0.1:9080"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
FIXTURE_PORT = 38127
ALERT_PORT = 19086
METRICS_PORT = 19087
BURST_COUNT = 6
SLOW_CANDIDATE = 0
ACK = "I_AUTHORIZE_OWNED_ALERT_CONCURRENCY_QUALIFICATION"
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class QualificationFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def ast_sha(source: str) -> str:
    tree = ast.parse(source)
    return sha(ast.dump(tree, include_attributes=False))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_raw(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    timeout: float = 30,
) -> tuple[int, bytes]:
    data = canonical(body) if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationFailure(f"local request failed: {url}") from exc


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    status, raw = request_raw(url, method=method, body=body, timeout=timeout)
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = {"unparsed_body_sha256": sha(raw)}
    return status, parsed


def docker(
    *args: str,
    check: bool = True,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def inspect_container(name: str) -> dict[str, Any]:
    result = docker("inspect", name)
    rows = json.loads(result.stdout)
    if len(rows) != 1:
        raise QualificationFailure(f"container identity missing: {name}")
    return rows[0]


def running_containers() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    result = docker("ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}")
    for line in result.stdout.splitlines():
        if line.strip():
            container_id, name, image = line.split("\t", 2)
            rows.append({"id": container_id, "name": name, "image": image})
    return sorted(rows, key=lambda item: item["name"])


def main_snapshot() -> dict[str, Any]:
    config_status, configs = request_json(f"{MAIN_ALERT}/api/v1/verification/config")
    rules_status, rules = request_json(f"{MAIN_ALERT}/api/v1/realtime")
    streams_status, streams = request_json(f"{RTVLM}/v1/streams/get-stream-info")
    if (config_status, rules_status, streams_status) != (200, 200, 200):
        raise QualificationFailure("main runtime snapshot failed")
    return {
        "alert_configs": configs,
        "realtime_rules": rules,
        "rtvlm_streams": streams,
        "running_containers": running_containers(),
    }


def live_file(container: str, path: str) -> str:
    result = docker(
        "exec", container, "/usr/local/bin/python", "-c",
        "import sys;sys.stdout.write(open(sys.argv[1],encoding='utf-8').read())",
        path,
    )
    return result.stdout


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    free_bytes = shutil.disk_usage(REPO).free
    if free_bytes < contract["execution"]["minimum_free_bytes"]:
        raise QualificationFailure("disk safety floor not met")
    if any(not port_available(port) for port in (ALERT_PORT, METRICS_PORT, FIXTURE_PORT)):
        raise QualificationFailure("an owned loopback port is already in use")

    exact_live = 0
    semantic_live = 0
    for lock in contract["source_locks"]:
        source = REPO / lock["path"]
        if not source.is_file() or source.is_symlink() or file_sha(source) != lock["sha256"]:
            raise QualificationFailure(f"source lock drifted: {lock['path']}")
        if lock.get("live_path"):
            live = live_file(lock["container"], lock["live_path"])
            if lock.get("live_sha256"):
                if sha(live) != lock["live_sha256"]:
                    raise QualificationFailure(f"exact live source drifted: {lock['live_path']}")
                exact_live += 1
            if lock.get("semantic_ast_sha256"):
                if ast_sha(source.read_text(encoding="utf-8")) != lock["semantic_ast_sha256"]:
                    raise QualificationFailure(f"host AST lock drifted: {lock['path']}")
                if ast_sha(live) != lock["semantic_ast_sha256"]:
                    raise QualificationFailure(f"live AST drifted: {lock['live_path']}")
                semantic_live += 1

    identities: dict[str, Any] = {}
    for name, expected in contract["runtime"]["containers"].items():
        row = inspect_container(name)
        state = row.get("State", {})
        if (
            row.get("Image") != expected["image_id"]
            or state.get("Status") != "running"
            or state.get("OOMKilled") is not False
        ):
            raise QualificationFailure(f"runtime identity drifted: {name}")
        identities[name] = {
            "image_id": row["Image"],
            "running": True,
            "oom_killed": False,
            "restart_count": row.get("RestartCount", 0),
        }
    for url in (
        f"{MAIN_ALERT}/health",
        f"{RTVLM}/v1/health/ready",
        f"{ELASTIC}/_cluster/health",
    ):
        status, _ = request_json(url)
        if status != 200:
            raise QualificationFailure(f"runtime health failed: {url}")
    return {
        "free_bytes_before": free_bytes,
        "exact_live_source_locks": exact_live,
        "semantic_live_source_locks": semantic_live,
        "containers": identities,
    }


class LocalFixture:
    def __init__(self, video: Path, slow_seconds: float, fast_seconds: float) -> None:
        self.video = video
        self.slow_seconds = slow_seconds
        self.fast_seconds = fast_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        self.vst_requests: dict[str, int] = {}
        self.media_requests: dict[str, int] = {}
        self.nim_calls: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _send_json(self, status: int, value: Any) -> None:
                raw = canonical(value)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def do_HEAD(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path.startswith("/media/") and parsed.path.endswith(".mp4"):
                    raw = owner.video.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    return
                self.send_error(404)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/vst/api/v1/live/streams":
                    self._send_json(200, [])
                    return
                storage_prefix = "/vst/api/v1/storage/file/"
                if parsed.path.startswith(storage_prefix) and parsed.path.endswith("/url"):
                    sensor = urllib.parse.unquote(
                        parsed.path[len(storage_prefix):-len("/url")]
                    )
                    with owner._lock:
                        owner.vst_requests[sensor] = owner.vst_requests.get(sensor, 0) + 1
                    media = urllib.parse.quote(sensor, safe="")
                    self._send_json(200, {
                        "videoUrl": f"http://127.0.0.1:{FIXTURE_PORT}/media/{media}.mp4",
                        "streamId": sensor,
                    })
                    return
                if parsed.path.startswith("/media/") and parsed.path.endswith(".mp4"):
                    sensor = urllib.parse.unquote(parsed.path[len("/media/"):-len(".mp4")])
                    raw = owner.video.read_bytes()
                    with owner._lock:
                        owner.media_requests[sensor] = owner.media_requests.get(sensor, 0) + 1
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if urllib.parse.urlsplit(self.path).path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > 32 * 1024 * 1024:
                    self._send_json(413, {"error": "bounded local request required"})
                    return
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid JSON"})
                    return
                match = re.search(r"candidate=(\d+)", json.dumps(body, separators=(",", ":")))
                if match is None:
                    self._send_json(422, {"error": "candidate marker absent"})
                    return
                candidate = int(match.group(1))
                if candidate < 0 or candidate >= BURST_COUNT:
                    self._send_json(422, {"error": "candidate marker out of range"})
                    return
                delay = owner.slow_seconds if candidate == SLOW_CANDIDATE else owner.fast_seconds
                started_monotonic = time.monotonic()
                started_at = utc_now()
                with owner._lock:
                    owner._active += 1
                    owner.max_active = max(owner.max_active, owner._active)
                try:
                    time.sleep(delay)
                    verdict = "YES" if candidate % 2 == 0 else "NO"
                    content = json.dumps({
                        "prediction_answer": verdict,
                        "reasoning": f"candidate {candidate} deterministic local fixture response",
                    }, separators=(",", ":"))
                    response = {
                        "id": f"thor-row327-{candidate}",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "thor-row327-local-fixture",
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                    self._send_json(200, response)
                finally:
                    completed_at = utc_now()
                    duration = time.monotonic() - started_monotonic
                    with owner._lock:
                        owner._active -= 1
                        owner.nim_calls.append({
                            "candidate": candidate,
                            "started_at": started_at,
                            "completed_at": completed_at,
                            "duration_seconds": round(duration, 3),
                            "request_sha256": sha(raw),
                        })

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self.server = Server(("127.0.0.1", FIXTURE_PORT), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise QualificationFailure("local fixture server did not stop")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_active": self.max_active,
                "vst_requests": dict(self.vst_requests),
                "media_requests": dict(self.media_requests),
                "nim_calls": [dict(item) for item in self.nim_calls],
            }


def live_runtime_config() -> dict[str, Any]:
    result = docker(
        "exec", "vss-alert-bridge", "/usr/local/bin/python", "-c",
        "import sys;sys.stdout.buffer.write(open('/app/runtime/config.yml','rb').read())",
    )
    value = yaml.safe_load(result.stdout)
    if not isinstance(value, dict):
        raise QualificationFailure("live Alert config is not an object")
    return value


def owned_config(base: dict[str, Any], prefix: str, incident_topic: str, alert_topic: str) -> dict[str, Any]:
    value = copy.deepcopy(base)
    value["vst_config"] = {
        "base_url": f"http://127.0.0.1:{FIXTURE_PORT}",
        "sensor_list_endpoint": "/vst/api/v1/live/streams",
        "segment_anchor": "end",
        "segment_duration_seconds": 1,
        "add_overlay": False,
        "url_retention_minutes": 5,
        "timeout": 5,
        "storage": {
            "base_url": f"http://127.0.0.1:{FIXTURE_PORT}",
            "media_file_path_by_id_endpoint": "/api/v1/storage/file/path",
        },
    }
    kafka = value.setdefault("kafka", {})
    kafka.update({
        "bootstrap_servers": "127.0.0.1:9092",
        "group_id": f"{prefix}legacy",
        "anomalyTopic": incident_topic,
        "enhanced_anomaly_topic": f"{prefix}enhanced",
        "incidents_topic": f"{prefix}sink-incidents",
        "max_poll_records": 1,
        "auto_offset_reset": "earliest",
        "enable_auto_commit": False,
        "max_poll_interval_ms": 300000,
        "poll_timeout": 100,
        "message_type": "Incident",
        "session_timeout_ms": 10000,
        "heartbeat_interval_ms": 3000,
    })
    bridge = value.setdefault("event_bridge", {})
    bridge["sourceType"] = "kafka"
    bridge["sinkType"] = "kafka"
    bridge["kafka_source"] = {
        "group_id": f"{prefix}source",
        "topics": {"incident": incident_topic, "alert": alert_topic},
    }
    bridge["kafka_sink"] = {
        "topics": {
            "enhanced_anomaly": f"{prefix}enhanced",
            "incidents": f"{prefix}sink-incidents",
        },
    }
    redis_source = bridge.setdefault("redis_source", {})
    redis_source["dedup_ttl_seconds"] = 2
    redis_source["protect_confirmed_verdicts"] = {"enabled": False, "ttl_seconds": 2}
    redis_source["end_time_delta_filter"] = {
        "enabled": False, "threshold_seconds": 0, "ttl_seconds": 2,
    }

    value["vlm"] = {
        "base_url": f"http://127.0.0.1:{FIXTURE_PORT}/v1",
        "model": "thor-row327-local-fixture",
        "max_tokens": 64,
        "temperature": 0.0,
        "request_timeout": 15,
        "num_frames": 1,
        "enable_sampling": False,
        "media_mode": "video",
        "response_format": "json",
        "json_parser": {
            "verdict_field": "prediction_answer",
            "reasoning_fields": ["reasoning"],
        },
    }
    value["elastic"] = {"enabled": True, "hosts": ["http://127.0.0.1:9200"]}
    value["persistence"] = {
        "enabled": True,
        "backend": "elasticsearch",
        "index_prefix": f"{prefix}configs-",
    }
    value["vlm_enhanced_sink"] = {
        "incident": {
            "type": "elastic",
            "elastic": {"index": f"{prefix}vlm-incidents"},
        },
        "alert": {
            "type": "elastic",
            "elastic": {"index": f"{prefix}vlm-alerts"},
        },
    }
    value["prompt"] = {"prefer_payload_prompt": False, "override_prompts_on_start": False}
    agent = value.setdefault("alert_agent", {})
    agent.update({
        "num_workers": 1,
        "chunk_size": 1,
        "include_latency_info": True,
        "vst_pass_through_mode": False,
        "async_dispatch_workers": 3,
        "async_dispatch_max_in_flight": BURST_COUNT,
        "always_on": False,
        "enrichment": {"enabled": False},
        "metrics": {"per_sensor_labels": True},
        "async_io": {
            "enabled": True,
            "vst_enabled": False,
            "elastic_enabled": False,
            "redis_enabled": False,
            "external_timeout_seconds": 15,
            "sink_warn_in_flight": BURST_COUNT,
        },
        "url_transform": {"enabled": False},
    })
    value.setdefault("vss_agent", {})["enabled"] = False
    value.setdefault("websocket", {})["enabled"] = False
    value.setdefault("webhook", {}).setdefault("openclaw", {})["enabled"] = False
    value["alert_type_config_file"] = "/app/alert_type_config.json"
    value["logging"] = {
        "level": "DEBUG",
        "format": "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s",
        "third_party_level": "WARNING",
        "truncate_base64": True,
    }
    return value


def write_config(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    path.chmod(0o444)


def start_owned_container(name: str, config_path: Path, image: str) -> None:
    if docker("inspect", name, check=False).returncode == 0:
        raise QualificationFailure(f"owned container already exists: {name}")
    docker(
        "run", "--detach", "--name", name,
        "--network", "host", "--no-healthcheck", "--read-only",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=192m",
        "--env", f"FASTAPI_PORT={ALERT_PORT}",
        "--env", "PROMETHEUS_METRICS_ENABLED=true",
        "--env", f"PROMETHEUS_PORT={METRICS_PORT}",
        "--env", "PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-row327",
        "--env", "VLM_WARMUP_ENABLED=false",
        "--env", "ALERT_VLM_MEDIA_SOURCE_USING_BASE64=true",
        "--env", "ALERT_AGENT_CONFIG_DIR=/app",
        "--mount", f"type=bind,src={config_path},dst=/app/thor-row327-config.yml,readonly",
        "--entrypoint", "/usr/local/bin/python",
        image,
        "/app/enhance_alert_with_vlm.py", "--config", "/app/thor-row327-config.yml",
    )


def wait_owned_ready(name: str, attempts: int) -> None:
    for _ in range(attempts):
        row = inspect_container(name)
        if row.get("State", {}).get("Status") != "running":
            log_result = docker("logs", name, check=False)
            logs = log_result.stdout + log_result.stderr
            raise QualificationFailure(f"owned Alert container exited: {sha(logs)}")
        try:
            health_status, _ = request_json(f"{ALERT_BASE}/health", timeout=2)
            metrics_status, _ = request_raw(METRICS_URL, timeout=2)
        except QualificationFailure:
            health_status, metrics_status = 0, 0
        log_result = docker("logs", name, check=False)
        logs = log_result.stdout + log_result.stderr
        if (
            health_status == 200
            and metrics_status == 200
            and "Starting anomaly processing loop" in logs
            and "Async message dispatch enabled with 3 workers" in logs
        ):
            return
        time.sleep(1)
    raise QualificationFailure("owned Alert readiness timeout")


def stop_owned_container(name: str) -> bool:
    if docker("inspect", name, check=False).returncode != 0:
        return False
    docker("rm", "--force", name)
    return True


def kafka_admin():
    from confluent_kafka.admin import AdminClient
    return AdminClient({"bootstrap.servers": "127.0.0.1:9092"})


def kafka_topics() -> set[str]:
    metadata = kafka_admin().list_topics(timeout=10)
    return set(metadata.topics)


def create_topics(names: list[str]) -> None:
    from confluent_kafka.admin import NewTopic
    existing = kafka_topics()
    if any(name in existing for name in names):
        raise QualificationFailure("owned Kafka topic already exists")
    admin = kafka_admin()
    futures = admin.create_topics(
        [NewTopic(name, num_partitions=1, replication_factor=1) for name in names],
        operation_timeout=10,
    )
    for name, future in futures.items():
        try:
            future.result()
        except Exception as exc:
            raise QualificationFailure(
                f"Kafka topic creation failed: {name}: {type(exc).__name__}: {exc}"
            ) from exc


def delete_topics(names: list[str]) -> None:
    existing = kafka_topics()
    targets = [name for name in names if name in existing]
    if targets:
        admin = kafka_admin()
        futures = admin.delete_topics(targets, operation_timeout=10)
        for future in futures.values():
            try:
                future.result()
            except Exception:
                pass
    for _ in range(30):
        if all(name not in kafka_topics() for name in names):
            return
        time.sleep(1)
    raise QualificationFailure("owned Kafka topic cleanup timed out")


def delete_consumer_group(group: str) -> None:
    admin = kafka_admin()
    try:
        futures = admin.delete_consumer_groups([group], request_timeout=10)
        for future in futures.values():
            try:
                future.result()
            except Exception:
                pass
    except (AttributeError, TypeError):
        result = docker(
            "exec", "kafka", "kafka-consumer-groups",
            "--bootstrap-server", "127.0.0.1:9092",
            "--delete", "--group", group,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise QualificationFailure("owned Kafka consumer group cleanup failed")


def publish_incident(topic: str, payload: dict[str, Any]) -> None:
    alert_root = REPO / "services/alert"
    sys.path.insert(0, str(alert_root))
    try:
        from confluent_kafka import Producer
        from google.protobuf import json_format
        from mdx.anomaly.protobuf import Incident as NvIncident
        message = NvIncident()
        json_format.ParseDict(payload, message, ignore_unknown_fields=True)
        errors: list[str] = []

        def delivered(error: Any, _message: Any) -> None:
            if error is not None:
                errors.append(str(error))

        producer = Producer({"bootstrap.servers": "127.0.0.1:9092"})
        producer.produce(
            topic,
            message.SerializeToString(),
            key=str(payload["id"]).encode("utf-8"),
            callback=delivered,
        )
        outstanding = producer.flush(15)
        if outstanding or errors:
            raise QualificationFailure("Kafka incident delivery was not acknowledged")
    finally:
        if sys.path and sys.path[0] == str(alert_root):
            sys.path.pop(0)


def incident_hits(index_pattern: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(index_pattern, safe="-*_.,")
    status, body = request_json(
        f"{ELASTIC}/{encoded}/_search?allow_no_indices=true&ignore_unavailable=true",
        method="POST",
        body={"size": 1000, "query": {"match_all": {}}},
    )
    # A uniquely named result index is created asynchronously by the sink.
    # Elasticsearch can report the missing/initializing index as a transient
    # HTTP error during the first bounded polls. Treat only retryable statuses
    # as an empty observation; poll_outputs still fails closed at its deadline.
    if status in {404, 408, 425, 429, 500, 502, 503, 504}:
        return []
    hits = body.get("hits", {}).get("hits") if isinstance(body, dict) else None
    if status != 200 or not isinstance(hits, list):
        raise QualificationFailure(f"owned Elasticsearch query failed: status={status}")
    return hits


def owned_indices(prefix: str) -> list[str]:
    pattern = urllib.parse.quote(f"{prefix}*", safe="-_*.")
    status, body = request_json(f"{ELASTIC}/_cat/indices/{pattern}?format=json&h=index")
    if status == 404:
        return []
    if status != 200 or not isinstance(body, list):
        raise QualificationFailure("owned index inventory failed")
    names = sorted(
        str(item.get("index")) for item in body if isinstance(item, dict) and item.get("index")
    )
    if any(not name.startswith(prefix) for name in names):
        raise QualificationFailure("owned index inventory escaped prefix")
    return names


def delete_owned_indices(prefix: str) -> int:
    names = owned_indices(prefix)
    if not names:
        return 0
    encoded = ",".join(urllib.parse.quote(name, safe="-_.") for name in names)
    status, body = request_json(f"{ELASTIC}/{encoded}", method="DELETE")
    if status != 200 or body.get("acknowledged") is not True:
        raise QualificationFailure("owned Elasticsearch cleanup failed")
    return len(names)


def redis_exists(keys: list[str]) -> list[str]:
    present: list[str] = []
    for key in keys:
        result = docker("exec", "redis", "redis-cli", "--raw", "EXISTS", key)
        if result.stdout.strip() == "1":
            present.append(key)
    return present


def delete_redis_keys(keys: list[str]) -> int:
    deleted = 0
    for key in keys:
        result = docker("exec", "redis", "redis-cli", "--raw", "DEL", key)
        try:
            deleted += int(result.stdout.strip())
        except ValueError as exc:
            raise QualificationFailure("owned Redis cleanup returned invalid count") from exc
    return deleted


def metric_samples(text: str, name: str) -> list[tuple[dict[str, str], float]]:
    from prometheus_client.parser import text_string_to_metric_families
    rows: list[tuple[dict[str, str], float]] = []
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name:
                rows.append((dict(sample.labels), float(sample.value)))
    return rows


def metric_value(text: str, name: str, labels: dict[str, str]) -> float:
    matches = [
        value for sample_labels, value in metric_samples(text, name)
        if all(sample_labels.get(key) == expected for key, expected in labels.items())
    ]
    if len(matches) != 1:
        raise QualificationFailure(f"metric series missing or ambiguous: {name} {labels}")
    return matches[0]


def metric_sum_or_zero(text: str, name: str, labels: dict[str, str]) -> float:
    """Sum matching samples, treating an uninstantiated counter as zero.

    Alert Bridge uses Prometheus multiprocess collection. Labelled counters
    that no worker increments are omitted completely from that scrape, while
    a used counter can produce one or more matching worker samples. Source
    locks prove the counter and both dispatch fallback increments are wired;
    summing exported matches preserves positive evidence and makes the absent
    representation mean the only value it can represent here: zero.
    """
    matches = [
        value for sample_labels, value in metric_samples(text, name)
        if all(sample_labels.get(key) == expected for key, expected in labels.items())
    ]
    return sum(matches)


def poll_outputs(index_pattern: str, count: int, attempts: int, interval: float) -> list[dict[str, Any]]:
    for _ in range(attempts):
        hits = incident_hits(index_pattern)
        if len(hits) >= count:
            return hits
        time.sleep(interval)
    raise QualificationFailure("owned Alert outputs did not reach terminal count")


def delete_configs(categories: list[str]) -> int:
    deleted = 0
    for category in categories:
        encoded = urllib.parse.quote(category, safe="")
        try:
            status, body = request_json(
                f"{ALERT_BASE}/api/v1/verification/config/{encoded}",
                method="DELETE",
                timeout=5,
            )
        except QualificationFailure:
            continue
        if status == 200 and body.get("status") == "success":
            deleted += 1
    return deleted


def execute(contract: dict[str, Any], contract_raw: bytes, run_id: str) -> dict[str, Any]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise QualificationFailure("invalid run ID")
    started = time.monotonic()
    runtime = verify_runtime(contract)
    fixture_path = REPO / contract["fixture"]["path"]
    if (
        not fixture_path.is_file()
        or fixture_path.stat().st_size != contract["fixture"]["bytes"]
        or file_sha(fixture_path) != contract["fixture"]["sha256"]
    ):
        raise QualificationFailure("fixture identity drifted")

    before = main_snapshot()
    before_digest = sha(canonical(before))
    suffix = sha(run_id)[:16]
    prefix = f"thor-row327-{suffix}-"
    container = f"thor-row327-{suffix}"
    incident_topic = f"{prefix}incidents"
    alert_topic = f"{prefix}alerts"
    group = f"{prefix}source"
    topics = [incident_topic, alert_topic]
    categories = [f"thor_row327_{suffix}_{i}" for i in range(BURST_COUNT)]
    sensors = [f"thor-row327-sensor-{suffix}-{i}" for i in range(BURST_COUNT)]
    redis_keys = [f"alert_config:{category}" for category in categories]
    if owned_indices(prefix) or redis_exists(redis_keys) or any(name in kafka_topics() for name in topics):
        raise QualificationFailure("owned namespace is not empty")

    fixture = LocalFixture(
        fixture_path,
        slow_seconds=contract["execution"]["slow_vlm_seconds"],
        fast_seconds=contract["execution"]["fast_vlm_seconds"],
    )
    image = contract["runtime"]["containers"]["vss-alert-bridge"]["image_name"]
    config = owned_config(live_runtime_config(), prefix, incident_topic, alert_topic)
    config_projection = {
        "num_workers": config["alert_agent"]["num_workers"],
        "async_io_enabled": config["alert_agent"]["async_io"]["enabled"],
        "dispatch_workers": config["alert_agent"]["async_dispatch_workers"],
        "max_in_flight": config["alert_agent"]["async_dispatch_max_in_flight"],
        "per_sensor_metrics": config["alert_agent"]["metrics"]["per_sensor_labels"],
        "vlm_base_url_loopback": config["vlm"]["base_url"].startswith("http://127.0.0.1:"),
        "vlm_response_format": config["vlm"]["response_format"],
        "source_type": config["event_bridge"]["sourceType"],
        "sink_type": config["vlm_enhanced_sink"]["incident"]["type"],
    }
    fixture_started = False
    container_started = False
    topics_attempted = False
    created_categories: list[str] = []
    logs = ""
    outputs: list[dict[str, Any]] = []
    metrics_text = ""
    topic_delete_count = 0
    config_api_deleted = 0
    redis_deleted = 0
    indices_deleted = 0
    container_removed = False
    primary: BaseException | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="thor-row327-") as temp_dir:
            temp_root = Path(temp_dir)
            temp_root.chmod(0o755)
            config_path = temp_root / "config.yml"
            write_config(config_path, config)
            fixture.start()
            fixture_started = True
            topics_attempted = True
            create_topics(topics)
            start_owned_container(container, config_path, image)
            container_started = True
            wait_owned_ready(container, contract["execution"]["startup_attempts"])

            for i, category in enumerate(categories):
                expected = "YES" if i % 2 == 0 else "NO"
                body = {
                    "alert_type": category,
                    "prompt": (
                        f"Thor local concurrency qualification candidate={i}. "
                        f"Return JSON prediction_answer={expected} and a concise reasoning field."
                    ),
                    "system_prompt": "Return only one JSON object with prediction_answer and reasoning.",
                    "output_category": f"Thor Row327 Output {suffix} {i}",
                    "vlm_params": {
                        "model": "thor-row327-local-fixture",
                        "media_mode": "video",
                        "response_format": "json",
                        "num_frames": 1,
                        "max_tokens": 64,
                        "temperature": 0.0,
                        "request_timeout": 15,
                        "max_retries": 0,
                    },
                }
                status, response = request_json(
                    f"{ALERT_BASE}/api/v1/verification/config", method="POST", body=body,
                )
                if status != 201 or response.get("alert_type") != category:
                    raise QualificationFailure(f"candidate config creation failed: {i}")
                created_categories.append(category)
                encoded = urllib.parse.quote(category, safe="")
                read_status, readback = request_json(
                    f"{ALERT_BASE}/api/v1/verification/config/{encoded}"
                )
                if (
                    read_status != 200
                    or readback.get("prompt") != body["prompt"]
                    or readback.get("output_category") != body["output_category"]
                ):
                    raise QualificationFailure(f"candidate config readback failed: {i}")

            time.sleep(1)
            event_base = datetime.now(timezone.utc) - timedelta(seconds=4)
            produced_started = time.monotonic()
            for i, (category, sensor) in enumerate(zip(categories, sensors)):
                timestamp = (event_base + timedelta(milliseconds=i * 5)).isoformat().replace("+00:00", "Z")
                end = (event_base + timedelta(seconds=1, milliseconds=i * 5)).isoformat().replace("+00:00", "Z")
                publish_incident(incident_topic, {
                    "id": f"thor-row327-event-{suffix}-{i}",
                    "sensorId": sensor,
                    "timestamp": timestamp,
                    "end": end,
                    "objectIds": [f"candidate-object-{i}"],
                    "place": {
                        "name": f"Thor Row327 Candidate {i}",
                        "id": f"place-{i}", "type": "qualification", "info": {},
                    },
                    "analyticsModule": {
                        "id": "Thor Row327",
                        "description": f"Candidate {i}",
                        "info": {}, "source": "local-fixture", "version": "1",
                    },
                    "category": category,
                    "isAnomaly": True,
                    "info": {"qual_candidate": str(i), "primaryObjectId": f"candidate-object-{i}"},
                    "frameIds": [],
                    "embeddings": [],
                })
            produce_duration = time.monotonic() - produced_started

            outputs = poll_outputs(
                f"{prefix}vlm-incidents-*",
                BURST_COUNT,
                contract["execution"]["terminal_poll_attempts"],
                contract["execution"]["terminal_poll_seconds"],
            )
            if len(outputs) != BURST_COUNT:
                raise QualificationFailure("unexpected owned output count")

            status, metrics_raw = request_raw(METRICS_URL)
            if status != 200:
                raise QualificationFailure("metrics scrape failed")
            metrics_text = metrics_raw.decode("utf-8")
            logs_result = docker("logs", container)
            logs = logs_result.stdout + logs_result.stderr
    except BaseException as exc:
        primary = exc
    finally:
        if container_started:
            config_api_deleted = delete_configs(created_categories)
            try:
                logs_result = docker("logs", container, check=False)
                logs = logs_result.stdout + logs_result.stderr
            except Exception:
                pass
            try:
                container_removed = stop_owned_container(container)
            except BaseException as exc:
                if primary is None:
                    primary = exc
        if fixture_started:
            try:
                fixture.stop()
            except BaseException as exc:
                if primary is None:
                    primary = exc
        try:
            redis_deleted = delete_redis_keys(redis_keys)
        except BaseException as exc:
            if primary is None:
                primary = exc
        try:
            indices_deleted = delete_owned_indices(prefix)
        except BaseException as exc:
            if primary is None:
                primary = exc
        if topics_attempted:
            try:
                delete_consumer_group(group)
                delete_topics(topics)
                topic_delete_count = len(topics)
            except BaseException as exc:
                if primary is None:
                    primary = exc

    after = main_snapshot()
    after_digest = sha(canonical(after))
    cleanup = {
        "before_sha256": before_digest,
        "after_sha256": after_digest,
        "exact_main_runtime_restored": before_digest == after_digest,
        "running_container_set_preserved": before["running_containers"] == after["running_containers"],
        "owned_container_absent": docker("inspect", container, check=False).returncode != 0,
        "owned_indices_absent": not owned_indices(prefix),
        "owned_redis_keys_absent": not redis_exists(redis_keys),
        "owned_kafka_topics_absent": all(name not in kafka_topics() for name in topics),
        "fixture_port_closed": port_available(FIXTURE_PORT),
        "api_port_closed": port_available(ALERT_PORT),
        "metrics_port_closed": port_available(METRICS_PORT),
        "api_configs_deleted": config_api_deleted,
        "redis_keys_deleted_by_fallback": redis_deleted,
        "indices_deleted": indices_deleted,
        "topics_deleted": topic_delete_count,
    }
    if primary is not None:
        raise primary
    if not all(
        cleanup[key] for key in (
            "exact_main_runtime_restored",
            "running_container_set_preserved",
            "owned_container_absent",
            "owned_indices_absent",
            "owned_redis_keys_absent",
            "owned_kafka_topics_absent",
            "fixture_port_closed",
            "api_port_closed",
            "metrics_port_closed",
        )
    ):
        raise QualificationFailure("exact cleanup invariant failed")

    fixture_state = fixture.snapshot()
    calls = sorted(fixture_state["nim_calls"], key=lambda item: item["candidate"])
    if len(calls) != BURST_COUNT or {item["candidate"] for item in calls} != set(range(BURST_COUNT)):
        counts = {
            str(candidate): sum(item["candidate"] == candidate for item in calls)
            for candidate in range(BURST_COUNT)
        }
        output_summary = sorted((
            {
                "sensor": str((hit.get("_source") or {}).get("sensorId", "")),
                "status": str(((hit.get("_source") or {}).get("info") or {}).get("verificationResponseStatus", "")),
                "verdict": str(((hit.get("_source") or {}).get("info") or {}).get("verdict", "")),
                "error_source": str(((hit.get("_source") or {}).get("info") or {}).get("errorSource", "")),
            }
            for hit in outputs
        ), key=lambda item: item["sensor"])
        diagnostic_lines = [
            line for line in logs.splitlines()
            if (
                sensors[1] in line
                or "Unexpected error downloading media" in line
                or "VLM validation/processing error" in line
            )
        ][-20:]
        raise QualificationFailure(
            "local VLM call identity was not one-per-candidate: "
            f"counts={counts} total={len(calls)} "
            f"vst={fixture_state['vst_requests']} media={fixture_state['media_requests']} "
            f"outputs={output_summary} diagnostics={diagnostic_lines}"
        )
    slow_call = next(item for item in calls if item["candidate"] == SLOW_CANDIDATE)
    slow_completed = datetime.fromisoformat(slow_call["completed_at"].replace("Z", "+00:00"))
    completion_order = [
        item["candidate"] for item in sorted(calls, key=lambda item: item["completed_at"])
    ]
    fast_before_slow = [
        item["candidate"] for item in calls
        if item["candidate"] != SLOW_CANDIDATE
        and datetime.fromisoformat(item["completed_at"].replace("Z", "+00:00")) < slow_completed
    ]
    slow_response_marker = f"VLM response received [sensor={sensors[SLOW_CANDIDATE]}"
    slow_response_position = logs.find(slow_response_marker)
    if slow_response_position < 0:
        raise QualificationFailure("slow candidate response log was not observed")
    queued_before_slow = logs[:slow_response_position].count("Message queued for async dispatch")
    all_queue_events = logs.count("Message queued for async dispatch")
    dispatch_threads = sorted(set(re.findall(
        r" - (ab-vlm-dispatch_\d+) - .*VLM request sent", logs,
    )))
    if (
        fixture_state["max_active"] < contract["acceptance"]["minimum_parallel_vlm_calls"]
        or len(fast_before_slow) != BURST_COUNT - 1
        or queued_before_slow < BURST_COUNT
        or all_queue_events != BURST_COUNT
        or len(dispatch_threads) < contract["acceptance"]["minimum_dispatch_threads"]
        or "falling back to inline" in logs
        or "Dispatched message processing failed" in logs
    ):
        raise QualificationFailure("non-blocking concurrency oracle failed")

    by_sensor: dict[str, dict[str, Any]] = {}
    for hit in outputs:
        source = hit.get("_source")
        if not isinstance(source, dict) or not isinstance(source.get("sensorId"), str):
            raise QualificationFailure("owned output schema invalid")
        by_sensor[source["sensorId"]] = source
    candidate_receipts: list[dict[str, Any]] = []
    for i, (category, sensor) in enumerate(zip(categories, sensors)):
        source = by_sensor.get(sensor)
        if not isinstance(source, dict):
            raise QualificationFailure(f"candidate output missing: {i}")
        info = source.get("info")
        if not isinstance(info, dict):
            raise QualificationFailure(f"candidate info missing: {i}")
        expected_verdict = "confirmed" if i % 2 == 0 else "rejected"
        expected_category = f"Thor Row327 Output {suffix} {i}"
        expected_video = f"http://127.0.0.1:{FIXTURE_PORT}/media/{urllib.parse.quote(sensor, safe='')}.mp4"
        try:
            latency = json.loads(info.get("latency"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise QualificationFailure(f"candidate latency invalid: {i}") from exc
        if (
            source.get("category") != expected_category
            or info.get("qual_candidate") != str(i)
            or info.get("primaryObjectId") != f"candidate-object-{i}"
            or info.get("videoSource") != expected_video
            or info.get("verdict") != expected_verdict
            or info.get("reasoning") != f"candidate {i} deterministic local fixture response"
            or str(info.get("verificationResponseCode")) != "200"
            or info.get("verificationResponseStatus") != "OK"
            or latency.get("vlmRequest", {}).get("success") is not True
            or fixture_state["vst_requests"].get(sensor) != 1
            or fixture_state["media_requests"].get(sensor, 0) < 2
        ):
            raise QualificationFailure(f"candidate correlation/schema failed: {i}")

        event_metric = metric_value(
            metrics_text,
            "alert_bridge_events_by_sensor_total",
            {"sensorId": sensor, "verdict": expected_verdict},
        )
        after_dedup_metric = metric_value(
            metrics_text,
            "alert_bridge_events_after_dedup_by_sensor_total",
            {"sensorId": sensor},
        )
        terminal_histograms = {
            "worker_queue_wait": metric_value(
                metrics_text,
                "alert_bridge_worker_queue_wait_duration_by_sensor_seconds_count",
                {"sensorId": sensor},
            ),
            "vlm_duration": metric_value(
                metrics_text,
                "alert_bridge_vlm_duration_by_sensor_seconds_count",
                {"sensorId": sensor},
            ),
            "worker_processing": metric_value(
                metrics_text,
                "alert_bridge_worker_processing_by_sensor_seconds_count",
                {"sensorId": sensor},
            ),
        }
        if (
            event_metric != 1.0
            or after_dedup_metric != 1.0
            or any(value != 1.0 for value in terminal_histograms.values())
        ):
            raise QualificationFailure(f"candidate terminal metrics failed: {i}")
        candidate_receipts.append({
            "candidate": i,
            "sensor_id": sensor,
            "input_category": category,
            "output_category": expected_category,
            "verdict": expected_verdict,
            "media_correlated": True,
            "parser_schema_conformant": True,
            "latency_terminal": True,
            "terminal_metric_counts": terminal_histograms,
            "event_metric_count": event_metric,
            "after_dedup_metric_count": after_dedup_metric,
        })

    fallback = metric_sum_or_zero(
        metrics_text,
        "alert_bridge_async_external_io_fallback_total",
        {"operation": "dispatch_message", "reason": "executor_unavailable"},
    ) + metric_sum_or_zero(
        metrics_text,
        "alert_bridge_async_external_io_fallback_total",
        {"operation": "dispatch_message", "reason": "submit_error"},
    )
    if fallback != 0.0:
        raise QualificationFailure("async dispatcher fallback metric was nonzero")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "contract_sha256": sha(contract_raw),
        "run": {
            "id_sha256": sha(run_id),
            "duration_seconds": round(time.monotonic() - started, 3),
            "free_bytes_before": runtime["free_bytes_before"],
            "free_bytes_after": shutil.disk_usage(REPO).free,
        },
        "runtime": {
            "containers": runtime["containers"],
            "exact_live_source_locks": runtime["exact_live_source_locks"],
            "semantic_live_source_locks": runtime["semantic_live_source_locks"],
            "owned_image_id": inspect_container("vss-alert-bridge")["Image"],
            "owned_image_name": image,
        },
        "configuration": config_projection,
        "ingestion": {
            "transport": "kafka-protobuf",
            "candidate_count": BURST_COUNT,
            "topic_count": len(topics),
            "publish_duration_seconds": round(produce_duration, 3),
            "all_vst_requests_correlated": len(fixture_state["vst_requests"]) == BURST_COUNT,
            "all_media_requests_correlated": len(fixture_state["media_requests"]) == BURST_COUNT,
        },
        "concurrency": {
            "dispatch_workers": config_projection["dispatch_workers"],
            "maximum_parallel_vlm_calls": fixture_state["max_active"],
            "dispatch_threads": dispatch_threads,
            "queue_events_total": all_queue_events,
            "queue_events_before_slowest_completed": queued_before_slow,
            "slow_candidate": SLOW_CANDIDATE,
            "slow_duration_seconds": slow_call["duration_seconds"],
            "fast_candidates_completed_before_slow": sorted(fast_before_slow),
            "completion_order": completion_order,
            "all_independent_fast_candidates_overtook_slow": len(fast_before_slow) == BURST_COUNT - 1,
            "inline_fallbacks": int(fallback),
            "container_log_sha256": sha(logs),
        },
        "candidates": {
            "count": len(candidate_receipts),
            "all_persisted": len(candidate_receipts) == BURST_COUNT,
            "all_media_correlated": all(item["media_correlated"] for item in candidate_receipts),
            "all_parser_schemas_conformant": all(item["parser_schema_conformant"] for item in candidate_receipts),
            "all_categories_preserved": len({item["output_category"] for item in candidate_receipts}) == BURST_COUNT,
            "confirmed_count": sum(item["verdict"] == "confirmed" for item in candidate_receipts),
            "rejected_count": sum(item["verdict"] == "rejected" for item in candidate_receipts),
            "records": candidate_receipts,
        },
        "metrics": {
            "per_candidate_terminal_metrics": True,
            "events_total": BURST_COUNT,
            "vlm_duration_observations": BURST_COUNT,
            "worker_processing_observations": BURST_COUNT,
            "worker_queue_wait_observations": BURST_COUNT,
            "dispatch_fallbacks": int(fallback),
            "scrape_sha256": sha(metrics_text),
        },
        "cleanup": cleanup,
        "policy": {
            "network": "loopback-only",
            "external_requests": 0,
            "agent_generate_calls": 0,
            "warehouse_sample_bundle": "excluded",
            "main_alert_mutations": 0,
            "main_rtvlm_mutations": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", default=str(HERE / "runtime-receipt.json"))
    args = parser.parse_args(argv)
    if args.acknowledgement != ACK:
        raise SystemExit("exact acknowledgement required")
    contract_path = HERE / "contract.json"
    contract_raw = contract_path.read_bytes()
    contract = json.loads(contract_raw)
    try:
        receipt = execute(contract, contract_raw, args.run_id)
    except QualificationFailure as exc:
        print(json.dumps({
            "package_id": contract.get("package_id"),
            "status": "failed",
            "failure": str(exc),
        }, sort_keys=True))
        return 1
    output = Path(args.output).resolve()
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "package_id": receipt["package_id"],
        "status": receipt["status"],
        "receipt_sha256": file_sha(output),
        "duration_seconds": receipt["run"]["duration_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
