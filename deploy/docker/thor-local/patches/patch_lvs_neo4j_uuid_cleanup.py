#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fix UUID-scoped Neo4j cleanup in the released CA-RAG wheel.

The 3.2.1 query drops the entire Cypher row when either optional entity or
summary matches are absent. A short video with no extracted entities therefore
retains its Document and Chunk nodes after ``/files/{id}`` returns success.
Preserve the null row; the query already filters nulls from ``nodesToDelete``.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import site
import stat
import tempfile


ENTITY_OLD = "WHERE e IS NOT NULL AND NOT EXISTS { // Ensure entity is not linked elsewhere"
ENTITY_NEW = "WHERE e IS NULL OR NOT EXISTS { // Preserve row when no entity was extracted"
SUMMARY_OLD = "WHERE s IS NOT NULL AND NOT EXISTS { // Ensure summary is not linked elsewhere"
SUMMARY_NEW = "WHERE s IS NULL OR NOT EXISTS { // Preserve row when no summary was extracted"

ROBUST_UUID_CLEANUP_QUERY = r'''
MATCH (n)
WHERE n.uuid = $uuid
WITH collect(n) AS owned
OPTIONAL MATCH (ownedChunk:Chunk)-[:HAS_ENTITY]->(entity)
WHERE ownedChunk IN owned
WITH owned, collect(DISTINCT entity) AS candidateEntities
WITH owned, [entity IN candidateEntities WHERE entity IS NOT NULL AND NOT EXISTS {
  MATCH (otherChunk:Chunk)-[:HAS_ENTITY]->(entity)
  WHERE NOT otherChunk IN owned
}] AS orphanedEntities
OPTIONAL MATCH (summaryChunk:Chunk)-[:IN_SUMMARY]->(summary:Summary)
WHERE summaryChunk IN owned
WITH owned, orphanedEntities, collect(DISTINCT summary) AS candidateSummaries
WITH [node IN owned + orphanedEntities + candidateSummaries WHERE node IS NOT NULL] AS nodesToDelete
UNWIND nodesToDelete AS nodeToDelete
DETACH DELETE nodeToDelete
'''.strip()


def default_target() -> Path:
    relative = Path("vss_ctx_rag/functions/rag/graph_rag/constants.py")
    candidates = [Path(root) / relative for root in site.getsitepackages()]
    matches = [path for path in candidates if path.is_file() and not path.is_symlink()]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one installed CA-RAG constants target, found {len(matches)}"
        )
    return matches[0]


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} marker, found {count}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    source = _replace_once(source, ENTITY_OLD, ENTITY_NEW, "Neo4j entity cleanup")
    source = _replace_once(source, SUMMARY_OLD, SUMMARY_NEW, "Neo4j summary cleanup")
    pattern = re.compile(
        r'QUERY_TO_DELETE_UUID_GRAPH\s*=\s*(?:[rRuUbBfF]*)'
        r'(?P<quote>"""|\'\'\').*?(?P=quote)',
        re.DOTALL,
    )
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one UUID cleanup query assignment, found {len(matches)}"
        )
    source = pattern.sub(
        'QUERY_TO_DELETE_UUID_GRAPH = r"""\n'
        + ROBUST_UUID_CLEANUP_QUERY
        + '\n"""',
        source,
        count=1,
    )
    ast.parse(source)
    return source


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
