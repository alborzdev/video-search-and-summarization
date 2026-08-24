# SPDX-License-Identifier: MIT

from datetime import UTC
from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.source_analysis_state import _detection_disabled_sources
from vss_agents.api.source_analysis_state import _paused_sources
from vss_agents.api.source_analysis_state import _source_analysis_profiles
from vss_agents.api.source_analysis_state import _source_kinds
from vss_agents.api.source_analysis_state import get_source_analysis_profile
from vss_agents.api.source_analysis_state import get_source_kind
from vss_agents.api.source_analysis_state import is_source_detection_enabled
from vss_agents.api.source_analysis_state import load_source_analysis_state
from vss_agents.api.source_analysis_state import set_source_analysis_profile
from vss_agents.api.source_analysis_state import set_source_detection_enabled
from vss_agents.api.source_analysis_state import set_source_kind
from vss_agents.api.source_analysis_state import set_source_paused
from vss_agents.api.source_control import SourceAnalysisRequest
from vss_agents.api.source_control import _semantic_index_is_fresh
from vss_agents.api.source_control import create_source_control_router


@pytest.fixture(autouse=True)
def clear_paused_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("VSS_SOURCE_ANALYSIS_STATE_FILE", str(tmp_path / "source-analysis-state.json"))
    load_source_analysis_state(force=True)
    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()
    yield
    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()


def configured_router():
    return create_source_control_router(
        ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
    )


def test_paused_desired_state_survives_process_reload():
    set_source_paused("sensor-persisted", True)
    _paused_sources.clear()

    load_source_analysis_state(force=True)

    assert "sensor-persisted" in _paused_sources


def test_detector_choice_survives_process_reload():
    set_source_detection_enabled("traffic-camera", False)
    _detection_disabled_sources.clear()

    load_source_analysis_state(force=True)

    assert is_source_detection_enabled("traffic-camera") is False
    assert get_source_analysis_profile("traffic-camera") == "semantic-search"


def test_explicit_profile_survives_process_reload():
    from vss_agents.api.source_analysis_state import set_source_analysis_profile

    set_source_analysis_profile("intersection-camera", "traffic-monitoring")
    _source_analysis_profiles.clear()

    load_source_analysis_state(force=True)

    assert get_source_analysis_profile("intersection-camera") == "traffic-monitoring"
    assert is_source_detection_enabled("intersection-camera") is True


def test_source_kind_survives_process_reload():
    set_source_kind("recording-1", "recorded")
    _source_kinds.clear()

    load_source_analysis_state(force=True)

    assert get_source_kind("recording-1") == "recorded"


@pytest.mark.asyncio
async def test_index_freshness_resolves_vst_uuid_to_indexed_sensor_name():
    config = ServiceConfig(
        vst_internal_url="http://vst:30888",
        elasticsearch_url="http://elasticsearch:9200",
    )
    response = MagicMock()
    response.json.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                }
            ]
        }
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)

    with (
        patch(
            "vss_agents.api.source_control.vst_get_streams_info",
            new=AsyncMock(
                return_value={
                    "sensor-uuid": {
                        "name": "Preview_01_main",
                        "url": "rtsp://vst/live/sensor-uuid",
                    }
                }
            ),
        ),
        patch("vss_agents.api.source_control.httpx.AsyncClient", return_value=client),
    ):
        is_fresh = await _semantic_index_is_fresh(config, "sensor-uuid")

    assert is_fresh is True
    payload = client.post.await_args.kwargs["json"]
    identifiers = payload["query"]["bool"]["should"][0]["terms"]["info.sensorId.keyword"]
    assert identifiers == ["Preview_01_main", "sensor-uuid"]


@pytest.mark.asyncio
async def test_pause_then_status_reports_actual_desired_state():
    router = configured_router()
    status_endpoint = router.routes[0].endpoint
    control_endpoint = router.routes[1].endpoint
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("vss_agents.api.source_control.httpx.AsyncClient", return_value=client),
        patch(
            "vss_agents.api.source_control.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "sensor-1", "rtsp://vst/live")),
        ),
        patch("vss_agents.api.source_control.stop_managed_embedding_generation", new=AsyncMock()),
        patch("vss_agents.api.source_control.cleanup_rtvi_embed_generation", new=AsyncMock(return_value=(True, "OK"))),
        patch(
            "vss_agents.api.source_control.cleanup_source_from_all_rtvi_cv",
            new=AsyncMock(return_value=(True, "OK")),
        ),
    ):
        result = await control_endpoint("sensor-1", SourceAnalysisRequest(action="pause", name="Camera 1"))

    assert result.state == "paused"
    assert result.analysis_active is False
    status = await status_endpoint("sensor-1")
    assert status.state == "paused"


@pytest.mark.asyncio
async def test_resume_reports_partial_but_persists_desired_active_for_recovery():
    router = configured_router()
    control_endpoint = router.routes[1].endpoint
    _paused_sources.add("sensor-1")
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("vss_agents.api.source_control.httpx.AsyncClient", return_value=client),
        patch(
            "vss_agents.api.source_control.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "sensor-1", "rtsp://vst/live")),
        ),
        patch(
            "vss_agents.api.source_control.reconcile_live_source_now",
            new=AsyncMock(
                return_value={
                    "detection": False,
                    "embedding_resource": True,
                    "embedding": True,
                    "caption_resource": True,
                }
            ),
        ),
    ):
        result = await control_endpoint("sensor-1", SourceAnalysisRequest(action="resume", name="Camera 1"))

    assert result.state == "partial"
    assert result.analysis_active is False
    assert "sensor-1" not in _paused_sources


@pytest.mark.asyncio
async def test_status_is_partial_until_runtime_is_proved_active():
    router = configured_router()
    status_endpoint = router.routes[0].endpoint

    with patch(
        "vss_agents.api.source_control.get_live_analysis_runtime_steps",
        return_value={},
    ):
        status = await status_endpoint("sensor-1")

    assert status.state == "partial"
    assert status.analysis_active is False
    assert "recovering" in status.message


@pytest.mark.asyncio
async def test_status_is_active_only_with_detection_and_connected_embedding():
    router = configured_router()
    status_endpoint = router.routes[0].endpoint

    with patch(
        "vss_agents.api.source_control.get_live_analysis_runtime_steps",
        return_value={
            "detection": True,
            "embedding_resource": True,
            "embedding": True,
            "caption_resource": True,
        },
    ):
        status = await status_endpoint("sensor-1")

    assert status.state == "active"
    assert status.analysis_active is True
    assert status.steps["indexing"] is True


@pytest.mark.asyncio
async def test_general_scene_is_active_without_warehouse_detector():
    router = configured_router()
    status_endpoint = router.routes[0].endpoint
    set_source_detection_enabled("traffic-camera", False)

    with patch(
        "vss_agents.api.source_control.get_live_analysis_runtime_steps",
        return_value={
            "detection": False,
            "embedding_resource": True,
            "embedding": True,
            "caption_resource": True,
        },
    ):
        status = await status_endpoint("traffic-camera")

    assert status.state == "active"
    assert status.analysis_active is True
    assert status.detection_enabled is False


@pytest.mark.asyncio
async def test_configure_general_scene_reconciles_the_selected_profile():
    router = configured_router()
    control_endpoint = router.routes[1].endpoint
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("vss_agents.api.source_control.httpx.AsyncClient", return_value=client),
        patch(
            "vss_agents.api.source_control.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "sensor-1", "rtsp://vst/live")),
        ),
        patch(
            "vss_agents.api.source_control.reconcile_live_source_now",
            new=AsyncMock(
                return_value={"detection": False, "embedding": True, "embedding_resource": True}
            ),
        ) as reconcile,
    ):
        result = await control_endpoint(
            "sensor-1",
            SourceAnalysisRequest(
                action="configure",
                name="Camera 1",
                detectionEnabled=False,
            ),
        )

    assert result.state == "active"
    assert result.analysis_active is True
    assert result.detection_enabled is False
    assert result.steps["detection"] is False
    reconcile.assert_awaited_once()
    assert reconcile.await_args.args[1:] == (
        "sensor-1",
        "Camera 1",
        "rtsp://vst/live",
    )


@pytest.mark.asyncio
async def test_configure_rejects_a_finite_profile_already_assigned_to_another_source(monkeypatch):
    monkeypatch.setenv("VSS_TRAFFIC_RTVI_CV_URL", "http://traffic:9010")
    set_source_analysis_profile("intersection-a", "traffic-monitoring")
    control_endpoint = configured_router().routes[1].endpoint

    with (
        patch(
            "vss_agents.api.source_control.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "intersection-b", "rtsp://vst/live/intersection-b")),
        ),
        patch("vss_agents.api.source_control.reconcile_live_source_now", new=AsyncMock()) as reconcile,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await control_endpoint(
                "intersection-b",
                SourceAnalysisRequest(
                    action="configure",
                    name="Intersection B",
                    analysisProfileId="traffic-monitoring",
                ),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "analysis_profile_capacity_exhausted"
    assert exc_info.value.detail["occupiedSourceIds"] == ["intersection-a"]
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_is_partial_when_embeddings_are_not_reaching_search():
    router = configured_router()
    status_endpoint = router.routes[0].endpoint

    with (
        patch(
            "vss_agents.api.source_control.get_live_analysis_runtime_steps",
            return_value={
                "detection": True,
                "embedding_resource": True,
                "embedding": True,
                "caption_resource": True,
            },
        ),
        patch(
            "vss_agents.api.source_control._semantic_index_is_fresh",
            new=AsyncMock(return_value=False),
        ),
    ):
        status = await status_endpoint("sensor-1")

    assert status.state == "partial"
    assert status.analysis_active is False
    assert status.steps["indexing"] is False
