#!/usr/bin/env python3
"""Bounded concrete HTTP candidate for the LVS semantic runtime oracle.

``plan`` is inert. ``execute-http`` requires the exact acknowledgement and a
reviewed manifest. The runtime lane is deliberately a partial successor: it
proves only semantics exposed by the deployed LVS HTTP API and never promotes
the full Agent capability.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
OWNERSHIP_UUID_NAMESPACE = UUID("8f34d639-1b33-4b56-9aa9-cff7be88c144")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class ExecutorError(RuntimeError):
    """Stable public failure code; response and fixture details stay private."""

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
    """urllib transport with environment proxies and redirects disabled."""

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


def _read_regular(
    path: Path, maximum: int, code: str, *, absolute: bool = False
) -> bytes:
    if absolute and not path.is_absolute():
        raise ExecutorError(code)
    if absolute:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise ExecutorError(code)
            except ExecutorError:
                raise
            except OSError as exc:
                raise ExecutorError(code) from exc
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
        pieces: list[bytes] = []
        total = 0
        while total <= maximum:
            piece = os.read(descriptor, min(131072, maximum + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
        raw = b"".join(pieces)
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
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise ExecutorError(code)
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str, *, object_only: bool = True) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ExecutorError(code)
            value[key] = item
        return value

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
    if object_only and not isinstance(value, dict):
        raise ExecutorError(code)
    return value


def _json_file(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    return _decode(_read_regular(path, MAX_CONFIG_BYTES, code), code)


def _validate_schema(value: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _json_file(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ExecutorError(code)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_response") from exc


def _digest(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


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


def _contract() -> dict[str, Any]:
    return _json_file(CONTRACT_PATH)


def _one(rows: Sequence[Any], key: str, value: Any) -> dict[str, Any]:
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    return matches[0]


def _selected_oracle() -> dict[str, Any]:
    selected = _json_file(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
            "post-state-capability-oracles.json"
        )
    )
    rows = selected.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise ExecutorError("configuration_error")
    return _one(rows, "oracle_id", "oracle.runtime.agent.lvs-profile")


def compile_plan() -> dict[str, Any]:
    """Verify sources, frozen oracle state, and the honest partial boundary."""

    contract = _contract()
    workflow = contract.get("http_workflow", [])
    coverage = contract.get("predecessor_action_coverage", {})
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id")
        != "thor-vss-lvs-semantic-runtime-http-successor-v1"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [item.get("order") for item in workflow] != list(range(1, 15))
        or contract.get("execution_bounds")
        != {
            "max_requests": 14,
            "max_actions": 14,
            "max_duration_seconds": 900,
            "owned_file_count": 2,
        }
        or len(coverage.get("concrete_complete", [])) != 1
        or len(coverage.get("concrete_partial", {})) != 5
        or len(coverage.get("residual_adapter_required", {})) != 8
        or contract.get("evidence", {}).get("promotion_eligible") is not False
        or contract.get("evidence", {}).get("executor_ready") is not False
    ):
        raise ExecutorError("configuration_error")
    seen: set[str] = set()
    for lock in contract.get("source_locks", []):
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
            or not SHA256_RE.fullmatch(str(lock["sha256"]))
        ):
            raise ExecutorError("configuration_error")
        seen.add(lock["path"])
        if (
            _digest(
                _read_regular(
                    _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
                )
            )
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")

    oracle = _selected_oracle()
    expected_contract = {
        "cross_agent_prompt_visibility": False,
        "experimental_ui_only": ["stream_summary", "stream_qa"],
        "hitl_fields": ["scenario", "events", "optional_objects"],
        "latest_query_overwrites_shared_prompt": True,
        "live_caption_requires": ["kafka", "logstash"],
        "requirements": ["lvs_backend", "rtvi_vlm", "elasticsearch"],
        "tools": [
            "lvs_video_understanding",
            "lvs_config_media",
            "lvs_stream_understanding",
            "lvs_caption_retrieval",
            "video_report_gen",
        ],
        "uploaded_video_reports": "one_or_multiple",
        "wave3_acceptance": {
            "executor_ready": False,
            "materialized": False,
            "package": "agent-smartcity",
            "planning_requirement_ids": ["lvs-multi-file"],
        },
    }
    bounds = oracle.get("execution_bounds", {})
    if (
        oracle.get("capability_id") != contract["capability_id"]
        or oracle.get("current_state") != "open_unexecuted"
        or oracle.get("evidence") != []
        or oracle.get("fixture", {}).get("input", {}).get("contract")
        != expected_contract
        or bounds.get("max_requests") != 14
        or bounds.get("max_actions") != 14
        or bounds.get("executor") is not None
        or bounds.get("collectors") != []
    ):
        raise ExecutorError("configuration_error")
    Draft202012Validator.check_schema(_json_file(MANIFEST_SCHEMA_PATH))
    Draft202012Validator.check_schema(_json_file(RECEIPT_SCHEMA_PATH))
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_plan_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 14,
        "action_bound": 14,
        "selected_metadata_rows": 500,
        "selected_metadata_lvs_state": "open_unexecuted_null_bound",
        "concrete_complete_actions": 1,
        "concrete_partial_actions": 5,
        "residual_adapter_actions": 8,
        "executor_ready": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
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


def _manifest(path: Path) -> dict[str, Any]:
    value = _json_file(path, "invalid_manifest")
    _validate_schema(value, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    value["lvs_origin"] = _origin(value["lvs_origin"])
    fixtures = value["fixtures"]
    if (
        fixtures[0]["sha256"] == fixtures[1]["sha256"]
        or fixtures[0]["path"] == fixtures[1]["path"]
    ):
        raise ExecutorError("invalid_manifest")
    return value


class _Budget:
    def __init__(self, *, maximum: int, duration_seconds: int) -> None:
        self.maximum = maximum
        self.duration_seconds = duration_seconds
        self.requests = 0
        self.actions = 0
        self.started = time.monotonic()

    def consume(self) -> None:
        if self.requests >= self.maximum or self.actions >= self.maximum:
            raise ExecutorError("oracle_failed")
        if time.monotonic() - self.started > self.duration_seconds:
            raise ExecutorError("oracle_failed")
        self.requests += 1
        self.actions += 1


def _file_row(value: Any, *, require_media_type: bool) -> dict[str, Any]:
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
    rows = [_file_row(row, require_media_type=True) for row in value["data"]]
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)) or len(ids) > 1_000_000:
        raise ExecutorError("invalid_response")
    return rows


def _unrelated_projection(
    rows: list[dict[str, Any]], owned_ids: set[str]
) -> list[dict[str, Any]]:
    projection = [row for row in rows if str(row["id"]) not in owned_ids]
    return sorted(projection, key=lambda row: str(row["id"]))


def _multipart(
    *,
    run_id: str,
    file_id: str,
    filename: str,
    media: bytes,
    sequence: int,
) -> tuple[str, bytes]:
    boundary = f"vss-lvs-{_digest(f'{run_id}:{sequence}')[:32]}"
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": file_id,
        "sensor_name": f"vss-{_digest(run_id)[:16]}-{sequence}",
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


def _report_nonempty(value: Any, *, file_id: str, model: str) -> bool:
    if (
        not isinstance(value, dict)
        or value.get("video_id") != file_id
        or value.get("model") != model
        or not isinstance(value.get("choices"), list)
        or not value["choices"]
    ):
        return False
    try:
        content = value["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return False
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        structured = json.loads(content)
    except json.JSONDecodeError:
        return True
    if not isinstance(structured, dict):
        return False
    summary = structured.get("video_summary")
    events = structured.get("events")
    return (isinstance(summary, str) and bool(summary.strip())) or (
        isinstance(events, list) and bool(events)
    )


def execute(
    *,
    manifest: Mapping[str, Any],
    acknowledgement: str,
    transport: Transport,
) -> dict[str, Any]:
    """Execute the concrete HTTP subset against an already-approved deployment."""

    plan = compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    if not isinstance(manifest, Mapping):
        raise ExecutorError("invalid_manifest")
    manifest = dict(manifest)
    _validate_schema(manifest, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    manifest["lvs_origin"] = _origin(manifest["lvs_origin"])
    if (
        not RUN_ID_RE.fullmatch(manifest["run_id"])
        or manifest["fixtures"][0]["sha256"] == manifest["fixtures"][1]["sha256"]
        or manifest["fixtures"][0]["path"] == manifest["fixtures"][1]["path"]
        or transport.proxies_enabled
        or transport.redirects_enabled
    ):
        raise ExecutorError("invalid_manifest")

    fixture_bytes: list[bytes] = []
    fixture_names: list[str] = []
    for item in manifest["fixtures"]:
        path = Path(item["path"])
        name = path.name
        try:
            canonical_path = path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ExecutorError("invalid_manifest") from exc
        if path != canonical_path or not SAFE_FILENAME_RE.fullmatch(name):
            raise ExecutorError("invalid_manifest")
        raw = _read_regular(
            path,
            contract["transport"]["max_fixture_bytes_each"],
            "invalid_manifest",
            absolute=True,
        )
        if _digest(raw) != item["sha256"]:
            raise ExecutorError("invalid_manifest")
        fixture_bytes.append(raw)
        fixture_names.append(name)

    budget = _Budget(maximum=14, duration_seconds=900)
    observations: list[dict[str, Any]] = []
    registered: list[str] = []
    deleted: set[str] = set()
    owned_ids = {
        str(
            uuid5(
                OWNERSHIP_UUID_NAMESPACE,
                f"{manifest['run_id']}:{index}:{item['sha256']}",
            )
        )
        for index, item in enumerate(manifest["fixtures"], 1)
    }
    if len(owned_ids) != 2:
        raise ExecutorError("invalid_manifest")
    ordered_ids = sorted(owned_ids)
    pre_projection: list[dict[str, Any]] | None = None

    def call(
        action_id: str,
        method: str,
        path: str,
        *,
        path_template: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: int | None = None,
        cleanup: bool = False,
    ) -> Response:
        budget.consume()
        if body is not None and len(body) > contract["transport"]["max_request_bytes"]:
            raise ExecutorError("invalid_manifest")
        headers = {"Accept": "application/json"}
        if content_type is not None:
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
            or not isinstance(response.body, bytes)
            or len(response.body) > contract["transport"]["max_response_bytes"]
        ):
            raise ExecutorError("invalid_response")
        observations.append(
            {
                "order": budget.actions,
                "action_id": action_id,
                "method": method,
                "path_template": path_template or path,
                "http_status": response.status,
                "response_bytes": len(response.body),
                "response_sha256": _digest(response.body),
                "result": "cleanup_pass" if cleanup else "pass",
            }
        )
        return response

    primary: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        pre = call(
            "capture-pre-state", "GET", "/files?purpose=vision", path_template="/files"
        )
        if pre.status != 200:
            raise ExecutorError("oracle_failed")
        pre_rows = _file_list(_decode(pre.body, "invalid_response"))
        if owned_ids.intersection(str(row["id"]) for row in pre_rows):
            raise ExecutorError("oracle_failed")
        pre_projection = _unrelated_projection(pre_rows, owned_ids)

        ready = call("verify-lvs-ready", "GET", "/v1/ready")
        if ready.status != 200:
            raise ExecutorError("oracle_failed")

        models = call("verify-model-advertised", "GET", "/models")
        model_data = (
            _decode(models.body, "invalid_response") if models.status == 200 else {}
        )
        advertised = model_data.get("data") if isinstance(model_data, dict) else None
        if not isinstance(advertised, list) or not any(
            isinstance(row, dict) and row.get("id") == manifest["model"]
            for row in advertised
        ):
            raise ExecutorError("oracle_failed")

        for sequence, (file_id, raw, name) in enumerate(
            zip(ordered_ids, fixture_bytes, fixture_names), 1
        ):
            boundary, multipart = _multipart(
                run_id=manifest["run_id"],
                file_id=file_id,
                filename=name,
                media=raw,
                sequence=sequence,
            )
            upload = call(
                f"upload-{'first' if sequence == 1 else 'second'}-owned-file",
                "POST",
                "/files",
                body=multipart,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
            uploaded = _file_row(
                _decode(upload.body, "invalid_response"), require_media_type=True
            )
            expected_sensor = f"vss-{_digest(manifest['run_id'])[:16]}-{sequence}"
            if (
                upload.status != 200
                or str(uploaded["id"]) != file_id
                or uploaded["bytes"] != len(raw)
                or uploaded["filename"] != name
                or uploaded["sensor_name"] != expected_sensor
            ):
                raise ExecutorError("oracle_failed")
            registered.append(file_id)

            readback = call(
                f"verify-{'first' if sequence == 1 else 'second'}-owned-file",
                "GET",
                f"/files/{file_id}",
                path_template="/files/{owned_file_id}",
            )
            fetched = _file_row(
                _decode(readback.body, "invalid_response"), require_media_type=False
            )
            if (
                readback.status != 200
                or str(fetched["id"]) != file_id
                or fetched["bytes"] != len(raw)
                or fetched["filename"] != name
                or fetched["sensor_name"] != expected_sensor
            ):
                raise ExecutorError("oracle_failed")

        request_value = {
            "id": ordered_ids[0],
            "model": manifest["model"],
            "scenario": manifest["scenario"],
            "events": manifest["events"],
            "objects_of_interest": manifest.get("objects_of_interest", []),
            "chunk_duration": 10,
            "num_frames_per_second_or_fixed_frames_chunk": 20,
            "use_fps_for_chunking": False,
            "seed": 1,
        }
        report = call(
            "single-video-report",
            "POST",
            "/v1/summarize",
            body=_canonical(request_value),
            content_type="application/json",
            timeout=contract["transport"]["summarize_timeout_seconds"],
        )
        report_value = (
            _decode(report.body, "invalid_response") if report.status == 200 else {}
        )
        if not _report_nonempty(
            report_value, file_id=ordered_ids[0], model=manifest["model"]
        ):
            raise ExecutorError("oracle_failed")
    except BaseException as exc:
        primary = exc
    finally:
        cleanup_failed = False
        for file_id in reversed(registered):
            label = "second" if file_id == ordered_ids[1] else "first"
            try:
                deletion = call(
                    f"cleanup-{label}-owned-file",
                    "DELETE",
                    f"/files/{file_id}",
                    path_template="/files/{owned_file_id}",
                    cleanup=True,
                )
                value = (
                    _decode(deletion.body, "invalid_response")
                    if deletion.status == 200
                    else {}
                )
                if value != {"id": file_id, "object": "file", "deleted": True}:
                    cleanup_failed = True
                else:
                    deleted.add(file_id)
            except BaseException:
                cleanup_failed = True
            try:
                absent = call(
                    f"verify-{label}-owned-absence",
                    "GET",
                    "/files?purpose=vision",
                    path_template="/files",
                    cleanup=True,
                )
                rows = (
                    _file_list(_decode(absent.body, "invalid_response"))
                    if absent.status == 200
                    else []
                )
                if absent.status != 200 or file_id in {str(row["id"]) for row in rows}:
                    cleanup_failed = True
            except BaseException:
                cleanup_failed = True

        try:
            restored = call(
                "verify-unrelated-state-restored",
                "GET",
                "/files?purpose=vision",
                path_template="/files",
                cleanup=True,
            )
            restored_rows = (
                _file_list(_decode(restored.body, "invalid_response"))
                if restored.status == 200
                else []
            )
            if (
                restored.status != 200
                or pre_projection is None
                or _canonical(_unrelated_projection(restored_rows, owned_ids))
                != _canonical(pre_projection)
                or owned_ids.intersection(str(row["id"]) for row in restored_rows)
            ):
                cleanup_failed = True
        except BaseException:
            cleanup_failed = True

        try:
            final_ready = call(
                "verify-lvs-ready-after-cleanup",
                "GET",
                "/v1/ready",
                cleanup=True,
            )
            if final_ready.status != 200:
                cleanup_failed = True
        except BaseException:
            cleanup_failed = True
        if cleanup_failed:
            cleanup_error = ExecutorError("cleanup_failed")

    if cleanup_error is not None:
        if isinstance(cleanup_error, ExecutorError):
            raise cleanup_error
        raise ExecutorError("cleanup_failed") from cleanup_error
    if primary is not None:
        if isinstance(primary, ExecutorError):
            raise primary
        raise ExecutorError("oracle_failed") from primary
    if (
        len(registered) != 2
        or deleted != owned_ids
        or budget.requests != 14
        or budget.actions != 14
        or time.monotonic() - budget.started > budget.duration_seconds
    ):
        raise ExecutorError("oracle_failed")

    coverage = contract["predecessor_action_coverage"]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "candidate_pass",
        "contract_sha256": _digest(
            _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
        ),
        "run_id_sha256": _digest(manifest["run_id"]),
        "origin_sha256": _digest(manifest["lvs_origin"]),
        "fixture_sha256": [item["sha256"] for item in manifest["fixtures"]],
        "model_sha256": _digest(manifest["model"]),
        "budget": {
            "requests": budget.requests,
            "max_requests": 14,
            "actions": budget.actions,
            "max_actions": 14,
            "max_duration_seconds": 900,
        },
        "observations": observations,
        "semantic_coverage": {
            "concrete_complete": coverage["concrete_complete"],
            "concrete_partial": list(coverage["concrete_partial"]),
            "residual_adapter_required": list(coverage["residual_adapter_required"]),
        },
        "cleanup": {
            "registered_owned_files": 2,
            "deleted_owned_files": 2,
            "owned_absent": True,
            "unrelated_state_restored": True,
            "exact_delete_confirmations": True,
        },
        "promotion_eligible": False,
        "executor_ready": False,
        "warehouse_sample_bundle": "excluded",
    }
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "configuration_error")
    if plan["executor_ready"] is not False:
        raise ExecutorError("configuration_error")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute-http")
    live.add_argument("--manifest", required=True)
    live.add_argument("--acknowledgement", required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = compile_plan()
        else:
            if args.acknowledgement != _contract()["authorization"]["acknowledgement"]:
                raise ExecutorError("authorization_required")
            result = execute(
                manifest=_manifest(Path(args.manifest)),
                acknowledgement=args.acknowledgement,
                transport=LiveTransport(),
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
