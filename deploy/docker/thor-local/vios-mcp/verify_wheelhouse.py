#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed verification for the Thor VIOS MCP offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")
SAFE_WHEEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")


class VerificationError(ValueError):
    """The staged wheelhouse does not match its immutable contract."""


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def load_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = REQUIREMENT.fullmatch(line)
        if match is None:
            raise VerificationError(
                f"{path}:{line_number}: dependency must use one exact name==version pin"
            )
        name, version = normalize_name(match.group(1)), match.group(2)
        if name in requirements:
            raise VerificationError(f"duplicate requirement: {name}")
        requirements[name] = version
    if not requirements:
        raise VerificationError("requirements contract is empty")
    return requirements


def load_lock(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != {"schema_version", "platform", "python", "files"}:
        raise VerificationError("wheel lock has unknown or missing top-level keys")
    if payload["schema_version"] != 1:
        raise VerificationError("wheel lock schema_version must be 1")
    if payload["platform"] != "linux-aarch64" or payload["python"] != "cp312":
        raise VerificationError("wheel lock targets the wrong platform or Python ABI")
    files = payload["files"]
    if not isinstance(files, list) or not files:
        raise VerificationError("wheel lock files must be a non-empty list")
    locked: dict[str, dict[str, object]] = {}
    for item in files:
        if not isinstance(item, dict) or set(item) != {"filename", "size", "sha256"}:
            raise VerificationError("wheel lock entry has unknown or missing keys")
        filename, size, digest = item["filename"], item["size"], item["sha256"]
        if not isinstance(filename, str) or SAFE_WHEEL_NAME.fullmatch(filename) is None:
            raise VerificationError(f"unsafe wheel filename in lock: {filename!r}")
        if filename in locked:
            raise VerificationError(f"duplicate wheel lock entry: {filename}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise VerificationError(f"invalid locked size for {filename}")
        if not isinstance(digest, str) or HEX_SHA256.fullmatch(digest) is None:
            raise VerificationError(f"invalid locked SHA-256 for {filename}")
        locked[filename] = item
    if list(locked) != sorted(locked):
        raise VerificationError("wheel lock entries must be sorted by filename")
    return locked


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_identity(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names: set[str] = set()
            metadata_members: list[str] = []
            for item in archive.infolist():
                member = PurePosixPath(item.filename)
                if (
                    item.filename.startswith("/")
                    or "\\" in item.filename
                    or ".." in member.parts
                    or item.filename in names
                ):
                    raise VerificationError(f"unsafe archive member in {path.name}: {item.filename}")
                names.add(item.filename)
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise VerificationError(f"symlink archive member in {path.name}: {item.filename}")
                if len(member.parts) == 2 and member.parts[0].endswith(".dist-info") and member.name == "METADATA":
                    metadata_members.append(item.filename)
            if len(metadata_members) != 1:
                raise VerificationError(f"{path.name} must contain exactly one dist-info/METADATA")
            metadata = BytesParser().parsebytes(archive.read(metadata_members[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise VerificationError(f"invalid wheel archive {path.name}: {exc}") from exc
    name, version = metadata.get("Name"), metadata.get("Version")
    if not name or not version:
        raise VerificationError(f"{path.name} METADATA is missing Name or Version")
    return normalize_name(name), version


def verify(lock_path: Path, requirements_path: Path, wheelhouse: Path) -> int:
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise VerificationError(f"wheelhouse must be a real directory: {wheelhouse}")
    locked = load_lock(lock_path)
    requirements = load_requirements(requirements_path)
    actual: dict[str, os.DirEntry[str]] = {}
    with os.scandir(wheelhouse) as entries:
        for entry in entries:
            if entry.name in actual:
                raise VerificationError(f"duplicate wheelhouse entry: {entry.name}")
            if not entry.is_file(follow_symlinks=False) or entry.is_symlink():
                raise VerificationError(f"wheelhouse entry must be a regular file: {entry.name}")
            if SAFE_WHEEL_NAME.fullmatch(entry.name) is None:
                raise VerificationError(f"unexpected wheelhouse entry: {entry.name}")
            actual[entry.name] = entry
    if set(actual) != set(locked):
        missing = sorted(set(locked) - set(actual))
        extra = sorted(set(actual) - set(locked))
        raise VerificationError(f"wheelhouse membership drift: missing={missing}, extra={extra}")

    identities: dict[str, str] = {}
    for filename in sorted(locked):
        path = wheelhouse / filename
        expected = locked[filename]
        if path.stat(follow_symlinks=False).st_size != expected["size"]:
            raise VerificationError(f"wheel size drift: {filename}")
        if hash_file(path) != expected["sha256"]:
            raise VerificationError(f"wheel SHA-256 drift: {filename}")
        package, version = wheel_identity(path)
        if package in identities:
            raise VerificationError(f"multiple wheels provide package {package}")
        identities[package] = version
    if identities != requirements:
        raise VerificationError(
            f"wheel metadata does not match exact requirements: expected={requirements}, actual={identities}"
        )
    return len(locked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument("--lock", type=Path, default=root / "wheels-linux-aarch64.lock.json")
    parser.add_argument(
        "--requirements", type=Path, default=root / "requirements-linux-aarch64.txt"
    )
    parser.add_argument("--wheelhouse", type=Path, default=root / "wheelhouse")
    args = parser.parse_args()
    try:
        count = verify(args.lock, args.requirements, args.wheelhouse)
    except (OSError, json.JSONDecodeError, VerificationError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] Verified {count} exact CPython 3.12 Linux/AArch64 wheels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
