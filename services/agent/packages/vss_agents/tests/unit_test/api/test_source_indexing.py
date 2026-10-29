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

"""Finite indexing intent, real cancellation boundaries and honest status."""

import asyncio
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from vss_agents.api import rtsp_ingest
from vss_agents.api import source_indexing as state
from vss_agents.api import source_indexing_control as control
from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.source_analysis_state import load_source_analysis_state
from vss_agents.api.source_analysis_state import set_source_analysis_profile
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.api.source_analysis_state import set_source_paused
from vss_agents.api.source_control import create_source_control_router


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VSS_SOURCE_ANALYSIS_STATE_FILE", str(tmp_path / "source-analysis-state.json"))
    monkeypatch.setenv("VSS_SOURCE_INDEXING_STATE_FILE", str(tmp_path / "source-indexing-state.json"))
    load_source_analysis_state(force=True)
    state.load_indexing_policies(force=True)
    rtsp_ingest._embedding_operation_locks.clear()
    rtsp_ingest._embedding_cleanup_results.clear()
    yield
    rtsp_ingest._embedding_operation_locks.clear()
    rtsp_ingest._embedding_cleanup_results.clear()


@pytest.fixture
def config():
    return ServiceConfig(
        vst_internal_url="http://vst.test",
        rtvi_cv_base_url="http://cv.test",
        rtvi_embed_base_url="http://embed.test",
        elasticsearch_url="http://search.test",
    )


def endpoint(config, method):
    router = control.create_source_indexing_router(config)
    return next(route.endpoint for route in router.routes if method in route.methods)


def city():
    set_source_analysis_profile("camera", "smart-city")


def verified_source():
    return patch.object(
        control,
        "get_stream_info_by_name",
        new=AsyncMock(return_value=(True, "OK", "camera", "rtsp://source.test/live")),
    )


def test_defaults_and_durable_disabled_policy():
    assert state.get_indexing_policy("warehouse").mode == "continuous"
    city()
    assert state.get_indexing_policy("camera").mode == "on-demand"
    assert state.indexing_is_allowed("camera") is False
    state.set_indexing_mode("camera", "disabled")
    state.load_indexing_policies(force=True)
    assert state.get_indexing_policy("camera").mode == "disabled"
    assert state.indexing_is_allowed("warehouse") is True


def test_finite_session_is_interrupted_after_restart():
    city()
    session = state.begin_indexing_session("camera", 120)
    state.mark_indexing_started("camera", session.id)
    assert state.indexing_is_allowed("camera", session.id)
    state.load_indexing_policies(force=True)
    restored = state.get_indexing_policy("camera").session
    assert restored.id == session.id
    assert restored.state == "interrupted"
    assert restored.ended_at is not None
    assert state.indexing_is_allowed("camera") is False


def test_expired_session_never_restarts_or_changes_terminal_state():
    city()
    session = state.begin_indexing_session("camera", 30)
    state._policies["camera"].session.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    assert state.indexing_is_allowed("camera") is False
    assert state.get_indexing_policy("camera").session.state == "completed"
    state.mark_indexing_started("camera", session.id)
    assert state.get_indexing_policy("camera").session.state == "completed"


def test_paused_source_cannot_begin_a_window():
    city()
    set_source_paused("camera", True)
    with pytest.raises(ValueError, match="Resume"):
        state.begin_indexing_session("camera", 120)
    assert not state.indexing_is_allowed("camera")


def test_switch_to_continuous_does_not_keep_an_old_window_as_current_scope():
    city()
    state.begin_indexing_session("camera", 120)
    state.finish_indexing_session("camera", "cancelled", "operator")
    state.set_indexing_mode("camera", "continuous")
    assert state.get_indexing_policy("camera").session is None
    assert state.indexing_is_allowed("camera")


def test_corrupt_policy_fails_closed_for_all_profiles(monkeypatch, tmp_path):
    path = tmp_path / "source-indexing-state.json"
    path.write_text('{"schemaVersion": 500, "sources": {}}')
    state.load_indexing_policies(force=True)
    assert state.get_indexing_policy("warehouse").mode == "disabled"
    assert not state.indexing_is_allowed("warehouse")
    with pytest.raises(ValueError, match="Repair"):
        state.set_indexing_mode("warehouse", "continuous")
    assert json.loads(path.read_text())["schemaVersion"] == 500


def test_timezone_less_persisted_lease_fails_closed(tmp_path):
    city()
    state.begin_indexing_session("camera", 120)
    path = tmp_path / "source-indexing-state.json"
    body = json.loads(path.read_text())
    body["sources"]["camera"]["session"]["deadlineAt"] = "2026-10-26T16:00:00"
    path.write_text(json.dumps(body))
    state.load_indexing_policies(force=True)
    assert state.indexing_policy_error() == "indexing-policy-state-unreadable"
    assert state.get_indexing_policy("camera").mode == "disabled"
    assert not state.indexing_is_allowed("camera")


@pytest.mark.parametrize("duration", [0, 29, 601, True, 30.5, "120"])
def test_window_validation_is_strict_and_bounded(duration):
    with pytest.raises(ValidationError):
        control.IndexingActionRequest(name="Intersection", action="start", durationSeconds=duration)


@pytest.mark.asyncio
async def test_policy_is_persisted_before_stopping_any_resources(config):
    city()

    async def stop(*args):
        assert state.get_indexing_policy("camera").mode == "disabled"
        return True, "Stopped"

    with verified_source(), patch.object(control, "stop_source_indexing", new=AsyncMock(side_effect=stop)) as cleanup:
        result = await endpoint(config, "PUT")(
            "camera", control.IndexingPolicyRequest(name="Intersection", mode="disabled")
        )
    cleanup.assert_awaited_once()
    assert result["mode"] == "disabled"
    assert not result["generationConnected"]
    assert not result["searchScope"]["available"]
    assert result["evidence"]["documentCount"] is None


@pytest.mark.asyncio
async def test_start_window_has_a_finite_lease_and_does_not_touch_cv(config):
    city()
    with (
        verified_source(),
        patch.object(control, "stop_source_indexing", new=AsyncMock(return_value=(True, "OK"))),
        patch.object(control, "add_to_rtvi_embed", new=AsyncMock(return_value=(True, "OK", "camera"))) as register,
        patch.object(control, "start_embedding_generation", new=AsyncMock(return_value=(True, "OK"))) as start,
        patch.object(
            control, "_window_evidence", new=AsyncMock(return_value={"status": "no-documents", "liveFresh": False})
        ),
        patch.object(rtsp_ingest, "add_to_rtvi_cv", new=AsyncMock()) as cv,
    ):
        result = await endpoint(config, "POST")(
            "camera", control.IndexingActionRequest(name="Intersection", action="start", durationSeconds=120)
        )
    assert result["session"]["durationSeconds"] == 120
    assert result["session"]["state"] == "starting"
    assert result["indexingRequested"] is True
    assert result["generationConnected"] is False
    assert result["state"] == "recovering"
    assert result["searchScope"]["applied"] is False
    assert result["searchScope"]["queryParams"] is None
    register.assert_awaited_once()
    start.assert_awaited_once()
    cv.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_start_does_not_replace_the_current_session(config):
    city()
    original = state.begin_indexing_session("camera", 120)
    with verified_source(), patch.object(control, "stop_source_indexing", new=AsyncMock()) as stop:
        with pytest.raises(HTTPException) as error:
            await endpoint(config, "POST")("camera", control.IndexingActionRequest(name="Intersection", action="start"))
    assert error.value.status_code == 409
    assert state.get_indexing_policy("camera").session.id == original.id
    stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_window_is_durable_before_cleanup_and_does_not_reconcile(config):
    city()
    state.begin_indexing_session("camera", 120)

    async def stop(*args):
        assert state.get_indexing_policy("camera").session.state == "cancelled"
        return True, "Stopped"

    with (
        verified_source(),
        patch.object(control, "stop_source_indexing", new=AsyncMock(side_effect=stop)),
        patch.object(
            control, "_window_evidence", new=AsyncMock(return_value={"status": "unverified", "liveFresh": False})
        ),
    ):
        result = await endpoint(config, "POST")(
            "camera", control.IndexingActionRequest(name="Intersection", action="cancel")
        )
    assert result["state"] == "cancelled"
    assert not result["indexingRequested"]
    state.load_indexing_policies(force=True)
    assert not state.indexing_is_allowed("camera")


@pytest.mark.asyncio
async def test_cancel_continuous_indexing_disables_reconciliation(config):
    with verified_source(), patch.object(control, "stop_source_indexing", new=AsyncMock(return_value=(True, "OK"))):
        await endpoint(config, "POST")("camera", control.IndexingActionRequest(name="Intersection", action="cancel"))
    assert state.get_indexing_policy("camera").mode == "disabled"
    assert not state.indexing_is_allowed("camera")


@pytest.mark.asyncio
async def test_failed_stale_cleanup_does_not_start_a_new_window(config):
    city()
    with (
        verified_source(),
        patch.object(control, "stop_source_indexing", new=AsyncMock(return_value=(False, "Failed"))),
        patch.object(control, "add_to_rtvi_embed", new=AsyncMock()) as register,
    ):
        with pytest.raises(HTTPException) as error:
            await endpoint(config, "POST")("camera", control.IndexingActionRequest(name="Intersection", action="start"))
    assert error.value.status_code == 409
    assert state.get_indexing_policy("camera").session is None
    register.assert_not_awaited()


@pytest.mark.asyncio
async def test_deadline_stops_a_silent_sse_and_releases_both_resources(config):
    city()
    state.begin_indexing_session("camera", 30)
    state._policies["camera"].session.deadline_at = datetime.now(UTC) + timedelta(milliseconds=10)
    cancelled = asyncio.Event()

    async def silent_sse(_config, _stream, started):
        started.set_result((True, "OK"))
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    started = asyncio.get_running_loop().create_future()
    with (
        patch.object(rtsp_ingest, "_supervise_embedding_generation", side_effect=silent_sse),
        patch.object(
            rtsp_ingest, "cleanup_rtvi_embed_generation", new=AsyncMock(return_value=(True, "OK"))
        ) as generation,
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_stream", new=AsyncMock(return_value=(True, "OK"))) as resource,
    ):
        await asyncio.wait_for(rtsp_ingest._run_embedding_generation(config, "camera", started), timeout=1)
    assert cancelled.is_set()
    assert state.get_indexing_policy("camera").session.state == "completed"
    generation.assert_awaited_once()
    resource.assert_awaited_once()
    assert rtsp_ingest.embedding_cleanup_status("camera")[0] is True


@pytest.mark.asyncio
async def test_disabled_policy_never_spawns_an_embedding_task(config):
    state.set_indexing_mode("camera", "disabled")
    with patch.object(rtsp_ingest, "_run_embedding_generation", new=AsyncMock()) as generation:
        success, _ = await rtsp_ingest.start_embedding_generation(None, config, "camera")
    assert not success
    generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_generation_is_not_reported_before_remote_cleanup(config):
    city()
    state.begin_indexing_session("camera", 120)
    started = asyncio.get_running_loop().create_future()
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def refused(_config, _source, acknowledgement):
        acknowledgement.set_result((False, "HTTP 400"))

    async def stop_remote(*args):
        cleaning.set()
        await release.wait()
        return True, "Stopped"

    with (
        patch.object(rtsp_ingest, "_supervise_embedding_generation", side_effect=refused),
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_generation", new=AsyncMock(side_effect=stop_remote)),
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_stream", new=AsyncMock(return_value=(True, "OK"))),
    ):
        task = asyncio.create_task(rtsp_ingest._run_embedding_generation(config, "camera", started))
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not started.done()
        release.set()
        await asyncio.wait_for(task, 1)
    assert started.result() == (False, "HTTP 400")
    assert state.get_indexing_policy("camera").session.state == "failed"


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_abort_remote_cleanup(config):
    city()
    state.begin_indexing_session("camera", 120)
    started = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def silent(_config, _source, acknowledgement):
        acknowledgement.set_result((True, "OK"))
        entered.set()
        await asyncio.sleep(60)

    async def stop_remote(*args):
        cleaning.set()
        await release.wait()
        return True, "Stopped"

    with (
        patch.object(rtsp_ingest, "_supervise_embedding_generation", side_effect=silent),
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_generation", new=AsyncMock(side_effect=stop_remote)),
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_stream", new=AsyncMock(return_value=(True, "OK"))) as resource,
    ):
        task = asyncio.create_task(rtsp_ingest._run_embedding_generation(config, "camera", started))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 1)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    resource.assert_awaited_once()
    assert rtsp_ingest.embedding_cleanup_status("camera")[0] is True


@pytest.mark.asyncio
async def test_managed_stop_cancels_task_and_sends_both_remote_delete_requests(config):
    city()
    state.begin_indexing_session("camera", 120)
    entered = asyncio.Event()

    async def active():
        entered.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(active())
    rtsp_ingest._embedding_generation_tasks["camera"] = task
    await entered.wait()
    with (
        patch.object(
            rtsp_ingest, "cleanup_rtvi_embed_generation", new=AsyncMock(return_value=(True, "OK"))
        ) as generation,
        patch.object(rtsp_ingest, "cleanup_rtvi_embed_stream", new=AsyncMock(return_value=(True, "OK"))) as resource,
    ):
        success, _ = await rtsp_ingest.stop_source_indexing(AsyncMock(), config, "camera")
    assert task.cancelled()
    assert success
    assert state.get_indexing_policy("camera").session.state == "cancelled"
    generation.assert_awaited_once()
    resource.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_default_city_keeps_detection_but_stops_old_embeddings(config):
    city()
    with (
        patch.object(rtsp_ingest, "detector_endpoint_for_profile", return_value="http://city.test"),
        patch.object(rtsp_ingest, "_registered_cv_stream_ids", new=AsyncMock(return_value={"camera"})),
        patch.object(rtsp_ingest, "stop_source_indexing", new=AsyncMock(return_value=(True, "OK"))) as stop,
        patch.object(rtsp_ingest, "add_to_rtvi_embed", new=AsyncMock()) as register,
        patch.object(rtsp_ingest, "start_embedding_generation", new=AsyncMock()) as start,
    ):
        result = await rtsp_ingest._reconcile_live_source(
            AsyncMock(),
            config,
            "camera",
            "Intersection",
            "rtsp://source.test/live",
            {"http://city.test": {"camera"}},
            {"camera"},
            set(),
        )
    assert result["detection"] is True
    assert result["embedding"] is False
    stop.assert_awaited_once()
    register.assert_not_awaited()
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_city_analysis_status_can_be_healthy_without_live_indexing(config):
    city()
    router = create_source_control_router(config)
    status = next(
        route.endpoint for route in router.routes if route.path.endswith("/analysis") and "GET" in route.methods
    )
    with (
        patch(
            "vss_agents.api.source_control.get_live_analysis_runtime_steps",
            return_value={"detection": True, "embedding": False},
        ),
        patch("vss_agents.api.source_control.detector_endpoint_for_profile", return_value="http://city.test"),
        patch("vss_agents.api.source_control._semantic_index_is_fresh", new=AsyncMock()) as fresh,
    ):
        result = await status("camera")
    assert result.state == "active"
    assert result.analysis_active is True
    assert result.indexing_policy == "on-demand"
    assert result.indexing_required is False
    assert result.steps["embedding"] is False
    assert result.steps["indexing"] is False
    fresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_evidence_query_is_source_and_interval_scoped(config):
    client = AsyncMock()
    response = MagicMock()
    response.json.return_value = {
        "hits": {"total": {"value": 3}, "hits": [{"_source": {"timestamp": "2026-10-26T10:00:01Z"}}]}
    }
    client.post.return_value = response
    with patch.object(control.httpx, "AsyncClient") as factory:
        factory.return_value.__aenter__.return_value = client
        result = await control._window_evidence(
            config, "camera", "Intersection", "2026-10-26T10:00:00Z", "2026-10-26T10:02:00Z"
        )
    body = client.post.await_args.kwargs["json"]
    assert body["query"]["bool"]["filter"][1] == {
        "range": {"timestamp": {"gte": "2026-10-26T10:00:00Z", "lte": "2026-10-26T10:02:00Z"}}
    }
    assert body["query"]["bool"]["filter"][0]["bool"]["should"][0] == {
        "terms": {"sensor.id.keyword": ["Intersection", "camera"]}
    }
    assert result["documentCount"] == 3
    assert result["status"] == "indexed-window"


@pytest.mark.asyncio
async def test_live_indexing_rejects_recorded_source(config):
    set_source_kind("camera", "recorded")
    with verified_source(), pytest.raises(HTTPException) as error:
        await endpoint(config, "POST")("camera", control.IndexingActionRequest(name="Intersection", action="start"))
    assert error.value.status_code == 409


def test_booth_search_pins_the_selected_session_camera_and_interval():
    city()
    session = state.begin_indexing_session("camera", 120)
    state.mark_indexing_started("camera", session.id)
    # Simulate a window already collecting footage, without a wall-clock wait.
    state._policies["camera"].session.started_at -= timedelta(seconds=2)
    request = control.BoothSearchRequest(name="Intersection", sessionId=session.id, query="a bus stops", topK=6)
    prepared = control.build_booth_search_request("camera", request)
    assert prepared["endpoint"] == "/api/v1/embed_search"
    assert prepared["sessionId"] == session.id
    assert prepared["scope"]["executed"] is False
    params = prepared["request"]["params"]
    assert json.loads(params["exact_sensor_ids"]) == ["camera", "Intersection"]
    assert params["timestamp_start"] == prepared["scope"]["timestampStart"]
    assert params["timestamp_end"] == prepared["scope"]["timestampEnd"]
    assert params["query"] == "a bus stops"
    assert params["top_k"] == "6"


def test_stale_or_unacknowledged_search_session_cannot_be_substituted():
    city()
    session = state.begin_indexing_session("camera", 120)
    with pytest.raises(ValueError, match="no longer current"):
        control.build_booth_search_request(
            "camera", control.BoothSearchRequest(name="Intersection", sessionId="old", query="bus")
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        control.build_booth_search_request(
            "camera", control.BoothSearchRequest(name="Intersection", sessionId=session.id, query="bus")
        )


@pytest.mark.asyncio
async def test_failed_stop_is_retried_even_when_resource_inventory_is_empty(config):
    city()
    rtsp_ingest._embedding_cleanup_results["camera"] = (False, "Generation DELETE failed")
    with (
        patch.object(rtsp_ingest, "detector_endpoint_for_profile", return_value="http://city.test"),
        patch.object(rtsp_ingest, "_registered_cv_stream_ids", new=AsyncMock(return_value={"camera"})),
        patch.object(rtsp_ingest, "stop_source_indexing", new=AsyncMock(return_value=(True, "OK"))) as stop,
    ):
        result = await rtsp_ingest._reconcile_live_source(
            AsyncMock(),
            config,
            "camera",
            "Intersection",
            "rtsp://source.test/live",
            {"http://city.test": {"camera"}},
            set(),
            set(),
        )
    assert result["detection"] is True
    assert result["embedding"] is False
    stop.assert_awaited_once()
