# Smart City data contracts

Design proposal, October 21, 2026. These are implementation contracts, not endpoints or schemas already deployed. See the [research decisions](smart-city-integration-research.md).

## October 26 implementation addendum: native encoded-AU clock

The pinned Spark/Isaac profile can explicitly select `sourceClockMode: source-native-sei`. Ordinary cameras retain `source-rtcp`; absence of the profile option never enables native SEI. A validated single member of the pinned camera pair uses this clock with ordinary NvDCF during source admission. Shared map IDs still require the complete pair and the existing staged-tracker, calibration, session, position and visibility guards.

In this mode, `sourceTimeNs` is the producer's Unix wall timestamp at **encoded-frame handoff**, correlated to the exact H.264 access unit by raw PTS before either tracker. It is not physical exposure time, browser presentation time, simulation time, an RTCP reconstruction or an offset-corrected value. `rawSourcePtsNs` retains the access-unit PTS. Each observation, source snapshot and exact-preview envelope carries:

```json
"timestampBasis": "source-native-sei",
"sourceClockEvidence": {
  "schemaVersion": "city.source-native-sei.v1",
  "method": "isaac-native-sei-wall-capture",
  "correlation": "exact-au-pts",
  "captureTimeNs": "1793000000000000000",
  "auPtsNs": "123400000",
  "frameCounter": "42"
}
```

These six evidence fields are exact: unknown fields, missing evidence, mismatched capture time/PTS and numeric JSON timestamps are rejected. Capture time and AU PTS are bounded signed-64-bit nonnegative integer strings (capture time must be positive); frame counter is an unsigned-64-bit integer string. In one source session, all three advance strictly. A source reset flag cannot bypass these checks. A new worker/session can reset counters; existing shared-epoch retirement still applies.

The backend admits this basis only for the explicit live Isaac site and pinned source/calibration subset. An admitted native profile rejects RTCP fallback. Exact-preview history retains the selected frame's proof, rather than newer source evidence. The UI requires matching model/proof/basis and never joins RTCP and native SEI observations. Native shared markers retain the existing **150 ms** demo window, 1 m entry / 1.5 m split thresholds and all other guards; they remain experimental and unqualified for cross-camera accuracy. `browserClockVerified` remains false, and ordinary browser video overlay paths remain gated by their separate clock requirements.

The implementation and offline controls do not establish live clock alignment or tracker accuracy; final runtime qualification is separate. The legacy `prepare_mv3dt.py` recording/preflight evidence schema remains explicitly RTCP/recorded-clock-only and cannot qualify this new basis by relabelling it.

## 1. Identity and coordinate conventions

| Field | Meaning |
| --- | --- |
| `siteId` | Stable ID for this intersection; separate from an industry profile. |
| `sourceId` | Existing VSS source UUID. Never use a changeable camera label as identity. |
| `sourceSessionId` | New epoch after reconnect, replay restart or backward source time. |
| `localTrackId` | String: detector/tracker ID within source and session. Never coerce uint64 IDs into JavaScript numbers. |
| `globalTrackId` | Nullable; assigned only by the validated association layer. |
| `calibrationRevision` | Immutable version of camera geometry and map transforms. |
| `rulesRevision` | Applied immutable rule-set revision, not merely the requested revision. |
| `modelRevision` | Model family, checkpoint hash, parser/preprocessor and engine build identity. |

Canonical site coordinates are local Cartesian metres: right-handed X/Y ground plane, Z up. Select and document a fixed origin and yaw when the map is exported. The scene's original stage units/axes must be transformed into this convention. Do not invent latitude/longitude to satisfy an older geographic API.

Image coordinates refer to the **original decoded image**, with X right, Y down and origin at top left. Boxes use `[x, y, width, height]` in pixels. Rule editor points are normalized to this same image, not the browser panel. Record width/height, orientation, rectification and crop; convert explicitly if analysis geometry differs.

## 2. Static site package from Isaac Sim

Deliver once per scene/camera revision. No simulator actor positions are needed at runtime.

| Artifact/field | Required content |
| --- | --- |
| `site.json` | Schema version, site ID, asset revision, metre units, axis/origin definition and bounds. |
| `map.svg` or `map.png` | Street surface, curbs/crossings/stop areas, no moving actors. |
| `mapTransform` | Explicit world-metres to map-pixels matrix, image dimensions, bounds and Y-axis convention. A vector plan may stay directly in metres. |
| `cameras[]` | Source UUID, image dimensions, calibration revision and lens model. |
| `K` | 3 × 3 intrinsic matrix for the delivered image geometry. |
| `T_cv_from_site` | 4 × 4 world-to-camera transform: camera X right, Y down, Z forward. State the convention; do not infer it from an unlabeled matrix. |
| `distortion` | Explicit zero distortion or named model and coefficients, plus whether video is already rectified. |
| `imageTransform` | Resize, crop, pad and rotation between rendered camera image and published RTSP. Identity if unchanged. |
| `groundSurface` | Plane in site coordinates, piecewise planes, or a static road mesh/proxy with units. |
| `imageToGroundHomography` | Optional derived 3 × 3 transform for an already-undistorted image and named plane. Direction must be explicit. |
| `validGroundPolygon` | Region in which projection is valid; mask sky, facades and problematic near-horizon pixels. |
| `landmarks[]` | Image points and known site points for independent reprojection/error checks. |
| `coverage[]` | Camera footprint and optional primary ownership zones. |
| `lanes/zones` | Optional static vector semantics with stable IDs, not animated actor data. |

Validate more than matrix invertibility: units, pose orientation, distortion, held-out landmarks across the complete used region, and signs of X/Y. Use at least four non-collinear correspondences if fitting homography and preferably 8–12 additional/spread-out checks. Reject points with unstable homogeneous division, behind-camera geometry or excessive distance/error. Record calibration quality by region.

Changing a camera pose, focal length, crop, aspect ratio or ground surface invalidates its calibration until a new revision passes checks. A source reconnect alone need not invalidate static geometry, but it must revalidate reported image dimensions.

The sim team remains responsible for its native ParticleField rendering policy. This handoff does not authorize opening a legacy composition or rendering a scene to obtain the plan.

## 3. Observation stream

Keep existing NVSchema protobuf on Kafka. Preserve current field types and old consumers. Map canonical classes into existing accepted types and store precise classes and city-specific attributes in namespaced `info` fields until a versioned protobuf change is justified. Do not assume unknown string types pass existing validators.

Proposed browser representation below uses **illustrative values**, not observations from a running city:

```json
{
  "schemaVersion": "city.observations.v1",
  "siteId": "expo-intersection",
  "sourceId": "example-source-uuid",
  "sourceSessionId": "example-session-uuid",
  "sequence": "1842",
  "sourceFrameId": "1842",
  "sourceTimeNs": "1792617600123456789",
  "timestampBasis": "source-rtcp",
  "receivedAt": "2026-10-21T21:20:00.140Z",
  "image": {"width": 1920, "height": 1080},
  "calibrationRevision": "cal-3",
  "rulesRevision": "rules-12",
  "modelRevision": "example-engine-build-id",
  "objects": [
    {
      "localTrackId": "7263",
      "globalTrackId": null,
      "class": "bus",
      "confidence": 0.93,
      "bboxPx": [820, 430, 210, 180],
      "anchorPx": [925, 610],
      "anchorMethod": "bbox-bottom-centre",
      "positionM": [12.4, 8.1],
      "projectionStatus": "valid",
      "positionUncertaintyM": 1.2,
      "velocityMps": null,
      "observedThisFrame": true,
      "zoneIds": ["bus-stop-approach"]
    }
  ]
}
```

Here `sourceTimeNs` is Unix-epoch nanoseconds, not the raw NTP wire representation; it corresponds to 21:20:00.123456789 UTC. Convert DeepStream timestamps explicitly and retain the clock basis. Do not use this illustrative record as live data.

Requirements:

- Publish zero-object frames and source heartbeats. No detections and no data are different states.
- Include observed-versus-tracker-predicted status. Prediction must not masquerade as a fresh detection.
- Missing/invalid calibration yields `positionM: null` plus a reason. Never fall back to pixel coordinates under metre labels.
- Use null for unavailable confidence, velocity or uncertainty; never manufacture zero or a precision estimate.
- Start with calibrated anchor positions, not assumed full vehicle footprints. Add footprints only under a separately validated method/version.
- Per-frame metadata feeds rule evaluation. Browser snapshots can be coalesced to 10–15 Hz; durable crossing events must not disappear when intermediate display snapshots are dropped.
- Cache short track history and apply bounded TTL. Never extrapolate indefinitely during an occlusion or stalled stream.
- Class changes, track reset and source epoch must be handled explicitly. A recycled numeric tracker ID must not inherit old dwell time.

Suggested internal fields include `ct.city.sourceSessionId`, `ct.city.class`, `ct.city.calibrationRevision`, `ct.city.rulesRevision`, `ct.city.timestampBasis`, and `ct.city.projectionStatus`. Confirm protobuf round-trip and legacy ingestion before selecting their exact names.

## 4. Time and presentation

Maintain source event time, ingest time and browser presentation time separately. For RTSP, source RTCP/NTP time is preferred. If unavailable, retain a declared arrival-time basis with measured uncertainty; disable claims requiring accurate cross-camera alignment until fixed.

The media gateway must preserve or expose a mapping from presented video frames to the source clock, including after re-encode. WebRTC presentation metadata can help when available, but browser receipt time and `video.currentTime` alone do not establish the mapping. DASH replay uses media time plus the verified archive segment timeline.

Use one shared display cursor for both cameras, map and evidence. If stream delays differ, buffer the faster stream or clearly expose independent times; do not silently portray asynchronous events as simultaneous. Record dropped/late frames and timestamp discontinuities.

The overlay selects observations matching the presented frame. Map interpolation is bounded between measured samples, or short explicitly predicted intervals; observations older than the configured freshness limit are marked stale. Longer gaps hide/fade tracks and make affected event state unknown. Disconnect is not proof that a vehicle left a zone.

## 5. Rule definition and activation

Extend the current monitoring-rule API and editor. Keep one canonical rule store; do not maintain independently editable polygons in DeepStream, behavior analytics and the browser.

Proposed rule example:

```json
{
  "schemaVersion": "city.rule.v1",
  "id": "restricted-stop-west",
  "revision": 12,
  "siteId": "expo-intersection",
  "sourceId": "example-source-uuid",
  "kind": "stopped-in-zone",
  "classes": ["car", "bus", "truck", "motorcycle"],
  "geometry": {
    "space": "image-normalized",
    "points": [[0.31, 0.48], [0.62, 0.48], [0.71, 0.82], [0.20, 0.82]]
  },
  "calibrationRevision": "cal-3",
  "conditions": {
    "speedBelowMps": 0.5,
    "minimumDurationMs": 5000,
    "clearAfterMs": 1000,
    "maximumObservationGapMs": 500
  },
  "authority": "behavior-analytics",
  "primitiveProvider": "deepstream-nvdsanalytics",
  "enabled": true
}
```

Thresholds above are initial demonstration examples to tune, not validated values. A world-space rule instead contains metre coordinates, an authoritative ground polygon and a defined projection method. Do not silently replace world containment with a different image rule near ambiguous boundaries.

Rule families:

| Kind | Geometry | Primitive / authoritative state |
| --- | --- | --- |
| `area-entry` | Polygon | Native membership; backend transition |
| `line-crossing` | Two endpoints plus explicit allowed direction vector | Native crossing; backend durable event/count |
| `occupancy-threshold` | Polygon, class filter, count threshold, duration | Native per-frame count; backend sustained threshold |
| `dwell` | Polygon and duration | Backend track/zone state |
| `stopped-in-zone` | Polygon, metre-speed threshold and duration | Backend calibrated state |
| `wrong-way` | Lane polygon/direction and duration | Native direction evidence plus backend validation |
| `queue` | Lane polygon, class/speed/count thresholds | Backend aggregate state |

Do not invoke both existing `TripwireEvent` and native crossing as independent publishers for the same rule. Select one primitive authority; the backend is the durable event publisher. Per-rule thresholds, timers and cooldowns must remain independent, unlike the current API's aggregation of some global settings.

Activation transaction:

1. Validate geometry, class capability, source dimensions, speed calibration and supported rule type.
2. Save a pending immutable revision with compare-and-swap against the previous revision.
3. Compile normalized geometry into the configured analytics coordinate system; maintain UUID-to-DeepStream stream-index mapping through reconnects. Convert class groups explicitly.
4. Write the worker configuration atomically in an application-owned directory. Restrict this to controlled file paths.
5. Request DS 9.2 analytics reload through its documented API; ensure the actual worker has the corresponding handler/plugin.
6. Apply matching backend rule state. Emit active revision and effective timestamp from the worker/backend adapter after successful application.
7. Mark active in UI only after that acknowledgement; otherwise show pending/error and retain or restore the last good revision.

The documented reload API is not itself a cross-service transaction or revision readback. Those are adapter responsibilities. Test which native counters reset on reload and track a counter epoch; never add a reset cumulative count as a negative increment or duplicate history.

## 6. Event lifecycle and evidence

Use `normal → candidate → active → cleared`, with separate `unknown` observation health. Timers use source elapsed time, not an assumed FPS. Hysteresis absorbs edge jitter; a short lost track can remain uncertain, but a long gap must not become a fabricated departure.

Each event contains immutable event ID, site/source/session, rule ID/revision, class and track references, start/trigger/end times, measured values, calibration/model revisions and evidence status. Use an idempotency key from the source session, rule and transition identity. Replay, reconnect or Kafka redelivery must not create duplicate incidents.

Evidence links use the existing VSS retained-clip service and source timestamps. Suggested initial clip window: five seconds before and five seconds after the trigger, with an explicit pending state while the latter is collected. Clip URLs and resource IDs come from VSS, not constructed browser guesses.

The UI can immediately show “Vehicle stopped in zone · 5 seconds” from structured facts. A later explanation appears separately with its evidence and generation status. Reports compute totals/durations from structured event records, and may use the VLM to explain them. Model prose is not the source of numerical totals.

## 7. Proposed application interfaces

These names are proposed, not currently available APIs:

| Interface | Purpose |
| --- | --- |
| `GET /api/vision/sites/:id` | Static map, current calibration/rule revisions and capabilities |
| `WS /api/vision/sites/:id/live` | Authenticated snapshots/deltas, event notifications and health |
| Existing monitoring-rule route, extended | Versioned edits, pending/applied state, errors |
| Existing event/evidence routes | Incident history, retained media and reports |
| Existing analysis-profile route, extended | Model capability and actual admitted source capacity |

A small live gateway can run beside the current API and be reverse-proxied under the same origin; do not assume a Next.js request handler is a persistent WebSocket server. Reuse application authorization. Browser clients receive no RTSP credentials or Kafka access.

On subscription send a complete snapshot and sequence, then bounded updates. Slow clients receive a fresh snapshot instead of an unbounded backlog. Durable event history remains retrievable even if a notification is missed. Keep event persistence independent from animation updates. Expose fresh/stale/disconnected states for each source, analysis worker and map projection.

## 8. Artifact lock to create during implementation

Record: detector package/tag, checkpoint URL and SHA256, license/notice, ONNX hash/opset, input contract, output class map, parser/preprocessor source revision, TensorRT and CUDA versions, GPU identity, precision/batch profiles, engine hash, DS base digest, custom application build revision, tracker configuration hash, site/calibration/rule revisions and evaluated dataset revision.

Unresolved hashes remain explicitly unresolved until artifacts exist. Keep this model/site lock separate from user-editable runtime settings. A checkpoint or preprocessing change invalidates old performance and accuracy receipts.
