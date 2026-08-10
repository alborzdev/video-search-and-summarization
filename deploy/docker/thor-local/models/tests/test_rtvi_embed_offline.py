# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Static contract for Thor's cache-only RT-Embed derivative."""

import json

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
        "THOR_LOCAL_RTVI_EMBED_BIND_ADDRESS:-127.0.0.1",
    ):
        assert fragment in section

    assert "MODEL_PATH:" not in section


def test_thor_rtvi_embed_uses_loopback_for_host_and_agent() -> None:
    compose = (REPO_ROOT / "deploy/docker/thor-local/compose.yml").read_text()
    section = compose.split("\n  rtvi-embed:\n", 1)[1].split("\n  rtvi-vlm:\n", 1)[0]
    config = (
        REPO_ROOT
        / "deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml"
    ).read_text()

    assert "ports: !override" in section
    assert (
        '"${THOR_LOCAL_RTVI_EMBED_BIND_ADDRESS:-127.0.0.1}:${RTVI_EMBED_PORT?}:8000"'
        in section
    )
    assert "rtvi_embed_base_url: ${COSMOS_EMBED_ENDPOINT}" in config
    assert "rtvi_embed_base_url: http://${HOST_IP}:${RTVI_EMBED_PORT}" not in config


def test_embedding_cache_uses_base_image_as_artifact_provenance() -> None:
    launcher = (REPO_ROOT / "deploy/docker/scripts/thor-local.sh").read_text()
    contract = launcher.split("\nembedding_cache_contract() {\n", 1)[1].split(
        "\n}\n\nstream_embedding_volume_tree()", 1
    )[0]
    verifier = launcher.split("\nstaged_embedding_cache_is_present() {\n", 1)[1].split(
        "\n}\n\nrequire_staged_embedding_cache()", 1
    )[0]

    assert 'print(service["image"])' in contract
    assert 'print(service["build"]["args"]["BASE_IMAGE"])' in contract
    assert 'docker image inspect "${embed_image}"' in verifier
    assert '--image "${provenance_image}"' in verifier
    assert '--image "${embed_image}"' not in verifier


def test_cosmos_embed_triton_config_modes_match_shipped_templates() -> None:
    lock = json.loads(
        (REPO_ROOT / "deploy/docker/thor-local/models/artifacts.lock.json").read_text()
    )
    files = {
        row["path"]: row
        for row in lock["artifacts"]["cosmos_embed_triton"]["tree"]["files"]
    }
    template_root = (
        REPO_ROOT
        / "services/rtvi/rt-embed/src/models/custom/samples/cosmos-embed1/triton_model_repo"
    )
    for relative in (
        "text_embeddings/config.pbtxt",
        "video_embeddings/config.pbtxt",
    ):
        template = template_root / relative
        assert template.stat().st_mode & 0o777 == 0o664
        assert files[relative]["mode"] == 0o664
        assert files[relative]["type"] == "file"
