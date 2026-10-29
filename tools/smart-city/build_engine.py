#!/usr/bin/env python3
"""Build a device-local RF-DETR engine under the saved VSS memory guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from manage import ROOT, ensure_headroom, hardware_inventory, state_dir


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build(device: str, size: str) -> dict:
    actual = hardware_inventory()
    if actual.get("platform") != device:
        raise RuntimeError(
            "Build engines on the selected actual device after its runtime preflight"
        )
    ensure_headroom(device)
    directory = state_dir(device)
    model = directory / "models" / f"rfdetr-{size}"
    graph = model / f"rfdetr-{size}.onnx"
    export = json.loads((model / "export-receipt.json").read_text())
    if export["onnxSha256"] != digest(graph) or not export["dynamicBatch"]:
        raise RuntimeError("The ONNX artifact does not match its export receipt")
    resolution = {"small": 512, "medium": 576, "large": 704}[size]
    if export["spatialResolution"] != resolution:
        raise RuntimeError("Unexpected model resolution")
    engine = directory / "models" / f"rfdetr-{size}-fp16-b2.engine"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log = directory / "runtime" / f"engine-{size}-{stamp}.log"
    image = f"vss-city-perception:{device}"
    image_info = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image])
    )[0]
    name = f"vss-city-engine-{size}-{os.getpid()}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--runtime",
        "nvidia",
        "--gpus",
        "all",
        "--network",
        "none",
        "--user",
        "1000:1000",
        "--memory",
        "8g",
        "--memory-swap",
        "8g",
        "--cpus",
        "6",
        "-v",
        f"{directory}/models:/models",
        "--entrypoint",
        "/opt/nvidia/nvidia_entrypoint.sh",
        image,
        "/usr/src/tensorrt/bin/trtexec",
        f"--onnx=/models/rfdetr-{size}/rfdetr-{size}.onnx",
        f"--saveEngine=/models/{engine.name}",
        "--fp16",
        f"--minShapes=input:1x3x{resolution}x{resolution}",
        f"--optShapes=input:2x3x{resolution}x{resolution}",
        f"--maxShapes=input:2x3x{resolution}x{resolution}",
        # trtexec defaults unitless pool sizes to MiB. "MiB" is not an
        # accepted suffix and TensorRT 10.16 interprets it as just 2 KiB.
        "--memPoolSize=workspace:2048",
        "--skipInference",
        "--dumpLayerInfo",
        "--profilingVerbosity=layer_names_only",
    ]
    started = time.monotonic()
    peak_duration = 1200
    with log.open("w") as output:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            while process.poll() is None:
                ensure_headroom(device)
                if time.monotonic() - started > peak_duration:
                    raise RuntimeError("Engine build exceeded its 20-minute bound")
                time.sleep(0.5)
            if process.returncode:
                raise RuntimeError(f"Engine build failed; inspect {log}")
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["docker", "stop", "-t", "5", name],
                    capture_output=True,
                    check=False,
                )
                process.terminate()
                process.wait(timeout=10)
    receipt = {
        "schemaVersion": "city.engine-build.v1",
        "device": device,
        "model": size,
        "gpu": actual["gpu"],
        "hostPlatform": actual,
        "builtAt": stamp,
        "seconds": time.monotonic() - started,
        "imageId": image_info["Id"],
        "onnxSha256": digest(graph),
        "engineSha256": digest(engine),
        "command": command,
        "precision": "FP16 internal, FP32 input/output",
        "batchRange": [1, 2],
        "log": str(log.relative_to(ROOT)),
        "qualification": "build-only; inference parity and accuracy are separate",
    }
    (engine.with_suffix(".build.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("spark", "thor"), default="spark")
    parser.add_argument("--size", choices=("small", "medium", "large"), required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.device, args.size), indent=2))
