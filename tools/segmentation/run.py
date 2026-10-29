"""Guarded, offline local Moondream CLI; no HTTP service or implicit downloads."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS = ROOT / ".spark/settings.json"
GUARD = "vss-spark-guard.service"
MAX_IMAGE_PIXELS = 16_000_000


def available_gib():
    return next(int(line.split()[1]) / 2**20 for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:"))


def saved_reserve(path=SETTINGS):
    value = json.loads(Path(path).read_text())["reserve_gib"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise RuntimeError("Saved Spark reserve must be finite and positive.")
    return float(value)


def guard_active():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", GUARD],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0


def admission():
    reserve = saved_reserve()
    if not guard_active():
        raise RuntimeError(f"The existing user guard must be active: {GUARD}")
    available = available_gib()
    if available < reserve:
        raise RuntimeError(f"Need {reserve:g} GiB available (saved reserve); have {available:.2f}.")
    return reserve


def json_default(value):
    if isinstance(value, Path):
        return str(value)
    # Scalar NumPy metadata is safe; refuse to silently expand mask arrays.
    if type(value).__module__.startswith("numpy") and getattr(value, "ndim", None) == 0:
        return value.item()
    raise TypeError(f"Unsupported JSON result type: {type(value).__name__}")


def write_json(path, data):
    def safe(value):
        # Rejected model coordinates can contain NaN/Infinity. Keep evidence of
        # them without emitting invalid JSON or silently converting them to 0.
        if isinstance(value, float) and not math.isfinite(value):
            return {"nonfinite_float": str(value)}
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe(item) for item in value]
        return value

    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(safe(data), indent=2, allow_nan=False, default=json_default) + "\n")
    temporary.replace(path)


def claim_output(path):
    """An exclusive marker also prevents two callers claiming one empty folder."""
    path = Path(path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"Output directory is not empty; choose a new directory: {path}")
    with (path / ".run-lock").open("x") as stream:
        stream.write(str(os.getpid()) + "\n")
    return path


def load_image(path):
    from PIL import Image
    with Image.open(path) as source:
        if source.width < 1 or source.height < 1 or source.width * source.height > MAX_IMAGE_PIXELS:
            raise ValueError("Image must contain between 1 and 16 million pixels")
        # Preserve the file's pixel orientation. Grounding and overlays use this
        # exact raster; no EXIF rotation or resizing is applied behind the caller.
        return source.convert("RGB")


def draw_grounding(image, result, destination):
    from PIL import ImageDraw
    drawing = image.copy()
    draw = ImageDraw.Draw(drawing)
    width, height = drawing.size
    line_width = max(2, round(min(width, height) / 250))
    def pixel(x, y):
        return min(width - 1, x * width), min(height - 1, y * height)

    for index, obj in enumerate(result.get("objects", [])):
        if "box" not in obj:
            continue
        x0, y0, x1, y1 = obj["box"]
        bounds = (*pixel(x0, y0), *pixel(x1, y1))
        draw.rectangle(bounds, outline="#ffbf47", width=line_width)
        draw.text((bounds[0] + 3, bounds[1] + 3), str(index), fill="#ffbf47", stroke_width=1, stroke_fill="black")
    for obj in result.get("points", []) + result.get("objects", []):
        if "point" not in obj:
            continue
        x, y = obj["point"]
        x, y = pixel(x, y)
        radius = max(4, line_width * 2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="#ffbf47", width=line_width)
    drawing.save(destination)


def save_result(image, result, directory):
    """Write actual predictions; no ground-truth inputs or manufactured masks."""
    import numpy as np
    from PIL import Image
    from tools.segmentation.evaluate import as_binary_mask, save_overlay

    started = time.perf_counter()
    directory = Path(directory)
    directory.mkdir()
    saved = {key: copy.deepcopy(value) for key, value in result.items() if key != "objects"}
    saved["objects"] = []
    union = np.zeros((image.height, image.width), dtype=bool)
    mask_count = 0
    for index, obj in enumerate(result.get("objects", [])):
        record = {key: copy.deepcopy(value) for key, value in obj.items() if key != "mask"}
        if "mask" in obj:
            mask = as_binary_mask(obj["mask"])
            if mask.shape != union.shape:
                raise ValueError("Model mask dimensions differ from the original image")
            mask_path = directory / f"mask-{index:03d}.png"
            overlay_path = directory / f"overlay-{index:03d}.png"
            Image.fromarray(mask.astype(np.uint8) * 255).save(mask_path)
            save_overlay(image, mask, overlay_path)
            record["mask_artifact"] = {
                "path": str(mask_path), "overlay": str(overlay_path),
                "pixels": int(mask.sum()), "sha256": hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                "encoding": "grayscale PNG, 0 background / 255 foreground",
            }
            union |= mask
            mask_count += 1
        saved["objects"].append(record)
    # Show the unmodified image on an absence result, rather than inventing a
    # segmentation. The JSON explicitly records whether any masks were made.
    overview = directory / "overlay.png"
    if mask_count:
        save_overlay(image, union, overview)
    else:
        image.save(overview)
    grounding = directory / "grounding.png"
    draw_grounding(image, saved, grounding)
    saved["artifacts"] = {"overlay": str(overview), "grounding_overlay": str(grounding),
                          "mask_count": mask_count, "mask_color": "teal", "grounding_color": "amber"}
    saved["prompt_source"] = "moondream_predicted" if result["operation"] != "describe" else "none"
    saved["accuracy_evaluated"] = False
    saved["artifact_write_ms"] = (time.perf_counter() - started) * 1000
    write_json(directory / "result.json", saved)
    return saved


def run_worker(config, directory, bridge_factory=None):
    """One resident bridge for all requested calls. Injection supports CPU tests."""
    started = time.perf_counter()
    if bridge_factory is None:
        from tools.segmentation.moondream_bridge import MoondreamBridge
        bridge_factory = MoondreamBridge
    image_started = time.perf_counter()
    image = load_image(config["image"])
    image_open_ms = (time.perf_counter() - image_started) * 1000
    directory = Path(directory)
    results = []
    with bridge_factory(model=config["model"], segmenter_name=config["segmenter"],
                        presence_mode=config["presence"], max_objects=config["max_objects"],
                        gb10_compat=config["gb10_compat"]) as bridge:
        for index in range(config["repeat"]):
            operation = getattr(bridge, config["task"])
            if config["task"] == "describe":
                result = operation(image)
            elif config["task"] == "segment":
                result = operation(image, config["object"], grounded_by=config.get("grounded_by", "point"))
            else:
                result = operation(image, config["object"])
            result["call_index"] = index
            result["process_phase"] = "first_call" if index == 0 else "resident_reuse"
            load_ms = result["timings_ms"]["moondream_load"] + result["timings_ms"]["segmenter_load"]
            result["model_load_ms"] = load_ms
            result["call_excluding_model_load_ms"] = max(0, result["timings_ms"]["total"] - load_ms)
            saved = save_result(image, result, directory / f"call-{index:03d}")
            results.append({"call_index": index, "process_phase": result["process_phase"],
                            "status": result["status"], "result": str(directory / f"call-{index:03d}" / "result.json"),
                            "timings_ms": result["timings_ms"], "model_load_ms": load_ms,
                            "call_excluding_model_load_ms": result["call_excluding_model_load_ms"],
                            "artifact_write_ms": saved["artifact_write_ms"],
                            "mask_count": saved["artifacts"]["mask_count"]})
            print(json.dumps({"event": "call_complete", **results[-1]}), flush=True)
    summary = {"task": config["task"], "image": config["image"],
               "input_file_sha256": hashlib.sha256(Path(config["image"]).read_bytes()).hexdigest(),
               "image_open_ms": image_open_ms, "calls": results,
               "worker_total_ms": (time.perf_counter() - started) * 1000,
               "timing_scope": "Serial local calls. First call includes lazy model load. Resident reuse is not a sustained-throughput benchmark. Artifact writes are separate.",
               "accuracy_evaluated": False}
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_initialized():
        summary["cuda_peak_allocated_gib"] = torch.cuda.max_memory_allocated() / 2**30
        summary["cuda_peak_reserved_gib"] = torch.cuda.max_memory_reserved() / 2**30
    write_json(directory / "result.json", summary)
    return summary


def child_environment(directory):
    site = Path(sys.prefix) / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    libs = sorted({str(path) for package in ("nvidia", "nvpl") for path in (site / package).glob("**/lib") if path.is_dir()})
    return dict(os.environ, LD_LIBRARY_PATH=":".join(libs + [os.environ.get("LD_LIBRARY_PATH", "")]),
                PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                HF_HUB_DISABLE_TELEMETRY="1", OMP_NUM_THREADS="4",
                SEGMENTATION_CHILD_OUTPUT=str(directory), SEGMENTATION_PARENT_PID=str(os.getpid()))


def terminate_child(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def supervise(config):
    reserve = admission()
    # Validate decoding and dimensions before claiming an output or loading GPU
    # libraries; the child reopens the same image for actual inference.
    load_image(config["image"])
    directory = claim_output(config["output_dir"])
    config = dict(config, output_dir=str(directory))
    write_json(directory / "settings.json", {**config, "reserve_gib_at_admission": reserve,
               "startup_extra_gib": 30, "runtime_extra_gib": 3, "guard": GUARD,
               "cli_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    print(json.dumps({"output_dir": str(directory), "reserve_gib": reserve}), flush=True)
    began = time.monotonic()
    reason = None
    process = None
    returncode = 1
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, interrupted)
    with (directory / "inference.jsonl").open("w") as out, (directory / "inference.stderr").open("w") as err, (directory / "memory.jsonl").open("w") as memory:
        try:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--_child"],
                                       cwd=ROOT, env=child_environment(directory), stdout=out, stderr=err,
                                       start_new_session=True)
            last_guard_check = began
            while process.poll() is None:
                elapsed = time.monotonic() - began
                # Never relax the admitted floor; respect a later increase too.
                reserve = max(reserve, saved_reserve())
                available = available_gib()
                memory.write(json.dumps({"elapsed_s": elapsed, "available_gib": available, "reserve_gib": reserve}) + "\n")
                memory.flush()
                if available < reserve + 3:
                    reason = "reserve_headroom"
                elif elapsed > config["timeout"]:
                    reason = "timeout"
                elif time.monotonic() - last_guard_check >= 2:
                    last_guard_check = time.monotonic()
                    if not guard_active():
                        reason = "guard_inactive"
                if reason:
                    terminate_child(process)
                    break
                time.sleep(0.2)
            returncode = process.wait()
        except KeyboardInterrupt:
            reason, returncode = "interrupted", 130
        except Exception as exc:
            reason = f"supervisor_error: {type(exc).__name__}: {exc}"
        finally:
            if process is not None:
                terminate_child(process)
            signal.signal(signal.SIGTERM, previous_sigterm)
            receipt = {"returncode": returncode, "child_returncode": process.returncode if process else None,
                       "stop_reason": reason, "elapsed_s": time.monotonic() - began,
                       "output_dir": str(directory), "reserve_gib": reserve}
            write_json(directory / "exit.json", receipt)
    print(json.dumps(receipt), flush=True)
    # A controlled supervisor stop is a failure even if a child exits cleanly.
    return 0 if returncode == 0 and reason is None else (130 if reason == "interrupted" else 1)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("segment", "detect", "point", "describe"), default="segment")
    parser.add_argument("--image", help="Local image; no downloads")
    parser.add_argument("--object", help="Object text, required except for describe")
    parser.add_argument("--model", choices=("moondream2", "moondream3-preview", "moondream3.1-9B-A2B"), default="moondream2")
    parser.add_argument("--segmenter", choices=("edgetam", "sam2.1-tiny"), default="sam2.1-tiny")
    parser.add_argument("--grounded-by", choices=("detect", "point"), help="Actual Moondream box or positive point for segment (default: point)")
    parser.add_argument("--presence", choices=("off", "query"), default="off", help="Optional yes/no filter for segment only; not calibrated absence detection")
    parser.add_argument("--max-objects", type=int, default=3)
    parser.add_argument("--gb10-compat", action="store_true", help="Explicit Moondream3 compatibility patch; not used by Moondream2")
    parser.add_argument("--output-dir", help="New or empty local folder; existing artifacts are never overwritten")
    parser.add_argument("--repeat", type=int, default=1, help="1–10 calls in one resident child; first call includes startup")
    parser.add_argument("--timeout", type=float, default=600, help="Maximum child lifetime, seconds (default 600)")
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._child:
        return args
    if not args.image or not args.output_dir:
        parser.error("--image and --output-dir are required")
    if args.task != "describe" and (not args.object or not args.object.strip() or len(args.object) > 512):
        parser.error("--object must contain 1–512 characters")
    if args.task == "describe" and args.object is not None:
        parser.error("describe uses the scene-description prompt; omit --object")
    if args.task != "segment" and args.presence != "off":
        parser.error("--presence query applies only to segment")
    if args.task != "segment" and args.grounded_by is not None:
        parser.error("--grounded-by applies only to segment; --task point directly runs point grounding")
    if args.grounded_by is None:
        args.grounded_by = "point"
    if not 1 <= args.max_objects <= 3 or not 1 <= args.repeat <= 10:
        parser.error("--max-objects must be 1–3 and --repeat must be 1–10")
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be 1–3600 seconds")
    if (args.model != "moondream2") != args.gb10_compat:
        parser.error("Moondream3 Preview and 3.1 require --gb10-compat; Moondream2 must omit it")
    args.image = str(Path(args.image).expanduser().resolve(strict=True))
    if not Path(args.image).is_file():
        parser.error("--image must be a local file")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args._child:
        if os.environ.get("SEGMENTATION_PARENT_PID") != str(os.getppid()) or not os.environ.get("SEGMENTATION_CHILD_OUTPUT"):
            raise RuntimeError("Internal child mode requires this CLI's active supervisor")
        directory = Path(os.environ["SEGMENTATION_CHILD_OUTPUT"])
        config = json.loads((directory / "settings.json").read_text())
        admission()
        try:
            run_worker(config, directory)
            return 0
        except Exception as exc:
            write_json(directory / "error.json", {"type": type(exc).__name__, "message": str(exc)})
            traceback.print_exc()
            return 1
    config = vars(args)
    config.pop("_child")
    return supervise(config)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Local inference refused or failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
