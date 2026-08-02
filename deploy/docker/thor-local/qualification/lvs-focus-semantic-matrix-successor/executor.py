#!/usr/bin/env python3
"""Bounded LVS object/event/scenario focus semantic-matrix candidate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from ipaddress import ip_address
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, cast, Mapping, Protocol, Sequence
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 64 * 1024 * 1024
RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}\Z")
OWNERSHIP_NAMESPACE = UUID("3d04b879-8ea3-4f58-9a86-23665080ce75")
CASE_IDS = (
    "object_only",
    "event_only",
    "scenario_only",
    "combined_relationship",
    "distractor_control",
    "absent_negative",
)
ASSERTIONS = (
    "target_object",
    "target_event",
    "target_scenario",
    "target_relationship",
    "distractor_object",
    "distractor_event",
)


class ExecutorError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_manifest",
        "invalid_response",
        "oracle_failed",
        "source_drift",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"


class Transport(Protocol):
    proxies_enabled: bool
    redirects_enabled: bool

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Response: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, fp, code, message, headers, new_url
        return None


class LiveTransport:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Response:
        request = Request(url, data=body, method=method, headers=dict(headers))
        try:
            opened = self._opener.open(request, timeout=timeout_seconds)
        except HTTPError as exc:
            opened = exc
        except Exception as exc:
            raise ExecutorError("invalid_response") from exc
        raw = opened.read(max_response_bytes + 1)
        if len(raw) > max_response_bytes:
            raise ExecutorError("invalid_response")
        content_type = (
            opened.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        return Response(int(opened.status), raw, content_type)


def _read_regular(
    path: Path, maximum: int, code: str, *, absolute: bool = False
) -> bytes:
    if absolute and not path.is_absolute():
        raise ExecutorError(code)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError(code) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ExecutorError(code)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            if not chunk:
                raise ExecutorError(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, key) != getattr(after, key) for key in stable):
            raise ExecutorError(code)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ExecutorError(code)
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ExecutorError(code)),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(code) from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _schema(path: Path) -> Any:
    value = _decode(
        _read_regular(path, MAX_CONFIG_BYTES, "configuration_error"),
        "configuration_error",
    )
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc
    return value


def _validate_schema(value: Any, path: Path, code: str) -> None:
    if list(Draft202012Validator(_schema(path)).iter_errors(value)):
        raise ExecutorError(code)


def _contract() -> dict[str, Any]:
    value = _decode(
        _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error"),
        "configuration_error",
    )
    if not isinstance(value, dict):
        raise ExecutorError("configuration_error")
    return value


def _repo_path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise ExecutorError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ExecutorError("configuration_error")
        except OSError as exc:
            raise ExecutorError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc
    return current


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    _schema(MANIFEST_SCHEMA_PATH)
    _schema(RECEIPT_SCHEMA_PATH)
    envelope = contract.get("action_envelope", [])
    matrix = contract.get("semantic_matrix", [])
    bounds = contract.get("execution_bounds", {})
    decision = contract.get("decision", {})
    if (
        contract.get("package_id") != "lvs-focus-semantic-matrix-successor"
        or contract.get("capability_id")
        != "manifest-entry.video-summarization-file.04-object-event-scenario-focus"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("order") for row in envelope] != list(range(1, 15))
        or [row.get("order") for row in matrix] != list(range(1, 7))
        or tuple(row.get("case_id") for row in matrix) != CASE_IDS
        or bounds
        != {
            "max_requests": 14,
            "max_actions": 14,
            "max_duration_seconds": 2400,
            "owned_file_count": 1,
            "semantic_matrix_cases": 6,
        }
        or decision.get("deterministic_semantic_matrix_implemented") is not True
        or decision.get("request_artifact_correlation_implemented") is not True
        or decision.get("frozen_action_envelope_reconciled") is not True
        or decision.get("runtime_receipt_present") is not False
        or decision.get("executor_ready") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
    ):
        raise ExecutorError("configuration_error")
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 8:
        raise ExecutorError("configuration_error")
    seen: set[str] = set()
    source: dict[str, bytes] = {}
    for lock in locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
        ):
            raise ExecutorError("configuration_error")
        seen.add(lock["path"])
        raw = _read_regular(
            _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
        )
        if _sha(raw) != lock["sha256"]:
            raise ExecutorError("source_drift")
        source[lock["path"]] = raw
    models = source["services/video-summarization/src/vss_api_models.py"].decode()
    server = source["services/video-summarization/src/via_server.py"].decode()
    openapi = source["services/video-summarization/api_spec/openapi.json"].decode()
    if (
        not all(
            token in models
            for token in (
                "class SummarizationQuery",
                "objects_of_interest:",
                "scenario: str = Field",
                "events: list[",
                "schema: str = Field",
                "enable_vlm_structured_output: bool = Field",
            )
        )
        or not all(
            token in server
            for token in (
                "query.objects_of_interest",
                "query.scenario",
                "query.events",
                '"video_id": videoId',
                '"object": "summarization.completion"',
            )
        )
        or '"/v1/summarize"' not in openapi
    ):
        raise ExecutorError("source_drift")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_focus_matrix_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 14,
        "action_bound": 14,
        "matrix_cases": 6,
        "runtime_receipt_present": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ExecutorError("invalid_manifest") from exc
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutorError("invalid_manifest")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ExecutorError("invalid_manifest") from exc
    if not address.is_loopback:
        raise ExecutorError("invalid_manifest")
    rendered = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{rendered}:{port}"


def _validate_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    _validate_schema(result, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    result["lvs_origin"] = _origin(result["lvs_origin"])
    if not RUN_RE.fullmatch(result["run_id"]):
        raise ExecutorError("invalid_manifest")
    terms = result["semantic_fixture"]
    normalized = [" ".join(str(value).casefold().split()) for value in terms.values()]
    if len(normalized) != len(set(normalized)) or any(
        left in right or right in left
        for index, left in enumerate(normalized)
        for right in normalized[index + 1 :]
    ):
        raise ExecutorError("invalid_manifest")
    return result


class Budget:
    def __init__(self, maximum: int, duration: int) -> None:
        self.maximum = maximum
        self.duration = duration
        self.requests = 0
        self.actions = 0
        self.started = time.monotonic()

    def consume(self) -> None:
        if (
            self.requests >= self.maximum
            or self.actions >= self.maximum
            or time.monotonic() - self.started > self.duration
        ):
            raise ExecutorError("oracle_failed")
        self.requests += 1
        self.actions += 1


def _file_row(value: Any, require_media_type: bool) -> dict[str, Any]:
    required = {"id", "bytes", "filename", "purpose", "sensor_name"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ExecutorError("invalid_response")
    try:
        UUID(str(value["id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExecutorError("invalid_response") from exc
    if (
        type(value["bytes"]) is not int
        or value["bytes"] < 0
        or not isinstance(value["filename"], str)
        or not isinstance(value["sensor_name"], str)
        or value["purpose"] != "vision"
        or (require_media_type and value.get("media_type") != "video")
    ):
        raise ExecutorError("invalid_response")
    return value


def _file_list(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or value.get("object") != "list"
        or not isinstance(value.get("data"), list)
    ):
        raise ExecutorError("invalid_response")
    rows = [_file_row(row, True) for row in value["data"]]
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)) or len(ids) > 1_000_000:
        raise ExecutorError("invalid_response")
    return rows


def _unrelated(rows: Sequence[dict[str, Any]], owned_id: str) -> list[dict[str, Any]]:
    return sorted(
        (row for row in rows if str(row["id"]) != owned_id),
        key=lambda row: str(row["id"]),
    )


def _multipart(
    run_id: str, file_id: str, filename: str, media: bytes
) -> tuple[str, bytes]:
    boundary = f"vss-lvs-focus-{_sha(run_id)[:24]}"
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": file_id,
        "sensor_name": f"vss-focus-{_sha(run_id)[:16]}",
    }
    pieces: list[bytes] = []
    for name, value in fields.items():
        pieces.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    pieces.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: video/mp4\r\n\r\n",
            media,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return boundary, b"".join(pieces)


def _matrix_cases(terms: Mapping[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": "object_only",
            "scenario": terms["neutral_scenario"],
            "events": [],
            "objects": [terms["target_object"]],
            "assertions": ["target_object"],
            "markers": [[terms["target_object"]]],
        },
        {
            "case_id": "event_only",
            "scenario": terms["neutral_scenario"],
            "events": [terms["target_event"]],
            "objects": [],
            "assertions": ["target_event"],
            "markers": [[terms["target_event"]]],
        },
        {
            "case_id": "scenario_only",
            "scenario": terms["target_scenario"],
            "events": [],
            "objects": [],
            "assertions": ["target_scenario"],
            "markers": [[terms["target_scenario"]]],
        },
        {
            "case_id": "combined_relationship",
            "scenario": terms["target_scenario"],
            "events": [terms["target_event"], terms["distractor_event"]],
            "objects": [terms["target_object"], terms["distractor_object"]],
            "assertions": ["target_relationship"],
            "markers": [
                [
                    terms["target_object"],
                    terms["target_event"],
                    terms["target_scenario"],
                    terms["target_relationship"],
                ]
            ],
        },
        {
            "case_id": "distractor_control",
            "scenario": terms["neutral_scenario"],
            "events": [terms["distractor_event"]],
            "objects": [terms["distractor_object"]],
            "assertions": ["distractor_object", "distractor_event"],
            "markers": [[terms["distractor_object"]], [terms["distractor_event"]]],
        },
        {
            "case_id": "absent_negative",
            "scenario": terms["neutral_scenario"],
            "events": [terms["absent_event"]],
            "objects": [terms["absent_object"]],
            "assertions": [],
            "markers": [],
        },
    ]


def _output_schema(
    case: Mapping[str, Any], caption_source_sha256: str
) -> dict[str, Any]:
    expected = case["assertions"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "case_id",
            "caption_source_sha256",
            "focused_assertions",
            "evidence",
        ],
        "properties": {
            "case_id": {"const": case["case_id"]},
            "caption_source_sha256": {"const": caption_source_sha256},
            "focused_assertions": {"const": expected},
            "evidence": {
                "type": "array",
                "minItems": len(expected),
                "maxItems": len(expected),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "assertion",
                        "start_seconds",
                        "end_seconds",
                        "description",
                    ],
                    "properties": {
                        "assertion": {"enum": list(ASSERTIONS)},
                        "start_seconds": {"type": "number", "minimum": 0},
                        "end_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 4096,
                        },
                    },
                },
            },
        },
    }


def _request_value(
    case: Mapping[str, Any], *, file_id: str, model: str, caption_source_sha256: str
) -> dict[str, Any]:
    return {
        "id": file_id,
        "model": model,
        "scenario": case["scenario"],
        "events": case["events"],
        "objects_of_interest": case["objects"],
        "schema": _canonical(_output_schema(case, caption_source_sha256)).decode(
            "ascii"
        ),
        "auto_generate_prompt": True,
        "override_vlm_prompt": False,
        "enable_vlm_structured_output": True,
        "chunk_duration": 10,
        "num_frames_per_second_or_fixed_frames_chunk": 20,
        "use_fps_for_chunking": False,
        "temperature": 0,
        "seed": 1,
    }


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _artifact(
    value: Any,
    *,
    body: bytes,
    case: Mapping[str, Any],
    file_id: str,
    model: str,
    caption_source_sha256: str,
    terms: Mapping[str, str],
    seen_response_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutorError("invalid_response")
    response_id = value.get("id")
    try:
        UUID(str(response_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ExecutorError("invalid_response") from exc
    if (
        not isinstance(response_id, str)
        or response_id in seen_response_ids
        or value.get("video_id") != file_id
        or value.get("model") != model
        or value.get("object") != "summarization.completion"
        or type(value.get("created")) is not int
        or value["created"] < 0
    ):
        raise ExecutorError("oracle_failed")
    seen_response_ids.add(response_id)
    media_info = value.get("media_info")
    if (
        not isinstance(media_info, dict)
        or media_info.get("type") != "offset"
        or type(media_info.get("start_offset")) is not int
        or type(media_info.get("end_offset")) is not int
        or media_info["start_offset"] < 0
        or media_info["end_offset"] < media_info["start_offset"]
    ):
        raise ExecutorError("invalid_response")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ExecutorError("invalid_response")
    choice = choices[0]
    try:
        content = choice["message"]["content"]
        role = choice["message"]["role"]
    except (KeyError, TypeError) as exc:
        raise ExecutorError("invalid_response") from exc
    if (
        choice.get("index") != 0
        or choice.get("finish_reason") != "stop"
        or role != "assistant"
        or not isinstance(content, str)
    ):
        raise ExecutorError("invalid_response")
    structured = _decode(content.encode("utf-8"), "invalid_response")
    if not isinstance(structured, dict) or set(structured) != {
        "case_id",
        "caption_source_sha256",
        "focused_assertions",
        "evidence",
    }:
        raise ExecutorError("invalid_response")
    expected = case["assertions"]
    evidence = structured.get("evidence")
    if (
        structured.get("case_id") != case["case_id"]
        or structured.get("caption_source_sha256") != caption_source_sha256
        or structured.get("focused_assertions") != expected
        or not isinstance(evidence, list)
        or len(evidence) != len(expected)
    ):
        raise ExecutorError("oracle_failed")
    forbidden = [terms["absent_object"], terms["absent_event"]]
    if case["case_id"] in {
        "object_only",
        "event_only",
        "scenario_only",
        "combined_relationship",
    }:
        forbidden.extend([terms["distractor_object"], terms["distractor_event"]])
    for row, assertion, markers in zip(evidence, expected, case["markers"]):
        if (
            not isinstance(row, dict)
            or set(row) != {"assertion", "start_seconds", "end_seconds", "description"}
            or row.get("assertion") != assertion
        ):
            raise ExecutorError("invalid_response")
        start, end, description = (
            row.get("start_seconds"),
            row.get("end_seconds"),
            row.get("description"),
        )
        if (
            type(start) not in {int, float}
            or type(end) not in {int, float}
            or not isinstance(description, str)
            or not description.strip()
        ):
            raise ExecutorError("invalid_response")
        start_number = cast(int | float, start)
        end_number = cast(int | float, end)
        if (
            not math.isfinite(float(start_number))
            or not math.isfinite(float(end_number))
            or not 0 <= float(start_number) < float(end_number) <= 86400
        ):
            raise ExecutorError("invalid_response")
        normalized = _normalized(description)
        if any(_normalized(marker) not in normalized for marker in markers) or any(
            _normalized(term) in normalized for term in forbidden
        ):
            raise ExecutorError("oracle_failed")
    usage = value.get("usage")
    if (
        not isinstance(usage, dict)
        or type(usage.get("total_chunks_processed")) is not int
        or usage["total_chunks_processed"] <= 0
    ):
        raise ExecutorError("invalid_response")
    return {
        "response_sha256": _sha(body),
        "response_id_sha256": _sha(response_id),
        "observed_assertion_count": len(expected),
        "evidence_count": len(evidence),
    }


def execute(
    *, manifest: Mapping[str, Any], acknowledgement: str, transport: Transport
) -> dict[str, Any]:
    plan = compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    if not isinstance(manifest, Mapping):
        raise ExecutorError("invalid_manifest")
    manifest = _validate_manifest(manifest)
    if transport.proxies_enabled or transport.redirects_enabled:
        raise ExecutorError("invalid_manifest")
    fixture_path = Path(manifest["fixture"]["path"])
    try:
        canonical_path = fixture_path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ExecutorError("invalid_manifest") from exc
    if fixture_path != canonical_path or not SAFE_FILENAME_RE.fullmatch(
        fixture_path.name
    ):
        raise ExecutorError("invalid_manifest")
    media = _read_regular(
        fixture_path,
        contract["transport"]["max_fixture_bytes"],
        "invalid_manifest",
        absolute=True,
    )
    if (
        _sha(media) != manifest["fixture"]["sha256"]
        or len(media) < 12
        or media[4:8] != b"ftyp"
    ):
        raise ExecutorError("invalid_manifest")

    owned_id = str(
        uuid5(
            OWNERSHIP_NAMESPACE, f"{manifest['run_id']}:{manifest['fixture']['sha256']}"
        )
    )
    sensor_name = f"vss-focus-{_sha(manifest['run_id'])[:16]}"
    caption_source_sha256 = _sha(
        _canonical(
            {"file_id": owned_id, "fixture_sha256": manifest["fixture"]["sha256"]}
        )
    )
    cases = _matrix_cases(manifest["semantic_fixture"])
    budget = Budget(14, 2400)
    pre_projection: list[dict[str, Any]] | None = None
    upload_attempted = False
    deleted = False
    matrix_rows: list[dict[str, Any]] = []
    seen_response_ids: set[str] = set()

    def call(
        action_id: str,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: int | None = None,
    ) -> Response:
        del action_id
        budget.consume()
        if body is not None and len(body) > contract["transport"]["max_request_bytes"]:
            raise ExecutorError("invalid_manifest")
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        response = transport.request(
            method=method,
            url=f"{manifest['lvs_origin']}{path}",
            headers=headers,
            body=body,
            timeout_seconds=float(
                timeout or contract["transport"]["short_timeout_seconds"]
            ),
            max_response_bytes=contract["transport"]["max_response_bytes"],
        )
        if (
            not isinstance(response, Response)
            or not 100 <= response.status <= 599
            or len(response.body) > contract["transport"]["max_response_bytes"]
        ):
            raise ExecutorError("invalid_response")
        return response

    def json_response(response: Response, allowed: tuple[int, ...] = (200,)) -> Any:
        if (
            response.status not in allowed
            or response.content_type != "application/json"
        ):
            raise ExecutorError("oracle_failed")
        return _decode(response.body, "invalid_response")

    primary: BaseException | None = None
    cleanup_failed = False
    try:
        pre = call("capture-complete-file-prestate", "GET", "/files?purpose=vision")
        pre_rows = _file_list(json_response(pre))
        if owned_id in {str(row["id"]) for row in pre_rows}:
            raise ExecutorError("oracle_failed")
        pre_projection = _unrelated(pre_rows, owned_id)
        if call("verify-lvs-ready", "GET", "/v1/ready").status != 200:
            raise ExecutorError("oracle_failed")
        models = json_response(call("verify-model-advertised", "GET", "/models"))
        advertised = models.get("data") if isinstance(models, dict) else None
        if not isinstance(advertised, list) or not any(
            isinstance(row, dict) and row.get("id") == manifest["model"]
            for row in advertised
        ):
            raise ExecutorError("oracle_failed")

        boundary, multipart = _multipart(
            manifest["run_id"], owned_id, fixture_path.name, media
        )
        upload_attempted = True
        uploaded = _file_row(
            json_response(
                call(
                    "upload-one-owned-caption-source",
                    "POST",
                    "/files",
                    body=multipart,
                    content_type=f"multipart/form-data; boundary={boundary}",
                )
            ),
            True,
        )
        if (
            str(uploaded["id"]) != owned_id
            or uploaded["bytes"] != len(media)
            or uploaded["filename"] != fixture_path.name
            or uploaded["sensor_name"] != sensor_name
        ):
            raise ExecutorError("oracle_failed")
        fetched = _file_row(
            json_response(
                call("verify-owned-caption-source", "GET", f"/files/{owned_id}")
            ),
            False,
        )
        if (
            str(fetched["id"]) != owned_id
            or fetched["bytes"] != len(media)
            or fetched["filename"] != fixture_path.name
            or fetched["sensor_name"] != sensor_name
        ):
            raise ExecutorError("oracle_failed")

        for order, case in enumerate(cases, 1):
            request_value = _request_value(
                case,
                file_id=owned_id,
                model=manifest["model"],
                caption_source_sha256=caption_source_sha256,
            )
            request_body = _canonical(request_value)
            response = call(
                f"focus-{case['case_id']}",
                "POST",
                "/v1/summarize",
                body=request_body,
                content_type="application/json",
                timeout=contract["transport"]["summarize_timeout_seconds"],
            )
            value = json_response(response)
            artifact = _artifact(
                value,
                body=response.body,
                case=case,
                file_id=owned_id,
                model=manifest["model"],
                caption_source_sha256=caption_source_sha256,
                terms=manifest["semantic_fixture"],
                seen_response_ids=seen_response_ids,
            )
            matrix_rows.append(
                {
                    "order": order,
                    "case_id": case["case_id"],
                    "request_sha256": _sha(request_body),
                    **artifact,
                    "expected_assertion_count": len(case["assertions"]),
                    "source_identity_correlated": True,
                    "forbidden_terms_excluded": True,
                }
            )
    except BaseException as exc:
        primary = exc
    finally:
        if upload_attempted:
            try:
                deletion = json_response(
                    call(
                        "delete-exact-owned-caption-source",
                        "DELETE",
                        f"/files/{owned_id}",
                    ),
                    (200,),
                )
                if deletion != {"id": owned_id, "object": "file", "deleted": True}:
                    cleanup_failed = True
                else:
                    deleted = True
            except BaseException:
                cleanup_failed = True
        try:
            restored_rows = _file_list(
                json_response(
                    call(
                        "prove-owned-absence-and-unrelated-restoration",
                        "GET",
                        "/files?purpose=vision",
                    )
                )
            )
            if (
                pre_projection is None
                or owned_id in {str(row["id"]) for row in restored_rows}
                or _canonical(_unrelated(restored_rows, owned_id))
                != _canonical(pre_projection)
            ):
                cleanup_failed = True
        except BaseException:
            cleanup_failed = True
        try:
            if call("verify-lvs-ready-after-cleanup", "GET", "/v1/ready").status != 200:
                cleanup_failed = True
        except BaseException:
            cleanup_failed = True
    if cleanup_failed:
        raise ExecutorError("cleanup_failed")
    if primary is not None:
        if isinstance(primary, ExecutorError):
            raise primary
        raise ExecutorError("oracle_failed") from primary
    if (
        not upload_attempted
        or not deleted
        or len(matrix_rows) != 6
        or budget.requests != 14
        or budget.actions != 14
        or time.monotonic() - budget.started > budget.duration
    ):
        raise ExecutorError("oracle_failed")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "candidate_focus_matrix_pass_non_promoting",
        "contract_sha256": _sha(
            _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
        ),
        "run_id_sha256": _sha(manifest["run_id"]),
        "origin_sha256": _sha(manifest["lvs_origin"]),
        "model_sha256": _sha(manifest["model"]),
        "fixture_sha256": manifest["fixture"]["sha256"],
        "caption_source_sha256": caption_source_sha256,
        "budget": {
            "requests": 14,
            "max_requests": 14,
            "actions": 14,
            "max_actions": 14,
            "max_duration_seconds": 2400,
        },
        "matrix": matrix_rows,
        "cleanup": {
            "registered_owned_files": 1,
            "deleted_owned_files": 1,
            "owned_absent": True,
            "unrelated_state_restored": True,
            "exact_delete_confirmation": True,
        },
        "canonical_runtime_evidence": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "configuration_error")
    if plan["executor_ready"] is not False:
        raise ExecutorError("configuration_error")
    return receipt


def _json_file(path: Path) -> dict[str, Any]:
    value = _decode(
        _read_regular(path, MAX_CONFIG_BYTES, "invalid_manifest", absolute=True),
        "invalid_manifest",
    )
    if not isinstance(value, dict):
        raise ExecutorError("invalid_manifest")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    live = commands.add_parser("execute-http")
    live.add_argument("--manifest", type=Path, required=True)
    live.add_argument("--acknowledgement", required=True)
    args = parser.parse_args(argv)
    try:
        value = (
            compile_plan()
            if args.command == "plan"
            else execute(
                manifest=_json_file(args.manifest),
                acknowledgement=args.acknowledgement,
                transport=LiveTransport(),
            )
        )
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except ExecutorError as exc:
        print(
            json.dumps(
                {"schema_version": 1, "status": "failed", "error_code": exc.code}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
