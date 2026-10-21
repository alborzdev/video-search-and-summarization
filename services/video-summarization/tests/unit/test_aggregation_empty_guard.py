# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""
Unit tests for the CA-RAG aggregation empty-result guard.

These tests distinguish valid no-match results from blank or malformed
aggregation responses. They also cover structured-result repair, bounded
retries, and actionable failures.
"""

import json
from types import SimpleNamespace

import pytest


def _make_handler(retries=2):
    from via_stream_handler import ViaStreamHandler

    handler = ViaStreamHandler.__new__(ViaStreamHandler)
    handler._aggregation_empty_retries = retries
    return handler


class _FakeCtxMgr:
    """ctx_mgr stub returning a scripted response per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.docs = []

    def call(self, state):
        self.calls.append(state)
        return self._responses.pop(0)

    def add_doc(self, text, doc_i, doc_meta):
        self.docs.append((text, doc_i, doc_meta))


def _response(function_name, result, metadata=None):
    return {function_name: {"result": result, "metadata": metadata or {}}}


def _summary(events=None, video_summary=""):
    return json.dumps(
        {
            "events": events or [],
            "total_events": len(events or []),
            "video_summary": video_summary,
            "uuid": "test-id",
        }
    )


class TestIsEmptyAggregationResult:
    """Only results with neither events nor a summary count as empty."""

    @pytest.mark.parametrize(
        "result",
        [
            None,
            "",
            "   ",
        ],
        ids=[
            "none",
            "blank",
            "whitespace",
        ],
    )
    def test_empty_results(self, result):
        handler = _make_handler()
        assert handler._is_empty_aggregation_result(result) is True

    @pytest.mark.parametrize(
        "result",
        [
            _summary(),
            _summary(video_summary="   "),
            {"events": [], "total_events": 0, "video_summary": ""},
            "[]",
            [],
            _summary(video_summary="A forklift crossed the aisle."),
            _summary(events=[{"type": "forklift"}]),
            "A forklift crossed the aisle.",
        ],
        ids=[
            "no-events-no-summary",
            "no-events-whitespace-summary",
            "no-events-dict-result",
            "no-events-json-array",
            "no-events-list-result",
            "summary-only",
            "events-only",
            "free-text",
        ],
    )
    def test_usable_results(self, result):
        handler = _make_handler()
        assert handler._is_empty_aggregation_result(result) is False


class TestCallAggregationWithEmptyGuard:
    """An empty aggregation sample is retried before it reaches the caller."""

    def test_first_non_empty_result_returned_without_retry(self):
        handler = _make_handler(retries=2)
        expected = _response("summarization", _summary(video_summary="A busy aisle."))
        ctx_mgr = _FakeCtxMgr([expected])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is expected
        assert len(ctx_mgr.calls) == 1

    def test_empty_result_is_retried_until_non_empty(self):
        handler = _make_handler(retries=2)
        good = _response("summarization", _summary(video_summary="A forklift tipped over."))
        ctx_mgr = _FakeCtxMgr([_response("summarization", ""), good])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is good
        assert len(ctx_mgr.calls) == 2

    def test_210_second_sample_fails_actionably_after_bounded_retries(self):
        from via_exception import ViaException

        handler = _make_handler(retries=2)
        ctx_mgr = _FakeCtxMgr([_response("summarization", "") for _ in range(3)])

        with pytest.raises(ViaException) as exc_info:
            handler._call_aggregation_with_empty_guard(
                ctx_mgr,
                "summarization",
                # The documented 210-second sample produces 21 ten-second chunks.
                {"start_index": 0, "end_index": 21},
                "warehouse-sample",
                "job-210-second-regression",
            )

        assert len(ctx_mgr.calls) == 3
        assert exc_info.value.status_code == 502
        assert exc_info.value.code == "AggregationFailed"
        assert exc_info.value.job_id == "job-210-second-regression"
        assert exc_info.value.failed_stage == "aggregation"

    def test_retries_disabled_fails_after_a_single_call(self):
        from via_exception import ViaException

        handler = _make_handler(retries=0)
        only = _response("summarization", "")
        ctx_mgr = _FakeCtxMgr([only])

        with pytest.raises(ViaException):
            handler._call_aggregation_with_empty_guard(
                ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
            )

        assert len(ctx_mgr.calls) == 1

    @pytest.mark.parametrize(
        "raw",
        [
            '```json\n{"events": [{"type": "forklift"}], "video_summary": ""}\n```',
            '{"events": [{"type": "forklift",}], "video_summary": "",}',
            '{"events": "[{\\"type\\": \\"forklift\\"}]", "video_summary": ""}',
        ],
        ids=["markdown-fence", "repairable-json", "serialized-events"],
    )
    def test_event_json_is_repaired_and_normalized(self, raw):
        handler = _make_handler(retries=2)
        response = _response("summarization", raw)
        ctx_mgr = _FakeCtxMgr([response])

        result = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 21}, "test-id"
        )

        parsed = json.loads(result["summarization"]["result"])
        assert parsed["events"] == [{"type": "forklift"}]
        assert len(ctx_mgr.calls) == 1

    @pytest.mark.parametrize(
        "raw",
        [
            '{"events": "null", "video_summary": ""}',
            '{"events": "42", "video_summary": ""}',
            '{"events": [null, "not-an-event"], "video_summary": {}}',
            '{"events": [], "video_summary": 42}',
        ],
        ids=[
            "serialized-null-events",
            "serialized-scalar-events",
            "scalar-event-list-and-object-summary",
            "numeric-summary",
        ],
    )
    def test_malformed_fields_do_not_bypass_empty_guard(self, raw):
        from via_exception import ViaException

        handler = _make_handler(retries=0)
        ctx_mgr = _FakeCtxMgr([_response("summarization", raw)])

        with pytest.raises(ViaException) as exc_info:
            handler._call_aggregation_with_empty_guard(
                ctx_mgr, "summarization", {"start_index": 0, "end_index": 21}, "test-id"
            )

        assert exc_info.value.code == "AggregationFailed"
        assert len(ctx_mgr.calls) == 1

    def test_valid_no_match_result_succeeds_without_retry(self):
        handler = _make_handler(retries=2)
        no_match = _response("summarization", _summary())
        ctx_mgr = _FakeCtxMgr([no_match])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 21}, "test-id"
        )

        assert json.loads(response["summarization"]["result"])["events"] == []
        assert len(ctx_mgr.calls) == 1

    def test_malformed_events_do_not_discard_valid_summary(self):
        handler = _make_handler(retries=0)
        ctx_mgr = _FakeCtxMgr(
            [
                _response(
                    "summarization",
                    '{"events": "null", "video_summary": "Warehouse activity."}',
                )
            ]
        )

        result = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 21}, "test-id"
        )

        parsed = json.loads(result["summarization"]["result"])
        assert parsed["events"] == []
        assert parsed["video_summary"] == "Warehouse activity."
        assert len(ctx_mgr.calls) == 1

    def test_error_response_is_not_retried(self):
        handler = _make_handler(retries=2)
        error = {"error": "elasticsearch shard limit exceeded"}
        ctx_mgr = _FakeCtxMgr([error])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is error
        assert len(ctx_mgr.calls) == 1

    def test_metadata_comes_from_the_successful_attempt(self):
        handler = _make_handler(retries=2)
        good = _response(
            "summarization_online",
            _summary(video_summary="A crash near the loading dock."),
            metadata={"total_tokens": 1234},
        )
        ctx_mgr = _FakeCtxMgr([_response("summarization_online", ""), good])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization_online", {"uuids": ["test-id"]}, "test-id"
        )

        assert response["summarization_online"]["metadata"] == {"total_tokens": 1234}
        assert len(ctx_mgr.calls) == 2


class TestReadAggregationEmptyRetries:
    """LVS_AGGREGATION_EMPTY_RETRIES overrides the default retry budget."""

    def test_default_when_unset(self, monkeypatch):
        from via_stream_handler import DEFAULT_AGGREGATION_EMPTY_RETRIES, ViaStreamHandler

        monkeypatch.delenv("LVS_AGGREGATION_EMPTY_RETRIES", raising=False)
        assert (
            ViaStreamHandler._read_aggregation_empty_retries() == DEFAULT_AGGREGATION_EMPTY_RETRIES
        )

    @pytest.mark.parametrize("raw,expected", [("0", 0), ("1", 1), ("5", 5)])
    def test_valid_override(self, monkeypatch, raw, expected):
        from via_stream_handler import ViaStreamHandler

        monkeypatch.setenv("LVS_AGGREGATION_EMPTY_RETRIES", raw)
        assert ViaStreamHandler._read_aggregation_empty_retries() == expected

    def test_invalid_value_falls_back_to_default(self, monkeypatch):
        from via_stream_handler import DEFAULT_AGGREGATION_EMPTY_RETRIES, ViaStreamHandler

        monkeypatch.setenv("LVS_AGGREGATION_EMPTY_RETRIES", "many")
        assert (
            ViaStreamHandler._read_aggregation_empty_retries() == DEFAULT_AGGREGATION_EMPTY_RETRIES
        )

    def test_negative_value_disables_retry(self, monkeypatch):
        from via_stream_handler import ViaStreamHandler

        monkeypatch.setenv("LVS_AGGREGATION_EMPTY_RETRIES", "-3")
        assert ViaStreamHandler._read_aggregation_empty_retries() == 0


class TestAggregationEventBoundsGuard:
    def test_out_of_range_timestamp_sample_is_retried(self):
        handler = _make_handler(retries=2)
        invalid = _summary(
            events=[
                {
                    "start_time": 0,
                    "end_time": 20,
                    "type": "movement",
                    "description": "movement",
                }
            ],
            video_summary="Movement occurred.",
        )
        valid = _summary(
            events=[
                {
                    "start_time": 0,
                    "end_time": 10,
                    "type": "movement",
                    "description": "movement",
                }
            ],
            video_summary="Movement occurred.",
        )
        expected = _response("summarization", valid)
        ctx_mgr = _FakeCtxMgr([_response("summarization", invalid), expected])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr,
            "summarization",
            {"start_index": 0, "end_index": 3},
            "test-id",
            event_time_bounds=(0.0, 10.0),
        )

        assert response is expected
        assert len(ctx_mgr.calls) == 2

    def test_all_out_of_range_timestamp_samples_fail_closed(self):
        handler = _make_handler(retries=2)
        invalid = _response(
            "summarization",
            _summary(
                events=[
                    {
                        "start_time": 10,
                        "end_time": 15,
                        "type": "movement",
                        "description": "movement",
                    }
                ],
                video_summary="Movement occurred.",
            ),
        )
        ctx_mgr = _FakeCtxMgr([invalid, invalid, invalid])

        with pytest.raises(Exception, match="outside the processed media interval"):
            handler._call_aggregation_with_empty_guard(
                ctx_mgr,
                "summarization",
                {"start_index": 0, "end_index": 3},
                "test-id",
                event_time_bounds=(0.0, 10.0),
            )
        assert len(ctx_mgr.calls) == 3


class TestFullFileAggregationTimeBounds:
    @staticmethod
    def _bounds(creation_time=None, start=1735689600, end=1735689624, **request):
        req = SimpleNamespace(
            is_live=False, start_timestamp=None, end_timestamp=None,
            creation_time=creation_time,
        )
        for name, value in request.items():
            setattr(req, name, value)
        chunks = [SimpleNamespace(chunk=SimpleNamespace(
            start_pts=start * 1e9, end_pts=end * 1e9,
        ))]
        bounds = _make_handler()._full_file_aggregation_time_bounds(req, chunks)
        # Computing validation bounds must not alter persisted recording clocks.
        assert chunks[0].chunk.start_pts == start * 1e9
        assert chunks[0].chunk.end_pts == end * 1e9
        return bounds

    @pytest.mark.parametrize("origin", ["2025-01-01T00:00:00Z", "2024-12-31T19:00:00-05:00"])
    def test_absolute_recording_origin_yields_file_seconds(self, origin):
        bounds = self._bounds(origin)
        assert bounds == (0.0, 24.0)
        handler = _make_handler()
        assert not handler._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[{"start_time": 0, "end_time": 20}]), bounds
        )
        assert handler._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[{"start_time": 0, "end_time": 25}]), bounds
        )

    def test_already_relative_chunks_are_unchanged(self):
        assert self._bounds("2025-01-01T00:00:00Z", start=0, end=24) == (0.0, 24.0)

    def test_fractional_origin_rounding_cannot_disable_the_range_guard(self):
        bounds = self._bounds(
            "2025-01-01T00:00:00.123456Z",
            start=1735689600.1234558, end=1735689624.123456,
        )
        assert bounds[0] == 0.0
        assert bounds[1] == pytest.approx(24.0)
        assert _make_handler()._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[{"start_time": 0, "end_time": 25}]), bounds
        )

    @pytest.mark.parametrize("origin", [None, "invalid", "2025-01-01T00:00:00", "2025-01-02T00:00:00Z"])
    def test_absent_ambiguous_or_mismatched_origin_is_not_rebased(self, origin):
        assert self._bounds(origin) == (1735689600.0, 1735689624.0)

    @pytest.mark.parametrize("overrides", [
        {"is_live": True}, {"start_timestamp": "00:00:05"},
        {"end_timestamp": "00:00:20"},
    ])
    def test_live_and_partial_requests_keep_existing_contract(self, overrides):
        assert self._bounds("2025-01-01T00:00:00Z", **overrides) is None

    def test_empty_chunks_have_no_bounds(self):
        req = SimpleNamespace(is_live=False, start_timestamp=None, end_timestamp=None)
        assert _make_handler()._full_file_aggregation_time_bounds(req, []) is None


class TestAggregationTimestampBounds:
    def test_valid_numeric_events_are_accepted(self):
        handler = _make_handler()
        result = _summary(
            events=[
                {"start_time": 0, "end_time": 5},
                {"start_time": 5, "end_time": 10},
            ]
        )
        assert handler._aggregation_has_out_of_range_event_timestamps(
            result, (0.0, 10.0)
        ) is False

    @pytest.mark.parametrize(
        "event",
        [
            {"start_time": -1, "end_time": 5},
            {"start_time": 0, "end_time": 11},
            {"start_time": 5, "end_time": 5},
            {"start_time": "0", "end_time": 5},
        ],
    )
    def test_invalid_numeric_events_are_rejected(self, event):
        handler = _make_handler()
        assert handler._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[event]), (0.0, 10.0)
        ) is True

    def test_unbounded_custom_or_live_result_is_unchanged(self):
        handler = _make_handler()
        assert handler._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[{"start_time": 0, "end_time": 20}]), None
        ) is False
        assert handler._aggregation_has_out_of_range_event_timestamps(
            _summary(events=[{"custom": "value"}]), (0.0, 10.0)
        ) is False


class TestStructuredInferenceDocument:
    class _Chunk:
        start_pts = 3_000_000_000
        end_pts = 6_000_000_000

    def test_plain_text_file_caption_includes_exact_media_interval(self):
        handler = _make_handler()
        req_info = type(
            "Request",
            (),
            {"enable_vlm_structured_output": False, "is_live": False},
        )()

        value = handler._structured_inference_document(
            req_info, self._Chunk(), "A worker carries a box."
        )

        assert value == (
            "Video interval: 3.000 to 6.000 seconds. "
            "Any event timestamps must stay within this interval. "
            "Caption: A worker carries a box."
        )

    @pytest.mark.parametrize(
        "structured,is_live",
        [(True, False), (False, True), (True, True)],
    )
    def test_structured_or_live_caption_is_unchanged(self, structured, is_live):
        handler = _make_handler()
        req_info = type(
            "Request",
            (),
            {"enable_vlm_structured_output": structured, "is_live": is_live},
        )()

        assert (
            handler._structured_inference_document(req_info, self._Chunk(), "caption")
            == "caption"
        )
