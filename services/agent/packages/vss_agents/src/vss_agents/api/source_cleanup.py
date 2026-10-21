# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Source-scoped cleanup for generated VSS search and analytics data."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import quote

from elasticsearch import AsyncElasticsearch
from elasticsearch import NotFoundError

from vss_agents.utils.sanitize import scrub_log

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


async def registered_rtvi_cv_stream_ids(client: httpx.AsyncClient, base_url: str) -> set[str]:
    """Return the source IDs that a specific RTVI-CV worker actually owns.

    RTVI-CV's remove endpoint is not reliably idempotent: some releases can
    tear down an unrelated active pipeline when asked to remove an unknown
    camera ID.  Lifecycle callers therefore use this inventory as a safety
    precondition before issuing a remove request.  Malformed responses raise
    so callers can distinguish an authoritative empty inventory from a worker
    whose state could not be read.
    """
    endpoint = base_url.rstrip("/")
    if not endpoint:
        return set()

    response = await client.get(f"{endpoint}/api/v1/stream/get-stream-info")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("RTVI-CV stream inventory returned an unexpected response")
    stream_info = payload.get("stream-info")
    if not isinstance(stream_info, dict):
        raise RuntimeError("RTVI-CV stream inventory is missing stream-info")
    streams = stream_info.get("stream-info")
    if not isinstance(streams, list):
        raise RuntimeError("RTVI-CV stream inventory is missing its stream list")

    return {
        stream_id
        for stream in streams
        if isinstance(stream, dict)
        and isinstance((stream_id := stream.get("camera_id") or stream.get("camera-id")), str)
        and stream_id
    }


# A source can be represented by its immutable VST ID in uploaded-video data
# and by its friendly sensor name in live pipelines. Query both exact values
# across every field used by the released VSS producers.
GENERATED_INDEX_FIELDS: dict[str, tuple[str, ...]] = {
    "embeddings": (
        "sensor.id.keyword",
        "info.sensorId.keyword",
    ),
    "detections": (
        "sensorId.keyword",
        "sensor.id.keyword",
        "info.sensorId.keyword",
    ),
    "behavior": (
        "sensor.id.keyword",
        "info.sensorId.keyword",
        "sensorId.keyword",
    ),
    "incidents": (
        "sensorId.keyword",
        "sensor.id.keyword",
        "info.sensorId.keyword",
    ),
    "vlm_incidents": (
        "sensorId.keyword",
        "sensor.id.keyword",
        "info.sensorId.keyword",
        "camera_id.keyword",
    ),
}

GENERATED_INDEX_PATTERNS: dict[str, str] = {
    "embeddings": "mdx-embed-filtered-*",
    "detections": "mdx-raw-*",
    "behavior": "mdx-behavior-*",
    "incidents": "mdx-incidents-*",
    "vlm_incidents": "mdx-vlm-incidents-*",
}

# Detector indexes can be large enough that Elasticsearch continues a
# delete-by-query after the client would otherwise give up.  Give the request
# a realistic window, then verify the exact source-scoped postcondition rather
# than treating transport timing as proof that records survived.
GENERATED_DELETE_TIMEOUT_SECONDS = 120
GENERATED_DELETE_ATTEMPTS = 2


@dataclass(frozen=True)
class GeneratedDataCleanup:
    """Outcome of deleting all generated records owned by one source."""

    deleted_documents: dict[str, int]
    deleted_collections: tuple[str, ...]
    failures: dict[str, str]

    @property
    def success(self) -> bool:
        return not self.failures

    @property
    def total_deleted(self) -> int:
        return sum(self.deleted_documents.values())


async def delete_lvs_graph_history(
    client: httpx.AsyncClient,
    lvs_backend_url: str,
    source_id: str,
) -> tuple[bool, str]:
    """Delete graph-Q&A knowledge owned by one source.

    LVS cleanup is deliberately independent from Elasticsearch cleanup: the
    graph may exist even after its caption collection has been removed. The
    endpoint is idempotent, so lifecycle retries are safe.
    """
    if not lvs_backend_url:
        return True, "Skipped (not configured)"
    try:
        response = await client.delete(f"{lvs_backend_url.rstrip('/')}/v1/qa/{quote(source_id, safe='')}")
        if response.status_code == 404:
            return True, "Already absent"
        if response.status_code != 200:
            return False, f"Video history returned {response.status_code}"
        try:
            payload = response.json()
        except Exception:
            return False, "Video history returned unreadable confirmation"
        if payload.get("deleted") is not True or str(payload.get("id")) != source_id:
            return False, "Video history returned invalid deletion confirmation"
        return True, "OK"
    except Exception as exc:
        logger.error(
            "Graph history cleanup failed for %s",
            scrub_log(source_id),
            exc_info=True,
        )
        return False, str(exc)


def _source_identity_query(source_id: str, source_name: str, fields: tuple[str, ...]) -> dict[str, Any]:
    names = [source_name] if source_name else []
    if "." in source_name and source_name.rsplit(".", 1)[1].casefold() in {
        "avi",
        "m4v",
        "mkv",
        "mov",
        "mp4",
        "webm",
    }:
        # Older upload and RT-CV paths disagreed on whether camera_name kept
        # the media extension. Querying both exact aliases prevents stale
        # detector evidence without broad substring matching.
        names.append(source_name.rsplit(".", 1)[0])
    values = tuple(dict.fromkeys(value for value in (source_id, *names) if value))
    return {
        "bool": {
            "minimum_should_match": 1,
            "should": [{"term": {field: value}} for field in fields for value in values],
        }
    }


def _collection_name(source_id: str) -> str:
    safe_id = source_id
    for separator in ("-", "/", "\\", " "):
        safe_id = safe_id.replace(separator, "_")
    return f"default_{safe_id.lower()}"


def _complete_delete_result(result: Any) -> tuple[bool, int, str]:
    timed_out = result.get("timed_out")
    failures = result.get("failures")
    version_conflicts = result.get("version_conflicts")
    deleted = result.get("deleted")
    complete = (
        timed_out is False
        and failures == []
        and type(version_conflicts) is int
        and version_conflicts == 0
        and type(deleted) is int
        and deleted >= 0
    )
    if complete:
        return True, deleted, ""
    return (
        False,
        0,
        "Delete incomplete: "
        f"timed_out_valid={timed_out is False}, failures_valid={failures == []}, "
        f"version_conflicts_valid={type(version_conflicts) is int and version_conflicts == 0}, "
        f"deleted_valid={type(deleted) is int and deleted >= 0}",
    )


async def _count_generated_documents(
    client: AsyncElasticsearch,
    index_pattern: str,
    query: dict[str, Any],
) -> int:
    result = await client.count(
        index=index_pattern,
        body={"query": query},
        allow_no_indices=True,
        ignore_unavailable=True,
    )
    count = result.get("count")
    if type(count) is not int or count < 0:
        raise ValueError("Elasticsearch returned an invalid source document count")
    return count


async def _delete_generated_category(
    client: AsyncElasticsearch,
    index_pattern: str,
    query: dict[str, Any],
) -> tuple[int, str]:
    """Delete one category and prove that no exact source matches remain."""
    try:
        initial_count = await _count_generated_documents(client, index_pattern, query)
    except NotFoundError:
        return 0, ""
    if initial_count == 0:
        return 0, ""

    remaining = initial_count
    last_failure = ""
    for attempt in range(1, GENERATED_DELETE_ATTEMPTS + 1):
        try:
            result = await client.delete_by_query(
                index=index_pattern,
                body={"query": query},
                refresh=True,
                conflicts="proceed",
                allow_no_indices=True,
                ignore_unavailable=True,
            )
            complete, _deleted, failure = _complete_delete_result(result)
            if not complete:
                last_failure = failure
        except NotFoundError:
            return initial_count, ""
        except Exception as exc:
            # The server may have completed the task after the transport timed
            # out.  The exact follow-up count below is the source of truth.
            last_failure = str(exc)
            logger.warning(
                "Generated-data delete attempt %d/%d returned before confirmation",
                attempt,
                GENERATED_DELETE_ATTEMPTS,
                exc_info=True,
            )

        try:
            remaining = await _count_generated_documents(client, index_pattern, query)
        except NotFoundError:
            remaining = 0
        except Exception as exc:
            last_failure = f"Post-delete verification failed: {exc}"
            if attempt == GENERATED_DELETE_ATTEMPTS:
                break
            continue

        if remaining == 0:
            return initial_count, ""
        last_failure = f"Delete incomplete: {remaining} exact source documents remain"

    deleted = max(0, initial_count - remaining)
    return deleted, last_failure or "Delete could not be verified"


async def delete_generated_source_data(
    elasticsearch_url: str,
    source_id: str,
    source_name: str,
    *,
    categories: tuple[str, ...] | None = None,
    delete_caption_collection: bool = True,
) -> GeneratedDataCleanup:
    """Delete embeddings, detections, analytics, incidents, and captions for one source.

    Wildcard index patterns deliberately span every date partition. Exact
    keyword terms and both known source identities prevent data from another
    source with a similar name from being removed.
    """
    deleted_documents: dict[str, int] = {}
    deleted_collections: list[str] = []
    failures: dict[str, str] = {}
    selected_categories = categories or tuple(GENERATED_INDEX_PATTERNS)
    unknown_categories = set(selected_categories) - set(GENERATED_INDEX_PATTERNS)
    if unknown_categories:
        raise ValueError(f"Unknown generated-data categories: {sorted(unknown_categories)}")

    client = AsyncElasticsearch(
        elasticsearch_url,
        request_timeout=GENERATED_DELETE_TIMEOUT_SECONDS,
        max_retries=2,
        retry_on_timeout=True,
    )
    try:
        for category in selected_categories:
            index_pattern = GENERATED_INDEX_PATTERNS[category]
            query = _source_identity_query(
                source_id,
                source_name,
                GENERATED_INDEX_FIELDS[category],
            )
            try:
                deleted, failure = await _delete_generated_category(
                    client,
                    index_pattern,
                    query,
                )
                deleted_documents[category] = deleted
                if not failure:
                    logger.info(
                        "Deleted %s %s documents for source %s",
                        deleted,
                        category,
                        scrub_log(source_id),
                    )
                else:
                    failures[category] = failure
            except NotFoundError:
                deleted_documents[category] = 0
            except Exception as exc:
                logger.error(
                    "Generated-data cleanup failed for %s (%s)",
                    scrub_log(source_id),
                    category,
                    exc_info=True,
                )
                failures[category] = str(exc)

        # LVS/RTVI-VLM caption collections are source-specific indexes rather
        # than date partitions. Deleting the exact normalized index is safe;
        # Logstash recreates it if the live source is analyzed again.
        if delete_caption_collection:
            collection = _collection_name(source_id)
            try:
                if await client.indices.exists(index=collection):
                    count_result = await client.count(index=collection)
                    count = count_result.get("count", 0)
                    delete_result = await client.indices.delete(index=collection)
                    if delete_result.get("acknowledged") is True:
                        deleted_collections.append(collection)
                        deleted_documents["captions"] = count if type(count) is int else 0
                    else:
                        failures["captions"] = "Elasticsearch did not acknowledge collection deletion"
                else:
                    deleted_documents["captions"] = 0
            except NotFoundError:
                deleted_documents["captions"] = 0
            except Exception as exc:
                logger.error(
                    "Caption collection cleanup failed for %s",
                    scrub_log(source_id),
                    exc_info=True,
                )
                failures["captions"] = str(exc)
    finally:
        await client.close()

    return GeneratedDataCleanup(
        deleted_documents=deleted_documents,
        deleted_collections=tuple(deleted_collections),
        failures=failures,
    )
