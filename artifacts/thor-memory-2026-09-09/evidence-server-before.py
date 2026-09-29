#!/usr/bin/env python3
"""Create browser-safe MP4 evidence clips when VIOS cannot remux bad RTSP timestamps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


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
CACHE_ROOT = Path(os.getenv("CACHE_ROOT", "/cache")).resolve()
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "600"))
MAX_CACHE_BYTES = int(os.getenv("MAX_CACHE_BYTES", str(4 * 1024 * 1024 * 1024)))
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")
PREPARE_LOCK = threading.Lock()


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
    upstream_request = Request(
        COSMOS_EMBED_API_URL,
        data=json.dumps(
            {"model": COSMOS_EMBED_MODEL, "text_input": texts}
        ).encode("utf-8"),
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
    embeddings: list[dict[str, object]] = []
    for index, item in enumerate(data):
        vector = item.get("embeddings") if isinstance(item, dict) else None
        if (
            not isinstance(vector, list)
            or not vector
            or any(not isinstance(value, (int, float)) for value in vector)
        ):
            raise RuntimeError("The local Cosmos embedding response was invalid")
        embeddings.append(
            {"embedding": vector, "index": index, "object": "embedding"}
        )
    return {
        "data": embeddings,
        "model": COSMOS_EMBED_MODEL,
        "object": "list",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("startTime and endTime must be ISO-8601 strings")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def local_media_path(vst_path: object) -> Path:
    if not isinstance(vst_path, str) or not vst_path.startswith(f"{VST_PATH_PREFIX}/"):
        raise ValueError("VIOS returned an invalid media path")
    relative = vst_path[len(VST_PATH_PREFIX) :].lstrip("/")
    candidate = (MEDIA_ROOT / relative).resolve()
    if MEDIA_ROOT not in candidate.parents or not candidate.is_file():
        raise ValueError("VIOS media is not available to the clip service")
    return candidate


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


def validate_output(path: Path) -> None:
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
    if float(result.stdout.strip()) <= 0 or path.stat().st_size <= 0:
        raise RuntimeError("Generated clip is empty")


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


def build_clip(stream_id: str, start_time: str, end_time: str) -> tuple[str, str]:
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
            os.utime(output, None)
            output.with_suffix(".json").write_text(
                json.dumps({"sensorId": stream_id}),
                encoding="utf-8",
            )
            return key, start_time

        paths = get_media_paths(stream_id, start_time, end_time)
        source_start = probe_start_time(paths[0])
        offset = max(0.0, start.timestamp() - source_start)
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="evidence-", dir=CACHE_ROOT) as temp_dir:
            temp = Path(temp_dir)
            concat = temp / "inputs.txt"
            concat.write_text(
                "".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in paths),
                encoding="utf-8",
            )
            candidate = temp / "clip.mp4"
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
                *input_args, *output_seek, "-t", f"{duration:.3f}",
                "-map", "0:v:0", "-an", "-fflags", "+genpts",
                "-avoid_negative_ts", "make_zero",
            ]
            copy_command = common + ["-c:v", "copy", "-movflags", "+faststart", str(candidate)]
            try:
                subprocess.run(copy_command, check=True, capture_output=True, timeout=120)
                validate_output(candidate)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, RuntimeError):
                candidate.unlink(missing_ok=True)
                transcode_command = common + [
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(candidate),
                ]
                subprocess.run(transcode_command, check=True, capture_output=True, timeout=300)
                validate_output(candidate)
            candidate.replace(output)
            output.with_suffix(".json").write_text(
                json.dumps({"sensorId": stream_id}),
                encoding="utf-8",
            )
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
        if request_path not in {"/prepare", "/purge", "/v1/embeddings"}:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
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
        except ValueError as error:
            self.json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
        except Exception as error:
            print(f"local support service failed: {type(error).__name__}: {error}", flush=True)
            message = (
                "Text embeddings could not be generated"
                if request_path == "/v1/embeddings"
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
