#!/usr/bin/env python3
"""Authorization-gated LVS semantic closure supplement.

The default ``plan`` command is static and inert.  ``execute-closure`` performs
only bounded numeric-loopback HTTP requests.  It never starts or stops a
service, downloads a fixture from the Internet, reads credentials, deletes a
resource, or uses the Warehouse sample.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID
from uuid import uuid5

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_TOOLS = [
    "lvs_video_understanding",
    "lvs_config_media",
    "lvs_stream_understanding",
    "lvs_caption_retrieval",
    "video_report_gen",
]
OWNED_STREAM_UUID_NAMESPACE = UUID("51f4f906-4bf4-5df5-ae4e-7f814ab47a41")


class ExecutorError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_manifest",
        "invalid_response",
        "oracle_failed",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


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
    def redirect_request(self, request, fp, code, message, headers, new_url):
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
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            try:
                opened = self._opener.open(request, timeout=timeout_seconds)
            except HTTPError as response:
                opened = response
            with opened:
                raw = opened.read(max_response_bytes + 1)
                if len(raw) > max_response_bytes:
                    raise ExecutorError("invalid_response")
                return Response(status=int(opened.status), body=raw)
        except ExecutorError:
            raise
        except (OSError, TimeoutError, URLError) as exc:
            raise ExecutorError("transport_error") from exc


def _read_regular(path: Path, maximum: int, code: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError(code) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ExecutorError(code)
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, name) != getattr(after, name) for name in stable
        ):
            raise ExecutorError(code)
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ExecutorError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ExecutorError(code)),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(code) from exc
    if not isinstance(value, dict):
        raise ExecutorError(code)
    return value


def _json_file(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    return _decode(_read_regular(path, MAX_CONFIG_BYTES, code), code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_response") from exc


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _owned_stream_id(run_id: str) -> str:
    return str(uuid5(OWNED_STREAM_UUID_NAMESPACE, run_id))


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
        except ExecutorError:
            raise
        except OSError as exc:
            raise ExecutorError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc
    return current


def _validate_schema(value: Any, path: Path, code: str) -> None:
    try:
        schema = _json_file(path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        if list(validator.iter_errors(value)):
            raise ExecutorError(code)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc


def _contract() -> dict[str, Any]:
    return _json_file(CONTRACT_PATH)


def _numeric_origin(value: str, code: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        address = ip_address(parsed.hostname or "")
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ExecutorError(code) from exc
    if (
        parsed.scheme != "http"
        or not address.is_loopback
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutorError(code)
    return str(address), port


def _iso(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ExecutorError(code) from exc
    if parsed.tzinfo is None:
        raise ExecutorError(code)
    return parsed.astimezone(timezone.utc)


def _timeline_duration_microseconds(rows: Any, sensor_id: str) -> int:
    if not isinstance(rows, dict):
        raise ExecutorError("invalid_response")
    entries = rows.get(sensor_id)
    if not isinstance(entries, list) or not entries:
        raise ExecutorError("oracle_failed")
    starts: list[datetime] = []
    ends: list[datetime] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ExecutorError("invalid_response")
        start = _iso(entry.get("startTime"), "invalid_response")
        end = _iso(entry.get("endTime"), "invalid_response")
        if end <= start:
            raise ExecutorError("oracle_failed")
        starts.append(start)
        ends.append(end)
    return int((max(ends) - min(starts)).total_seconds() * 1_000_000)


def _nonempty_completion(
    value: Mapping[str, Any],
    stream_id: str,
    model: str,
) -> bool:
    if str(value.get("video_id")) != stream_id or value.get("model") != model:
        return False
    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    negative_phrases = (
        "no event",
        "no relevant",
        "nothing observed",
        "not found",
        "unable to",
    )
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"].strip().casefold()
            if len(content) >= 12 and not any(
                phrase in content for phrase in negative_phrases
            ):
                return True
    return False


def _empty_completion(value: Mapping[str, Any], stream_id: str, model: str) -> bool:
    return (
        str(value.get("video_id")) == stream_id
        and value.get("model") == model
        and value.get("choices") == []
    )


def _es_total(value: Mapping[str, Any]) -> int:
    shards = value.get("_shards")
    if value.get("timed_out") is not False or not isinstance(shards, Mapping):
        raise ExecutorError("invalid_response")
    total_shards = shards.get("total")
    successful_shards = shards.get("successful")
    skipped_shards = shards.get("skipped")
    failed_shards = shards.get("failed")
    if (
        type(total_shards) is not int
        or type(successful_shards) is not int
        or type(skipped_shards) is not int
        or type(failed_shards) is not int
        or min(total_shards, successful_shards, skipped_shards, failed_shards) < 0
        or failed_shards != 0
        or successful_shards + skipped_shards != total_shards
    ):
        raise ExecutorError("invalid_response")
    hits = value.get("hits")
    total = hits.get("total") if isinstance(hits, Mapping) else None
    if isinstance(total, int) and total >= 0:
        return total
    if isinstance(total, Mapping):
        count = total.get("value")
        if isinstance(count, int) and count >= 0:
            return count
    raise ExecutorError("invalid_response")


def _delete_by_query_count(value: Mapping[str, Any]) -> int:
    """Validate an Elasticsearch delete-by-query completion."""

    deleted = value.get("deleted")
    failures = value.get("failures")
    conflicts = value.get("version_conflicts")
    if (
        value.get("timed_out") is not False
        or failures != []
        or type(deleted) is not int
        or deleted < 0
        or type(conflicts) is not int
        or conflicts != 0
    ):
        raise ExecutorError("cleanup_failed")
    return deleted


def _is_missing_index(value: Mapping[str, Any]) -> bool:
    error = value.get("error")
    return (
        value.get("status") == 404
        and isinstance(error, Mapping)
        and error.get("type") == "index_not_found_exception"
    )


def _validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    _validate_schema(value, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    for name in (
        "agent_origin",
        "lvs_origin",
        "rtvi_vlm_origin",
        "vst_origin",
        "elasticsearch_origin",
    ):
        _numeric_origin(value[name], "invalid_manifest")
    allowed = value["allowed_media_origins"]
    for origin in allowed:
        _numeric_origin(origin, "invalid_manifest")
    if len(set(allowed)) != len(allowed):
        raise ExecutorError("invalid_manifest")
    run_id = value["run_id"]
    fixtures = value["fixtures"]
    if (
        len({item["sensor_id"] for item in fixtures}) != 2
        or len({item["stored_media_sha256"] for item in fixtures}) != 2
        or any(item["owner_run_id"] != run_id for item in fixtures)
    ):
        raise ExecutorError("invalid_manifest")
    stream = value["live_stream"]
    try:
        UUID(stream["id"])
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_manifest") from exc
    if (
        stream["owner_run_id"] != run_id
        or stream["id"] != _owned_stream_id(run_id)
        or _iso(stream["end_time"], "invalid_manifest")
        <= _iso(stream["start_time"], "invalid_manifest")
        or stream["id"] in {item["sensor_id"] for item in fixtures}
    ):
        raise ExecutorError("invalid_manifest")
    return value


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    workflow = contract.get("workflow", [])
    if (
        contract.get("schema_version") != 1
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("order") for row in workflow] != list(range(1, 19))
        or sum(row.get("max_cost", 0) for row in workflow) != 24
        or contract.get("execution_bounds", {}).get("max_requests") != 24
        or contract.get("execution_bounds", {}).get("max_actions") != 24
        or contract.get("transport", {}).get("poll_attempts") != 5
        or contract.get("transport", {}).get("poll_delay_seconds") != 2
        or contract.get("transport", {}).get("cleanup_quiescence_seconds") != 2
        or contract.get("transport", {}).get("cleanup_reserve_seconds") != 300
        or contract.get("ownership")
        != {
            "live_stream_uuid_derivation": "uuid5:51f4f906-4bf4-5df5-ae4e-7f814ab47a41:<run_id>",
            "exclusive_collection_attestation_required": True,
            "preexisting_collection_must_be_empty": True,
        }
        or contract.get("evidence", {}).get("promotion_eligible") is not False
        or contract.get("evidence", {}).get("executor_ready") is not False
        or contract.get("evidence", {}).get("canonical_state_advanced") is not False
    ):
        raise ExecutorError("configuration_error")
    seen: set[str] = set()
    for lock in contract.get("source_locks", []):
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
            or not SHA_RE.fullmatch(lock["sha256"])
        ):
            raise ExecutorError("configuration_error")
        seen.add(lock["path"])
        if (
            _sha(
                _read_regular(
                    _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
                )
            )
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")
    if seen != {
        "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.json",
        "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/contract.json",
        "deploy/docker/thor-local/qualification/lvs-semantic-runtime-agent-session-successor/executor.py",
        "services/agent/src/vss_agents/api/custom_fastapi_worker.py",
        "services/video-summarization/src/via_server.py",
        "services/video-summarization/src/vss_api_models.py",
        "deploy/docker/developer-profiles/dev-profile-lvs/vss-agent/configs/config.yml",
        "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py",
        "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py",
    }:
        raise ExecutorError("configuration_error")
    selected = _json_file(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration-rebase-successor/post-state-capability-oracles.json"
        )
    )
    rows = selected.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise ExecutorError("configuration_error")
    matches = [row for row in rows if row.get("oracle_id") == contract["oracle_id"]]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    row = matches[0]
    if (
        row.get("capability_id") != contract["capability_id"]
        or row.get("current_state") != "open_unexecuted"
        or row.get("evidence") != []
        or row.get("execution_bounds", {}).get("executor") is not None
        or row.get("execution_bounds", {}).get("max_requests") != 14
        or row.get("execution_bounds", {}).get("max_actions") != 14
    ):
        raise ExecutorError("configuration_error")
    _validate_schema({}, MANIFEST_SCHEMA_PATH, "invalid_manifest") if False else None
    Draft202012Validator.check_schema(_json_file(MANIFEST_SCHEMA_PATH))
    Draft202012Validator.check_schema(_json_file(RECEIPT_SCHEMA_PATH))
    coverage = contract["semantic_coverage"]
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_plan_valid",
        "runtime_activity_performed": False,
        "runtime_evidence_created": False,
        "warehouse_sample_bundle": "excluded",
        "max_requests": 24,
        "frozen_canonical_max_requests": 14,
        "closed_semantics": len(coverage["closed_by_this_successor"]),
        "unavoidable_semantics": len(coverage["still_unavoidable"]),
        "promotion_eligible": False,
        "executor_ready": False,
        "canonical_state_advanced": False,
    }


class Budget:
    def __init__(
        self,
        maximum: int,
        duration_seconds: int,
        cleanup_reserve_seconds: int,
        clock: Any,
    ) -> None:
        self.maximum = maximum
        self.duration_seconds = duration_seconds
        self.cleanup_reserve_seconds = cleanup_reserve_seconds
        self.clock = clock
        self.started = clock()
        self.requests = 0
        self.actions = 0

    def consume(self, *, cleanup: bool) -> float:
        elapsed = self.clock() - self.started
        limit = self.duration_seconds
        if not cleanup:
            limit -= self.cleanup_reserve_seconds
        remaining = limit - elapsed
        if (
            self.requests >= self.maximum
            or self.actions >= self.maximum
            or remaining <= 0
        ):
            raise ExecutorError("oracle_failed")
        self.requests += 1
        self.actions += 1
        return remaining


def execute(
    *,
    manifest: dict[str, Any],
    acknowledgement: str,
    transport: Transport | None = None,
    sleeper: Any = time.sleep,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    manifest = _validate_manifest(manifest)
    if transport is None:
        transport = LiveTransport()
    if transport.proxies_enabled or transport.redirects_enabled:
        raise ExecutorError("configuration_error")

    budget = Budget(
        24,
        1800,
        contract["transport"]["cleanup_reserve_seconds"],
        clock,
    )
    observations: list[dict[str, Any]] = []

    def call(
        action_id: str,
        surface: str,
        origin: str,
        method: str,
        path: str,
        *,
        path_template: str | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
        extra_headers: Mapping[str, str] | None = None,
        cleanup: bool = False,
    ) -> Response:
        remaining = budget.consume(cleanup=cleanup)
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = transport.request(
                method=method,
                url=origin.rstrip("/") + path,
                headers=headers,
                body=body,
                timeout_seconds=min(
                    timeout or contract["transport"]["short_timeout_seconds"],
                    remaining,
                ),
                max_response_bytes=contract["transport"]["max_response_bytes"],
            )
        except ExecutorError:
            raise
        except Exception as exc:
            raise ExecutorError("transport_error") from exc
        if not isinstance(response.status, int) or not isinstance(response.body, bytes):
            raise ExecutorError("invalid_response")
        observations.append(
            {
                "order": budget.actions,
                "action_id": action_id,
                "surface": surface,
                "method": method,
                "path_template": path_template or path,
                "http_status": response.status,
                "response_bytes": len(response.body),
                "response_sha256": _sha(response.body),
            }
        )
        return response

    agent_origin = manifest["agent_origin"]
    lvs_origin = manifest["lvs_origin"]
    rtvi_vlm_origin = manifest["rtvi_vlm_origin"]
    vst_origin = manifest["vst_origin"]
    elasticsearch_origin = manifest["elasticsearch_origin"]
    identity = manifest["lvs_identity"]

    tool_response = call(
        "discover-five-agent-tools",
        "agent",
        agent_origin,
        "GET",
        "/api/v1/runtime-tools/lvs",
    )
    tools = (
        _decode(tool_response.body, "invalid_response")
        if tool_response.status == 200
        else {}
    )
    if tools != {
        "schema_version": 1,
        "catalog": "lvs-advertised-runtime-tools",
        "expected": EXPECTED_TOOLS,
        "available": EXPECTED_TOOLS,
        "missing": [],
        "ready": True,
    }:
        raise ExecutorError("oracle_failed")

    ready = call("verify-lvs-ready", "lvs", lvs_origin, "GET", "/v1/ready")
    if ready.status != 200:
        raise ExecutorError("oracle_failed")
    metadata_response = call(
        "verify-lvs-build", "lvs", lvs_origin, "GET", "/v1/metadata"
    )
    metadata = (
        _decode(metadata_response.body, "invalid_response")
        if metadata_response.status == 200
        else {}
    )
    if (
        metadata.get("version") != identity["version"]
        or metadata.get("sub_version") != identity["sub_version"]
    ):
        raise ExecutorError("oracle_failed")
    models_response = call("verify-lvs-model", "lvs", lvs_origin, "GET", "/models")
    models = (
        _decode(models_response.body, "invalid_response")
        if models_response.status == 200
        else {}
    )
    model_rows = models.get("data")
    if not isinstance(model_rows, list) or not any(
        isinstance(row, dict) and row.get("id") == identity["model"]
        for row in model_rows
    ):
        raise ExecutorError("oracle_failed")

    timeline_response = call(
        "capture-complete-vst-timeline",
        "vst",
        vst_origin,
        "GET",
        "/vst/api/v1/storage/timelines",
    )
    timelines = (
        _decode(timeline_response.body, "invalid_response")
        if timeline_response.status == 200
        else {}
    )
    timeline_digest = _sha(_canonical(timelines))
    fixture_rows: list[dict[str, Any]] = []
    allowed_media = set(manifest["allowed_media_origins"])
    for index, fixture in enumerate(manifest["fixtures"], 1):
        sensor_id = fixture["sensor_id"]
        duration_us = _timeline_duration_microseconds(timelines, sensor_id)
        expected_us = int(round(float(fixture["duration_seconds"]) * 1_000_000))
        if duration_us != expected_us:
            raise ExecutorError("oracle_failed")
        entries = timelines[sensor_id]
        starts = [_iso(row["startTime"], "invalid_response") for row in entries]
        ends = [_iso(row["endTime"], "invalid_response") for row in entries]
        params = urlencode(
            {
                "startTime": min(starts).isoformat().replace("+00:00", "Z"),
                "endTime": max(ends).isoformat().replace("+00:00", "Z"),
                "container": "mp4",
                "configuration": json.dumps(
                    {"disableAudio": False}, separators=(",", ":")
                ),
            }
        )
        resolver = call(
            f"resolve-{'first' if index == 1 else 'second'}-owned-vst-object",
            "vst",
            vst_origin,
            "GET",
            f"/vst/api/v1/storage/file/{quote(sensor_id, safe='')}/url?{params}",
            path_template="/vst/api/v1/storage/file/{sensor_id}/url",
        )
        resolved = (
            _decode(resolver.body, "invalid_response") if resolver.status == 200 else {}
        )
        media_url = resolved.get("videoUrl")
        if not isinstance(media_url, str):
            raise ExecutorError("oracle_failed")
        parsed = urlsplit(media_url)
        media_origin = f"{parsed.scheme}://{parsed.netloc}"
        _numeric_origin(media_origin, "invalid_response")
        if (
            media_origin not in allowed_media
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/")
            or parsed.fragment
        ):
            raise ExecutorError("oracle_failed")
        media_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        media = call(
            f"hash-{'first' if index == 1 else 'second'}-owned-vst-object",
            "media",
            media_origin,
            "GET",
            media_path,
            path_template="response-derived-exact-video-url",
            timeout=contract["transport"]["caption_timeout_seconds"],
        )
        if (
            media.status != 200
            or len(media.body) != fixture["stored_media_bytes"]
            or _sha(media.body) != fixture["stored_media_sha256"]
        ):
            raise ExecutorError("oracle_failed")
        fixture_rows.append(
            {
                "sensor_id_sha256": _sha(sensor_id),
                "stored_media_sha256": _sha(media.body),
                "stored_media_bytes": len(media.body),
                "duration_microseconds": duration_us,
                "timeline_readback": True,
                "exact_bytes_readback": True,
            }
        )

    stream = manifest["live_stream"]
    summarize_body = _canonical(
        {
            "id": stream["id"],
            "model": identity["model"],
            "start_time": stream["start_time"],
            "end_time": stream["end_time"],
            "camera_id": stream["id"],
            "delete_external_collection": False,
            "enable_qa": False,
        }
    )
    # The stream UUID maps to one dedicated `default_<uuid>` collection.  A
    # completely empty prestate lets cleanup remove every raw, structured, and
    # aggregate document produced by this run; filtering only `raw_events`
    # would leak the documents written by /v1/stream_summarize.
    es_body = _canonical(
        {
            "size": 0,
            "track_total_hits": True,
            "query": {"match_all": {}},
        }
    )
    delete_body = _canonical({"query": {"match_all": {}}})
    es_index = "default_" + stream["id"].replace("-", "_")
    es_path = f"/{es_index}/_search"
    pre = call(
        "prove-live-caption-collection-preexisting-empty",
        "elasticsearch",
        elasticsearch_origin,
        "POST",
        es_path,
        path_template="/default_{stream_id}/_search",
        body=es_body,
        timeout=contract["transport"]["caption_timeout_seconds"],
    )
    pre_value = _decode(pre.body, "invalid_response")
    preempty = (pre.status == 200 and _es_total(pre_value) == 0) or (
        pre.status == 404 and _is_missing_index(pre_value)
    )
    if not preempty:
        raise ExecutorError("oracle_failed")

    generate_body = _canonical(
        {
            "id": stream["id"],
            "model": identity["model"],
            "prompt": stream["prompt"],
            "chunk_duration": stream["chunk_duration"],
            "chunk_overlap_duration": 0,
            "num_frames_per_second_or_fixed_frames_chunk": 20,
            "use_fps_for_chunking": False,
            "seed": 1,
            "scenario": stream["scenario"],
            "events": stream["events"],
            "objects_of_interest": stream["objects_of_interest"],
            "override_vlm_prompt": True,
            "enable_qa": False,
        }
    )
    caption_start_attempted = False
    caption_accepted = False
    delivered = False
    delivered_count = 0
    poll_attempts = 0
    post_digest = ""
    cleanup_evidence: dict[str, Any] | None = None
    try:
        # Even an interrupted request can reach the server.  Set this before
        # transport so every ambiguous start gets an exact best-effort stop and
        # collection cleanup in `finally`.
        caption_start_attempted = True
        started = call(
            "start-live-caption",
            "lvs",
            lvs_origin,
            "POST",
            "/v1/generate_captions",
            body=generate_body,
            timeout=contract["transport"]["caption_timeout_seconds"],
        )
        started_value = (
            _decode(started.body, "invalid_response") if started.status == 200 else {}
        )
        if started_value != {
            "id": stream["id"],
            "status": "accepted",
            "model": identity["model"],
        }:
            raise ExecutorError("oracle_failed")
        caption_accepted = True

        for poll_attempts in range(1, contract["transport"]["poll_attempts"] + 1):
            if poll_attempts > 1:
                try:
                    sleeper(float(contract["transport"]["poll_delay_seconds"]))
                except Exception as exc:
                    raise ExecutorError("transport_error") from exc
            response = call(
                "observe-live-caption-logstash-delivery",
                "elasticsearch",
                elasticsearch_origin,
                "POST",
                es_path,
                path_template="/default_{stream_id}/_search",
                body=es_body,
                timeout=contract["transport"]["caption_timeout_seconds"],
            )
            value = (
                _decode(response.body, "invalid_response")
                if response.status == 200
                else {}
            )
            count = _es_total(value) if response.status == 200 else -1
            if count > 0:
                delivered = True
                delivered_count = count
                break
            if count != 0:
                raise ExecutorError("oracle_failed")
        if not delivered:
            raise ExecutorError("oracle_failed")

        retrieved_response = call(
            "retrieve-live-caption-from-ca-rag",
            "lvs",
            lvs_origin,
            "POST",
            "/v1/stream_summarize",
            body=summarize_body,
            timeout=contract["transport"]["caption_timeout_seconds"],
        )
        retrieved_value = (
            _decode(retrieved_response.body, "invalid_response")
            if retrieved_response.status == 200
            else {}
        )
        if not _nonempty_completion(
            retrieved_value,
            stream["id"],
            identity["model"],
        ):
            raise ExecutorError("oracle_failed")

        post_response = call(
            "verify-complete-vst-timeline-preserved",
            "vst",
            vst_origin,
            "GET",
            "/vst/api/v1/storage/timelines",
        )
        post_timelines = (
            _decode(post_response.body, "invalid_response")
            if post_response.status == 200
            else {}
        )
        post_digest = _sha(_canonical(post_timelines))
        if post_digest != timeline_digest:
            raise ExecutorError("oracle_failed")
    finally:
        if caption_start_attempted:
            cleanup_failed = False
            stopped = False
            quiescence_counts: list[int] = []
            deleted_count = -1
            absence_counts: list[int] = []

            try:
                stop = call(
                    "stop-exact-live-caption-stream",
                    "rtvi-vlm",
                    rtvi_vlm_origin,
                    "DELETE",
                    f"/v1/generate_captions/{quote(stream['id'], safe='')}",
                    path_template="/v1/generate_captions/{stream_id}",
                    timeout=contract["transport"]["caption_timeout_seconds"],
                    extra_headers={"x-stream-id": stream["id"]},
                    cleanup=True,
                )
                # A known accepted start must have one active stream to stop.
                # For an ambiguous failed start, 400 is an acceptable no-active
                # response only if the scoped DB cleanup below also converges.
                stopped = stop.status == 200
                if not stopped and not (not caption_accepted and stop.status == 400):
                    cleanup_failed = True
            except ExecutorError:
                cleanup_failed = True

            for index in range(2):
                if index:
                    try:
                        sleeper(
                            float(contract["transport"]["cleanup_quiescence_seconds"])
                        )
                    except Exception:
                        cleanup_failed = True
                try:
                    response = call(
                        "prove-stopped-delivery-quiescence",
                        "elasticsearch",
                        elasticsearch_origin,
                        "POST",
                        es_path,
                        path_template="/default_{stream_id}/_search",
                        body=es_body,
                        timeout=contract["transport"]["caption_timeout_seconds"],
                        cleanup=True,
                    )
                    value = (
                        _decode(response.body, "invalid_response")
                        if response.status == 200
                        else {}
                    )
                    if response.status != 200:
                        raise ExecutorError("cleanup_failed")
                    quiescence_counts.append(_es_total(value))
                except ExecutorError:
                    cleanup_failed = True

            quiescent = (
                len(quiescence_counts) == 2
                and quiescence_counts[0] == quiescence_counts[1]
                and quiescence_counts[1] >= delivered_count
            )
            if not quiescent:
                cleanup_failed = True

            try:
                deleted = call(
                    "delete-exact-owned-caption-collection",
                    "elasticsearch",
                    elasticsearch_origin,
                    "POST",
                    f"/{es_index}/_delete_by_query?refresh=true&conflicts=proceed",
                    path_template="/default_{stream_id}/_delete_by_query",
                    body=delete_body,
                    timeout=contract["transport"]["caption_timeout_seconds"],
                    cleanup=True,
                )
                value = (
                    _decode(deleted.body, "invalid_response")
                    if deleted.status == 200
                    else {}
                )
                if deleted.status != 200:
                    raise ExecutorError("cleanup_failed")
                deleted_count = _delete_by_query_count(value)
                if quiescence_counts and deleted_count < max(quiescence_counts):
                    raise ExecutorError("cleanup_failed")
            except ExecutorError:
                cleanup_failed = True

            for index in range(2):
                if index:
                    try:
                        sleeper(
                            float(contract["transport"]["cleanup_quiescence_seconds"])
                        )
                    except Exception:
                        cleanup_failed = True
                try:
                    response = call(
                        "prove-owned-caption-collection-absent",
                        "elasticsearch",
                        elasticsearch_origin,
                        "POST",
                        es_path,
                        path_template="/default_{stream_id}/_search",
                        body=es_body,
                        timeout=contract["transport"]["caption_timeout_seconds"],
                        cleanup=True,
                    )
                    value = (
                        _decode(response.body, "invalid_response")
                        if response.status == 200
                        else {}
                    )
                    if response.status != 200:
                        raise ExecutorError("cleanup_failed")
                    absence_counts.append(_es_total(value))
                except ExecutorError:
                    cleanup_failed = True

            absent = absence_counts == [0, 0]
            if not absent:
                cleanup_failed = True
            cleanup_evidence = {
                "stop_acknowledged": stopped,
                "delivery_quiescent": quiescent,
                "quiescence_observations": len(quiescence_counts),
                "deleted_documents": deleted_count,
                "owned_collection_absent": absent,
                "delayed_no_reappearance": absent,
            }
            if cleanup_failed:
                raise ExecutorError("cleanup_failed")

    if budget.requests < 20 or budget.requests > 24:
        raise ExecutorError("oracle_failed")
    if cleanup_evidence is None:
        raise ExecutorError("cleanup_failed")

    coverage = contract["semantic_coverage"]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "closure_supplement_complete_non_promoting",
        "contract_sha256": _sha(
            _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
        ),
        "manifest_sha256": _sha(_canonical(manifest)),
        "identity": {
            "run_id_sha256": _sha(manifest["run_id"]),
            "agent_origin_sha256": _sha(agent_origin),
            "lvs_origin_sha256": _sha(lvs_origin),
            "rtvi_vlm_origin_sha256": _sha(rtvi_vlm_origin),
            "vst_origin_sha256": _sha(vst_origin),
            "elasticsearch_origin_sha256": _sha(elasticsearch_origin),
            "lvs_version_sha256": _sha(identity["version"]),
            "lvs_sub_version_sha256": _sha(identity["sub_version"]),
            "model_sha256": _sha(identity["model"]),
        },
        "budget": {
            "requests": budget.requests,
            "max_requests": 24,
            "actions": budget.actions,
            "max_actions": 24,
            "max_duration_seconds": 1800,
        },
        "observations": observations,
        "fixture_readback": fixture_rows,
        "live_caption": {
            "stream_id_sha256": _sha(stream["id"]),
            "preexisting_collection_empty": True,
            "generation_accepted": True,
            "logstash_delivery_observed": True,
            "ca_rag_retrieval_nonempty": True,
            "poll_attempts": poll_attempts,
        },
        "state_preservation": {
            "complete_vst_timeline_digest_before": timeline_digest,
            "complete_vst_timeline_digest_after": post_digest,
            "complete_vst_timeline_preserved": True,
            "stream_registration_deleted": False,
        },
        "cleanup": cleanup_evidence,
        "coverage": {
            "closed_by_this_successor": coverage["closed_by_this_successor"],
            "closed_by_predecessor": coverage["closed_by_predecessor"],
            "still_unavoidable": sorted(coverage["still_unavoidable"]),
        },
        "promotion_eligible": False,
        "executor_ready": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "configuration_error")
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute-closure")
    live.add_argument("--manifest", type=Path, required=True)
    live.add_argument("--acknowledgement", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "execute-closure":
            contract = _contract()
            if args.acknowledgement != contract["authorization"]["acknowledgement"]:
                raise ExecutorError("authorization_required")
            result = execute(
                manifest=_json_file(args.manifest, "invalid_manifest"),
                acknowledgement=args.acknowledgement,
            )
        else:
            result = compile_plan()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
