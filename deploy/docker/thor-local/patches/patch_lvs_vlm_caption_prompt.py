#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make the released LVS file-caption route honor ``VlmQuery.prompt``."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import stat
import sys
import tempfile


DEFAULT_TARGET = Path("/opt/nvidia/via/via-engine/via_server.py")

OLD_BLOCK = '''                "vlm_input_height": query.vlm_input_height,
                "enable_reasoning": query.enable_reasoning,
                # VLM captions specific defaults (no summarization)
'''

NEW_BLOCK = '''                "vlm_input_height": query.vlm_input_height,
                "enable_reasoning": query.enable_reasoning,
                # VlmQuery.prompt is the public caption instruction. Preserve
                # it instead of replacing it with the summarization prompt
                # assembled from the intentionally empty scenario/events
                # fields below. generate_vlm_captions supplies its documented
                # default caption prompt later when this value is empty.
                "override_vlm_prompt": True,
                # VLM captions specific defaults (no summarization)
'''


def patch_source(source: str) -> str:
    count = source.count(OLD_BLOCK)
    if count != 1:
        raise RuntimeError(
            f"Expected one LVS VLM-caption prompt patch marker, found {count}"
        )
    patched = source.replace(OLD_BLOCK, NEW_BLOCK, 1)
    ast.parse(patched)
    return patched


def patch_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"LVS via_server target is not a regular file: {path}")
    before = path.stat(follow_symlinks=False)
    source = path.read_text(encoding="utf-8")
    after = path.stat(follow_symlinks=False)
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in stable):
        raise RuntimeError("LVS via_server target changed while it was being read")

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".thor-vlm-caption-prompt",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(patch_source(source))
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
        raise RuntimeError("usage: patch_lvs_vlm_caption_prompt.py [VIA_SERVER_PATH]")
    target = Path(argv[1]) if len(argv) == 2 else DEFAULT_TARGET
    patch_file(target)
    if target == DEFAULT_TARGET:
        Path(__file__).unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
