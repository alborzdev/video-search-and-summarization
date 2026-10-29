# SPDX-License-Identifier: Apache-2.0
"""Camera-local, event-time analytics with bounded display state.

No ground-truth actor positions or automatically generated observations enter here.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from threading import RLock
import time
import uuid
from typing import Callable

from .geometry import cross, directed_crossing, point_in_polygon, project
from .models import MapAssociation, MobilityConfig, Observation, Rule, RuleSet, Site
from .mobility import MobilityAnalytics, configuration_issues
from .motion import observed_velocity
from .store import CityStore
from .showcase import ShowcaseAnalytics


def iso_ns(value: int) -> str:
    try:
        return datetime.fromtimestamp(value / 1e9, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return str(value)


class ConflictError(ValueError):
    pass


EVENT_STATE_HISTORY_LIMIT = 32
STOP_PENDING_REASON = "stop-observation-pending"
STOP_CLEARING_REASON = "stop-clear-pending"
STOP_PROOF_FIELDS = ("stopObservedDurationNs", "stopLastConfirmedNs", "stopPreviousConfirmed")
LIVE_SOURCE_CLOCK_BASES = {"source-rtcp", "source-native-sei"}
NATIVE_CITY_CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"}


class CityEngine:
    def __init__(self, store: CityStore | None = None, clock: Callable[[], float] = time.monotonic, freshness_seconds: float = 2.0, track_ttl_seconds: float = 15.0, max_tracks: int = 2000, history_frames: int = 60):
        self.store = store or CityStore()
        self.clock = clock
        self.freshness = freshness_seconds
        self.track_ttl = track_ttl_seconds
        self.max_tracks = max_tracks
        self.history_frames = history_frames
        self.lock = RLock()
        self.site = Site.model_validate(self.store.get("site", {}))
        saved = self.store.get("rules", {"rules": [], "revision": 0})
        self.rules = [Rule.model_validate(rule) for rule in saved["rules"]]
        self.rules_revision = saved["revision"]
        self.sources: dict[str, dict] = {}
        self.tracks: dict[str, dict] = {}
        self.rule_states: dict[tuple[str, str], dict] = {}
        self.metrics: dict[str, dict] = {}
        self.showcase = ShowcaseAnalytics()
        self.events = {event["id"]: event for event in self.store.events(site_id=self.site.id)}
        self.sequence = 0
        self.analytics_scope = {"epoch": str(uuid.uuid4()), "kind": "normal", "runId": None, "startedAt": datetime.now(timezone.utc).isoformat()}
        self.analytics_suppressed = False
        self.required_tracking_epoch = None
        self.analytics_capture_floor_ns = 0
        self.boundary_observer = None
        self.media: dict[str, str] = {}
        self.histories: dict[str, deque] = {}
        self.frame_generation = 0
        self.frame_contexts: dict[str, dict] = {}
        self.map_demo_requested = os.environ.get("CITY_MV3DT_DEMO_ENABLED", "").lower() == "true"
        self.map_demo_site = os.environ.get("CITY_MV3DT_DEMO_SITE_ID", "")
        try:
            raw_calibrations = os.environ.get("CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS", "{}")
            calibrations = json.loads(raw_calibrations) if len(raw_calibrations) <= 16384 else {}
            self.map_demo_calibrations = calibrations if (isinstance(calibrations, dict) and len(calibrations) == 2
                and all(isinstance(k, str) and 0 < len(k) <= 200 and isinstance(v, str) and 0 < len(v) <= 200
                        for k, v in calibrations.items())) else {}
        except (ValueError, TypeError):
            self.map_demo_calibrations = {}
        self.map_demo_epoch: str | None = None
        self.retired_map_demo_epochs: deque = deque(maxlen=32)
        self.source_clock_mode = os.environ.get("CITY_SOURCE_CLOCK_MODE", "source-rtcp")
        if self.source_clock_mode not in LIVE_SOURCE_CLOCK_BASES:
            raise ValueError("Unsupported CITY_SOURCE_CLOCK_MODE")
        self.mobility = MobilityAnalytics(MobilityConfig.model_validate(self.store.get(f"mobility:{self.site.id}", {})), max_tracks=max_tracks)
        # A process restart is observation loss, never evidence that an event cleared.
        for event in self.events.values():
            if event["state"] == "active":
                self._mark_unknown(event, "analytics-restarted")

    def reset_analytics_scope(self, *, kind, run_id=None, scenario_id=None, suppressed=False, capture_floor_ns=0):
        """Invalidate evidence without altering camera clocks, geometry or history."""
        with self.lock:
            # Archive the actual final camera summary before invalidation
            # clears queue/curb state. Ending observation is not evidence of
            # departure or clearance; active events still become unknown below.
            archive = {**deepcopy(self.analytics_scope), "endedAt": datetime.now(timezone.utc).isoformat(),
                "lastSourceTimeNs": {key: str(value["lastNs"]) for key, value in self.sources.items()},
                "metrics": deepcopy(list(self.metrics.values())),
                "showcase": self.showcase.snapshot(self),
                "mobility": deepcopy(self.mobility.snapshot(self, 5)),
                "mobilitySnapshotBasis": "last-observed-before-boundary",
                "observationEnd": {"reason": "scenario-boundary", "activeEventState": "unknown"}}
            self._unknown_events("scenario-boundary")
            scopes = self.store.get(f"analytics-scopes:{self.site.id}", [])
            self.store.set(f"analytics-scopes:{self.site.id}", [*scopes, archive][-100:])
            self.analytics_scope = {"epoch": str(uuid.uuid4()), "kind": kind, "runId": run_id,
                "scenarioId": scenario_id, "startedAt": datetime.now(timezone.utc).isoformat()}
            self.analytics_suppressed = suppressed
            self.analytics_capture_floor_ns = capture_floor_ns
            self.tracks.clear()
            self.rule_states.clear()
            self.metrics.clear()
            self.showcase = ShowcaseAnalytics()
            self.mobility = MobilityAnalytics(self.mobility.config, max_tracks=self.max_tracks)
            self.frame_generation += 1
            self.frame_contexts.clear()
            self.sequence += 1
            return deepcopy(self.analytics_scope)

    def scope_json(self):
        return {**deepcopy(self.analytics_scope), "suppressed": self.analytics_suppressed}

    def _site_sources(self):
        return {source.id: source for source in self.site.sources}

    def _map_demo_approved(self):
        return (self.map_demo_requested and self.site.mode == "live" and self.site.id == self.map_demo_site
                and bool(self.map_demo_calibrations)
                and {source.id: source.calibrationRevision for source in self.site.sources} == self.map_demo_calibrations)

    def _native_sei_clock_approved(self):
        # Only the explicit local Spark/Isaac profile renders this environment.
        # Ordinary admission starts one pinned camera before the complete pair;
        # clock authority is independent of shared-tracker activation.
        return (self.source_clock_mode == "source-native-sei" and self.site.id == "isaac-intersection-a"
                and self.map_demo_requested and self.site.mode == "live" and self.site.id == self.map_demo_site
                and bool(self.map_demo_calibrations) and bool(self.site.sources)
                and all(source.id in self.map_demo_calibrations
                        and source.calibrationRevision == self.map_demo_calibrations[source.id]
                        for source in self.site.sources))

    def _validate_source_clock(self, observation, previous):
        native = observation.timestampBasis == "source-native-sei"
        approved = self._native_sei_clock_approved()
        if native and not approved:
            raise ValueError("source-native-sei requires the explicit pinned Isaac clock profile")
        if approved and not native:
            raise ValueError("The native SEI profile cannot fall back to another clock basis")
        if (native and previous.get("declaredSession") == observation.sourceSessionId
                and previous.get("timestampBasis") == "source-native-sei"):
            old = previous.get("sourceClockEvidence")
            if (old is None or int(observation.sourceClockEvidence.frameCounter) <= int(old["frameCounter"])
                    or int(observation.sourceTimeNs) <= previous["lastNs"]
                    or int(observation.rawSourcePtsNs) <= int(old["auPtsNs"])):
                raise ValueError("Native SEI clock/counter/PTS must advance within its source session")

    def _map_demo_frame(self, observation, previous, source):
        if not (self._map_demo_approved() and observation.trackingMode == "mv3dt-demo"
                and observation.timestampBasis in LIVE_SOURCE_CLOCK_BASES and observation.fusionEpoch):
            return False
        if observation.timestampBasis == "source-native-sei" and not observation.modelRevision:
            return False
        epoch = observation.fusionEpoch
        if previous and previous.get("sessionId") != source["sessionId"] and epoch == previous.get("mapFusionEpoch"):
            # A restarted camera must not reuse an old shared-ID namespace.
            self.retired_map_demo_epochs.append(epoch)
            if self.map_demo_epoch == epoch:
                self.map_demo_epoch = None
        if epoch in self.retired_map_demo_epochs:
            return False
        if self.map_demo_epoch != epoch:
            if self.map_demo_epoch is not None:
                self.retired_map_demo_epochs.append(self.map_demo_epoch)
            self.map_demo_epoch = epoch
        source["mapFusionEpoch"] = epoch
        return True

    def _map_association(self, observation, obj, config, frame_valid):
        native = obj.native3D
        single = observation.trackingArchitecture == "mv3dt-native-v1"
        local_identity_matches = native is not None and (
            (observation.trackingArchitecture in (None, "mv3dt-native-v1") and native.localTargetId is None
                and native.localTrackingMethod is None and native.targetId == obj.localTrackId)
            or (observation.trackingArchitecture == "nvdcf-local-then-mv3dt-v1"
                and native.localTrackingMethod == "nvidia-nvdcf-first-stage-9.2"
                and native.localTargetId == obj.localTrackId))
        if not (frame_valid and (obj.class_name in NATIVE_CITY_CLASSES if single else obj.class_name == "person") and obj.observedThisFrame
                and obj.associationMethod == "mv3dt-demo" and native is not None
                and native.method == "nvidia-mv3dt-9.2" and native.state == "observed"
                and native.calibrationRevision == config.calibrationRevision
                and local_identity_matches and native.visibility is not None and native.visibility >= .25
                and all(math.isfinite(value) for value in [*native.worldPositionM, *native.imageFootPx])
                and obj.globalTrackId == f"mv3dt-demo:{observation.fusionEpoch}:{native.targetId}"):
            return None
        position = {}
        if single:
            x, y = native.worldPositionM
            xmin, ymin, xmax, ymax = self.site.map.bounds
            if not (xmin <= x <= xmax and ymin <= y <= ymax
                    and 0 <= native.imageFootPx[0] <= config.width and 0 <= native.imageFootPx[1] <= config.height
                    and (not config.validGroundPolygon or point_in_polygon(native.imageFootPx, config.validGroundPolygon))):
                return None
            position = dict(positionM=list(native.worldPositionM), positionBasis="native-mv3dt-world-foot")
        return MapAssociation(method="mv3dt-demo", globalTrackId=obj.globalTrackId, targetId=native.targetId,
            fusionEpoch=observation.fusionEpoch, calibrationRevision=native.calibrationRevision,
            visibility=native.visibility, sourceClockBasis=observation.timestampBasis,
            classPolicy=observation.trackingClassPolicy if single else None, **position).model_dump(exclude_none=True)

    def _association_status(self):
        result = {"mode": "camera-local", "globalFusionEnabled": False}
        if self.map_demo_requested:
            approved = self._map_demo_approved()
            now = self.clock()
            available_sources = {track["sourceId"] for track in self.tracks.values()
                if track.get("mapAssociation") and track["mapAssociation"]["fusionEpoch"] == self.map_demo_epoch
                and track["observedThisFrame"] and now - track["received"] <= self.freshness}
            native = approved and all(self.sources.get(source_id, {}).get("trackingArchitecture") == "mv3dt-native-v1"
                for source_id in self.map_demo_calibrations)
            result["mapFusion"] = {"mode": "mv3dt-demo", "enabled": approved,
                "available": approved and available_sources == set(self.map_demo_calibrations),
                "experimental": True, "qualified": False,
                "positionBasis": "native-mv3dt-world-foot" if native else "camera-local-homography",
                "analyticsIdentityBasis": "camera-local", "status": "enabled" if approved else "site-or-calibration-not-approved"}
        return result

    def site_json(self):
        with self.lock:
            result = self.site.model_dump()
            for source in result["sources"]:
                if self._native_sei_clock_approved():
                    source["browserClockVerified"] = False
                if source["id"] in self.media:
                    source["mediaUrl"] = f"/api/vision/city/media/{source['id']}"
            return result

    def put_site(self, site: Site):
        with self.lock:
            expected = site.model_extra.get("expectedRevision")
            if expected is not None and expected != self.site.revision:
                raise ConflictError("site changed; reload the current revision before saving")
            if site.id == self.site.id and site.revision < self.site.revision:
                raise ConflictError("site revision cannot move backwards")
            site = site.model_copy(deep=True)
            site.model_extra.pop("expectedRevision", None)
            for source in site.sources:
                # This live API capability is not part of saved calibration.
                source.model_extra.pop("processedPreview", None)
                previous_source = self._site_sources().get(source.id)
                if site.id == self.site.id and previous_source is not None and source.id in self.media and source.mediaUrl == f"/api/vision/city/media/{source.id}":
                    # Likewise, server-registered media decorates GET without
                    # changing the underlying user-supplied site package.
                    source.mediaUrl = previous_source.mediaUrl
            if site != self.site:
                self.frame_generation += 1
                self.frame_contexts.clear()
                self._unknown_events("site-or-calibration-changed")
                self.sources.clear()
                self.tracks.clear()
                self.rule_states.clear()
                self.metrics.clear()
                self.histories.clear()
                self.map_demo_epoch = None
                self.retired_map_demo_epochs.clear()
                self.store.clear_history()
                source_configs = {source.id: source for source in site.sources}
                previous_configs = self._site_sources()
                if self.rules or self.rules_revision:
                    self.rules_revision += 1
                    rules = []
                    for rule in self.rules:
                        if rule.sourceId not in source_configs:
                            continue
                        update = {"revision": self.rules_revision}
                        needs_calibration = rule.geometry.space == "site-metres" or rule.kind in {"stopped-in-zone", "queue", "wrong-way"}
                        source = source_configs[rule.sourceId]
                        previous_source = previous_configs.get(rule.sourceId)
                        calibration_changed = previous_source is None or any(getattr(previous_source, key) != getattr(source, key) for key in ("width", "height", "imageToGroundHomography", "classImageToGroundHomographies", "validGroundPolygon", "calibrationRevision"))
                        if needs_calibration and source.imageToGroundHomography is None:
                            update.update(enabled=False, validationError="calibration-required-after-site-change")
                        elif needs_calibration and calibration_changed:
                            update.update(enabled=False, validationError="calibration-changed-after-site-change")
                        retained_rule = rule.model_copy(update=update)
                        # A stale optional binding must not make GET -> PUT fail.
                        # Metric rules remain disabled until reviewed; image-only
                        # rules do not inherit a dependency on ground calibration.
                        if retained_rule.model_extra.get("calibrationRevision") != source.calibrationRevision:
                            retained_rule.model_extra.pop("calibrationRevision", None)
                        rules.append(retained_rule)
                    self.rules = rules
                    self.store.set("rules", {"rules": [rule.model_dump() for rule in self.rules], "revision": self.rules_revision})
                self.site = site
                self.mobility = MobilityAnalytics(MobilityConfig.model_validate(self.store.get(f"mobility:{site.id}", {})), max_tracks=self.max_tracks)
                self.events = {event["id"]: event for event in self.store.events(site_id=site.id)}
                self.store.set("site", site.model_dump())
                self.sequence += 1
            return self.site_json()

    def rules_json(self):
        return {"rules": [rule.model_dump() for rule in self.rules], "revision": self.rules_revision, "status": "active", "authority": "city-behavior-analytics"}

    def put_rules(self, payload: RuleSet):
        with self.lock:
            if payload.expectedRevision is not None and payload.expectedRevision != self.rules_revision:
                raise ConflictError("rules changed; reload the current revision before saving")
            sources = self._site_sources()
            for rule in payload.rules:
                if rule.sourceId not in sources:
                    raise ValueError(f"unknown source for rule {rule.id}")
                source = sources[rule.sourceId]
                rule_calibration = rule.model_extra.get("calibrationRevision")
                if rule_calibration is not None and rule_calibration != source.calibrationRevision:
                    raise ValueError(f"calibration revision mismatch for rule {rule.id}")
                if rule.enabled and (rule.geometry.space == "site-metres" or rule.kind in {"stopped-in-zone", "queue", "wrong-way"}) and source.imageToGroundHomography is None:
                    raise ValueError(f"rule {rule.id} requires valid ground calibration")
            self._unknown_events("rules-replaced")
            self.frame_generation += 1
            self.frame_contexts.clear()
            self.rules_revision += 1
            self.rules = [rule.model_copy(update={"revision": self.rules_revision}) for rule in payload.rules]
            self.rule_states.clear()
            self.metrics.clear()
            self.mobility = MobilityAnalytics(self.mobility.config, max_tracks=self.max_tracks)
            self.store.set("rules", {"rules": [rule.model_dump() for rule in self.rules], "revision": self.rules_revision})
            self.sequence += 1
            return self.rules_json()

    def _set_event_state(self, event: dict, state: str, ns: int, reason: str | None = None):
        """Persist a bounded source-clock history, not just the latest state."""
        history = event.setdefault("stateHistory", [])
        event.setdefault("stateHistoryComplete", False)  # legacy records lack prior transitions
        if history:
            ns = max(ns, int(history[-1]["atNs"]))
        transition = {"atNs": str(ns), "state": state, "reason": reason}
        if history and history[-1]["atNs"] == str(ns):
            history[-1] = transition
        elif not history or (history[-1]["state"], history[-1]["reason"]) != (state, reason):
            history.append(transition)
        if len(history) > EVENT_STATE_HISTORY_LIMIT:
            del history[:-EVENT_STATE_HISTORY_LIMIT]
            event["stateHistoryComplete"] = False
        event["stateHistoryStartsAtNs"] = history[0]["atNs"]
        event.update(state=state, stateReason=reason, updatedAtNs=str(ns))
        if event.get("kind") == "stopped-in-zone" and state != "active":
            event.update(stopEvidenceStatus="unknown" if state == "unknown" else "cleared", stopEvidenceAtNs=None)
        if state in {"active", "unknown"}:
            event["unknownAtNs"] = str(ns) if state == "unknown" else None
        self.store.save_event(event)

    def _mark_unknown(self, event: dict, reason: str):
        # Configuration/loss has no new camera observation. Bound invalidation
        # to the last known source clock, never fabricate a departure or use
        # unrelated wall time (recorded/fixture clocks can be historical).
        source_ns = self.sources.get(event["sourceId"], {}).get("lastNs", -1)
        at = max(source_ns, int(event.get("updatedAtNs", event["triggeredAtNs"])))
        self._set_event_state(event, "unknown", at, reason)

    def _unknown_events(self, reason: str, source_id: str | None = None):
        self.mobility.invalidate_source(source_id, reason)
        for event in self.events.values():
            if event["state"] == "active" and (source_id is None or event["sourceId"] == source_id):
                self._mark_unknown(event, reason)
        rule_ids = {rule.id for rule in self.rules if source_id is None or rule.sourceId == source_id}
        for (rule_id, _), state in self.rule_states.items():
            if rule_id in rule_ids:
                # Loss also breaks not-yet-triggered duration/clear candidates
                # and line segments; no continuous movement was observed.
                for field in ("candidateSince", "candidateSinceSequence", "clearSince", "enteredAt", "lastPoint", "lastPointNs", *STOP_PROOF_FIELDS):
                    state.pop(field, None)
                state["observationInvalidated"] = True

    def _new_session(self, source_id: str, source: dict, session: str):
        self._unknown_events("source-session-reset", source_id)
        self.mobility.reset_source(source_id)
        self.tracks = {key: track for key, track in self.tracks.items() if track["sourceId"] != source_id}
        rule_ids = {rule.id for rule in self.rules if rule.sourceId == source_id}
        self.rule_states = {key: value for key, value in self.rule_states.items() if key[0] not in rule_ids}
        self.histories.pop(source_id, None)
        retired = source.get("retiredSessions", deque(maxlen=32))
        if source.get("declaredSession"):
            retired.append(source["declaredSession"])
        return {"sessionId": session, "declaredSession": session, "lastNs": -1, "lastSequence": -1, "retiredSessions": retired, "recentResetFrames": source.get("recentResetFrames", deque(maxlen=32)), "resets": source.get("resets", 0)}

    def ingest(self, observation: Observation):
        with self.lock:
            if observation.siteId != self.site.id:
                raise ValueError("siteId does not match configured site")
            config = self._site_sources().get(observation.sourceId)
            if config is None:
                raise ValueError("register source in site package before ingestion")
            if (observation.image.width, observation.image.height) != (config.width, config.height):
                raise ValueError("decoded image dimensions differ from calibration; update the site package")
            if observation.calibrationRevision is not None and observation.calibrationRevision != config.calibrationRevision:
                raise ValueError("observation calibrationRevision differs from configured camera")
            now, ns, seq = self.clock(), int(observation.sourceTimeNs), int(observation.sequence)
            source_id = observation.sourceId
            previous = self.sources.get(source_id, {})
            self._validate_source_clock(observation, previous)
            declared = observation.sourceSessionId
            if declared in previous.get("retiredSessions", ()) and declared != previous.get("declaredSession"):
                return {"accepted": False, "reason": "retired-session", "sourceId": source_id}
            reset_identity = (declared, seq, ns, observation.timestampBasis)
            if observation.reset and reset_identity in previous.get("recentResetFrames", ()):
                return {"accepted": False, "reason": "duplicate-reset", "sourceId": source_id, "sequence": observation.sequence}
            source = previous
            if not source or declared != source.get("declaredSession"):
                source = self._new_session(source_id, previous, declared)
            elif observation.timestampBasis != source.get("timestampBasis") and not observation.reset:
                if seq <= source["lastSequence"]:
                    return {"accepted": False, "reason": "late-prior-clock-basis", "sourceId": source_id, "sequence": observation.sequence}
                resets = source.get("resets", 0) + 1
                source = self._new_session(source_id, previous, f"{declared}~clock-basis-{resets}")
                source.update(declaredSession=declared, resets=resets)
            elif observation.reset or (ns < source["lastNs"] - 2_000_000_000 and seq < source["lastSequence"]):
                resets = source.get("resets", 0) + 1
                source = self._new_session(source_id, previous, f"{declared}~reset-{resets}")
                source.update(declaredSession=declared, resets=resets)
            elif seq <= source["lastSequence"] or ns < source["lastNs"]:
                return {"accepted": False, "reason": "duplicate-or-out-of-order", "sourceId": source_id, "sequence": observation.sequence}
            if previous and now - previous.get("received", now) > self.freshness:
                # Detect a stalled source even if nobody polled health while it
                # was offline and its media clock resumes only one frame later.
                self._unknown_events("source-stale", source_id)
            map_frame_valid = self._map_demo_frame(observation, previous, source)
            source.update(previousFrameNs=source["lastNs"], lastNs=ns, lastSequence=seq, received=now, timestampBasis=observation.timestampBasis, mediaTimeSeconds=observation.mediaTimeSeconds, mediaTimeBasis=observation.mediaTimeBasis, rawSourcePtsNs=observation.rawSourcePtsNs, modelRevision=observation.modelRevision, trackingArchitecture=observation.trackingArchitecture, trackingMode=observation.trackingMode, fusionEpoch=observation.fusionEpoch, trackingEpoch=observation.trackingEpoch)
            source["sourceClockEvidence"] = observation.sourceClockEvidence.model_dump() if observation.sourceClockEvidence else None
            if observation.reset:
                source["recentResetFrames"].append(reset_identity)
            progress = source.setdefault("clockProgress", deque(maxlen=16))
            if not progress or now - progress[-1][0] >= 1:
                progress.append((now, ns))
            self.sources[source_id] = source
            if self.boundary_observer is not None:
                self.boundary_observer(observation)
            gated = (self.analytics_suppressed or ns < self.analytics_capture_floor_ns
                or (self.required_tracking_epoch is not None and observation.trackingEpoch != self.required_tracking_epoch))
            if gated:
                self.sequence += 1
                self._save_history(source_id, ns, observation.mediaTimeSeconds)
                return {"accepted": True, "sourceId": source_id, "sessionId": source["sessionId"],
                    "sequence": observation.sequence, "trackCount": 0, "analyticsSuppressed": True,
                    "analyticsScope": self.scope_json()}
            current = set()
            for obj in observation.objects:
                track_id = f"{source_id}:{source['sessionId']}:{self.analytics_scope['epoch']}:{obj.localTrackId}"
                old = self.tracks.get(track_id)
                # A class change breaks the duration/speed chain instead of inheriting dwell.
                if old and old["class"] != obj.class_name:
                    self._retire_track(track_id, "track-class-changed")
                    old = None
                anchor = [obj.bboxPx[0] + obj.bboxPx[2] / 2, obj.bboxPx[1] + obj.bboxPx[3]]
                homography = config.classImageToGroundHomographies.get(obj.class_name, config.imageToGroundHomography)
                position, projection_status = project(anchor, homography, config.validGroundPolygon, self.site.map.bounds)
                if not (0 <= anchor[0] <= config.width and 0 <= anchor[1] <= config.height):
                    position, projection_status = None, "outside-image"
                velocity = None
                image_velocity = None
                # Predictions may carry a box, but must neither add motion
                # samples nor erase the bounded history of real observations.
                motion_samples = old.get("motionSamples", []) if old else []
                if position is not None and obj.observedThisFrame:
                    last_real_ns = old.get("lastObservedSourceTimeNsInt") if old else None
                    last_real_wall = old.get("lastObservedReceived", old["received"]) if old else None
                    continuous = bool(old and motion_samples and last_real_ns is not None
                        and last_real_wall is not None and now - last_real_wall <= self.freshness
                        and 0 < ns - last_real_ns <= 1_000_000_000)
                    velocity, motion_samples = observed_velocity(old.get("motionSamples", []) if old else [],
                        ns, position, continuous=continuous)
                elif obj.observedThisFrame:
                    motion_samples = []  # Invalid real projection breaks the motion proof.
                if old and obj.observedThisFrame and old["observedThisFrame"] and now - old["received"] <= self.freshness:
                    elapsed = (ns - old["sourceTimeNsInt"]) / 1e9
                    if 0 < elapsed <= 1.0:
                        image_velocity = [(anchor[i] - old["anchorPx"][i]) / (elapsed * (config.width if i == 0 else config.height)) for i in range(2)]
                trail = deque(old["trail"] if old else [], maxlen=40)
                if position is not None and obj.observedThisFrame:
                    trail.append({"positionM": position, "sourceTimeNs": str(ns)})
                track = {"id": track_id, "sourceId": source_id, "sessionId": source["sessionId"], "sourceSessionId": source["sessionId"], "localTrackId": obj.localTrackId, "globalTrackId": obj.globalTrackId, "associationMethod": obj.associationMethod, "class": obj.class_name, "bboxPx": obj.bboxPx, "anchorPx": anchor, "positionM": position, "projectionStatus": projection_status, "positionUncertaintyM": obj.positionUncertaintyM, "velocityMps": velocity, "speedMps": math.hypot(*velocity) if velocity else None, "confidence": obj.confidence, "observedThisFrame": obj.observedThisFrame, "stale": not obj.observedThisFrame, "sourceTimeNs": str(ns), "sourceTimeNsInt": ns, "mediaTimeSeconds": observation.mediaTimeSeconds, "received": now, "trail": list(trail), "calibrationRevision": config.calibrationRevision, "modelRevision": observation.modelRevision}
                if observation.trackingMode == "mv3dt-demo" or obj.associationMethod == "mv3dt-demo":
                    # Experimental display association never becomes an analytics identity.
                    track.update(globalTrackId=None, associationMethod=None)
                track["mapAssociation"] = self._map_association(observation, obj, config, map_frame_valid)
                # Tracker predictions carry a new frame clock, but are not new
                # detections. Duration/gap rules must use the last real sighting
                # so repeated predictions cannot preserve an alert indefinitely.
                previous_observed_ns = old["lastObservedSourceTimeNsInt"] if old else None
                track["lastObservedSourceTimeNsInt"] = ns if obj.observedThisFrame else previous_observed_ns
                track["lastObservedReceived"] = now if obj.observedThisFrame else (old.get("lastObservedReceived", old["received"]) if old else None)
                track["previousObservedSourceTimeNsInt"] = previous_observed_ns
                track["imageVelocityNormalizedPerSecond"] = image_velocity
                track["motionSamples"] = motion_samples
                track["speedEstimationBasis"] = "trailing-observed-position-fit-1s"
                self.tracks[track_id] = track
                current.add(track_id)
            for track in self.tracks.values():
                if track["sourceId"] == source_id and track["id"] not in current:
                    track["observedThisFrame"] = False
                    track["mapAssociation"] = None
            self._evaluate(source_id, ns)
            self.showcase.observe(self, source_id, ns)
            self.mobility.observe(self, source_id, ns, now)
            self._prune(now)
            self.sequence += 1
            self._save_history(source_id, ns, observation.mediaTimeSeconds)
            return {"accepted": True, "sourceId": source_id, "sessionId": source["sessionId"], "sequence": observation.sequence, "trackCount": len(current)}

    def put_mobility_config(self, config: MobilityConfig):
        with self.lock:
            if config.expectedRevision is not None and config.expectedRevision != self.mobility.config.revision:
                raise ConflictError("mobility configuration changed; reload before saving")
            issues = configuration_issues(config, self.site, self.rules)
            if issues:
                raise ValueError("; ".join(f"{item['id']}: {item['reason']}" for item in issues))
            saved = config.model_copy(update={"revision": self.mobility.config.revision + 1, "expectedRevision": None}, deep=True)
            self.store.set(f"mobility:{self.site.id}", saved.model_dump())
            self.mobility = MobilityAnalytics(saved, max_tracks=self.max_tracks)
            return {"config": saved.model_dump(), "configRevision": saved.revision}

    def mobility_json(self, window_minutes=5):
        if window_minutes not in (1, 5, 15):
            raise ValueError("windowMinutes must be 1, 5 or 15")
        with self.lock:
            self._refresh_freshness(self.clock())
            return {**self.mobility.snapshot(self, window_minutes), "analyticsScope": self.scope_json()}

    def _retire_track(self, track_id: str, reason: str):
        self.tracks.pop(track_id, None)
        aggregate_rules = {rule.id for rule in self.rules if rule.kind in {"occupancy-threshold", "queue"}}
        for key, state in list(self.rule_states.items()):
            if key[1] == track_id:
                if key[0] in aggregate_rules and state.get("inside"):
                    aggregate = self.rule_states.setdefault((key[0], "__aggregate__"), {})
                    lost = aggregate.setdefault("lostInsideTrackIds", set())
                    # Display/cache eviction cannot prove departure. Retain a
                    # bounded identity tombstone until actual reacquisition;
                    # overflow stays explicitly uncertain until a source reset.
                    if track_id in lost or len(lost) < self.max_tracks:
                        lost.add(track_id)
                    else:
                        aggregate["lostInsideOverflow"] = True
                if state.get("eventId") in self.events:
                    event = self.events[state["eventId"]]
                    if event["state"] == "active":
                        self._mark_unknown(event, reason)
                self.rule_states.pop(key)

    def _point(self, track, rule, source=None):
        if rule.geometry.space == "site-metres":
            return track["positionM"]
        source = source or self._site_sources()[track["sourceId"]]
        return [track["anchorPx"][0] / source.width, track["anchorPx"][1] / source.height]

    def _event(self, rule: Rule, key: str, state: dict, ns: int, track_ids: list[str], measurements: dict, instant: bool = False):
        source = self.sources[rule.sourceId]
        since = state.get("candidateSince", ns)
        since_sequence = state.get("candidateSinceSequence", source["lastSequence"])
        identity = f"{self.site.id}|{rule.sourceId}|{source['sessionId']}|{rule.id}|{rule.revision}|{key}|{since}|{since_sequence}"
        event_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
        start_media = source.get("mediaTimeSeconds")
        if start_media is not None:
            start_media = max(0, start_media - (ns - since) / 1e9)
        event = {"analyticsScope": self.scope_json(), "id": event_id, "siteId": self.site.id, "mode": self.site.mode, "ruleId": rule.id, "ruleName": rule.name, "ruleRevision": rule.revision, "kind": rule.kind, "sourceId": rule.sourceId, "sessionId": source["sessionId"], "trackIds": track_ids, "state": "cleared" if instant else "active", "startedAt": iso_ns(since), "startedAtNs": str(since), "triggeredAt": iso_ns(ns), "triggeredAtNs": str(ns), "endedAt": iso_ns(ns) if instant else None, "endedAtNs": str(ns) if instant else None, "updatedAtNs": str(ns), "message": f"{rule.name}: {rule.kind.replace('-', ' ')}", "metrics": measurements, "calibrationRevision": self._site_sources()[rule.sourceId].calibrationRevision, "modelRevision": source.get("modelRevision"), "evidence": {"status": "source-recording" if self.site.mode == "recorded-inference" and start_media is not None else "unavailable", "sourceId": rule.sourceId, "startTimeNs": str(max(0, since - 5_000_000_000)), "endTimeNs": str(ns + 5_000_000_000), "mediaTimeSeconds": start_media, "clipUrl": self._site_sources()[rule.sourceId].mediaUrl}}
        if rule.sourceId in self.media:
            event["evidence"]["clipUrl"] = f"/api/vision/city/media/{rule.sourceId}"
        event["evidence"]["startMediaTimeSeconds"] = start_media
        event["evidence"]["triggerMediaTimeSeconds"] = source.get("mediaTimeSeconds")
        if event_id not in self.events:
            event["triggerMetrics"] = deepcopy(measurements)
            event["stateHistory"] = [{"atNs": str(ns), "state": event["state"], "reason": None}]
            event["stateHistoryComplete"] = True
            event["stateHistoryStartsAtNs"] = str(ns)
            self.events[event_id] = event
            self.store.save_event(event)
        state["eventId"] = event_id
        return event_id

    def _transition(self, rule, key, ns, condition, tracks, measurements, uncertain=False, *, evidence_reasons=None, uncertainty_reason="observation-gap", duration_ns=None):
        state = self.rule_states.setdefault((rule.id, key), {})
        event = self.events.get(state.get("eventId"))
        if uncertain:
            if evidence_reasons is not None and uncertainty_reason is not None:
                evidence_reasons.add(uncertainty_reason)
            if event and event["state"] == "active":
                self._set_event_state(event, "unknown", ns, "observation-gap")
            state.pop("candidateSince", None)
            state.pop("candidateSinceSequence", None)
            state.pop("clearSince", None)
            if rule.kind == "stopped-in-zone":
                for field in STOP_PROOF_FIELDS:
                    state.pop(field, None)
            return "unknown"
        if condition:
            state.pop("clearSince", None)
            state.setdefault("candidateSince", ns)
            state.setdefault("candidateSinceSequence", self.sources[rule.sourceId]["lastSequence"])
            if event and event["state"] == "unknown":
                # The same unresolved incident can resume, but a duration
                # condition must be proven again after the blind interval.
                event["latestMetrics"] = measurements
                if (ns - state["candidateSince"] if duration_ns is None else duration_ns) < rule.conditions.minimumDurationMs * 1_000_000:
                    if evidence_reasons is not None:
                        evidence_reasons.add("duration-requalification")
                    return "unknown"
                self._set_event_state(event, "active", ns)
            if event and event["state"] in {"active", "unknown"}:
                event["latestMetrics"] = measurements
                return "active"
            if (ns - state["candidateSince"] if duration_ns is None else duration_ns) >= rule.conditions.minimumDurationMs * 1_000_000:
                self._event(rule, key, state, ns, tracks, measurements)
                return "active"
            return "candidate"
        state.pop("candidateSince", None)
        state.pop("candidateSinceSequence", None)
        if event and event["state"] in {"active", "unknown"}:
            state.setdefault("clearSince", ns)
            if ns - state["clearSince"] >= rule.conditions.clearAfterMs * 1_000_000:
                event.update(endedAt=iso_ns(ns), endedAtNs=str(ns))
                self._set_event_state(event, "cleared", ns)
                state.pop("eventId", None)
                state.pop("clearSince", None)
            else:
                if event["state"] == "unknown" and evidence_reasons is not None:
                    evidence_reasons.add("clear-hysteresis")
                return event["state"]
        return "normal"

    def _stop_pending(self, rule, key, ns, evidence_reasons):
        """Keep the incident identity during a bounded loss, without stop proof."""
        state = self.rule_states[(rule.id, key)]
        last = state.get("stopLastConfirmedNs")
        state["stopPreviousConfirmed"] = False
        if (last is None or state.get("observationInvalidated")
                or not 0 <= ns - last <= rule.conditions.maximumObservationGapMs * 1_000_000):
            return False
        event = self.events.get(state.get("eventId"))
        if event and event["state"] == "active":
            if event.get("stopEvidenceStatus") != "pending":
                event.update(stopEvidenceStatus="pending", stopEvidenceAtNs=None)
                self._set_event_state(event, "active", ns, STOP_PENDING_REASON)
        evidence_reasons.add(STOP_PENDING_REASON)
        return True

    def _stop_transition(self, rule, key, ns, condition, track, measurements, uncertain, evidence_reasons):
        """Accumulate only consecutive fresh stopped intervals, never blind time."""
        state = self.rule_states[(rule.id, key)]
        if uncertain and self._stop_pending(rule, key, ns, evidence_reasons):
            return "unknown"
        if condition and not uncertain:
            previous = state.get("stopLastConfirmedNs")
            if state.get("stopPreviousConfirmed") and previous is not None:
                state["stopObservedDurationNs"] = state.get("stopObservedDurationNs", 0) + ns - previous
            state.update(stopLastConfirmedNs=ns, stopPreviousConfirmed=True)
        else:
            state["stopPreviousConfirmed"] = False
            state.pop("stopLastConfirmedNs", None)
        duration = state.get("stopObservedDurationNs", 0)
        measurements = {**measurements, "durationMs": duration / 1e6,
                        "durationBasis": "consecutive-fresh-stopped-observations"}
        status = self._transition(rule, key, ns, condition, [track["id"]], measurements,
            uncertain=uncertain, evidence_reasons=evidence_reasons, uncertainty_reason="speed-unavailable",
            duration_ns=duration)
        event = self.events.get(state.get("eventId"))
        if event and event["state"] == "active":
            evidence = "confirmed" if condition and not uncertain else "clearing"
            reason = None if evidence == "confirmed" else STOP_CLEARING_REASON
            changed = event.get("stopEvidenceStatus") != evidence or event.get("stateReason") != reason
            event.update(stopEvidenceStatus=evidence, stopEvidenceAtNs=str(ns) if evidence == "confirmed" else None,
                         latestMetrics=measurements)
            if changed:
                self._set_event_state(event, "active", ns, reason)
        elif not event or event["state"] == "cleared":
            if not condition:
                for field in STOP_PROOF_FIELDS:
                    state.pop(field, None)
        return status

    def _evaluate(self, source_id: str, ns: int):
        candidates = [track for track in self.tracks.values() if track["sourceId"] == source_id]
        source_config = self._site_sources()[source_id]
        for rule in self.rules:
            if not rule.enabled or rule.sourceId != source_id:
                continue
            metric = self.metrics.setdefault(rule.id, {"ruleId": rule.id, "totalCrossings": 0, "count": 0, "occupancy": 0, "activeEventCount": 0, "oldestDwellMs": 0, "status": "normal"})
            maximum_gap_ns = rule.conditions.maximumObservationGapMs * 1_000_000
            previous_frame_ns = self.sources[source_id].get("previousFrameNs", -1)
            if rule.kind in {"occupancy-threshold", "queue"} and previous_frame_ns >= 0 and ns - previous_frame_ns > maximum_gap_ns:
                # Aggregate duration has its own state. A camera-wide clock gap
                # breaks its proof even if the same objects are seen again.
                self._transition(rule, "__aggregate__", ns, False, [], {}, uncertain=True)
            relevant = [track for track in candidates if not rule.classes or track["class"] in rule.classes]
            inside, unknown, statuses, oldest = [], False, [], 0
            evidence_reasons: set[str] = set()
            rule_speeds = {}
            for track in relevant:
                key = track["id"]
                state = self.rule_states.setdefault((rule.id, key), {})
                observed_ns = track["lastObservedSourceTimeNsInt"]
                gap = ns - observed_ns if observed_ns is not None else None
                fresh = track["observedThisFrame"] and gap == 0
                rule_speeds[key] = track["speedMps"]
                point = self._point(track, rule, source_config)
                if not fresh:
                    if state.get("inside"):
                        if not state.get("observationInvalidated") and gap is not None and gap <= maximum_gap_ns:
                            inside.append(track)
                            if rule.kind == "stopped-in-zone":
                                if self._stop_pending(rule, key, ns, evidence_reasons):
                                    statuses.append("unknown")
                                elif state.get("eventId"):
                                    statuses.append(self._transition(rule, key, ns, False, [key], {}, uncertain=True,
                                        evidence_reasons=evidence_reasons))
                        else:
                            unknown = True
                            reason = "waiting-for-fresh-observation" if state.get("observationInvalidated") else "observation-gap"
                            statuses.append(self._transition(rule, key, ns, False, [key], {}, uncertain=True, evidence_reasons=evidence_reasons, uncertainty_reason=reason))
                    continue
                state.pop("observationInvalidated", None)
                previous_ns = track["previousObservedSourceTimeNsInt"]
                if previous_ns is not None and ns - previous_ns > maximum_gap_ns:
                    self._transition(rule, key, ns, False, [key], {}, uncertain=True)
                    state.pop("enteredAt", None)
                    # A metre-speed estimate across a longer interval may be
                    # displayed, but cannot prove this rule's stricter gap limit.
                    rule_speeds[key] = None
                if point is None:
                    if state.get("inside"):
                        unknown = True
                    statuses.append(self._transition(rule, key, ns, False, [key], {}, uncertain=True, evidence_reasons=evidence_reasons, uncertainty_reason="projection-unavailable"))
                    continue
                if rule.kind == "line-crossing":
                    last = state.get("lastPoint")
                    last_ns = state.get("lastPointNs", ns)
                    hysteresis = rule.conditions.lineHysteresis
                    if hysteresis is None:
                        hysteresis = 0.003 if rule.geometry.space == "image-normalized" else 0.15
                    distance = abs(cross(*rule.geometry.points, point)) / math.dist(*rule.geometry.points)
                    if distance > hysteresis and last is not None and ns - last_ns <= rule.conditions.maximumObservationGapMs * 1_000_000 and directed_crossing(last, point, rule.geometry.points, rule.geometry.direction):
                        state["candidateSince"] = ns
                        state["candidateSinceSequence"] = self.sources[source_id]["lastSequence"]
                        self._event(rule, key, state, ns, [key], {"direction": rule.geometry.direction, "count": 1}, instant=True)
                        state.pop("eventId", None)
                        metric["totalCrossings"] += 1
                    if distance > max(1e-7, hysteresis):
                        state.update(lastPoint=point, lastPointNs=ns)
                    continue
                contains = point_in_polygon(point, rule.geometry.points)
                state["inside"] = contains
                aggregate = self.rule_states.get((rule.id, "__aggregate__"), {})
                aggregate.get("lostInsideTrackIds", set()).discard(key)
                if contains:
                    inside.append(track)
                    state.setdefault("enteredAt", ns)
                    oldest = max(oldest, (ns - state["enteredAt"]) / 1e6)
                else:
                    state.pop("enteredAt", None)
                condition, uncertain = contains, False
                speed = rule_speeds[key]
                if rule.kind in {"stopped-in-zone", "queue"}:
                    condition = contains and speed is not None and speed <= rule.conditions.speedBelowMps
                    uncertain = contains and speed is None
                elif rule.kind == "wrong-way":
                    velocity = track["velocityMps"] if rule.geometry.space == "site-metres" else track.get("imageVelocityNormalizedPerSecond")
                    direction = rule.geometry.direction
                    norm = math.hypot(*velocity) if velocity else 0
                    condition = contains and speed is not None and speed >= rule.conditions.speedAboveMps and norm > 0 and sum(velocity[i] * direction[i] for i in range(2)) / (norm * math.hypot(*direction)) <= rule.conditions.wrongWayCosine if velocity else False
                    uncertain = contains and (velocity is None or speed is None)
                if rule.kind not in {"occupancy-threshold", "queue"}:
                    if uncertain and track["positionM"] is None:
                        evidence_reasons.add("projection-unavailable")
                    reason = "speed-unavailable" if speed is None else "direction-unavailable"
                    measurements = {"durationMs": (ns - state.get("candidateSince", ns)) / 1e6, "speedMps": speed}
                    if rule.kind == "stopped-in-zone":
                        statuses.append(self._stop_transition(rule, key, ns, condition, track, measurements, uncertain, evidence_reasons))
                    else:
                        statuses.append(self._transition(rule, key, ns, condition, [key], measurements, uncertain=uncertain, evidence_reasons=evidence_reasons, uncertainty_reason=reason))
            if rule.kind in {"occupancy-threshold", "queue"}:
                aggregate = self.rule_states.get((rule.id, "__aggregate__"), {})
                if aggregate.get("lostInsideTrackIds"):
                    evidence_reasons.add("lost-track-membership")
                if aggregate.get("lostInsideOverflow"):
                    evidence_reasons.add("lost-track-capacity")
                unknown = unknown or bool(aggregate.get("lostInsideTrackIds")) or aggregate.get("lostInsideOverflow", False)
                qualifying = inside
                if rule.kind == "queue":
                    qualifying = [track for track in inside if rule_speeds[track["id"]] is not None and rule_speeds[track["id"]] <= rule.conditions.speedBelowMps]
                    if any(rule_speeds[track["id"]] is None for track in inside):
                        unknown = True
                        evidence_reasons.add("speed-unavailable")
                        if any(track["positionM"] is None for track in inside):
                            evidence_reasons.add("projection-unavailable")
                condition = len(qualifying) >= rule.conditions.countThreshold
                statuses.append(self._transition(rule, "__aggregate__", ns, condition, [track["id"] for track in qualifying], {"count": len(qualifying), "threshold": rule.conditions.countThreshold}, uncertain=unknown and not condition, evidence_reasons=evidence_reasons, uncertainty_reason=None))
            count = len(qualifying) if rule.kind == "queue" else len(inside)
            status = next((status for status in ("active", "unknown", "candidate") if status in statuses), "normal")
            metric.update(occupancy=len(inside), count=count, oldestDwellMs=oldest, timestamp=iso_ns(ns), activeEventCount=sum(event["state"] == "active" and event["ruleId"] == rule.id for event in self.events.values()), status=status, evidenceReasons=sorted(evidence_reasons) if status == "unknown" else [])

    def _prune(self, now: float):
        for key, track in list(self.tracks.items()):
            if now - track["received"] > self.track_ttl:
                self._retire_track(key, "track-expired")
        if len(self.tracks) > self.max_tracks:
            for key in sorted(self.tracks, key=lambda key: self.tracks[key]["received"])[:len(self.tracks) - self.max_tracks]:
                self._retire_track(key, "capacity-eviction")
        if len(self.events) > 1000:
            recent = sorted(self.events.values(), key=lambda event: int(event["triggeredAtNs"]), reverse=True)
            # Keep display memory bounded even if thousands of tracks become unknown.
            # All transitions remain available in the independently bounded SQL store.
            self.events = {event["id"]: event for event in recent[:1000]}

    def _track_json(self, track: dict, now: float):
        # This is a detached public JSON snapshot. Copying every scalar and
        # trail point through Python's generic deepcopy dominates frame-cache
        # work under two-camera load. The C JSON codec preserves the wire
        # values and isolates all nested lists/dicts from later track updates.
        public = {key: value for key, value in track.items() if key not in {"received", "lastObservedReceived", "sourceTimeNsInt", "lastObservedSourceTimeNsInt", "previousObservedSourceTimeNsInt", "motionSamples"}}
        result = json.loads(json.dumps(public, allow_nan=False, separators=(",", ":")))
        result["stale"] = now - track["received"] > self.freshness or not track["observedThisFrame"]
        if result.get("mapAssociation") and (result["stale"] or not self._map_demo_approved()
                or result["mapAssociation"]["fusionEpoch"] != self.map_demo_epoch):
            result["mapAssociation"] = None
        return result

    def _source_json(self, config, now):
        state = self.sources.get(config.id)
        result = config.model_dump()
        result["analyticsScope"] = self.scope_json()
        result["trackingEpoch"] = state.get("trackingEpoch") if state else None
        result["modelRevision"] = state.get("modelRevision") if state else None
        result["sourceClockMode"] = "source-native-sei" if self._native_sei_clock_approved() else "source-rtcp"
        result["sourceClockEvidence"] = deepcopy(state.get("sourceClockEvidence")) if state else None
        if self._native_sei_clock_approved():
            result["browserClockVerified"] = False
        for field in ("trackingArchitecture", "trackingMode", "fusionEpoch"):
            result[field] = state.get(field) if state else None
        if config.id in self.media:
            result["mediaUrl"] = f"/api/vision/city/media/{config.id}"
        result.update(status="awaiting-observations" if state is None else ("stale" if now - state["received"] > self.freshness else "live"), lastSourceTimeNs=str(state["lastNs"]) if state else None, sessionId=state["sessionId"] if state else None, sourceSessionId=state["declaredSession"] if state else None, sequence=str(state["lastSequence"]) if state else None, mediaTimeSeconds=state.get("mediaTimeSeconds") if state else None, mediaTimeBasis=state.get("mediaTimeBasis") if state else None, rawSourcePtsNs=state.get("rawSourcePtsNs") if state else None, timestampBasis=state.get("timestampBasis") if state else None)
        progress = state.get("clockProgress", ()) if state else ()
        interval = state["received"] - progress[0][0] if progress else 0
        ratio = ((state["lastNs"] - progress[0][1]) / 1e9 / interval) if interval >= 3 else None
        basis = state.get("timestampBasis") if state else None
        age = time.time() - state["lastNs"] / 1e9 if state and self.site.mode == "live" and basis in LIVE_SOURCE_CLOCK_BASES else None
        delayed = age is not None and (age > 5 or age < -5 or (ratio is not None and ratio < 0.9))
        result.update(ingestAgeSeconds=max(0, now - state["received"]) if state else None, sourceClockAgeSeconds=age, sourceClockProgressRatio=ratio, sourceClockPrecision="unverified", sourceClockStatus="delayed-or-unsynchronized" if delayed else (f"unverified-{basis}" if age is not None else "unavailable"))
        return result

    def _save_history(self, source_id: str, ns: int, media_time: float | None):
        history = self.histories.setdefault(source_id, deque(maxlen=self.history_frames))
        now = self.clock()
        source_rule_ids = {rule.id for rule in self.rules if rule.sourceId == source_id}
        sample = {"analyticsScope": self.scope_json(), "mediaTimeSeconds": media_time, "sourceTimeNs": str(ns), "timestamp": iso_ns(ns), "tracks": [self._track_json(track, now) for track in self.tracks.values() if track["sourceId"] == source_id], "source": self._source_json(self._site_sources()[source_id], now), "metrics": deepcopy([value for key, value in self.metrics.items() if key in source_rule_ids])}
        if source_id not in self.frame_contexts:
            self.frame_contexts[source_id] = {"generation": self.frame_generation, "siteId": self.site.id, "siteRevision": self.site.revision, "mode": self.site.mode, "rulesRevision": self.rules_revision, "rules": [rule.model_dump() for rule in self.rules if rule.sourceId == source_id]}
        # Context is immutable within a generation and shared by cached frames.
        sample.update(context=self.frame_contexts[source_id], receivedAt=now, sequence=str(self.sources[source_id]["lastSequence"]), engineSequence=str(self.sequence))
        sample["association"] = self._association_status()
        relevant_events = sorted((event for event in self.events.values() if event["sourceId"] == source_id and event["sessionId"] == self.sources[source_id]["sessionId"] and event.get("analyticsScope", {}).get("epoch") == self.analytics_scope["epoch"]), key=lambda event: int(event["triggeredAtNs"]), reverse=True)[:100]
        sample["events"] = deepcopy([{key: value for key, value in event.items() if key != "stateHistory"} for event in relevant_events])
        history.append(sample)
        if media_time is not None and self.site.mode in {"recorded-inference", "fixture-replay"}:
            self.store.save_history(source_id, self.sources[source_id]["sessionId"], sample)

    def _refresh_freshness(self, now):
        self._prune(now)
        for config in self.site.sources:
            state = self.sources.get(config.id)
            if state and now - state["received"] > self.freshness:
                self._unknown_events("source-stale", config.id)
                for rule in self.rules:
                    if rule.sourceId == config.id and rule.id in self.metrics:
                        self.metrics[rule.id].update(status="unknown", activeEventCount=0, evidenceReasons=["source-stale"])

    def health_state(self):
        """Maintain loss/expiry semantics without copying every track and event."""
        with self.lock:
            now = self.clock()
            self._refresh_freshness(now)
            sources = []
            for config in self.site.sources:
                source = self.sources.get(config.id)
                status = "awaiting-observations" if source is None else ("stale" if now - source["received"] > self.freshness else "live")
                sources.append({"id": config.id, "status": status})
            return {"mode": self.site.mode, "siteId": self.site.id, "setupRequired": not self.site.sources, "awaitingObservations": bool(self.site.sources) and not self.sources, "sources": sources, "association": self._association_status()}

    def snapshot(self, source_id: str | None = None, media_time: float | None = None, maximum_skew: float = 0.25, source_time_ns: int | None = None):
        with self.lock:
            now = self.clock()
            self._refresh_freshness(now)
            sources = [self._source_json(source, now) for source in self.site.sources if source_id is None or source.id == source_id]
            historical = media_time is not None or source_time_ns is not None
            # An aligned request uses its saved frame, not a throwaway deep copy
            # of the current tracks and their trails.
            tracks = [] if historical else [self._track_json(track, now) for track in self.tracks.values() if source_id is None or track["sourceId"] == source_id]
            metrics = [] if historical else deepcopy(list(self.metrics.values()))
            aligned = None
            historical_clocks = {}
            historical_scopes = {}
            if historical:
                tracks, aligned, metrics = [], True, []
                for source in sources:
                    current_session = self.sources.get(source["id"], {}).get("sessionId")
                    if source_time_ns is not None:
                        history = self.histories.get(source["id"], ())
                        nearest = min(history, key=lambda sample: abs(int(sample["sourceTimeNs"]) - source_time_ns), default=None)
                        if nearest and nearest["source"].get("timestampBasis") not in LIVE_SOURCE_CLOCK_BASES:
                            source["clockAlignmentReason"] = "source-capture-clock-required"
                            nearest = None
                    elif self.site.mode in {"recorded-inference", "fixture-replay"}:
                        nearest = self.store.nearest_history(source["id"], media_time, current_session)
                        if nearest and self.site.mode == "recorded-inference" and nearest["source"].get("mediaTimeBasis") != "gstreamer-segment-stream-time":
                            source["clockAlignmentReason"] = "verified-media-clock-required"
                            nearest = None
                    else:
                        media_history = (sample for sample in self.histories.get(source["id"], ()) if sample["mediaTimeSeconds"] is not None)
                        nearest = min(media_history, key=lambda sample: abs(sample["mediaTimeSeconds"] - media_time), default=None)
                    skew = (abs(int(nearest["sourceTimeNs"]) - source_time_ns) / 1e9 if source_time_ns is not None else abs(nearest["mediaTimeSeconds"] - media_time)) if nearest else None
                    source.update(clockAligned=skew is not None and skew <= maximum_skew, alignmentSkewSeconds=skew)
                    if nearest and skew is not None and skew <= maximum_skew:
                        historical_scopes[source["id"]] = deepcopy(nearest.get("analyticsScope"))
                        source["analyticsScope"] = deepcopy(nearest.get("analyticsScope"))
                        source["trackingEpoch"] = nearest["source"].get("trackingEpoch")
                        tracks.extend(deepcopy(nearest["tracks"]))
                        metrics.extend(deepcopy(nearest["metrics"]))
                        source.update(currentStatus=source["status"], currentLastSourceTimeNs=source.get("lastSourceTimeNs"), mediaTimeSeconds=nearest["mediaTimeSeconds"], status="replay" if source_time_ns is None else source["status"], lastSourceTimeNs=nearest["source"]["lastSourceTimeNs"], sessionId=nearest["source"]["sessionId"], timestampBasis=nearest["source"].get("timestampBasis"), mediaTimeBasis=nearest["source"].get("mediaTimeBasis"), rawSourcePtsNs=nearest["source"].get("rawSourcePtsNs"))
                        historical_clocks[source["id"]] = (int(nearest["source"]["lastSourceTimeNs"]), nearest["source"]["sessionId"])
                        source.update(currentModelRevision=source.get("modelRevision"), modelRevision=nearest["source"].get("modelRevision"), sourceClockProgressRatio=nearest["source"].get("sourceClockProgressRatio"))
                        source.update(sourceClockMode=nearest["source"].get("sourceClockMode"), sourceClockEvidence=deepcopy(nearest["source"].get("sourceClockEvidence")))
                        basis = nearest["source"].get("timestampBasis")
                        source["sourceClockAgeSeconds"] = time.time() - int(nearest["sourceTimeNs"]) / 1e9 if self.site.mode == "live" and basis in LIVE_SOURCE_CLOCK_BASES else None
                        selected_age, selected_ratio = source["sourceClockAgeSeconds"], source.get("sourceClockProgressRatio")
                        selected_delayed = selected_age is not None and (abs(selected_age) > 5 or (selected_ratio is not None and selected_ratio < 0.9))
                        source["sourceClockStatus"] = "delayed-or-unsynchronized" if selected_delayed else (f"unverified-{basis}" if selected_age is not None else "unavailable")
                    else:
                        aligned = False
            configured_source_ids = {source.id for source in self.site.sources}
            events = [] if historical else sorted((event for event in self.events.values() if event["sourceId"] in configured_source_ids and (source_id is None or event["sourceId"] == source_id)), key=lambda event: int(event["triggeredAtNs"]), reverse=True)[:100]
            if historical:
                events = []
                for saved_event in self.store.events(1000, site_id=self.site.id, source_id=source_id):
                    at = historical_clocks.get(saved_event["sourceId"])
                    if at is None or saved_event["sessionId"] != at[1] or int(saved_event["triggeredAtNs"]) > at[0]:
                        continue
                    event = deepcopy(saved_event)
                    event["metrics"] = deepcopy(event.get("triggerMetrics", event["metrics"]))
                    # Latest observations must not leak future measurements into replay.
                    event.pop("latestMetrics", None)
                    event.pop("stopEvidenceAtNs", None)
                    history = event.get("stateHistory", [])
                    selected = next((transition for transition in reversed(history) if int(transition["atNs"]) <= at[0]), None)
                    if selected is not None:
                        event.update(state=selected["state"], stateReason=selected["reason"], updatedAtNs=selected["atNs"], unknownAtNs=selected["atNs"] if selected["state"] == "unknown" else None, historicalStateStatus="recorded-transition")
                    elif not history and at[0] >= int(event.get("updatedAtNs", event["triggeredAtNs"])):
                        # Legacy records prove only their last saved boundary.
                        event["historicalStateStatus"] = "legacy-last-boundary"
                    else:
                        reason = "state-history-truncated" if history else "state-history-unavailable"
                        event.update(state="unknown", stateReason=reason, updatedAtNs=None, unknownAtNs=None, historicalStateStatus=reason)
                    # A historical frame must not disclose later state changes.
                    event["stateHistory"] = [transition for transition in history if int(transition["atNs"]) <= at[0]]
                    event["stateHistoryStartsAtNs"] = event["stateHistory"][0]["atNs"] if event["stateHistory"] else None
                    if event.get("kind") == "stopped-in-zone":
                        event["stopEvidenceStatus"] = ({STOP_PENDING_REASON: "pending", STOP_CLEARING_REASON: "clearing"}
                            .get(event.get("stateReason"), "confirmed" if event["state"] == "active" else event["state"]))
                    if event["state"] != "cleared":
                        event.update(endedAt=None, endedAtNs=None)
                        if "durationMs" in event["metrics"]:
                            continuous = event["state"] == "active" and event.get("stateHistoryComplete", False) and not any(
                                transition["state"] == "unknown" or transition.get("reason") in {STOP_PENDING_REASON, STOP_CLEARING_REASON}
                                for transition in event["stateHistory"])
                            # An elapsed incident age is not an observed dwell
                            # duration when history contains a blind interval.
                            event["metrics"]["durationMs"] = max(0, (at[0] - int(event["startedAtNs"])) / 1e6) if continuous else None
                            event["durationStatus"] = "continuous-observation" if continuous else "unavailable-observation-gap"
                    events.append(event)
                    if len(events) == 100:
                        break
            if source_id is not None:
                events = [event for event in events if event["sourceId"] == source_id]
            metric_index = {metric["ruleId"]: metric for metric in metrics}
            selected_scope = (next(iter(historical_scopes.values())) if len(historical_scopes) == 1 else {"kind": "historical-per-camera", "sources": historical_scopes}) if historical else self.scope_json()
            return {"analyticsScope": selected_scope, "siteId": self.site.id, "siteRevision": self.site.revision, "mode": self.site.mode, "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "sequence": str(self.sequence), "rulesRevision": self.rules_revision, "sources": sources, "tracks": tracks, "zones": [{"id": rule.id, "name": rule.name, "sourceId": rule.sourceId, "kind": rule.kind, "geometry": rule.geometry.model_dump(), "enabled": rule.enabled, "active": metric_index.get(rule.id, {}).get("status") == "active", "occupancy": metric_index.get(rule.id, {}).get("occupancy")} for rule in self.rules if rule.kind != "line-crossing"], "rules": self.rules_json()["rules"], "events": deepcopy(events), "metrics": metrics, "setupRequired": not self.site.sources, "awaitingObservations": bool(self.site.sources) and not self.sources, "clockAligned": aligned, "mediaTimeSeconds": media_time, "sourceTimeNs": str(source_time_ns) if source_time_ns is not None else None, "association": self._association_status()}
