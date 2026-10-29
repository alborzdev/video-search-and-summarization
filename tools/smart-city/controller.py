#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Local host controller implementing the VSS RTVI-CV source lifecycle.

Run as the host user: python tools/smart-city/controller.py. Never mount the
Docker socket into the HTTP analytics container. This service binds loopback.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import re
import runpy
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.error import HTTPError
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote, unquote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ID = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
LOGGER = logging.getLogger(__name__)


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    scenarioId: str | None = None
    runId: str | None = None
    requestId: str = Field(min_length=16, max_length=80)


class DetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^(start|stop|restart)$")


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str = Field(pattern=r"^(start|stop)$")


@lru_cache(maxsize=4)
def _manage_module(root: Path):
    """Retain module-local artifact caches without caching readiness results."""
    spec = importlib.util.spec_from_file_location(
        "city_manage_guard", root / "tools/smart-city/manage.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Saved memory guard could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OPENCV_PROBE = """
import json, math, os, sys, time
live = sys.argv[2] == 'live'
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'protocol_whitelist;' + ('rtsp,rtsps,tcp,udp,rtp,crypto' if live else 'file,pipe')
if live: os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] += '|rtsp_transport;tcp'
import cv2
cv2.setNumThreads(1)
class LiveDecodeNotReady(ValueError): pass
for attempt in range(2 if live else 1):
    capture = cv2.VideoCapture(sys.argv[1], cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE])
    retry = False
    try:
        if not capture.isOpened():
            if live: raise LiveDecodeNotReady('Registered live source did not open')
            raise ValueError('Registered video did not open')
        if live:
            ok, first_frame = capture.read()
            if not ok or first_frame is None: raise LiveDecodeNotReady('Registered live source has no decodable frame')
        width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (0 < width <= 16384 and 0 < height <= 16384): raise ValueError('Invalid decoded image dimensions')
        if live and first_frame.shape[:2] != (height, width): raise ValueError('Live source dimensions differ from its decoded frame')
        result = {'width': width, 'height': height}
        if not live:
            fps, count = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if not (math.isfinite(fps) and math.isfinite(count) and fps > 0 and count > 0): raise ValueError('Recording duration is unavailable')
            result['durationSeconds'] = count / fps
        print(json.dumps(result))
        break
    except LiveDecodeNotReady:
        if attempt == 1: raise
        retry = True
    finally:
        capture.release()
    if retry: time.sleep(2)
"""


class SensorValue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    camera_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    camera_name: str = Field(default="Camera", max_length=256)
    camera_url: str = Field(default="", max_length=4096)
    change: str = "camera_add"


class SensorRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str = "sensor"
    value: SensorValue


@dataclass
class Settings:
    root: Path = ROOT
    device: str = "spark"
    gateway: str = "http://127.0.0.1:9184/api/v1/city"
    vss_origin: str = "http://127.0.0.1:30888"
    maximum_sources: int = 2
    maximum_frames: int = 18000

    @property
    def directory(self) -> Path:
        return self.root / f".{self.device}" / "city"


class HostRuntime:
    """Small OS boundary, replaceable by deterministic controller tests."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def json(
        self, path: str, payload: dict[str, Any] | None = None, method: str = "GET"
    ) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            path, data=body, headers={"Content-Type": "application/json"}, method=method
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    def command(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            arguments, capture_output=True, text=True, timeout=20, check=False
        )

    def readiness(self) -> tuple[bool, str]:
        image = self.command(
            [
                "docker",
                "image",
                "inspect",
                f"vss-city-perception:{self.settings.device}",
            ]
        )
        if image.returncode:
            return False, "Native DeepStream image or RF-DETR engine is not staged"
        try:
            module = _manage_module(self.settings.root)
            module.selected_city_model(self.settings.device)
            module.require_actual_device(self.settings.device)
            module.ensure_headroom(self.settings.device)
            self.json(self.settings.gateway + "/health")
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            return (
                False,
                f"Detections unavailable: {str(exc)[:200] or type(exc).__name__}",
            )
        return True, "Native image, engine, gateway and saved memory guard available"

    def inventory(self) -> list[dict[str, Any]]:
        result = self.json(
            self.settings.vss_origin.rstrip("/") + "/vst/api/v1/sensor/list"
        )
        if not isinstance(result, list):
            raise TypeError("VIOS inventory did not return a source list")
        return result

    def probe(self, path: Path | str) -> dict[str, Any]:
        live = str(path).startswith(("rtsp://", "rtsps://"))
        if shutil.which("ffprobe") is None:
            try:
                # Both live capture attempts share command()'s existing hard
                # 20-second limit; retries cannot exceed the Agent's 60s read
                # timeout. Only transient open/read readiness is retried.
                result = self.command(
                    [
                        sys.executable,
                        "-c",
                        OPENCV_PROBE,
                        str(path),
                        "live" if live else "recorded",
                    ]
                )
            except subprocess.TimeoutExpired:
                raise ValueError(
                    "Registered source CPU probe exceeded its bounded timeout"
                ) from None
            if result.returncode:
                raise ValueError("Registered source CPU decode probe failed")
            return json.loads(result.stdout)
        protocols = "file,rtsp,rtsps,tcp,udp,rtp,crypto" if live else "file,pipe"
        result = self.command(
            [
                "ffprobe",
                "-v",
                "error",
                "-rw_timeout",
                "5000000",
                "-read_intervals",
                "%+#1",
                "-protocol_whitelist",
                protocols,
                *(["-rtsp_transport", "tcp"] if live else []),
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
        if result.returncode:
            raise ValueError("Registered media could not be probed")
        probe = json.loads(result.stdout)
        stream = probe["streams"][0]
        result = {
            "width": int(stream["width"]),
            "height": int(stream["height"]),
        }
        duration = probe.get("format", {}).get("duration")
        if duration is not None and duration != "N/A":
            result["durationSeconds"] = float(duration)
        elif not live:
            raise ValueError("Recording lacks a finite playback duration")
        return result

    def download(self, url: str, path: Path) -> None:
        allowed_origin = urlparse(self.settings.vss_origin)

        # Agent's proxy translation uses these local Compose aliases. Resolve
        # them to the configured service, never to a caller-selected server.
        url = self.vss_storage_uri(url)

        def allowed(value: str) -> bool:
            parsed = urlparse(value)
            return (
                parsed.scheme in {"http", "https"}
                and parsed.hostname == allowed_origin.hostname
                and parsed.port == allowed_origin.port
                and not parsed.username
                and parsed.path.startswith("/vst/")
            )

        class Redirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if not allowed(newurl):
                    raise ValueError(
                        "VIOS export redirected outside its configured origin"
                    )
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        if not allowed(url):
            raise ValueError(
                "Media download must use the configured VIOS export origin"
            )
        if shutil.disk_usage(path.parent).free < 2 * 1024**3:
            raise ValueError("Need two GiB free before staging a bounded source export")
        temporary = path.with_suffix(".partial")
        try:
            opener = urllib.request.build_opener(Redirects())
            with (
                opener.open(url, timeout=60) as response,
                temporary.open("wb") as output,
            ):
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 1024**3:
                        raise ValueError(
                            "VIOS export exceeds the one-GiB source staging limit"
                        )
                    output.write(chunk)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def vss_storage_uri(self, value: str) -> str:
        parsed = urlparse(value)
        expected = urlparse(self.settings.vss_origin)
        aliases = {expected.hostname}
        if expected.hostname in {"127.0.0.1", "localhost", "172.17.0.1"}:
            aliases.update(
                {
                    "127.0.0.1",
                    "localhost",
                    "172.17.0.1",
                    "host.docker.internal",
                    "vst-ingress",
                }
            )
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in aliases
            or parsed.port != expected.port
            or parsed.username
            or parsed.password
            or not parsed.path.startswith("/vst/")
        ):
            raise ValueError(
                "Recording HTTP URI is outside the configured VIOS storage service"
            )
        return parsed._replace(scheme=expected.scheme, netloc=expected.netloc).geturl()

    def start(self, log: Path, *, live: bool = False):
        arguments = [
            sys.executable,
            str(self.settings.root / "tools/smart-city/manage.py"),
            "--device",
            self.settings.device,
            "analyze",
            "--frames",
            "0" if live else str(self.settings.maximum_frames),
        ]
        if live:
            arguments.append("--live")
        with log.open("a") as output:
            return subprocess.Popen(
                arguments,
                cwd=self.settings.root,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    def stop(self, process) -> None:
        # The fixed, application-owned detector name never comes from HTTP.
        stopped = self.command(["docker", "stop", "-t", "5", "vss-city-detector"])
        if stopped.returncode:
            actual = self.command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    "vss-city-detector",
                ]
            )
            missing = any(
                message in getattr(actual, "stderr", "").lower()
                for message in ("no such object", "no such container")
            )
            if (actual.returncode == 0 and actual.stdout.strip() != "false") or (
                actual.returncode and not missing
            ):
                raise RuntimeError("Detector stop was not confirmed")
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


class CityController:
    def __init__(self, settings: Settings, runtime: HostRuntime | None = None):
        self.settings, self.runtime = settings, runtime or HostRuntime(settings)
        self.lock = RLock()
        self.process = None
        self.settings.directory.mkdir(parents=True, exist_ok=True)
        self.detection_state_file = (
            self.settings.directory / "controller-detections.json"
        )
        self.detections_paused = (
            json.loads(self.detection_state_file.read_text()).get("paused") is True
            if self.detection_state_file.exists()
            else False
        )
        self.state_file = self.settings.directory / "controller-sources.json"
        self.sources = (
            json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        )
        self.calibration_file = self.settings.directory / "controller-calibrations.json"
        self.calibrations = (
            json.loads(self.calibration_file.read_text())
            if self.calibration_file.exists()
            else {}
        )
        self.rules_file = self.settings.directory / "controller-source-rules.json"
        self.source_rules = (
            json.loads(self.rules_file.read_text()) if self.rules_file.exists() else {}
        )

    def _save(self) -> None:
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.sources, indent=2) + "\n")
        temporary.replace(self.state_file)

    def readiness(self) -> tuple[bool, str]:
        # Startup and running checks use the operator's saved reserve.
        # No additional startup allowance (operator request, 2026-10-28).
        return self.runtime.readiness()

    def _wait_cold_readiness(self) -> None:
        deadline = time.monotonic() + 10
        while True:
            ready, reason = self.runtime.readiness()
            if ready:
                return
            if time.monotonic() >= deadline:
                raise HTTPException(
                    503,
                    f"Previous worker stopped, but the saved memory reserve or runtime is unavailable: {reason}",
                )
            time.sleep(0.25)

    def _resolve(self, value: SensorValue) -> dict[str, Any]:
        registered = next(
            (
                item
                for item in self.runtime.inventory()
                if item.get("sensorId") == value.camera_id
            ),
            None,
        )
        if registered is None:
            raise ValueError(
                "Source is not registered in the configured VIOS inventory"
            )
        parsed = urlparse(value.camera_url)
        directory = (self.settings.directory / "media").resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if registered.get("type") == "sensor_file":
            if parsed.scheme not in {"file", "http", "https", "rtsp", "rtsps"}:
                raise ValueError("Unsupported registered recording URI")
            filename = Path(str(registered.get("location", ""))).name
            if not filename or filename in {".", ".."}:
                raise ValueError("VIOS recording lacks a valid filename")
            path = (directory / filename).resolve()
            if not path.is_relative_to(directory) or path.is_symlink():
                raise ValueError(
                    "Recording path escapes the controlled media directory"
                )
            if parsed.scheme == "file":
                if parsed.netloc not in {"", "localhost"}:
                    raise ValueError(
                        "File URI must refer to the controlled local media directory"
                    )
                supplied = Path(unquote(parsed.path)).resolve()
                if supplied != path and str(parsed.path) != f"/media/{filename}":
                    raise ValueError(
                        "File URI is not this source's registered controlled media"
                    )
            elif parsed.scheme in {"http", "https"}:
                HostRuntime(self.settings).vss_storage_uri(value.camera_url)
            if not path.is_file():
                # Existing originals are preferred; otherwise export only the
                # registered source through the configured VIOS storage API.
                timelines = self.runtime.json(
                    self.settings.vss_origin + "/vst/api/v1/storage/timelines"
                )
                segments = timelines.get(value.camera_id, [])
                if len(segments) != 1:
                    raise ValueError(
                        "Recording must have one indexed retained segment before analysis"
                    )
                from urllib.parse import urlencode

                query = urlencode(
                    {
                        "startTime": segments[0]["startTime"],
                        "endTime": segments[0]["endTime"],
                        "container": "mp4",
                    }
                )
                export = self.runtime.json(
                    f"{self.settings.vss_origin}/vst/api/v1/storage/file/{value.camera_id}/url?{query}"
                )
                self.runtime.download(export["videoUrl"], path)
            return {
                "id": value.camera_id,
                "name": value.camera_name or registered.get("name", value.camera_id),
                "vssSensorId": value.camera_id,
                "mediaUrl": f"/api/vision/city/media/{value.camera_id}",
                "inputUri": f"file:///media/{filename}",
                "filename": filename,
                "kind": "recorded",
                **self.runtime.probe(path),
            }
        if parsed.scheme not in {"rtsp", "rtsps"}:
            raise ValueError("Live source must be a registered RTSP stream")
        registered_urls = {
            item
            for item in (registered.get("sensorUrl"), registered.get("location"))
            if isinstance(item, str) and item.startswith(("rtsp://", "rtsps://"))
        }
        try:
            streams = self.runtime.json(
                f"{self.settings.vss_origin}/vst/api/v1/sensor/{quote(value.camera_id, safe='')}/streams"
            )
        except HTTPError as exc:
            if exc.code != 404:
                raise
            # VIOS can list a persisted live sensor and its active stream in
            # the aggregate inventory while its per-sensor route returns 404
            # after restart. Keep the same registration/URL checks and accept
            # only the requested sensor's exact stream entry from that API.
            inventory = self.runtime.json(f"{self.settings.vss_origin}/vst/api/v1/sensor/streams")
            streams = [stream for group in inventory if isinstance(group, dict) and isinstance(group.get(value.camera_id), list)
                       for stream in group[value.camera_id] if isinstance(stream, dict)] if isinstance(inventory, list) else []
        if isinstance(streams, list):
            registered_urls.update(
                stream["url"]
                for stream in streams
                if isinstance(stream, dict)
                and stream.get("streamId") == value.camera_id
                and isinstance(stream.get("url"), str)
            )
        if value.camera_url not in registered_urls:
            raise ValueError("RTSP URI does not match the registered VIOS source")
        allowed_hosts = set(
            os.environ.get("CITY_RTSP_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
        )
        if parsed.hostname not in allowed_hosts:
            raise ValueError(
                "Registered RTSP host is not enabled in CITY_RTSP_ALLOWED_HOSTS"
            )
        return {
            "id": value.camera_id,
            "name": value.camera_name,
            "vssSensorId": value.camera_id,
            "inputUri": value.camera_url,
            "kind": "live",
            **self.runtime.probe(value.camera_url),
        }

    def _configure(self) -> None:
        site = self.runtime.json(self.settings.gateway + "/site")
        rules = self.runtime.json(self.settings.gateway + "/rules")
        previous = (
            {source["id"]: source for source in site.get("sources", [])}
            if site.get("mode") != "fixture-replay"
            else {}
        )
        # The gateway correctly rejects rules for absent cameras. Retain each
        # configured camera's rules during source-profile pause/remove so an
        # incremental add does not erase the second camera's saved setup.
        # Replace lists for cameras still present: intentional UI deletions win.
        for source_id in previous:
            self.source_rules[source_id] = [
                rule for rule in rules["rules"] if rule["sourceId"] == source_id
            ]
        temporary = self.rules_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.source_rules, indent=2) + "\n")
        temporary.replace(self.rules_file)
        for source_id, config in previous.items():
            # Null calibration is an operator revocation, not a missing update.
            # Replace the archive so re-adding an absent camera cannot resurrect
            # a transform, polygon or revision that the operator cleared.
            self.calibrations[source_id] = {
                key: config[key] for key in ("width", "height") if key in config
            }
            self.calibrations[source_id].update(
                imageToGroundHomography=config.get("imageToGroundHomography"),
                classImageToGroundHomographies=config.get("classImageToGroundHomographies", {}),
                validGroundPolygon=config.get("validGroundPolygon"),
                calibrationRevision=config.get("calibrationRevision"),
            )
            # Static extrinsics/coverage belong to the same calibration. Keep
            # them through incremental camera activation, and clear omitted or
            # revoked fields rather than reviving an old projection package.
            if config.get("calibrationRevision") and config.get("imageToGroundHomography"):
                self.calibrations[source_id].update({key: config[key] for key in (
                    "K", "T_cv_from_site", "projectionMatrix3x4", "classGroundPlaneWorldZM",
                    "groundCoverageM", "cameraPositionWorldM", "lensModel",
                    "maximumAlgebraicRoundtripErrorM", "validation"
                ) if key in config})
        temporary = self.calibration_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.calibrations, indent=2) + "\n")
        temporary.replace(self.calibration_file)
        sources = []
        for index, source in enumerate(self.sources.values()):
            merged = {
                **self.calibrations.get(source["id"], {}),
                **previous.get(source["id"], {}),
                **source,
                "deepstreamStreamIndex": index,
            }
            calibration = self.calibrations.get(source["id"], {})
            if any(
                key in calibration and calibration[key] != source.get(key)
                for key in ("width", "height")
            ):
                merged.update(
                    imageToGroundHomography=None,
                    classImageToGroundHomographies={},
                    calibrationRevision=None,
                    calibrationStatus="image-dimensions-changed",
                )
                for key in ("K", "T_cv_from_site", "projectionMatrix3x4", "classGroundPlaneWorldZM",
                            "groundCoverageM", "cameraPositionWorldM", "lensModel",
                            "maximumAlgebraicRoundtripErrorM", "validation", "validGroundPolygon"):
                    merged.pop(key, None)
            merged.pop("filename", None)
            sources.append(merged)
        if site.get("mode") == "fixture-replay":
            site = {
                "id": "vss-smart-city",
                "name": "Smart City",
                "revision": 1,
                "map": {"bounds": [-50, -50, 50, 50], "roads": [], "buildings": []},
            }
        else:
            site["revision"] = site.get("revision", 1) + 1
        site.update(
            sources=sources,
            mode="live"
            if any(source["kind"] == "live" for source in self.sources.values())
            else "recorded-inference",
        )
        self.runtime.json(self.settings.gateway + "/site", site, "PUT")
        current_rules = self.runtime.json(self.settings.gateway + "/rules")
        restored_rules = []
        for source in sources:
            for rule in self.source_rules.get(source["id"], []):
                rule = dict(rule)
                if rule.get("calibrationRevision") is not None and rule[
                    "calibrationRevision"
                ] != source.get("calibrationRevision"):
                    rule.pop("calibrationRevision")
                    rule.update(
                        enabled=False, validationError="calibration-revision-changed"
                    )
                requires_calibration = rule.get("geometry", {}).get(
                    "space"
                ) == "site-metres" or rule.get("kind") in {
                    "stopped-in-zone",
                    "queue",
                    "wrong-way",
                }
                if (
                    requires_calibration
                    and source.get("imageToGroundHomography") is None
                ):
                    rule.update(
                        enabled=False,
                        validationError="calibration-required-after-site-change",
                    )
                restored_rules.append(rule)
        self.runtime.json(
            self.settings.gateway + "/rules",
            {"rules": restored_rules, "expectedRevision": current_rules["revision"]},
            "PUT",
        )
        # Runtime media registration is server-controlled and source-scoped.
        self.runtime.json(
            self.settings.gateway + "/media-registration",
            {
                "sources": [
                    {"sourceId": source["id"], "filename": source["filename"]}
                    for source in self.sources.values()
                    if source.get("filename")
                ]
            },
            "PUT",
        )

    def add(self, value: SensorValue) -> dict[str, Any]:
        with self.lock:
            ready, reason = self.readiness()
            if not ready:
                raise HTTPException(503, reason)
            if (
                value.camera_id not in self.sources
                and len(self.sources) >= self.settings.maximum_sources
            ):
                raise HTTPException(
                    409, "Smart City capacity exhausted: maximum two registered sources"
                )
            source = self._resolve(value)
            if (
                self.sources
                and source["kind"] != next(iter(self.sources.values()))["kind"]
            ):
                raise ValueError(
                    "Use recorded or live sources together; mixed clocks require a separate site"
                )
            if (
                self.sources.get(value.camera_id) == source
                and self.process is not None
                and self.process.poll() is None
            ):
                return {
                    "status": "ok",
                    "camera_id": value.camera_id,
                    "sourceState": "registered",
                    "message": "Already registered",
                    "profileId": "smart-city",
                }
            old = dict(self.sources)
            self.sources[value.camera_id] = source
            configuration_attempted = False
            try:
                self.runtime.stop(self.process)
                self.process = None
                self._wait_cold_readiness()
                configuration_attempted = True
                self._configure()
                self._save()
                log = self.settings.directory / "runtime" / "controller-worker.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                if not self.detections_paused:
                    self.process = self.runtime.start(
                        log, live=source["kind"] == "live"
                    )
            except (
                HTTPException,
                RuntimeError,
                ValueError,
                OSError,
                KeyError,
                subprocess.SubprocessError,
            ):
                self.sources = old
                self._save()
                if configuration_attempted:
                    try:
                        self._configure()
                    except (
                        RuntimeError,
                        ValueError,
                        OSError,
                        KeyError,
                        subprocess.SubprocessError,
                    ):
                        LOGGER.warning(
                            "Canonical source rollback failed; worker remains stopped",
                            exc_info=True,
                        )
                raise
            return {
                "status": "accepted",
                "camera_id": value.camera_id,
                "sourceState": "registered-stopped"
                if self.detections_paused
                else "starting",
                "profileId": "smart-city",
            }

    def remove(self, source_id: str) -> dict[str, Any]:
        with self.lock:
            if source_id not in self.sources:
                return {
                    "status": "ok",
                    "camera_id": source_id,
                    "message": "Already absent",
                }
            self.runtime.stop(self.process)
            self.process = None
            previous = dict(self.sources)
            self.sources.pop(source_id)
            try:
                self._configure()
                self._save()
            except Exception:
                # Keep ownership retryable if any canonical/configuration or
                # persistence step fails. The worker stays stopped throughout;
                # restarting it after a partial update would mix configurations.
                self.sources = previous
                try:
                    self._save()
                except Exception:
                    LOGGER.warning(
                        "Source ownership rollback could not be persisted",
                        exc_info=True,
                    )
                try:
                    self._configure()
                except Exception:
                    LOGGER.warning(
                        "Canonical source rollback failed; worker remains stopped",
                        exc_info=True,
                    )
                raise
            if self.sources:
                ready, _reason = self.runtime.readiness()
                if ready and not self.detections_paused:
                    log = self.settings.directory / "runtime" / "controller-worker.log"
                    log.parent.mkdir(parents=True, exist_ok=True)
                    self.process = self.runtime.start(
                        log,
                        live=all(
                            source["kind"] == "live" for source in self.sources.values()
                        ),
                    )
            return {"status": "ok", "camera_id": source_id, "message": "Removed"}

    def inventory(self) -> dict[str, Any]:
        with self.lock:
            return self._inventory_locked()

    def _inventory_locked(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        return {
            "stream-info": {
                "stream-info": [
                    {
                        "camera_id": source["id"],
                        "camera_name": source["name"],
                        "camera_url": source["inputUri"],
                        "status": "running" if running else "registered-stopped",
                    }
                    for source in self.sources.values()
                ]
            },
            "capacity": {
                "maxSources": self.settings.maximum_sources,
                "registeredSources": len(self.sources),
                "availableSources": self.settings.maximum_sources - len(self.sources),
            },
        }

    def recover_analysis(self) -> bool:
        """Manual retry or one gated preparation retry of a failed live worker."""
        with self.lock:
            if self.detections_paused:
                raise ValueError(
                    "Detections are off. Start detections before running a scenario."
                )
            if not self.sources:
                raise ValueError(
                    "Camera detections are paused. Resume detections before retrying the scenario."
                )
            if not all(source["kind"] == "live" for source in self.sources.values()):
                raise ValueError("Scenario recovery requires registered live cameras.")
            if self.process is not None and self.process.poll() is None:
                return False
            self.runtime.stop(self.process)
            self.process = None
            self._wait_cold_readiness()
            self._configure()
            log = self.settings.directory / "runtime" / "controller-worker.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            self.process = self.runtime.start(log, live=True)
            return True

    def detection_status(self) -> dict[str, Any]:
        """Actual worker state, distinct from registered camera ownership/readiness."""
        with self.lock:
            process = self.process
            exit_code = process.poll() if process is not None else None
            running = process is not None and exit_code is None
            ready, reason = self.readiness()
            return {
                "schemaVersion": "city.detections.v1",
                "state": "running"
                if running
                else "paused"
                if self.detections_paused
                else "stopped",
                "ready": ready,
                "detail": reason,
                "lastExitCode": exit_code,
                "sources": [
                    {"id": source["id"], "name": source["name"]}
                    for source in self.sources.values()
                ],
            }

    def control_detections(self, action: str) -> dict[str, Any]:
        """Pause only the worker; keep cameras, calibration, rules and recording.

        Starts use the same cold admission/configuration path as scenario recovery.
        A failed worker is never automatically retried after a simulator outage.
        """
        with self.lock:
            if action not in {"start", "stop", "restart"}:
                raise ValueError("Choose start, stop or restart.")
            if action in {"stop", "restart"}:
                self.runtime.stop(self.process)
                self.process = None
            old_paused = self.detections_paused
            self.detections_paused = action == "stop"
            try:
                if action != "stop":
                    self.recover_analysis()
            except Exception:
                self.detections_paused = old_paused
                raise
            temporary = self.detection_state_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"paused": self.detections_paused}) + "\n")
            temporary.replace(self.detection_state_file)
            return self.detection_status()

    def supervise(self) -> None:
        """Renew successful bounded live segments; failures require explicit resume."""
        with self.lock:
            if (
                self.detections_paused
                or not self.sources
                or self.process is None
                or self.process.poll() is None
            ):
                return
            if self.process.returncode != 0 or not all(
                source["kind"] == "live" for source in self.sources.values()
            ):
                return
            ready, _ = self.runtime.readiness()
            if ready:
                self.process = self.runtime.start(
                    self.settings.directory / "runtime" / "controller-worker.log",
                    live=True,
                )


def create_app(controller: CityController | None = None) -> FastAPI:
    controller = controller or CityController(
        Settings(
            device=os.environ.get("CITY_DEVICE", "spark"),
            gateway=os.environ.get(
                "CITY_GATEWAY_URL", "http://127.0.0.1:9184/api/v1/city"
            ),
            vss_origin=os.environ.get("CITY_VSS_ORIGIN", "http://127.0.0.1:30888"),
        )
    )
    demo = runpy.run_path(str(Path(__file__).with_name("demo_control.py")))["DemoControl"](
        gateway=controller.settings.gateway,
        state_path=controller.settings.directory / "runtime" / "prepared-control.json",
        recover_analysis=controller.recover_analysis,
    )

    @asynccontextmanager
    async def lifespan(app):
        async def supervisor():
            while True:
                await asyncio.sleep(1)
                await asyncio.to_thread(controller.supervise)
                await asyncio.to_thread(demo.poll)

        task = asyncio.create_task(supervisor())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if controller.process is not None:
                controller.runtime.stop(controller.process)

    avatars = runpy.run_path(str(Path(__file__).with_name('avatar_control.py')))['AvatarControl']()
    app = FastAPI(title="Local VSS Smart City source controller", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.client and request.client.host not in {
            "127.0.0.1",
            "::1",
            "testclient",
        }:
            return JSONResponse({"detail": "Controller is local-only"}, status_code=403)
        return await call_next(request)

    @app.get("/api/v1/health/get-dsready-state")
    def readiness():
        ready, reason = controller.readiness()
        if not ready:
            raise HTTPException(503, reason)
        return {
            "status": "ready",
            "detail": reason,
            "capacity": controller.inventory()["capacity"],
        }

    @app.get("/api/v1/stream/get-stream-info")
    def inventory():
        return controller.inventory()

    @app.get("/api/v1/health")
    def health():
        ready, reason = controller.readiness()
        return {"ready": ready, "detail": reason, **controller.inventory()}

    @app.post("/api/v1/stream/add")
    def add(payload: SensorRequest):
        try:
            return controller.add(payload.value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/v1/stream/remove")
    def remove(payload: SensorRequest):
        return controller.remove(payload.value.camera_id)

    @app.get("/api/v1/detections")
    def detection_status():
        return controller.detection_status()

    @app.post("/api/v1/detections")
    def detection_control(payload: DetectionRequest):
        try:
            return controller.control_detections(payload.action)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(
                503,
                "Detection control failed; check the controller and saved memory reserve.",
            ) from exc

    @app.get("/api/v1/demo")
    def demo_status():
        try:
            return demo.request()
        except (OSError, ValueError, RuntimeError) as exc:
            return {"schemaVersion": "city.tradeshow-control.v1", "available": False, "playing": False,
                    "scenario": {"state": "offline", "active": False, "catalog": []}, "detail": str(exc)[:240]}

    @app.get('/api/v1/avatars')
    def avatar_status():
        try:
            return avatars.request()
        except (OSError, ValueError, RuntimeError):
            return {'schemaVersion': 'city.live-avatars.v1', 'available': False, 'running': False,
                    'busy': False, 'canStart': False, 'active': 0,
                    'message': 'Start Smart City Demo to connect live avatars.'}

    @app.post('/api/v1/avatars')
    def avatar_action(payload: AvatarRequest):
        try:
            return avatars.request(payload.operation)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)[:240]) from exc

    @app.post("/api/v1/demo")
    def demo_action(payload: DemoRequest):
        try:
            return demo.request(payload.operation, scenario_id=payload.scenarioId,
                                run_id=payload.runId, request_id=payload.requestId)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)[:240]) from exc

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("spark", "thor"), default="spark")
    parser.add_argument("--port", type=int, default=9190)
    options = parser.parse_args()
    os.environ["CITY_DEVICE"] = options.device
    uvicorn.run(create_app(), host="127.0.0.1", port=options.port, workers=1)
