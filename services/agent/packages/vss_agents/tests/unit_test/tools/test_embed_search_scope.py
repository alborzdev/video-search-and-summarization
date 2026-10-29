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

"""Exact source/time filters stay strict without changing legacy search."""

import pytest

from vss_agents.tools.embed_search_scope import exact_source_scope_filters


def test_legacy_search_without_explicit_scope_is_unchanged():
    assert exact_source_scope_filters({"video_sources": "Intersection", "timestamp_start": "legacy-invalid"}) == []


def test_exact_scope_contains_no_wildcard_and_keeps_both_schema_aliases():
    filters = exact_source_scope_filters(
        {
            "exact_sensor_ids": '["camera-id", "Intersection *", "camera-id"]',
            "timestamp_start": "2026-10-26T10:00:00Z",
            "timestamp_end": "2026-10-26T10:02:00Z",
        }
    )
    assert filters == [
        {
            "bool": {
                "minimum_should_match": 1,
                "should": [
                    {"terms": {"sensor.id.keyword": ["camera-id", "Intersection *"]}},
                    {"terms": {"info.sensorId.keyword": ["camera-id", "Intersection *"]}},
                ],
            }
        },
        {"range": {"timestamp": {"gte": "2026-10-26T10:00:00+00:00", "lte": "2026-10-26T10:02:00+00:00"}}},
    ]


@pytest.mark.parametrize("value", ["", "not-json", "{}", "[]", '[""]', "[null]", "[3]", '["a", []]'])
def test_malformed_explicit_source_scope_fails_closed(value):
    with pytest.raises(ValueError, match="exact_sensor_ids"):
        exact_source_scope_filters({"exact_sensor_ids": value})


@pytest.mark.parametrize(
    "bounds",
    [
        {"timestamp_start": "bad"},
        {"timestamp_end": "2026-10-26T10:00:00"},
        {"timestamp_start": "2026-10-26T10:00:00Z", "timestamp_end": "2026-10-26T09:00:00Z"},
        {"timestamp_start": "2026-10-26T10:00:00Z", "timestamp_end": "2026-10-26T10:00:00Z"},
    ],
)
def test_malformed_selected_time_scope_does_not_drop_its_bounds(bounds):
    with pytest.raises(ValueError):
        exact_source_scope_filters({"exact_sensor_ids": '["camera"]', **bounds})


def test_literal_source_only_scope_remains_supported():
    assert len(exact_source_scope_filters({"exact_sensor_ids": '["camera"]'})) == 1
