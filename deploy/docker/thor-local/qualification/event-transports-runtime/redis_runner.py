#!/usr/bin/env python3
"""Exercise the mounted NVIDIA Redis stream sink/source against local Redis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

from mdx.analytics.core.schema.config import AppConfig
from mdx.analytics.core.stream.sink.sink_redis_stream import SinkRedisStream
from mdx.analytics.core.stream.source.source_redis_stream import SourceRedisStream


SOURCE_ROOT = Path("/workspace/behavior/src")
SINK_SOURCE = SOURCE_ROOT / "mdx/analytics/core/stream/sink/sink_redis_stream.py"
SOURCE_SOURCE = SOURCE_ROOT / "mdx/analytics/core/stream/source/source_redis_stream.py"
STREAM = "vss-protocol-case-redis-events"
GROUP_BASE = "vss-protocol-case-redis-group"


def _run() -> dict[str, object]:
    config = AppConfig(
        redisStream={
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "streams": [{"name": "events", "value": STREAM}],
            "consumer": {
                "readCount": 200,
                "readBlockMs": 100,
                "mkstream": True,
                "retryMaxAttempts": 1,
                "retryIntervalSec": 0,
            },
            "producer": {"maxLen": 10000},
            "group": GROUP_BASE,
        }
    )
    sink = SinkRedisStream(config)
    source = SourceRedisStream(config)
    effective_group = source._get_group_id(STREAM, GROUP_BASE)

    # Create the production consumer group before XADD so '>' receives the one fixture.
    conn = source._get_consumer(STREAM, effective_group)
    payload = b'{"case_id":"vss-protocol-case-redis-001"}'
    key = b"vss-protocol-case-redis-001"
    headers = {"content-type": "application/json"}
    sink.write_msg("events", payload, key, headers)
    messages = source.read("events")
    if len(messages) != 1:
        raise RuntimeError(f"expected one Redis StreamMessage, received {len(messages)}")
    message = messages[0]
    positive_match = (
        message.key == key
        and message.value == payload
        and message.headers == {"content-type": b"application/json"}
        and isinstance(message.timestamp, int)
        and message.timestamp > 0
    )
    if not positive_match:
        raise RuntimeError("production Redis source did not preserve the envelope")
    pending_after_positive = conn.xpending(STREAM, effective_group)["pending"]
    if pending_after_positive != 0:
        raise RuntimeError("positive Redis entry was not acknowledged")

    negative_id = conn.xadd(
        STREAM,
        {
            "key": key,
            "value": payload,
            "headers": "{",
        },
        maxlen=10000,
        approximate=True,
    )
    negative_type = None
    try:
        source.read("events")
    except json.JSONDecodeError as exc:
        negative_type = type(exc).__name__
    if negative_type != "JSONDecodeError":
        raise RuntimeError("malformed Redis headers did not take JSON rejection path")
    pending_after_negative = conn.xpending(STREAM, effective_group)["pending"]
    if pending_after_negative != 1:
        raise RuntimeError("malformed Redis entry was unexpectedly acknowledged")

    sink.close()
    source.close()
    return {
        "status": "passed",
        "source_sha256": {
            "sink": hashlib.sha256(SINK_SOURCE.read_bytes()).hexdigest(),
            "source": hashlib.sha256(SOURCE_SOURCE.read_bytes()).hexdigest(),
        },
        "production_classes": ["SinkRedisStream", "SourceRedisStream"],
        "effective_group_derived_by_source": True,
        "positive": {
            "vector_id": "redis-one-events-envelope",
            "message_count": len(messages),
            "key_match": message.key == key,
            "value_match": message.value == payload,
            "headers_match": message.headers == {"content-type": b"application/json"},
            "timestamp_from_entry_id": message.timestamp > 0,
            "pending_after_xack": pending_after_positive,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
        "negative": {
            "vector_id": "redis-malformed-headers",
            "rejection": negative_type,
            "entry_pending_before_cleanup": pending_after_negative,
            "entry_id_observed": bool(negative_id),
        },
    }


def main() -> int:
    started = time.monotonic()
    try:
        result = _run()
        result["duration_ms"] = round((time.monotonic() - started) * 1000)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"redis runner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
