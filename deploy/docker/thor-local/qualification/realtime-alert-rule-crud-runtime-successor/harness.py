#!/usr/bin/env python3
"""Qualify immutable realtime-alert rule CRUD/replacement on live Thor."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
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


ACK = "I_AUTHORIZE_OWNED_REALTIME_RULE_CRUD"
ALERT = "http://127.0.0.1:9080/api/v1/realtime"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
PUBLISH = "rtsp://127.0.0.1:8554"
INPUT = "rtsp://172.18.0.1:8554"
RULE_INDEX = "ab-alert-realtime-rules"
INCIDENT_INDEX = "mdx-vlm-incidents-*"
MAX_DURATION_SECONDS = 300
INTERNAL_FIELDS = {
    "_id", "_index", "_score", "owns_rtvi_stream", "rtvi_request_id",
    "rtvi_stream_id", "last_replay_at",
}


class QualificationFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


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
        return sorted(body["rules"], key=lambda item: str(item.get("id", "")))
    raise QualificationFailure("unexpected Alert Bridge rule-list envelope")


def streams_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = next(
            (body[key] for key in ("results", "streams", "items", "data")
             if isinstance(body.get(key), list)),
            None,
        )
    else:
        items = None
    if items is None:
        raise QualificationFailure("unexpected RT-VLM stream-list envelope")
    return sorted(items, key=lambda item: str(item.get("id", "")))


def es_hits(index: str) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC}/{index}/_search?allow_no_indices=true",
        method="POST",
        body={"size": 10000, "query": {"match_all": {}}},
    )
    if status != 200:
        raise QualificationFailure(f"Elasticsearch snapshot failed for {index}")
    hits = body.get("hits", {}).get("hits", [])
    if not isinstance(hits, list):
        raise QualificationFailure("unexpected Elasticsearch search envelope")
    return sorted(hits, key=lambda item: (str(item.get("_index", "")), str(item.get("_id", ""))))


def snapshot() -> dict[str, list[dict[str, Any]]]:
    rule_status, rule_body = request_json(ALERT)
    stream_status, stream_body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
    if rule_status != 200 or stream_status != 200:
        raise QualificationFailure("runtime snapshot endpoint failed")
    return {
        "rules": rules_from(rule_body),
        "streams": streams_from(stream_body),
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


def disk_free_bytes() -> int:
    return shutil.disk_usage("/").free


def rule_doc(rule_id: str) -> dict[str, Any]:
    status, body = request_json(
        f"{ELASTIC}/{RULE_INDEX}/_doc/{urllib.parse.quote(rule_id)}"
    )
    if status != 200 or not body.get("found") or not isinstance(body.get("_source"), dict):
        raise QualificationFailure("persisted rule document was not readable")
    return body["_source"]


def get_public_rule(rule_id: str) -> tuple[int, dict[str, Any] | None]:
    status, body = request_json(f"{ALERT}/{urllib.parse.quote(rule_id)}")
    rule = body.get("rule") if isinstance(body, dict) else None
    return status, rule if isinstance(rule, dict) else None


def incident_count(rule_id: str) -> int:
    status, body = request_json(
        f"{ELASTIC}/{INCIDENT_INDEX}/_count?allow_no_indices=true",
        method="POST",
        body={"query": {"term": {"info.alertRuleId.keyword": rule_id}}},
    )
    return int(body.get("count", 0)) if status == 200 else 0


def wait_for_incident(rule_id: str, request_id: str, timeout: float = 150) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    query = urllib.parse.urlencode({"alert_rule_id": rule_id, "limit": 100})
    while time.monotonic() < deadline:
        status, body = request_json(f"{ALERT}/incidents?{query}")
        incidents = body.get("incidents", []) if isinstance(body, dict) else []
        if status == 200 and isinstance(incidents, list):
            matching = [
                item for item in incidents
                if item.get("info", {}).get("requestId") == request_id
            ]
            if matching:
                return matching
        time.sleep(2)
    raise QualificationFailure("replacement rule produced no request-correlated incident")


def delete_owned_incidents(rule_ids: list[str]) -> int:
    if not rule_ids:
        return 0
    status, body = request_json(
        f"{ELASTIC}/{INCIDENT_INDEX}/_delete_by_query"
        "?refresh=true&conflicts=proceed&allow_no_indices=true",
        method="POST",
        body={"query": {"terms": {"info.alertRuleId.keyword": rule_ids}}},
        timeout=90,
    )
    if status != 200:
        raise QualificationFailure("owned incident cleanup failed")
    return int(body.get("deleted", 0))


def raw_index_name(stream_id: str) -> str:
    return "default_" + re.sub(r"[^a-z0-9]+", "_", stream_id.lower()).strip("_")


def index_exists(index: str) -> bool:
    status, _ = request_json(f"{ELASTIC}/{urllib.parse.quote(index)}", method="HEAD")
    return status == 200


def create_payload(
    *,
    stream_url: str,
    sensor_id: str,
    sensor_name: str,
    alert_type: str,
    prompt: str,
    system_prompt: str,
) -> dict[str, Any]:
    return {
        "live_stream_url": stream_url,
        "sensor_id": sensor_id,
        "sensor_name": sensor_name,
        "alert_type": alert_type,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "chunk_duration": 4,
        "chunk_overlap_duration": 0,
        "num_frames_per_second_or_fixed_frames_chunk": 1,
        "use_fps_for_chunking": False,
        "vlm_input_width": 512,
        "vlm_input_height": 512,
        "enable_reasoning": False,
    }


def assert_uuid(value: str, label: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise QualificationFailure(f"{label} was not a stable UUID") from exc


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
        contract.get("package_id") != "realtime-alert-rule-crud-runtime-successor"
        or contract.get("capability_id") != "manifest-entry.realtime-alerts.01-rule-crud"
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
    free_before = disk_free_bytes()

    safe_run = re.sub(r"[^a-zA-Z0-9-]", "-", args.run_id)[:36]
    sensor_id = str(uuid.uuid4())
    unknown_id = str(uuid.uuid4())
    sensor_name = f"thor-rule-crud-{safe_run}"
    publish_url = f"{PUBLISH}/{sensor_name}"
    input_url = f"{INPUT}/{sensor_name}"
    old_type = f"crud_old_{safe_run}"[:80]
    replacement_type = f"crud_replacement_{safe_run}"[:80]
    old_prompt = "Answer No. Is this replacement rule active?"
    replacement_prompt = "Answer Yes. Is this a valid replacement video segment?"
    old_payload = create_payload(
        stream_url=input_url,
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        alert_type=old_type,
        prompt=old_prompt,
        system_prompt="Answer exactly No.",
    )
    replacement_payload = create_payload(
        stream_url=input_url,
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        alert_type=replacement_type,
        prompt=replacement_prompt,
        system_prompt="Answer exactly Yes.",
    )

    publisher: subprocess.Popen[bytes] | None = None
    rule_ids: list[str] = []
    request_ids: list[str] = []
    stream_id = ""
    raw_index = ""
    raw_index_preexisting = False
    deleted_incidents = 0
    generated_incidents: list[dict[str, Any]] = []
    mutation_sequence: list[str] = []
    validation_state_preserved = False
    unknown_update_no_create = False
    public_internal_fields_hidden = False
    shared_stream_preserved = False
    replacement_active_after_old_delete = False
    repeated_delete_explicit_not_found = False
    old_absent_after_delete = False
    immutable_config_preserved = False

    try:
        invalid_source = dict(old_payload, live_stream_url="https://invalid.local/video")
        source_status, _ = request_json(ALERT, method="POST", body=invalid_source)
        invalid_prompt = dict(old_payload, prompt="   ")
        prompt_status, _ = request_json(ALERT, method="POST", body=invalid_prompt)
        patch_status, _ = request_json(
            f"{ALERT}/{unknown_id}", method="PATCH", body=replacement_payload
        )
        validation_state_preserved = state_digests(snapshot()) == before_digests
        unknown_update_no_create = patch_status in (404, 405) and validation_state_preserved
        if source_status != 422 or prompt_status != 422 or not unknown_update_no_create:
            raise QualificationFailure("prompt/source or unknown-update validation failed")
        mutation_sequence.extend([
            "POST invalid source rejected",
            "POST empty prompt rejected",
            "PATCH unknown rule rejected without create",
        ])

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

        create_status, create_body = request_json(
            ALERT, method="POST", body=old_payload, timeout=180
        )
        if create_status != 201:
            raise QualificationFailure("initial rule creation failed")
        old_id = str(create_body.get("id", ""))
        assert_uuid(old_id, "initial rule identity")
        rule_ids.append(old_id)
        mutation_sequence.append("POST initial immutable rule")

        get_status, old_public = get_public_rule(old_id)
        list_status, list_body = request_json(ALERT)
        listed = rules_from(list_body) if list_status == 200 else []
        if get_status != 200 or old_public is None or len(listed) != 1:
            raise QualificationFailure("initial rule read/list failed")
        if old_public.get("id") != old_id or listed[0].get("id") != old_id:
            raise QualificationFailure("initial rule identity changed across read/list")
        old_doc = rule_doc(old_id)
        old_request = str(old_doc.get("rtvi_request_id", ""))
        stream_id = str(old_doc.get("rtvi_stream_id", ""))
        assert_uuid(old_request, "initial RT-VLM request identity")
        assert_uuid(stream_id, "shared RT-VLM stream identity")
        request_ids.append(old_request)
        raw_index = raw_index_name(stream_id)
        raw_index_preexisting = index_exists(raw_index)
        if raw_index_preexisting:
            raise QualificationFailure("candidate raw-events index unexpectedly pre-existed")

        replacement_status, replacement_body = request_json(
            ALERT, method="POST", body=replacement_payload, timeout=180
        )
        if replacement_status != 201:
            raise QualificationFailure("replacement rule creation failed")
        replacement_id = str(replacement_body.get("id", ""))
        assert_uuid(replacement_id, "replacement rule identity")
        if replacement_id == old_id:
            raise QualificationFailure("replacement reused immutable rule identity")
        rule_ids.append(replacement_id)
        mutation_sequence.append("POST replacement immutable rule")

        replacement_get_status, replacement_public = get_public_rule(replacement_id)
        list_status, list_body = request_json(ALERT)
        listed = rules_from(list_body) if list_status == 200 else []
        replacement_doc = rule_doc(replacement_id)
        replacement_request = str(replacement_doc.get("rtvi_request_id", ""))
        replacement_stream = str(replacement_doc.get("rtvi_stream_id", ""))
        assert_uuid(replacement_request, "replacement RT-VLM request identity")
        request_ids.append(replacement_request)
        if replacement_request == old_request or replacement_stream != stream_id:
            raise QualificationFailure("replacement request/stream identity contract failed")
        stream_status, stream_body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
        owned_streams = [
            item for item in streams_from(stream_body)
            if item.get("id") == stream_id and item.get("liveStreamUrl") == input_url
        ] if stream_status == 200 else []
        if replacement_get_status != 200 or replacement_public is None or len(listed) != 2:
            raise QualificationFailure("replacement read/list failed")
        if len(owned_streams) != 1:
            raise QualificationFailure("replacement did not share exactly one RT-VLM stream")

        public_internal_fields_hidden = all(
            not (INTERNAL_FIELDS & set(item))
            for item in (old_public, replacement_public, *listed)
        )
        immutable_config_preserved = (
            old_public.get("id") == old_id
            and old_public.get("prompt") == old_prompt
            and old_public.get("alert_type") == old_type
            and replacement_public.get("id") == replacement_id
            and replacement_public.get("prompt") == replacement_prompt
            and replacement_public.get("alert_type") == replacement_type
            and old_public.get("created_at") == listed[0 if listed[0]["id"] == old_id else 1].get("created_at")
        )
        if not public_internal_fields_hidden or not immutable_config_preserved:
            raise QualificationFailure("public rule identity/config contract failed")

        delete_status, _ = request_json(
            f"{ALERT}/{old_id}", method="DELETE", timeout=180
        )
        mutation_sequence.append("DELETE superseded rule by immutable identity")
        if delete_status != 200:
            raise QualificationFailure("superseded rule delete failed")
        repeat_status, repeat_body = request_json(
            f"{ALERT}/{old_id}", method="DELETE", timeout=60
        )
        repeated_delete_explicit_not_found = (
            repeat_status == 404 and repeat_body.get("error") == "not_found"
        )
        old_get_status, _ = get_public_rule(old_id)
        old_absent_after_delete = old_get_status == 404
        list_status, list_body = request_json(ALERT)
        active = rules_from(list_body) if list_status == 200 else []
        stream_status, stream_body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
        owned_streams = [
            item for item in streams_from(stream_body) if item.get("id") == stream_id
        ] if stream_status == 200 else []
        shared_stream_preserved = len(owned_streams) == 1
        replacement_active_after_old_delete = (
            len(active) == 1
            and active[0].get("id") == replacement_id
            and shared_stream_preserved
        )
        if not all((
            repeated_delete_explicit_not_found,
            old_absent_after_delete,
            replacement_active_after_old_delete,
        )):
            raise QualificationFailure("delete/not-found/replacement continuity failed")

        generated_incidents = wait_for_incident(replacement_id, replacement_request)
        if not all(
            item.get("info", {}).get("alertRuleId") == replacement_id
            and item.get("info", {}).get("requestId") == replacement_request
            and item.get("info", {}).get("streamId") == stream_id
            and item.get("sensorId") == sensor_id
            and item.get("category") == replacement_type
            for item in generated_incidents
        ):
            raise QualificationFailure("replacement incident lost immutable correlation")
        mutation_sequence.append("GET replacement-correlated incident after old delete")

        replacement_delete, _ = request_json(
            f"{ALERT}/{replacement_id}", method="DELETE", timeout=180
        )
        if replacement_delete != 200:
            raise QualificationFailure("replacement cleanup delete failed")
        mutation_sequence.append("DELETE replacement rule")
    finally:
        for rule_id in reversed(rule_ids):
            try:
                request_json(f"{ALERT}/{rule_id}", method="DELETE", timeout=180)
            except Exception:
                pass
        time.sleep(4)
        try:
            deleted_incidents += delete_owned_incidents(rule_ids)
            for _ in range(3):
                if not any(incident_count(rule_id) for rule_id in rule_ids):
                    break
                time.sleep(2)
                deleted_incidents += delete_owned_incidents(rule_ids)
        except Exception:
            pass
        if raw_index and not raw_index_preexisting:
            try:
                request_json(f"{ELASTIC}/{urllib.parse.quote(raw_index)}", method="DELETE")
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
    if raw_index and index_exists(raw_index):
        raise QualificationFailure("owned raw-events index remains after cleanup")

    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms > MAX_DURATION_SECONDS * 1000:
        raise QualificationFailure("qualification exceeded its duration contract")
    receipt = {
        "schema_version": 1,
        "package_id": "realtime-alert-rule-crud-runtime-successor",
        "capability_id": "manifest-entry.realtime-alerts.01-rule-crud",
        "contract_sha256": sha(contract_raw),
        "status": "passed",
        "run": {
            "duration_ms": duration_ms,
            "fixture_bytes": len(fixture_raw),
            "fixture_sha256": sha(fixture_raw),
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
            "disk_free_before_bytes": free_before,
            "disk_free_after_bytes": disk_free_bytes(),
        },
        "lifecycle": {
            "prompt_source_validation": validation_state_preserved,
            "unknown_update_no_create": unknown_update_no_create,
            "replacement_semantics": "create-replacement-then-delete-old",
            "immutable_distinct_rule_ids": len(set(rule_ids)) == 2,
            "immutable_config_preserved": immutable_config_preserved,
            "public_internal_fields_hidden": public_internal_fields_hidden,
            "one_shared_stream": shared_stream_preserved,
            "distinct_request_ids": len(set(request_ids)) == 2,
            "replacement_active_after_old_delete": replacement_active_after_old_delete,
            "old_rule_absent_after_delete": old_absent_after_delete,
            "repeated_delete_explicit_not_found": repeated_delete_explicit_not_found,
            "replacement_incident_count": len(generated_incidents),
            "replacement_incident_correlated": True,
            "rule_identity_sha256": [sha(value) for value in rule_ids],
            "request_identity_sha256": [sha(value) for value in request_ids],
            "stream_identity_sha256": sha(stream_id),
            "old_config_sha256": sha(canonical(old_payload)),
            "replacement_config_sha256": sha(canonical(replacement_payload)),
            "mutation_sequence": mutation_sequence,
        },
        "cleanup": {
            "exact_unrelated_state_restored": before_digests == after_digests,
            "before_sha256": before_digests,
            "after_sha256": after_digests,
            "owned_incidents_deleted": deleted_incidents,
            "owned_raw_index_absent": not raw_index or not index_exists(raw_index),
            "owned_artifacts_absent": not any(
                token and token in canonical(after).decode()
                for token in (*rule_ids, *request_ids, stream_id, sensor_id, safe_run)
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
