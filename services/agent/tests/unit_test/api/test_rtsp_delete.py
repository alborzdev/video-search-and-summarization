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
"""Unit tests for rtsp_delete module.

Covers ``DELETE /api/v1/rtsp-streams/delete/{name}``. The shared VST / RTVI
helpers and ``ServiceConfig`` are tested in ``test_rtsp_ingest.py`` since they
live in ``vss_agents.api.rtsp_ingest``.
"""

from unittest.mock import ANY
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

import pytest

from vss_agents.api.rtsp_delete import DeleteStreamResponse
from vss_agents.api.rtsp_delete import create_rtsp_delete_router
from vss_agents.api.rtsp_delete import register_rtsp_delete_routes
from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.source_cleanup import GeneratedDataCleanup


class TestDeleteStreamResponse:
    """Test DeleteStreamResponse model."""

    def test_response_creation(self):
        response = DeleteStreamResponse(
            status="success",
            message="Stream deleted",
            name="camera-1",
            sensorId="sensor-123",
        )
        assert response.status == "success"
        assert response.name == "camera-1"
        assert response.sensor_id == "sensor-123"

    def test_response_partial_status(self):
        response = DeleteStreamResponse(
            status="partial",
            message="Partially deleted",
            name="camera-1",
            sensorId="sensor-123",
        )
        assert response.status == "partial"

    def test_non_failure_response_requires_stable_identity(self):
        with pytest.raises(ValueError, match="requires sensorId"):
            DeleteStreamResponse(status="success", message="Stream deleted", name="camera-1")


class TestCreateRtspDeleteRouter:
    """Test create_rtsp_delete_router function."""

    def test_create_router(self):
        router = create_rtsp_delete_router(ServiceConfig(vst_internal_url="http://vst:30888"))
        assert router is not None

    def test_router_has_one_route(self):
        router = create_rtsp_delete_router(ServiceConfig(vst_internal_url="http://vst:30888"))
        # delete-only — the add route lives in rtsp_ingest.
        assert len(router.routes) == 1


class TestDeleteStreamEndpoint:
    """Test delete_stream endpoint."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.cleanup_source_from_all_rtvi_cv")
    @patch("vss_agents.api.rtsp_delete.cleanup_rtvi_embed_stream")
    @patch("vss_agents.api.rtsp_delete.cleanup_rtvi_embed_generation")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.httpx.AsyncClient")
    async def test_successful_delete_with_full_rtvi(
        self,
        mock_client_class,
        mock_get_stream_info,
        mock_cleanup_embed_gen,
        mock_cleanup_embed_stream,
        mock_cleanup_all_cv,
        mock_cleanup_vst_sensor,
    ):
        """Successful delete when RTVI is fully configured (search-style)."""
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
                delete_vst_storage_on_stream_remove=False,
            )
        )

        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_cleanup_embed_gen.return_value = (True, "OK")
        mock_cleanup_embed_stream.return_value = (True, "OK")
        mock_cleanup_all_cv.return_value = (True, "OK")
        mock_cleanup_vst_sensor.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(name="camera-1")

        assert response.status == "success"
        assert response.name == "camera-1"
        assert response.sensor_id == "sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.cleanup_rtvi_vlm_stream")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.httpx.AsyncClient")
    async def test_delete_calls_rtvi_vlm_cleanup_when_only_vlm_configured(
        self,
        mock_client_class,
        mock_get_stream_info,
        mock_cleanup_rtvi_vlm,
        mock_cleanup_vst_sensor,
    ):
        """rtvi-vlm cleanup must run whenever ``rtvi_vlm_url`` is configured."""
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
                delete_vst_storage_on_stream_remove=False,
            )
        )

        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_cleanup_rtvi_vlm.return_value = (True, "OK")
        mock_cleanup_vst_sensor.return_value = (True, "OK")

        await router.routes[0].endpoint(name="camera-1")

        mock_cleanup_rtvi_vlm.assert_awaited_once_with(mock_client, ANY, "sensor-123")

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_storage")
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    async def test_delete_stream_not_found(
        self,
        mock_get_stream_info,
        _mock_cleanup_vst_sensor,
        _mock_cleanup_vst_storage,
    ):
        """Test deletion when stream is not found.

        The cleanup_* helpers are patched out so even if the endpoint
        accidentally invokes them after the lookup failure they don't hit the
        network; the only behavior under test is that the endpoint returns a
        failure response when ``get_stream_info_by_name`` says the stream
        doesn't exist.
        """
        router = create_rtsp_delete_router(ServiceConfig(vst_internal_url="http://vst:30888"))

        mock_get_stream_info.return_value = (False, "Stream not found", None, None)

        endpoint = router.routes[0].endpoint
        response = await endpoint(name="nonexistent-camera")

        assert response.status == "failure"
        assert "not found" in response.message.lower() or "Failed to find" in response.message

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.cleanup_source_from_all_rtvi_cv")
    @patch("vss_agents.api.rtsp_delete.cleanup_rtvi_embed_stream")
    @patch("vss_agents.api.rtsp_delete.cleanup_rtvi_embed_generation")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.httpx.AsyncClient")
    async def test_partial_delete(
        self,
        mock_client_class,
        mock_get_stream_info,
        mock_cleanup_embed_gen,
        mock_cleanup_embed_stream,
        mock_cleanup_all_cv,
        mock_cleanup_vst_sensor,
    ):
        """Partial deletion when some services fail."""
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
                delete_vst_storage_on_stream_remove=False,
            )
        )

        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_cleanup_embed_gen.return_value = (True, "OK")
        mock_cleanup_embed_stream.return_value = (False, "Error")
        mock_cleanup_all_cv.return_value = (True, "OK")
        mock_cleanup_vst_sensor.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(name="camera-1")

        assert response.status == "partial"
        assert response.sensor_id == "sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.delete_generated_source_data")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    async def test_delete_cascades_generated_data_across_all_partitions(
        self,
        mock_get_stream_info,
        mock_delete_generated,
        mock_cleanup_vst_sensor,
    ):
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                elasticsearch_url="http://elasticsearch:9200",
                delete_vst_storage_on_stream_remove=False,
            )
        )
        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst/live")
        mock_delete_generated.return_value = GeneratedDataCleanup(
            deleted_documents={"embeddings": 5, "detections": 20},
            deleted_collections=(),
            failures={},
        )
        mock_cleanup_vst_sensor.return_value = (True, "OK")

        response = await router.routes[0].endpoint(name="camera-1")

        assert response.status == "success"
        assert response.generated_data_deleted == 25
        mock_delete_generated.assert_awaited_once_with(
            "http://elasticsearch:9200",
            "sensor-123",
            "camera-1",
        )

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.delete_lvs_graph_history")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.httpx.AsyncClient")
    async def test_delete_cascades_graph_history(
        self,
        mock_client_class,
        mock_get_stream_info,
        mock_delete_graph,
        mock_cleanup_vst_sensor,
    ):
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                lvs_backend_url="http://lvs:38111",
                delete_vst_storage_on_stream_remove=False,
            )
        )
        client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst/live")
        mock_delete_graph.return_value = (True, "OK")
        mock_cleanup_vst_sensor.return_value = (True, "OK")

        response = await router.routes[0].endpoint(name="camera-1")

        assert response.status == "success"
        mock_delete_graph.assert_awaited_once_with(client, "http://lvs:38111", "sensor-123")

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.set_source_deleting")
    async def test_delete_blocks_reconciliation_until_teardown_finishes(
        self,
        mock_set_source_deleting,
        mock_get_stream_info,
        mock_cleanup_vst_sensor,
    ):
        """The reconciler must see a tombstone for the entire destructive window."""
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                delete_vst_storage_on_stream_remove=False,
            )
        )
        events: list[tuple[str, bool]] = []
        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst/live")
        mock_set_source_deleting.side_effect = lambda _stream_id, deleting: events.append(("deleting", deleting))

        async def cleanup_sensor(_config, _stream_id):
            events.append(("cleanup", True))
            return True, "OK"

        mock_cleanup_vst_sensor.side_effect = cleanup_sensor

        response = await router.routes[0].endpoint(name="camera-1")

        assert response.status == "success"
        assert events == [
            ("deleting", True),
            ("cleanup", True),
            ("deleting", False),
        ]
        mock_set_source_deleting.assert_has_calls([call("sensor-123", True), call("sensor-123", False)])

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_delete.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_delete.get_stream_info_by_name")
    @patch("vss_agents.api.rtsp_delete.set_source_deleting")
    async def test_delete_clears_reconciliation_tombstone_after_unexpected_error(
        self,
        mock_set_source_deleting,
        mock_get_stream_info,
        mock_cleanup_vst_sensor,
    ):
        router = create_rtsp_delete_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                delete_vst_storage_on_stream_remove=False,
            )
        )
        mock_get_stream_info.return_value = (True, "OK", "sensor-123", "rtsp://vst/live")
        mock_cleanup_vst_sensor.side_effect = RuntimeError("unexpected cleanup failure")

        with pytest.raises(RuntimeError, match="unexpected cleanup failure"):
            await router.routes[0].endpoint(name="camera-1")

        mock_set_source_deleting.assert_has_calls([call("sensor-123", True), call("sensor-123", False)])


class TestRegisterRtspDeleteRoutes:
    """Test register_rtsp_delete_routes function."""

    def test_register_with_full_rtvi_config(self):
        """search-style: VST + RTVI-CV + RTVI-embed all configured."""
        mock_app = MagicMock()
        mock_config = MagicMock()
        mock_streaming_config = MagicMock()
        mock_streaming_config.vst_internal_url = "http://vst:30888"
        mock_streaming_config.rtvi_cv_base_url = "http://rtvi-cv:9000"
        mock_streaming_config.rtvi_embed_base_url = "http://rtvi-embed:8017"
        mock_streaming_config.rtvi_vlm_base_url = "http://rtvi-vlm:8018"
        mock_streaming_config.rtvi_embed_model = "test-model"
        mock_streaming_config.rtvi_embed_chunk_duration = 10
        mock_streaming_config.delete_vst_storage_on_stream_remove = False
        mock_config.general.front_end.streaming_ingest = mock_streaming_config

        register_rtsp_delete_routes(mock_app, mock_config)

        assert mock_app.include_router.called

    def test_register_vst_only_no_rtvi_urls(self):
        """alerts/base-style: only VST configured, no RTVI URLs.

        Empty RTVI URLs mean the corresponding cleanup steps self-skip at
        request time. Registration must succeed.
        """
        mock_app = MagicMock()
        mock_config = MagicMock()
        mock_streaming_config = MagicMock()
        mock_streaming_config.vst_internal_url = "http://vst:30888"
        mock_streaming_config.rtvi_cv_base_url = ""
        mock_streaming_config.rtvi_embed_base_url = ""
        mock_streaming_config.rtvi_embed_model = "cosmos-embed1-448p"
        mock_streaming_config.rtvi_embed_chunk_duration = 5
        mock_streaming_config.delete_vst_storage_on_stream_remove = True
        mock_config.general.front_end.streaming_ingest = mock_streaming_config

        register_rtsp_delete_routes(mock_app, mock_config)

        assert mock_app.include_router.called

    def test_register_missing_streaming_ingest_raises(self):
        """Without streaming_ingest configured, registration must fail loudly."""
        mock_app = MagicMock()
        mock_config = MagicMock()
        mock_config.general.front_end = MagicMock(spec=[])

        with pytest.raises(ValueError, match="streaming_ingest"):
            register_rtsp_delete_routes(mock_app, mock_config)

    def test_register_missing_vst_url_raises(self):
        """streaming_ingest present but vst_internal_url empty must raise."""
        mock_app = MagicMock()
        mock_config = MagicMock()
        mock_streaming_config = MagicMock()
        mock_streaming_config.vst_internal_url = ""
        mock_streaming_config.rtvi_cv_base_url = ""
        mock_streaming_config.rtvi_embed_base_url = ""
        mock_streaming_config.rtvi_embed_model = "cosmos-embed1-448p"
        mock_streaming_config.rtvi_embed_chunk_duration = 5
        mock_streaming_config.delete_vst_storage_on_stream_remove = True
        mock_config.general.front_end.streaming_ingest = mock_streaming_config

        with pytest.raises(ValueError, match="vst_internal_url"):
            register_rtsp_delete_routes(mock_app, mock_config)
