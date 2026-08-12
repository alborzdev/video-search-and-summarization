#!/usr/bin/env python3
"""Qualify chunked dense captions and file summarization on Thor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
HELPER_PATH = (
    REPO
    / "deploy/docker/thor-local/qualification/lvs-recommended-config-runtime-successor/harness.py"
)
FILE_ID = "29629729-aaaa-4bbb-8ccc-296297296297"
FILENAME = "thor-rows296-297-caption-summary.mp4"
SENSOR_NAME = "thor-rows296-297-caption-summary"
FIXTURE = REPO / "services/alert/warmup/test.mp4"
MODEL = "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
MINIMUM_FREE_BYTES = 10 * 1024**3
CHUNK_DURATION = 3
VIDEO_DURATION = 10.0
CAPTION_PROMPT = (
    "Describe the worker's visible action in this segment. Specifically state whether "
    "the worker is carrying a box, walking toward the green rolling ladder, or climbing "
    "the ladder."
)
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("lvs_qualification_helper", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("qualification helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FILE_ID = FILE_ID
    module.FILENAME = FILENAME
    module.SENSOR_NAME = SENSOR_NAME
    return module


H = _load_helper()
QualificationError = H.QualificationError


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _has(value: str, *stems: str) -> bool:
    lowered = value.lower()
    return any(stem in lowered for stem in stems)


def caption_semantics(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if len(chunks) != 4:
        raise QualificationError("expected exactly four bounded caption chunks")
    intervals: list[list[float]] = []
    for chunk in chunks:
        if sorted(chunk) != ["content", "end_time", "reasoning_description", "start_time"]:
            raise QualificationError("caption response fields drifted")
        if not isinstance(chunk["content"], str) or not chunk["content"].strip():
            raise QualificationError("caption content is empty")
        try:
            start = float(chunk["start_time"])
            end = float(chunk["end_time"])
        except (TypeError, ValueError) as exc:
            raise QualificationError("caption interval is not numeric") from exc
        if not 0 <= start < end <= VIDEO_DURATION:
            raise QualificationError("caption interval is outside the fixture")
        intervals.append([start, end])
    expected = [[0.0, 3.0], [3.0, 6.0], [6.0, 9.0], [9.0, 10.0]]
    if intervals != expected:
        raise QualificationError(f"caption chronology drifted: {intervals}")
    first = chunks[0]["content"]
    last = chunks[-1]["content"]
    aggregate = "\n".join(chunk["content"] for chunk in chunks)
    first_event = (
        _has(first, "box", "boxes")
        and _has(first, "carry", "carrying", "hold", "holding", "walk")
    )
    last_event = _has(last, "ladder") and _has(last, "climb", "standing", "step", "shelf")
    absent_control = not _has(aggregate, "forklift", "fork lift")
    if not first_event or not last_event or not absent_control:
        raise QualificationError("caption semantic oracle failed")
    return {
        "chunk_count": len(chunks),
        "intervals": intervals,
        "chronological_and_contiguous": True,
        "first_event_carrying_box": True,
        "last_event_on_ladder_at_shelf": True,
        "absent_forklift_excluded": True,
        "content_sha256": [sha_bytes(chunk["content"].encode()) for chunk in chunks],
        "reasoning_fields_empty": all(not chunk["reasoning_description"] for chunk in chunks),
    }


def parse_summary(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise QualificationError("summary content is not JSON")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise QualificationError("summary JSON is invalid") from exc
    if not isinstance(value, dict) or sorted(value) != ["events", "video_summary"]:
        raise QualificationError("summary response keys drifted")
    summary = value["video_summary"]
    events = value["events"]
    if not isinstance(summary, str) or not isinstance(events, list) or len(events) != 2:
        raise QualificationError("summary event structure failed")
    if not (
        _has(summary, "worker")
        and _has(summary, "box", "boxes")
        and _has(summary, "ladder")
        and _has(summary, "carry", "carrying")
        and _has(summary, "climb", "climbing")
        and not _has(summary, "forklift", "fork lift")
    ):
        raise QualificationError("summary endpoint-event oracle failed")
    times: list[list[float]] = []
    for event in events:
        if not isinstance(event, dict):
            raise QualificationError("summary event is not an object")
        try:
            start = float(event["start_time"])
            end = float(event["end_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QualificationError("summary event interval is invalid") from exc
        if not isinstance(event.get("description"), str) or not isinstance(event.get("type"), str):
            raise QualificationError("summary event text is invalid")
        times.append([start, end])
    if not (times[0][0] == 0.0 and times[0][1] <= times[1][0] and times[1][1] == 10.0):
        raise QualificationError(f"summary chronology failed: {times}")
    event_text = "\n".join(f"{event['type']} {event['description']}" for event in events)
    if not (
        _has(event_text, "box", "boxes")
        and _has(event_text, "carry", "carrying")
        and _has(event_text, "ladder")
        and _has(event_text, "climb", "climbing")
        and not _has(event_text, "forklift", "fork lift")
    ):
        raise QualificationError("summary event details failed")
    return {
        "response_keys": sorted(value),
        "event_count": len(events),
        "event_intervals": times,
        "beginning_box_event_present": True,
        "ending_ladder_event_present": True,
        "absent_forklift_excluded": True,
        "chronological": True,
        "content_sha256": sha_bytes(content.encode()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", required=True)
    parser.add_argument("--output", type=Path, default=RECEIPT_PATH)
    args = parser.parse_args()
    expected_ack = "I_ACK_ONE_OWNED_LVS_FILE_AND_TWO_LOCAL_CAPTION_SUMMARY_REQUESTS"
    if args.ack != expected_ack:
        raise QualificationError(f"acknowledgement must equal {expected_ack}")
    started = time.monotonic()
    free_before = shutil.disk_usage(REPO).free
    if free_before < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor is not met")

    before_files = H.files()
    if any(item.get("id") == FILE_ID or item.get("filename") == FILENAME for item in before_files["data"]):
        raise QualificationError("owned LVS fixture already exists")
    password = H.graph_password()
    before_graph = H.graph_snapshot(password)
    if H.graph_owned_count(password):
        raise QualificationError("owned graph identity already exists")
    before_runtime = H.runtime_snapshot()
    before_running = H.running_containers()
    if not before_runtime["healthy"] or before_runtime["oom_killed"]:
        raise QualificationError("LVS runtime is not healthy")

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for lock in contract["source_locks"]:
        if H.sha_file(REPO / lock["path"]) != lock["sha256"]:
            raise QualificationError(f"host source lock drifted: {lock['path']}")
        if lock.get("container_path") and H.live_sha(lock["container_path"]) != lock["sha256"]:
            raise QualificationError(f"live source lock drifted: {lock['container_path']}")
    ready_status, _, _ = H.request("GET", "/v1/ready")
    models_status, models, _ = H.request("GET", "/models")
    if ready_status != 200 or models_status != 200:
        raise QualificationError("LVS is not ready")
    if [item.get("id") for item in models.get("data", [])] != [MODEL]:
        raise QualificationError("unexpected LVS model identity")

    file_added = False
    cleanup_failures: list[str] = []
    delete_status = 0
    caption_status = 0
    summary_status = 0
    caption_result: dict[str, Any] = {}
    summary_result: dict[str, Any] = {}
    caption_usage: dict[str, Any] = {}
    summary_usage: dict[str, Any] = {}
    caption_response_sha = ""
    summary_response_sha = ""
    try:
        upload_body, upload_type = H.multipart(FIXTURE.read_bytes())
        upload_status, uploaded, _ = H.request("POST", "/files", upload_body, upload_type, timeout=60)
        if (
            upload_status != 200
            or uploaded.get("id") != FILE_ID
            or uploaded.get("filename") != FILENAME
            or uploaded.get("sensor_name") != SENSOR_NAME
        ):
            raise QualificationError("owned file upload failed")
        file_added = True
        common = {
            "id": FILE_ID,
            "model": MODEL,
            "prompt": CAPTION_PROMPT,
            "chunk_duration": CHUNK_DURATION,
            "max_tokens": 128,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 1,
        }
        caption_status, captions, caption_raw = H.request(
            "POST", "/generate_vlm_captions", common, timeout=180
        )
        if caption_status != 200 or captions.get("model") != MODEL:
            raise QualificationError("chunked caption request failed")
        caption_result = caption_semantics(captions.get("chunk_responses", []))
        caption_usage = captions.get("usage", {})
        if caption_usage.get("total_chunks_processed") != 4:
            raise QualificationError("caption usage did not record four chunks")
        caption_response_sha = sha_bytes(caption_raw)

        summary_request = dict(common)
        summary_request.update({
            "scenario": "A warehouse worker moves a box and uses a green rolling ladder.",
            "events": ["worker carries a box", "worker climbs the green rolling ladder"],
            "objects_of_interest": ["worker", "box", "green rolling ladder"],
            "override_vlm_prompt": True,
            "enable_vlm_structured_output": False,
            "enable_qa": False,
        })
        summary_status, summary, summary_raw = H.request(
            "POST", "/v1/summarize", summary_request, timeout=180
        )
        try:
            content = summary["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise QualificationError("summary completion shape failed") from exc
        if summary_status != 200 or summary.get("model") != MODEL or summary.get("object") != "summarization.completion":
            raise QualificationError("file summary request failed")
        summary_result = parse_summary(content)
        summary_usage = summary.get("usage", {})
        if (
            summary_usage.get("total_chunks_processed") != 4
            or summary_usage.get("summary_requests") != 1
            or not isinstance(summary_usage.get("summary_tokens"), int)
            or summary_usage["summary_tokens"] <= 0
        ):
            raise QualificationError("summary usage did not prove aggregation")
        summary_response_sha = sha_bytes(summary_raw)
    finally:
        if file_added:
            try:
                delete_status, deleted, _ = H.request(
                    "DELETE", f"/files/{urllib.parse.quote(FILE_ID, safe='')}", timeout=120
                )
                if delete_status != 200 or deleted.get("deleted") is not True:
                    cleanup_failures.append("owned file deletion failed")
            except Exception as exc:
                cleanup_failures.append(f"owned file deletion: {type(exc).__name__}")

    after_files = H.files()
    after_graph = H.graph_snapshot(password)
    after_runtime = H.runtime_snapshot()
    after_running = H.running_containers()
    free_after = shutil.disk_usage(REPO).free
    if cleanup_failures:
        raise QualificationError("; ".join(cleanup_failures))
    if after_files != before_files or H.graph_owned_count(password) != 0 or after_graph != before_graph:
        raise QualificationError("LVS/graph baseline was not restored exactly")
    if after_runtime != before_runtime or after_running != before_running:
        raise QualificationError("runtime/container baseline changed")
    if free_after < MINIMUM_FREE_BYTES:
        raise QualificationError("free-space safety floor was crossed")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "passed",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "contract_sha256": H.sha_file(CONTRACT_PATH),
        "run": {
            "id_sha256": sha_bytes(f"thor-lvs-file-296-297-{time.time_ns()}".encode()),
            "duration_seconds": round(time.monotonic() - started, 6),
            "free_bytes_before": free_before,
            "free_bytes_after": free_after,
        },
        "runtime": {
            **after_runtime,
            "endpoint_loopback": True,
            "model": MODEL,
            "live_source_locks_exact": True,
        },
        "fixture": {
            "duration_seconds": VIDEO_DURATION,
            "sha256": H.sha_file(FIXTURE),
            "ground_truth": {
                "beginning": "worker_carries_box_across_foreground",
                "ending": "worker_on_green_ladder_at_shelf",
                "absent_control": "forklift",
            },
        },
        "chunked_dense_captions": {
            "route": "/generate_vlm_captions",
            "http_status": caption_status,
            "model": MODEL,
            "chunk_duration": CHUNK_DURATION,
            "response_sha256": caption_response_sha,
            "usage_total_chunks_processed": caption_usage["total_chunks_processed"],
            **caption_result,
        },
        "file_summarization": {
            "route": "/v1/summarize",
            "http_status": summary_status,
            "model": MODEL,
            "object": "summarization.completion",
            "chunk_duration": CHUNK_DURATION,
            "response_sha256": summary_response_sha,
            "usage_total_chunks_processed": summary_usage["total_chunks_processed"],
            "summary_requests": summary_usage["summary_requests"],
            "summary_tokens_positive": summary_usage["summary_tokens"] > 0,
            "aggregation_tokens_positive": summary_usage.get("aggregation_tokens", 0) > 0,
            **summary_result,
        },
        "cleanup": {
            "delete_status": delete_status,
            "file_catalog_before_sha256": sha_bytes(H.canonical(before_files)),
            "file_catalog_after_sha256": sha_bytes(H.canonical(after_files)),
            "file_catalog_restored_exactly": after_files == before_files,
            "graph_before": before_graph,
            "graph_after": after_graph,
            "graph_restored_exactly": after_graph == before_graph,
            "owned_graph_nodes_absent": H.graph_owned_count(password) == 0,
            "running_container_set_preserved": after_running == before_running,
            "runtime_state_preserved": after_runtime == before_runtime,
            "failures": cleanup_failures,
        },
        "policy": {
            "external_requests": 0,
            "agent_generate_calls": 0,
            "inference_api_requests": 2,
            "vios_or_rt_cv_stream_mutations": 0,
            "core_service_lifecycle_actions": 0,
            "warehouse_sample_bundle": "excluded",
            "raw_resource_ids_retained": False,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "credentials_retained": False,
        },
    }
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if UUID_PATTERN.search(rendered):
        raise QualificationError("receipt would retain a raw UUID")
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "official_indices": receipt["official_indices"],
        "receipt_sha256": H.sha_file(args.output),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
