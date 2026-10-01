# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""History snapshot clearing never invokes ingestion lifecycle endpoints."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import HTTPException
import httpx
from pydantic import ValidationError
import pytest

from vss_agents.api.history_clear import PIT_KEEP_ALIVE
from vss_agents.api.history_clear import CategorySnapshot
from vss_agents.api.history_clear import ClearHistoryRequest
from vss_agents.api.history_clear import HistoryClearService
from vss_agents.api.history_clear import HistoryPlan
from vss_agents.api.history_clear import category_for_index
from vss_agents.api.history_clear import category_query


@pytest.mark.parametrize("name", ["ab-alert-realtime-rules", ".security", "mdx-raw-thor-bootstrap", "default_fake"])
def test_strict_index_allowlist(name: str) -> None:
    assert category_for_index(name) is None


def test_appearance_vectors_are_clearable_generated_track_history() -> None:
    assert category_for_index("mdx-appearance-cosmos-768-v1") == "behavior"
    assert category_for_index("mdx-appearance-arbitrary/system") is None


def test_queries_preserve_unknown_times_and_cutoff_crossing_intervals() -> None:
    cutoff = datetime(2026, 10, 1, tzinfo=UTC)
    query = category_query("embeddings", cutoff)
    assert query["bool"]["filter"] == [
        {"range": {"timestamp": {"lt": cutoff.isoformat()}}},
        {"range": {"end": {"lt": cutoff.isoformat()}}},
    ]
    captions = category_query("captions", cutoff)
    assert captions["bool"]["filter"][1] == {
        "range": {"metadata.content_metadata.end_ntp_float": {"lt": cutoff.timestamp()}},
    }


def test_confirmation_cannot_override_sources_or_cutoff() -> None:
    with pytest.raises(ValidationError):
        ClearHistoryRequest(planToken="token-is-long-enough", confirmation="YES")
    with pytest.raises(ValidationError):
        ClearHistoryRequest(planToken="token-is-long-enough", confirmation="CLEAR_HISTORY", sourceIds=["other"])


def make_service() -> HistoryClearService:
    return HistoryClearService(
        SimpleNamespace(
            elasticsearch_url="http://search",
            vst_url="http://video",
            lvs_backend_url="",
            vst_streamprocessor_url="",
        )
    )


@pytest.mark.asyncio
async def test_snapshot_deletes_exact_versions_and_preserves_new_late_and_updated_data() -> None:
    service = make_service()
    cutoff = datetime.now(UTC) - timedelta(minutes=4, seconds=59)
    snapshot = CategorySnapshot("pit-before-confirmation", category_query("detections", cutoff), 2, 1)
    plan = HistoryPlan(cutoff, cutoff + timedelta(minutes=5), ["active-camera"], {"detections": snapshot})
    service.plans["token"] = plan
    # The PIT includes old versions only. Current store additionally has late and new arrivals.
    current = {"old": 3, "updated-track": 9, "new": 10, "late-old-timestamp": 11}
    captured = [("old", 3), ("updated-track", 4)]
    searches = 0
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal searches
        requests.append(str(request.url))
        if request.url.path == "/_search":
            body = json.loads(request.content)
            assert body["pit"]["id"] == "pit-before-confirmation"
            assert body["pit"]["keep_alive"] == PIT_KEEP_ALIVE
            searches += 1
            hits = (
                [
                    {
                        "_index": "mdx-raw-2026-10-01",
                        "_id": name,
                        "_seq_no": version,
                        "_primary_term": 1,
                        "sort": [index],
                    }
                    for index, (name, version) in enumerate(captured)
                ]
                if searches == 1
                else []
            )
            return httpx.Response(200, json={"hits": {"hits": hits}})
        if request.url.path == "/_bulk":
            items = []
            for line in request.content.decode().splitlines():
                operation = json.loads(line)["delete"]
                assert operation["if_primary_term"] == 1
                name = operation["_id"]
                if current[name] != operation["if_seq_no"]:
                    items.append({"delete": {"status": 409}})
                else:
                    del current[name]
                    items.append({"delete": {"status": 200, "result": "deleted"}})
            return httpx.Response(200, json={"items": items})
        if request.url.path == "/_pit":
            return httpx.Response(200, json={"succeeded": True})
        raise AssertionError(f"Unexpected service call {request.url}")

    original_client = httpx.AsyncClient
    with patch(
        "vss_agents.api.history_clear.httpx.AsyncClient",
        side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    ):
        result = await service.execute("token")
        repeated = await service.execute("token")
    assert current == {"updated-track": 9, "new": 10, "late-old-timestamp": 11}
    assert result["deletedByCategory"] == {"detections": 1}
    assert result["retainedByCategory"] == {"detections": 2}
    assert result["ingestionUnchanged"] is True
    assert repeated is result
    assert all("sensor" not in request and "stream" not in request for request in requests)


@pytest.mark.asyncio
async def test_expired_and_running_plans_cannot_execute() -> None:
    service = make_service()
    now = datetime.now(UTC)
    service.plans["expired"] = HistoryPlan(now, now - timedelta(seconds=1), [])
    service.plans["running"] = HistoryPlan(now, now + timedelta(minutes=1), [], running=True)
    for token in ("unknown", "expired", "running"):
        with pytest.raises(HTTPException) as exc:
            await service.execute(token)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_partial_bulk_reports_count_before_failure() -> None:
    service = make_service()
    now = datetime.now(UTC)
    snapshot = CategorySnapshot("pit", category_query("detections", now), 2, 0)
    service.plans["partial"] = HistoryPlan(now, now + timedelta(minutes=1), [], {"detections": snapshot})

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_search":
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_index": "mdx-raw-2026-10-01",
                                "_id": name,
                                "_seq_no": seq,
                                "_primary_term": 1,
                                "sort": [seq],
                            }
                            for seq, name in enumerate(("one", "two"))
                        ]
                    }
                },
            )
        if request.url.path == "/_bulk":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"delete": {"status": 200, "result": "deleted"}},
                        {"delete": {"status": 500}},
                    ]
                },
            )
        return httpx.Response(200, json={"succeeded": True})

    original_client = httpx.AsyncClient
    with patch(
        "vss_agents.api.history_clear.httpx.AsyncClient",
        side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    ):
        result = await service.execute("partial")
    assert result["deletedByCategory"]["detections"] == 1
    assert result["status"] == "partial"
    assert "detections" in result["failures"]


@pytest.mark.asyncio
async def test_preview_opens_all_snapshots_before_cutoff_and_ignores_unknown_indexes() -> None:
    service = make_service()
    pit_times: list[datetime] = []
    media_times: list[datetime] = []
    requested_indexes: list[str] = []

    async def capture_media(config: object, cutoff: datetime) -> dict[str, dict[str, int]]:
        assert len(pit_times) == 2
        media_times.append(datetime.now(UTC))
        assert cutoff <= media_times[0]
        return {"countsByCategory": {}, "retainedByCategory": {}, "failures": {}}

    def handle(request: httpx.Request) -> httpx.Response:
        if "sensor/streams" in request.url.path:
            return httpx.Response(200, json=[{"camera-id": [{"name": "camera"}]}])
        if request.url.path.endswith("/_mapping"):
            dates = {"mappings": {"properties": {"timestamp": {"type": "date"}, "end": {"type": "date"}}}}
            return httpx.Response(
                200,
                json={
                    "mdx-raw-2026-10-01": dates,
                    "mdx-embed-filtered-2026-10-01": dates,
                    "mdx-raw-thor-bootstrap": dates,
                    "default_fake": dates,
                },
            )
        if request.url.path.endswith("/_pit"):
            assert request.url.params["keep_alive"] == "30m"
            pit_times.append(datetime.now(UTC))
            requested_indexes.append(request.url.path)
            return httpx.Response(200, json={"id": f"pit-{len(pit_times)}"})
        if request.url.path == "/_search":
            assert len(pit_times) == 2
            body = json.loads(request.content)
            assert body["pit"]["keep_alive"] == "30m"
            if "query" in body:
                cutoff = body["query"]["bool"]["filter"][0]["range"]["timestamp"]["lt"]
                assert datetime.fromisoformat(cutoff) >= max(pit_times + media_times)
            return httpx.Response(200, json={"hits": {"total": {"value": 0, "relation": "eq"}}})
        raise AssertionError(request.url)

    original_client = httpx.AsyncClient
    with (
        patch(
            "vss_agents.api.history_clear.httpx.AsyncClient",
            side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
        ),
        patch("vss_agents.api.history_clear.preview_history_media", side_effect=capture_media),
    ):
        preview = await service.preview()
    assert media_times
    assert datetime.fromisoformat(preview["cutoff"]) >= media_times[0]
    assert preview["sourceIds"] == ["camera-id"]
    assert preview["countsByCategory"] == {"detections": 0, "embeddings": 0}
    assert all("bootstrap" not in path and "fake" not in path for path in requested_indexes)


@pytest.mark.asyncio
async def test_media_result_merged_and_private_manifest_stays_server_side() -> None:
    service = make_service()
    now = datetime.now(UTC)
    private_manifest = {
        "countsByCategory": {"recordings": 2},
        "retainedByCategory": {"recordings": 1},
        "failures": {},
        "recordings": [{"row_id": 123, "file_path": "/private/archive.mkv"}],
    }
    service.plans["media"] = HistoryPlan(now, now + timedelta(minutes=1), [], media=private_manifest)
    media_result = {"deletedByCategory": {"recordings": 2}, "retainedByCategory": {"recordings": 1}, "failures": {}}
    with patch("vss_agents.api.history_clear.clear_history_media", return_value=media_result) as clear:
        result = await service.execute("media")
    clear.assert_awaited_once_with(service.config, private_manifest)
    assert result["deletedByCategory"] == {"recordings": 2}
    assert result["retainedByCategory"] == {"recordings": 1}
    assert result["status"] == "success"
    assert "/private/archive.mkv" not in json.dumps(result)


@pytest.mark.asyncio
async def test_cancel_closes_only_snapshot_resources_and_is_repeatable() -> None:
    service = make_service()
    now = datetime.now(UTC)
    snapshot = CategorySnapshot("private-pit", category_query("detections", now), 12, 0)
    plan = HistoryPlan(now, now + timedelta(minutes=5), [], {"detections": snapshot})
    service.plans["cancel-plan"] = plan
    with patch.object(service, "_close", new_callable=AsyncMock) as close:
        result = await service.cancel("cancel-plan")
        repeated = await service.cancel("cancel-plan")
    assert close.await_count == 1
    assert close.await_args.args[1] is plan
    assert result == repeated == {"status": "cancelled", "ingestionUnchanged": True}
    assert "cancel-plan" not in service.plans
    assert snapshot.deleted == 0


@pytest.mark.asyncio
async def test_cancel_does_not_interrupt_running_clear() -> None:
    service = make_service()
    now = datetime.now(UTC)
    service.plans["running"] = HistoryPlan(now, now + timedelta(minutes=5), [], running=True)
    with patch.object(service, "_close", new_callable=AsyncMock) as close:
        with pytest.raises(HTTPException) as error:
            await service.cancel("running")
    assert error.value.status_code == 409
    close.assert_not_awaited()
    assert "running" in service.plans


@pytest.mark.asyncio
async def test_cancel_route_accepts_private_token_in_delete_body() -> None:
    from fastapi import FastAPI

    from vss_agents.api.history_clear import create_history_clear_router

    service = make_service()
    now = datetime.now(UTC)
    token = "token-with-enough-characters"
    service.plans[token] = HistoryPlan(now, now + timedelta(minutes=5), [])
    app = FastAPI()
    with patch("vss_agents.api.history_clear.HistoryClearService", return_value=service):
        app.include_router(create_history_clear_router(service.config))
    with patch.object(service, "_close", new_callable=AsyncMock):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://maintenance") as client:
            response = await client.request("DELETE", "/api/v1/history-clear", json={"planToken": token})
    assert response.status_code == 200
    assert response.json() == {"status": "cancelled", "ingestionUnchanged": True}
    assert token not in service.plans


@pytest.mark.asyncio
async def test_cancel_releases_evidence_and_pit_without_deleting_user_data() -> None:
    service = make_service()
    now = datetime.now(UTC)
    plan = HistoryPlan(
        now,
        now + timedelta(minutes=5),
        [],
        {"detections": CategorySnapshot("captured-pit", category_query("detections", now), 12, 0)},
        media={"evidence": {"planToken": "private-evidence-token"}},
    )
    service.plans["cancel-both"] = plan
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/_pit":
            assert request.method == "DELETE"
            assert json.loads(request.content) == {"id": "captured-pit"}
            return httpx.Response(200, json={"succeeded": True})
        if request.url.path == "/history/cancel":
            assert request.method == "POST"
            assert request.headers["X-History-Metadata-Token"] == "metadata-secret"
            assert json.loads(request.content) == {"planToken": "private-evidence-token"}
            return httpx.Response(200, json={"status": "cancelled"})
        raise AssertionError(f"Unexpected user-data mutation: {request.url}")

    original_client = httpx.AsyncClient
    with (
        patch.dict(
            "os.environ", {"HISTORY_EVIDENCE_URL": "http://evidence", "HISTORY_METADATA_TOKEN": "metadata-secret"}
        ),
        patch(
            "vss_agents.api.history_clear.httpx.AsyncClient",
            side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
        ),
    ):
        result = await service.cancel("cancel-both")
    assert result["status"] == "cancelled"
    assert len(requests) == 2
    assert plan.categories["detections"].deleted == 0
    assert "cancel-both" not in service.plans
