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
"""Unit tests for report_agent module."""

from datetime import datetime
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from vss_agents.agents.report_agent import ReportAgentInput
from vss_agents.agents.report_agent import VideoReportAgentInput
from vss_agents.agents.report_agent import _video_report_observability


class TestReportAgentInput:
    """Test ReportAgentInput model."""

    def test_defaults(self):
        input_data = ReportAgentInput()
        assert input_data.start_time is None
        assert input_data.end_time is None
        assert input_data.incident_id is None
        assert input_data.source is None
        assert input_data.source_type is None
        assert input_data.vlm_reasoning is None

    def test_with_incident_id(self):
        input_data = ReportAgentInput(incident_id="incident-123")
        assert input_data.incident_id == "incident-123"

    def test_with_time_range(self):
        start = datetime(2025, 1, 1, 0, 0)
        end = datetime(2025, 1, 1, 23, 59)
        input_data = ReportAgentInput(start_time=start, end_time=end)
        assert input_data.start_time == start
        assert input_data.end_time == end

    def test_with_source_sensor(self):
        input_data = ReportAgentInput(source="sensor-001", source_type="sensor")
        assert input_data.source == "sensor-001"
        assert input_data.source_type == "sensor"

    def test_with_source_place(self):
        input_data = ReportAgentInput(source="Main Street", source_type="place")
        assert input_data.source_type == "place"

    def test_invalid_source_type(self):
        with pytest.raises(ValidationError):
            ReportAgentInput(source="test", source_type="invalid")

    def test_vlm_reasoning_enabled(self):
        input_data = ReportAgentInput(vlm_reasoning=True)
        assert input_data.vlm_reasoning is True

    def test_vlm_reasoning_disabled(self):
        input_data = ReportAgentInput(vlm_reasoning=False)
        assert input_data.vlm_reasoning is False


class TestVideoReportAgentInput:
    """Test VideoReportAgentInput model."""

    def test_all_fields(self):
        input_data = VideoReportAgentInput(sensor_id="vst-sensor-001", user_query="What's happening in this video?")
        assert input_data.sensor_id == "vst-sensor-001"
        assert input_data.user_query == "What's happening in this video?"

    def test_missing_sensor_id(self):
        with pytest.raises(ValidationError):
            VideoReportAgentInput(user_query="test")

    def test_only_sensor_id(self):
        input_data = VideoReportAgentInput(sensor_id="vst-sensor-001")
        assert input_data.sensor_id == "vst-sensor-001"
        assert input_data.user_query == "Generate a detailed report of the video."

    def test_json_encoded_sensor_id_list_is_normalized(self):
        input_data = VideoReportAgentInput(sensor_id='["video-one", "video-two"]')
        assert input_data.sensor_id == ["video-one", "video-two"]

    def test_non_json_bracketed_sensor_name_is_preserved(self):
        input_data = VideoReportAgentInput(sensor_id="[warehouse-camera]")
        assert input_data.sensor_id == "[warehouse-camera]"


class TestVideoReportObservability:
    CORRELATION_ID = "lvs-" + "b" * 32

    @classmethod
    def _result(cls, reports: list[dict], failed: list[str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            report_correlation_id=cls.CORRELATION_ID,
            requested_sensor_ids=["alpha.mp4", "beta.mp4"],
            failed_sensor_ids=failed or [],
            all_reports=reports,
            http_url=reports[0]["http_url"] if reports else None,
        )

    @classmethod
    def _artifact(cls, sensor_id: str, source_index: int) -> dict:
        return {
            "sensor_id": sensor_id,
            "source_index": source_index,
            "source_count": 2,
            "report_correlation_id": cls.CORRELATION_ID,
            "http_url": f"http://localhost/static/{sensor_id}.md",
            "pdf_url": f"http://localhost/static/{sensor_id}.pdf",
            "object_store_key": f"{sensor_id}.md",
            "pdf_object_store_key": f"{sensor_id}.pdf",
            "file_size": 101 + source_index,
            "pdf_file_size": 201 + source_index,
        }

    def test_complete_two_video_envelope_correlates_each_artifact(self):
        value = _video_report_observability(
            self._result([self._artifact("alpha.mp4", 0), self._artifact("beta.mp4", 1)]),
            ["alpha.mp4", "beta.mp4"],
        )
        assert value["complete"] is True
        assert value["report_count"] == 2
        assert value["successful_sensor_ids"] == ["alpha.mp4", "beta.mp4"]
        assert [item["source_index"] for item in value["artifacts"]] == [0, 1]
        assert all(item["report_correlation_id"] == self.CORRELATION_ID for item in value["artifacts"])
        assert value["artifacts"][0]["markdown"]["object_store_key"] == "alpha.mp4.md"

    def test_partial_envelope_is_explicit_not_complete(self):
        value = _video_report_observability(
            self._result([self._artifact("alpha.mp4", 0)], ["beta.mp4"]),
            ["alpha.mp4", "beta.mp4"],
        )
        assert value["complete"] is False
        assert value["successful_sensor_ids"] == ["alpha.mp4"]
        assert value["failed_sensor_ids"] == ["beta.mp4"]

    @pytest.mark.parametrize("mutation", ["swap", "foreign", "duplicate", "missing-correlation"])
    def test_ambiguous_artifact_correlation_fails_closed(self, mutation):
        first = self._artifact("alpha.mp4", 0)
        second = self._artifact("beta.mp4", 1)
        reports = [first, second]
        result = self._result(reports)
        if mutation == "swap":
            second["source_index"] = 0
        elif mutation == "foreign":
            second["sensor_id"] = "foreign.mp4"
        elif mutation == "duplicate":
            second["sensor_id"] = "alpha.mp4"
        else:
            result.report_correlation_id = None
        with pytest.raises(ValueError, match="Report Agent"):
            _video_report_observability(result, ["alpha.mp4", "beta.mp4"])
