# SPDX-License-Identifier: Apache-2.0
"""Bounded camera-local mobility measurements in source time, never actor truth."""
from collections import deque
import math

from .geometry import cross, directed_crossing, point_in_polygon
from .models import MobilityConfig

HORIZON_NS = 900_000_000_000
MAX_RECORDS = 10000
MAX_INTERVALS = 2048
CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"}


def configuration_issues(config, site, rules):
    by_id = {rule.id: rule for rule in rules}
    cameras = {source.id: source for source in site.sources}
    issues = []
    for kind, items in (("movement", config.movements), ("crossing", config.crossings), ("queue", config.queues), ("curb", config.curbs)):
        for item in items:
            ids = [item.entryRuleId, item.exitRuleId] if kind == "movement" else ([item.waitingRuleId, item.crossingRuleId] if kind == "crossing" else [item.zoneRuleId])
            refs = [by_id.get(key) for key in ids]
            reason = None
            if any(ref is None for ref in refs):
                reason = "Referenced rule no longer exists."
            elif any(not ref.enabled for ref in refs):
                reason = "Referenced rule is disabled."
            elif len(set(ids)) != len(ids):
                reason = "Entry and exit rules must be distinct."
            elif len({ref.sourceId for ref in refs}) != 1:
                reason = "A measurement must belong to one camera."
            elif refs[0].sourceId not in cameras:
                reason = "The owner camera is unavailable."
            elif kind in {"crossing", "queue", "curb"} and any(len(ref.geometry.points) < 3 for ref in refs):
                reason = "This measurement requires polygon rules."
            elif kind == "movement" and any(len(ref.geometry.points) == 2 and ref.kind != "line-crossing" for ref in refs):
                reason = "Movement gates must be line-crossing rules or polygons."
            elif kind == "movement" and not set.intersection(*(set(ref.classes) or CLASSES for ref in refs), set(item.classes) or CLASSES):
                reason = "Movement gates and requested classes have no shared class."
            elif kind == "crossing" and any(ref.classes and "person" not in ref.classes for ref in refs):
                reason = "Pedestrian crossing rules must allow the person class."
            elif kind == "queue" and cameras[refs[0].sourceId].imageToGroundHomography is None:
                reason = "Queue extent requires valid ground calibration."
            elif kind == "curb" and not ((set(refs[0].classes) or CLASSES) & (CLASSES - {"person"})):
                reason = "Curb measurements require at least one canonical vehicle class."
            if reason:
                issues.append({"kind": kind, "id": item.id, "reason": reason})
    return issues


def _seconds(intervals, start, end):
    return sum(max(0, min(b, end) - max(a, start)) for a, b in intervals) / 1e9


def _interval(values, start, end):
    if end <= start:
        return None
    # Activation may prove an earlier dwell onset; merge backwards as needed.
    while values and values[-1][1] >= start:
        a, b = values.pop()
        start, end = min(start, a), max(end, b)
    evicted_end = values[0][1] if len(values) == values.maxlen else None
    values.append((start, end))
    return evicted_end


def _quantile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)


def _point(track, rule, source):
    if rule.geometry.space == "site-metres":
        return track.get("positionM")
    anchor = track.get("anchorPx")
    return [anchor[0] / source.width, anchor[1] / source.height] if anchor else None


def _gate(previous, current, rule):
    if previous is None or current is None:
        return False
    if len(rule.geometry.points) == 2:
        return _off_line(current, rule) and directed_crossing(previous, current, rule.geometry.points, rule.geometry.direction)
    return not point_in_polygon(previous, rule.geometry.points) and point_in_polygon(current, rule.geometry.points)


def _off_line(point, rule):
    hysteresis = rule.conditions.lineHysteresis
    if hysteresis is None:
        hysteresis = .003 if rule.geometry.space == "image-normalized" else .15
    return abs(cross(*rule.geometry.points, point)) / math.dist(*rule.geometry.points) > max(1e-7, hysteresis)


def _retained_point(previous, current, rule):
    # Preserve the last side when an observed anchor touches a finite line.
    if len(rule.geometry.points) == 2 and not _off_line(current, rule):
        return previous
    return current


class MobilityAnalytics:
    def __init__(self, config=None, max_tracks=2000):
        self.config = config or MobilityConfig()
        self.max_tracks = max_tracks
        self.sources = {}
        self.journeys = {}
        self.seen_events = set()
        self.episodes = {}
        self.blocked = {}
        self.spatial = None
        self.curb = None

    def _curb(self):
        if self.curb is None:
            from .mobility_curb import MobilityCurbAnalytics
            self.curb = MobilityCurbAnalytics(max_tracks=self.max_tracks)
        return self.curb

    def _spatial(self):
        if self.spatial is None:
            from .mobility_spatial import MobilitySpatial
            self.spatial = MobilitySpatial(max_tracks=self.max_tracks)
        return self.spatial

    def reset_source(self, source_id):
        self.invalidate_source(source_id, "source-session-reset")
        self.sources.pop(source_id, None)
        self.episodes = {key: value for key, value in self.episodes.items() if value["sourceId"] != source_id}
        self.blocked = {key: value for key, value in self.blocked.items() if value["sourceId"] != source_id}
        if self.spatial:
            self.spatial.reset(source_id, reason="source-session-reset")

    def invalidate_source(self, source_id=None, reason="observation-gap"):
        for key, state in list(self.journeys.items()):
            if source_id is None or state["sourceId"] == source_id:
                self._incomplete(state, reason)
                del self.journeys[key]
        for sid, source in self.sources.items():
            if source_id is None or source_id == sid:
                source["interrupted"] = True
        for episode in self.episodes.values():
            if (source_id is None or episode["sourceId"] == source_id) and episode["state"] == "active":
                episode["state"] = "unknown"
        if self.spatial:
            self.spatial.reset(source_id, reason=reason)
        if self.curb:
            self.curb.reset(source_id, reason=reason)

    def _record(self, source_id, record):
        source = self.sources.get(source_id)
        if source is None:
            return
        records = source["records"]
        if len(records) == records.maxlen:
            source["truncatedUntilNs"] = max(source["truncatedUntilNs"], records[0]["atNs"] + HORIZON_NS)
        records.append(record)

    def _incomplete(self, state, reason):
        if state.get("startedNs") is not None:
            self._record(state["sourceId"], {"kind": "incomplete", "id": state["movementId"], "atNs": state["lastNs"], "reason": reason})

    def observe(self, engine, source_id, ns, now):
        runtime = engine.sources[source_id]
        source = self.sources.setdefault(source_id, {"sessionId": runtime["sessionId"], "lastNs": None, "lastWall": None, "intervals": deque(maxlen=MAX_INTERVALS), "records": deque(maxlen=MAX_RECORDS), "interrupted": True, "truncatedUntilNs": 0})
        previous_ns = source["lastNs"]
        continuous = previous_ns is not None and 0 < ns - previous_ns <= 1_000_000_000 and now - source["lastWall"] <= engine.freshness and not source["interrupted"]
        if continuous:
            intervals = source["intervals"]
            if len(intervals) == intervals.maxlen and intervals[-1][1] < previous_ns:
                source["truncatedUntilNs"] = max(source["truncatedUntilNs"], intervals[0][1] + HORIZON_NS)
            _interval(intervals, previous_ns, ns)
        source.update(lastNs=ns, lastWall=now, interrupted=False)
        cutoff = ns - HORIZON_NS
        while source["records"] and source["records"][0]["atNs"] < cutoff:
            source["records"].popleft()
        while source["intervals"] and source["intervals"][0][1] < cutoff:
            source["intervals"].popleft()
        config_source = engine._site_sources()[source_id]
        rules = {rule.id: rule for rule in engine.rules}
        issues = {issue["id"] for issue in configuration_issues(self.config, engine.site, engine.rules)}
        tracks = [track for track in engine.tracks.values() if track["sourceId"] == source_id]
        observed = {track["id"]: track for track in tracks if track["observedThisFrame"] and track["lastObservedSourceTimeNsInt"] == ns}
        completed_entries = set()
        for item in self.config.movements:
            if item.id in issues or rules[item.entryRuleId].sourceId != source_id:
                continue
            entry, exit_rule = rules[item.entryRuleId], rules[item.exitRuleId]
            gap = min(entry.conditions.maximumObservationGapMs, exit_rule.conditions.maximumObservationGapMs) * 1_000_000
            classes = (set(entry.classes) or CLASSES) & (set(exit_rule.classes) or CLASSES) & (set(item.classes) or CLASSES)
            for key, state in list(self.journeys.items()):
                if key[0] == item.id and (ns - state["lastNs"] > gap or (key[1] in observed and observed[key[1]]["class"] != state["class"])):
                    self._incomplete(state, "observation-gap-or-class-change")
                    del self.journeys[key]
            for track_id, track in observed.items():
                if track["class"] not in classes:
                    continue
                key = (item.id, track_id)
                points = (_point(track, entry, config_source), _point(track, exit_rule, config_source))
                state = self.journeys.get(key)
                if any(point is None for point in points):
                    if state:
                        self._incomplete(state, "projection-unavailable")
                        del self.journeys[key]
                    continue
                if state is None:
                    if len(self.journeys) >= self.max_tracks:
                        oldest = next(iter(self.journeys))
                        self._incomplete(self.journeys.pop(oldest), "capacity")
                        source["truncatedUntilNs"] = ns + HORIZON_NS
                    state = {"sourceId": source_id, "movementId": item.id, "class": track["class"], "lastNs": ns, "points": points, "pointTimes": (ns, ns), "startedNs": None}
                    self.journeys[key] = state
                entry_hit, exit_hit = (ns - at <= gap and _gate(old, new, rule) for at, old, new, rule in zip(state["pointTimes"], state["points"], points, (entry, exit_rule)))
                if entry_hit and exit_hit:
                    self._incomplete(state, "gate-order-unresolved")
                    state["startedNs"] = None
                elif exit_hit and state["startedNs"] is not None:
                    self._record(source_id, {"kind": "movement", "id": item.id, "class": state["class"], "atNs": ns, "travelSeconds": (ns - state["startedNs"]) / 1e9})
                    completed_entries.add((entry.id, track_id, state["startedNs"], state["class"]))
                    state["startedNs"] = None
                elif entry_hit and state["startedNs"] is None:
                    state["startedNs"] = ns
                retained = tuple(_retained_point(old, new, rule) for old, new, rule in zip(state["points"], points, (entry, exit_rule)))
                state.update(pointTimes=tuple(at if kept is old else ns for at, kept, old in zip(state["pointTimes"], retained, state["points"])), points=retained, lastNs=ns)
        if completed_entries:
            entry_ids = {item.id: item.entryRuleId for item in self.config.movements}
            for (movement_id, track_id), state in self.journeys.items():
                # One observed exit resolves the other turn alternatives for
                # this exact entry episode. Different entry gates, classes,
                # tracks or interrupted episodes retain their own evidence.
                if state["startedNs"] is not None and (entry_ids[movement_id], track_id, state["startedNs"], state["class"]) in completed_entries:
                    state["startedNs"] = None
        # Existing rule evidence supplies immediate line and obstruction reports.
        self.seen_events.intersection_update(engine.events)
        for event in engine.events.values():
            if event["sourceId"] != source_id or event["sessionId"] != runtime["sessionId"]:
                continue
            rule = rules.get(event["ruleId"])
            if rule is None or not rule.enabled:
                continue
            if rule.kind == "line-crossing" and event["id"] not in self.seen_events and int(event["triggeredAtNs"]) == ns:
                track = engine.tracks.get(event["trackIds"][0], {}) if event["trackIds"] else {}
                self._record(source_id, {"kind": "line", "id": rule.id, "atNs": ns, "class": track.get("class", "unknown")})
                self.seen_events.add(event["id"])
            if rule.kind != "stopped-in-zone":
                continue
            fresh_proof = (bool(event["trackIds"]) and all(track_id in observed for track_id in event["trackIds"])
                and event.get("stopEvidenceStatus") == "confirmed" and event.get("stopEvidenceAtNs") == str(ns))
            measurement_state = "unknown" if event["state"] == "active" and not fresh_proof else event["state"]
            episode = self.episodes.get(event["id"])
            if episode and episode["state"] == "cleared" and event["state"] == "cleared":
                continue
            if episode is None and event["state"] == "active":
                episode = {"id": event["id"], "ruleId": rule.id, "sourceId": source_id, "startedNs": int(event["startedAtNs"]), "lastNs": ns, "state": "active", "intervals": deque(maxlen=MAX_INTERVALS)}
                self.episodes[event["id"]] = episode
                # Count only received active evidence after aggregation starts;
                # do not backfill candidate time or pre-restart event history.
                start = ns
            elif episode and continuous and episode["state"] == "active" and measurement_state == "active" and ns - episode["lastNs"] <= rule.conditions.maximumObservationGapMs * 1_000_000:
                start = episode["lastNs"]
            else:
                start = ns
            if episode:
                if start < ns:
                    evicted = _interval(episode["intervals"], start, ns)
                    blocked = self.blocked.setdefault(rule.id, {"sourceId": source_id, "intervals": deque(maxlen=MAX_INTERVALS)})
                    union_evicted = _interval(blocked["intervals"], start, ns)
                    if evicted is not None or union_evicted is not None:
                        source["truncatedUntilNs"] = max(source["truncatedUntilNs"], max(evicted or 0, union_evicted or 0) + HORIZON_NS)
                episode.update(state=measurement_state, lastNs=ns)
        for key, episode in list(self.episodes.items()):
            if episode["sourceId"] == source_id and episode["lastNs"] < cutoff:
                del self.episodes[key]
        while len(self.episodes) > MAX_RECORDS:
            del self.episodes[next(iter(self.episodes))]
            source["truncatedUntilNs"] = ns + HORIZON_NS
        if self.config.queues or self.config.crossings:
            valid = self.config.model_dump()
            valid["queues"] = [value for value in valid["queues"] if value["id"] not in issues]
            valid["crossings"] = [value for value in valid["crossings"] if value["id"] not in issues]
            self._spatial().update(source_id, runtime["sessionId"], ns, tracks, engine.rules, config_source, valid, emit_snapshot=False)
        if self.config.curbs:
            self._curb().update(source_id, runtime["sessionId"], ns, tracks, engine.rules, config_source, [item for item in self.config.curbs if item.id not in issues])

    def snapshot(self, engine, window_minutes):
        window_ns = window_minutes * 60_000_000_000
        coverage, records = [], {}
        for config in engine.site.sources:
            state, runtime = self.sources.get(config.id), engine.sources.get(config.id)
            end = state["lastNs"] if state else None
            start = end - window_ns if end is not None else None
            seconds = _seconds(state["intervals"], start, end) if state else 0
            status = "awaiting-observations" if runtime is None else ("stale" if engine.clock() - runtime["received"] > engine.freshness else "live")
            coverage.append({"sourceId": config.id, "name": config.name, "status": status, "windowStartNs": str(max(0, start)) if start is not None else None, "windowEndNs": str(end) if end is not None else None, "timestampBasis": runtime.get("timestampBasis") if runtime else None, "observedSeconds": seconds, "windowSeconds": window_minutes * 60, "coverageRatio": min(1, seconds / (window_minutes * 60)), "truncated": bool(state and state["truncatedUntilNs"] > end)})
            records[config.id] = [record for record in state["records"] if start <= record["atNs"] <= end] if state else []
        by_source = {item["sourceId"]: item for item in coverage}
        def status(source_id):
            row = by_source.get(source_id)
            return "unavailable" if not row or row["status"] != "live" else ("ready" if row["coverageRatio"] >= 0.999 and not row["truncated"] else "partial")
        def counts(items):
            result = {}
            for item in items:
                result[item["class"]] = result.get(item["class"], 0) + 1
            return result
        line_counts, obstructions = [], []
        for rule in engine.rules:
            if not rule.enabled:
                continue
            if rule.kind == "line-crossing":
                selected = [record for record in records.get(rule.sourceId, []) if record["kind"] == "line" and record["id"] == rule.id]
                line_counts.append({"ruleId": rule.id, "name": rule.name, "sourceId": rule.sourceId, "count": len(selected), "byClass": counts(selected), "status": status(rule.sourceId)})
            if rule.kind == "stopped-in-zone":
                end = self.sources.get(rule.sourceId, {}).get("lastNs", 0)
                start = end - window_ns
                episodes = [item for item in self.episodes.values() if item["ruleId"] == rule.id and item["lastNs"] >= start]
                intervals = self.blocked.get(rule.id, {}).get("intervals", [])
                pending = sum(event.get("stopEvidenceStatus") in {"pending", "clearing"} and event["ruleId"] == rule.id
                              and event["state"] == "active" for event in engine.events.values())
                obstructions.append({"ruleId": rule.id, "name": rule.name, "sourceId": rule.sourceId, "episodeCount": len(episodes), "completedEpisodes": sum(item["state"] == "cleared" for item in episodes), "ongoingEpisodes": sum(item["state"] == "active" for item in episodes), "unknownEpisodes": sum(item["state"] == "unknown" for item in episodes), "pendingEvidenceEpisodes": pending, "blockedSeconds": _seconds(intervals, start, end), "longestObservedEpisodeSeconds": max((_seconds(item["intervals"], start, end) for item in episodes), default=None), "eventIds": [item["id"] for item in episodes[-20:]], "status": status(rule.sourceId)})
        rules = {rule.id: rule for rule in engine.rules}
        issues = configuration_issues(self.config, engine.site, engine.rules)
        invalid = {issue["id"] for issue in issues}
        movements = []
        for item in self.config.movements:
            source_id = rules[item.entryRuleId].sourceId if item.entryRuleId in rules else None
            selected = [record for record in records.get(source_id, []) if record["id"] == item.id]
            complete = [record for record in selected if record["kind"] == "movement"]
            durations = [record["travelSeconds"] for record in complete]
            movements.append({"id": item.id, "name": item.name, "sourceId": source_id, "completedCount": len(complete), "incompleteCount": sum(record["kind"] == "incomplete" for record in selected), "activeCount": sum(state["movementId"] == item.id and state["startedNs"] is not None for state in self.journeys.values()), "byClass": counts(complete), "medianTravelSeconds": _quantile(durations, .5), "p95TravelSeconds": _quantile(durations, .95), "status": "unavailable" if item.id in invalid else status(source_id)})
        spatial = self.spatial.snapshot(window_minutes, {sid: state["lastNs"] for sid, state in self.sources.items()}) if self.spatial else {"queues": [], "crossings": []}
        curbs = self._curb().snapshot(window_minutes, self.config.curbs, engine.rules, {sid: state["lastNs"] for sid, state in self.sources.items()}, issues) if self.config.curbs else []
        return {"schemaVersion": "city.mobility.v1", "siteId": engine.site.id, "siteRevision": engine.site.revision, "mode": engine.site.mode, "configRevision": self.config.revision, "windowMinutes": window_minutes, "timeBasis": "per-camera-source-time", "globalFusionEnabled": False, "config": self.config.model_dump(), "coverage": coverage, "lineCounts": line_counts, "movements": movements, "obstructions": obstructions, **spatial, "curbs": curbs, "configurationIssues": issues, "limitations": ["Counts belong to their owner camera; overlapping views are not deduplicated.", "Observation coverage measures received frame time, not detector recall or physical traffic exposure.", "Times use camera source time, not nominal Isaac scenario time or signal delay.", "Stopped-zone evidence uses a ground anchor, not a validated vehicle footprint. Blocked time counts observed active intervals after confirmation; missing frames and candidate time are excluded.", "Curb roles label operator-defined zones; detections do not establish loading activity, permission or a traffic violation.", "Rolling windows are bounded in memory and restart after analytics/configuration/source-session resets."]}
