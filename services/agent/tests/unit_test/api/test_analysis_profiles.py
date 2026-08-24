# SPDX-License-Identifier: MIT

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api.analysis_profiles import ANALYSIS_PROFILES
from vss_agents.api.analysis_profiles import SEMANTIC_PROFILE_ID
from vss_agents.api.analysis_profiles import TRAFFIC_PROFILE_ID
from vss_agents.api.analysis_profiles import WAREHOUSE_PROFILE_ID
from vss_agents.api.analysis_profiles import _local_profile_recommendation
from vss_agents.api.analysis_profiles import _nemotron_profile_recommendation
from vss_agents.api.analysis_profiles import create_analysis_profiles_router


def test_catalog_exposes_only_concrete_vss_profiles():
    assert [profile.id for profile in ANALYSIS_PROFILES] == [
        SEMANTIC_PROFILE_ID,
        WAREHOUSE_PROFILE_ID,
        TRAFFIC_PROFILE_ID,
    ]
    warehouse = ANALYSIS_PROFILES[1]
    traffic = ANALYSIS_PROFILES[2]
    assert {"Person", "Forklift", "Pallet"}.issubset(warehouse.object_types)
    assert {"Bicycle", "Car", "Person", "Road sign"}.issubset(traffic.object_types)
    assert traffic.max_sources == 1


@pytest.mark.parametrize(
    ("source_name", "intent", "expected"),
    [
        ("WH1 Loading Dock", "alert when a forklift approaches a person", WAREHOUSE_PROFILE_ID),
        ("Main Intersection", "watch cars and pedestrian crossings", TRAFFIC_PROFILE_ID),
        ("Camera 4", "make the footage searchable", SEMANTIC_PROFILE_ID),
    ],
)
def test_local_recommendation_is_safe_and_scene_aware(source_name, intent, expected):
    profile_id, confidence, reason = _local_profile_recommendation(source_name, intent)
    assert profile_id == expected
    assert 0 <= confidence <= 1
    assert reason


@pytest.mark.asyncio
async def test_nemotron_recommendation_accepts_only_manifest_tool_calls(monkeypatch):
    monkeypatch.setenv("VSS_ANALYSIS_PLANNER_ENABLED", "true")
    monkeypatch.setenv("VSS_ANALYSIS_PLANNER_BASE_URL", "http://planner:30081/v1")
    response = MagicMock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "traffic_monitoring",
                                "arguments": '{"confidence": 0.94, "reason": "Road scene with cars"}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)

    with patch("vss_agents.api.analysis_profiles.httpx.AsyncClient", return_value=client):
        recommendation = await _nemotron_profile_recommendation(
            "Intersection 1",
            "Detect cars entering the crossing",
        )

    assert recommendation == (TRAFFIC_PROFILE_ID, 0.94, "Road scene with cars")
    payload = client.post.await_args.kwargs["json"]
    assert {tool["function"]["name"] for tool in payload["tools"]} == {
        "semantic_search",
        "warehouse_safety",
        "traffic_monitoring",
    }


@pytest.mark.asyncio
async def test_catalog_readiness_reflects_real_workers(monkeypatch):
    monkeypatch.setenv("VSS_TRAFFIC_RTVI_CV_URL", "http://traffic:9010")
    response = MagicMock()
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=[response, response])
    router = create_analysis_profiles_router("http://warehouse:9000")

    with patch("vss_agents.api.analysis_profiles.httpx.AsyncClient", return_value=client):
        result = await router.routes[0].endpoint()

    assert [profile.ready for profile in result.profiles] == [True, True, True]
    assert client.get.await_args_list[0].args[0].startswith("http://warehouse:9000/")
    assert client.get.await_args_list[1].args[0].startswith("http://traffic:9010/")


@pytest.mark.asyncio
async def test_source_profile_endpoint_returns_durable_selected_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("VSS_SOURCE_ANALYSIS_STATE_FILE", str(tmp_path / "analysis-state.json"))
    monkeypatch.setenv("VSS_TRAFFIC_RTVI_CV_URL", "http://traffic:9010")
    from vss_agents.api.source_analysis_state import load_source_analysis_state
    from vss_agents.api.source_analysis_state import set_source_analysis_profile

    load_source_analysis_state(force=True)
    set_source_analysis_profile("intersection-1", TRAFFIC_PROFILE_ID)
    response = MagicMock()
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    router = create_analysis_profiles_router("http://warehouse:9000")

    with patch("vss_agents.api.analysis_profiles.httpx.AsyncClient", return_value=client):
        result = await router.routes[1].endpoint("intersection-1")

    assert result.source_id == "intersection-1"
    assert result.profile_id == TRAFFIC_PROFILE_ID
    assert result.profile.object_types == ["Bicycle", "Car", "Person", "Road sign"]
