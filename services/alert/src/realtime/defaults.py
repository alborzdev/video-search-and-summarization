#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Environment-selectable defaults for real-time VLM alert rules.

The upstream values remain the fallback so generic NVIDIA profiles keep their
existing behaviour.  Edge profiles can select a bounded fixed-frame contract
without making every UI or API client repeat hardware-specific parameters.
Invalid values fail at process import instead of creating an alert that can
only fail asynchronously after a live stream has been registered.
"""

from dataclasses import dataclass
import os
from typing import Mapping, Optional


def _read_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; found {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}; found {value}"
        )
    return value


def _read_bool(
    environ: Mapping[str, str], name: str, default: bool
) -> bool:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false; found {raw!r}")


def _read_optional_int(
    environ: Mapping[str, str],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> Optional[int]:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return None
    return _read_int(
        environ, name, minimum, minimum=minimum, maximum=maximum
    )


@dataclass(frozen=True, slots=True)
class RealtimeAlertDefaults:
    chunk_duration: int
    chunk_overlap_duration: int
    frames_per_second_or_fixed_chunk: int
    use_fps_for_chunking: bool
    vlm_input_width: int
    vlm_input_height: int
    enable_reasoning: bool
    max_tokens: Optional[int]
    enable_audio: Optional[bool]


def load_realtime_alert_defaults(
    environ: Optional[Mapping[str, str]] = None,
) -> RealtimeAlertDefaults:
    env = os.environ if environ is None else environ
    chunk_duration = _read_int(
        env,
        "REALTIME_ALERT_CHUNK_DURATION",
        30,
        minimum=1,
        maximum=3600,
    )
    chunk_overlap = _read_int(
        env,
        "REALTIME_ALERT_CHUNK_OVERLAP_DURATION",
        5,
        minimum=0,
        maximum=3599,
    )
    if chunk_overlap >= chunk_duration:
        raise RuntimeError(
            "REALTIME_ALERT_CHUNK_OVERLAP_DURATION must be smaller than "
            "REALTIME_ALERT_CHUNK_DURATION"
        )

    enable_audio_raw = env.get("REALTIME_ALERT_ENABLE_AUDIO")
    enable_audio = (
        None
        if enable_audio_raw is None or not enable_audio_raw.strip()
        else _read_bool(env, "REALTIME_ALERT_ENABLE_AUDIO", False)
    )

    return RealtimeAlertDefaults(
        chunk_duration=chunk_duration,
        chunk_overlap_duration=chunk_overlap,
        frames_per_second_or_fixed_chunk=_read_int(
            env,
            "REALTIME_ALERT_FRAMES_PER_CHUNK",
            10,
            minimum=1,
            maximum=100000,
        ),
        use_fps_for_chunking=_read_bool(
            env, "REALTIME_ALERT_USE_FPS", True
        ),
        vlm_input_width=_read_int(
            env,
            "REALTIME_ALERT_VLM_INPUT_WIDTH",
            256,
            minimum=1,
            maximum=4096,
        ),
        vlm_input_height=_read_int(
            env,
            "REALTIME_ALERT_VLM_INPUT_HEIGHT",
            256,
            minimum=1,
            maximum=4096,
        ),
        enable_reasoning=_read_bool(
            env, "REALTIME_ALERT_ENABLE_REASONING", True
        ),
        max_tokens=_read_optional_int(
            env, "REALTIME_ALERT_MAX_TOKENS", minimum=1, maximum=4096
        ),
        enable_audio=enable_audio,
    )


DEFAULTS = load_realtime_alert_defaults()
