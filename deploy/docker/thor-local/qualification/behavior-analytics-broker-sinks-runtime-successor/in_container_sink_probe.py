#!/usr/bin/env python3
"""Publish all advertised Behavior Analytics output families through one built-in sink."""

from __future__ import annotations

import argparse
import hashlib
import json
import time

from mdx.analytics.core.schema.config import AppConfig
from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2
from mdx.analytics.core.stream.sink.sink_base import ProtoBytesSerializer, StrBytesSerializer
from mdx.analytics.core.stream.sink.sink_factory import get_sink


FAMILIES = {
    "frames": "frames",
    "behaviors": "behavior",
    "events": "events",
    "incidents": "incidents",
    "anomalies": "anomaly",
    "cluster": "behaviorPlus",
    "space-utilization": "spaceUtilization",
}


def _mapping(backend: str) -> dict[str, str]:
    prefix = f"vss-sink-matrix-{backend}"
    if backend == "mqtt":
        return {dest: f"vss/sink/matrix/{dest}" for dest in FAMILIES.values()}
    return {dest: f"{prefix}-{dest}" for dest in FAMILIES.values()}


def _config(backend: str, mapping: dict[str, str]) -> AppConfig:
    entries = [{"name": key, "value": value} for key, value in mapping.items()]
    common = {"app": [{"name": "sinkType", "value": backend}]}
    if backend == "kafka":
        common["kafka"] = {
            "brokers": "localhost:9092",
            "group": "vss-sink-matrix",
            "topics": entries,
            "producer": {"lingerMs": 0},
        }
    elif backend == "redisStream":
        common["redisStream"] = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "group": "vss-sink-matrix",
            "streams": entries,
            "producer": {"maxLen": 1000},
        }
    else:
        common["mqtt"] = {
            "host": "localhost",
            "port": 1883,
            "clientId": "vss-sink-matrix-producer",
            "keepAliveSec": 30,
            "topics": entries,
            "producer": {"qos": 1, "retain": False},
        }
    return AppConfig(**common)


def _messages() -> dict[str, tuple[object, str]]:
    sensor = "sink-matrix-camera"
    frame = schema_pb2.Frame(id="frame-1", sensorId=sensor, version="1.0")
    frame.objects.add(id="track-1", type="Person")

    behavior = ext_pb2.Behavior(id="behavior-1")
    behavior.sensor.id = sensor
    behavior.object.id = "track-1"

    event = ext_pb2.Behavior(id="event-1")
    event.sensor.id = sensor
    event.object.id = "track-1"
    event.event.type = "ENTRY"
    event.event.info["class"] = "roi"

    incident = ext_pb2.Incident(sensorId=sensor, category="FOV Count Violation")
    incident.objectIds.append("track-1")

    anomaly = ext_pb2.Behavior(id="anomaly-1")
    anomaly.sensor.id = sensor
    anomaly.object.id = "track-1"
    anomaly.info["anomaly.type"] = "qualification"

    cluster = ext_pb2.Behavior(id="cluster-1")
    cluster.sensor.id = sensor
    cluster.object.id = "track-1"
    cluster.info["cluster.index"] = "7"

    space = ext_pb2.SpaceUtilization(id="zone-1")
    space.sensors.append(sensor)
    space.metrics.spaceOccupied = 1.0
    space.metrics.freeSpace = 2.0
    space.metrics.totalSpace = 3.0
    space.metrics.spaceUtilization = 1.0 / 3.0

    return {
        "frames": (frame, sensor),
        "behaviors": (behavior, sensor),
        "events": (event, sensor),
        "incidents": (incident, sensor),
        "anomalies": (anomaly, sensor),
        "cluster": (cluster, sensor),
        "space-utilization": (space, "zone-1"),
    }


def run(backend: str) -> dict:
    mapping = _mapping(backend)
    config = _config(backend, mapping)
    sink = get_sink(config)
    expected_class = {
        "kafka": "SinkKafka",
        "redisStream": "SinkRedisStream",
        "mqtt": "SinkMQTT",
    }[backend]
    if type(sink).__name__ != expected_class:
        raise RuntimeError(f"sink factory returned {type(sink).__name__}, expected {expected_class}")
    payloads = {}
    try:
        for family, (message, key) in _messages().items():
            payload = message.SerializeToString()
            payloads[family] = {
                "destination_key": FAMILIES[family],
                "broker_destination": mapping[FAMILIES[family]],
                "key": key,
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "payload_bytes": len(payload),
            }
            sink.write(
                FAMILIES[family],
                [message],
                ProtoBytesSerializer,
                key_extractor=lambda _value, key=key: key,
                key_serializer=StrBytesSerializer,
                headers={"family": family, "backend": backend},
            )
        if backend == "mqtt":
            time.sleep(1.0)
    finally:
        sink.close()
    return {
        "backend": backend,
        "factory_class": type(sink).__name__,
        "families": payloads,
        "family_count": len(payloads),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("kafka", "redisStream", "mqtt"))
    args = parser.parse_args()
    print(json.dumps(run(args.backend), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
