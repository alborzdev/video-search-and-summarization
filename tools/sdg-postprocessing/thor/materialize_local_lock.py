#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rewrite a checksum-locked conda URL lock to local cache file URLs."""

import argparse
from pathlib import Path
from urllib.parse import unquote, urlparse


def materialize(source: Path, package_dir: Path, output: Path) -> int:
    lines = []
    count = 0
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("https://"):
            lines.append(raw)
            continue
        url, separator, digest = line.partition("#")
        if not separator or len(digest) != 64:
            raise ValueError(f"Conda lock entry is not SHA-256 pinned: {line}")
        name = unquote(Path(urlparse(url).path).name)
        package = (package_dir / name).resolve()
        if not package.is_file():
            raise FileNotFoundError(f"Missing cached conda package: {package}")
        # Conda's explicit-file installer treats a percent-encoded ``!`` as a
        # literal part of the cache-record filename (not as URL escaping).
        # Package paths are controlled, absolute, and contain no whitespace,
        # so preserve the literal conda filename here.
        if any(character.isspace() for character in str(package)):
            raise ValueError(f"Conda package cache path contains whitespace: {package}")
        lines.append(f"file://{package}#{digest}")
        count += 1
    if count == 0:
        raise ValueError(f"No package URLs found in {source}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = materialize(args.source, args.package_dir, args.output)
    print(f"Materialized {count} checksum-locked conda package URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
