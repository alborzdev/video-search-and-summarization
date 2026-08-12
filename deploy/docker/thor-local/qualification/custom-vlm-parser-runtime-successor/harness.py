#!/usr/bin/env python3
"""Qualify configured custom VLM parsing through the Thor Alert REST API."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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
MAIN_ALERT = "http://127.0.0.1:9080"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
OWNED_ALERT_PORT = 19082
NEGATIVE_ALERT_PORT = 19083
MEDIA_PORT = 38126
MEDIA_PATH = "/thor-owned/custom-parser.mp4"
ACK = "I_AUTHORIZE_OWNED_CUSTOM_VLM_PARSER_QUALIFICATION"
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


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    timeout: float = 70,
) -> tuple[int, Any]:
    data = canonical(body) if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"unparsed_body_sha256": sha(raw)}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationFailure(f"local request failed: {url}") from exc


def docker(*args: str, check: bool = True, timeout: float = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def running_containers() -> list[dict[str, str]]:
    rows = []
    result = docker("ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}")
    for line in result.stdout.splitlines():
        if line.strip():
            container_id, name, image = line.split("\t", 2)
            rows.append({"id": container_id, "name": name, "image": image})
    return sorted(rows, key=lambda item: item["name"])


def main_snapshot() -> dict[str, Any]:
    status, configs = request_json(f"{MAIN_ALERT}/api/v1/verification/config")
    status_rules, rules = request_json(f"{MAIN_ALERT}/api/v1/realtime")
    status_streams, streams = request_json(f"{RTVLM}/v1/streams/get-stream-info")
    if status != 200 or status_rules != 200 or status_streams != 200:
        raise QualificationFailure("main runtime snapshot failed")
    return {
        "alert_configs": configs,
        "realtime_rules": rules,
        "rtvlm_streams": streams,
        "running_containers": running_containers(),
    }


def live_file_sha(container: str, path: str) -> str:
    result = docker(
        "exec", container, "/usr/local/bin/python", "-c",
        "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())",
        path,
    )
    return result.stdout.strip()


def inspect_container(name: str) -> dict[str, Any]:
    result = docker("inspect", name)
    rows = json.loads(result.stdout)
    if len(rows) != 1:
        raise QualificationFailure(f"container identity missing: {name}")
    return rows[0]


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    free_bytes = shutil.disk_usage(REPO).free
    if free_bytes < contract["execution"]["minimum_free_bytes"]:
        raise QualificationFailure("disk safety floor not met")
    source_count = 0
    live_count = 0
    for lock in contract["source_locks"]:
        source = REPO / lock["path"]
        if not source.is_file() or source.is_symlink() or sha(source.read_bytes()) != lock["sha256"]:
            raise QualificationFailure(f"source lock drifted: {lock['path']}")
        source_count += 1
        if lock.get("container") and lock.get("container_path"):
            if live_file_sha(lock["container"], lock["container_path"]) != lock["sha256"]:
                raise QualificationFailure(f"live source lock drifted: {lock['container_path']}")
            live_count += 1
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
    for url in (f"{MAIN_ALERT}/health", f"{RTVLM}/v1/health/ready"):
        status, _ = request_json(url)
        if status != 200:
            raise QualificationFailure(f"runtime health failed: {url}")
    return {
        "free_bytes_before": free_bytes,
        "source_lock_count": source_count,
        "live_source_lock_count": live_count,
        "containers": identities,
    }


class FixtureServer:
    def __init__(self, fixture: Path) -> None:
        self.fixture = fixture
        self.get_count = 0
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_HEAD(self) -> None:  # noqa: N802
                self._serve(head=True)

            def do_GET(self) -> None:  # noqa: N802
                self._serve(head=False)

            def _serve(self, *, head: bool) -> None:
                if urllib.parse.urlsplit(self.path).path != MEDIA_PATH:
                    self.send_error(404)
                    return
                raw = owner.fixture.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    with owner._lock:
                        owner.get_count += 1
                    self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", MEDIA_PORT), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise QualificationFailure("fixture server did not stop")


def live_runtime_config() -> dict[str, Any]:
    result = docker(
        "exec", "vss-alert-bridge", "/usr/local/bin/python", "-c",
        "import sys;sys.stdout.buffer.write(open('/app/runtime/config.yml','rb').read())",
    )
    value = yaml.safe_load(result.stdout)
    if not isinstance(value, dict):
        raise QualificationFailure("live Alert config is not an object")
    return value


def owned_config(
    base: dict[str, Any],
    *,
    prefix: str,
    response_parser: str,
) -> dict[str, Any]:
    value = copy.deepcopy(base)
    value.setdefault("vlm", {})["response_parser"] = response_parser
    value["vlm"]["request_timeout"] = 70
    value.setdefault("kafka", {})["group_id"] = f"{prefix}worker"
    value["kafka"]["enhanced_anomaly_topic"] = f"{prefix}enhanced"
    value["kafka"]["incidents_topic"] = f"{prefix}incidents"
    event_bridge = value.setdefault("event_bridge", {})
    kafka_source = event_bridge.setdefault("kafka_source", {})
    kafka_source["group_id"] = f"{prefix}source"
    kafka_source["topics"] = {
        "incident": f"{prefix}input-incidents",
        "alert": f"{prefix}input-alerts",
    }
    value.setdefault("persistence", {})["enabled"] = True
    value["persistence"]["backend"] = "elasticsearch"
    value["persistence"]["index_prefix"] = prefix
    value.setdefault("alert_agent", {})["always_on"] = False
    value["alert_agent"].setdefault("media_download", {})["allow_private_urls"] = True
    value["alert_agent"]["media_download"]["enabled"] = True
    value.setdefault("websocket", {})["enabled"] = False
    value.setdefault("webhook", {}).setdefault("openclaw", {})["enabled"] = False
    value["alert_type_config_file"] = "/app/alert_type_config.json"
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
    return value


def write_config(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    path.chmod(0o444)


def start_owned_container(
    *,
    name: str,
    port: int,
    config_path: Path,
    parser_path: Path,
    image: str,
) -> None:
    result = docker("inspect", name, check=False)
    if result.returncode == 0:
        raise QualificationFailure(f"owned container already exists: {name}")
    docker(
        "run", "--detach", "--name", name, "--network", "host",
        "--no-healthcheck", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=64m",
        "--env", f"FASTAPI_PORT={port}",
        "--env", "PROMETHEUS_METRICS_ENABLED=false",
        "--env", "VLM_WARMUP_ENABLED=false",
        "--env", "ALERT_DIRECT_MEDIA_USE_VERDICT=false",
        "--env", "ALERT_VLM_MEDIA_SOURCE_USING_BASE64=true",
        "--env", "ALERT_AGENT_CONFIG_DIR=/app",
        "--mount", f"type=bind,src={config_path},dst=/app/thor-row326-config.yml,readonly",
        "--mount", f"type=bind,src={parser_path},dst=/app/thor_custom_parser.py,readonly",
        "--entrypoint", "/usr/local/bin/python",
        image,
        "/app/enhance_alert_with_vlm.py", "--config", "/app/thor-row326-config.yml",
    )


def wait_health(base_url: str, container: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        row = inspect_container(container)
        if row.get("State", {}).get("Status") != "running":
            logs = docker("logs", container, check=False).stdout
            raise QualificationFailure(f"owned Alert container exited: {sha(logs)}")
        try:
            status, _ = request_json(f"{base_url}/health", timeout=2)
        except QualificationFailure:
            status = 0
        if status == 200:
            return
        time.sleep(1)
    raise QualificationFailure("owned Alert health timeout")


def terminal_job(base_url: str, status_url: str, contract: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    states: list[str] = []
    ranks = {"queued": 0, "running": 1, "publishing": 2, "completed": 3, "failed": 3}
    prior = -1
    for attempt in range(contract["execution"]["terminal_poll_attempts"]):
        if attempt:
            time.sleep(contract["execution"]["terminal_poll_seconds"])
        status, body = request_json(f"{base_url}{status_url}")
        state = body.get("state") if isinstance(body, dict) else None
        if status != 200 or state not in ranks or ranks[state] < prior:
            raise QualificationFailure("invalid custom-parser terminal state")
        states.append(state)
        prior = ranks[state]
        if body.get("terminal") is True:
            return body, states
    raise QualificationFailure("custom-parser terminal polling exhausted")


def incident_hits(index_pattern: str, query: dict[str, Any]) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(index_pattern, safe="-*_,")
    status, body = request_json(
        f"{ELASTIC}/{encoded}/_search?allow_no_indices=true&ignore_unavailable=true",
        method="POST",
        body={"size": 10000, "query": query},
    )
    hits = body.get("hits", {}).get("hits") if isinstance(body, dict) else None
    if status != 200 or not isinstance(hits, list):
        raise QualificationFailure("Elasticsearch query failed")
    return hits


def backend_hits(marker: str) -> list[dict[str, Any]]:
    return incident_hits(
        "mdx-vlm-incidents-*", {"match_phrase": {"info.prompt": marker}},
    )


def delete_backend_hits(marker: str) -> int:
    deleted = 0
    for hit in backend_hits(marker):
        source = hit.get("_source")
        info = source.get("info") if isinstance(source, dict) else None
        analytics = source.get("analyticsModule") if isinstance(source, dict) else None
        if (
            not isinstance(info, dict)
            or marker not in str(info.get("prompt", ""))
            or source.get("category") != "vlm-alert"
            or not isinstance(analytics, dict)
            or analytics.get("source") != "rtvi-vlm"
        ):
            raise QualificationFailure("refused to delete non-owned RT-VLM output")
        index = urllib.parse.quote(str(hit.get("_index")), safe="-_.")
        document = urllib.parse.quote(str(hit.get("_id")), safe="-_.")
        status, body = request_json(f"{ELASTIC}/{index}/_doc/{document}", method="DELETE")
        if status != 200 or body.get("result") != "deleted":
            raise QualificationFailure("owned RT-VLM output cleanup failed")
        deleted += 1
    if deleted:
        status, _ = request_json(f"{ELASTIC}/_refresh", method="POST")
        if status != 200:
            raise QualificationFailure("Elasticsearch refresh failed")
    return deleted


def owned_indices(prefix: str) -> list[str]:
    pattern = urllib.parse.quote(f"{prefix}*", safe="-_*.")
    status, body = request_json(f"{ELASTIC}/_cat/indices/{pattern}?format=json&h=index")
    if status == 404:
        return []
    if status != 200 or not isinstance(body, list):
        raise QualificationFailure("owned-index inventory failed")
    names = sorted(
        str(item.get("index")) for item in body if isinstance(item, dict) and item.get("index")
    )
    if any(not name.startswith(prefix) for name in names):
        raise QualificationFailure("owned-index inventory escaped prefix")
    return names


def delete_owned_indices(prefix: str) -> int:
    names = owned_indices(prefix)
    if not names:
        return 0
    encoded = ",".join(urllib.parse.quote(name, safe="-_.") for name in names)
    status, body = request_json(f"{ELASTIC}/{encoded}", method="DELETE")
    if status != 200 or body.get("acknowledged") is not True:
        raise QualificationFailure("owned-index cleanup failed")
    return len(names)


def stop_owned_container(name: str) -> bool:
    row = docker("inspect", name, check=False)
    if row.returncode != 0:
        return False
    docker("rm", "--force", name)
    return True


def execute(contract: dict[str, Any], contract_raw: bytes, run_id: str) -> dict[str, Any]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise QualificationFailure("invalid run ID")
    started = time.monotonic()
    runtime = verify_runtime(contract)
    fixture = REPO / contract["fixture"]["path"]
    fixture_raw = fixture.read_bytes()
    if sha(fixture_raw) != contract["fixture"]["sha256"] or len(fixture_raw) != contract["fixture"]["bytes"]:
        raise QualificationFailure("fixture identity drifted")
    before = main_snapshot()
    before_digest = sha(canonical(before))
    suffix = sha(run_id)[:16]
    prefix = f"thor-row326-{suffix}-"
    negative_prefix = f"thor-row326-negative-{suffix}-"
    positive_name = f"thor-row326-{suffix}"
    negative_name = f"thor-row326-negative-{suffix}"
    if owned_indices(prefix) or owned_indices(negative_prefix):
        raise QualificationFailure("owned Elasticsearch prefix is not empty")
    marker = f"Thor Custom Parser {suffix}"
    parser_path = HERE / contract["parser"]["module_path"]
    dotted_path = contract["parser"]["dotted_path"]
    base_config = live_runtime_config()
    positive_config = owned_config(base_config, prefix=prefix, response_parser=dotted_path)
    negative_dotted_path = "thor_unapproved_parser.DoesNotExist"
    negative_config = owned_config(
        base_config, prefix=negative_prefix, response_parser=negative_dotted_path,
    )
    config_projection = {
        "response_parser": positive_config["vlm"]["response_parser"],
        "model": positive_config["vlm"]["model"],
        "base_url": positive_config["vlm"]["base_url"],
        "persistence_index_prefix": positive_config["persistence"]["index_prefix"],
        "incident_index": positive_config["vlm_enhanced_sink"]["incident"]["elastic"]["index"],
        "fastapi_port": OWNED_ALERT_PORT,
    }
    image = contract["runtime"]["containers"]["vss-alert-bridge"]["image_name"]
    fixture_server = FixtureServer(fixture)
    positive_logs = ""
    negative_logs = ""
    terminal: dict[str, Any] | None = None
    states: list[str] = []
    stored_source: dict[str, Any] | None = None
    parser_output: dict[str, Any] | None = None
    config_readback: dict[str, Any] | None = None
    fixture_started = False
    primary: BaseException | None = None
    backend_deleted = 0
    indices_deleted = 0
    positive_removed = False
    negative_removed = False
    media_url = f"http://127.0.0.1:{MEDIA_PORT}{MEDIA_PATH}"
    category = f"thor_custom_parser_{suffix}"
    output_category = f"{marker} Verified"
    event_id = f"thor-custom-parser-event-{suffix}"
    sensor_id = f"thor-custom-parser-sensor-{suffix}"
    try:
        with tempfile.TemporaryDirectory(prefix="thor-row326-") as temp_dir:
            temp_root = Path(temp_dir)
            temp_root.chmod(0o755)
            positive_config_path = temp_root / "positive.yml"
            negative_config_path = temp_root / "negative.yml"
            write_config(positive_config_path, positive_config)
            write_config(negative_config_path, negative_config)
            fixture_server.start()
            fixture_started = True
            start_owned_container(
                name=positive_name,
                port=OWNED_ALERT_PORT,
                config_path=positive_config_path,
                parser_path=parser_path,
                image=image,
            )
            owned_alert = f"http://127.0.0.1:{OWNED_ALERT_PORT}"
            wait_health(owned_alert, positive_name)
            expected_config = {
                "alert_type": category,
                "prompt": (
                    "Across these time-ordered warehouse frames, is at least one person "
                    "visibly wearing both a bright yellow high-visibility safety vest and "
                    "a yellow hard hat? Return only JSON with prediction_answer exactly "
                    "YES or NO and reasoning as one concise evidence-based sentence. "
                    f"Qualification token: {marker}."
                ),
                "system_prompt": (
                    "Return exactly one valid JSON object with keys prediction_answer and "
                    "reasoning. prediction_answer must be exactly YES or NO."
                ),
                "output_category": output_category,
                "vlm_params": {
                    "media_mode": "snapshots",
                    "response_format": "json",
                    "max_tokens": 128,
                    "snapshot_frames": 4,
                    "temperature": 0.0,
                    "num_frames": 4,
                    "request_timeout": 70,
                },
            }
            status, created = request_json(
                f"{owned_alert}/api/v1/verification/config",
                method="POST",
                body=expected_config,
            )
            if status != 201 or created.get("alert_type") != category:
                raise QualificationFailure("owned parser config creation failed")
            exact_category = urllib.parse.quote(category, safe="")
            status, config_readback = request_json(
                f"{owned_alert}/api/v1/verification/config/{exact_category}"
            )
            if status != 200 or any(
                config_readback.get(key) != value for key, value in expected_config.items()
            ):
                raise QualificationFailure("owned parser config readback failed")
            status, admitted = request_json(
                f"{owned_alert}/api/v1/verification/ondemand",
                method="POST",
                body={
                    "id": event_id,
                    "sensorId": sensor_id,
                    "category": category,
                    "info": {"media_urls": [media_url], "media_type": "video"},
                },
            )
            correlation_id = admitted.get("correlationId") if isinstance(admitted, dict) else None
            status_url = admitted.get("statusUrl") if isinstance(admitted, dict) else None
            if (
                status != 202
                or admitted.get("status") != "accepted"
                or not isinstance(correlation_id, str)
                or not correlation_id.startswith("job-")
                or status_url != f"/api/v1/verification/ondemand/{correlation_id}"
            ):
                raise QualificationFailure("custom-parser request was not admitted")
            terminal, states = terminal_job(owned_alert, status_url, contract)
            result = terminal.get("result") if isinstance(terminal, dict) else None
            sink = result.get("sinkDelivery") if isinstance(result, dict) else None
            if (
                terminal.get("state") != "completed"
                or terminal.get("terminal") is not True
                or result.get("processingOutcome") != "verified"
                or result.get("verdict") != ""
                or result.get("verificationResponseCode") != 200
                or not isinstance(sink, dict)
                or sink.get("transport") != "elastic"
                or sink.get("outcome") != "acknowledged"
                or not isinstance(sink.get("index"), str)
                or not sink["index"].startswith(prefix)
                or not isinstance(sink.get("documentId"), str)
            ):
                raise QualificationFailure("custom-parser terminal receipt was not exact")
            sink_index = urllib.parse.quote(sink["index"], safe="-_.")
            sink_document = urllib.parse.quote(sink["documentId"], safe="-_.")
            status, stored = request_json(f"{ELASTIC}/{sink_index}/_doc/{sink_document}")
            stored_source = stored.get("_source") if isinstance(stored, dict) else None
            info = stored_source.get("info") if isinstance(stored_source, dict) else None
            encoded_parser_output = info.get("vlm_response") if isinstance(info, dict) else None
            try:
                parser_output = json.loads(encoded_parser_output)
            except (TypeError, json.JSONDecodeError) as exc:
                raise QualificationFailure("persisted parser output is not JSON") from exc
            if (
                status != 200
                or stored_source.get("id") != event_id
                or stored_source.get("sensorId") != sensor_id
                or stored_source.get("category") != output_category
                or info.get("verdict") != ""
                or str(info.get("verificationResponseCode")) != "200"
                or info.get("verificationResponseStatus") != "OK"
                or "reasoning" in info
                or parser_output.get("parser_id") != contract["parser"]["parser_id"]
                or parser_output.get("normalized_verdict") != "confirmed"
                or not isinstance(parser_output.get("normalized_reasoning"), str)
                or not parser_output["normalized_reasoning"].strip()
                or not re.fullmatch(r"[0-9a-f]{64}", str(parser_output.get("raw_response_sha256", "")))
            ):
                raise QualificationFailure("persisted custom-parser schema was not exact")
            positive_log_result = docker("logs", positive_name)
            positive_logs = positive_log_result.stdout + positive_log_result.stderr
            required_log_literals = (
                f"Loaded pluggable response parser: '{dotted_path}'",
                f"Pluggable response parser active: '{dotted_path}'",
                f"On-demand pluggable response parser active: '{dotted_path}'",
            )
            if any(literal not in positive_logs for literal in required_log_literals):
                raise QualificationFailure("parser identity was not exposed in both processes")
            status, deleted = request_json(
                f"{owned_alert}/api/v1/verification/config/{exact_category}", method="DELETE"
            )
            if status != 200 or deleted.get("status") != "success":
                raise QualificationFailure("owned parser config cleanup failed")
            positive_removed = stop_owned_container(positive_name)
            start_owned_container(
                name=negative_name,
                port=NEGATIVE_ALERT_PORT,
                config_path=negative_config_path,
                parser_path=parser_path,
                image=image,
            )
            for _ in range(30):
                row = inspect_container(negative_name)
                if row.get("State", {}).get("Status") != "running":
                    break
                time.sleep(1)
            negative_log_result = docker("logs", negative_name, check=False)
            negative_logs = negative_log_result.stdout + negative_log_result.stderr
            negative_health_reachable = True
            try:
                request_json(f"http://127.0.0.1:{NEGATIVE_ALERT_PORT}/health", timeout=1)
            except QualificationFailure:
                negative_health_reachable = False
            row = inspect_container(negative_name)
            if (
                row.get("State", {}).get("Status") == "running"
                or negative_health_reachable
                or negative_dotted_path not in negative_logs
                or "Failed to import parser module" not in negative_logs
            ):
                raise QualificationFailure("unapproved parser path did not fail startup")
            negative_removed = stop_owned_container(negative_name)
    except BaseException as exc:
        primary = exc
    finally:
        try:
            positive_removed = stop_owned_container(positive_name) or positive_removed
            negative_removed = stop_owned_container(negative_name) or negative_removed
            backend_deleted = delete_backend_hits(marker)
            indices_deleted = delete_owned_indices(prefix) + delete_owned_indices(negative_prefix)
        except BaseException as exc:
            if primary is None:
                primary = exc
        if fixture_started:
            try:
                fixture_server.stop()
            except BaseException as exc:
                if primary is None:
                    primary = exc
    after = main_snapshot()
    after_digest = sha(canonical(after))
    cleanup_exact = (
        before_digest == after_digest
        and not owned_indices(prefix)
        and not owned_indices(negative_prefix)
        and not backend_hits(marker)
        and docker("inspect", positive_name, check=False).returncode != 0
        and docker("inspect", negative_name, check=False).returncode != 0
    )
    if primary is not None:
        if not cleanup_exact:
            raise QualificationFailure("cleanup failed after custom-parser error") from primary
        if isinstance(primary, QualificationFailure):
            raise primary
        raise QualificationFailure("unexpected custom-parser qualification failure") from primary
    if not cleanup_exact:
        raise QualificationFailure("exact custom-parser cleanup failed")
    if fixture_server.get_count < 1:
        raise QualificationFailure("fixture was not downloaded")
    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms > contract["execution"]["maximum_duration_seconds"] * 1000:
        raise QualificationFailure("custom-parser qualification duration exceeded")
    assert terminal is not None and stored_source is not None and parser_output is not None
    result = terminal["result"]
    sink = result["sinkDelivery"]
    return {
        "schema_version": 1,
        "status": "passed",
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "contract_sha256": sha(contract_raw),
        "run": {
            "status": "passed",
            "run_id_sha256": sha(run_id),
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "duration_ms": duration_ms,
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "runtime": {
            **runtime,
            "free_bytes_after": shutil.disk_usage(REPO).free,
            "model": contract["runtime"]["model"],
            "isolated_alert_image_id": contract["runtime"]["containers"]["vss-alert-bridge"]["image_id"],
        },
        "parser": {
            "dotted_path": dotted_path,
            "parser_id": parser_output["parser_id"],
            "module_sha256": sha(parser_path.read_bytes()),
            "config_projection_sha256": sha(canonical(config_projection)),
            "worker_loader_observed": True,
            "api_loader_observed": True,
            "identity_exposed": True,
            "config_exposed": config_readback is not None,
            "shared_instance_contract": True,
        },
        "api": {
            "health_http_status": 200,
            "config_create_http_status": 201,
            "config_readback_exact": True,
            "submission_http_status": 202,
            "server_generated_job_id": True,
            "poll_states": states,
            "terminal_state": "completed",
            "processing_outcome": result["processingOutcome"],
            "verification_response_code": result["verificationResponseCode"],
            "sink_transport": sink["transport"],
            "sink_outcome": sink["outcome"],
            "event_id_sha256": sha(event_id),
            "persisted_source_sha256": sha(canonical(stored_source)),
        },
        "output": {
            "parser_id": parser_output["parser_id"],
            "normalized_verdict": parser_output["normalized_verdict"],
            "normalized_reasoning_present": True,
            "raw_response_sha256_present": True,
            "outer_verdict_empty": True,
            "vlm_response_json_present": True,
            "default_reasoning_field_absent": True,
            "verification_response_status": "OK",
            "service_response_schema_conformant": True,
            "mapped_category_sha256": sha(output_category),
        },
        "negative": {
            "dotted_path_sha256": sha(negative_dotted_path),
            "startup_rejected": True,
            "health_never_reachable": True,
            "import_failure_observed": True,
        },
        "fixture": {
            "sha256": sha(fixture_raw),
            "bytes": len(fixture_raw),
            "media_url_sha256": sha(media_url),
            "http_get_count": fixture_server.get_count,
        },
        "cleanup": {
            "before_sha256": before_digest,
            "after_sha256": after_digest,
            "exact_main_runtime_restored": True,
            "positive_container_removed": positive_removed,
            "negative_container_removed": negative_removed,
            "owned_indices_deleted": indices_deleted,
            "owned_indices_absent": True,
            "owned_rtvlm_documents_deleted": backend_deleted,
            "owned_rtvlm_documents_absent": True,
            "fixture_server_stopped": True,
            "running_container_set_preserved": True,
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
        contract = json.loads(contract_raw)
        if contract.get("execution", {}).get("acknowledgement") != ACK:
            raise QualificationFailure("contract acknowledgement drifted")
        receipt = execute(contract, contract_raw, args.run_id)
        encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except QualificationFailure as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
