# SPDX-License-Identifier: Apache-2.0
"""CPU fixtures prove curb evidence semantics, never detector accuracy."""
import pytest
from pydantic import ValidationError

from test_city import engine, frame, rule, set_rule
from apps.city.models import MobilityConfig, Observation, RuleSet


def configure(engine, **changes):
    value = rule("occupancy-threshold")
    set_rule(engine, value)
    config = {"id": "curb", "name": "Loading area", "zoneRuleId": "rule-1", "role": "loading", "dwellThresholdMs": 100, "maximumObservationGapMs": 200, **changes}
    engine.put_mobility_config(MobilityConfig.model_validate({"curbs": [config]}))


def report(engine, minutes=1):
    return engine.mobility_json(minutes)["curbs"][0]


def test_old_config_defaults_and_new_validation(engine):
    assert MobilityConfig().curbs == []
    engine, _ = engine
    configure(engine)
    assert report(engine)["occupancy"] is None
    assert report(engine)["status"] == "unknown"
    for changes in [{"role": "illegal-parking"}, {"dwellThresholdMs": -1}, {"maximumObservationGapMs": 49}]:
        with pytest.raises(ValidationError):
            MobilityConfig.model_validate({"curbs": [{"id": "x", "name": "x", "zoneRuleId": "rule-1", **changes}]})
    with pytest.raises(ValueError, match="vehicle class"):
        value = rule()
        value["classes"] = ["person"]
        set_rule(engine, value)
        engine.put_mobility_config(MobilityConfig.model_validate({"curbs": [{"id": "x", "name": "x", "zoneRuleId": "rule-1"}]}))


def test_observed_arrival_departure_and_completed_dwell(engine):
    engine, _ = engine
    configure(engine)
    for seconds, x in [(0, 10), (.1, 30), (.2, 30), (.3, 30), (.4, 90)]:
        engine.ingest(frame(seconds, x=x))
    row = report(engine)
    assert row["arrivalCount"] == row["departureCount"] == row["turnoverCount"] == row["completedVisitCount"] == 1
    assert row["partialVisitCount"] == row["incompleteVisitCount"] == 0
    assert row["completedDwellP50Ms"] == pytest.approx(200)
    assert row["occupiedSeconds"] == pytest.approx(.2)
    # A 200ms stop immediately after a rapid arrival is shorter than the
    # causal velocity window; occupancy/dwell must not become stopped proof.
    assert row["observedStoppedSeconds"] == 0
    assert row["occupancy"] == 0 and row["status"] == "empty"


def test_two_wheeler_is_a_vehicle_for_curb_measurements(engine):
    engine, _ = engine
    value = rule('occupancy-threshold')
    value['classes'] = ['two-wheeler']
    set_rule(engine, value)
    engine.put_mobility_config(MobilityConfig.model_validate({'curbs': [{'id': 'curb', 'name': 'Curb', 'zoneRuleId': 'rule-1'}]}))
    sample = frame(0).model_dump(by_alias=True)
    sample['objects'][0]['class'] = 'two-wheeler'
    engine.ingest(Observation.model_validate(sample))
    assert report(engine)['observedOccupancy'] == 1


def test_scope_archive_preserves_completed_curb_visit_and_dwell(engine):
    engine, _ = engine
    configure(engine)
    engine.reset_analytics_scope(kind="scenario", run_id="curb-run")
    for seconds, x in [(0, 10), (.1, 30), (.2, 30), (.3, 30), (.4, 90)]:
        engine.ingest(frame(seconds, x=x))
    before = engine.mobility.snapshot(engine, 5)
    assert before["curbs"][0]["completedVisitCount"] == 1
    assert before["curbs"][0]["completedDwellP50Ms"] == pytest.approx(200)
    engine.reset_analytics_scope(kind="normal")
    archive = engine.store.get("analytics-scopes:test")[-1]
    assert archive["runId"] == "curb-run"
    assert archive["mobility"] == before
    assert archive["observationEnd"]["reason"] == "scenario-boundary"
    assert report(engine)["completedVisitCount"] == 0
    assert report(engine)["completedDwellP50Ms"] is None


def test_sustained_stop_with_box_jitter_has_stopped_evidence(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0, x=10))
    for i in range(1, 41):
        engine.ingest(frame(i / 20, x=30 + .7 * (-1) ** i))
    row = report(engine)
    assert row['occupancy'] == row['stoppedCount'] == 1
    assert row['observedStoppedSeconds'] >= .8


def test_first_seen_inside_is_partial_and_can_have_observed_departure(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0))
    assert report(engine)["arrivalCount"] == 0
    assert report(engine)["partialVisitCount"] == 1
    assert report(engine)["stoppedCount"] is None
    engine.ingest(frame(.1))
    row = report(engine)
    assert row["persistentOccupancyCount"] == 1
    assert row["byClass"] == row["persistentByClass"] == {"car": 1}
    assert row["stoppedCount"] == 1
    engine.ingest(frame(.2, x=90))
    row = report(engine)
    assert row["departureCount"] == 1
    assert row["completedVisitCount"] == 0
    assert row["completedDwellP50Ms"] is None


@pytest.mark.parametrize("predicted", [False, True])
def test_short_occlusion_preserves_visit_without_counting_blind_interval(engine, predicted):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0, x=10))
    engine.ingest(frame(.1))
    if predicted:
        value = frame(.2).model_dump(by_alias=True)
        value["objects"][0]["observedThisFrame"] = False
        engine.ingest(Observation.model_validate(value))
    else:
        engine.ingest(frame(.2, objects=False))
    row = report(engine)
    assert row["status"] == "unknown" and row["occupancy"] is None
    assert row["pendingTrackCount"] == 1
    assert row["incompleteVisitCount"] == 0
    engine.ingest(frame(.3))
    assert report(engine)["arrivalCount"] == 1
    assert report(engine)["partialVisitCount"] == 0
    assert report(engine)["occupiedSeconds"] == 0
    engine.ingest(frame(.4))
    assert report(engine)["occupiedSeconds"] == pytest.approx(.1)
    engine.ingest(frame(.5, x=90))
    assert report(engine)["completedVisitCount"] == 1


def test_long_loss_is_incomplete_once_and_reacquisition_inside_is_partial(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0, x=10))
    engine.ingest(frame(.1))
    engine.ingest(frame(.4, objects=False))
    engine.ingest(frame(.5, objects=False))
    row = report(engine)
    assert row["incompleteVisitCount"] == 1
    assert row["departureCount"] == 0
    assert row["lostTrackCount"] == 1 and row["occupancy"] is None
    engine.ingest(frame(.6))
    row = report(engine)
    assert row["arrivalCount"] == 1 and row["partialVisitCount"] == 1
    assert row["lostTrackCount"] == 0 and row["occupancy"] == 1


def test_fresh_positive_occupancy_recovers_as_lower_bound_after_other_track_loss(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0))
    engine.ingest(frame(.3, objects=False))
    value = frame(.4).model_dump(by_alias=True)
    value["objects"][0]["localTrackId"] = "new-visible"
    engine.ingest(Observation.model_validate(value))
    row = report(engine)
    assert row["status"] == "active"
    assert row["occupancy"] == row["observedOccupancy"] == 1
    assert row["occupancyIsLowerBound"] is True
    assert row["lostTrackCount"] == 1
    assert row["departureCount"] == 0


def test_union_does_not_double_occupied_or_stopped_seconds(engine):
    engine, _ = engine
    configure(engine)
    for seconds in [0, .1, .2]:
        value = frame(seconds).model_dump(by_alias=True)
        value["objects"].append({**value["objects"][0], "localTrackId": "second"})
        engine.ingest(Observation.model_validate(value))
    row = report(engine)
    assert row["occupancy"] == row["stoppedCount"] == row["persistentOccupancyCount"] == 2
    assert row["occupiedSeconds"] == pytest.approx(.2)
    assert row["observedStoppedSeconds"] == pytest.approx(.1)


def test_wall_stall_keeps_history_and_does_not_emit_departure(engine):
    engine, clock = engine
    configure(engine)
    engine.ingest(frame(0))
    engine.ingest(frame(.1))
    clock.value += 3
    row = report(engine)
    assert row["occupiedSeconds"] == pytest.approx(.1)
    assert row["status"] == "unknown" and row["occupancy"] is None
    assert row["incompleteVisitCount"] == 1
    assert report(engine)["incompleteVisitCount"] == 1
    engine.ingest(frame(.2, x=90))
    assert report(engine)["departureCount"] == 0
    assert report(engine)["occupancy"] == 0


def test_session_reset_window_expiry_and_disabled_ref(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0))
    engine.ingest(frame(.1, x=90))
    engine.ingest(frame(61, x=90))
    assert report(engine, 1)["departureCount"] == 0
    assert report(engine, 5)["departureCount"] == 1
    engine.ingest(frame(0, session="new"))
    assert report(engine, 5)["departureCount"] == 0
    engine.put_rules(RuleSet(rules=[]))
    row = report(engine)
    assert row["status"] == "unknown" and row["occupancy"] is None
    assert "no longer exists" in row["qualityReasons"][0]


def test_track_capacity_is_bounded_and_disclosed(engine):
    engine, _ = engine
    configure(engine)
    engine.mobility._curb().max_tracks = 1
    for sequence in range(5):
        value = frame(sequence / 10).model_dump(by_alias=True)
        value["objects"][0]["localTrackId"] = str(sequence)
        engine.ingest(Observation.model_validate(value))
    state = engine.mobility.curb.rows["curb"]
    assert len(state["tracks"]) <= 1 and len(state["lost"]) <= 1
    assert report(engine)["occupancyIsLowerBound"]
    assert any("capacity" in reason for reason in report(engine)["qualityReasons"])


def test_uncalibrated_image_zone_has_occupancy_but_unknown_stopped_duration(engine):
    engine, _ = engine
    engine.site.sources[0].imageToGroundHomography = None
    configure(engine)
    for seconds in [0, .1, .2]:
        engine.ingest(frame(seconds))
    row = report(engine)
    assert row["occupancy"] == 1
    assert row["occupiedSeconds"] == pytest.approx(.2)
    assert row["stoppedCount"] is None
    assert row["observedStoppedSeconds"] is None
    assert row["stoppedEvidenceSeconds"] == 0


def test_projection_failure_outside_roi_does_not_poison_curb_occupancy(engine):
    engine, _ = engine
    configure(engine)
    saved = engine.rules[0].model_dump()
    saved["geometry"] = {"space": "site-metres", "points": [[2, 2], [8, 2], [8, 8], [2, 8]]}
    engine.put_rules(RuleSet.model_validate({"rules": [saved]}))
    # Geometry is still projectable; the validity mask excludes this road user.
    engine.site.sources[0].validGroundPolygon = [[20, 20], [80, 20], [80, 80], [20, 80]]
    engine.ingest(frame(0, x=90))
    assert next(iter(engine.tracks.values()))["positionM"] is None
    row = report(engine)
    assert row["status"] == "empty" and row["occupancy"] == 0


def test_lost_membership_expires_only_at_disclosed_horizon_without_departure(engine):
    engine, _ = engine
    configure(engine)
    engine.ingest(frame(0))
    engine.ingest(frame(.3, objects=False))
    engine.ingest(frame(60, objects=False))
    assert report(engine)["status"] == "unknown"
    engine.ingest(frame(901, objects=False))
    row = report(engine, 15)
    assert row["lostTrackCount"] == 0
    assert row["departureCount"] == row["turnoverCount"] == 0
    assert row["occupancy"] == 0
