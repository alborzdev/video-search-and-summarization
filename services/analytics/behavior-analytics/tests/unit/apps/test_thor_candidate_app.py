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


def test_rule_events_survive_already_reported_person_fov_activity() -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock
    import sys

    app_dir = MODULE_PATH.parent
    sys.path.insert(0, str(app_dir))
    try:
        from main_thor_candidate_app import ThorCandidateApp
        app = object.__new__(ThorCandidateApp)
        app.config = SimpleNamespace(fov_count_violation_incident_object_type="Person")
        app.reported_fov_sensors = {"camera-1"}
        app.calibration = Mock()
        app.calibration.transform_frame.side_effect = lambda frame: frame
        area = SimpleNamespace(category="Restricted Area Violation", id="area-1")
        proximity = SimpleNamespace(category="Proximity Violation", id="proximity-1")
        fov = SimpleNamespace(category="FOV Count Violation", id="already-reported")
        app.frame_state_mgmt = Mock()
        app.frame_state_mgmt.get_state.return_value = SimpleNamespace(fov_count_violation_state=True)
        app.frame_state_mgmt.get_incidents.return_value = [area, proximity, fov]
        app.write_incidents = Mock()
        frame = nvSchema.Frame(sensorId="camera-1")
        _object(frame, "person-1", "Person")

        app.generate_incidents([frame], SimpleNamespace(batch_id=1))

        app.frame_state_mgmt.get_incidents.assert_called_once_with("camera-1")
        app.write_incidents.assert_called_once_with([area, proximity])
        assert app.reported_fov_sensors == {"camera-1"}
    finally:
        sys.path.remove(str(app_dir))


def test_eight_hour_continuous_fov_track_churn_keeps_presence_within_ttl() -> None:
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from mdx.analytics.core.stream.state.frame.frame_state_management import FrameStateMgmt

    manager = object.__new__(FrameStateMgmt)
    manager.config = SimpleNamespace(incident_object_ttl=60)
    state = SimpleNamespace(object_presence={}, object_ids=[])
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    # Accelerate one fresh tracked object per second over eight hours. This
    # exercises the deployed frame state TTL independently of inference/GPU.
    for second in range(8 * 3600):
        object_id = str(second)
        state.object_ids.append(object_id)
        manager._update_object_state(state, [object_id], start + timedelta(seconds=second), 1)
        assert len(state.object_presence) <= 61
        assert len(state.object_ids) <= 61
    assert set(state.object_ids) == set(state.object_presence)
    assert "0" not in state.object_presence
