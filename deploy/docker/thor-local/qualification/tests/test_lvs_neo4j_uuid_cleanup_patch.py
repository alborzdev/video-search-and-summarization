# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the CA-RAG UUID graph-cleanup image patch."""

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
PATCH_PATH = (
    REPO_ROOT
    / "deploy/docker/thor-local/patches/patch_lvs_neo4j_uuid_cleanup.py"
)
SPEC = importlib.util.spec_from_file_location("patch_lvs_neo4j_uuid_cleanup", PATCH_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


SOURCE = f'''QUERY_TO_DELETE_UUID_GRAPH = r"""
WITH d, docChunks, e, entityChunk
{MODULE.ENTITY_OLD}
    MATCH (e)<-[:HAS_ENTITY]-(otherChunk:Chunk)
}}
WITH d, docChunks, orphanedEntities, s, summaryChunk
{MODULE.SUMMARY_OLD}
    MATCH (s)<-[:IN_SUMMARY]-(otherChunk:Chunk)
}}
"""
'''


def test_patch_preserves_optional_rows_for_entity_free_and_summary_free_graphs():
    updated = MODULE.patch_source(SOURCE)

    assert MODULE.ENTITY_OLD not in updated
    assert MODULE.SUMMARY_OLD not in updated
    assert "WHERE n.uuid = $uuid" in updated
    assert "owned + orphanedEntities + candidateSummaries" in updated
    assert "MATCH (d:Document {uuid:$uuid})" not in updated


@pytest.mark.parametrize("missing", [MODULE.ENTITY_OLD, MODULE.SUMMARY_OLD])
def test_patch_fails_closed_when_released_marker_is_missing(missing):
    with pytest.raises(RuntimeError, match="Expected one"):
        MODULE.patch_source(SOURCE.replace(missing, "missing marker", 1))


def test_patch_fails_closed_when_released_marker_is_ambiguous():
    with pytest.raises(RuntimeError, match="found 2"):
        MODULE.patch_source(SOURCE.replace(MODULE.ENTITY_OLD, MODULE.ENTITY_OLD * 2, 1))
