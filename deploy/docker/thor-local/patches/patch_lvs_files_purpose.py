#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backport upstream main's fail-closed LVS file-purpose validation to GA."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import stat
import sys
import tempfile


DEFAULT_TARGET = Path("/opt/nvidia/via/via-engine/via_server.py")

OLD_BLOCK = '''        async def list_video_files(
            purpose: Annotated[
                str,
                Query(
                    description="Only return files with the given purpose.",
                    max_length=36,
                    pattern=r"^[a-zA-Z]*$",
                ),
            ],
        ) -> ListFilesResponse:
            if purpose != "vision":
                return {"data": [], "object": "list"}
'''

NEW_BLOCK = '''        async def list_video_files(
            purpose: Annotated[
                Purpose,
                Query(
                    description="Only return files with the given purpose. Must be 'vision'.",
                ),
            ],
        ) -> ListFilesResponse:
'''


def patch_source(source: str) -> str:
    count = source.count(OLD_BLOCK)
    if count != 1:
        raise RuntimeError(f"Expected one LVS file-purpose patch marker, found {count}")
    patched = source.replace(OLD_BLOCK, NEW_BLOCK, 1)
    ast.parse(patched)
    return patched


def patch_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"LVS via_server target is not a regular file: {path}")
    before = path.stat(follow_symlinks=False)
    source = path.read_text(encoding="utf-8")
    after = path.stat(follow_symlinks=False)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError("LVS via_server target changed while it was being read")
    patched = patch_source(source)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".thor-purpose",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(patched)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(before.st_mode), follow_symlinks=False)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        raise RuntimeError("usage: patch_lvs_files_purpose.py [VIA_SERVER_PATH]")
    target = Path(argv[1]) if len(argv) == 2 else DEFAULT_TARGET
    patch_file(target)
    if target == DEFAULT_TARGET:
        Path(__file__).unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
