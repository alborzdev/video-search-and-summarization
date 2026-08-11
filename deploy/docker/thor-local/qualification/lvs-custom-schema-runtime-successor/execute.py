#!/usr/bin/env python3
"""Qualify LVS custom JSON-schema output on the current local Thor runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import stat
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
ACK = "I_ACK_LVS_CUSTOM_SCHEMA_AND_EXACT_FILE_CLEANUP"
OWNERSHIP_NAMESPACE = UUID("60ad24c4-a1ad-4ae7-9b23-41c62ee68030")
MAX_STATIC_BYTES = 128 * 1024 * 1024
sys.dont_write_bytecode = True


class QualificationError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_response",
        "oracle_failed",
        "runtime_unavailable",
        "source_drift",
        "transport_error",
    }

    def __init__(self, code: str, *, detail: dict[str, Any] | None = None) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        self.detail = dict(detail or {})
        super().__init__(self.code)


def _sha(raw: bytes | str) -> str:
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc


def _decode(raw: bytes, code: str = "invalid_response") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise QualificationError(code)
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                QualificationError(code)
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(code) from exc


def _read_regular(path: Path, maximum: int = MAX_STATIC_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise QualificationError("configuration_error")
        raw = b""
        while len(raw) <= maximum:
            piece = os.read(descriptor, min(131072, maximum + 1 - len(raw)))
            if not piece:
                break
            raw += piece
        after = os.fstat(descriptor)
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key)
            for key in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise QualificationError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _repo_file(relative: str, expected_sha: str) -> tuple[Path, bytes]:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise QualificationError("configuration_error")
    current = REPO
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise QualificationError("configuration_error")
        except OSError as exc:
            raise QualificationError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(REPO)
    except (OSError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    raw = _read_regular(current)
    if _sha(raw) != expected_sha:
        raise QualificationError("source_drift")
    return current, raw


def _contract() -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(CONTRACT_PATH)
    value = _decode(raw, "configuration_error")
    if not isinstance(value, dict):
        raise QualificationError("configuration_error")
    return value, raw


def _load_focus(contract: dict[str, Any]) -> Any:
    lock = next(
        row
        for row in contract["source_locks"]
        if row["path"].endswith("lvs-focus-semantic-matrix-successor/executor.py")
    )
    path, _raw = _repo_file(lock["path"], lock["sha256"])
    spec = importlib.util.spec_from_file_location("_lvs_schema_focus_base", path)
    if spec is None or spec.loader is None:
        raise QualificationError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise QualificationError("configuration_error") from exc
    return module


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema_version", "package_id", "capability_id", "advertised_literal",
        "product_version", "acknowledgement", "default_execution_enabled",
        "warehouse_sample_bundle", "endpoints", "model_id", "required_semantics",
        "positive_schema", "negative_schema", "containers", "action_envelope",
        "execution_bounds", "source_locks", "privacy",
    }
    if set(contract) != expected_keys:
        raise QualificationError("configuration_error")
    if (
        contract["schema_version"] != 1
        or contract["package_id"] != "lvs-custom-schema-runtime-successor"
        or contract["capability_id"]
        != "manifest-entry.video-summarization-file.03-structured-output"
        or contract["advertised_literal"] != "structured output"
        or contract["product_version"] != "3.2.1"
        or contract["acknowledgement"] != ACK
        or contract["default_execution_enabled"] is not False
        or contract["warehouse_sample_bundle"] != "excluded"
        or contract["endpoints"] != {"lvs_origin": "http://127.0.0.1:38111"}
        or contract["model_id"]
        != "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
    ):
        raise QualificationError("configuration_error")
    actions = contract["action_envelope"]
    if (
        not isinstance(actions, list)
        or len(actions) != 10
        or [row.get("order") for row in actions] != list(range(1, 11))
        or contract["execution_bounds"]
        != {
            "max_http_requests": 10,
            "max_duration_seconds": 900,
            "max_fixture_bytes": 8388608,
            "max_request_bytes": 10485760,
            "max_response_bytes": 4194304,
            "short_timeout_seconds": 20,
            "summarize_timeout_seconds": 300,
            "min_free_bytes": 10737418240,
            "service_lifecycle": "forbidden",
            "model_staging": "forbidden",
            "network_scope": "numeric-loopback-only",
        }
        or contract["privacy"]
        != {
            "retain_raw_resource_ids": False,
            "retain_raw_prompts": False,
            "retain_raw_semantic_output": False,
            "retain_response_hashes": True,
        }
    ):
        raise QualificationError("configuration_error")
    locks = contract["source_locks"]
    if not isinstance(locks, list) or len(locks) != 5:
        raise QualificationError("configuration_error")
    sources: dict[str, bytes] = {}
    for row in locks:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise QualificationError("configuration_error")
        _path, sources[row["path"]] = _repo_file(row["path"], row["sha256"])
    handler = sources["services/video-summarization/src/via_stream_handler.py"].decode()
    models = sources["services/video-summarization/src/vss_api_models.py"].decode()
    openapi = sources["services/video-summarization/api_spec/openapi.json"].decode()
    if not all(
        token in handler
        for token in (
            '] = "structured_inference"',
            '"prompts", {"caption": ""}',
            "def _use_db_caption_aggregation",
            "requires start_index/end_index",
        )
    ) or not all(
        token in models
        for token in (
            "class SummarizationQuery",
            "schema:",
            "batch_response_method:",
            "auto_generate_prompt:",
            "enable_vlm_structured_output:",
        )
    ) or '"/v1/summarize"' not in openapi:
        raise QualificationError("source_drift")
    Draft202012Validator.check_schema(_decode(_read_regular(RECEIPT_SCHEMA_PATH), "configuration_error"))
    return {"focus": _load_focus(contract)}


def plan() -> dict[str, Any]:
    contract, raw = _contract()
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "passed",
        "contract_sha256": _sha(raw),
        "actions": 0,
        "max_actions": 10,
        "writes_or_lifecycle_actions": False,
        "acknowledgement_required": True,
        "warehouse_sample_bundle": "excluded",
    }


def _schema(marker_values: list[str]) -> str:
    schema = {
        "title": "ThorCustomEventExtraction",
        "description": "Extract custom timestamped events",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "title": "ThorCustomEvent",
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "start_time": {"type": "number"},
                        "end_time": {"type": "number"},
                        "description": {"type": "string"},
                        "type": {"type": "string"},
                        "schema_marker": {"type": "string", "enum": marker_values},
                    },
                    "required": [
                        "start_time", "end_time", "description", "type",
                        "schema_marker",
                    ],
                },
            }
        },
        "required": ["events"],
    }
    Draft202012Validator.check_schema(schema)
    return _canonical(schema).decode("ascii")


def _request(identifier: str, model: str, schema: str) -> bytes:
    return _canonical(
        {
            "id": identifier,
            "model": model,
            "scenario": "general observation",
            "events": ["visible object movement"],
            "objects_of_interest": ["amber crate"],
            "schema": schema,
            "batch_response_method": "json_schema",
            "auto_generate_prompt": False,
            "override_vlm_prompt": False,
            "enable_vlm_structured_output": False,
            "chunk_duration": 10,
            "num_frames_per_second_or_fixed_frames_chunk": 20,
            "use_fps_for_chunking": False,
            "temperature": 0,
            "seed": 1,
        }
    )


def _generate_fixture(path: Path, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QualificationError("runtime_unavailable")
    filter_graph = (
        "[0:v][1:v]overlay=x='100+60*t':y=260:shortest=1,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='VISIBLE OBJECT MOVEMENT':fontcolor=white:fontsize=42:x=35:y=40,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='AMBER CRATE MOVES ACROSS FRAME':fontcolor=0xffd080:fontsize=36:x=35:y=100[v]"
    )
    command = [
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x20252b:s=1280x720:r=8:d=10",
        "-f", "lavfi", "-i", "color=c=0xffa500:s=220x160:r=8:d=10",
        "-filter_complex", filter_graph, "-map", "[v]", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(60, max(1, remaining)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_unavailable") from exc
    if completed.returncode != 0 or completed.stdout:
        raise QualificationError("runtime_unavailable")
    raw = _read_regular(path, 8388608)
    if len(raw) < 12 or raw[4:8] != b"ftyp":
        raise QualificationError("runtime_unavailable")
    return raw


def _container_snapshot(contract: dict[str, Any], deadline: float) -> dict[str, Any]:
    delimiter = "|schema-runtime-field|"
    template = (
        f"{{{{json .Config.Image}}}}{delimiter}{{{{json .Image}}}}{delimiter}"
        f"{{{{json .State.Status}}}}{delimiter}"
        "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}"
        f"{delimiter}{{{{json .RestartCount}}}}{delimiter}{{{{json .State.OOMKilled}}}}"
    )
    result: dict[str, Any] = {}
    for row in contract["containers"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationError("runtime_unavailable")
        try:
            completed = subprocess.run(
                ["/usr/bin/docker", "inspect", "--format", template, row["name"]],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=min(30, max(1, remaining)),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QualificationError("runtime_unavailable") from exc
        parts = completed.stdout.decode("utf-8", errors="strict").strip().split(delimiter)
        if completed.returncode != 0 or len(parts) != 6:
            raise QualificationError("runtime_unavailable")
        try:
            image, image_id, status, health, restarts, oom = [json.loads(part) for part in parts]
        except json.JSONDecodeError as exc:
            raise QualificationError("runtime_unavailable") from exc
        if (
            image != row["image"] or status != "running" or health != "healthy"
            or restarts != 0 or oom is not False or not str(image_id).startswith("sha256:")
        ):
            raise QualificationError("runtime_unavailable")
        result[row["name"]] = {
            "image": image,
            "image_id": image_id,
            "status": status,
            "health": health,
            "restart_count": restarts,
            "oom_killed": oom,
        }
    return result


def _json_response(response: Any) -> dict[str, Any]:
    if response.content_type != "application/json":
        raise QualificationError("invalid_response")
    value = _decode(response.body)
    if not isinstance(value, dict):
        raise QualificationError("invalid_response")
    return value


def _content(response: Any, identifier: str, model: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    envelope = _json_response(response)
    response_id = envelope.get("id")
    try:
        UUID(str(response_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("invalid_response") from exc
    if (
        response.status != 200 or envelope.get("video_id") != identifier
        or envelope.get("model") != model
        or envelope.get("object") != "summarization.completion"
        or envelope.get("media_info")
        != {"type": "offset", "start_offset": None, "end_offset": None}
    ):
        raise QualificationError("oracle_failed")
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise QualificationError("invalid_response")
    choice = choices[0]
    try:
        message = choice["message"]
        content = message["content"]
    except (KeyError, TypeError) as exc:
        raise QualificationError("invalid_response") from exc
    if (
        choice.get("index") != 0 or choice.get("finish_reason") != "stop"
        or message.get("role") != "assistant" or not isinstance(content, str)
    ):
        raise QualificationError("invalid_response")
    structured = _decode(content.encode("utf-8"))
    if not isinstance(structured, dict):
        raise QualificationError("invalid_response")
    return envelope, structured, content


def _validate_positive(response: Any, identifier: str, contract: dict[str, Any]) -> dict[str, Any]:
    envelope, structured, content = _content(response, identifier, contract["model_id"])
    if set(structured) != {"events", "video_summary"} or not isinstance(structured["video_summary"], str):
        raise QualificationError("invalid_response", detail={"stage": "positive_content_shape"})
    events = structured["events"]
    expected_keys = set(contract["positive_schema"]["required_event_keys"])
    if not isinstance(events, list) or not events:
        raise QualificationError("oracle_failed", detail={"stage": "positive_events_empty"})
    for event in events:
        if not isinstance(event, dict) or set(event) != expected_keys:
            raise QualificationError(
                "oracle_failed",
                detail={
                    "stage": "positive_event_keys",
                    "event_is_object": isinstance(event, dict),
                    "event_keys_exact": isinstance(event, dict) and set(event) == expected_keys,
                },
            )
        start, end = event["start_time"], event["end_time"]
        if (
            type(start) not in {int, float} or type(end) not in {int, float}
            or not math.isfinite(float(start)) or not math.isfinite(float(end))
            or not 0 <= float(start) < float(end) <= 10.5
            or not isinstance(event["description"], str) or not event["description"].strip()
            or event["type"] != "visible object movement"
            or event["schema_marker"] != contract["positive_schema"]["schema_marker"]
        ):
            raise QualificationError(
                "oracle_failed",
                detail={
                    "stage": "positive_event_values",
                    "timestamps_valid": type(start) in {int, float}
                    and type(end) in {int, float}
                    and math.isfinite(float(start))
                    and math.isfinite(float(end))
                    and 0 <= float(start) < float(end) <= 10.5,
                    "description_nonempty": isinstance(event["description"], str)
                    and bool(event["description"].strip()),
                    "type_exact": event["type"] == "visible object movement",
                    "schema_marker_exact": event["schema_marker"]
                    == contract["positive_schema"]["schema_marker"],
                },
            )
    usage = envelope.get("usage")
    chunks = usage.get("total_chunks_processed") if isinstance(usage, dict) else None
    if type(chunks) is not int or chunks < 1:
        raise QualificationError("invalid_response")
    return {
        "http_status": 200,
        "response_sha256": _sha(response.body),
        "content_sha256": _sha(content),
        "event_count": len(events),
        "event_keys_exact": True,
        "schema_markers_exact": True,
        "types_exact": True,
        "timestamps_valid": True,
        "fixture_grounded": True,
        "chunks_processed": chunks,
    }


def _validate_negative(response: Any, identifier: str, contract: dict[str, Any]) -> dict[str, Any]:
    event_count: int | None = None
    if response.status == 200:
        _envelope, structured, _content_value = _content(
            response, identifier, contract["model_id"]
        )
        events = structured.get("events")
        if not isinstance(events, list) or events:
            raise QualificationError("oracle_failed")
        event_count = 0
    elif 400 <= response.status <= 599:
        _json_response(response)
    else:
        raise QualificationError("oracle_failed")
    return {
        "http_status": response.status,
        "response_sha256": _sha(response.body),
        "json_parseable": True,
        "malformed_success_rejected": True,
        "event_count": event_count,
    }


def _privacy_walk(value: Any) -> None:
    forbidden_keys = {"id", "identifier", "prompt", "content", "raw", "url", "path"}
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).casefold()
            if lowered in forbidden_keys or lowered.endswith("_url"):
                raise QualificationError("configuration_error")
            _privacy_walk(item)
    elif isinstance(value, list):
        for item in value:
            _privacy_walk(item)
    elif isinstance(value, str):
        lowered = value.casefold()
        if "http://" in lowered or "https://" in lowered or "bearer " in lowered or "nvapi-" in lowered:
            raise QualificationError("configuration_error")


def execute(acknowledgement: str, *, transport: Any | None = None) -> dict[str, Any]:
    contract, contract_raw = _contract()
    static = _verify_static(contract)
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    if shutil.disk_usage(REPO).free < contract["execution_bounds"]["min_free_bytes"]:
        raise QualificationError("runtime_unavailable")
    started = time.monotonic()
    deadline = started + contract["execution_bounds"]["max_duration_seconds"]
    runtime_before = _container_snapshot(contract, deadline)
    focus = static["focus"]
    client = transport if transport is not None else focus.LiveTransport()
    action_index = 0
    uploaded = False
    deleted = False
    identifier = str(uuid5(OWNERSHIP_NAMESPACE, contract["package_id"]))
    pre_rows: list[dict[str, Any]] | None = None
    positive_result: dict[str, Any] | None = None
    negative_result: dict[str, Any] | None = None
    cleanup_failure = False
    primary: BaseException | None = None

    def call(method: str, path: str, *, template: str | None = None, body: bytes | None = None, content_type: str | None = None, timeout: float | None = None) -> Any:
        nonlocal action_index
        if action_index >= len(contract["action_envelope"]):
            raise QualificationError("oracle_failed")
        expected = contract["action_envelope"][action_index]
        if expected["method"] != method or expected["path"] != (template or path):
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
        except QualificationError:
            raise
        except Exception as exc:
            raise QualificationError("transport_error") from exc

    def direct(method: str, path: str) -> Any:
        """Failure-path HTTP that does not pretend skipped actions executed."""
        try:
            return client.request(
                method=method,
                url=contract["endpoints"]["lvs_origin"] + path,
                headers={"Accept": "application/json"},
                body=None,
                timeout_seconds=float(contract["execution_bounds"]["short_timeout_seconds"]),
                max_response_bytes=contract["execution_bounds"]["max_response_bytes"],
            )
        except Exception as exc:
            raise QualificationError("transport_error") from exc

    with tempfile.TemporaryDirectory(prefix="vss-custom-schema-") as temporary:
        fixture_path = Path(temporary) / "custom-schema.mp4"
        fixture = _generate_fixture(fixture_path, deadline)
        if len(fixture) > contract["execution_bounds"]["max_fixture_bytes"]:
            raise QualificationError("runtime_unavailable")
        positive_schema = _schema([contract["positive_schema"]["schema_marker"]])
        negative_schema = _schema([])
        try:
            pre = call("GET", "/files?purpose=vision", template="/files")
            pre_rows = focus._file_list(_json_response(pre))
            if identifier in {str(row["id"]) for row in pre_rows}:
                raise QualificationError("oracle_failed")
            if call("GET", "/v1/ready").status != 200:
                raise QualificationError("runtime_unavailable")
            models = _json_response(call("GET", "/models"))
            data = models.get("data")
            if not isinstance(data, list) or not any(
                isinstance(row, dict) and row.get("id") == contract["model_id"]
                for row in data
            ):
                raise QualificationError("runtime_unavailable")
            boundary, multipart = focus._multipart(
                contract["package_id"], identifier, fixture_path.name, fixture
            )
            uploaded = True
            upload = call(
                "POST", "/files", body=multipart,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
            row = focus._file_row(_json_response(upload), True)
            if str(row["id"]) != identifier or row["bytes"] != len(fixture):
                raise QualificationError("oracle_failed")
            readback = focus._file_row(
                _json_response(call("GET", f"/files/{identifier}", template="/files/{owned_id}")),
                False,
            )
            if str(readback["id"]) != identifier or readback["bytes"] != len(fixture):
                raise QualificationError("oracle_failed")
            positive = call(
                "POST", "/v1/summarize",
                body=_request(identifier, contract["model_id"], positive_schema),
                content_type="application/json",
                timeout=contract["execution_bounds"]["summarize_timeout_seconds"],
            )
            positive_result = _validate_positive(positive, identifier, contract)
            negative = call(
                "POST", "/v1/summarize",
                body=_request(identifier, contract["model_id"], negative_schema),
                content_type="application/json",
                timeout=contract["execution_bounds"]["summarize_timeout_seconds"],
            )
            negative_result = _validate_negative(negative, identifier, contract)
        except BaseException as exc:
            primary = exc
        finally:
            normal_completion = primary is None and action_index == 7
            if uploaded:
                try:
                    deletion = (
                        call("DELETE", f"/files/{identifier}", template="/files/{owned_id}")
                        if normal_completion
                        else direct("DELETE", f"/files/{identifier}")
                    )
                    deleted_value = _json_response(deletion)
                    deleted = deletion.status == 200 and deleted_value == {
                        "id": identifier, "object": "file", "deleted": True
                    }
                    if not deleted:
                        cleanup_failure = True
                except BaseException:
                    cleanup_failure = True
            try:
                post_response = (
                    call("GET", "/files?purpose=vision", template="/files")
                    if normal_completion
                    else direct("GET", "/files?purpose=vision")
                )
                post_rows = focus._file_list(_json_response(post_response))
                if pre_rows is None or _canonical(post_rows) != _canonical(pre_rows):
                    cleanup_failure = True
                ready_response = (
                    call("GET", "/v1/ready")
                    if normal_completion
                    else direct("GET", "/v1/ready")
                )
                if ready_response.status != 200:
                    cleanup_failure = True
            except BaseException:
                cleanup_failure = True
        if cleanup_failure:
            raise QualificationError("cleanup_failed")
        if primary is not None:
            if isinstance(primary, QualificationError):
                raise primary
            raise QualificationError("oracle_failed") from primary
        if positive_result is None or negative_result is None or not deleted or action_index != 10:
            raise QualificationError("oracle_failed")
        runtime_after = _container_snapshot(contract, deadline)
        runtime_unchanged = _canonical(runtime_before) == _canonical(runtime_after)
        if not runtime_unchanged:
            raise QualificationError("oracle_failed")
        receipt = {
            "schema_version": 1,
            "package_id": contract["package_id"],
            "capability_id": contract["capability_id"],
            "status": "passed",
            "contract_sha256": _sha(contract_raw),
            "duration_seconds": round(time.monotonic() - started, 6),
            "actions": action_index,
            "runtime": {
                "before_sha256": _sha(_canonical(runtime_before)),
                "after_sha256": _sha(_canonical(runtime_after)),
                "unchanged": True,
                "healthy": True,
            },
            "fixture": {
                "bytes": len(fixture),
                "sha256": _sha(fixture),
                "owned_id_sha256": _sha(identifier),
            },
            "schemas": {
                "positive_sha256": _sha(positive_schema),
                "negative_sha256": _sha(negative_schema),
            },
            "positive": positive_result,
            "negative": negative_result,
            "cleanup": {
                "owned_deleted": True,
                "owned_absent": True,
                "catalog_restored": True,
                "ready_after": True,
            },
            "policy": {
                "agent_generate_calls": 0,
                "rt_cv_or_vios_stream_mutations": 0,
                "warehouse_sample_bundle": "excluded",
                "raw_ids_retained": False,
                "raw_prompts_retained": False,
                "raw_semantic_output_retained": False,
            },
        }
        schema = _decode(_read_regular(RECEIPT_SCHEMA_PATH), "configuration_error")
        errors = list(Draft202012Validator(schema).iter_errors(receipt))
        if errors:
            raise QualificationError("configuration_error")
        _privacy_walk(receipt)
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
