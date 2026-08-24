# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for resetting a live source without removing its VST registration."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.source_cleanup import GeneratedDataCleanup
from vss_agents.api.source_reset import ResetLiveSourceRequest
from vss_agents.api.source_reset import create_source_reset_router


@pytest.mark.asyncio
async def test_live_reset_pauses_cleans_storage_and_resumes_analysis():
    config = ServiceConfig(
        vst_internal_url="http://vst:30888",
        rtvi_cv_base_url="http://rtvi-cv:9000",
        rtvi_embed_base_url="http://rtvi-embed:8017",
        rtvi_vlm_base_url="http://rtvi-vlm:8018",
        elasticsearch_url="http://elasticsearch:9200",
        lvs_backend_url="http://lvs:38111",
    )
    router = create_source_reset_router(config)
    endpoint = router.routes[0].endpoint
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    cleanup = GeneratedDataCleanup(
        deleted_documents={"embeddings": 12, "detections": 80},
        deleted_collections=(),
        failures={},
    )

    with (
        patch("vss_agents.api.source_reset.httpx.AsyncClient", return_value=client),
        patch(
            "vss_agents.api.source_reset.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "sensor-123", "rtsp://proxy/live")),
        ),
        patch("vss_agents.api.source_reset.stop_managed_embedding_generation", new=AsyncMock()) as stop,
        patch(
            "vss_agents.api.source_reset.cleanup_rtvi_embed_generation",
            new=AsyncMock(return_value=(True, "OK")),
        ),
        patch(
            "vss_agents.api.source_reset.cleanup_source_from_all_rtvi_cv",
            new=AsyncMock(return_value=(True, "OK")),
        ),
        patch(
            "vss_agents.api.source_reset.cleanup_rtvi_vlm_stream",
            new=AsyncMock(return_value=(True, "OK")),
        ),
        patch(
            "vss_agents.api.source_reset.delete_generated_source_data",
            new=AsyncMock(return_value=cleanup),
        ) as delete_generated,
        patch(
            "vss_agents.api.source_reset.delete_lvs_graph_history",
            new=AsyncMock(return_value=(True, "OK")),
        ) as delete_graph,
        patch("vss_agents.api.source_reset.cleanup_vst_storage", new=AsyncMock(return_value=(True, "OK"))),
        patch(
            "vss_agents.api.source_reset.add_to_rtvi_vlm",
            new=AsyncMock(return_value=(True, "OK", "sensor-123")),
        ),
        patch("vss_agents.api.source_reset.add_to_rtvi_cv", new=AsyncMock(return_value=(True, "OK"))),
        patch(
            "vss_agents.api.source_reset.start_embedding_generation",
            new=AsyncMock(return_value=(True, "OK")),
        ) as start,
    ):
        result = await endpoint(
            stream_id="sensor-123",
            request=ResetLiveSourceRequest(name="Camera Main", clearRecordings=True),
        )

    assert result.status == "success"
    assert result.deleted_documents == 92
    assert result.recordings_cleared is True
    assert result.analysis_resumed is True
    stop.assert_awaited_once_with("sensor-123")
    delete_generated.assert_awaited_once_with(
        "http://elasticsearch:9200",
        "sensor-123",
        "Camera Main",
    )
    delete_graph.assert_awaited_once_with(client, "http://lvs:38111", "sensor-123")
    start.assert_awaited_once_with(None, config, "sensor-123")


@pytest.mark.asyncio
async def test_live_reset_rejects_name_id_mismatch_without_deleting_data():
    config = ServiceConfig(
        vst_internal_url="http://vst:30888",
        elasticsearch_url="http://elasticsearch:9200",
    )
    endpoint = create_source_reset_router(config).routes[0].endpoint

    with (
        patch(
            "vss_agents.api.source_reset.get_stream_info_by_name",
            new=AsyncMock(return_value=(True, "OK", "different-sensor", "rtsp://proxy/live")),
        ),
        patch("vss_agents.api.source_reset.delete_generated_source_data", new=AsyncMock()) as delete_generated,
    ):
        result = await endpoint(
            stream_id="sensor-123",
            request=ResetLiveSourceRequest(name="Camera Main"),
        )

    assert result.status == "failure"
    delete_generated.assert_not_awaited()
