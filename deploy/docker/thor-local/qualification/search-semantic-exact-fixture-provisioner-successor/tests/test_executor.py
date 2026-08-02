from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import unquote, urlparse

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_exact_fixture_executor", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


SENSOR_ID = "00000000-0000-4000-8000-000000000001"
RUN_ID = "unit-a"
NAMESPACE = f"vss-search-owned-{RUN_ID}"
ACK = "I_ACK_SEARCH_EXACT_FIXTURE_LIFECYCLE_AND_OWNED_CLEANUP"


class Response:
    def __init__(self, status: int, value: Any) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self._body = json.dumps(value, separators=(",", ":")).encode()

    def read(self, maximum: int) -> bytes:
        return self._body[:maximum]


class FakeOpener:
    proxies_enabled = False
    redirects_enabled = False

    def __init__(self, *, functional: bool = True) -> None:
        self.functional = functional
        self.uploaded = False
        self.completed = False
        self.deleted = False
        self.requests: list[tuple[str, str]] = []

    @staticmethod
    def _empty_search() -> Response:
        return Response(
            200,
            {
                "timed_out": False,
                "_shards": {
                    "total": 1,
                    "successful": 1,
                    "skipped": 0,
                    "failed": 0,
                },
                "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
            },
        )

    def _search(self, index: str) -> Response:
        if not self.completed or self.deleted:
            return self._empty_search()
        if index == "mdx-embed-filtered-2025-01-01":
            source = {
                "sensor": {"id": SENSOR_ID},
                "llm": {"visionEmbeddings": [{"vector": [0.1, 0.2]}]},
            }
            row = {"_index": index, "_id": "embed-1", "_source": source}
        elif index == "mdx-behavior-2025-01-01":
            source = {
                "sensor": {"id": NAMESPACE},
                "object": {"id": "object-7"},
                "timestamp": "2025-01-01T00:00:01Z",
                "end": "2025-01-01T00:00:03Z",
                "embeddings": {"vector": [0.3, 0.4]},
            }
            row = {"_index": index, "_id": "behavior-1", "_source": source}
        else:
            if not self.functional:
                return self._empty_search()
            source = {
                "sensorId": NAMESPACE,
                "timestamp": "2025-01-01T00:00:02Z",
                "objects": [
                    {
                        "id": "object-7",
                        "bbox": {"leftX": 1, "rightX": 10, "topY": 2, "bottomY": 20},
                    }
                ],
            }
            row = {"_index": index, "_id": "raw-1", "_source": source}
        return Response(
            200,
            {
                "timed_out": False,
                "_shards": {
                    "total": 1,
                    "successful": 1,
                    "skipped": 0,
                    "failed": 0,
                },
                "hits": {
                    "total": {"value": 1, "relation": "eq"},
                    "hits": [row],
                },
            },
        )

    def open(self, request: Any, timeout: float) -> Response:
        del timeout
        method = request.get_method()
        url = request.full_url
        self.requests.append((method, url))
        parsed = urlparse(url)
        path = parsed.path
        if method == "GET" and path == "/vst/api/v1/sensor/streams":
            if self.uploaded and not self.deleted:
                return Response(200, [{SENSOR_ID: [{"name": NAMESPACE}]}])
            return Response(200, [])
        if method == "POST" and path == "/api/v1/videos":
            return Response(
                200, {"url": "http://127.0.0.1:30888/vst/api/v1/storage/file"}
            )
        if method == "POST" and path == "/vst/api/v1/storage/file":
            assert request.get_header("Nvstreamer-chunk-number") == "1"
            assert request.get_header("Nvstreamer-total-chunks") == "1"
            assert request.get_header("Nvstreamer-is-last-chunk") == "true"
            assert request.get_header("Nvstreamer-file-name") == f"{NAMESPACE}.mp4"
            assert executor.UUID_RE.fullmatch(
                request.get_header("Nvstreamer-identifier")
            )
            self.uploaded = True
            return Response(200, {"sensorId": SENSOR_ID})
        if method == "POST" and path == f"/api/v1/videos/{SENSOR_ID}/complete":
            self.completed = True
            return Response(
                200,
                {
                    "message": "ok",
                    "sensor_id": SENSOR_ID,
                    "filename": NAMESPACE,
                    "chunks_processed": 1,
                },
            )
        if method == "DELETE" and path == f"/api/v1/videos/{SENSOR_ID}":
            self.deleted = True
            return Response(
                200, {"status": "success", "message": "ok", "video_id": SENSOR_ID}
            )
        if method == "POST" and path == "/_mget":
            body = json.loads(request.data)
            return Response(
                200,
                {
                    "docs": [
                        {"_index": item["_index"], "_id": item["_id"], "found": False}
                        for item in body["docs"]
                    ]
                },
            )
        if method == "POST" and path.endswith("/_search"):
            return self._search(unquote(path.split("/", 2)[1]))
        raise AssertionError(f"unexpected request: {method} {url}")


def _media(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"0" * 256)
    return path


def _execute(tmp_path: Path, opener: FakeOpener) -> dict[str, Any]:
    return executor.execute_lifecycle(
        run_id=RUN_ID,
        acknowledgement=ACK,
        media_path=_media(tmp_path),
        agent_origin="http://127.0.0.1:8000",
        vst_origin="http://127.0.0.1:30888",
        elasticsearch_origin="http://127.0.0.1:9200",
        opener_factory=lambda: opener,
        sleeper=lambda _seconds: None,
    )


def test_inert_plan_source_locks_current_production_contracts():
    plan = executor.compile_plan()
    assert plan == {
        "schema_version": 1,
        "package_id": "search-semantic-exact-fixture-provisioner-successor",
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


def test_authorization_fails_before_transport(tmp_path: Path):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="authorization_required"):
        executor.execute_lifecycle(
            run_id=RUN_ID,
            acknowledgement="wrong",
            media_path=_media(tmp_path),
            agent_origin="http://127.0.0.1:8000",
            vst_origin="http://127.0.0.1:30888",
            elasticsearch_origin="http://127.0.0.1:9200",
            opener_factory=lambda: opener,
        )
    assert opener.requests == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8000",
        "https://127.0.0.1:8000",
        "http://10.0.0.1:8000",
        "http://127.0.0.1",
    ],
)
def test_non_numeric_or_non_loopback_origins_fail_closed(tmp_path: Path, origin: str):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="configuration_error"):
        executor.execute_lifecycle(
            run_id=RUN_ID,
            acknowledgement=ACK,
            media_path=_media(tmp_path),
            agent_origin=origin,
            vst_origin="http://127.0.0.1:30888",
            elasticsearch_origin="http://127.0.0.1:9200",
            opener_factory=lambda: opener,
        )
    assert opener.requests == []


def test_success_discovers_model_documents_and_proves_delayed_cleanup(tmp_path: Path):
    opener = FakeOpener()
    receipt = _execute(tmp_path, opener)
    assert receipt["status"] == "candidate_fixture_lifecycle_complete_non_promoting"
    assert receipt["fixture"] == {
        "embed_documents": 1,
        "behavior_documents": 1,
        "raw_documents": 1,
        "selected_object_reconciled": True,
        "handoff_sha256": receipt["fixture"]["handoff_sha256"],
        "consumer_invoked": False,
        "consumer_receipt_sha256": None,
        "consumer_transport_accounting": "not-requested",
        "raw_document_ids_recorded": True,
        "operator_preprovisioned": False,
    }
    assert receipt["cleanup"]["delayed_no_reappearance"] is True
    assert receipt["cleanup"]["remediation_deleted_documents"] == 0
    assert receipt["cleanup"]["consecutive_absence_observations"] == 2
    assert receipt["cleanup"]["foreign_delete_attempted"] is False
    assert receipt["budget"]["requests"] == 24
    assert opener.deleted is True
    assert sum(path.endswith("/_mget") for _, path in opener.requests) == 2


def test_unbounded_consumer_is_rejected_before_transport(tmp_path: Path):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="configuration_error"):
        executor.execute_lifecycle(
            run_id=RUN_ID,
            acknowledgement=ACK,
            media_path=_media(tmp_path),
            agent_origin="http://127.0.0.1:8000",
            vst_origin="http://127.0.0.1:30888",
            elasticsearch_origin="http://127.0.0.1:9200",
            opener_factory=lambda: opener,
            fixture_consumer=lambda _handoff: None,
        )
    assert opener.requests == []


def _semantic_template() -> dict[str, Any]:
    def assertion(shape: str, *, maximum: int = 10, span: int = 0) -> dict[str, Any]:
        return {
            "response_shape": shape,
            "minimum_results": 1,
            "maximum_results": maximum,
            "expected_sensor_ids": ["$sensor_id"],
            "expected_object_ids": ["$selected_object_id"],
            "expected_ordered_sensor_ids": [],
            "top_sensor_id": "$sensor_id",
            "top_video_name": "$namespace",
            "minimum_span_seconds": span,
        }

    search_body = {
        "query": "person walking",
        "source_type": "video_file",
        "video_sources": ["$namespace"],
        "agent_mode": False,
        "use_critic": False,
    }
    attribute_body = {
        "query": "red clothing",
        "source_type": "video_file",
        "video_sources": ["$namespace"],
        "fuse_multi_attribute": False,
    }
    specs = [
        ("search-route", "/api/v1/search", search_body, assertion("search"), 200),
        (
            "attribute-route",
            "/api/v1/search/attribute",
            attribute_body,
            assertion("attribute"),
            200,
        ),
        (
            "fusion-route",
            "/api/v1/search/fusion",
            search_body | {"agent_mode": True},
            assertion("search"),
            200,
        ),
        (
            "image-route",
            "/api/v1/search/image",
            search_body | {"reference_object": "$selected_object"},
            assertion("search"),
            200,
        ),
        (
            "same-object-merge",
            "/api/v1/search",
            search_body,
            assertion("search", span=1),
            200,
        ),
        (
            "append-multiple-attributes",
            "/api/v1/search/attribute",
            attribute_body | {"query": ["red clothing", "walking"]},
            assertion("attribute"),
            200,
        ),
        (
            "rerank-or-fallback",
            "/api/v1/search/fusion",
            search_body | {"agent_mode": True},
            assertion("search"),
            200,
        ),
        (
            "fuse-multiple-attributes",
            "/api/v1/search/attribute",
            attribute_body
            | {
                "query": ["red clothing", "walking"],
                "fuse_multi_attribute": True,
            },
            assertion("attribute"),
            200,
        ),
        (
            "same-video-top-k",
            "/api/v1/search",
            search_body | {"top_k": 1},
            assertion("search", maximum=1),
            200,
        ),
        (
            "selected-bbox-knn",
            "/api/v1/search/image",
            search_body | {"reference_object": "$selected_object"},
            assertion("search"),
            200,
        ),
        (
            "reject-invalid-index-family",
            "/api/v1/search",
            {
                "query": "reject invalid index family",
                "source_type": "vss-invalid-search-*",
                "agent_mode": False,
                "use_critic": False,
            },
            {
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
            422,
        ),
    ]
    return {
        "schema_version": 1,
        "media_attestation": executor.BoundedSemanticFixtureConsumer.ATTESTATION,
        "operations": [
            {
                "step_id": step_id,
                "method": "POST",
                "path": path,
                "body": body,
                "allowed_statuses": [status],
                "assertion": expected,
            }
            for step_id, path, body, expected, status in specs
        ],
    }


def test_dynamic_consumer_uses_handoff_and_shared_transport(tmp_path: Path):
    class SemanticOpener(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            path = urlparse(request.full_url).path
            if request.get_method() == "POST" and path.startswith("/api/v1/search"):
                self.requests.append((request.get_method(), request.full_url))
                body = json.loads(request.data)
                if body.get("source_type") == "vss-invalid-search-*":
                    return Response(422, {"detail": [{"msg": "invalid"}]})
                assert body["video_sources"] == [NAMESPACE]
                if path.endswith("/attribute"):
                    return Response(
                        200,
                        [
                            {
                                "metadata": {
                                    "sensor_id": SENSOR_ID,
                                    "video_name": NAMESPACE,
                                    "object_id": "object-7",
                                    "start_time": "2025-01-01T00:00:01Z",
                                    "end_time": "2025-01-01T00:00:03Z",
                                }
                            }
                        ],
                    )
                return Response(
                    200,
                    {
                        "data": [
                            {
                                "sensor_id": SENSOR_ID,
                                "video_name": NAMESPACE,
                                "object_ids": ["object-7"],
                                "start_time": "2025-01-01T00:00:01Z",
                                "end_time": "2025-01-01T00:00:03Z",
                            }
                        ],
                        "search_messages": [],
                    },
                )
            return super().open(request, timeout)

    opener = SemanticOpener()
    consumer = executor.BoundedSemanticFixtureConsumer(
        search_origin="http://127.0.0.1:8001", template=_semantic_template()
    )
    receipt = executor.execute_lifecycle(
        run_id=RUN_ID,
        acknowledgement=ACK,
        media_path=_media(tmp_path),
        agent_origin="http://127.0.0.1:8000",
        vst_origin="http://127.0.0.1:30888",
        elasticsearch_origin="http://127.0.0.1:9200",
        opener_factory=lambda: opener,
        sleeper=lambda _seconds: None,
        fixture_consumer=consumer,
    )
    assert receipt["fixture"]["consumer_invoked"] is True
    assert receipt["fixture"]["consumer_receipt_sha256"] is not None
    assert (
        receipt["fixture"]["consumer_transport_accounting"]
        == "shared-lifecycle-budget-and-deadline"
    )
    assert receipt["budget"] == {
        "requests": 35,
        "max_requests": 77,
        "actions": 23,
        "max_actions": 23,
    }


def test_delayed_scoped_writes_are_exactly_remediated(tmp_path: Path):
    class DelayedWriteOpener(FakeOpener):
        def __init__(self) -> None:
            super().__init__()
            self.late = False

        def _search(self, index: str) -> Response:
            if not self.late:
                return super()._search(index)
            deleted = self.deleted
            self.deleted = False
            try:
                return super()._search(index)
            finally:
                self.deleted = deleted

        def open(self, request: Any, timeout: float) -> Response:
            path = urlparse(request.full_url).path
            method = request.get_method()
            if method == "POST" and path == "/_bulk":
                self.requests.append((method, request.full_url))
                rows = [json.loads(line) for line in request.data.splitlines()]
                self.late = False
                return Response(
                    200,
                    {
                        "errors": False,
                        "items": [
                            {
                                "delete": {
                                    "_index": row["delete"]["_index"],
                                    "_id": row["delete"]["_id"],
                                    "status": 200,
                                    "result": "deleted",
                                }
                            }
                            for row in rows
                        ],
                    },
                )
            if method == "POST" and path == "/_mget" and self.late:
                self.requests.append((method, request.full_url))
                requested = json.loads(request.data)["docs"]
                documents = []
                for item in requested:
                    search = json.loads(self._search(item["_index"])._body)
                    source = search["hits"]["hits"][0]["_source"]
                    documents.append(item | {"found": True, "_source": source})
                return Response(200, {"docs": documents})
            response = super().open(request, timeout)
            if method == "DELETE" and path == f"/api/v1/videos/{SENSOR_ID}":
                self.late = True
            return response

    opener = DelayedWriteOpener()
    receipt = _execute(tmp_path, opener)
    assert receipt["cleanup"]["remediation_deleted_documents"] == 3
    assert receipt["cleanup"]["consecutive_absence_observations"] == 2
    assert receipt["budget"]["requests"] == 30
    assert sum(path.endswith("/_bulk") for _, path in opener.requests) == 1


def test_empty_vst_stream_entry_is_not_misclassified_as_absent():
    assert executor._streams([{SENSOR_ID: []}]) == {SENSOR_ID: None}


@pytest.mark.parametrize(
    "response",
    [
        {
            "timed_out": True,
            "_shards": {"failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 3, "successful": 2, "failed": 1},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 3, "successful": 2, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 1, "successful": True, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {
                "total": 1,
                "successful": 1,
                "skipped": 0,
                "failed": 0,
            },
            "hits": {"total": {"value": 2, "relation": "eq"}, "hits": [{}]},
        },
    ],
)
def test_partial_elasticsearch_search_never_proves_absence(response):
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        executor._hits(response, 1000)


@pytest.mark.parametrize("mode", ["wrong-id", "reordered"])
def test_exact_absence_rejects_uncorrelated_mget_rows(tmp_path: Path, mode: str):
    class BadMget(FakeOpener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/_mget"
            ):
                value = json.loads(response._body)
                if mode == "wrong-id":
                    value["docs"][0]["_id"] = "wrong"
                else:
                    value["docs"].reverse()
                return Response(200, value)
            return response

    opener = BadMget()
    with pytest.raises(executor.LifecycleError, match="cleanup_failed"):
        _execute(tmp_path, opener)


def test_shared_deadline_clamps_requests_and_reserves_cleanup_time():
    class CaptureOpener:
        proxies_enabled = False
        redirects_enabled = False

        def __init__(self):
            self.timeouts = []

        def open(self, request, timeout):
            del request
            self.timeouts.append(timeout)
            return "response"

    now = [0.0]
    capture = CaptureOpener()
    bounded = executor.DeadlineOpener(
        capture,
        maximum_seconds=900,
        cleanup_reserve_seconds=180,
        monotonic=lambda: now[0],
    )
    assert bounded.open(object(), 600) == "response"
    assert capture.timeouts == [600.0]
    now[0] = 710.0
    bounded.open(object(), 60)
    assert capture.timeouts[-1] == 10.0
    now[0] = 721.0
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        bounded.open(object(), 60)
    bounded.enter_cleanup()
    bounded.open(object(), 60)
    assert capture.timeouts[-1] == 60.0


@pytest.mark.parametrize(
    "bbox",
    [
        {"leftX": True, "rightX": 10, "topY": 2, "bottomY": 20},
        {"leftX": -1, "rightX": 10, "topY": 2, "bottomY": 20},
        {"leftX": 10, "rightX": 1, "topY": 2, "bottomY": 20},
    ],
)
def test_selected_object_rejects_invalid_bbox(bbox):
    behavior = [
        {
            "_source": {
                "sensor": {"id": NAMESPACE},
                "object": {"id": "object-7"},
                "timestamp": "2025-01-01T00:00:01Z",
                "end": "2025-01-01T00:00:03Z",
                "embeddings": {"vector": [0.3]},
            }
        }
    ]
    raw = [
        {
            "_source": {
                "sensorId": NAMESPACE,
                "timestamp": "2025-01-01T00:00:02Z",
                "objects": [{"id": "object-7", "bbox": bbox}],
            }
        }
    ]
    with pytest.raises(executor.LifecycleError, match="fixture_not_ready"):
        executor._selected_object(behavior, raw, NAMESPACE)


def test_selected_object_rejects_bbox_outside_behavior_interval():
    behavior = [
        {
            "_source": {
                "sensor": {"id": NAMESPACE},
                "object": {"id": "object-7"},
                "timestamp": "2025-01-01T00:00:01Z",
                "end": "2025-01-01T00:00:03Z",
                "embeddings": {"vector": [0.3]},
            }
        }
    ]
    raw = [
        {
            "_source": {
                "sensorId": NAMESPACE,
                "timestamp": "2025-01-01T00:00:04Z",
                "objects": [
                    {
                        "id": "object-7",
                        "bbox": {"leftX": 1, "rightX": 10, "topY": 2, "bottomY": 20},
                    }
                ],
            }
        }
    ]
    with pytest.raises(executor.LifecycleError, match="fixture_not_ready"):
        executor._selected_object(behavior, raw, NAMESPACE)


def test_selected_object_uses_raw_bbox_frame_timestamp():
    behavior = [
        {
            "_source": {
                "sensor": {"id": NAMESPACE},
                "object": {"id": "object-7"},
                "timestamp": "2025-01-01T00:00:01Z",
                "end": "2025-01-01T00:00:03Z",
                "embeddings": {"vector": [0.3]},
            }
        }
    ]
    raw = [
        {
            "_source": {
                "sensorId": NAMESPACE,
                "timestamp": "2025-01-01T00:00:02Z",
                "objects": [
                    {
                        "id": "object-7",
                        "bbox": {
                            "leftX": 1,
                            "rightX": 10,
                            "topY": 2,
                            "bottomY": 20,
                        },
                    }
                ],
            }
        }
    ]
    assert executor._selected_object(behavior, raw, NAMESPACE)["timestamp"] == (
        "2025-01-01T00:00:02Z"
    )


def test_not_ready_still_uses_agent_delete_and_exact_absence_checks(tmp_path: Path):
    opener = FakeOpener(functional=False)
    with pytest.raises(executor.LifecycleError, match="fixture_not_ready"):
        _execute(tmp_path, opener)
    assert opener.deleted is True
    assert len(opener.requests) == 51
    assert sum(path.endswith("/_mget") for _, path in opener.requests) == 2


def test_upload_url_must_equal_reviewed_vst_origin(tmp_path: Path):
    class WrongUploadUrl(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/api/v1/videos"
            ):
                self.requests.append((request.get_method(), request.full_url))
                return Response(
                    200, {"url": "http://127.0.0.1:39999/vst/api/v1/storage/file"}
                )
            return super().open(request, timeout)

    opener = WrongUploadUrl()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.uploaded is False
    assert opener.deleted is False


def test_transport_failure_after_allocation_is_wrapped_and_cleaned(tmp_path: Path):
    class CompleteTransportFailure(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path
                == f"/api/v1/videos/{SENSOR_ID}/complete"
            ):
                raise OSError("simulated transport failure")
            return super().open(request, timeout)

    opener = CompleteTransportFailure()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.uploaded is True
    assert opener.deleted is True


def test_ambiguous_upload_timeout_reconciles_owned_name_and_cleans(tmp_path: Path):
    class AmbiguousUploadTimeout(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/vst/api/v1/storage/file"
            ):
                self.requests.append((request.get_method(), request.full_url))
                self.uploaded = True
                raise TimeoutError("response lost after VST allocation")
            return super().open(request, timeout)

    opener = AmbiguousUploadTimeout()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.uploaded is True
    assert opener.deleted is True
    assert (
        sum(path.endswith("/vst/api/v1/sensor/streams") for _, path in opener.requests)
        == 4
    )


@pytest.mark.parametrize(
    "reported_sensor_id",
    ["not-a-uuid", "00000000-0000-4000-8000-000000000099"],
)
def test_malformed_upload_identity_reconciles_owned_name_and_cleans(
    tmp_path: Path, reported_sensor_id: str
):
    class MalformedUploadIdentity(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            response = super().open(request, timeout)
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/vst/api/v1/storage/file"
            ):
                return Response(200, {"sensorId": reported_sensor_id})
            return response

    opener = MalformedUploadIdentity()
    with pytest.raises(executor.LifecycleError) as caught:
        _execute(tmp_path, opener)
    assert caught.value.code in {"transport_error", "ownership_conflict"}
    assert opener.uploaded is True
    assert opener.deleted is True
    assert sum(
        path.endswith("/vst/api/v1/sensor/streams") for _, path in opener.requests
    ) == (4 if reported_sensor_id == "not-a-uuid" else 5)


def test_ambiguous_upload_without_allocation_reproves_name_absence(tmp_path: Path):
    class UploadTimeoutBeforeAllocation(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/vst/api/v1/storage/file"
            ):
                self.requests.append((request.get_method(), request.full_url))
                raise TimeoutError("VST did not allocate")
            return super().open(request, timeout)

    opener = UploadTimeoutBeforeAllocation()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.uploaded is False
    assert opener.deleted is False
    assert sum(path.endswith("/_search") for _, path in opener.requests) == 4


def test_ambiguous_upload_duplicate_owned_names_fails_without_guessing(tmp_path: Path):
    second_sensor_id = "00000000-0000-4000-8000-000000000002"

    class DuplicateOwnedNames(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            method = request.get_method()
            path = urlparse(request.full_url).path
            if method == "POST" and path == "/vst/api/v1/storage/file":
                self.requests.append((method, request.full_url))
                self.uploaded = True
                raise TimeoutError("ambiguous duplicate allocation")
            if (
                method == "GET"
                and path == "/vst/api/v1/sensor/streams"
                and self.uploaded
                and not self.deleted
            ):
                self.requests.append((method, request.full_url))
                return Response(
                    200,
                    [
                        {SENSOR_ID: [{"name": NAMESPACE}]},
                        {second_sensor_id: [{"name": NAMESPACE}]},
                    ],
                )
            return super().open(request, timeout)

    opener = DuplicateOwnedNames()
    with pytest.raises(executor.LifecycleError, match="cleanup_failed"):
        _execute(tmp_path, opener)
    assert opener.deleted is False
    assert not any(method == "DELETE" for method, _path in opener.requests)
