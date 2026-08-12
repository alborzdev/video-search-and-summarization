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

The aggregation LLM intermittently samples an unparseable response, which used to
surface to the caller as HTTP 200 with total_events=0, events=[] and
video_summary="". These tests cover the empty-result detection and the bounded
retry that re-runs aggregation before such a sample reaches the caller.
"""

import json

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

    def call(self, state):
        self.calls.append(state)
        return self._responses.pop(0)


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
            _summary(),
            _summary(video_summary="   "),
            {"events": [], "total_events": 0, "video_summary": ""},
        ],
        ids=[
            "none",
            "blank",
            "whitespace",
            "no-events-no-summary",
            "whitespace-summary",
            "dict-result",
        ],
    )
    def test_empty_results(self, result):
        handler = _make_handler()
        assert handler._is_empty_aggregation_result(result) is True

    @pytest.mark.parametrize(
        "result",
        [
            _summary(video_summary="A forklift crossed the aisle."),
            _summary(events=[{"type": "forklift"}]),
            "A forklift crossed the aisle.",
            "[]",
        ],
        ids=["summary-only", "events-only", "free-text", "non-dict-json"],
    )
    def test_non_empty_results(self, result):
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
        ctx_mgr = _FakeCtxMgr([_response("summarization", _summary()), good])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is good
        assert len(ctx_mgr.calls) == 2

    def test_retries_are_bounded_and_last_response_returned(self):
        handler = _make_handler(retries=2)
        last = _response("summarization", _summary())
        ctx_mgr = _FakeCtxMgr(
            [_response("summarization", _summary()), _response("summarization", _summary()), last]
        )

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is last
        assert len(ctx_mgr.calls) == 3

    def test_retries_disabled_makes_a_single_call(self):
        handler = _make_handler(retries=0)
        only = _response("summarization", _summary())
        ctx_mgr = _FakeCtxMgr([only])

        response = handler._call_aggregation_with_empty_guard(
            ctx_mgr, "summarization", {"start_index": 0, "end_index": 1}, "test-id"
        )

        assert response is only
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
