# SPDX-License-Identifier: Apache-2.0
"""Explicit geometry/event fixtures. These are NOT AI model observations.

Use only on a dedicated city gateway. Never runs on import or live startup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import urllib.request
import uuid


CLASSES = ["car", "bus", "truck", "person", "bicycle", "motorcycle"]
EPOCH_NS = 1_700_000_000_000_000_000


def fixture_site():
    return {"id": "city-geometry-fixture", "name": "Geometry fixture · synthetic observations", "revision": 1, "mode": "fixture-replay", "fixtureLabel": "Synthetic geometry and event test — not AI inference", "sources": [{"id": "fixture-north", "name": "Fixture camera A · synthetic", "width": 1000, "height": 1000, "deepstreamStreamIndex": 0, "imageToGroundHomography": [[0.1, 0, -50], [0, -0.1, 50], [0, 0, 1]], "validGroundPolygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "calibrationRevision": "fixture-exact-1"}, {"id": "fixture-east", "name": "Fixture camera B · synthetic", "width": 1000, "height": 1000, "deepstreamStreamIndex": 1, "imageToGroundHomography": [[0, 0.1, -50], [0.1, 0, -50], [0, 0, 1]], "validGroundPolygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "calibrationRevision": "fixture-exact-1"}], "map": {"bounds": [-50, -50, 50, 50], "roads": [{"id": "east-west", "name": "Fixture street", "points": [[-50, 0], [50, 0]], "width": 20}, {"id": "north-south", "name": "Fixture avenue", "points": [[0, -50], [0, 50]], "width": 18}], "buildings": [{"id": name, "points": points} for name, points in [("north-west", [[-46, 17], [-17, 17], [-17, 45], [-46, 45]]), ("north-east", [[17, 17], [45, 17], [45, 45], [17, 45]]), ("south-west", [[-46, -45], [-17, -45], [-17, -17], [-46, -17]]), ("south-east", [[17, -45], [45, -45], [45, -17], [17, -17]])]]}}


def package_site(duration=20.0):
    site = fixture_site()
    site["map"]["bounds"] = [-45, -35, 45, 35]
    site["map"]["roads"][0]["points"] = [[-45, 0], [45, 0]]
    site["map"]["roads"][1]["points"] = [[0, -35], [0, 35]]
    for building in site["map"]["buildings"]:
        building["points"] = [[max(-44, min(44, x)), max(-34, min(34, y))] for x, y in building["points"]]
    for source in site["sources"]:
        source.update(fixtureDurationSeconds=duration, durationSeconds=duration)
    return site


def image_anchor(source_id, x, y):
    if source_id == "fixture-north":
        return [(x + 50) * 10, (50 - y) * 10]
    return [(y + 50) * 10, (x + 50) * 10]


def image_geometry(source_id, polygon):
    return {"space": "image-normalized", "points": [[v / 1000 for v in image_anchor(source_id, *point)] for point in polygon]}


def fixture_rules():
    source = "fixture-north"
    stopped = image_geometry(source, [[-16, -10], [7, -10], [7, 0], [-16, 0]])
    intersection = image_geometry(source, [[-10, -10], [10, -10], [10, 10], [-10, 10]])
    wrong_way = image_geometry(source, [[-40, 1], [40, 1], [40, 7], [-40, 7]])
    wrong_way["direction"] = [1, 0]
    base = {"sourceId": source, "enabled": True, "revision": 1}
    return {"rules": [
        {**base, "id": "fixture-eastbound-count", "name": "Eastbound crossings", "kind": "line-crossing", "classes": ["car", "bus", "bicycle"], "geometry": {"space": "image-normalized", "points": [[0.5, 0.35], [0.5, 0.65]], "direction": [1, 0]}, "conditions": {"maximumObservationGapMs": 500}},
        {**base, "id": "fixture-crossing-occupancy", "name": "Intersection occupancy", "kind": "occupancy-threshold", "classes": CLASSES, "geometry": intersection, "conditions": {"countThreshold": 2, "minimumDurationMs": 500, "clearAfterMs": 200}},
        {**base, "id": "fixture-restricted-stop", "name": "Vehicle stopped in clearway", "kind": "stopped-in-zone", "classes": ["car", "bus"], "geometry": stopped, "conditions": {"minimumDurationMs": 2000, "speedBelowMps": 0.5, "clearAfterMs": 200}},
        {**base, "id": "fixture-queue", "name": "Two vehicles waiting", "kind": "queue", "classes": ["car", "bus"], "geometry": stopped, "conditions": {"countThreshold": 2, "minimumDurationMs": 1000, "speedBelowMps": 0.5, "clearAfterMs": 200}},
        {**base, "id": "fixture-wrong-way", "name": "Vehicle against lane direction", "kind": "wrong-way", "classes": ["truck"], "geometry": wrong_way, "conditions": {"minimumDurationMs": 500, "speedAboveMps": 0.5, "clearAfterMs": 200}},
        {**base, "id": "fixture-person-crossing", "name": "Person in crossing", "kind": "area-entry", "classes": ["person"], "geometry": intersection, "conditions": {"clearAfterMs": 200}},
        {**base, "id": "fixture-person-dwell", "name": "Crossing dwell", "kind": "dwell", "classes": ["person"], "geometry": intersection, "conditions": {"minimumDurationMs": 1000, "clearAfterMs": 200}},
        {**base, "sourceId": "fixture-east", "id": "fixture-southbound-person-count", "name": "Person crossing second camera", "kind": "line-crossing", "classes": ["person"], "geometry": {"space": "image-normalized", "points": [[0.5, 0.35], [0.5, 0.65]], "direction": [-1, 0]}, "conditions": {"maximumObservationGapMs": 500}},
    ]}


def actors_at(seconds):
    """Deterministic positions for six labelled actors, only used to make boxes."""
    t = seconds
    car_x = -35 + 6 * min(t, 5) + 6 * max(0, t - 11)
    bus_x = -38 + 4 * min(t, 7) + 4 * max(0, t - 13)
    return [("car", car_x, -3, 50, 30), ("bus", bus_x, -6, 80, 36), ("truck", 35 - 4 * t, 4, 75, 35), ("person", 4, 30 - 4 * t, 12, 25), ("bicycle", -40 + 5 * t, 8, 25, 20), ("motorcycle", 40 - 5 * t, -8, 25, 20)]


def observations(duration=20.0, fps=15, session="fixture-session", round_index=0):
    for index in range(math.ceil(duration * fps) + 1):
        elapsed = min(index / fps, duration)
        for source in fixture_site()["sources"]:
            objects = []
            for class_name, x, y, width, height in actors_at(elapsed):
                if not (-49 < x < 49 and -49 < y < 49):
                    continue
                anchor = image_anchor(source["id"], x, y)
                objects.append({"localTrackId": f"fixture-{class_name}", "class": class_name, "confidence": None, "bboxPx": [anchor[0] - width / 2, anchor[1] - height, width, height], "observedThisFrame": True, "fixture": True})
            yield {"schemaVersion": "city.observations.v1", "siteId": "city-geometry-fixture", "sourceId": source["id"], "sourceSessionId": f"{session}-{round_index}", "sequence": str(index), "sourceFrameId": str(index), "sourceTimeNs": str(EPOCH_NS + round((round_index * duration + elapsed) * 1e9)), "timestampBasis": "labelled-fixture-epoch-plus-time", "mediaTimeSeconds": elapsed, "modelRevision": "synthetic-fixture-no-model", "image": {"width": 1000, "height": 1000}, "objects": objects}


def put_json(base_url, method, path, payload):
    request = urllib.request.Request(base_url.rstrip("/") + "/api/v1/city/" + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9184")
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--no-realtime", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--write-package", type=Path)
    args = parser.parse_args()
    if not 1 <= args.duration <= 300 or not 1 <= args.fps <= 60:
        parser.error("duration must be 1–300 seconds and fps 1–60")
    if args.write_package:
        args.write_package.mkdir(parents=True, exist_ok=True)
        (args.write_package / "site.json").write_text(json.dumps(package_site(args.duration), indent=2) + "\n")
        (args.write_package / "rules.json").write_text(json.dumps(fixture_rules(), indent=2) + "\n")
        with (args.write_package / "observations.jsonl").open("w") as output:
            for frame in observations(args.duration, args.fps):
                output.write(json.dumps(frame) + "\n")
        print(f"Wrote explicitly labelled fixture package to {args.write_package}")
        return
    put_json(args.base_url, "PUT", "site", package_site(args.duration))
    put_json(args.base_url, "PUT", "rules", fixture_rules())
    print("Fixture mode active. All observations are synthetic geometry/event tests, not AI inference.", flush=True)
    if args.seed_only:
        return
    session = "fixture-" + uuid.uuid4().hex[:12]
    round_index = 0
    while True:
        start = time.monotonic()
        for frame in observations(args.duration, args.fps, session, round_index):
            if not args.no_realtime:
                remaining = start + frame["mediaTimeSeconds"] - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
            result = put_json(args.base_url, "POST", "observations", frame)
            if not result.get("accepted"):
                raise RuntimeError(f"fixture observation rejected: {result}")
        round_index += 1
        print(f"Completed fixture loop {round_index}", flush=True)
        if not args.repeat:
            break


if __name__ == "__main__":
    main()
