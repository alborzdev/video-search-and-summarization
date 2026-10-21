# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline cold-start coverage for the private tradeshow image's codec cache."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
import zipfile

import pytest


def _installer() -> ModuleType:
    source = Path(__file__).resolve().parents[4] / "docker" / "install_proprietary_codecs.py"
    spec = importlib.util.spec_from_file_location("vss_cached_codecs", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cached_wheel_installs_and_restarts_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _installer()
    wheel = tmp_path / "opencv.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("cv2/__init__.py", "# fixture\n")
    target = tmp_path / "installed"
    monkeypatch.setenv("VSS_PROPRIETARY_CODECS_DIR", str(target))
    monkeypatch.delenv("VSS_PROPRIETARY_CODECS_WHEEL", raising=False)
    monkeypatch.setattr(module, "DEFAULT_CACHED_WHEEL", str(wheel))
    network = Mock(side_effect=AssertionError("offline startup must not request a wheel"))
    monkeypatch.setattr(module, "_select_wheel_url", network)

    assert module.install() == str(target)
    assert (target / "cv2" / "__init__.py").is_file()
    wheel.unlink()
    assert module.install() == str(target)
    network.assert_not_called()


def test_explicit_wheel_takes_precedence_over_image_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _installer()
    wheel = tmp_path / "operator.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("operator-selected.txt", "selected")
    target = tmp_path / "installed"
    monkeypatch.setenv("VSS_PROPRIETARY_CODECS_DIR", str(target))
    monkeypatch.setenv("VSS_PROPRIETARY_CODECS_WHEEL", str(wheel))
    monkeypatch.setattr(module, "DEFAULT_CACHED_WHEEL", str(tmp_path / "missing.whl"))

    assert module.install() == str(target)
    assert (target / "operator-selected.txt").read_text() == "selected"
