# SPDX-License-Identifier: Apache-2.0
"""NVSchema adapter. It accepts the existing generated protobuf Frame object.

Transport ownership remains in VSS. This module does not invent session epochs
or treat NVSchema geometry as calibrated city coordinates.
"""
from __future__ import annotations
from datetime import datetime, timezone


def from_frame(frame, *, site_id: str, source_id: str, session_id: str, width: int, height: int, sequence: int | str | None = None) -> dict:
    info = dict(getattr(frame, "info", {}))
    # Protobuf Timestamp retains integer precision; do not round-trip via float.
    timestamp = getattr(frame, "timestamp", None)
    if timestamp is None:
        raise ValueError("NVSchema frame has no timestamp")
    if hasattr(timestamp, "seconds"):
        ns = timestamp.seconds * 1_000_000_000 + timestamp.nanos
    elif isinstance(timestamp, str):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        ns = int(parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp() * 1e9)
    else:
        raise ValueError("unsupported NVSchema timestamp representation")
    objects = []
    for obj in frame.objects:
        object_info = dict(getattr(obj, "info", {}))
        box = obj.bbox
        objects.append({"localTrackId": str(obj.id), "class": object_info.get("ct.city.class", obj.type), "confidence": obj.confidence if getattr(obj, "confidence", None) is not None else None, "bboxPx": [box.leftX, box.topY, box.rightX - box.leftX, box.bottomY - box.topY], "observedThisFrame": object_info.get("ct.city.observedThisFrame", "true").lower() != "false", "globalTrackId": object_info.get("ct.city.globalTrackId"), "associationMethod": object_info.get("ct.city.associationMethod")})
    return {"schemaVersion": "city.observations.v1", "siteId": site_id, "sourceId": source_id, "sourceSessionId": session_id, "sequence": str(sequence if sequence is not None else frame.id), "sourceFrameId": str(frame.id), "sourceTimeNs": str(ns), "timestampBasis": info.get("ct.city.timestampBasis", "nvschema-declared"), "modelRevision": info.get("ct.city.modelRevision"), "image": {"width": width, "height": height}, "objects": objects}
