from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import unquote, urlparse

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_rtsp_executor", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)

RUN_ID = "unit-a"
NAME = f"vss-search-rtsp-owned-{RUN_ID}"
SENSOR_ID = "00000000-0000-4000-8000-000000000001"
CONTROL_ID = "00000000-0000-4000-8000-000000000002"
CONTROL_NAME = "reviewed-unrelated-control"
RTSP_URL = "rtsp://127.0.0.1:8554/reviewed-test-stream"
RTSP_SHA = hashlib.sha256(RTSP_URL.encode()).hexdigest()
ACK = "I_ACK_SEARCH_RTSP_ARCHIVE_LIFECYCLE_AND_OWNED_CLEANUP"
INDICES = {
    "embed": "mdx-embed-filtered-2025-01-01",
    "behavior": "mdx-behavior-2025-01-01",
    "raw": "mdx-raw-2025-01-01",
}
CONTROL_SOURCES = {
    "embed": {"sensor": {"id": CONTROL_ID}, "marker": "control-embed"},
    "behavior": {"sensor": {"id": CONTROL_NAME}, "marker": "control-behavior"},
    "raw": {"sensorId": CONTROL_NAME, "marker": "control-raw"},
}


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

    def __init__(
        self, *, mutate_control_after_delete: bool = False, reappear: bool = False
    ) -> None:
        self.added = False
        self.deleted = False
        self.cleanup_round = 0
        self.mutate_control_after_delete = mutate_control_after_delete
        self.reappear = reappear
        self.requests: list[tuple[str, str]] = []

    @staticmethod
    def _search_response(rows: list[dict[str, Any]]) -> Response:
        return Response(
            200,
            {
                "timed_out": False,
                "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
                "hits": {"total": {"value": len(rows), "relation": "eq"}, "hits": rows},
            },
        )

    def _owned_row(self, index: str) -> dict[str, Any]:
        if index == INDICES["embed"]:
            source = {"sensor": {"id": SENSOR_ID}, "llm": {"visionEmbeddings": [[0.1]]}}
            suffix = "embed"
        elif index == INDICES["behavior"]:
            source = {"sensor": {"id": NAME}, "object": {"id": "object-1"}}
            suffix = "behavior"
        else:
            source = {"sensorId": NAME, "objects": [{"id": "object-1"}]}
            suffix = "raw"
        return {"_index": index, "_id": f"owned-{suffix}", "_source": source}

    def open(self, request: Any, timeout: float) -> Response:
        assert 0 < timeout <= 30
        method = request.get_method()
        parsed = urlparse(request.full_url)
        path = parsed.path
        self.requests.append((method, path))
        if method == "GET" and path == "/vst/api/v1/sensor/streams":
            streams = [{CONTROL_ID: [{"name": CONTROL_NAME}]}]
            if self.added and (
                not self.deleted or (self.reappear and self.cleanup_round >= 2)
            ):
                streams.append({SENSOR_ID: [{"name": NAME}]})
            if self.deleted:
                self.cleanup_round += 1
            return Response(200, streams)
        if method == "POST" and path == "/api/v1/rtsp-streams/add":
            payload = json.loads(request.data)
            assert payload == {
                "sensorUrl": RTSP_URL,
                "name": NAME,
                "username": "",
                "password": "",
                "location": "",
                "tags": "",
            }
            self.added = True
            return Response(
                200,
                {
                    "status": "success",
                    "message": "ok",
                    "sensorId": SENSOR_ID,
                    "name": NAME,
                },
            )
        if method == "DELETE" and path == f"/api/v1/rtsp-streams/delete/{NAME}":
            self.deleted = True
            return Response(
                200,
                {
                    "status": "success",
                    "message": "ok",
                    "sensorId": SENSOR_ID,
                    "name": NAME,
                },
            )
        if method == "POST" and path.endswith("/_search"):
            index = unquote(path.split("/", 2)[1])
            payload = json.loads(request.data)
            expected = next(iter(payload["query"]["term"].values()))
            owned_expected = SENSOR_ID if index == INDICES["embed"] else NAME
            present = self.added and not self.deleted and expected == owned_expected
            if (
                self.reappear
                and self.deleted
                and self.cleanup_round >= 2
                and expected == owned_expected
            ):
                present = True
            return self._search_response([self._owned_row(index)] if present else [])
        if method == "POST" and path == "/_mget":
            requested = json.loads(request.data)["docs"]
            rows = []
            for item in requested:
                index, document_id = item["_index"], item["_id"]
                family = next(
                    (key for key, value in INDICES.items() if value == index), None
                )
                if document_id.startswith("control-") and family is not None:
                    source = dict(CONTROL_SOURCES[family])
                    if (
                        self.deleted
                        and self.mutate_control_after_delete
                        and family == "raw"
                    ):
                        source["marker"] = "changed"
                    rows.append(
                        {
                            "_index": index,
                            "_id": document_id,
                            "found": True,
                            "_source": source,
                        }
                    )
                else:
                    present = self.added and not self.deleted
                    if self.reappear and self.deleted and self.cleanup_round >= 2:
                        present = True
                    row = {"_index": index, "_id": document_id, "found": present}
                    if present:
                        row["_source"] = self._owned_row(index)["_source"]
                    rows.append(row)
            return Response(200, {"docs": rows})
        raise AssertionError(f"unexpected request {method} {request.full_url}")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _control(tmp_path: Path) -> tuple[Path, str]:
    value = {
        "schema_version": 1,
        "sensor_id": CONTROL_ID,
        "name": CONTROL_NAME,
        "documents": [
            {
                "family": family,
                "index": index,
                "document_id": f"control-{family}",
                "source_sha256": hashlib.sha256(
                    _canonical(CONTROL_SOURCES[family])
                ).hexdigest(),
            }
            for family, index in INDICES.items()
        ],
    }
    path = tmp_path / "control.json"
    path.write_bytes(_canonical(value))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _execute(tmp_path: Path, opener: FakeOpener, **changes: Any) -> dict[str, Any]:
    control, control_sha = _control(tmp_path)
    arguments = {
        "run_id": RUN_ID,
        "acknowledgement": ACK,
        "rtsp_url": RTSP_URL,
        "reviewed_rtsp_sha256": RTSP_SHA,
        "control_path": control,
        "reviewed_control_sha256": control_sha,
        "agent_origin": "http://127.0.0.1:8000",
        "vst_origin": "http://127.0.0.1:30888",
        "elasticsearch_origin": "http://127.0.0.1:9200",
        "opener_factory": lambda: opener,
        "sleeper": lambda _seconds: None,
    }
    arguments.update(changes)
    return executor.execute_lifecycle(**arguments)


def test_plan_is_inert_and_locks_current_production_sources():
    assert executor.compile_plan() == {
        "schema_version": 1,
        "package_id": "search-rtsp-archive-lifecycle-successor",
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


def test_authorization_fails_before_transport(tmp_path: Path):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="authorization_required"):
        _execute(tmp_path, opener, acknowledgement="wrong")
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
def test_http_origins_are_numeric_loopback_only(tmp_path: Path, origin: str):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="configuration_error"):
        _execute(tmp_path, opener, agent_origin=origin)
    assert opener.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "rtsp://localhost:8554/x",
        "rtsp://8.8.8.8:8554/x",
        "rtsp://169.254.1.1:8554/x",
        "rtsp://0.0.0.0:8554/x",
        "http://127.0.0.1:8554/x",
        "rtsp://user:pass@127.0.0.1:8554/x",
    ],
)
def test_rtsp_url_is_exact_reviewed_numeric_local_only(tmp_path: Path, url: str):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError):
        _execute(
            tmp_path,
            opener,
            rtsp_url=url,
            reviewed_rtsp_sha256=hashlib.sha256(url.encode()).hexdigest(),
        )
    assert opener.requests == []


def test_private_container_gateway_rtsp_url_is_allowed() -> None:
    url = "rtsp://172.17.0.1:8554/reviewed-test-stream"
    digest = hashlib.sha256(url.encode()).hexdigest()

    assert executor._rtsp_url(url, digest) == url


def test_review_digest_mismatch_fails_before_transport(tmp_path: Path):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="authorization_required"):
        _execute(tmp_path, opener, reviewed_rtsp_sha256="0" * 64)
    assert opener.requests == []


def test_control_review_digest_mismatch_fails_before_transport(tmp_path: Path):
    opener = FakeOpener()
    with pytest.raises(executor.LifecycleError, match="authorization_required"):
        _execute(tmp_path, opener, reviewed_control_sha256="0" * 64)
    assert opener.requests == []


def test_success_binds_identity_readiness_control_and_delayed_cleanup(tmp_path: Path):
    opener = FakeOpener()
    receipt = _execute(tmp_path, opener)
    assert (
        receipt["status"] == "candidate_rtsp_archive_lifecycle_complete_non_promoting"
    )
    assert receipt["readiness"] == {
        "vst_exact_identity": True,
        "embed_documents": 1,
        "behavior_documents": 1,
        "raw_documents": 1,
        "complete_search_accounting": True,
    }
    assert receipt["control"]["preserved"] is True
    assert receipt["cleanup"]["delayed_no_reappearance"] is True
    assert receipt["budget"] == {
        "requests": 22,
        "max_requests": 64,
        "actions": 11,
        "max_actions": 11,
    }
    serialized = json.dumps(receipt)
    for secret in (RTSP_URL, NAME, SENSOR_ID, CONTROL_NAME, CONTROL_ID):
        assert secret not in serialized


def test_add_response_must_bind_exact_name_and_stable_sensor_id(tmp_path: Path):
    class WrongAddName(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            response = super().open(request, timeout)
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/api/v1/rtsp-streams/add"
            ):
                return Response(
                    200,
                    {
                        "status": "success",
                        "message": "ok",
                        "sensorId": SENSOR_ID,
                        "name": "wrong-name",
                    },
                )
            return response

    opener = WrongAddName()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.deleted is True


def test_owned_name_collision_fails_without_add_or_delete(tmp_path: Path):
    class Collision(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            response = super().open(request, timeout)
            if (
                request.get_method() == "GET"
                and urlparse(request.full_url).path == "/vst/api/v1/sensor/streams"
            ):
                return Response(
                    200,
                    [
                        {CONTROL_ID: [{"name": CONTROL_NAME}]},
                        {SENSOR_ID: [{"name": NAME}]},
                    ],
                )
            return response

    opener = Collision()
    with pytest.raises(executor.LifecycleError, match="ownership_conflict"):
        _execute(tmp_path, opener)
    assert not any(path == "/api/v1/rtsp-streams/add" for _, path in opener.requests)
    assert not any(method == "DELETE" for method, _ in opener.requests)


@pytest.mark.parametrize(
    "response",
    [
        {
            "timed_out": True,
            "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 2, "successful": 1, "skipped": 0, "failed": 1},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 1, "successful": 1, "failed": 0},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "timed_out": False,
            "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": 2, "relation": "eq"}, "hits": [{}]},
        },
    ],
)
def test_partial_search_accounting_never_proves_readiness_or_absence(response: Any):
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        executor._hits(response, 1000)


def test_control_mutation_after_owned_delete_fails_cleanup(tmp_path: Path):
    opener = FakeOpener(mutate_control_after_delete=True)
    with pytest.raises(executor.LifecycleError, match="cleanup_failed"):
        _execute(tmp_path, opener)
    assert opener.deleted is True


def test_delayed_reappearance_is_detected(tmp_path: Path):
    opener = FakeOpener(reappear=True)
    with pytest.raises(executor.LifecycleError, match="cleanup_failed"):
        _execute(tmp_path, opener)
    assert opener.deleted is True


def test_ambiguous_add_reconciles_exact_owned_name_and_cleans(tmp_path: Path):
    class LostAddResponse(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            if (
                request.get_method() == "POST"
                and urlparse(request.full_url).path == "/api/v1/rtsp-streams/add"
            ):
                self.requests.append(("POST", "/api/v1/rtsp-streams/add"))
                self.added = True
                raise TimeoutError("lost after allocation")
            return super().open(request, timeout)

    opener = LostAddResponse()
    with pytest.raises(executor.LifecycleError, match="transport_error"):
        _execute(tmp_path, opener)
    assert opener.deleted is True


def test_delete_response_must_bind_exact_name_and_sensor_id(tmp_path: Path):
    class WrongDeleteIdentity(FakeOpener):
        def open(self, request: Any, timeout: float) -> Response:
            response = super().open(request, timeout)
            if request.get_method() == "DELETE":
                return Response(
                    200,
                    {
                        "status": "success",
                        "message": "ok",
                        "sensorId": CONTROL_ID,
                        "name": NAME,
                    },
                )
            return response

    opener = WrongDeleteIdentity()
    with pytest.raises(executor.LifecycleError, match="cleanup_failed"):
        _execute(tmp_path, opener)


def test_empty_vst_descriptor_is_presence_not_absence():
    assert executor._streams([{SENSOR_ID: []}]) == {SENSOR_ID: None}
