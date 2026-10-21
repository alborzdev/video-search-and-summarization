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

"""Snapshot generated media and knowledge without touching producer lifecycle.

The optional recording metadata bridge is read-only. VST's public file listing
does not expose closed status or duration, so a frozen, identity-checked database
row is required before its exact filePath deletion API can be used safely.
Neo4j deletes compare node properties and relationship identities under a lock.
The last chunk for each document is retained as an ingestion predecessor.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

import httpx

if TYPE_CHECKING:
    from datetime import datetime


class MediaConfig(Protocol):
    """Only existing service addresses are needed; no config schema change."""

    vst_url: str


JSON = dict[str, Any]  # External storage contracts carry heterogeneous JSON properties.
MAX_GRAPH_NODES = 10000
GRAPH_SNAPSHOT_QUERY = """
MATCH (n)
WITH n LIMIT $limit
OPTIONAL MATCH (n)-[r]-(other)
RETURN elementId(n), labels(n), properties(n),
       collect(DISTINCT {id: elementId(r), other: elementId(other), type: type(r), properties: properties(r)})
"""
GRAPH_DELETE_QUERY = """
UNWIND $nodes AS item
MATCH (n) WHERE elementId(n) = item.id
CALL apoc.lock.nodes([n])
WITH n, item
WHERE properties(n) = item.properties AND apoc.coll.sort(labels(n)) = apoc.coll.sort(item.labels)
  AND NOT EXISTS {
    MATCH (n)-[r]-(other) WHERE NOT any(edge IN item.edges WHERE
      edge.id = elementId(r) AND edge.other = elementId(other) AND edge.properties = properties(r))
  }
WITH collect(n) AS candidates
UNWIND candidates AS n
DETACH DELETE n
RETURN count(*)
"""
GRAPH_REPAIR_DOCUMENT_QUERY = """
MATCH (d:Document) WHERE elementId(d) IN $documents
CALL apoc.lock.nodes([d])
WITH d WHERE NOT EXISTS { MATCH (d)-[:FIRST_CHUNK]->(:Chunk) }
MATCH (c:Chunk)-[:PART_OF]->(d)
WITH d, c ORDER BY c.position, c.start_time, c.id
WITH d, head(collect(c)) AS first
MERGE (d)-[:FIRST_CHUNK]->(first)
RETURN count(*)
"""
GRAPH_DELETE_ORPHANS_QUERY = """
UNWIND $nodes AS item
MATCH (n) WHERE elementId(n) = item.id
CALL apoc.lock.nodes([n])
WITH n, item
WHERE properties(n) = item.properties AND apoc.coll.sort(labels(n)) = apoc.coll.sort(item.labels)
  AND NOT EXISTS {
    MATCH (n)-[r]-(other) WHERE NOT any(edge IN item.edges WHERE
      edge.id = elementId(r) AND edge.other = elementId(other) AND edge.properties = properties(r))
  }
  AND NOT EXISTS { MATCH (n)--(:Chunk) }
WITH collect(n) AS candidates
UNWIND candidates AS n
DETACH DELETE n
RETURN count(*)
"""
GRAPH_SCRUB_PREDECESSORS_QUERY = """
UNWIND $nodes AS item
MATCH (n:Chunk) WHERE elementId(n) = item.id
CALL apoc.lock.nodes([n])
WITH n, item
WHERE properties(n) = item.properties AND apoc.coll.sort(labels(n)) = apoc.coll.sort(item.labels)
SET n.text = ''
REMOVE n.embedding, n.asset_dir, n.file, n.start_time, n.end_time, n.start_pts, n.end_pts, n.pts_offset_ns
WITH n, item
OPTIONAL MATCH (n)-[r:HAS_ENTITY|IN_SUMMARY|HAS_SUBTITLE]-()
WHERE any(edge IN item.edges WHERE edge.id = elementId(r) AND edge.properties = properties(r))
WITH n, collect(r) AS edges
FOREACH (edge IN edges | DELETE edge)
RETURN count(n)
"""


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def recording_is_old(row: JSON, cutoff_ms: float, live_ids: set[str]) -> bool:
    """Require closed, unprotected live media fully before the frozen cutoff."""
    start = _number(row.get("start_time"))
    duration = _number(row.get("file_duration"))
    return bool(
        row.get("stream_id") in live_ids
        and isinstance(row.get("file_path"), str)
        and row["file_path"]
        and start is not None
        and start > 0
        and duration is not None
        and duration > 1  # VST FILE_INIT_DURATION is 1, not a completed fragment.
        and start + duration < cutoff_ms
        and str(row.get("file_protection")) == "0"
    )


def recording_disk_path(row: JSON) -> Path:
    """Map a verified recording path into the read-only inspection mount."""
    root = Path(os.environ["HISTORY_RECORDINGS_ROOT"]).resolve()
    prefix = Path(os.environ["HISTORY_RECORDINGS_PATH_PREFIX"])
    relative = Path(row["file_path"]).relative_to(prefix)
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("Recording escaped the inspection mount")
    return path


async def _json(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    """External APIs return heterogeneous JSON; all consumers validate shapes."""
    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


async def _recording_rows(client: httpx.AsyncClient) -> list[JSON]:
    url = os.getenv("HISTORY_RECORDINGS_SNAPSHOT_URL", "")
    if not url:
        raise ValueError("Closed recording metadata is not configured")
    payload = await _json(
        client,
        "GET",
        url,
        headers={"X-History-Metadata-Token": os.getenv("HISTORY_METADATA_TOKEN", "")},
    )
    if isinstance(payload, dict):
        payload = payload.get("recordings")
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("Closed recording metadata is invalid")
    if any(not isinstance(row.get("row_id"), int) for row in payload):
        raise ValueError("Closed recording metadata has no immutable row identity")
    return payload


def _graph_auth() -> httpx.BasicAuth:
    username = os.getenv("GRAPH_DB_USERNAME", "")
    password = os.getenv("GRAPH_DB_PASSWORD", "")
    if not username or not password:
        raise ValueError("Graph history storage credentials are not configured")
    return httpx.BasicAuth(username, password)


async def _graph(client: httpx.AsyncClient, statement: str, parameters: JSON) -> list[list[Any]]:
    url = os.getenv("GRAPH_DB_HTTP_URL", "").rstrip("/")
    if not url:
        raise ValueError("Graph history storage is not configured")
    payload = await _json(
        client,
        "POST",
        url + "/db/neo4j/tx/commit",
        auth=_graph_auth(),
        json={"statements": [{"statement": statement, "parameters": parameters}]},
    )
    if not isinstance(payload, dict) or payload.get("errors") or len(payload.get("results", [])) != 1:
        raise ValueError("Graph history storage did not confirm the transaction")
    return [entry["row"] for entry in payload["results"][0]["data"]]


def graph_candidates(rows: list[list[Any]], cutoff: datetime) -> JSON:
    """Derive old graph ownership from absolute chunk times and exact edges."""
    nodes: dict[str, JSON] = {}
    for row in rows:
        if len(row) != 4 or not isinstance(row[0], str) or not isinstance(row[2], dict):
            raise ValueError("Graph snapshot contained an unsupported node")
        nodes[row[0]] = {"id": row[0], "labels": row[1], "properties": row[2], "edges": row[3]}
    eligible: set[str] = set()
    tails: dict[tuple[str, str], tuple[float, str]] = {}
    for node_id, node in nodes.items():
        if "Chunk" not in node["labels"]:
            continue
        properties = node["properties"]
        start = _number(properties.get("start_time"))
        end = _number(properties.get("end_time"))
        if start is None or end is None or start <= 0 or end < start or end >= cutoff.timestamp():
            continue
        eligible.add(node_id)
        owner = (str(properties.get("uuid", "")), str(properties.get("camera_id", "")))
        current = tails.get(owner)
        if current is None or (end, node_id) > current:
            tails[owner] = (end, node_id)
    # Keep the identity of an ingestion predecessor but remove its old content.
    predecessors = {node_id for _, node_id in tails.values()}
    old_chunks = set(eligible)
    eligible.difference_update(predecessors)
    documents: set[str] = set()
    orphans: set[str] = set()
    for node_id in old_chunks:
        for edge in nodes[node_id]["edges"]:
            other = nodes.get(edge["other"])
            if other is None:
                continue
            if "Document" in other["labels"]:
                documents.add(other["id"])
            elif edge["type"] in {"HAS_ENTITY", "IN_SUMMARY", "HAS_SUBTITLE"}:
                attached = {
                    relation["other"]
                    for relation in other["edges"]
                    if relation["other"] in nodes and "Chunk" in nodes[relation["other"]]["labels"]
                }
                if attached and attached <= old_chunks:
                    orphans.add(other["id"])

    def snapshot(node_id: str) -> JSON:
        node = nodes[node_id]
        return {
            "id": node_id,
            "properties": node["properties"],
            "labels": node["labels"],
            "edges": [edge for edge in node["edges"] if edge["id"] is not None],
        }

    return {
        "chunks": [snapshot(node_id) for node_id in sorted(eligible)],
        "predecessors": [snapshot(node_id) for node_id in sorted(predecessors)],
        "orphans": [snapshot(node_id) for node_id in sorted(orphans)],
        "documents": sorted(documents),
        "total": len(nodes),
    }


async def preview_history_media(config: MediaConfig, cutoff: datetime) -> JSON:
    """Return a server-only manifest and public category counts."""
    manifest: JSON = {"countsByCategory": {}, "retainedByCategory": {}, "failures": {}}
    report_root = os.getenv("HISTORY_AGENT_REPORTS_DIR", "")
    if report_root:
        try:
            generated = [
                path for path in Path(report_root).iterdir() if re.fullmatch(r"agent_report_\d{8}_\d{6}\.md", path.name)
            ]
            manifest["countsByCategory"]["agentReports"] = 0
            manifest["retainedByCategory"]["agentReports"] = len(generated)
            if generated:
                # The current agent writer can overwrite a same-second filename
                # after an unbounded object-store await and has no shared lock.
                manifest["failures"]["agentReports"] = (
                    "Generated agent reports require writer-coordinated cleanup and were retained"
                )
        except OSError:
            manifest["failures"]["agentReports"] = "Could not inspect generated agent reports"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            catalog = await _json(client, "GET", config.vst_url + "/vst/api/v1/sensor/streams")
            live_ids = {
                stream["streamId"]
                for sensor in catalog
                for streams in sensor.values()
                for stream in streams
                if stream.get("type") == "Rtsp" and isinstance(stream.get("streamId"), str)
            }
            rows = await _recording_rows(client)
            paths: dict[str, int] = {}
            for row in rows:
                path = row.get("file_path", "")
                paths[path] = paths.get(path, 0) + 1
            eligible = [
                row
                for row in rows
                if recording_is_old(row, cutoff.timestamp() * 1000, live_ids) and paths[row["file_path"]] == 1
            ]
            for row in eligible:
                recording_disk_path(row)  # Require a safe physical-removal inspection capability.
            manifest["recordings"] = eligible
            manifest["countsByCategory"]["recordings"] = len(eligible)
            manifest["retainedByCategory"]["recordings"] = len(rows) - len(eligible)
        except Exception:
            manifest["failures"]["recordings"] = "Could not verify closed recording identities; recordings retained"
        try:
            graph_rows = await _graph(client, GRAPH_SNAPSHOT_QUERY, {"limit": MAX_GRAPH_NODES + 1})
            if len(graph_rows) > MAX_GRAPH_NODES:
                raise ValueError("Graph snapshot exceeds the safe maintenance limit")
            graph = graph_candidates(graph_rows, cutoff)
            manifest["graph"] = graph
            count = len(graph["chunks"]) + len(graph["orphans"]) + len(graph["predecessors"])
            manifest["countsByCategory"]["graph"] = count
            manifest["retainedByCategory"]["graph"] = graph["total"] - count
        except Exception:
            manifest["failures"]["graph"] = "Could not verify graph history snapshot; knowledge retained"
        try:
            evidence_url = os.getenv("HISTORY_EVIDENCE_URL", "").rstrip("/")
            if not evidence_url:
                raise ValueError("Evidence history service is not configured")
            evidence = await _json(
                client,
                "POST",
                evidence_url + "/history/preview",
                json={"cutoff": cutoff.isoformat()},
                headers={"X-History-Metadata-Token": os.getenv("HISTORY_METADATA_TOKEN", "")},
            )
            if not isinstance(evidence, dict) or not isinstance(evidence.get("planToken"), str):
                raise ValueError("Evidence history snapshot was invalid")
            manifest["evidence"] = evidence
            manifest["countsByCategory"]["evidenceClips"] = int(evidence["count"])
            manifest["retainedByCategory"]["evidenceClips"] = int(evidence["retained"])
        except Exception:
            manifest["failures"]["evidenceClips"] = "Could not verify generated evidence snapshot; clips retained"
    return manifest


async def clear_history_media(config: MediaConfig, manifest: JSON) -> JSON:
    """Consume only the frozen server manifest; preserve changed identities."""
    result: JSON = {
        "deletedByCategory": {},
        "retainedByCategory": dict(manifest["retainedByCategory"]),
        "failures": dict(manifest["failures"]),
    }
    if "agentReports" in manifest.get("countsByCategory", {}):
        result["deletedByCategory"]["agentReports"] = 0
    async with httpx.AsyncClient(timeout=60) as client:
        if "recordings" in manifest:
            deleted = 0
            retained = 0
            unconfirmed = 0
            try:
                current = {row["row_id"]: row for row in await _recording_rows(client)}
                for row in manifest["recordings"]:
                    matching_paths = [
                        record for record in current.values() if record.get("file_path") == row["file_path"]
                    ]
                    if current.get(row["row_id"]) != row or matching_paths != [row]:
                        retained += 1
                        continue
                    payload = await _json(
                        client,
                        "DELETE",
                        config.vst_url + "/vst/api/v1/storage/file",
                        params={"filePath": row["file_path"]},
                    )
                    if not isinstance(payload, dict):
                        raise ValueError("Recording deletion returned an invalid confirmation")
                    # VST success alone is insufficient; verify exact DB identity disappeared.
                    after = {record["row_id"]: record for record in await _recording_rows(client)}
                    latest = after.get(row["row_id"])
                    disk_exists = recording_disk_path(row).exists()
                    new_reference = any(
                        record.get("file_path") == row["file_path"] and record != row for record in after.values()
                    )
                    if latest is None and not disk_exists:
                        deleted += 1
                    else:
                        retained += 1
                        # A changed identity, newly shared file, or a concurrent
                        # protection request is an expected CAS retention. An
                        # unchanged eligible row or orphaned physical file is a
                        # real incomplete deletion, even with HTTP 200.
                        protected_paths = payload.get("protectedFiles", [])
                        protected = (
                            isinstance(protected_paths, list)
                            and row["file_path"] in protected_paths
                            and latest is not None
                        )
                        changed = latest is not None and latest != row
                        if not (new_reference or protected or changed):
                            unconfirmed += 1
                    current = after
                if unconfirmed:
                    result["failures"]["recordings"] = (
                        f"{unconfirmed} old recording files or database rows could not be removed"
                    )
            except Exception:
                result["failures"]["recordings"] = (
                    "Recording cleanup could not be fully confirmed; old files may remain"
                )
                retained = len(manifest["recordings"]) - deleted
            result["deletedByCategory"]["recordings"] = deleted
            result["retainedByCategory"]["recordings"] += retained
        if "graph" in manifest:
            graph = manifest["graph"]
            deleted = 0
            try:
                if graph["chunks"]:
                    rows = await _graph(client, GRAPH_DELETE_QUERY, {"nodes": graph["chunks"]})
                    deleted += int(rows[0][0])
                    await _graph(client, GRAPH_REPAIR_DOCUMENT_QUERY, {"documents": graph["documents"]})
                if graph["predecessors"]:
                    rows = await _graph(client, GRAPH_SCRUB_PREDECESSORS_QUERY, {"nodes": graph["predecessors"]})
                    deleted += int(rows[0][0])
                if graph["orphans"]:
                    rows = await _graph(client, GRAPH_DELETE_ORPHANS_QUERY, {"nodes": graph["orphans"]})
                    deleted += int(rows[0][0])
            except Exception:
                result["failures"]["graph"] = (
                    "Graph cleanup could not be fully confirmed; some old knowledge may remain"
                )
            result["deletedByCategory"]["graph"] = deleted
            result["retainedByCategory"]["graph"] += (
                len(graph["chunks"]) + len(graph["orphans"]) + len(graph["predecessors"]) - deleted
            )
        if "evidence" in manifest:
            try:
                evidence_url = os.environ["HISTORY_EVIDENCE_URL"].rstrip("/")
                evidence = await _json(
                    client,
                    "POST",
                    evidence_url + "/history/clear",
                    json={"planToken": manifest["evidence"]["planToken"]},
                    headers={"X-History-Metadata-Token": os.getenv("HISTORY_METADATA_TOKEN", "")},
                )
                if not isinstance(evidence, dict) or not isinstance(evidence.get("deleted"), int):
                    raise ValueError("Evidence cleanup was not confirmed")
                result["deletedByCategory"]["evidenceClips"] = evidence["deleted"]
                result["retainedByCategory"]["evidenceClips"] += int(evidence["retained"])
            except Exception:
                result["failures"]["evidenceClips"] = "Evidence cleanup could not be confirmed; old clips may remain"
    return result
