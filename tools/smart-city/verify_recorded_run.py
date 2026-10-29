#!/usr/bin/env python3
"""Audit a completed native replay and its durable browser-time history."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from manage import request


def verify(path: Path) -> dict:
    site = request("site")
    if site["mode"] != "recorded-inference":
        raise ValueError("Select the real recorded-inference site first")
    expected_files = {"traffic-sample.mp4": 1443, "pedestrian-sample.mp4": 795}
    frames = defaultdict(list)
    classes = Counter()
    observations = 0
    for line in path.open():
        frame = json.loads(line)
        if (
            frame["siteId"] != site["id"]
            or frame["mediaTimeBasis"] != "gstreamer-segment-stream-time"
        ):
            raise ValueError("Wrong site or unverified media clock")
        frames[frame["sourceId"]].append(frame)
        width, height = frame["image"]["width"], frame["image"]["height"]
        for track in frame["objects"]:
            classes[track["class"]] += 1
            observations += 1
            if not isinstance(track["localTrackId"], str):
                raise TypeError("Tracker IDs must stay strings")
            box = track["bboxPx"]
            if len(box) != 4 or not all(math.isfinite(x) for x in box):
                raise ValueError("Invalid detection box")
            x, y, w, h = box
            if (
                min(x, y, w, h) < -0.001
                or x + w > width + 0.01
                or y + h > height + 0.01
            ):
                raise ValueError("Detection box exceeds decoded geometry")
    sources = []
    for source in site["sources"]:
        rows = frames[source["id"]]
        expected = expected_files[Path(source["inputUri"]).name]
        if len(rows) != expected or [int(row["sequence"]) for row in rows] != list(
            range(expected)
        ):
            raise ValueError("Missing or duplicated source frame sequence")
        if rows[0]["mediaTimeSeconds"] != 0:
            raise ValueError("Browser media timeline must begin at zero")
        if len({row["sourceSessionId"] for row in rows}) != 1:
            raise ValueError("Unexpected session change within replay")
        samples = []
        for seconds in (
            0.0,
            1.0,
            rows[len(rows) // 2]["mediaTimeSeconds"],
            rows[-1]["mediaTimeSeconds"],
        ):
            snapshot = request(
                "snapshot?"
                + urlencode({"mediaTimeSeconds": seconds, "sourceId": source["id"]})
            )
            selected = next(
                item for item in snapshot["sources"] if item["id"] == source["id"]
            )
            if not selected["clockAligned"] or selected["alignmentSkewSeconds"] > 0.1:
                raise ValueError(
                    "Durable history does not align with the requested video time"
                )
            tracks = [
                track
                for track in snapshot["tracks"]
                if track["sourceId"] == source["id"]
            ]
            if any(track["positionM"] is not None for track in tracks):
                raise ValueError(
                    "Uncalibrated independent recordings must not generate shared map positions"
                )
            samples.append(
                {
                    "requestedSeconds": seconds,
                    "selectedSeconds": selected["mediaTimeSeconds"],
                    "skewSeconds": selected["alignmentSkewSeconds"],
                    "tracks": len(tracks),
                }
            )
        sources.append(
            {
                "sourceId": source["id"],
                "frames": expected,
                "firstMediaSeconds": rows[0]["mediaTimeSeconds"],
                "lastMediaSeconds": rows[-1]["mediaTimeSeconds"],
                "firstRawSourcePtsNs": rows[0]["rawSourcePtsNs"],
                "historyChecks": samples,
            }
        )
    if not observations or not {"person", "car", "bus"}.issubset(classes):
        raise ValueError("Real traffic positive controls are missing")
    return {
        "schemaVersion": "city.recorded-run.v1",
        "verifiedAt": datetime.now(UTC).isoformat(),
        "observationsSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "siteId": site["id"],
        "sources": sources,
        "frames": sum(len(rows) for rows in frames.values()),
        "trackedObjectObservations": observations,
        "classObservationCounts": dict(classes),
        "passed": True,
        "scope": "Complete two-file native inference, geometry bounds, stable string IDs and durable browser-time lookup. Independent uncalibrated recordings; not event accuracy, live RTSP timing or shared-map qualification.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = verify(args.observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
