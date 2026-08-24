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
"""Unit tests for the route dispatcher in CustomFastApiFrontEndWorker.

The dispatcher registers the source lifecycle route sets on every profile, with no
per-profile capability flags:

  * ``register_video_upload``               — POST /api/v1/videos
  * ``register_video_upload_complete``      — POST /api/v1/videos/{sensor_id}/complete
  * ``register_video_search_ingest_routes`` — PUT  /api/v1/videos-for-search/{filename} (deprecated)
  * ``register_rtsp_ingest_routes``         — POST /api/v1/rtsp-streams/add
  * ``register_rtsp_delete_routes``         — DELETE /api/v1/rtsp-streams/delete/{name}
  * ``register_video_delete_routes``        — DELETE /api/v1/videos/{video_id}
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from nat.builder.framework_enum import LLMFrameworkEnum
import pytest

from vss_agents.api.custom_fastapi_worker import LVS_RUNTIME_TOOL_NAMES
from vss_agents.api.custom_fastapi_worker import CustomFastApiFrontEndWorker
from vss_agents.api.custom_fastapi_worker import VisionInspectionRequest
from vss_agents.api.custom_fastapi_worker import discover_lvs_runtime_tools
from vss_agents.api.custom_fastapi_worker import inspect_vision_source
from vss_agents.api.front_end_config import StreamingIngestConfig

_MISSING = object()


def _make_worker(streaming_ingest):
    """Construct a worker bypassing the parent ``__init__`` so we can drive
    ``_register_streaming_routes`` directly without standing up a full NAT
    Config object. The dispatcher only reads ``self.config`` so a duck-typed
    MagicMock is sufficient.
    """
    worker = CustomFastApiFrontEndWorker.__new__(CustomFastApiFrontEndWorker)
    config = MagicMock()
    if streaming_ingest is _MISSING:
        config.general.front_end = MagicMock(spec=[])  # no streaming_ingest attr at all
    else:
        config.general.front_end.streaming_ingest = streaming_ingest
    worker._config = config
    return worker


@pytest.fixture
def patched_register_fns():
    """Patch every register fn the dispatcher delegates to.

    Returns a 6-tuple in the order:
        (video_upload, video_upload_complete, video_search_ingest,
         rtsp_ingest, rtsp_delete, video_delete)
    """
    with (
        patch("vss_agents.api.custom_fastapi_worker.register_video_upload") as video_upload,
        patch("vss_agents.api.custom_fastapi_worker.register_video_upload_complete") as video_upload_complete,
        patch("vss_agents.api.custom_fastapi_worker.register_video_search_ingest_routes") as video_search_ingest,
        patch("vss_agents.api.custom_fastapi_worker.register_rtsp_ingest_routes") as rtsp_ingest,
        patch("vss_agents.api.custom_fastapi_worker.register_rtsp_delete_routes") as rtsp_delete,
        patch("vss_agents.api.custom_fastapi_worker.register_video_delete_routes") as video_delete,
    ):
        yield (
            video_upload,
            video_upload_complete,
            video_search_ingest,
            rtsp_ingest,
            rtsp_delete,
            video_delete,
        )


class TestRegisterStreamingRoutesDispatcher:
    """``CustomFastApiFrontEndWorker._register_streaming_routes``."""

    def test_universal_routes_register_unconditionally(self, patched_register_fns):
        """All six register fns fire on every profile, with no per-profile
        flag. Each handler self-skips downstream calls when its backing
        service isn't configured."""
        (
            video_upload,
            video_upload_complete,
            video_search_ingest,
            rtsp_ingest,
            rtsp_delete,
            video_delete,
        ) = patched_register_fns
        worker = _make_worker(MagicMock())  # any non-None streaming_ingest

        worker._register_streaming_routes(MagicMock())

        video_upload.assert_called_once()
        video_upload_complete.assert_called_once()
        video_search_ingest.assert_called_once()
        rtsp_ingest.assert_called_once()
        rtsp_delete.assert_called_once()
        video_delete.assert_called_once()

    def test_missing_streaming_ingest_raises(self, patched_register_fns):
        """Every profile must declare streaming_ingest so a misconfigured
        profile can't silently boot with no custom routes."""
        (
            video_upload,
            video_upload_complete,
            video_search_ingest,
            rtsp_ingest,
            rtsp_delete,
            video_delete,
        ) = patched_register_fns
        worker = _make_worker(_MISSING)

        with pytest.raises(ValueError, match="streaming_ingest"):
            worker._register_streaming_routes(MagicMock())

        video_upload.assert_not_called()
        video_upload_complete.assert_not_called()
        video_search_ingest.assert_not_called()
        rtsp_ingest.assert_not_called()
        rtsp_delete.assert_not_called()
        video_delete.assert_not_called()

    def test_legacy_stream_mode_in_yaml_raises(self, patched_register_fns):
        """A profile YAML that still carries the legacy ``stream_mode`` knob
        on streaming_ingest must fail loudly at startup."""
        (
            video_upload,
            video_upload_complete,
            video_search_ingest,
            rtsp_ingest,
            rtsp_delete,
            video_delete,
        ) = patched_register_fns
        cfg = StreamingIngestConfig(stream_mode="search")
        worker = _make_worker(cfg)

        with pytest.raises(ValueError, match="stream_mode is no longer supported"):
            worker._register_streaming_routes(MagicMock())

        video_upload.assert_not_called()
        video_upload_complete.assert_not_called()
        video_search_ingest.assert_not_called()
        rtsp_ingest.assert_not_called()
        rtsp_delete.assert_not_called()
        video_delete.assert_not_called()


@pytest.mark.asyncio
async def test_lvs_runtime_discovery_resolves_all_five_live_tools():
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=object())

    result = await discover_lvs_runtime_tools(builder)

    assert result == {
        "schema_version": 1,
        "catalog": "lvs-advertised-runtime-tools",
        "expected": list(LVS_RUNTIME_TOOL_NAMES),
        "available": list(LVS_RUNTIME_TOOL_NAMES),
        "missing": [],
        "ready": True,
    }
    assert [call.args[0] for call in builder.get_tool.await_args_list] == list(LVS_RUNTIME_TOOL_NAMES)


@pytest.mark.asyncio
async def test_lvs_runtime_discovery_is_fail_closed_and_complete():
    builder = MagicMock()

    async def get_tool(name, **_kwargs):
        if name == "lvs_caption_retrieval":
            raise RuntimeError("not constructed")
        if name == "video_report_gen":
            return None
        return object()

    builder.get_tool = AsyncMock(side_effect=get_tool)
    result = await discover_lvs_runtime_tools(builder)

    assert result["ready"] is False
    assert result["available"] == list(LVS_RUNTIME_TOOL_NAMES[:3])
    assert result["missing"] == ["lvs_caption_retrieval", "video_report_gen"]
    assert builder.get_tool.await_count == 5


@pytest.mark.asyncio
async def test_direct_replay_inspection_executes_visual_tool_once_at_playhead():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value="Two vehicles cross the intersection.")
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=tool)
    request = VisionInspectionRequest(
        source_kind="replay",
        sensor_id="traffic-sensor",
        query="What objects do you see?",
        asked_at="2026-08-13T12:00:00Z",
        current_time_seconds=40,
        duration_seconds=120,
    )

    result = await inspect_vision_source(builder, request)

    assert result == {
        "answer": "Two vehicles cross the intersection.",
        "evidence_tool": "video_understanding",
        "observed_range": {"start_seconds": 34.0, "end_seconds": 58.0},
    }
    builder.get_tool.assert_awaited_once_with(
        "video_understanding",
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )
    tool.ainvoke.assert_awaited_once()
    assert tool.ainvoke.await_args.kwargs["input"]["sensor_id"] == "traffic-sensor"


@pytest.mark.asyncio
async def test_direct_live_inspection_uses_recent_iso_evidence_window():
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value="Traffic is moving through the junction.")
    builder = MagicMock()
    builder.get_tool = AsyncMock(return_value=tool)
    request = VisionInspectionRequest(
        source_kind="live",
        sensor_id="junction-camera",
        query="What is happening now?",
        asked_at="2026-08-13T12:00:30Z",
    )

    result = await inspect_vision_source(builder, request)

    assert result["evidence_tool"] == "video_understanding_iso"
    assert result["observed_range"] is None
    tool_input = tool.ainvoke.await_args.kwargs["input"]
    assert tool_input["start_timestamp"] == "2026-08-13T12:00:00Z"
    assert tool_input["end_timestamp"] == "2026-08-13T12:00:25Z"
