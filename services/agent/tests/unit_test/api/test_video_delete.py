# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for idempotent uploaded-video cleanup."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.api.video_delete import _delete_es_documents


@pytest.mark.asyncio
async def test_missing_optional_es_index_is_successful_noop():
    """Profiles may legitimately omit behavior/raw indexes."""

    class MissingIndex(Exception):
        pass

    client = MagicMock()
    client.delete_by_query = AsyncMock(side_effect=MissingIndex("missing"))
    client.close = AsyncMock()

    with (
        patch("vss_agents.api.video_delete.AsyncElasticsearch", return_value=client),
        patch("vss_agents.api.video_delete.NotFoundError", MissingIndex),
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
