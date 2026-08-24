# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
PATCH_PATH = REPO_ROOT / "deploy/docker/thor-local/patches/patch_lvs_graphrag_schema.py"
SPEC = importlib.util.spec_from_file_location("patch_lvs_graphrag_schema", PATCH_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


SOURCE = f'''VECTOR_GRAPH_SEARCH_QUERY_PREFIX = """
        WITH node as chunk, score
{MODULE.OLD_SCHEMA}
            WHEN $uuid IS NOT NULL THEN d.uuid = $uuid
            ELSE true
        END
"""
'''


def test_patch_traverses_the_schema_written_by_graph_ingestion():
    updated = MODULE.patch_source(SOURCE)

    assert MODULE.OLD_SCHEMA not in updated
    assert MODULE.NEW_SCHEMA in updated
    assert "FIRST_CHUNK" in updated
    assert "NEXT_CHUNK*0.." in updated


def test_patch_fails_closed_when_released_marker_is_missing():
    with pytest.raises(RuntimeError, match="found 0"):
        MODULE.patch_source(SOURCE.replace(MODULE.OLD_SCHEMA, "missing"))


def test_patch_fails_closed_when_released_marker_is_ambiguous():
    with pytest.raises(RuntimeError, match="found 2"):
        MODULE.patch_source(SOURCE.replace(MODULE.OLD_SCHEMA, MODULE.OLD_SCHEMA * 2))
