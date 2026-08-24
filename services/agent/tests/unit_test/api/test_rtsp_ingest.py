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
"""Unit tests for rtsp_ingest module."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import HTTPException
import httpx
import pytest
from tenacity import AsyncRetrying
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_none

from vss_agents.api.rtsp_ingest import AddStreamRequest
from vss_agents.api.rtsp_ingest import AddStreamResponse
from vss_agents.api.rtsp_ingest import ServiceConfig
from vss_agents.api.rtsp_ingest import _is_nvstream_url
from vss_agents.api.rtsp_ingest import _registered_cv_stream_ids
from vss_agents.api.rtsp_ingest import _with_include_audio
from vss_agents.api.rtsp_ingest import add_to_rtvi_cv
from vss_agents.api.rtsp_ingest import add_to_rtvi_embed
from vss_agents.api.rtsp_ingest import add_to_rtvi_vlm
from vss_agents.api.rtsp_ingest import add_to_vst
from vss_agents.api.rtsp_ingest import cleanup_rtvi_cv
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_generation
from vss_agents.api.rtsp_ingest import cleanup_rtvi_embed_stream
from vss_agents.api.rtsp_ingest import cleanup_rtvi_vlm_stream
from vss_agents.api.rtsp_ingest import cleanup_vst_sensor
from vss_agents.api.rtsp_ingest import cleanup_vst_storage
from vss_agents.api.rtsp_ingest import create_rtsp_ingest_router
from vss_agents.api.rtsp_ingest import get_stream_info_by_name
from vss_agents.api.rtsp_ingest import reconcile_live_source_now
from vss_agents.api.rtsp_ingest import reconcile_registered_live_sources
from vss_agents.api.rtsp_ingest import register_rtsp_ingest_routes
from vss_agents.api.rtsp_ingest import start_embedding_generation
from vss_agents.api.rtsp_ingest import stop_managed_embedding_generation
from vss_agents.api.source_analysis_state import _detection_disabled_sources
from vss_agents.api.source_analysis_state import _paused_sources
from vss_agents.api.source_analysis_state import _source_analysis_profiles
from vss_agents.api.source_analysis_state import _source_kinds
from vss_agents.api.source_analysis_state import load_source_analysis_state
from vss_agents.api.source_analysis_state import set_source_analysis_profile
from vss_agents.api.source_analysis_state import set_source_kind


@pytest.fixture(autouse=True)
def isolated_source_analysis_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "VSS_SOURCE_ANALYSIS_STATE_FILE",
        str(tmp_path / "source-analysis-state.json"),
    )
    load_source_analysis_state(force=True)
    yield
    _paused_sources.clear()
    _detection_disabled_sources.clear()
    _source_analysis_profiles.clear()
    _source_kinds.clear()


def _single_attempt_retry() -> AsyncRetrying:
    """Return a retry strategy that executes exactly once with no delay (for unit tests)."""
    return AsyncRetrying(stop=stop_after_attempt(1), wait=wait_none(), reraise=True)


def _multi_attempt_retry(attempts: int = 3) -> AsyncRetrying:
    """Return a retry strategy with *attempts* tries, no delay, retrying on any Exception."""
    return AsyncRetrying(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(attempts),
        wait=wait_none(),
        reraise=True,
    )


class TestIsNvstreamUrl:
    """Predicate for `/nvstream/` paths."""

    @pytest.mark.parametrize(
        "url",
        [
            "rtsp://nvstreamer:31555/nvstream/file.mp4",
            "rtsp://10.0.0.1:31555/nvstream/sub/dir/file.mp4",
            "rtsp://nvstreamer:31555/nvstream/file.mp4?x=1",
        ],
    )
    def test_matches_nvstream_paths(self, url):
        assert _is_nvstream_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "rtsp://vst:30557/live/uuid-abc",
            "rtsp://camera.lab:554/cam1",
            "rtsp://nvstreamer:31555/nvstreamX/file.mp4",
            "",
        ],
    )
    def test_rejects_non_nvstream_paths(self, url):
        assert _is_nvstream_url(url) is False


class TestWithIncludeAudio:
    """``_with_include_audio`` merges ``includeAudio=true`` into the RTSP URL."""

    def test_appends_when_query_absent(self):
        assert _with_include_audio("rtsp://vst:554/sensor-123") == "rtsp://vst:554/sensor-123?includeAudio=true"

    def test_preserves_existing_query_keys(self):
        result = _with_include_audio("rtsp://vst:554/sensor-123?transport=tcp")
        # `parse_qsl`/`urlencode` may reorder, so check both keys are present.
        assert result.startswith("rtsp://vst:554/sensor-123?")
        assert "transport=tcp" in result
        assert "includeAudio=true" in result

    def test_idempotent_when_already_present(self):
        """Don't duplicate the key on retry."""
        url = "rtsp://vst:554/sensor-123?includeAudio=true"
        assert _with_include_audio(url) == url

    def test_preserves_explicit_false(self):
        """Per-request ``includeAudio=false`` wins over the operator-level
        ``ENABLE_AUDIO`` flag, so a caller can opt a single stream out."""
        url = "rtsp://vst:554/sensor-123?includeAudio=false"
        assert _with_include_audio(url) == url


class TestServiceConfig:
    """Test ServiceConfig class."""

    def test_basic_config(self):
        config = ServiceConfig(vst_internal_url="http://vst:30888")
        assert config.vst_url == "http://vst:30888"
        assert config.rtvi_cv_url == ""
        assert config.rtvi_embed_url == ""
        assert config.rtvi_vlm_url == ""
        assert config.rtvi_embed_model == "cosmos-embed1-448p"
        assert config.rtvi_embed_chunk_duration == 5
        # default: alerts/base/lvs-style behavior — VST owns storage, so delete it on remove
        assert config.delete_vst_storage_on_stream_remove is True
        # audio-aware VLMs are opt-in
        assert config.enable_audio is False

    def test_full_config(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888/",
            rtvi_cv_base_url="http://rtvi-cv:9000/",
            rtvi_embed_base_url="http://rtvi-embed:8017/",
            rtvi_vlm_base_url="http://rtvi-vlm:8018/",
            rtvi_embed_model="custom-model",
            rtvi_embed_chunk_duration=10,
            delete_vst_storage_on_stream_remove=False,
            enable_audio=True,
        )
        assert config.vst_url == "http://vst:30888"
        assert config.rtvi_cv_url == "http://rtvi-cv:9000"
        assert config.rtvi_embed_url == "http://rtvi-embed:8017"
        assert config.rtvi_vlm_url == "http://rtvi-vlm:8018"
        assert config.rtvi_embed_model == "custom-model"
        assert config.rtvi_embed_chunk_duration == 10
        # search-style: RTVI owns storage lifecycle, leave VST storage alone
        assert config.delete_vst_storage_on_stream_remove is False
        assert config.enable_audio is True


class TestAddStreamRequest:
    """Test AddStreamRequest model."""

    def test_required_fields(self):
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        assert request.sensor_url == "rtsp://camera:554/stream"
        assert request.name == "camera-1"
        assert request.username == ""
        assert request.password == ""
        assert request.location == ""
        assert request.tags == ""

    def test_all_fields(self):
        request = AddStreamRequest(
            sensor_url="rtsp://camera:554/stream",
            name="camera-1",
            username="admin",
            password="pw",  # pragma: allowlist secret
            location="Building A",
            tags="entrance,security",
        )
        assert request.username == "admin"
        assert request.password == "pw"  # pragma: allowlist secret
        assert request.location == "Building A"
        assert request.tags == "entrance,security"

    def test_alias_sensor_url(self):
        """Test that sensorUrl alias works."""
        request = AddStreamRequest(sensorUrl="rtsp://camera:554/stream", name="camera-1")
        assert request.sensor_url == "rtsp://camera:554/stream"

    def test_missing_required_fields_fails(self):
        with pytest.raises(Exception):
            AddStreamRequest(name="camera-1")  # Missing sensor_url


class TestAddStreamResponse:
    """Test AddStreamResponse model."""

    def test_success_response(self):
        response = AddStreamResponse(
            status="success",
            message="Stream added successfully",
            sensorId="sensor-123",
            name="camera-1",
        )
        assert response.status == "success"
        assert response.message == "Stream added successfully"
        assert response.error is None
        assert response.sensor_id == "sensor-123"
        assert response.name == "camera-1"

    def test_success_response_requires_stable_identity(self):
        with pytest.raises(ValueError, match="requires sensorId and name"):
            AddStreamResponse(status="success", message="Stream added successfully")

    def test_failure_response(self):
        response = AddStreamResponse(status="failure", message="Failed to add stream", error="VST error")
        assert response.status == "failure"
        assert response.error == "VST error"


class TestAddToVst:
    """Test add_to_vst function."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    @patch("vss_agents.api.rtsp_ingest.vst_get_rtsp_url")
    async def test_successful_add(self, mock_get_rtsp_url, mock_add_sensor):
        config = ServiceConfig(vst_internal_url="http://vst:30888")
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")

        # Mock VST add sensor
        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        # Mock VST get RTSP URL
        mock_get_rtsp_url.return_value = (True, "OK", "rtsp://vst:554/sensor-123")

        success, _msg, sensor_id, rtsp_url = await add_to_vst(config, request)

        assert success is True
        assert sensor_id == "sensor-123"
        assert rtsp_url == "rtsp://vst:554/sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_proxy_stream")
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    async def test_direct_streamprocessor_add(self, mock_add_sensor, mock_add_proxy):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            vst_streamprocessor_url="http://streamprocessor:30001/",
        )
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        mock_add_proxy.return_value = (True, "OK", "rtsp://vst:30554/live/sensor-123")

        success, _msg, sensor_id, rtsp_url = await add_to_vst(config, request)

        assert success is True
        assert sensor_id == "sensor-123"
        assert rtsp_url == "rtsp://vst:30554/live/sensor-123"
        mock_add_proxy.assert_awaited_once_with(
            sensor_id="sensor-123",
            sensor_url="rtsp://camera:554/stream",
            name="camera-1",
            streamprocessor_url="http://streamprocessor:30001",
        )

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_proxy_stream")
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    async def test_direct_streamprocessor_failure_preserves_sensor_id_for_rollback(
        self, mock_add_sensor, mock_add_proxy
    ):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            vst_streamprocessor_url="http://streamprocessor:30001",
        )
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        mock_add_proxy.return_value = (False, "streamprocessor unavailable", None)

        success, msg, sensor_id, rtsp_url = await add_to_vst(config, request)

        assert success is False
        assert "unavailable" in msg
        assert sensor_id == "sensor-123"
        assert rtsp_url is None

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    @patch("vss_agents.api.rtsp_ingest.vst_get_rtsp_url")
    async def test_appends_include_audio_for_nvstream_source(self, mock_get_rtsp_url, mock_add_sensor):
        """``enable_audio=True`` + nvstreamer source -> VST gets the audio-opted URL."""
        config = ServiceConfig(vst_internal_url="http://vst:30888", enable_audio=True)
        request = AddStreamRequest(
            sensor_url="rtsp://nvstreamer:31555/nvstream/file.mp4",
            name="cam1",
        )

        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        mock_get_rtsp_url.return_value = (True, "OK", "rtsp://vst:30557/live/uuid-abc")

        success, _msg, _sensor_id, rtsp_url = await add_to_vst(config, request)

        assert success is True
        assert mock_add_sensor.call_args.kwargs["sensor_url"] == (
            "rtsp://nvstreamer:31555/nvstream/file.mp4?includeAudio=true"
        )
        # VST's downstream URL is returned unchanged.
        assert rtsp_url == "rtsp://vst:30557/live/uuid-abc"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    @patch("vss_agents.api.rtsp_ingest.vst_get_rtsp_url")
    async def test_does_not_rewrite_non_nvstream_source(self, mock_get_rtsp_url, mock_add_sensor):
        """Generic RTSP cameras don't speak ``includeAudio``; leave them alone."""
        config = ServiceConfig(vst_internal_url="http://vst:30888", enable_audio=True)
        request = AddStreamRequest(sensor_url="rtsp://camera.lab:554/cam1", name="cam1")

        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        mock_get_rtsp_url.return_value = (True, "OK", "rtsp://vst:30557/live/uuid-abc")

        await add_to_vst(config, request)

        assert mock_add_sensor.call_args.kwargs["sensor_url"] == "rtsp://camera.lab:554/cam1"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    @patch("vss_agents.api.rtsp_ingest.vst_get_rtsp_url")
    async def test_does_not_rewrite_when_audio_disabled(self, mock_get_rtsp_url, mock_add_sensor):
        """Default profile (``enable_audio=False``) is unchanged behavior."""
        config = ServiceConfig(vst_internal_url="http://vst:30888")
        request = AddStreamRequest(
            sensor_url="rtsp://nvstreamer:31555/nvstream/file.mp4",
            name="cam1",
        )

        mock_add_sensor.return_value = (True, "OK", "sensor-123")
        mock_get_rtsp_url.return_value = (True, "OK", "rtsp://vst:30557/live/uuid-abc")

        await add_to_vst(config, request)

        assert mock_add_sensor.call_args.kwargs["sensor_url"] == "rtsp://nvstreamer:31555/nvstream/file.mp4"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    async def test_vst_returns_error(self, mock_add_sensor):
        config = ServiceConfig(vst_internal_url="http://vst:30888")
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")

        mock_add_sensor.return_value = (False, "VST returned 500: Internal Server Error", None)

        success, msg, sensor_id, _rtsp_url = await add_to_vst(config, request)

        assert success is False
        assert "500" in msg
        assert sensor_id is None

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_add_sensor")
    async def test_vst_missing_sensor_id(self, mock_add_sensor):
        config = ServiceConfig(vst_internal_url="http://vst:30888")
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")

        mock_add_sensor.return_value = (False, "VST response missing sensor ID: {}", None)

        success, msg, _sensor_id, _rtsp_url = await add_to_vst(config, request)

        assert success is False
        assert "missing sensor ID" in msg


class TestAddToRtviCv:
    """Test add_to_rtvi_cv function."""

    @pytest.mark.asyncio
    async def test_successful_add(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="http://rtvi-cv:9000")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)

        success, msg = await add_to_rtvi_cv(mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123")

        assert success is True
        assert msg == "OK"

    @pytest.mark.asyncio
    async def test_skipped_when_not_configured(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="")

        success, msg = await add_to_rtvi_cv(mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123")

        assert success is True
        assert "Skipped" in msg
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_rtvi_cv_error(self, mock_retry):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="http://rtvi-cv:9000")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Error"
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_retry.return_value = _single_attempt_retry()

        success, msg = await add_to_rtvi_cv(mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123")

        assert success is False
        assert "500" in msg

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_retries_transient_transport_failure(self, mock_retry):
        """A recovering RTVI-CV process must not force the whole ingest transaction to roll back."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="http://rtvi-cv:9000")

        ok_response = MagicMock()
        ok_response.status_code = 200
        mock_client.post = AsyncMock(side_effect=[httpx.ConnectTimeout(""), ok_response])
        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, msg = await add_to_rtvi_cv(
            mock_client,
            config,
            "sensor-123",
            "camera-1",
            "rtsp://vst:554/sensor-123",
        )

        assert success is True
        assert msg == "OK"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_empty_transport_error_reports_exception_type(self, mock_retry):
        """httpx timeout messages are often empty; the UI still needs an actionable failure reason."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="http://rtvi-cv:9000")
        mock_client.post = AsyncMock(side_effect=httpx.ConnectTimeout(""))
        mock_retry.return_value = _single_attempt_retry()

        success, msg = await add_to_rtvi_cv(
            mock_client,
            config,
            "sensor-123",
            "camera-1",
            "rtsp://vst:554/sensor-123",
        )

        assert success is False
        assert "ConnectTimeout" in msg


class TestAddToRtviEmbed:
    """Test add_to_rtvi_embed function."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_successful_add(self, mock_retry):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"streams": [{"id": "rtvi-stream-123"}]})
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_retry.return_value = _single_attempt_retry()

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "rtvi-stream-123"

    @pytest.mark.asyncio
    async def test_skipped_when_not_configured(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="")

        success, msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert "Skipped" in msg
        assert stream_id == "sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_fallback_to_sensor_id(self, mock_retry):
        """Test that stream_id falls back to sensor_id when not in response."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"streams": []})
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_retry.return_value = _single_attempt_retry()

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_retry_succeeds_after_transient_failure(self, mock_retry):
        """Test that a transient 503 followed by 200 succeeds."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.text = "Service Unavailable"

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json = MagicMock(return_value={"streams": [{"id": "rtvi-stream-123"}]})

        mock_client.post = AsyncMock(side_effect=[fail_response, ok_response])

        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "rtvi-stream-123"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_all_retries_exhausted(self, mock_retry):
        """Test that persistent failures return an error after retries are exhausted."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        fail_response = MagicMock()
        fail_response.status_code = 500
        fail_response.text = "Internal Server Error"

        mock_client.post = AsyncMock(return_value=fail_response)

        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is False
        assert "RTVI-embed" in msg
        assert stream_id is None
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_connection_error_retried(self, mock_retry):
        """Test that network-level exceptions are retried."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json = MagicMock(return_value={"streams": [{"id": "rtvi-stream-123"}]})

        mock_client.post = AsyncMock(side_effect=[httpx.ConnectError("connection refused"), ok_response])

        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "rtvi-stream-123"
        assert mock_client.post.call_count == 2


class TestAddToRtviEmbedRealRetry:
    """Tests that exercise the real create_retry_strategy to pin configured retry parameters."""

    @pytest.mark.asyncio
    @patch("vss_agents.utils.retry.wait_random", return_value=wait_none())
    async def test_retries_on_transport_error(self, _mock_wait):
        """Real retry strategy retries httpx.TransportError and eventually succeeds."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json = MagicMock(return_value={"streams": [{"id": "rtvi-stream-123"}]})

        mock_client.post = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                httpx.ConnectError("connection refused"),
                ok_response,
            ]
        )

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "rtvi-stream-123"
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    @patch("vss_agents.utils.retry.wait_random", return_value=wait_none())
    async def test_retries_on_timeout(self, _mock_wait):
        """httpx.TimeoutException (subclass of TransportError) is retried."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json = MagicMock(return_value={"streams": [{"id": "rtvi-stream-123"}]})

        mock_client.post = AsyncMock(side_effect=[httpx.ReadTimeout("timed out"), ok_response])

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "rtvi-stream-123"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    @patch("vss_agents.utils.retry.wait_random", return_value=wait_none())
    async def test_does_not_retry_on_non_retryable_exception(self, _mock_wait):
        """Real retry strategy does NOT retry exceptions outside the configured tuple."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        mock_client.post = AsyncMock(side_effect=KeyError("unexpected"))

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is False
        assert stream_id is None
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch("vss_agents.utils.retry.wait_random", return_value=wait_none())
    async def test_exhausts_all_six_retries_on_server_error(self, _mock_wait):
        """Real retry strategy attempts exactly 6 times before giving up on 500s."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        fail_response = MagicMock()
        fail_response.status_code = 500
        fail_response.text = "Internal Server Error"

        mock_client.post = AsyncMock(return_value=fail_response)

        success, _msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is False
        assert stream_id is None
        assert mock_client.post.call_count == 6

    @pytest.mark.asyncio
    @patch("vss_agents.utils.retry.wait_random", return_value=wait_none())
    async def test_4xx_not_retried(self, _mock_wait):
        """Real retry strategy returns immediately on 4xx client errors."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        bad_request = MagicMock()
        bad_request.status_code = 400
        bad_request.text = "Bad Request"

        mock_client.post = AsyncMock(return_value=bad_request)

        success, msg, stream_id = await add_to_rtvi_embed(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is False
        assert "400" in msg
        assert stream_id is None
        mock_client.post.assert_called_once()


class TestAddToRtviVlm:
    """Test add_to_rtvi_vlm function."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_successful_add(self, mock_retry):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_vlm_base_url="http://rtvi-vlm:8018")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"results": [{"id": "sensor-123"}]}'
        mock_response.json = MagicMock(return_value={"results": [{"id": "sensor-123"}]})
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_retry.return_value = _single_attempt_retry()

        success, _msg, stream_id = await add_to_rtvi_vlm(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert stream_id == "sensor-123"
        mock_client.post.assert_called_once_with(
            "http://rtvi-vlm:8018/v1/streams/add",
            json={
                "streams": [
                    {
                        "liveStreamUrl": "rtsp://vst:554/sensor-123",
                        "description": "camera-1",
                        "sensor_name": "sensor-123",
                        "id": "sensor-123",
                    }
                ],
            },
            headers={"x-stream-id": "sensor-123"},
        )

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_downstream_url_is_never_rewritten(self, mock_retry):
        """rtvi-vlm gets VST's ``/live/<uuid>`` URL verbatim; audio opt-in happens upstream."""
        mock_client = MagicMock()
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
            enable_audio=True,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"results": [{"id": "sensor-123"}]}'
        mock_response.json = MagicMock(return_value={"results": [{"id": "sensor-123"}]})
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_retry.return_value = _single_attempt_retry()

        downstream_url = "rtsp://vst:30557/live/uuid-abc"
        await add_to_rtvi_vlm(mock_client, config, "sensor-123", "camera-1", downstream_url)

        sent = mock_client.post.call_args.kwargs["json"]["streams"][0]["liveStreamUrl"]
        assert sent == downstream_url

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_retries_vst_proxy_until_rtvi_vlm_can_read_video(self, mock_retry):
        """VST can publish its proxy URL shortly before the relay SDP is ready."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_vlm_base_url="http://rtvi-vlm:8018")

        not_ready_response = MagicMock()
        not_ready_response.status_code = 200
        not_ready_response.content = b'{"errors": [{"error_code": "InvalidFile", "status_code": 400}]}'
        not_ready_response.json = MagicMock(
            return_value={
                "results": [],
                "errors": [
                    {
                        "index": 0,
                        "error": "Could not connect to the RTSP URL or there is no video stream from the RTSP URL",
                        "error_code": "InvalidFile",
                        "status_code": 400,
                    }
                ],
            }
        )

        ready_response = MagicMock()
        ready_response.status_code = 200
        ready_response.content = b'{"results": [{"id": "sensor-123"}]}'
        ready_response.json = MagicMock(return_value={"results": [{"id": "sensor-123"}]})
        mock_client.post = AsyncMock(side_effect=[not_ready_response, ready_response])
        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, msg, stream_id = await add_to_rtvi_vlm(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:30562/live/sensor-123"
        )

        assert success is True
        assert msg == "OK"
        assert stream_id == "sensor-123"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.create_retry_strategy")
    async def test_does_not_retry_non_media_batch_error(self, mock_retry):
        """Request-shape failures are permanent and must still fail immediately."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_vlm_base_url="http://rtvi-vlm:8018")

        bad_request_response = MagicMock()
        bad_request_response.status_code = 200
        bad_request_response.content = b'{"errors": [{"error_code": "InvalidParameters", "status_code": 422}]}'
        bad_request_response.json = MagicMock(
            return_value={
                "results": [],
                "errors": [
                    {
                        "index": 0,
                        "error": "Invalid live stream request",
                        "error_code": "InvalidParameters",
                        "status_code": 422,
                    }
                ],
            }
        )
        mock_client.post = AsyncMock(return_value=bad_request_response)
        mock_retry.return_value = _multi_attempt_retry(attempts=3)

        success, msg, stream_id = await add_to_rtvi_vlm(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:30562/live/sensor-123"
        )

        assert success is False
        assert "InvalidParameters" in msg
        assert stream_id is None
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_skipped_when_not_configured(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_vlm_base_url="")

        success, msg, stream_id = await add_to_rtvi_vlm(
            mock_client, config, "sensor-123", "camera-1", "rtsp://vst:554/sensor-123"
        )

        assert success is True
        assert "Skipped" in msg
        assert stream_id == "sensor-123"
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_stream_success(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_vlm_base_url="http://rtvi-vlm:8018")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.delete = AsyncMock(return_value=mock_response)

        success, msg = await cleanup_rtvi_vlm_stream(mock_client, config, "sensor-123")

        assert success is True
        assert msg == "OK"
        mock_client.delete.assert_called_once_with(
            "http://rtvi-vlm:8018/v1/streams/delete/sensor-123",
            headers={"x-stream-id": "sensor-123"},
        )


class TestStartEmbeddingGeneration:
    """Test start_embedding_generation function."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest._supervise_embedding_generation")
    async def test_successful_start_keeps_supervisor_alive(self, mock_supervise):
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        async def hold_connection(_config, _stream_id, started):
            started.set_result((True, "OK"))
            await asyncio.Event().wait()

        mock_supervise.side_effect = hold_connection

        success, msg = await start_embedding_generation(None, config, "stream-123")

        assert success is True
        assert msg == "OK"
        await stop_managed_embedding_generation("stream-123")
        mock_supervise.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skipped_when_not_configured(self):
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="")
        mock_client = MagicMock()

        success, msg = await start_embedding_generation(mock_client, config, "stream-123")

        assert success is True
        assert "Skipped" in msg


class TestRestartReconciliation:
    """Durable VST inventory must rehydrate empty in-memory RTVI services."""

    @pytest.mark.asyncio
    async def test_reads_real_rtvi_cv_inventory_after_service_restart(self):
        client = MagicMock()
        response = MagicMock()
        response.json.return_value = {
            "stream-info": {
                "stream-count": 2,
                "stream-info": [
                    {"camera_id": "sensor-1", "camera_name": "Camera 1", "source_id": 0},
                    {"camera-id": "sensor-2", "camera_name": "Camera 2", "source_id": 1},
                ],
            }
        }
        client.get = AsyncMock(return_value=response)

        inventory = await _registered_cv_stream_ids(client, "http://rtvi-cv:9000")

        assert inventory == {"sensor-1", "sensor-2"}
        client.get.assert_awaited_once_with("http://rtvi-cv:9000/api/v1/stream/get-stream-info")
        response.raise_for_status.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_does_not_remove_paused_source_absent_from_detector_inventory(self):
        """An unknown remove can tear down a different active DeepStream source."""
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
        )
        _paused_sources.add("paused-1")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "active-1": {
                            "name": "Active camera",
                            "url": "rtsp://vst/live/active-1",
                        },
                        "paused-1": {
                            "name": "Paused camera",
                            "url": "rtsp://vst/live/paused-1",
                        },
                    }
                ),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._detector_inventories",
                new=AsyncMock(return_value={"http://rtvi-cv:9000": {"active-1"}}),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._reconcile_live_source",
                new=AsyncMock(return_value={}),
            ) as reconcile,
            patch(
                "vss_agents.api.rtsp_ingest.stop_managed_embedding_generation",
                new=AsyncMock(),
            ),
            patch(
                "vss_agents.api.rtsp_ingest.cleanup_rtvi_cv",
                new=AsyncMock(return_value=(True, "OK")),
            ) as cleanup_cv,
        ):
            _active, desired = await reconcile_registered_live_sources(config)

        assert desired == 1
        cleanup_cv.assert_not_awaited()
        reconcile.assert_awaited_once()
        assert reconcile.await_args.args[2] == "active-1"

    @pytest.mark.asyncio
    async def test_removes_paused_source_only_from_worker_that_reports_it(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
        )
        _paused_sources.add("paused-1")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "paused-1": {
                            "name": "Paused camera",
                            "url": "rtsp://vst/live/paused-1",
                        }
                    }
                ),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._detector_inventories",
                new=AsyncMock(return_value={"http://rtvi-cv:9000": {"paused-1"}}),
            ),
            patch(
                "vss_agents.api.rtsp_ingest.cleanup_rtvi_cv",
                new=AsyncMock(return_value=(True, "OK")),
            ) as cleanup_cv,
            patch(
                "vss_agents.api.rtsp_ingest.stop_managed_embedding_generation",
                new=AsyncMock(),
            ),
        ):
            _active, desired = await reconcile_registered_live_sources(config)

        assert desired == 0
        cleanup_cv.assert_awaited_once_with(
            client,
            config,
            "paused-1",
            "Paused camera",
            "rtsp://vst/live/paused-1",
            base_url="http://rtvi-cv:9000",
        )

    @pytest.mark.asyncio
    async def test_reconciles_vst_source_when_rtvi_inventories_are_empty(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "sensor-1": {
                            "name": "Camera 1",
                            "url": "rtsp://vst/live/sensor-1",
                        }
                    }
                ),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_cv_stream_ids",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_stream_ids",
                new=AsyncMock(side_effect=[set(), set()]),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._reconcile_live_source",
                new=AsyncMock(
                    return_value={
                        "detection": True,
                        "embedding_resource": True,
                        "embedding": True,
                        "caption_resource": True,
                    }
                ),
            ) as reconcile,
            patch("vss_agents.api.rtsp_ingest.is_source_paused", return_value=False),
        ):
            active, desired = await reconcile_registered_live_sources(config)

        assert desired == 1
        assert active == 0  # no connected supervisor was faked in this unit test
        reconcile.assert_awaited_once_with(
            client,
            config,
            "sensor-1",
            "Camera 1",
            "rtsp://vst/live/sensor-1",
            {"http://rtvi-cv:9000": set()},
            set(),
            set(),
        )

    @pytest.mark.asyncio
    async def test_ignores_uploaded_file_sources_in_vst_inventory(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "live-1": {"name": "Camera 1", "url": "rtsp://vst/live/live-1"},
                        "file-1": {
                            "name": "Recorded sample",
                            "url": "/home/vst/vst_release/streamer_videos/sample.mp4",
                        },
                    }
                ),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_cv_stream_ids",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_stream_ids",
                new=AsyncMock(side_effect=[set(), set()]),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._reconcile_live_source",
                new=AsyncMock(return_value={}),
            ) as reconcile,
            patch("vss_agents.api.rtsp_ingest.is_source_paused", return_value=False),
        ):
            _active, desired = await reconcile_registered_live_sources(config)

        assert desired == 1
        reconcile.assert_awaited_once()
        assert reconcile.await_args.args[2:5] == (
            "live-1",
            "Camera 1",
            "rtsp://vst/live/live-1",
        )

    @pytest.mark.asyncio
    async def test_ignores_recording_even_when_vst_exposes_it_as_rtsp_playback(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
        )
        set_source_kind("recording-1", "recorded")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "live-1": {"name": "Camera 1", "url": "rtsp://vst/live/live-1"},
                        "recording-1": {
                            "name": "Uploaded replay",
                            "url": "rtsp://vst/live/recording-1",
                        },
                    }
                ),
            ),
            patch("vss_agents.api.rtsp_ingest._registered_cv_stream_ids", new=AsyncMock(return_value=set())),
            patch("vss_agents.api.rtsp_ingest._reconcile_live_source", new=AsyncMock()) as reconcile,
            patch("vss_agents.api.rtsp_ingest.is_source_paused", return_value=False),
        ):
            _active, desired = await reconcile_registered_live_sources(config)

        assert desired == 1
        assert reconcile.await_args.args[2] == "live-1"

    @pytest.mark.asyncio
    async def test_skips_source_deleted_after_catalog_snapshot(self):
        """A delete that begins mid-pass must win over stale VST inventory."""
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        deleting = False

        async def inventory_after_delete_starts(_client, _base_url):
            nonlocal deleting
            deleting = True
            return set()

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest.vst_get_streams_info",
                new=AsyncMock(
                    return_value={
                        "sensor-1": {
                            "name": "Camera 1",
                            "url": "rtsp://vst/live/sensor-1",
                        }
                    }
                ),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_cv_stream_ids",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_stream_ids",
                new=AsyncMock(side_effect=inventory_after_delete_starts),
            ),
            patch(
                "vss_agents.api.rtsp_ingest.is_source_deleting",
                side_effect=lambda _stream_id: deleting,
            ),
            patch(
                "vss_agents.api.rtsp_ingest._reconcile_live_source",
                new=AsyncMock(),
            ) as reconcile,
            patch(
                "vss_agents.api.rtsp_ingest.stop_managed_embedding_generation",
                new=AsyncMock(),
            ) as stop_embedding,
            patch("vss_agents.api.rtsp_ingest.clear_live_analysis_runtime") as clear_runtime,
            patch("vss_agents.api.rtsp_ingest.is_source_paused", return_value=False),
        ):
            active, desired = await reconcile_registered_live_sources(config)

        assert (active, desired) == (0, 0)
        reconcile.assert_not_awaited()
        stop_embedding.assert_awaited_once_with("sensor-1")
        clear_runtime.assert_called_once_with("sensor-1")

    @pytest.mark.asyncio
    async def test_immediate_reconcile_registers_every_missing_runtime_resource(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest._registered_cv_stream_ids",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_stream_ids",
                new=AsyncMock(side_effect=[set(), set()]),
            ),
            patch(
                "vss_agents.api.rtsp_ingest.add_to_rtvi_cv",
                new=AsyncMock(return_value=(True, "OK")),
            ) as add_cv,
            patch(
                "vss_agents.api.rtsp_ingest.add_to_rtvi_embed",
                new=AsyncMock(return_value=(True, "OK", "sensor-2")),
            ) as add_embed,
            patch(
                "vss_agents.api.rtsp_ingest.add_to_rtvi_vlm",
                new=AsyncMock(return_value=(True, "OK", "sensor-2")),
            ) as add_vlm,
            patch(
                "vss_agents.api.rtsp_ingest.start_embedding_generation",
                new=AsyncMock(return_value=(True, "OK")),
            ) as start_embed,
        ):
            steps = await reconcile_live_source_now(
                config,
                "sensor-2",
                "Camera 2",
                "rtsp://vst/live/sensor-2",
            )

        assert all(steps.values())
        add_cv.assert_awaited_once()
        add_embed.assert_awaited_once()
        add_vlm.assert_awaited_once()
        start_embed.assert_awaited_once_with(None, config, "sensor-2")

    @pytest.mark.asyncio
    async def test_general_scene_reconcile_removes_stale_warehouse_detector(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
            rtvi_embed_base_url="http://rtvi-embed:8017",
            rtvi_vlm_base_url="http://rtvi-vlm:8018",
        )
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient", return_value=client),
            patch(
                "vss_agents.api.rtsp_ingest._registered_cv_stream_ids",
                new=AsyncMock(return_value={"traffic-1"}),
            ),
            patch(
                "vss_agents.api.rtsp_ingest._registered_stream_ids",
                new=AsyncMock(side_effect=[{"traffic-1"}, {"traffic-1"}]),
            ),
            patch("vss_agents.api.rtsp_ingest.is_source_detection_enabled", return_value=False),
            patch(
                "vss_agents.api.rtsp_ingest.get_source_analysis_profile",
                return_value="semantic-search",
            ),
            patch(
                "vss_agents.api.rtsp_ingest.cleanup_rtvi_cv",
                new=AsyncMock(return_value=(True, "OK")),
            ) as cleanup_cv,
            patch(
                "vss_agents.api.rtsp_ingest.start_embedding_generation",
                new=AsyncMock(return_value=(True, "OK")),
            ),
        ):
            steps = await reconcile_live_source_now(
                config,
                "traffic-1",
                "Traffic Camera",
                "rtsp://vst/live/traffic-1",
            )

        assert steps["detection"] is False
        assert steps["embedding"] is True
        cleanup_cv.assert_awaited_once()


class TestGetStreamInfoByName:
    """Test get_stream_info_by_name function."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_get_stream_info_by_name")
    async def test_successful_lookup(self, mock_vst_get_stream_info):
        config = ServiceConfig(vst_internal_url="http://vst:30888")

        mock_vst_get_stream_info.return_value = ("sensor-123", "rtsp://vst:554/sensor-123")

        success, _msg, stream_id, rtsp_url = await get_stream_info_by_name(config, "camera-1")

        assert success is True
        assert stream_id == "sensor-123"
        assert rtsp_url == "rtsp://vst:554/sensor-123"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_get_stream_info_by_name")
    async def test_name_not_found(self, mock_vst_get_stream_info):
        config = ServiceConfig(vst_internal_url="http://vst:30888")

        mock_vst_get_stream_info.return_value = (None, None)

        success, msg, _stream_id, _rtsp_url = await get_stream_info_by_name(config, "camera-1")

        assert success is False
        assert "not found" in msg


class TestCleanupFunctions:
    """Test cleanup functions."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_delete_sensor")
    async def test_cleanup_vst_sensor_success(self, mock_vst_delete_sensor):
        config = ServiceConfig(vst_internal_url="http://vst:30888")

        mock_vst_delete_sensor.return_value = (True, "OK")

        success, _msg = await cleanup_vst_sensor(config, "sensor-123")

        assert success is True

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_delete_sensor")
    @patch("vss_agents.api.rtsp_ingest.vst_delete_proxy_stream")
    async def test_cleanup_direct_proxy_before_sensor(self, mock_delete_proxy, mock_delete_sensor):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            vst_streamprocessor_url="http://streamprocessor:30001",
        )
        mock_delete_proxy.return_value = (True, "OK")
        mock_delete_sensor.return_value = (True, "OK")

        success, msg = await cleanup_vst_sensor(config, "sensor-123")

        assert success is True
        assert msg == "OK"
        mock_delete_proxy.assert_awaited_once_with("sensor-123", "http://streamprocessor:30001")
        mock_delete_sensor.assert_awaited_once_with("sensor-123", "http://vst:30888")

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.vst_delete_storage")
    async def test_cleanup_vst_storage_no_timeline(self, mock_vst_delete_storage):
        config = ServiceConfig(vst_internal_url="http://vst:30888")

        mock_vst_delete_storage.return_value = (True, "No storage to delete")

        success, msg = await cleanup_vst_storage(config, "sensor-123")

        assert success is True
        assert "No storage to delete" in msg

    @pytest.mark.asyncio
    async def test_cleanup_rtvi_cv_skipped(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_cv_base_url="")

        success, msg = await cleanup_rtvi_cv(mock_client, config, "sensor-123")

        assert success is True
        assert "Skipped" in msg

    @pytest.mark.asyncio
    async def test_cleanup_rtvi_cv_skips_unknown_id_in_authoritative_inventory(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
        )
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

        success, msg = await cleanup_rtvi_cv(client, config, "recorded-source")

        assert success is True
        assert msg == "Already absent"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_rtvi_cv_removes_id_present_in_worker_inventory(self):
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_cv_base_url="http://rtvi-cv:9000",
        )
        inventory_response = MagicMock()
        inventory_response.json.return_value = {
            "stream-info": {
                "stream-count": 1,
                "stream-info": [{"camera_id": "sensor-123"}],
            }
        }
        remove_response = MagicMock(status_code=204)
        client = MagicMock()
        client.get = AsyncMock(return_value=inventory_response)
        client.post = AsyncMock(return_value=remove_response)

        success, msg = await cleanup_rtvi_cv(client, config, "sensor-123")

        assert success is True
        assert msg == "OK"
        client.post.assert_awaited_once()
        assert client.post.await_args.kwargs["headers"] == {"x-stream-id": "sensor-123"}

    @pytest.mark.asyncio
    async def test_cleanup_rtvi_embed_stream_success(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.delete = AsyncMock(return_value=mock_response)

        success, _msg = await cleanup_rtvi_embed_stream(mock_client, config, "stream-123")

        assert success is True

    @pytest.mark.asyncio
    async def test_cleanup_rtvi_embed_generation_success(self):
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", rtvi_embed_base_url="http://rtvi-embed:8017")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.delete = AsyncMock(return_value=mock_response)

        success, _msg = await cleanup_rtvi_embed_generation(mock_client, config, "stream-123")

        assert success is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("cleanup", "config_kwargs"),
        [
            (cleanup_rtvi_embed_stream, {"rtvi_embed_base_url": "http://rtvi-embed:8017"}),
            (cleanup_rtvi_embed_generation, {"rtvi_embed_base_url": "http://rtvi-embed:8017"}),
            (cleanup_rtvi_vlm_stream, {"rtvi_vlm_base_url": "http://rtvi-vlm:8018"}),
        ],
    )
    async def test_cleanup_missing_rtvi_resource_is_successful_noop(self, cleanup, config_kwargs):
        """Already-absent RTVI resources preserve idempotent delete semantics."""
        mock_client = MagicMock()
        config = ServiceConfig(vst_internal_url="http://vst:30888", **config_kwargs)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"code":"BadParameter","message":"No such resource stream-123"}'
        mock_client.delete = AsyncMock(return_value=mock_response)

        success, message = await cleanup(mock_client, config, "stream-123")

        assert success is True
        assert message == "Already absent"

    @pytest.mark.asyncio
    async def test_cleanup_other_bad_parameter_remains_failure(self):
        """Idempotency handling must not hide unrelated malformed requests."""
        mock_client = MagicMock()
        config = ServiceConfig(
            vst_internal_url="http://vst:30888",
            rtvi_embed_base_url="http://rtvi-embed:8017",
        )
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"code":"BadParameter","message":"invalid stream id"}'
        mock_client.delete = AsyncMock(return_value=mock_response)

        success, _message = await cleanup_rtvi_embed_stream(mock_client, config, "stream-123")

        assert success is False


class TestCreateRtspStreamApiRouter:
    """Test create_rtsp_ingest_router function."""

    def test_create_router(self):
        router = create_rtsp_ingest_router(ServiceConfig(vst_internal_url="http://vst:30888"))
        assert router is not None

    def test_create_router_with_all_params(self):
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
                rtvi_embed_model="custom-model",
                rtvi_embed_chunk_duration=10,
                delete_vst_storage_on_stream_remove=True,
            )
        )
        assert router is not None

    def test_router_has_routes(self):
        router = create_rtsp_ingest_router(ServiceConfig(vst_internal_url="http://vst:30888"))
        assert len(router.routes) == 1  # add endpoint only; delete lives in rtsp_delete


class TestAddStreamEndpoint:
    """Test add_stream endpoint."""

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.start_embedding_generation")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_embed")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_cv")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_successful_add_with_full_rtvi(
        self, mock_client_class, mock_add_vst, mock_add_rtvi_cv, mock_add_rtvi_embed, mock_start_embed
    ):
        """Test successful stream addition with RTVI-CV + RTVI-embed configured (search-style)."""
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
            )
        )

        # Mock httpx client
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        # Mock all helper functions
        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_add_rtvi_cv.return_value = (True, "OK")
        mock_add_rtvi_embed.return_value = (True, "OK", "sensor-123")
        mock_start_embed.return_value = (True, "OK")

        # Get endpoint and call
        endpoint = router.routes[0].endpoint
        request = AddStreamRequest(
            sensor_url="rtsp://camera:554/stream",
            name="camera-1",
            analysisProfileId="warehouse-safety",
        )
        response = await endpoint(request)

        assert response.status == "success"
        assert "camera-1" in response.message
        assert response.sensor_id == "sensor-123"
        assert response.name == "camera-1"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.start_embedding_generation")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_embed")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_cv")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_vlm")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_unified_profile_registers_alert_and_search_paths(
        self,
        mock_client_class,
        mock_add_vst,
        mock_add_rtvi_vlm,
        mock_add_rtvi_cv,
        mock_add_rtvi_embed,
        mock_start_embed,
    ):
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
            )
        )
        client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst/live/sensor-123")
        mock_add_rtvi_vlm.return_value = (True, "OK", "sensor-123")
        mock_add_rtvi_cv.return_value = (True, "OK")
        mock_add_rtvi_embed.return_value = (True, "OK", "sensor-123")
        mock_start_embed.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(
            AddStreamRequest(
                sensor_url="rtsp://camera/main",
                name="camera-1",
                analysisProfileId="warehouse-safety",
            )
        )

        assert response.status == "success"
        assert response.sensor_id == "sensor-123"
        assert response.name == "camera-1"
        mock_add_rtvi_vlm.assert_awaited_once()
        mock_add_rtvi_cv.assert_awaited_once()
        mock_add_rtvi_embed.assert_awaited_once()
        mock_start_embed.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.commit_analysis_profile_capacity_reservation")
    @patch("vss_agents.api.rtsp_ingest.start_embedding_generation")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_embed")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_cv")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_vlm")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_general_scene_skips_warehouse_detector_but_keeps_search_and_cosmos(
        self,
        mock_client_class,
        mock_add_vst,
        mock_add_rtvi_vlm,
        mock_add_rtvi_cv,
        mock_add_rtvi_embed,
        mock_start_embed,
        mock_commit_profile,
    ):
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
            )
        )
        client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_add_vst.return_value = (True, "OK", "traffic-1", "rtsp://vst/live/traffic-1")
        mock_add_rtvi_vlm.return_value = (True, "OK", "traffic-1")
        mock_add_rtvi_embed.return_value = (True, "OK", "traffic-1")
        mock_start_embed.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(
            AddStreamRequest(
                sensor_url="rtsp://camera/traffic",
                name="Traffic Camera",
                detectionEnabled=False,
            )
        )

        assert response.status == "success"
        assert response.detection_enabled is False
        mock_commit_profile.assert_called_once()
        assert mock_commit_profile.call_args.args[1] == "traffic-1"
        mock_add_rtvi_cv.assert_not_awaited()
        mock_add_rtvi_vlm.assert_awaited_once()
        mock_add_rtvi_embed.assert_awaited_once()
        mock_start_embed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_rejects_profile_at_capacity_before_creating_a_vst_source(self, monkeypatch):
        monkeypatch.setenv("VSS_TRAFFIC_RTVI_CV_URL", "http://traffic:9010")
        set_source_analysis_profile("intersection-a", "traffic-monitoring")
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://warehouse:9000",
            )
        )
        endpoint = router.routes[0].endpoint

        with patch("vss_agents.api.rtsp_ingest.add_to_vst", new=AsyncMock()) as add_to_vst:
            with pytest.raises(HTTPException) as exc_info:
                await endpoint(
                    AddStreamRequest(
                        sensor_url="rtsp://camera/intersection-b",
                        name="Intersection B",
                        analysisProfileId="traffic-monitoring",
                    )
                )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {
            "code": "analysis_profile_capacity_exhausted",
            "maxSources": 1,
            "occupiedSourceIds": ["intersection-a"],
            "pendingReservations": 0,
            "profileId": "traffic-monitoring",
        }
        add_to_vst.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    async def test_successful_add_vst_only(self, mock_add_vst):
        """Test successful stream addition with VST only (no RTVI URLs configured).

        With no RTVI URLs, the LVS branch is skipped (``rtvi_vlm_base_url`` is
        empty) and ``add_to_rtvi_cv``/``add_to_rtvi_embed``/
        ``start_embedding_generation`` self-skip — VST add is the only real
        side effect.
        """
        router = create_rtsp_ingest_router(ServiceConfig(vst_internal_url="http://vst:30888"))

        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")

        endpoint = router.routes[0].endpoint
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        response = await endpoint(request)

        assert response.status == "success"
        assert "camera-1" in response.message
        assert response.sensor_id == "sensor-123"
        assert response.name == "camera-1"

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_storage")
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_vlm")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_rtvi_vlm_failure_triggers_rollback(
        self, mock_client_class, mock_add_vst, mock_add_rtvi_vlm, mock_cleanup_sensor, mock_cleanup_storage
    ):
        """Test that RTVI-VLM failure triggers VST cleanup in LVS mode.

        Configuring ``rtvi_vlm_base_url`` enables the LVS branch (the router
        derives ``is_lvs_mode`` from a non-empty ``config.rtvi_vlm_url``).
        """
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
            )
        )

        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_add_rtvi_vlm.return_value = (False, "RTVI-VLM error", None)
        mock_cleanup_sensor.return_value = (True, "OK")
        mock_cleanup_storage.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        response = await endpoint(request)

        assert response.status == "failure"
        assert "RTVI-VLM" in response.message
        mock_cleanup_sensor.assert_called_once()
        mock_cleanup_storage.assert_called_once()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    async def test_vst_failure_no_rollback_needed(self, mock_add_vst):
        """Test that VST failure doesn't trigger rollback (nothing to rollback)."""
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_embed_base_url="http://rtvi-embed:8017",
            )
        )

        mock_add_vst.return_value = (False, "VST returned 500: Server error", None, None)

        endpoint = router.routes[0].endpoint
        request = AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1")
        response = await endpoint(request)

        assert response.status == "failure"
        assert "VST" in response.message

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_storage")
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    async def test_proxy_activation_failure_rolls_back_created_sensor(
        self, mock_add_vst, mock_cleanup_sensor, mock_cleanup_storage
    ):
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                vst_streamprocessor_url="http://streamprocessor:30001",
            )
        )
        mock_add_vst.return_value = (False, "streamprocessor unavailable", "sensor-123", None)
        mock_cleanup_sensor.return_value = (True, "OK")
        mock_cleanup_storage.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(AddStreamRequest(sensor_url="rtsp://camera:554/stream", name="camera-1"))

        assert response.status == "failure"
        assert "streamprocessor unavailable" in response.message
        mock_cleanup_sensor.assert_awaited_once()
        assert mock_cleanup_sensor.await_args.args[1] == "sensor-123"
        mock_cleanup_storage.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_storage")
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_cv")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_rtvi_cv_failure_triggers_rollback(
        self, mock_client_class, mock_add_vst, mock_add_rtvi_cv, mock_cleanup_sensor, mock_cleanup_storage
    ):
        """Test that RTVI-CV failure triggers VST cleanup."""
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_cv_base_url="http://rtvi-cv:9000",
                rtvi_embed_base_url="http://rtvi-embed:8017",
            )
        )

        # Mock httpx client
        mock_client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

        # VST success, RTVI-CV failure
        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst:554/sensor-123")
        mock_add_rtvi_cv.return_value = (False, "RTVI-CV error")
        mock_cleanup_sensor.return_value = (True, "OK")
        mock_cleanup_storage.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        request = AddStreamRequest(
            sensor_url="rtsp://camera:554/stream",
            name="camera-1",
            analysisProfileId="warehouse-safety",
        )
        response = await endpoint(request)

        assert response.status == "failure"
        assert "RTVI-CV" in response.message
        # Should have called cleanup functions
        mock_cleanup_sensor.assert_called_once()
        mock_cleanup_storage.assert_called_once()

    @pytest.mark.asyncio
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_storage")
    @patch("vss_agents.api.rtsp_ingest.cleanup_vst_sensor")
    @patch("vss_agents.api.rtsp_ingest.cleanup_rtvi_vlm_stream")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_cv")
    @patch("vss_agents.api.rtsp_ingest.add_to_rtvi_vlm")
    @patch("vss_agents.api.rtsp_ingest.add_to_vst")
    @patch("vss_agents.api.rtsp_ingest.httpx.AsyncClient")
    async def test_unified_search_failure_rolls_back_alert_registration(
        self,
        mock_client_class,
        mock_add_vst,
        mock_add_rtvi_vlm,
        mock_add_rtvi_cv,
        mock_cleanup_vlm,
        mock_cleanup_sensor,
        mock_cleanup_storage,
    ):
        router = create_rtsp_ingest_router(
            ServiceConfig(
                vst_internal_url="http://vst:30888",
                rtvi_vlm_base_url="http://rtvi-vlm:8018",
                rtvi_cv_base_url="http://rtvi-cv:9000",
            )
        )
        client = MagicMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_add_vst.return_value = (True, "OK", "sensor-123", "rtsp://vst/live/sensor-123")
        mock_add_rtvi_vlm.return_value = (True, "OK", "sensor-123")
        mock_add_rtvi_cv.return_value = (False, "RTVI-CV unavailable")
        mock_cleanup_vlm.return_value = (True, "OK")
        mock_cleanup_sensor.return_value = (True, "OK")
        mock_cleanup_storage.return_value = (True, "OK")

        endpoint = router.routes[0].endpoint
        response = await endpoint(
            AddStreamRequest(
                sensor_url="rtsp://camera/main",
                name="camera-1",
                analysisProfileId="warehouse-safety",
            )
        )

        assert response.status == "failure"
        mock_cleanup_vlm.assert_awaited_once()
        assert mock_cleanup_vlm.await_args.args[2] == "sensor-123"
        mock_cleanup_sensor.assert_awaited_once()
        mock_cleanup_storage.assert_awaited_once()


class TestRegisterRtspStreamApiRoutes:
    """Test register_rtsp_ingest_routes function."""

    def test_register_with_full_rtvi_config(self):
        """search-style: VST + RTVI-CV + RTVI-embed all configured, RTVI manages storage."""
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

        register_rtsp_ingest_routes(mock_app, mock_config)

        assert mock_app.include_router.called

    def test_register_vst_only_no_rtvi_urls(self):
        """alerts-style: only VST configured, no RTVI URLs.

        ``register_rtsp_ingest_routes`` no longer requires
        ``rtvi_embed_base_url`` — empty values mean RTVI steps self-skip at
        request time. This must succeed.
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

        register_rtsp_ingest_routes(mock_app, mock_config)

        assert mock_app.include_router.called

    def test_register_missing_streaming_ingest_raises(self):
        """Without streaming_ingest configured, registration must fail loudly."""
        mock_app = MagicMock()
        mock_config = MagicMock()
        mock_config.general.front_end = MagicMock(spec=[])  # no streaming_ingest

        with pytest.raises(ValueError, match="streaming_ingest"):
            register_rtsp_ingest_routes(mock_app, mock_config)

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
            register_rtsp_ingest_routes(mock_app, mock_config)
