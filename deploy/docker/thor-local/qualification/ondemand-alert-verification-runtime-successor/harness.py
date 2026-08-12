#!/usr/bin/env python3
"""Qualify the operator-triggered Alert Bridge verification API on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ALERT = "http://127.0.0.1:9080"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
MEDIA_ORIGIN = "http://127.0.0.1:38125"
MEDIA_PATH = "/thor-owned/warehouse-ppe.mp4"
INCIDENT_INDEX = "mdx-vlm-incidents-*"
ACK = "I_AUTHORIZE_OWNED_ONDEMAND_ALERT_VERIFICATION"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class QualificationFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()


def sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationFailure(f"expected object: {path}")
    return value


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


def configs() -> list[dict[str, Any]]:
    status, body = request_json(f"{ALERT}/api/v1/verification/config")
    rows = body.get("configs") if isinstance(body, dict) else None
    if status != 200 or not isinstance(rows, list):
        raise QualificationFailure("alert config snapshot failed")
    return sorted(rows, key=lambda item: str(item.get("alert_type", "")))


def rules() -> list[dict[str, Any]]:
    status, body = request_json(f"{ALERT}/api/v1/realtime")
    rows = body.get("rules") if isinstance(body, dict) else None
    if status != 200 or not isinstance(rows, list):
        raise QualificationFailure("realtime rule snapshot failed")
    return sorted(rows, key=lambda item: str(item.get("id", "")))


def streams() -> list[dict[str, Any]]:
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
    return sorted(rows, key=lambda item: str(item.get("id", "")))


def incident_hits(query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC}/{INCIDENT_INDEX}/_search?allow_no_indices=true&ignore_unavailable=true",
        method="POST",
        body={"size": 10000, "query": query or {"match_all": {}}},
    )
    hits = body.get("hits", {}).get("hits") if isinstance(body, dict) else None
    if status != 200 or not isinstance(hits, list):
        raise QualificationFailure("incident snapshot failed")
    normalized = [
        {
            "_id": item.get("_id"),
            "_index": item.get("_index"),
            "_source": item.get("_source"),
        }
        for item in hits
    ]
    return sorted(
        normalized,
        key=lambda item: (str(item.get("_index", "")), str(item.get("_id", ""))),
    )


def running_containers() -> list[dict[str, str]]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    rows = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        container_id, name, image = line.split("\t", 2)
        rows.append({"id": container_id, "name": name, "image": image})
    return sorted(rows, key=lambda item: item["name"])


def snapshot() -> dict[str, Any]:
    return {
        "configs": configs(),
        "incidents": incident_hits(),
        "realtime_rules": rules(),
        "rtvlm_streams": streams(),
        "running_containers": running_containers(),
    }


def snapshot_delta(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Return bounded diagnostics for exact-state mismatches."""
    changed = []
    for key in sorted(set(before) | set(after)):
        before_value = before.get(key)
        after_value = after.get(key)
        if canonical(before_value) == canonical(after_value):
            continue
        changed.append(
            {
                "section": key,
                "before_count": len(before_value) if isinstance(before_value, list) else None,
                "after_count": len(after_value) if isinstance(after_value, list) else None,
                "before_sha256": sha(canonical(before_value)),
                "after_sha256": sha(canonical(after_value)),
            }
        )
    return json.dumps(changed, sort_keys=True, separators=(",", ":"))


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    free_bytes = shutil.disk_usage(REPO).free
    if free_bytes < contract["execution"]["minimum_free_bytes"]:
        raise QualificationFailure("disk safety floor not met")

    checked = 0
    live_checked = 0
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationFailure(f"source lock drifted: {lock['path']}")
        checked += 1
        container = lock.get("container")
        destination = lock.get("container_path")
        if container and destination:
            result = subprocess.run(
                [
                    "docker", "exec", container,
                    lock.get("container_python", "/usr/local/bin/python"),
                    "-c",
                    "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())",
                    destination,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip() != lock["sha256"]:
                raise QualificationFailure(f"live source lock drifted: {destination}")
            live_checked += 1

    identities: dict[str, Any] = {}
    for name, expected in contract["runtime"]["containers"].items():
        result = subprocess.run(
            ["docker", "inspect", name],
            check=True,
            capture_output=True,
            timeout=30,
        )
        rows = json.loads(result.stdout)
        if len(rows) != 1:
            raise QualificationFailure(f"runtime identity missing: {name}")
        row = rows[0]
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
        }

    for url in (f"{ALERT}/health", f"{RTVLM}/v1/health/ready"):
        status, _ = request_json(url)
        if status != 200:
            raise QualificationFailure(f"runtime health failed: {url}")
    return {
        "free_bytes_before": free_bytes,
        "source_lock_count": checked,
        "live_source_lock_count": live_checked,
        "containers": identities,
    }


class FixtureServer:
    def __init__(self, fixture: Path) -> None:
        self.fixture = fixture
        self.get_count = 0
        self._lock = threading.Lock()
        fixture_server = self

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
                raw = fixture_server.fixture.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    with fixture_server._lock:
                        fixture_server.get_count += 1
                    self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 38125), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise QualificationFailure("fixture server did not stop")


def owned_event_hits(event_ids: list[str]) -> list[dict[str, Any]]:
    return incident_hits(
        {
            "bool": {
                "should": [
                    {"terms": {"id.keyword": event_ids}},
                    {"terms": {"id": event_ids}},
                ],
                "minimum_should_match": 1,
            }
        }
    )


def owned_rtvlm_hits(marker: str) -> list[dict[str, Any]]:
    return incident_hits({"match_phrase": {"info.prompt": marker}})


def delete_hit(hit: dict[str, Any]) -> None:
    index = urllib.parse.quote(str(hit["_index"]), safe="-_.")
    document = urllib.parse.quote(str(hit["_id"]), safe="-_.")
    status, body = request_json(f"{ELASTIC}/{index}/_doc/{document}", method="DELETE")
    if status != 200 or body.get("result") != "deleted":
        raise QualificationFailure("owned incident cleanup failed")


def delete_owned_hits(event_ids: list[str], sensor_id: str) -> int:
    deleted = 0
    for hit in owned_event_hits(event_ids):
        source = hit.get("_source")
        if (
            not isinstance(source, dict)
            or source.get("id") not in event_ids
            or source.get("sensorId") != sensor_id
        ):
            raise QualificationFailure("refused to delete non-owned incident")
        delete_hit(hit)
        deleted += 1
    if deleted:
        status, _ = request_json(f"{ELASTIC}/_refresh", method="POST")
        if status != 200:
            raise QualificationFailure("Elasticsearch refresh failed")
    return deleted


def delete_owned_rtvlm_hits(marker: str) -> int:
    deleted = 0
    for hit in owned_rtvlm_hits(marker):
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
            raise QualificationFailure("refused to delete non-owned RT-VLM incident")
        delete_hit(hit)
        deleted += 1
    if deleted:
        status, _ = request_json(f"{ELASTIC}/_refresh", method="POST")
        if status != 200:
            raise QualificationFailure("Elasticsearch refresh failed")
    return deleted


def terminal_job(status_url: str, contract: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    states: list[str] = []
    rank = {"queued": 0, "running": 1, "publishing": 2, "completed": 3, "failed": 3, "cancelled": 3}
    prior = -1
    for attempt in range(contract["execution"]["terminal_poll_attempts"]):
        if attempt:
            time.sleep(contract["execution"]["terminal_poll_seconds"])
        status, body = request_json(f"{ALERT}{status_url}")
        state = body.get("state") if isinstance(body, dict) else None
        if status != 200 or state not in rank:
            raise QualificationFailure("invalid terminal job status")
        if rank[state] < prior:
            raise QualificationFailure("terminal job state regressed")
        prior = rank[state]
        states.append(state)
        if body.get("terminal") is True:
            return body, states
    raise QualificationFailure("terminal job polling exhausted")


def accepted_job(body: Any, event_id: str) -> tuple[str, str]:
    correlation_id = body.get("correlationId") if isinstance(body, dict) else None
    status_url = body.get("statusUrl") if isinstance(body, dict) else None
    if (
        body.get("status") != "accepted"
        or not isinstance(correlation_id, str)
        or not correlation_id.startswith("job-")
        or correlation_id == event_id
        or status_url != f"/api/v1/verification/ondemand/{correlation_id}"
    ):
        raise QualificationFailure("invalid on-demand admission")
    return correlation_id, status_url


def execute(contract: dict[str, Any], contract_raw: bytes, run_id: str) -> dict[str, Any]:
    if not ID_RE.fullmatch(run_id):
        raise QualificationFailure("invalid run ID")
    runtime = verify_runtime(contract)
    fixture_path = REPO / contract["fixture"]["path"]
    fixture_raw = fixture_path.read_bytes()
    if (
        sha(fixture_raw) != contract["fixture"]["sha256"]
        or len(fixture_raw) != contract["fixture"]["bytes"]
    ):
        raise QualificationFailure("fixture identity drifted")

    before = snapshot()
    before_digest = sha(canonical(before))
    suffix = sha(run_id)[:16]
    category = f"thor_ondemand_{suffix}"
    secondary_category = f"thor_ondemand_secondary_{suffix}"
    missing_category = f"thor_ondemand_missing_{suffix}"
    sensor_id = f"thor-fixture-{suffix}"
    positive_event = f"thor-positive-{suffix}"
    secondary_event = f"thor-secondary-{suffix}"
    cancel_event = f"thor-cancel-{suffix}"
    event_ids = [positive_event, secondary_event, cancel_event]
    owned_categories = {category, secondary_category}
    if any(item.get("alert_type") in owned_categories for item in before["configs"]):
        raise QualificationFailure("owned config already exists")
    if owned_event_hits(event_ids):
        raise QualificationFailure("owned incident already exists")

    marker = f"Thor Multi-Category {suffix}"
    primary_output = f"{marker} Primary"
    secondary_output = f"{marker} Secondary"
    prompt = (
        "Across these time-ordered warehouse frames, is at least one person "
        "visibly wearing both a bright yellow high-visibility safety vest and "
        "a yellow hard hat? Return only JSON with prediction_answer exactly "
        "YES or NO and reasoning as one concise evidence-based sentence. "
        f"Qualification token: {marker}; class: primary."
    )
    expected_config = {
        "alert_type": category,
        "prompt": prompt,
        "system_prompt": (
            "You verify only visible evidence in chronological camera frames. "
            "Return exactly one valid JSON object with keys prediction_answer and "
            "reasoning. prediction_answer must be exactly YES or NO."
        ),
        "output_category": primary_output,
        "vlm_params": {
            "media_mode": "snapshots",
            "response_format": "json",
            "max_tokens": 128,
            "snapshot_frames": 4,
            "temperature": 0.0,
            "num_frames": 4,
            "json_parser": {
                "verdict_field": "prediction_answer",
                "reasoning_fields": ["reasoning", "explanation"],
            },
            "request_timeout": 60,
        },
    }
    secondary_config = {
        **expected_config,
        "alert_type": secondary_category,
        "prompt": prompt.replace("class: primary", "class: secondary"),
        "output_category": secondary_output,
    }
    media_url = f"{MEDIA_ORIGIN}{MEDIA_PATH}"
    fixture_server = FixtureServer(fixture_path)
    configs_owned: set[str] = set()
    positive_id = ""
    positive_status_url = ""
    cancel_id = ""
    cancel_status_url = ""
    positive_terminal: dict[str, Any] | None = None
    positive_states: list[str] = []
    secondary_id = ""
    secondary_status_url = ""
    secondary_terminal: dict[str, Any] | None = None
    secondary_states: list[str] = []
    secondary_sink_source: dict[str, Any] | None = None
    cancel_snapshot: dict[str, Any] | None = None
    sink_source: dict[str, Any] | None = None
    primary: BaseException | None = None
    cleanup_deleted = 0
    cleanup_rtvlm_deleted = 0
    started = time.monotonic()
    fixture_server.start()
    try:
        status, created = request_json(
            f"{ALERT}/api/v1/verification/config", method="POST", body=expected_config,
        )
        if status != 201 or created.get("alert_type") != category:
            raise QualificationFailure("owned config creation failed")
        configs_owned.add(category)
        exact_path = urllib.parse.quote(category, safe="")
        status, inspected = request_json(f"{ALERT}/api/v1/verification/config/{exact_path}")
        if status != 200 or any(inspected.get(key) != value for key, value in expected_config.items()):
            raise QualificationFailure("owned config inspection failed")

        status, created = request_json(
            f"{ALERT}/api/v1/verification/config", method="POST", body=secondary_config,
        )
        if status != 201 or created.get("alert_type") != secondary_category:
            raise QualificationFailure("secondary config creation failed")
        configs_owned.add(secondary_category)
        secondary_path = urllib.parse.quote(secondary_category, safe="")
        status, inspected = request_json(f"{ALERT}/api/v1/verification/config/{secondary_path}")
        if status != 200 or any(inspected.get(key) != value for key, value in secondary_config.items()):
            raise QualificationFailure("secondary config inspection failed")

        payload = {
            "id": positive_event,
            "sensorId": sensor_id,
            "category": category,
            "info": {"media_urls": [media_url], "media_type": "video"},
        }
        status, admitted = request_json(
            f"{ALERT}/api/v1/verification/ondemand", method="POST", body=payload,
        )
        if status != 202:
            raise QualificationFailure("positive on-demand submission failed")
        positive_id, positive_status_url = accepted_job(admitted, positive_event)
        positive_terminal, positive_states = terminal_job(positive_status_url, contract)
        result = positive_terminal.get("result")
        sink = result.get("sinkDelivery") if isinstance(result, dict) else None
        if (
            positive_terminal.get("state") != "completed"
            or positive_terminal.get("terminal") is not True
            or result.get("processingOutcome") != "verified"
            or result.get("verdict") != "confirmed"
            or result.get("verificationResponseCode") != 200
            or not isinstance(sink, dict)
            or sink.get("transport") != "elastic"
            or sink.get("outcome") != "acknowledged"
            or not isinstance(sink.get("index"), str)
            or not isinstance(sink.get("documentId"), str)
        ):
            raise QualificationFailure("positive terminal verdict was not exact")
        index = urllib.parse.quote(sink["index"], safe="-_.")
        document = urllib.parse.quote(sink["documentId"], safe="-_.")
        status, stored = request_json(f"{ELASTIC}/{index}/_doc/{document}")
        sink_source = stored.get("_source") if isinstance(stored, dict) else None
        info = sink_source.get("info") if isinstance(sink_source, dict) else None
        if (
            status != 200
            or sink_source.get("id") != positive_event
            or sink_source.get("sensorId") != sensor_id
            or sink_source.get("category") != primary_output
            or not isinstance(info, dict)
            or info.get("verdict") != "confirmed"
            or str(info.get("verificationResponseCode")) != "200"
            or not isinstance(info.get("reasoning"), str)
            or not info["reasoning"].strip()
        ):
            raise QualificationFailure("persisted positive verdict was not correlated")

        secondary_payload = {
            "id": secondary_event,
            "sensorId": sensor_id,
            "category": secondary_category.upper(),
            "info": {"media_urls": [media_url], "media_type": "video"},
        }
        status, admitted = request_json(
            f"{ALERT}/api/v1/verification/ondemand",
            method="POST",
            body=secondary_payload,
        )
        if status != 202:
            raise QualificationFailure("secondary category submission failed")
        secondary_id, secondary_status_url = accepted_job(admitted, secondary_event)
        if secondary_id == positive_id:
            raise QualificationFailure("server reused a multi-category job ID")
        secondary_terminal, secondary_states = terminal_job(
            secondary_status_url, contract,
        )
        secondary_result = secondary_terminal.get("result")
        secondary_sink = (
            secondary_result.get("sinkDelivery")
            if isinstance(secondary_result, dict) else None
        )
        if (
            secondary_terminal.get("state") != "completed"
            or secondary_terminal.get("terminal") is not True
            or secondary_result.get("processingOutcome") != "verified"
            or secondary_result.get("verdict") != "confirmed"
            or secondary_result.get("verificationResponseCode") != 200
            or not isinstance(secondary_sink, dict)
            or secondary_sink.get("transport") != "elastic"
            or secondary_sink.get("outcome") != "acknowledged"
            or not isinstance(secondary_sink.get("index"), str)
            or not isinstance(secondary_sink.get("documentId"), str)
        ):
            raise QualificationFailure("secondary category verdict was not exact")
        secondary_index = urllib.parse.quote(secondary_sink["index"], safe="-_.")
        secondary_document = urllib.parse.quote(
            secondary_sink["documentId"], safe="-_.",
        )
        status, stored = request_json(
            f"{ELASTIC}/{secondary_index}/_doc/{secondary_document}",
        )
        secondary_sink_source = (
            stored.get("_source") if isinstance(stored, dict) else None
        )
        secondary_info = (
            secondary_sink_source.get("info")
            if isinstance(secondary_sink_source, dict) else None
        )
        if (
            status != 200
            or not isinstance(secondary_sink_source, dict)
            or secondary_sink_source.get("id") != secondary_event
            or secondary_sink_source.get("sensorId") != sensor_id
            or secondary_sink_source.get("category") != secondary_output
            or not isinstance(secondary_info, dict)
            or secondary_info.get("verdict") != "confirmed"
            or str(secondary_info.get("verificationResponseCode")) != "200"
            or secondary_info.get("verificationResponseStatus") != "OK"
            or not isinstance(secondary_info.get("reasoning"), str)
            or not secondary_info["reasoning"].strip()
        ):
            raise QualificationFailure("secondary persisted mapping was not correlated")

        cancel_payload = {
            "id": cancel_event,
            "sensorId": sensor_id,
            "category": category,
            "info": {"media_urls": [media_url], "media_type": "video"},
        }
        status, admitted = request_json(
            f"{ALERT}/api/v1/verification/ondemand", method="POST", body=cancel_payload,
        )
        if status != 202:
            raise QualificationFailure("cancellation submission failed")
        cancel_id, cancel_status_url = accepted_job(admitted, cancel_event)
        if cancel_id == positive_id:
            raise QualificationFailure("server reused a job ID")
        status, cancelled = request_json(f"{ALERT}{cancel_status_url}", method="DELETE")
        if (
            status != 202
            or cancelled.get("state") != "cancelled"
            or cancelled.get("terminal") is not True
            or cancelled.get("cancellationAccepted") is not True
            or "result" in cancelled
        ):
            raise QualificationFailure("pre-publish cancellation was not accepted")
        time.sleep(contract["execution"]["cancellation_settle_seconds"])
        status, cancel_snapshot = request_json(f"{ALERT}{cancel_status_url}")
        if (
            status != 200
            or cancel_snapshot.get("state") != "cancelled"
            or cancel_snapshot.get("terminal") is not True
            or "result" in cancel_snapshot
            or owned_event_hits([cancel_event])
        ):
            raise QualificationFailure("cancelled job published after cancellation")
        backend_hits = owned_rtvlm_hits(marker)
        if len(backend_hits) != contract["execution"]["expected_rtvlm_publications"]:
            raise QualificationFailure("RT-VLM backend publications were not quiescent")

        status, rejected = request_json(
            f"{ALERT}/api/v1/verification/ondemand",
            method="POST",
            body={
                "id": f"thor-negative-{suffix}",
                "sensorId": sensor_id,
                "category": missing_category,
                "info": {"media_urls": [media_url], "media_type": "video"},
            },
        )
        if (
            status != 400
            or rejected.get("error") != "unknown_category"
            or "correlationId" in rejected
        ):
            raise QualificationFailure("unknown category did not fail before admission")
    except BaseException as exc:
        primary = exc
    finally:
        try:
            cleanup_deleted = delete_owned_hits(event_ids, sensor_id)
            cleanup_rtvlm_deleted = delete_owned_rtvlm_hits(marker)
            for owned_category in sorted(configs_owned):
                exact_path = urllib.parse.quote(owned_category, safe="")
                status, body = request_json(
                    f"{ALERT}/api/v1/verification/config/{exact_path}", method="DELETE",
                )
                if status != 200 or body.get("status") != "success":
                    raise QualificationFailure("owned config cleanup failed")
        except BaseException as exc:
            if primary is None:
                primary = exc
        try:
            fixture_server.stop()
        except BaseException as exc:
            if primary is None:
                primary = exc

    after = snapshot()
    after_digest = sha(canonical(after))
    if primary is not None:
        if before_digest != after_digest:
            raise QualificationFailure(
                f"cleanup failed after primary error: {snapshot_delta(before, after)}"
            ) from primary
        if isinstance(primary, QualificationFailure):
            raise primary
        raise QualificationFailure("unexpected qualification failure") from primary
    if (
        before_digest != after_digest
        or owned_event_hits(event_ids)
        or owned_rtvlm_hits(marker)
    ):
        raise QualificationFailure(
            f"exact runtime state was not restored: {snapshot_delta(before, after)}"
        )
    if any(item.get("alert_type") in owned_categories for item in after["configs"]):
        raise QualificationFailure("owned config remains")
    if fixture_server.get_count < 1:
        raise QualificationFailure("fixture was not downloaded")
    if time.monotonic() - started > contract["execution"]["maximum_duration_seconds"]:
        raise QualificationFailure("qualification duration exceeded")

    assert (
        positive_terminal is not None
        and secondary_terminal is not None
        and cancel_snapshot is not None
        and sink_source is not None
        and secondary_sink_source is not None
    )
    result = positive_terminal["result"]
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
            "duration_ms": round((time.monotonic() - started) * 1000),
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "runtime": {
            **runtime,
            "free_bytes_after": shutil.disk_usage(REPO).free,
            "model": contract["runtime"]["model"],
        },
        "fixture": {
            "sha256": sha(fixture_raw),
            "bytes": len(fixture_raw),
            "media_url_sha256": sha(media_url),
            "http_get_count": fixture_server.get_count,
        },
        "positive": {
            "event_id_sha256": sha(positive_event),
            "correlation_id_sha256": sha(positive_id),
            "status_url_sha256": sha(positive_status_url),
            "server_generated_job_id": True,
            "poll_states": positive_states,
            "terminal_state": "completed",
            "processing_outcome": "verified",
            "verdict": "confirmed",
            "verification_response_code": 200,
            "sink_transport": "elastic",
            "sink_outcome": "acknowledged",
            "sink_index_sha256": sha(sink["index"]),
            "sink_document_id_sha256": sha(sink["documentId"]),
            "persisted_source_sha256": sha(canonical(sink_source)),
            "mapped_category_sha256": sha(primary_output),
            "reasoning_present": True,
        },
        "classification": {
            "configured_category_count": 2,
            "input_alias_count": 2,
            "case_normalized_alias_observed": True,
            "distinct_output_categories": True,
            "all_terminal_states_completed": True,
            "all_processing_outcomes_verified": True,
            "all_verdicts_confirmed": True,
            "all_reasoning_present": True,
            "all_parse_statuses_ok": True,
            "primary_output_category_sha256": sha(primary_output),
            "secondary_output_category_sha256": sha(secondary_output),
            "secondary_event_id_sha256": sha(secondary_event),
            "secondary_correlation_id_sha256": sha(secondary_id),
            "secondary_status_url_sha256": sha(secondary_status_url),
            "secondary_poll_states": secondary_states,
            "secondary_persisted_source_sha256": sha(
                canonical(secondary_sink_source)
            ),
        },
        "cancellation": {
            "event_id_sha256": sha(cancel_event),
            "correlation_id_sha256": sha(cancel_id),
            "status_url_sha256": sha(cancel_status_url),
            "delete_http_status": 202,
            "cancellation_accepted": True,
            "terminal_state": "cancelled",
            "result_absent": True,
            "settle_seconds": contract["execution"]["cancellation_settle_seconds"],
            "sink_hit_count": 0,
        },
        "negative": {
            "unknown_category_http_status": 400,
            "error": "unknown_category",
            "job_id_absent": True,
        },
        "cleanup": {
            "before_sha256": before_digest,
            "after_sha256": after_digest,
            "config_count_before": len(before["configs"]),
            "config_count_after": len(after["configs"]),
            "incident_count_before": len(before["incidents"]),
            "incident_count_after": len(after["incidents"]),
            "running_container_count": len(before["running_containers"]),
            "owned_incident_documents_deleted": cleanup_deleted,
            "owned_rtvlm_documents_deleted": cleanup_rtvlm_deleted,
            "owned_config_absent": True,
            "owned_sink_documents_absent": True,
            "fixture_server_stopped": True,
            "running_container_set_preserved": True,
            "terminal_job_delete_api_available": False,
            "terminal_records_retained_until_ttl_or_restart": True,
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
            args.output.write_text(encoded)
        print(encoded, end="")
        return 0
    except QualificationFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
