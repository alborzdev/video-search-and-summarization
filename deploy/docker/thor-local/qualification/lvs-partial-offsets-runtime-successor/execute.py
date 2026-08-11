#!/usr/bin/env python3
"""Qualify LVS partial-video offset selection on the current Thor runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
ACK = "I_ACK_LVS_PARTIAL_OFFSETS_AND_EXACT_FILE_CLEANUP"
OWNERSHIP_NAMESPACE = UUID("fc075d21-72be-43ae-89a6-c9e8bd565e72")
sys.dont_write_bytecode = True


class QualificationError(RuntimeError):
    def __init__(self, code: str, detail: dict[str, Any] | None = None) -> None:
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(code)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("package_id") != "lvs-partial-offsets-runtime-successor"
        or contract.get("capability_id")
        != "manifest-entry.video-summarization-file.06-partial-video-offsets"
        or contract.get("acknowledgement") != ACK
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("endpoints") != {"lvs_origin": "http://127.0.0.1:38111"}
    ):
        raise QualificationError("configuration_error")
    if contract.get("positive_media_info") != {
        "type": "offset", "start_offset": 3, "end_offset": 6
    } or contract.get("negative_media_info") != {
        "type": "offset", "start_offset": 6, "end_offset": 3
    }:
        raise QualificationError("configuration_error")
    actions = contract.get("action_envelope")
    if not isinstance(actions, list) or len(actions) != 10 or [x.get("order") for x in actions] != list(range(1, 11)):
        raise QualificationError("configuration_error")
    if contract.get("execution_bounds", {}).get("max_http_requests") != 10:
        raise QualificationError("configuration_error")
    sources: dict[str, Path] = {}
    for lock in contract.get("source_locks", []):
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError("source_drift", {"source": lock["path"]})
        sources[lock["path"]] = path
    required = {
        "deploy/docker/thor-local/qualification/lvs-custom-schema-runtime-successor/execute.py",
        "deploy/docker/thor-local/qualification/lvs-focus-semantic-matrix-successor/executor.py",
        "services/video-summarization/src/via_server.py",
        "services/video-summarization/src/via_stream_handler.py",
        "services/video-summarization/src/vss_api_models.py",
        "services/video-summarization/api_spec/openapi.json",
        "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
    }
    if set(sources) != required:
        raise QualificationError("configuration_error")
    models_text = sources["services/video-summarization/src/vss_api_models.py"].read_text()
    handler_text = sources["services/video-summarization/src/via_stream_handler.py"].read_text()
    server_text = sources["services/video-summarization/src/via_server.py"].read_text()
    if not all(token in models_text for token in ("class MediaInfoOffset", "start_offset", "end_offset", "start_offset >= self.end_offset")):
        raise QualificationError("source_drift")
    if not all(token in handler_text for token in ("query.media_info.start_offset", "query.media_info.end_offset", "rtvi_media_info")):
        raise QualificationError("source_drift")
    if not all(token in server_text for token in ("MediaInfoOffset.for_response", '"media_info"')):
        raise QualificationError("source_drift")
    Draft202012Validator.check_schema(_load_json(RECEIPT_SCHEMA_PATH))
    base = _load_module("_lvs_offsets_base", sources["deploy/docker/thor-local/qualification/lvs-custom-schema-runtime-successor/execute.py"])
    focus = _load_module("_lvs_offsets_focus", sources["deploy/docker/thor-local/qualification/lvs-focus-semantic-matrix-successor/executor.py"])
    return {"base": base, "focus": focus}


def plan() -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "inert_offsets_plan_valid",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "actions": 0,
        "max_actions": 10,
        "writes_or_lifecycle_actions": False,
    }


def _generate_fixture(path: Path, deadline: float) -> bytes:
    filter_graph = (
        "drawbox=x=40+300*t:y=300:w=160:h=120:color=blue:t=fill:enable='between(t,0,2.999)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='BLUE MOVES OUTSIDE BEFORE':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=80:enable='between(t,0,2.999)',"
        "drawbox=x=40+300*(t-3):y=300:w=160:h=120:color=green:t=fill:enable='between(t,3,5.999)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='GREEN MOVES IN RANGE':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=80:enable='between(t,3,5.999)',"
        "drawbox=x=40+300*(t-6):y=300:w=160:h=120:color=red:t=fill:enable='gte(t,6)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='RED MOVES OUTSIDE AFTER':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=80:enable='gte(t,6)'"
    )
    command = [
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x20252b:s=1280x720:r=8:d=9",
        "-vf", filter_graph, "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
    ]
    try:
        result = subprocess.run(
            command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=min(60, max(1, deadline - time.monotonic())), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_unavailable") from exc
    if result.returncode != 0 or result.stdout:
        raise QualificationError("runtime_unavailable")
    raw = path.read_bytes()
    if len(raw) < 12 or raw[4:8] != b"ftyp":
        raise QualificationError("runtime_unavailable")
    return raw


def _request(identifier: str, model: str, media_info: dict[str, Any]) -> bytes:
    return _canonical(
        {
            "id": identifier,
            "model": model,
            "scenario": "color-coded moving-square timeline inspection",
            "events": ["green square moves across the frame"],
            "objects_of_interest": ["moving green square"],
            "media_info": media_info,
            "chunk_duration": 3,
            "num_frames_per_second_or_fixed_frames_chunk": 12,
            "use_fps_for_chunking": False,
            "enable_reasoning": False,
            "temperature": 0,
            "seed": 1,
        }
    )


def _json_response(base: Any, response: Any) -> dict[str, Any]:
    return base._json_response(response)


def _validate_positive(base: Any, response: Any, identifier: str, contract: dict[str, Any]) -> dict[str, Any]:
    value = _json_response(base, response)
    if response.status != 200 or value.get("video_id") != identifier or value.get("model") != contract["model_id"]:
        raise QualificationError("oracle_failed", {"stage": "envelope"})
    try:
        UUID(str(value.get("id")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("invalid_response") from exc
    if value.get("media_info") != contract["positive_media_info"]:
        raise QualificationError("oracle_failed", {"stage": "response_media_info"})
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise QualificationError("invalid_response")
    try:
        content = choices[0]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("invalid_response") from exc
    structured = base._decode(content.encode("utf-8"))
    if not isinstance(structured, dict) or set(structured) != {"events", "total_events", "uuids", "video_summary"}:
        raise QualificationError("invalid_response")
    events = structured["events"]
    if not isinstance(events, list) or not events or structured["total_events"] != len(events) or structured["uuids"] != [identifier]:
        uuids = structured.get("uuids")
        raise QualificationError(
            "oracle_failed",
            {
                "stage": "structured_content",
                "events_list": isinstance(events, list),
                "event_count": len(events) if isinstance(events, list) else None,
                "total_events_integer": type(structured.get("total_events")) is int,
                "total_events_correlated": isinstance(events, list)
                and structured.get("total_events") == len(events),
                "uuids_list": isinstance(uuids, list),
                "uuid_count": len(uuids) if isinstance(uuids, list) else None,
                "source_identity_correlated": uuids == [identifier],
            },
        )
    semantic_parts = [structured.get("video_summary")]
    starts: list[float] = []
    ends: list[float] = []
    for event in events:
        if not isinstance(event, dict):
            raise QualificationError("invalid_response")
        start, end = event.get("start_time"), event.get("end_time")
        if type(start) not in {int, float} or type(end) not in {int, float}:
            raise QualificationError("invalid_response")
        start_f, end_f = float(start), float(end)
        if not math.isfinite(start_f) or not math.isfinite(end_f) or not 3 <= start_f < end_f <= 6.5:
            raise QualificationError("oracle_failed", {"stage": "original_timeline"})
        starts.append(start_f)
        ends.append(end_f)
        semantic_parts.extend((event.get("type"), event.get("description")))
    if not all(isinstance(part, str) for part in semantic_parts):
        raise QualificationError("invalid_response")
    semantic = " ".join(semantic_parts).casefold()
    if "green" not in semantic or "blue" in semantic or "red" in semantic:
        raise QualificationError("oracle_failed", {"stage": "range_exclusion"})
    usage = value.get("usage")
    chunks = usage.get("total_chunks_processed") if isinstance(usage, dict) else None
    if type(chunks) is not int or chunks < 1:
        raise QualificationError("invalid_response")
    return {
        "http_status": 200,
        "response_sha256": _sha(response.body),
        "content_sha256": _sha(content),
        "event_count": len(events),
        "in_range_marker_present": True,
        "out_of_range_markers_absent": True,
        "original_timeline_timestamps": True,
        "minimum_event_start": min(starts),
        "maximum_event_end": max(ends),
        "media_info_exact": True,
        "source_identity_correlated": True,
        "chunks_processed": chunks,
    }


def _validate_negative(base: Any, response: Any) -> dict[str, Any]:
    value = _json_response(base, response)
    if (
        response.status != 422
        or not isinstance(value.get("code"), str)
        or not value["code"].strip()
        or not isinstance(value.get("message"), str)
        or not value["message"].strip()
    ):
        raise QualificationError("oracle_failed", {"stage": "reversed_range_negative"})
    return {
        "http_status": 422,
        "response_sha256": _sha(response.body),
        "json_parseable": True,
        "validation_error_envelope": True,
        "reversed_range_rejected": True,
    }


def execute(acknowledgement: str, transport: Any | None = None) -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    modules = _verify_static(contract)
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    if shutil.disk_usage(REPO).free < contract["execution_bounds"]["min_free_bytes"]:
        raise QualificationError("runtime_unavailable")
    base, focus = modules["base"], modules["focus"]
    started = time.monotonic()
    deadline = started + contract["execution_bounds"]["max_duration_seconds"]
    runtime_before = base._container_snapshot(contract, deadline)
    client = transport if transport is not None else focus.LiveTransport()
    identifier = str(uuid5(OWNERSHIP_NAMESPACE, contract["package_id"]))
    action_index = 0
    uploaded = False
    deleted = False
    pre_rows: list[dict[str, Any]] | None = None
    positive_result = None
    negative_result = None
    primary: BaseException | None = None
    cleanup_failed = False

    def call(method: str, path: str, *, template: str | None = None, body: bytes | None = None, content_type: str | None = None, timeout: float | None = None) -> Any:
        nonlocal action_index
        if action_index >= 10:
            raise QualificationError("oracle_failed")
        expected = contract["action_envelope"][action_index]
        if (method, template or path) != (expected["method"], expected["path"]):
            raise QualificationError("configuration_error")
        action_index += 1
        if body is not None and len(body) > contract["execution_bounds"]["max_request_bytes"]:
            raise QualificationError("configuration_error")
        try:
            return client.request(
                method=method,
                url=contract["endpoints"]["lvs_origin"] + path,
                headers={"Accept": "application/json", **({"Content-Type": content_type} if content_type else {})},
                body=body,
                timeout_seconds=float(timeout or contract["execution_bounds"]["short_timeout_seconds"]),
                max_response_bytes=contract["execution_bounds"]["max_response_bytes"],
            )
        except Exception as exc:
            raise QualificationError("transport_error") from exc

    def direct(method: str, path: str) -> Any:
        try:
            return client.request(
                method=method, url=contract["endpoints"]["lvs_origin"] + path,
                headers={"Accept": "application/json"}, body=None,
                timeout_seconds=float(contract["execution_bounds"]["short_timeout_seconds"]),
                max_response_bytes=contract["execution_bounds"]["max_response_bytes"],
            )
        except Exception as exc:
            raise QualificationError("transport_error") from exc

    with tempfile.TemporaryDirectory(prefix="vss-partial-offsets-") as temporary:
        fixture_path = Path(temporary) / "offset-phases.mp4"
        fixture = _generate_fixture(fixture_path, deadline)
        if _sha(fixture) != contract["fixture"]["sha256"] or len(fixture) > contract["execution_bounds"]["max_fixture_bytes"]:
            raise QualificationError("source_drift", {"stage": "fixture"})
        try:
            pre_rows = focus._file_list(_json_response(base, call("GET", "/files?purpose=vision", template="/files")))
            if identifier in {str(row["id"]) for row in pre_rows}:
                raise QualificationError("oracle_failed")
            if call("GET", "/v1/ready").status != 200:
                raise QualificationError("runtime_unavailable")
            models = _json_response(base, call("GET", "/models"))
            if not any(isinstance(row, dict) and row.get("id") == contract["model_id"] for row in models.get("data", [])):
                raise QualificationError("runtime_unavailable")
            boundary, multipart = focus._multipart(contract["package_id"], identifier, fixture_path.name, fixture)
            uploaded = True
            row = focus._file_row(_json_response(base, call("POST", "/files", body=multipart, content_type=f"multipart/form-data; boundary={boundary}")), True)
            if str(row["id"]) != identifier or row["bytes"] != len(fixture):
                raise QualificationError("oracle_failed")
            readback = focus._file_row(_json_response(base, call("GET", f"/files/{identifier}", template="/files/{owned_id}")), False)
            if str(readback["id"]) != identifier or readback["bytes"] != len(fixture):
                raise QualificationError("oracle_failed")
            positive_result = _validate_positive(
                base,
                call("POST", "/v1/summarize", body=_request(identifier, contract["model_id"], contract["positive_media_info"]), content_type="application/json", timeout=contract["execution_bounds"]["summarize_timeout_seconds"]),
                identifier,
                contract,
            )
            negative_result = _validate_negative(
                base,
                call("POST", "/v1/summarize", body=_request(identifier, contract["model_id"], contract["negative_media_info"]), content_type="application/json", timeout=contract["execution_bounds"]["short_timeout_seconds"]),
            )
        except BaseException as exc:
            primary = exc
        finally:
            normal = primary is None and action_index == 7
            if uploaded:
                try:
                    deletion = call("DELETE", f"/files/{identifier}", template="/files/{owned_id}") if normal else direct("DELETE", f"/files/{identifier}")
                    deleted = deletion.status == 200 and _json_response(base, deletion) == {"id": identifier, "object": "file", "deleted": True}
                    cleanup_failed |= not deleted
                except BaseException:
                    cleanup_failed = True
            try:
                post = call("GET", "/files?purpose=vision", template="/files") if normal else direct("GET", "/files?purpose=vision")
                post_rows = focus._file_list(_json_response(base, post))
                cleanup_failed |= pre_rows is None or _canonical(post_rows) != _canonical(pre_rows)
                ready = call("GET", "/v1/ready") if normal else direct("GET", "/v1/ready")
                cleanup_failed |= ready.status != 200
            except BaseException:
                cleanup_failed = True
        if cleanup_failed:
            raise QualificationError("cleanup_failed")
        if primary is not None:
            if isinstance(primary, QualificationError):
                raise primary
            raise QualificationError("oracle_failed") from primary
        if not deleted or action_index != 10 or positive_result is None or negative_result is None:
            raise QualificationError("oracle_failed")
    runtime_after = base._container_snapshot(contract, deadline)
    if _canonical(runtime_before) != _canonical(runtime_after):
        raise QualificationError("oracle_failed", {"stage": "runtime_changed"})
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(time.monotonic() - started, 6),
        "actions": action_index,
        "fixture": {"bytes": len(fixture), "sha256": _sha(fixture), "owned_id_sha256": _sha(identifier)},
        "runtime": {"before_sha256": _sha(_canonical(runtime_before)), "after_sha256": _sha(_canonical(runtime_after)), "unchanged": True, "healthy": True},
        "positive": positive_result,
        "negative": negative_result,
        "cleanup": {"owned_deleted": True, "owned_absent": True, "catalog_restored": True, "ready_after": True},
        "policy": {"agent_generate_calls": 0, "rt_cv_or_vios_stream_mutations": 0, "service_lifecycle_actions": 0, "raw_ids_retained": False, "raw_prompts_retained": False, "raw_semantic_output_retained": False, "warehouse_sample_bundle": "excluded"},
    }
    schema = _load_json(RECEIPT_SCHEMA_PATH)
    if list(Draft202012Validator(schema).iter_errors(receipt)):
        raise QualificationError("configuration_error")
    base._privacy_walk(receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    live = commands.add_parser("execute")
    live.add_argument("--ack", required=True)
    args = parser.parse_args(argv)
    try:
        value = plan() if args.command == "plan" else execute(args.ack)
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        failure = {"schema_version": 1, "status": "failed", "error_code": exc.code}
        if exc.detail:
            failure["detail"] = exc.detail
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
