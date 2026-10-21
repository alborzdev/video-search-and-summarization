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

"""Clear a frozen history snapshot while producers continue writing.

Only known generated indexes are considered. PIT snapshots and conditional bulk
version deletes protect new documents, late arrivals, and updated live tracks.
The existing source reset and lifecycle deletion helpers are intentionally unused.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import logging
import os
import re
import secrets
from typing import Any
from typing import Literal
from typing import Protocol

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from vss_agents.api.history_media import clear_history_media
from vss_agents.api.history_media import preview_history_media

logger = logging.getLogger(__name__)
PLAN_LIFETIME = timedelta(minutes=5)
# Lease spans five-minute confirmation plus the twenty-minute cleanup budget.
# A later category must not expire while earlier categories are being cleared.
PIT_KEEP_ALIVE = "30m"
PAGE_SIZE = 1000
# Explicit category allowlist excludes rules, application/system indexes, and aliases.
INDEX_CATEGORIES = {
    "embeddings": "mdx-embed-filtered-",
    "detections": "mdx-raw-",
    "behavior": "mdx-behavior-",
    "incidents": "mdx-incidents-",
    "vlmIncidents": "mdx-vlm-incidents-",
}
CAPTION_INDEX = re.compile(r"^default_[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}$")


class HistoryConfig(Protocol):
    """Only existing service URLs are needed; model and NAT imports are unnecessary."""

    vst_url: str
    elasticsearch_url: str
    lvs_backend_url: str
    vst_streamprocessor_url: str


class ClearHistoryRequest(BaseModel):
    """An explicit confirmation bound to a server-created snapshot."""

    plan_token: str = Field(alias="planToken", min_length=16, max_length=256)
    confirmation: Literal["CLEAR_HISTORY"]
    model_config = ConfigDict(extra="forbid")


class CancelHistoryRequest(BaseModel):
    """Release a private preview's snapshot resources without deleting data."""

    plan_token: str = Field(alias="planToken", min_length=16, max_length=256)
    model_config = ConfigDict(extra="forbid")


@dataclass
class CategorySnapshot:
    """Frozen category search with a continually renewed PIT identifier."""

    pit: str
    query: dict[str, Any]  # Elasticsearch query DSL is heterogeneous JSON.
    count: int
    retained: int
    indexes: tuple[str, ...] = ()
    deleted: int = 0
    conflicts: int = 0


@dataclass
class HistoryPlan:
    """Process-local confirmation plan; never accepts index or source input."""

    cutoff: datetime
    expires: datetime
    source_ids: list[str]
    categories: dict[str, CategorySnapshot] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    media: dict[str, Any] = field(
        default_factory=lambda: {"countsByCategory": {}, "retainedByCategory": {}, "failures": {}}
    )  # Contains frozen server-only recording/graph/evidence identities.
    running: bool = False
    result: dict[str, Any] | None = None  # Wire response with category dictionaries and scalar metadata.


def category_query(category: str, cutoff: datetime) -> dict[str, Any]:
    """Preserve records with unknown end times and any interval crossing cutoff."""
    if category == "captions":
        return {
            "bool": {
                "filter": [
                    {"range": {"metadata.content_metadata.start_ntp_float": {"lt": cutoff.timestamp()}}},
                    {"range": {"metadata.content_metadata.end_ntp_float": {"lt": cutoff.timestamp()}}},
                ],
            },
        }
    filters: list[dict[str, Any]] = [{"range": {"timestamp": {"lt": cutoff.isoformat()}}}]
    if category == "detections":
        # Raw per-frame messages have no end. If an interval is present, respect it.
        filters.append(
            {
                "bool": {
                    "minimum_should_match": 1,
                    "should": [
                        {"bool": {"must_not": {"exists": {"field": "end"}}}},
                        {"range": {"end": {"lt": cutoff.isoformat()}}},
                    ],
                },
            },
        )
    else:
        filters.append({"range": {"end": {"lt": cutoff.isoformat()}}})
    return {"bool": {"filter": filters}}


def _mapping_type(properties: dict[str, Any], path: str) -> str | None:
    value: dict[str, Any] = {"properties": properties}
    for component in path.split("."):
        value = value.get("properties", {}).get(component, {})
    kind = value.get("type")
    return kind if isinstance(kind, str) else None


def category_for_index(name: str) -> str | None:
    """Require exact published category names, never user-supplied patterns."""
    # Cached appearance vectors are generated demo history, alongside tracks.
    if name == "mdx-appearance-cosmos-768-v1":
        return "behavior"
    for category, prefix in INDEX_CATEGORIES.items():
        if re.fullmatch(re.escape(prefix) + r"\d{4}-\d{2}-\d{2}", name):
            return category
    if CAPTION_INDEX.fullmatch(name):
        return "captions"
    return None


def _verified_total(response: dict[str, Any]) -> int:
    """Require exact counts; a partial count is not an authoritative preview."""
    total = response.get("hits", {}).get("total", {})
    value = total.get("value")
    if total.get("relation") != "eq" or type(value) is not int or value < 0:
        raise ValueError("History snapshot returned an incomplete count")
    return value


class HistoryClearService:
    """Snapshot coordinator with bounded plans and single-use execution."""

    def __init__(self, config: HistoryConfig) -> None:
        self.config = config
        self.plans: dict[str, HistoryPlan] = {}
        self.lock = asyncio.Lock()

    async def _es(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.request(method, self.config.elasticsearch_url + path, json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Search storage returned invalid JSON")
        if path == "/_search" and (payload.get("timed_out") or payload.get("_shards", {}).get("failed", 0)):
            raise ValueError("History snapshot search was incomplete")
        return payload

    async def _close(self, client: httpx.AsyncClient, plan: HistoryPlan) -> None:
        for snapshot in plan.categories.values():
            try:
                await self._es(client, "DELETE", "/_pit", {"id": snapshot.pit})
            except Exception:
                logger.warning("Could not close history snapshot", exc_info=True)
        evidence = plan.media.get("evidence")
        evidence_url = os.getenv("HISTORY_EVIDENCE_URL", "").rstrip("/")
        if isinstance(evidence, dict) and isinstance(evidence.get("planToken"), str) and evidence_url:
            try:
                response = await client.post(
                    evidence_url + "/history/cancel",
                    json={"planToken": evidence["planToken"]},
                    headers={"X-History-Metadata-Token": os.getenv("HISTORY_METADATA_TOKEN", "")},
                )
                response.raise_for_status()
                if response.json().get("status") != "cancelled":
                    raise ValueError("Evidence snapshot release was not confirmed")
            except Exception:
                logger.warning("Could not close evidence history snapshot", exc_info=True)

    async def preview(self) -> dict[str, Any]:
        """Create immutable preview snapshots using server-owned source inventory."""
        if not self.config.elasticsearch_url:
            raise HTTPException(503, "History clearing is not configured")
        # Fail closed if the camera inventory cannot be read. No lifecycle writes occur.
        async with httpx.AsyncClient(timeout=30) as inventory_client:
            inventory_response = await inventory_client.get(self.config.vst_url + "/vst/api/v1/sensor/streams")
            inventory_response.raise_for_status()
            inventory = inventory_response.json()
        if not isinstance(inventory, list) or any(not isinstance(entry, dict) for entry in inventory):
            raise HTTPException(503, "Camera inventory could not be verified")
        sources = [source for entry in inventory for source in entry]
        cutoff = datetime.now(UTC)
        plan = HistoryPlan(cutoff, cutoff + PLAN_LIFETIME, sorted(sources))
        async with self.lock, httpx.AsyncClient(timeout=120) as client:
            for token, existing in list(self.plans.items()):
                if existing.expires < cutoff and not existing.running:
                    await self._close(client, existing)
                    del self.plans[token]
            if len(self.plans) >= 8:
                raise HTTPException(429, "Too many history previews; wait for an existing preview to expire")
            mappings = await self._es(
                client,
                "GET",
                "/mdx-embed-filtered-*,mdx-raw-*,mdx-behavior-*,mdx-appearance-*,mdx-incidents-*,mdx-vlm-incidents-*,default_*/_mapping?allow_no_indices=true&ignore_unavailable=true",
            )
            indexes: dict[str, list[str]] = {}
            for name, mapping in mappings.items():
                category = category_for_index(name)
                if not category:
                    continue
                properties = mapping.get("mappings", {}).get("properties", {})
                required = (
                    {
                        "metadata.content_metadata.start_ntp_float": {"double", "float"},
                        "metadata.content_metadata.end_ntp_float": {"double", "float"},
                    }
                    if category == "captions"
                    else {"timestamp": {"date", "date_nanos"}, "end": {"date", "date_nanos"}}
                )
                if category == "detections":
                    required.pop("end")
                if any(_mapping_type(properties, path) not in types for path, types in required.items()):
                    plan.failures[category] = "Some indexes have unsupported time mappings and were retained"
                    continue
                indexes.setdefault(category, []).append(name)
            # Create every PIT before publishing the wall-clock cutoff. This also
            # protects late old-timestamp arrivals during preview construction.
            snapshots: dict[str, str] = {}
            for category, names in indexes.items():
                try:
                    response = await self._es(client, "POST", f"/{','.join(names)}/_pit?keep_alive={PIT_KEEP_ALIVE}")
                    snapshots[category] = response["id"]
                except Exception:
                    logger.warning("History snapshot creation failed: %s", category, exc_info=True)
                    plan.failures[category] = "Could not create a verified history snapshot"
            # Media may use source timestamps rather than creation timestamps.
            # Freeze its identities before the public cutoff too, so delayed
            # old-source-time graph writes after that cutoff always survive.
            # The earlier eligibility bound conservatively retains borderline media.
            plan.media = await preview_history_media(self.config, cutoff)
            cutoff = datetime.now(UTC)
            plan.cutoff = cutoff
            plan.expires = cutoff + PLAN_LIFETIME
            for category, pit in snapshots.items():
                try:
                    query = category_query(category, cutoff)
                    count = await self._es(
                        client,
                        "POST",
                        "/_search",
                        {
                            "pit": {"id": pit, "keep_alive": PIT_KEEP_ALIVE},
                            "size": 0,
                            "track_total_hits": True,
                            "query": query,
                        },
                    )
                    pit = count.get("pit_id", pit)
                    total = await self._es(
                        client,
                        "POST",
                        "/_search",
                        {
                            "pit": {"id": pit, "keep_alive": PIT_KEEP_ALIVE},
                            "size": 0,
                            "track_total_hits": True,
                        },
                    )
                    pit = total.get("pit_id", pit)
                    eligible = _verified_total(count)
                    retained = _verified_total(total) - eligible
                    if retained < 0:
                        raise ValueError("History snapshot count was inconsistent")
                    plan.categories[category] = CategorySnapshot(
                        pit, query, eligible, retained, tuple(indexes[category])
                    )
                except Exception:
                    logger.warning("History preview category failed: %s", category, exc_info=True)
                    plan.failures[category] = "Could not create a verified history snapshot"
                    if pit:
                        await self._es(client, "DELETE", "/_pit", {"id": pit})
            token = secrets.token_urlsafe(32)
            self.plans[token] = plan
        return {
            "planToken": token,
            "cutoff": cutoff.isoformat(),
            "expiresAt": plan.expires.isoformat(),
            "sourceIds": plan.source_ids,
            "countsByCategory": {
                **{category: snapshot.count for category, snapshot in plan.categories.items()},
                **plan.media["countsByCategory"],
            },
            "retainedByCategory": {
                **{category: snapshot.retained for category, snapshot in plan.categories.items()},
                **plan.media["retainedByCategory"],
            },
            "failures": {**plan.failures, **plan.media["failures"]},
            "ingestionUnchanged": True,
        }

    async def _delete_snapshot(self, client: httpx.AsyncClient, snapshot: CategorySnapshot) -> tuple[int, int]:
        """Delete only exact snapshot versions; conflicts preserve ongoing updates."""
        cursor: list[Any] | None = None  # Elasticsearch sort values can be numeric or string.
        while True:
            body: dict[str, Any] = {
                "pit": {"id": snapshot.pit, "keep_alive": PIT_KEEP_ALIVE},
                "size": PAGE_SIZE,
                "query": snapshot.query,
                "sort": ["_shard_doc"],
                "seq_no_primary_term": True,
                "_source": False,
                "track_total_hits": False,
            }
            if cursor is not None:
                body["search_after"] = cursor
            response = await self._es(client, "POST", "/_search", body)
            if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                raise ValueError("History snapshot search was incomplete")
            snapshot.pit = response.get("pit_id", snapshot.pit)
            hits = response["hits"]["hits"]
            if not hits:
                break
            operations = [
                json.dumps(
                    {
                        "delete": {
                            "_index": hit["_index"],
                            "_id": hit["_id"],
                            "if_seq_no": hit["_seq_no"],
                            "if_primary_term": hit["_primary_term"],
                        }
                    }
                )
                for hit in hits
            ]
            bulk = await client.post(
                self.config.elasticsearch_url + "/_bulk",
                content="\n".join(operations) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
            )
            bulk.raise_for_status()
            items = bulk.json().get("items")
            if not isinstance(items, list) or len(items) != len(hits):
                raise ValueError("History deletion returned incomplete confirmation")
            for item in items:
                outcome = item["delete"]
                if outcome.get("status") == 200 and outcome.get("result") == "deleted":
                    snapshot.deleted += 1
                elif outcome.get("status") == 409:
                    snapshot.conflicts += 1
                elif outcome.get("status") == 404:
                    continue  # Already removed independently.
                else:
                    raise ValueError("A history document could not be deleted")
            cursor = hits[-1]["sort"]
        if snapshot.indexes:
            await self._es(client, "POST", f"/{','.join(snapshot.indexes)}/_refresh")
        return snapshot.deleted, snapshot.conflicts

    async def cancel(self, token: str) -> dict[str, Any]:
        """Close unused PITs; running cleanup cannot be canceled midway."""
        async with self.lock:
            plan = self.plans.get(token)
            if plan is not None:
                if plan.running:
                    raise HTTPException(409, "History clearing is already running")
                async with httpx.AsyncClient(timeout=30) as client:
                    await self._close(client, plan)
                del self.plans[token]
        return {"status": "cancelled", "ingestionUnchanged": True}

    async def execute(self, token: str) -> dict[str, Any]:
        """Consume one confirmed plan and preserve partial failure information."""
        async with self.lock:
            plan = self.plans.get(token)
            if plan is None:
                raise HTTPException(409, "History preview is unknown; preview again")
            if plan.result is not None:
                return plan.result
            if plan.running:
                raise HTTPException(409, "History clearing is already running")
            if plan.expires < datetime.now(UTC):
                raise HTTPException(409, "History preview expired; preview again")
            plan.running = True
        deleted: dict[str, int] = {}
        retained = {category: snapshot.retained for category, snapshot in plan.categories.items()}
        failures = dict(plan.failures)
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                for category, snapshot in plan.categories.items():
                    try:
                        deleted[category], conflicts = await self._delete_snapshot(client, snapshot)
                        retained[category] += conflicts
                    except Exception:
                        deleted[category] = snapshot.deleted
                        retained[category] += snapshot.conflicts
                        logger.warning("History clear category failed: %s", category, exc_info=True)
                        failures[category] = "History cleanup could not be fully confirmed; some old records may remain"
                media_result = await clear_history_media(self.config, plan.media)
                deleted.update(media_result["deletedByCategory"])
                retained.update(media_result["retainedByCategory"])
                failures.update(media_result["failures"])
            finally:
                await self._close(client, plan)
                plan.running = False
        result: dict[str, Any] = {
            "status": "partial" if failures else "success",
            "cutoff": plan.cutoff.isoformat(),
            "sourceIds": plan.source_ids,
            "deletedByCategory": deleted,
            "retainedByCategory": retained,
            "failures": failures,
            "ingestionUnchanged": True,
        }
        plan.result = result
        return result


def create_history_clear_router(config: HistoryConfig) -> APIRouter:
    """Register preview and confirmation without invoking producer lifecycle APIs."""
    router = APIRouter()
    service = HistoryClearService(config)

    @router.get("/api/v1/history-clear/preview", tags=["History"])
    async def preview() -> dict[str, Any]:
        return await service.preview()

    @router.post("/api/v1/history-clear", tags=["History"])
    async def execute(request: ClearHistoryRequest) -> dict[str, Any]:
        return await service.execute(request.plan_token)

    @router.delete("/api/v1/history-clear", tags=["History"])
    async def cancel(request: CancelHistoryRequest) -> dict[str, Any]:
        return await service.cancel(request.plan_token)

    return router


def register_history_clear_routes(app: FastAPI, config: Any) -> None:  # NAT frontend config is dynamically composed.
    """Use the existing streaming service configuration and URLs."""
    from vss_agents.api.rtsp_ingest import _resolve_service_config

    app.include_router(create_history_clear_router(_resolve_service_config(config)))
