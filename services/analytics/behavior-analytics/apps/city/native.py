# SPDX-License-Identifier: Apache-2.0
"""Compile image primitives to the native worker's controlled watch directory.

Backend rules remain authoritative. Native ROI counts are intentionally
unfiltered, since nvdsanalytics class-id applies to a section rather than ROI.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

from .models import Rule, Site


def compile_analytics(site: Site, rules: list[Rule], revision: int) -> tuple[str, list[dict]]:
    lines = [f"# city-rules-revision={revision}", "[property]", "enable=1", "config-width=10000", "config-height=10000", "osd-mode=0", "display-font-size=12", ""]
    capabilities = []
    by_source = {}
    for index, source in enumerate(site.sources):
        stream = source.deepstreamStreamIndex if source.deepstreamStreamIndex is not None else index
        if not isinstance(stream, int) or stream < 0 or stream > 1024:
            raise ValueError("deepstreamStreamIndex must be a bounded integer")
        by_source[source.id] = stream
    for source in site.sources:
        stream_rules = [rule for rule in rules if rule.enabled and rule.sourceId == source.id]
        rois, crossings, directions = [], [], []
        for rule in stream_rules:
            if rule.geometry.space != "image-normalized":
                capabilities.append({"ruleId": rule.id, "primitiveStatus": "backend-only", "reason": "world geometry requires independent inverse-projection validation"})
                continue
            # Opaque stable IDs keep rule names from injecting INI syntax.
            import hashlib
            label = "city_" + hashlib.sha256(rule.id.encode()).hexdigest()[:16]
            points = [[round(v * 10000) for v in point] for point in rule.geometry.points]
            coordinates = ";".join(str(v) for point in points for v in point)
            if rule.kind == "line-crossing":
                direction = rule.geometry.direction
                magnitude = max(abs(v) for v in direction)
                center = [sum(point[i] for point in points) / 2 for i in range(2)]
                start = [round(center[i] - direction[i] / magnitude * 500) for i in range(2)]
                end = [round(center[i] + direction[i] / magnitude * 500) for i in range(2)]
                vector = ";".join(str(v) for point in [start, end] + points for v in point)
                crossings.append(f"line-crossing-{label}={vector}")
            else:
                rois.append(f"roi-{label}={coordinates}")
            if rule.kind == "wrong-way":
                direction = rule.geometry.direction
                magnitude = max(abs(v) for v in direction)
                center = [sum(point[i] for point in points) / len(points) for i in range(2)]
                start = [round(center[i] - direction[i] / magnitude * 500) for i in range(2)]
                end = [round(center[i] + direction[i] / magnitude * 500) for i in range(2)]
                directions.append(f"direction-{label}=" + ";".join(str(v) for point in [start, end] for v in point))
            capabilities.append({"ruleId": rule.id, "primitiveStatus": "compiled", "nativeLabel": label, "nativeClassFilter": "all", "eventAuthority": "city-behavior-analytics"})
        for kind, values in (("roi-filtering", rois), ("line-crossing", crossings), ("direction-detection", directions)):
            if values:
                lines.extend([f"[{kind}-stream-{by_source[source.id]}]", "enable=1", "class-id=-1"])
                if kind == "roi-filtering":
                    lines.append("inverse-roi=0")
                if kind == "line-crossing":
                    lines.extend(["extended=0", "mode=balanced"])
                lines.extend(values + [""])
    return "\n".join(lines) + "\n", capabilities


class NativeAnalyticsBridge:
    def __init__(self, directory: str | None):
        self.directory = Path(directory).resolve() if directory else None
        self.revision = 0
        self.capabilities = []

    def apply(self, site: Site, rules: list[Rule], revision: int):
        contents, self.capabilities = compile_analytics(site, rules, revision)
        self.revision = revision
        if self.directory is None:
            return self.status()
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".analytics-", suffix=".ini", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "analytics.ini")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.status()

    def status(self):
        result = {"status": "not-connected" if self.directory is None else "pending", "requestedRevision": self.revision, "appliedRevision": None, "primitives": self.capabilities, "eventAuthority": "city-behavior-analytics"}
        if self.directory is None:
            return result
        try:
            ack = json.loads((self.directory / "analytics-ack.json").read_text())
            revision = ack.get("revision")
            if isinstance(revision, str) and revision.isdigit():
                revision = int(revision)
            result["appliedRevision"] = revision
            if revision == self.revision:
                result.update(status=ack.get("status", "pending"), counterEpoch=ack.get("counterEpoch"), sourceTimeNs=ack.get("sourceTimeNs"), error=ack.get("error"))
                if ack.get("sourceClockMode") in {"source-rtcp", "source-native-sei"}:
                    result["sourceClockMode"] = ack["sourceClockMode"]
        except (OSError, ValueError, TypeError):
            pass
        return result
