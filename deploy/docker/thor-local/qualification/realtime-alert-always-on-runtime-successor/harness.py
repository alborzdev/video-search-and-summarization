#!/usr/bin/env python3
"""Exercise the deployed Thor always-on alert lifecycle with owned state."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
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


ACK = "I_AUTHORIZE_OWNED_REALTIME_ALWAYS_ON_AND_ALERT_BRIDGE_RESTART"
ALERT_ORIGIN = "http://127.0.0.1:9080"
RTVLM_ORIGIN = "http://127.0.0.1:8018"
ELASTIC_ORIGIN = "http://127.0.0.1:9200"
PUBLISH_ORIGIN = "rtsp://127.0.0.1:8554"
INPUT_ORIGIN = "rtsp://172.18.0.1:8554"
RULE_INDEX = "ab-alert-realtime-rules"
MAX_DURATION_SECONDS = 240


class QualificationFailure(RuntimeError):
    pass


def stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: stable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(stable(value), separators=(",", ":"), ensure_ascii=False).encode()


def sha(value: Any) -> str:
    raw = value if isinstance(value, bytes) else str(value).encode()
    return hashlib.sha256(raw).hexdigest()


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
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


def streams_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("results", "streams", "items", "data"):
            if isinstance(body.get(key), list):
                return body[key]
    raise QualificationFailure("unexpected RT-VLM stream-list envelope")


def rules_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("rules"), list):
        return body["rules"]
    raise QualificationFailure("unexpected Alert Bridge rule-list envelope")


def snapshot() -> dict[str, Any]:
    rules_status, rules_body = request_json(f"{ALERT_ORIGIN}/api/v1/realtime")
    streams_status, streams_body = request_json(
        f"{RTVLM_ORIGIN}/v1/streams/get-stream-info"
    )
    persisted_status, persisted_body = request_json(
        f"{ELASTIC_ORIGIN}/{RULE_INDEX}/_search?size=10000"
    )
    if rules_status != 200 or streams_status != 200 or persisted_status != 200:
        raise QualificationFailure("runtime snapshot endpoint failed")
    hits = persisted_body.get("hits", {}).get("hits", [])
    if not isinstance(hits, list):
        raise QualificationFailure("unexpected persisted-rule envelope")
    return {
        "rules": rules_from(rules_body),
        "streams": streams_from(streams_body),
        "persisted": hits,
    }


def unrelated_digest(items: list[dict[str, Any]], owned: set[str]) -> str:
    filtered = [
        item for item in items
        if not any(token and token in canonical(item).decode() for token in owned)
    ]
    filtered.sort(key=lambda item: canonical(item))
    return sha(canonical(filtered))


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


def rtvlm_worker_counts(sensor_id: str, since: str) -> tuple[int, int]:
    result = subprocess.run(
        ["docker", "logs", "--since", since, "vss-rtvi-vlm"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    logs = result.stdout + result.stderr
    quoted = re.escape(sensor_id)
    created = len(re.findall(
        rf"Created live stream query .* for videoId {quoted}", logs
    ))
    removed = len(re.findall(
        rf"Removed live stream {quoted} from pipeline for query", logs
    ))
    return created, removed


def wait_alert_health(timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = request_json(f"{ALERT_ORIGIN}/health", timeout=3)
            if status == 200 and body.get("status") == "ok":
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise QualificationFailure("Alert Bridge did not become healthy after restart")


def post_event(sensor_id: str, sensor_name: str, input_url: str, change: str):
    event: dict[str, Any] = {"camera_id": sensor_id, "change": change}
    if change == "camera_streaming":
        event.update({"camera_name": sensor_name, "camera_url": input_url})
    return request_json(
        f"{ALERT_ORIGIN}/api/v1/realtime/always-on",
        method="POST",
        body={
            "source": "vst",
            "alert_type": "camera_status_change",
            "event": event,
        },
        timeout=150,
    )


def assert_start(response: tuple[int, Any]) -> str:
    status, body = response
    details = body.get("details") if isinstance(body, dict) else None
    if (
        status != 200
        or body.get("reason") != "STREAM_ADD_SUCCESS"
        or not isinstance(details, list)
        or len(details) != 1
        or details[0].get("rule_id") != "thor_notable_activity"
        or details[0].get("alert_type") != "Notable Activity"
        or details[0].get("result") != "success"
        or details[0].get("status") != 201
    ):
        raise QualificationFailure("always-on start did not activate the declared rule")
    identity = details[0].get("alert_rule_id", "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", identity):
        raise QualificationFailure("always-on start returned no rule identity")
    return identity


def assert_duplicate(response: tuple[int, Any]) -> None:
    status, body = response
    if status != 200 or body.get("reason") != "STREAM_ADD_ALREADY_ACTIVE":
        raise QualificationFailure("duplicate camera event was not idempotent")
    if "details" in body:
        raise QualificationFailure("duplicate short-circuit unexpectedly fanned out")


def assert_worker_count(sensor_id: str, since: str, expected: int) -> tuple[int, int]:
    created, removed = rtvlm_worker_counts(sensor_id, since)
    if created - removed != expected:
        raise QualificationFailure(
            f"caption worker count mismatch: created={created} removed={removed}"
        )
    return created, removed


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

    started_monotonic = time.monotonic()
    since = dt.datetime.now(dt.timezone.utc).isoformat()
    contract_path = Path(args.contract).resolve()
    fixture_path = Path(args.fixture).resolve()
    output_path = Path(args.output).resolve()
    contract_raw = contract_path.read_bytes()
    contract = json.loads(contract_raw)
    if (
        contract.get("package_id") != "realtime-alert-always-on-runtime-successor"
        or contract.get("capability_id")
        != "manifest-entry.realtime-alerts.03-always-on-lifecycle"
    ):
        raise QualificationFailure("qualification contract identity mismatch")
    fixture_raw = fixture_path.read_bytes()
    if sha(fixture_raw) != contract["fixture"]["sha256"]:
        raise QualificationFailure("fixture hash mismatch")

    sensor_id = str(uuid.uuid4())
    safe_run = re.sub(r"[^a-zA-Z0-9-]", "-", args.run_id)[:48]
    sensor_name = f"thor-always-on-{safe_run}"
    publish_url = f"{PUBLISH_ORIGIN}/{sensor_name}"
    input_url = f"{INPUT_ORIGIN}/{sensor_name}"
    owned = {sensor_id, sensor_name, input_url}
    publisher: subprocess.Popen | None = None
    camera_active = False
    stream_added = False
    restart_performed = False

    before = snapshot()
    if before["rules"] or before["persisted"]:
        raise QualificationFailure("pre-existing realtime rules are not allowed")
    if any(item.get("id") == sensor_id for item in before["streams"]):
        raise QualificationFailure("owned sensor identity collision")
    before_count, before_running_sha = running_container_digest()
    before_digests = {
        "rules": unrelated_digest(before["rules"], owned),
        "persisted_rules": unrelated_digest(before["persisted"], owned),
        "rtvlm_streams": unrelated_digest(before["streams"], owned),
    }
    worker_created: list[int] = []
    worker_removed: list[int] = []
    first_rule_id = ""
    second_rule_id = ""
    mutation_sequence: list[str] = []
    lifecycle_stream_removed = False

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

        add_status, add_body = request_json(
            f"{RTVLM_ORIGIN}/v1/streams/add",
            method="POST",
            body={"streams": [{
                "id": sensor_id,
                "liveStreamUrl": input_url,
                "description": "owned always-on qualification fixture",
            }]},
            timeout=60,
        )
        mutation_sequence.append("POST /v1/streams/add")
        results = add_body.get("results", []) if isinstance(add_body, dict) else []
        errors = add_body.get("errors", []) if isinstance(add_body, dict) else []
        if add_status != 200 or errors or len(results) != 1 or results[0].get("id") != sensor_id:
            raise QualificationFailure("owned RT-VLM stream registration failed")
        stream_added = True

        first_rule_id = assert_start(
            post_event(sensor_id, sensor_name, input_url, "camera_streaming")
        )
        mutation_sequence.append("POST /api/v1/realtime/always-on camera_streaming")
        camera_active = True
        created, removed = assert_worker_count(sensor_id, since, 1)
        worker_created.append(created)
        worker_removed.append(removed)

        assert_duplicate(post_event(sensor_id, sensor_name, input_url, "camera_streaming"))
        mutation_sequence.append("POST /api/v1/realtime/always-on duplicate")
        created, removed = assert_worker_count(sensor_id, since, 1)
        worker_created.append(created)
        worker_removed.append(removed)

        subprocess.run(
            ["docker", "restart", "vss-alert-bridge"],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        mutation_sequence.append("docker restart vss-alert-bridge")
        restart_performed = True
        camera_active = False
        wait_alert_health()

        second_rule_id = assert_start(
            post_event(sensor_id, sensor_name, input_url, "camera_streaming")
        )
        mutation_sequence.append("POST /api/v1/realtime/always-on restart replay")
        camera_active = True
        created, removed = assert_worker_count(sensor_id, since, 1)
        if created != 2 or removed != 1:
            raise QualificationFailure("restart replay did not replace exactly one worker")
        worker_created.append(created)
        worker_removed.append(removed)

        assert_duplicate(post_event(sensor_id, sensor_name, input_url, "camera_streaming"))
        mutation_sequence.append("POST /api/v1/realtime/always-on duplicate after restart")
        created, removed = assert_worker_count(sensor_id, since, 1)
        worker_created.append(created)
        worker_removed.append(removed)

        remove_status, remove_body = post_event(
            sensor_id, sensor_name, input_url, "camera_remove"
        )
        mutation_sequence.append("POST /api/v1/realtime/always-on camera_remove")
        details = remove_body.get("details", []) if isinstance(remove_body, dict) else []
        if (
            remove_status != 200
            or remove_body.get("reason") != "STREAM_REMOVE_SUCCESS"
            or len(details) != 1
            or details[0].get("rule_id") != "thor_notable_activity"
            or details[0].get("result") != "success"
        ):
            raise QualificationFailure("camera_remove did not stop the declared rule")
        camera_active = False
        created, removed = assert_worker_count(sensor_id, since, 0)
        if created != 2 or removed != 2:
            raise QualificationFailure("camera_remove did not remove the replacement worker")
        worker_created.append(created)
        worker_removed.append(removed)

        _, streams_body = request_json(f"{RTVLM_ORIGIN}/v1/streams/get-stream-info")
        lifecycle_stream_removed = not any(
            item.get("id") == sensor_id for item in streams_from(streams_body)
        )
        if not lifecycle_stream_removed:
            raise QualificationFailure("camera_remove left the owned RT-VLM stream behind")
        stream_added = False
    finally:
        if camera_active:
            try:
                post_event(sensor_id, sensor_name, input_url, "camera_remove")
            except Exception:
                pass
        if stream_added:
            try:
                request_json(
                    f"{RTVLM_ORIGIN}/v1/generate_captions/{urllib.parse.quote(sensor_id)}",
                    method="DELETE",
                    timeout=150,
                )
                request_json(
                    f"{RTVLM_ORIGIN}/v1/streams/delete/{urllib.parse.quote(sensor_id)}",
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
    after_count, after_running_sha = running_container_digest()
    after_digests = {
        "rules": unrelated_digest(after["rules"], owned),
        "persisted_rules": unrelated_digest(after["persisted"], owned),
        "rtvlm_streams": unrelated_digest(after["streams"], owned),
    }
    owned_absent = (
        not any(token in canonical(after).decode() for token in owned)
        and first_rule_id not in canonical(after).decode()
        and second_rule_id not in canonical(after).decode()
    )
    if before_digests != after_digests or not owned_absent:
        raise QualificationFailure("exact unrelated runtime state was not restored")
    if before_count != after_count or before_running_sha != after_running_sha:
        raise QualificationFailure("Alert Bridge restart changed the running container set")
    final_created, final_removed = assert_worker_count(sensor_id, since, 0)

    duration_ms = round((time.monotonic() - started_monotonic) * 1000)
    if duration_ms > MAX_DURATION_SECONDS * 1000:
        raise QualificationFailure("qualification exceeded its duration contract")
    receipt = {
        "schema_version": 1,
        "package_id": "realtime-alert-always-on-runtime-successor",
        "capability_id": "manifest-entry.realtime-alerts.03-always-on-lifecycle",
        "contract_sha256": sha(contract_raw),
        "status": "passed",
        "run": {
            "duration_ms": duration_ms,
            "fixture_bytes": len(fixture_raw),
            "fixture_sha256": sha(fixture_raw),
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
        },
        "always_on": {
            "feature_flag_enabled": True,
            "declared_rule_count": 1,
            "declared_rule_exact": True,
            "initial_start_success": True,
            "duplicate_before_restart_idempotent": True,
            "alert_bridge_restart_performed": restart_performed,
            "restart_replay_success": True,
            "restart_replaced_worker_exactly_once": True,
            "duplicate_after_restart_idempotent": True,
            "process_scoped_rule_identity_rotated": first_rule_id != second_rule_id,
            "rule_identity_sha256": [sha(first_rule_id), sha(second_rule_id)],
            "stream_identity_sha256": sha(sensor_id),
            "worker_created_counts": worker_created,
            "worker_removed_counts": worker_removed,
            "one_caption_worker_after_each_start": True,
            "camera_remove_success": True,
            "lifecycle_stream_removed": lifecycle_stream_removed,
            "mutation_sequence": mutation_sequence,
        },
        "cleanup": {
            "exact_unrelated_state_restored": before_digests == after_digests,
            "before_sha256": before_digests,
            "after_sha256": after_digests,
            "owned_artifacts_absent": owned_absent,
            "publisher_stopped": publisher is not None and publisher.poll() is not None,
            "running_container_set_preserved": before_running_sha == after_running_sha,
            "running_container_count": after_count,
            "final_worker_created_count": final_created,
            "final_worker_removed_count": final_removed,
            "final_caption_worker_count": final_created - final_removed,
        },
    }
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
