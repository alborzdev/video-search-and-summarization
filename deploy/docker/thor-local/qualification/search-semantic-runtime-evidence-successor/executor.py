#!/usr/bin/env python3
"""Authorization-gated 14-request Search semantic HTTP executor.

The default command is an inert source/contract check.  ``execute-http`` is
explicit, numeric-loopback-only, and operates on an operator-attested fixture
namespace that was provisioned outside this fixed 14-request envelope.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
COMMON_PATH = HERE.parent / "runtime-evidence-common" / "common.py"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_ITEMS = 4096
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PLAIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class ExecutorError(RuntimeError):
    """Expose a stable code without leaking response or fixture material."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "invalid_manifest",
        "invalid_receipt",
        "oracle_failed",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _load_common() -> Any:
    spec = importlib.util.spec_from_file_location(
        "search_semantic_runtime_common", COMMON_PATH
    )
    if spec is None or spec.loader is None:
        raise ExecutorError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


common = _load_common()


def _read(path: Path, maximum: int = MAX_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ExecutorError("configuration_error")
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
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise ExecutorError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _decode(
    raw: bytes,
    code: str,
    *,
    object_only: bool = True,
    enforce_common_package_bound: bool = True,
) -> Any:
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
    if object_only and not isinstance(value, dict):
        raise ExecutorError(code)
    if enforce_common_package_bound:
        try:
            common.canonical_bytes(value)
        except common.EvidenceCommonError as exc:
            raise ExecutorError(code) from exc
    return value


def _json(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    return _decode(_read(path), code)


def _validate(value: Any, schema_path: Path, code: str) -> None:
    try:
        schema = _json(schema_path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ExecutorError(code)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc


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


def _contract() -> dict[str, Any]:
    value = _json(CONTRACT_PATH)
    _validate(value, CONTRACT_SCHEMA_PATH, "configuration_error")
    return value


def _one(rows: Sequence[Any], key: str, value: Any) -> dict[str, Any]:
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    return matches[0]


def _selected_metadata_contract() -> dict[str, Any]:
    selected = _decode(
        _read(
            _repo_path(
                "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
                "post-state-capability-oracles.json"
            )
        ),
        "configuration_error",
        enforce_common_package_bound=False,
    )
    rows = selected.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise ExecutorError("configuration_error")
    row = _one(rows, "oracle_id", "oracle.runtime.agent.search-profile")
    fixture_contract = row.get("fixture", {}).get("input", {}).get("contract")
    expected = {
        "attribute": {
            "minimum_clip_seconds": 1,
            "multiple_attributes": "append",
            "same_object_merge": True,
        },
        "default_rank_fusion": "rrf",
        "fusion": {
            "multiple_attributes": "fuse",
            "order": ["embedding", "rerank_or_fallback"],
            "same_video_top_k": 1,
        },
        "image": {"retrieval": "object_level_knn", "selected_bbox": True},
        "indices": ["mdx-embed-filtered-*", "mdx-behavior-*", "mdx-raw-*"],
        "routes": [
            "/api/v1/search",
            "/api/v1/search/attribute",
            "/api/v1/search/fusion",
            "/api/v1/search/image",
        ],
        "wave3_acceptance": {
            "executor_ready": False,
            "materialized": False,
            "package": "agent-smartcity",
            "planning_requirement_ids": ["search-documents-and-bboxes"],
        },
    }
    bounds = row.get("execution_bounds", {})
    if (
        row.get("capability_id") != "runtime.agent.search-profile"
        or row.get("current_state") != "open_unexecuted"
        or row.get("evidence") != []
        or fixture_contract != expected
        or bounds.get("max_requests") != 14
        or bounds.get("max_actions") != 14
        or bounds.get("executor") is not None
        or bounds.get("collectors") != []
    ):
        raise ExecutorError("configuration_error")
    return fixture_contract


def _selected_bbox_reference() -> dict[str, Any]:
    fixture = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/"
            "search-semantic-runtime-readiness-successor/selected-bbox-fixture.json"
        )
    )
    try:
        image = base64.b64decode(fixture["image_base64"], validate=True)
    except (KeyError, binascii.Error, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc
    expected_reference = {
        "object_id": "vehicle-0001",
        "sensor_name": "camera-01",
        "sensor_id": "00000000-0000-4000-8000-000000000001",
        "timestamp": "2026-01-01T00:00:01Z",
    }
    if (
        fixture.get("fixture_id") != "thor-search-selected-bbox-v2"
        or fixture.get("query_frame_id") != "frame-camera-01-0001"
        or fixture.get("bbox_xyxy_normalized") != [0.125, 0.25, 0.625, 0.75]
        or fixture.get("expected_document_id") != "doc-camera-01-0001"
        or fixture.get("reference_object") != expected_reference
        or hashlib.sha256(image).hexdigest() != fixture.get("image_sha256")
    ):
        raise ExecutorError("configuration_error")
    return expected_reference


def compile_plan() -> dict[str, Any]:
    """Validate frozen predecessors and return an inert, non-network plan."""

    contract = _contract()
    workflow = contract.get("workflow", [])
    expected_workflow = [
        (1, "capture-pre-state", "elasticsearch", "POST", "/_mget"),
        (2, "search-route", "search", "POST", "/api/v1/search"),
        (3, "attribute-route", "search", "POST", "/api/v1/search/attribute"),
        (4, "fusion-route", "search", "POST", "/api/v1/search/fusion"),
        (5, "image-route", "search", "POST", "/api/v1/search/image"),
        (6, "same-object-merge", "search", "POST", "/api/v1/search"),
        (7, "append-multiple-attributes", "search", "POST", "/api/v1/search/attribute"),
        (8, "rerank-or-fallback", "search", "POST", "/api/v1/search/fusion"),
        (9, "fuse-multiple-attributes", "search", "POST", "/api/v1/search/attribute"),
        (10, "same-video-top-k", "search", "POST", "/api/v1/search"),
        (11, "selected-bbox-knn", "search", "POST", "/api/v1/search/image"),
        (12, "reject-invalid-index-family", "search", "POST", "/api/v1/search"),
        (13, "restore-owned-state", "elasticsearch", "POST", "/_bulk"),
        (14, "verify-postconditions", "elasticsearch", "POST", "/_mget"),
    ]
    if (
        contract.get("package_id") != "search-semantic-runtime-evidence-successor"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or [
            (
                row.get("order"),
                row.get("id"),
                row.get("target"),
                row.get("method"),
                row.get("path"),
            )
            for row in workflow
        ]
        != expected_workflow
        or contract.get("execution_bounds", {}).get("max_requests") != 14
        or contract.get("execution_bounds", {}).get("max_actions") != 14
        or contract.get("execution_bounds", {}).get("owned_document_count") != 6
        or contract.get("required_exact_routes")
        != [
            "/api/v1/search",
            "/api/v1/search/attribute",
            "/api/v1/search/fusion",
            "/api/v1/search/image",
        ]
        or contract.get("forbidden_route_aliases")
        != ["/api/v1/attribute_search", "/api/v1/embed_search"]
        or contract.get("authorization", {}).get("authorization_id")
        != "search-semantic-runtime"
        or contract.get("authorization", {}).get("acknowledgement")
        != "I_ACK_SEARCH_SEMANTIC_RUNTIME_AND_EXACT_OWNED_CLEANUP"
        or contract.get("authorization", {}).get("ownership_attestation")
        != "I_ATTEST_THIS_EXACT_RUN_NAMESPACE_IS_PREPROVISIONED_FOR_THIS_RUN_AND_MAY_BE_DELETED"
        or contract.get("transport")
        != {
            "numeric_loopback_only": True,
            "proxies": False,
            "follow_redirects": False,
            "max_request_bytes": 65536,
            "max_response_bytes": 1048576,
            "timeout_seconds": 10,
        }
    ):
        raise ExecutorError("configuration_error")
    seen: set[str] = set()
    for lock in contract.get("source_locks", []):
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
        ):
            raise ExecutorError("configuration_error")
        seen.add(lock["path"])
        if (
            hashlib.sha256(_read(_repo_path(lock["path"]))).hexdigest()
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")
    predecessor = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/search-semantic-runtime-readiness-successor/contract.json"
        )
    )
    boundary = predecessor.get("runtime_executor_boundary", {})
    if (
        predecessor.get("package_id") != "search-semantic-runtime-readiness-successor"
        or boundary.get("implemented") is not False
        or predecessor.get("promotion_eligible") is not False
    ):
        raise ExecutorError("configuration_error")
    selected_contract = _selected_metadata_contract()
    _selected_bbox_reference()
    if selected_contract["routes"] != contract["required_exact_routes"]:
        raise ExecutorError("configuration_error")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_plan_valid",
        "default_execution_enabled": False,
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 14,
        "action_bound": 14,
        "required_exact_routes": contract["required_exact_routes"],
        "selected_metadata_rows": 500,
        "selected_metadata_search_state": "open_unexecuted_null_bound",
        "predecessor_preserved": True,
        "preprovisioned_fixture_attestation_required": True,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, request: Any, fp: Any, code: int, message: str, headers: Any, new_url: str
    ) -> None:
        del request, fp, code, message, headers, new_url
        return None


class LiveOpener:
    """No-proxy/no-redirect opener admitted by runtime-evidence-common."""

    proxies_enabled = False
    redirects_enabled = False

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, request: Any, timeout: float) -> Any:
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response


def _document_key(document: Mapping[str, Any]) -> tuple[str, str]:
    return str(document.get("index")), str(document.get("document_id"))


def _expected_documents(
    contract: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[tuple[str, str]]:
    namespace = manifest["namespace"]
    return [
        (template.format(namespace=namespace), f"{namespace}-{suffix}")
        for template in contract["ownership"]["index_templates"]
        for suffix in contract["ownership"]["document_suffixes"]
    ]


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validate_operation_body(
    step_id: str, body: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    namespace = manifest["namespace"]
    search_steps = {
        "search-route",
        "fusion-route",
        "image-route",
        "same-object-merge",
        "rerank-or-fallback",
        "same-video-top-k",
        "selected-bbox-knn",
    }
    attribute_steps = {
        "attribute-route",
        "append-multiple-attributes",
        "fuse-multiple-attributes",
    }
    if step_id == "reject-invalid-index-family":
        if body != {
            "query": "reject invalid index family",
            "source_type": "vss-invalid-search-*",
            "agent_mode": False,
            "use_critic": False,
        }:
            raise ExecutorError("invalid_manifest")
        return
    if step_id in search_steps:
        required = {"query", "source_type", "video_sources", "agent_mode", "use_critic"}
        allowed = required | {
            "reference_object",
            "top_k",
            "min_cosine_similarity",
            "timestamp_start",
            "timestamp_end",
        }
        if (
            not required.issubset(body)
            or not set(body).issubset(allowed)
            or not isinstance(body["query"], str)
            or not body["query"]
            or body["source_type"] != "video_file"
            or body["video_sources"] != [namespace]
            or type(body["agent_mode"]) is not bool
            or body["use_critic"] is not False
        ):
            raise ExecutorError("invalid_manifest")
        if (
            step_id in {"fusion-route", "rerank-or-fallback"}
            and body["agent_mode"] is not True
        ):
            raise ExecutorError("invalid_manifest")
        if (
            step_id not in {"fusion-route", "rerank-or-fallback"}
            and body["agent_mode"] is not False
        ):
            raise ExecutorError("invalid_manifest")
        if step_id in {"image-route", "selected-bbox-knn"}:
            if body.get("reference_object") != manifest["selected_object"]:
                raise ExecutorError("invalid_manifest")
        elif "reference_object" in body:
            raise ExecutorError("invalid_manifest")
        if step_id == "same-video-top-k" and body.get("top_k") != 1:
            raise ExecutorError("invalid_manifest")
    elif step_id in attribute_steps:
        allowed = {
            "query",
            "source_type",
            "video_sources",
            "top_k",
            "min_similarity",
            "fuse_multi_attribute",
            "timestamp_start",
            "timestamp_end",
            "exclude_videos",
        }
        if (
            not {
                "query",
                "source_type",
                "video_sources",
                "fuse_multi_attribute",
            }.issubset(body)
            or not set(body).issubset(allowed)
            or body["source_type"] != "video_file"
            or body["video_sources"] != [namespace]
        ):
            raise ExecutorError("invalid_manifest")
        query = body["query"]
        if step_id == "attribute-route" and (not isinstance(query, str) or not query):
            raise ExecutorError("invalid_manifest")
        if step_id in {"append-multiple-attributes", "fuse-multiple-attributes"} and (
            not isinstance(query, list)
            or len(query) < 2
            or any(not isinstance(item, str) or not item for item in query)
        ):
            raise ExecutorError("invalid_manifest")
        expected_fuse = step_id == "fuse-multiple-attributes"
        if body["fuse_multi_attribute"] is not expected_fuse:
            raise ExecutorError("invalid_manifest")
    else:
        raise ExecutorError("invalid_manifest")


def _manifest(value: Any, run_id: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    _validate(value, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    if (
        not isinstance(value, dict)
        or not PLAIN_RE.fullmatch(run_id)
        or value.get("run_id") != run_id
    ):
        raise ExecutorError("invalid_manifest")
    namespace = contract["ownership"]["namespace_template"].format(run_id=run_id)
    if (
        value.get("namespace") != namespace
        or value.get("ownership_attestation")
        != contract["authorization"]["ownership_attestation"]
    ):
        raise ExecutorError("invalid_manifest")
    documents = value["documents"]
    if [_document_key(item) for item in documents] != _expected_documents(
        contract, value
    ):
        raise ExecutorError("invalid_manifest")
    if len({_document_key(item) for item in documents}) != 6 or any(
        not SHA256_RE.fullmatch(item["source_sha256"]) for item in documents
    ):
        raise ExecutorError("invalid_manifest")
    sentinel = value["sentinel"]
    if (
        _document_key(sentinel) in {_document_key(item) for item in documents}
        or namespace in sentinel["index"]
        or namespace in sentinel["document_id"]
        or not SHA256_RE.fullmatch(sentinel["source_sha256"])
    ):
        raise ExecutorError("invalid_manifest")
    if not _aware_timestamp(value["selected_object"]["timestamp"]):
        raise ExecutorError("invalid_manifest")
    if value["selected_object"] != _selected_bbox_reference():
        raise ExecutorError("invalid_manifest")
    delay = value["reappearance_delay_seconds"]
    bounds = contract["execution_bounds"]
    if (
        isinstance(delay, bool)
        or not isinstance(delay, (int, float))
        or not bounds["minimum_reappearance_delay_seconds"]
        <= delay
        <= bounds["maximum_reappearance_delay_seconds"]
    ):
        raise ExecutorError("invalid_manifest")
    operations = value["operations"]
    expected = contract["workflow"][1:12]
    for operation, workflow in zip(operations, expected, strict=True):
        if (
            operation["step_id"] != workflow["id"]
            or operation["method"] != workflow["method"]
            or operation["path"] != workflow["path"]
            or operation["path"] in contract["forbidden_route_aliases"]
            or operation["allowed_statuses"]
            != ([422] if workflow["id"] == "reject-invalid-index-family" else [200])
        ):
            raise ExecutorError("invalid_manifest")
        assertion = operation["assertion"]
        if assertion["minimum_results"] > assertion["maximum_results"]:
            raise ExecutorError("invalid_manifest")
        expected_shape = (
            "validation_error"
            if workflow["id"] == "reject-invalid-index-family"
            else "attribute"
            if workflow["path"].endswith("/attribute")
            else "search"
        )
        if assertion["response_shape"] != expected_shape:
            raise ExecutorError("invalid_manifest")
        if workflow["id"] == "reject-invalid-index-family":
            if assertion != {
                "response_shape": "validation_error",
                "minimum_results": 0,
                "maximum_results": 0,
                "expected_sensor_ids": [],
                "expected_object_ids": [],
                "expected_ordered_sensor_ids": [],
                "top_sensor_id": None,
                "top_video_name": None,
                "minimum_span_seconds": 0,
            }:
                raise ExecutorError("invalid_manifest")
        else:
            if (
                assertion["minimum_results"] < 1
                or assertion["top_video_name"] != namespace
            ):
                raise ExecutorError("invalid_manifest")
        if (
            workflow["id"] in {"append-multiple-attributes", "fuse-multiple-attributes"}
            and len(assertion["expected_object_ids"]) < 2
        ):
            raise ExecutorError("invalid_manifest")
        if (
            workflow["id"] == "same-object-merge"
            and assertion["minimum_span_seconds"] < 1
        ):
            raise ExecutorError("invalid_manifest")
        if workflow["id"] == "same-video-top-k" and assertion["maximum_results"] != 1:
            raise ExecutorError("invalid_manifest")
        _validate_operation_body(workflow["id"], operation["body"], value)
    return value


def _mget_body(manifest: Mapping[str, Any]) -> bytes:
    documents = list(manifest["documents"]) + [manifest["sentinel"]]
    return common.canonical_bytes(
        {
            "docs": [
                {"_index": item["index"], "_id": item["document_id"]}
                for item in documents
            ]
        }
    )


def _bulk_delete_body(manifest: Mapping[str, Any]) -> bytes:
    lines = [
        common.canonical_bytes(
            {"delete": {"_index": item["index"], "_id": item["document_id"]}}
        )
        for item in reversed(manifest["documents"])
    ]
    return b"\n".join(lines) + b"\n"


def _response_json(result: Any, *, object_only: bool = False) -> Any:
    if result.media_type != "application/json":
        raise ExecutorError("oracle_failed")
    return _decode(result.body, "oracle_failed", object_only=object_only)


def _validate_mget(
    result: Any, manifest: Mapping[str, Any], *, expect_owned: bool
) -> None:
    if result.status != 200:
        raise ExecutorError("oracle_failed")
    value = _response_json(result, object_only=True)
    rows = value.get("docs")
    expected = list(manifest["documents"]) + [manifest["sentinel"]]
    if (
        not isinstance(rows, list)
        or len(rows) != len(expected)
        or len(rows) > MAX_RESPONSE_ITEMS
    ):
        raise ExecutorError("oracle_failed")
    for position, (row, document) in enumerate(zip(rows, expected, strict=True)):
        if (
            not isinstance(row, dict)
            or row.get("_index") != document["index"]
            or row.get("_id") != document["document_id"]
        ):
            raise ExecutorError("oracle_failed")
        owned = position < 6
        should_exist = expect_owned if owned else True
        if row.get("found") is not should_exist:
            raise ExecutorError("oracle_failed")
        if should_exist:
            source = row.get("_source")
            if (
                not isinstance(source, dict)
                or common.digest_value(source) != document["source_sha256"]
            ):
                raise ExecutorError("oracle_failed")
        elif "_source" in row:
            raise ExecutorError("oracle_failed")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    )


def _semantic_rows(value: Any, shape: str) -> list[dict[str, Any]]:
    if shape == "search":
        if (
            not isinstance(value, dict)
            or set(value) != {"data", "search_messages"}
            or not isinstance(value["data"], list)
            or not isinstance(value["search_messages"], list)
        ):
            raise ExecutorError("oracle_failed")
        rows = value["data"]
    elif shape == "attribute":
        if not isinstance(value, list):
            raise ExecutorError("oracle_failed")
        rows = value
    else:
        raise ExecutorError("oracle_failed")
    if len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise ExecutorError("oracle_failed")
    return rows


def _assert_semantic(result: Any, operation: Mapping[str, Any]) -> None:
    assertion = operation["assertion"]
    if result.status not in operation["allowed_statuses"]:
        raise ExecutorError("oracle_failed")
    value = _response_json(result, object_only=False)
    if assertion["response_shape"] == "validation_error":
        if (
            result.status != 422
            or not isinstance(value, dict)
            or not isinstance(value.get("detail"), list)
        ):
            raise ExecutorError("oracle_failed")
        return
    rows = _semantic_rows(value, assertion["response_shape"])
    if not assertion["minimum_results"] <= len(rows) <= assertion["maximum_results"]:
        raise ExecutorError("oracle_failed")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if assertion["response_shape"] == "search":
            object_ids = row.get("object_ids", [])
            normalized.append(
                {
                    "sensor_id": row.get("sensor_id"),
                    "video_name": row.get("video_name"),
                    "object_ids": object_ids if isinstance(object_ids, list) else [],
                    "start": row.get("start_time"),
                    "end": row.get("end_time"),
                }
            )
        else:
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                raise ExecutorError("oracle_failed")
            normalized.append(
                {
                    "sensor_id": metadata.get("sensor_id"),
                    "video_name": metadata.get("video_name"),
                    "object_ids": [metadata.get("object_id")],
                    "start": metadata.get("start_time")
                    or metadata.get("frame_timestamp"),
                    "end": metadata.get("end_time") or metadata.get("frame_timestamp"),
                }
            )
    sensors = [row["sensor_id"] for row in normalized]
    videos = [row["video_name"] for row in normalized]
    object_ids = [
        str(item)
        for row in normalized
        for item in row["object_ids"]
        if item is not None
    ]
    if (
        not set(assertion["expected_sensor_ids"]).issubset(sensors)
        or not set(assertion["expected_object_ids"]).issubset(object_ids)
        or (
            assertion["expected_ordered_sensor_ids"]
            and sensors[: len(assertion["expected_ordered_sensor_ids"])]
            != assertion["expected_ordered_sensor_ids"]
        )
        or (
            assertion["top_sensor_id"] is not None
            and (not sensors or sensors[0] != assertion["top_sensor_id"])
        )
        or (
            assertion["top_video_name"] is not None
            and (not videos or videos[0] != assertion["top_video_name"])
        )
    ):
        raise ExecutorError("oracle_failed")
    if assertion["minimum_span_seconds"]:
        spans: list[float] = []
        for row in normalized:
            start, end = _parse_time(row["start"]), _parse_time(row["end"])
            if start is not None and end is not None:
                spans.append((end - start).total_seconds())
        if not spans or max(spans) < assertion["minimum_span_seconds"]:
            raise ExecutorError("oracle_failed")


def _validate_bulk_delete(result: Any, manifest: Mapping[str, Any]) -> None:
    if result.status != 200:
        raise ExecutorError("cleanup_failed")
    value = _response_json(result, object_only=True)
    rows = value.get("items")
    expected = list(reversed(manifest["documents"]))
    if value.get("errors") is not False or not isinstance(rows, list) or len(rows) != 6:
        raise ExecutorError("cleanup_failed")
    for row, document in zip(rows, expected, strict=True):
        delete = row.get("delete") if isinstance(row, dict) else None
        if (
            not isinstance(delete, dict)
            or delete.get("_index") != document["index"]
            or delete.get("_id") != document["document_id"]
            or delete.get("status") != 200
            or delete.get("result") != "deleted"
        ):
            raise ExecutorError("cleanup_failed")


def _observation(
    sequence: int, step: Mapping[str, Any], result: Any, oracle: Any
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "step_id": step["id"],
        "target": step["target"],
        "status": "pass",
        "result_code": step["id"].replace("-", "_") + "_verified",
        "response_status": result.status,
        "response_bytes": len(result.body),
        "response_sha256": hashlib.sha256(result.body).hexdigest(),
        "oracle_sha256": hashlib.sha256(common.canonical_bytes(oracle)).hexdigest(),
    }


def execute_http(
    *,
    manifest: dict[str, Any],
    run_id: str,
    acknowledgement: str,
    search_origin: str,
    elasticsearch_origin: str,
    search_opener_factory: Callable[[], Any] = LiveOpener,
    elasticsearch_opener_factory: Callable[[], Any] = LiveOpener,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute the exact 14-action envelope and return sanitized evidence."""

    compile_plan()
    contract = _contract()
    manifest = _manifest(manifest, run_id, contract)
    try:
        guard = common.RunAuthorizationGuard.from_token(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=contract["authorization"]["acknowledgement"],
        )
        identity = guard.admit(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
        search_paths = list(
            dict.fromkeys(row["path"] for row in manifest["operations"])
        )
        search_target = common.LoopbackTarget.admit(search_origin, search_paths)
        elasticsearch_target = common.LoopbackTarget.admit(
            elasticsearch_origin, ["/_mget", "/_bulk"]
        )
    except common.EvidenceCommonError as exc:
        raise ExecutorError("authorization_required") from exc
    bounds = contract["execution_bounds"]
    budget = common.ExecutionBudget(bounds["max_requests"], bounds["max_actions"])
    try:
        search_transport = common.BoundedHTTPTransport(
            target=search_target,
            opener=search_opener_factory(),
            budget=budget,
            max_request_bytes=contract["transport"]["max_request_bytes"],
            max_response_bytes=contract["transport"]["max_response_bytes"],
            timeout_seconds=contract["transport"]["timeout_seconds"],
        )
        elasticsearch_transport = common.BoundedHTTPTransport(
            target=elasticsearch_target,
            opener=elasticsearch_opener_factory(),
            budget=budget,
            max_request_bytes=contract["transport"]["max_request_bytes"],
            max_response_bytes=contract["transport"]["max_response_bytes"],
            timeout_seconds=contract["transport"]["timeout_seconds"],
        )
    except common.EvidenceCommonError as exc:
        raise ExecutorError("transport_error") from exc
    ledger = common.ResourceLedger(identity, budget, max_resources=1)
    observations: list[dict[str, Any]] = []
    cleanup_state = {
        "deleted": False,
        "delayed_absent": False,
        "sentinel_unchanged": False,
        "delay_milliseconds": 0,
    }
    cleanup_started: float | None = None

    def cleanup(resource_id: str) -> None:
        nonlocal cleanup_started
        if resource_id != manifest["namespace"]:
            raise ExecutorError("cleanup_failed")
        try:
            result = elasticsearch_transport.request(
                "POST",
                "/_bulk",
                body=_bulk_delete_body(manifest),
                media_type="application/x-ndjson",
            )
            _validate_bulk_delete(result, manifest)
        except (common.EvidenceCommonError, ExecutorError) as exc:
            raise ExecutorError("cleanup_failed") from exc
        cleanup_state["deleted"] = True
        cleanup_started = monotonic()
        observations.append(
            _observation(
                13,
                contract["workflow"][12],
                result,
                {"exact_registered_deletes": 6, "index_delete": False},
            )
        )

    def postcondition(resource_id: str) -> bool:
        if resource_id != manifest["namespace"] or cleanup_started is None:
            return False
        delay = float(manifest["reappearance_delay_seconds"])
        elapsed = monotonic() - cleanup_started
        if not math.isfinite(elapsed) or elapsed < 0:
            return False
        if elapsed < delay:
            sleeper(delay - elapsed)
        elapsed = monotonic() - cleanup_started
        if (
            not math.isfinite(elapsed)
            or elapsed < delay
            or elapsed > bounds["maximum_reappearance_delay_seconds"] + 10
        ):
            return False
        try:
            result = elasticsearch_transport.request(
                "POST",
                "/_mget",
                body=_mget_body(manifest),
                media_type="application/json",
            )
            _validate_mget(result, manifest, expect_owned=False)
        except (common.EvidenceCommonError, ExecutorError):
            return False
        cleanup_state["delayed_absent"] = True
        cleanup_state["sentinel_unchanged"] = True
        cleanup_state["delay_milliseconds"] = math.floor(elapsed * 1000)
        observations.append(
            _observation(
                14,
                contract["workflow"][13],
                result,
                {
                    "owned_absent": 6,
                    "sentinel_unchanged": True,
                    "minimum_delay_seconds": delay,
                },
            )
        )
        return True

    primary: BaseException | None = None
    try:
        first = elasticsearch_transport.request(
            "POST", "/_mget", body=_mget_body(manifest), media_type="application/json"
        )
        _validate_mget(first, manifest, expect_owned=True)
        budget.consume_action()
        observations.append(
            _observation(
                1,
                contract["workflow"][0],
                first,
                {"exact_source_readbacks": 6, "sentinel_readback": True},
            )
        )
        ledger.register(
            owner_run_id=run_id,
            resource_type="search-fixture-namespace",
            resource_id=manifest["namespace"],
            cleanup=cleanup,
            postcondition=postcondition,
        )
        for sequence, (operation, step) in enumerate(
            zip(manifest["operations"], contract["workflow"][1:12], strict=True),
            start=2,
        ):
            result = search_transport.request(
                operation["method"],
                operation["path"],
                body=common.canonical_bytes(operation["body"]),
                media_type="application/json",
            )
            _assert_semantic(result, operation)
            budget.consume_action()
            observations.append(
                _observation(sequence, step, result, operation["assertion"])
            )
    except BaseException as exc:
        primary = exc
    finally:
        if ledger.active_count:
            try:
                if not ledger.cleanup():
                    raise ExecutorError("cleanup_failed")
                ledger.assert_postconditions()
            except BaseException as cleanup_error:
                primary = ExecutorError("cleanup_failed")
                primary.__cause__ = cleanup_error
    if primary is not None:
        if isinstance(primary, ExecutorError):
            raise primary
        if isinstance(primary, common.EvidenceCommonError):
            raise ExecutorError("transport_error") from primary
        raise ExecutorError("oracle_failed") from primary
    observations.sort(key=lambda row: row["sequence"])
    if (
        budget.requests != 14
        or budget.actions != 14
        or [row["sequence"] for row in observations] != list(range(1, 15))
        or not all(cleanup_state.values())
    ):
        raise ExecutorError("oracle_failed")
    semantic_keys = [
        "search_route",
        "attribute_route",
        "fusion_route",
        "image_route",
        "same_object_merge",
        "append_multiple_attributes",
        "rerank_or_fallback_outcome",
        "fuse_multiple_attributes",
        "same_video_top_k",
        "selected_object_knn",
        "invalid_index_family_rejected_before_handler",
    ]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "bounded-numeric-loopback-http-candidate",
        "status": "candidate_runtime_receipt_complete_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "planning_requirement_id": contract["planning_requirement_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "contract_sha256": hashlib.sha256(_read(CONTRACT_PATH)).hexdigest(),
        "manifest_sha256": hashlib.sha256(common.canonical_bytes(manifest)).hexdigest(),
        "search_origin_sha256": hashlib.sha256(
            search_target.origin.encode("ascii")
        ).hexdigest(),
        "elasticsearch_origin_sha256": hashlib.sha256(
            elasticsearch_target.origin.encode("ascii")
        ).hexdigest(),
        "identity": identity.evidence(),
        "budget": budget.evidence(),
        "observations": observations,
        "route_identity": {
            "exact_routes_observed": contract["required_exact_routes"],
            "forbidden_alias_used": False,
            "redirects_followed": False,
        },
        "semantic_observations": {key: True for key in semantic_keys},
        "ownership": {
            "namespace_sha256": hashlib.sha256(
                manifest["namespace"].encode("ascii")
            ).hexdigest(),
            "operator_preprovisioned_attestation": True,
            "exact_readback_verified": True,
            "registered_document_count": 6,
            "raw_document_ids_recorded": False,
        },
        "cleanup": {
            "exact_bulk_deleted_document_count": 6,
            "index_delete_attempted": False,
            "ambiguous_or_foreign_delete_attempted": False,
            "delayed_absence_verified": True,
            "late_reappearance_observed": False,
            "delay_milliseconds": cleanup_state["delay_milliseconds"],
            "sentinel_unchanged": True,
            "foreign_resources_mutated": False,
        },
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Any) -> dict[str, Any]:
    _validate(receipt, RECEIPT_SCHEMA_PATH, "invalid_receipt")
    if not isinstance(receipt, dict):
        raise ExecutorError("invalid_receipt")
    contract = _contract()
    if (
        receipt.get("contract_sha256")
        != hashlib.sha256(_read(CONTRACT_PATH)).hexdigest()
        or receipt.get("package_id") != contract["package_id"]
        or receipt.get("budget")
        != {"requests": 14, "max_requests": 14, "actions": 14, "max_actions": 14}
        or [row.get("sequence") for row in receipt.get("observations", [])]
        != list(range(1, 15))
        or [row.get("step_id") for row in receipt["observations"]]
        != [row["id"] for row in contract["workflow"]]
        or any(row.get("status") != "pass" for row in receipt["observations"])
    ):
        raise ExecutorError("invalid_receipt")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "candidate_receipt_valid_non_promoting",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "receipt_sha256": hashlib.sha256(common.canonical_bytes(receipt)).hexdigest(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute-http")
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--search-origin", required=True)
    execute.add_argument("--elasticsearch-origin", required=True)
    validate = subparsers.add_parser("validate-receipt")
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "execute-http":
            result = execute_http(
                manifest=_json(args.manifest, "invalid_manifest"),
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                search_origin=args.search_origin,
                elasticsearch_origin=args.elasticsearch_origin,
            )
        elif args.command == "validate-receipt":
            result = validate_receipt(_json(args.receipt, "invalid_receipt"))
        else:
            result = compile_plan()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ExecutorError as exc:
        print(
            json.dumps({"status": "error", "code": exc.code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
