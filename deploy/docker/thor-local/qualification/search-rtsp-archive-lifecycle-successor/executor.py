#!/usr/bin/env python3
"""Bounded, authorization-gated Search RTSP archive lifecycle candidate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, cast, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTROL_SCHEMA_PATH = HERE / "control.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
)
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


class LifecycleError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "control_changed",
        "fixture_not_ready",
        "ownership_conflict",
        "source_drift",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise LifecycleError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise LifecycleError("configuration_error")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            if not chunk:
                raise LifecycleError("configuration_error")
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
            raise LifecycleError("configuration_error")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str = "transport_error") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise LifecycleError(code)
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(LifecycleError(code)),
        )
    except LifecycleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifecycleError(code) from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise LifecycleError("configuration_error") from exc


def _schema(path: Path) -> Any:
    value = _decode(_read_regular(path, MAX_CONFIG_BYTES), "configuration_error")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise LifecycleError("configuration_error") from exc
    return value


def _validate(value: Any, path: Path, code: str = "configuration_error") -> None:
    if list(Draft202012Validator(_schema(path)).iter_errors(value)):
        raise LifecycleError(code)


def _contract() -> dict[str, Any]:
    value = _decode(
        _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES), "configuration_error"
    )
    if not isinstance(value, dict):
        raise LifecycleError("configuration_error")
    return value


def _repo_file(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise LifecycleError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise LifecycleError("configuration_error")
        except OSError as exc:
            raise LifecycleError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise LifecycleError("configuration_error") from exc
    return current


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    _schema(CONTROL_SCHEMA_PATH)
    _schema(RECEIPT_SCHEMA_PATH)
    expected = [
        "validate-authorization-origins-reviewed-rtsp-and-control",
        "prove-owned-name-and-name-scoped-documents-absent",
        "capture-reviewed-unrelated-control-projection",
        "add-exact-run-owned-rtsp-through-agent",
        "bind-add-response-to-exact-name-and-stable-sensor-id",
        "poll-vst-readiness-for-same-id-and-name",
        "poll-fixed-search-indices-with-complete-accounting",
        "delete-through-agent-by-exact-name-and-identity",
        "prove-exact-vst-and-search-absence",
        "prove-unrelated-control-preserved",
        "prove-delayed-no-reappearance",
    ]
    bounds = contract.get("execution_bounds", {})
    decision = contract.get("decision", {})
    if (
        contract.get("package_id") != "search-rtsp-archive-lifecycle-successor"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("order") for row in contract.get("workflow", [])]
        != list(range(1, 12))
        or [row.get("id") for row in contract.get("workflow", [])] != expected
        or bounds.get("max_requests") != 64
        or bounds.get("max_actions") != 11
        or bounds.get("cleanup_reserve_seconds") != 180
        or contract.get("indices")
        != {
            "embed": "mdx-embed-filtered-2025-01-01",
            "behavior": "mdx-behavior-2025-01-01",
            "raw": "mdx-raw-2025-01-01",
        }
        or decision.get("rtsp_add_readiness_delete_candidate_implemented") is not True
        or decision.get("runtime_receipt_present") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
    ):
        raise LifecycleError("configuration_error")
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 3:
        raise LifecycleError("configuration_error")
    seen: set[str] = set()
    locked: dict[str, bytes] = {}
    for lock in locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
        ):
            raise LifecycleError("configuration_error")
        seen.add(lock["path"])
        raw = _read_regular(_repo_file(lock["path"]), MAX_CONFIG_BYTES)
        if hashlib.sha256(raw).hexdigest() != lock["sha256"]:
            raise LifecycleError("source_drift")
        locked[lock["path"]] = raw
    ingest = locked["services/agent/src/vss_agents/api/rtsp_ingest.py"].decode()
    delete = locked["services/agent/src/vss_agents/api/rtsp_delete.py"].decode()
    config = locked[
        "deploy/docker/developer-profiles/dev-profile-search/vss-agent/configs/config.yml"
    ].decode()
    required = (
        '"/api/v1/rtsp-streams/add"' in ingest
        and "sensor_id=sensor_id" in ingest
        and "name=request.name" in ingest
        and '"/api/v1/rtsp-streams/delete/{name}"' in delete
        and "sensor_id=stream_id" in delete
        and "rtvi_embed_base_url:" in config
        and "rtvi_cv_base_url:" in config
        and "elasticsearch_url:" in config
    )
    if not required:
        raise LifecycleError("source_drift")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_rtsp_archive_lifecycle_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 64,
        "action_bound": 11,
        "runtime_receipt_present": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class LiveOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, request: Request, timeout: float) -> Any:
        return self._opener.open(request, timeout=timeout)


class RequestBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0

    def take(self) -> None:
        if self.used >= self.maximum:
            raise LifecycleError("transport_error")
        self.used += 1


class DeadlineOpener:
    proxies_enabled: Any = False
    redirects_enabled: Any = False

    def __init__(
        self,
        opener: Any,
        maximum_seconds: float,
        cleanup_reserve_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._opener = opener
        self._monotonic = monotonic
        self._started = monotonic()
        self._deadline = self._started + maximum_seconds
        self._cleanup_reserve = cleanup_reserve_seconds
        self._cleanup = False
        self.proxies_enabled = getattr(opener, "proxies_enabled", None)
        self.redirects_enabled = getattr(opener, "redirects_enabled", None)

    def enter_cleanup(self) -> None:
        self._cleanup = True

    def open(self, request: Request, timeout: float) -> Any:
        reserve = 0.0 if self._cleanup else self._cleanup_reserve
        remaining = self._deadline - self._monotonic() - reserve
        if remaining <= 0:
            raise LifecycleError("transport_error")
        return self._opener.open(request, timeout=min(float(timeout), remaining))


def _origin(value: str) -> str:
    parsed = urlparse(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise LifecycleError("configuration_error") from exc
    if (
        parsed.scheme != "http"
        or not address.is_loopback
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise LifecycleError("configuration_error")
    return f"http://{address.compressed}:{port}"


def _rtsp_url(value: str, reviewed_sha256: str) -> str:
    if (
        not SHA_RE.fullmatch(reviewed_sha256)
        or hashlib.sha256(value.encode("utf-8")).hexdigest() != reviewed_sha256
    ):
        raise LifecycleError("authorization_required")
    parsed = urlparse(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise LifecycleError("configuration_error") from exc
    if (
        parsed.scheme != "rtsp"
        or not (address.is_loopback or address.is_private)
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise LifecycleError("configuration_error")
    return value


def _response(response: Any, maximum: int) -> tuple[int, str, bytes]:
    raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise LifecycleError("transport_error")
    content_type = (
        response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    )
    return int(response.status), content_type, raw


def _json_request(
    opener: Any,
    budget: RequestBudget,
    *,
    method: str,
    url: str,
    timeout: float,
    maximum: int,
    value: Any | None = None,
    allowed: tuple[int, ...] = (200, 201),
) -> Any:
    data = None if value is None else _canonical(value)
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    budget.take()
    try:
        status, content_type, raw = _response(opener.open(request, timeout), maximum)
    except HTTPError as exc:
        status, content_type, raw = _response(exc, maximum)
    except LifecycleError:
        raise
    except Exception as exc:
        raise LifecycleError("transport_error") from exc
    if status not in allowed or content_type != "application/json":
        raise LifecycleError("transport_error")
    return _decode(raw)


def _streams(value: Any) -> dict[str, str | None]:
    if not isinstance(value, list) or len(value) > 10000:
        raise LifecycleError("transport_error")
    result: dict[str, str | None] = {}
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            raise LifecycleError("transport_error")
        sensor_id, entries = next(iter(item.items()))
        if (
            not isinstance(sensor_id, str)
            or sensor_id in result
            or not isinstance(entries, list)
        ):
            raise LifecycleError("transport_error")
        if not entries:
            result[sensor_id] = None
            continue
        first = entries[0]
        if not isinstance(first, dict) or not isinstance(first.get("name"), str):
            raise LifecycleError("transport_error")
        result[sensor_id] = first["name"]
    return result


def _search_body(field: str, value: str, maximum: int) -> dict[str, Any]:
    return {
        "query": {"term": {field: value}},
        "size": maximum,
        "sort": [{"_id": {"order": "asc"}}],
    }


def _hits(value: Any, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("timed_out") is not False:
        raise LifecycleError("transport_error")
    shards = value.get("_shards")
    if not isinstance(shards, dict):
        raise LifecycleError("transport_error")
    raw_counts = tuple(
        shards.get(key) for key in ("total", "successful", "skipped", "failed")
    )
    if any(type(count) is not int or count < 0 for count in raw_counts):
        raise LifecycleError("transport_error")
    counts = cast(tuple[int, int, int, int], raw_counts)
    if counts[3] != 0 or counts[1] + counts[2] != counts[0]:
        raise LifecycleError("transport_error")
    try:
        hit_block, rows = value["hits"], value["hits"]["hits"]
        total = hit_block["total"]
    except (KeyError, TypeError) as exc:
        raise LifecycleError("transport_error") from exc
    if (
        not isinstance(rows, list)
        or len(rows) > maximum
        or not isinstance(total, dict)
        or total.get("relation") != "eq"
        or type(total.get("value")) is not int
        or total["value"] != len(rows)
    ):
        raise LifecycleError("transport_error")
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("_index"), str)
            or not isinstance(row.get("_id"), str)
            or not isinstance(row.get("_source"), dict)
        ):
            raise LifecycleError("transport_error")
    return rows


def _query_scopes(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    indices: Mapping[str, str],
    sensor_id: str,
    name: str,
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
) -> dict[str, list[dict[str, Any]]]:
    scopes = {
        "embed": ("sensor.id.keyword", sensor_id),
        "behavior": ("sensor.id.keyword", name),
        "raw": ("sensorId.keyword", name),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for family in ("embed", "behavior", "raw"):
        field, expected = scopes[family]
        value = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{es_origin}/{quote(indices[family], safe='')}/_search",
            timeout=timeout,
            maximum=maximum_response,
            value=_search_body(field, expected, maximum_documents),
        )
        result[family] = _hits(value, maximum_documents)
    return result


def _prove_name_scopes_absent(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    indices: Mapping[str, str],
    name: str,
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
    code: str = "ownership_conflict",
) -> None:
    for family, field in (
        ("behavior", "sensor.id.keyword"),
        ("raw", "sensorId.keyword"),
    ):
        response = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{es_origin}/{quote(indices[family], safe='')}/_search",
            timeout=timeout,
            maximum=maximum_response,
            value=_search_body(field, name, maximum_documents),
        )
        if _hits(response, maximum_documents):
            raise LifecycleError(code)


def _assert_owned(
    documents: Mapping[str, Sequence[Mapping[str, Any]]], sensor_id: str, name: str
) -> None:
    for row in documents["embed"]:
        source = row["_source"]
        if (
            not isinstance(source.get("sensor"), Mapping)
            or source["sensor"].get("id") != sensor_id
        ):
            raise LifecycleError("ownership_conflict")
    for row in documents["behavior"]:
        source = row["_source"]
        if (
            not isinstance(source.get("sensor"), Mapping)
            or source["sensor"].get("id") != name
        ):
            raise LifecycleError("ownership_conflict")
    for row in documents["raw"]:
        if row["_source"].get("sensorId") != name:
            raise LifecycleError("ownership_conflict")


def _documents(
    documents: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for family in ("embed", "behavior", "raw"):
        for row in documents[family]:
            key = (row["_index"], row["_id"])
            if key in seen:
                raise LifecycleError("transport_error")
            seen.add(key)
            result.append({"index": key[0], "document_id": key[1]})
    return result


def _mget(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    requested: Sequence[Mapping[str, str]],
    timeout: float,
    maximum: int,
) -> list[dict[str, Any]]:
    response = _json_request(
        opener,
        budget,
        method="POST",
        url=f"{es_origin}/_mget",
        timeout=timeout,
        maximum=maximum,
        value={
            "docs": [
                {"_index": row["index"], "_id": row["document_id"]} for row in requested
            ]
        },
    )
    rows = response.get("docs") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) != len(requested):
        raise LifecycleError("transport_error")
    for row, wanted in zip(rows, requested):
        if (
            not isinstance(row, dict)
            or row.get("_index") != wanted["index"]
            or row.get("_id") != wanted["document_id"]
        ):
            raise LifecycleError("transport_error")
    return rows


def _load_control(
    path: Path,
    reviewed_sha256: str,
    indices: Mapping[str, str],
    name: str,
) -> tuple[dict[str, Any], str]:
    raw = _read_regular(path, _contract()["transport"]["max_control_bytes"])
    digest = hashlib.sha256(raw).hexdigest()
    if not SHA_RE.fullmatch(reviewed_sha256) or digest != reviewed_sha256:
        raise LifecycleError("authorization_required")
    value = _decode(raw, "configuration_error")
    _validate(value, CONTROL_SCHEMA_PATH)
    if value["name"] == name:
        raise LifecycleError("configuration_error")
    families = {row["family"]: row for row in value["documents"]}
    if set(families) != set(indices) or any(
        families[key]["index"] != indices[key] for key in indices
    ):
        raise LifecycleError("configuration_error")
    return value, digest


def _assert_control(
    opener: Any,
    budget: RequestBudget,
    *,
    vst_origin: str,
    es_origin: str,
    control: Mapping[str, Any],
    timeout: float,
    maximum: int,
    streams: Mapping[str, str | None] | None = None,
) -> None:
    current = streams
    if current is None:
        current = _streams(
            _json_request(
                opener,
                budget,
                method="GET",
                url=f"{vst_origin}/vst/api/v1/sensor/streams",
                timeout=timeout,
                maximum=maximum,
            )
        )
    if current.get(control["sensor_id"]) != control["name"]:
        raise LifecycleError("control_changed")
    requested = [
        {"index": row["index"], "document_id": row["document_id"]}
        for row in control["documents"]
    ]
    rows = _mget(
        opener,
        budget,
        es_origin=es_origin,
        requested=requested,
        timeout=timeout,
        maximum=maximum,
    )
    for actual, expected in zip(rows, control["documents"]):
        if (
            actual.get("found") is not True
            or not isinstance(actual.get("_source"), dict)
            or hashlib.sha256(_canonical(actual["_source"])).hexdigest()
            != expected["source_sha256"]
        ):
            raise LifecycleError("control_changed")


def _exact_absence(
    opener: Any,
    budget: RequestBudget,
    *,
    vst_origin: str,
    es_origin: str,
    indices: Mapping[str, str],
    sensor_id: str,
    name: str,
    documents: Sequence[Mapping[str, str]],
    control: Mapping[str, Any],
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
) -> None:
    streams = _streams(
        _json_request(
            opener,
            budget,
            method="GET",
            url=f"{vst_origin}/vst/api/v1/sensor/streams",
            timeout=timeout,
            maximum=maximum_response,
        )
    )
    if sensor_id in streams or name in streams.values():
        raise LifecycleError("cleanup_failed")
    if any(
        _query_scopes(
            opener,
            budget,
            es_origin=es_origin,
            indices=indices,
            sensor_id=sensor_id,
            name=name,
            timeout=timeout,
            maximum_response=maximum_response,
            maximum_documents=maximum_documents,
        ).values()
    ):
        raise LifecycleError("cleanup_failed")
    rows = _mget(
        opener,
        budget,
        es_origin=es_origin,
        requested=documents,
        timeout=timeout,
        maximum=maximum_response,
    )
    if any(row.get("found") is not False for row in rows):
        raise LifecycleError("cleanup_failed")
    _assert_control(
        opener,
        budget,
        vst_origin=vst_origin,
        es_origin=es_origin,
        control=control,
        timeout=timeout,
        maximum=maximum_response,
        streams=streams,
    )


def execute_lifecycle(
    *,
    run_id: str,
    acknowledgement: str,
    rtsp_url: str,
    reviewed_rtsp_sha256: str,
    control_path: Path,
    reviewed_control_sha256: str,
    agent_origin: str,
    vst_origin: str,
    elasticsearch_origin: str,
    opener_factory: Callable[[], Any] = LiveOpener,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise LifecycleError("authorization_required")
    if not RUN_RE.fullmatch(run_id):
        raise LifecycleError("configuration_error")
    name = f"vss-search-rtsp-owned-{run_id}"
    reviewed_rtsp = _rtsp_url(rtsp_url, reviewed_rtsp_sha256)
    agent, vst, es = (
        _origin(agent_origin),
        _origin(vst_origin),
        _origin(elasticsearch_origin),
    )
    control, control_digest = _load_control(
        control_path, reviewed_control_sha256, contract["indices"], name
    )
    timeout = float(contract["transport"]["timeout_seconds"])
    maximum_response = int(contract["transport"]["max_response_bytes"])
    maximum_documents = int(contract["execution_bounds"]["max_documents_per_index"])
    budget = RequestBudget(int(contract["execution_bounds"]["max_requests"]))
    started = monotonic()
    opener = DeadlineOpener(
        opener_factory(),
        float(contract["execution_bounds"]["max_duration_seconds"]),
        float(contract["execution_bounds"]["cleanup_reserve_seconds"]),
        monotonic,
    )
    if (
        getattr(opener, "proxies_enabled", None) is not False
        or getattr(opener, "redirects_enabled", None) is not False
    ):
        raise LifecycleError("configuration_error")

    sensor_id: str | None = None
    add_attempted = False
    ready: dict[str, list[dict[str, Any]]] | None = None
    discovered: list[dict[str, str]] = []
    original_error: LifecycleError | None = None
    cleanup_complete = False
    try:
        streams = _streams(
            _json_request(
                opener,
                budget,
                method="GET",
                url=f"{vst}/vst/api/v1/sensor/streams",
                timeout=timeout,
                maximum=maximum_response,
            )
        )
        if name in streams.values():
            raise LifecycleError("ownership_conflict")
        _prove_name_scopes_absent(
            opener,
            budget,
            es_origin=es,
            indices=contract["indices"],
            name=name,
            timeout=timeout,
            maximum_response=maximum_response,
            maximum_documents=maximum_documents,
        )
        _assert_control(
            opener,
            budget,
            vst_origin=vst,
            es_origin=es,
            control=control,
            timeout=timeout,
            maximum=maximum_response,
            streams=streams,
        )

        add_attempted = True
        added = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{agent}/api/v1/rtsp-streams/add",
            timeout=timeout,
            maximum=maximum_response,
            value={
                "sensorUrl": reviewed_rtsp,
                "name": name,
                "username": "",
                "password": "",
                "location": "",
                "tags": "",
            },
        )
        reported_id = added.get("sensorId") if isinstance(added, dict) else None
        if (
            added.get("status") != "success"
            or added.get("name") != name
            or not isinstance(reported_id, str)
            or not UUID_RE.fullmatch(reported_id)
        ):
            raise LifecycleError("transport_error")
        if reported_id == control["sensor_id"]:
            raise LifecycleError("ownership_conflict")

        for attempt in range(
            contract["execution_bounds"]["vst_readiness_poll_attempts"]
        ):
            streams = _streams(
                _json_request(
                    opener,
                    budget,
                    method="GET",
                    url=f"{vst}/vst/api/v1/sensor/streams",
                    timeout=timeout,
                    maximum=maximum_response,
                )
            )
            matches = [item for item, item_name in streams.items() if item_name == name]
            if len(matches) > 1:
                raise LifecycleError("ownership_conflict")
            if matches == [reported_id]:
                sensor_id = reported_id
                break
            if matches and matches != [reported_id]:
                raise LifecycleError("ownership_conflict")
            if (
                attempt + 1
                < contract["execution_bounds"]["vst_readiness_poll_attempts"]
            ):
                sleeper(float(contract["execution_bounds"]["poll_delay_seconds"]))
        if sensor_id is None:
            raise LifecycleError("fixture_not_ready")

        for attempt in range(
            contract["execution_bounds"]["search_readiness_poll_attempts"]
        ):
            ready = _query_scopes(
                opener,
                budget,
                es_origin=es,
                indices=contract["indices"],
                sensor_id=sensor_id,
                name=name,
                timeout=timeout,
                maximum_response=maximum_response,
                maximum_documents=maximum_documents,
            )
            if all(ready.values()):
                _assert_owned(ready, sensor_id, name)
                break
            if (
                attempt + 1
                < contract["execution_bounds"]["search_readiness_poll_attempts"]
            ):
                sleeper(float(contract["execution_bounds"]["poll_delay_seconds"]))
        if ready is None or not all(ready.values()):
            raise LifecycleError("fixture_not_ready")
        discovered = _documents(ready)
    except LifecycleError as exc:
        original_error = exc
    finally:
        opener.enter_cleanup()
        if add_attempted and sensor_id is None:
            try:
                streams = _streams(
                    _json_request(
                        opener,
                        budget,
                        method="GET",
                        url=f"{vst}/vst/api/v1/sensor/streams",
                        timeout=timeout,
                        maximum=maximum_response,
                    )
                )
                matches = [
                    item for item, item_name in streams.items() if item_name == name
                ]
                if len(matches) > 1 or (matches and not UUID_RE.fullmatch(matches[0])):
                    raise LifecycleError("cleanup_failed")
                sensor_id = matches[0] if matches else None
                if sensor_id is None:
                    _prove_name_scopes_absent(
                        opener,
                        budget,
                        es_origin=es,
                        indices=contract["indices"],
                        name=name,
                        timeout=timeout,
                        maximum_response=maximum_response,
                        maximum_documents=maximum_documents,
                        code="cleanup_failed",
                    )
                    _assert_control(
                        opener,
                        budget,
                        vst_origin=vst,
                        es_origin=es,
                        control=control,
                        timeout=timeout,
                        maximum=maximum_response,
                        streams=streams,
                    )
                    cleanup_complete = True
            except LifecycleError:
                cleanup_complete = False
        if sensor_id is not None:
            try:
                deleted = _json_request(
                    opener,
                    budget,
                    method="DELETE",
                    url=f"{agent}/api/v1/rtsp-streams/delete/{quote(name, safe='')}",
                    timeout=timeout,
                    maximum=maximum_response,
                    allowed=(200,),
                )
                if (
                    not isinstance(deleted, dict)
                    or deleted.get("status") != "success"
                    or deleted.get("name") != name
                    or deleted.get("sensorId") != sensor_id
                ):
                    raise LifecycleError("cleanup_failed")
                for attempt in range(
                    contract["execution_bounds"]["cleanup_poll_attempts"]
                ):
                    if attempt:
                        sleeper(
                            float(contract["execution_bounds"]["poll_delay_seconds"])
                        )
                    _exact_absence(
                        opener,
                        budget,
                        vst_origin=vst,
                        es_origin=es,
                        indices=contract["indices"],
                        sensor_id=sensor_id,
                        name=name,
                        documents=discovered,
                        control=control,
                        timeout=timeout,
                        maximum_response=maximum_response,
                        maximum_documents=maximum_documents,
                    )
                cleanup_complete = True
            except LifecycleError:
                cleanup_complete = False
        if add_attempted and not cleanup_complete:
            raise LifecycleError("cleanup_failed")

    if original_error is not None:
        raise original_error
    if sensor_id is None or ready is None or not all(ready.values()) or not discovered:
        raise LifecycleError("fixture_not_ready")
    if monotonic() - started > contract["execution_bounds"]["max_duration_seconds"]:
        raise LifecycleError("transport_error")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-numeric-local-rtsp-archive-lifecycle",
        "status": "candidate_rtsp_archive_lifecycle_complete_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "identity": {
            "run_id": run_id,
            "name_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "sensor_id_sha256": hashlib.sha256(sensor_id.encode()).hexdigest(),
            "rtsp_url_sha256": reviewed_rtsp_sha256,
        },
        "readiness": {
            "vst_exact_identity": True,
            "embed_documents": len(ready["embed"]),
            "behavior_documents": len(ready["behavior"]),
            "raw_documents": len(ready["raw"]),
            "complete_search_accounting": True,
        },
        "control": {
            "reviewed_projection_sha256": control_digest,
            "sensor_id_sha256": hashlib.sha256(
                control["sensor_id"].encode()
            ).hexdigest(),
            "name_sha256": hashlib.sha256(control["name"].encode()).hexdigest(),
            "document_count": 3,
            "preserved": True,
        },
        "cleanup": {
            "agent_delete_exact_success": True,
            "vst_absent": True,
            "identity_scoped_documents_absent": True,
            "exact_discovered_documents_absent": True,
            "delayed_no_reappearance": True,
            "foreign_delete_attempted": False,
        },
        "budget": {
            "requests": budget.used,
            "max_requests": budget.maximum,
            "actions": 11,
            "max_actions": 11,
        },
        "warehouse_sample_bundle": "excluded",
    }
    _validate(receipt, RECEIPT_SCHEMA_PATH)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    live = commands.add_parser("exercise-http")
    live.add_argument("--run-id", required=True)
    live.add_argument("--acknowledgement", required=True)
    live.add_argument("--rtsp-url", required=True)
    live.add_argument("--reviewed-rtsp-sha256", required=True)
    live.add_argument("--control", type=Path, required=True)
    live.add_argument("--reviewed-control-sha256", required=True)
    live.add_argument("--agent-origin", required=True)
    live.add_argument("--vst-origin", required=True)
    live.add_argument("--elasticsearch-origin", required=True)
    live.add_argument("--receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            value = compile_plan()
        else:
            value = execute_lifecycle(
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                rtsp_url=args.rtsp_url,
                reviewed_rtsp_sha256=args.reviewed_rtsp_sha256,
                control_path=args.control,
                reviewed_control_sha256=args.reviewed_control_sha256,
                agent_origin=args.agent_origin,
                vst_origin=args.vst_origin,
                elasticsearch_origin=args.elasticsearch_origin,
            )
            if args.receipt is not None:
                # Refuse to overwrite and require a direct regular-file target.
                descriptor = os.open(
                    args.receipt,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                )
                try:
                    os.write(
                        descriptor,
                        json.dumps(value, indent=2, sort_keys=True).encode() + b"\n",
                    )
                finally:
                    os.close(descriptor)
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except LifecycleError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "error_code": exc.code,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
