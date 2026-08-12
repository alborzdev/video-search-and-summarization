#!/usr/bin/env python3
"""Qualify rule-scoped incident retrieval against the live Thor stack."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


ACK = "I_AUTHORIZE_OWNED_REALTIME_INCIDENT_RETRIEVAL"
ALERT_ORIGIN = "http://127.0.0.1:9080"
RTVLM_ORIGIN = "http://127.0.0.1:8018"
ELASTIC_ORIGIN = "http://127.0.0.1:9200"
PUBLISH_ORIGIN = "rtsp://127.0.0.1:8554"
INPUT_ORIGIN = "rtsp://172.18.0.1:8554"
RULE_INDEX = "ab-alert-realtime-rules"
INCIDENT_INDEX = "mdx-vlm-incidents-*"
MAX_DURATION_SECONDS = 300


class QualificationFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    timeout: float = 45,
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


def rules_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict) and isinstance(body.get("rules"), list):
        return body["rules"]
    raise QualificationFailure("unexpected Alert Bridge rule-list envelope")


def streams_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("results", "streams", "items", "data"):
            if isinstance(body.get(key), list):
                return body[key]
    raise QualificationFailure("unexpected RT-VLM stream-list envelope")


def es_hits(index: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC_ORIGIN}/{index}/_search",
        method="POST",
        body={
            "size": 10000,
            "sort": [{"timestamp": {"order": "asc", "unmapped_type": "date"}}],
            "query": query or {"match_all": {}},
        },
    )
    if status != 200:
        raise QualificationFailure(f"Elasticsearch snapshot failed for {index}")
    hits = body.get("hits", {}).get("hits", [])
    if not isinstance(hits, list):
        raise QualificationFailure("unexpected Elasticsearch search envelope")
    return hits


def snapshot() -> dict[str, list[dict[str, Any]]]:
    rules_status, rules_body = request_json(f"{ALERT_ORIGIN}/api/v1/realtime")
    streams_status, streams_body = request_json(
        f"{RTVLM_ORIGIN}/v1/streams/get-stream-info"
    )
    if rules_status != 200 or streams_status != 200:
        raise QualificationFailure("runtime snapshot endpoint failed")
    return {
        "rules": rules_from(rules_body),
        "streams": streams_from(streams_body),
        "persisted_rules": es_hits(RULE_INDEX),
        "incidents": es_hits(INCIDENT_INDEX),
    }


def state_digests(state: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {key: sha(canonical(value)) for key, value in sorted(state.items())}


def running_container_digest() -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    ids = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    return len(ids), sha(canonical(ids))


def query_incidents(**filters: Any) -> tuple[int, Any]:
    params = {
        key: value
        for key, value in filters.items()
        if value is not None
    }
    url = f"{ALERT_ORIGIN}/api/v1/realtime/incidents?{urllib.parse.urlencode(params)}"
    return request_json(url)


def wait_for_rule_incident(rule_id: str, timeout: float = 150) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body = query_incidents(alert_rule_id=rule_id, limit=100)
        if status == 200 and body.get("count", 0) > 0:
            incidents = body.get("incidents", [])
            if isinstance(incidents, list):
                return incidents
        time.sleep(2)
    raise QualificationFailure("RT-VLM did not persist a rule-identified incident in time")


def put_control(index: str, doc_id: str, document: dict[str, Any]) -> None:
    status, _ = request_json(
        f"{ELASTIC_ORIGIN}/{index}/_doc/{urllib.parse.quote(doc_id)}?refresh=true",
        method="PUT",
        body=document,
    )
    if status not in (200, 201):
        raise QualificationFailure("failed to create owned control incident")


def delete_owned_incidents(rule_id: str) -> None:
    request_json(
        f"{ELASTIC_ORIGIN}/{INCIDENT_INDEX}/_delete_by_query"
        "?refresh=true&conflicts=proceed",
        method="POST",
        body={"query": {"term": {"info.alertRuleId.keyword": rule_id}}},
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.ack != ACK:
        raise QualificationFailure("explicit acknowledgement is required")

    started = time.monotonic()
    contract_path = Path(args.contract).resolve()
    fixture_path = Path(args.fixture).resolve()
    output_path = Path(args.output).resolve()
    contract_raw = contract_path.read_bytes()
    contract = json.loads(contract_raw)
    if (
        contract.get("package_id")
        != "realtime-alert-incident-retrieval-runtime-successor"
        or contract.get("capability_id")
        != "manifest-entry.realtime-alerts.04-incident-retrieval"
    ):
        raise QualificationFailure("qualification contract identity mismatch")
    fixture_raw = fixture_path.read_bytes()
    if sha(fixture_raw) != contract["fixture"]["sha256"]:
        raise QualificationFailure("fixture hash mismatch")

    before = snapshot()
    if before["rules"] or before["persisted_rules"] or before["streams"]:
        raise QualificationFailure("pre-existing realtime rule or stream state is not allowed")
    before_digests = state_digests(before)
    before_count, before_containers_sha = running_container_digest()

    sensor_id = str(uuid.uuid4())
    unknown_rule_id = str(uuid.uuid4())
    safe_run = re.sub(r"[^a-zA-Z0-9-]", "-", args.run_id)[:40]
    sensor_name = f"thor-incident-{safe_run}"
    category = f"thor_incident_{safe_run}"[:80]
    publish_url = f"{PUBLISH_ORIGIN}/{sensor_name}"
    input_url = f"{INPUT_ORIGIN}/{sensor_name}"
    publisher: subprocess.Popen[bytes] | None = None
    rule_id = ""
    stream_id = ""
    stream_owned = False
    control_ids: list[str] = []
    positive_count = 0
    all_bound_count = 0
    stable_ids = False
    evidence_references_bound = False
    every_bound_enforced = False
    unknown_rule_empty = False
    malformed_rule_rejected = False
    mutation_sequence: list[str] = []

    try:
        publisher = subprocess.Popen(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-re", "-stream_loop", "-1", "-i", str(fixture_path),
                "-an", "-c:v", "copy", "-f", "rtsp",
                "-rtsp_transport", "tcp", publish_url,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(1.5)
        if publisher.poll() is not None:
            raise QualificationFailure("owned RTSP publisher exited early")

        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
        create_status, create_body = request_json(
            f"{ALERT_ORIGIN}/api/v1/realtime",
            method="POST",
            body={
                "live_stream_url": input_url,
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "alert_type": category,
                "prompt": "Answer Yes. Is this a valid video segment?",
                "system_prompt": "Answer exactly Yes.",
                "chunk_duration": 4,
                "chunk_overlap_duration": 0,
                "num_frames_per_second_or_fixed_frames_chunk": 1,
                "use_fps_for_chunking": False,
                "vlm_input_width": 512,
                "vlm_input_height": 512,
                "enable_reasoning": False,
            },
            timeout=150,
        )
        mutation_sequence.append("POST /api/v1/realtime")
        if create_status != 201:
            raise QualificationFailure("owned realtime rule creation failed")
        rule_id = str(create_body.get("id", ""))
        try:
            uuid.UUID(rule_id)
        except ValueError as exc:
            raise QualificationFailure("rule creation returned no stable UUID") from exc
        stream_owned = True

        stream_status, stream_body = request_json(
            f"{RTVLM_ORIGIN}/v1/streams/get-stream-info"
        )
        if stream_status != 200:
            raise QualificationFailure("could not resolve owned RT-VLM stream identity")
        owned_streams = [
            item for item in streams_from(stream_body)
            if item.get("liveStreamUrl") == input_url
        ]
        if len(owned_streams) != 1 or not owned_streams[0].get("id"):
            raise QualificationFailure("owned RT-VLM stream identity was not unique")
        stream_id = str(owned_streams[0]["id"])
        try:
            uuid.UUID(stream_id)
        except ValueError as exc:
            raise QualificationFailure("RT-VLM returned no stable stream UUID") from exc

        generated = wait_for_rule_incident(rule_id)
        positive_count = len(generated)
        if not all(
            item.get("info", {}).get("alertRuleId") == rule_id
            and item.get("info", {}).get("streamId") == stream_id
            and item.get("sensorId") == sensor_id
            and item.get("category") == category
            for item in generated
        ):
            raise QualificationFailure("generated incident lost rule or stream identity")

        now = dt.datetime.now(dt.timezone.utc)
        current_index = f"mdx-vlm-incidents-{now.date().isoformat()}"
        old_time = iso(window_start - dt.timedelta(days=1))
        current_time = iso(now)
        controls = [
            ("wrong-stream", "other-stream", sensor_id, category, current_time),
            ("wrong-sensor", stream_id, "other-sensor", category, current_time),
            ("wrong-category", stream_id, sensor_id, "other-category", current_time),
            ("wrong-time", stream_id, sensor_id, category, old_time),
        ]
        for suffix, stream_value, sensor_value, category_value, timestamp in controls:
            doc_id = f"{safe_run}-{suffix}-{uuid.uuid4().hex}"
            control_ids.append(doc_id)
            put_control(current_index, doc_id, {
                "timestamp": timestamp,
                "end": timestamp,
                "sensorId": sensor_value,
                "category": category_value,
                "frameIds": [f"candidate-control-{suffix}"],
                "info": {
                    "alertRuleId": rule_id,
                    "streamId": stream_value,
                    "candidateControl": suffix,
                    "videoSource": f"candidate-evidence-{suffix}",
                },
            })
        mutation_sequence.append("PUT four owned Elasticsearch control incidents")

        window_end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5)
        status, body = query_incidents(
            alert_rule_id=rule_id,
            stream_id=stream_id,
            sensor_id=sensor_id,
            category=category,
            start_time=iso(window_start),
            end_time=iso(window_end),
            limit=100,
        )
        mutation_sequence.append("GET /api/v1/realtime/incidents all bounds")
        if status != 200 or body.get("count", 0) < 1:
            raise QualificationFailure("all-bound incident query returned no generated record")
        matched = body.get("incidents", [])
        if not isinstance(matched, list):
            raise QualificationFailure("unexpected incident response envelope")
        all_bound_count = len(matched)
        every_bound_enforced = all(
            item.get("info", {}).get("alertRuleId") == rule_id
            and item.get("info", {}).get("streamId") == stream_id
            and item.get("sensorId") == sensor_id
            and item.get("category") == category
            and not item.get("info", {}).get("candidateControl")
            for item in matched
        )
        stable_ids = all(
            isinstance(item.get("_id"), str) and item.get("_id")
            and isinstance(item.get("_index"), str) and item.get("_index")
            and item.get("info", {}).get("alertRuleId") == rule_id
            for item in matched
        )
        evidence_references_bound = all(
            isinstance(item.get("frameIds"), list) and item.get("frameIds")
            and isinstance(item.get("llm", {}).get("queries"), list)
            and item.get("llm", {}).get("queries")
            and "candidate-evidence-" not in canonical(item).decode()
            for item in matched
        )
        if not every_bound_enforced or not stable_ids or not evidence_references_bound:
            raise QualificationFailure("all-bound response violated identity or evidence contract")

        status, body = query_incidents(
            alert_rule_id=unknown_rule_id,
            stream_id=stream_id,
            sensor_id=sensor_id,
            category=category,
            start_time=iso(window_start),
            end_time=iso(window_end),
            limit=100,
        )
        unknown_rule_empty = status == 200 and body.get("count") == 0 and body.get("total") == 0
        if not unknown_rule_empty:
            raise QualificationFailure("unknown rule filter did not return an empty result")

        malformed_status, _ = query_incidents(alert_rule_id="not-a-uuid")
        malformed_rule_rejected = malformed_status == 422
        if not malformed_rule_rejected:
            raise QualificationFailure("malformed rule identity was not rejected")
    finally:
        if rule_id:
            try:
                delete_status, _ = request_json(
                    f"{ALERT_ORIGIN}/api/v1/realtime/{urllib.parse.quote(rule_id)}",
                    method="DELETE",
                    timeout=180,
                )
                if delete_status in (200, 404):
                    mutation_sequence.append("DELETE /api/v1/realtime/{owned-rule}")
                    stream_owned = False
            except Exception:
                pass
            try:
                delete_owned_incidents(rule_id)
                mutation_sequence.append("DELETE owned incident documents")
            except Exception:
                pass
        if stream_owned:
            try:
                cleanup_stream_id = stream_id or sensor_id
                request_json(
                    f"{RTVLM_ORIGIN}/v1/generate_captions/{urllib.parse.quote(cleanup_stream_id)}",
                    method="DELETE",
                    timeout=150,
                )
                request_json(
                    f"{RTVLM_ORIGIN}/v1/streams/delete/{urllib.parse.quote(cleanup_stream_id)}",
                    method="DELETE",
                    timeout=150,
                )
            except Exception:
                pass
        if publisher is not None and publisher.poll() is None:
            publisher.send_signal(signal.SIGINT)
            try:
                publisher.wait(timeout=10)
            except subprocess.TimeoutExpired:
                publisher.terminate()
                publisher.wait(timeout=5)

    after = snapshot()
    after_digests = state_digests(after)
    after_count, after_containers_sha = running_container_digest()
    if before_digests != after_digests:
        raise QualificationFailure("exact unrelated runtime state was not restored")
    if before_count != after_count or before_containers_sha != after_containers_sha:
        raise QualificationFailure("running container set changed")

    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms > MAX_DURATION_SECONDS * 1000:
        raise QualificationFailure("qualification exceeded its duration contract")
    receipt = {
        "schema_version": 1,
        "package_id": "realtime-alert-incident-retrieval-runtime-successor",
        "capability_id": "manifest-entry.realtime-alerts.04-incident-retrieval",
        "contract_sha256": sha(contract_raw),
        "status": "passed",
        "run": {
            "duration_ms": duration_ms,
            "fixture_bytes": len(fixture_raw),
            "fixture_sha256": sha(fixture_raw),
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
        },
        "retrieval": {
            "rule_identity_propagated": True,
            "generated_incident_count": positive_count,
            "control_incident_count": len(control_ids),
            "all_bound_result_count": all_bound_count,
            "all_filters_combined": every_bound_enforced,
            "stable_incident_and_rule_identity": stable_ids,
            "evidence_references_only_for_matching_records": evidence_references_bound,
            "unknown_rule_returns_empty": unknown_rule_empty,
            "malformed_rule_rejected": malformed_rule_rejected,
            "filter_names": [
                "alert_rule_id", "stream_id", "sensor_id", "category",
                "start_time", "end_time",
            ],
            "rule_identity_sha256": sha(rule_id),
            "stream_identity_sha256": sha(stream_id),
            "mutation_sequence": mutation_sequence,
        },
        "cleanup": {
            "exact_unrelated_state_restored": before_digests == after_digests,
            "before_sha256": before_digests,
            "after_sha256": after_digests,
            "owned_artifacts_absent": not any(
                token in canonical(after).decode()
                for token in (rule_id, stream_id, sensor_id, safe_run)
            ),
            "publisher_stopped": publisher is not None and publisher.poll() is not None,
            "running_container_set_preserved": before_containers_sha == after_containers_sha,
            "running_container_count": after_count,
        },
    }
    if not receipt["cleanup"]["owned_artifacts_absent"]:
        raise QualificationFailure("owned artifacts remain after cleanup")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(json.dumps(receipt, indent=2).encode() + b"\n")
    print(json.dumps({
        "package_id": receipt["package_id"],
        "status": receipt["status"],
        "duration_ms": duration_ms,
        "receipt_sha256": sha(output_path.read_bytes()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualificationFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
