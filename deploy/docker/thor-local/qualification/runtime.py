#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run isolated, read-only runtime qualification against Thor loopback APIs."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.dont_write_bytecode = True

from contract import ContractError, normalize_openapi_document  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "runtime_inventory.json"
DEFAULT_EXPECTED_DIR = SCRIPT_DIR / "expected"
MAX_OPENAPI_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
PORT_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
QUERY_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
SAFE_ERROR_CODES = {
    "configuration_error",
    "connection_refused",
    "contract_drift",
    "http_error",
    "invalid_json",
    "invalid_openapi",
    "invalid_response",
    "not_available",
    "redirect_refused",
    "response_too_large",
    "timeout",
    "transport_error",
}
UNAVAILABLE_ERROR_CODES = {"connection_refused", "timeout", "transport_error"}


class RuntimeConfigError(ValueError):
    """Raised for an unsafe or malformed runtime qualification configuration."""


class RuntimeResponseError(ValueError):
    """Raised for a bounded, already-redacted response validation error."""

    def __init__(self, code: str) -> None:
        if code not in SAFE_ERROR_CODES:
            code = "invalid_response"
        self.code = code
        super().__init__(code)


class NoRedirects(HTTPRedirectHandler):
    """Prevent a loopback endpoint from redirecting the qualifier elsewhere."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _is_plain_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and Path(value).name == value
        and value not in {".", ".."}
    )


def _validate_path(value: Any, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not value.startswith("/"):
        raise RuntimeConfigError("configuration_error")
    if any(ord(character) < 0x21 or ord(character) == 0x7F for character in value):
        raise RuntimeConfigError("configuration_error")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeConfigError("configuration_error")
    return value


def _validate_port(value: Any) -> int:
    if isinstance(value, bool):
        raise RuntimeConfigError("configuration_error")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeConfigError("configuration_error") from exc
    if not 1 <= port <= 65535:
        raise RuntimeConfigError("configuration_error")
    return port


def _validate_origin(value: str) -> str:
    """Accept only an HTTP origin with a numeric loopback address."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RuntimeConfigError("configuration_error") from exc
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeConfigError("configuration_error")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise RuntimeConfigError("configuration_error") from exc
    if not address.is_loopback:
        raise RuntimeConfigError("configuration_error")
    port = _validate_port(port)
    literal = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{literal}:{port}"


def _validate_expected_status(value: Any) -> list[int]:
    if not isinstance(value, list) or not value:
        raise RuntimeConfigError("configuration_error")
    statuses: list[int] = []
    for item in value:
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or not 100 <= item <= 599
        ):
            raise RuntimeConfigError("configuration_error")
        statuses.append(item)
    if len(set(statuses)) != len(statuses):
        raise RuntimeConfigError("configuration_error")
    return statuses


def _validate_expected_jobs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeConfigError("configuration_error")
    jobs: list[str] = []
    for item in value:
        if not _is_plain_name(item):
            raise RuntimeConfigError("configuration_error")
        jobs.append(item)
    if len(set(jobs)) != len(jobs):
        raise RuntimeConfigError("configuration_error")
    return jobs


def _validate_query(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise RuntimeConfigError("configuration_error")
    query: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not QUERY_KEY_RE.fullmatch(key)
            or not isinstance(item, str)
            or len(item) > 256
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in item)
        ):
            raise RuntimeConfigError("configuration_error")
        query[key] = item
    return query


def load_runtime_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError("configuration_error") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeConfigError("configuration_error")
    services = value.get("services")
    if not isinstance(services, list) or not services:
        raise RuntimeConfigError("configuration_error")

    service_ids: set[str] = set()
    probe_ids: set[str] = set()
    for service in services:
        if not isinstance(service, dict) or not _is_plain_name(service.get("id")):
            raise RuntimeConfigError("configuration_error")
        service_id = service["id"]
        if service_id in service_ids:
            raise RuntimeConfigError("configuration_error")
        service_ids.add(service_id)
        port_env = service.get("port_env")
        if port_env is not None and (
            not isinstance(port_env, str) or not PORT_ENV_RE.fullmatch(port_env)
        ):
            raise RuntimeConfigError("configuration_error")
        _validate_port(service.get("default_port"))

        probes = service.get("probes")
        if not isinstance(probes, list) or not probes:
            raise RuntimeConfigError("configuration_error")
        local_ids: set[str] = set()
        for probe in probes:
            if not isinstance(probe, dict) or not _is_plain_name(probe.get("id")):
                raise RuntimeConfigError("configuration_error")
            probe_id = probe["id"]
            qualified_id = f"{service_id}:{probe_id}"
            if probe_id in local_ids or qualified_id in probe_ids:
                raise RuntimeConfigError("configuration_error")
            local_ids.add(probe_id)
            probe_ids.add(qualified_id)
            kind = probe.get("kind")
            if kind not in {
                "health",
                "mcp",
                "openapi",
                "prometheus-targets",
                "reachability",
                "semantic",
            }:
                raise RuntimeConfigError("configuration_error")
            if probe.get("method", "GET") != "GET":
                raise RuntimeConfigError("configuration_error")
            _validate_path(probe.get("path"))
            _validate_query(probe.get("query"))
            _validate_expected_status(probe.get("expected_status", [200]))
            if probe.get("availability", "required") not in {"required", "optional"}:
                raise RuntimeConfigError("configuration_error")
            if kind == "mcp" and probe.get("mode", "http") not in {"http", "sse"}:
                raise RuntimeConfigError("configuration_error")
            if kind == "openapi":
                if not _is_plain_name(probe.get("expected_manifest")):
                    raise RuntimeConfigError("configuration_error")
                _validate_path(probe.get("path_prefix", ""), allow_empty=True)
            if kind == "prometheus-targets":
                if probe.get("expected_status", [200]) != [200]:
                    raise RuntimeConfigError("configuration_error")
                _validate_expected_jobs(probe.get("expected_jobs"))
    return value


def parse_endpoint_overrides(
    assignments: list[str], service_ids: set[str]
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for assignment in assignments:
        service_id, separator, origin = assignment.partition("=")
        if (
            not separator
            or service_id not in service_ids
            or service_id in overrides
            or not origin
        ):
            raise RuntimeConfigError("configuration_error")
        overrides[service_id] = _validate_origin(origin)
    return overrides


def _service_origin(service: dict[str, Any], override: str | None) -> tuple[str, int]:
    if override is not None:
        origin = _validate_origin(override)
        port = urlsplit(origin).port
        if port is None:
            raise RuntimeConfigError("configuration_error")
        return origin, port
    port_value: Any = service["default_port"]
    port_env = service.get("port_env")
    if port_env and os.environ.get(port_env):
        port_value = os.environ[port_env]
    port = _validate_port(port_value)
    return f"http://127.0.0.1:{port}", port


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, RuntimeConfigError):
        return "configuration_error"
    if isinstance(exc, RuntimeResponseError):
        return exc.code
    if isinstance(exc, HTTPError):
        return "redirect_refused" if 300 <= exc.code < 400 else "http_error"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        return "transport_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ContractError):
        return "invalid_openapi"
    return "invalid_response"


def _request(
    opener: Any,
    origin: str,
    path: str,
    timeout: float,
    *,
    accept: str,
    query: dict[str, str] | None = None,
) -> Any:
    safe_origin = _validate_origin(origin)
    safe_path = _validate_path(path)
    safe_query = _validate_query(query)
    suffix = f"?{urlencode(safe_query)}" if safe_query else ""
    request = Request(
        f"{safe_origin}{safe_path}{suffix}",
        headers={
            "Accept": accept,
            "User-Agent": "vss-thor-runtime-qualification/1",
        },
        method="GET",
    )
    return opener.open(request, timeout=timeout)


def _base_probe_record(
    service_id: str, probe: dict[str, Any], port: int
) -> dict[str, Any]:
    record = {
        "availability": probe.get("availability", "required"),
        "id": f"{service_id}:{probe['id']}",
        "kind": probe["kind"],
        "method": "GET",
        "path": probe["path"],
        "port": port,
        "service": service_id,
    }
    query = _validate_query(probe.get("query"))
    if query:
        record["query_keys"] = sorted(query)
    return record


def _finish_probe(
    record: dict[str, Any], started: float, status: str, **fields: Any
) -> dict[str, Any]:
    record.update(fields)
    record["elapsed_ms"] = max(0, round((time.monotonic() - started) * 1000))
    record["status"] = status
    return record


def _status_probe(
    opener: Any,
    origin: str,
    port: int,
    service_id: str,
    probe: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    record = _base_probe_record(service_id, probe, port)
    expected_status = set(probe.get("expected_status", [200]))
    response: Any = None
    try:
        if probe["kind"] == "mcp" and probe.get("mode") == "sse":
            accept = "text/event-stream"
        elif probe["kind"] == "mcp":
            accept = "application/json, text/event-stream"
        else:
            accept = "application/json"
        try:
            response = _request(
                opener,
                origin,
                probe["path"],
                timeout,
                accept=accept,
                query=probe.get("query"),
            )
            http_status = int(response.status)
        except HTTPError as exc:
            response = exc
            http_status = int(exc.code)
            if 300 <= http_status < 400 and http_status not in expected_status:
                raise
        record["http_status"] = http_status
        if http_status not in expected_status:
            if probe.get("availability") == "optional" and http_status in {404, 405}:
                return _finish_probe(record, started, "skip", error="not_available")
            raise RuntimeResponseError("http_error")
        if probe["kind"] == "mcp" and probe.get("mode") == "sse":
            media_type = response.headers.get_content_type().lower()
            if media_type != "text/event-stream":
                raise RuntimeResponseError("invalid_response")
            record["transport"] = "sse"
        elif probe["kind"] == "mcp":
            record["transport"] = "streamable-http"
        return _finish_probe(record, started, "pass")
    except Exception as exc:  # every probe failure must remain redacted
        error = _classify_error(exc)
        http_status = getattr(exc, "code", None)
        fields: dict[str, Any] = {"error": error}
        if isinstance(http_status, int):
            fields["http_status"] = http_status
        status = "unavailable" if error in UNAVAILABLE_ERROR_CODES else "fail"
        return _finish_probe(record, started, status, **fields)
    finally:
        if response is not None:
            response.close()


def _read_bounded(response: Any, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise RuntimeResponseError("response_too_large")
        except ValueError as exc:
            raise RuntimeResponseError("invalid_response") from exc
    body = response.read(limit + 1)
    if len(body) > limit:
        raise RuntimeResponseError("response_too_large")
    return body


def _load_expected_manifest(expected_dir: Path, filename: str) -> dict[str, Any]:
    if not _is_plain_name(filename):
        raise RuntimeConfigError("configuration_error")
    try:
        value = json.loads((expected_dir / filename).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError("configuration_error") from exc
    if not isinstance(value, dict) or value.get("kind") != "rest":
        raise RuntimeConfigError("configuration_error")
    return value


def _drift_fingerprint(values: list[Any]) -> str | None:
    if not values:
        return None
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _canonical_route_path(path: str) -> str:
    """Match framework path-converter syntax to its emitted OpenAPI path."""

    return re.sub(r"\{([^{}:]+):[^{}]+\}", r"{\1}", path)


def compare_live_openapi(
    live_document: dict[str, Any],
    expected: dict[str, Any],
    *,
    path_prefix: str = "",
) -> dict[str, Any]:
    operations, component_hash = normalize_openapi_document(
        live_document, path_prefix=path_prefix
    )
    expected_operations = expected.get("operations")
    if not isinstance(expected_operations, list):
        raise RuntimeConfigError("configuration_error")

    live_by_route = {
        (item["method"], _canonical_route_path(item["path"])): item
        for item in operations
    }
    expected_by_route: dict[tuple[str, str], dict[str, Any]] = {}
    for item in expected_operations:
        if not isinstance(item, dict):
            raise RuntimeConfigError("configuration_error")
        method = item.get("method")
        path = item.get("path")
        if not isinstance(method, str) or not isinstance(path, str):
            raise RuntimeConfigError("configuration_error")
        expected_by_route[(method, _canonical_route_path(path))] = item

    expected_routes = set(expected_by_route)
    live_routes = set(live_by_route)
    missing = sorted(expected_routes - live_routes)
    extra = sorted(live_routes - expected_routes)
    schema_drift: list[tuple[str, str]] = []
    operation_id_drift: list[tuple[str, str]] = []
    for route in sorted(expected_routes & live_routes):
        expected_item = expected_by_route[route]
        live_item = live_by_route[route]
        expected_schema = expected_item.get("schema_hash")
        if (
            isinstance(expected_schema, str)
            and live_item.get("schema_hash") != expected_schema
        ):
            schema_drift.append(route)
        expected_operation_id = expected_item.get("operation_id")
        if (
            isinstance(expected_operation_id, str)
            and live_item.get("operation_id") != expected_operation_id
        ):
            operation_id_drift.append(route)

    expected_component_hash = expected.get("component_schema_hash")
    component_drift = bool(
        isinstance(expected_component_hash, str)
        and component_hash != expected_component_hash
    )
    fingerprint_values: list[Any] = [
        ["missing", missing],
        ["extra", extra],
        ["schema", schema_drift],
        ["operation_id", operation_id_drift],
        ["components", component_drift],
    ]
    drift = bool(
        missing or extra or schema_drift or operation_id_drift or component_drift
    )
    comparison: dict[str, Any] = {
        "component_schema_drift": component_drift,
        "expected_route_count": len(expected_routes),
        "extra_route_count": len(extra),
        "live_route_count": len(live_routes),
        "missing_route_count": len(missing),
        "operation_id_drift_count": len(operation_id_drift),
        "schema_drift_count": len(schema_drift),
    }
    if drift:
        comparison["drift_fingerprint"] = _drift_fingerprint(fingerprint_values)
    return comparison


def _openapi_probe(
    opener: Any,
    origin: str,
    port: int,
    service_id: str,
    probe: dict[str, Any],
    timeout: float,
    expected_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    record = _base_probe_record(service_id, probe, port)
    response: Any = None
    try:
        try:
            response = _request(
                opener,
                origin,
                probe["path"],
                timeout,
                accept="application/json",
            )
            http_status = int(response.status)
        except HTTPError as exc:
            response = exc
            http_status = int(exc.code)
            if 300 <= http_status < 400:
                raise
        record["http_status"] = http_status
        if http_status != 200:
            if probe.get("availability") == "optional" and http_status in {404, 405}:
                return _finish_probe(record, started, "skip", error="not_available")
            raise RuntimeResponseError("http_error")

        body = _read_bounded(response, MAX_OPENAPI_BYTES)
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeResponseError("invalid_json") from exc
        if not isinstance(document, dict):
            raise RuntimeResponseError("invalid_openapi")
        expected = _load_expected_manifest(expected_dir, probe["expected_manifest"])
        comparison = compare_live_openapi(
            document, expected, path_prefix=probe.get("path_prefix", "")
        )
        record["comparison"] = comparison
        has_drift = any(
            comparison[key]
            for key in (
                "component_schema_drift",
                "extra_route_count",
                "missing_route_count",
                "operation_id_drift_count",
                "schema_drift_count",
            )
        )
        if has_drift:
            raise RuntimeResponseError("contract_drift")
        return _finish_probe(record, started, "pass")
    except Exception as exc:  # every probe failure must remain redacted
        error = _classify_error(exc)
        http_status = getattr(exc, "code", None)
        fields: dict[str, Any] = {"error": error}
        if isinstance(http_status, int):
            fields["http_status"] = http_status
        status = "unavailable" if error in UNAVAILABLE_ERROR_CODES else "fail"
        return _finish_probe(record, started, status, **fields)
    finally:
        if response is not None:
            response.close()


def _prometheus_targets_probe(
    opener: Any,
    origin: str,
    port: int,
    service_id: str,
    probe: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Prove the versioned target set is present and every target is up."""

    started = time.monotonic()
    record = _base_probe_record(service_id, probe, port)
    response: Any = None
    try:
        try:
            response = _request(
                opener,
                origin,
                probe["path"],
                timeout,
                accept="application/json",
            )
            http_status = int(response.status)
        except HTTPError as exc:
            response = exc
            http_status = int(exc.code)
        record["http_status"] = http_status
        if http_status != 200:
            raise RuntimeResponseError("http_error")

        body = _read_bounded(response, MAX_JSON_BYTES)
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeResponseError("invalid_json") from exc
        if not isinstance(document, dict) or document.get("status") != "success":
            raise RuntimeResponseError("invalid_response")
        data = document.get("data")
        targets = data.get("activeTargets") if isinstance(data, dict) else None
        if not isinstance(targets, list):
            raise RuntimeResponseError("invalid_response")

        live: list[tuple[str, str]] = []
        for target in targets:
            if not isinstance(target, dict):
                raise RuntimeResponseError("invalid_response")
            labels = target.get("labels")
            job = labels.get("job") if isinstance(labels, dict) else None
            health = target.get("health")
            if not _is_plain_name(job) or not isinstance(health, str):
                raise RuntimeResponseError("invalid_response")
            live.append((job, health))

        expected = set(_validate_expected_jobs(probe.get("expected_jobs")))
        live_jobs = {job for job, _ in live}
        missing = sorted(expected - live_jobs)
        extra = sorted(live_jobs - expected)
        unhealthy = sorted(
            (job, health) for job, health in live if job in expected and health != "up"
        )
        repeated = sorted(
            job for job in live_jobs if sum(item[0] == job for item in live) > 1
        )
        drift_values: list[Any] = [
            ["missing", missing],
            ["extra", extra],
            ["unhealthy", unhealthy],
            ["repeated", repeated],
        ]
        comparison: dict[str, Any] = {
            "active_target_count": len(live),
            "expected_target_count": len(expected),
            "extra_job_count": len(extra),
            "missing_job_count": len(missing),
            "repeated_job_count": len(repeated),
            "unhealthy_target_count": len(unhealthy),
        }
        if missing or extra or unhealthy or repeated:
            comparison["drift_fingerprint"] = _drift_fingerprint(drift_values)
            record["comparison"] = comparison
            raise RuntimeResponseError("contract_drift")
        record["comparison"] = comparison
        return _finish_probe(record, started, "pass")
    except Exception as exc:  # every probe failure must remain redacted
        error = _classify_error(exc)
        http_status = getattr(exc, "code", None)
        fields: dict[str, Any] = {"error": error}
        if isinstance(http_status, int):
            fields["http_status"] = http_status
        status = "unavailable" if error in UNAVAILABLE_ERROR_CODES else "fail"
        return _finish_probe(record, started, status, **fields)
    finally:
        if response is not None:
            response.close()


def _configuration_failure() -> dict[str, Any]:
    return {
        "probes": [
            {
                "error": "configuration_error",
                "id": "qualification:configuration",
                "kind": "configuration",
                "status": "fail",
            }
        ],
        "read_only": True,
        "result": "fail",
        "safety": {
            "container_lifecycle": False,
            "http_methods": ["GET"],
            "loopback_only": True,
            "proxies": False,
            "resource_mutations": False,
        },
        "schema_version": 1,
        "summary": {
            "failed": 1,
            "passed": 0,
            "skipped": 0,
            "total": 1,
            "unavailable": 0,
        },
        "target": "loopback",
        "tier": "runtime",
    }


def run_runtime(
    config_path: Path = DEFAULT_CONFIG,
    expected_dir: Path = DEFAULT_EXPECTED_DIR,
    *,
    endpoint_assignments: list[str] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    try:
        if not 0 < timeout <= 60:
            raise RuntimeConfigError("configuration_error")
        config = load_runtime_config(config_path)
        services = config["services"]
        overrides = parse_endpoint_overrides(
            endpoint_assignments or [], {service["id"] for service in services}
        )
        # Empty proxy configuration prevents ambient HTTP(S)_PROXY variables
        # from sending loopback qualification traffic to another machine.
        opener = build_opener(ProxyHandler({}), NoRedirects())
        results: list[dict[str, Any]] = []
        for service in services:
            service_id = service["id"]
            origin, port = _service_origin(service, overrides.get(service_id))
            for probe in service["probes"]:
                if probe["kind"] == "openapi":
                    result = _openapi_probe(
                        opener,
                        origin,
                        port,
                        service_id,
                        probe,
                        timeout,
                        expected_dir,
                    )
                elif probe["kind"] == "prometheus-targets":
                    result = _prometheus_targets_probe(
                        opener,
                        origin,
                        port,
                        service_id,
                        probe,
                        timeout,
                    )
                else:
                    result = _status_probe(
                        opener,
                        origin,
                        port,
                        service_id,
                        probe,
                        timeout,
                    )
                results.append(result)
    except (RuntimeConfigError, KeyError, TypeError, ValueError):
        return _configuration_failure()

    summary = {
        "failed": sum(item["status"] == "fail" for item in results),
        "passed": sum(item["status"] == "pass" for item in results),
        "skipped": sum(item["status"] == "skip" for item in results),
        "total": len(results),
        "unavailable": sum(item["status"] == "unavailable" for item in results),
    }
    if summary["failed"]:
        result = "fail"
    elif summary["unavailable"]:
        result = "unavailable"
    else:
        result = "pass"
    return {
        "probes": results,
        "read_only": True,
        "result": result,
        "safety": {
            "container_lifecycle": False,
            "http_methods": ["GET"],
            "loopback_only": True,
            "proxies": False,
            "resource_mutations": False,
        },
        "schema_version": 1,
        "summary": summary,
        "target": "loopback",
        "tier": "runtime",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--expected-dir", type=Path, default=DEFAULT_EXPECTED_DIR)
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        metavar="SERVICE=HTTP_LOOPBACK_ORIGIN",
        help="override one service origin; numeric loopback HTTP origins only",
    )
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument(
        "--compact", action="store_true", help="emit compact rather than indented JSON"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_runtime(
        args.config,
        args.expected_dir,
        endpoint_assignments=args.endpoint,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            report,
            indent=None if args.compact else 2,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
        )
    )
    return {"pass": 0, "fail": 1, "unavailable": 2}[report["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
