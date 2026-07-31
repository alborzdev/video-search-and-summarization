#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verify the complete Thor SDG offline cache and all artifact checksums."""

import argparse
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


MINIFORGE_NAME = "Miniforge3-25.3.1-0-Linux-aarch64.sh"
MINIFORGE_SHA256 = "a57c9e3d6c0c449c0283fd07e0bfa30d95eb8d547a14e8dc06c606405d01a7f0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksums(cache: Path) -> dict[str, str]:
    sidecar = cache / "SHA256SUMS"
    if not sidecar.is_file():
        raise FileNotFoundError(f"Missing cache checksum sidecar: {sidecar}")
    entries: dict[str, str] = {}
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid SHA256SUMS line: {line!r}")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Unsafe SHA256SUMS path: {relative!r}")
        if relative in entries:
            raise ValueError(f"Duplicate SHA256SUMS entry: {relative}")
        entries[relative] = digest
    return entries


def parse_requirements(path: Path) -> list[tuple[str, str]]:
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator or not name or not version:
            raise ValueError(f"Requirement is not exactly pinned: {line}")
        result.append((re.sub(r"[-_.]+", "_", name).lower(), version.lower()))
    return result


def read_wheel_lock(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        candidate = Path(relative)
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or candidate.is_absolute()
            or candidate.parts[:1] != ("wheels",)
            or len(candidate.parts) != 2
            or candidate.suffix != ".whl"
            or ".." in candidate.parts
        ):
            raise ValueError(f"Invalid committed wheel lock line: {line!r}")
        if relative in entries:
            raise ValueError(f"Duplicate committed wheel lock entry: {relative}")
        entries[relative] = digest
    if not entries:
        raise ValueError(f"Committed wheel lock is empty: {path}")
    return entries


def verify_wheels(cache: Path, pip_requirements: Path, wheel_lock: Path) -> int:
    locked = read_wheel_lock(wheel_lock)
    wheel_dir = cache / "wheels"
    actual = {
        str(path.relative_to(cache)): path
        for path in wheel_dir.glob("*.whl")
        if path.is_file()
    }
    if set(locked) != set(actual):
        unlisted = sorted(set(actual) - set(locked))
        missing = sorted(set(locked) - set(actual))
        raise ValueError(
            f"Committed wheel inventory mismatch; unlisted={unlisted}, missing={missing}"
        )
    for relative, expected in locked.items():
        artifact = actual[relative]
        if artifact.is_symlink():
            raise ValueError(f"Cached wheel must not be a symlink: {artifact}")
        digest = sha256(artifact)
        if digest != expected:
            raise ValueError(
                f"Committed wheel checksum mismatch for {artifact}: "
                f"expected {expected}, got {digest}"
            )

    wheel_names = [Path(relative).name.lower() for relative in locked]
    requirements = parse_requirements(pip_requirements)
    for normalized_name, version in requirements:
        prefix = f"{normalized_name}-{version}-"
        matches = [name for name in wheel_names if name.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one locked wheel for {normalized_name}=={version}, "
                f"got {matches}"
            )
    if len(wheel_names) != len(requirements):
        raise ValueError(
            f"Committed wheel lock has {len(wheel_names)} files for "
            f"{len(requirements)} requirements"
        )
    return len(wheel_names)


def verify(
    cache: Path,
    conda_lock: Path,
    pip_requirements: Path,
    wheel_lock: Path,
) -> tuple[int, int]:
    entries = read_checksums(cache)
    actual_files = {
        str(path.relative_to(cache))
        for path in cache.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(entries) != actual_files:
        missing = sorted(actual_files - set(entries))
        stale = sorted(set(entries) - actual_files)
        raise ValueError(
            f"SHA256SUMS inventory mismatch; unlisted={missing}, missing={stale}"
        )
    for relative, expected in entries.items():
        artifact = cache / relative
        if artifact.is_symlink():
            raise ValueError(f"Cached artifact must not be a symlink: {artifact}")
        actual = sha256(artifact)
        if actual != expected:
            raise ValueError(
                f"Checksum mismatch for {artifact}: expected {expected}, got {actual}"
            )

    installer = cache / MINIFORGE_NAME
    if entries.get(MINIFORGE_NAME) != MINIFORGE_SHA256:
        raise ValueError("The pinned Miniforge installer is absent or has the wrong digest")
    if not installer.is_file():
        raise FileNotFoundError(installer)

    conda_count = 0
    openusd_found = False
    for raw in conda_lock.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("https://"):
            continue
        url, separator, expected = line.partition("#")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Conda lock entry is not SHA-256 pinned: {line}")
        name = unquote(Path(urlparse(url).path).name)
        relative = f"conda/{name}"
        if entries.get(relative) != expected:
            raise ValueError(f"Conda cache does not match lock entry: {name}")
        conda_count += 1
        openusd_found |= name.startswith("openusd-26.05-py310")
    if conda_count == 0 or not openusd_found:
        raise ValueError("Conda lock is empty or lacks OpenUSD 26.05 for Python 3.10")

    return conda_count, verify_wheels(cache, pip_requirements, wheel_lock)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    parser.add_argument("conda_lock", type=Path)
    parser.add_argument("pip_requirements", type=Path)
    parser.add_argument("wheel_lock", type=Path)
    args = parser.parse_args()
    conda_count, wheel_count = verify(
        args.cache.resolve(),
        args.conda_lock.resolve(),
        args.pip_requirements.resolve(),
        args.wheel_lock.resolve(),
    )
    print(
        f"Thor SDG offline cache verified: {conda_count} conda packages, "
        f"{wheel_count} Python wheels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
