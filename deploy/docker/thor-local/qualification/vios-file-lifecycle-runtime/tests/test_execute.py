from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_file_lifecycle_execute", HERE / "execute.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def test_canonical_state_digest_is_order_independent() -> None:
    assert executor._canonical({"b": 2, "a": [1]}) == b'{"a":[1],"b":2}'


def test_owned_identity_search_is_recursive_and_exact_or_path_scoped() -> None:
    value = {"sensor": [{"id": "owned-id", "path": "/data/owned-file.mp4"}]}
    assert executor._contains_string(value, "owned-id")
    assert executor._contains_string(value, "owned-file.mp4")
    assert not executor._contains_string(value, "other-id")


def test_stale_file_sensor_metadata_requires_absent_owned_file() -> None:
    sensors = [{"sensorId": "owned-sensor"}]
    assert executor._stale_file_sensor_metadata(
        sensors, {"other": []}, "owned-sensor", "owned-file"
    )
    assert not executor._stale_file_sensor_metadata(
        sensors,
        {"owned-sensor": [{"metadata": {"id": "owned-file"}}]},
        "owned-sensor",
        "owned-file",
    )
    assert not executor._stale_file_sensor_metadata(
        [], {"other": []}, "owned-sensor", "owned-file"
    )


def test_duplicate_json_keys_fail_closed() -> None:
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json(b'{"id":1,"id":2}', "test")


def test_timeline_requires_an_ordered_range() -> None:
    assert executor._timeline_bounds(
        [{"startTime": "2025-01-01T00:00:00.000Z", "endTime": "2025-01-01T00:00:02.000Z"}]
    ) == ("2025-01-01T00:00:00.000Z", "2025-01-01T00:00:02.000Z")
    with pytest.raises(executor.QualificationError, match="timeline"):
        executor._timeline_bounds([])


def test_empty_media_probe_fails_closed() -> None:
    with pytest.raises(executor.QualificationError, match="empty test media"):
        executor._probe_media(b"", "test media")


def test_interior_clip_bounds_are_derived_from_runtime_timeline() -> None:
    assert executor._interior_clip_bounds(
        "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:02.000Z"
    ) == ("2025-01-01T00:00:00.400Z", "2025-01-01T00:00:01.600Z")
    with pytest.raises(executor.QualificationError, match="too short"):
        executor._interior_clip_bounds(
            "2025-01-01T00:00:00.000Z", "2025-01-01T00:00:01.000Z"
        )
