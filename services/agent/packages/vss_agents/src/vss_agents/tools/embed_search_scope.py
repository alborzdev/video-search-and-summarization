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

"""Explicit exact-source filters for callers that select a demo interval."""

from __future__ import annotations

from datetime import datetime
import json
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def exact_source_scope_filters(params: Mapping[str, str]) -> list[dict[str, Any]]:
    """Build ES JSON filters; malformed explicit scope must never become global.

    Legacy callers without exact_sensor_ids retain their existing behavior.
    Both released embedding source-ID fields are queried with exact terms.
    Bounds refer to each chunk's indexed start timestamp, not its entire span.
    """
    if "exact_sensor_ids" not in params:
        return []
    try:
        aliases = json.loads(params["exact_sensor_ids"])
    except (TypeError, ValueError) as exc:
        raise ValueError("exact_sensor_ids must be a nonempty JSON array") from exc
    if (
        not isinstance(aliases, list)
        or not 1 <= len(aliases) <= 32
        or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 256 for alias in aliases)
    ):
        raise ValueError("exact_sensor_ids must contain 1-32 nonempty source aliases")
    values = list(dict.fromkeys(aliases))
    filters: list[dict[str, Any]] = [
        {
            "bool": {
                "minimum_should_match": 1,
                "should": [
                    {"terms": {"sensor.id.keyword": values}},
                    {"terms": {"info.sensorId.keyword": values}},
                ],
            }
        }
    ]
    timestamps: dict[str, datetime] = {}
    for name in ("timestamp_start", "timestamp_end"):
        value = params.get(name, "")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        timestamps[name] = parsed
    if len(timestamps) == 2 and timestamps["timestamp_end"] <= timestamps["timestamp_start"]:
        raise ValueError("timestamp_end must be after timestamp_start")
    bounds = {
        key: timestamps[name].isoformat()
        for key, name in (("gte", "timestamp_start"), ("lte", "timestamp_end"))
        if name in timestamps
    }
    if bounds:
        filters.append({"range": {"timestamp": bounds}})
    return filters
