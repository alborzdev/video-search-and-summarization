#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Inert-by-default VIOS calibration-client compatibility server for Thor.

This module intentionally keeps the browser client's incremental UI state
separate from the strict VSS export compiler in ``backend.py``.  It never
dereferences a project URL and has no outbound network client.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import urlsplit

import backend

HOST = "127.0.0.1"
PORT = 8013
ACKNOWLEDGEMENT = "I_ACCEPT_LOCAL_VIOS_CALIBRATION_UI_SERVER_8013"
MAX_JSON_BYTES = backend.MAX_INPUT_BYTES
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_MULTIPART_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_PROJECTS = 128
MAX_SENSORS = 128
MAX_TEXT = 10_000
PROJECT_FILE = "ui-project.json"
STAGED_FILE = "staged-sensors.json"
MEDIA_DIRECTORY = "media"
PLAIN_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
PROJECT_ID = r"[1-9][0-9]{0,8}"
PROJECT_PATH = re.compile(rf"^/api/projects/({PROJECT_ID})/$")
SENSOR_PATH = re.compile(rf"^/api/sensors/({PLAIN_ID})/$")
APPROX_PATH = re.compile(rf"^/api/approxHomography/({PLAIN_ID})/$")
HOMOGRAPHY_PATH = re.compile(rf"^/api/homography/({PLAIN_ID})/$")
IMPORT_PATH = re.compile(rf"^/api/importSensors/({PROJECT_ID})/$")
PENDING_PATHS = (
    re.compile(rf"^/api/invertImage/({PLAIN_ID})/$"),
    re.compile(rf"^/api/getWarpedFiles/({PROJECT_ID})/$"),
    re.compile(rf"^/api/getImageFiles/({PROJECT_ID})/$"),
    re.compile(rf"^/api/uploadWebApi/({PROJECT_ID})/$"),
)
MEDIA_PATH = re.compile(
    rf"^/media/projects/({PROJECT_ID})/sensors/({PLAIN_ID})/"
    r"([0-9a-f]{64}\.(?:png|jpg))$"
)
CALIBRATION_TYPES = {"geo", "cartesian", "floorplan", "mtmc", "image"}
CARDINAL_DIRECTIONS = {
    "NW",
    "NNW",
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
}
JSON_SENSOR_FIELDS = {
    "coordinates",
    "geoLocation",
    "sensorPolygon",
    "edgeLengths",
    "floorPlanPolygon",
    "gisPolygon",
    "roiPolygon",
    "cropRoiPolygon",
    "imHomography",
    "homography",
    "mapCenter",
    "scaleFactorPolygon",
    "scalePolygon",
    "tripwireLines",
    "tripDirLines",
}
SENSOR_BOOLEAN_FIELDS = {"isCalibrated", "isValidated"}
SENSOR_INTEGER_FIELDS = {
    "height",
    "width",
    "floorPlanImHeight",
    "floorPlanImWidth",
    "mapZoom",
    "invertImXPad",
    "invertImYPad",
    "invertImWidth",
    "invertImHeight",
}
SENSOR_NUMBER_FIELDS = {"originLat", "originLng", "scaleFactor"}
SENSOR_ARRAY_FIELDS = {"corridor_set", "place_set"}
SENSOR_NULLABLE_INTEGER_FIELDS = {"intersection_set"}
SENSOR_NULLABLE_TEXT_FIELDS = {
    "imageUrl",
    "invertImageUrl",
    "floorPlanImageUrl",
}
SENSOR_IMMUTABLE_FIELDS = {"id", "created", "project"}
SENSOR_TEXT_FIELDS = {
    "mapAPIKey",
    "modified",
    "sensorId",
    "calibrationType",
    "sensorName",
    "cardinalDirection",
    "rtspURL",
    "majorRoad",
    "minorRoad",
    "mmsInfo_protocol",
    "mmsInfo_host",
    "mmsInfo_type",
    "fps",
    "deviceId",
    "videoURL",
    "depth",
    "fieldOfView",
    "direction",
    "view",
    "type",
}
SENSOR_FIELDS = (
    SENSOR_BOOLEAN_FIELDS
    | SENSOR_INTEGER_FIELDS
    | SENSOR_NUMBER_FIELDS
    | SENSOR_ARRAY_FIELDS
    | SENSOR_NULLABLE_INTEGER_FIELDS
    | SENSOR_NULLABLE_TEXT_FIELDS
    | SENSOR_IMMUTABLE_FIELDS
    | SENSOR_TEXT_FIELDS
    | JSON_SENSOR_FIELDS
)
PROJECT_MUTABLE_FIELDS = {
    "name",
    "calibrationType",
    "mapAPIKey",
    "mapFile",
    "webApiUrl",
    "scaleFactor",
    "calibrationJsonTemp",
    "imageMetaDataJsonTemp",
    "imageFiles",
    "calibrationJson",
    "sensorMetadataCsv",
    "imageMetaDataJson",
    "roadNetworkJson",
    "mmsURL",
    "placeTypeHierarchy",
    "floorPlanImageUrl",
    "floorPlanImHeight",
    "floorPlanImWidth",
    "rtspURL",
    "coordinates",
    "mapCoordinates",
    "mapZoom",
    "mapCenter",
    "originLat",
    "originLng",
    "cityPlace",
    "roomPlace",
}
MULTIPART_TEXT_FIELDS = {
    "sensorPolygon",
    "homography",
    "imHomography",
    "edgeLengths",
    "isCalibrated",
    "isValidated",
}


class UIError(RuntimeError):
    """A bounded client operation or owned persistence action failed."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _encoded_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _json_response(status: int, value: Any) -> Response:
    return Response(status, _encoded_json(value), "application/json; charset=utf-8")


def _text_response(status: int, value: str) -> Response:
    return Response(status, (value + "\n").encode(), "text/plain; charset=utf-8")


def _strict_json_value(data: bytes, *, maximum: int = MAX_JSON_BYTES) -> Any:
    if not data or len(data) > maximum:
        raise UIError(413, f"JSON body must contain 1..{maximum} bytes")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=backend._strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                backend.CalibrationError(f"non-finite JSON number: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, backend.CalibrationError) as exc:
        raise UIError(400, f"invalid strict JSON: {exc}") from exc


def _strict_json_object(data: bytes) -> dict[str, Any]:
    value = _strict_json_value(data)
    if not isinstance(value, dict):
        raise UIError(400, "JSON body root must be an object")
    return value


def _plain_id(value: Any, label: str) -> str:
    try:
        return backend._plain_id(value, label)
    except backend.CalibrationError as exc:
        raise UIError(400, str(exc)) from exc


def _project_id(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not (1 <= value <= 999_999_999)
    ):
        raise UIError(400, "project id must be an integer in 1..999999999")
    return value


def _bounded_text(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise UIError(400, f"{label} must be a bounded string")
    return value


def _finite(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise UIError(400, f"{label} must be a finite number")
    return float(value)


def _json_string(value: Any, label: str) -> str | None:
    if label == "mapCenter" and value is None:
        return None
    text = _bounded_text(value, label)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=backend._strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                backend.CalibrationError(f"non-finite JSON number: {token}")
            ),
        )
    except (json.JSONDecodeError, backend.CalibrationError) as exc:
        raise UIError(400, f"{label} must contain strict JSON") from exc
    if label == "homography" and text not in ("", "[]"):
        if (
            not isinstance(parsed, list)
            or len(parsed) != 3
            or any(not isinstance(row, list) or len(row) != 3 for row in parsed)
        ):
            raise UIError(400, "homography must contain a 3x3 JSON matrix")
        for row in parsed:
            for item in row:
                _finite(item, "homography entry")
    return text


def _safe_root(root: Path) -> Path:
    if not root.is_absolute():
        raise UIError(400, "data root must be an explicit absolute path")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.exists() and current.is_symlink():
            raise UIError(400, "data root must not contain symlinks")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise UIError(400, "data root must be a regular directory")
    return root.resolve(strict=True)


def _project_defaults(
    project_id: int, name: str, calibration_type: str
) -> dict[str, Any]:
    timestamp = _now()
    return {
        "id": project_id,
        "sensor_set": [],
        "intersection_set": [],
        "city_set": [],
        "placeTypes_set": [],
        "corridor_set": [],
        "created": timestamp,
        "modified": timestamp,
        "name": name,
        "calibrationType": calibration_type,
        "mapAPIKey": "",
        "mapFile": "",
        "webApiUrl": "",
        "scaleFactor": 1.0,
        "calibrationJsonTemp": "",
        "imageMetaDataJsonTemp": "",
        "imageFiles": None,
        "calibrationJson": "",
        "sensorMetadataCsv": "",
        "imageMetaDataJson": "",
        "roadNetworkJson": "",
        "mmsURL": "",
        "placeTypeHierarchy": "",
        "floorPlanImageUrl": None,
        "floorPlanImHeight": 0,
        "floorPlanImWidth": 0,
        "rtspURL": "",
        "coordinates": "[]",
        "mapCoordinates": "[]",
        "mapZoom": 0,
        "mapCenter": None,
        "originLat": 0.0,
        "originLng": 0.0,
        "cityPlace": None,
        "roomPlace": None,
    }


def _sensor_defaults(
    sensor_id: str, project_id: int, calibration_type: str
) -> dict[str, Any]:
    timestamp = _now()
    return {
        "id": sensor_id,
        "mapAPIKey": "",
        "created": timestamp,
        "modified": timestamp,
        "sensorId": sensor_id,
        "height": 0,
        "width": 0,
        "isCalibrated": False,
        "isValidated": False,
        "calibrationType": calibration_type,
        "coordinates": "[]",
        "geoLocation": "[]",
        "sensorPolygon": "[]",
        "edgeLengths": "[]",
        "floorPlanPolygon": "[]",
        "gisPolygon": "[]",
        "roiPolygon": "[]",
        "cropRoiPolygon": "[]",
        "floorPlanImHeight": 0,
        "floorPlanImWidth": 0,
        "imHomography": "[]",
        "homography": "[]",
        "mapZoom": 0,
        "mapCenter": None,
        "originLat": 0.0,
        "originLng": 0.0,
        "scaleFactor": 1.0,
        "scaleFactorPolygon": "[]",
        "scalePolygon": "[]",
        "sensorName": sensor_id,
        "cardinalDirection": "NW",
        "imageUrl": None,
        "invertImageUrl": None,
        "floorPlanImageUrl": None,
        "rtspURL": "",
        "invertImXPad": 0,
        "invertImYPad": 0,
        "invertImWidth": 0,
        "invertImHeight": 0,
        "majorRoad": "",
        "minorRoad": "",
        "tripwireLines": "[]",
        "tripDirLines": "[]",
        "mmsInfo_protocol": "",
        "mmsInfo_host": "",
        "mmsInfo_type": "",
        "fps": "",
        "deviceId": "",
        "videoURL": "",
        "depth": "",
        "fieldOfView": "",
        "direction": "",
        "view": "",
        "type": "camera",
        "project": project_id,
        "intersection_set": None,
        "corridor_set": [],
        "place_set": [],
    }


def _validate_project_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not patch or not set(patch).issubset(PROJECT_MUTABLE_FIELDS):
        raise UIError(400, "project patch contains unknown or no fields")
    result: dict[str, Any] = {}
    for key, value in patch.items():
        if key == "calibrationType":
            if value not in CALIBRATION_TYPES:
                raise UIError(400, "unsupported calibrationType")
            result[key] = value
        elif key == "mapAPIKey":
            if value != "":
                raise UIError(400, "mapAPIKey must remain empty in provider-free mode")
            result[key] = ""
        elif key in {"scaleFactor", "originLat", "originLng"}:
            result[key] = _finite(value, key)
            if key == "scaleFactor" and result[key] <= 0:
                raise UIError(400, "scaleFactor must be positive")
        elif key in {"floorPlanImHeight", "floorPlanImWidth", "mapZoom"}:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not (0 <= value <= 16384)
            ):
                raise UIError(400, f"{key} must be a bounded nonnegative integer")
            result[key] = value
        elif key in {
            "imageFiles",
            "floorPlanImageUrl",
            "mapCenter",
            "cityPlace",
            "roomPlace",
        }:
            result[key] = _bounded_text(value, key, nullable=True)
        else:
            result[key] = _bounded_text(value, key)
    return result


def _validate_sensor_patch(
    current: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    if not patch or not set(patch).issubset(SENSOR_FIELDS):
        raise UIError(400, "sensor patch contains unknown or no fields")
    result: dict[str, Any] = {}
    for key, value in patch.items():
        if key in SENSOR_IMMUTABLE_FIELDS or key in {
            "imageUrl",
            "invertImageUrl",
            "floorPlanImageUrl",
        }:
            if value != current[key]:
                raise UIError(409, f"{key} is server-owned and immutable")
            continue
        if key in SENSOR_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise UIError(400, f"{key} must be boolean")
            result[key] = value
        elif key in SENSOR_INTEGER_FIELDS:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not (0 <= value <= 16384)
            ):
                raise UIError(400, f"{key} must be a bounded nonnegative integer")
            result[key] = value
        elif key in SENSOR_NUMBER_FIELDS:
            number = _finite(value, key)
            if key == "scaleFactor" and number <= 0:
                raise UIError(400, "scaleFactor must be positive")
            if key == "originLat" and not -90 <= number <= 90:
                raise UIError(400, "originLat is outside its allowed range")
            if key == "originLng" and not -180 <= number <= 180:
                raise UIError(400, "originLng is outside its allowed range")
            result[key] = number
        elif key in SENSOR_ARRAY_FIELDS:
            if (
                not isinstance(value, list)
                or len(value) > 128
                or any(
                    isinstance(item, bool) or not isinstance(item, int)
                    for item in value
                )
            ):
                raise UIError(400, f"{key} must be a bounded integer array")
            result[key] = value
        elif key in SENSOR_NULLABLE_INTEGER_FIELDS:
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise UIError(400, f"{key} must be an integer or null")
            result[key] = value
        elif key in JSON_SENSOR_FIELDS:
            result[key] = _json_string(value, key)
        elif key == "calibrationType":
            if value not in CALIBRATION_TYPES:
                raise UIError(400, "unsupported calibrationType")
            result[key] = value
        elif key == "cardinalDirection":
            if value not in CARDINAL_DIRECTIONS:
                raise UIError(400, "unsupported cardinalDirection")
            result[key] = value
        elif key == "mapAPIKey":
            if value != "":
                raise UIError(400, "mapAPIKey must remain empty in provider-free mode")
            result[key] = ""
        else:
            result[key] = _bounded_text(value, key)
    return result


def _image_kind(data: bytes) -> tuple[str, str]:
    if (
        len(data) >= 24
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[12:16] == b"IHDR"
    ):
        return "png", "image/png"
    if len(data) >= 4 and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        return "jpg", "image/jpeg"
    raise UIError(415, "imageUrl must be a bounded PNG or JPEG file")


def _parse_multipart(content_type: str, body: bytes) -> tuple[bytes, dict[str, str]]:
    if len(body) > MAX_MULTIPART_BYTES:
        raise UIError(413, "multipart body exceeds 16 MiB")
    if (
        not content_type.lower().startswith("multipart/form-data;")
        or "boundary=" not in content_type.lower()
    ):
        raise UIError(
            415, "sensor image PATCH requires multipart/form-data with a boundary"
        )
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise UIError(400, "multipart body is malformed")
    values: dict[str, str] = {}
    image: bytes | None = None
    seen: set[str] = set()
    for part in message.iter_parts():
        if part.is_multipart():
            raise UIError(400, "nested multipart content is forbidden")
        name = part.get_param("name", header="content-disposition")
        if name not in MULTIPART_TEXT_FIELDS | {"imageUrl"} or name in seen:
            raise UIError(400, "multipart body has an unknown or duplicate field")
        seen.add(name)
        payload = part.get_payload(decode=True) or b""
        if name == "imageUrl":
            if not part.get_filename() or not (1 <= len(payload) <= MAX_IMAGE_BYTES):
                raise UIError(400, "imageUrl must contain one bounded file")
            image = payload
        else:
            try:
                value = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UIError(400, f"multipart field {name} is not UTF-8") from exc
            if len(value) > MAX_TEXT:
                raise UIError(400, f"multipart field {name} exceeds its bound")
            values[name] = value
    if seen != MULTIPART_TEXT_FIELDS | {"imageUrl"} or image is None:
        raise UIError(400, "multipart body is missing required client fields")
    return image, values


class LocalUIStore:
    """Incremental UI state confined to ``data_root/ui-projects``."""

    def __init__(self, data_root: Path) -> None:
        root = _safe_root(data_root)
        self.root = root / "ui-projects"
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise UIError(400, "ui-projects must be a regular directory")
        self._lock = threading.RLock()

    def _directory(self, project_id: int) -> Path:
        _project_id(project_id)
        directory = self.root / str(project_id)
        if directory.is_symlink():
            raise UIError(500, "project directory must not be a symlink")
        return directory

    def _read(self, path: Path) -> Any:
        if path.is_symlink() or not path.is_file():
            raise UIError(404, "owned state file not found")
        try:
            return _strict_json_value(path.read_bytes(), maximum=MAX_STATE_BYTES)
        except OSError as exc:
            raise UIError(500, "cannot read owned state") from exc

    def _write(self, path: Path, value: Any) -> None:
        encoded = _encoded_json(value)
        if len(encoded) > MAX_STATE_BYTES:
            raise UIError(507, "owned UI state exceeds 32 MiB")
        temporary = path.with_name(f".{path.name}.new")
        if temporary.exists() or temporary.is_symlink():
            raise UIError(409, "stale UI-state transaction exists")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            raise

    def _get_unlocked(self, project_id: int) -> dict[str, Any]:
        path = self._directory(project_id) / PROJECT_FILE
        value = self._read(path)
        if not isinstance(value, dict) or value.get("id") != project_id:
            raise UIError(500, "stored UI project is invalid")
        return value

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            entries = sorted(
                self.root.iterdir(),
                key=lambda item: int(item.name) if item.name.isdigit() else -1,
            )
            if len(entries) > MAX_PROJECTS:
                raise UIError(507, "UI project count exceeds 128")
            result = []
            for entry in entries:
                if entry.is_symlink() or not entry.is_dir() or not entry.name.isdigit():
                    raise UIError(500, "ui-projects contains an unmanaged entry")
                result.append(self._get_unlocked(int(entry.name)))
            return result

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        if set(body) != {"name", "calibrationType"}:
            raise UIError(400, "project create needs exactly name and calibrationType")
        name = _bounded_text(body["name"], "name")
        if not name.strip():
            raise UIError(400, "name must not be blank")
        calibration_type = body["calibrationType"]
        if calibration_type not in CALIBRATION_TYPES:
            raise UIError(400, "unsupported calibrationType")
        with self._lock:
            projects = self.list()
            if len(projects) >= MAX_PROJECTS:
                raise UIError(507, "UI project count exceeds 128")
            project_id = max((item["id"] for item in projects), default=0) + 1
            project = _project_defaults(project_id, name.strip(), calibration_type)
            directory = self._directory(project_id)
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise UIError(409, "project id collision") from exc
            try:
                self._write(directory / PROJECT_FILE, project)
            except Exception:
                if not any(directory.iterdir()):
                    directory.rmdir()
                raise
            return project

    def get(self, project_id: int) -> dict[str, Any]:
        with self._lock:
            return self._get_unlocked(project_id)

    def patch(self, project_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        normalized = _validate_project_patch(patch)
        with self._lock:
            project = self._get_unlocked(project_id)
            project.update(normalized)
            project["modified"] = _now()
            self._write(self._directory(project_id) / PROJECT_FILE, project)
            return project

    def _owned_media_files(self, directory: Path) -> list[Path]:
        files: list[Path] = []
        if not directory.exists():
            return files
        if directory.is_symlink() or not directory.is_dir():
            raise UIError(409, "project media is unmanaged")
        for sensor_dir in directory.iterdir():
            if (
                sensor_dir.is_symlink()
                or not sensor_dir.is_dir()
                or not re.fullmatch(PLAIN_ID, sensor_dir.name)
            ):
                raise UIError(409, "project media contains an unmanaged sensor entry")
            for image in sensor_dir.iterdir():
                if (
                    image.is_symlink()
                    or not image.is_file()
                    or not re.fullmatch(r"[0-9a-f]{64}\.(?:png|jpg)", image.name)
                ):
                    raise UIError(409, "project media contains an unmanaged file")
                files.append(image)
        return files

    def delete(self, project_id: int) -> dict[str, Any]:
        with self._lock:
            directory = self._directory(project_id)
            self._get_unlocked(project_id)
            allowed = {PROJECT_FILE, STAGED_FILE, MEDIA_DIRECTORY}
            if any(
                entry.name not in allowed or entry.is_symlink()
                for entry in directory.iterdir()
            ):
                raise UIError(409, "project contains unmanaged files; delete refused")
            media = directory / MEDIA_DIRECTORY
            files = self._owned_media_files(media)
            sensor_dirs = (
                sorted(media.iterdir(), key=lambda path: path.name)
                if media.is_dir()
                else []
            )
            for image in files:
                image.unlink()
            for sensor_dir in sensor_dirs:
                sensor_dir.rmdir()
            if media.is_dir():
                media.rmdir()
            staged = directory / STAGED_FILE
            if staged.is_file() and not staged.is_symlink():
                staged.unlink()
            (directory / PROJECT_FILE).unlink()
            directory.rmdir()
            return {"deleted": project_id}

    def _sensor_unlocked(
        self, sensor_id: str
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        _plain_id(sensor_id, "sensor id")
        matches: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for project in self.list():
            for sensor in project["sensor_set"]:
                if sensor.get("id") == sensor_id:
                    matches.append((project["id"], project, sensor))
        if not matches:
            raise UIError(404, "sensor not found")
        if len(matches) != 1:
            raise UIError(409, "sensor id is not unique across UI projects")
        return matches[0]

    def get_sensor(self, sensor_id: str) -> dict[str, Any]:
        with self._lock:
            return self._sensor_unlocked(sensor_id)[2]

    def _persist_sensor(
        self, project_id: int, project: dict[str, Any], sensor: dict[str, Any]
    ) -> dict[str, Any]:
        project["sensor_set"] = [
            sensor if item["id"] == sensor["id"] else item
            for item in project["sensor_set"]
        ]
        project["modified"] = _now()
        self._write(self._directory(project_id) / PROJECT_FILE, project)
        return sensor

    def patch_sensor(self, sensor_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            project_id, project, current = self._sensor_unlocked(sensor_id)
            normalized = _validate_sensor_patch(current, patch)
            external_id = normalized.get("sensorId", current["sensorId"])
            for candidate in self.list():
                for other in candidate["sensor_set"]:
                    if other["id"] != sensor_id and other["sensorId"] == external_id:
                        raise UIError(409, "sensorId is not unique across UI projects")
            sensor = {**current, **normalized, "modified": _now()}
            return self._persist_sensor(project_id, project, sensor)

    def stage_sensors(self, project_id: int, manifest: Any) -> dict[str, Any]:
        if not isinstance(manifest, dict) or set(manifest) != {"sensors"}:
            raise UIError(400, "staged manifest must contain exactly sensors")
        rows = manifest["sensors"]
        if not isinstance(rows, list) or not (1 <= len(rows) <= MAX_SENSORS):
            raise UIError(400, "staged sensors must contain 1..128 entries")
        normalized = []
        seen_ids: set[str] = set()
        seen_external_ids: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not row:
                raise UIError(400, f"staged sensor {index} must be an object")
            allowed = (
                SENSOR_FIELDS - SENSOR_IMMUTABLE_FIELDS - SENSOR_NULLABLE_TEXT_FIELDS
            ) | {"id"}
            if not set(row).issubset(allowed) or "sensorId" not in row:
                raise UIError(
                    400, f"staged sensor {index} has unknown fields or no sensorId"
                )
            external_id = _plain_id(row["sensorId"], f"staged sensor {index}.sensorId")
            sensor_id = _plain_id(
                row.get("id", external_id), f"staged sensor {index}.id"
            )
            if sensor_id in seen_ids or external_id in seen_external_ids:
                raise UIError(409, "staged sensor identities must be unique")
            seen_ids.add(sensor_id)
            seen_external_ids.add(external_id)
            normalized.append({**row, "id": sensor_id, "sensorId": external_id})
        with self._lock:
            self._get_unlocked(project_id)
            for project in self.list():
                if project["id"] == project_id:
                    continue
                for sensor in project["sensor_set"]:
                    if (
                        sensor["id"] in seen_ids
                        or sensor["sensorId"] in seen_external_ids
                    ):
                        raise UIError(
                            409, "staged sensor identity conflicts with another project"
                        )
            self._write(
                self._directory(project_id) / STAGED_FILE, {"sensors": normalized}
            )
        return {"project_id": project_id, "staged": len(normalized)}

    def import_staged(self, project_id: int) -> int:
        with self._lock:
            project = self._get_unlocked(project_id)
            staged = self._read(self._directory(project_id) / STAGED_FILE)
            if not isinstance(staged, dict) or not isinstance(
                staged.get("sensors"), list
            ):
                raise UIError(500, "staged sensor manifest is invalid")
            existing = {sensor["id"]: sensor for sensor in project["sensor_set"]}
            imported = []
            for row in staged["sensors"]:
                sensor_id = row["id"]
                current = existing.get(sensor_id) or _sensor_defaults(
                    sensor_id, project_id, project["calibrationType"]
                )
                patch = {key: value for key, value in row.items() if key != "id"}
                normalized = _validate_sensor_patch(current, patch)
                imported.append({**current, **normalized, "modified": _now()})
            project["sensor_set"] = imported
            project["modified"] = _now()
            self._write(self._directory(project_id) / PROJECT_FILE, project)
            return len(imported)

    def homography(self, sensor_id: str, *, approximate: bool) -> dict[str, Any]:
        with self._lock:
            project_id, project, current = self._sensor_unlocked(sensor_id)
            try:
                figures = json.loads(current["sensorPolygon"])
                world = json.loads(current["edgeLengths"])
            except json.JSONDecodeError as exc:
                raise UIError(
                    422, "sensor calibration coordinates are invalid"
                ) from exc
            if not isinstance(figures, list) or not figures:
                raise UIError(422, "sensorPolygon needs a calibration figure")
            figure = next(
                (
                    item
                    for item in figures
                    if isinstance(item, dict)
                    and item.get("class") in {"calib", "cartCalib"}
                ),
                figures[0],
            )
            points = figure.get("points") if isinstance(figure, dict) else None
            if (
                not isinstance(points, list)
                or not isinstance(world, list)
                or len(points) != len(world)
            ):
                raise UIError(
                    422, "sensorPolygon and edgeLengths must have matching points"
                )
            correspondences = []
            for index, (image_point, world_point) in enumerate(
                zip(points, world, strict=True)
            ):
                if not isinstance(image_point, dict) or not {"lat", "lng"}.issubset(
                    image_point
                ):
                    raise UIError(422, f"sensorPolygon point {index} is invalid")
                if not isinstance(world_point, dict) or set(world_point) != {
                    "lat",
                    "lng",
                }:
                    raise UIError(422, f"edgeLengths point {index} is invalid")
                correspondences.append(
                    {
                        "image": [image_point["lng"], image_point["lat"]],
                        "world": [world_point["lng"], world_point["lat"]],
                    }
                )
            try:
                matrix, rms = backend.solve_homography(correspondences)
            except backend.CalibrationError as exc:
                raise UIError(422, str(exc)) from exc
            sensor = {
                **current,
                "homography": json.dumps(matrix, separators=(",", ":")),
                "modified": _now(),
            }
            self._persist_sensor(project_id, project, sensor)
            return {
                "sensor_id": sensor_id,
                "homography": matrix,
                "reprojection_rms": rms,
                "approximate": approximate,
            }

    def upload_image(
        self, sensor_id: str, content_type: str, body: bytes
    ) -> dict[str, Any]:
        image, fields = _parse_multipart(content_type, body)
        extension, _mime = _image_kind(image)
        boolean_values: dict[str, bool] = {}
        for name in ("isCalibrated", "isValidated"):
            if fields[name] not in {"true", "false"}:
                raise UIError(400, f"multipart field {name} must be true or false")
            boolean_values[name] = fields[name] == "true"
        patch: dict[str, Any] = {
            name: fields[name]
            for name in ("sensorPolygon", "homography", "imHomography", "edgeLengths")
        }
        patch.update(boolean_values)
        with self._lock:
            project_id, project, current = self._sensor_unlocked(sensor_id)
            normalized = _validate_sensor_patch(current, patch)
            digest_name = f"{hashlib.sha256(image).hexdigest()}.{extension}"
            media_root = self._directory(project_id) / MEDIA_DIRECTORY
            media_root.mkdir(mode=0o700, exist_ok=True)
            if media_root.is_symlink() or not media_root.is_dir():
                raise UIError(409, "project media directory is invalid")
            media = media_root / sensor_id
            media.mkdir(mode=0o700, exist_ok=True)
            if media.is_symlink() or not media.is_dir():
                raise UIError(409, "sensor media directory is invalid")
            image_path = media / digest_name
            created = False
            if not image_path.exists():
                descriptor = os.open(
                    image_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(image)
                    stream.flush()
                    os.fsync(stream.fileno())
                created = True
            elif (
                image_path.is_symlink()
                or not image_path.is_file()
                or image_path.read_bytes() != image
            ):
                raise UIError(409, "image digest path collision")
            url = f"media/projects/{project_id}/sensors/{sensor_id}/{digest_name}"
            sensor = {**current, **normalized, "imageUrl": url, "modified": _now()}
            try:
                return self._persist_sensor(project_id, project, sensor)
            except Exception:
                if created and image_path.is_file() and not image_path.is_symlink():
                    image_path.unlink()
                raise

    def media(self, project_id: int, sensor_id: str, filename: str) -> Response:
        with self._lock:
            project = self._get_unlocked(project_id)
            sensor = next(
                (item for item in project["sensor_set"] if item["id"] == sensor_id),
                None,
            )
            if sensor is None:
                raise UIError(404, "sensor not found")
            relative = f"media/projects/{project_id}/sensors/{sensor_id}/{filename}"
            if relative not in {
                sensor.get("imageUrl"),
                sensor.get("invertImageUrl"),
                sensor.get("floorPlanImageUrl"),
            }:
                raise UIError(404, "media is not referenced by the sensor")
            path = self._directory(project_id) / MEDIA_DIRECTORY / sensor_id / filename
            if path.is_symlink() or not path.is_file():
                raise UIError(404, "media not found")
            if not 1 <= path.stat().st_size <= MAX_IMAGE_BYTES:
                raise UIError(409, "stored media exceeds its identity bound")
            data = path.read_bytes()
            extension, mime = _image_kind(data)
            if (
                not filename.endswith(f".{extension}")
                or hashlib.sha256(data).hexdigest() != filename.split(".")[0]
            ):
                raise UIError(409, "stored media identity mismatch")
            return Response(200, data, mime, {"Content-Length": str(len(data))})


class Application:
    def __init__(self, store: LocalUIStore) -> None:
        self.store = store

    def dispatch(
        self, method: str, path: str, body: bytes = b"", *, content_type: str = ""
    ) -> Response:
        try:
            if path == "/api/projects/":
                if method == "GET":
                    return _json_response(200, self.store.list())
                if method == "POST":
                    return _json_response(
                        201, self.store.create(_strict_json_object(body))
                    )
            match = PROJECT_PATH.fullmatch(path)
            if match:
                project_id = int(match.group(1))
                if method == "GET":
                    return _json_response(200, self.store.get(project_id))
                if method == "PATCH":
                    return _json_response(
                        200, self.store.patch(project_id, _strict_json_object(body))
                    )
                if method == "DELETE":
                    return _json_response(200, self.store.delete(project_id))
            match = SENSOR_PATH.fullmatch(path)
            if match:
                sensor_id = match.group(1)
                if method == "GET":
                    return _json_response(200, self.store.get_sensor(sensor_id))
                if method == "PATCH":
                    if content_type.lower().startswith("multipart/form-data"):
                        return _json_response(
                            200, self.store.upload_image(sensor_id, content_type, body)
                        )
                    return _json_response(
                        200,
                        self.store.patch_sensor(sensor_id, _strict_json_object(body)),
                    )
            match = APPROX_PATH.fullmatch(path)
            if match and method == "GET":
                return _json_response(
                    200, self.store.homography(match.group(1), approximate=True)
                )
            match = HOMOGRAPHY_PATH.fullmatch(path)
            if match and method == "GET":
                return _json_response(
                    200, self.store.homography(match.group(1), approximate=False)
                )
            match = IMPORT_PATH.fullmatch(path)
            if match and method == "GET":
                count = self.store.import_staged(int(match.group(1)))
                return _text_response(200, f"Imported {count} locally staged sensor(s)")
            match = MEDIA_PATH.fullmatch(path)
            if match and method == "GET":
                return self.store.media(
                    int(match.group(1)), match.group(2), match.group(3)
                )
            if any(pattern.fullmatch(path) for pattern in PENDING_PATHS):
                raise UIError(
                    501,
                    "image inversion, ZIP export, and Web API upload remain explicitly pending",
                )
            raise UIError(404, "endpoint not found")
        except UIError as exc:
            return _json_response(exc.status, {"message": str(exc)})
        except OSError as exc:
            return _json_response(
                500,
                {
                    "message": f"owned local persistence failed: {exc.strerror or 'I/O error'}"
                },
            )


def _loopback_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
    ):
        raise argparse.ArgumentTypeError(
            "allowed origins must use numeric loopback 127.0.0.1"
        )
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise argparse.ArgumentTypeError(
            "allowed origins must contain only scheme, 127.0.0.1, and port"
        )
    return f"{parsed.scheme}://127.0.0.1:{parsed.port}"


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ThorVIOSCalibrationUI/0.1"

    def _cors_headers(self) -> dict[str, str]:
        origin = self.headers.get("Origin", "")
        allowed = getattr(self.server, "allowed_origins", frozenset())
        if origin and origin in allowed:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Vary": "Origin",
            }
        return {}

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = getattr(self.server, "allowed_origins", frozenset())
        if origin not in allowed:
            self._respond(
                _json_response(
                    403, {"message": "CORS origin is not explicitly allowed"}
                )
            )
            return
        requested_method = self.headers.get("Access-Control-Request-Method", "")
        if requested_method not in {"GET", "POST", "PATCH", "DELETE"}:
            self._respond(
                _json_response(403, {"message": "CORS method is not allowed"})
            )
            return
        requested_headers = {
            item.strip().lower()
            for item in self.headers.get("Access-Control-Request-Headers", "").split(
                ","
            )
            if item.strip()
        }
        if not requested_headers.issubset({"content-type", "streamid"}):
            self._respond(
                _json_response(403, {"message": "CORS headers are not allowed"})
            )
            return
        response = Response(
            204,
            b"",
            "text/plain; charset=utf-8",
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, streamId",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )
        self._respond(response)

    def _handle(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            self._respond(
                _json_response(
                    400,
                    {"message": "absolute URLs, queries, and fragments are forbidden"},
                )
            )
            return
        if self.headers.get("Transfer-Encoding"):
            self._respond(
                _json_response(400, {"message": "transfer encoding is forbidden"})
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(_json_response(400, {"message": "invalid content length"}))
            return
        maximum = (
            MAX_MULTIPART_BYTES
            if self.headers.get_content_type() == "multipart/form-data"
            else MAX_JSON_BYTES
        )
        if length < 0 or length > maximum:
            self._respond(
                _json_response(413, {"message": "request body exceeds its route bound"})
            )
            return
        body = self.rfile.read(length) if length else b""
        application = getattr(self.server, "application")
        self._respond(
            application.dispatch(
                self.command,
                parsed.path,
                body,
                content_type=self.headers.get("Content-Type", ""),
            )
        )

    def _respond(self, response: Response) -> None:
        headers = {**response.headers, **self._cors_headers()}
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header(
            "Content-Length", headers.pop("Content-Length", str(len(response.body)))
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

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
        "persistence": "explicit_local_data_root/ui-projects",
        "client_compatible": [
            "project_crud",
            "partial_sensor_json_patch",
            "persisted_homography",
            "bounded_image_multipart_and_static_media",
            "local_staged_sensor_import",
        ],
        "pending": [
            "invert_image",
            "warped_and_image_zip",
            "upload_web_api",
            "same_origin_proxy_and_ui_route",
        ],
        "provider_egress": "forbidden",
        "runtime_evidence": [],
    }


def serve(data_root: Path, allowed_origins: frozenset[str]) -> None:
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    server.application = Application(LocalUIStore(data_root))
    server.allowed_origins = allowed_origins
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs="?", choices=("plan", "serve", "stage-sensors"), default="plan"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--input", type=Path)
    parser.add_argument(
        "--allowed-origin", action="append", type=_loopback_origin, default=[]
    )
    parser.add_argument("--acknowledgement")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(plan(), sort_keys=True))
        return 0
    if args.data_root is None or not args.data_root.is_absolute():
        print("ERROR: command requires an explicit absolute --data-root")
        return 1
    try:
        if args.command == "stage-sensors":
            if args.project_id is None or args.input is None:
                raise UIError(400, "stage-sensors requires --project-id and --input")
            if (
                not args.input.is_absolute()
                or args.input.is_symlink()
                or not args.input.is_file()
            ):
                raise UIError(
                    400,
                    "stage-sensors input must be an absolute regular non-symlink file",
                )
            manifest = _strict_json_value(args.input.read_bytes())
            result = LocalUIStore(args.data_root).stage_sensors(
                args.project_id, manifest
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.acknowledgement != ACKNOWLEDGEMENT:
            print(f"ERROR: serve requires --acknowledgement {ACKNOWLEDGEMENT}")
            return 1
        serve(args.data_root, frozenset(args.allowed_origin))
    except (OSError, UIError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
