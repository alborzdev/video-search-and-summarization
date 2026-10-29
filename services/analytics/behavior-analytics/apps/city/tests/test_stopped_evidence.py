# SPDX-License-Identifier: Apache-2.0
"""Real-only motion history and bounded stopped-incident evidence contracts."""
from copy import deepcopy

import pytest

from test_city import engine, frame, rule, set_rule
from apps.city.engine import STOP_PENDING_REASON
from apps.city.models import Observation


def feed(engine, seconds, *, observed=True, objects=True, x=30, local_id=None, class_name=None):
    sample = frame(seconds, x=x, seq=round(seconds * 100), objects=objects).model_dump(by_alias=True)
    if objects:
        obj = sample["objects"][0]
        obj["observedThisFrame"] = observed
        if local_id is not None:
            obj["localTrackId"] = local_id
        if class_name is not None:
            obj["class"] = class_name
    assert engine.ingest(Observation.model_validate(sample))["accepted"]
    return next(iter(engine.tracks.values()), None)


def stopped(engine, minimum=200, gap=1000, clear=200):
    set_rule(engine, rule("stopped-in-zone", minimumDurationMs=minimum,
        maximumObservationGapMs=gap, clearAfterMs=clear, speedBelowMps=.35))


def event(engine):
    return next(iter(engine.events.values()))


def obstruction(engine):
    return engine.mobility_json(1)["obstructions"][0]


@pytest.mark.parametrize("predicted", [False, True])
def test_short_missing_or_predicted_frame_preserves_only_real_motion_history(engine, predicted):
    engine, _ = engine
    for seconds in [0, .1, .2]:
        track = feed(engine, seconds)
    before = deepcopy(track["motionSamples"])
    track = feed(engine, .3, objects=predicted, observed=False, x=75)
    assert track["motionSamples"] == before
    if predicted:
        assert track["speedMps"] is None
    track = feed(engine, .4)
    assert track["speedMps"] == pytest.approx(0)
    assert len(track["motionSamples"]) == len(before) + 1
    assert all(sample[1:] == [3, 4] for sample in track["motionSamples"])


@pytest.mark.parametrize("change", ["source-gap", "wall-gap", "identity", "class"])
def test_real_motion_history_cannot_bridge_long_gap_or_new_identity(engine, change):
    engine, clock = engine
    for seconds in [0, .1, .2]:
        feed(engine, seconds)
    if change == "wall-gap":
        clock.value += 3
    track = feed(engine, 1.3 if change == "source-gap" else .3,
        local_id="another" if change == "identity" else None,
        class_name="truck" if change == "class" else None)
    if change == "identity":
        track = next(track for track in engine.tracks.values() if track["localTrackId"] == "another")
    assert track["speedMps"] is None
    assert len(track["motionSamples"]) == 1


def test_pending_incident_retains_identity_but_never_counts_blind_time(engine):
    engine, _ = engine
    stopped(engine)
    for seconds in [0, .1, .2, .3]:
        feed(engine, seconds)
    incident = event(engine)
    assert incident["state"] == "active"
    identity = incident["id"]
    before = obstruction(engine)["blockedSeconds"]
    feed(engine, .4, objects=False)
    assert incident["id"] == identity and incident["state"] == "active"
    assert incident["stopEvidenceStatus"] == "pending"
    assert incident["stateReason"] == STOP_PENDING_REASON
    assert engine.metrics["rule-1"]["status"] == "unknown"
    assert engine.metrics["rule-1"]["evidenceReasons"] == [STOP_PENDING_REASON]
    pending = obstruction(engine)
    assert pending["pendingEvidenceEpisodes"] == 1
    assert pending["ongoingEpisodes"] == 0
    assert pending["blockedSeconds"] == before
    feed(engine, .5)
    assert incident["state"] == "active" and incident["stopEvidenceStatus"] == "confirmed"
    assert incident["stateReason"] is None
    assert incident["latestMetrics"]["durationMs"] == pytest.approx(200)
    assert obstruction(engine)["blockedSeconds"] == before
    feed(engine, .6)
    assert incident["latestMetrics"]["durationMs"] == pytest.approx(300)
    assert obstruction(engine)["blockedSeconds"] == pytest.approx(before + .1)
    assert len(engine.events) == 1


def test_short_gap_during_candidate_does_not_advance_duration_threshold(engine):
    engine, _ = engine
    stopped(engine, minimum=400)
    for seconds in [0, .1, .2]:
        feed(engine, seconds)
    feed(engine, .3, objects=False)
    for seconds in [.5, .6, .7]:
        feed(engine, seconds)
        assert not engine.events
    feed(engine, .8)
    assert event(engine)["triggerMetrics"]["durationMs"] == pytest.approx(400)
    assert event(engine)["startedAtNs"] == frame(.1).sourceTimeNs


def test_pending_expires_at_existing_gap_limit_and_stop_must_requalify(engine):
    engine, _ = engine
    stopped(engine)
    for seconds in [0, .1, .2, .3]:
        feed(engine, seconds)
    incident = event(engine)
    before = obstruction(engine)["blockedSeconds"]
    feed(engine, .4, objects=False)
    feed(engine, 1.4, objects=False)
    assert incident["state"] == "unknown"
    assert incident["stopEvidenceStatus"] == "unknown"
    for seconds in [1.5, 1.6, 1.7]:
        feed(engine, seconds)
        assert incident["state"] == "unknown"
    feed(engine, 1.8)
    assert incident["state"] == "active"
    assert incident["latestMetrics"]["durationMs"] == pytest.approx(200)
    assert obstruction(engine)["blockedSeconds"] == before


def test_fresh_movement_during_recovery_requires_actual_clear_and_does_not_count_stopped_time(engine):
    engine, _ = engine
    stopped(engine)
    for seconds in [0, .1, .2, .3]:
        feed(engine, seconds)
    incident = event(engine)
    before = obstruction(engine)["blockedSeconds"]
    feed(engine, .4, objects=False)
    feed(engine, .5, x=40)
    assert incident["state"] == "active" and incident["stopEvidenceStatus"] == "clearing"
    feed(engine, .6, x=50)
    feed(engine, .7, x=60)
    assert incident["state"] == "cleared"
    assert incident["stopEvidenceStatus"] == "cleared"
    assert obstruction(engine)["blockedSeconds"] == before


def test_class_change_cannot_resume_pending_incident(engine):
    engine, _ = engine
    stopped(engine)
    for seconds in [0, .1, .2, .3]:
        feed(engine, seconds)
    incident = event(engine)
    feed(engine, .4, objects=False)
    feed(engine, .5, class_name="truck")
    assert incident["state"] == "unknown" and incident["stateReason"] == "track-class-changed"
    assert incident["stopEvidenceStatus"] == "unknown"
    assert len(engine.events) == 1


def test_queue_recovery_uses_real_history_but_prediction_is_not_stationary_evidence(engine):
    engine, _ = engine
    set_rule(engine, rule("queue", minimumDurationMs=100, maximumObservationGapMs=1000,
        countThreshold=1, speedBelowMps=.35))
    for seconds in [0, .1, .2]:
        feed(engine, seconds)
    feed(engine, .3, observed=False, x=75)
    assert engine.metrics["rule-1"]["status"] == "unknown"
    track = feed(engine, .4)
    assert track["speedMps"] == pytest.approx(0)
    assert engine.metrics["rule-1"]["count"] == 1
    feed(engine, .5)
    assert engine.metrics["rule-1"]["status"] == "active"


def test_historical_pending_evidence_does_not_become_a_continuous_duration(engine):
    engine, _ = engine
    stopped(engine)
    for seconds in [0, .1, .2, .3]:
        feed(engine, seconds)
    feed(engine, .4, objects=False)
    feed(engine, .5)
    feed(engine, .6)
    pending = engine.snapshot(source_id="cam-1", media_time=.4)["events"][0]
    assert pending["state"] == "active" and pending["stopEvidenceStatus"] == "pending"
    assert pending["metrics"]["durationMs"] is None
    assert pending["durationStatus"] == "unavailable-observation-gap"
    assert "stopEvidenceAtNs" not in pending and "latestMetrics" not in pending
    recovered = engine.snapshot(source_id="cam-1", media_time=.6)["events"][0]
    assert recovered["stopEvidenceStatus"] == "confirmed"
    assert recovered["metrics"]["durationMs"] is None
