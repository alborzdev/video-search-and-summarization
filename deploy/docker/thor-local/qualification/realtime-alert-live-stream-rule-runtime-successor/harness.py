#!/usr/bin/env python3
"""Qualify natural-language alert discrimination over one live RTSP stream."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


ACK = "I_AUTHORIZE_OWNED_LIVE_STREAM_VLM_RULE"
ALERT = "http://127.0.0.1:9080/api/v1/realtime"
RTVLM = "http://127.0.0.1:8018"
ELASTIC = "http://127.0.0.1:9200"
PUBLISH = "rtsp://127.0.0.1:8554"
INPUT = "rtsp://172.18.0.1:8554"
RULE_INDEX = "ab-alert-realtime-rules"
INCIDENT_INDEX = "mdx-vlm-incidents-*"
PHASE_SECONDS = 12
LOOP_SECONDS = 36


class QualificationFailure(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    timeout: float = 60,
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


def rules_from(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict) and isinstance(body.get("rules"), list):
        return sorted(body["rules"], key=lambda item: str(item.get("id", "")))
    raise QualificationFailure("unexpected realtime rule-list envelope")


def streams_from(body: Any) -> list[dict[str, Any]]:
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
    if rows is None:
        raise QualificationFailure("unexpected RT-VLM stream-list envelope")
    return sorted(rows, key=lambda item: str(item.get("id", "")))


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
    return sorted(
        hits,
        key=lambda item: (str(item.get("_index", "")), str(item.get("_id", ""))),
    )


def snapshot() -> dict[str, list[dict[str, Any]]]:
    rule_status, rule_body = request_json(ALERT)
    stream_status, stream_body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
    if rule_status != 200 or stream_status != 200:
        raise QualificationFailure("runtime snapshot endpoint failed")
    return {
        "rules": rules_from(rule_body),
        "persisted_rules": es_hits(RULE_INDEX),
        "streams": streams_from(stream_body),
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
    identities = sorted(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    return len(identities), sha(canonical(identities))


def verify_runtime_identity(contract: dict[str, Any]) -> dict[str, Any]:
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
            or row.get("RestartCount") != 0
        ):
            raise QualificationFailure(f"runtime identity drifted: {name}")
    checked = 0
    for lock in contract["source_locks"]:
        container = lock.get("container")
        destination = lock.get("container_path")
        if not container or not destination:
            continue
        result = subprocess.run(
            [
                "docker", "exec", container,
                lock.get("container_python", "/usr/bin/python3"),
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
        checked += 1
    return {
        "container_count": len(contract["runtime"]["containers"]),
        "container_images_exact": True,
        "containers_running": True,
        "restart_count_zero": True,
        "oom_killed_false": True,
        "live_source_count": checked,
        "live_sources_match_locks": True,
    }


def generate_fixture(path: Path) -> bytes:
    filter_graph = (
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x0040FF:t=fill:"
        "enable='between(t,0,11.999)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='BLUE':fontcolor=white:fontsize=180:"
        "x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,11.999)',"
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:"
        "enable='between(t,12,23.999)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='GREEN':fontcolor=black:fontsize=180:"
        "x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,12,23.999)',"
        "drawbox=x=0:y=0:w=iw:h=ih:color=0xFF0000:t=fill:"
        "enable='gte(t,24)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='RED':fontcolor=white:fontsize=180:"
        "x=(w-text_w)/2:y=(h-text_h)/2:enable='gte(t,24)'"
    )
    result = subprocess.run(
        [
            "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=8:d=36",
            "-vf", filter_graph, "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0 or result.stdout:
        raise QualificationFailure("deterministic fixture generation failed")
    raw = path.read_bytes()
    if len(raw) < 12 or raw[4:8] != b"ftyp":
        raise QualificationFailure("deterministic fixture is not MP4")
    return raw


def rule_doc(rule_id: str) -> dict[str, Any]:
    status, body = request_json(
        f"{ELASTIC}/{RULE_INDEX}/_doc/{urllib.parse.quote(rule_id)}"
    )
    source = body.get("_source") if isinstance(body, dict) else None
    if status != 200 or not isinstance(source, dict):
        raise QualificationFailure("persisted rule document was not readable")
    return source


def raw_index_name(stream_id: str) -> str:
    return "default_" + re.sub(r"[^a-z0-9]+", "_", stream_id.lower()).strip("_")


def index_exists(index: str) -> bool:
    status, _ = request_json(
        f"{ELASTIC}/{urllib.parse.quote(index)}", method="HEAD"
    )
    return status == 200


def raw_windows(index: str, request_id: str) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC}/{index}/_search?allow_no_indices=true",
        method="POST",
        body={"size": 100, "query": {"match_all": {}}},
    )
    if status != 200:
        return []
    rows = [
        hit.get("_source", {})
        for hit in body.get("hits", {}).get("hits", [])
        if hit.get("_source", {})
        .get("metadata", {})
        .get("content_metadata", {})
        .get("requestId")
        == request_id
    ]
    return sorted(
        rows,
        key=lambda row: int(
            row.get("metadata", {}).get("content_metadata", {}).get("chunkIdx", -1)
        ),
    )


def rule_incidents(rule_id: str) -> list[dict[str, Any]]:
    status, body = request_json(
        f"{ELASTIC}/{INCIDENT_INDEX}/_search?allow_no_indices=true",
        method="POST",
        body={
            "size": 100,
            "query": {"term": {"info.alertRuleId.keyword": rule_id}},
        },
    )
    if status != 200:
        return []
    return [hit.get("_source", {}) for hit in body.get("hits", {}).get("hits", [])]


def delete_owned_incidents(rule_id: str) -> int:
    status, body = request_json(
        f"{ELASTIC}/{INCIDENT_INDEX}/_delete_by_query"
        "?refresh=true&conflicts=proceed&allow_no_indices=true",
        method="POST",
        body={"query": {"term": {"info.alertRuleId.keyword": rule_id}}},
        timeout=90,
    )
    if status != 200:
        raise QualificationFailure("owned incident cleanup failed")
    return int(body.get("deleted", 0))


def answer_is_match(text: Any) -> bool | None:
    token = str(text or "").strip().casefold().rstrip(".! ")
    if token == "yes":
        return True
    if token == "no":
        return False
    return None


def cyclically_contiguous(indices: list[int], cycle_size: int) -> bool:
    if not indices:
        return False
    values = set(indices)
    return any(
        values == {(start + offset) % cycle_size for offset in range(len(values))}
        for start in range(cycle_size)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.ack != ACK:
        raise QualificationFailure("explicit acknowledgement is required")

    contract_path = Path(args.contract).resolve()
    output_path = Path(args.output).resolve()
    contract_raw = contract_path.read_bytes()
    contract = json.loads(contract_raw)
    if (
        contract.get("package_id")
        != "realtime-alert-live-stream-rule-runtime-successor"
        or contract.get("capability_id")
        != "manifest-entry.realtime-alerts.00-live-stream-vlm-rules"
        or contract.get("official_indices") != [328]
    ):
        raise QualificationFailure("qualification contract identity mismatch")
    repo = Path(__file__).resolve().parents[5]
    for lock in contract["source_locks"]:
        source = repo / lock["path"]
        if not source.is_file() or source.is_symlink() or sha(source.read_bytes()) != lock["sha256"]:
            raise QualificationFailure(f"source lock drifted: {lock['path']}")
    ffmpeg = Path(contract["fixture"]["ffmpeg_path"])
    if (
        not ffmpeg.is_file()
        or ffmpeg.is_symlink()
        or sha(ffmpeg.read_bytes()) != contract["fixture"]["ffmpeg_sha256"]
    ):
        raise QualificationFailure("host ffmpeg lock drifted")
    runtime_identity = verify_runtime_identity(contract)
    if shutil.disk_usage("/").free < contract["execution"]["minimum_free_bytes"]:
        raise QualificationFailure("disk free-space floor is not satisfied")

    started = time.monotonic()
    before = snapshot()
    if before["rules"] or before["persisted_rules"] or before["streams"]:
        raise QualificationFailure("pre-existing realtime rule or stream state is not allowed")
    before_digests = state_digests(before)
    before_count, before_containers_sha = running_container_digest()
    free_before = shutil.disk_usage("/").free

    safe_run = re.sub(r"[^a-zA-Z0-9-]", "-", args.run_id)[:36]
    sensor_id = str(uuid.uuid4())
    sensor_name = f"thor-live-rule-{safe_run}"
    publish_url = f"{PUBLISH}/{sensor_name}"
    input_url = f"{INPUT}/{sensor_name}"
    alert_type = f"green_square_{safe_run}"[:80]
    prompt = "Is the dominant full-frame background color green? Answer exactly Yes or No."
    system_prompt = (
        "Inspect only the current video window. Answer exactly Yes if the "
        "dominant full-frame background is green. Answer exactly No if it is blue or red."
    )
    payload = {
        "live_stream_url": input_url,
        "sensor_id": sensor_id,
        "sensor_name": sensor_name,
        "alert_type": alert_type,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "chunk_duration": 4,
        "chunk_overlap_duration": 0,
        "num_frames_per_second_or_fixed_frames_chunk": 3,
        "use_fps_for_chunking": False,
        "vlm_input_width": 512,
        "vlm_input_height": 512,
        "enable_reasoning": False,
        "temperature": 0.0,
        "seed": 17,
    }

    publisher: subprocess.Popen[bytes] | None = None
    rule_id = ""
    request_id = ""
    stream_id = ""
    raw_index = ""
    raw_preexisting = False
    fixture_raw = b""
    observed_matches: list[bool] = []
    raw_rows: list[dict[str, Any]] = []
    positive_chunks: list[int] = []
    negative_chunks: list[int] = []
    incidents: list[dict[str, Any]] = []
    deleted_incidents = 0
    primary: BaseException | None = None

    with tempfile.TemporaryDirectory(prefix="vss-live-stream-rule-") as temp_dir:
        fixture_path = Path(temp_dir) / "timeline.mp4"
        fixture_raw = generate_fixture(fixture_path)
        if (
            len(fixture_raw) != contract["fixture"]["bytes"]
            or sha(fixture_raw) != contract["fixture"]["sha256"]
        ):
            raise QualificationFailure("deterministic fixture contract drifted")
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
            time.sleep(2)
            if publisher.poll() is not None:
                raise QualificationFailure("owned RTSP publisher exited early")

            create_status, create_body = request_json(
                ALERT, method="POST", body=payload, timeout=180,
            )
            if create_status != 201:
                raise QualificationFailure(f"live rule creation returned {create_status}")
            rule_id = str(create_body.get("id", ""))
            uuid.UUID(rule_id)
            persisted = rule_doc(rule_id)
            request_id = str(persisted.get("rtvi_request_id", ""))
            stream_id = str(persisted.get("rtvi_stream_id", ""))
            uuid.UUID(request_id)
            uuid.UUID(stream_id)
            raw_index = raw_index_name(stream_id)
            raw_preexisting = index_exists(raw_index)
            if raw_preexisting:
                raise QualificationFailure("owned raw-events index unexpectedly pre-existed")

            deadline = time.monotonic() + contract["execution"]["window_wait_seconds"]
            while time.monotonic() < deadline:
                candidates = [
                    row
                    for row in raw_windows(raw_index, request_id)
                    if answer_is_match(row.get("text")) is not None
                ]
                by_chunk = {
                    int(row["metadata"]["content_metadata"]["chunkIdx"]): row
                    for row in candidates
                }
                required = contract["execution"]["minimum_raw_windows"]
                if all(index in by_chunk for index in range(required)):
                    raw_rows = [by_chunk[index] for index in range(required)]
                    break
                time.sleep(3)

            for row in raw_rows:
                observed = answer_is_match(row.get("text"))
                if observed is None:
                    raise QualificationFailure("live visual-window answer was not boolean")
                observed_matches.append(observed)
            if (
                len(observed_matches) != contract["execution"]["minimum_raw_windows"]
                or sum(observed_matches) != contract["execution"]["expected_positive_windows"]
            ):
                raise QualificationFailure("live visual-window discrimination drifted")

            positive_positions = [
                position for position, match in enumerate(observed_matches) if match
            ]
            if not cyclically_contiguous(positive_positions, len(observed_matches)):
                raise QualificationFailure("positive windows did not match one visual phase")
            raw_flags = [
                row["metadata"]["content_metadata"].get("incidentDetected") == "true"
                for row in raw_rows
            ]
            if raw_flags != observed_matches:
                raise QualificationFailure("non-matching raw window emitted an alert")
            positive_chunks = sorted(
                int(row["metadata"]["content_metadata"]["chunkIdx"])
                for row, match in zip(raw_rows, observed_matches)
                if match
            )
            negative_chunks = sorted(
                int(row["metadata"]["content_metadata"]["chunkIdx"])
                for row, match in zip(raw_rows, observed_matches)
                if not match
            )
            incident_deadline = time.monotonic() + 30
            incident_chunks: list[int] = []
            while time.monotonic() < incident_deadline:
                incidents = rule_incidents(rule_id)
                incident_chunks = sorted(
                    int(item.get("info", {}).get("chunkIdx", -1))
                    for item in incidents
                )
                if set(positive_chunks).issubset(incident_chunks):
                    break
                time.sleep(2)
            if (
                incident_chunks != positive_chunks
            ):
                raise QualificationFailure("incident chunks did not match visual phase")
            if not all(
                item.get("info", {}).get("alertRuleId") == rule_id
                and item.get("info", {}).get("requestId") == request_id
                and item.get("info", {}).get("streamId") == stream_id
                and item.get("sensorId") == sensor_id
                and item.get("category") == alert_type
                for item in incidents
            ):
                raise QualificationFailure("matching incident correlation drifted")
        except BaseException as exc:
            primary = exc
        finally:
            if rule_id:
                try:
                    request_json(f"{ALERT}/{rule_id}", method="DELETE", timeout=180)
                except Exception:
                    pass
            time.sleep(4)
            if rule_id:
                for _ in range(3):
                    try:
                        deleted_incidents += delete_owned_incidents(rule_id)
                    except Exception:
                        pass
                    if not rule_incidents(rule_id):
                        break
                    time.sleep(2)
            if raw_index and not raw_preexisting:
                try:
                    request_json(
                        f"{ELASTIC}/{urllib.parse.quote(raw_index)}", method="DELETE"
                    )
                except Exception:
                    pass
            try:
                _, stream_body = request_json(f"{RTVLM}/v1/streams/get-stream-info")
                for row in streams_from(stream_body):
                    if row.get("id") == sensor_id or row.get("liveStreamUrl") == input_url:
                        request_json(
                            f"{RTVLM}/v1/streams/delete/{row['id']}",
                            method="DELETE",
                            timeout=60,
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
    cleanup_ok = (
        before_digests == after_digests
        and before_count == after_count
        and before_containers_sha == after_containers_sha
        and (not raw_index or not index_exists(raw_index))
    )
    if not cleanup_ok:
        raise QualificationFailure("exact unrelated runtime state was not restored")
    if primary is not None:
        if isinstance(primary, QualificationFailure):
            raise primary
        raise QualificationFailure("live rule oracle failed") from primary

    duration_ms = round((time.monotonic() - started) * 1000)
    if duration_ms > contract["execution"]["maximum_duration_ms"]:
        raise QualificationFailure("qualification exceeded its duration contract")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "contract_sha256": sha(contract_raw),
        "status": "passed",
        "run": {
            "duration_ms": duration_ms,
            "fixture_bytes": len(fixture_raw),
            "fixture_sha256": sha(fixture_raw),
            "numeric_local_endpoints_only": True,
            "agent_generate_request_count": 0,
            "disk_free_before_bytes": free_before,
            "disk_free_after_bytes": shutil.disk_usage("/").free,
        },
        "runtime_identity": runtime_identity,
        "window_oracle": {
            "bounded_window_seconds": 4,
            "raw_window_count": len(raw_rows),
            "complete_visual_cycle_seconds": LOOP_SECONDS,
            "visual_phase_seconds": PHASE_SECONDS,
            "expected_positive_window_count": 3,
            "expected_negative_window_count": 6,
            "observed_match_sequence": observed_matches,
            "positive_window_indices": positive_chunks,
            "negative_window_indices": negative_chunks,
            "positive_windows_cyclically_contiguous": True,
            "positive_window_count": sum(observed_matches),
            "negative_window_count": len(observed_matches) - sum(observed_matches),
            "raw_incident_flags_match_verdicts": True,
            "incident_count": len(incidents),
            "incident_window_indices": positive_chunks,
            "no_negative_window_emitted_alert": True,
            "only_matching_windows_emitted_alerts": True,
            "rule_stream_request_incident_correlated": True,
            "rule_identity_sha256": sha(rule_id),
            "request_identity_sha256": sha(request_id),
            "stream_identity_sha256": sha(stream_id),
            "prompt_configuration_sha256": sha(canonical(payload)),
        },
        "cleanup": {
            "exact_unrelated_state_restored": True,
            "before_sha256": before_digests,
            "after_sha256": after_digests,
            "owned_incidents_deleted": deleted_incidents,
            "owned_raw_index_absent": not raw_index or not index_exists(raw_index),
            "owned_artifacts_absent": not any(
                token and token in canonical(after).decode()
                for token in (rule_id, request_id, stream_id, sensor_id, safe_run)
            ),
            "publisher_stopped": publisher is not None and publisher.poll() is not None,
            "running_container_set_preserved": before_containers_sha == after_containers_sha,
            "running_container_count": after_count,
        },
    }
    if not all(
        (
            receipt["cleanup"]["owned_artifacts_absent"],
            receipt["cleanup"]["publisher_stopped"],
            receipt["cleanup"]["owned_raw_index_absent"],
        )
    ):
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
        print(json.dumps({"status": "failed", "error": str(exc)}))
        raise SystemExit(1)
