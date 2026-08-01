#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Inert-by-default loopback REST adapter for the Thor calibration backend."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import urlsplit

import backend

HOST = "127.0.0.1"
PORT = 8003
ACKNOWLEDGEMENT = "I_ACCEPT_LOCAL_LEGACY_CALIBRATION_SERVER_8003"
MAX_BODY_BYTES = backend.MAX_INPUT_BYTES
MAX_PROJECTS = 128
PROJECT_FILES = ("project.json", "calibration.json", "road-network.json")
IMPLEMENTED_ENDPOINTS = (
    ("GET", "/api/projects/"),
    ("POST", "/api/projects/"),
    ("GET", "/api/projects/{project_id}/"),
    ("PATCH", "/api/projects/{project_id}/"),
    ("DELETE", "/api/projects/{project_id}/"),
    ("GET", "/api/sensors/{sensor_id}/"),
    ("PATCH", "/api/sensors/{sensor_id}/"),
    ("GET", "/api/approxHomography/{sensor_id}/"),
    ("GET", "/api/homography/{sensor_id}/"),
)
MISSING_ENDPOINTS = (
    ("GET", "/api/invertImage/{sensor_id}/"),
    ("GET", "/api/importSensors/{project_id}/"),
    ("GET", "/api/getWarpedFiles/{project_id}/"),
    ("GET", "/api/getImageFiles/{project_id}/"),
    ("GET", "/api/uploadWebApi/{project_id}/"),
)
PLAIN_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
PROJECT_PATH = re.compile(rf"^/api/projects/({PLAIN_ID})/$")
SENSOR_PATH = re.compile(rf"^/api/sensors/({PLAIN_ID})/$")
APPROX_PATH = re.compile(rf"^/api/approxHomography/({PLAIN_ID})/$")
HOMOGRAPHY_PATH = re.compile(rf"^/api/homography/({PLAIN_ID})/$")
MISSING_PATHS = tuple(
    re.compile(
        "^"
        + re.escape(path)
        .replace(re.escape("{sensor_id}"), f"({PLAIN_ID})")
        .replace(re.escape("{project_id}"), f"({PLAIN_ID})")
        + "$"
    )
    for _method, path in MISSING_ENDPOINTS
)


class RestError(RuntimeError):
    """A bounded request or local persistence operation failed."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(data: bytes) -> dict[str, Any]:
    if not data or len(data) > MAX_BODY_BYTES:
        raise RestError(413, "JSON body must contain 1..1048576 bytes")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=backend._strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                backend.CalibrationError(f"non-finite JSON number: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, backend.CalibrationError) as exc:
        raise RestError(400, f"invalid strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RestError(400, "JSON body root must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return backend.load_project(path)
    except (OSError, backend.CalibrationError) as exc:
        raise RestError(500, f"stored project is invalid: {path.name}") from exc


def _safe_data_root(root: Path) -> Path:
    if not root.is_absolute():
        raise RestError(400, "data root must be an explicit absolute path")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise RestError(400, "data root must not contain symlinks")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise RestError(400, "data root must be a regular directory")
    return root.resolve(strict=True)


class LocalProjectStore:
    """Project persistence restricted to one explicit local root."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_data_root(root)
        self._lock = threading.RLock()

    def _directory(self, project_id: str) -> Path:
        backend._plain_id(project_id, "project_id")
        path = self.root / project_id
        if path.is_symlink():
            raise RestError(500, "project directory must not be a symlink")
        return path

    def _project(self, project_id: str) -> dict[str, Any]:
        path = self._directory(project_id) / "project.json"
        if not path.is_file() or path.is_symlink():
            raise RestError(404, "project not found")
        return _read_json(path)

    def _write_file(self, path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.new")
        if temporary.exists() or temporary.is_symlink():
            raise RestError(409, "stale project transaction exists")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_encoded(value))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            raise

    def _persist(self, project: dict[str, Any], *, create: bool) -> dict[str, Any]:
        try:
            calibration, road_network = backend.compile_project(project)
        except backend.CalibrationError as exc:
            raise RestError(422, str(exc)) from exc
        project_id = project["project_id"]
        directory = self._directory(project_id)
        if create:
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise RestError(409, "project already exists") from exc
        elif not directory.is_dir():
            raise RestError(404, "project not found")
        self._write_file(directory / "project.json", project)
        self._write_file(directory / "calibration.json", calibration)
        self._write_file(directory / "road-network.json", road_network)
        return project

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            entries = sorted(self.root.iterdir(), key=lambda path: path.name)
            if len(entries) > MAX_PROJECTS:
                raise RestError(507, "local project count exceeds 128")
            projects = []
            for entry in entries:
                if entry.is_symlink() or not entry.is_dir():
                    raise RestError(500, "data root contains an unmanaged entry")
                projects.append(self._project(entry.name))
            return projects

    def create(self, project: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if len(list(self.root.iterdir())) >= MAX_PROJECTS:
                raise RestError(507, "local project count exceeds 128")
            return self._persist(project, create=True)

    def get(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            return self._project(project_id)

    def patch(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not patch or not set(patch).issubset(
                backend.ALLOWED_TOP_COMMON | {"camera", "cameras"}
            ):
                raise RestError(400, "project patch contains unknown or no fields")
            if "project_id" in patch and patch["project_id"] != project_id:
                raise RestError(409, "project_id is immutable")
            updated = {**self._project(project_id), **patch, "project_id": project_id}
            return self._persist(updated, create=False)

    def delete(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            directory = self._directory(project_id)
            if not directory.is_dir():
                raise RestError(404, "project not found")
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
            if {entry.name for entry in entries} != set(PROJECT_FILES) or any(
                entry.is_symlink() or not entry.is_file() for entry in entries
            ):
                raise RestError(409, "project contains unmanaged files; delete refused")
            for entry in entries:
                entry.unlink()
            directory.rmdir()
            return {"deleted": project_id}

    def _sensor(self, sensor_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        backend._plain_id(sensor_id, "sensor_id")
        matches = []
        for project in self.list():
            cameras = project.get("cameras", [project.get("camera")])
            for camera in cameras:
                if isinstance(camera, dict) and camera.get("id") == sensor_id:
                    matches.append((project["project_id"], project, camera))
        if not matches:
            raise RestError(404, "sensor not found")
        if len(matches) != 1:
            raise RestError(409, "sensor id is not unique across local projects")
        return matches[0]

    def get_sensor(self, sensor_id: str) -> dict[str, Any]:
        project_id, _project, camera = self._sensor(sensor_id)
        return {"project_id": project_id, **camera}

    def patch_sensor(self, sensor_id: str, camera: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            project_id, project, _current = self._sensor(sensor_id)
            if not isinstance(camera, dict) or set(camera) != backend.ALLOWED_CAMERA:
                raise RestError(400, "sensor patch must be one exact camera object")
            if camera.get("id") != sensor_id:
                raise RestError(409, "sensor id is immutable")
            if "cameras" in project:
                project["cameras"] = [
                    camera if item["id"] == sensor_id else item
                    for item in project["cameras"]
                ]
            else:
                project["camera"] = camera
            self._persist(project, create=False)
            return {"project_id": project_id, **camera}

    def homography(self, sensor_id: str, *, approximate: bool) -> dict[str, Any]:
        project_id, _project, _camera = self._sensor(sensor_id)
        calibration = _read_json(self._directory(project_id) / "calibration.json")
        sensor = next(
            item for item in calibration["sensors"] if item["id"] == sensor_id
        )
        attributes = {
            item["name"]: item["value"] for item in sensor.get("attributes", [])
        }
        return {
            "project_id": project_id,
            "sensor_id": sensor_id,
            "homography": sensor["homography"],
            "reprojection_rms": float(attributes["reprojectionRms"]),
            "approximate": approximate,
        }


class Application:
    """Transport-independent REST routing used by the loopback handler."""

    def __init__(self, store: LocalProjectStore) -> None:
        self.store = store

    def dispatch(
        self, method: str, path: str, body: bytes = b""
    ) -> tuple[int, dict[str, Any]]:
        try:
            if path == "/api/projects/":
                if method == "GET":
                    return 200, {"projects": self.store.list()}
                if method == "POST":
                    return 201, self.store.create(_strict_json(body))
            match = PROJECT_PATH.fullmatch(path)
            if match:
                project_id = match.group(1)
                if method == "GET":
                    return 200, self.store.get(project_id)
                if method == "PATCH":
                    return 200, self.store.patch(project_id, _strict_json(body))
                if method == "DELETE":
                    return 200, self.store.delete(project_id)
            match = SENSOR_PATH.fullmatch(path)
            if match:
                if method == "GET":
                    return 200, self.store.get_sensor(match.group(1))
                if method == "PATCH":
                    return 200, self.store.patch_sensor(
                        match.group(1), _strict_json(body)
                    )
            match = APPROX_PATH.fullmatch(path)
            if match and method == "GET":
                return 200, self.store.homography(match.group(1), approximate=True)
            match = HOMOGRAPHY_PATH.fullmatch(path)
            if match and method == "GET":
                return 200, self.store.homography(match.group(1), approximate=False)
            if any(pattern.fullmatch(path) for pattern in MISSING_PATHS):
                raise RestError(
                    501,
                    "client-observed upload/import/warp endpoint is not implemented",
                )
            raise RestError(404, "endpoint not found")
        except RestError as exc:
            return exc.status, {"error": str(exc)}
        except backend.CalibrationError as exc:
            return 400, {"error": str(exc)}


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ThorLegacyCalibration/0.1"

    def _handle(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            self._respond(
                400, {"error": "absolute URLs, queries, and fragments are forbidden"}
            )
            return
        if self.headers.get("Transfer-Encoding"):
            self._respond(400, {"error": "transfer encoding is forbidden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, {"error": "invalid content length"})
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._respond(413, {"error": "request body exceeds the one MiB bound"})
            return
        body = self.rfile.read(length) if length else b""
        application = getattr(self.server, "application")
        status, payload = application.dispatch(self.command, parsed.path, body)
        self._respond(status, payload)

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        encoded = _encoded(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def plan() -> dict[str, Any]:
    return {
        "mode": "inert_plan_only",
        "started": False,
        "bind": {"host": HOST, "port": PORT, "loopback_only": True},
        "persistence": "explicit_local_data_root_only",
        "implemented_endpoints": [list(item) for item in IMPLEMENTED_ENDPOINTS],
        "missing_endpoints": [list(item) for item in MISSING_ENDPOINTS],
        "provider_egress": "forbidden",
        "runtime_evidence": [],
    }


def serve(data_root: Path) -> None:
    application = Application(LocalProjectStore(data_root))
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    server.application = application
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("plan", "serve"), default="plan")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--acknowledgement")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if args.acknowledgement != ACKNOWLEDGEMENT:
        print(f"ERROR: serve requires --acknowledgement {ACKNOWLEDGEMENT}")
        return 1
    if args.data_root is None or not args.data_root.is_absolute():
        print("ERROR: serve requires an explicit absolute --data-root")
        return 1
    try:
        serve(args.data_root)
    except (OSError, RestError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
