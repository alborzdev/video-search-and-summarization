#!/usr/bin/env python3
"""Exercise a namespaced VIOS upload/download/delete transaction on Thor."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid


BASE = "http://127.0.0.1:30888/vst/api/v1"
MAX_RESPONSE = 16 * 1024 * 1024
TIMESTAMP = "2025-01-01T00:00:00.000Z"
CAPABILITY_ID = "behavior.vios.byte-identical-download"


class QualificationError(RuntimeError):
    """The bounded runtime transaction did not satisfy its contract."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON in {label}: {value}")
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON response: {label}") from exc


def _contains_string(value: Any, target: str) -> bool:
    if isinstance(value, str):
        return value == target or target in value
    if isinstance(value, list):
        return any(_contains_string(item, target) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_string(key, target) or _contains_string(item, target)
            for key, item in value.items()
        )
    return False


def _stale_file_sensor_metadata(
    sensors: Any, files: Any, sensor_id: str, file_id: str
) -> bool:
    """Return true only after storage deletion left owned sensor metadata behind."""
    return _contains_string(sensors, sensor_id) and not _contains_string(files, file_id)


class Client:
    def __init__(self, base: str = BASE) -> None:
        if base != BASE:
            raise QualificationError("the VIOS qualifier is fixed to the loopback ingress")
        self.base = base
        self.receipts: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        if not path.startswith("/") or "#" in path:
            raise QualificationError("unsafe HTTP path")
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers=headers or {},
        )
        try:
            response = urllib.request.urlopen(request, timeout=20)
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
            response_headers = response.headers
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE + 1)
            response_headers = exc.headers
        except (OSError, urllib.error.URLError) as exc:
            raise QualificationError(f"VIOS request failed: {method} {path}") from exc
        if len(raw) > MAX_RESPONSE:
            raise QualificationError(f"oversized VIOS response: {method} {path}")
        self.receipts.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "content_type": (response_headers.get("Content-Type") or "").split(";", 1)[0],
            }
        )
        return status, raw

    def json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] = {200},
    ) -> tuple[int, Any]:
        status, raw = self.request(method, path, body=body, headers=headers)
        if status not in expected:
            raise QualificationError(
                f"unexpected VIOS status {status}: {method} {path}"
            )
        return status, _strict_json(raw, f"{method} {path}")

def _fixture(path: Path) -> dict[str, Any]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x120:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000",
        "-t",
        "2",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-bf",
        "0",
        "-g",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        str(path),
    ]
    try:
        subprocess.run(command, check=True, timeout=30)
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                (
                    "stream=codec_name,codec_type,width,height,has_b_frames,"
                    "r_frame_rate,sample_rate,channels"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("failed to materialize the bounded media fixture") from exc
    streams = _strict_json(probe, "fixture ffprobe").get("streams")
    if not isinstance(streams, list) or len(streams) != 2:
        raise QualificationError("fixture does not contain exactly one video and audio stream")
    video = [item for item in streams if item.get("codec_type") == "video"]
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    if (
        len(video) != 1
        or video[0].get("codec_name") != "h264"
        or video[0].get("has_b_frames") != 0
        or video[0].get("width") != 160
        or video[0].get("height") != 120
        or len(audio) != 1
        or audio[0].get("codec_name") != "aac"
        or audio[0].get("sample_rate") != "48000"
    ):
        raise QualificationError("fixture codec contract differs")
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": _sha(raw), "streams": streams}


def _timeline_bounds(value: Any) -> tuple[str, str]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
    elif isinstance(value, dict):
        for item in value.values():
            if isinstance(item, list):
                candidates.extend(entry for entry in item if isinstance(entry, dict))
    for item in candidates:
        start = item.get("startTime")
        end = item.get("endTime")
        if isinstance(start, str) and isinstance(end, str) and start < end:
            return start, end
    raise QualificationError("uploaded stream has no valid timeline range")


def _probe_media(raw: bytes, label: str) -> dict[str, Any]:
    if not raw:
        raise QualificationError(f"empty {label} response")
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height:format=duration",
                "-of",
                "json",
                "pipe:0",
            ],
            input=raw,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"failed to probe {label} response") from exc
    probe = _strict_json(result.stdout, f"{label} ffprobe")
    streams = probe.get("streams")
    if not isinstance(streams, list) or not streams:
        raise QualificationError(f"{label} response has no media stream")
    return probe


def _interior_clip_bounds(start: str, end: str) -> tuple[str, str]:
    try:
        start_value = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_value = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualificationError("timeline bounds are not ISO-8601 timestamps") from exc
    if (end_value - start_value).total_seconds() < 1.5:
        raise QualificationError("timeline is too short for a distinct interior clip")
    clip_start = start_value + timedelta(milliseconds=400)
    clip_end = end_value - timedelta(milliseconds=400)
    return (
        clip_start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        clip_end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )


def _decode_first_rgb(raw: bytes, label: str) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            input=raw,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"failed to decode {label}") from exc
    if not result.stdout:
        raise QualificationError(f"decoded {label} is empty")
    return result.stdout


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise QualificationError("unsafe receipt output")
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def execute() -> dict[str, Any]:
    client = Client()
    token = uuid.uuid4().hex
    filename = f"vss_qual_vios_lifecycle_{token}.mp4"
    sensor_id: str | None = None
    stream_id: str | None = None
    file_id: str | None = None
    cleanup_attempts: list[dict[str, Any]] = []
    pre_sensors: Any = None
    pre_files: Any = None
    timeline: tuple[str, str] | None = None
    clip: bytes | None = None
    clip_probe: dict[str, Any] | None = None
    snapshot: bytes | None = None
    snapshot_probe: dict[str, Any] | None = None
    snapshot_rgb_mae: float | None = None
    primary_error: Exception | None = None

    with tempfile.TemporaryDirectory(prefix="vss-vios-file-lifecycle-") as directory:
        fixture_path = Path(directory) / filename
        fixture = _fixture(fixture_path)
        try:
            _, pre_sensors = client.json("GET", "/sensor/list")
            _, pre_files = client.json("GET", "/storage/file/list")
            if _contains_string(pre_sensors, filename) or _contains_string(
                pre_files, filename
            ):
                raise QualificationError("qualification namespace already exists")

            upload_path = (
                "/storage/file/"
                + urllib.parse.quote(filename, safe="")
                + "?timestamp="
                + urllib.parse.quote(TIMESTAMP, safe="")
            )
            fixture_bytes = fixture_path.read_bytes()
            upload_headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(fixture_bytes)),
            }
            _, upload = client.json(
                "PUT",
                upload_path,
                body=fixture_bytes,
                headers=upload_headers,
                expected={200, 201},
            )
            if not isinstance(upload, dict):
                raise QualificationError("upload response is not an object")
            sensor_id = upload.get("sensorId")
            stream_id = upload.get("streamId")
            file_id = upload.get("id")
            if (
                not all(isinstance(value, str) and value for value in (sensor_id, stream_id, file_id))
                or upload.get("filename") != Path(filename).stem
                or upload.get("bytes") != fixture["bytes"]
            ):
                raise QualificationError(
                    "upload response identity differs: "
                    f"keys={sorted(upload)}, "
                    f"filename={upload.get('filename')!r}, "
                    f"bytes={upload.get('bytes')!r}"
                )

            duplicate_status, _ = client.json(
                "PUT",
                upload_path,
                body=fixture_bytes,
                headers=upload_headers,
                expected={409},
            )
            if duplicate_status != 409:
                raise QualificationError("duplicate v2 upload was not rejected")

            quoted_sensor = urllib.parse.quote(sensor_id, safe="")
            quoted_stream = urllib.parse.quote(stream_id, safe="")
            quoted_file = urllib.parse.quote(file_id, safe="")
            _, timelines = client.json("GET", f"/storage/{quoted_stream}/timelines")
            timeline = _timeline_bounds(timelines)
            _, file_list = client.json("GET", f"/storage/file/{quoted_sensor}/list")
            _, file_path = client.json(
                "GET", f"/storage/file/path?id={quoted_file}&metadata=true"
            )
            _, media_info = client.json(
                "GET", f"/storage/file/mediainfo?id={quoted_file}"
            )
            if not all(
                _contains_string(value, expected)
                for value, expected in (
                    (file_list, file_id),
                    (file_path, file_id),
                )
            ):
                raise QualificationError("uploaded file is absent from a VIOS readback")
            if not isinstance(media_info, dict) or media_info.get("Width") != 160 or media_info.get("Height") != 120:
                raise QualificationError("VIOS media-info dimensions differ")

            download_status, download = client.request(
                "GET", f"/storage/file?id={quoted_file}"
            )
            if download_status != 200:
                raise QualificationError("full-file download failed")
            if _sha(download) != fixture["sha256"] or len(download) != fixture["bytes"]:
                raise QualificationError("full-file download is not byte-identical")

            clip_bounds = _interior_clip_bounds(*timeline)
            encoded_start = urllib.parse.quote(clip_bounds[0], safe="")
            encoded_end = urllib.parse.quote(clip_bounds[1], safe="")
            clip_status, clip = client.request(
                "GET",
                (
                    f"/storage/file/{quoted_stream}?startTime={encoded_start}"
                    f"&endTime={encoded_end}&container=mp4&disableAudio=true"
                    "&transcode=full"
                ),
            )
            if clip_status != 200:
                raise QualificationError("time-bounded MP4 clip download failed")
            clip_probe = _probe_media(clip, "time-bounded clip")
            clip_video = [
                item
                for item in clip_probe["streams"]
                if item.get("codec_type") == "video"
            ]
            if len(clip_video) != 1 or clip_video[0].get("codec_name") != "h264":
                raise QualificationError("time-bounded clip video contract differs")
            if _sha(clip) == fixture["sha256"]:
                raise QualificationError("generated clip is not distinct from the full file")

            snapshot_start = urllib.parse.quote(timeline[0], safe="")
            snapshot_status, snapshot = client.request(
                "GET",
                (
                    f"/storage/stream/{quoted_stream}/picture"
                    f"?startTime={snapshot_start}"
                ),
            )
            if snapshot_status != 200:
                raise QualificationError("historical snapshot download failed")
            snapshot_probe = _probe_media(snapshot, "historical snapshot")
            snapshot_video = [
                item
                for item in snapshot_probe["streams"]
                if item.get("codec_type") == "video"
            ]
            if (
                len(snapshot_video) != 1
                or snapshot_video[0].get("codec_name") != "mjpeg"
                or snapshot_video[0].get("width") != 160
                or snapshot_video[0].get("height") != 120
            ):
                raise QualificationError("historical snapshot image contract differs")
            source_rgb = _decode_first_rgb(fixture_bytes, "owned source fixture")
            snapshot_rgb = _decode_first_rgb(snapshot, "historical snapshot")
            if len(source_rgb) != len(snapshot_rgb):
                raise QualificationError("snapshot pixel dimensions differ from owned fixture")
            snapshot_rgb_mae = sum(
                abs(source - observed)
                for source, observed in zip(source_rgb, snapshot_rgb, strict=True)
            ) / len(source_rgb)
            if snapshot_rgb_mae > 20.0:
                raise QualificationError("snapshot is not correlated to the owned visual marker")
        except Exception as exc:  # cleanup must still run for any bounded failure
            primary_error = exc
        finally:
            if stream_id and sensor_id:
                if timeline is None:
                    try:
                        _, current_timeline = client.json(
                            "GET",
                            f"/storage/{urllib.parse.quote(stream_id, safe='')}/timelines",
                        )
                        timeline = _timeline_bounds(current_timeline)
                    except Exception as exc:
                        cleanup_attempts.append(
                            {"operation": "timeline-read", "result": "failed", "error": str(exc)}
                        )
                if timeline is not None:
                    delete_path = (
                        f"/storage/file/{urllib.parse.quote(stream_id, safe='')}"
                        f"?startTime={urllib.parse.quote(timeline[0], safe='')}"
                        f"&endTime={urllib.parse.quote(timeline[1], safe='')}"
                    )
                    try:
                        status, _ = client.json("DELETE", delete_path, expected={200})
                        cleanup_attempts.append(
                            {"operation": "stream-range-delete", "result": "passed", "status": status}
                        )
                    except Exception as exc:
                        cleanup_attempts.append(
                            {"operation": "stream-range-delete", "result": "failed", "error": str(exc)}
                        )
            if file_id:
                try:
                    _, current_files = client.json("GET", "/storage/file/list")
                    if _contains_string(current_files, file_id):
                        status, _ = client.json(
                            "DELETE",
                            f"/storage/file?id={urllib.parse.quote(file_id, safe='')}",
                            expected={200},
                        )
                        cleanup_attempts.append(
                            {"operation": "file-id-delete-fallback", "result": "passed", "status": status}
                        )
                except Exception as exc:
                    cleanup_attempts.append(
                        {"operation": "file-id-delete-fallback", "result": "failed", "error": str(exc)}
                    )

        post_sensors: Any = None
        post_files: Any = None
        if sensor_id and file_id:
            for _ in range(20):
                _, post_sensors = client.json("GET", "/sensor/list")
                _, post_files = client.json("GET", "/storage/file/list")
                if not _contains_string(post_sensors, sensor_id) and not _contains_string(
                    post_files, file_id
                ):
                    break
                time.sleep(0.5)
            if _stale_file_sensor_metadata(
                post_sensors, post_files, sensor_id, file_id
            ):
                try:
                    status, deleted = client.json(
                        "DELETE",
                        f"/sensor/{urllib.parse.quote(sensor_id, safe='')}",
                        expected={200},
                    )
                    if deleted is not True:
                        raise QualificationError(
                            "stale owned file-sensor metadata delete was not acknowledged"
                        )
                    cleanup_attempts.append(
                        {
                            "operation": "stale-file-sensor-metadata-delete",
                            "result": "passed",
                            "status": status,
                        }
                    )
                except Exception as exc:
                    cleanup_attempts.append(
                        {
                            "operation": "stale-file-sensor-metadata-delete",
                            "result": "failed",
                            "error": str(exc),
                        }
                    )
                for _ in range(20):
                    _, post_sensors = client.json("GET", "/sensor/list")
                    _, post_files = client.json("GET", "/storage/file/list")
                    if not _contains_string(
                        post_sensors, sensor_id
                    ) and not _contains_string(post_files, file_id):
                        break
                    time.sleep(0.5)
        else:
            _, post_sensors = client.json("GET", "/sensor/list")
            _, post_files = client.json("GET", "/storage/file/list")

        cleanup_passed = (
            sensor_id is not None
            and file_id is not None
            and not _contains_string(post_sensors, sensor_id)
            and not _contains_string(post_files, file_id)
            and _canonical(pre_sensors) == _canonical(post_sensors)
            and _canonical(pre_files) == _canonical(post_files)
        )
        if not cleanup_passed:
            raise QualificationError("owned file cleanup or exact non-owned restoration failed")
        if primary_error is not None:
            if isinstance(primary_error, QualificationError):
                raise primary_error
            raise QualificationError("runtime transaction failed") from primary_error

        return {
            "schema_version": 1,
            "qualification_id": "thor-vss-3.2.1-vios-file-lifecycle-runtime",
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed",
            "runtime_evidence": True,
            "target": {
                "product_version": "3.2.1",
                "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            },
            "capability_results": {
                CAPABILITY_ID: "passed_current",
                "vios_namespaced_file_lifecycle": "passed_current",
            },
            "bounds": {
                "endpoint": BASE,
                "loopback_only": True,
                "warehouse_sample_bundle_used": False,
                "rtsp_sensor_added": False,
                "agent_generate_called": False,
                "existing_sensor_count": len(pre_sensors),
                "fixture": fixture,
            },
            "observations": {
                "upload_filename": filename,
                "upload_file_id": file_id,
                "upload_sensor_id": sensor_id,
                "upload_stream_id": stream_id,
                "timeline": {"startTime": timeline[0], "endTime": timeline[1]},
                "duplicate_v2_upload_status": 409,
                "upload_response_bytes": fixture["bytes"],
                "full_download_bytes": fixture["bytes"],
                "full_download_sha256": fixture["sha256"],
                "clip_download": {
                    "bytes": len(clip),
                    "sha256": _sha(clip),
                    "probe": clip_probe,
                    "requested_bounds": {
                        "startTime": clip_bounds[0],
                        "endTime": clip_bounds[1],
                    },
                    "distinct_from_full_file": True,
                    "time_bounded": True,
                },
                "historical_snapshot": {
                    "bytes": len(snapshot),
                    "sha256": _sha(snapshot),
                    "probe": snapshot_probe,
                    "source_rgb_mean_absolute_error": snapshot_rgb_mae,
                    "visual_marker_correlated": True,
                    "timestamp_from_runtime_timeline": True,
                },
                "registration_readbacks": [
                    "stream_timeline",
                    "sensor_file_list",
                    "file_path_and_metadata",
                    "media_info",
                    "full_file",
                    "time_bounded_mp4_clip",
                    "historical_snapshot",
                ],
                "pre_sensor_list_sha256": _sha(_canonical(pre_sensors)),
                "post_sensor_list_sha256": _sha(_canonical(post_sensors)),
                "pre_file_list_sha256": _sha(_canonical(pre_files)),
                "post_file_list_sha256": _sha(_canonical(post_files)),
            },
            "cleanup": {
                "result": "passed",
                "attempts": cleanup_attempts,
                "owned_sensor_absent": True,
                "owned_file_absent": True,
                "exact_sensor_list_restored": True,
                "exact_file_list_restored": True,
                "temporary_fixture_removed_by_context": True,
            },
            "requests": client.receipts,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the bounded mutation")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "failed", "error": "--execute is required"}))
        return 2
    try:
        receipt = execute()
        _write_receipt(args.output.resolve(), receipt)
    except (OSError, QualificationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "output": str(args.output),
                "receipt_sha256": _sha(args.output.read_bytes()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
