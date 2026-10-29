# Smart City analytics gateway

This is the shared Smart City analytics foundation for VSS. It consumes real worker observations, projects camera-local tracks onto a calibrated local-metre map, evaluates rules and supplies the native Smart City workspace. Import/startup produces no sample observations.

Run from `services/analytics/behavior-analytics`:

```bash
python -m pip install -r apps/city/requirements.txt
CITY_STATE_DB=/opt/city/state/city.sqlite3 uvicorn apps.city.main:app --host 127.0.0.1 --port 9184
```

The parent deployment provides the isolated service/container and same-origin UI proxy. The gateway is an internal service: bind to loopback or a private service network and expose the browser route through VSS authorization. It must not receive a public unauthenticated port.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `CITY_STATE_DB` | SQLite state path; default `/tmp/vss-city/state.sqlite3`. Mount durable storage in the deployment. |
| `CITY_SITE_FILE` | Optional static JSON package to load only when the database has no configured sources. |
| `CITY_RULES_FILE` | Optional `{rules:[...]}` JSON or rule array, loaded only when no rules exist. |
| `CITY_MEDIA_ROOT` | Server-controlled directory for recorded media, default `/opt/city/media`. |
| `CITY_MEDIA_REGISTRY_JSON` | Server-controlled source ID → relative filename dictionary. HTTP requests cannot register filesystem paths. |
| `CITY_NATIVE_CONFIG_DIR` | Shared directory for `analytics.ini` and `analytics-ack.json`. Without it, native primitive status is `not-connected`; backend rule evaluation still works. |

Site packages contain `id`, `name`, `revision`, `mode`, `sources` and `map`. Mode is one of `live`, `recorded-inference` or `fixture-replay`. A source has `id`, `name`, original decoded `width`/`height`, optional 3×3 `imageToGroundHomography`, image-pixel `validGroundPolygon`, `calibrationRevision`, `mediaUrl`, optional VSS `vssSensorId` and `deepstreamStreamIndex`. Source IDs must match the worker exactly. `map.bounds` is `[minX,minY,maxX,maxY]`; vector `roads` and `buildings` use `points` in local metres.

Snapshots include `siteRevision` for bounded UI configuration refresh. Source `modelRevision` comes from actual observations; a historically selected source and its tracks share the selected frame's model revision. Live health separates `ingestAgeSeconds` from reported `sourceClockAgeSeconds` and a bounded `sourceClockProgressRatio` (16 approximately one-second samples). A source can receive fresh observations while its video timeline falls behind. `sourceClockStatus: delayed-or-unsynchronized` flags an absolute clock offset above five seconds or progress below 0.9 of arrival time; those are diagnostic thresholds, not measured camera accuracy. `sourceClockPrecision` remains `unverified`. RTCP source-clock metadata alone does not qualify browser overlay alignment or physical capture latency.

Missing calibration yields `positionM: null` and `projectionStatus: missing-calibration`. Invalid matrices fail validation; failed/horizon/out-of-map projections never return pixels labelled as metres. Known camera geometry is still subject to independent landmark validation in the final scene. A bbox-bottom-centre is an estimated ground anchor, not an inferred full vehicle footprint.

## HTTP contract

All JSON responses are unwrapped. Canonical observation/site semantics are also described in `docs/smart-city-data-contracts.md` at repository root.

| Route | Result |
| --- | --- |
| `GET/PUT /api/v1/city/site` | Site package. Replacing geometry invalidates transient tracks/history and makes ongoing events unknown. |
| `GET /api/v1/city/snapshot` | Complete bounded current state; initially valid empty state with `setupRequired: true`. |
| `GET /api/v1/city/snapshot?mediaTimeSeconds=3&sourceId=cam-a` | Closest recorded observations within `maximumSkewSeconds` (default 0.25); source ID is optional to query both cameras at a shared media time. Missing matching history returns no tracks and `clockAligned: false`. |
| `GET /api/v1/city/snapshot?sourceId=cam-a&sourceTimeNs=1792617600123456789` | Bounded live frame lookup for a source capture clock. `source-rtcp` or explicitly pinned/proven `source-native-sei` permits lookup; arrival/unsynchronized clocks return no boxes. Browser video presentation still requires its independent clock guard. |
| `GET/PUT /api/v1/city/rules` | `{rules:[...],revision,status,nativeAnalytics}`. PUT accepts `{rules:[...],expectedRevision:n}`; stale compare-and-swap returns HTTP 409. |
| `POST /api/v1/city/observations` | Validate and process one complete source frame, including zero objects. Returns `{accepted,sourceId,sessionId,sequence,trackCount}` or a rejected duplicate/out-of-order reason. |
| `GET /api/v1/city/events` | `{events:[...],limit,mode}`; supports `sourceId`, `ruleId`, `state`, `limit<=1000`. |
| `GET /api/v1/city/reports?format=json` | Structured event records and counts, explicitly camera-local. `format=csv` returns an export. |
| `GET /api/v1/city/stream` | SSE `snapshot` events with complete snapshots at up to 4 Hz; snapshot construction/encoding runs outside the ASGI loop, and slow readers do not accumulate a queued delta backlog. Exact analyzed previews have their own delivery cadence. |
| `GET /api/v1/city/health` | Service health, setup status, source freshness and native application acknowledgement. |
| `GET /api/v1/city/media/{sourceId}` | Only registered source recordings. Framework file response supports HTTP ranges. Outgoing browser URLs use `/api/vision/city/media/{sourceId}`. |
| `PUT /api/v1/city/media-registration` | Internal host controller registers `{sources:[{sourceId,filename}]}` for existing site IDs and existing video basenames within the configured media root. No HTTP paths or remote downloads are accepted here. |

Observation example (illustrative only):

```json
{
  "schemaVersion": "city.observations.v1",
  "siteId": "expo-intersection",
  "sourceId": "cam-a",
  "sourceSessionId": "new-uuid-per-restart",
  "sequence": "101",
  "sourceFrameId": "101",
  "sourceTimeNs": "1792617600123456789",
  "timestampBasis": "file-epoch-plus-pts",
  "mediaTimeSeconds": 3.366666667,
  "image": {"width": 1920, "height": 1080},
  "modelRevision": "recorded-artifact-lock-id",
  "objects": [{
    "localTrackId": "18446744073709551614",
    "class": "bus",
    "confidence": 0.93,
    "bboxPx": [820, 430, 210, 180],
    "observedThisFrame": true,
    "globalTrackId": null,
    "associationMethod": null,
    "positionUncertaintyM": null
  }]
}
```

The gateway derives positions from boxes and configured calibration; incoming unverified `positionM` extras are not used. Source clocks and sequence numbers remain integer strings. Prediction is explicitly marked and does not count as a fresh observation. Each worker restart/replay loop needs a new `sourceSessionId`; `reset: true` is an explicit discontinuity. Small late/out-of-order frames are rejected. A clock rollback larger than two seconds accompanied by sequence rollback starts a new internal epoch.

Snapshots include `siteId`, `mode`, `timestamp`, `sequence`, `sources`, `tracks`, `zones`, `rules`, `events`, `metrics`, `setupRequired` and `association`. Tracks retain source/session/local identity, optional global identity, bounding boxes, projection status, velocity and bounded trails. Global association is not enabled automatically: `association.globalFusionEnabled` is false. An upstream validated MV3DT adapter can supply a nullable `globalTrackId` and method without replacing camera-local identity.

Configured cameras with no observations since startup report `awaiting-observations`, with `setupRequired: false` and `awaitingObservations: true`. Historical replay can still be available from SQLite. A native configuration acknowledgement is historical application evidence: `lastAppliedRevision` remains visible after worker completion, while `status: applied-inactive` and `operationalStatus: stale` or `awaiting-observations` prevent an old acknowledgement from appearing as a current active worker.

## VSS source profile controller

`tools/smart-city/controller.py` is a separate host-user process that implements the existing RTVI-CV lifecycle REST contract. It listens only on loopback port 9190 and uses the host Docker CLI through fixed argument lists. It does not expose a Docker socket in the analytics container. Set the Agent's `VSS_CITY_RTVI_CV_URL=http://127.0.0.1:9190` to enable the `smart-city` source analysis profile; no worker is enabled by a default URL.

The controller implements `POST /api/v1/stream/add`, `POST /api/v1/stream/remove`, `GET /api/v1/stream/get-stream-info`, `GET /api/v1/health/get-dsready-state` and `GET /api/v1/health`. Add/remove use the existing `{key:"sensor",value:{camera_id,camera_name,camera_url,change,metadata},headers:{source:"vst"}}` shape. Inventory uses `{"stream-info":{"stream-info":[{"camera_id":"..."}]}}`, matching existing Agent cleanup. Maximum capacity is two registered sources; duplicate add is idempotent while running, and unknown removal never stops a different source.

Readiness requires an actual native worker image, RF-DETR engine, current saved memory guard/headroom and a healthy city gateway. Callback source UUIDs must exist in the configured VIOS inventory. File sources use controlled staged originals or source-specific VIOS exports; arbitrary HTTP origins, filesystem paths and shell commands are rejected. Actual image dimensions come from `ffprobe`, rather than the Agent's generic metadata default. RTSP requires an exact registered URL and a hostname explicitly enabled by `CITY_RTSP_ALLOWED_HOSTS`. Recorded and live sources use separate sites/time domains.

Each accepted source set updates the canonical gateway site, registers controlled media and runs the existing guarded `manage.py analyze` command. Adding/removing one of two sources restarts the shared worker and therefore changes tracker sessions. Recorded files finish after their bounded pass. Live sources use explicit `--live --frames 0`, retaining the saved guard and cancellation cleanup; unexpected successful end-of-stream renews under that guard, while a failed process remains stopped until explicit resume. The controller's source state file never proves that a worker is currently running. Host controller integration and native inference still require their separate runtime receipt; CPU unit tests mock Docker and services.

Install the isolated host environment from `tools/smart-city/controller-requirements.txt`, then run its Python with `tools/smart-city/controller.py --device spark`. The controller performs metadata probing in a separate CPU process with an outer 20-second timeout. It uses host ffprobe when available and otherwise its pinned OpenCV package with software decoding and five-second open/read timeouts. No system ffmpeg installation or GPU probe is required.

The reproducible operator commands are:

```bash
python3 tools/smart-city/manage.py controller-setup
python3 tools/smart-city/manage.py controller-service
systemctl --user daemon-reload
systemctl --user enable --now vss-city-controller-spark.service
python3 tools/smart-city/manage.py profile-enable
python3 tools/smart-city/manage.py controller-status
```

The user service runs `.spark/city/control-env/bin/python`, listens on loopback 9190, and reads optional `.spark/city/controller.env`. Supported settings are `CITY_RTSP_ALLOWED_HOSTS`, `CITY_VSS_ORIGIN` and `CITY_GATEWAY_URL`; no shell evaluation occurs. For a manually managed process instead of systemd, use `controller-start`/`controller-stop`; PID checks verify both the command and Linux process creation time before signalling. The `controller-service` command writes the reviewable user unit; it does not itself enable it. Stop the standalone process before enabling the user unit.

`profile-enable` writes an additive `.spark/city/agent-city-overlay.json` and recreates only `vss-agent` with `--no-deps`. It preserves the existing base Compose file, all other profile endpoints, model services and saved budgets. The explicit city overlay must be reapplied after a base Agent recreation/render. `profile-disable` removes only the city worker URL; it does not delete the catalog entry or other industry profiles. Stop the persistent host service with `systemctl --user stop vss-city-controller-spark.service`.

Source operations also use the existing Agent, keeping its capacity, cleanup and durable selection logic:

```bash
# Connect preview only; no detector, embedding or VLM analysis starts.
python3 tools/smart-city/manage.py preview-register --url rtsp://CAMERA_HOST/city --name city-camera

# Apply Smart City to an uploaded recording. This starts actual GPU inference.
python3 tools/smart-city/manage.py source-analysis --kind recorded --source-id VIOS_UUID --profile smart-city

# Configure then resume an already registered paused RTSP camera.
python3 tools/smart-city/manage.py source-analysis --kind live --source-id VIOS_UUID --name city-camera --profile smart-city
python3 tools/smart-city/manage.py source-analysis --kind live --source-id VIOS_UUID --name city-camera --action resume

# Pause live analysis without deleting the source or its retained media.
python3 tools/smart-city/manage.py source-analysis --kind live --source-id VIOS_UUID --name city-camera --action pause
```

Read source UUIDs from actual registration/list responses. Do not replace the placeholders above with a guessed name-derived ID. Configuring a paused source keeps it paused; `resume` is the explicit inference action. Recorded reconfiguration skips embedding generation through the existing Agent analysis endpoint. Live resume follows the existing VSS live analysis path and can also restore configured semantic services, so its resource envelope must be qualified separately.

## Rules and native primitives

Supported backend rules are `area-entry`, `line-crossing`, `occupancy-threshold`, `dwell`, `stopped-in-zone`, `queue`, and `wrong-way`. Geometry uses `image-normalized` or `site-metres`; polygons must be non-self-intersecting and have positive area. Lines need exactly two endpoints and an explicit movement `direction`. Wrong-way polygons need an allowed direction. Directions are interpreted in the geometry's own coordinate system. Conditions contain independent duration, clear hysteresis, observation-gap, count and speed thresholds.

Timers use source elapsed time, not wall time or assumed FPS. Long unobserved gaps do not accumulate candidate dwell. Fresh observed exits can clear an event; source loss or expired tracks make it unknown. Queue counts refer to slow tracked anchors inside the polygon, not a claim about why traffic stopped. Stationary/queue/wrong-way rules require calibration so metre-speed thresholds are meaningful.

Backend rules become active when applied locally. Native state is reported separately and never assumed active merely because the INI was written. The gateway atomically writes `analytics.ini` with `# city-rules-revision=<n>`. The worker watches that file and writes `analytics-ack.json` only after application, including a new counter epoch. The bridge recognizes an active acknowledgement only if its revision matches the requested revision. Worker-native ROI primitives are unfiltered by class because DeepStream class filtering applies at section level; authoritative class-specific counts/events come from the backend. World polygons remain backend-only until inverse projection is validated. Native crossing metadata cannot independently publish duplicate city incidents.

The `nvschema.from_frame` adapter converts the existing generated NVSchema protobuf frame, preserves integer nanosecond precision and precise classes from `ct.city.class`. Existing VSS Kafka consumers can call this adapter with configured source identity/session/dimensions; this standalone service does not silently subscribe to every Kafka camera or infer sessions from display names.

## Existing VSS visual questions for recorded sources

City source IDs and VIOS IDs serve different purposes. Set the site's `vssSensorId` to the assigned VIOS sensor UUID. For uploaded files the sensor/stream UUIDs observed below are identical. The UI then uses the existing `/api/vision/analyst` replay path and the existing Cosmos reservation/admission checks. Embedding is not required to inspect a selected retained recording.

The existing media-only upload method is implemented in `libs/vss/core/src/vss_core/vios/client.py:upload_media`: `PUT /vst/api/v1/storage/file/{filename}?timestamp=<ISO>` with raw bytes and `Content-Type: application/octet-stream`. Prefer the configured `vss vios add --type video` CLI where installed; it wraps this method and waits for indexing. For protocol debugging/explicit local integration, the supported request is:

```bash
curl --fail-with-body --request PUT \
  --header 'Content-Type: application/octet-stream' \
  --data-binary @.spark/city/media/traffic-sample.mp4 \
  'http://127.0.0.1:30888/vst/api/v1/storage/file/traffic-sample.mp4?timestamp=2025-01-01T00%3A00%3A00.000Z'
```

Read assigned UUIDs from the upload response and verify `/vst/api/v1/storage/timelines`; never derive IDs from filenames. Do not repeat a successful upload merely because the initial request took time. The Agent's separate `POST /api/v1/videos/{sensor_id}/complete` endpoint invokes configured embedding hooks even for the semantic profile; it currently has no per-request skip-embedding control. Media-only upload intentionally avoids those extra GPU jobs.

Local media registration completed on October 22, 2026, without invoking model work:

| Recording | Assigned sensor/stream ID | Verified retained range |
| --- | --- | --- |
| `traffic-sample` | `9821cf71-2e77-44e3-8655-7c1ddbe47681` | `2025-01-01T00:00:00.000Z` to `2025-01-01T00:00:48.100Z` |
| `pedestrian-sample` | `b6e98271-cb65-4c3f-b6c7-d0b890a2a533` | `2025-01-01T00:00:00.000Z` to `2025-01-01T00:01:19.500Z` |

These are machine-local registrations, not portable constants or proof of Cosmos qualification. On another deployment, list/register sources and use its returned IDs. For the current local traffic recording, the existing UI analyst request shape is:

```json
{
  "query": "Describe the traffic visible in this interval.",
  "scope": "selected-source",
  "askedAt": "2026-10-22T04:10:00.000Z",
  "conversationId": "city-traffic-check",
  "sources": [{
    "sensorId": "9821cf71-2e77-44e3-8655-7c1ddbe47681",
    "streamId": "9821cf71-2e77-44e3-8655-7c1ddbe47681",
    "name": "Traffic sample",
    "kind": "replay",
    "playback": {"capturedAt": "2026-10-22T04:10:00.000Z", "currentTimeSeconds": 12, "durationSeconds": 48.1}
  }]
}
```

Use the actual current request time for `askedAt`/`capturedAt`; the illustrated values above are not copied recording clock values. Cosmos must be restored and admitted before this request is run. This media registration did not test the VLM.

## Explicit fixtures

Fixtures are opt-in, visibly synthetic, and use the same validated API/engine path as worker observations. They have two exact known camera transforms, a simple street plan, six object classes and all seven rule families. They are intended to test geometry and event logic, not model accuracy, video synchronization or global tracking. Replacing a live site's configuration with fixtures is an explicit operator action.

```bash
# Write a package without touching any running gateway.
python -m apps.city.fixtures --write-package /tmp/city-geometry-fixture

# Seed and replay twenty seconds quickly through the HTTP ingestion API.
python -m apps.city.fixtures --base-url http://127.0.0.1:9184 --fps 5 --no-realtime

# Explicit continuous display loop; all panes remain labelled synthetic.
python -m apps.city.fixtures --base-url http://127.0.0.1:9184 --repeat
```

The fixture command changes the gateway site to `city-geometry-fixture` with `mode: fixture-replay`. It never attaches traffic video to synthetic observations. Each camera declares `fixtureDurationSeconds: 20`. The UI may render the known coordinate grid and fixture boxes without pretending there is camera video.

## Bounded state and validation

In-memory state is bounded to 16 configured cameras, 2,000 tracks, 40 trail points per track, 60 cached frames per source and 1,000 displayed events. Missing tracks expire after 15 seconds; freshness defaults to two seconds. SQLite retains at most 50,000 event records and 18,000 frames per source, with a 256 MiB global serialized-frame budget. Each event record retains at most 32 source-clock state transitions. Historical queries preserve an unknown observation gap after recovery; requests before a truncated transition history report `state-history-truncated` and unknown state rather than guessing active. Legacy records without the needed transitions report `state-history-unavailable` before their last proven boundary. Historical responses omit future transitions. History trimming is amortized every 32 writes, with immediate byte-budget checks. Historical frame queries survive worker completion and gateway restart; current-source health remains separate. Site/calibration replacement invalidates old frame history. Recorded history is not extrapolated beyond a matching timestamp.

The optional [exact inference-frame preview](PREVIEW.md) pairs a bounded JPEG with the source/session/sequence/time/model-matched frame snapshot. It retains only two latest volatile images, expires them after two seconds and never puts JPEGs into SQLite/history/events. This proves the native image/metadata pair independently of a missing WebRTC capture clock; it does not claim absolute clock or map calibration verification.

Run focused CPU tests from `services/analytics/behavior-analytics`:

```bash
python -m pip install pytest httpx
python -m pytest -q apps/city/tests/test_city.py
```

Tests cover invalid/boundary/finite geometry, directed crossings, duplicate delivery, source-time dwell, calibrated stop and queue logic, wrong-way coordinate conventions, gaps and source resets, stale/unknown state, bounded cache/SQLite history, restart persistence, media range access, rule revision conflicts, native revision acknowledgements and all rule families through explicit fixtures. Native DeepStream/TensorRT inference and final-city accuracy need separate runtime receipts.

## Prepared scenario evidence boundaries (October 26, 2026)

`POST /api/v1/city/scenario-boundary` accepts `{action, runId, scenarioId?}`.
The host controller owns one opaque `runId` throughout preparation, playback and
cleanup; simulator actor IDs or positions are never accepted here.

1. `prepare` synchronously gates analytics before the controller moves actors.
2. After staging, `settle` writes a native tracker reset request. Poll `GET` on
   the same path until `state: ready`. Both cameras must supply at least three
   accepted post-reset observations spanning one source-clock second, after the
   staging capture fence. Both tracker stages must acknowledge the serialized
   reset under the paired map profile. A 20-second deadline fails closed.
3. `play` opens a new scenario scope immediately before actor playback. Images
   captured before that command remain excluded even when delivered later.
4. `normal` archives the run and starts a fresh normal-traffic scope when normal
   movement resumes without repositioning. If cleanup can move actors, call
   `recover` first, perform cleanup, then `settle`, wait for `ready`, and `normal`.

Repeated requests in the same phase are idempotent. Another run cannot take the
active gate. A gateway restart during a scenario recovers with analytics gated;
`recover` / `settle` / `normal` are required before resumption. Failed settlement
never automatically opens the gate. Actor cleanup and its watchdog remain the
host controller's responsibility. Ready can wait for the operator while fresh
post-reset camera frames continue; stale frames refuse Play.

Capture/source sessions and sequences continue through boundaries. Source-clock
proof, exact image matching, calibration, rule revisions and evidence thresholds
are unchanged. Gated frames retain exact preview pixels with empty operational
tracks/metrics/events. Scope changes clear motion fits, trails, rule candidates,
queue/pedestrian/curb journeys and rolling counts; they do not invent a departure.
Live events become unknown at the last observed time when evidence is cut.

Snapshots, exact-preview snapshots, sources, mobility and new events carry
`analyticsScope`. Historical frames retain their original scope. New track keys
include the scope UUID, so a reused low-level tracking number cannot inherit a
trail. `GET /api/v1/city/analytics-scopes` retains the last 100 scope summaries;
durable events retain their original scope separately under the ordinary event
retention limit. Legacy events have no retroactively invented run label.
Archived mobility is the last observed summary before scope invalidation,
identified by `mobilitySnapshotBasis: "last-observed-before-boundary"`.
`observationEnd` records the boundary reason and the transition of active events
to `unknown`; the saved summary does not assert subsequent departure or clearance.

The focused synthetic-observation tests prove the boundary behavior, not AI
recall or scenario success. Live paired tracker reset and RTSP continuity still
require the current deployment's measured receipt.
