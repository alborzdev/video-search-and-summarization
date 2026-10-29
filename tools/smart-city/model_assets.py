#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage reviewed RF-DETR assets without changing the VSS inference stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = {
    "large": {
        "filename": "rf-detr-large-2026.pth",
        "url": "https://storage.googleapis.com/rfdetr/rf-detr-large-2026.pth",
        "md5": "5cb72153541cbcb9aa6efa26222acc75",
        "sha256": "0f4e20e19a99c0f8a62b5685f57f6c8b5c371c59081feda6752a0561a79ccf38",
        "resolution": 704,
    },
    "small": {
        "filename": "rf-detr-small.pth",
        "url": "https://storage.googleapis.com/rfdetr/small_coco/checkpoint_best_regular.pth",
        "md5": "fb37061c1af7bace359c91b723a8d5c1",
        "sha256": "d81979a9213a2109345158ce9232668df4c1ae52e9b8db3f2ec0a8cbad959b33",
        "resolution": 512,
    },
    "medium": {
        "filename": "rf-detr-medium.pth",
        "url": "https://storage.googleapis.com/rfdetr/medium_coco/checkpoint_best_regular.pth",
        "md5": "7223f764a87b863f02eb8d52bf0ce2ee",
        "sha256": "749ff6071828aaffac63e204c4f4135ed3d6cdae4d702e086c360edc3b5768c8",
        "resolution": 576,
    },
}


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stage(size: str, directory: Path) -> dict:
    asset = ASSETS[size]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset["filename"]
    if target.is_symlink():
        raise RuntimeError("Refusing a model path that redirects through a symlink")
    if not target.exists():
        if shutil.disk_usage(directory).free < 2 * 1024**3:
            raise RuntimeError("At least 2 GiB of staging space is required")
        temporary = target.with_suffix(".partial")
        try:
            with urllib.request.urlopen(asset["url"], timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if digest(temporary, "md5") != asset["md5"]:
                raise RuntimeError("Checkpoint does not match the pinned upstream checksum")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if digest(target, "md5") != asset["md5"]:
        raise RuntimeError("Existing checkpoint checksum does not match")
    sha256 = digest(target, "sha256")
    if asset.get("sha256") and sha256 != asset["sha256"]:
        raise RuntimeError("Existing checkpoint SHA256 does not match")
    receipt = {
        "model": f"RF-DETR-{size}", "package": "rfdetr==1.11.2",
        "license": "Apache-2.0", "url": asset["url"], "path": str(target.resolve()),
        "bytes": target.stat().st_size, "sha256": sha256,
        "upstreamMd5": asset["md5"], "inputResolution": asset["resolution"],
    }
    (directory / f"{size}-checkpoint.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("size", choices=ASSETS)
    parser.add_argument("--directory", type=Path, default=ROOT / ".spark/city/models")
    args = parser.parse_args()
    print(json.dumps(stage(args.size, args.directory), indent=2))


if __name__ == "__main__":
    main()
