# SPDX-License-Identifier: Apache-2.0
"""CPU-only exact frame preview API qualification, using a real static JPEG."""

from __future__ import annotations

import base64
import json
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from fastapi.testclient import TestClient

from apps.city.engine import CityEngine
from apps.city.main import create_app
from apps.city.models import Observation, RuleSet, Site
from apps.city.preview import (
    MAX_JPEG_BYTES,
    MAX_JSON_BYTES,
    MAX_NATIVE_STATUS_BYTES,
    FrameIdentity,
    PreviewError,
    PreviewStore,
    jpeg_dimensions,
    native_preview_status,
)

JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCABkAGQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDz+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD//2Q=="
)
BASE = 1_700_000_000_000_000_000


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


def observation(sequence=0, *, source="cam", session="session-a", ns=BASE, x=30, seen=True, size=100):
    return Observation.model_validate(
        {
            "siteId": "preview-test",
            "sourceId": source,
            "sourceSessionId": session,
            "sequence": str(sequence),
            "sourceTimeNs": str(ns),
            "timestampBasis": "recorded-pts",
            "mediaTimeSeconds": sequence / 10,
            "mediaTimeBasis": "gstreamer-segment-stream-time",
            "modelRevision": "model-sha256-test",
            "image": {"width": size, "height": size},
            "objects": [{"localTrackId": "car-a", "class": "car", "confidence": 0.9, "bboxPx": [x - 5, 30, 10, 10]}]
            if seen
            else [],
        }
    )


def headers(sample):
    return {
        "Content-Type": "image/jpeg",
        "X-City-Source-Id": sample.sourceId,
        "X-City-Session-Id": sample.sourceSessionId,
        "X-City-Sequence": sample.sequence,
        "X-City-Source-Time-Ns": sample.sourceTimeNs,
        "X-City-Width": str(sample.image.width),
        "X-City-Height": str(sample.image.height),
        "X-City-Model-Revision": sample.modelRevision,
    }


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv("CITY_NATIVE_CONFIG_DIR", raising=False)
    clock = Clock()
    engine = CityEngine(clock=clock, history_frames=4)
    engine.put_site(
        Site.model_validate(
            {
                "id": "preview-test",
                "mode": "recorded-inference",
                "sources": [
                    {
                        "id": "cam",
                        "width": 100,
                        "height": 100,
                        "inputUri": "rtsp://private-user:secret@private-camera/live",
                        "password": "secret",
                    }
                ],
            }
        )
    )
    engine.put_rules(
        RuleSet.model_validate(
            {
                "rules": [
                    {
                        "id": "zone",
                        "sourceId": "cam",
                        "kind": "area-entry",
                        "conditions": {"clearAfterMs": 0},
                        "geometry": {
                            "space": "image-normalized",
                            "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
                        },
                    }
                ]
            }
        )
    )
    app = create_app(engine, media_registry={})
    with TestClient(app) as client:
        yield engine, clock, app, client


def envelope(response):
    assert response.status_code == 200
    length = struct.unpack(">I", response.content[:4])[0]
    assert length <= MAX_JSON_BYTES
    dto = json.loads(response.content[4 : 4 + length])
    assert response.content[4 + length :] == JPEG
    return dto


def test_preview_encoding_does_not_run_on_asgi_event_loop(setup, monkeypatch):
    engine, _, app, client = setup
    sample = observation()
    engine.ingest(sample)
    # The TestClient portal owns the actual ASGI event loop thread.
    loop_thread = client.portal.call(threading.get_ident)
    store = app.state.previews
    original = store.accept
    threads = []

    def accept(*args):
        threads.append(threading.get_ident())
        return original(*args)

    monkeypatch.setattr(store, 'accept', accept)
    assert client.post('/api/v1/city/preview', content=JPEG, headers=headers(sample)).status_code == 201
    assert threads and all(thread != loop_thread for thread in threads)


def test_exact_frame_geometry_events_model_and_private_uri_redaction(setup):
    engine, _, app, client = setup
    first = observation()
    assert client.post("/api/v1/city/observations", json=first.model_dump(by_alias=True)).json()["accepted"]
    # Same camera timestamp, different sequence: a nearest-time lookup is wrong.
    assert client.post("/api/v1/city/observations", json=observation(1, x=90).model_dump(by_alias=True)).json()[
        "accepted"
    ]
    assert next(iter(engine.events.values()))["state"] == "cleared"
    response = client.post("/api/v1/city/preview", content=JPEG, headers=headers(first))
    assert response.status_code == 201
    dto = envelope(client.get("/api/v1/city/preview/cam"))
    assert dto["schemaVersion"] == "city.preview.v1"
    assert dto["sequence"] == "0" and dto["sourceTimeNs"] == str(BASE)
    assert dto["snapshot"]["tracks"][0]["bboxPx"] == [25, 30, 10, 10]
    assert dto["snapshot"]["events"][0]["state"] == "active"
    assert dto["snapshot"]["sources"][0]["sequence"] == "0"
    assert dto["snapshot"]["sources"][0]["sourceSessionId"] == first.sourceSessionId
    assert dto["modelRevision"] == first.modelRevision
    assert dto["timestampBasis"] == "recorded-pts"
    assert dto["provenance"]["browserClockVerified"] is False
    assert dto["snapshot"]["clockAligned"] is None
    serialized = json.dumps(dto)
    assert "private-camera" not in serialized and "secret" not in serialized
    # Image bytes are volatile; accepted observation count and durable metadata do not change.
    assert len(engine.histories["cam"]) == 2
    assert engine.sources["cam"]["lastSequence"] == 1
    assert app.state.previews.health()["retainedBytes"] <= 4 + MAX_JSON_BYTES + MAX_JPEG_BYTES
    for row in engine.store.connection.execute("SELECT value FROM history"):
        assert "image/jpeg" not in row[0] and "JFIF" not in row[0]


def test_display_bounds_repeated_history_but_keeps_all_active_states_and_trail_span(setup):
    engine, _, _, client = setup
    first = observation()
    engine.ingest(first)
    sample = engine.histories["cam"][-1]
    template = sample["events"][0]
    sample["events"] = [{**deepcopy(template), "id": str(index),
                         "state": "active" if index in {12, 48, 99} else "cleared",
                         "message": "Historical event detail " * 40}
                        for index in range(100)]
    sample["tracks"][0]["trail"] = [{"positionM": [index, index / 2], "sourceTimeNs": str(BASE + index)}
                                     for index in range(40)]
    original = deepcopy(sample)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(first)).status_code == 201
    dto = envelope(client.get("/api/v1/city/preview/cam"))
    shown = dto["snapshot"]
    assert [event["id"] for event in shown["events"] if event["state"] == "active"] == ["12", "48", "99"]
    assert [event["id"] for event in shown["events"] if event["state"] != "active"] == list(map(str, range(8)))
    assert dto["displayScope"]["omittedOtherEvents"] == 89
    trail = shown["tracks"][0]["trail"]
    assert len(trail) == 12
    assert trail[0] == original["tracks"][0]["trail"][0]
    assert trail[-1] == original["tracks"][0]["trail"][-1]
    assert all(point in original["tracks"][0]["trail"] for point in trail)
    assert [int(point["sourceTimeNs"]) for point in trail] == sorted(int(point["sourceTimeNs"]) for point in trail)
    assert sample == original
    unbounded = {**shown, "events": sample["events"], "tracks": sample["tracks"]}
    assert len(json.dumps(shown)) < len(json.dumps(unbounded)) / 3


def test_preview_preserves_frame_evidence_reasons_without_mutating_history(setup):
    engine, _, _, client = setup
    engine.ingest(observation())
    missing = observation(1, ns=BASE + 2_000_000_000, seen=False)
    engine.ingest(missing)
    assert engine.metrics["zone"]["evidenceReasons"] == ["observation-gap"]
    samples = deepcopy(list(engine.histories["cam"]))
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(missing)).status_code == 201
    assert list(engine.histories["cam"]) == samples
    # A later observed exit must not rewrite the already paired frame or its reason.
    engine.ingest(observation(2, ns=BASE + 2_100_000_000, x=90))
    assert engine.metrics["zone"]["evidenceReasons"] == []
    dto = envelope(client.get("/api/v1/city/preview/cam"))
    assert dto["snapshot"]["metrics"][0]["evidenceReasons"] == ["observation-gap"]
    assert dto["snapshot"]["metrics"][0]["status"] == "unknown"
    assert "secret" not in json.dumps(dto)


def test_jpeg_before_metadata_waits_without_ingesting_and_pending_is_bounded(setup):
    engine, _, _, client = setup
    sample = observation()
    with ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(client.post, "/api/v1/city/preview", content=JPEG, headers=headers(sample))
        time.sleep(0.04)
        assert not engine.sources
        engine.ingest(sample)
        assert response.result(timeout=2).status_code == 201
    pending = observation(2, ns=BASE + 2)
    started = time.monotonic()
    response = client.post("/api/v1/city/preview", content=JPEG, headers=headers(pending))
    assert response.status_code == 202 and response.json()["retryable"] is True
    assert time.monotonic() - started < 1
    assert engine.sources["cam"]["lastSequence"] == 0


def test_exact_preview_preserves_class_specific_ground_calibration(setup):
    engine, _, _, client = setup
    site = engine.site_json()
    road = [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]]
    person = [[0.1, 0, 1], [0, 0.1, 2], [0, 0, 1]]
    site["sources"][0].update(imageToGroundHomography=road,
                               classImageToGroundHomographies={"person": person})
    engine.put_site(Site.model_validate(site))
    sample = observation()
    sample.objects[0].class_name = "person"
    engine.ingest(sample)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 201
    dto = envelope(client.get("/api/v1/city/preview/cam"))
    source = dto["snapshot"]["sources"][0]
    assert source["imageToGroundHomography"] == road
    assert source["classImageToGroundHomographies"] == {"person": person}
    assert dto["snapshot"]["tracks"][0]["positionM"] == [4.0, 6.0]
    assert "secret" not in json.dumps(dto)


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("X-City-Source-Id", "absent", 404),
        ("X-City-Model-Revision", "other", 409),
        ("X-City-Source-Time-Ns", str(BASE + 1), 409),
        ("X-City-Width", "99", 409),
        ("X-City-Sequence", "-1", 422),
        ("Content-Type", "image/png", 415),
    ],
)
def test_mismatched_identity_headers_rejected(setup, field, value, status):
    engine, _, _, client = setup
    sample = observation()
    engine.ingest(sample)
    changed = {**headers(sample), field: value}
    assert client.post("/api/v1/city/preview", content=JPEG, headers=changed).status_code == status
    assert client.get("/api/v1/city/preview/cam").status_code == 204


def test_duplicate_sequence_supersession_and_duplicate_clock_handling(setup):
    engine, _, _, client = setup
    first, second = observation(), observation(1, x=40)
    for sample in (first, second):
        engine.ingest(sample)
        assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 201
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(second)).status_code == 200
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(first)).status_code == 409
    assert envelope(client.get("/api/v1/city/preview/cam"))["sequence"] == "1"


def test_freshness_etag_and_generation_or_session_invalidates_payload(setup):
    engine, clock, app, client = setup
    sample = observation()
    engine.ingest(sample)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 201
    first = client.get("/api/v1/city/preview/cam")
    assert client.get("/api/v1/city/preview/cam", headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    clock.value += 2.01
    assert client.get("/api/v1/city/preview/cam").status_code == 204
    assert client.get("/api/v1/city/site").json()["sources"][0]["processedPreview"]["status"] == "stale"
    assert app.state.previews.health()["retainedBytes"] == 0
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 409
    new = observation(0, session="session-b", ns=BASE + 5)
    engine.ingest(new)
    assert client.get("/api/v1/city/preview/cam").headers["x-city-preview-status"] == "waiting"
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(new)).status_code == 201
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 409
    engine.put_rules(RuleSet.model_validate({"rules": []}))
    assert client.get("/api/v1/city/preview/cam").status_code == 204
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(new)).status_code == 409


def test_conditional_wait_wakes_on_the_next_exact_frame_without_blocking_other_routes(setup, monkeypatch):
    engine, _, app, client = setup
    first, second = observation(), observation(1, ns=BASE + 100_000_000, x=40)
    engine.ingest(first)
    client.post("/api/v1/city/preview", content=JPEG, headers=headers(first))
    etag = client.get("/api/v1/city/preview/cam").headers["etag"]
    checked = Event()
    original = app.state.previews.get

    def get(source_id):
        value = original(source_id)
        checked.set()
        return value

    monkeypatch.setattr(app.state.previews, "get", get)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(client.get, "/api/v1/city/preview/cam?waitMs=1000", headers={"If-None-Match": etag})
        assert checked.wait(1)
        assert not waiting.done()
        assert client.get("/api/v1/city/health").status_code == 200
        engine.ingest(second)
        assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(second)).status_code == 201
        result = waiting.result(timeout=1)
    assert result.headers["etag"] != etag
    assert envelope(result)["sequence"] == "1"


def test_conditional_wait_times_out_and_rechecks_session_invalidation(setup, monkeypatch):
    engine, _, app, client = setup
    sample = observation()
    engine.ingest(sample)
    client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample))
    etag = client.get("/api/v1/city/preview/cam").headers["etag"]
    assert client.get("/api/v1/city/preview/cam?waitMs=5", headers={"If-None-Match": etag}).status_code == 304
    checked = Event()
    original = app.state.previews.get

    def get(source_id):
        value = original(source_id)
        checked.set()
        return value

    monkeypatch.setattr(app.state.previews, "get", get)
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(client.get, "/api/v1/city/preview/cam?waitMs=50", headers={"If-None-Match": etag})
        assert checked.wait(1)
        engine.ingest(observation(0, session="new-session", ns=BASE + 1))
        assert waiting.result(timeout=1).status_code == 204
    for value in (-1, 1001):
        assert client.get(f"/api/v1/city/preview/cam?waitMs={value}").status_code == 422


@pytest.mark.parametrize("registered_media", [False, True])
def test_site_get_put_does_not_persist_capability_or_reset_exact_frame(setup, registered_media):
    engine, _, _, client = setup
    if registered_media:
        engine.media["cam"] = "/controlled/registered.mp4"
    sample = observation()
    engine.ingest(sample)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 201
    generation = engine.frame_generation
    site = client.get("/api/v1/city/site").json()
    assert site["sources"][0]["processedPreview"]["available"] is True
    assert client.put("/api/v1/city/site", json=site).status_code == 200
    assert engine.frame_generation == generation
    assert "processedPreview" not in engine.site.sources[0].model_extra
    assert envelope(client.get("/api/v1/city/preview/cam"))["sequence"] == "0"


def test_stale_tracks_keep_observation_flags_not_invented_frame_boxes(setup):
    engine, _, _, client = setup
    engine.ingest(observation())
    missing = observation(1, ns=BASE + 100_000_000, seen=False)
    engine.ingest(missing)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(missing)).status_code == 201
    track = envelope(client.get("/api/v1/city/preview/cam"))["snapshot"]["tracks"][0]
    assert track["observedThisFrame"] is False and track["stale"] is True
    assert track["sourceTimeNs"] != missing.sourceTimeNs


def test_internal_reset_epoch_and_removed_source_cannot_serve_old_jpeg(setup):
    engine, _, app, client = setup
    first = observation()
    engine.ingest(first)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(first)).status_code == 201
    reset = observation(ns=BASE + 100_000_000).model_copy(update={"reset": True})
    engine.ingest(reset)
    assert client.get("/api/v1/city/preview/cam").status_code == 204
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(reset)).status_code == 201
    dto = envelope(client.get("/api/v1/city/preview/cam"))
    assert dto["sourceSessionId"] == first.sourceSessionId
    assert dto["sessionId"].endswith("reset-1")
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(first)).status_code == 409
    site = engine.site.model_dump()
    site["sources"] = []
    engine.put_site(Site.model_validate(site))
    assert client.get("/api/v1/city/preview/cam").status_code == 404
    assert app.state.previews.health()["retainedBytes"] == 0


def test_valid_jpeg_wrong_aspect_and_evicted_exact_frame_are_rejected(setup):
    engine, _, _, client = setup
    site = engine.site.model_dump()
    site["sources"][0]["height"] = 200
    engine.put_site(Site.model_validate(site))
    sample = observation().model_dump(by_alias=True)
    sample["image"]["height"] = 200
    sample = Observation.model_validate(sample)
    engine.ingest(sample)
    assert jpeg_dimensions(JPEG) == (100, 100)
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(sample)).status_code == 409
    site["sources"][0]["height"] = 100
    engine.put_site(Site.model_validate(site))
    for sequence in range(6):
        engine.ingest(observation(sequence))
    assert len(engine.histories["cam"]) == 4
    assert client.post("/api/v1/city/preview", content=JPEG, headers=headers(observation())).status_code == 409


def test_invalid_and_oversized_jpeg_bodies_are_bounded_before_store(setup):
    engine, _, app, client = setup
    sample = observation()
    engine.ingest(sample)
    for body, expected in [(b"not-jpeg", 422), (JPEG[:-2], 422), (b"x" * (MAX_JPEG_BYTES + 1), 413)]:
        assert client.post("/api/v1/city/preview", content=body, headers=headers(sample)).status_code == expected

    def chunks():
        yield b"x" * MAX_JPEG_BYTES
        yield b"x"

    assert client.post("/api/v1/city/preview", content=chunks(), headers=headers(sample)).status_code == 413
    assert app.state.previews.health()["retainedBytes"] == 0


def test_scaled_jpeg_geometry_capacity_and_json_bound(monkeypatch):
    engine = CityEngine(clock=Clock())
    engine.put_site(
        Site.model_validate(
            {
                "id": "preview-test",
                "mode": "live",
                "sources": [{"id": source, "width": 200, "height": 200} for source in ["a", "b", "c"]],
            }
        )
    )
    store = PreviewStore(engine)
    for source in ["a", "b", "c"]:
        sample = observation(source=source, size=200)
        engine.ingest(sample)
        identity = FrameIdentity.headers({key.lower(): value for key, value in headers(sample).items()})
        if source == "c":
            with pytest.raises(PreviewError, match="capacity"):
                store.accept(identity, JPEG, jpeg_dimensions(JPEG))
        else:
            assert store.accept(identity, JPEG, jpeg_dimensions(JPEG))["accepted"]
            body, _, _ = store.get(source)
            dto = json.loads(body[4 : 4 + struct.unpack(">I", body[:4])[0]])
            assert dto["image"]["width"] == 200 and dto["image"]["jpegWidth"] == 100
    assert len(store.frames) == 2
    engine.put_rules(RuleSet.model_validate({"rules": []}))
    sample = observation(1, source="a", size=200)
    engine.ingest(sample)
    monkeypatch.setattr("apps.city.preview.MAX_JSON_BYTES", 64)
    with pytest.raises(PreviewError, match="metadata-too-large"):
        store.accept(
            FrameIdentity.headers({key.lower(): value for key, value in headers(sample).items()}), JPEG, (100, 100)
        )
    assert store.health()["retainedBytes"] == 0


def test_serialization_releases_engine_lock_but_keeps_its_exact_history_row(setup, monkeypatch):
    engine, _, app, _ = setup
    store = app.state.previews
    first = observation(0, x=30)
    engine.ingest(first)
    identity = FrameIdentity.headers({key.lower(): value for key, value in headers(first).items()})
    entered, release = Event(), Event()
    encode = store._encode

    def paused(dto):
        entered.set()
        assert release.wait(2)
        return encode(dto)

    monkeypatch.setattr(store, "_encode", paused)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(store.accept, identity, JPEG, (100, 100))
        assert entered.wait(1)
        # This ingest must finish while encoding is blocked. A borrowed live
        # track would also replace the old bbox with the newer x=70 observation.
        ingest = workers.submit(engine.ingest, observation(1, x=70, ns=BASE + 100_000_000))
        try:
            assert ingest.result(timeout=0.5)["accepted"]
        finally:
            release.set()
        assert pending.result(timeout=1)["accepted"]
    body, _, _ = store.get("cam")
    dto = json.loads(body[4:4 + struct.unpack(">I", body[:4])[0]])
    assert dto["sequence"] == "0"
    assert dto["snapshot"]["tracks"][0]["bboxPx"][0] == 25
    assert dto["snapshot"]["sources"][0]["sequence"] == "0"


def test_native_stage_timings_are_bounded_public_summaries(tmp_path):
    good = {"count": 20, "mean": 10.5, "last": 20, "max": 20, "p50Upper": 10, "p95Upper": 20}
    value = {"schemaVersion": "city.preview-native-status.v1", "enabled": True, "failed": False,
             "updatedAtNs": str(time.time_ns()), "sources": [{"sourceId": "cam", "timingMs": {
                 "post": {**good, "inputUri": "rtsp://private", "rawSamples": [1, 2, 3]},
                 "postQueue": {**good, "mean": float("inf")},
                 "selectedToJpeg": {**good, "count": True}, "unknown-private-stage": good}}]}
    (tmp_path / "preview-stats.json").write_text(json.dumps(value))
    status = native_preview_status(tmp_path, {"cam": {}})
    assert status["sources"][0]["timingMs"] == {"post": good}


@pytest.mark.parametrize("change", ["rules", "session", "eviction", "expiry", "newer-preview"])
def test_serialized_frame_cannot_publish_after_concurrent_supersession(setup, monkeypatch, change):
    engine, clock, app, _ = setup
    store = app.state.previews
    first = observation(0)
    engine.ingest(first)
    identity = FrameIdentity.headers({key.lower(): value for key, value in headers(first).items()})
    entered, release = Event(), Event()
    encode = store._encode

    def paused(dto):
        if dto["sequence"] == "0":
            entered.set()
            assert release.wait(2)
        return encode(dto)

    monkeypatch.setattr(store, "_encode", paused)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(store.accept, identity, JPEG, (100, 100))
        assert entered.wait(1)

        def mutate():
            if change == "rules":
                engine.put_rules(RuleSet.model_validate({"rules": []}))
            elif change == "session":
                engine.ingest(observation(0, session="new-native-session"))
            elif change == "expiry":
                clock.value += 3
            else:
                for sequence in range(1, 6 if change == "eviction" else 2):
                    engine.ingest(observation(sequence, ns=BASE + sequence * 100_000_000))
                if change == "newer-preview":
                    second = observation(1, ns=BASE + 100_000_000)
                    ident = FrameIdentity.headers({key.lower(): value for key, value in headers(second).items()})
                    assert store.accept(ident, JPEG, (100, 100))["accepted"]

        mutation = workers.submit(mutate)
        try:
            mutation.result(timeout=0.5)
        finally:
            release.set()
        with pytest.raises(PreviewError):
            pending.result(timeout=1)
    if change == "newer-preview":
        assert store.frames["cam"]["sequence"] == "1"
        assert store.accepted == 1
    else:
        assert store.accepted == 0


def test_native_delivery_counters_are_bounded_sanitized_and_never_clock_proof(tmp_path, setup, monkeypatch):
    engine, _, _, _ = setup
    monkeypatch.setenv("CITY_NATIVE_CONFIG_DIR", str(tmp_path))
    value = {
        "schemaVersion": "city.preview-native-status.v1",
        "enabled": True,
        "failed": False,
        "updatedAtNs": str(time.time_ns()),
        "error": "rtsp://secret:password@private-host",
        "fpsLimitPerSource": 15,
        "sources": [
            {
                "sourceId": "cam",
                "published": 42,
                "observedPublishedFps": 14.9,
                "lastPublishedAtNs": str(time.time_ns()),
                "inputUri": "rtsp://secret@private-host",
                "password": "secret",
            },
            {"sourceId": "retired-camera", "published": 99},
        ],
    }
    path = tmp_path / "preview-stats.json"
    path.write_text(json.dumps(value))
    with TestClient(create_app(engine, media_registry={})) as client:
        health = client.get("/api/v1/city/health").json()["processedPreview"]
    native = health["nativeDelivery"]
    assert native["status"] == "fresh" and native["enabled"] is True
    assert native["sources"] == [
        {
            "sourceId": "cam",
            "published": 42,
            "observedPublishedFps": 14.9,
            "lastPublishedAtNs": value["sources"][0]["lastPublishedAtNs"],
        }
    ]
    assert "secret" not in json.dumps(native) and "private-host" not in json.dumps(native)
    assert health["acceptedFrames"] == 0  # delivery counters do not invent a correlated frame
    value["updatedAtNs"] = str(time.time_ns() - 10_000_000_000)
    path.write_text(json.dumps(value))
    assert native_preview_status(tmp_path, {"cam"})["status"] == "stale"


def test_native_status_missing_malformed_and_oversize_are_safe(tmp_path):
    assert native_preview_status(None, {"cam"})["status"] == "not-connected"
    assert native_preview_status(tmp_path, {"cam"})["status"] == "missing"
    path = tmp_path / "preview-stats.json"
    for data in ("{not-json", "x" * (MAX_NATIVE_STATUS_BYTES + 1), json.dumps({"schemaVersion": "other"})):
        path.write_text(data)
        status = native_preview_status(tmp_path, {"cam"})
        assert status == {"status": "invalid", "enabled": False, "failed": False, "sources": []}


def test_pipeline_diagnostics_are_bounded_public_counters(tmp_path):
    value = {'schemaVersion': 'city.preview-native-status.v1', 'updatedAtNs': str(time.time_ns()),
             'pipeline': {'detectorCadence': 1, 'muxTimeoutUs': 10000, 'batches': 50,
                          'inferredFrames': 55, 'trackedFrames': 54, 'fullBatches': -1,
                          'preprocessInferPathMs': {'mean': 10.5, 'p95Upper': 20},
                          'trackerAnalyticsPathMs': {'mean': float('nan'), 'p95Upper': 20},
                          'private': 'secret'},
             'sources': [{'sourceId': 'cam', 'decoder': 'hardware', 'decoderExtraSurfaces': 4}]}
    (tmp_path / 'preview-stats.json').write_text(json.dumps(value))
    result = native_preview_status(tmp_path, {'cam'})
    assert result['pipeline'] == {'detectorCadence': 1, 'muxTimeoutUs': 10000, 'batches': 50,
                                  'inferredFrames': 55, 'trackedFrames': 54,
                                  'preprocessInferPathMs': {'mean': 10.5, 'p95Upper': 20}}
    assert result['sources'] == [{'sourceId': 'cam', 'decoder': 'hardware', 'decoderExtraSurfaces': 4}]


def test_sse_snapshot_work_does_not_block_other_async_requests(monkeypatch):
    import asyncio
    import threading
    from apps.city.engine import CityEngine
    from apps.city.main import create_app

    engine = CityEngine()
    original = engine.snapshot
    release = threading.Event()
    timed_out = []
    def slow_snapshot():
        if not release.wait(timeout=1):
            timed_out.append(True)
        return original()
    monkeypatch.setattr(engine, 'snapshot', slow_snapshot)
    app = create_app(engine)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/v1/city/stream')
    class Viewer:
        async def is_disconnected(self): return False
    async def run():
        response = await endpoint(Viewer())
        pending_frame = asyncio.create_task(anext(response.body_iterator))
        # A separate request on the event loop must make progress while a
        # viewer's expensive snapshot is being built.
        async def unrelated_request():
            release.set()
        await asyncio.create_task(unrelated_request())
        frame = await pending_frame
        await response.body_iterator.aclose()
        assert 'event: snapshot' in frame and 'data: ' in frame
    asyncio.run(run())
    assert not timed_out
