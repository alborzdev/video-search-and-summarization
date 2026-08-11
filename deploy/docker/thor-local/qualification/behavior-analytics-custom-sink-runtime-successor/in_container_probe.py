#!/usr/bin/env python3
"""Exercise the custom Sink implementation inside the released VSS image."""

from __future__ import annotations

import argparse
import base64
import hashlib
import inspect
import json
from pathlib import Path

from custom_sink import JsonlFileSink
from mdx.analytics.core.schema.proto import ext_pb2
from mdx.analytics.core.stream.sink.sink_base import (
    JsonBytesSerializer,
    ProtoBytesSerializer,
    Sink,
    StrBytesSerializer,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _bytes(field: dict[str, str] | None) -> bytes | None:
    if field is None:
        return None
    if field["encoding"] == "base64":
        return base64.b64decode(field["value"], validate=True)
    if field["encoding"] == "utf-8":
        return field["value"].encode()
    raise ValueError(f"unknown wire encoding: {field['encoding']}")


def run(output_dir: Path) -> dict:
    event_path = output_dir / "events.jsonl"
    incident_path = output_dir / "incidents.jsonl"
    if not issubclass(JsonlFileSink, Sink) or inspect.isabstract(JsonlFileSink):
        raise RuntimeError("custom sink does not concretely implement Sink")

    sink = JsonlFileSink({"events": event_path, "incidents": incident_path})
    events = [
        {"id": "event-1", "type": "roi:ENTRY", "sensor": "Camera_01"},
        {"id": "event-2", "type": "tripwire:OUT", "sensor": "Camera_02"},
    ]
    sink.write(
        "events",
        events,
        JsonBytesSerializer,
        key_extractor=lambda value: value["id"],
        key_serializer=StrBytesSerializer,
        headers={"schema": "event-json", "binary": b"\x00\x01"},
    )
    raw_payload = b"\x00raw\xff"
    sink.write_msg(
        "events",
        raw_payload,
        b"raw-1",
        headers={"schema": "opaque-bytes"},
    )
    incident = ext_pb2.Incident(category="FOV Count Violation", sensorId="Camera_01")
    incident.objectIds.append("person-1")
    sink.write(
        "incidents",
        [incident],
        ProtoBytesSerializer,
        key_extractor=lambda value: value.sensorId,
        key_serializer=StrBytesSerializer,
        headers={"schema": "nv.Incident"},
    )
    sink.close()
    sink.close()

    event_rows = _load_rows(event_path)
    incident_rows = _load_rows(incident_path)
    decoded_events = [json.loads(_bytes(row["value"])) for row in event_rows[:2]]
    decoded_incident = ext_pb2.Incident()
    decoded_incident.ParseFromString(_bytes(incident_rows[0]["value"]))
    if decoded_events != events:
        raise RuntimeError("JSON batch serialization drifted")
    if _bytes(event_rows[2]["value"]) != raw_payload:
        raise RuntimeError("single-message bytes were not preserved")
    if [value["id"] for value in decoded_events] != ["event-1", "event-2"]:
        raise RuntimeError("batch ordering drifted")
    if [_bytes(row["key"]).decode() for row in event_rows] != ["event-1", "event-2", "raw-1"]:
        raise RuntimeError("key extraction/serialization drifted")
    if _bytes(event_rows[0]["headers"]["binary"]) != b"\x00\x01":
        raise RuntimeError("binary header drifted")
    if decoded_incident.category != "FOV Count Violation":
        raise RuntimeError("protobuf category drifted")
    if decoded_incident.sensorId != "Camera_01" or list(decoded_incident.objectIds) != ["person-1"]:
        raise RuntimeError("protobuf identity drifted")

    return {
        "interface": {
            "base_class": "Sink",
            "concrete": True,
            "implemented_methods": ["write", "write_msg", "close"],
        },
        "batch_write": {
            "records": 2,
            "event_ids": [value["id"] for value in decoded_events],
            "event_types": [value["type"] for value in decoded_events],
            "keys": [_bytes(row["key"]).decode() for row in event_rows[:2]],
            "json_bytes_serializer": True,
            "binary_header_preserved": True,
        },
        "single_write": {
            "records": 1,
            "key": _bytes(event_rows[2]["key"]).decode(),
            "payload_sha256": hashlib.sha256(_bytes(event_rows[2]["value"])).hexdigest(),
            "opaque_bytes_preserved": True,
        },
        "protobuf_write": {
            "records": 1,
            "key": _bytes(incident_rows[0]["key"]).decode(),
            "category": decoded_incident.category,
            "sensor_id": decoded_incident.sensorId,
            "object_ids": list(decoded_incident.objectIds),
            "proto_bytes_serializer": True,
        },
        "outputs": {
            "destinations": ["events", "incidents"],
            "event_records": len(event_rows),
            "incident_records": len(incident_rows),
            "events_sha256": _sha(event_path),
            "incidents_sha256": _sha(incident_path),
            "double_close_safe": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
