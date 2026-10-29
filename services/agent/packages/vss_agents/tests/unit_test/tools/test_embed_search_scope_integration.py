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

"""Exercise explicit scope through the production NAT search query builder."""

import pytest

from vss_agents.tools.embed_search import EmbedSearchConfig
from vss_agents.tools.embed_search import QueryInput
from vss_agents.tools.embed_search import _build_es_query


def config():
    return EmbedSearchConfig(
        cosmos_embed_endpoint="http://embed.test", es_endpoint="http://search.test", vst_external_url="http://vst.test"
    )


def test_exact_camera_and_interval_are_knn_prefilters():
    request = QueryInput(
        source_type="rtsp",
        params={
            "query": "a bus stops",
            "exact_sensor_ids": '["camera-id","Intersection"]',
            "video_sources": '["Intersection"]',
            "timestamp_start": "2026-10-26T10:00:00Z",
            "timestamp_end": "2026-10-26T10:02:00Z",
            "top_k": "6",
        },
    )
    built = _build_es_query(request, [0.1, 0.2], config())
    filters = built["knn"]["filter"]["bool"]["must"]
    assert filters[0] == {
        "bool": {
            "minimum_should_match": 1,
            "should": [
                {"terms": {"sensor.id.keyword": ["camera-id", "Intersection"]}},
                {"terms": {"info.sensorId.keyword": ["camera-id", "Intersection"]}},
            ],
        }
    }
    assert filters[1] == {
        "range": {"timestamp": {"gte": "2026-10-26T10:00:00+00:00", "lte": "2026-10-26T10:02:00+00:00"}}
    }
    assert built["knn"]["query_vector"] == [0.1, 0.2]
    assert "post_filter" not in built


@pytest.mark.parametrize(
    "scope", [{"exact_sensor_ids": "[]"}, {"exact_sensor_ids": '["camera"]', "timestamp_end": "invalid"}]
)
def test_invalid_explicit_scope_cannot_fall_back_to_unfiltered_search(scope):
    with pytest.raises(ValueError):
        _build_es_query(QueryInput(source_type="rtsp", params={"query": "bus", **scope}), [0.1], config())
