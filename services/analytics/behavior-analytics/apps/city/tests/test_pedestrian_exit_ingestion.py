# SPDX-License-Identifier: Apache-2.0
"""Real CityEngine ingestion boundaries around pending pedestrian exits."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.city.engine import CityEngine
from apps.city.models import MobilityConfig, Observation, RuleSet, Site


def configured_engine():
    engine = CityEngine(clock=lambda: 100.0)
    engine.put_site(Site.model_validate({"id": "test", "mode": "fixture-replay",
        "sources": [{"id": "cam", "width": 100, "height": 200,
            "imageToGroundHomography": [[.1, 0, 0], [0, .1, 0], [0, 0, 1]],
            "calibrationRevision": "fixture-only"}],
        "map": {"bounds": [0, 0, 10, 20]}}))
    engine.put_rules(RuleSet.model_validate({"rules": [
        {"id": "wait", "sourceId": "cam", "kind": "occupancy-threshold", "classes": ["person"],
            "geometry": {"space": "site-metres", "points": [[2, 0], [8, 0], [8, 4], [2, 4]]}},
        {"id": "cross", "sourceId": "cam", "kind": "occupancy-threshold", "classes": ["person"],
            "geometry": {"space": "site-metres", "points": [[2, 4], [8, 4], [8, 14], [2, 14]]}}]}))
    engine.put_mobility_config(MobilityConfig.model_validate({"crossings": [
        {"id": "p", "name": "Fixture crossing", "waitingRuleId": "wait", "crossingRuleId": "cross"}]}))
    return engine


def ingest(engine, seq, y, *, kind="person", session="s", reset=False):
    observation = Observation.model_validate({"siteId": "test", "sourceId": "cam", "sourceSessionId": session,
        "sequence": str(seq), "sourceTimeNs": str(1_700_000_000_000_000_000 + seq * 100_000_000),
        "timestampBasis": "fixture-epoch-plus-pts", "image": {"width": 100, "height": 200}, "reset": reset,
        "objects": [{"localTrackId": "same-sdk-handle", "class": kind, "confidence": .9,
            "bboxPx": [45, y * 10 - 10, 10, 10], "observedThisFrame": True}]})
    assert engine.ingest(observation)["accepted"] is True
    return engine.mobility_json()["crossings"][0]


def pending_engine():
    engine = configured_engine()
    for seq, y in [(1, 2), (2, 5), (3, 10), (4, 15)]:
        row = ingest(engine, seq, y)
    assert row["pendingExitTrackCount"] == 1 and row["completedCount"] == 0
    return engine


def test_actual_ingestion_class_change_then_person_return_cannot_complete():
    engine = pending_engine()
    row = ingest(engine, 5, 16, kind="bicycle")
    assert row["incompleteCount"] == 1 and row["pendingExitTrackCount"] == row["completedCount"] == 0
    row = ingest(engine, 6, 17)
    assert row["incompleteCount"] == 1 and row["completedCount"] == 0
    assert next(iter(engine.tracks.values()))["class"] == "person"


@pytest.mark.parametrize("boundary", ["new-session", "explicit-reset"])
def test_actual_ingestion_session_boundary_cannot_confirm_previous_exit(boundary):
    engine = pending_engine()
    row = ingest(engine, 5, 16, session="new" if boundary == "new-session" else "s", reset=boundary == "explicit-reset")
    assert row["completedCount"] == row["pendingExitTrackCount"] == 0
    row = ingest(engine, 6, 17, session="new" if boundary == "new-session" else "s")
    assert row["completedCount"] == 0


def test_public_mobility_json_exposes_numeric_recovery_not_internal_outcome_enum():
    engine = configured_engine()
    for seq, y in [(1, 2), (2, 5), (3, 10), (4, 15), (5, 10)]:
        ingest(engine, seq, y)
    report = engine.mobility_json()
    encoded = json.dumps(report, allow_nan=False)
    row = report["crossings"][0]
    assert row["recoveredExitCandidateCount"] == 1 and row["completedCount"] == 0
    assert row["completionBasis"] == "observed-far-side-exit"
    assert "exit-candidate-recovered" not in encoded
    assert "outcomes" not in row
