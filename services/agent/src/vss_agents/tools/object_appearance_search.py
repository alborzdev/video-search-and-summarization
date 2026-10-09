# SPDX-License-Identifier: Apache-2.0
"""Bounded retained-detection appearance search with the already loaded Cosmos model.

This provider has its own 768-dimensional index. Detector/ReID vectors from other
models are never read as Cosmos vectors or written into the legacy behavior index.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from datetime import timedelta
import hashlib
import math
import os
from typing import TYPE_CHECKING
from typing import Any
import uuid

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

import aiohttp

INDEX = "mdx-appearance-cosmos-768-v1"
PROVIDER = "cosmos-embed1-448p-anomaly-detection/image-v1"
_LOCK = asyncio.Lock()


def enabled() -> bool:
    return os.getenv("VSS_OBJECT_APPEARANCE_ENABLED", "false").lower() == "true"


def document_id(sensor_id: str, object_id: str, timestamp: str) -> str:
    return hashlib.sha256(f"{PROVIDER}\0{sensor_id}\0{object_id}\0{timestamp}".encode()).hexdigest()


def valid_vector(vector: Any) -> bool:
    return (
        isinstance(vector, list)
        and len(vector) == 768
        and all(isinstance(x, (float, int)) and math.isfinite(x) for x in vector)
        and any(x != 0 for x in vector)
    )


async def _json(session: aiohttp.ClientSession, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with session.post(url, json=payload) as response:
        response.raise_for_status()
        return await response.json()


async def _encode(session: aiohttp.ClientSession, detection: dict[str, Any], sensor_id: str) -> list[float]:
    crop = await _json(
        session,
        os.getenv("VSS_OBJECT_APPEARANCE_CROP_URL", "http://127.0.0.1:8098/appearance-crop"),
        {
            "sensorId": sensor_id,
            "timestamp": detection["timestamp"],
            "bbox": detection["bbox"],
        },
    )
    image = crop.get("image_base64", "")
    if not image or len(base64.b64decode(image, validate=True)) > 4 * 1024 * 1024:
        raise ValueError("The retained detection crop is unavailable or too large.")
    result = await _json(
        session,
        os.getenv("VSS_OBJECT_APPEARANCE_EMBED_URL", "http://127.0.0.1:8017").rstrip("/")
        + "/v1/generate_video_embeddings",
        {
            "id": str(uuid.uuid4()),
            "url": "data:image/png;base64," + image,
            "media_type": "image",
            "model": PROVIDER.split("/")[0],
            "stream": False,
            "publish_results": False,
        },
    )
    chunks = result.get("chunk_responses", [])
    vector = chunks[0].get("embeddings", []) if chunks else []
    if not valid_vector(vector):
        raise ValueError("The appearance encoder did not return a finite 768-dimensional vector.")
    return vector


async def _detections(
    es: AsyncElasticsearch,
    aliases: list[str],
    timestamp: datetime,
    object_id: str | None = None,
    object_type: str | None = None,
    limit: int = 120,
    timestamp_start: datetime | None = None,
    timestamp_end: datetime | None = None,
) -> list[dict[str, Any]]:
    window = timedelta(seconds=1) if object_id is not None else timedelta(hours=2)
    start = max(timestamp - window, timestamp_start) if timestamp_start else timestamp - window
    end = min(timestamp + window, timestamp_end) if timestamp_end else timestamp + window
    if start > end:
        return []
    filters = [
        {"terms": {"sensorId.keyword": aliases}},
        {
            "range": {
                "timestamp": {
                    "gte": start.isoformat(),
                    "lte": end.isoformat(),
                }
            }
        },
    ]
    nested_filters = []
    if object_id is not None:
        nested_filters.append({"term": {"objects.id.keyword": str(object_id)}})
    if object_type:
        nested_filters.append({"term": {"objects.type.keyword": object_type}})
    if nested_filters:
        filters.append({"nested": {"path": "objects", "query": {"bool": {"filter": nested_filters}}}})
    response = await es.search(
        index="mdx-raw-*",
        ignore_unavailable=True,
        body={
            "query": {"bool": {"filter": filters}},
            "size": limit,
            "sort": [{"timestamp": "desc"}],
            "_source": ["timestamp", "sensorId", "objects.id", "objects.type", "objects.bbox"],
        },
    )
    detections = []
    for hit in response["hits"]["hits"]:
        frame = hit["_source"]
        for obj in frame.get("objects", []):
            if object_id is not None and str(obj.get("id")) != str(object_id):
                continue
            if object_type and obj.get("type") != object_type:
                continue
            bbox = obj.get("bbox", {})
            if not all(
                isinstance(bbox.get(k), (float, int)) and math.isfinite(bbox[k])
                for k in ("leftX", "topY", "rightX", "bottomY")
            ):
                continue
            if bbox["rightX"] <= bbox["leftX"] or bbox["bottomY"] <= bbox["topY"]:
                continue
            detections.append(
                {
                    "timestamp": frame["timestamp"],
                    "object_id": str(obj["id"]),
                    "object_type": obj.get("type", "Unknown"),
                    "bbox": bbox,
                }
            )
    return detections


async def _cached_vector(es: AsyncElasticsearch, seed_key: str) -> list[float]:
    # Elasticsearch 9 excludes dense vectors from _source unless explicitly
    # requested. Cache hits must retrieve real stored features, not regenerate.
    response = await es.search(
        index=INDEX,
        body={
            "size": 1,
            "query": {"ids": {"values": [seed_key]}},
            "_source": {"includes": ["vector"], "exclude_vectors": False},
        },
    )
    hits = response["hits"]["hits"]
    if not hits or not valid_vector(hits[0]["_source"].get("vector")):
        raise ValueError("The cached appearance vector could not be read from its isolated index.")
    return hits[0]["_source"]["vector"]


async def search_reference_appearance(
    *,
    object_id: str,
    es: AsyncElasticsearch,
    reference_sensor_id: str | None = None,
    reference_sensor_name: str | None = None,
    reference_timestamp: datetime | None = None,
    verifiedsensor_aliases: list[str] | None = None,
    verified_sensor_aliases: list[str] | None = None,
    sensor_id: str | None = None,
    sensor_name: str | None = None,
    timestamp: datetime | None = None,
    sensor_aliases: list[str] | None = None,
    top_k: int = 5,
    min_similarity: float = 0.0,
    source_type: str = "rtsp",
    video_sources: list[str] | None = None,
    timestamp_start: datetime | None = None,
    timestamp_end: datetime | None = None,
    **_kwargs: Any,
) -> list[Any] | None:
    """Prepare at most twelve same-camera tracked-object crops, then rank genuine vectors.

    A first request performs bounded preparation; subsequent requests reuse cached
    vectors. It retrieves appearances, never establishes a person's identity.
    """
    if not enabled():
        return None
    from vss_agents.tools.attribute_search import AttributeSearchMetadata
    from vss_agents.tools.attribute_search import AttributeSearchResult

    reference_sensor_id = reference_sensor_id or sensor_id
    reference_sensor_name = reference_sensor_name or sensor_name
    reference_timestamp = reference_timestamp or timestamp
    if not reference_sensor_id or reference_timestamp is None:
        raise ValueError("An exact source UUID and detection timestamp are required.")
    aliases = list(
        dict.fromkeys(verified_sensor_aliases or verifiedsensor_aliases or sensor_aliases or [reference_sensor_id])
    )
    if reference_sensor_id not in aliases:
        aliases.append(reference_sensor_id)
    if timestamp_start and timestamp_end and timestamp_start > timestamp_end:
        raise ValueError("The appearance search end must follow its start.")
    if video_sources and not any(name in [*aliases, reference_sensor_name] for name in video_sources):
        return []
    if source_type == "video_file":
        # This helper currently prepares retained live-camera tracks only. Never
        # silently return camera data for a recorded-file-only search request.
        return []
    async with _LOCK:
        seeds = await _detections(es, aliases, reference_timestamp, object_id=object_id, limit=3)
        if not seeds:
            raise ValueError("The exact selected detection has no retained frame metadata near that timestamp.")
        seed = min(
            seeds,
            key=lambda item: abs(
                (datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")) - reference_timestamp).total_seconds()
            ),
        )
        if not await es.indices.exists(index=INDEX):
            await es.indices.create(
                index=INDEX,
                mappings={
                    "properties": {
                        "provider": {"type": "keyword"},
                        "sensor_id": {"type": "keyword"},
                        "object_id": {"type": "keyword"},
                        "object_type": {"type": "keyword"},
                        "timestamp": {"type": "date"},
                        "end": {"type": "date"},
                        "source_type": {"type": "keyword"},
                        "vector": {"type": "dense_vector", "dims": 768, "index": True, "similarity": "cosine"},
                    }
                },
            )
        preparation_start = timestamp_start or reference_timestamp - timedelta(hours=2)
        preparation_end = timestamp_end or reference_timestamp + timedelta(hours=2)
        tracks = await es.search(
            index="mdx-behavior-*",
            ignore_unavailable=True,
            body={
                "size": 48,
                "_source": ["object.id", "timestamp", "end"],
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"sensor.id.keyword": aliases}},
                            {"term": {"object.type.keyword": seed["object_type"]}},
                            {
                                "range": {
                                    "timestamp": {"lte": preparation_end.isoformat()}
                                }
                            },
                            {"range": {"end": {"gte": preparation_start.isoformat()}}},
                        ]
                    }
                },
                "sort": [{"timestamp": "desc"}],
            },
        )
        track_docs = [hit["_source"] for hit in tracks["hits"]["hits"]]
        track_docs.sort(
            key=lambda item: abs(
                (datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")) - reference_timestamp).total_seconds()
            )
        )
        candidates = []
        # Reused continuous tracks also have real appearances in other moments.
        for offset in (-12, 12):
            frames = await _detections(
                es,
                aliases,
                reference_timestamp + timedelta(seconds=offset),
                object_id=str(object_id),
                object_type=seed["object_type"],
                limit=1,
                timestamp_start=preparation_start,
                timestamp_end=preparation_end,
            )
            if frames:
                candidates.append(frames[0])
        seen_tracks = {str(object_id)}
        for track in track_docs:
            track_id = str(track.get("object", {}).get("id", ""))
            if not track_id or track_id in seen_tracks:
                continue
            seen_tracks.add(track_id)
            start = datetime.fromisoformat(track["timestamp"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(track.get("end", track["timestamp"]).replace("Z", "+00:00"))
            start = max(start, preparation_start)
            end = min(end, preparation_end)
            if start > end:
                continue
            sample = start + (end - start) / 2
            frames = await _detections(
                es, aliases, sample, object_id=track_id, object_type=seed["object_type"], limit=1,
                timestamp_start=preparation_start, timestamp_end=preparation_end,
            )
            if frames:
                candidates.append(frames[0])
            if len(candidates) >= 11:
                break
        # One representative per tracker ID, distributed around the selected time.
        candidates.sort(
            key=lambda item: abs(
                (datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")) - reference_timestamp).total_seconds()
            )
        )
        selected = [seed]
        seen = {seed["object_id"]}
        for item in candidates:
            if item["object_id"] not in seen or (
                item["object_id"] == seed["object_id"] and item["timestamp"] != seed["timestamp"]
            ):
                selected.append(item)
                seen.add(item["object_id"])
            if len(selected) >= 12:
                break
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            for detection in selected:
                key = document_id(reference_sensor_id, detection["object_id"], detection["timestamp"])
                if await es.exists(index=INDEX, id=key):
                    continue
                try:
                    vector = await _encode(session, detection, reference_sensor_id)
                    await es.index(
                        index=INDEX,
                        id=key,
                        document={
                            **detection,
                            "provider": PROVIDER,
                            "sensor_id": reference_sensor_id,
                            "sensor_name": reference_sensor_name,
                            "source_type": "rtsp",
                            "end": detection["timestamp"],
                            "vector": vector,
                        },
                    )
                except Exception:
                    if detection is seed:
                        raise
                    # Unavailable retained footage is skipped; no substitute frame
                    # or fabricated embedding is added to the appearance archive.
                    continue
        await es.indices.refresh(index=INDEX)
        seed_key = document_id(reference_sensor_id, seed["object_id"], seed["timestamp"])
        seed_doc = {"vector": await _cached_vector(es, seed_key)}
        filters = [
            {"term": {"provider": PROVIDER}},
            {"term": {"sensor_id": reference_sensor_id}},
            {"term": {"source_type": source_type}},
        ]
        if timestamp_start or timestamp_end:
            filters.append(
                {
                    "range": {
                        "timestamp": {
                            **({"gte": timestamp_start.isoformat()} if timestamp_start else {}),
                            **({"lte": timestamp_end.isoformat()} if timestamp_end else {}),
                        }
                    }
                }
            )
        response = await es.search(
            index=INDEX,
            body={
                "size": top_k,
                "knn": {
                    "field": "vector",
                    "query_vector": seed_doc["vector"],
                    "k": top_k,
                    "num_candidates": max(24, top_k),
                    "filter": {
                        "bool": {
                            "filter": filters,
                            "must_not": [
                                {
                                    "range": {
                                        "timestamp": {
                                            "gte": (reference_timestamp - timedelta(seconds=5)).isoformat(),
                                            "lte": (reference_timestamp + timedelta(seconds=5)).isoformat(),
                                        }
                                    }
                                }
                            ],
                        }
                    },
                },
                "_source": {"excludes": ["vector"]},
            },
        )
        results = []
        for hit in response["hits"]["hits"]:
            item = hit["_source"]
            score = float(hit["_score"])
            if score < min_similarity:
                continue
            stamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
            if (item.get("provider") != PROVIDER or item.get("sensor_id") != reference_sensor_id
                    or item.get("source_type") != source_type
                    or (timestamp_start and stamp < timestamp_start)
                    or (timestamp_end and stamp > timestamp_end)):
                continue
            clip_start = max(stamp - timedelta(seconds=2), timestamp_start) if timestamp_start else stamp - timedelta(seconds=2)
            clip_end = min(stamp + timedelta(seconds=3), timestamp_end) if timestamp_end else stamp + timedelta(seconds=3)
            results.append(
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(
                        sensor_id=item["sensor_id"],
                        object_id=item["object_id"],
                        object_type=item["object_type"],
                        frame_timestamp=item["timestamp"],
                        start_time=clip_start.isoformat(),
                        end_time=clip_end.isoformat(),
                        bbox=item["bbox"],
                        behavior_score=score,
                        frame_score=score,
                        video_name=item.get("sensor_name") or reference_sensor_name,
                    )
                )
            )
        return results
