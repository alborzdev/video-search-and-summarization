# SPDX-License-Identifier: Apache-2.0
"""Prepared-scene gate: source clocks stay live; operational evidence starts fresh.

This controller accepts no actor positions/IDs. Native reset confirmation and
settling come from image observations, never the simulator's success response.
"""
from copy import deepcopy
import json
import os
import re
import tempfile
import time
import uuid

from .engine import ConflictError


class ScenarioBoundary:
    SETTLE_SECONDS = 1.0
    MINIMUM_FRAMES = 3
    DEADLINE_SECONDS = 20.0

    def __init__(self, engine, directory, wall_ns=time.time_ns):
        self.engine, self.directory, self.wall_ns = engine, directory, wall_ns
        self.key = f"scenario-boundary:{engine.site.id}"
        self.state = engine.store.get(self.key, {"state": "normal", "runId": None})
        self.samples = {}
        self.deadline = None
        if self.state.get("state") != "normal":
            self.state.update(state="failed", error="gateway-restarted-during-scenario; settle before resuming")
            engine.reset_analytics_scope(kind="recovery", run_id=self.state.get("runId"), suppressed=True)
        engine.required_tracking_epoch = self.state.get("trackingEpoch")
        engine.boundary_observer = self.observe

    def _save(self):
        self.engine.store.set(self.key, self.state)

    def _native_ack(self):
        if self.directory is None:
            return None
        try:
            with (self.directory / "scenario-boundary-ack.json").open("rb") as stream:
                data = stream.read(16385)
            if len(data) > 16384:
                return None
            ack = json.loads(data)
            if ack.get("trackingEpoch") != self.state.get("trackingEpoch"):
                return None
            return ack
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _write_reset(self, epoch, floor):
        if self.directory is None:
            raise ValueError("native scenario reset is not connected")
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".scenario-boundary-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(f"[scenario-boundary]\nepoch={epoch}\nafter-capture-ns={floor}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.directory / "scenario-boundary.ini")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def observe(self, observation):
        # Called under the engine ingestion lock, after all existing clock checks.
        if self.state["state"] not in {"settling", "ready"} or observation.trackingEpoch != self.state.get("trackingEpoch"):
            return
        ns = int(observation.sourceTimeNs)
        if ns < int(self.state["afterCaptureNs"]):
            return
        current = self.samples.get(observation.sourceId)
        if current is None or current["sessionId"] != observation.sourceSessionId:
            current = {"firstNs": ns, "frames": 0, "sessionId": observation.sourceSessionId}
            self.samples[observation.sourceId] = current
        current.update(lastNs=ns, frames=current["frames"] + 1, received=self.engine.clock())
        self._refresh()

    def _qualified(self, ack, now):
        sources = set(self.engine._site_sources())
        stages_match = bool(ack and ack.get("trackerStages") in (1, 2))
        if stages_match and self.engine._map_demo_approved():
            # Match the reset to the architecture of every current camera.
            # Native MV3DT uses one tracker; the staged NvDCF/MV3DT path uses two.
            architectures = {self.engine.sources.get(source, {}).get("trackingArchitecture") for source in sources}
            stages_match = any(architectures == {architecture} and ack["trackerStages"] == stages
                for architecture, stages in (("mv3dt-native-v1", 1), ("nvdcf-local-then-mv3dt-v1", 2)))
        return bool(sources and ack and ack.get("status") == "applied"
            and set(ack.get("sourceIds", [])) == sources and set(self.samples) == sources
            and ack.get("trackingEpoch") == self.state.get("trackingEpoch")
            and stages_match
            and all(self.samples[source]["frames"] >= self.MINIMUM_FRAMES
                and self.samples[source]["lastNs"] - self.samples[source]["firstNs"] >= self.SETTLE_SECONDS * 1e9
                and now - self.samples[source]["received"] <= self.engine.freshness
                and self.samples[source]["sessionId"] == self.engine.sources.get(source, {}).get("declaredSession")
                and self.engine.sources.get(source, {}).get("trackingEpoch") == self.state.get("trackingEpoch")
                for source in sources))

    def _refresh(self):
        if self.state["state"] not in {"settling", "ready"}:
            return
        now = self.engine.clock()
        ack = self._native_ack()
        if ack and ack.get("status") == "error":
            self.state.update(state="failed", error=ack.get("error", "native-reset-failed"))
            self._save()
        elif self.state["state"] == "ready":
            if not self._qualified(ack, now):
                self.state.update(state="failed", error="ready-camera-continuity-lost-or-stale; recover and settle again")
                self._save()
        elif self.deadline is not None and now >= self.deadline:
            self.state.update(state="failed", error="post-reset-camera-settling-timeout")
            self._save()
        elif self._qualified(ack, now):
            self.state.update(state="ready", readyAtNs=str(self.wall_ns()), nativeReset=ack)
            self._save()

    def status(self):
        with self.engine.lock:
            self._refresh()
            return {**deepcopy(self.state), "analyticsScope": self.engine.scope_json(),
                "settling": {key: {"frames": value["frames"], "observedSeconds": (value["lastNs"] - value["firstNs"]) / 1e9}
                    for key, value in self.samples.items()},
                "settleMinimumSeconds": self.SETTLE_SECONDS,
                "deadlineSeconds": self.DEADLINE_SECONDS,
                "historyScope": "Prior events retain their original scope; archived scope summaries are retained separately."}

    def command(self, payload):
        action, run_id = payload.get("action"), payload.get("runId")
        if action not in {"prepare", "recover", "settle", "play", "normal"}:
            raise ValueError("action must be prepare, recover, settle, play or normal")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", run_id):
            raise ValueError("runId must be a bounded opaque identifier")
        scenario_id = payload.get("scenarioId")
        if scenario_id is not None and (not isinstance(scenario_id, str) or len(scenario_id) > 100):
            raise ValueError("scenarioId must be a bounded string")
        with self.engine.lock:
            self._refresh()
            current = self.state["state"]
            if action == "prepare":
                if not self.engine._site_sources():
                    raise ConflictError("configured cameras are required before preparation")
                if current != "normal":
                    if run_id == self.state.get("runId"):
                        return self.status()
                    raise ConflictError("another scenario boundary is active")
                if run_id == self.state.get("completedRunId"):
                    raise ConflictError("runId has already completed; use a new runId")
                self.state = {"state": "preparing", "runId": run_id, "scenarioId": scenario_id,
                    "preparedAtNs": str(self.wall_ns()), "trackingEpoch": self.engine.required_tracking_epoch}
                # Persist fail-closed intent before returning authorization to teleport.
                self._save()
                self.engine.reset_analytics_scope(kind="preparing", run_id=run_id, scenario_id=scenario_id, suppressed=True)
            elif run_id != self.state.get("runId"):
                if action == "normal" and current == "normal" and run_id == self.state.get("completedRunId"):
                    return self.status()
                raise ConflictError("runId does not own the active boundary")
            elif action == "recover":
                if current == "recovering":
                    return self.status()
                self.state.update(state="recovering", recoveryAtNs=str(self.wall_ns()))
                self._save()
                self.engine.reset_analytics_scope(kind="recovering", run_id=run_id,
                    scenario_id=self.state.get("scenarioId"), suppressed=True)
            elif action == "settle":
                if current in {"settling", "ready"}:
                    return self.status()
                epoch, floor = str(uuid.uuid4()), self.wall_ns()
                self.engine.analytics_suppressed = True
                self.engine.required_tracking_epoch = epoch
                self.engine.reset_analytics_scope(kind="settling", run_id=run_id,
                    scenario_id=self.state.get("scenarioId"), suppressed=True, capture_floor_ns=floor)
                self.state.update(state="settling", trackingEpoch=epoch, afterCaptureNs=str(floor), error=None)
                self.samples.clear()
                self.deadline = self.engine.clock() + self.DEADLINE_SECONDS
                self._save()
                try:
                    self._write_reset(epoch, floor)
                except Exception as exc:
                    self.state.update(state="failed", error=f"native-reset-request-failed: {exc}")
                    self._save()
                    raise ValueError(self.state["error"]) from exc
            elif action == "play":
                if current == "running":
                    return self.status()
                if current != "ready":
                    raise ConflictError("post-reset camera settling must be ready before Play: " + str(self.state.get("error") or current))
                if not self._qualified(self._native_ack(), self.engine.clock()):
                    raise ConflictError("camera continuity changed after settling")
                self.engine.reset_analytics_scope(kind="scenario", run_id=run_id,
                    scenario_id=self.state.get("scenarioId"), capture_floor_ns=self.wall_ns())
                self.state.update(state="running", playedAtNs=str(self.wall_ns()))
            elif action == "normal":
                if current not in {"ready", "running"}:
                    raise ConflictError("failed/cancelled preparation requires settle before normal analytics")
                self.engine.reset_analytics_scope(kind="normal", capture_floor_ns=self.wall_ns())
                self.state = {"state": "normal", "runId": None, "completedRunId": run_id,
                    "trackingEpoch": self.engine.required_tracking_epoch, "restoredAtNs": str(self.wall_ns())}
            self._save()
            return self.status()
