"""Resident, loopback-only Moondream2 + SAM 2.1 Tiny inference service.

The HTTP layer is standard-library only. Models load in one background worker;
health probes never enter that worker or synchronize CUDA. No request can name
a file, URL, checkpoint, device, or model. Run using the staged Photon venv.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import suppress
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_IMAGE_BYTES = 2 * 1024**2
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 1024
MAX_BODY_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8192
GUARD = "vss-spark-guard.service"
IDENTITY = {"moondream": "moondream2", "segmenter": "sam2.1-tiny",
            "runtime": "photon", "device": "cuda", "gb10_compat": False}


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def reserve_gib():
    value = json.loads((ROOT / ".spark/settings.json").read_text())["reserve_gib"]
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise RuntimeError("Saved Spark reserve must be finite and nonnegative")
    return float(value)


def available_gib():
    return next(int(line.split()[1]) / 2**20
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:"))


def guard_active():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", GUARD],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=2).returncode == 0


def startup_admission():
    reserve = reserve_gib()
    if not guard_active():
        raise RuntimeError(f"Required Spark guard is inactive: {GUARD}")
    if available_gib() < reserve:
        raise RuntimeError("Need saved reserve available for local vision startup")
    return reserve


def parse_payload(raw):
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RequestError(400, "Body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise RequestError(400, "Body must be a JSON object")
    allowed = {"task", "image_base64", "object", "grounded_by", "presence"}
    if set(body) - allowed:
        raise RequestError(400, "Unsupported request fields")
    task = body.get("task", "segment")
    if task not in ("segment", "detect", "point", "describe"):
        raise RequestError(400, "Unsupported task")
    object_text = body.get("object")
    if task != "describe":
        if (not isinstance(object_text, str) or not object_text.strip()
                or len(object_text) > 512):
            raise RequestError(400, "object must contain 1 to 512 characters")
        object_text = object_text.strip()
    elif object_text is not None:
        raise RequestError(400, "describe does not accept object")
    grounded_by = body.get("grounded_by", "point")
    presence = body.get("presence", "off")
    if grounded_by not in ("point", "detect") or presence not in ("off", "query"):
        raise RequestError(400, "Unsupported grounding or presence mode")
    if task != "segment" and ("grounded_by" in body or "presence" in body):
        raise RequestError(400, "grounded_by and presence apply only to segment")
    encoded = body.get("image_base64")
    if not isinstance(encoded, str) or not encoded:
        raise RequestError(400, "image_base64 must contain raw base64 image bytes")
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise RequestError(413, "Image exceeds 2 MiB")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RequestError(400, "image_base64 is not valid raw base64") from exc
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise RequestError(413, "Image must contain at most 2 MiB")
    return {"task": task, "object": object_text, "grounded_by": grounded_by,
            "presence": presence, "image_bytes": image_bytes}


def decode_image(data):
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP"):
                raise RequestError(415, "Only PNG, JPEG and WebP images are supported")
            if (source.width < 1 or source.height < 1
                    or source.width * source.height > MAX_IMAGE_PIXELS):
                raise RequestError(413, "Image must contain at most 16 megapixels")
            if getattr(source, "n_frames", 1) != 1:
                raise RequestError(415, "Animated images are not supported")
            info = {"source_width": source.width, "source_height": source.height,
                    "format": source.format, "encoded_bytes": len(data),
                    "max_dimension": MAX_IMAGE_DIMENSION, "exif_transposed": True}
            image = ImageOps.exif_transpose(source).convert("RGB")
            info.update(width=image.width, height=image.height)
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            info["resized"] = image.size != (info["width"], info["height"])
            info.update(inference_width=image.width, inference_height=image.height)
            return image, info
    except RequestError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise RequestError(413, "Image dimensions exceed the upload limit") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise RequestError(400, "Image bytes could not be decoded") from exc


def encode_result(result, input_image):
    import numpy as np
    from PIL import Image

    # Keep actual model outputs, without heavyweight source manifests or arrays.
    response = {key: value for key, value in result.items()
                if key not in ("objects", "moondream_receipt", "segmenter_receipt")}
    response["objects"] = []
    for item in result.get("objects", []):
        obj = {key: value for key, value in item.items() if key != "mask"}
        if "mask" in item:
            mask = np.asarray(item["mask"])
            expected = (result["image"]["height"], result["image"]["width"])
            if mask.dtype != np.bool_ or mask.shape != expected:
                raise RuntimeError("Unexpected binary mask shape or type")
            buffer = io.BytesIO()
            Image.fromarray(mask.astype(np.uint8) * 255).save(buffer, format="PNG")
            obj["mask_png_base64"] = base64.b64encode(buffer.getvalue()).decode("ascii")
            obj["mask_encoding"] = "PNG grayscale: 0 background, 255 foreground"
        response["objects"].append(obj)
    response["input_image"] = input_image
    response["model_identity"] = dict(IDENTITY)
    response["accuracy_evaluated"] = False
    return response


def safe_json(value):
    """Reject arbitrary objects/arrays; preserve rejected nonfinite coordinates."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": str(value)}
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(item) for item in value]
    return value


def create_warmed_bridge():
    from PIL import Image
    from tools.segmentation.moondream_bridge import MoondreamBridge
    from tools.segmentation.adapter import load

    bridge = MoondreamBridge(model="moondream2", segmenter_name="sam2.1-tiny",
                             max_objects=3, presence_mode="off", gb10_compat=False)
    try:
        neutral = Image.new("RGB", (64, 64), (127, 127, 127))
        bridge.describe(neutral)
        # Warmup must not depend on a neutral fixture producing a detection.
        # Attach the same adapter that subsequent bridge requests will reuse.
        segmenter = load("sam2.1-tiny", device="cuda")
        segmenter.set_image(neutral)
        segmenter.predict(points=[[0.5, 0.5]], labels=[1], multimask=True)
        bridge._segmenter = segmenter
        return bridge
    except Exception:
        bridge.close()
        raise


class Runtime:
    def __init__(self, token, admitted_reserve, *, factory=create_warmed_bridge,
                 fatal=None):
        self.token = token
        self.reserve = admitted_reserve
        self.factory = factory
        self.fatal = fatal or self._exit
        self.gate = threading.Lock()
        self.state_lock = threading.Lock()
        self.stopping = threading.Event()
        self.state, self.error, self.bridge = "warming", None, None
        self.started = time.monotonic()
        self.warmup_ms = None

    @staticmethod
    def _exit(message):
        print(json.dumps({"event": "local_vision_exit", "reason": message}), file=sys.stderr, flush=True)
        os._exit(75)

    def health(self):
        with self.state_lock:
            result = {"ready": self.state == "ready", "status": self.state,
                      "model": "moondream2", "segmenter": "sam2.1-tiny", "runtime": "photon",
                      "busy": self.gate.locked(), "uptime_s": round(time.monotonic() - self.started, 3)}
            if self.warmup_ms is not None:
                result["warmup_ms"] = self.warmup_ms
            if self.error is not None:
                result["error"] = self.error
            return result

    def fail(self, message):
        with self.state_lock:
            self.state, self.error = "failed", message
        self.stopping.set()
        self.fatal(message)

    def check_memory(self):
        saved = reserve_gib()
        with self.state_lock:
            self.reserve = max(self.reserve, saved)
            reserve = self.reserve
        if available_gib() < reserve + 3:
            raise RuntimeError("Available memory fell below saved reserve + 3 GiB")

    def warm(self):
        started = time.perf_counter()
        try:
            with self.gate:
                self.check_memory()
                bridge = self.factory()
                self.check_memory()
                if self.stopping.is_set():
                    bridge.close()
                    return
                with self.state_lock:
                    self.bridge = bridge
                    self.warmup_ms = (time.perf_counter() - started) * 1000
                    self.state = "ready"
        except Exception as exc:
            traceback.print_exc()
            self.fail(f"Warmup failed: {type(exc).__name__}: {exc}")

    def watchdog(self):
        next_guard = 0.0
        while not self.stopping.wait(0.5):
            try:
                self.check_memory()
                if time.monotonic() >= next_guard:
                    next_guard = time.monotonic() + 2
                    if not guard_active():
                        raise RuntimeError("Required Spark guard became inactive")
            except Exception as exc:
                self.fail(f"Watchdog stopped service: {type(exc).__name__}: {exc}")
                return

    def start(self):
        threading.Thread(target=self.watchdog, name="vision-watchdog", daemon=True).start()
        threading.Thread(target=self.warm, name="vision-warmup", daemon=True).start()

    def infer(self, raw):
        """Caller holds the one nonblocking request gate through body + inference."""
        started = time.perf_counter()
        try:
            self.check_memory()
        except Exception as exc:
            self.fail(f"Request admission stopped service: {type(exc).__name__}: {exc}")
            raise RequestError(503, "Local vision stopped for memory headroom") from exc
        payload = parse_payload(raw)
        image, info = decode_image(payload["image_bytes"])
        preparation_ms = (time.perf_counter() - started) * 1000
        operation = getattr(self.bridge, payload["task"])
        if payload["task"] == "segment":
            self.bridge.presence_mode = payload["presence"]
            result = operation(image, payload["object"], grounded_by=payload["grounded_by"])
        elif payload["task"] == "describe":
            result = operation(image)
        else:
            result = operation(image, payload["object"])
        response = encode_result(result, info)
        response["service_timings_ms"] = {"image_prepare": preparation_ms,
            "total": (time.perf_counter() - started) * 1000}
        response["process_phase"] = "resident_reuse"
        return response


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        # Never log uploaded images, object queries, or authentication headers.
        return

    @property
    def runtime(self):
        return self.server.runtime

    def respond(self, status, value):
        data = json.dumps(safe_json(value), allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if status == 429:
            self.send_header("Retry-After", "1")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path not in ("/health", "/healthz", "/ready", "/readyz"):
            self.respond(404, {"error": "Not found"})
            return
        health = self.runtime.health()
        status = 503 if self.path in ("/ready", "/readyz") and not health["ready"] else 200
        self.respond(status, health)

    def do_POST(self):
        acquired = False
        try:
            if self.path != "/infer":
                raise RequestError(404, "Not found")
            supplied = self.headers.get("X-VSS-Model-Token", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), self.runtime.token.encode("ascii")):
                raise RequestError(401, "Invalid model token")
            if not self.runtime.health()["ready"]:
                raise RequestError(503, "Models are not ready")
            if self.headers.get("Transfer-Encoding"):
                raise RequestError(400, "Chunked bodies are not accepted")
            if self.headers.get_content_type() != "application/json":
                raise RequestError(415, "Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as exc:
                raise RequestError(411, "Content-Length is required") from exc
            if length < 1 or length > MAX_BODY_BYTES:
                raise RequestError(413, "Request body exceeds the upload limit")
            acquired = self.runtime.gate.acquire(blocking=False)
            if not acquired:
                raise RequestError(429, "The local inference worker is busy")
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise RequestError(400, "Incomplete request body")
            response = self.runtime.infer(raw)
            self.respond(200, response)
        except RequestError as exc:
            self.respond(exc.status, {"error": str(exc)})
        except (TimeoutError, ConnectionError, BrokenPipeError):
            with suppress(OSError):
                self.respond(408, {"error": "Request connection timed out or closed"})
        except Exception:
            traceback.print_exc()
            with suppress(OSError):
                self.respond(500, {"error": "Local inference failed"})
        finally:
            if acquired:
                self.runtime.gate.release()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, runtime):
        self.runtime = runtime
        super().__init__(address, Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, choices=[8026], default=8026)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text().strip()
    if len(token) < 24 or not token.isascii() or any(ch.isspace() for ch in token):
        raise RuntimeError("Model token must be at least 24 non-whitespace ASCII characters")
    admitted = startup_admission()
    runtime = Runtime(token, admitted)
    server = Server((args.host, args.port), runtime)
    runtime.start()
    print(json.dumps({"event": "local_vision_listening", "host": args.host,
                      "port": args.port, "reserve_gib": admitted}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        runtime.stopping.set()
        server.server_close()
        if runtime.gate.acquire(blocking=False):
            try:
                if runtime.bridge is not None:
                    runtime.bridge.close()
            finally:
                runtime.gate.release()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Local vision server refused startup: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
