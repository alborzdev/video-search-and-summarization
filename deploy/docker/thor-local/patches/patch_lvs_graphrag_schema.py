#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Align the released GraphRAG retrieval query with its ingestion schema.

VSS 3.2.1 ingestion writes ``Document-[:FIRST_CHUNK]->Chunk`` followed by a
``NEXT_CHUNK`` chain. Its chunk retriever still requires a ``Chunk-[:PART_OF]``
edge that ingestion never creates, so even high-scoring vectors are discarded.
Traverse the actual document-owned chunk chain instead.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import site
import stat
import tempfile


OLD_SCHEMA = """        MATCH (chunk)-[:PART_OF]->(d:Document)
        WHERE CASE"""
NEW_SCHEMA = """        MATCH (d:Document)-[:FIRST_CHUNK]->(firstChunk:Chunk)
        MATCH (firstChunk)-[:NEXT_CHUNK*0..]->(chunk)
        WHERE CASE"""


def default_target() -> Path:
    relative = Path("vss_ctx_rag/functions/rag/graph_rag/constants.py")
    matches = [
        Path(root) / relative
        for root in site.getsitepackages()
        if (Path(root) / relative).is_file()
        and not (Path(root) / relative).is_symlink()
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one installed CA-RAG constants target, found {len(matches)}"
        )
    return matches[0]


def patch_source(source: str) -> str:
    count = source.count(OLD_SCHEMA)
    if count != 1:
        raise RuntimeError(
            f"Expected one obsolete GraphRAG relationship marker, found {count}"
        )
    updated = source.replace(OLD_SCHEMA, NEW_SCHEMA, 1)
    ast.parse(updated)
    return updated


def patch_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"CA-RAG patch target is not a regular file: {path}")
    before = path.stat(follow_symlinks=False)
    source = path.read_text(encoding="utf-8")
    after = path.stat(follow_symlinks=False)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError(f"CA-RAG patch target changed while being read: {path}")
    updated = patch_source(source)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with open(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(updated)
            handle.flush()
        temporary.chmod(stat.S_IMODE(before.st_mode))
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path)
    options = parser.parse_args()
    patch_file(options.target or default_target())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
