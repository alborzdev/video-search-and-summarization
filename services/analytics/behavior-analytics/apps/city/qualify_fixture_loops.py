# SPDX-License-Identifier: Apache-2.0
"""Execute synthetic rule qualification in a private CPU engine and SQLite DB.

This module has no network access, Docker invocation, model loader or live-source
control. Its optional FastAPI TestClient uses only the private in-process app.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
import math
import os
import resource
import sys
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .engine import CityEngine
from .fixtures import EPOCH_NS, actors_at, fixture_rules, observations, package_site
from .models import Observation, RuleSet, Site
from .store import CityStore

DURATION = 20.0
COUNTS_PER_LOOP = {
    "area-entry": 1,
    "dwell": 1,
    "line-crossing": 4,
    "occupancy-threshold": 1,
    "queue": 1,
    "stopped-in-zone": 2,
    "wrong-way": 1,
}
HISTORY_BYTES = 32 * 1024 * 1024


class FixtureClock:
    value = 1000.0

    def __call__(self):
        return self.value


def configure(store: CityStore, clock: FixtureClock) -> CityEngine:
    engine = CityEngine(store, clock=clock, history_frames=4, max_tracks=64)
    engine.put_site(Site.model_validate(package_site(DURATION)))
    engine.put_rules(RuleSet.model_validate(fixture_rules()))
    return engine


def ingest(engine: CityEngine, clock: FixtureClock, payload: dict):
    clock.value = 1000 + (int(payload["sourceTimeNs"]) - EPOCH_NS) / 1e9
    result = engine.ingest(Observation.model_validate(payload))
    assert result["accepted"], result
    return result


def check_projection(snapshot: dict, media_time: float):
    expected = {name: [x, y] for name, x, y, *_ in actors_at(media_time)}
    for track in snapshot["tracks"]:
        assert track["confidence"] is None
        assert track["globalTrackId"] is None
        assert track["modelRevision"] == "synthetic-fixture-no-model"
        point = track["positionM"]
        if point is not None:
            target = expected[track["class"]]
            assert math.dist(point, target) < 1e-8
    assert snapshot["association"] == {"mode": "camera-local", "globalFusionEnabled": False}


def timeline(events: list[dict], round_index: int):
    epoch = EPOCH_NS + round(round_index * DURATION * 1e9)
    return sorted(
        (
            event["ruleId"],
            event["sourceId"],
            (int(event["startedAtNs"]) - epoch) / 1e9,
            (int(event["triggeredAtNs"]) - epoch) / 1e9,
            (int(event["endedAtNs"]) - epoch) / 1e9,
        )
        for event in events
    )


def check_event_history(engine: CityEngine, event: dict, fps: int):
    evidence = event["evidence"]
    assert evidence["status"] == "unavailable" and evidence["clipUrl"] is None
    assert event["mode"] == "fixture-replay"
    assert event["modelRevision"] == "synthetic-fixture-no-model"
    onset, trigger = evidence["startMediaTimeSeconds"], evidence["triggerMediaTimeSeconds"]
    assert onset is not None and trigger is not None and onset <= trigger + 1e-8
    assert abs((int(event["triggeredAtNs"]) - int(event["startedAtNs"])) / 1e9 - (trigger - onset)) < 1e-7
    before = engine.snapshot(source_id=event["sourceId"], media_time=max(0, trigger - 1 / fps), maximum_skew=1e-6)
    assert before["clockAligned"] is True
    assert event["id"] not in {item["id"] for item in before["events"]}
    at_trigger = engine.snapshot(source_id=event["sourceId"], media_time=trigger, maximum_skew=1e-6)
    assert at_trigger["clockAligned"] is True
    found = next(item for item in at_trigger["events"] if item["id"] == event["id"])
    assert found["state"] == ("cleared" if event["kind"] == "line-crossing" else "active")
    assert found["metrics"].get("count") == event["triggerMetrics"].get("count")
    assert set(found["trackIds"]) <= {track["id"] for track in at_trigger["tracks"]}
    check_projection(at_trigger, trigger)
    assert all(track["sessionId"] == event["sessionId"] for track in at_trigger["tracks"])
    assert at_trigger["sources"][0]["modelRevision"] == "synthetic-fixture-no-model"
    end_media = trigger + (int(event["endedAtNs"]) - int(event["triggeredAtNs"])) / 1e9
    cleared = engine.snapshot(source_id=event["sourceId"], media_time=end_media, maximum_skew=1e-6)
    assert next(item for item in cleared["events"] if item["id"] == event["id"])["state"] == "cleared"


@contextmanager
def private_app_environment(directory: Path):
    """Protect even the module-level app factory from ambient live paths."""
    values = {
        "CITY_STATE_DB": str(directory / "unused-module-app.sqlite3"),
        "CITY_MEDIA_ROOT": str(directory / "no-camera-media"),
        "CITY_MEDIA_REGISTRY_JSON": "{}",
        "CITY_NATIVE_CONFIG_DIR": "",
        "CITY_SITE_FILE": "",
        "CITY_RULES_FILE": "",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def api_reports(engine: CityEngine, directory: Path):
    from fastapi.testclient import TestClient

    was_imported = "apps.city.main" in sys.modules
    with private_app_environment(directory):
        main = importlib.import_module("apps.city.main")
        app = main.create_app(engine, media_registry={}, media_root=str(directory))
        with TestClient(app) as client:
            response = client.get("/api/v1/city/reports")
            assert response.status_code == 200
            report = response.json()
            response = client.get("/api/v1/city/reports?format=csv")
            assert response.status_code == 200
            rows = list(csv.DictReader(io.StringIO(response.text)))
            assert {row["id"] for row in rows} == {event["id"] for event in report["events"]}
            assert report["mode"] == "fixture-replay" and not report["truncated"]
        if not was_imported:
            main.app.state.city.store.close()
    return report, len(rows)


def reset_probe(fps: int):
    """A mid-incident source reset must mean unknown, never a fabricated exit."""
    clock, store = FixtureClock(), CityStore()
    engine = configure(store, clock)
    old_frames = {}
    for payload in observations(duration=9, fps=fps, session="reset-check", round_index=0):
        ingest(engine, clock, payload)
        old_frames[payload["sourceId"]] = payload
    active = {event["id"] for event in engine.events.values() if event["state"] == "active"}
    assert len(active) == 6
    new_frames = list(observations(duration=DURATION, fps=fps, session="reset-check", round_index=1))
    for payload in new_frames[:2]:
        ingest(engine, clock, payload)
        rejected = engine.ingest(Observation.model_validate(old_frames[payload["sourceId"]]))
        assert rejected["reason"] == "retired-session"
    assert all(engine.events[event_id]["state"] == "unknown" for event_id in active)
    assert all(engine.events[event_id]["stateReason"] == "source-session-reset" for event_id in active)
    assert all(track["velocityMps"] is None for track in engine.tracks.values())
    for payload in new_frames[2:]:
        ingest(engine, clock, payload)
        if payload["mediaTimeSeconds"] <= 2:
            assert not any(
                event["state"] == "active" and event["kind"] in {"dwell", "queue", "stopped-in-zone"}
                for event in engine.events.values()
            )
    new_events = [event for event in engine.events.values() if event["sessionId"] == "reset-check-1"]
    assert Counter(event["kind"] for event in new_events) == COUNTS_PER_LOOP
    assert all(event["state"] == "cleared" for event in new_events)
    store.close()
    return {
        "activeEventsMadeUnknown": len(active),
        "oldSessionFramesRejected": 2,
        "newSessionEvents": len(new_events),
        "velocityAndDurationStateReset": True,
        "fabricatedClears": 0,
    }


def qualify(loops: int = 30, fps: int = 5):
    if not 1 <= loops <= 30 or fps != 5:
        raise ValueError(
            "This deterministic qualification supports 1–30 complete loops at the fixed 5 FPS rule-test rate"
        )
    started = time.monotonic()
    hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("engine.py", "fixtures.py", "geometry.py", "models.py", "store.py", "main.py")
    }
    with tempfile.TemporaryDirectory(prefix="vss-city-synthetic-qualification-") as temporary:
        directory = Path(temporary)
        database = directory / "private-fixture.sqlite3"
        store = CityStore(str(database), max_history_bytes=HISTORY_BYTES)
        clock = FixtureClock()
        engine = configure(store, clock)
        accepted, duplicates, late, history_checks = 0, 0, 0, 0
        previous_first = {}
        expected_timeline = None
        all_ids = set()
        per_loop = []
        for round_index in range(loops):
            first = {}
            for payload in observations(
                duration=DURATION, fps=fps, session="qualification-loop", round_index=round_index
            ):
                ingest(engine, clock, payload)
                accepted += 1
                if payload["sequence"] == "0":
                    first[payload["sourceId"]] = payload
                    assert all(
                        track["velocityMps"] is None
                        for track in engine.tracks.values()
                        if track["sourceId"] == payload["sourceId"]
                    )
                    duplicate = engine.ingest(Observation.model_validate(payload))
                    assert duplicate["reason"] == "duplicate-or-out-of-order"
                    duplicates += 1
                    if previous_first:
                        rejected = engine.ingest(Observation.model_validate(previous_first[payload["sourceId"]]))
                        assert rejected["reason"] == "retired-session"
                        late += 1
                if payload["mediaTimeSeconds"] == DURATION:
                    duplicate = engine.ingest(Observation.model_validate(payload))
                    assert duplicate["reason"] == "duplicate-or-out-of-order"
                    duplicates += 1
            events = [
                event
                for event in store.events(1000, site_id=engine.site.id)
                if event["sessionId"] == f"qualification-loop-{round_index}"
            ]
            assert Counter(event["kind"] for event in events) == COUNTS_PER_LOOP
            assert len(events) == 11 and all(event["state"] == "cleared" for event in events)
            assert all(event["id"] not in all_ids for event in events)
            all_ids.update(event["id"] for event in events)
            current_timeline = timeline(events, round_index)
            if expected_timeline is None:
                expected_timeline = current_timeline
            else:
                assert current_timeline == expected_timeline
            for event in events:
                check_event_history(engine, event, fps)
                history_checks += 3
            shared = engine.snapshot(media_time=9, maximum_skew=1e-6)
            assert shared["clockAligned"] is True and len(shared["sources"]) == 2
            check_projection(shared, 9)
            positions = [
                {track["class"]: track["positionM"] for track in shared["tracks"] if track["sourceId"] == source["id"]}
                for source in shared["sources"]
            ]
            assert positions[0].keys() == positions[1].keys()
            assert all(math.dist(positions[0][name], positions[1][name]) < 1e-8 for name in positions[0])
            previous_first = first
            per_loop.append(
                {
                    "loop": round_index + 1,
                    "events": len(events),
                    "totalsByKind": dict(Counter(event["kind"] for event in events)),
                    "allCleared": True,
                    "sameRelativeTimeline": True,
                }
            )
        report, csv_rows = api_reports(engine, directory)
        expected_totals = {kind: count * loops for kind, count in COUNTS_PER_LOOP.items()}
        assert report["eventCount"] == 11 * loops and report["totalsByKind"] == expected_totals
        before_ids = {event["id"] for event in report["events"]}
        history_rows, history_bytes = store.connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM history"
        ).fetchone()
        assert history_bytes <= HISTORY_BYTES
        store.close()
        reopened = CityStore(str(database), max_history_bytes=HISTORY_BYTES)
        restored = CityEngine(reopened, clock=clock, history_frames=4, max_tracks=64)
        durable, durable_csv_rows = api_reports(restored, directory)
        assert durable["eventCount"] == report["eventCount"]
        assert durable["totalsByKind"] == expected_totals
        assert {event["id"] for event in durable["events"]} == before_ids
        assert durable_csv_rows == csv_rows == 11 * loops
        replay = restored.snapshot(media_time=9, maximum_skew=1e-6)
        assert replay["clockAligned"] is True and len(replay["tracks"]) == 12
        assert all(source["sessionId"] == f"qualification-loop-{loops - 1}" for source in replay["sources"])
        assert replay["mode"] == "fixture-replay"
        check_projection(replay, 9)
        check_reset = reset_probe(fps)
        reopened.close()
    assert all(
        hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest
        for name, digest in hashes.items()
    )
    return {
        "schemaVersion": "city.synthetic-rule-loop-qualification.v1",
        "capturedAt": datetime.now(UTC).isoformat(),
        "result": "passed",
        "mode": "fixture-replay",
        "qualification": "Synthetic geometry/rule execution only. No AI model inference, model accuracy, physical camera calibration, cross-camera identity fusion, RTSP or live UI qualification.",
        "isolation": {
            "engine": "private direct CityEngine",
            "database": "temporary private SQLite; removed after verification",
            "reports": "in-process FastAPI TestClient; no listener or network client",
            "nativeBridge": "disabled",
            "liveServicesMutated": False,
            "gpuUsed": False,
        },
        "completeLoops": loops,
        "secondsPerLoop": DURATION,
        "testRateFpsPerCamera": fps,
        "cameras": 2,
        "syntheticClasses": ["person", "bicycle", "car", "motorcycle", "bus", "truck"],
        "acceptedObservations": accepted,
        "duplicateObservationsRejected": duplicates,
        "lateRetiredSessionObservationsRejected": late,
        "ruleFamilies": sorted(COUNTS_PER_LOOP),
        "eventCount": durable["eventCount"],
        "totalsByKind": expected_totals,
        "eventIdsUniqueAcrossLoops": len(all_ids) == 11 * loops,
        "relativeTimelinesEqualAcrossLoops": True,
        "historicalBeforeTriggerAtTriggerAtClearChecks": history_checks,
        "linkedTwoViewProjectionChecks": loops,
        "syntheticVideoEvidenceUnavailable": True,
        "cameraLocalIdsNotFused": True,
        "durableJsonAndCsvEventCounts": {
            "beforeReopen": report["eventCount"],
            "afterReopen": durable["eventCount"],
            "csvRowsAfterReopen": durable_csv_rows,
        },
        "history": {
            "memoryCacheFramesPerCamera": 4,
            "sqliteFramesRetained": history_rows,
            "serializedBytesRetained": history_bytes,
            "serializedBytesQuota": HISTORY_BYTES,
            "latestLoopReplayAfterReopen": True,
        },
        "midIncidentResetProbe": check_reset,
        "perLoop": per_loop,
        "codeSha256": hashes,
        "elapsedWallSeconds": time.monotonic() - started,
        "maximumResidentMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loops", type=int, default=30)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.receipt.exists():
        parser.error("Receipt already exists; select a new output path to preserve evidence")
    result = qualify(arguments.loops)
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"perLoop", "codeSha256"}}, indent=2))


if __name__ == "__main__":
    main()
