# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for environment-selectable realtime alert defaults."""

import pytest

from realtime.defaults import load_realtime_alert_defaults


def test_upstream_defaults_are_preserved_without_environment() -> None:
    defaults = load_realtime_alert_defaults({})

    assert defaults.chunk_duration == 30
    assert defaults.chunk_overlap_duration == 5
    assert defaults.frames_per_second_or_fixed_chunk == 10
    assert defaults.use_fps_for_chunking is True
    assert defaults.vlm_input_width == 256
    assert defaults.vlm_input_height == 256
    assert defaults.enable_reasoning is True
    assert defaults.max_tokens is None
    assert defaults.enable_audio is None


def test_thor_fixed_frame_defaults_are_selectable() -> None:
    defaults = load_realtime_alert_defaults(
        {
            "REALTIME_ALERT_CHUNK_DURATION": "10",
            "REALTIME_ALERT_CHUNK_OVERLAP_DURATION": "2",
            "REALTIME_ALERT_FRAMES_PER_CHUNK": "4",
            "REALTIME_ALERT_USE_FPS": "false",
            "REALTIME_ALERT_VLM_INPUT_WIDTH": "512",
            "REALTIME_ALERT_VLM_INPUT_HEIGHT": "512",
            "REALTIME_ALERT_ENABLE_REASONING": "false",
            "REALTIME_ALERT_MAX_TOKENS": "128",
            "REALTIME_ALERT_ENABLE_AUDIO": "false",
        }
    )

    assert defaults.chunk_duration == 10
    assert defaults.chunk_overlap_duration == 2
    assert defaults.frames_per_second_or_fixed_chunk == 4
    assert defaults.use_fps_for_chunking is False
    assert defaults.vlm_input_width == 512
    assert defaults.vlm_input_height == 512
    assert defaults.enable_reasoning is False
    assert defaults.max_tokens == 128
    assert defaults.enable_audio is False


@pytest.mark.parametrize(
    "environment, message",
    [
        ({"REALTIME_ALERT_USE_FPS": "maybe"}, "must be true or false"),
        (
            {
                "REALTIME_ALERT_CHUNK_DURATION": "5",
                "REALTIME_ALERT_CHUNK_OVERLAP_DURATION": "5",
            },
            "must be smaller",
        ),
        ({"REALTIME_ALERT_MAX_TOKENS": "0"}, "between 1 and 4096"),
    ],
)
def test_invalid_defaults_fail_fast(environment, message) -> None:
    with pytest.raises(RuntimeError, match=message):
        load_realtime_alert_defaults(environment)
