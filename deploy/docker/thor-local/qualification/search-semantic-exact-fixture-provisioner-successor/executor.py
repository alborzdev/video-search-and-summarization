#!/usr/bin/env python3
"""Bounded exact-owned Search fixture lifecycle.

``plan`` is inert. ``exercise-http`` is explicitly authorized, numeric-
loopback-only, and always attempts agent-backed cleanup after VST allocates a
sensor ID. No Elasticsearch fixture documents are synthesized by this tool.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, Mapping, Sequence, cast
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
SEMANTIC_EXECUTOR_PATH = (
    HERE.parent / "search-semantic-runtime-evidence-successor" / "executor.py"
)
RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
)


class LifecycleError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
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


def _contract() -> dict[str, Any]:
    value = _decode(
        _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES), "configuration_error"
    )
    if not isinstance(value, dict):
        raise LifecycleError("configuration_error")
    return value


def _schema(schema_path: Path) -> Any:
    schema = _decode(
        _read_regular(schema_path, MAX_CONFIG_BYTES), "configuration_error"
    )
    try:
        Draft202012Validator.check_schema(schema)
    except LifecycleError:
        raise
    except Exception as exc:
        raise LifecycleError("configuration_error") from exc
    return schema


def _validate(value: Any, schema_path: Path) -> None:
    if list(Draft202012Validator(_schema(schema_path)).iter_errors(value)):
        raise LifecycleError("configuration_error")


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
    _schema(RECEIPT_SCHEMA_PATH)
    expected_workflow = [
        "validate-owned-media-and-origins",
        "prove-vst-name-absent",
        "request-exact-upload-url",
        "upload-one-owned-file-and-capture-vst-id",
        "prove-vst-allocation-and-es-prestate-absence",
        "complete-ingest-fail-closed",
        "discover-model-generated-exact-documents",
        "reconcile-selected-object-across-behavior-and-raw",
        "emit-dynamic-fixture-handoff",
        "delete-through-agent-owned-lifecycle",
        "prove-exact-cross-system-absence",
        "prove-delayed-no-reappearance",
    ]
    bounds = contract.get("execution_bounds", {})
    transport = contract.get("transport", {})
    decision = contract.get("decision", {})
    if (
        contract.get("package_id")
        != "search-semantic-exact-fixture-provisioner-successor"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [row.get("order") for row in contract.get("workflow", [])]
        != list(range(1, 13))
        or [row.get("id") for row in contract.get("workflow", [])] != expected_workflow
        or bounds.get("max_requests") != 77
        or bounds.get("max_actions") != 23
        or bounds.get("readiness_poll_attempts") != 10
        or bounds.get("cleanup_poll_attempts") != 4
        or bounds.get("cleanup_reserve_seconds") != 180
        or contract.get("fixture_consumer")
        != {
            "enabled": True,
            "kind": "source-locked-bounded-dynamic-semantic-consumer",
            "max_operations": 11,
            "shared_request_budget": True,
            "shared_deadline": True,
            "cleanup_reserve_preserved": True,
            "arbitrary_callback_allowed": False,
            "media_attestation_required": True,
        }
        or transport.get("numeric_loopback_only") is not True
        or transport.get("proxies") is not False
        or transport.get("follow_redirects") is not False
        or decision.get("safe_exact_full_fixture_creation_implemented") is not True
        or decision.get("failed_ingest_delayed_write_remediation_implemented")
        is not True
        or decision.get("failed_ingest_delayed_write_remediation_proven") is not False
        or decision.get("runtime_receipt_present") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
        or contract.get("indices")
        != {
            "embed": "mdx-embed-filtered-2025-01-01",
            "behavior": "mdx-behavior-2025-01-01",
            "raw": "mdx-raw-2025-01-01",
        }
    ):
        raise LifecycleError("configuration_error")

    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 14:
        raise LifecycleError("configuration_error")
    seen: set[str] = set()
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

    ingest = _read_regular(
        _repo_file("services/agent/src/vss_agents/api/video_ingest.py"),
        MAX_CONFIG_BYTES,
    ).decode()
    delete = _read_regular(
        _repo_file("services/agent/src/vss_agents/api/video_delete.py"),
        MAX_CONFIG_BYTES,
    ).decode()
    required_ingest = [
        'raise HTTPException(status_code=502, detail="RTVI-CV add failed: service not reachable")',
        'raise HTTPException(status_code=502, detail="RTVI-CV add failed: request timed out")',
        'result.get("usage", {}).get("total_chunks_processed", 0)',
        '"/api/v1/videos/{sensor_id}/complete"',
        "_rollback_search_post_processing",
        "authoritative_camera_name = await get_sensor_id_from_stream_id",
        'detail="Embedding generation failed: no chunks processed"',
    ]
    required_delete = [
        'headers={"x-stream-id": sensor_id}',
        "results.append(False)",
        "rtvi_embed_es_index",
        'status = "partial"',
        "timed_out is False",
        "failures == []",
        "type(deleted) is int",
    ]
    if any(fragment not in ingest for fragment in required_ingest) or any(
        fragment not in delete for fragment in required_delete
    ):
        raise LifecycleError("configuration_error")
    vst_utils = _read_regular(
        _repo_file("services/agent/src/vss_agents/tools/vst/utils.py"),
        MAX_CONFIG_BYTES,
    ).decode()
    if "duplicate VST sensor name" not in vst_utils:
        raise LifecycleError("configuration_error")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_exact_fixture_lifecycle_valid",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 77,
        "action_bound": 23,
        "integrated_dynamic_consumer_available": True,
        "operator_preprovisioned_fixture_required": False,
        "runtime_receipt_present": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, request: Any, fp: Any, code: int, message: str, headers: Any, newurl: str
    ) -> None:
        del request, fp, code, message, headers, newurl
        return None


class LiveOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, request: Request, timeout: float) -> Any:
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response


class RequestBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0

    def take(self) -> None:
        if self.used >= self.maximum:
            raise LifecycleError("transport_error")
        self.used += 1


class DeadlineOpener:
    """Clamp every executor-managed request to one shared wall-clock budget."""

    def __init__(
        self,
        opener: Any,
        *,
        maximum_seconds: float,
        cleanup_reserve_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if maximum_seconds <= 0 or not 0 < cleanup_reserve_seconds < maximum_seconds:
            raise LifecycleError("configuration_error")
        self._opener = opener
        self._monotonic = monotonic
        self._deadline = monotonic() + maximum_seconds
        self._cleanup_reserve_seconds = cleanup_reserve_seconds
        self._cleanup_mode = False
        self.proxies_enabled = getattr(opener, "proxies_enabled", None)
        self.redirects_enabled = getattr(opener, "redirects_enabled", None)

    def enter_cleanup(self) -> None:
        self._cleanup_mode = True

    def remaining(self) -> float:
        reserve = 0.0 if self._cleanup_mode else self._cleanup_reserve_seconds
        return self._deadline - self._monotonic() - reserve

    def open(self, request: Request, timeout: float) -> Any:
        remaining = self.remaining()
        if remaining <= 0:
            raise LifecycleError("transport_error")
        return self._opener.open(request, timeout=min(float(timeout), remaining))


class _SemanticResult:
    def __init__(self, status: int, media_type: str, body: bytes) -> None:
        self.status = status
        self.media_type = media_type
        self.body = body


def _load_semantic_executor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "search_semantic_integrated_oracle", SEMANTIC_EXECUTOR_PATH
    )
    if spec is None or spec.loader is None:
        raise LifecycleError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LifecycleError("configuration_error") from exc
    return module


def _replace_dynamic(value: Any, replacements: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        if value.startswith("$"):
            if value not in replacements:
                raise LifecycleError("configuration_error")
            return replacements[value]
        return value
    if isinstance(value, list):
        return [_replace_dynamic(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_dynamic(item, replacements) for key, item in value.items()
        }
    return value


class BoundedSemanticFixtureConsumer:
    """Consume a dynamic handoff with the lifecycle's opener and budgets."""

    ATTESTATION = (
        "I_ATTEST_THE_OWNED_MEDIA_CONTAINS_THE_TARGET_ACTION_AND_EXCLUDES_"
        "THE_DISTRACTOR_ACTION"
    )
    STEPS = [
        ("search-route", "/api/v1/search", 200),
        ("attribute-route", "/api/v1/search/attribute", 200),
        ("fusion-route", "/api/v1/search/fusion", 200),
        ("image-route", "/api/v1/search/image", 200),
        ("same-object-merge", "/api/v1/search", 200),
        ("append-multiple-attributes", "/api/v1/search/attribute", 200),
        ("rerank-or-fallback", "/api/v1/search/fusion", 200),
        ("fuse-multiple-attributes", "/api/v1/search/attribute", 200),
        ("same-video-top-k", "/api/v1/search", 200),
        ("selected-bbox-knn", "/api/v1/search/image", 200),
        ("reject-invalid-index-family", "/api/v1/search", 422),
    ]

    def __init__(self, *, search_origin: str, template: Mapping[str, Any]) -> None:
        self.search_origin = _origin(search_origin)
        self.template = _decode(_canonical(template), "configuration_error")
        operations = self.template.get("operations")
        if (
            self.template.get("schema_version") != 1
            or self.template.get("media_attestation") != self.ATTESTATION
            or not isinstance(operations, list)
            or len(operations) != len(self.STEPS)
        ):
            raise LifecycleError("configuration_error")
        for operation, (step_id, path, status) in zip(
            operations, self.STEPS, strict=True
        ):
            if (
                not isinstance(operation, dict)
                or operation.get("step_id") != step_id
                or operation.get("method") != "POST"
                or operation.get("path") != path
                or operation.get("allowed_statuses") != [status]
                or not isinstance(operation.get("body"), dict)
                or not isinstance(operation.get("assertion"), dict)
            ):
                raise LifecycleError("configuration_error")

    def consume(
        self,
        handoff: Mapping[str, Any],
        *,
        opener: Any,
        budget: RequestBudget,
        timeout: float,
        maximum_response: int,
    ) -> dict[str, Any]:
        selected = handoff["selected_object"]
        replacements = {
            "$namespace": handoff["namespace"],
            "$sensor_id": handoff["sensor_id"],
            "$selected_object_id": selected["object_id"],
            "$selected_object": selected,
        }
        operations = _replace_dynamic(self.template["operations"], replacements)
        semantic = _load_semantic_executor()
        dynamic_manifest = {
            "namespace": handoff["namespace"],
            "selected_object": selected,
        }
        observation_digests: list[str] = []
        for operation, (step_id, path, status) in zip(
            operations, self.STEPS, strict=True
        ):
            assertion = operation.get("assertion", {})
            allowed_sensor_ids = assertion.get("expected_sensor_ids", [])
            allowed_object_ids = assertion.get("expected_object_ids", [])
            if (
                operation.get("step_id") != step_id
                or operation.get("path") != path
                or operation.get("allowed_statuses") != [status]
                or not isinstance(allowed_sensor_ids, list)
                or not isinstance(allowed_object_ids, list)
                or any(item != handoff["sensor_id"] for item in allowed_sensor_ids)
                or any(item != selected["object_id"] for item in allowed_object_ids)
                or assertion.get("top_video_name") not in (None, handoff["namespace"])
                or assertion.get("top_sensor_id") not in (None, handoff["sensor_id"])
            ):
                raise LifecycleError("configuration_error")
            try:
                semantic._validate_operation_body(
                    step_id, operation["body"], dynamic_manifest
                )
            except Exception as exc:
                raise LifecycleError("configuration_error") from exc
            response_status, media_type, raw = _request(
                opener,
                budget,
                method="POST",
                url=f"{self.search_origin}{path}",
                timeout=timeout,
                maximum=maximum_response,
                body=_canonical(operation["body"]),
                content_type="application/json",
            )
            result = _SemanticResult(response_status, media_type, raw)
            try:
                semantic._assert_semantic(result, operation)
            except Exception as exc:
                raise LifecycleError("fixture_not_ready") from exc
            observation_digests.append(
                hashlib.sha256(
                    _canonical(
                        {
                            "step_id": step_id,
                            "status": response_status,
                            "response_bytes": len(raw),
                            "response_sha256": hashlib.sha256(raw).hexdigest(),
                            "assertion_sha256": hashlib.sha256(
                                _canonical(operation["assertion"])
                            ).hexdigest(),
                        }
                    )
                ).hexdigest()
            )
        return {
            "schema_version": 1,
            "status": "dynamic_semantic_fixture_consumed_non_promoting",
            "operations": len(operations),
            "observation_digests": observation_digests,
            "runtime_receipt_present": False,
            "promotion_eligible": False,
        }


def _origin(value: str) -> str:
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        address = ipaddress.ip_address(host) if host else None
    except (ValueError, TypeError) as exc:
        raise LifecycleError("configuration_error") from exc
    if (
        parsed.scheme != "http"
        or address is None
        or not address.is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise LifecycleError("configuration_error")
    return (
        f"http://[{host}]:{parsed.port}"
        if address.version == 6
        else f"http://{host}:{parsed.port}"
    )


def _response_bytes(response: Any, maximum: int) -> tuple[int, str, bytes]:
    try:
        status = int(response.status)
        media_type = (
            str(response.headers.get("Content-Type", ""))
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        raw = response.read(maximum + 1)
    except Exception as exc:
        raise LifecycleError("transport_error") from exc
    if len(raw) > maximum:
        raise LifecycleError("transport_error")
    return status, media_type, raw


def _request(
    opener: Any,
    budget: RequestBudget,
    *,
    method: str,
    url: str,
    timeout: float,
    maximum: int,
    body: bytes | None = None,
    content_type: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, str, bytes]:
    budget.take()
    request_headers = {"Accept": "application/json"}
    if content_type:
        request_headers["Content-Type"] = content_type
    if headers:
        request_headers.update(headers)
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        response = opener.open(request, timeout=timeout)
    except Exception as exc:
        raise LifecycleError("transport_error") from exc
    return _response_bytes(response, maximum)


def _json_request(
    opener: Any,
    budget: RequestBudget,
    *,
    method: str,
    url: str,
    timeout: float,
    maximum: int,
    value: Any | None = None,
    allowed: Sequence[int] = (200,),
) -> Any:
    status, media_type, raw = _request(
        opener,
        budget,
        method=method,
        url=url,
        timeout=timeout,
        maximum=maximum,
        body=None if value is None else _canonical(value),
        content_type=None if value is None else "application/json",
    )
    if status not in allowed or media_type != "application/json":
        raise LifecycleError("transport_error")
    return _decode(raw)


def _streams(value: Any) -> dict[str, str | None]:
    if not isinstance(value, list) or len(value) > 10000:
        raise LifecycleError("transport_error")
    result: dict[str, str | None] = {}
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            raise LifecycleError("transport_error")
        stream_id, entries = next(iter(item.items()))
        if not isinstance(stream_id, str) or not isinstance(entries, list):
            raise LifecycleError("transport_error")
        if stream_id in result:
            raise LifecycleError("transport_error")
        if not entries:
            # An empty stream descriptor still proves the sensor exists. Keep
            # the identity so cleanup cannot falsely report VST absence.
            result[stream_id] = None
            continue
        name = entries[0].get("name") if isinstance(entries[0], dict) else None
        if not isinstance(name, str):
            raise LifecycleError("transport_error")
        result[stream_id] = name
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
    shard_counts = (
        (
            shards.get("total"),
            shards.get("successful"),
            shards.get("skipped"),
            shards.get("failed"),
        )
        if isinstance(shards, dict)
        else ()
    )
    if (
        not isinstance(shards, dict)
        or len(shard_counts) != 4
        or any(type(count) is not int or count < 0 for count in shard_counts)
    ):
        raise LifecycleError("transport_error")
    complete_counts = cast(tuple[int, int, int, int], shard_counts)
    if (
        complete_counts[3] != 0
        or complete_counts[1] + complete_counts[2] != complete_counts[0]
    ):
        raise LifecycleError("transport_error")
    try:
        hits = value["hits"]
        rows = hits["hits"]
        total = hits["total"]
    except (KeyError, TypeError) as exc:
        raise LifecycleError("transport_error") from exc
    if (
        not isinstance(rows, list)
        or len(rows) > maximum
        or any(not isinstance(row, dict) for row in rows)
        or not isinstance(total, dict)
        or total.get("relation") != "eq"
        or type(total.get("value")) is not int
        or total["value"] != len(rows)
    ):
        raise LifecycleError("transport_error")
    for row in rows:
        if (
            not isinstance(row.get("_index"), str)
            or not isinstance(row.get("_id"), str)
            or not isinstance(row.get("_source"), dict)
        ):
            raise LifecycleError("transport_error")
    return rows


def _nested(source: Mapping[str, Any], *path: str) -> Any:
    value: Any = source
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _query_owned(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    indices: Mapping[str, str],
    sensor_id: str,
    namespace: str,
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
) -> dict[str, list[dict[str, Any]]]:
    scopes = {
        "embed": ("sensor.id.keyword", sensor_id),
        "behavior": ("sensor.id.keyword", namespace),
        "raw": ("sensorId.keyword", namespace),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for family in ("embed", "behavior", "raw"):
        field, value = scopes[family]
        response = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{es_origin}/{quote(indices[family], safe='')}/_search",
            timeout=timeout,
            maximum=maximum_response,
            value=_search_body(field, value, maximum_documents),
        )
        result[family] = _hits(response, maximum_documents)
    return result


def _prove_name_scopes_absent(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    indices: Mapping[str, str],
    namespace: str,
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
) -> None:
    """Fail before upload if the run-derived name is already indexed.

    The embedding identity is allocated by VST and cannot be checked yet, but
    behavior/raw use the deterministic camera name. Checking those scopes
    before allocation prevents a later cleanup from touching orphaned foreign
    records that happen to share the requested run ID.
    """

    scopes = {
        "behavior": ("sensor.id.keyword", namespace),
        "raw": ("sensorId.keyword", namespace),
    }
    for family in ("behavior", "raw"):
        field, value = scopes[family]
        response = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{es_origin}/{quote(indices[family], safe='')}/_search",
            timeout=timeout,
            maximum=maximum_response,
            value=_search_body(field, value, maximum_documents),
        )
        if _hits(response, maximum_documents):
            raise LifecycleError("ownership_conflict")


def _assert_owned_sources(
    documents: Mapping[str, Sequence[Mapping[str, Any]]], sensor_id: str, namespace: str
) -> None:
    for row in documents["embed"]:
        if _nested(row["_source"], "sensor", "id") != sensor_id:
            raise LifecycleError("ownership_conflict")
        vector = _nested(row["_source"], "llm", "visionEmbeddings")
        if not isinstance(vector, (list, dict)) or not vector:
            raise LifecycleError("fixture_not_ready")
    for row in documents["behavior"]:
        if _nested(row["_source"], "sensor", "id") != namespace:
            raise LifecycleError("ownership_conflict")
    for row in documents["raw"]:
        if row["_source"].get("sensorId") != namespace:
            raise LifecycleError("ownership_conflict")


def _selected_object(
    behavior: Sequence[Mapping[str, Any]],
    raw: Sequence[Mapping[str, Any]],
    namespace: str,
) -> dict[str, str]:
    def aware_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    raw_objects: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = {}
    for frame in raw:
        source = frame["_source"]
        frame_timestamp = aware_timestamp(
            source.get("timestamp")
            or source.get("@timestamp")
            or source.get("frame_timestamp")
        )
        if frame_timestamp is None:
            continue
        objects = source.get("objects", [])
        if not isinstance(objects, list):
            continue
        for item in objects:
            if isinstance(item, dict) and isinstance(item.get("id"), (str, int)):
                raw_objects.setdefault(str(item["id"]), []).append(
                    (frame_timestamp, item)
                )
    for row in behavior:
        source = row["_source"]
        object_id = _nested(source, "object", "id")
        timestamp = source.get("timestamp")
        end = source.get("end")
        start_time = aware_timestamp(timestamp)
        end_time = aware_timestamp(end)
        embeddings = source.get("embeddings")
        if isinstance(embeddings, list):
            embeddings = embeddings[0] if embeddings else None
        vector = embeddings.get("vector") if isinstance(embeddings, dict) else None
        raw_match = next(
            (
                (frame_time, item)
                for frame_time, item in raw_objects.get(str(object_id), [])
                if start_time is not None
                and end_time is not None
                and start_time <= frame_time <= end_time
            ),
            None,
        )
        raw_object = raw_match[1] if raw_match is not None else None
        bbox = raw_object.get("bbox") if isinstance(raw_object, Mapping) else None
        coordinates = (
            [bbox.get(key) for key in ("leftX", "rightX", "topY", "bottomY")]
            if isinstance(bbox, Mapping)
            else []
        )
        numeric_coordinates = (
            cast(list[int | float], coordinates)
            if len(coordinates) == 4
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in coordinates
            )
            else []
        )
        bbox_ok = bool(numeric_coordinates) and (
            numeric_coordinates[0] >= 0
            and numeric_coordinates[2] >= 0
            and numeric_coordinates[1] > numeric_coordinates[0]
            and numeric_coordinates[3] > numeric_coordinates[2]
        )
        if (
            object_id is not None
            and start_time is not None
            and end_time is not None
            and start_time <= end_time
            and isinstance(vector, list)
            and vector
            and bbox_ok
            and raw_match is not None
        ):
            return {
                "object_id": str(object_id),
                "sensor_name": namespace,
                "timestamp": raw_match[0].isoformat().replace("+00:00", "Z"),
            }
    raise LifecycleError("fixture_not_ready")


def _document_manifest(
    documents: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for family in ("embed", "behavior", "raw"):
        for row in documents[family]:
            result.append(
                {
                    "family": family,
                    "index": row["_index"],
                    "document_id": row["_id"],
                    "source_sha256": hashlib.sha256(
                        _canonical(row["_source"])
                    ).hexdigest(),
                }
            )
    keys = [(row["index"], row["document_id"]) for row in result]
    if len(keys) != len(set(keys)):
        raise LifecycleError("ownership_conflict")
    return result


def _multipart(media: bytes, filename: str, run_id: str) -> tuple[bytes, str]:
    boundary = "vss-thor-" + hashlib.sha256(run_id.encode("ascii")).hexdigest()[:24]
    lines = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="mediaFile"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: video/mp4\r\n\r\n",
        media,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="filename"\r\n\r\n',
        filename.encode("ascii"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="metadata"\r\n\r\n',
        b'{"timestamp":"2025-01-01T00:00:00"}',
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def _cleanup_candidates(
    opener: Any,
    budget: RequestBudget,
    *,
    vst_origin: str,
    es_origin: str,
    indices: Mapping[str, str],
    sensor_id: str,
    namespace: str,
    documents: Sequence[Mapping[str, str]],
    timeout: float,
    maximum_response: int,
    maximum_documents: int,
) -> list[dict[str, str]]:
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
    if sensor_id in streams or namespace in streams.values():
        raise LifecycleError("cleanup_failed")
    owned = _query_owned(
        opener,
        budget,
        es_origin=es_origin,
        indices=indices,
        sensor_id=sensor_id,
        namespace=namespace,
        timeout=timeout,
        maximum_response=maximum_response,
        maximum_documents=maximum_documents,
    )
    scoped: dict[tuple[str, str], dict[str, str]] = {}
    for family in ("embed", "behavior", "raw"):
        for row in owned[family]:
            key = (row["_index"], row["_id"])
            scoped[key] = {"index": key[0], "document_id": key[1]}
    mget = _json_request(
        opener,
        budget,
        method="POST",
        url=f"{es_origin}/_mget",
        timeout=timeout,
        maximum=maximum_response,
        value={
            "docs": [
                {"_index": row["index"], "_id": row["document_id"]} for row in documents
            ]
        },
    )
    rows = mget.get("docs") if isinstance(mget, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != len(documents)
        or any(
            not isinstance(row, dict)
            or row.get("_index") != requested["index"]
            or row.get("_id") != requested["document_id"]
            for row, requested in zip(rows, documents)
        )
    ):
        raise LifecycleError("cleanup_failed")
    exact_found: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("found") is True:
            if not isinstance(row.get("_source"), dict):
                raise LifecycleError("cleanup_failed")
            exact_found.add((row["_index"], row["_id"]))
        elif row.get("found") is not False or "_source" in row:
            raise LifecycleError("cleanup_failed")
    # A reappeared exact ID must still be visible through the reviewed exact
    # run-identity query. Otherwise its ownership is ambiguous and this tool
    # must not delete it.
    if not exact_found.issubset(scoped):
        raise LifecycleError("cleanup_failed")
    return [scoped[key] for key in sorted(scoped)]


def _delete_exact_documents(
    opener: Any,
    budget: RequestBudget,
    *,
    es_origin: str,
    documents: Sequence[Mapping[str, str]],
    timeout: float,
    maximum_response: int,
) -> None:
    if not documents:
        return
    body = (
        b"\n".join(
            _canonical(
                {
                    "delete": {
                        "_index": row["index"],
                        "_id": row["document_id"],
                    }
                }
            )
            for row in documents
        )
        + b"\n"
    )
    status, media_type, raw = _request(
        opener,
        budget,
        method="POST",
        url=f"{es_origin}/_bulk",
        timeout=timeout,
        maximum=maximum_response,
        body=body,
        content_type="application/x-ndjson",
    )
    value = _decode(raw)
    items = value.get("items") if isinstance(value, dict) else None
    if (
        status != 200
        or media_type != "application/json"
        or value.get("errors") is not False
        or not isinstance(items, list)
        or len(items) != len(documents)
    ):
        raise LifecycleError("cleanup_failed")
    for item, requested in zip(items, documents):
        deleted = item.get("delete") if isinstance(item, dict) else None
        if (
            not isinstance(deleted, dict)
            or deleted.get("_index") != requested["index"]
            or deleted.get("_id") != requested["document_id"]
            or deleted.get("status") not in (200, 404)
            or deleted.get("result") not in ("deleted", "not_found")
        ):
            raise LifecycleError("cleanup_failed")


def execute_lifecycle(
    *,
    run_id: str,
    acknowledgement: str,
    media_path: Path,
    agent_origin: str,
    vst_origin: str,
    elasticsearch_origin: str,
    opener_factory: Callable[[], Any] = LiveOpener,
    sleeper: Callable[[float], None] = time.sleep,
    fixture_consumer: BoundedSemanticFixtureConsumer | None = None,
) -> dict[str, Any]:
    """Provision, prove, and roll back one model-generated Search fixture."""

    compile_plan()
    contract = _contract()
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise LifecycleError("authorization_required")
    if (
        fixture_consumer is not None
        and type(fixture_consumer) is not BoundedSemanticFixtureConsumer
    ):
        raise LifecycleError("configuration_error")
    if not RUN_RE.fullmatch(run_id):
        raise LifecycleError("configuration_error")
    namespace = f"vss-search-owned-{run_id}"
    filename = f"{namespace}.mp4"
    media = _read_regular(media_path, contract["transport"]["max_media_bytes"])
    if len(media) < 12 or media[4:8] != b"ftyp":
        raise LifecycleError("configuration_error")
    media_sha256 = hashlib.sha256(media).hexdigest()
    agent = _origin(agent_origin)
    vst = _origin(vst_origin)
    es = _origin(elasticsearch_origin)
    timeout = float(contract["transport"]["timeout_seconds"])
    maximum_response = int(contract["transport"]["max_response_bytes"])
    maximum_documents = int(contract["execution_bounds"]["max_documents_per_index"])
    budget = RequestBudget(int(contract["execution_bounds"]["max_requests"]))
    started = time.monotonic()
    opener = DeadlineOpener(
        opener_factory(),
        maximum_seconds=float(contract["execution_bounds"]["max_duration_seconds"]),
        cleanup_reserve_seconds=float(
            contract["execution_bounds"]["cleanup_reserve_seconds"]
        ),
    )
    if (
        getattr(opener, "proxies_enabled", None) is not False
        or getattr(opener, "redirects_enabled", None) is not False
    ):
        raise LifecycleError("configuration_error")

    sensor_id: str | None = None
    upload_attempted = False
    discovered: dict[str, list[dict[str, Any]]] | None = None
    documents: list[dict[str, str]] = []
    selected: dict[str, str] | None = None
    handoff: dict[str, Any] | None = None
    handoff_sha256: str | None = None
    consumer_receipt_sha256: str | None = None
    consumer_invoked = False
    original_error: LifecycleError | None = None
    cleanup_complete = False
    remediation_deletes = 0
    consecutive_absence_observations = 0
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
        if namespace in streams.values() or filename in streams.values():
            raise LifecycleError("ownership_conflict")
        _prove_name_scopes_absent(
            opener,
            budget,
            es_origin=es,
            indices=contract["indices"],
            namespace=namespace,
            timeout=timeout,
            maximum_response=maximum_response,
            maximum_documents=maximum_documents,
        )

        upload_handshake = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{agent}/api/v1/videos",
            timeout=timeout,
            maximum=maximum_response,
            value={"filename": filename},
        )
        upload_url = (
            upload_handshake.get("url") if isinstance(upload_handshake, dict) else None
        )
        if upload_url != f"{vst}/vst/api/v1/storage/file":
            raise LifecycleError("transport_error")

        upload_body, upload_type = _multipart(media, filename, run_id)
        transfer_digest = hashlib.sha256(
            f"transfer:{run_id}".encode("ascii")
        ).hexdigest()
        transfer_id = (
            f"{transfer_digest[:8]}-{transfer_digest[8:12]}-4{transfer_digest[13:16]}-"
            f"8{transfer_digest[17:20]}-{transfer_digest[20:32]}"
        )
        # A timed-out or malformed upload response may still mean that VST
        # created the run-named sensor. Mark the attempt before transport so
        # `finally` can reconcile that exact namespace and remove it.
        upload_attempted = True
        status, media_type, raw = _request(
            opener,
            budget,
            method="POST",
            url=upload_url,
            timeout=timeout,
            maximum=maximum_response,
            body=upload_body,
            content_type=upload_type,
            headers={
                "nvstreamer-chunk-number": "1",
                "nvstreamer-total-chunks": "1",
                "nvstreamer-is-last-chunk": "true",
                "nvstreamer-identifier": transfer_id,
                "nvstreamer-file-name": filename,
            },
        )
        if status not in (200, 201) or media_type != "application/json":
            raise LifecycleError("transport_error")
        upload_response = _decode(raw)
        reported_sensor_id = (
            upload_response.get("sensorId")
            if isinstance(upload_response, dict)
            else None
        )
        if not isinstance(reported_sensor_id, str) or not UUID_RE.fullmatch(
            reported_sensor_id
        ):
            raise LifecycleError("transport_error")

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
        # File Search and deletion both depend on this exact name. Refuse an
        # allocation whose VST name diverges instead of guessing aliases.
        if streams.get(reported_sensor_id) != namespace:
            raise LifecycleError("ownership_conflict")
        # Trust the response identity only after VST proves that it owns the
        # exact run-derived name. This prevents cleanup from deleting a valid
        # but foreign UUID returned by a malformed response.
        sensor_id = reported_sensor_id

        prestate = _query_owned(
            opener,
            budget,
            es_origin=es,
            indices=contract["indices"],
            sensor_id=sensor_id,
            namespace=namespace,
            timeout=timeout,
            maximum_response=maximum_response,
            maximum_documents=maximum_documents,
        )
        if any(prestate.values()):
            raise LifecycleError("ownership_conflict")

        complete = _json_request(
            opener,
            budget,
            method="POST",
            url=f"{agent}/api/v1/videos/{quote(sensor_id, safe='')}/complete",
            timeout=float(contract["transport"]["complete_timeout_seconds"]),
            maximum=maximum_response,
            value={"filename": namespace},
        )
        if (
            not isinstance(complete, dict)
            or complete.get("sensor_id") != sensor_id
            or complete.get("filename") != namespace
            or not isinstance(complete.get("chunks_processed"), int)
            or complete["chunks_processed"] <= 0
        ):
            raise LifecycleError("fixture_not_ready")

        for attempt in range(contract["execution_bounds"]["readiness_poll_attempts"]):
            discovered = _query_owned(
                opener,
                budget,
                es_origin=es,
                indices=contract["indices"],
                sensor_id=sensor_id,
                namespace=namespace,
                timeout=timeout,
                maximum_response=maximum_response,
                maximum_documents=maximum_documents,
            )
            if all(discovered.values()):
                try:
                    _assert_owned_sources(discovered, sensor_id, namespace)
                    selected = _selected_object(
                        discovered["behavior"], discovered["raw"], namespace
                    )
                    selected["sensor_id"] = sensor_id
                    break
                except LifecycleError as exc:
                    if exc.code not in {"fixture_not_ready"}:
                        raise
            if attempt + 1 < contract["execution_bounds"]["readiness_poll_attempts"]:
                sleeper(float(contract["execution_bounds"]["poll_delay_seconds"]))
        if discovered is None or selected is None or not all(discovered.values()):
            raise LifecycleError("fixture_not_ready")
        documents = _document_manifest(discovered)
        handoff = {
            "schema_version": 1,
            "run_id": run_id,
            "namespace": namespace,
            "sensor_id": sensor_id,
            "indices": contract["indices"],
            "documents": documents,
            "selected_object": selected,
        }
        handoff_bytes = _canonical(handoff)
        handoff_sha256 = hashlib.sha256(handoff_bytes).hexdigest()
        if fixture_consumer is not None:
            consumer_receipt = fixture_consumer.consume(
                handoff,
                opener=opener,
                budget=budget,
                timeout=timeout,
                maximum_response=maximum_response,
            )
            consumer_receipt_sha256 = hashlib.sha256(
                _canonical(consumer_receipt)
            ).hexdigest()
            consumer_invoked = True
    except LifecycleError as exc:
        original_error = exc
    finally:
        opener.enter_cleanup()
        if upload_attempted and sensor_id is None:
            try:
                cleanup_streams = _streams(
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
                    stream_id
                    for stream_id, name in cleanup_streams.items()
                    if name in {namespace, filename}
                ]
                if len(matches) > 1 or (matches and not UUID_RE.fullmatch(matches[0])):
                    raise LifecycleError("cleanup_failed")
                if matches:
                    sensor_id = matches[0]
                else:
                    # No VST allocation exists under either exact owned name.
                    # Re-prove deterministic ES name scopes even though the
                    # completion endpoint could not have been reached.
                    _prove_name_scopes_absent(
                        opener,
                        budget,
                        es_origin=es,
                        indices=contract["indices"],
                        namespace=namespace,
                        timeout=timeout,
                        maximum_response=maximum_response,
                        maximum_documents=maximum_documents,
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
                    url=f"{agent}/api/v1/videos/{quote(sensor_id, safe='')}",
                    timeout=timeout,
                    maximum=maximum_response,
                    allowed=(200,),
                )
                if (
                    not isinstance(deleted, dict)
                    or deleted.get("status") != "success"
                    or deleted.get("video_id") != sensor_id
                ):
                    raise LifecycleError("cleanup_failed")
                # Exact document IDs are available only after readiness. An
                # earlier failure still proves zero scoped matches and VST
                # absence; the empty exact-mget set is intentionally valid.
                for attempt in range(
                    contract["execution_bounds"]["cleanup_poll_attempts"]
                ):
                    if attempt:
                        sleeper(
                            float(contract["execution_bounds"]["poll_delay_seconds"])
                        )
                    candidates = _cleanup_candidates(
                        opener,
                        budget,
                        vst_origin=vst,
                        es_origin=es,
                        indices=contract["indices"],
                        sensor_id=sensor_id,
                        namespace=namespace,
                        documents=documents,
                        timeout=timeout,
                        maximum_response=maximum_response,
                        maximum_documents=maximum_documents,
                    )
                    if candidates:
                        _delete_exact_documents(
                            opener,
                            budget,
                            es_origin=es,
                            documents=candidates,
                            timeout=timeout,
                            maximum_response=maximum_response,
                        )
                        remediation_deletes += len(candidates)
                        consecutive_absence_observations = 0
                    else:
                        consecutive_absence_observations += 1
                        if consecutive_absence_observations == 2:
                            break
                cleanup_complete = consecutive_absence_observations == 2
            except LifecycleError:
                cleanup_complete = False
        if upload_attempted and not cleanup_complete:
            raise LifecycleError("cleanup_failed")

    if original_error is not None:
        raise original_error
    if (
        sensor_id is None
        or discovered is None
        or selected is None
        or not documents
        or handoff is None
        or handoff_sha256 is None
    ):
        raise LifecycleError("fixture_not_ready")
    elapsed = time.monotonic() - started
    if elapsed > contract["execution_bounds"]["max_duration_seconds"]:
        raise LifecycleError("transport_error")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-numeric-loopback-functional-fixture-lifecycle",
        "status": "candidate_fixture_lifecycle_complete_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "identity": {
            "run_id": run_id,
            "namespace_sha256": hashlib.sha256(namespace.encode()).hexdigest(),
            "sensor_id_sha256": hashlib.sha256(sensor_id.encode()).hexdigest(),
            "media_sha256": media_sha256,
        },
        "budget": {
            "requests": budget.used,
            "max_requests": budget.maximum,
            "actions": 23 if consumer_invoked else 12,
            "max_actions": 23,
        },
        "fixture": {
            "embed_documents": len(discovered["embed"]),
            "behavior_documents": len(discovered["behavior"]),
            "raw_documents": len(discovered["raw"]),
            "selected_object_reconciled": True,
            "handoff_sha256": handoff_sha256,
            "consumer_invoked": consumer_invoked,
            "consumer_receipt_sha256": consumer_receipt_sha256,
            "consumer_transport_accounting": (
                "shared-lifecycle-budget-and-deadline"
                if consumer_invoked
                else "not-requested"
            ),
            "raw_document_ids_recorded": True,
            "operator_preprovisioned": False,
        },
        "cleanup": {
            "agent_delete_success": True,
            "vst_absent": True,
            "identity_scoped_documents_absent": True,
            "exact_discovered_documents_absent": True,
            "delayed_no_reappearance": True,
            "remediation_deleted_documents": remediation_deletes,
            "consecutive_absence_observations": consecutive_absence_observations,
            "foreign_delete_attempted": False,
        },
        "warehouse_sample_bundle": "excluded",
    }
    _validate(receipt, RECEIPT_SCHEMA_PATH)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("plan")
    execute = subcommands.add_parser("exercise-http")
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--media", type=Path, required=True)
    execute.add_argument("--agent-origin", required=True)
    execute.add_argument("--vst-origin", required=True)
    execute.add_argument("--elasticsearch-origin", required=True)
    execute.add_argument("--search-origin")
    execute.add_argument("--semantic-template", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = compile_plan()
        else:
            if bool(args.search_origin) != bool(args.semantic_template):
                raise LifecycleError("configuration_error")
            consumer = (
                BoundedSemanticFixtureConsumer(
                    search_origin=args.search_origin,
                    template=_decode(
                        _read_regular(args.semantic_template, MAX_CONFIG_BYTES),
                        "configuration_error",
                    ),
                )
                if args.semantic_template is not None
                else None
            )
            result = execute_lifecycle(
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                media_path=args.media,
                agent_origin=args.agent_origin,
                vst_origin=args.vst_origin,
                elasticsearch_origin=args.elasticsearch_origin,
                fixture_consumer=consumer,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except LifecycleError as exc:
        print(exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
