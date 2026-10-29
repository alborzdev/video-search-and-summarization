# SPDX-License-Identifier: Apache-2.0
"""Observed curb-zone visits and interval unions, without parking-law claims."""
from collections import deque
from copy import deepcopy
import math

from .geometry import finite_point, point_in_polygon
from .mobility_spatial import _image_polygon

HORIZON_NS = 900_000_000_000
MAX_RECORDS = 4096
MAX_INTERVALS = 2048
VEHICLES = {"bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"}


def _counts(values):
    result = {}
    for value in values:
        result[value["class"]] = result.get(value["class"], 0) + 1
    return result


def _quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def _seconds(values, cutoff, end):
    return sum(max(0, min(b, end) - max(a, cutoff)) for a, b in values) / 1e9


class MobilityCurbAnalytics:
    def __init__(self, max_tracks=2000):
        self.max_tracks = max(1, min(int(max_tracks), 5000))
        self.rows = {}

    def _record(self, row, ns, kind, track=None):
        if len(row["records"]) == row["records"].maxlen:
            row["truncatedUntilNs"] = max(row["truncatedUntilNs"], row["records"][0]["ns"] + HORIZON_NS)
        row["records"].append({"ns": ns, "kind": kind, "dwellMs": track["dwellNs"] / 1e6 if track else None})

    def _interval(self, row, key, start, end):
        if start is None or end <= start:
            return
        values = row[key]
        if values and values[-1][1] >= start:
            start = min(start, values.pop()[0])
        elif len(values) == values.maxlen:
            row["truncatedUntilNs"] = max(row["truncatedUntilNs"], values[0][1] + HORIZON_NS)
        values.append((start, end))

    def _lose(self, row, track_id, track, ns):
        if track["inside"]:
            self._record(row, ns, "incomplete", track)
            row["lost"][track_id] = ns
            if len(row["lost"]) > self.max_tracks:
                del row["lost"][next(iter(row["lost"]))]
                row["uncertainUntilNs"] = max(row["uncertainUntilNs"], ns + HORIZON_NS)
        del row["tracks"][track_id]

    def reset(self, source_id=None, reason="configuration-changed"):
        loss = reason in {"source-stale", "observation-gap"}
        for key, row in list(self.rows.items()):
            if source_id is not None and row["sourceId"] != source_id:
                continue
            if not loss:
                del self.rows[key]
                continue
            ns = row["lastSeenNs"]
            for track_id, track in list(row["tracks"].items()):
                self._lose(row, track_id, track, ns)
            row["lastNs"] = None
            row["current"] = self._current([], row, [f"No fresh observation since {reason}."], stale=True)

    def _current(self, visits, row, reasons, *, stale=False):
        pending = sum(track["inside"] and track["lastNs"] != row["lastNs"] for track in row["tracks"].values())
        lower = bool(pending or row["lost"] or reasons or row["uncertainUntilNs"] > row["lastSeenNs"])
        persistent = [visit for visit in visits if visit["observedDwellMs"] >= row["config"].dwellThresholdMs]
        stopped = [visit for visit in visits if visit["stopped"] is True]
        speed_unknown = any(visit["stopped"] is None for visit in visits)
        if speed_unknown:
            reasons.append("Stopped status is unavailable for one or more visible vehicles.")
        if pending:
            reasons.append("Recently visible vehicles are temporarily missing; their visits remain pending.")
        if row["lost"]:
            reasons.append("Interrupted visits remain unresolved within the 15-minute evidence horizon.")
        if row["uncertainUntilNs"] > row["lastSeenNs"]:
            reasons.append("Bounded track capacity omitted unresolved membership.")
        known = bool(visits) and not stale
        unknown = stale or (lower and not visits)
        return {"status": "unknown" if unknown else "active" if known else "empty",
            "occupancy": None if unknown else len(visits), "observedOccupancy": 0 if stale else len(visits),
            "occupancyIsLowerBound": lower or stale, "pendingTrackCount": pending, "lostTrackCount": len(row["lost"]),
            "byClass": _counts(visits), "longestActiveObservedDwellMs": max((visit["observedDwellMs"] for visit in visits), default=None),
            "persistentOccupancyCount": None if unknown else len(persistent), "persistentByClass": _counts(persistent),
            "stoppedCount": None if unknown or speed_unknown else len(stopped), "stoppedByClass": _counts(stopped),
            "activeVisits": visits, "qualityReasons": sorted(set(reasons))}

    def update(self, source_id, session_id, ns, tracks, rules, source, configs):
        by_rule = {rule.id: rule for rule in rules}
        observed = [track for track in tracks if track.get("sourceId") == source_id and track.get("sessionId", session_id) == session_id
            and track.get("observedThisFrame") is True and track.get("lastObservedSourceTimeNsInt") == ns and not track.get("stale", False)]
        overflow = len(observed) > self.max_tracks
        observed = observed[:self.max_tracks]
        for config in configs:
            rule = by_rule.get(config.zoneRuleId)
            if rule is None or rule.sourceId != source_id or not rule.enabled:
                continue
            row = self.rows.get(config.id)
            if row is None or row["sessionId"] != session_id:
                row = {"sourceId": source_id, "sessionId": session_id, "config": config, "lastNs": None, "lastSeenNs": ns,
                    "tracks": {}, "lost": {}, "records": deque(maxlen=MAX_RECORDS), "occupied": deque(maxlen=MAX_INTERVALS),
                    "stopped": deque(maxlen=MAX_INTERVALS), "speedEvidence": deque(maxlen=MAX_INTERVALS), "truncatedUntilNs": 0, "uncertainUntilNs": 0, "current": {}}
                self.rows[config.id] = row
            gap = config.maximumObservationGapMs * 1_000_000
            previous_ns = row["lastNs"]
            if previous_ns is not None and ns < previous_ns:
                continue
            row.update(lastNs=ns, lastSeenNs=ns)
            for track_id, state in list(row["tracks"].items()):
                if ns - state["lastNs"] > gap:
                    self._lose(row, track_id, state, ns)
            row["lost"] = {key: at for key, at in row["lost"].items() if ns - at <= HORIZON_NS}
            reasons, visits = [], []
            if overflow:
                row["uncertainUntilNs"] = ns + HORIZON_NS
                reasons.append("The observed track capacity was reached.")
            classes = VEHICLES & (set(rule.classes) or VEHICLES)
            image_polygons = {}
            for track in observed:
                track_id, class_name = track["id"], track["class"]
                old = row["tracks"].get(track_id)
                if old is not None and old["class"] != class_name:
                    self._lose(row, track_id, old, ns)
                    old = None
                if class_name not in classes:
                    continue
                point = track.get("positionM") if rule.geometry.space == "site-metres" else ([track["anchorPx"][0] / source.width, track["anchorPx"][1] / source.height] if track.get("anchorPx") else None)
                if point is None:
                    if class_name not in image_polygons:
                        image_polygons[class_name] = _image_polygon(rule, source, class_name)
                    polygon, anchor = image_polygons[class_name], track.get("anchorPx")
                    if polygon is not None and anchor is not None and finite_point(anchor) and not point_in_polygon(anchor, polygon):
                        inside = False
                    else:
                        reasons.append("An observed vehicle cannot be assigned to or excluded from the curb zone.")
                        continue
                else:
                    inside = point_in_polygon(point, rule.geometry.points)
                row["lost"].pop(track_id, None)
                fresh_speed = track.get("previousObservedSourceTimeNsInt") is not None and ns - track["previousObservedSourceTimeNsInt"] <= gap
                speed, velocity = track.get("speedMps"), track.get("velocityMps")
                stopped = speed <= rule.conditions.speedBelowMps if fresh_speed and isinstance(speed, (int, float)) and math.isfinite(speed) and velocity is not None and finite_point(velocity) else None
                if old is None:
                    if len(row["tracks"]) >= self.max_tracks:
                        victim = next(iter(row["tracks"]))
                        self._lose(row, victim, row["tracks"][victim], ns)
                        row["truncatedUntilNs"] = ns + HORIZON_NS
                    old = {"inside": inside, "lastNs": ns, "class": class_name, "partial": True, "dwellNs": 0, "stopped": stopped}
                    row["tracks"][track_id] = old
                    if inside:
                        self._record(row, ns, "partial")
                elif inside and not old["inside"]:
                    old.update(partial=False, dwellNs=0)
                    self._record(row, ns, "arrival")
                elif not inside and old["inside"]:
                    self._record(row, ns, "departure")
                    if not old["partial"]:
                        self._record(row, ns, "complete", old)
                    old.update(dwellNs=0, partial=True)
                elif inside and old["inside"] and old["lastNs"] == previous_ns and 0 <= ns - old["lastNs"] <= gap:
                    old["dwellNs"] += ns - old["lastNs"]
                    self._interval(row, "occupied", old["lastNs"], ns)
                    if old["stopped"] is not None and stopped is not None:
                        self._interval(row, "speedEvidence", old["lastNs"], ns)
                    if old["stopped"] is True and stopped is True:
                        self._interval(row, "stopped", old["lastNs"], ns)
                old.update(inside=inside, lastNs=ns, stopped=stopped)
                if inside:
                    visits.append({"trackId": track_id, "class": class_name, "observedDwellMs": old["dwellNs"] / 1e6, "partial": old["partial"], "stopped": stopped})
            row["current"] = self._current(visits, row, reasons)
            for key in ("records", "occupied", "stopped", "speedEvidence"):
                values = row[key]
                while values and (values[0]["ns"] if key == "records" else values[0][1]) < ns - HORIZON_NS:
                    values.popleft()

    def snapshot(self, window_minutes, configs, rules, source_times, issues=()):
        if window_minutes not in (1, 5, 15):
            raise ValueError("window_minutes must be 1, 5 or 15")
        by_rule = {rule.id: rule for rule in rules}
        invalid = {issue["id"]: issue["reason"] for issue in issues if issue["kind"] == "curb"}
        result = []
        for config in configs:
            rule, row = by_rule.get(config.zoneRuleId), self.rows.get(config.id)
            source_id = rule.sourceId if rule else None
            end = source_times.get(source_id)
            cutoff = end - window_minutes * 60_000_000_000 if end is not None else None
            samples = [item for item in row["records"] if cutoff is not None and cutoff <= item["ns"] <= end] if row else []
            durations = [item["dwellMs"] for item in samples if item["kind"] == "complete"]
            current = deepcopy(row["current"]) if row else {"status": "unknown", "occupancy": None, "observedOccupancy": 0,
                "occupancyIsLowerBound": True, "pendingTrackCount": 0, "lostTrackCount": 0, "byClass": {}, "longestActiveObservedDwellMs": None,
                "persistentOccupancyCount": None, "persistentByClass": {}, "stoppedCount": None, "stoppedByClass": {}, "activeVisits": [], "qualityReasons": ["Awaiting camera observations."]}
            if config.id in invalid:
                current.update(status="unknown", occupancy=None, observedOccupancy=0, occupancyIsLowerBound=True,
                    byClass={}, persistentOccupancyCount=None, persistentByClass={}, stoppedCount=None, stoppedByClass={},
                    longestActiveObservedDwellMs=None, activeVisits=[], qualityReasons=[invalid[config.id]])
            if row and end is not None and row["truncatedUntilNs"] > end:
                current["qualityReasons"].append("Bounded history omits older evidence within this window.")
            departures = sum(item["kind"] == "departure" for item in samples)
            speed_seconds = _seconds(row["speedEvidence"], cutoff, end) if row and cutoff is not None else 0
            result.append({"id": config.id, "name": config.name, "sourceId": source_id, "ruleId": config.zoneRuleId, "zoneRuleId": config.zoneRuleId,
                "role": config.role, "asOfSourceTimeNs": str(row["lastSeenNs"]) if row else None, "windowMinutes": window_minutes, "timeBasis": "source-time",
                **current, "arrivalCount": sum(item["kind"] == "arrival" for item in samples), "departureCount": departures, "turnoverCount": departures,
                "completedVisitCount": len(durations), "incompleteVisitCount": sum(item["kind"] == "incomplete" for item in samples),
                "partialVisitCount": sum(item["kind"] == "partial" for item in samples),
                "occupiedSeconds": _seconds(row["occupied"], cutoff, end) if row and cutoff is not None else 0,
                "observedStoppedSeconds": _seconds(row["stopped"], cutoff, end) if speed_seconds > 0 else None,
                "stoppedEvidenceSeconds": speed_seconds,
                "completedDwellP50Ms": _quantile(durations, .5), "completedDwellP95Ms": _quantile(durations, .95)})
        return result
