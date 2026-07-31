#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate the immutable dependency contract of a Logstash offline pack."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

EXPECTED_GEMS = {
    "logstash-codec-protobuf": "logstash-codec-protobuf-1.3.0-java.gem",
    "google-protobuf": "google-protobuf-3.23.4-java.gem",
    "ruby-protocol-buffers": "ruby-protocol-buffers-1.6.1.gem",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _read_checksum(checksum_file: Path, pack: Path, description: str) -> str:
    if not checksum_file.is_file():
        _fail(f"{description} not found: {checksum_file}")
    checksum_lines = checksum_file.read_text(encoding="utf-8").splitlines()
    if len(checksum_lines) != 1:
        _fail(f"{description} must contain exactly one line")
    match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", checksum_lines[0])
    if match is None or match.group(2) != pack.name:
        _fail(f"{description} must be '<sha256>  <pack-basename>'")
    return match.group(1)


def verify(
    pack: Path,
    checksum_file: Path,
    expected_checksum_file: Path | None = None,
) -> None:
    if not pack.is_file():
        _fail(f"offline pack not found: {pack}")

    generated_digest = _read_checksum(checksum_file, pack, "generated checksum")
    if expected_checksum_file is not None:
        expected_digest = _read_checksum(
            expected_checksum_file, pack, "expected checksum lock"
        )
        if generated_digest != expected_digest:
            _fail(
                "generated checksum does not match expected checksum lock: "
                f"{generated_digest} != {expected_digest}"
            )

    actual = hashlib.sha256(pack.read_bytes()).hexdigest()
    if actual != generated_digest:
        _fail(f"checksum mismatch: expected {generated_digest}, got {actual}")

    try:
        with zipfile.ZipFile(pack) as archive:
            members = archive.namelist()
            bad_paths = [
                name
                for name in members
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            ]
            if bad_paths:
                _fail(f"unsafe archive member: {bad_paths[0]}")
            basenames = {PurePosixPath(name).name for name in members}
    except zipfile.BadZipFile as exc:
        _fail(f"invalid zip archive: {exc}")

    for gem_name, expected_filename in EXPECTED_GEMS.items():
        candidates = sorted(
            name
            for name in basenames
            if name.startswith(f"{gem_name}-") and name.endswith(".gem")
        )
        if candidates != [expected_filename]:
            _fail(
                f"unexpected {gem_name} artifacts: {candidates}; "
                f"expected only {expected_filename}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path)
    parser.add_argument("checksum_file", type=Path)
    parser.add_argument("expected_checksum_file", nargs="?", type=Path)
    args = parser.parse_args()
    try:
        verify(args.pack, args.checksum_file, args.expected_checksum_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"OK: {args.pack.name} has the pinned protobuf dependency set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
