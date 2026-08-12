# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared media-transport configuration for Alert Bridge VLM calls."""

import os
from typing import Any, Mapping


_TRUE_VALUES = frozenset(("1", "true", "yes"))
_FALSE_VALUES = frozenset(("0", "false", "no"))


def resolve_vlm_media_source_using_base64(config: Mapping[str, Any]) -> bool:
    """Resolve whether VLM media must be downloaded and sent inline.

    NVIDIA's shared profiles keep ``vlm_media_source_using_base64`` in the
    ``vlm`` configuration block.  Thor's local OpenAI-compatible VLM refuses
    private and loopback URLs, so its compose overlay can force the safe
    download-and-inline path without changing the shared profile template.

    Invalid environment values fail startup instead of silently selecting a
    transport that cannot reach local VIOS media.
    """

    override = os.getenv("ALERT_VLM_MEDIA_SOURCE_USING_BASE64")
    if override is None:
        return config.get("vlm", {}).get(
            "vlm_media_source_using_base64", False
        )

    normalized = override.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        "ALERT_VLM_MEDIA_SOURCE_USING_BASE64 must be a boolean value"
    )
