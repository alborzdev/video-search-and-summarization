# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Thor candidate metadata adapter."""

import importlib.util
from pathlib import Path

from mdx.analytics.core.schema.proto import schema_pb2 as nvSchema

MODULE_PATH = Path(__file__).parents[3] / "apps" / "thor_candidate" / "fov_adapter.py"
SPEC = importlib.util.spec_from_file_location("fov_adapter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ensure_fov_metric = MODULE.ensure_fov_metric

GATE_MODULE_PATH = Path(__file__).parents[3] / "apps" / "thor_candidate" / "incident_gate.py"
GATE_SPEC = importlib.util.spec_from_file_location("incident_gate", GATE_MODULE_PATH)
assert GATE_SPEC is not None and GATE_SPEC.loader is not None
GATE_MODULE = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(GATE_MODULE)
first_incident_per_activity = GATE_MODULE.first_incident_per_activity


def _object(frame: nvSchema.Frame, object_id: str, object_type: str) -> None:
    obj = frame.objects.add()
    obj.id = object_id
    obj.type = object_type


def test_builds_fov_metric_case_insensitively() -> None:
    frame = nvSchema.Frame()
    _object(frame, "person-1", "Person")
    _object(frame, "person-2", "person")
    _object(frame, "forklift-1", "Forklift")
    _object(frame, "", "Person")

    ensure_fov_metric(frame, "person")

    assert len(frame.fov) == 1
    assert frame.fov[0].type == "person"
    assert frame.fov[0].count == 2
    assert list(frame.fov[0].objectIds) == ["person-1", "person-2"]


def test_preserves_existing_producer_metric() -> None:
    frame = nvSchema.Frame()
    unrelated = frame.fov.add()
    unrelated.type = "Forklift"
    metric = frame.fov.add()
    metric.type = "Person"
    metric.count = 7
    metric.objectIds.append("producer-owned")
    _object(frame, "person-1", "person")

    ensure_fov_metric(frame, "person")

    assert len(frame.fov) == 2
    assert frame.fov[1].type == "person"
    assert frame.fov[1].count == 7
    assert list(frame.fov[1].objectIds) == ["producer-owned"]


def test_does_not_add_empty_metric() -> None:
    frame = nvSchema.Frame()
    _object(frame, "forklift-1", "Forklift")

    ensure_fov_metric(frame, "person")

    assert not frame.fov


def test_candidate_gate_emits_once_until_activity_expires() -> None:
    reported: set[str] = set()

    assert first_incident_per_activity("camera-1", ["first", "extra"], True, reported) == ["first"]
    assert first_incident_per_activity("camera-1", ["update"], True, reported) == []
    assert first_incident_per_activity("camera-1", [], True, reported) == []
    assert first_incident_per_activity("camera-1", ["completed"], False, reported) == []
    assert reported == set()

    assert first_incident_per_activity("camera-1", ["next"], True, reported) == ["next"]


def test_candidate_gate_keeps_unreported_completed_incident() -> None:
    reported: set[str] = set()

    assert first_incident_per_activity("camera-1", ["completed", "extra"], False, reported) == ["completed"]
    assert first_incident_per_activity("camera-1", [], False, reported) == []
