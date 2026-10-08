#!/usr/bin/env python3
"""Create browser-safe MP4 evidence clips when VIOS cannot remux bad RTSP timestamps."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import UUID


HOST = os.getenv("EVIDENCE_CLIP_HOST", "127.0.0.1")
PORT = int(os.getenv("EVIDENCE_CLIP_PORT", "8098"))
VST_API_URL = os.getenv("VST_API_URL", "http://127.0.0.1:30888/vst/api").rstrip("/")
COSMOS_EMBED_API_URL = os.getenv(
    "COSMOS_EMBED_API_URL",
    "http://127.0.0.1:8017/v1/generate_text_embeddings",
)
COSMOS_EMBED_MODEL = os.getenv(
    "COSMOS_EMBED_MODEL", "cosmos-embed1-448p-anomaly-detection"
)
VST_PATH_PREFIX = os.getenv("VST_PATH_PREFIX", "/home/vst/vst_release/vst_video").rstrip("/")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/media")).resolve()
RECORDING_PATH_PREFIX = os.getenv("RECORDING_PATH_PREFIX", "/home/vst/vst_release/streamer_videos").rstrip("/")
RECORDING_ROOT = Path(os.getenv("RECORDING_ROOT", "/recordings")).resolve()
CACHE_ROOT = Path(os.getenv("CACHE_ROOT", "/cache")).resolve()
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "600"))
MAX_CACHE_BYTES = int(os.getenv("MAX_CACHE_BYTES", str(4 * 1024 * 1024 * 1024)))
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")
PREPARE_LOCK = threading.Lock()
HISTORY_PLANS: dict[str, dict] = {}
NATIVE_CLIP_TIMEOUT_SECONDS = 45
MAX_NATIVE_CLIP_BYTES = min(MAX_CACHE_BYTES, 512 * 1024 * 1024)
APPEARANCE_LOCK = threading.Lock()
MAX_APPEARANCE_FRAME_BYTES = 4 * 1024 * 1024
MAX_APPEARANCE_PNG_BYTES = 1024 * 1024
APPEARANCE_TIMEOUT_SECONDS = 50
PICTURE_LOCK = threading.Lock()
PICTURE_CACHE: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
MAX_PICTURE_CACHE_BYTES = 8 * 1024 * 1024


class AppearanceBusy(RuntimeError):
    pass


def recorded_picture(payload: object) -> bytes:
    """Read retained media on CPU; galleries must not fan out GPU decoders."""
    if not isinstance(payload, dict):
        raise ValueError("A picture request is required")
    sensor = payload.get("sensorId")
    if not isinstance(sensor, str) or not ID_PATTERN.fullmatch(sensor):
        raise ValueError("Invalid sensor ID")
    instant = parse_timestamp(payload.get("timestamp")).astimezone(timezone.utc)
    timestamp = instant.isoformat().replace("+00:00", "Z")
    width, height = payload.get("width", 1280), payload.get("height", 720)
    if any(type(v) is not int or v < 1 or v > limit
           for v, limit in ((width, 1920), (height, 1080))):
        raise ValueError("Invalid picture dimensions")
    key = (sensor, timestamp, width, height)
    if not PICTURE_LOCK.acquire(timeout=45):
        raise AppearanceBusy("Recorded picture service is busy")
    try:
        for cached_key, (expires, _) in list(PICTURE_CACHE.items()):
            if expires < time.monotonic():
                del PICTURE_CACHE[cached_key]
        if key in PICTURE_CACHE:
            PICTURE_CACHE.move_to_end(key)
            return PICTURE_CACHE[key][1]
        end = instant + timedelta(seconds=0.2)
        paths = get_media_paths(sensor, timestamp, end.isoformat().replace("+00:00", "Z"))
        origin = (recording_start(sensor, instant, end)
                  if RECORDING_ROOT in paths[0].parents else probe_start_time(paths[0]))
        if not math.isfinite(origin) or instant.timestamp() < origin - 0.25:
            raise ValueError("Recording does not cover the requested picture")
        offset = max(0.0, instant.timestamp() - origin)
        with tempfile.TemporaryDirectory(prefix="picture-") as directory:
            if len(paths) == 1:
                # VIOS epoch-PTS MKVs can have broken seek indexes that jump
                # past the requested instant. Decode to the instant instead of
                # trusting an input seek and silently returning a later frame.
                inputs = ["-i", str(paths[0])]
                seek = ["-ss", f"{offset:.6f}"]
            else:
                concat = Path(directory) / "inputs.txt"
                concat.write_text("".join(
                    f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
                    for path in paths), encoding="utf-8")
                inputs = ["-f", "concat", "-safe", "0", "-i", str(concat)]
                seek = ["-ss", f"{offset:.6f}"]
            result = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-hwaccel", "none",
                "-threads", "1", "-filter_threads", "1", *inputs, *seek,
                "-map", "0:v:0", "-an", "-frames:v", "1", "-vf",
                f"scale={width}:{height}", "-c:v", "mjpeg", "-threads", "1",
                "-f", "image2pipe", "pipe:1",
            ], check=True, capture_output=True, timeout=15)
        image = result.stdout
        if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9") or len(image) > MAX_APPEARANCE_FRAME_BYTES:
            raise RuntimeError("Recorded picture is unavailable")
        PICTURE_CACHE[key] = (time.monotonic() + 60, image)
        while sum(len(v[1]) for v in PICTURE_CACHE.values()) > MAX_PICTURE_CACHE_BYTES or len(PICTURE_CACHE) > 32:
            PICTURE_CACHE.popitem(last=False)
        return image
    finally:
        PICTURE_LOCK.release()


def appearance_request(payload: object) -> tuple[str, str, tuple[int, int, int, int]]:
    """Accept only a canonical source, instant and raw 1280x720 detector box."""
    if not isinstance(payload, dict):
        raise ValueError("A valid appearance crop request is required")
    sensor = payload.get("sensorId")
    if not isinstance(sensor, str) or len(sensor) != 36:
        raise ValueError("sensorId must be a UUID")
    try:
        sensor = str(UUID(sensor))
    except ValueError as error:
        raise ValueError("sensorId must be a UUID") from error
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise ValueError("timestamp must be an ISO-8601 instant")
    instant = parse_timestamp(timestamp).astimezone(timezone.utc)
    timestamp = instant.isoformat().replace("+00:00", "Z")
    box = payload.get("bbox")
    names = ("leftX", "topY", "rightX", "bottomY")
    if not isinstance(box, dict):
        raise ValueError("bbox must contain raw frame coordinates")
    values = [box.get(name) for name in names]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError("bbox coordinates must be finite numbers")
    left, top, right, bottom = values
    if left >= right or top >= bottom:
        raise ValueError("bbox must have positive width and height")
    left = max(0, min(1280, math.floor(left)))
    top = max(0, min(720, math.floor(top)))
    right = max(0, min(1280, math.ceil(right)))
    bottom = max(0, min(720, math.ceil(bottom)))
    if right <= left or bottom <= top:
        raise ValueError("bbox does not intersect the raw frame")
    return sensor, timestamp, (left, top, right, bottom)


def appearance_clip_frame(sensor: str, timestamp: str, deadline: float) -> Path:
    """Bound the existing clip fallback, including all of its FFmpeg children."""
    if not PREPARE_LOCK.acquire(blocking=False):
        raise AppearanceBusy("Evidence preparation is busy")
    try:
        end = (parse_timestamp(timestamp) + timedelta(seconds=1)).isoformat()
        code = ("import json,server,sys; server.MAX_NATIVE_CLIP_BYTES=16777216; "
                "print(json.dumps(server.build_clip(sys.argv[1],sys.argv[2],sys.argv[3],cpu_only=True)))")
        process = subprocess.Popen(
            [sys.executable, "-c", code, sensor, timestamp, end],
            cwd=str(Path(__file__).resolve().parent), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(timeout=max(0.01, min(35, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise RuntimeError("Appearance clip fallback timed out") from None
        if process.returncode or len(stdout) > 4096:
            raise RuntimeError("Recorded appearance frame is unavailable")
        result = json.loads(stdout)
        if not isinstance(result, list) or len(result) != 2 or not KEY_PATTERN.fullmatch(str(result[0])):
            raise RuntimeError("Appearance clip fallback returned an invalid key")
        path = CACHE_ROOT / f"{result[0]}.mp4"
        if not path.is_file() or path.stat().st_size > MAX_APPEARANCE_FRAME_BYTES * 4:
            raise RuntimeError("Appearance clip fallback exceeded the size limit")
        return path
    finally:
        PREPARE_LOCK.release()


def generate_appearance_crop(payload: object) -> dict[str, str]:
    sensor, timestamp, (left, top, right, bottom) = appearance_request(payload)
    if not APPEARANCE_LOCK.acquire(blocking=False):
        raise AppearanceBusy("Appearance crop service is busy")
    try:
        deadline = time.monotonic() + APPEARANCE_TIMEOUT_SECONDS
        with tempfile.TemporaryDirectory(prefix="appearance-") as directory:
            frame = Path(directory) / "frame.jpg"
            endpoint = (f"{VST_API_URL}/v1/replay/stream/{sensor}/picture?"
                        + urlencode({"startTime": timestamp}))
            try:
                with build_opener(_NoRedirect()).open(
                    Request(endpoint, headers={"Accept": "image/jpeg"}), timeout=8,
                ) as response:
                    advertised = response.headers.get("Content-Length")
                    if advertised is not None and not 0 < int(advertised) <= MAX_APPEARANCE_FRAME_BYTES:
                        raise RuntimeError("Appearance frame exceeds the size limit")
                    chunks = []
                    size = 0
                    picture_deadline = min(deadline, time.monotonic() + 10)
                    while True:
                        if time.monotonic() >= picture_deadline:
                            raise RuntimeError("Appearance frame download timed out")
                        chunk = response.read1(min(65536, MAX_APPEARANCE_FRAME_BYTES + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_APPEARANCE_FRAME_BYTES:
                            raise RuntimeError("Appearance frame exceeds the size limit")
                    data = b"".join(chunks)
                if (not data.startswith(b"\xff\xd8") or len(data) > MAX_APPEARANCE_FRAME_BYTES
                        or (advertised is not None and len(data) != int(advertised))):
                    raise RuntimeError("VIOS returned an invalid appearance frame")
                frame.write_bytes(data)
            except (OSError, ValueError, RuntimeError):
                frame = appearance_clip_frame(sensor, timestamp, deadline)
            output = Path(directory) / "crop.png"
            # Replay pictures may be resized by VIOS. Restore the detector's
            # raw coordinate space before cropping, then cap the model input.
            filters = (f"scale=1280:720,crop={right-left}:{bottom-top}:{left}:{top}:exact=1,"
                       "scale=448:448:force_original_aspect_ratio=decrease")
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-hwaccel", "none",
                "-threads", "1", "-filter_threads", "1", "-max_alloc", "67108864",
                "-i", str(frame), "-vf", filters, "-frames:v", "1", "-an",
                "-c:v", "png", "-threads", "1", "-fs", str(MAX_APPEARANCE_PNG_BYTES), str(output),
            ], check=True, capture_output=True, timeout=max(0.01, min(8, deadline - time.monotonic())))
            if not output.is_file() or not 0 < output.stat().st_size <= MAX_APPEARANCE_PNG_BYTES:
                raise RuntimeError("Appearance crop exceeds the size limit")
            png = output.read_bytes()
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("Appearance crop is not a PNG")
            return {"image_base64": base64.b64encode(png).decode("ascii")}
    finally:
        APPEARANCE_LOCK.release()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def native_media_url(value: object) -> str:
    """Use only VIOS storage paths on the configured VIOS origin.

    VIOS may advertise its public hostname; it never chooses the download host.
    Redirects are also disabled when downloading, so an advertised URL cannot
    cause the exporter to fetch another service or an arbitrary remote host.
    """
    if not isinstance(value, str):
        raise ValueError("VIOS returned no native clip URL")
    api = urlparse(VST_API_URL)
    media = urlparse(value)
    prefix = api.path.removesuffix("/api").rstrip("/") + "/storage/"
    decoded = unquote(media.path)
    if (
        api.scheme not in {"http", "https"}
        or not api.netloc
        or media.scheme not in {"", "http", "https"}
        or not decoded.startswith(prefix)
        or not decoded.lower().endswith(".mp4")
        or ".." in decoded.split("/")
        or "%" in decoded
        or "\\" in decoded
        or any(ord(character) < 32 for character in decoded)
    ):
        raise ValueError("VIOS returned an invalid native storage path")
    return urlunparse((api.scheme, api.netloc, media.path, "", media.query, ""))


def retain_native_clip(stream_id: str, start_time: str, end_time: str, candidate: Path, duration: float) -> None:
    """Retain the same native MP4 route used by evidence playback, if valid."""
    query = urlencode({
        "startTime": start_time, "endTime": end_time, "expiryMinutes": "60",
        "container": "mp4", "disableAudio": "true", "transcode": "full",
    })
    endpoint = f"{VST_API_URL}/v1/storage/file/{quote(stream_id, safe='')}/url?{query}"
    deadline = time.monotonic() + NATIVE_CLIP_TIMEOUT_SECONDS
    opener = build_opener(_NoRedirect())

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("Native clip retention timed out")
        return min(seconds, 20)

    with opener.open(Request(endpoint, headers={"Accept": "application/json"}), timeout=remaining()) as response:
        raw = response.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("VIOS native clip response is too large")
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("VIOS returned an invalid native clip response")
    if payload.get("startTime") is not None:
        actual_start = parse_timestamp(payload["startTime"])
        if abs((actual_start - parse_timestamp(start_time)).total_seconds()) > 0.25:
            raise ValueError("VIOS native clip starts outside the requested interval")
    url = native_media_url(payload.get("videoUrl"))
    with opener.open(Request(url), timeout=remaining()) as response, candidate.open("wb") as output:
        advertised_size = response.headers.get("Content-Length")
        if advertised_size is not None and not 0 < int(advertised_size) <= MAX_NATIVE_CLIP_BYTES:
            raise ValueError("VIOS native clip exceeds the retention size limit")
        size = 0
        while True:
            remaining()
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_NATIVE_CLIP_BYTES:
                raise ValueError("VIOS native clip exceeds the retention size limit")
            output.write(chunk)
        if advertised_size is not None and size != int(advertised_size):
            raise ValueError("VIOS native clip download was incomplete")
    validate_output(candidate, duration)


def generate_text_embeddings(payload: object) -> dict[str, object]:
    """Adapt Cosmos Embed text vectors to NVIDIAEmbeddings' OpenAI contract.

    The local RT-Embed service deliberately exposes ``embeddings`` through
    ``/generate_text_embeddings`` while LangChain's NVIDIA client expects
    ``embedding`` through ``/embeddings``. Keeping this small adapter on the
    loopback-only evidence service lets LVS GraphRAG use the same local model
    without another heavyweight container or any cloud dependency.
    """
    if not isinstance(payload, dict):
        raise ValueError("A valid embedding request is required")
    raw_input = payload.get("input")
    texts = [raw_input] if isinstance(raw_input, str) else raw_input
    if (
        not isinstance(texts, list)
        or not texts
        or len(texts) > 50
        or any(not isinstance(item, str) or not item.strip() for item in texts)
    ):
        raise ValueError("input must contain between 1 and 50 non-empty strings")
    if any(len(item) > 32_768 for item in texts):
        raise ValueError("Embedding input is too long")
    # RT-Embed limits each echoed text to 1,000 characters. LVS summaries can
    # be longer, so embed every chunk and pool them instead of losing the tail.
    chunks = [text[offset:offset + 1000] for text in texts for offset in range(0, len(text), 1000)]
    vectors = []
    for offset in range(0, len(chunks), 50):
        vectors.extend(_embed_text_batch(chunks[offset:offset + 50]))
    embeddings: list[dict[str, object]] = []
    offset = 0
    for index, text in enumerate(texts):
        count = (len(text) + 999) // 1000
        parts = vectors[offset:offset + count]
        if count == 1:
            vector = parts[0]
        else:
            if any(len(part) != len(parts[0]) for part in parts):
                raise RuntimeError("The local Cosmos embedding dimensions differed")
            weights = [len(chunk) for chunk in chunks[offset:offset + count]]
            vector = [sum(part[i] * weight for part, weight in zip(parts, weights)) / sum(weights)
                      for i in range(len(parts[0]))]
            norm = math.sqrt(sum(value * value for value in vector))
            if not math.isfinite(norm) or norm == 0:
                raise RuntimeError("The pooled Cosmos embedding was invalid")
            vector = [value / norm for value in vector]
        offset += count
        embeddings.append({"embedding": vector, "index": index, "object": "embedding"})
    return {
        "data": embeddings,
        "model": COSMOS_EMBED_MODEL,
        "object": "list",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def _embed_text_batch(texts: list[str]) -> list[list[float]]:
    upstream_request = Request(
        COSMOS_EMBED_API_URL,
        data=json.dumps({"model": COSMOS_EMBED_MODEL, "text_input": texts}).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(upstream_request, timeout=60) as response:
            upstream = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError("The local Cosmos embedding model is unavailable") from error
    data = upstream.get("data") if isinstance(upstream, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError("The local Cosmos embedding response was incomplete")
    vectors = []
    for item in data:
        vector = item.get("embeddings") if isinstance(item, dict) else None
        if (
            not isinstance(vector, list)
            or not vector
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in vector)
        ):
            raise RuntimeError("The local Cosmos embedding response was invalid")
        vectors.append(vector)
    return vectors


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("startTime and endTime must be ISO-8601 strings")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def local_media_path(vst_path: object) -> Path:
    if isinstance(vst_path, str):
        for prefix, root in ((VST_PATH_PREFIX, MEDIA_ROOT), (RECORDING_PATH_PREFIX, RECORDING_ROOT)):
            if vst_path.startswith(f"{prefix}/"):
                candidate = (root / vst_path[len(prefix) :].lstrip("/")).resolve()
                if root not in candidate.parents or not candidate.is_file():
                    raise ValueError("VIOS media is not available to the clip service")
                return candidate
    raise ValueError("VIOS returned an invalid media path")


def get_media_paths(stream_id: str, start_time: str, end_time: str) -> list[Path]:
    query = urlencode({"startTime": start_time, "endTime": end_time})
    url = f"{VST_API_URL}/v1/storage/file/{quote(stream_id, safe='')}/path?{query}"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError("VIOS could not resolve the recorded media") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError("No recorded media covers the requested time range")
    paths = [local_media_path(item.get("mediaFilePath")) for item in payload if isinstance(item, dict)]
    if not paths:
        raise ValueError("No readable media covers the requested time range")
    return paths


def probe_start_time(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=start_time",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return float(result.stdout.strip())


def validate_output(path: Path, expected_duration: float) -> None:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    actual = float(result.stdout.strip())
    if not math.isfinite(actual) or actual <= 0 or path.stat().st_size <= 0:
        raise RuntimeError("Generated clip is empty")
    if abs(actual - expected_duration) > 0.25:
        raise RuntimeError("Generated clip does not cover the requested duration")


def recording_start(stream_id: str, start: datetime, end: datetime) -> float:
    """Resolve the wall-clock origin of a file whose media PTS starts at zero."""
    url = f"{VST_API_URL}/v1/storage/{quote(stream_id, safe='')}/timelines"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=20) as response:
        timelines = json.load(response)
    if isinstance(timelines, list):
        for timeline in timelines:
            origin = parse_timestamp(timeline.get("startTime"))
            stop = parse_timestamp(timeline.get("endTime"))
            if origin <= start < end <= stop:
                return origin.timestamp()
    raise ValueError("No recording timeline covers the selected interval")


def purge_cache() -> None:
    clips = sorted(CACHE_ROOT.glob("*.mp4"), key=lambda item: item.stat().st_mtime)
    total = sum(item.stat().st_size for item in clips)
    while clips and total > MAX_CACHE_BYTES:
        stale = clips.pop(0)
        size = stale.stat().st_size
        stale.unlink(missing_ok=True)
        stale.with_suffix(".json").unlink(missing_ok=True)
        total -= size


def purge_source_cache(stream_id: str) -> tuple[int, int]:
    """Remove generated evidence clips belonging to one exact source ID."""
    if not ID_PATTERN.fullmatch(stream_id):
        raise ValueError("Invalid sensor ID")
    removed_files = 0
    removed_bytes = 0
    with PREPARE_LOCK:
        for metadata_path in CACHE_ROOT.glob("*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if metadata.get("sensorId") != stream_id:
                continue
            clip_path = metadata_path.with_suffix(".mp4")
            if clip_path.is_file():
                removed_bytes += clip_path.stat().st_size
                clip_path.unlink(missing_ok=True)
                removed_files += 1
            metadata_path.unlink(missing_ok=True)
    return removed_files, removed_bytes


def cache_identity(path: Path) -> tuple | None:
    """Identity under PREPARE_LOCK; cache writers use that same lock."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Evidence cache contains a nonregular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def preview_cache_history(cutoff: str) -> dict:
    """Freeze old immutable cache pairs; retain every subsequently touched pair."""
    boundary = parse_timestamp(cutoff).timestamp()
    if not math.isfinite(boundary) or boundary > time.time() + 1:
        raise ValueError("History cutoff must be a past timestamp")
    with PREPARE_LOCK:
        now = time.monotonic()
        for token, plan in list(HISTORY_PLANS.items()):
            if plan["expires"] < now:
                del HISTORY_PLANS[token]
        if len(HISTORY_PLANS) >= 8:
            raise ValueError("Too many evidence history previews")
        keys = {
            path.stem for suffix in ("*.mp4", "*.json") for path in CACHE_ROOT.glob(suffix)
            if KEY_PATTERN.fullmatch(path.stem)
        }
        snapshot = {}
        retained = 0
        for key in keys:
            try:
                identities = tuple(cache_identity(CACHE_ROOT / f"{key}.{suffix}") for suffix in ("mp4", "json"))
            except ValueError:
                retained += 1
                continue
            if all(identity is None or identity[3] / 1e9 < boundary for identity in identities):
                snapshot[key] = identities
            else:
                retained += 1
        token = secrets.token_urlsafe(32)
        # The public confirmation expires after five minutes. This private
        # lease also covers the subsequent bounded backend cleanup operation.
        HISTORY_PLANS[token] = {"expires": now + 30 * 60, "snapshot": snapshot, "result": None}
        return {"planToken": token, "count": len(snapshot), "retained": retained}


def clear_cache_history(token: str) -> dict:
    """Compare and unlink frozen cache pairs while excluding concurrent prepare."""
    with PREPARE_LOCK:
        plan = HISTORY_PLANS.get(token)
        if plan is None or plan["expires"] < time.monotonic():
            raise ValueError("Evidence history preview expired or is unknown")
        if plan["result"] is not None:
            return plan["result"]
        deleted = 0
        retained = 0
        for key, expected in plan["snapshot"].items():
            paths = tuple(CACHE_ROOT / f"{key}.{suffix}" for suffix in ("mp4", "json"))
            try:
                current = tuple(cache_identity(path) for path in paths)
            except ValueError:
                retained += 1
                continue
            if current != expected:
                retained += 1
                continue
            for path in paths:
                path.unlink(missing_ok=True)
            deleted += 1
        plan["result"] = {"deleted": deleted, "retained": retained}
        return plan["result"]


def cancel_cache_history(token: str) -> dict:
    """Release an unused preview; cached video and metadata stay untouched."""
    with PREPARE_LOCK:
        HISTORY_PLANS.pop(token, None)
    return {"status": "cancelled"}


def build_clip(stream_id: str, start_time: str, end_time: str, *, cpu_only: bool = False) -> tuple[str, str]:
    if not ID_PATTERN.fullmatch(stream_id):
        raise ValueError("Invalid sensor ID")
    start = parse_timestamp(start_time)
    end = parse_timestamp(end_time)
    duration = (end - start).total_seconds()
    if duration <= 0 or duration > MAX_DURATION_SECONDS:
        raise ValueError(f"Clip duration must be between 0 and {MAX_DURATION_SECONDS} seconds")

    key = hashlib.sha256(f"v2\0{stream_id}\0{start_time}\0{end_time}".encode()).hexdigest()
    output = CACHE_ROOT / f"{key}.mp4"
    with PREPARE_LOCK:
        if output.is_file() and output.stat().st_size > 0:
            try:
                validate_output(output, duration)
            except (subprocess.SubprocessError, ValueError, RuntimeError):
                pass  # Rebuild incomplete clips made by older service versions.
            else:
                os.utime(output, None)
                output.with_suffix(".json").write_text(
                    json.dumps({"sensorId": stream_id}),
                    encoding="utf-8",
                )
                return key, start_time

        CACHE_ROOT.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="evidence-", dir=CACHE_ROOT) as temp_dir:
            temp = Path(temp_dir)
            candidate = temp / "clip.mp4"
            try:
                retain_native_clip(stream_id, start_time, end_time, candidate, duration)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                # Native VIOS playback handles some epoch-PTS MKV recordings
                # that local FFmpeg cannot trim accurately. When native export
                # is unavailable, retain the existing recorded-media fallback.
                candidate.unlink(missing_ok=True)
                paths = get_media_paths(stream_id, start_time, end_time)
                source_start = (
                    recording_start(stream_id, start, end)
                    if RECORDING_ROOT in paths[0].parents
                    else probe_start_time(paths[0])
                )
                offset = max(0.0, start.timestamp() - source_start)
                concat = temp / "inputs.txt"
                concat.write_text(
                    "".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in paths),
                    encoding="utf-8",
                )
                if len(paths) == 1:
                    input_args = ["-ss", f"{offset:.3f}", "-i", str(paths[0])]
                    output_seek: list[str] = []
                else:
                    # The concat demuxer rebases timestamps. Seek after opening it so
                    # the requested offset remains relative to the joined recording.
                    input_args = ["-f", "concat", "-safe", "0", "-i", str(concat)]
                    output_seek = ["-ss", f"{offset:.3f}"]
                common = [
                    "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
                    *(["-hwaccel", "none", "-threads", "1", "-filter_threads", "1"] if cpu_only else []),
                    *input_args, *output_seek, "-t", f"{duration:.3f}",
                    "-map", "0:v:0", "-an", "-fflags", "+genpts",
                    "-avoid_negative_ts", "make_zero",
                ]
                copy_command = common + ["-c:v", "copy", "-movflags", "+faststart", str(candidate)]
                try:
                    subprocess.run(copy_command, check=True, capture_output=True, timeout=120)
                    validate_output(candidate, duration)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, RuntimeError):
                    candidate.unlink(missing_ok=True)
                    transcode_command = common + [
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        *(["-threads", "1"] if cpu_only else []),
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(candidate),
                    ]
                    subprocess.run(transcode_command, check=True, capture_output=True, timeout=300)
                    validate_output(candidate, duration)
            metadata = temp / "metadata.json"
            metadata.write_text(json.dumps({"sensorId": stream_id}), encoding="utf-8")
            candidate.replace(output)
            metadata.replace(output.with_suffix(".json"))
        purge_cache()
    return key, start_time


class Handler(BaseHTTPRequestHandler):
    server_version = "VssEvidenceClip/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep logs useful without ever printing source URLs or request bodies.
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    def json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.json_response(HTTPStatus.OK, {"status": "healthy"})
            return
        match = re.fullmatch(r"/media/([a-f0-9]{64})\.mp4", parsed.path)
        if not match:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        path = CACHE_ROOT / f"{match.group(1)}.mp4"
        if not path.is_file():
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "clip expired"})
            return
        self.serve_media(path)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/media/([a-f0-9]{64})\.mp4", parsed.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = CACHE_ROOT / f"{match.group(1)}.mp4"
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.serve_media(path, send_body=False)

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        if request_path not in {"/prepare", "/picture", "/purge", "/v1/embeddings", "/appearance-crop", "/history/preview", "/history/clear", "/history/cancel"}:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > (4096 if request_path in {"/appearance-crop", "/picture"} else 2_000_000):
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if request_path == "/picture":
                image = recorded_picture(payload)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(image)))
                self.send_header("Cache-Control", "private, max-age=60")
                self.end_headers()
                self.wfile.write(image)
                return
            if request_path == "/appearance-crop":
                self.json_response(HTTPStatus.OK, generate_appearance_crop(payload))
                return
            if request_path.startswith("/history/"):
                token = os.getenv("HISTORY_METADATA_TOKEN", "")
                if not token or not secrets.compare_digest(self.headers.get("X-History-Metadata-Token", ""), token):
                    self.json_response(HTTPStatus.FORBIDDEN, {"error": "History maintenance is not authorized"})
                    return
                if not isinstance(payload, dict):
                    raise ValueError("Invalid history request")
                if request_path == "/history/preview":
                    result = preview_cache_history(str(payload.get("cutoff", "")))
                elif request_path == "/history/cancel":
                    result = cancel_cache_history(str(payload.get("planToken", "")))
                else:
                    result = clear_cache_history(str(payload.get("planToken", "")))
                self.json_response(HTTPStatus.OK, result)
                return
            if request_path == "/v1/embeddings":
                self.json_response(
                    HTTPStatus.OK, generate_text_embeddings(payload)
                )
                return
            if request_path == "/purge":
                removed_files, removed_bytes = purge_source_cache(str(payload.get("sensorId", "")))
                self.json_response(
                    HTTPStatus.OK,
                    {"removedFiles": removed_files, "removedBytes": removed_bytes},
                )
                return
            key, clip_start = build_clip(
                str(payload.get("sensorId", "")),
                payload.get("startTime"),
                payload.get("endTime"),
            )
            self.json_response(HTTPStatus.OK, {"key": key, "startTime": clip_start})
        except AppearanceBusy as error:
            self.json_response(HTTPStatus.TOO_MANY_REQUESTS, {"error": str(error)})
        except ValueError as error:
            self.json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
        except Exception as error:
            print(f"local support service failed: {type(error).__name__}: {error}", flush=True)
            message = (
                "Text embeddings could not be generated"
                if request_path == "/v1/embeddings"
                else "Appearance crop could not be generated"
                if request_path == "/appearance-crop"
                else "Evidence clip could not be generated"
            )
            self.json_response(HTTPStatus.BAD_GATEWAY, {"error": message})

    def serve_media(self, path: Path, send_body: bool = True) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        status = HTTPStatus.OK
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else end
            elif match.group(2):
                length = int(match.group(2))
                start = max(0, size - length)
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, max-age=3600")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        with path.open("rb") as media:
            media.seek(start)
            remaining = length
            while remaining:
                chunk = media.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


if __name__ == "__main__":
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if not MEDIA_ROOT.is_dir():
        raise SystemExit(f"Media root does not exist: {MEDIA_ROOT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
