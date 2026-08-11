# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Security tests for exact-host private HTTP media origins."""

import asyncio
import os
import socket
from unittest.mock import patch

import pytest

from api_models.common import is_asset_download_private_host_allowed
from api_models.embeddings import validate_url_against_ssrf
from common.service_exception import ServiceException
from utils.asset_manager import (
    validate_url_ssrf_runtime,
    validate_url_ssrf_runtime_async,
)


ENV_NAME = "ASSET_DOWNLOAD_ALLOWED_PRIVATE_HOSTS"
PRIVATE_DNS_RESULT = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.1", 0)),
]


def test_allowlist_is_exact_dns_hostname_only(monkeypatch):
    monkeypatch.setenv(
        ENV_NAME,
        "Host.Docker.Internal.,*.example.test,10.0.0.1,10.0.0.0/8",
    )
    assert is_asset_download_private_host_allowed("host.docker.internal") is True
    assert is_asset_download_private_host_allowed("HOST.DOCKER.INTERNAL.") is True
    assert is_asset_download_private_host_allowed("sub.host.docker.internal") is False
    assert is_asset_download_private_host_allowed("example.test") is False
    assert is_asset_download_private_host_allowed("10.0.0.1") is False


def test_static_validation_rejects_private_dns_without_allowlist(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    with patch("api_models.embeddings.socket.getaddrinfo", return_value=PRIVATE_DNS_RESULT):
        with pytest.raises(ValueError, match="SSRF protection"):
            validate_url_against_ssrf("http://fixture.internal/video.mp4")


def test_static_validation_accepts_only_exact_allowed_private_host(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "fixture.internal")
    with patch(
        "api_models.embeddings.socket.getaddrinfo",
        side_effect=AssertionError("allowed exact host must not resolve during model validation"),
    ):
        validate_url_against_ssrf("http://fixture.internal/video.mp4")

    with patch("api_models.embeddings.socket.getaddrinfo", return_value=PRIVATE_DNS_RESULT):
        with pytest.raises(ValueError, match="SSRF protection"):
            validate_url_against_ssrf("http://child.fixture.internal/video.mp4")


def test_ip_literals_cannot_bypass_ssrf_with_allowlist(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "127.0.0.1,10.0.0.1")
    with pytest.raises(ValueError, match="SSRF protection"):
        validate_url_against_ssrf("http://127.0.0.1/video.mp4")
    with pytest.raises(ValueError, match="SSRF protection"):
        validate_url_against_ssrf("http://10.0.0.1/video.mp4")


def test_sync_runtime_revalidates_exact_host(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "fixture.internal")
    with patch(
        "utils.asset_manager.socket.getaddrinfo",
        side_effect=AssertionError("allowed exact host must not resolve in runtime guard"),
    ):
        validate_url_ssrf_runtime("http://fixture.internal/video.mp4")

    monkeypatch.delenv(ENV_NAME)
    with pytest.raises(ServiceException) as exc_info:
        validate_url_ssrf_runtime("http://127.0.0.1/video.mp4")
    assert exc_info.value.status_code == 422


def test_async_runtime_revalidates_exact_host_and_redirect_targets(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "fixture.internal")
    asyncio.run(validate_url_ssrf_runtime_async("http://fixture.internal/video.mp4"))

    # A redirect target is passed through this guard as a new URL. An unlisted
    # loopback target must remain blocked even when the original host is allowed.
    with pytest.raises(ServiceException) as exc_info:
        asyncio.run(validate_url_ssrf_runtime_async("http://127.0.0.1/redirected.mp4"))
    assert exc_info.value.status_code == 422


def test_environment_is_not_mutated_by_validation(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "fixture.internal")
    before = os.environ[ENV_NAME]
    assert is_asset_download_private_host_allowed("fixture.internal") is True
    assert os.environ[ENV_NAME] == before
