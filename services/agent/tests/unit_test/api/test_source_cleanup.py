# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for exact, cross-partition generated-data cleanup."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api.source_cleanup import GENERATED_INDEX_PATTERNS
from vss_agents.api.source_cleanup import _source_identity_query
from vss_agents.api.source_cleanup import delete_generated_source_data
from vss_agents.api.source_cleanup import delete_lvs_graph_history


def test_source_identity_covers_legacy_media_name_without_extension():
    query = _source_identity_query(
        "sensor-123",
        "sample-sim-jaywalking.mp4",
        ("sensorId.keyword",),
    )

    values = [clause["term"]["sensorId.keyword"] for clause in query["bool"]["should"]]
    assert values == [
        "sensor-123",
        "sample-sim-jaywalking.mp4",
        "sample-sim-jaywalking",
    ]


@pytest.mark.asyncio
async def test_graph_cleanup_requires_exact_success_confirmation():
    client = MagicMock()
    client.delete = AsyncMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "deleted": True,
        "id": "sensor-123",
        "object": "qa_knowledge",
    }
    client.delete.return_value = response

    success, message = await delete_lvs_graph_history(
        client,
        "http://lvs:38111/",
        "sensor-123",
    )

    assert success is True
    assert message == "OK"
    client.delete.assert_awaited_once_with("http://lvs:38111/v1/qa/sensor-123")


@pytest.mark.asyncio
async def test_graph_cleanup_rejects_ambiguous_confirmation():
    client = MagicMock()
    client.delete = AsyncMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"deleted": True, "id": "another-source"}
    client.delete.return_value = response

    success, message = await delete_lvs_graph_history(
        client,
        "http://lvs:38111",
        "sensor-123",
    )

    assert success is False
    assert "invalid" in message.lower()


@pytest.mark.asyncio
async def test_cleanup_uses_exact_id_and_name_across_every_generated_index():
    client = MagicMock()
    client.delete_by_query = AsyncMock(
        side_effect=[
            {"deleted": count, "timed_out": False, "failures": [], "version_conflicts": 0}
            for count in range(1, len(GENERATED_INDEX_PATTERNS) + 1)
        ]
    )
    client.count = AsyncMock(
        side_effect=[
            item for count in range(1, len(GENERATED_INDEX_PATTERNS) + 1) for item in ({"count": count}, {"count": 0})
        ]
    )
    client.indices.exists = AsyncMock(return_value=False)
    client.close = AsyncMock()

    with patch("vss_agents.api.source_cleanup.AsyncElasticsearch", return_value=client):
        result = await delete_generated_source_data(
            "http://elasticsearch:9200",
            "sensor-123",
            "Camera Main",
        )

    assert result.success is True
    assert result.total_deleted == sum(range(1, len(GENERATED_INDEX_PATTERNS) + 1))
    assert [call.kwargs["index"] for call in client.delete_by_query.await_args_list] == list(
        GENERATED_INDEX_PATTERNS.values()
    )
    for call in client.delete_by_query.await_args_list:
        should = call.kwargs["body"]["query"]["bool"]["should"]
        terms = {(field, value) for clause in should for field, value in clause["term"].items()}
        assert any(value == "sensor-123" for _, value in terms)
        assert any(value == "Camera Main" for _, value in terms)
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_deletes_exact_source_caption_collection():
    client = MagicMock()
    client.delete_by_query = AsyncMock(
        return_value={"deleted": 0, "timed_out": False, "failures": [], "version_conflicts": 0}
    )
    client.indices.exists = AsyncMock(return_value=True)
    client.count = AsyncMock(
        side_effect=[
            *({"count": 0} for _ in GENERATED_INDEX_PATTERNS),
            {"count": 7},
        ]
    )
    client.indices.delete = AsyncMock(return_value={"acknowledged": True})
    client.close = AsyncMock()

    with patch("vss_agents.api.source_cleanup.AsyncElasticsearch", return_value=client):
        result = await delete_generated_source_data(
            "http://elasticsearch:9200",
            "A0000000-0000-4000-8000-000000000001",
            "Camera Main",
        )

    expected = "default_a0000000_0000_4000_8000_000000000001"
    client.indices.exists.assert_awaited_once_with(index=expected)
    client.indices.delete.assert_awaited_once_with(index=expected)
    assert result.deleted_collections == (expected,)
    assert result.deleted_documents["captions"] == 7


@pytest.mark.asyncio
async def test_cleanup_accepts_timeout_when_postcondition_proves_records_are_gone():
    """An Elasticsearch client timeout is not a failure if deletion completed."""
    client = MagicMock()
    client.count = AsyncMock(
        side_effect=[
            {"count": 4},
            {"count": 0},
            *({"count": 0} for _ in range(len(GENERATED_INDEX_PATTERNS) - 1)),
        ]
    )
    client.delete_by_query = AsyncMock(side_effect=TimeoutError("client timed out"))
    client.indices.exists = AsyncMock(return_value=False)
    client.close = AsyncMock()

    with patch("vss_agents.api.source_cleanup.AsyncElasticsearch", return_value=client):
        result = await delete_generated_source_data(
            "http://elasticsearch:9200",
            "sensor-123",
            "Camera Main",
        )

    assert result.success is True
    assert result.deleted_documents["embeddings"] == 4
    assert client.delete_by_query.await_count == 1


@pytest.mark.asyncio
async def test_cleanup_retries_when_exact_records_remain_after_first_delete():
    client = MagicMock()
    client.count = AsyncMock(
        side_effect=[
            {"count": 4},
            {"count": 2},
            {"count": 0},
            *({"count": 0} for _ in range(len(GENERATED_INDEX_PATTERNS) - 1)),
        ]
    )
    client.delete_by_query = AsyncMock(
        side_effect=[
            {"deleted": 2, "timed_out": False, "failures": [], "version_conflicts": 0},
            {"deleted": 2, "timed_out": False, "failures": [], "version_conflicts": 0},
        ]
    )
    client.indices.exists = AsyncMock(return_value=False)
    client.close = AsyncMock()

    with patch("vss_agents.api.source_cleanup.AsyncElasticsearch", return_value=client):
        result = await delete_generated_source_data(
            "http://elasticsearch:9200",
            "sensor-123",
            "Camera Main",
        )

    assert result.success is True
    assert result.deleted_documents["embeddings"] == 4
    assert client.delete_by_query.await_count == 2
