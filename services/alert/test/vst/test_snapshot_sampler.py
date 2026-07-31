# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for historical VST snapshot sampling."""

from unittest.mock import Mock

import pytest
import requests

from vst.snapshot_sampler import (
    VSTSnapshotError,
    VSTSnapshotSampler,
    _best_timeline_overlap,
    equidistant_timestamps,
)


def test_equidistant_timestamps_caps_at_four() -> None:
    assert equidistant_timestamps(
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:03Z",
        20,
    ) == [
        "2025-01-01T00:00:00.000Z",
        "2025-01-01T00:00:01.000Z",
        "2025-01-01T00:00:02.000Z",
        "2025-01-01T00:00:03.000Z",
    ]


@pytest.mark.parametrize(
    ("start", "end", "count", "message"),
    [
        ("bad", "2025-01-01T00:00:03Z", 4, "valid ISO-8601"),
        ("2025-01-01T00:00:00", "2025-01-01T00:00:03Z", 4, "timezone"),
        ("2025-01-01T00:00:03Z", "2025-01-01T00:00:00Z", 4, "precedes"),
        ("2025-01-01T00:00:00Z", "2025-01-01T00:00:03Z", 0, "positive"),
    ],
)
def test_equidistant_timestamps_rejects_invalid_input(
    start, end, count, message
) -> None:
    with pytest.raises(VSTSnapshotError, match=message):
        equidistant_timestamps(start, end, count)


def test_single_or_zero_duration_returns_one_timestamp() -> None:
    assert equidistant_timestamps(
        "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", 4
    ) == ["2025-01-01T00:00:00.000Z"]


def test_timeline_overlap_skips_invalid_entries_and_preserves_an_instant() -> None:
    assert _best_timeline_overlap(
        "2025-01-01T00:00:01Z",
        "2025-01-01T00:00:01Z",
        [
            {"startTime": "invalid", "endTime": "invalid"},
            {
                "startTime": "2025-01-01T00:00:00Z",
                "endTime": "2025-01-01T00:00:02Z",
            },
        ],
    ) == ("2025-01-01T00:00:01.000Z", "2025-01-01T00:00:01.000Z")
    assert equidistant_timestamps(
        "2025-01-01T00:00:00Z", "2025-01-01T00:00:03Z", 1
    ) == ["2025-01-01T00:00:00.000Z"]


def _handler(stream_id="stream-1", base_url="http://127.0.0.1:30888") -> Mock:
    handler = Mock()
    handler._get_stream_id_from_name.return_value = stream_id
    handler.config = {"vst_config": {"base_url": base_url, "request_timeout": 2}}
    return handler


def _timeline_response(
    start="2025-01-01T00:00:00Z", end="2025-01-01T00:00:04Z"
) -> Mock:
    response = Mock()
    response.json.return_value = {"stream-1": [{"startTime": start, "endTime": end}]}
    return response


def test_sampler_resolves_four_local_urls() -> None:
    responses = []
    for index in range(4):
        response = Mock()
        response.json.return_value = {
            "imageUrl": f"http://10.88.9.12:30888/vst/storage/temp_files/frame-{index}.jpg"
        }
        responses.append(response)
    request_get = Mock(side_effect=[_timeline_response(), *responses])

    result = VSTSnapshotSampler(_handler(), request_get=request_get).sample(
        "pit-POV",
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:03Z",
        4,
    )

    assert result == [
        f"http://127.0.0.1:30888/vst/storage/temp_files/frame-{index}.jpg"
        for index in range(4)
    ]
    assert request_get.call_count == 5
    assert request_get.call_args_list[0].kwargs == {"timeout": 2.0}
    assert request_get.call_args_list[1].kwargs == {
        "params": {"startTime": "2025-01-01T00:00:00.000Z"},
        "timeout": 2.0,
    }


def test_sampler_clips_to_recorded_timeline() -> None:
    timeline = _timeline_response(
        start="2025-01-01T00:00:01Z", end="2025-01-01T00:00:03Z"
    )
    image = Mock()
    image.json.return_value = {
        "imageUrl": "http://vst:30888/vst/storage/temp_files/frame.jpg"
    }
    request_get = Mock(side_effect=[timeline, image, image, image, image])

    VSTSnapshotSampler(_handler(), request_get=request_get).sample(
        "pit-POV",
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:04Z",
        4,
    )

    timestamps = [
        call.kwargs["params"]["startTime"] for call in request_get.call_args_list[1:]
    ]
    assert timestamps[0] == "2025-01-01T00:00:01.000Z"
    assert timestamps[-1] == "2025-01-01T00:00:02.950Z"


def test_sampler_rejects_missing_stream_or_base_url() -> None:
    with pytest.raises(VSTSnapshotError, match="stream not found"):
        VSTSnapshotSampler(_handler(stream_id=None)).sample(
            "missing", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z"
        )
    with pytest.raises(VSTSnapshotError, match="base URL"):
        VSTSnapshotSampler(_handler(base_url="")).sample(
            "pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z"
        )


def test_sampler_wraps_http_and_payload_failures() -> None:
    request_get = Mock(side_effect=requests.ConnectionError("offline"))
    with pytest.raises(VSTSnapshotError, match="timeline request failed"):
        VSTSnapshotSampler(_handler(), request_get=request_get).sample(
            "pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z", 1
        )

    request_get = Mock(
        side_effect=[_timeline_response(), requests.ConnectionError("offline")]
    )
    with pytest.raises(VSTSnapshotError, match="picture request failed"):
        VSTSnapshotSampler(_handler(), request_get=request_get).sample(
            "pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z", 1
        )

    response = Mock()
    response.json.return_value = {}
    with pytest.raises(VSTSnapshotError, match="omitted imageUrl"):
        VSTSnapshotSampler(
            _handler(), request_get=Mock(side_effect=[_timeline_response(), response])
        ).sample("pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z", 1)

    with pytest.raises(VSTSnapshotError, match="does not overlap"):
        VSTSnapshotSampler(
            _handler(),
            request_get=Mock(
                return_value=_timeline_response(
                    start="2025-01-01T01:00:00Z",
                    end="2025-01-01T01:00:01Z",
                )
            ),
        ).sample("pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z", 1)


def test_sampler_rejects_invalid_returned_url() -> None:
    response = Mock()
    response.json.return_value = {"imageUrl": "not-a-url"}
    with pytest.raises(VSTSnapshotError, match="invalid image URL"):
        VSTSnapshotSampler(
            _handler(), request_get=Mock(side_effect=[_timeline_response(), response])
        ).sample("pit", "2025-01-01T00:00:00Z", "2025-01-01T00:00:01Z", 1)
