#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only CPU audit of saved native SDK IDs, bounded spans and replacements.

Outputs are diagnostics. They never become operational aliases or proof of a
completed crossing. Inputs must be trusted native observation NDJSON. Latest
source sessions are selected explicitly and excluded older rows are reported.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
from itertools import pairwise
from pathlib import Path
from typing import Any


def audit(
    path: Path,
    *,
    maximum_bytes: int = 96 * 1024 * 1024,
    snapshot_bytes: int | None = None,
    start_ns: int | None = None,
    end_ns: int | None = None,
) -> dict:
    p = Path(path)
    file_size = p.stat().st_size
    limit = file_size if snapshot_bytes is None else snapshot_bytes
    if limit < 0 or limit > file_size or maximum_bytes <= 0:
        raise ValueError("Snapshot/max-byte bounds do not match the retained input")
    if start_ns is not None and end_ns is not None and start_ns > end_ns:
        raise ValueError("Start time must not exceed end time")
    rows = []
    malformed = 0
    raw_rows = 0
    digest = hashlib.sha256()
    with p.open("rb") as f:
        offset = max(0, limit - maximum_bytes)
        f.seek(offset)
        if offset:
            f.readline()
        segment_start = f.tell()
        while f.tell() < limit:
            line = f.readline(limit - f.tell())
            digest.update(line)
            try:
                r = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            raw_rows += 1
            ns = int(r["sourceTimeNs"])
            if (
                start_ns is not None
                and ns < start_ns
                or end_ns is not None
                and ns > end_ns
            ):
                continue
            rows.append(
                {
                    "sid": r["sourceId"],
                    "session": r["sourceSessionId"],
                    "ns": int(r["sourceTimeNs"]),
                    "seq": int(r["sequence"]),
                    "frame": r.get("sourceFrameId"),
                    "diagnostic": "trackerDiagnostics" in r,
                    "epochReason": r.get("sourceEpochReason"),
                    "basis": r.get("timestampBasis"),
                    "amb": r.get("nativeTrackAmbiguity", {}),
                    "objs": r["objects"],
                }
            )
    session_counts = {
        sid: len({row["session"] for row in rows if row["sid"] == sid})
        for sid in {row["sid"] for row in rows}
    }
    rows_before_session_filter = len(rows)
    latest = {r["sid"]: r["session"] for r in rows}
    rows = [r for r in rows if r["session"] == latest[r["sid"]]]
    by_source = collections.defaultdict(list)
    first_seen: dict[tuple[str, str], int] = {}
    class_by_id = collections.defaultdict(set)
    for r in rows:
        by_source[r["sid"]].append(r)
        for o in r["objs"]:
            key = (r["sid"], o["localTrackId"])
            first_seen[key] = min(first_seen.get(key, r["ns"]), r["ns"])
            class_by_id[o["localTrackId"]].add(o["class"])

    def percentile(values, q):
        if not values:
            return None
        s = sorted(values)
        return s[round((len(s) - 1) * q)]

    def distribution(values):
        return {
            "min": min(values) if values else None,
            "p25": percentile(values, 0.25),
            "median": percentile(values, 0.5),
            "p75": percentile(values, 0.75),
            "p95": percentile(values, 0.95),
            "max": max(values) if values else None,
        }

    def iou(a, b):
        x = max(a[0], b[0])
        y = max(a[1], b[1])
        w = max(0, min(a[0] + a[2], b[0] + b[2]) - x)
        h = max(0, min(a[1] + a[3], b[1] + b[3]) - y)
        inter = w * h
        return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter else 0

    result = {
        "file": str(p),
        "snapshotBytes": limit,
        "rows": len(rows),
        "malformedOrPartialLinesSkipped": malformed,
        "diagnosticRows": sum(r["diagnostic"] for r in rows),
        "bySource": {},
    }
    for sid, rr in by_source.items():
        tracks: dict[str, dict[str, Any]] = {}
        previous = {}
        previous_all = {}
        prev_row = None
        events = []
        gaps = []
        frame_counts = []
        observed_counts = []
        pred_counts = []
        amb_counts = []
        idclasses = collections.defaultdict(set)
        for r in rr:
            people = {o["localTrackId"]: o for o in r["objs"] if o["class"] == "person"}
            observed = {
                k: o for k, o in people.items() if o.get("observedThisFrame") is True
            }
            frame_counts.append(len(people))
            observed_counts.append(len(observed))
            pred_counts.append(len(people) - len(observed))
            for o in r["objs"]:
                idclasses[o["localTrackId"]].add(o["class"])
            amb_counts.append(r["amb"].get("omittedObjectCount", 0))
            for ident, o in people.items():
                t = tracks.setdefault(
                    ident,
                    {
                        "firstNs": r["ns"],
                        "lastNs": r["ns"],
                        "firstSeq": r["seq"],
                        "lastSeq": r["seq"],
                        "samples": 0,
                        "observedSamples": 0,
                        "gaps": 0,
                        "observedNs": [],
                    },
                )
                if t["samples"] and r["seq"] - t["lastSeq"] > 1:
                    t["gaps"] += 1
                    gaps.append((r["ns"] - t["lastNs"]) / 1e9)
                t["lastNs"] = r["ns"]
                t["lastSeq"] = r["seq"]
                t["samples"] += 1
                if o.get("observedThisFrame") is True:
                    t["observedSamples"] += 1
                    t["observedNs"].append(r["ns"])
            if (
                prev_row
                and r["seq"] == prev_row["seq"] + 1
                and r["ns"] - prev_row["ns"] < 500_000_000
            ):
                ended = {k: o for k, o in previous.items() if k not in people}
                appeared = {k: o for k, o in observed.items() if k not in previous_all}
                pairs = sorted(
                    [
                        (iou(a["bboxPx"], b["bboxPx"]), old, new, a, b)
                        for old, a in ended.items()
                        for new, b in appeared.items()
                    ],
                    reverse=True,
                )
                used_old = set()
                used_new = set()
                for score, old, new, a, b in pairs:
                    if score < 0.5:
                        break
                    if old in used_old or new in used_new:
                        continue
                    used_old.add(old)
                    used_new.add(new)
                    peers = [
                        other
                        for other in by_source
                        if other != sid
                        and (other, new) in first_seen
                        and first_seen[(other, new)] < r["ns"]
                    ]
                    events.append(
                        {
                            "ns": r["ns"],
                            "sequence": r["seq"],
                            "oldId": old,
                            "newId": new,
                            "iou": score,
                            "toLowerId": int(new) < int(old),
                            "newPreviouslyPresentPeer": bool(peers),
                            "oldConfidence": a.get("confidence"),
                            "newConfidence": b.get("confidence"),
                            "oldBox": a["bboxPx"],
                            "newBox": b["bboxPx"],
                            "frameGapSeconds": (r["ns"] - prev_row["ns"]) / 1e9,
                            "currentAmbiguousOmissions": r["amb"].get(
                                "omittedObjectCount", 0
                            ),
                            "previousAmbiguousOmissions": prev_row["amb"].get(
                                "omittedObjectCount", 0
                            ),
                        }
                    )
            previous = observed
            previous_all = people
            prev_row = r
        life = [(x["lastNs"] - x["firstNs"]) / 1e9 for x in tracks.values()]
        samples = [x["observedSamples"] for x in tracks.values()]
        uniq_class = collections.defaultdict(set)
        for row in rr:
            for o in row["objs"]:
                uniq_class[o["class"]].add(o["localTrackId"])
        observed_gaps: list[float] = []
        for t in tracks.values():
            observed_gaps.extend(
                (b - a) / 1e9 for a, b in zip(t["observedNs"], t["observedNs"][1:])
            )
        duration = (rr[-1]["ns"] - rr[0]["ns"]) / 1e9
        result["bySource"][sid] = {
            "sessionId": latest[sid],
            "fromUtc": datetime.datetime.fromtimestamp(
                rr[0]["ns"] / 1e9, datetime.UTC
            ).isoformat(),
            "toUtc": datetime.datetime.fromtimestamp(
                rr[-1]["ns"] / 1e9, datetime.UTC
            ).isoformat(),
            "durationSeconds": duration,
            "frames": len(rr),
            "sourceFrameGaps": sum(b["seq"] != a["seq"] + 1 for a, b in pairwise(rr)),
            "sourceEpochReasonRows": sum(bool(r["epochReason"]) for r in rr),
            "uniqueIdsByClass": {k: len(v) for k, v in uniq_class.items()},
            "personIdNumericRange": [
                min(map(int, tracks)) if tracks else None,
                max(map(int, tracks)) if tracks else None,
            ],
            "personFrameCounts": distribution(frame_counts),
            "observedPersonFrameCounts": distribution(observed_counts),
            "predictedPersonFrameCounts": distribution(pred_counts),
            "personObservationSpansSeconds": distribution(life),
            "personObservedSamplesPerId": distribution(samples),
            "personIdsAtMost1Second": sum(x <= 1 for x in life),
            "personIdsAtLeast10Seconds": sum(x >= 10 for x in life),
            "personIdsAtLeast30Seconds": sum(x >= 30 for x in life),
            "personIdsWithReappearanceGaps": sum(
                t["gaps"] > 0 for t in tracks.values()
            ),
            "sameIdReappearanceGapSeconds": distribution(gaps),
            "observedSameIdGapSeconds": distribution(observed_gaps),
            "ambiguousFrames": sum(x > 0 for x in amb_counts),
            "ambiguousOmittedObjects": sum(amb_counts),
            "ambiguityCapacityExceededFrames": sum(
                r["amb"].get("capacityExceeded", False) for r in rr
            ),
            "duplicateIdCountTotal": sum(
                r["amb"].get("duplicateIdCount", 0) for r in rr
            ),
            "sameIdDifferentClassCount": sum(len(c) > 1 for c in idclasses.values()),
            "highIouAdjacentReplacements": {
                "iouAtLeast0.5": len(events),
                "iouAtLeast0.8": sum(e["iou"] >= 0.8 for e in events),
                "toLowerId": sum(e["toLowerId"] for e in events),
                "newPreviouslyPresentPeer": sum(
                    e["newPreviouslyPresentPeer"] for e in events
                ),
                "iouAtLeast0.8AndNewPreviouslyPresentPeer": sum(
                    e["iou"] >= 0.8 and e["newPreviouslyPresentPeer"] for e in events
                ),
            },
            "replacementExamples": sorted(events, key=lambda x: x["iou"], reverse=True)[
                :12
            ],
            "longestPersonTracks": [
                {
                    "id": ident,
                    **{k: v for k, v in t.items() if k != "observedNs"},
                    "durationSeconds": (t["lastNs"] - t["firstNs"]) / 1e9,
                }
                for ident, t in sorted(
                    tracks.items(),
                    key=lambda item: item[1]["lastNs"] - item[1]["firstNs"],
                    reverse=True,
                )[:8]
            ],
            "oneSampleExamples": [
                ident for ident, t in tracks.items() if t["samples"] == 1
            ][:12],
        }
        left = {ident for ident, t in tracks.items() if t["firstSeq"] == rr[0]["seq"]}
        right = {ident for ident, t in tracks.items() if t["lastSeq"] == rr[-1]["seq"]}
        uncensored = [
            (t["lastNs"] - t["firstNs"]) / 1e9
            for ident, t in tracks.items()
            if ident not in left | right
        ]
        summary = result["bySource"][sid]
        summary["firstSourceTimeNs"] = str(rr[0]["ns"])
        summary["lastSourceTimeNs"] = str(rr[-1]["ns"])
        summary["windowCensoring"] = {
            "leftCensoredIds": len(left),
            "rightCensoredIds": len(right),
            "bothCensoredIds": len(left & right),
            "uncensoredWithinWindowIds": len(tracks.keys() - left - right),
            "meaning": "An ID present at the first/last sampled frame may have begun earlier/continued later; observation spans are not physical track lifetimes.",
        }
        summary["uncensoredWithinWindowObservationSpansSeconds"] = distribution(
            uncensored
        )
        summary["newPersonIdsExcludingLeftCensoredPerMinute"] = (
            (len(tracks) - len(left)) * 60 / duration if duration else None
        )
        summary["adjacentReplacementsIouAtLeast0.8PerMinute"] = (
            sum(e["iou"] >= 0.8 for e in events) * 60 / duration if duration else None
        )
        summary["observedPersonSamples"] = sum(observed_counts)
        for t in summary["longestPersonTracks"]:
            t["leftCensored"] = t["id"] in left
            t["rightCensored"] = t["id"] in right

    result["crossClassSdkIds"] = {
        k: sorted(v) for k, v in class_by_id.items() if len(v) > 1
    }
    result["sourceSegment"] = {
        "byteStart": segment_start,
        "byteEndExclusive": limit,
        "sha256": digest.hexdigest(),
        "rawRows": raw_rows,
        "inputFileBytesAtStart": file_size,
        "maximumBytes": maximum_bytes,
    }
    result["selection"] = {
        "requestedStartNs": str(start_ns) if start_ns is not None else None,
        "requestedEndNs": str(end_ns) if end_ns is not None else None,
        "latestSourceSessionOnly": True,
        "sourceSessionCountsBeforeSelection": session_counts,
        "olderSessionRowsExcluded": rows_before_session_filter - len(rows),
    }
    result["limits"] = [
        "SDK ID sighting spans are bounded-window observations, not physical person lifetimes.",
        "Numeric counter range includes other classes and is not a person count.",
        "High-IoU adjacent replacements are continuity diagnostics, not physical identity labels or production alias records.",
        "Peer-preexisting IDs are consistent with late SDK adoption/correction but do not prove every cause.",
        "No source-frame decoding, inference, GT matching, gap-threshold change, or operational ID merging occurs.",
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-bytes", type=int, default=96 * 1024 * 1024)
    parser.add_argument(
        "--snapshot-bytes",
        type=int,
        help="Pin an exact retained prefix before later appended rows",
    )
    parser.add_argument("--start-ns", type=int)
    parser.add_argument("--end-ns", type=int)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must differ from the preserved input")
    result = audit(
        args.input,
        maximum_bytes=args.maximum_bytes,
        snapshot_bytes=args.snapshot_bytes,
        start_ns=args.start_ns,
        end_ns=args.end_ns,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": result["rows"],
                "sourceSegment": result["sourceSegment"],
                "bySource": {
                    sid: {
                        key: value[key]
                        for key in [
                            "sessionId",
                            "durationSeconds",
                            "frames",
                            "uniqueIdsByClass",
                            "personObservationSpansSeconds",
                            "windowCensoring",
                            "highIouAdjacentReplacements",
                        ]
                    }
                    for sid, value in result["bySource"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
