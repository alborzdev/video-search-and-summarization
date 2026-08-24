# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for idempotent uploaded-video cleanup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api.source_cleanup import GeneratedDataCleanup
from vss_agents.api.video_delete import EsCleanupConfig
from vss_agents.api.video_delete import _delete_es_documents
from vss_agents.api.video_delete import _remove_from_rtvi_cv
from vss_agents.api.video_delete import create_video_delete_router
from vss_agents.api.video_delete import register_video_delete_routes
from vss_agents.tools.vst.utils import VSTError


@pytest.mark.asyncio
async def test_missing_optional_es_index_is_successful_noop():
    """Profiles may legitimately omit behavior/raw indexes."""

    class MissingIndexError(Exception):
        pass

    client = MagicMock()
    client.delete_by_query = AsyncMock(side_effect=MissingIndexError("missing"))
    client.close = AsyncMock()

    with (
        patch("vss_agents.api.video_delete.AsyncElasticsearch", return_value=client),
        patch("vss_agents.api.video_delete.NotFoundError", MissingIndexError),
    ):
        success, message = await _delete_es_documents(
            "http://elasticsearch:9200",
            "mdx-behavior-2025-01-01",
            "camera-1",
            "sensor.id.keyword",
        )

    assert success is True
    assert message == "Index not present"
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"deleted": 1, "timed_out": True, "failures": [], "version_conflicts": 0},
        {"deleted": 1, "timed_out": False, "failures": [{"cause": "boom"}], "version_conflicts": 0},
        {"deleted": 1, "timed_out": False, "failures": [], "version_conflicts": 1},
        {},
        {"deleted": 1, "timed_out": False, "failures": {}, "version_conflicts": 0},
        {"deleted": 1, "timed_out": False, "failures": [], "version_conflicts": False},
        {"deleted": -1, "timed_out": False, "failures": [], "version_conflicts": 0},
        {"deleted": True, "timed_out": False, "failures": [], "version_conflicts": 0},
    ],
)
async def test_incomplete_delete_by_query_result_fails_closed(result):
    client = MagicMock()
    client.delete_by_query = AsyncMock(return_value=result)
    client.close = AsyncMock()

    with patch("vss_agents.api.video_delete.AsyncElasticsearch", return_value=client):
        success, message = await _delete_es_documents(
            "http://elasticsearch:9200",
            "mdx-embed-filtered-2025-01-01",
            "sensor-1",
            "sensor.id.keyword",
        )

    assert success is False
    assert message.startswith("Delete incomplete:")
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_delete_by_query_result_is_successful():
    client = MagicMock()
    client.delete_by_query = AsyncMock(
        return_value={"deleted": 0, "timed_out": False, "failures": [], "version_conflicts": 0}
    )
    client.close = AsyncMock()

    with patch("vss_agents.api.video_delete.AsyncElasticsearch", return_value=client):
        success, message = await _delete_es_documents(
            "http://elasticsearch:9200",
            "mdx-embed-filtered-2025-01-01",
            "sensor-1",
            "sensor.id.keyword",
        )

    assert success is True
    assert message == "Deleted 0 documents"
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_rtvi_cv_remove_uses_stream_affinity_header():
    inventory_response = MagicMock()
    inventory_response.json.return_value = {
        "stream-info": {
            "stream-count": 1,
            "stream-info": [{"camera_id": "00000000-0000-4000-8000-000000000001"}],
        }
    }
    response = MagicMock(status_code=204)
    client = MagicMock()
    client.get = AsyncMock(return_value=inventory_response)
    client.post = AsyncMock(return_value=response)

    success, message = await _remove_from_rtvi_cv(
        client,
        "http://rtvi-cv:9000",
        "00000000-0000-4000-8000-000000000001",
        "owned-clip",
    )

    assert success is True
    assert message == "OK"
    assert client.post.await_args.kwargs["headers"] == {"x-stream-id": "00000000-0000-4000-8000-000000000001"}


@pytest.mark.asyncio
async def test_rtvi_cv_remove_treats_affinity_scoped_absence_as_success():
    inventory_response = MagicMock()
    inventory_response.raise_for_status.side_effect = RuntimeError("inventory unavailable")
    response = MagicMock(status_code=404)
    client = MagicMock()
    client.get = AsyncMock(return_value=inventory_response)
    client.post = AsyncMock(return_value=response)

    success, message = await _remove_from_rtvi_cv(client, "http://rtvi-cv:9000", "sensor-1", "owned-clip")

    assert success is True
    assert message == "Already absent"


@pytest.mark.asyncio
async def test_rtvi_cv_remove_skips_unknown_id_in_authoritative_inventory():
    inventory_response = MagicMock()
    inventory_response.json.return_value = {
        "stream-info": {
            "stream-count": 1,
            "stream-info": [{"camera_id": "unrelated-live-camera"}],
        }
    }
    client = MagicMock()
    client.get = AsyncMock(return_value=inventory_response)
    client.post = AsyncMock()

    success, message = await _remove_from_rtvi_cv(
        client,
        "http://rtvi-cv:9000",
        "recorded-source",
        "recorded-clip",
    )

    assert success is True
    assert message == "Already absent"
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_es_identity_lookup_failure_cannot_report_delete_success():
    router = create_video_delete_router(
        vst_internal_url="http://vst:30888",
        es_config=EsCleanupConfig(url="http://elasticsearch:9200"),
    )
    endpoint = router.routes[0].endpoint
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("vss_agents.api.video_delete.httpx.AsyncClient", return_value=client),
        patch(
            "vss_agents.api.video_delete.get_sensor_id_from_stream_id",
            new=AsyncMock(side_effect=VSTError("missing")),
        ),
        patch(
            "vss_agents.api.video_delete.delete_generated_source_data",
            new=AsyncMock(
                return_value=GeneratedDataCleanup(
                    deleted_documents={},
                    deleted_collections=(),
                    failures={},
                )
            ),
        ),
        patch(
            "vss_agents.api.video_delete.delete_vst_storage",
            new=AsyncMock(return_value=(True, "OK")),
        ),
        patch(
            "vss_agents.api.video_delete.delete_vst_sensor",
            new=AsyncMock(return_value=(True, "OK")),
        ),
    ):
        result = await endpoint("00000000-0000-4000-8000-000000000001")

    assert result.status == "partial"


def test_registration_uses_configured_embedding_index_for_cleanup():
    streaming = SimpleNamespace(
        vst_internal_url="http://vst:30888",
        elasticsearch_url="http://elasticsearch:9200",
        rtvi_cv_base_url="",
        rtvi_embed_es_index="owned-embed-index",
    )
    config = SimpleNamespace(general=SimpleNamespace(front_end=SimpleNamespace(streaming_ingest=streaming)))
    app = MagicMock()
    router = MagicMock()

    with patch("vss_agents.api.video_delete.create_video_delete_router", return_value=router) as create_router:
        register_video_delete_routes(app, config)

    assert create_router.call_args.kwargs["es_config"].embed_index == "owned-embed-index"
    app.include_router.assert_called_once_with(router)
