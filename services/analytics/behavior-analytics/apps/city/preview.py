# SPDX-License-Identifier: Apache-2.0
"""Bounded, volatile JPEGs paired only to exact accepted inference frames."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import time
from dataclasses import dataclass
from threading import RLock

from .engine import CityEngine

MAX_JPEG_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024
MAX_PREVIEW_SOURCES = 2
PREVIEW_TTL_SECONDS = 2.0
FRAME_MEDIA_TYPE = "application/vnd.connecttech.city-frame"
MAX_NATIVE_STATUS_BYTES = 32 * 1024
MAX_PREVIEW_OTHER_EVENTS = 8
MAX_PREVIEW_TRAIL_POINTS = 12
PUBLIC_FRAME_SOURCE_FIELDS = {
    "analyticsScope",
    "trackingEpoch",
    "id",
    "name",
    "width",
    "height",
    "vssSensorId",
    "sessionId",
    "sourceSessionId",
    "sequence",
    "status",
    "lastSourceTimeNs",
    "mediaTimeSeconds",
    "mediaTimeBasis",
    "rawSourcePtsNs",
    "modelRevision",
    "timestampBasis",
    "imageToGroundHomography",
    "classImageToGroundHomographies",
    "validGroundPolygon",
    "calibrationRevision",
    "calibrationStatus",
    "durationSeconds",
    "ingestAgeSeconds",
    "sourceClockAgeSeconds",
    "sourceClockProgressRatio",
    "sourceClockPrecision",
    "sourceClockStatus",
    "sourceClockMode",
    "sourceClockEvidence",
    "browserClockVerified",
}


def native_preview_status(directory, registered_sources):
    """Read only bounded public delivery counters; these are not capture clocks."""
    result = {
        "status": "not-connected" if directory is None else "missing",
        "enabled": False,
        "failed": False,
        "sources": [],
    }
    if directory is None:
        return result
    try:
        with (directory / "preview-stats.json").open("rb") as handle:
            encoded = handle.read(MAX_NATIVE_STATUS_BYTES + 1)
        if len(encoded) > MAX_NATIVE_STATUS_BYTES:
            raise ValueError("native status exceeds limit")
        value = json.loads(encoded)
        if not isinstance(value, dict) or value.get("schemaVersion") != "city.preview-native-status.v1":
            raise ValueError("invalid native status schema")
        updated = value.get("updatedAtNs")
        if (
            not isinstance(updated, str)
            or not re.fullmatch(r"[0-9]{1,19}", updated)
            or int(updated) > 9223372036854775807
        ):
            raise ValueError("invalid delivery timestamp")
        age = time.time() - int(updated) / 1e9
        result.update(
            status="fresh" if 0 <= age <= 5 else "stale",
            updatedAtNs=updated,
            deliveryAgeSeconds=age,
            enabled=value.get("enabled") is True,
            failed=value.get("failed") is True,
        )
        if value.get("transport") in {"jpeg", "webrtc"}:
            result["transport"] = value["transport"]
        if value.get("codec") in {"JPEG", "H264"}:
            result["codec"] = value["codec"]
        for field in (
            "fpsLimitPerSource",
            "jpegQuality",
            "maxJpegBytes",
            "identityLimitPerSource",
            "pendingJpegs",
            "pendingMetadata",
            "metadataQueueLimitPerSource",
            "batchQueueOverruns",
        ):
            number = value.get(field)
            if type(number) in {int, float} and 0 <= number <= 9223372036854775807:
                result[field] = number
        pipeline = value.get('pipeline')
        if isinstance(pipeline, dict):
            public_pipeline = {}
            for key, low, high in (('detectorCadence', 1, 3), ('muxTimeoutUs', 1000, 1000000),
                                   ('batches', 0, 2**63-1), ('fullBatches', 0, 2**63-1),
                                   ('inferredFrames', 0, 2**63-1), ('trackedFrames', 0, 2**63-1)):
                number = pipeline.get(key)
                if type(number) is int and low <= number <= high:
                    public_pipeline[key] = number
            for key in ('preprocessInferPathMs', 'trackerAnalyticsPathMs'):
                timing = pipeline.get(key)
                if isinstance(timing, dict) and all(type(timing.get(field)) in {int, float}
                        and math.isfinite(timing[field]) and 0 <= timing[field] <= 1e9
                        for field in ('mean', 'p95Upper')):
                    public_pipeline[key] = {field: timing[field] for field in ('mean', 'p95Upper')}
            result['pipeline'] = public_pipeline
        sources = value.get("sources", [])
        if not isinstance(sources, list) or len(sources) > MAX_PREVIEW_SOURCES:
            raise ValueError("invalid native sources")
        counters = (
            "width",
            "height",
            "selected",
            "rateDropped",
            "sourceQueueOverruns",
            "identityMissing",
            "identityEvicted",
            "identitiesPending",
            "geometryMismatch",
            "encoded",
            "oversizeDropped",
            "networkQueueDropped",
            "published",
            "postFailed",
            "pendingDropped",
            "metadataReadyBeforeVideo",
            "metadataUnconfirmedBeforeVideo",
            "observedEncodedFps",
            "observedPublishedFps",
        )
        for source in sources:
            if not isinstance(source, dict) or source.get("sourceId") not in registered_sources:
                continue
            public = {"sourceId": source["sourceId"]}
            if source.get('decoder') in ('cpu', 'hardware', 'unknown'):
                public['decoder'] = source['decoder']
            if type(source.get('decoderExtraSurfaces')) is int and 0 <= source['decoderExtraSurfaces'] <= 8:
                public['decoderExtraSurfaces'] = source['decoderExtraSurfaces']
            if type(source.get('decoderLowLatency')) is bool:
                public['decoderLowLatency'] = source['decoderLowLatency']
            for field in counters:
                number = source.get(field)
                if type(number) in {int, float} and 0 <= number <= 9223372036854775807:
                    public[field] = number
            timing = source.get("timingMs")
            if isinstance(timing, dict):
                phases = {}
                for phase in ("selectedToJpeg", "selectedToEncode", "postQueue", "post", "metadataAdmissionWait"):
                    sample = timing.get(phase)
                    if not isinstance(sample, dict):
                        continue
                    count = sample.get("count")
                    fields = ("mean", "last", "max", "p50Upper", "p95Upper")
                    if (type(count) is int and 0 <= count <= 9223372036854775807
                            and all(type(sample.get(key)) in {int, float} and math.isfinite(sample[key])
                                    and 0 <= sample[key] <= 1e9 for key in fields)):
                        phases[phase] = {"count": count, **{key: sample[key] for key in fields}}
                if phases:
                    public["timingMs"] = phases
            published_at = source.get("lastPublishedAtNs")
            if (
                isinstance(published_at, str)
                and re.fullmatch(r"[0-9]{1,19}", published_at)
                and int(published_at) <= 9223372036854775807
            ):
                public["lastPublishedAtNs"] = published_at
            result["sources"].append(public)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        result = {"status": "invalid", "enabled": False, "failed": False, "sources": []}
    return result


class PreviewError(ValueError):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass(frozen=True)
class FrameIdentity:
    source: str
    session: str
    sequence: str
    ns: str
    width: int
    height: int
    model: str | None

    @classmethod
    def headers(cls, headers):
        def integer(name, maximum):
            value = headers.get(name, "")
            if not re.fullmatch(r"\d{1,30}", value) or int(value) > maximum:
                raise PreviewError(422, f"invalid-{name}")
            return value

        source, session = headers.get("x-city-source-id", ""), headers.get("x-city-session-id", "")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", source) or not 1 <= len(session) <= 200:
            raise PreviewError(422, "invalid-source-or-session")
        width, height = int(integer("x-city-width", 16384)), int(integer("x-city-height", 16384))
        if min(width, height) < 1:
            raise PreviewError(422, "invalid-image-dimensions")
        model = headers.get("x-city-model-revision")
        if model is not None and not 1 <= len(model) <= 512:
            raise PreviewError(422, "invalid-model-revision")
        return cls(
            source,
            session,
            integer("x-city-sequence", 10**30 - 1),
            integer("x-city-source-time-ns", 9223372036854775807),
            width,
            height,
            model,
        )


def jpeg_dimensions(data: bytes):
    """Read bounded JPEG SOF geometry without an image/GPU dependency."""
    if not 4 <= len(data) <= MAX_JPEG_BYTES:
        raise PreviewError(413 if len(data) > MAX_JPEG_BYTES else 422, "invalid-jpeg-size")
    if data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        raise PreviewError(422, "invalid-jpeg-markers")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            raise PreviewError(422, "invalid-jpeg-marker")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0xDA}:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            raise PreviewError(422, "invalid-jpeg-segment")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                raise PreviewError(422, "invalid-jpeg-sof")
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            if min(width, height) < 1 or max(width, height) > 16384:
                raise PreviewError(422, "invalid-jpeg-dimensions")
            return width, height
        offset += length
    raise PreviewError(422, "jpeg-dimensions-unavailable")


def public_value(value):
    """Defense in depth: worker URLs and secrets never enter the envelope."""
    if isinstance(value, list):
        return [public_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: public_value(item)
            for key, item in value.items()
            if key.lower() not in {"inputuri", "filename", "input_uri", "rtspurl", "rtspuri", "password", "credentials"}
        }
    return value


def display_trail(points):
    """Keep the captured trail's time span and endpoints at bounded display cost."""
    if len(points) <= MAX_PREVIEW_TRAIL_POINTS:
        return points
    return [points[index * (len(points) - 1) // (MAX_PREVIEW_TRAIL_POINTS - 1)]
            for index in range(MAX_PREVIEW_TRAIL_POINTS)]


def display_events(events):
    """Retain every captured active event and the newest other outcomes.

    History rows are already newest-first. This does not edit those rows or
    substitute current event state for the state at the analyzed frame.
    """
    other = 0
    result = []
    for event in events:
        if event.get("state") == "active":
            result.append(event)
        elif other < MAX_PREVIEW_OTHER_EVENTS:
            result.append(event)
            other += 1
    return result


class PreviewStore:
    """At most two latest images; no JPEG, envelope or frame is written to disk."""

    def __init__(self, engine: CityEngine):
        self.engine = engine
        self.lock = RLock()
        self.frames: dict[str, dict] = {}
        self.accepted = 0

    def _purge(self):
        now = self.engine.clock()
        for source_id, frame in list(self.frames.items()):
            source = self.engine.sources.get(source_id)
            if (
                source_id not in self.engine._site_sources()
                or frame["generation"] != self.engine.frame_generation
                or source is None
                or frame["sessionId"] != source["sessionId"]
            ):
                del self.frames[source_id]
            elif now - frame["receivedAt"] > PREVIEW_TTL_SECONDS:
                # Preserve only a tiny stale marker, never the expired payload.
                frame.pop("body", None)

    def _sample(self, identity: FrameIdentity):
        config = self.engine._site_sources().get(identity.source)
        if config is None:
            raise PreviewError(404, "source-not-configured")
        if self.engine.site.mode not in {"live", "recorded-inference"}:
            raise PreviewError(409, "preview-requires-real-inference-mode")
        if (identity.width, identity.height) != (config.width, config.height):
            raise PreviewError(409, "observation-dimensions-mismatch")
        source = self.engine.sources.get(identity.source)
        if source is None:
            return None
        if identity.session != source["declaredSession"]:
            if identity.session in source.get("retiredSessions", ()):
                raise PreviewError(409, "source-session-retired")
            return None  # metadata for a new producer session may be in flight
        sample = next(
            (
                sample
                for sample in reversed(self.engine.histories.get(identity.source, ()))
                if sample.get("sequence") == identity.sequence
                and sample["sourceTimeNs"] == identity.ns
                and sample["source"].get("sourceSessionId") == identity.session
            ),
            None,
        )
        if sample is None:
            if int(identity.sequence) <= source["lastSequence"]:
                raise PreviewError(409, "exact-frame-unavailable")
            return None
        if sample.get("context", {}).get("generation") != self.engine.frame_generation:
            raise PreviewError(409, "frame-generation-superseded")
        if sample["source"]["modelRevision"] != identity.model:
            raise PreviewError(409, "model-revision-mismatch")
        if self.engine.clock() - sample["receivedAt"] > PREVIEW_TTL_SECONDS:
            raise PreviewError(409, "observation-frame-stale")
        return sample

    def _snapshot(self, sample):
        # _save_history() creates independent tracks/metrics/events/source and
        # shares only an immutable generation context. The captured row stays
        # read-only when it leaves the bounded deque; no live track is borrowed.
        # Publication rechecks that the exact row/session/generation is current.
        context = sample["context"]
        metrics = sample["metrics"]
        index = {metric["ruleId"]: metric for metric in metrics}
        source = {key: value for key, value in sample["source"].items() if key in PUBLIC_FRAME_SOURCE_FIELDS}
        media_url = sample["source"].get("mediaUrl")
        if isinstance(media_url, str) and media_url == f"/api/vision/city/media/{source['id']}":
            source["mediaUrl"] = media_url
        source["processedPreview"] = {"available": True, "status": "ready"}
        # The immutable frame carries its own source-specific rule geometry.
        return {
            "analyticsScope": sample.get("analyticsScope"),
            "siteId": context["siteId"],
            "siteRevision": context["siteRevision"],
            "mode": context["mode"],
            "timestamp": sample["timestamp"],
            "sequence": sample["engineSequence"],
            "rulesRevision": context["rulesRevision"],
            "sources": [source],
            "tracks": [{**track, "trail": display_trail(track.get("trail", []))}
                       for track in sample["tracks"]],
            "rules": context["rules"],
            "zones": [
                {
                    "id": rule["id"],
                    "name": rule["name"],
                    "sourceId": rule["sourceId"],
                    "kind": rule["kind"],
                    "geometry": rule["geometry"],
                    "enabled": rule["enabled"],
                    "active": index.get(rule["id"], {}).get("status") == "active",
                    "occupancy": index.get(rule["id"], {}).get("occupancy"),
                }
                for rule in context["rules"]
                if rule["kind"] != "line-crossing"
            ],
            "metrics": metrics,
            "events": display_events(sample["events"]),
            "setupRequired": False,
            "awaitingObservations": False,
            "clockAligned": None,
            "sourceTimeNs": sample["sourceTimeNs"],
            "mediaTimeSeconds": sample["mediaTimeSeconds"],
            "association": sample.get("association", {"mode": "camera-local", "globalFusionEnabled": False}),
        }

    def _order(self, identity, digest):
        """Check publication order/capacity while both locks are held."""
        old = self.frames.get(identity.source)
        if old:
            if int(identity.sequence) < int(old["sequence"]):
                raise PreviewError(409, "preview-sequence-superseded")
            if identity.sequence == old["sequence"]:
                if identity.ns != old["sourceTimeNs"] or digest != old["digest"]:
                    raise PreviewError(409, "conflicting-preview-frame")
                return {"accepted": True, "duplicate": True, "etag": old["etag"]}
        elif len(self.frames) >= MAX_PREVIEW_SOURCES:
            raise PreviewError(409, "preview-source-capacity")
        return None

    @staticmethod
    def _encode(dto):
        encoded = json.dumps(public_value(dto), allow_nan=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_JSON_BYTES:
            raise PreviewError(413, "paired-metadata-too-large")
        return encoded

    def accept(self, identity: FrameIdentity, jpeg: bytes, dimensions: tuple[int, int]):
        # Pixel hashing, public filtering, JSON serialization and body assembly
        # do not need the analytics lock. The immutable history row is captured
        # briefly, then all identities are checked again before publication.
        width, height = dimensions
        with self.engine.lock, self.lock:
            self._purge()
            sample = self._sample(identity)
            if sample is None:
                return None
            if (width > identity.width or height > identity.height
                    or abs(width * identity.height - height * identity.width) > max(identity.width, identity.height)):
                raise PreviewError(409, "jpeg-aspect-or-dimensions-mismatch")
            generation = self.engine.frame_generation
            session = sample["source"]["sessionId"]
        # Pending metadata is polled by the HTTP endpoint. Do not hash the same
        # JPEG on every poll before its history row has arrived.
        digest = hashlib.sha256(jpeg).hexdigest()
        with self.engine.lock, self.lock:
            self._purge()
            if self.engine.frame_generation != generation or self._sample(identity) is not sample:
                raise PreviewError(409, "exact-frame-superseded-during-hashing")
            duplicate = self._order(identity, digest)
            if duplicate is not None:
                return duplicate
        source = sample["source"]
        snapshot = self._snapshot(sample)
        dto = {
            "schemaVersion": "city.preview.v1",
            "sourceId": identity.source,
            "sourceSessionId": identity.session,
            "sessionId": source["sessionId"],
            "sequence": identity.sequence,
            "sourceTimeNs": identity.ns,
            "timestampBasis": source["timestampBasis"],
            "sourceClockEvidence": source.get("sourceClockEvidence"),
            "modelRevision": source["modelRevision"],
            "image": {
                "width": identity.width,
                "height": identity.height,
                "jpegWidth": width,
                "jpegHeight": height,
                "mimeType": "image/jpeg",
            },
            "provenance": {
                "kind": "native-post-inference-exact-frame",
                "correlation": "source-session-sequence-time",
                "clockAlignment": "source-frame-exact",
                "browserClockVerified": False,
            },
            "displayScope": {
                "events": "all-captured-active-plus-recent-other",
                "maximumOtherEvents": MAX_PREVIEW_OTHER_EVENTS,
                "omittedOtherEvents": len(sample["events"]) - len(snapshot["events"]),
                "maximumTrailPoints": MAX_PREVIEW_TRAIL_POINTS,
                "trailSampling": "captured-span-endpoints-preserved",
                "fullHistory": "separate-events-and-history-api",
            },
            "snapshot": snapshot,
        }
        encoded = self._encode(dto)
        etag = (
            '"'
            + hashlib.sha256(
                f"{generation}|{session}|{identity.sequence}|{identity.ns}".encode()
            ).hexdigest()
            + '"'
        )
        body = struct.pack(">I", len(encoded)) + encoded + jpeg
        with self.engine.lock, self.lock:
            self._purge()
            if self.engine.frame_generation != generation:
                raise PreviewError(409, "frame-generation-superseded")
            current = self._sample(identity)
            if current is not sample or current["source"]["sessionId"] != session:
                raise PreviewError(409, "exact-frame-superseded-during-encoding")
            duplicate = self._order(identity, digest)
            if duplicate is not None:
                return duplicate
            self.frames[identity.source] = {
                "body": body,
                "etag": etag,
                "receivedAt": self.engine.clock(),
                "generation": self.engine.frame_generation,
                "sessionId": source["sessionId"],
                "sequence": identity.sequence,
                "sourceTimeNs": identity.ns,
                "digest": digest,
            }
            self.accepted += 1
            return {"accepted": True, "duplicate": False, "etag": etag}

    def get(self, source_id):
        with self.engine.lock, self.lock:
            self._purge()
            if source_id not in self.engine._site_sources():
                raise PreviewError(404, "source-not-configured")
            frame = self.frames.get(source_id)
            return (
                (frame.get("body"), frame["etag"], "ready" if frame.get("body") else "stale")
                if frame
                else (None, None, "waiting")
            )

    def capability(self, source_id):
        try:
            body, _, status = self.get(source_id)
            return {"available": body is not None, "status": status}
        except PreviewError:
            return {"available": False, "status": "waiting"}

    def decorate(self, payload):
        for source in payload.get("sources", []):
            source["processedPreview"] = self.capability(source["id"])
        return payload

    def health(self):
        with self.engine.lock, self.lock:
            self._purge()
            return {
                "enabled": True,
                "acceptedFrames": self.accepted,
                "maximumSources": MAX_PREVIEW_SOURCES,
                "maximumJpegBytes": MAX_JPEG_BYTES,
                "maximumJsonBytes": MAX_JSON_BYTES,
                "ttlSeconds": PREVIEW_TTL_SECONDS,
                "retainedBytes": sum(len(frame.get("body", b"")) for frame in self.frames.values()),
                "sources": [
                    {"id": source_id, **self.capability(source_id)} for source_id in self.engine._site_sources()
                ],
            }
