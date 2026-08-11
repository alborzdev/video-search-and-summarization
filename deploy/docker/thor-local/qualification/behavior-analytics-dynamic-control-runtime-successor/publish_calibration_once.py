#!/usr/bin/env python3
"""Publish one schema-valid calibration snapshot to a qualification topic."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from confluent_kafka import Producer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.payload.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("calibrationType") not in {"image", "cartesian", "geo"}:
        raise ValueError("payload must be an image, cartesian, or geo calibration object")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    producer = Producer({"bootstrap.servers": args.bootstrap_servers})
    producer.produce(
        topic=args.topic,
        key=b"calibration",
        value=json.dumps(value, separators=(",", ":")).encode("utf-8"),
        headers=[("event.type", b"upsert-all"), ("timestamp", timestamp.encode("utf-8"))],
    )
    remaining = producer.flush(timeout=10)
    if remaining:
        raise RuntimeError(f"{remaining} calibration message(s) were not delivered")
    print(json.dumps({
        "status": "published",
        "calibration_type": value["calibrationType"],
        "sensor_count": len(value.get("sensors", [])),
        "topic": args.topic,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
