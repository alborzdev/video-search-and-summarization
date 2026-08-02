# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Static contract for Thor's cache-only RT-Embed derivative."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]


def test_thor_rtvi_embed_is_source_overlaid_and_offline() -> None:
    compose = (REPO_ROOT / "deploy/docker/thor-local/compose.yml").read_text()
    section = compose.split("\n  rtvi-embed:\n", 1)[1].split("\n  rtvi-vlm:\n", 1)[0]

    for fragment in (
        "THOR_LOCAL_RTVI_EMBED_IMAGE",
        "services/rtvi/rt-embed",
        "docker/Dockerfile",
        'RTVI_OFFLINE: "true"',
        'HF_HUB_OFFLINE: "1"',
        'TRANSFORMERS_OFFLINE: "1"',
        'NGC_CLI_API_KEY: ""',
        'NGC_API_KEY: ""',
        'NVIDIA_API_KEY: ""',
        'HF_TOKEN: ""',
    ):
        assert fragment in section

    assert "MODEL_PATH:" not in section
