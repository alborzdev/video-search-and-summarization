# SPDX-License-Identifier: Apache-2.0
"""Source-time mobility contracts; CPU fixtures are never live detector evidence."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_city import engine, frame, rule, set_rule
from apps.city.engine import CityEngine, ConflictError
from apps.city.main import create_app
from apps.city.models import MobilityConfig, Observation, RuleSet, Site
from apps.city.mobility import _quantile


def gates(engine, gap=200):
    entries = []
    for key, x in (("entry", .4), ("exit", .7)):
        value = rule("line-crossing", maximumObservationGapMs=gap)
        value.update(id=key, name=key)
        value["geometry"]["points"] = [[x, .1], [x, .9]]
        entries.append(value)
    engine.put_rules(RuleSet.model_validate({"rules": entries}))
    return {"movements": [{"id": "through", "name": "Through", "entryRuleId": "entry", "exitRuleId": "exit"}]}


def install(engine, config):
    return engine.put_mobility_config(MobilityConfig.model_validate(config))


def test_config_persists_without_resetting_camera_or_native_rules(engine):
    engine, clock = engine
    config = gates(engine)
    engine.ingest(frame(0))
    before = (deepcopy(engine.tracks), deepcopy(engine.sources), engine.rules_revision, engine.site.revision)
    result = install(engine, {**config, "expectedRevision": 0})
    assert result["configRevision"] == 1
    assert (engine.tracks, engine.sources, engine.rules_revision, engine.site.revision) == before
    assert CityEngine(store=engine.store, clock=clock).mobility.config.revision == 1
    with pytest.raises(ConflictError):
        install(engine, {**config, "expectedRevision": 0})


@pytest.mark.parametrize("change", ["missing", "disabled", "same", "class"])
def test_invalid_movement_references_are_rejected(engine, change):
    engine, _ = engine
    config = gates(engine)
    if change == "missing":
        config["movements"][0]["exitRuleId"] = "absent"
    elif change == "same":
        config["movements"][0]["exitRuleId"] = "entry"
    elif change == "class":
        config["movements"][0]["classes"] = ["person"]
    else:
        engine.rules[1].enabled = False
    with pytest.raises(ValueError):
        install(engine, config)


def test_cross_camera_gates_rejected_and_deleted_rules_fail_closed(engine):
    engine, _ = engine
    config = gates(engine)
    install(engine, config)
    engine.rules[1].sourceId = "other-camera"
    with pytest.raises(ValueError, match="one camera"):
        install(engine, config)
    engine.put_rules(RuleSet(rules=[]))
    result = engine.mobility_json(1)
    assert result["configurationIssues"]
    assert result["movements"][0]["status"] == "unavailable"
    engine.ingest(frame(0))  # Deleted references cannot crash ingestion.


@pytest.mark.parametrize("point", [[0, 0], [float("nan"), 1], [float("inf"), 1]])
def test_queue_axis_must_be_finite_and_off_stop_line(point):
    with pytest.raises(ValidationError):
        MobilityConfig.model_validate({"queues": [{"id": "q", "name": "Queue", "zoneRuleId": "r", "stopLine": [[0, 0], [1, 0]], "upstreamPoint": point, "spillbackDistanceM": 10}]})


def test_line_totals_window_coverage_and_session_reset(engine):
    engine, clock = engine
    set_rule(engine, rule("line-crossing"))
    for seconds, x in [(0, 40), (.1, 60), (.2, 40), (.3, 60)]:
        engine.ingest(frame(seconds, x=x))
    result = engine.mobility_json(1)
    assert result["lineCounts"][0]["count"] == 2
    assert result["lineCounts"][0]["byClass"] == {"car": 2}
    assert result["coverage"][0]["observedSeconds"] == pytest.approx(.3)
    clock.value += 3
    assert engine.mobility_json(1)["coverage"][0]["status"] == "stale"
    assert engine.mobility_json(1)["coverage"][0]["observedSeconds"] == pytest.approx(.3)
    engine.ingest(frame(61, x=60))
    assert engine.mobility_json(1)["lineCounts"][0]["count"] == 0
    assert engine.mobility_json(5)["lineCounts"][0]["count"] == 2
    engine.ingest(frame(0, session="session-2"))
    assert engine.mobility_json(5)["lineCounts"][0]["count"] == 0


def test_complete_movement_retains_line_touch_and_measures_source_time(engine):
    engine, _ = engine
    install(engine, gates(engine))
    for seconds, x in [(0, 30), (.1, 40), (.2, 50), (.3, 70), (.4, 80)]:
        engine.ingest(frame(seconds, x=x))
    result = engine.mobility_json(1)["movements"][0]
    assert result["completedCount"] == 1
    assert result["incompleteCount"] == 0
    assert result["byClass"] == {"car": 1}
    assert result["medianTravelSeconds"] == pytest.approx(.2)
    assert result["activeCount"] == 0


@pytest.mark.parametrize("loss", ["source-gap", "wall-stall", "prediction"])
def test_interrupted_movement_is_incomplete_not_a_completed_turn(engine, loss):
    engine, clock = engine
    install(engine, gates(engine))
    engine.ingest(frame(0, x=30))
    engine.ingest(frame(.1, x=50))
    if loss == "wall-stall":
        clock.value += 3
        engine.ingest(frame(.2, x=80))
    elif loss == "source-gap":
        engine.ingest(frame(.4, x=80))
    else:
        predicted = frame(.4, x=80).model_dump(by_alias=True)
        predicted["objects"][0]["observedThisFrame"] = False
        engine.ingest(Observation.model_validate(predicted))
        engine.ingest(frame(.5, x=80))
    result = engine.mobility_json(1)["movements"][0]
    assert result["completedCount"] == 0
    assert result["incompleteCount"] == 1


def test_first_sighting_inside_polygon_is_not_a_movement_entry(engine):
    engine, _ = engine
    config = gates(engine)
    entry = rule("occupancy-threshold")
    entry.update(id="entry")
    entry["geometry"]["points"] = [[.2, .2], [.5, .2], [.5, .8], [.2, .8]]
    engine.put_rules(RuleSet.model_validate({"rules": [entry, engine.rules[1].model_dump()]}))
    install(engine, config)
    engine.ingest(frame(0, x=30))
    engine.ingest(frame(.1, x=80))
    assert engine.mobility_json(1)["movements"][0]["completedCount"] == 0


def test_obstruction_union_excludes_blind_time_and_does_not_double_count(engine):
    engine, _ = engine
    set_rule(engine, rule("stopped-in-zone", minimumDurationMs=100, clearAfterMs=0, maximumObservationGapMs=200))
    def two(seconds, *, objects=True, x=30):
        value = frame(seconds, x=x, objects=objects).model_dump(by_alias=True)
        if objects:
            value["objects"].append({**value["objects"][0], "localTrackId": "second"})
        engine.ingest(Observation.model_validate(value))
    for seconds in [0, .1, .2, .3]:
        two(seconds)
    row = engine.mobility_json(1)["obstructions"][0]
    assert row["episodeCount"] == 2
    assert row["blockedSeconds"] == pytest.approx(.1)
    two(.4, objects=False)
    row = engine.mobility_json(1)["obstructions"][0]
    assert row["unknownEpisodes"] == 2
    assert row["blockedSeconds"] == pytest.approx(.1)
    two(.5)
    # Real-only motion history permits immediate fresh re-observation. The
    # missing .3 -> .5 span remains excluded; no new duration qualification
    # delay is charged for a bounded loss after this incident was confirmed.
    assert engine.mobility_json(1)["obstructions"][0]["blockedSeconds"] == pytest.approx(.1)
    two(.6)
    two(.7)
    two(.8)
    assert engine.mobility_json(1)["obstructions"][0]["blockedSeconds"] == pytest.approx(.4)
    two(.9, x=90)
    row = engine.mobility_json(1)["obstructions"][0]
    assert row["completedEpisodes"] == 2
    assert row["ongoingEpisodes"] == 0
    two(61.8, objects=False)
    assert engine.mobility_json(1)["obstructions"][0]["episodeCount"] == 0


def test_bounded_record_eviction_marks_partial_coverage(engine, monkeypatch):
    from apps.city import mobility
    monkeypatch.setattr(mobility, "MAX_RECORDS", 2)
    engine, _ = engine
    set_rule(engine, rule("line-crossing"))
    for i, x in enumerate([40, 60, 40, 60, 40, 60]):
        engine.ingest(frame(i / 10, x=x))
    result = engine.mobility_json(1)
    assert len(engine.mobility.sources["cam-1"]["records"]) == 2
    assert result["coverage"][0]["truncated"] is True
    assert result["lineCounts"][0]["status"] == "partial"


def test_mobility_api_windows_and_optimistic_conflicts(engine):
    engine, _ = engine
    config = gates(engine)
    with TestClient(create_app(engine, media_registry={})) as client:
        for window in [1, 5, 15]:
            assert client.get(f"/api/v1/city/mobility?windowMinutes={window}").status_code == 200
        assert client.get("/api/v1/city/mobility?windowMinutes=2").status_code == 422
        assert client.put("/api/v1/city/mobility/config", json={**config, "expectedRevision": 0}).status_code == 200
        assert client.put("/api/v1/city/mobility/config", json={**config, "expectedRevision": 0}).status_code == 409


def test_travel_percentiles_interpolate_even_sample_median():
    assert _quantile([1, 3], .5) == 2
    assert _quantile([], .95) is None


def test_spatial_integration_receives_frames_and_wall_loss(engine):
    engine, clock = engine
    set_rule(engine, rule("queue", minimumDurationMs=0))
    install(engine, {"queues": [{"id": "approach", "name": "Approach", "zoneRuleId": "rule-1", "stopLine": [[0, 0], [5, 0]], "upstreamPoint": [2.5, 10], "spillbackDistanceM": 3, "minimumDurationMs": 0}]})
    for seconds in [0, .1, .2]:
        engine.ingest(frame(seconds))
    row = engine.mobility_json(1)["queues"][0]
    assert row["sourceId"] == "cam-1"
    assert row["count"] == 1
    assert row["observedExtentM"] == pytest.approx(4)
    maximum = row["maximumObservedExtentM"]
    clock.value += 3
    row = engine.mobility_json(1)["queues"][0]
    assert row["status"] == "unknown"
    assert row["observedExtentM"] is None
    assert row["maximumObservedExtentM"] == maximum


@pytest.mark.parametrize("observed_departure", [False, True])
def test_scope_archive_preserves_last_observed_queue_before_invalidation(engine, observed_departure):
    engine, _ = engine
    set_rule(engine, rule("queue", countThreshold=1, minimumDurationMs=0))
    install(engine, {"queues": [{"id": "approach", "name": "Approach", "zoneRuleId": "rule-1", "stopLine": [[0, 0], [5, 0]], "upstreamPoint": [2.5, 10], "spillbackDistanceM": 3, "minimumDurationMs": 0}]})
    engine.reset_analytics_scope(kind="scenario", run_id="queue-run")
    for seconds in [0, .1, .2, .3]:
        engine.ingest(frame(seconds))
    if observed_departure:
        engine.ingest(frame(.4, x=90))
    before = deepcopy(engine.mobility.snapshot(engine, 5))
    queue = before["queues"][0]
    assert queue["count"] == (0 if observed_departure else 1)
    assert queue["maximumObservedExtentM"] == pytest.approx(4)
    active = [event for event in engine.events.values() if event["state"] == "active"]
    if not observed_departure:
        assert active
    engine.reset_analytics_scope(kind="normal")
    archive = engine.store.get("analytics-scopes:test")[-1]
    assert archive["runId"] == "queue-run"
    assert archive["mobility"] == before
    assert archive["mobility"]["queues"][0]["clearanceConfirmed"] == queue["clearanceConfirmed"]
    assert archive["observationEnd"] == {"reason": "scenario-boundary", "activeEventState": "unknown"}
    assert archive["mobilitySnapshotBasis"] == "last-observed-before-boundary"
    for event in active:
        assert event["state"] == "unknown" and event["stateReason"] == "scenario-boundary"
        assert event["endedAt"] is None
    assert engine.mobility.snapshot(engine, 5)["queues"] == []
    engine.ingest(frame(.5, x=90))
    assert engine.mobility.snapshot(engine, 5)["queues"][0]["maximumObservedExtentM"] == 0
    assert engine.store.get("analytics-scopes:test")[-1]["mobility"] == before


def alternative_gates(engine, *, reverse=False):
    config = gates(engine)
    alternate = rule("line-crossing", maximumObservationGapMs=200)
    alternate.update(id="other-exit", name="Other exit", classes=["car", "person"])
    alternate["geometry"].update(points=[[.1, .6], [.9, .6]], direction=[0, 1])
    rules = [value.model_dump() for value in engine.rules]
    for value in rules:
        value["classes"] = ["car", "person"]
    engine.put_rules(RuleSet.model_validate({"rules": [*rules, alternate]}))
    config["movements"][0]["classes"] = ["car"]
    config["movements"].append({"id": "other", "name": "Other", "entryRuleId": "entry", "exitRuleId": "other-exit", "classes": ["car", "person"]})
    if reverse:
        config["movements"].reverse()
    return config


@pytest.mark.parametrize("reverse", [False, True])
def test_observed_exit_resolves_shared_entry_alternatives_independent_of_order(engine, reverse):
    engine, _ = engine
    install(engine, alternative_gates(engine, reverse=reverse))
    for seconds, x in [(0, 30), (.1, 50), (.2, 80), (.5, 80)]:
        engine.ingest(frame(seconds, x=x))
    rows = {row["id"]: row for row in engine.mobility_json(1)["movements"]}
    assert rows["through"]["completedCount"] == 1
    assert rows["other"]["completedCount"] == 0
    assert all(row["activeCount"] == row["incompleteCount"] == 0 for row in rows.values())


def test_resolved_turn_does_not_clear_another_track_class_or_entry_gate(engine):
    engine, _ = engine
    config = alternative_gates(engine)
    other_entry = engine.rules[0].model_copy(update={"id": "separate-entry"}, deep=True)
    engine.put_rules(RuleSet(rules=[*engine.rules, other_entry]))
    config["movements"].append({"id": "separate", "name": "Separate gate", "entryRuleId": "separate-entry", "exitRuleId": "other-exit", "classes": ["car"]})
    install(engine, config)
    for seconds, car_x, person_x in [(0, 30, 30), (.1, 50, 50), (.2, 80, 50)]:
        value = frame(seconds, x=car_x).model_dump(by_alias=True)
        value["objects"].append({**value["objects"][0], "localTrackId": "person", "class": "person", "bboxPx": [person_x - 5, 30, 10, 10]})
        engine.ingest(Observation.model_validate(value))
    rows = {row["id"]: row for row in engine.mobility_json(1)["movements"]}
    assert rows["through"]["completedCount"] == 1
    assert rows["other"]["activeCount"] == 1  # Person has not taken either exit.
    assert rows["separate"]["activeCount"] == 1  # Another entry measurement stays independent.
    engine.ingest(frame(.5, objects=False))
    rows = {row["id"]: row for row in engine.mobility_json(1)["movements"]}
    assert rows["through"]["incompleteCount"] == 0
    assert rows["other"]["incompleteCount"] == rows["separate"]["incompleteCount"] == 1


def test_shared_entry_without_observed_exit_keeps_real_interruptions(engine):
    engine, _ = engine
    install(engine, alternative_gates(engine))
    engine.ingest(frame(0, x=30))
    engine.ingest(frame(.1, x=50))
    engine.ingest(frame(.4, objects=False))
    assert all(row["incompleteCount"] == 1 and row["completedCount"] == 0 for row in engine.mobility_json(1)["movements"])
