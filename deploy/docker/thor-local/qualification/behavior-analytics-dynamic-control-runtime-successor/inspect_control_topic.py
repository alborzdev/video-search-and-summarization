#!/usr/bin/env python3
"""Summarize an isolated Behavior Analytics control topic without identifiers."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import time

from confluent_kafka import Consumer, KafkaError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--idle-sec", type=float, default=5.0)
    args = parser.parse_args()

    consumer = Consumer({
        "bootstrap.servers": args.bootstrap_servers,
        "group.id": f"vss-behavior-control-inspector-{time.time_ns()}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.partition.eof": True,
    })
    consumer.subscribe([args.topic])
    key_counts: Counter[str] = Counter()
    event_counts: dict[str, Counter[str]] = {
        "behavior-analytics-config": Counter(),
        "calibration": Counter(),
    }
    ack_statuses: Counter[str] = Counter()
    calibration_types: Counter[str] = Counter()
    config_sections: Counter[str] = Counter()
    record_count = 0
    eof_seen = False
    last_record_at = time.monotonic()
    deadline = last_record_at + 30
    try:
        while time.monotonic() < deadline:
            message = consumer.poll(0.5)
            if message is None:
                if eof_seen and time.monotonic() - last_record_at >= args.idle_sec:
                    break
                continue
            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    eof_seen = True
                    continue
                raise RuntimeError(str(message.error()))
            record_count += 1
            last_record_at = time.monotonic()
            key = (message.key() or b"").decode("utf-8", errors="replace")
            key_counts[key] += 1
            headers = {
                name: (value or b"").decode("utf-8", errors="replace")
                for name, value in (message.headers() or [])
            }
            event_type = headers.get("event.type", "missing")
            if key in event_counts:
                event_counts[key][event_type] += 1
            try:
                body = json.loads((message.value() or b"{}").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if key == "behavior-analytics-config" and isinstance(body, dict):
                status = body.get("status")
                if event_type == "ack":
                    ack_statuses[str(status)] += 1
                config = body.get("config")
                if isinstance(config, dict):
                    config_sections.update(config.keys())
            elif key == "calibration" and isinstance(body, dict):
                value = body.get("calibrationType")
                if isinstance(value, str):
                    calibration_types[value] += 1
    finally:
        consumer.close()

    result = {
        "record_count": record_count,
        "key_counts": dict(sorted(key_counts.items())),
        "event_counts": {
            key: dict(sorted(counts.items())) for key, counts in sorted(event_counts.items())
        },
        "ack_statuses": dict(sorted(ack_statuses.items())),
        "config_sections_observed": dict(sorted(config_sections.items())),
        "calibration_types_observed": dict(sorted(calibration_types.items())),
        "identifiers_retained": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if record_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
