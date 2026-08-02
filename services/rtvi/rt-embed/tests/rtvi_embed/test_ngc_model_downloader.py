# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Cache-only guarantees for the RT-Embed model downloader."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src/vlm_pipeline/ngc_model_downloader.py"
)
SPEC = importlib.util.spec_from_file_location(
    "rt_embed_ngc_model_downloader", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
DOWNLOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOWNLOADER)


@pytest.mark.no_gpu
@pytest.mark.test_in_ci
class TestOfflineModelAcquisition:
    def test_cached_ngc_model_is_reused_offline(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("RTVI_OFFLINE", "true")
        cached = tmp_path / "nvidia_cosmos-embed1_v1_0"
        cached.mkdir()

        assert DOWNLOADER.download_model(
            "nvidia/cosmos-embed1:v1.0", str(tmp_path)
        ) == str(cached)

    def test_cached_git_model_is_reused_offline(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("RTVI_OFFLINE", "1")
        cached = tmp_path / "Cosmos-Embed1-448p"
        cached.mkdir()

        with patch.object(DOWNLOADER.subprocess, "run") as run:
            observed = DOWNLOADER.download_model_git(
                "https://huggingface.co/nvidia/Cosmos-Embed1-448p",
                str(tmp_path),
            )

        assert observed == str(cached)
        run.assert_not_called()

    def test_missing_ngc_model_fails_before_credentials_or_client(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setenv("RTVI_OFFLINE", "yes")
        monkeypatch.delenv("NGC_API_KEY", raising=False)

        with pytest.raises(FileNotFoundError, match="RTVI_OFFLINE"):
            DOWNLOADER.download_model("nvidia/cosmos-embed1:v1.0", str(tmp_path))

    def test_missing_git_model_fails_before_downloader(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setenv("RTVI_OFFLINE", "on")

        with (
            patch.object(DOWNLOADER.subprocess, "run") as run,
            pytest.raises(FileNotFoundError, match="RTVI_OFFLINE"),
        ):
            DOWNLOADER.download_model_git(
                "https://huggingface.co/nvidia/Cosmos-Embed1-448p",
                str(tmp_path),
            )

        run.assert_not_called()
