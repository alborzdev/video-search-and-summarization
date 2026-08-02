# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_semantic_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


RUN_ID = "run-001"
ACK = "I_ACK_SEARCH_SEMANTIC_RUNTIME_AND_EXACT_OWNED_CLEANUP"
ATTESTATION = "I_ATTEST_THIS_EXACT_RUN_NAMESPACE_IS_PREPROVISIONED_FOR_THIS_RUN_AND_MAY_BE_DELETED"
SEARCH_ORIGIN = "http://127.0.0.1:18000"
ES_ORIGIN = "http://127.0.0.1:19200"


class FakeResponse:
    def __init__(self, url: str, value: Any, status: int = 200) -> None:
        self.status = status
        self._url = url
        self._body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self._body)),
        }
        self.closed = False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def close(self) -> None:
        self.closed = True


class QueueOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, responses: list[tuple[int, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        assert timeout == 10
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected request")
        status, value = self.responses.pop(0)
        return FakeResponse(request.full_url, value, status)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _sha(value: Any) -> str:
    return executor.common.digest_value(value)


def _search_result(
    namespace: str,
    sensor: str,
    object_ids: list[str],
    *,
    start: str = "2026-01-01T00:00:00Z",
    end: str = "2026-01-01T00:00:01Z",
) -> dict[str, Any]:
    return {
        "video_name": namespace,
        "description": "bounded fixture result",
        "start_time": start,
        "end_time": end,
        "sensor_id": sensor,
        "screenshot_url": "",
        "similarity": 0.9,
        "object_ids": object_ids,
        "critic_result": None,
    }


def _attribute_result(namespace: str, sensor: str, object_id: str) -> dict[str, Any]:
    return {
        "screenshot_url": "",
        "metadata": {
            "sensor_id": sensor,
            "object_id": object_id,
            "object_type": "person",
            "frame_timestamp": "2026-01-01T00:00:00Z",
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-01T00:00:01Z",
            "bbox": {},
            "behavior_score": 0.9,
            "frame_score": 0.8,
            "video_name": namespace,
        },
    }


def _assertion(
    shape: str,
    namespace: str,
    *,
    minimum: int = 1,
    maximum: int = 10,
    sensors: list[str] | None = None,
    objects: list[str] | None = None,
    ordered: list[str] | None = None,
    top_sensor: str | None = "sensor-a",
    span: float = 0,
) -> dict[str, Any]:
    return {
        "response_shape": shape,
        "minimum_results": minimum,
        "maximum_results": maximum,
        "expected_sensor_ids": sensors or [],
        "expected_object_ids": objects or [],
        "expected_ordered_sensor_ids": ordered or [],
        "top_sensor_id": top_sensor,
        "top_video_name": namespace,
        "minimum_span_seconds": span,
    }


def make_manifest() -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    namespace = f"vss-oracle-runtime-agent-search-profile-{RUN_ID}"
    documents: list[dict[str, str]] = []
    sources: dict[tuple[str, str], dict[str, Any]] = {}
    for family in ("mdx-embed-filtered", "mdx-behavior", "mdx-raw"):
        index = f"{family}-{namespace}"
        for camera in ("01", "02"):
            document_id = f"{namespace}-doc-camera-{camera}-0001"
            source = {
                "namespace": namespace,
                "camera": camera,
                "family": family,
                "fixture": True,
            }
            documents.append(
                {
                    "index": index,
                    "document_id": document_id,
                    "source_sha256": _sha(source),
                }
            )
            sources[(index, document_id)] = source
    sentinel_source = {"sentinel": "preserve", "version": 1}
    sentinel = {
        "index": "vss-qualification-sentinel",
        "document_id": "foreign-sentinel",
        "source_sha256": _sha(sentinel_source),
    }
    sources[(sentinel["index"], sentinel["document_id"])] = sentinel_source
    selected = {
        "object_id": "vehicle-0001",
        "sensor_name": "camera-01",
        "sensor_id": "00000000-0000-4000-8000-000000000001",
        "timestamp": "2026-01-01T00:00:01Z",
    }
    common_search = {
        "query": "fixture query",
        "source_type": "video_file",
        "video_sources": [namespace],
        "agent_mode": False,
        "use_critic": False,
    }
    common_attr = {
        "query": "red jacket",
        "source_type": "video_file",
        "video_sources": [namespace],
        "fuse_multi_attribute": False,
    }
    rows: list[dict[str, Any]] = [
        {
            "step_id": "search-route",
            "method": "POST",
            "path": "/api/v1/search",
            "body": common_search,
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search", namespace, sensors=["sensor-a"], top_sensor="sensor-a"
            ),
        },
        {
            "step_id": "attribute-route",
            "method": "POST",
            "path": "/api/v1/search/attribute",
            "body": common_attr,
            "allowed_statuses": [200],
            "assertion": _assertion(
                "attribute",
                namespace,
                sensors=["sensor-a"],
                objects=["object-01"],
                top_sensor="sensor-a",
            ),
        },
        {
            "step_id": "fusion-route",
            "method": "POST",
            "path": "/api/v1/search/fusion",
            "body": common_search
            | {"query": "person in red jacket walking", "agent_mode": True},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search", namespace, objects=["object-01"], top_sensor="sensor-a"
            ),
        },
        {
            "step_id": "image-route",
            "method": "POST",
            "path": "/api/v1/search/image",
            "body": common_search | {"reference_object": selected},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search",
                namespace,
                sensors=["sensor-b"],
                objects=["object-02"],
                top_sensor="sensor-b",
            ),
        },
        {
            "step_id": "same-object-merge",
            "method": "POST",
            "path": "/api/v1/search",
            "body": common_search | {"query": "same object contiguous chunks"},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search",
                namespace,
                objects=["object-01"],
                top_sensor="sensor-a",
                span=2,
            ),
        },
        {
            "step_id": "append-multiple-attributes",
            "method": "POST",
            "path": "/api/v1/search/attribute",
            "body": common_attr
            | {
                "query": ["red jacket", "blue jeans"],
                "fuse_multi_attribute": False,
                "top_k": 2,
            },
            "allowed_statuses": [200],
            "assertion": _assertion(
                "attribute",
                namespace,
                minimum=2,
                maximum=2,
                objects=["object-01", "object-02"],
                top_sensor="sensor-a",
            ),
        },
        {
            "step_id": "rerank-or-fallback",
            "method": "POST",
            "path": "/api/v1/search/fusion",
            "body": common_search
            | {"query": "person walking in red jacket", "agent_mode": True},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search",
                namespace,
                minimum=2,
                maximum=2,
                ordered=["sensor-a", "sensor-b"],
                top_sensor="sensor-a",
            ),
        },
        {
            "step_id": "fuse-multiple-attributes",
            "method": "POST",
            "path": "/api/v1/search/attribute",
            "body": common_attr
            | {
                "query": ["red jacket", "blue jeans"],
                "fuse_multi_attribute": True,
                "top_k": 2,
            },
            "allowed_statuses": [200],
            "assertion": _assertion(
                "attribute",
                namespace,
                minimum=2,
                maximum=2,
                objects=["object-01", "object-02"],
                top_sensor="sensor-a",
            ),
        },
        {
            "step_id": "same-video-top-k",
            "method": "POST",
            "path": "/api/v1/search",
            "body": common_search | {"top_k": 1},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search", namespace, minimum=1, maximum=1, top_sensor="sensor-a"
            ),
        },
        {
            "step_id": "selected-bbox-knn",
            "method": "POST",
            "path": "/api/v1/search/image",
            "body": common_search
            | {"query": "selected object", "reference_object": selected},
            "allowed_statuses": [200],
            "assertion": _assertion(
                "search",
                namespace,
                sensors=["sensor-b"],
                objects=["object-02"],
                top_sensor="sensor-b",
            ),
        },
        {
            "step_id": "reject-invalid-index-family",
            "method": "POST",
            "path": "/api/v1/search",
            "body": {
                "query": "reject invalid index family",
                "source_type": "vss-invalid-search-*",
                "agent_mode": False,
                "use_critic": False,
            },
            "allowed_statuses": [422],
            "assertion": {
                "response_shape": "validation_error",
                "minimum_results": 0,
                "maximum_results": 0,
                "expected_sensor_ids": [],
                "expected_object_ids": [],
                "expected_ordered_sensor_ids": [],
                "top_sensor_id": None,
                "top_video_name": None,
                "minimum_span_seconds": 0,
            },
        },
    ]
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "ownership_attestation": ATTESTATION,
        "namespace": namespace,
        "documents": documents,
        "sentinel": sentinel,
        "selected_object": selected,
        "reappearance_delay_seconds": 2,
        "operations": rows,
    }, sources


def make_responses(
    manifest: dict[str, Any],
    sources: dict[tuple[str, str], dict[str, Any]],
    *,
    reappear: bool = False,
) -> tuple[list[tuple[int, Any]], list[tuple[int, Any]]]:
    namespace = manifest["namespace"]
    a = _search_result(namespace, "sensor-a", ["object-01"])
    b = _search_result(namespace, "sensor-b", ["object-02"])
    search = [
        (200, {"data": [a], "search_messages": []}),
        (200, [_attribute_result(namespace, "sensor-a", "object-01")]),
        (200, {"data": [a], "search_messages": []}),
        (200, {"data": [b], "search_messages": []}),
        (
            200,
            {
                "data": [
                    _search_result(
                        namespace, "sensor-a", ["object-01"], end="2026-01-01T00:00:02Z"
                    )
                ],
                "search_messages": [],
            },
        ),
        (
            200,
            [
                _attribute_result(namespace, "sensor-a", "object-01"),
                _attribute_result(namespace, "sensor-b", "object-02"),
            ],
        ),
        (200, {"data": [a, b], "search_messages": []}),
        (
            200,
            [
                _attribute_result(namespace, "sensor-a", "object-01"),
                _attribute_result(namespace, "sensor-b", "object-02"),
            ],
        ),
        (200, {"data": [a], "search_messages": []}),
        (200, {"data": [b], "search_messages": []}),
        (422, {"detail": [{"type": "literal_error", "loc": ["body", "source_type"]}]}),
    ]
    initial_docs = [
        {
            "_index": item["index"],
            "_id": item["document_id"],
            "found": True,
            "_source": sources[(item["index"], item["document_id"])],
        }
        for item in list(manifest["documents"]) + [manifest["sentinel"]]
    ]
    bulk_items = [
        {
            "delete": {
                "_index": item["index"],
                "_id": item["document_id"],
                "status": 200,
                "result": "deleted",
            }
        }
        for item in reversed(manifest["documents"])
    ]
    final_docs = []
    for position, item in enumerate(
        list(manifest["documents"]) + [manifest["sentinel"]]
    ):
        if position < 6 and not reappear:
            final_docs.append(
                {"_index": item["index"], "_id": item["document_id"], "found": False}
            )
        else:
            final_docs.append(
                {
                    "_index": item["index"],
                    "_id": item["document_id"],
                    "found": True,
                    "_source": sources[(item["index"], item["document_id"])],
                }
            )
    elasticsearch = [
        (200, {"docs": initial_docs}),
        (200, {"errors": False, "items": bulk_items}),
        (200, {"docs": final_docs}),
    ]
    return search, elasticsearch


def run_success() -> tuple[
    dict[str, Any], QueueOpener, QueueOpener, FakeClock, dict[str, Any]
]:
    manifest, sources = make_manifest()
    search_responses, es_responses = make_responses(manifest, sources)
    search_opener, es_opener, clock = (
        QueueOpener(search_responses),
        QueueOpener(es_responses),
        FakeClock(),
    )
    receipt = executor.execute_http(
        manifest=manifest,
        run_id=RUN_ID,
        acknowledgement=ACK,
        search_origin=SEARCH_ORIGIN,
        elasticsearch_origin=ES_ORIGIN,
        search_opener_factory=lambda: search_opener,
        elasticsearch_opener_factory=lambda: es_opener,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )
    return receipt, search_opener, es_opener, clock, manifest


def test_compile_plan_is_inert_and_binds_selected_500_row_metadata() -> None:
    plan = executor.compile_plan()
    assert plan["status"] == "inert_plan_valid"
    assert plan["runtime_requests"] == plan["runtime_actions"] == 0
    assert plan["selected_metadata_rows"] == 500
    assert plan["selected_metadata_search_state"] == "open_unexecuted_null_bound"
    assert plan["request_bound"] == plan["action_bound"] == 14


def test_success_executes_exact_routes_and_sanitizes_receipt() -> None:
    receipt, search, elasticsearch, clock, manifest = run_success()
    assert receipt["budget"] == {
        "requests": 14,
        "max_requests": 14,
        "actions": 14,
        "max_actions": 14,
    }
    assert len(search.requests) == 11
    assert len(elasticsearch.requests) == 3
    assert [
        request.full_url.removeprefix(SEARCH_ORIGIN) for request in search.requests[:4]
    ] == [
        "/api/v1/search",
        "/api/v1/search/attribute",
        "/api/v1/search/fusion",
        "/api/v1/search/image",
    ]
    assert [
        request.full_url.removeprefix(ES_ORIGIN) for request in elasticsearch.requests
    ] == ["/_mget", "/_bulk", "/_mget"]
    assert clock.sleeps == [2.0]
    assert receipt["cleanup"]["delay_milliseconds"] == 2000
    assert all(receipt["semantic_observations"].values())
    encoded = json.dumps(receipt, sort_keys=True)
    assert manifest["namespace"] not in encoded
    assert all(item["document_id"] not in encoded for item in manifest["documents"])
    assert "bounded fixture result" not in encoded
    assert (
        executor.validate_receipt(receipt)["status"]
        == "candidate_receipt_valid_non_promoting"
    )


def test_bulk_delete_is_exact_reverse_registered_document_order() -> None:
    _, _, elasticsearch, _, manifest = run_success()
    request = elasticsearch.requests[1]
    lines = [json.loads(line) for line in request.data.decode().splitlines()]
    expected = [
        {"delete": {"_index": item["index"], "_id": item["document_id"]}}
        for item in reversed(manifest["documents"])
    ]
    assert lines == expected
    assert all("delete" in line and len(line) == 1 for line in lines)


def test_authorization_mismatch_prevents_opener_construction() -> None:
    manifest, _ = make_manifest()
    calls = 0

    def factory() -> QueueOpener:
        nonlocal calls
        calls += 1
        return QueueOpener([])

    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement="wrong",
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=factory,
            elasticsearch_opener_factory=factory,
        )
    assert calls == 0


def test_non_loopback_target_is_rejected_before_transport() -> None:
    manifest, _ = make_manifest()
    with pytest.raises(executor.ExecutorError, match="authorization_required"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin="http://192.0.2.10:8000",
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=lambda: QueueOpener([]),
            elasticsearch_opener_factory=lambda: QueueOpener([]),
        )


def test_forbidden_alias_manifest_fails_before_transport() -> None:
    manifest, _ = make_manifest()
    manifest["operations"][1]["path"] = "/api/v1/attribute_search"
    with pytest.raises(executor.ExecutorError, match="invalid_manifest"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
        )


def test_source_digest_mismatch_never_registers_or_deletes() -> None:
    manifest, sources = make_manifest()
    search_responses, es_responses = make_responses(manifest, sources)
    es_responses[0][1]["docs"][0]["_source"] = {"tampered": True}
    search, elasticsearch = QueueOpener(search_responses), QueueOpener(es_responses)
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=lambda: search,
            elasticsearch_opener_factory=lambda: elasticsearch,
        )
    assert len(search.requests) == 0
    assert len(elasticsearch.requests) == 1


def test_semantic_failure_still_runs_exact_cleanup_and_postcondition() -> None:
    manifest, sources = make_manifest()
    search_responses, es_responses = make_responses(manifest, sources)
    search_responses[4] = (200, {"data": [], "search_messages": []})
    search, elasticsearch, clock = (
        QueueOpener(search_responses),
        QueueOpener(es_responses),
        FakeClock(),
    )
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=lambda: search,
            elasticsearch_opener_factory=lambda: elasticsearch,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )
    assert [
        request.full_url.removeprefix(ES_ORIGIN) for request in elasticsearch.requests
    ] == ["/_mget", "/_bulk", "/_mget"]


def test_late_reappearance_fails_cleanup_closed() -> None:
    manifest, sources = make_manifest()
    search_responses, es_responses = make_responses(manifest, sources, reappear=True)
    search, elasticsearch, clock = (
        QueueOpener(search_responses),
        QueueOpener(es_responses),
        FakeClock(),
    )
    with pytest.raises(executor.ExecutorError, match="cleanup_failed"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=lambda: search,
            elasticsearch_opener_factory=lambda: elasticsearch,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )


def test_invalid_negative_status_fails_but_cleans_up() -> None:
    manifest, sources = make_manifest()
    search_responses, es_responses = make_responses(manifest, sources)
    search_responses[-1] = (200, {"data": [], "search_messages": []})
    search, elasticsearch, clock = (
        QueueOpener(search_responses),
        QueueOpener(es_responses),
        FakeClock(),
    )
    with pytest.raises(executor.ExecutorError, match="oracle_failed"):
        executor.execute_http(
            manifest=manifest,
            run_id=RUN_ID,
            acknowledgement=ACK,
            search_origin=SEARCH_ORIGIN,
            elasticsearch_origin=ES_ORIGIN,
            search_opener_factory=lambda: search,
            elasticsearch_opener_factory=lambda: elasticsearch,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )
    assert len(elasticsearch.requests) == 3


def test_receipt_tampering_is_rejected() -> None:
    receipt, *_ = run_success()
    tampered = copy.deepcopy(receipt)
    tampered["promotion_eligible"] = True
    with pytest.raises(executor.ExecutorError, match="invalid_receipt"):
        executor.validate_receipt(tampered)
