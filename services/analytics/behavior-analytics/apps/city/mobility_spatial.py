# SPDX-License-Identifier: Apache-2.0
"""Bounded camera-local queue and pedestrian measurements in source time.

These estimates use observed ground anchors, never simulator actor positions or
shared camera identities. A polygon exit is only a completed traversal when the
same observed person crosses its far boundary; missing tracks prove no exit.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
import math

from .geometry import finite_point, point_in_polygon, project, segments_intersect, validate_homography, validate_polygon

HISTORY_NS = 900_000_000_000
VEHICLES = {"bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"}


def _point(track, rule, source):
    if rule.geometry.space == "site-metres":
        return track.get("positionM")
    anchor = track.get("anchorPx")
    return [anchor[0] / source.width, anchor[1] / source.height] if anchor else None


def _ground_polygon(rule, source, class_name="car"):
    if rule.geometry.space == "site-metres":
        return rule.geometry.points
    matrix = source.classImageToGroundHomographies.get(class_name, source.imageToGroundHomography)
    points = [project([p[0] * source.width, p[1] * source.height], matrix)[0] for p in rule.geometry.points]
    return points if all(point is not None for point in points) else None


def _image_polygon(rule, source, class_name):
    """Invert the zone, only when its whole polygon avoids the horizon.

    This proves image-plane exclusion; it does not assign an unvalidated ground
    position to an anchor rejected by the camera's valid-ground mask.
    """
    if rule.geometry.space == "image-normalized":
        return [[p[0] * source.width, p[1] * source.height] for p in rule.geometry.points]
    matrix = source.classImageToGroundHomographies.get(class_name, source.imageToGroundHomography)
    if matrix is None:
        return None
    try:
        validate_homography(matrix)
        scale = max(abs(v) for row in matrix for v in row)
        (a, b, c), (d, e, f), (g, h, i) = [[v / scale for v in row] for row in matrix]
        inverse = [[e*i-f*h, c*h-b*i, b*f-c*e], [f*g-d*i, a*i-c*g, c*d-a*f], [d*h-e*g, b*g-a*h, a*e-b*d]]
        scale = max(abs(v) for row in inverse for v in row)
        inverse = [[v / scale for v in row] for row in inverse]
        denominators = [inverse[2][0] * p[0] + inverse[2][1] * p[1] + inverse[2][2] for p in rule.geometry.points]
        if not (all(d > 1e-9 for d in denominators) or all(d < -1e-9 for d in denominators)):
            return None
        points = [project(p, inverse)[0] for p in rule.geometry.points]
        if any(p is None for p in points):
            return None
        validate_polygon(points)
        return points
    except (ValueError, ZeroDivisionError):
        return None


def _centroid(points):
    return [sum(p[axis] for p in points) / len(points) for axis in (0, 1)]


def _distance(point, origin, axis):
    return sum((point[i] - origin[i]) * axis[i] for i in (0, 1))


def _boundary_distance(point, polygon):
    distances = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx*dx + dy*dy)))
        distances.append(math.dist(point, [a[0] + t*dx, a[1] + t*dy]))
    return min(distances)


def _directional_edge_crossing(previous, current, polygon, axis, *, entering):
    if previous is None or current is None or axis is None or sum((current[i]-previous[i])*axis[i] for i in (0, 1)) <= 1e-9:
        return False
    edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    orientation = 1 if sum(a[0]*b[1]-b[0]*a[1] for a, b in edges) > 0 else -1
    # An offset approach centroid tilts the axis. Select actual boundary faces
    # within 45 degrees of that axis, rather than a farthest corner projection;
    # nearly parallel side edges cannot become entries/exits from that tilt.
    direction = -1 if entering else 1
    return any(direction * orientation * ((b[1]-a[1])*axis[0]-(b[0]-a[0])*axis[1]) >= math.dist(a, b) / math.sqrt(2)
        and segments_intersect(previous, current, a, b) for a, b in edges)


def _near_side_entry(previous, current, polygon, axis):
    return _directional_edge_crossing(previous, current, polygon, axis, entering=True)


def _quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


class MobilitySpatial:
    def __init__(self, max_tracks=2000):
        self.max_tracks = max(1, min(int(max_tracks), 5000))
        self.sources = {}

    def _lost(self, row, track_id, ns):
        if track_id not in row["retired"]:
            row["losses"].append({"trackId": track_id, "ns": ns})
            row["retired"][track_id] = ns
        if len(row["retired"]) > self.max_tracks:
            del row["retired"][next(iter(row["retired"]))]
            row["lossOverflowUntilNs"] = ns + HISTORY_NS

    def _prune_losses(self, row, ns):
        cutoff = ns - HISTORY_NS
        while row["losses"] and row["losses"][0]["ns"] < cutoff:
            row["losses"].popleft()
        row["retired"] = {key: at for key, at in row["retired"].items() if at >= cutoff}

    @staticmethod
    def _new_loss_state():
        return {"retired": {}, "losses": deque(maxlen=4096), "lossOverflowUntilNs": 0}

    def reset(self, source_id=None, reason="configuration-changed"):
        """Break continuity; retain valid history across an observation outage."""
        observation_loss = reason in {"source-stale", "observation-gap"}
        targets = self.sources.values() if source_id is None else [self.sources.get(source_id)]
        for state in targets:
            if not state:
                continue
            last_ns = state["lastNs"]
            state["lastNs"] = None
            for row in state["queues"].values():
                if observation_loss:
                    for track_id, at in row["pending"].items():
                        self._lost(row, track_id, last_ns if last_ns is not None else at)
                else:
                    row.update(self._new_loss_state())
                    row["history"].clear()
                row.update(members=set(), pending={}, since=None, spillbackSince=None)
                row["result"].update(status="unknown", count=0, observedExtentM=None, tailPositionM=None,
                    extentIsLowerBound=True, spillback=None, durationMs=0, spillbackDurationMs=0, trackIds=[],
                    pendingTrackCount=0, oldestPendingGapMs=None, membershipComplete=False, currentCountsAvailable=False,
                    qualityReasons=[f"No fresh observation since reset ({reason})."])
            for row in state["crossings"].values():
                if observation_loss:
                    for track_id, track in row["tracks"].items():
                        if track["phase"] in {"waiting", "crossing"}:
                            if last_ns is not None:
                                self._end_missing_visit(row, track_id, track, last_ns)
                else:
                    row.update(self._new_loss_state())
                    row["outcomes"].clear()
                    row["overflowNs"] = None
                    row["overflow"] = False
                row["tracks"].clear()
                row["result"].update(status="unknown", waitingCount=0, crossingCount=0,
                    pendingTrackCount=0, pendingExitTrackCount=0, oldestPendingGapMs=None, membershipComplete=False, currentCountsAvailable=False,
                    oldestObservedWaitMs=None, qualityReasons=[f"No fresh observation since reset ({reason})."])

    def _new_state(self, source_id, session_id, signature, config, rules):
        state = {"sessionId": session_id, "signature": signature, "lastNs": None, "lastSeenNs": None, "queues": {}, "crossings": {}}
        for cfg in config.get("queues", [])[:32]:
            rule = rules.get(cfg["zoneRuleId"])
            if rule is None or rule.sourceId != source_id:
                continue
            result = {"id": cfg["id"], "name": cfg.get("name", cfg["id"]), "sourceId": source_id,
                "ruleId": rule.id, "zoneRuleId": rule.id, "stopLineM": cfg["stopLine"],
                "upstreamPointM": cfg["upstreamPoint"], "spillbackDistanceM": cfg["spillbackDistanceM"],
                "extentBasis": "ground-anchor-distance", "timeBasis": "source-time"}
            state["queues"][cfg["id"]] = {"config": cfg, "result": result, "members": set(),
                "pending": {}, "since": None, "history": deque(maxlen=902), **self._new_loss_state()}
        for cfg in config.get("crossings", [])[:32]:
            waiting, crossing = rules.get(cfg["waitingRuleId"]), rules.get(cfg["crossingRuleId"])
            if waiting is None or crossing is None or waiting.sourceId != source_id or crossing.sourceId != source_id:
                continue
            result = {"id": cfg["id"], "name": cfg.get("name", cfg["id"]), "sourceId": source_id,
                "waitingRuleId": waiting.id, "crossingRuleId": crossing.id,
                "completionBasis": "observed-far-side-exit", "timeBasis": "source-time",
                "exitConfirmationBasis": "two-fresh-same-identity-observations"}
            state["crossings"][cfg["id"]] = {"config": cfg, "result": result, "tracks": {},
                "outcomes": deque(maxlen=4096), "overflowNs": None, **self._new_loss_state()}
        self.sources[source_id] = state
        self.reset(source_id, "new-session-or-configuration")
        # The validated site is limited to 16 sources. Bound direct callers too.
        while len(self.sources) > 16:
            del self.sources[next(iter(self.sources))]
        return state

    def update(self, source_id, session_id, ns, tracks, rules, source, config, *, emit_snapshot=True):
        rules = {rule.id: rule for rule in rules}
        referenced = {cfg["zoneRuleId"] for cfg in config.get("queues", [])}
        referenced.update(rule_id for cfg in config.get("crossings", []) for rule_id in (cfg["waitingRuleId"], cfg["crossingRuleId"]))
        signature = json.dumps({"config": config, "source": source.model_dump(),
            "rules": [rule.model_dump() for rule in rules.values() if rule.sourceId == source_id and rule.id in referenced]}, sort_keys=True)
        state = self.sources.get(source_id)
        if state is None or state["sessionId"] != session_id or state["signature"] != signature:
            state = self._new_state(source_id, session_id, signature, config, rules)
        ns = int(ns)
        previous_ns = state["lastNs"]
        if previous_ns is not None and ns <= previous_ns:
            return self.snapshot(source_times={source_id: previous_ns}) if emit_snapshot else None
        observed = [track for track in tracks if track.get("sourceId") == source_id
            and track.get("sessionId", session_id) == session_id
            and track.get("observedThisFrame") is True and not track.get("stale", False)
            and track.get("lastObservedSourceTimeNsInt", track.get("sourceTimeNsInt")) == ns]
        overflow = len(observed) > self.max_tracks
        observed = observed[:self.max_tracks]
        for row in state["queues"].values():
            self._queue(row, rules[row["config"]["zoneRuleId"]], source, observed, ns, previous_ns, overflow)
        for row in state["crossings"].values():
            self._crossing(row, rules[row["config"]["waitingRuleId"]], rules[row["config"]["crossingRuleId"]],
                source, observed, ns, previous_ns, overflow)
        state["lastNs"] = ns
        state["lastSeenNs"] = ns
        return self.snapshot(source_times={source_id: ns}) if emit_snapshot else None

    def _queue(self, row, rule, source, tracks, ns, previous_ns, overflow):
        cfg, result = row["config"], row["result"]
        result["asOfSourceTimeNs"] = str(ns)
        self._prune_losses(row, ns)
        if not rule.enabled:
            row.update(members=set(), pending={}, since=None, spillbackSince=None)
            result.update(status="disabled", currentCountsAvailable=False, count=0, observedExtentM=None, tailPositionM=None,
                extentIsLowerBound=False, spillback=None, durationMs=0, trackIds=[], qualityReasons=["The queue zone rule is disabled."])
            return
        origin = [(cfg["stopLine"][0][i] + cfg["stopLine"][1][i]) / 2 for i in (0, 1)]
        vector = [cfg["upstreamPoint"][i] - origin[i] for i in (0, 1)]
        length = math.hypot(*vector)
        if length < 1e-9:
            result.update(status="unknown", currentCountsAvailable=False, count=0, observedExtentM=None, tailPositionM=None,
                extentIsLowerBound=True, spillback=None, durationMs=0, trackIds=[], qualityReasons=["The queue approach axis is invalid."])
            return
        axis = [v / length for v in vector]
        gap_m, reach_m = cfg.get("maxAnchorGapM", 12), cfg.get("stopLineReachM", 12)
        maximum_gap_ns = cfg.get("maximumObservationGapMs", 1000) * 1_000_000
        reasons, candidates = [], []
        fresh_ids = {track["id"] for track in tracks}
        for track_id, at in list(row["pending"].items()):
            if track_id in fresh_ids:
                del row["pending"][track_id]
            elif ns - at > maximum_gap_ns:
                self._lost(row, track_id, ns)
                del row["pending"][track_id]
        pending_ages = [(ns-at)/1e6 for at in row["pending"].values()]
        if pending_ages:
            reasons.append("A previously queued track is no longer observed.")
        if overflow:
            reasons.append("The bounded track capacity was reached.")
        if previous_ns is not None and ns - previous_ns > maximum_gap_ns:
            reasons.append("Camera observations have a gap.")
        for track in tracks:
            if track.get("class") not in VEHICLES or (rule.classes and track["class"] not in rule.classes):
                continue
            point = _point(track, rule, source)
            if point is None:
                images = row.setdefault("imagePolygons", {})
                if track["class"] not in images:
                    images[track["class"]] = _image_polygon(rule, source, track["class"])
                image_zone, anchor = images[track["class"]], track.get("anchorPx")
                if image_zone is not None and anchor is not None and finite_point(anchor) and not point_in_polygon(anchor, image_zone):
                    row["retired"].pop(track["id"], None)
                    continue
                reasons.append("A vehicle has no valid ground projection.")
                continue
            if not point_in_polygon(point, rule.geometry.points):
                row["retired"].pop(track["id"], None)
                continue
            ground, speed = track.get("positionM"), track.get("speedMps")
            if ground is None or speed is None or not math.isfinite(speed):
                reasons.append("A vehicle in the zone has no valid position or speed.")
                continue
            if speed > rule.conditions.speedBelowMps:
                row["retired"].pop(track["id"], None)
                continue
            distance = _distance(ground, origin, axis)
            if distance >= 0:
                candidates.append((distance, track))
        candidates.sort(key=lambda item: (item[0], item[1]["id"]))
        connected, cells = [], {}
        cell_size = max(gap_m, 1e-9)
        for distance, track in candidates:
            # Anchors must connect spatially to the stop line or another queue
            # member. Longitudinal ordering alone can join unrelated lanes.
            p = track["positionM"]
            a, b = cfg["stopLine"]
            denominator = sum((b[i] - a[i]) ** 2 for i in (0, 1))
            t = max(0, min(1, sum((p[i] - a[i]) * (b[i] - a[i]) for i in (0, 1)) / denominator)) if denominator else 0
            stop_distance = math.dist(p, [a[i] + t * (b[i] - a[i]) for i in (0, 1)])
            cell = (math.floor(p[0] / cell_size), math.floor(p[1] / cell_size))
            neighbors = (prior for x in range(cell[0] - 1, cell[0] + 2) for y in range(cell[1] - 1, cell[1] + 2) for prior in cells.get((x, y), ()))
            if stop_distance <= reach_m or any(math.dist(p, prior) <= gap_m for prior in neighbors):
                connected.append((distance, track))
                cells.setdefault(cell, []).append(p)
        members = {track["id"] for _, track in connected}
        row["members"] = members
        for track_id in members:
            row["pending"][track_id] = ns
        if len(row["pending"]) > self.max_tracks:
            for track_id in list(row["pending"])[:-self.max_tracks]:
                self._lost(row, track_id, ns)
                del row["pending"][track_id]
        tail = connected[-1] if connected else None
        extent = tail[0] if tail else 0.0
        polygon = _ground_polygon(rule, source)
        boundary = max((_distance(p, origin, axis) for p in polygon), default=None) if polygon else None
        historical_loss = bool(row["retired"]) or ns < row["lossOverflowUntilNs"]
        lower_bound = bool(tail and (boundary is None or boundary - extent <= gap_m)) or bool(reasons) or historical_loss
        if tail and boundary is not None and boundary - extent <= gap_m:
            boundary_reason = "The observed tail is near the configured zone boundary."
        else:
            boundary_reason = None
        minimum_count = rule.conditions.countThreshold if rule.kind == "queue" else 1
        if reasons or len(members) < minimum_count:
            row["since"] = None
        elif row["since"] is None:
            row["since"] = ns
        duration = (ns - row["since"]) / 1e6 if row["since"] is not None else 0
        qualified = len(members) >= minimum_count and duration >= cfg.get("minimumDurationMs", 1000)
        if reasons or not members or extent < cfg["spillbackDistanceM"]:
            row["spillbackSince"] = None
        elif row.get("spillbackSince") is None:
            row["spillbackSince"] = ns
        spillback_duration = (ns - row["spillbackSince"]) / 1e6 if row.get("spillbackSince") is not None else 0
        spillback = qualified and extent >= cfg["spillbackDistanceM"] and spillback_duration >= cfg.get("minimumDurationMs", 1000)
        status = "unknown" if reasons or (historical_loss and not members) else "empty" if not members else "candidate" if not qualified else "spillback" if spillback else "queued"
        if historical_loss:
            reasons.append("Earlier queue tracks were lost; current visible anchors are a lower bound, not confirmed clearance.")
        result.update(status=status, count=len(members), observedExtentM=extent if status != "unknown" or members else None,
            extentIsLowerBound=lower_bound, tailPositionM=tail[1]["positionM"] if tail else None,
            spillback=True if spillback and status == "spillback" else None if status == "unknown" or historical_loss else False,
            durationMs=duration, spillbackDurationMs=spillback_duration, trackIds=sorted(members),
            countBasis="currently-observed", currentCountsAvailable=True, membershipComplete=not reasons and not historical_loss,
            pendingTrackCount=len(pending_ages), oldestPendingGapMs=max(pending_ages) if pending_ages else None,
            unresolvedHistoricalTrackCount=len(row["retired"]), oldestLostTrackAgeMs=(ns-min(row["retired"].values()))/1e6 if row["retired"] else None,
            lossEvidenceRetentionSeconds=900, clearanceConfirmed=False,
            qualityReasons=sorted(set(reasons + ([boundary_reason] if boundary_reason else []))))
        if status not in {"unknown", "disabled", "candidate"}:
            second = ns // 1_000_000_000
            history = row["history"]
            if history and history[-1]["second"] == second:
                history[-1]["extent"] = max(history[-1]["extent"], extent)
                history[-1]["ns"] = ns
            else:
                history.append({"second": second, "ns": ns, "extent": extent})
        while row["history"] and ns - row["history"][0]["ns"] > HISTORY_NS:
            row["history"].popleft()

    def _outcome(self, row, ns, outcome, track_id, wait_ms=None, **details):
        if len(row["outcomes"]) == row["outcomes"].maxlen:
            row["overflowNs"] = row["outcomes"][0]["ns"]
        row["outcomes"].append({"ns": ns, "outcome": outcome, "trackId": track_id, "waitMs": wait_ms, **details})

    def _end_missing_visit(self, row, track_id, state, ns):
        # First-seen crosswalk occupancy is not a new waiting-to-cross journey.
        # Do not repeatedly count the same unrecovered partial visit.
        if not state.get("lossCounted") and (state["phase"] == "waiting" or state.get("journey")):
            self._outcome(row, ns, "incomplete", track_id)
        if state["phase"] in {"waiting", "crossing"}:
            self._lost(row, track_id, ns)

    def _crossing(self, row, waiting, crossing, source, tracks, ns, previous_ns, overflow):
        result, cfg = row["result"], row["config"]
        result["asOfSourceTimeNs"] = str(ns)
        self._prune_losses(row, ns)
        if not waiting.enabled or not crossing.enabled:
            row["tracks"].clear()
            result.update(status="disabled", currentCountsAvailable=False, waitingCount=0, crossingCount=0, oldestObservedWaitMs=None,
                pendingTrackCount=0, pendingExitTrackCount=0, oldestPendingGapMs=None,
                qualityReasons=["A waiting or crossing rule is disabled."])
            return
        max_gap = cfg.get("maximumObservationGapMs", min(waiting.conditions.maximumObservationGapMs, crossing.conditions.maximumObservationGapMs)) * 1_000_000
        row["maximumGapNs"] = max_gap
        gap = previous_ns is not None and ns - previous_ns > max_gap
        reasons = ["Camera observations have a gap."] if gap else []
        if overflow:
            reasons.append("The bounded track capacity was reached.")
        if waiting.geometry.space == crossing.geometry.space:
            wait_polygon, cross_polygon = waiting.geometry.points, crossing.geometry.points
            coordinate_space = waiting.geometry.space
        else:
            wait_polygon = _ground_polygon(waiting, source, "person")
            cross_polygon = _ground_polygon(crossing, source, "person")
            coordinate_space = "site-metres"
        origin = _centroid(wait_polygon) if wait_polygon else None
        vector = [b - a for a, b in zip(origin, _centroid(cross_polygon))] if origin and cross_polygon else None
        length = math.hypot(*vector) if vector else 0
        axis = [v / length for v in vector] if length > 1e-9 else None
        if "imagePolygons" not in row:
            row["imagePolygons"] = [_image_polygon(rule, source, "person") for rule in (waiting, crossing)]
        image_polygons = row["imagePolygons"]
        people = {track["id"]: track for track in tracks if track.get("class") == "person"}
        changed_class = {track["id"] for track in tracks if track.get("class") != "person"}
        old_tracks, current = row["tracks"], {}
        # Keep briefly missing identities for re-observation, without displaying
        # predictions as people or inventing an exit. Expire exactly once.
        for track_id, old in old_tracks.items():
            if track_id in changed_class or gap or ns - old["lastSeenNs"] > max_gap:
                self._end_missing_visit(row, track_id, old, ns)
                continue
            if track_id not in people:
                current[track_id] = old
        usable_old = {key: old for key, old in old_tracks.items() if key not in changed_class
            and not gap and ns - old["lastSeenNs"] <= max_gap}
        waiting_count, crossing_count, waits, pending_ages = 0, 0, [], []
        for track_id, track in people.items():
            wait_point, cross_point = _point(track, waiting, source), _point(track, crossing, source)
            old = usable_old.get(track_id)
            if old and old.get("pendingExit") and ns - old.get("lastCrossingNs", old["lastSeenNs"]) > max_gap:
                self._end_missing_visit(row, track_id, old, ns)
                old = None
            if wait_point is None or cross_point is None:
                anchor = track.get("anchorPx")
                excluded = anchor is not None and finite_point(anchor) and all(poly is not None and not point_in_polygon(anchor, poly) for poly in image_polygons)
                if excluded and old is None:
                    row["retired"].pop(track_id, None)
                    continue
                if old is not None:
                    current[track_id] = old
                reasons.append("A pedestrian near the measurement zones has no valid position.")
                continue
            in_cross = point_in_polygon(cross_point, crossing.geometry.points)
            in_wait = point_in_polygon(wait_point, waiting.geometry.points) and not in_cross
            waiting_count += int(in_wait)
            crossing_count += int(in_cross)
            phase = "crossing" if in_cross else "waiting" if in_wait else "outside"
            # Half-pixel membership hysteresis rejects subpixel boundary flips.
            # This changes no ground-distance or observation-gap threshold.
            anchor = track.get("anchorPx")
            boundary_pending = bool(old and phase != old["phase"] and anchor is not None and
                any(poly is not None and _boundary_distance(anchor, poly) < .5 for poly in image_polygons))
            if boundary_pending:
                phase = old["phase"]
            confirmed_exit = None
            if old and old["phase"] == "crossing" and old.get("journey"):
                if phase != "crossing":
                    # An outside anchor is still outside for current occupancy.
                    # Retain only the journey proof while an exit is confirmed;
                    # do not copy this point to the map or invent an in-zone fix.
                    point = track.get("positionM") if coordinate_space == "site-metres" else cross_point
                    previous = old.get("lastCrossingPoint", old.get("lastCrossPoint"))
                    far_exit = _directional_edge_crossing(previous, point, cross_polygon, axis, entering=False) if cross_polygon else False
                    category = "returned" if phase == "waiting" else "completed" if far_exit else "incomplete"
                    pending = old.get("pendingExit")
                    if ns - old.get("lastCrossingNs", old["lastSeenNs"]) > max_gap:
                        self._end_missing_visit(row, track_id, old, ns)
                        old = None
                    elif pending and pending["category"] == category and ns > pending["firstNs"]:
                        confirmed_exit = pending
                    else:
                        # Neither an outside point, prediction nor repeated
                        # category changes may renew the last-inside deadline.
                        current[track_id] = {**old, "pendingExit": {"category": category, "firstNs": ns}}
                        continue
                elif old.get("pendingExit"):
                    if not in_cross:
                        # A half-pixel boundary ambiguity is not re-entry and
                        # cannot confirm or refresh an existing exit candidate.
                        current[track_id] = old
                        continue
                    self._outcome(row, ns, "exit-candidate-recovered", track_id)
                    old = dict(old)
                    old.pop("pendingExit")
            if old is None:
                item = {"phase": phase, "since": ns, "observedEntry": False, "journey": False,
                    "lossCounted": track_id in row["retired"], "briefGapCount": 0}
            elif old["phase"] == "outside" and phase == "waiting":
                row["retired"].pop(track_id, None)
                item = {"phase": "waiting", "since": ns, "observedEntry": True, "journey": False,
                    "lossCounted": False, "briefGapCount": 0}
            elif old["phase"] == "outside" and phase == "crossing":
                point = track.get("positionM") if coordinate_space == "site-metres" else cross_point
                entered_near_side = _near_side_entry(old.get("lastCrossPoint"), point, cross_polygon, axis) if cross_polygon else False
                item = {"phase": "crossing", "since": ns, "observedEntry": False, "journey": entered_near_side,
                    "lossCounted": False, "briefGapCount": 0}
            elif old["phase"] == "waiting" and phase == "crossing":
                wait_ms = (ns - old["since"]) / 1e6
                self._outcome(row, ns, "entered-crossing", track_id, wait_ms if old["observedEntry"] else None,
                    lowerBoundWaitMs=wait_ms if not old["observedEntry"] else None,
                    briefGapCount=old.get("briefGapCount", 0) + int(old["lastSeenNs"] != previous_ns))
                item = {**old, "phase": "crossing", "since": ns, "journey": True}
            elif old["phase"] == "waiting" and phase == "outside":
                self._outcome(row, ns, "abandoned", track_id)
                row["retired"].pop(track_id, None)
                item = {"phase": "outside", "since": ns, "observedEntry": False, "journey": False,
                    "lossCounted": False, "briefGapCount": 0}
            elif old["phase"] == "crossing" and phase != "crossing":
                if old["journey"]:
                    self._outcome(row, ns, confirmed_exit["category"], track_id,
                        firstObservedExitNs=str(confirmed_exit["firstNs"]), exitConfirmationSamples=2)
                row["retired"].pop(track_id, None)
                item = {"phase": phase, "since": ns, "observedEntry": phase == "waiting", "journey": False,
                    "lossCounted": False, "briefGapCount": 0}
            else:
                item = dict(old)
            if old and old["lastSeenNs"] != previous_ns:
                item["briefGapCount"] = item.get("briefGapCount", 0) + 1
            if phase == "outside":
                row["retired"].pop(track_id, None)
            item["lastSeenNs"] = ns
            if not boundary_pending:
                item["lastCrossPoint"] = track.get("positionM") if coordinate_space == "site-metres" else cross_point
            if in_cross and phase == "crossing":
                item["lastCrossingNs"] = ns
                item["lastCrossingPoint"] = track.get("positionM") if coordinate_space == "site-metres" else cross_point
            current[track_id] = item
            if in_wait and phase == "waiting":
                waits.append((ns - item["since"]) / 1e6)
        # Retain no more than the configured capacity, preferring fresh tracks.
        if len(current) > self.max_tracks:
            for track_id in sorted(current, key=lambda key: current[key]["lastSeenNs"])[:len(current)-self.max_tracks]:
                self._end_missing_visit(row, track_id, current.pop(track_id), ns)
            reasons.append("The bounded pedestrian state capacity was reached.")
        row["tracks"] = current
        pending_ages = [(ns-old["lastSeenNs"])/1e6 for old in current.values()
            if old["lastSeenNs"] != ns and old["phase"] in {"waiting", "crossing"} and not old.get("pendingExit")]
        pending_exits = [old for old in current.values() if old.get("pendingExit")]
        if any(old["lastSeenNs"] != ns and old["phase"] in {"waiting", "crossing"} and not old.get("pendingExit") for old in current.values()):
            reasons.append("A pedestrian is briefly missing; awaiting the same identity within the configured gap limit.")
        if pending_exits:
            reasons.append("A pedestrian exit awaits a second fresh observation; outside anchors are not counted in crossing occupancy.")
        historical_loss = bool(row["retired"]) or ns < row["lossOverflowUntilNs"]
        unknown = bool(reasons) or (historical_loss and not waiting_count and not crossing_count)
        if historical_loss:
            reasons.append("Earlier pedestrian visits are incomplete; current counts include only visible people.")
        if axis is None:
            reasons.append("Waiting and crossing geometry cannot define a far-side exit.")
            unknown = True
        result.update(status="unknown" if unknown else "active", waitingCount=waiting_count,
            crossingCount=crossing_count, oldestObservedWaitMs=max(waits) if waits else None,
            countBasis="currently-observed", currentCountsAvailable=True, membershipComplete=not unknown and not historical_loss,
            pendingTrackCount=len(pending_ages), pendingExitTrackCount=len(pending_exits), oldestPendingGapMs=max(pending_ages) if pending_ages else None,
            unresolvedHistoricalTrackCount=len(row["retired"]), oldestLostTrackAgeMs=(ns-min(row["retired"].values()))/1e6 if row["retired"] else None,
            lossEvidenceRetentionSeconds=900, waitBasis="first-observed-wait-entry-to-first-observed-crossing-entry",
            qualityReasons=sorted(set(reasons)))
        while row["outcomes"] and ns - row["outcomes"][0]["ns"] > HISTORY_NS:
            row["outcomes"].popleft()

    def snapshot(self, window_minutes=5, source_times=None):
        if window_minutes not in (1, 5, 15):
            raise ValueError("window_minutes must be 1, 5 or 15")
        result = {"queues": [], "crossings": []}
        for source_id, state in self.sources.items():
            now = (source_times or {}).get(source_id, state["lastSeenNs"])
            cutoff = now - window_minutes * 60_000_000_000 if now is not None else None
            for row in state["queues"].values():
                item = deepcopy(row["result"])
                history = [sample["extent"] for sample in row["history"] if cutoff is not None and cutoff <= sample["ns"] <= now]
                item.update(windowMinutes=window_minutes, maximumObservedExtentM=max(history) if history else None)
                losses = [sample for sample in row["losses"] if cutoff is not None and cutoff <= sample["ns"] <= now]
                item["lostTrackCount"] = len({sample["trackId"] for sample in losses})
                if now is not None and state["lastNs"] is not None and now - state["lastNs"] > row["config"].get("maximumObservationGapMs", 1000) * 1_000_000:
                    item.update(status="unknown", currentCountsAvailable=False, observedExtentM=None, tailPositionM=None, spillback=None, extentIsLowerBound=True,
                        qualityReasons=["The last queue observation has expired."])
                result["queues"].append(item)
            for row in state["crossings"].values():
                item = deepcopy(row["result"])
                samples = [sample for sample in row["outcomes"] if cutoff is not None and cutoff <= sample["ns"] <= now]
                waits = [sample["waitMs"] for sample in samples if sample["waitMs"] is not None]
                partial_waits = [sample["lowerBoundWaitMs"] for sample in samples if sample.get("lowerBoundWaitMs") is not None]
                losses = [sample for sample in row["losses"] if cutoff is not None and cutoff <= sample["ns"] <= now]
                item.update(windowMinutes=window_minutes, completedCount=sum(s["outcome"] == "completed" for s in samples),
                    abandonedCount=sum(s["outcome"] == "abandoned" for s in samples), returnedCount=sum(s["outcome"] == "returned" for s in samples),
                    incompleteCount=sum(s["outcome"] == "incomplete" for s in samples), waitSampleCount=len(waits),
                    waitP50Ms=_quantile(waits, .5), waitP95Ms=_quantile(waits, .95),
                    firstSeenWaitingCount=len(partial_waits), lowerBoundWaitP50Ms=_quantile(partial_waits, .5),
                    briefGapRecoveredWaitCount=sum(bool(s.get("briefGapCount")) for s in samples if s["outcome"] == "entered-crossing"),
                    recoveredExitCandidateCount=sum(s["outcome"] == "exit-candidate-recovered" for s in samples),
                    lostTrackCount=len({sample["trackId"] for sample in losses}))
                if cutoff is not None and row["overflowNs"] is not None and row["overflowNs"] >= cutoff:
                    item["qualityReasons"].append("The bounded journey history omits older samples in this window.")
                if now is not None and state["lastNs"] is not None and now - state["lastNs"] > row.get("maximumGapNs", 1_000_000_000):
                    item.update(status="unknown", currentCountsAvailable=False, oldestObservedWaitMs=None, qualityReasons=[*item["qualityReasons"], "The last pedestrian observation has expired."])
                result["crossings"].append(item)
        return result
