# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .geometry import validate_homography, validate_polygon


class Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, allow_inf_nan=False)


class Source(Model):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(default="Camera", max_length=200)
    width: int = Field(default=1920, ge=1, le=16384)
    height: int = Field(default=1080, ge=1, le=16384)
    mediaUrl: str | None = None
    vssSensorId: str | None = None
    imageToGroundHomography: list[list[float]] | None = None
    classImageToGroundHomographies: dict[str, list[list[float]]] = Field(default_factory=dict)
    validGroundPolygon: list[list[float]] | None = None
    calibrationRevision: str | None = None
    deepstreamStreamIndex: int | None = Field(default=None, ge=0, le=1024)

    @field_validator("imageToGroundHomography")
    @classmethod
    def homography(cls, value):
        if value is not None:
            validate_homography(value)
        return value

    @field_validator('classImageToGroundHomographies')
    @classmethod
    def class_homographies(cls, value):
        if not set(value) <= {'person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler'}:
            raise ValueError('Class-specific calibration needs canonical road-user classes')
        for matrix in value.values():
            validate_homography(matrix)
        return value

    @field_validator("validGroundPolygon")
    @classmethod
    def valid_polygon(cls, value):
        if value is not None:
            validate_polygon(value)
        return value


class Map(Model):
    bounds: list[float] = Field(default_factory=lambda: [-50, -50, 50, 50], min_length=4, max_length=4)
    roads: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    buildings: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)

    @field_validator("bounds")
    @classmethod
    def valid_bounds(cls, value):
        if not all(math.isfinite(x) for x in value) or value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("map bounds must have positive finite extent")
        return value


class Site(Model):
    id: str = Field(default="smart-city", min_length=1, max_length=200)
    name: str = Field(default="Smart City", max_length=200)
    revision: int = Field(default=1, ge=1)
    mode: Literal["live", "recorded-inference", "fixture-replay"] = "live"
    sources: list[Source] = Field(default_factory=list, max_length=16)
    map: Map = Field(default_factory=Map)

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, sources):
        if len({source.id for source in sources}) != len(sources):
            raise ValueError("source IDs must be unique")
        return sources


class Geometry(Model):
    space: Literal["image-normalized", "site-metres"] = "image-normalized"
    points: list[list[float]] = Field(min_length=2, max_length=128)
    direction: list[float] | None = Field(default=None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def valid_geometry(self):
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in self.points):
            raise ValueError("geometry points must be finite pairs")
        if self.space == "image-normalized" and any(v < 0 or v > 1 for p in self.points for v in p):
            raise ValueError("normalized points must be within [0,1]")
        if len(self.points) >= 3:
            validate_polygon(self.points)
        elif math.dist(*self.points) < 1e-9:
            raise ValueError("line endpoints must differ")
        if self.direction is not None and (not all(math.isfinite(v) for v in self.direction) or math.hypot(*self.direction) < 1e-9):
            raise ValueError("direction must have nonzero finite length")
        return self


class Conditions(Model):
    minimumDurationMs: int = Field(default=0, ge=0, le=3600000)
    clearAfterMs: int = Field(default=500, ge=0, le=60000)
    maximumObservationGapMs: int = Field(default=1000, ge=50, le=60000)
    speedBelowMps: float = Field(default=0.5, ge=0, le=100)
    speedAboveMps: float = Field(default=0.2, ge=0, le=100)
    countThreshold: int = Field(default=1, ge=1, le=10000)
    wrongWayCosine: float = Field(default=-0.5, ge=-1, le=0)
    lineHysteresis: float | None = Field(default=None, ge=0, le=10)


class MobilityMovement(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    entryRuleId: str = Field(min_length=1, max_length=200)
    exitRuleId: str = Field(min_length=1, max_length=200)
    classes: list[Literal["person", "bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"]] = Field(default_factory=list, max_length=7)


class MobilityCrossing(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    waitingRuleId: str = Field(min_length=1, max_length=200)
    crossingRuleId: str = Field(min_length=1, max_length=200)


class MobilityQueue(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    zoneRuleId: str = Field(min_length=1, max_length=200)
    stopLine: list[list[float]] = Field(min_length=2, max_length=2)
    upstreamPoint: list[float] = Field(min_length=2, max_length=2)
    spillbackDistanceM: float = Field(gt=0, le=10000)
    maxAnchorGapM: float = Field(default=12, gt=0, le=1000)
    stopLineReachM: float = Field(default=12, gt=0, le=1000)
    minimumDurationMs: int = Field(default=1000, ge=0, le=3600000)
    maximumObservationGapMs: int = Field(default=1000, ge=50, le=60000)

    @model_validator(mode="after")
    def metric_axis(self):
        from .geometry import cross, finite_point
        if any(not finite_point(point) for point in [*self.stopLine, self.upstreamPoint]) or math.dist(*self.stopLine) < 1e-6 or abs(cross(*self.stopLine, self.upstreamPoint)) < 1e-6:
            raise ValueError("queue needs a finite metre stop line and an upstream point off that line")
        return self


class MobilityCurb(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    zoneRuleId: str = Field(min_length=1, max_length=200)
    role: Literal["general", "loading", "bus-stop", "cycle-lane"] = "general"
    dwellThresholdMs: int = Field(default=30000, ge=0, le=3600000)
    maximumObservationGapMs: int = Field(default=1000, ge=50, le=60000)


class MobilityConfig(Model):
    revision: int = Field(default=0, ge=0)
    expectedRevision: int | None = Field(default=None, ge=0, exclude=True)
    movements: list[MobilityMovement] = Field(default_factory=list, max_length=32)
    crossings: list[MobilityCrossing] = Field(default_factory=list, max_length=32)
    queues: list[MobilityQueue] = Field(default_factory=list, max_length=32)
    curbs: list[MobilityCurb] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_measurements(self):
        ids = [item.id for items in (self.movements, self.crossings, self.queues, self.curbs) for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("mobility measurement IDs must be unique")
        return self


class Rule(Model):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(default="Monitoring zone", max_length=200)
    kind: Literal["area-entry", "line-crossing", "occupancy-threshold", "dwell", "stopped-in-zone", "queue", "wrong-way"]
    sourceId: str = Field(min_length=1, max_length=200)
    classes: list[str] = Field(default_factory=list, max_length=100)
    geometry: Geometry
    conditions: Conditions = Field(default_factory=Conditions)
    enabled: bool = True
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def valid_rule(self):
        if self.kind == "line-crossing":
            if len(self.geometry.points) != 2 or self.geometry.direction is None:
                raise ValueError("line-crossing requires two endpoints and a direction")
        elif len(self.geometry.points) < 3:
            raise ValueError("this rule requires a polygon")
        if self.kind == "wrong-way" and self.geometry.direction is None:
            raise ValueError("wrong-way requires an allowed direction")
        return self


class RuleSet(Model):
    rules: list[Rule] = Field(default_factory=list, max_length=256)
    expectedRevision: int | None = Field(default=None, ge=0)

    @field_validator("rules")
    @classmethod
    def unique_rules(cls, rules):
        if len({rule.id for rule in rules}) != len(rules):
            raise ValueError("rule IDs must be unique")
        return rules


class Image(Model):
    width: int = Field(ge=1, le=16384)
    height: int = Field(ge=1, le=16384)


class Native3DEvidence(Model):
    method: str = Field(min_length=1, max_length=100)
    targetId: str = Field(min_length=1, max_length=200)
    localTargetId: str | None = Field(default=None, min_length=1, max_length=200)
    localTrackingMethod: Literal["nvidia-nvdcf-first-stage-9.2"] | None = None
    calibrationRevision: str = Field(min_length=1, max_length=200)
    worldPositionM: list[float] = Field(min_length=2, max_length=2)
    imageFootPx: list[float] = Field(min_length=2, max_length=2)
    visibility: float | None = Field(default=None, ge=0, le=1)
    state: str = Field(min_length=1, max_length=100)


class MapAssociation(Model):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    method: Literal["mv3dt-demo"]
    globalTrackId: str = Field(min_length=1, max_length=500)
    targetId: str = Field(min_length=1, max_length=200)
    fusionEpoch: str = Field(min_length=1, max_length=200)
    calibrationRevision: str = Field(min_length=1, max_length=200)
    visibility: float = Field(ge=.25, le=1)
    sourceClockBasis: Literal["source-rtcp", "source-native-sei"]
    positionM: list[float] | None = Field(default=None, min_length=2, max_length=2)
    positionBasis: Literal["native-mv3dt-world-foot"] | None = None
    classPolicy: Literal["car-truck-family-v1"] | None = None


class NativeSeiClockEvidence(Model):
    """Validated encoded-AU handoff clock; never a physical-exposure claim."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schemaVersion: Literal["city.source-native-sei.v1"]
    method: Literal["isaac-native-sei-wall-capture"]
    correlation: Literal["exact-au-pts"]
    captureTimeNs: str
    auPtsNs: str
    frameCounter: str

    @field_validator("captureTimeNs", "auPtsNs", "frameCounter", mode="before")
    @classmethod
    def native_unsigned(cls, value, info):
        limit = 18446744073709551615 if info.field_name == "frameCounter" else 9223372036854775807
        if (not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 20 or int(value) > limit
                or (info.field_name == "captureTimeNs" and int(value) == 0)):
            raise ValueError("native SEI clock fields must be bounded unsigned integer strings")
        return value


class ObjectObservation(Model):
    localTrackId: str = Field(min_length=1, max_length=200)
    class_name: str = Field(alias="class", min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    bboxPx: list[float] = Field(min_length=4, max_length=4)
    observedThisFrame: bool = True
    globalTrackId: str | None = None
    associationMethod: str | None = None
    native3D: Native3DEvidence | None = None
    positionUncertaintyM: float | None = Field(default=None, ge=0)

    @field_validator("bboxPx")
    @classmethod
    def valid_box(cls, value):
        if not all(math.isfinite(v) for v in value) or value[2] <= 0 or value[3] <= 0:
            raise ValueError("bbox must have finite coordinates and positive width/height")
        return value


class Observation(Model):
    schemaVersion: str = "city.observations.v1"
    trackingArchitecture: Literal["nvdcf-local-then-mv3dt-v1", "mv3dt-native-v1"] | None = None
    trackingClassPolicy: Literal["car-truck-family-v1"] | None = None
    siteId: str = Field(min_length=1)
    sourceId: str = Field(min_length=1)
    sourceSessionId: str = Field(min_length=1, max_length=200)
    sequence: str = Field(max_length=30)
    sourceFrameId: str | None = None
    sourceTimeNs: str = Field(max_length=30)
    timestampBasis: str = Field(default="declared-source-time", min_length=1, max_length=100)
    sourceClockEvidence: NativeSeiClockEvidence | None = None
    mediaTimeSeconds: float | None = Field(default=None, ge=0)
    mediaTimeBasis: str | None = None
    rawSourcePtsNs: str | None = None
    image: Image
    objects: list[ObjectObservation] = Field(default_factory=list, max_length=5000)
    reset: bool = False
    modelRevision: str | None = None
    calibrationRevision: str | None = None
    trackingMode: str | None = Field(default=None, max_length=100)
    fusionEpoch: str | None = Field(default=None, min_length=1, max_length=200)
    trackingEpoch: str | None = Field(default=None, min_length=1, max_length=100)
    rulesRevision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def native_clock_matches_frame(self):
        if self.trackingClassPolicy is not None and self.trackingArchitecture != 'mv3dt-native-v1':
            raise ValueError('Association class policy requires one native MV3DT stage')
        if self.timestampBasis == "recorded-native-sei":
            raise ValueError("Offline native capture replay must not enter operational analytics")
        if self.timestampBasis == "source-native-sei":
            if (self.sourceClockEvidence is None
                    or self.sourceClockEvidence.captureTimeNs != self.sourceTimeNs
                    or self.sourceClockEvidence.auPtsNs != self.rawSourcePtsNs):
                raise ValueError("source-native-sei requires exact capture-time and AU-PTS evidence")
        elif self.sourceClockEvidence is not None:
            raise ValueError("native SEI evidence must retain source-native-sei provenance")
        return self

    @field_validator("sequence", "sourceTimeNs", mode="before")
    @classmethod
    def unsigned_integer(cls, value):
        value = str(value)
        if not value.isdigit() or len(value) > 30:
            raise ValueError("clock and sequence fields must be unsigned integer strings")
        return value

    @field_validator("sourceTimeNs")
    @classmethod
    def clock_in_range(cls, value):
        if int(value) > 9223372036854775807:
            raise ValueError("sourceTimeNs exceeds supported Unix nanosecond range")
        return value

    @field_validator("objects")
    @classmethod
    def unique_tracks(cls, objects):
        if len({obj.localTrackId for obj in objects}) != len(objects):
            raise ValueError("localTrackId must be unique within a frame")
        return objects
