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
Unit tests for ViaStreamHandler.update_ca_rag_config — scenario/events forwarding.

Verifies that scenario and events are forwarded to the CA-RAG summarization
params unconditionally, regardless of enable_vlm_structured_output, so that
the aggregation LLM has context for generating accurate summaries via both
/summarize and /v1/summarize.
"""

from threading import RLock


def _make_handler(config=None):
    from via_stream_handler import ViaStreamHandler

    handler = ViaStreamHandler.__new__(ViaStreamHandler)
    handler._lock = RLock()
    handler._ca_rag_config = config if config is not None else _base_config()
    handler._live_stream_info_map = {}
    return handler


def _base_config():
    return {
        "context_manager": {"functions": ["summarization"]},
        "functions": {
            "summarization": {
                "type": "vlm_structured_summarization_online",
                "tools": {"db": "vector_db", "llm": "llm_tool"},
            },
        },
        "tools": {
            "vector_db": {"params": {}},
            "llm_tool": {"params": {}},
        },
    }


def _make_ri(**overrides):
    from via_stream_handler import RequestInfo

    ri = RequestInfo()
    defaults = dict(
        source_id="test-id",
        is_live=False,
        chunk_size=10,
        summarize_batch_size=None,
        enable_vlm_structured_output=True,
        summarize=True,
        enable_audio=False,
        user_specified_collection_name=None,
        custom_metadata=None,
        delete_external_collection=False,
        schema=None,
        batch_response_method=None,
        scenario=None,
        events=None,
        auto_generate_prompt=None,
        time_metadata_keys=None,
        summarize_top_p=None,
        summarize_temperature=None,
        summarize_max_tokens=None,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(ri, k, v)
    return ri


class TestScenarioEventsForwarding:
    """scenario and events must reach CA-RAG params on every code path."""

    def test_forwarded_when_structured_output_enabled(self):
        handler = _make_handler()
        ri = _make_ri(
            enable_vlm_structured_output=True,
            scenario="warehouse",
            events=["forklift", "crash"],
        )
        config = handler.update_ca_rag_config(ri)
        params = config["functions"]["summarization"]["params"]
        assert params["scenario"] == "warehouse"
        assert params["events"] == ["forklift", "crash"]

    def test_forwarded_when_structured_output_disabled(self):
        handler = _make_handler()
        ri = _make_ri(
            enable_vlm_structured_output=False,
            scenario="retail",
            events=["theft", "slip-and-fall"],
        )
        config = handler.update_ca_rag_config(ri)
        params = config["functions"]["summarization"]["params"]
        assert params["scenario"] == "retail"
        assert params["events"] == ["theft", "slip-and-fall"]

    def test_none_scenario_not_forwarded(self):
        handler = _make_handler()
        ri = _make_ri(enable_vlm_structured_output=True, scenario=None, events=["crash"])
        config = handler.update_ca_rag_config(ri)
        params = config["functions"]["summarization"]["params"]
        assert "scenario" not in params
        assert params["events"] == ["crash"]

    def test_none_events_not_forwarded(self):
        handler = _make_handler()
        ri = _make_ri(enable_vlm_structured_output=True, scenario="security", events=None)
        config = handler.update_ca_rag_config(ri)
        params = config["functions"]["summarization"]["params"]
        assert params["scenario"] == "security"
        assert "events" not in params


class TestStructuredInferenceSelection:
    """The request's caption mode must select the matching CA-RAG function."""

    def test_structured_vlm_mode_preserves_default_aggregator(self):
        handler = _make_handler()
        config = handler.update_ca_rag_config(
            _make_ri(enable_vlm_structured_output=True)
        )
        assert (
            config["functions"]["summarization"]["type"]
            == "vlm_structured_summarization_online"
        )

    def test_plain_caption_mode_selects_schema_aware_aggregator(self):
        handler = _make_handler()
        config = handler.update_ca_rag_config(
            _make_ri(
                enable_vlm_structured_output=False,
                schema='{"type":"object","properties":{"events":{"type":"array"}}}',
                batch_response_method="json_schema",
                auto_generate_prompt=True,
                time_metadata_keys=["start_seconds", "end_seconds"],
            )
        )
        function = config["functions"]["summarization"]
        assert function["type"] == "structured_inference"
        assert function["params"] == {
            "prompts": {"caption": ""},
            "schema": '{"type":"object","properties":{"events":{"type":"array"}}}',
            "batch_response_method": "json_schema",
            "auto_generate_prompt": True,
            "time_metadata_keys": ["start_seconds", "end_seconds"],
            "uuid": "test-id",
        }

    def test_selection_does_not_mutate_base_config(self):
        base = _base_config()
        handler = _make_handler(base)
        handler.update_ca_rag_config(_make_ri(enable_vlm_structured_output=False))
        assert (
            base["functions"]["summarization"]["type"]
            == "vlm_structured_summarization_online"
        )


class TestCaptionAggregationRoute:
    """Only the UUID-capable aggregator may receive the DB call state."""

    def test_default_structured_summary_keeps_db_route(self):
        handler = _make_handler()
        handler._kafka_enabled = True
        handler._caption_source = "db"
        handler._ca_rag_config["functions"]["summarization"]["params"] = {
            "kafka_enabled": True
        }
        assert handler._use_db_caption_aggregation(
            _make_ri(enable_vlm_structured_output=True)
        )

    def test_custom_schema_summary_uses_index_range_route(self):
        handler = _make_handler()
        handler._kafka_enabled = True
        handler._caption_source = "db"
        handler._ca_rag_config["functions"]["summarization"]["params"] = {
            "kafka_enabled": True
        }
        assert not handler._use_db_caption_aggregation(
            _make_ri(enable_vlm_structured_output=False)
        )

    def test_partial_offset_summary_keeps_uuid_database_route(self):
        handler = _make_handler()
        handler._kafka_enabled = True
        handler._caption_source = "db"
        handler._ca_rag_config["functions"]["summarization"]["params"] = {
            "kafka_enabled": True
        }
        ri = _make_ri(enable_vlm_structured_output=True)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert handler._use_db_caption_aggregation(ri)


class TestRtviPartialOffsetNormalization:
    """Partial-file chunks must retain their original source timeline."""

    def test_relative_chunk_is_rebased_to_requested_window(self):
        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert handler._normalize_rtvi_file_chunk_offsets(ri, 0.0, 3.0) == (
            3.0,
            6.0,
        )

    def test_already_absolute_chunk_is_not_double_shifted(self):
        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert handler._normalize_rtvi_file_chunk_offsets(ri, 3.0, 6.0) == (
            3.0,
            6.0,
        )

    def test_full_file_chunk_is_unchanged(self):
        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = None
        ri.end_timestamp = None
        assert handler._normalize_rtvi_file_chunk_offsets(ri, 0.0, 3.0) == (
            0.0,
            3.0,
        )

    def test_live_timestamp_is_unchanged(self):
        handler = _make_handler()
        ri = _make_ri(is_live=True)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert handler._normalize_rtvi_file_chunk_offsets(ri, 0.0, 3.0) == (
            0.0,
            3.0,
        )

    def test_out_of_contract_pair_is_not_silently_rebased(self):
        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert handler._normalize_rtvi_file_chunk_offsets(ri, 1.0, 4.0) == (
            1.0,
            4.0,
        )

    def test_relative_aggregation_events_are_rebased(self):
        import json

        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        raw = json.dumps(
            {
                "events": [
                    {
                        "start_time": 0,
                        "end_time": 3,
                        "type": "movement",
                        "description": "movement",
                    }
                ],
                "video_summary": "movement",
            }
        )
        parsed = json.loads(handler._normalize_partial_aggregation_timestamps(ri, raw))
        assert parsed["events"][0]["start_time"] == 3.0
        assert parsed["events"][0]["end_time"] == 6.0

    def test_absolute_aggregation_events_are_unchanged(self):
        import json

        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        raw = json.dumps(
            {
                "events": [
                    {
                        "start_time": 3,
                        "end_time": 6,
                        "type": "movement",
                        "description": "movement",
                    }
                ]
            },
            sort_keys=True,
        )
        assert handler._normalize_partial_aggregation_timestamps(ri, raw) == raw

    def test_non_json_aggregation_is_unchanged(self):
        handler = _make_handler()
        ri = _make_ri(is_live=False)
        ri.start_timestamp = 3
        ri.end_timestamp = 6
        assert (
            handler._normalize_partial_aggregation_timestamps(ri, "plain summary")
            == "plain summary"
        )
