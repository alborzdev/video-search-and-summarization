# SPDX-License-Identifier: Apache-2.0
"""CPU contract tests: no generated footage is passed off as model inference."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.city.engine import CityEngine, ConflictError
from apps.city.engine import EVENT_STATE_HISTORY_LIMIT
from apps.city.geometry import directed_crossing, point_in_polygon, project, segments_intersect
from apps.city.main import create_app
from apps.city.models import Observation, RuleSet, Site
from apps.city.nvschema import from_frame
from apps.city.store import CityStore
from apps.city.native import NativeAnalyticsBridge, compile_analytics
from apps.city.fixtures import fixture_rules, observations, package_site, image_anchor


class Clock:
    value = 100.0
    def __call__(self):
        return self.value


@pytest.fixture
def engine():
    clock = Clock()
    engine = CityEngine(clock=clock, history_frames=4, max_tracks=10)
    engine.put_site(Site.model_validate({"id": "test", "mode": "fixture-replay", "sources": [{"id": "cam-1", "width": 100, "height": 100, "imageToGroundHomography": [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], "calibrationRevision": "fixture-1"}], "map": {"bounds": [0, 0, 10, 10]}}))
    return engine, clock


def frame(seconds, x=30, y=40, *, seq=None, session="session-1", objects=True, **extra):
    return Observation.model_validate({"siteId": "test", "sourceId": "cam-1", "sourceSessionId": session, "sequence": str(seq if seq is not None else round(seconds * 10)), "sourceTimeNs": str(1_700_000_000_000_000_000 + round(seconds * 1e9)), "timestampBasis": "fixture-epoch-plus-pts", "mediaTimeSeconds": seconds, "image": {"width": 100, "height": 100}, "objects": [{"localTrackId": "18446744073709551614", "class": "car", "confidence": 0.9, "bboxPx": [x - 5, y - 10, 10, 10]}] if objects else [], **extra})


def rule(kind="dwell", **conditions):
    geometry = {"space": "image-normalized", "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}
    if kind == "line-crossing":
        geometry = {"space": "image-normalized", "points": [[0.5, 0.1], [0.5, 0.9]], "direction": [1, 0]}
    if kind == "wrong-way":
        geometry["direction"] = [1, 0]
    return {"id": "rule-1", "name": "Test zone", "kind": kind, "sourceId": "cam-1", "classes": ["car"], "geometry": geometry, "conditions": conditions}


def set_rule(engine, value):
    return engine.put_rules(RuleSet.model_validate({"rules": [value]}))


def test_projection_never_substitutes_pixels():
    assert project([20, 30], None) == (None, "missing-calibration")
    assert project([20, 30], [[1, 0, 0], [0, 0, 0], [0, 0, 1]]) == (None, "invalid-calibration")
    assert project([2, 3], [[1, 0, 0], [0, 1, 0], [0, 1, -3]]) == (None, "unstable-projection")
    assert project([20, 30], [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]]) == ([2.0, 3.0], "valid")
    assert project([20, 30], [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[0, 0], [10, 0], [10, 10], [0, 10]])[1] == "outside-valid-region"
    assert project([20, 30], [[1, 0, 0], [0, 1, 0], [0, 0, 1]], bounds=[0, 0, 10, 10])[1] == "outside-map-bounds"


@pytest.mark.parametrize("scale", [1e-12, -1e-12, 1, -1, 1e308])
def test_projection_is_independent_of_equivalent_homography_scale(scale):
    homography = [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]]
    scaled = [[value * scale for value in row] for row in homography]
    source = Site.model_validate({"sources": [{"id": "cam", "imageToGroundHomography": scaled}]})
    point, status = project([20, 30], source.sources[0].imageToGroundHomography)
    assert status == "valid"
    assert point == pytest.approx([2, 3])
    horizon = [[1, 0, 0], [0, 1, 0], [0, 0.5, -1]]
    assert project([2, 2], [[value * scale for value in row] for row in horizon])[1] == "unstable-projection"


def test_person_navigation_plane_is_independent_of_vehicle_road_plane(engine):
    engine, _ = engine
    site = engine.site_json()
    site['sources'][0]['classImageToGroundHomographies'] = {'person': [[.1, 0, 1], [0, .1, 2], [0, 0, 1]]}
    engine.put_site(Site.model_validate(site))
    sample = frame(0).model_dump(by_alias=True)
    sample['objects'].append({**sample['objects'][0], 'localTrackId': 'person', 'class': 'person'})
    engine.ingest(Observation.model_validate(sample))
    by_class = {track['class']: track for track in engine.snapshot()['tracks']}
    assert by_class['car']['positionM'] == pytest.approx([3, 4])
    assert by_class['person']['positionM'] == pytest.approx([4, 6])


def test_class_ground_calibration_requires_canonical_class_and_valid_matrix():
    for value in ({'unknown': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, {'person': [[0, 0, 0]] * 3}):
        with pytest.raises(ValidationError):
            Site.model_validate({'sources': [{'id': 'camera', 'classImageToGroundHomographies': value}]})


def test_coarse_two_wheeler_is_a_distinct_rule_and_calibration_class(engine):
    engine, _ = engine
    site = engine.site_json()
    site['sources'][0]['classImageToGroundHomographies'] = {'two-wheeler': [[.1, 0, 1], [0, .1, 2], [0, 0, 1]]}
    engine.put_site(Site.model_validate(site))
    value = rule('occupancy-threshold', countThreshold=1)
    value['classes'] = ['two-wheeler']
    set_rule(engine, value)
    sample = frame(0).model_dump(by_alias=True)
    sample['objects'][0]['class'] = 'two-wheeler'
    engine.ingest(Observation.model_validate(sample))
    track = engine.snapshot()['tracks'][0]
    assert track['class'] == 'two-wheeler'
    assert track['positionM'] == pytest.approx([4, 6])
    assert engine.snapshot()['metrics'][0]['occupancy'] == 1


def test_polygon_boundary_and_validation():
    square = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert point_in_polygon([0, 0.5], square)
    assert point_in_polygon([0.4, 0.4], square)
    assert not point_in_polygon([1.1, 0.5], square)
    invalid = rule()
    invalid["geometry"]["points"] = [[0, 0], [1, 1], [0, 1], [1, 0]]
    with pytest.raises(ValidationError):
        RuleSet.model_validate({"rules": [invalid]})


@pytest.mark.parametrize("offset", [0, 0.4])
def test_small_nonzero_area_crossed_polygon_is_rejected(offset):
    scale = 0.005
    points = [[offset + scale * x, offset + scale * y] for x, y in [[0.1, 0.1], [0.9, 0.8], [0.1, 0.9], [0.8, 0.1]]]
    # Its signed area is nonzero; only a correct edge-intersection check rejects it.
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    assert abs(area) > 1e-9
    invalid = rule()
    invalid["geometry"]["points"] = points
    with pytest.raises(ValidationError, match="self-intersect"):
        RuleSet.model_validate({"rules": [invalid]})
    valid = rule()
    valid["geometry"]["points"] = [[offset + scale * x, offset + scale * y] for x, y in [[0, 0], [1, 0], [1, 1], [0, 1]]]
    RuleSet.model_validate({"rules": [valid]})
    a, b = [offset, offset], [offset + scale, offset]
    assert segments_intersect(a, b, b, [offset + scale, offset + scale])
    assert not segments_intersect(a, b, [offset, offset + scale], [offset + scale, offset + scale])


def test_directed_finite_crossing():
    line = [[0.5, 0], [0.5, 1]]
    assert directed_crossing([0.4, 0.5], [0.6, 0.5], line, [1, 0])
    assert not directed_crossing([0.6, 0.5], [0.4, 0.5], line, [1, 0])
    assert not directed_crossing([0.4, 2], [0.6, 2], line, [1, 0])
    assert not directed_crossing([0.4, 0.5], [0.5, 0.5], line, [1, 0])


def test_crossing_boundary_frame_duplicate_and_reverse(engine):
    engine, _ = engine
    set_rule(engine, rule("line-crossing"))
    for seconds, x in [(0, 40), (0.1, 50), (0.2, 60), (0.3, 40)]:
        engine.ingest(frame(seconds, x=x))
    assert len(engine.events) == 1
    assert engine.metrics["rule-1"]["totalCrossings"] == 1
    assert not engine.ingest(frame(0.3, x=40))["accepted"]
    assert list(engine.events.values())[0]["state"] == "cleared"


@pytest.mark.parametrize("kind,positions", [("area-entry", [30, 90, 30]), ("line-crossing", [40, 60, 40, 60])])
def test_distinct_sequences_with_duplicate_timestamp_do_not_collapse_incidents(engine, kind, positions):
    engine, _ = engine
    set_rule(engine, rule(kind, clearAfterMs=0))
    for sequence, x in enumerate(positions):
        assert engine.ingest(frame(0, seq=sequence, x=x))["accepted"]
    assert len(engine.events) == 2
    assert len(engine.store.events()) == 2
    if kind == "line-crossing":
        assert engine.metrics["rule-1"]["totalCrossings"] == 2
        assert all(event["state"] == "cleared" for event in engine.events.values())
    else:
        assert sorted(event["state"] for event in engine.events.values()) == ["active", "cleared"]
        assert engine.metrics["rule-1"]["activeEventCount"] == 1
    assert not engine.ingest(frame(0, seq=len(positions) - 1, x=positions[-1]))["accepted"]
    assert len(engine.events) == 2


def test_dwell_source_time_not_wallclock_and_real_exit_clear(engine):
    engine, clock = engine
    set_rule(engine, rule(minimumDurationMs=1000, clearAfterMs=100, maximumObservationGapMs=1500))
    engine.ingest(frame(0))
    clock.value += 0.001
    engine.ingest(frame(0.5))
    assert not engine.events
    engine.ingest(frame(1.0))
    assert list(engine.events.values())[0]["state"] == "active"
    engine.ingest(frame(1.1, x=90))
    engine.ingest(frame(1.2, x=90))
    assert list(engine.events.values())[0]["state"] == "cleared"


def test_loss_and_disconnect_are_unknown_not_departure(engine):
    engine, clock = engine
    set_rule(engine, rule("occupancy-threshold", maximumObservationGapMs=200, clearAfterMs=0))
    engine.ingest(frame(0))
    engine.ingest(frame(0.3, objects=False))
    assert list(engine.events.values())[0]["state"] == "unknown"
    engine.ingest(frame(0.4))
    assert list(engine.events.values())[0]["state"] == "active"
    clock.value += 3
    snapshot = engine.snapshot()
    assert snapshot["sources"][0]["status"] == "stale"
    assert snapshot["tracks"][0]["stale"] is True
    assert list(engine.events.values())[0]["state"] == "unknown"


def test_stopped_requires_calibrated_velocity(engine):
    engine, _ = engine
    set_rule(engine, rule("stopped-in-zone", minimumDurationMs=100, speedBelowMps=0.5))
    engine.ingest(frame(0))
    assert not engine.events
    engine.ingest(frame(0.1))
    assert not engine.events
    engine.ingest(frame(0.2))
    assert list(engine.events.values())[0]["state"] == "active"
    assert next(iter(engine.tracks.values()))["speedMps"] == 0


def test_queue_counts_only_slow_inside_tracks(engine):
    engine, _ = engine
    set_rule(engine, rule("queue", countThreshold=2, speedBelowMps=0.5))
    for seconds in [0, 0.1]:
        sample = frame(seconds).model_dump(by_alias=True)
        sample["objects"].append({**sample["objects"][0], "localTrackId": "second", "bboxPx": [40, 30, 10, 10]})
        engine.ingest(Observation.model_validate(sample))
    assert list(engine.events.values())[0]["metrics"]["count"] == 2


def test_queue_metrics_exclude_moving_occupants_in_current_and_replay(engine):
    engine, _ = engine
    set_rule(engine, rule("queue", countThreshold=2, speedBelowMps=0.5))
    for seconds in [0, 0.1]:
        sample = frame(seconds).model_dump(by_alias=True)
        sample["objects"].extend([
            {**sample["objects"][0], "localTrackId": "stopped-second", "bboxPx": [40, 30, 10, 10]},
            {**sample["objects"][0], "localTrackId": "moving", "bboxPx": [50 + seconds * 100, 30, 10, 10]},
        ])
        engine.ingest(Observation.model_validate(sample))
    for snapshot in (engine.snapshot(), engine.snapshot(media_time=0.1)):
        metric = snapshot["metrics"][0]
        assert metric["count"] == 2 and metric["occupancy"] == 3
        assert snapshot["events"][0]["metrics"]["count"] == 2


def test_wrong_way_uses_direction_and_velocity(engine):
    engine, _ = engine
    set_rule(engine, rule("wrong-way", minimumDurationMs=100))
    for seconds, x in [(0, 60), (0.1, 59), (0.2, 58)]:
        engine.ingest(frame(seconds, x=x))
    assert list(engine.events.values())[0]["kind"] == "wrong-way"


def test_session_reset_no_dwell_inheritance_or_late_retired_epoch(engine):
    engine, _ = engine
    set_rule(engine, rule(minimumDurationMs=500))
    engine.ingest(frame(0))
    engine.ingest(frame(0.5))
    engine.ingest(frame(0.6, session="session-2"))
    assert len(engine.tracks) == 1
    assert next(iter(engine.tracks.values()))["velocityMps"] is None
    assert list(engine.events.values())[0]["state"] == "unknown"
    assert not engine.ingest(frame(0.7, session="session-1"))["accepted"]
    assert len(engine.events) == 1


def test_reset_and_small_out_of_order_handling(engine):
    engine, _ = engine
    engine.ingest(frame(10))
    assert not engine.ingest(frame(9.9))["accepted"]
    result = engine.ingest(frame(0))
    assert result["accepted"] and result["sessionId"].endswith("reset-1")
    result = engine.ingest(frame(0.1))
    assert result["sessionId"].endswith("reset-1")


def test_explicit_reset_retry_is_idempotent_but_new_session_seq_zero_is_valid(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry"))
    first = frame(0, seq=0, reset=True)
    assert engine.ingest(first)["accepted"]
    assert engine.ingest(first) == {"accepted": False, "reason": "duplicate-reset", "sourceId": "cam-1", "sequence": "0"}
    engine.ingest(frame(0.1, seq=1))
    assert not engine.ingest(first)["accepted"]  # also safe after later frames
    reset = frame(0.2, seq=0, reset=True)
    assert engine.ingest(reset)["sessionId"].endswith("reset-1")
    assert not engine.ingest(reset)["accepted"]
    assert engine.ingest(frame(0.3, seq=0, session="new-session", reset=True))["accepted"]
    assert len(engine.events) == 3
    assert len(engine.sources["cam-1"]["recentResetFrames"]) == 3
    assert len({track["sessionId"] for track in engine.tracks.values()}) == 1


def test_history_bounded_aligned_and_not_latest_on_wrong_clock(engine):
    engine, _ = engine
    for i in range(8):
        engine.ingest(frame(i / 10))
    assert len(engine.histories["cam-1"]) == 4
    aligned = engine.snapshot(media_time=0.6, maximum_skew=0.01)
    assert aligned["clockAligned"] is True and len(aligned["tracks"]) == 1
    assert engine.snapshot(media_time=10, maximum_skew=0.01)["tracks"] == []
    assert engine.snapshot(media_time=10)["clockAligned"] is False


def test_live_media_lookup_skips_frames_without_media_time(engine):
    engine, _ = engine
    site = engine.site.model_dump()
    site["mode"] = "live"
    engine.put_site(Site.model_validate(site))
    first = frame(0).model_copy(update={"mediaTimeSeconds": None})
    engine.ingest(first)
    missing = engine.snapshot(media_time=0)
    assert missing["clockAligned"] is False and missing["tracks"] == []
    engine.ingest(frame(0.1))
    aligned = engine.snapshot(media_time=0.1, maximum_skew=0.01)
    assert aligned["clockAligned"] is True
    assert aligned["tracks"][0]["sourceTimeNs"] == frame(0.1).sourceTimeNs


def test_source_snapshot_filters_events_before_display_limit(engine):
    engine, _ = engine
    site = engine.site.model_dump()
    site["sources"].append({**site["sources"][0], "id": "cam-2"})
    engine.put_site(Site.model_validate(site))
    for index in range(105):
        event = {"id": str(index), "siteId": "test", "sourceId": "cam-1" if index == 0 else "cam-2", "sessionId": "session-1", "state": "cleared", "triggeredAtNs": str(index), "updatedAtNs": str(index)}
        engine.events[event["id"]] = event
    assert len(engine.snapshot()["events"]) == 100
    assert [event["id"] for event in engine.snapshot(source_id="cam-1")["events"]] == ["0"]


def test_track_and_trails_bounded(engine):
    engine, clock = engine
    for i in range(60):
        sample = frame(i / 10).model_dump(by_alias=True)
        sample["objects"][0]["localTrackId"] = str(i % 15)
        engine.ingest(Observation.model_validate(sample))
    assert len(engine.tracks) <= 10
    assert all(len(track["trail"]) <= 40 for track in engine.tracks.values())
    clock.value += 16
    assert not engine.snapshot()["tracks"]


def test_rule_compare_and_swap_and_missing_calibration(engine):
    engine, _ = engine
    result = set_rule(engine, rule())
    with pytest.raises(ConflictError):
        engine.put_rules(RuleSet.model_validate({"rules": [rule()], "expectedRevision": result["revision"] - 1}))
    site = engine.site.model_dump()
    site["sources"][0]["imageToGroundHomography"] = None
    engine.put_site(Site.model_validate(site))
    with pytest.raises(ValueError, match="calibration"):
        set_rule(engine, rule("queue"))


def test_rules_and_events_durable_restart_unknown(tmp_path):
    store = CityStore(str(tmp_path / "city.db"))
    original = CityEngine(store)
    original.put_site(Site.model_validate({"id": "test", "sources": [{"id": "cam-1", "width": 100, "height": 100}]}))
    set_rule(original, rule("area-entry"))
    original.ingest(frame(0))
    assert len(original.events) == 1
    restored = CityEngine(CityStore(str(tmp_path / "city.db")))
    assert restored.site.id == "test" and len(restored.rules) == 1
    assert list(restored.events.values())[0]["state"] == "unknown"


def test_api_empty_initial_state_validation_media_range_reports(tmp_path, engine):
    configured, _ = engine
    app = create_app(configured, media_registry={}, media_root=str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/city/site").json()["id"] == "test"
        assert client.get("/api/v1/city/snapshot").json()["awaitingObservations"] is True
        assert client.get("/api/v1/city/snapshot").json()["setupRequired"] is False
        assert client.post("/api/v1/city/observations", json=frame(0).model_dump(by_alias=True)).json()["accepted"]
        invalid = frame(0.1).model_dump(by_alias=True)
        invalid["image"]["width"] = 200
        assert client.post("/api/v1/city/observations", json=invalid).status_code == 422
        assert client.get("/api/v1/city/media/cam-1").status_code == 404
        assert client.get("/api/v1/city/reports?format=csv").status_code == 200
    (tmp_path / "clip.mp4").write_bytes(b"0123456789abcdef")
    app = create_app(configured, {"cam-1": "clip.mp4"}, str(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/v1/city/media/cam-1", headers={"Range": "bytes=2-5"})
        assert response.status_code == 206 and response.content == b"2345"
        assert client.get("/api/v1/city/site").json()["sources"][0]["mediaUrl"] == "/api/vision/city/media/cam-1"
    with pytest.raises(ValueError, match="outside"):
        create_app(configured, {"cam-1": "../secret.mp4"}, str(tmp_path))


def test_health_keeps_loss_semantics_without_building_track_event_snapshot(engine, monkeypatch):
    engine, clock = engine
    set_rule(engine, rule("area-entry"))
    engine.ingest(frame(0))
    app = create_app(engine, media_registry={})
    def forbidden(*args, **kwargs):
        raise AssertionError("health must not build or query the full display snapshot")
    monkeypatch.setattr(engine, "snapshot", forbidden)
    monkeypatch.setattr(engine, "_track_json", forbidden)
    monkeypatch.setattr(engine.store, "events", forbidden)
    with TestClient(app) as client:
        state = client.get("/api/v1/city/health").json()
        assert state["sources"] == [{"id": "cam-1", "status": "live"}]
        assert state["setupRequired"] is False and state["awaitingObservations"] is False
        clock.value += 3
        state = client.get("/api/v1/city/health").json()
        assert state["sources"] == [{"id": "cam-1", "status": "stale"}]
        assert next(iter(engine.events.values()))["state"] == "unknown"
        assert engine.metrics["rule-1"]["status"] == "unknown"
        assert engine.metrics["rule-1"]["activeEventCount"] == 0
        clock.value += 16
        client.get("/api/v1/city/health").raise_for_status()
        assert not engine.tracks


def test_events_api_filters_retained_history_before_limiting(engine):
    engine, _ = engine
    # These events are retained on disk but intentionally outside display memory.
    for index in range(1002):
        engine.store.save_event({"id": str(index), "siteId": "test", "sourceId": "wanted" if index == 0 else "other", "ruleId": "old-rule" if index == 0 else "new-rule", "state": "unknown" if index == 0 else "cleared", "triggeredAtNs": str(index), "updatedAtNs": str(index)})
    with TestClient(create_app(engine, media_registry={})) as client:
        for query in ("sourceId=wanted", "ruleId=old-rule", "state=unknown", "sourceId=wanted&ruleId=old-rule&state=unknown"):
            body = client.get("/api/v1/city/events?limit=1&" + query).json()
            assert [event["id"] for event in body["events"]] == ["0"]
            assert body["limit"] == 1


def test_nvschema_adapter_integer_nanoseconds_and_canonical_class():
    obj = SimpleNamespace(id="18446744073709551614", type="Vehicle", confidence=0.9, bbox=SimpleNamespace(leftX=10, topY=20, rightX=30, bottomY=50), info={"ct.city.class": "bus"})
    source = SimpleNamespace(id="12", timestamp=SimpleNamespace(seconds=1700000000, nanos=123456789), objects=[obj], info={})
    converted = from_frame(source, site_id="test", source_id="cam-1", session_id="epoch", width=100, height=100)
    validated = Observation.model_validate(converted)
    assert validated.sourceTimeNs == "1700000000123456789"
    assert validated.objects[0].class_name == "bus"
    assert validated.objects[0].bboxPx == [10, 20, 20, 30]


def test_global_track_association_remains_optional_preserved(engine):
    engine, _ = engine
    sample = frame(0).model_dump(by_alias=True)
    sample["objects"][0].update(globalTrackId="mv3dt-person-123", associationMethod="mv3dt", positionUncertaintyM=0.8)
    engine.ingest(Observation.model_validate(sample))
    track = engine.snapshot()["tracks"][0]
    assert track["globalTrackId"] == "mv3dt-person-123"
    assert track["localTrackId"] == "18446744073709551614"
    assert track["positionUncertaintyM"] == 0.8


def test_candidate_dwell_does_not_count_unobserved_gap(engine):
    engine, _ = engine
    set_rule(engine, rule(minimumDurationMs=1000, maximumObservationGapMs=500))
    engine.ingest(frame(0))
    engine.ingest(frame(3))
    assert not engine.events
    assert engine.metrics["rule-1"]["oldestDwellMs"] == 0


def test_tracker_predictions_do_not_extend_the_detection_gap(engine):
    engine, _ = engine
    set_rule(engine, rule("occupancy-threshold", maximumObservationGapMs=200, clearAfterMs=0))
    engine.ingest(frame(0))
    for seconds in (0.1, 0.2, 0.3, 0.4):
        sample = frame(seconds)
        sample.objects[0].observedThisFrame = False
        engine.ingest(sample)
    metric = engine.snapshot()["metrics"][0]
    assert metric["status"] == "unknown"
    assert metric["evidenceReasons"] == ["observation-gap"]
    assert metric["occupancy"] == 0
    assert metric["activeEventCount"] == 0
    assert list(engine.events.values())[0]["state"] == "unknown"
    # Reacquisition restores the known occupancy, not a new incident.
    engine.ingest(frame(0.5))
    assert len(engine.events) == 1
    assert engine.metrics["rule-1"]["status"] == "active"
    assert engine.metrics["rule-1"]["evidenceReasons"] == []


def test_dwell_reacquisition_after_predictions_starts_a_new_candidate(engine):
    engine, _ = engine
    set_rule(engine, rule("dwell", minimumDurationMs=500, maximumObservationGapMs=200))
    engine.ingest(frame(0))
    for seconds in (0.1, 0.2, 0.3, 0.4, 0.5):
        sample = frame(seconds)
        sample.objects[0].observedThisFrame = False
        engine.ingest(sample)
    engine.ingest(frame(0.6))
    assert not engine.events
    assert engine.metrics["rule-1"]["oldestDwellMs"] == 0
    for seconds in (0.7, 0.8, 0.9, 1.0, 1.1):
        engine.ingest(frame(seconds))
    assert len(engine.events) == 1
    event = next(iter(engine.events.values()))
    assert event["startedAtNs"] == frame(0.6).sourceTimeNs
    assert event["triggeredAtNs"] == frame(1.1).sourceTimeNs


def test_active_dwell_must_requalify_its_duration_after_a_blind_gap(engine):
    engine, _ = engine
    set_rule(engine, rule("dwell", minimumDurationMs=200, maximumObservationGapMs=100))
    for seconds in (0, 0.1, 0.2):
        engine.ingest(frame(seconds))
    event = next(iter(engine.events.values()))
    assert event["state"] == "active"
    engine.ingest(frame(0.4, objects=False))
    for seconds in (0.5, 0.6):
        engine.ingest(frame(seconds))
        assert event["state"] == "unknown"
        assert engine.metrics["rule-1"]["status"] == "unknown"
        assert engine.metrics["rule-1"]["evidenceReasons"] == ["duration-requalification"]
    engine.ingest(frame(0.7))
    assert event["state"] == "active"
    assert len(engine.events) == 1  # same unresolved incident, newly proven condition
    assert [value["state"] for value in event["stateHistory"]] == ["active", "unknown", "active"]
    assert event["stateHistory"][-1]["atNs"] == frame(0.7).sourceTimeNs


@pytest.mark.parametrize("inspect_while_stale", [False, True])
def test_source_stall_restarts_duration_even_when_source_clock_only_advances_one_frame(engine, inspect_while_stale):
    engine, clock = engine
    set_rule(engine, rule("dwell", minimumDurationMs=200, maximumObservationGapMs=200))
    for seconds in (0, 0.1, 0.2):
        engine.ingest(frame(seconds))
    event = next(iter(engine.events.values()))
    clock.value += 3
    if inspect_while_stale:
        assert engine.snapshot()["metrics"][0]["status"] == "unknown"
        assert engine.snapshot()["metrics"][0]["evidenceReasons"] == ["source-stale"]
    for seconds in (0.3, 0.4):
        engine.ingest(frame(seconds))
        assert event["state"] == "unknown"
        if seconds == 0.3:
            assert next(iter(engine.tracks.values()))["velocityMps"] is None
    engine.ingest(frame(0.5))
    assert event["state"] == "active"
    assert event["stateHistory"][-1]["atNs"] == frame(0.5).sourceTimeNs


def test_source_stall_does_not_invent_a_line_crossing(engine):
    engine, clock = engine
    set_rule(engine, rule("line-crossing"))
    engine.ingest(frame(0, x=40))
    clock.value += 3
    engine.ingest(frame(0.1, x=60))
    assert not engine.events
    engine.ingest(frame(0.2, x=40))
    engine.ingest(frame(0.3, x=60))
    assert len(engine.events) == 1
    assert engine.metrics["rule-1"]["totalCrossings"] == 1


@pytest.mark.parametrize("kind", ["occupancy-threshold", "queue"])
def test_aggregate_candidate_restarts_after_source_time_gap(engine, kind):
    engine, _ = engine
    set_rule(engine, rule(kind, minimumDurationMs=500, maximumObservationGapMs=200, countThreshold=1))
    for seconds in (0, 0.1, 0.2, 0.8):
        engine.ingest(frame(seconds))
    assert not engine.events
    if kind == "queue":
        assert engine.metrics["rule-1"]["status"] == "unknown"
        assert engine.metrics["rule-1"]["evidenceReasons"] == ["speed-unavailable"]
        assert engine.metrics["rule-1"]["count"] == 0
    for seconds in (0.9, 1.0, 1.1, 1.2):
        engine.ingest(frame(seconds))
        assert not engine.events
    engine.ingest(frame(1.3))
    if kind == "queue":
        assert not engine.events
        engine.ingest(frame(1.4))
    assert len(engine.events) == 1
    assert next(iter(engine.events.values()))["startedAtNs"] == frame(0.9 if kind == "queue" else 0.8).sourceTimeNs


def test_active_aggregate_requalifies_after_source_time_gap(engine):
    engine, _ = engine
    set_rule(engine, rule("occupancy-threshold", minimumDurationMs=200, maximumObservationGapMs=200))
    for seconds in (0, 0.1, 0.2):
        engine.ingest(frame(seconds))
    event = next(iter(engine.events.values()))
    for seconds in (0.8, 0.9):
        engine.ingest(frame(seconds))
        assert event["state"] == "unknown"
    engine.ingest(frame(1.0))
    assert len(engine.events) == 1 and event["state"] == "active"


@pytest.mark.parametrize("kind", ["occupancy-threshold", "queue"])
def test_reacquired_extra_track_does_not_reset_continuously_proven_aggregate(engine, kind):
    engine, _ = engine
    set_rule(engine, rule(kind, minimumDurationMs=500, maximumObservationGapMs=200, countThreshold=1))
    for seconds in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        sample = frame(seconds)
        if seconds in (0, 0.4):
            sample.objects.append(sample.objects[0].model_copy(update={"localTrackId": "extra"}))
        engine.ingest(sample)
    assert len(engine.events) == 1
    event = next(iter(engine.events.values()))
    assert event["startedAtNs"] == frame(0.1 if kind == "queue" else 0).sourceTimeNs
    assert event["triggeredAtNs"] == frame(0.6 if kind == "queue" else 0.5).sourceTimeNs


@pytest.mark.parametrize("prediction_only", [False, True])
def test_wall_stall_needs_fresh_occupancy_evidence_before_resuming(engine, prediction_only):
    engine, clock = engine
    set_rule(engine, rule("occupancy-threshold", maximumObservationGapMs=200, clearAfterMs=0))
    engine.ingest(frame(0))
    clock.value += 3
    for seconds in (0.1, 0.2):
        sample = frame(seconds, objects=prediction_only)
        if prediction_only:
            sample.objects[0].observedThisFrame = False
        engine.ingest(sample)
        metric = engine.metrics["rule-1"]
        assert metric["status"] == "unknown" and metric["occupancy"] == 0
        assert metric["evidenceReasons"] == ["waiting-for-fresh-observation"]
        assert metric["activeEventCount"] == 0
        assert next(iter(engine.events.values()))["state"] == "unknown"
    engine.ingest(frame(0.3))
    assert engine.metrics["rule-1"]["status"] == "active"
    assert len(engine.events) == 1


def test_aggregate_unknown_survives_track_expiry_until_observed_departure(engine):
    engine, clock = engine
    set_rule(engine, rule("occupancy-threshold", maximumObservationGapMs=200, clearAfterMs=0))
    engine.ingest(frame(0))
    clock.value += 16
    for seconds in (0.1, 0.2, 0.3):
        engine.ingest(frame(seconds, objects=False))
        assert not engine.tracks
        assert engine.metrics["rule-1"]["status"] == "unknown"
        assert engine.metrics["rule-1"]["evidenceReasons"] == (["waiting-for-fresh-observation"] if seconds == 0.1 else ["lost-track-membership"])
        assert next(iter(engine.events.values()))["state"] == "unknown"
    engine.ingest(frame(0.4, x=90))
    assert engine.metrics["rule-1"]["status"] == "normal"
    assert engine.metrics["rule-1"]["evidenceReasons"] == []
    assert next(iter(engine.events.values()))["state"] == "cleared"


def test_expired_extra_track_does_not_break_a_proven_occupancy_threshold(engine):
    engine, clock = engine
    set_rule(engine, rule("occupancy-threshold", minimumDurationMs=200, maximumObservationGapMs=200))
    for index in range(162):
        clock.value = 100 + index / 10
        sample = frame(index / 10)
        if index == 0:
            sample.objects.append(sample.objects[0].model_copy(update={"localTrackId": "extra"}))
        engine.ingest(sample)
    event = next(iter(engine.events.values()))
    assert len(engine.events) == 1 and event["state"] == "active"
    assert [transition["state"] for transition in event["stateHistory"]] == ["active"]
    aggregate = engine.rule_states[("rule-1", "__aggregate__")]
    assert len(aggregate["lostInsideTrackIds"]) == 1
    # This lost extra member does not make an already-proven threshold uncertain.
    assert engine.metrics["rule-1"]["evidenceReasons"] == []


def test_aggregate_lost_evidence_is_bounded_and_session_reset_clears_it(engine):
    engine, _ = engine
    engine.max_tracks = 2
    set_rule(engine, rule("occupancy-threshold"))
    for index in range(6):
        sample = frame(index / 10)
        sample.objects[0].localTrackId = str(index)
        engine.ingest(sample)
    aggregate = engine.rule_states[("rule-1", "__aggregate__")]
    assert len(aggregate["lostInsideTrackIds"]) == engine.max_tracks
    assert aggregate["lostInsideOverflow"] is True
    engine.ingest(frame(2, objects=False))
    assert engine.metrics["rule-1"]["evidenceReasons"] == ["lost-track-capacity", "lost-track-membership", "observation-gap"]
    engine.ingest(frame(2.1, session="new-session", objects=False))
    aggregate = engine.rule_states[("rule-1", "__aggregate__")]
    assert not aggregate.get("lostInsideTrackIds") and not aggregate.get("lostInsideOverflow")


def test_unknown_event_stays_unknown_during_clear_hysteresis(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry", maximumObservationGapMs=100, clearAfterMs=200))
    engine.ingest(frame(0))
    engine.ingest(frame(0.2, objects=False))
    engine.ingest(frame(0.3, x=90))
    assert list(engine.events.values())[0]["state"] == "unknown"
    assert engine.metrics["rule-1"]["status"] == "unknown"
    assert engine.metrics["rule-1"]["evidenceReasons"] == ["clear-hysteresis"]
    assert engine.metrics["rule-1"]["activeEventCount"] == 0
    for seconds in (0.4, 0.5):
        engine.ingest(frame(seconds, x=90))
    assert list(engine.events.values())[0]["state"] == "cleared"
    assert engine.metrics["rule-1"]["status"] == "normal"


def test_image_wrong_way_does_not_clear_when_ground_speed_is_unavailable(engine):
    engine, _ = engine
    site = engine.site.model_dump()
    site["map"]["bounds"] = [5.8, 0, 10, 10]
    engine.put_site(Site.model_validate(site))
    set_rule(engine, rule("wrong-way", minimumDurationMs=0, clearAfterMs=0))
    engine.ingest(frame(0, x=60))
    engine.ingest(frame(0.1, x=59))
    assert list(engine.events.values())[0]["state"] == "active"
    engine.ingest(frame(0.2, x=57))
    track = next(iter(engine.tracks.values()))
    assert track["imageVelocityNormalizedPerSecond"][0] < 0
    assert track["speedMps"] is None
    assert engine.metrics["rule-1"]["status"] == "unknown"
    assert engine.metrics["rule-1"]["evidenceReasons"] == ["projection-unavailable", "speed-unavailable"]
    assert list(engine.events.values())[0]["state"] == "unknown"


def test_wrongway_image_direction_is_not_world_axis(engine):
    engine, _ = engine
    site = engine.site.model_dump()
    site["sources"][0]["imageToGroundHomography"] = [[-0.1, 0, 10], [0, 0.1, 0], [0, 0, 1]]
    engine.put_site(Site.model_validate(site))
    set_rule(engine, rule("wrong-way", minimumDurationMs=0))
    engine.ingest(frame(0, x=60))
    engine.ingest(frame(0.1, x=59))
    assert next(iter(engine.tracks.values()))["velocityMps"][0] > 0
    assert len(engine.events) == 1  # image movement is opposite the allowed rightward arrow


def test_persistent_history_survives_memory_eviction_restart_and_health_stale(tmp_path, engine):
    source, _ = engine
    path = str(tmp_path / "history.db")
    clock = Clock()
    first = CityEngine(CityStore(path), clock=clock, history_frames=2)
    first.put_site(source.site)
    set_rule(first, rule("occupancy-threshold"))
    for i in range(20):
        first.ingest(frame(i / 10, x=30 if i < 10 else 90))
    assert len(first.histories["cam-1"]) == 2
    early = first.snapshot(media_time=0.2)
    assert len(early["tracks"]) == 1 and early["metrics"][0]["occupancy"] == 1
    assert early["zones"][0]["occupancy"] == 1
    restored = CityEngine(CityStore(path), clock=clock)
    historic = restored.snapshot(media_time=0.2)
    assert historic["clockAligned"] is True
    assert historic["tracks"][0]["stale"] is False
    assert historic["sources"][0]["status"] == "replay"
    assert restored.snapshot()["sources"][0]["status"] == "awaiting-observations"


def test_history_row_and_byte_limits():
    store = CityStore(max_history_frames=3, max_history_bytes=800)
    for i in range(64):
        store.save_history("source", "session", {"mediaTimeSeconds": i, "filler": "x" * 40})
    rows = store.connection.execute("SELECT COUNT(*),SUM(bytes) FROM history").fetchone()
    assert rows[0] <= 3 and rows[1] <= 800
    assert store.nearest_history("source", 63)["mediaTimeSeconds"] == 63


def test_native_compilation_safe_labels_and_ack(tmp_path, engine):
    engine, _ = engine
    dangerous = rule("line-crossing")
    dangerous["id"] = "x\n[malicious]"
    set_rule(engine, dangerous)
    text, capabilities = compile_analytics(engine.site, engine.rules, engine.rules_revision)
    assert "[malicious]" not in text
    assert "[line-crossing-stream-0]" in text
    assert "class-id=-1" in text
    bridge = NativeAnalyticsBridge(str(tmp_path))
    assert bridge.apply(engine.site, engine.rules, engine.rules_revision)["status"] == "pending"
    (tmp_path / "analytics-ack.json").write_text('{"revision":1,"status":"active","counterEpoch":"abc"}')
    assert bridge.status()["status"] == "active"
    assert bridge.status()["counterEpoch"] == "abc"
    (tmp_path / "analytics-ack.json").write_text('{"revision":"1","status":"active","counterEpoch":"def"}')
    assert bridge.status()["status"] == "active"
    assert bridge.status()["appliedRevision"] == 1


def test_explicit_full_fixture_uses_ingestion_and_exercises_all_rule_families():
    engine = CityEngine(history_frames=4)
    engine.put_site(Site.model_validate(package_site()))
    engine.put_rules(RuleSet.model_validate(fixture_rules()))
    classes = set()
    for sample in observations(fps=5):
        classes.update(obj["class"] for obj in sample["objects"])
        assert engine.ingest(Observation.model_validate(sample))["accepted"]
    assert classes == {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
    kinds = {event["kind"] for event in engine.events.values()}
    assert kinds == {"area-entry", "line-crossing", "occupancy-threshold", "dwell", "stopped-in-zone", "queue", "wrong-way"}
    assert all(event["mode"] == "fixture-replay" for event in engine.events.values())
    assert any(event["state"] == "cleared" and event["kind"] == "queue" for event in engine.events.values())
    snapshot = engine.snapshot(media_time=9)
    assert snapshot["clockAligned"] is True
    assert len(snapshot["sources"]) == 2
    assert all(track["globalTrackId"] is None for track in snapshot["tracks"])
    # Both camera transforms recover the same known synthetic location.
    for source in engine.site.sources:
        point, status = project(image_anchor(source.id, 12, -8), source.imageToGroundHomography)
        assert status == "valid" and point == pytest.approx([12, -8], abs=1e-12)


def test_historical_events_do_not_reveal_future_or_final_clear_state(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry", clearAfterMs=0))
    for seconds, x in [(0, 90), (0.1, 30), (0.2, 30), (0.3, 90)]:
        engine.ingest(frame(seconds, x=x))
    assert not engine.snapshot(media_time=0, maximum_skew=0.01)["events"]
    active = engine.snapshot(media_time=0.2, maximum_skew=0.01)["events"]
    assert len(active) == 1 and active[0]["state"] == "active" and active[0]["endedAt"] is None
    assert engine.snapshot(media_time=0.3, maximum_skew=0.01)["events"][0]["state"] == "cleared"


def test_rule_invalidation_is_unknown_in_durable_historical_replay(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry"))
    engine.ingest(frame(0))
    engine.ingest(frame(0.1))
    engine.put_rules(RuleSet.model_validate({"rules": []}))
    engine.ingest(frame(0.2))
    event = engine.store.events()[0]
    assert event["state"] == "unknown" and event["stateReason"] == "rules-replaced"
    assert event["unknownAtNs"] == frame(0.1).sourceTimeNs
    assert event["updatedAtNs"] == event["unknownAtNs"]
    assert event["endedAtNs"] is None
    assert engine.snapshot(media_time=0, maximum_skew=0.01)["events"][0]["state"] == "active"
    for seconds in (0.1, 0.2):
        historic = engine.snapshot(media_time=seconds, maximum_skew=0.01)["events"][0]
        assert historic["state"] == "unknown" and historic["endedAt"] is None


def test_historical_unknown_intervals_survive_resume_clear_and_sqlite_reopen(tmp_path, engine):
    configured, clock = engine
    database = str(tmp_path / "state-transitions.db")
    engine = CityEngine(CityStore(database), clock=clock, history_frames=2)
    engine.put_site(configured.site)
    set_rule(engine, rule("area-entry", maximumObservationGapMs=200, clearAfterMs=0))
    samples = [(0, True, 30), (0.3, False, 30), (0.4, True, 30), (0.7, False, 30), (0.8, True, 30), (0.9, True, 90)]
    for seconds, seen, x in samples:
        engine.ingest(frame(seconds, objects=seen, x=x))
    event = engine.store.events()[0]
    assert [entry["state"] for entry in event["stateHistory"]] == ["active", "unknown", "active", "unknown", "active", "cleared"]
    assert event["stateHistoryComplete"] is True
    for current in (engine, CityEngine(CityStore(database), clock=clock)):
        for seconds, expected in [(0, "active"), (0.3, "unknown"), (0.4, "active"), (0.7, "unknown"), (0.8, "active"), (0.9, "cleared")]:
            historic = current.snapshot(media_time=seconds, maximum_skew=0.01)["events"][0]
            assert historic["state"] == expected
            assert historic["historicalStateStatus"] == "recorded-transition"
            assert historic["stateReason"] == ("observation-gap" if expected == "unknown" else None)
            assert all(int(entry["atNs"]) <= int(frame(seconds).sourceTimeNs) for entry in historic["stateHistory"])
            if expected != "cleared":
                assert historic["endedAt"] is None and historic["endedAtNs"] is None


def test_historical_observed_duration_does_not_include_blind_intervals(engine):
    engine, _ = engine
    set_rule(engine, rule("dwell", minimumDurationMs=100, maximumObservationGapMs=200))
    for seconds, seen in ((0, True), (0.1, True), (0.2, True), (0.5, False), (0.6, True), (0.7, True)):
        engine.ingest(frame(seconds, objects=seen))
    before = engine.snapshot(media_time=0.2, maximum_skew=0.01)["events"][0]
    assert before["state"] == "active"
    assert before["metrics"]["durationMs"] == 200
    for seconds in (0.5, 0.6, 0.7):
        selected = engine.snapshot(media_time=seconds, maximum_skew=0.01)["events"][0]
        assert selected["metrics"]["durationMs"] is None
        assert selected["durationStatus"] == "unavailable-observation-gap"
        assert selected["triggerMetrics"]["durationMs"] == 100


def test_event_transition_history_is_bounded_and_older_state_is_explicit_unknown(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry", maximumObservationGapMs=200))
    engine.ingest(frame(0))
    for index in range(EVENT_STATE_HISTORY_LIMIT):
        engine.ingest(frame(index * 0.4 + 0.3, objects=False))
        engine.ingest(frame(index * 0.4 + 0.4))
    event = engine.store.events()[0]
    assert len(event["stateHistory"]) == EVENT_STATE_HISTORY_LIMIT
    assert event["stateHistoryComplete"] is False
    early = engine.snapshot(media_time=0.3, maximum_skew=0.01)["events"][0]
    assert early["state"] == "unknown"
    assert early["historicalStateStatus"] == "state-history-truncated"
    assert early["stateReason"] == "state-history-truncated"
    assert early["stateHistory"] == [] and early["endedAtNs"] is None
    last_gap = (EVENT_STATE_HISTORY_LIMIT - 1) * 0.4 + 0.3
    late = engine.snapshot(media_time=last_gap, maximum_skew=0.01)["events"][0]
    assert late["state"] == "unknown" and late["stateReason"] == "observation-gap"


def test_legacy_event_without_transitions_does_not_guess_earlier_state(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry", maximumObservationGapMs=200))
    for seconds, seen in [(0, True), (0.3, False), (0.4, True)]:
        engine.ingest(frame(seconds, objects=seen))
    event = engine.store.events()[0]
    for field in ("stateHistory", "stateHistoryComplete", "stateHistoryStartsAtNs"):
        event.pop(field, None)
    engine.store.save_event(event)
    old = engine.snapshot(media_time=0.3, maximum_skew=0.01)["events"][0]
    assert old["state"] == "unknown" and old["stateReason"] == "state-history-unavailable"
    assert old["historicalStateStatus"] == "state-history-unavailable"
    known = engine.snapshot(media_time=0.4, maximum_skew=0.01)["events"][0]
    assert known["state"] == "active" and known["historicalStateStatus"] == "legacy-last-boundary"


def test_line_hysteresis_rejects_boundary_jitter(engine):
    engine, _ = engine
    set_rule(engine, rule("line-crossing"))
    for i, x in enumerate([49.9, 50.1, 49.9, 50.1, 49.9]):
        engine.ingest(frame(i / 10, x=x))
    assert not engine.events
    engine.ingest(frame(0.5, x=45))
    engine.ingest(frame(0.6, x=55))
    assert len(engine.events) == 1


def test_site_and_calibration_revisions_gate_frames_and_rule_activation(engine):
    engine, _ = engine
    set_rule(engine, rule("queue"))
    old_rule_revision = engine.rules_revision
    sample = frame(0).model_dump(by_alias=True)
    sample["calibrationRevision"] = "wrong"
    with pytest.raises(ValueError, match="calibrationRevision"):
        engine.ingest(Observation.model_validate(sample))
    site = engine.site.model_dump()
    site["revision"] = 2
    site["sources"][0]["imageToGroundHomography"] = None
    engine.put_site(Site.model_validate(site))
    assert engine.rules_revision == old_rule_revision + 1
    assert engine.rules[0].enabled is False
    assert engine.rules[0].model_extra["validationError"] == "calibration-required-after-site-change"
    with pytest.raises(ConflictError):
        engine.put_site(Site.model_validate({**site, "expectedRevision": 1}))


@pytest.mark.parametrize("change", ["revision", "transform", "polygon"])
def test_direct_calibration_change_disables_metric_rules_preserves_image_rules(engine, change):
    engine, _ = engine
    metric = rule("queue")
    metric["calibrationRevision"] = "fixture-1"
    image = {**rule("area-entry"), "id": "image-rule", "calibrationRevision": "fixture-1"}
    engine.put_rules(RuleSet.model_validate({"rules": [metric, image]}))
    site = engine.site.model_dump()
    site["revision"] = 2
    source = site["sources"][0]
    if change == "revision":
        source["calibrationRevision"] = "fixture-2"
    elif change == "transform":
        source["imageToGroundHomography"][0][0] = 0.09
    else:
        source["validGroundPolygon"] = [[0, 0], [90, 0], [90, 90], [0, 90]]
    engine.put_site(Site.model_validate(site))
    rules = engine.rules_json()
    metric_rule, image_rule = rules["rules"]
    assert metric_rule["enabled"] is False
    assert metric_rule["validationError"] == "calibration-changed-after-site-change"
    assert image_rule["enabled"] is True
    if change == "revision":
        assert "calibrationRevision" not in metric_rule and "calibrationRevision" not in image_rule
    # Saved rules remain a valid API payload after the source package changes.
    engine.put_rules(RuleSet.model_validate({"rules": rules["rules"]}))


def test_http_body_limit_covers_chunked_without_content_length(engine):
    configured, _ = engine
    with TestClient(create_app(configured)) as client:
        def chunks():
            for _ in range(9):
                yield b"x" * 1024 * 1024
        response = client.post("/api/v1/city/observations", content=chunks())
        assert response.status_code == 413


def test_switching_site_never_exposes_fixture_events_as_recorded(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry"))
    engine.ingest(frame(0))
    assert len(engine.events) == 1
    engine.put_site(Site.model_validate({"id": "recorded-site", "mode": "recorded-inference", "sources": [{"id": "real-camera", "width": 100, "height": 100}]}))
    assert not engine.snapshot()["events"]
    with TestClient(create_app(engine)) as client:
        assert client.get("/api/v1/city/events").json()["events"] == []
        assert client.get("/api/v1/city/reports").json()["eventCount"] == 0
        assert "fixture-replay" not in client.get("/api/v1/city/reports?format=csv").text
    assert len(engine.store.events(site_id="test")) == 1  # historical evidence is retained under its own site


def test_dynamic_media_registration_is_restricted_to_configured_files(tmp_path, engine):
    engine, _ = engine
    (tmp_path / "camera.mp4").write_bytes(b"file contents")
    with TestClient(create_app(engine, media_registry={}, media_root=str(tmp_path))) as client:
        assert client.put("/api/v1/city/media-registration", json={"sources": [{"sourceId": "cam-1", "filename": "camera.mp4"}]}).status_code == 200
        assert client.get("/api/v1/city/media/cam-1").content == b"file contents"
        assert client.put("/api/v1/city/media-registration", json={"sources": [{"sourceId": "cam-1", "filename": "../secret.mp4"}]}).status_code == 422
        assert client.put("/api/v1/city/media-registration", json={"sources": [{"sourceId": "unknown", "filename": "camera.mp4"}]}).status_code == 422


def test_live_timestamp_lookup_requires_rtcp_and_matches_the_presented_clock(engine):
    engine, _ = engine
    sample = frame(0).model_dump(by_alias=True)
    sample.update(mediaTimeSeconds=None, timestampBasis="arrival-pts-unsynchronized")
    engine.ingest(Observation.model_validate(sample))
    ns = int(sample["sourceTimeNs"])
    assert not engine.snapshot(source_time_ns=ns)["clockAligned"]
    sample.update(sequence="1", sourceTimeNs=str(ns + 100_000_000), timestampBasis="source-rtcp")
    engine.ingest(Observation.model_validate(sample))
    aligned = engine.snapshot(source_time_ns=ns + 100_000_000, maximum_skew=0.01)
    assert aligned["clockAligned"] is True and len(aligned["tracks"]) == 1
    assert not engine.snapshot(source_time_ns=ns + 20_000_000_000)["clockAligned"]


def test_stale_native_ack_is_applied_history_not_current_active(tmp_path, monkeypatch, engine):
    engine, clock = engine
    monkeypatch.setenv("CITY_NATIVE_CONFIG_DIR", str(tmp_path))
    app = create_app(engine)
    (tmp_path / "analytics-ack.json").write_text('{"revision":"0","status":"active"}')
    with TestClient(app) as client:
        status = client.get("/api/v1/city/health").json()["nativeAnalyticsStatus"]
        assert status["status"] == "applied-inactive"
        assert status["operationalStatus"] == "awaiting-observations"
        engine.ingest(frame(0))
        assert client.get("/api/v1/city/health").json()["nativeAnalyticsStatus"]["status"] == "active"
        clock.value += 3
        status = client.get("/api/v1/city/health").json()["nativeAnalyticsStatus"]
        assert status["status"] == "applied-inactive" and status["operationalStatus"] == "stale"


def test_trigger_measurements_do_not_mutate_into_future_counts(engine):
    engine, _ = engine
    set_rule(engine, rule("occupancy-threshold", countThreshold=1, clearAfterMs=0))
    engine.ingest(frame(0))
    later = frame(0.1).model_dump(by_alias=True)
    later["objects"].append({**later["objects"][0], "localTrackId": "second"})
    engine.ingest(Observation.model_validate(later))
    engine.ingest(frame(0.2, x=90))
    event = engine.snapshot(media_time=0)["events"][0]
    assert event["metrics"]["count"] == 1
    assert event["triggerMetrics"]["count"] == 1


def test_recorded_clock_basis_and_selected_source_metadata_are_consistent(engine):
    engine, _ = engine
    site = engine.site.model_dump()
    site["mode"] = "recorded-inference"
    engine.put_site(Site.model_validate(site))
    legacy = frame(0).model_dump(by_alias=True)
    engine.ingest(Observation.model_validate(legacy))
    assert engine.snapshot(media_time=0)["clockAligned"] is False
    for seconds in (1, 2):
        sample = frame(seconds).model_dump(by_alias=True)
        sample.update(mediaTimeBasis="gstreamer-segment-stream-time", rawSourcePtsNs=str(seconds * 1_000_000_000 + 200_000_000))
        engine.ingest(Observation.model_validate(sample))
    selected = engine.snapshot(media_time=1)
    assert selected["clockAligned"] is True
    assert selected["sources"][0]["rawSourcePtsNs"] == "1200000000"
    assert selected["sources"][0]["mediaTimeSeconds"] == 1
    assert selected["sources"][0]["lastSourceTimeNs"] != selected["sources"][0]["currentLastSourceTimeNs"]


def test_timestamp_basis_switch_retires_tracks_durations_and_late_prior_clock(engine):
    engine, _ = engine
    set_rule(engine, rule("dwell", minimumDurationMs=500))
    engine.ingest(frame(0))
    engine.ingest(frame(0.5))
    assert list(engine.events.values())[0]["state"] == "active"
    switched = frame(0.6).model_dump(by_alias=True)
    switched.update(timestampBasis="source-rtcp", sourceTimeNs=str(int(switched["sourceTimeNs"]) + 1_000_000_000_000))
    result = engine.ingest(Observation.model_validate(switched))
    assert "clock-basis" in result["sessionId"]
    assert len(engine.events) == 1 and list(engine.events.values())[0]["state"] == "unknown"
    assert next(iter(engine.tracks.values()))["velocityMps"] is None
    assert engine.ingest(frame(0.5))["reason"] == "late-prior-clock-basis"


def test_now_snapshot_excludes_retired_inputs_but_reports_keep_history(engine):
    engine, _ = engine
    set_rule(engine, rule("area-entry"))
    engine.ingest(frame(0))
    assert len(engine.snapshot()["events"]) == 1
    site = engine.site.model_dump()
    site["sources"][0]["id"] = "replacement-camera"
    site["revision"] += 1
    engine.put_site(Site.model_validate(site))
    assert engine.snapshot()["events"] == []
    assert len(engine.store.events(site_id=site["id"])) == 1


def test_ingest_freshness_is_separate_from_delayed_live_source_clock(engine, monkeypatch):
    engine, clock = engine
    site = engine.site.model_dump()
    site["mode"] = "live"
    engine.put_site(Site.model_validate(site))
    monkeypatch.setattr("apps.city.engine.time.time", lambda: 1_700_000_020.0)
    for seconds in range(5):
        clock.value = 100 + seconds
        sample = frame(seconds * 0.5, seq=seconds).model_dump(by_alias=True)
        sample["timestampBasis"] = "source-rtcp"
        engine.ingest(Observation.model_validate(sample))
    source = engine.snapshot()["sources"][0]
    assert source["status"] == "live" and source["ingestAgeSeconds"] == 0
    assert source["sourceClockProgressRatio"] == 0.5
    assert source["sourceClockAgeSeconds"] == 18
    assert source["sourceClockStatus"] == "delayed-or-unsynchronized"
    assert source["sourceClockPrecision"] == "unverified"
    sample.update(sequence="5", sourceTimeNs="1700000020000000000", timestampBasis="arrival-pts-unsynchronized")
    engine.ingest(Observation.model_validate(sample))
    assert engine.snapshot()["sources"][0]["sourceClockAgeSeconds"] is None


def test_selected_frame_source_model_matches_selected_tracks(engine):
    engine, _ = engine
    for seconds, model in ((0, "rfdetr-small-first"), (1, "rfdetr-medium-second")):
        sample = frame(seconds).model_dump(by_alias=True)
        sample["modelRevision"] = model
        engine.ingest(Observation.model_validate(sample))
    selected = engine.snapshot(media_time=0)
    assert selected["sources"][0]["modelRevision"] == "rfdetr-small-first"
    assert selected["sources"][0]["currentModelRevision"] == "rfdetr-medium-second"
    assert selected["tracks"][0]["modelRevision"] == "rfdetr-small-first"
