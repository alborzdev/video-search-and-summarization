# SPDX-License-Identifier: Apache-2.0
"""Own the prepare/track/Play transaction without stopping the city or cameras.

The host supervisor advances this state even when every browser is closed.
Native scene receipts and image-derived analytics stay separate. All network
operations are bounded, and a lost response never authorizes another actor jump.
"""
from __future__ import annotations

import json
import re
import runpy
import time
import urllib.request
import uuid
from pathlib import Path
from threading import RLock


class DemoControl:
    STAGE_SECONDS = 45.0
    SETTLE_SECONDS = 25.0
    READY_SECONDS = 180.0
    CLEANUP_SECONDS = 30.0
    RUN_SECONDS = 120.0
    TERMINAL = {"completed", "cancelled", "failed", "idle"}

    def __init__(self, repo: Path | None = None, *,
                 gateway: str = "http://127.0.0.1:9184/api/v1/city",
                 state_path: Path | None = None, clock=time.time, recover_analysis=None):
        self.repo = Path(repo) if repo is not None else runpy.run_path(
            str(Path(__file__).with_name("isaac_workspace.py")))["runtime_root"]()
        self.gateway, self.clock = gateway.rstrip("/"), clock
        self.state_path = state_path
        self.recover_analysis = recover_analysis
        self.lock = RLock()
        self.transaction = None
        self.requests = {}
        if state_path is not None and state_path.exists():
            saved = json.loads(state_path.read_text())
            self.transaction = saved.get("transaction")
            self.requests = saved.get("requests", {})

    def _save(self):
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"transaction": self.transaction, "requests": self.requests}, indent=2) + "\n")
        temporary.replace(self.state_path)

    def _json(self, url, payload=None, *, headers=None, timeout=3):
        request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def _bridge(self, operation="status", *, scenario_id=None, run_id=None, boundary_id=None, request_id=None, expires_at=None):
        payload = {"action": "demo", "operation": operation}
        if operation != "status":
            payload.update(scenarioId=scenario_id, runId=run_id, boundaryToken=boundary_id,
                           requestId=request_id or uuid.uuid4().hex, expiresAt=expires_at if expires_at is not None else self.clock() + 3)
        token = (self.repo / "logs/vss-integration/bridge-token").read_text().strip()
        result = self._json("http://127.0.0.1:8766/control", payload,
                            headers={"X-City-Token": token})
        if result.get("ok") is not True:
            raise RuntimeError(str(result.get("error", "Simulator refused the operation")).splitlines()[-1][:240])
        data = result.get("data", {})
        if data.get("schemaVersion") != "city.tradeshow-control.v1":
            raise RuntimeError("City bridge does not support scenario controls")
        return data

    def _boundary(self, action=None):
        transaction = self.transaction
        payload = None if action is None else {"action": action, "runId": transaction["boundaryId"],
                                               "scenarioId": transaction["scenarioId"]}
        result = self._json(self.gateway + "/scenario-boundary", payload)
        if transaction is not None:
            transaction["boundary"] = result
        return result

    def _phase(self, phase):
        # Retried transport work must not extend a finite cleanup deadline.
        if self.transaction["phase"] != phase:
            self.transaction.update(phase=phase, phaseStartedAt=self.clock())
        self._save()

    def _owns(self, scene):
        tx = self.transaction
        return (isinstance(scene.get("runId"), str) and bool(scene["runId"])
                and scene.get("boundaryToken") == tx["boundaryId"]
                and scene.get("scenarioId") == tx["scenarioId"]
                and (tx.get("nativeRunId") is None or scene["runId"] == tx["nativeRunId"]))

    def _observe(self, data):
        scene, tx = data.get("scenario", {}), self.transaction
        if self._owns(scene):
            tx["nativeRunId"] = scene["runId"]
            tx["native"] = data
            self._save()
            return True
        return False

    def _retired_restoration(self, data, *, include_closed=False):
        """Retain an owned release receipt across replacement of an idle controller.

        This does not adopt the new controller or measure new motion. Cleanup
        may only finish the camera boundary after the old owner already proved
        release and normal flow, and the fresh controller claims no ownership.
        """
        tx = self.transaction
        if not tx or not tx.get("nativeRunId"):
            return None
        if tx["phase"] not in {"cleanup", "cleanup-settling", "recovery-failed"}:
            if not (include_closed and tx["phase"] == "closed" and tx.get("nativeRestorationReceiptRetained")):
                return None
        current = data.get("scenario", {})
        if not (current.get("state") == "idle" and current.get("active") is False
                and current.get("restored") is True and current.get("runId") is None
                and current.get("scenarioId") is None and current.get("boundaryToken") is None):
            return None
        receipt = tx.get("native", {}).get("scenario", {})
        if (self._owns(receipt) and receipt.get("state") in self.TERMINAL - {"idle"}
                and receipt.get("active") is False and receipt.get("restored") is True
                and receipt.get("normalFlowVerified") is True):
            return receipt
        return None

    def _ensure_gate(self):
        tx = self.transaction
        if not tx.get("boundaryAcquired"):
            boundary = self._boundary("prepare")
            if boundary.get("runId") != tx["boundaryId"]:
                raise RuntimeError("The analytics gate did not confirm this preparation owner")
            tx["boundaryAcquired"] = True
            self._save()

    def _begin_native(self, data):
        tx = self.transaction
        scene = data.get("scenario", {})
        if self._observe(data):
            self._phase("staging")
            return data
        if scene.get("active") or scene.get("runId") != tx.get("priorNativeRunId"):
            raise RuntimeError("Scene ownership changed before preparation")
        self._ensure_gate()
        if tx.get("nativePrepareIssued"):
            # Never resend a jump when its first response is unknown. Status
            # adopts only the same token; bridge expiry bounds queued commands.
            self._phase("staging")
            return data
        self._phase("staging")
        tx.update(nativePrepareIssued=True, nativePrepareExpiresAt=self.clock() + 3)
        self._save()  # Durable send intent precedes the native mutation.
        result = self._bridge("prepare", scenario_id=tx["scenarioId"], boundary_id=tx["boundaryId"],
                              request_id=tx["prepareRequestId"], expires_at=tx["nativePrepareExpiresAt"])
        if not self._observe(result):
            raise RuntimeError("Native preparation did not confirm its boundary owner")
        return result

    def _no_native_run(self, data):
        """Fresh status after command expiry proves an unknown send never took ownership."""
        tx, scene = self.transaction, data.get("scenario", {})
        if tx.get("nativeRunId") or self._owns(scene):
            return False
        if tx.get("nativePrepareIssued") and self.clock() <= tx.get("nativePrepareExpiresAt", tx["startedAt"] + 3) + 1:
            return False
        safe = (scene.get("runId") == tx.get("priorNativeRunId") and not scene.get("active")
                and scene.get("restored") is True and (scene.get("normalFlowVerified") is True or scene.get("state") == "idle"))
        if safe:
            tx["nativeAbsenceVerified"] = True
            self._save()
        return safe

    def _cancel(self, reason, *, failed=False, data=None):
        tx = self.transaction
        tx.update(reason=reason, outcome="failed" if failed else "cancelled")
        self._phase("cleanup")
        self._ensure_gate()
        self._boundary("recover")
        data = self._bridge() if data is None else data
        self._observe(data)
        if tx.get("nativeRunId") and self._owns(data.get("scenario", {})):
            data = self._bridge("cancel", run_id=tx["nativeRunId"], boundary_id=tx["boundaryId"],
                                request_id=tx.setdefault("cancelRequestId", uuid.uuid4().hex))
            self._observe(data)
        self._save()
        return data

    def _native_capture_error(self):
        if self.recover_analysis is None:
            return None
        health = self._json(self.gateway + "/health")
        native = health.get("nativeAnalyticsStatus", {})
        error = native.get("error") or ""
        return error if (native.get("status") == "error" and native.get("sourceClockMode") == "source-native-sei"
                         and error.startswith("native-capture-clock-rejected:")) else None

    def _renew_failed_capture(self):
        """One fresh worker during gated preparation/recovery, never during Play.

        A malformed capture still terminates its worker. Renewal changes source
        sessions and requires the full two-camera settling proof again; no bad
        frame or old identity can enter the new scenario scope.
        """
        tx = self.transaction
        if self.recover_analysis is None or tx.get("captureRenewalAttempted"):
            return False
        error = self._native_capture_error()
        if not error:
            return False
        # Durable intent bounds this even if process start succeeds but its
        # response is lost. Paused/unregistered sources are refused by callback.
        tx.update(captureRenewalAttempted=True, captureRenewalReason=error[:500])
        self._save()
        if self.recover_analysis() is not True:
            return False
        self._boundary("recover")
        self._boundary("settle")
        tx.update(phaseStartedAt=self.clock(), captureRenewalStartedAt=self.clock())
        self._save()
        return True

    def _advance(self, data):
        tx = self.transaction
        if not tx or tx["phase"] in {"closed", "recovery-failed"}:
            return data
        scene = data.get("scenario", {})
        owned = self._observe(data)
        retired = None if owned else self._retired_restoration(data)
        if retired is not None:
            # Keep tx.native byte-for-byte as the historical owned receipt.
            # Never send its run identity to the replacement controller.
            scene = retired
            tx["nativeRestorationReceiptRetained"] = True
            self._save()
        if tx.get("nativeRunId") and not owned and retired is None:
            self._boundary("recover")
            tx["reason"] = "Scene ownership changed; recovery needs attention"
            self._phase("recovery-failed")
            return data
        elapsed = self.clock() - tx["phaseStartedAt"]
        phase = tx["phase"]
        if owned and scene.get("state") == "recovery-failed":
            self._boundary("recover")
            tx["reason"] = scene.get("reason") or "Native actor cleanup failed"
            self._phase("recovery-failed")
        elif phase == "gating":
            if elapsed > self.STAGE_SECONDS:
                return self._cancel("Analytics preparation exceeded its finite deadline", failed=True, data=data)
            return self._begin_native(data)
        elif phase == "staging":
            if owned and scene.get("state") == "ready":
                self._boundary("settle")
                self._phase("settling")
            elif owned and scene.get("state") in self.TERMINAL and scene.get("restored") is True and scene.get("normalFlowVerified") is True:
                tx.update(outcome=scene.get("state"), reason=scene.get("reason", "Preparation failed"))
                self._boundary("settle")
                self._phase("cleanup-settling")
            elif not owned and self._no_native_run(data):
                return self._cancel("Native preparation was not accepted before its command expired", failed=True, data=data)
            elif elapsed > self.STAGE_SECONDS:
                return self._cancel("Preparation exceeded its finite deadline", failed=True, data=data)
        elif phase in {"settling", "cleanup-settling"}:
            if phase == "settling" and (not owned or scene.get("state") != "ready"):
                return self._cancel("Prepared scene stopped while camera tracking settled", failed=True, data=data)
            boundary = self._boundary()
            if boundary.get("state") == "ready":
                if phase == "cleanup-settling":
                    self._boundary("normal")
                    self._phase("closed")
                else:
                    self._phase("ready")
            elif boundary.get("state") == "failed" or elapsed > self.SETTLE_SECONDS:
                if self._renew_failed_capture():
                    return data
                if phase == "settling":
                    return self._cancel(boundary.get("error") or "Fresh tracker observations were not ready", failed=True, data=data)
                tx["reason"] = boundary.get("error") or "Analytics recovery exceeded its finite deadline"
                self._phase("recovery-failed")
        elif phase == "ready":
            if not owned or scene.get("state") != "ready":
                return self._cancel(scene.get("reason") or "Prepared scene is no longer ready", failed=True, data=data)
            boundary = self._boundary()
            if boundary.get("state") != "ready":
                return self._cancel(boundary.get("error") or "Prepared camera tracking stopped", failed=True, data=data)
            if elapsed > self.READY_SECONDS:
                return self._cancel("Prepared scene expired; normal traffic restored", data=data)
        elif phase == "running":
            if self._native_capture_error():
                return self._cancel("camera-capture-clock-rejected", failed=True, data=data)
            if owned and scene.get("state") in self.TERMINAL and scene.get("restored") is True and scene.get("normalFlowVerified") is True:
                tx.update(outcome=scene["state"], reason=scene.get("reason", ""))
                self._boundary("normal")
                self._phase("closed")
            elif elapsed > self.RUN_SECONDS:
                return self._cancel("Native presentation exceeded its finite deadline", failed=True, data=data)
        elif phase == "cleanup":
            self._ensure_gate()
            self._boundary("recover")
            if ((owned or retired is not None) and scene.get("restored") is True and scene.get("normalFlowVerified") is True and not scene.get("active")) or self._no_native_run(data):
                self._boundary("settle")
                self._phase("cleanup-settling")
            elif elapsed > self.CLEANUP_SECONDS:
                tx["reason"] = "Actor recovery exceeded its finite deadline"
                self._phase("recovery-failed")
            elif owned:
                data = self._bridge("cancel", run_id=tx["nativeRunId"], boundary_id=tx["boundaryId"],
                                    request_id=tx.setdefault("cancelRequestId", uuid.uuid4().hex))
                self._observe(data)
        return data

    def poll(self):
        """Called by the host supervisor, independent of UI requests."""
        with self.lock:
            tx = self.transaction
            if not tx or tx["phase"] in {"closed", "recovery-failed"}:
                return
            try:
                self._advance(self._bridge())
                if tx.pop("connectionError", None):
                    self._save()
            except (OSError, ValueError, RuntimeError) as exc:
                tx["connectionError"] = str(exc)[:240]
                # Native owns its own finite expiry. Keep analytics gated when
                # transport is lost; never infer restoration from a timeout.
                if self.clock() - tx["phaseStartedAt"] > (self.CLEANUP_SECONDS if tx["phase"] == "cleanup" else self.STAGE_SECONDS):
                    if tx["phase"] in {"cleanup", "cleanup-settling"}:
                        tx["reason"] = "Control connection failed during cleanup: " + str(exc)[:160]
                        self._phase("recovery-failed")
                    else:
                        try:
                            self._cancel("Control connection failed: " + str(exc)[:160], failed=True)
                        except (OSError, ValueError, RuntimeError):
                            self._phase("recovery-failed")
                self._save()

    def _decorate(self, data):
        data = json.loads(json.dumps(data))
        scene = data.setdefault("scenario", {})
        tx = self.transaction
        retired = self._retired_restoration(data, include_closed=True)
        if retired is not None:
            # Availability belongs to the current installation; only the old
            # run and its evidence are retained from the release receipt.
            scene.update({key: value for key, value in retired.items() if key != "catalog"})
            scene["nativeRestorationReceiptRetained"] = True
        native_released = bool(tx and self._owns(scene) and scene.get("restored") is True)
        if tx and (tx["phase"] != "closed" or scene.get("runId") == tx.get("nativeRunId") or
                   tx.get("nativeRunId") is None and scene.get("runId") == tx.get("priorNativeRunId")):
            scene.update(runId=tx.get("nativeRunId") or "host-" + tx["boundaryId"], scenarioId=tx["scenarioId"])
            title = next((item.get("title") for item in scene.get("catalog", []) if item.get("id") == tx["scenarioId"]), None)
            if title:
                scene["title"] = title
            boundary = tx.get("boundary", {})
            scene["analyticsBoundary"] = {
                "ready": tx["phase"] == "ready" and boundary.get("state") == "ready",
                "state": boundary.get("state", "unavailable"), "epoch": boundary.get("trackingEpoch"),
                "runId": tx["boundaryId"], "scope": boundary.get("analyticsScope"),
                "reason": tx.get("connectionError") or boundary.get("error") or "",
                "captureRenewalAttempted": bool(tx.get("captureRenewalAttempted")),
            }
            scene["timings"] = {**scene.get("timings", {}), "requestedAt": tx["startedAt"],
                                "hostPhase": tx["phase"]}
            if tx["phase"] in {"gating", "staging", "settling"}:
                native_phase = scene.get("phase") if tx["phase"] == "staging" and self._owns(scene) else None
                scene.update(state="preparing", active=True, phase="settling" if tx["phase"] == "settling" else native_phase or "staging", restored=False, normalFlowVerified=False)
            elif tx["phase"] in {"cleanup", "cleanup-settling"}:
                scene.update(state="recovering", active=True, phase="recovering", restored=native_released)
            elif tx["phase"] == "recovery-failed":
                scene.update(state="recovery-failed", active=False, phase="recovery-failed", restored=native_released,
                             reason=tx.get("reason") or tx.get("connectionError"))
            elif tx["phase"] == "closed" and tx.get("outcome"):
                scene.update(state=tx["outcome"], active=False, reason=tx.get("reason", ""), restored=True)
                if tx.get("nativeAbsenceVerified"):
                    scene.update(nativePreparationNotStarted=True, normalFlowUnchanged=True)
                    # This proves the original schedule was untouched, not a
                    # fresh displacement measurement from a native actor.
                    scene["normalFlowVerified"] = scene.get("normalFlowVerified") is True
        else:
            scene["analyticsBoundary"] = {"ready": False, "state": "normal"}
        return data

    def request(self, operation="status", *, scenario_id=None, run_id=None, request_id=None):
        if operation not in {"status", "prepare", "play", "cancel", "retry"}:
            raise ValueError("Unknown demo operation; prepare the scene before Play")
        if operation != "status":
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,80}", request_id):
                raise ValueError("Invalid demo request identity")
            if operation == "prepare" and (not isinstance(scenario_id, str) or not re.fullmatch(r"[a-z][a-z-]{1,79}", scenario_id)):
                raise ValueError("Select an available demo scenario")
        with self.lock:
            data = self._bridge()
            if operation == "status":
                return self._decorate(data)
            signature = [operation, scenario_id, run_id]
            if request_id in self.requests:
                if self.requests[request_id] != signature:
                    raise ValueError("Demo request identity was reused for another operation")
                return self._decorate(data)
            tx = self.transaction
            if operation == "prepare":
                if (tx and tx["phase"] != "closed") or data.get("scenario", {}).get("active") or data.get("scenario", {}).get("restored") is False:
                    raise ValueError("Finish the current scenario or its recovery first")
                catalog = data.get("scenario", {}).get("catalog", [])
                if not any(item.get("id") == scenario_id and item.get("available") for item in catalog):
                    raise ValueError("This scenario is unavailable")
                self.transaction = {"boundaryId": uuid.uuid4().hex, "scenarioId": scenario_id,
                                    "nativeRunId": None, "phase": "gating", "startedAt": self.clock(),
                                    "phaseStartedAt": self.clock(), "prepareRequestId": request_id,
                                    "priorNativeRunId": data.get("scenario", {}).get("runId"),
                                    "nativePrepareIssued": False, "boundaryAcquired": False}
                self.requests[request_id] = signature
                self._save()
                try:
                    data = self._begin_native(data)
                except (OSError, ValueError, RuntimeError) as exc:
                    self.transaction["connectionError"] = str(exc)[:240]
                    self._save()
                    raise
            else:
                if not tx or tx["phase"] == "closed":
                    raise ValueError("Prepare a scenario first")
                if run_id not in {tx.get("nativeRunId"), "host-" + tx["boundaryId"]} or not run_id:
                    raise ValueError("The selected scenario changed; refresh its status")
                if operation == "play":
                    boundary = self._boundary()
                    if tx["phase"] != "ready" or not self._owns(data["scenario"]) or data["scenario"].get("state") != "ready" or boundary.get("state") != "ready":
                        raise ValueError("Wait for the scene and fresh camera tracking to be ready")
                    self.requests[request_id] = signature
                    self._save()
                    self._boundary("play")
                    self._phase("running")
                    try:
                        data = self._bridge("play", run_id=tx["nativeRunId"], boundary_id=tx["boundaryId"], request_id=request_id)
                        tx["native"] = data
                        self._save()
                    except (OSError, ValueError, RuntimeError):
                        self._cancel("Play was not confirmed", failed=True)
                        raise
                elif operation == "cancel":
                    self.requests[request_id] = signature
                    self._save()
                    data = self._cancel("operator-cancel", data=data)
                else:
                    if tx["phase"] != "recovery-failed":
                        raise ValueError("Recovery retry is only for failed cleanup")
                    if self.recover_analysis is not None:
                        # Only an explicit, identity-checked retry may renew a
                        # failed detector. A paused source must stay paused.
                        self.recover_analysis()
                    self.requests[request_id] = signature
                    self._phase("cleanup")
                    self._ensure_gate()
                    self._boundary("recover")
                    self._observe(data)
                    if self._owns(data["scenario"]) and data["scenario"].get("state") == "recovery-failed":
                        data = self._bridge("retry", run_id=tx["nativeRunId"], boundary_id=tx["boundaryId"], request_id=request_id)
                    elif self._owns(data["scenario"]) and data["scenario"].get("active"):
                        data = self._bridge("cancel", run_id=tx["nativeRunId"], boundary_id=tx["boundaryId"], request_id=request_id)
            while len(self.requests) > 64:
                del self.requests[next(iter(self.requests))]
            self._save()
            return self._decorate(data)
