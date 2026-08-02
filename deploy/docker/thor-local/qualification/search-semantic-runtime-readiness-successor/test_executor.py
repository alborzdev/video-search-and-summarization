# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "search_readiness_executor", PACKAGE_DIR / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)


def test_executor_reproduces_checked_in_receipt() -> None:
    expected = json.loads(
        (PACKAGE_DIR / "execution-receipt.json").read_text(encoding="utf-8")
    )
    assert executor.execute() == expected


def test_routes_bind_to_actual_nat_input_models() -> None:
    result = executor.execute()
    assert len(result["route_bindings"]) == 8
    assert {"query", "source_type", "video_sources"} <= set(
        result["input_contracts"]["AttributeSearchInput"]
    )
    assert {"query", "source_type", "agent_mode", "reference_object"} <= set(
        result["input_contracts"]["SearchInput"]
    )
    assert {"object_id", "sensor_name", "sensor_id", "timestamp"} == set(
        result["input_contracts"]["ReferenceObject"]
    )
    assert (
        result["selected_bbox_fixture"]["request_semantics"]
        == "reference_object_metadata_not_raw_image"
    )


def test_selected_bbox_image_bytes_match_digest() -> None:
    fixture = json.loads(
        (PACKAGE_DIR / "selected-bbox-fixture.json").read_text(encoding="utf-8")
    )
    image = base64.b64decode(fixture["image_base64"], validate=True)
    assert len(image) == 274
    assert executor._sha256(image) == fixture["image_sha256"]


def test_missing_required_model_field_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = executor._model_fields

    def missing(relative: str, class_name: str) -> set[str]:
        fields = original(relative, class_name)
        if class_name == "ReferenceObject":
            fields.remove("timestamp")
        return fields

    monkeypatch.setattr(executor, "_model_fields", missing)
    with pytest.raises(executor.ContractError, match="missing fields"):
        executor.execute()


def test_route_misbinding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = executor._endpoint_bindings

    def misbound(relative: str) -> dict[str, str]:
        bindings = copy.deepcopy(original(relative))
        bindings["/api/v1/search/image"] = "embed_search"
        return bindings

    monkeypatch.setattr(executor, "_endpoint_bindings", misbound)
    with pytest.raises(executor.ContractError, match="route binding mismatch"):
        executor.execute()


def test_source_has_no_runtime_or_write_adapter() -> None:
    source = (PACKAGE_DIR / "executor.py").read_text(encoding="utf-8")
    forbidden = [
        "import requests",
        "import httpx",
        "import urllib",
        "import socket",
        "import subprocess",
        "import docker",
        ".write_text(",
        ".write_bytes(",
    ]
    assert not any(token in source for token in forbidden)
