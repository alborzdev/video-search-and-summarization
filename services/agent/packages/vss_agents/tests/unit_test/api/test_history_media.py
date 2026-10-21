# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Bounded media clears preserve open files, configurations, and new knowledge."""

from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from vss_agents.api.history_media import clear_history_media
from vss_agents.api.history_media import graph_candidates
from vss_agents.api.history_media import preview_history_media
from vss_agents.api.history_media import recording_is_old


def recording(**changes):
    return {
        "row_id": 1,
        "stream_id": "live",
        "file_path": "/vst_video/live/123.mkv",
        "start_time": 1000,
        "file_duration": 100,
        "file_protection": "0",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"file_duration": 1},
        {"file_duration": 0},
        {"file_duration": None},
        {"start_time": 1990},
        {"start_time": None},
        {"file_protection": "1"},
        {"stream_id": "uploaded-source"},
        {"file_path": ""},
    ],
)
def test_recording_selection_retains_open_crossing_protected_and_file_source(changes):
    assert not recording_is_old(recording(**changes), 2000, {"live"})


def test_recording_selection_requires_fully_closed_old_fragment():
    assert recording_is_old(recording(), 2000, {"live"})
    assert not recording_is_old(recording(file_duration=1000), 2000, {"live"})


def chunk(node_id, end, edges=None):
    return [
        node_id,
        ["Chunk"],
        {
            "id": node_id,
            "uuid": "source",
            "camera_id": "camera",
            "text": "old knowledge",
            "start_time": 1000.0,
            "end_time": end,
            "position": int(end) if end else 0,
        },
        edges or [],
    ]


def test_graph_keeps_empty_predecessor_identity_and_retains_unknown_or_new_time():
    cutoff = datetime.fromtimestamp(2000, UTC)
    rows = [chunk("old", 1100), chunk("tail", 1200), chunk("new", 2100), chunk("unknown", "")]
    plan = graph_candidates(rows, cutoff)
    assert [node["id"] for node in plan["chunks"]] == ["old"]
    assert [node["id"] for node in plan["predecessors"]] == ["tail"]
    assert plan["predecessors"][0]["properties"]["id"] == "tail"
    assert plan["total"] == 4


def test_graph_retains_entities_already_referenced_by_new_chunks():
    cutoff = datetime.fromtimestamp(2000, UTC)

    def edge(node_id, rel_id):
        return {"id": rel_id, "other": node_id, "type": "HAS_ENTITY", "properties": {}}

    rows = [
        chunk("old", 1100, [edge("shared", "a"), edge("owned", "b")]),
        chunk("tail", 1200),
        chunk("new", 2100, [edge("shared", "c")]),
        ["shared", ["__Entity__"], {"name": "shared"}, [edge("old", "a"), edge("new", "c")]],
        ["owned", ["__Entity__"], {"name": "old entity"}, [edge("old", "b")]],
    ]
    plan = graph_candidates(rows, cutoff)
    assert [node["id"] for node in plan["orphans"]] == ["owned"]
    assert plan["chunks"][0]["edges"][0]["properties"] == {}


@pytest.mark.asyncio
async def test_recording_execution_rechecks_identity_and_verifies_deletion():
    row = recording()
    changed = recording(row_id=2, file_path="/vst_video/live/456.mkv")
    manifest = {
        "recordings": [row, changed],
        "retainedByCategory": {"recordings": 3},
        "failures": {},
    }
    metadata = AsyncMock(side_effect=[[row, {**changed, "file_duration": 500}], [{**changed, "file_duration": 500}]])
    api = AsyncMock(return_value={"invalidFiles": [], "protectedFiles": []})
    with (
        patch("vss_agents.api.history_media._recording_rows", metadata),
        patch("vss_agents.api.history_media._json", api),
        patch(
            "vss_agents.api.history_media.recording_disk_path", return_value=Path("/does-not-exist-generated-history")
        ),
    ):
        result = await clear_history_media(SimpleNamespace(vst_url="http://video"), manifest)
    assert result["deletedByCategory"] == {"recordings": 1}
    assert result["retainedByCategory"] == {"recordings": 4}
    assert api.await_count == 1
    assert api.call_args.args[1:3] == ("DELETE", "http://video/vst/api/v1/storage/file")
    assert api.call_args.kwargs["params"] == {"filePath": row["file_path"]}


@pytest.mark.asyncio
async def test_ambiguous_vst_success_does_not_report_recording_removed():
    row = recording()
    manifest = {"recordings": [row], "retainedByCategory": {"recordings": 0}, "failures": {}}
    with (
        patch("vss_agents.api.history_media._recording_rows", AsyncMock(return_value=[row])),
        patch(
            "vss_agents.api.history_media._json",
            AsyncMock(return_value={"invalidFiles": [], "protectedFiles": []}),
        ),
        patch(
            "vss_agents.api.history_media.recording_disk_path", return_value=Path("/does-not-exist-generated-history")
        ),
    ):
        result = await clear_history_media(SimpleNamespace(vst_url="http://video"), manifest)
    assert result["deletedByCategory"]["recordings"] == 0
    assert result["retainedByCategory"]["recordings"] == 1
    assert "recordings" in result["failures"]


@pytest.mark.asyncio
async def test_physical_unlink_failure_after_db_delete_reports_partial_and_continues(tmp_path):
    old = recording()
    other = recording(row_id=2, file_path="/vst_video/live/456.mkv")
    leftover = tmp_path / "leftover.mkv"
    leftover.write_bytes(b"old physical recording")
    removed = tmp_path / "removed.mkv"
    manifest = {"recordings": [old, other], "retainedByCategory": {"recordings": 0}, "failures": {}}
    metadata = AsyncMock(side_effect=[[old, other], [other], []])
    api = AsyncMock(return_value={"invalidFiles": [], "protectedFiles": []})
    with (
        patch("vss_agents.api.history_media._recording_rows", metadata),
        patch("vss_agents.api.history_media._json", api),
        patch("vss_agents.api.history_media.recording_disk_path", side_effect=[leftover, removed]),
    ):
        result = await clear_history_media(SimpleNamespace(vst_url="http://video"), manifest)
    assert result["deletedByCategory"]["recordings"] == 1
    assert result["retainedByCategory"]["recordings"] == 1
    assert result["failures"]["recordings"] == "1 old recording files or database rows could not be removed"
    assert api.await_count == 2
    assert leftover.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["invalidFiles", "protectedFiles"])
async def test_vst_refusal_is_verified_and_only_concurrent_protection_is_expected(outcome):
    old = recording()
    manifest = {"recordings": [old], "retainedByCategory": {"recordings": 0}, "failures": {}}
    with (
        patch("vss_agents.api.history_media._recording_rows", AsyncMock(return_value=[old])),
        patch("vss_agents.api.history_media._json", AsyncMock(return_value={outcome: [old["file_path"]]})),
        patch(
            "vss_agents.api.history_media.recording_disk_path", return_value=Path("/does-not-exist-generated-history")
        ),
    ):
        result = await clear_history_media(SimpleNamespace(vst_url="http://video"), manifest)
    assert result["deletedByCategory"]["recordings"] == 0
    assert result["retainedByCategory"]["recordings"] == 1
    assert ("recordings" in result["failures"]) is (outcome == "invalidFiles")


@pytest.mark.asyncio
async def test_new_db_reference_to_old_path_prevents_path_scoped_delete():
    row = recording()
    manifest = {"recordings": [row], "retainedByCategory": {"recordings": 0}, "failures": {}}
    api = AsyncMock()
    with (
        patch("vss_agents.api.history_media._recording_rows", AsyncMock(return_value=[row, recording(row_id=2)])),
        patch("vss_agents.api.history_media._json", api),
    ):
        result = await clear_history_media(SimpleNamespace(vst_url="http://video"), manifest)
    assert result["deletedByCategory"]["recordings"] == 0
    assert result["retainedByCategory"]["recordings"] == 1
    api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_generated_report", [False, True])
async def test_agent_report_preview_preserves_source_state_and_templates(tmp_path, monkeypatch, has_generated_report):
    state = tmp_path / "source-analysis-state.json"
    template = tmp_path / "agent_report_template.md"
    state.write_text('{"camera":"keep"}')
    template.write_text("keep template")
    if has_generated_report:
        (tmp_path / "agent_report_20261001_100000.md").write_text("old report")
    monkeypatch.setenv("HISTORY_AGENT_REPORTS_DIR", str(tmp_path))
    monkeypatch.setenv("HISTORY_EVIDENCE_URL", "http://evidence")
    with (
        patch(
            "vss_agents.api.history_media._json",
            AsyncMock(side_effect=[[], {"planToken": "token", "count": 0, "retained": 0}]),
        ),
        patch("vss_agents.api.history_media._recording_rows", AsyncMock(return_value=[])),
        patch("vss_agents.api.history_media._graph", AsyncMock(return_value=[])),
    ):
        plan = await preview_history_media(SimpleNamespace(vst_url="http://video"), datetime.now(UTC))
    assert plan["countsByCategory"]["agentReports"] == 0
    assert plan["retainedByCategory"]["agentReports"] == int(has_generated_report)
    assert ("agentReports" in plan["failures"]) is has_generated_report
    assert state.read_text() == '{"camera":"keep"}'
    assert template.read_text() == "keep template"
