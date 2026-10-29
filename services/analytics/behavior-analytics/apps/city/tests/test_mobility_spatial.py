# SPDX-License-Identifier: Apache-2.0
"""Small CPU controls for observed spatial mobility; no model or scene runs."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.city.mobility_spatial import MobilitySpatial
from apps.city.models import Rule, Source


SOURCE = Source(id="cam", width=100, height=100,
    imageToGroundHomography=[[1, 0, 0], [0, 1, 0], [0, 0, 1]])


def polygon_rule(id, points, classes, **extra):
    return Rule(id=id, sourceId="cam", kind="occupancy-threshold", classes=classes,
        geometry={"space": "site-metres", "points": points}, **extra)


QUEUE = polygon_rule("queue", [[-3, 0], [3, 0], [3, 100], [-3, 100]], ["car"])
WAIT = polygon_rule("wait", [[-2, -5], [2, -5], [2, 0], [-2, 0]], ["person"])
CROSS = polygon_rule("cross", [[-2, 0], [2, 0], [2, 10], [-2, 10]], ["person"])
CONFIG = {"queues": [{"id": "q", "name": "North", "zoneRuleId": "queue",
    "stopLine": [[-3, 0], [3, 0]], "upstreamPoint": [0, 100], "spillbackDistanceM": 15,
    "maxAnchorGapM": 10, "stopLineReachM": 8, "minimumDurationMs": 500}],
    "crossings": [{"id": "p", "name": "Crosswalk", "waitingRuleId": "wait", "crossingRuleId": "cross"}]}


def track(id, x, y, *, kind="car", speed=0, observed=True, source="cam", session="s"):
    return {"id": id, "sourceId": source, "sessionId": session, "class": kind,
        "positionM": [x, y], "anchorPx": [x, y], "speedMps": speed,
        "observedThisFrame": observed, "stale": not observed}


def update(engine, seconds, tracks, *, session="s", config=CONFIG, rules=None):
    ns = round(seconds * 1e9)
    tracks = [{**t, "lastObservedSourceTimeNsInt": ns, "sourceTimeNsInt": ns} for t in tracks]
    return engine.update("cam", session, ns, tracks, rules or [QUEUE, WAIT, CROSS], SOURCE, config)


def person(x, y, id="person"):
    return track(id, x, y, kind="person")


def test_queue_connected_extent_excludes_isolated_stop_and_moving_vehicle():
    engine = MobilitySpatial()
    tracks = [track("a", 0, 5), track("b", 0, 14), track("c", 0, 23),
        track("isolated", 0, 80), track("moving", 0, 30, speed=5)]
    first = update(engine, 0, tracks)["queues"][0]
    assert first["status"] == "candidate"
    row = update(engine, .5, tracks)["queues"][0]
    assert row["status"] == "spillback"
    assert row["count"] == 3
    assert row["trackIds"] == ["a", "b", "c"]
    assert row["observedExtentM"] == 23
    assert row["tailPositionM"] == [0, 23]
    assert row["spillback"] is True
    assert row["stopLineM"] == [[-3, 0], [3, 0]]


def test_two_wheeler_contributes_to_vehicle_queue_when_selected():
    engine = MobilitySpatial()
    queue = polygon_rule('queue', [[-3, 0], [3, 0], [3, 100], [-3, 100]], ['two-wheeler'])
    sample = [track('wheel', 0, 5, kind='two-wheeler')]
    update(engine, 0, sample, rules=[queue, WAIT, CROSS])
    row = update(engine, .5, sample, rules=[queue, WAIT, CROSS])['queues'][0]
    assert row['count'] == 1
    assert row['trackIds'] == ['wheel']


def test_queue_missing_member_stays_unknown_until_actual_reobservation():
    engine = MobilitySpatial()
    tracks = [track("a", 0, 5), track("b", 0, 14)]
    update(engine, 0, tracks)
    update(engine, .5, tracks)
    for seconds in (1, 1.5):
        row = update(engine, seconds, [tracks[0]])["queues"][0]
        assert row["status"] == "unknown"
        assert row["spillback"] is None
        assert row["extentIsLowerBound"] is True
    row = update(engine, 2, [tracks[0], track("b", 8, 14)])["queues"][0]
    assert row["status"] == "candidate"  # observed outside is evidence of departure


def test_queue_gap_breaks_persistence_and_prediction_cannot_extend_it():
    engine = MobilitySpatial()
    update(engine, 0, [track("a", 0, 5)])
    assert update(engine, 2, [track("a", 0, 5)])["queues"][0]["status"] == "unknown"
    assert update(engine, 2.1, [track("a", 0, 5)])["queues"][0]["status"] == "candidate"
    assert update(engine, 2.6, [track("a", 0, 5)])["queues"][0]["status"] == "queued"
    row = update(engine, 2.7, [track("a", 0, 90, observed=False)])["queues"][0]
    assert row["status"] == "unknown"
    assert row["tailPositionM"] is None


def test_queue_is_lower_bound_near_zone_boundary():
    engine = MobilitySpatial()
    tracks = [track(str(y), 0, y) for y in range(5, 100, 9)]
    update(engine, 0, tracks)
    row = update(engine, .5, tracks)["queues"][0]
    assert row["extentIsLowerBound"] is True
    assert "boundary" in " ".join(row["qualityReasons"])


def test_new_spillback_boundary_reach_must_persist_separately():
    engine = MobilitySpatial()
    front = [track("a", 0, 5), track("b", 0, 14)]
    update(engine, 0, front)
    update(engine, .5, front)
    extended = front + [track("tail", 0, 22)]
    assert update(engine, 1, extended)["queues"][0]["spillback"] is False
    row = update(engine, 1.5, extended)["queues"][0]
    assert row["spillback"] is True
    assert row["spillbackDurationMs"] == 500


def test_observed_wait_cross_far_exit_produces_sample_and_completion():
    engine = MobilitySpatial()
    for seconds, y in [(0, -6), (.5, -3), (1, -2), (1.5, 1), (2, 9), (2.5, 11), (2.6, 11.2)]:
        row = update(engine, seconds, [person(0, y)])["crossings"][0]
    assert row["completedCount"] == 1
    assert row["waitSampleCount"] == 1
    assert row["waitP50Ms"] == 1000
    assert row["waitP95Ms"] == 1000
    assert row["waitingCount"] == row["crossingCount"] == 0


def test_first_seen_wait_is_lower_bound_excluded_from_wait_percentiles():
    engine = MobilitySpatial()
    for seconds, y in [(0, -3), (.5, 1), (1, 9), (1.5, 11), (1.6, 11.2)]:
        row = update(engine, seconds, [person(0, y)])["crossings"][0]
    assert row["completedCount"] == 1
    assert row["waitSampleCount"] == 0
    assert row["waitP50Ms"] is None


@pytest.mark.parametrize("destination,outcome", [((0, -6), "abandonedCount"), ((0, -2), "returnedCount"), ((3, 5), "incompleteCount")])
def test_departure_return_and_side_exit_are_distinct(destination, outcome):
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -6)])
    update(engine, .5, [person(0, -3)])
    if outcome != "abandonedCount":
        update(engine, 1, [person(0, 5)])
    row = update(engine, 1.5 if outcome != "abandonedCount" else 1, [person(*destination)])["crossings"][0]
    if outcome != "abandonedCount":
        assert row[outcome] == 0
        row = update(engine, 1.6, [person(*destination)])["crossings"][0]
    assert row[outcome] == 1
    assert row["completedCount"] == 0


def test_missing_track_unknown_then_expired_without_fabricated_exit_or_join():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -3)])
    row = update(engine, .5, [person(0, -3, id="other")])["crossings"][0]
    assert row["status"] == "unknown"
    assert row["incompleteCount"] == 0
    assert row["pendingTrackCount"] == 1
    assert row["abandonedCount"] == row["completedCount"] == 0
    update(engine, 1, [person(0, -3, id="other")])
    row = update(engine, 1.5, [person(0, 5), person(0, -3, id="other")])["crossings"][0]
    assert row["incompleteCount"] == 1
    row = update(engine, 2, [person(0, 11), person(0, -3, id="other")])["crossings"][0]
    assert row["completedCount"] == 0


def test_lost_waiter_does_not_silently_turn_into_known_empty_occupancy():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -3)])
    for seconds in (.5, 1, 1.5):
        row = update(engine, seconds, [])["crossings"][0]
        assert row["status"] == "unknown"
        assert row["incompleteCount"] == int(seconds > 1)
        assert row["abandonedCount"] == 0
    row = update(engine, 2, [person(0, -6)])["crossings"][0]
    assert row["status"] == "active"
    assert row["waitingCount"] == 0
    assert row["abandonedCount"] == 0  # reacquisition does not fill the gap


def test_snapshot_window_filters_samples_without_changing_source_identity():
    engine = MobilitySpatial()
    for seconds, y in [(0, -6), (.5, -3), (1, 1), (1.5, 9), (2, 11), (2.1, 11.2)]:
        update(engine, seconds, [person(0, y)])
    row = engine.snapshot(1, {"cam": 63_000_000_000})["crossings"][0]
    assert row["completedCount"] == 0
    row = engine.snapshot(5, {"cam": 63_000_000_000})["crossings"][0]
    assert row["completedCount"] == 1
    assert row["sourceId"] == "cam"


def test_reset_session_and_configuration_break_continuity_and_history():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -3)])
    row = update(engine, .5, [{**person(0, 5), "sessionId": "new"}], session="new")["crossings"][0]
    assert row["waitSampleCount"] == 0
    row = update(engine, 1, [{**person(0, 11), "sessionId": "new"}], session="new")["crossings"][0]
    assert row["completedCount"] == 0
    engine.reset("cam", "camera-stale")
    result = engine.snapshot()
    assert result["crossings"][0]["status"] == "unknown"
    assert result["queues"][0]["currentCountsAvailable"] is False
    assert result["crossings"][0]["currentCountsAvailable"] is False
    assert result["queues"][0]["observedExtentM"] is None
    changed = {**CONFIG, "crossings": [{**CONFIG["crossings"][0], "name": "New geometry"}]}
    row = update(engine, 1.5, [{**person(0, -3), "sessionId": "new"}], session="new", config=changed)["crossings"][0]
    assert row["name"] == "New geometry"


def test_foreign_camera_and_predicted_person_are_not_counted():
    engine = MobilitySpatial()
    row = update(engine, 0, [person(0, -3), track("foreign", 0, -3, kind="person", source="other"),
        track("prediction", 0, -3, kind="person", observed=False),
        track("old-session", 0, -3, kind="person", session="retired")])["crossings"][0]
    assert row["waitingCount"] == 1


def test_capacity_and_non_monotonic_frames_are_bounded():
    engine = MobilitySpatial(max_tracks=2)
    first = update(engine, 1, [person(0, -3, str(i)) for i in range(5)])
    assert len(engine.sources["cam"]["crossings"]["p"]["tracks"]) == 2
    assert first["crossings"][0]["status"] == "unknown"
    assert update(engine, .5, []) == first


def test_window_validation():
    with pytest.raises(ValueError):
        MobilitySpatial().snapshot(2)


def test_snapshot_expiry_keeps_history_but_hides_current_extent():
    engine = MobilitySpatial()
    update(engine, 0, [track("a", 0, 5)])
    update(engine, .5, [track("a", 0, 5)])
    result = engine.snapshot(5, {"cam": 2_000_000_000})
    assert result["queues"][0]["status"] == "unknown"
    assert result["queues"][0]["observedExtentM"] is None
    assert result["queues"][0]["maximumObservedExtentM"] == 5
    assert result["crossings"][0]["status"] == "unknown"


def test_ingest_can_skip_report_serialization(monkeypatch):
    engine = MobilitySpatial()
    monkeypatch.setattr(engine, "snapshot", lambda **kwargs: pytest.fail("ingest must not build a report"))
    assert engine.update("cam", "s", 0, [], [QUEUE, WAIT, CROSS], SOURCE, CONFIG, emit_snapshot=False) is None
    assert engine.sources["cam"]["lastNs"] == 0


def test_wall_stale_preserves_history_and_does_not_prove_zone_clearance():
    engine = MobilitySpatial()
    for seconds, y in [(0, -6), (.5, -3), (1, 1)]:
        update(engine, seconds, [person(0, y), track("car", 0, 5)])
    engine.reset("cam", "source-stale")
    engine.reset("cam", "source-stale")  # repeated health polling is idempotent
    result = engine.snapshot(5, {"cam": 1_000_000_000})
    assert result["crossings"][0]["waitSampleCount"] == 1
    assert result["crossings"][0]["incompleteCount"] == 1
    assert result["queues"][0]["maximumObservedExtentM"] == 5
    result = update(engine, 1.5, [])
    assert result["crossings"][0]["status"] == "unknown"
    assert result["queues"][0]["status"] == "unknown"
    engine.reset("cam", "source-session-reset")
    result = engine.snapshot(5, {"cam": 1_500_000_000})
    assert result["crossings"][0]["waitSampleCount"] == 0
    assert result["queues"][0]["maximumObservedExtentM"] is None


def test_queue_rule_minimum_count_prevents_single_vehicle_spillback():
    engine = MobilitySpatial()
    queue = QUEUE.model_copy(update={"kind": "queue", "conditions": QUEUE.conditions.model_copy(update={"countThreshold": 2})})
    rules = [queue, WAIT, CROSS]
    config = {**CONFIG, "queues": [{**CONFIG["queues"][0], "spillbackDistanceM": 3}]}
    update(engine, 0, [track("car", 0, 5)], rules=rules, config=config)
    row = update(engine, .5, [track("car", 0, 5)], rules=rules, config=config)["queues"][0]
    assert row["status"] == "candidate"
    assert row["spillback"] is False
    update(engine, 1, [track("car", 0, 5), track("second", 0, 14)], rules=rules, config=config)
    row = update(engine, 1.5, [track("car", 0, 5), track("second", 0, 14)], rules=rules, config=config)["queues"][0]
    assert row["status"] == "spillback"


def test_unprojected_vehicle_only_invalidates_queue_when_image_exclusion_is_unproven():
    engine = MobilitySpatial()
    outside = {**track("unprojected", 40, 40), "positionM": None}
    valid = track("queue-car", 0, 5)
    update(engine, 0, [valid, outside])
    row = update(engine, .5, [valid, outside])["queues"][0]
    assert row["status"] == "queued"
    assert row["trackIds"] == ["queue-car"]
    # No valid ground anchor inside the image zone must still be unknown.
    inside = {**outside, "anchorPx": [0, 10]}
    assert update(engine, 1, [valid, inside])["queues"][0]["status"] == "unknown"
    # An inverse horizon crossing the zone prevents safe image exclusion.
    source = SOURCE.model_copy(update={"imageToGroundHomography": [[1, 0, 0], [0, 1, 0], [0, .02, 1]]})
    rows = [{**t, "lastObservedSourceTimeNsInt": 0} for t in (valid, outside)]
    result = MobilitySpatial().update("cam", "s", 0, rows, [QUEUE, WAIT, CROSS], source, CONFIG)
    assert result["queues"][0]["status"] == "unknown"


def test_brief_same_identity_miss_recovers_crossing_without_duplicate_incomplete():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -6)])
    update(engine, .2, [person(0, -3)])
    missing = update(engine, .4, [])["crossings"][0]
    assert missing["waitingCount"] == 0  # no predicted person counted
    assert missing["pendingTrackCount"] == 1
    assert missing["incompleteCount"] == 0
    update(engine, .6, [person(0, -2)])
    update(engine, .8, [person(0, 1)])
    update(engine, 1, [person(0, 9)])
    row = update(engine, 1.2, [person(0, 11)])["crossings"][0]
    assert row["completedCount"] == 0
    row = update(engine, 1.3, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == row["waitSampleCount"] == 1
    assert row["incompleteCount"] == 0
    assert row["briefGapRecoveredWaitCount"] == 1
    assert row["waitP50Ms"] == 600


def test_expired_partial_visit_counts_incomplete_only_once_until_observed_new_entry():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -3)])
    update(engine, .5, [])
    update(engine, 1, [])
    row = update(engine, 1.5, [])["crossings"][0]
    assert row["incompleteCount"] == 1
    assert row["lostTrackCount"] == 1
    update(engine, 2, [person(0, -3)])
    update(engine, 2.5, [])
    update(engine, 3, [])
    assert update(engine, 3.5, [])["crossings"][0]["incompleteCount"] == 1
    update(engine, 4, [person(0, -6)])
    update(engine, 4.5, [person(0, -3)])
    update(engine, 5, [])
    update(engine, 5.5, [])
    assert update(engine, 6, [])["crossings"][0]["incompleteCount"] == 2


def test_positive_queue_recovers_as_lower_bound_after_lost_member_expires():
    engine = MobilitySpatial()
    update(engine, 0, [track("old", 0, 5)])
    update(engine, .5, [])
    update(engine, 1, [])
    row = update(engine, 1.5, [])["queues"][0]
    assert row["lostTrackCount"] == 1
    assert row["count"] == 0 and row["countBasis"] == "currently-observed"
    assert row["observedExtentM"] is None and row["spillback"] is None
    update(engine, 2, [track("new", 0, 5)])
    row = update(engine, 2.5, [track("new", 0, 5)])["queues"][0]
    assert row["status"] == "queued"
    assert row["observedExtentM"] == 5 and row["extentIsLowerBound"]
    assert not row["membershipComplete"] and row["spillback"] is None


def test_expired_loss_history_does_not_poison_future_observed_empty_epoch():
    engine = MobilitySpatial()
    update(engine, 0, [track("old", 0, 5), person(0, -3)])
    for second in (1, 2, 903, 903.5):
        result = update(engine, second, [])
    queue, crossing = result["queues"][0], result["crossings"][0]
    assert queue["status"] == "empty" and queue["countBasis"] == "currently-observed"
    assert queue["lostTrackCount"] == queue["unresolvedHistoricalTrackCount"] == 0
    assert queue["clearanceConfirmed"] is False
    assert crossing["status"] == "active" and crossing["lostTrackCount"] == 0


def test_subpixel_crossing_boundary_jitter_does_not_create_return_or_new_wait():
    engine = MobilitySpatial()
    for seconds, y in [(0, -6), (.2, -3), (.4, 1), (.6, -.1), (.8, .1), (1, 9), (1.2, 11), (1.3, 11.2)]:
        row = update(engine, seconds, [person(0, y)])["crossings"][0]
    assert row["waitSampleCount"] == row["completedCount"] == 1
    assert row["returnedCount"] == 0


def test_first_seen_wait_reports_lower_bound_without_inventing_entry_sample():
    engine = MobilitySpatial()
    update(engine, 0, [person(0, -3)])
    row = update(engine, .5, [person(0, 1)])["crossings"][0]
    assert row["waitSampleCount"] == 0
    assert row["firstSeenWaitingCount"] == 1
    assert row["lowerBoundWaitP50Ms"] == 500


@pytest.mark.parametrize("start,inside,completed", [((0, -6), (0, 1), 1), ((-3, 5), (0, 5), 0), ((0, 11), (0, 9), 0)])
def test_direct_near_side_crossing_can_complete_without_wait_sample(start, inside, completed):
    engine = MobilitySpatial()
    update(engine, 0, [person(*start)])
    update(engine, .5, [person(*inside)])
    update(engine, 1, [person(0, 9)])
    update(engine, 1.5, [person(0, 11)])
    row = update(engine, 1.6, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == completed
    assert row["waitSampleCount"] == row["firstSeenWaitingCount"] == 0


@pytest.mark.parametrize("exit_point,completed", [((-36.1, 64.2), 1), ((-34.9, 62.5), 0), ((-16.2, 64.2), 0)])
def test_offset_waiting_centroid_uses_actual_far_edge_not_farthest_corner(exit_point, completed):
    engine = MobilitySpatial()
    waiting = polygon_rule("wait", [[-16.9, 61], [-12.9, 61], [-12.9, 70.3], [-16.9, 70.3]], ["person"])
    crossing = polygon_rule("cross", [[-35.5, 63.3], [-16.9, 63.3], [-16.9, 70.3], [-35.5, 70.3]], ["person"])
    for seconds, point in [(0, (-14, 64.2)), (.5, (-18, 64.2)), (1, (-34.9, 64.2)), (1.5, exit_point), (1.6, exit_point)]:
        row = update(engine, seconds, [person(*point)], rules=[QUEUE, waiting, crossing])["crossings"][0]
    assert row["completedCount"] == completed
    assert row["waitSampleCount"] == 0  # first seen in approach; no invented arrival


def crossing_journey(engine):
    """An actually observed waiting entry followed by two inside anchors."""
    for seconds, point in [(0, (0, -6)), (.2, (0, -3)), (.4, (0, 1)), (.6, (0, 4))]:
        update(engine, seconds, [person(*point)])


def test_single_side_spike_preserves_journey_but_never_counts_outside_occupancy():
    engine = MobilitySpatial()
    crossing_journey(engine)
    row = update(engine, .791, [person(3.1, 4)])["crossings"][0]
    assert row["crossingCount"] == row["waitingCount"] == 0
    assert row["completedCount"] == row["incompleteCount"] == 0
    assert row["pendingExitTrackCount"] == 1
    assert row["pendingTrackCount"] == 0  # observed outside, not briefly missing
    assert row["status"] == "unknown" and not row["membershipComplete"]
    assert "second fresh observation" in " ".join(row["qualityReasons"])
    state = engine.sources["cam"]["crossings"]["p"]["tracks"]["person"]
    assert state["lastCrossingPoint"] == [0, 4]
    assert state["lastCrossingNs"] == 600_000_000
    assert state["pendingExit"]["category"] == "incomplete"

    recovered = update(engine, .845, [person(0, 4.2)])["crossings"][0]
    assert recovered["crossingCount"] == 1 and recovered["status"] == "active"
    assert recovered["incompleteCount"] == recovered["pendingExitTrackCount"] == 0
    assert recovered["recoveredExitCandidateCount"] == 1
    update(engine, 1, [person(0, 9)])
    assert update(engine, 1.2, [person(0, 11)])["crossings"][0]["completedCount"] == 0
    row = update(engine, 1.3, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == row["waitSampleCount"] == 1
    assert row["incompleteCount"] == 0
    terminal = engine.sources["cam"]["crossings"]["p"]["outcomes"][-1]
    assert terminal["firstObservedExitNs"] == "1200000000"
    assert terminal["exitConfirmationSamples"] == 2
    assert terminal["ns"] == 1_300_000_000


def test_single_far_side_spike_and_reentry_does_not_complete_early():
    engine = MobilitySpatial()
    crossing_journey(engine)
    assert update(engine, .7, [person(0, 11)])["crossings"][0]["completedCount"] == 0
    row = update(engine, .8, [person(0, 4.1)])["crossings"][0]
    assert row["completedCount"] == row["incompleteCount"] == 0
    assert row["crossingCount"] == row["recoveredExitCandidateCount"] == 1
    assert row["pendingExitTrackCount"] == 0


@pytest.mark.parametrize("position,outcome", [((3.1, 4), "incompleteCount"), ((0, -2), "returnedCount"), ((0, 11), "completedCount")])
def test_two_fresh_same_category_exit_observations_confirm_once(position, outcome):
    engine = MobilitySpatial()
    crossing_journey(engine)
    first = update(engine, .7, [person(*position)])["crossings"][0]
    assert first[outcome] == 0 and first["crossingCount"] == 0
    row = update(engine, .8, [person(*position)])["crossings"][0]
    assert row[outcome] == 1 and row["pendingExitTrackCount"] == 0
    assert update(engine, .9, [person(*position)])["crossings"][0][outcome] == 1


@pytest.mark.parametrize("next_sample", [[], [track("person", 0, 11, kind="person", observed=False)]])
def test_single_exit_then_loss_or_prediction_never_proves_completion(next_sample):
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(0, 11)])
    row = update(engine, .8, next_sample)["crossings"][0]
    assert row["completedCount"] == row["incompleteCount"] == 0
    assert row["crossingCount"] == 0 and row["pendingExitTrackCount"] == 1
    # Expiry is measured from the real inside anchor at .6, not the exit at .7.
    row = update(engine, 1.61, [])["crossings"][0]
    assert row["completedCount"] == 0 and row["incompleteCount"] == 1
    assert row["pendingExitTrackCount"] == 0 and row["status"] == "unknown"
    assert update(engine, 1.8, [])["crossings"][0]["incompleteCount"] == 1


def test_exit_category_changes_and_boundary_ambiguity_cannot_slide_inside_deadline():
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(3.1, 4)])
    # This outside anchor is within half a pixel of the far boundary. It must
    # neither count as an inside recovery nor refresh the trusted inside time.
    row = update(engine, .8, [person(0, 10.1)])["crossings"][0]
    assert row["crossingCount"] == row["completedCount"] == row["recoveredExitCandidateCount"] == 0
    update(engine, 1.2, [person(0, 11)])
    row = update(engine, 1.61, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == 0 and row["incompleteCount"] == 1


def test_changed_exit_category_requires_its_own_second_observation():
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(3.1, 4)])
    row = update(engine, .8, [person(0, 11)])["crossings"][0]
    assert row["completedCount"] == row["incompleteCount"] == 0
    row = update(engine, .9, [person(0, 11.1)])["crossings"][0]
    assert row["completedCount"] == 1 and row["incompleteCount"] == 0


def test_another_identity_cannot_confirm_exit_or_inherit_the_journey():
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(0, 11)])
    update(engine, .8, [person(0, 11.1, id="other")])
    row = update(engine, 1.61, [person(0, 11.2, id="other")])["crossings"][0]
    assert row["completedCount"] == 0 and row["incompleteCount"] == 1


def test_observed_class_change_invalidates_pending_exit_before_person_returns():
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(0, 11)])
    row = update(engine, .8, [track("person", 0, 11, kind="bicycle")])["crossings"][0]
    assert row["completedCount"] == 0 and row["incompleteCount"] == 1
    assert row["pendingExitTrackCount"] == 0
    row = update(engine, .9, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == 0 and row["incompleteCount"] == 1


@pytest.mark.parametrize("boundary", ["session", "calibration", "configuration", "reset"])
def test_pending_exit_cannot_confirm_across_continuity_boundaries(boundary):
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(0, 11)])
    if boundary == "session":
        row = update(engine, .8, [{**person(0, 11.2), "sessionId": "new"}], session="new")["crossings"][0]
    elif boundary == "calibration":
        ns = 800_000_000
        t = {**person(0, 11.2), "sourceTimeNsInt": ns, "lastObservedSourceTimeNsInt": ns}
        source = SOURCE.model_copy(update={"calibrationRevision": "changed"})
        row = engine.update("cam", "s", ns, [t], [QUEUE, WAIT, CROSS], source, CONFIG)["crossings"][0]
    elif boundary == "configuration":
        changed = {**CONFIG, "crossings": [{**CONFIG["crossings"][0], "name": "Changed"}]}
        row = update(engine, .8, [person(0, 11.2)], config=changed)["crossings"][0]
    else:
        engine.reset("cam", "source-stale")
        row = update(engine, .8, [person(0, 11.2)])["crossings"][0]
    assert row["completedCount"] == row["pendingExitTrackCount"] == 0


def test_duplicate_source_time_or_old_observation_cannot_confirm_exit():
    engine = MobilitySpatial()
    crossing_journey(engine)
    update(engine, .7, [person(0, 11)])
    assert update(engine, .7, [person(0, 11.2)])["crossings"][0]["completedCount"] == 0
    t = {**person(0, 11.2), "sourceTimeNsInt": 800_000_000, "lastObservedSourceTimeNsInt": 700_000_000}
    row = engine.update("cam", "s", 800_000_000, [t], [QUEUE, WAIT, CROSS], SOURCE, CONFIG)["crossings"][0]
    assert row["completedCount"] == 0 and row["pendingExitTrackCount"] == 1
