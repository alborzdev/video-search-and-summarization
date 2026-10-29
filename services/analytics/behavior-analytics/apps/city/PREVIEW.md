# Exact inference-frame preview contract

This optional path replaces an unproven WebRTC capture-clock link with an image and analytics DTO from the **same native post-inference frame**. It does not verify an absolute camera/browser clock or physical ground calibration. The native producer is the trusted origin of the image-to-header identity; the gateway verifies that identity against an already accepted observation. It never creates another observation.

## Native producer

`POST /api/v1/city/preview`, `Content-Type: image/jpeg`, maximum **2 MiB**, with these headers:

| Header | Meaning |
| --- | --- |
| `X-City-Source-Id` | Configured source ID |
| `X-City-Session-Id` | Native `sourceSessionId`, not a guessed engine epoch |
| `X-City-Sequence` | Exact decimal observation sequence |
| `X-City-Source-Time-Ns` | Exact decimal observation source timestamp |
| `X-City-Width`, `X-City-Height` | Original observation dimensions |
| `X-City-Model-Revision` | Exact observation model revision; required when that revision is present |

The gateway matches source, declared session, sequence, source time, model and original geometry in its bounded **in-memory accepted-frame history**. It never uses a nearest timestamp or the recorded SQLite history to invent a new live frame. Duplicate source timestamps are allowed when sequences differ. Internal engine epochs, including reset/clock-basis changes, invalidate previously retained images. Configuration/rule generations also invalidate them.

The JPEG can retain original dimensions or use proportional downscaling. Its SOF dimensions and aspect ratio are checked against observation geometry; the browser must successfully decode it before presentation. The native implementation currently uses full original dimensions, JPEG quality 70 and a default ceiling of 15 JPEGs per second per source. Its preview branch has independent bounded queues; dropping a preview does not drop detection metadata.

| Response | Meaning |
| --- | --- |
| `201` | New exact frame accepted |
| `200` | Identical duplicate already accepted; no freshness extension |
| `202` | Metadata not yet present after at most 200 ms; retryable preview drop |
| `404` | Source not configured |
| `409` | Retired/superseded identity, geometry/model mismatch, stale observation, or capacity |
| `413` | JPEG or paired metadata exceeds its limit |
| `415` / `422` | Unsupported body type or invalid headers/JPEG geometry |

Fixture mode is rejected. A failed preview never reinserts metadata, fabricates a track or extends an old image's lifetime.

## Browser read

`GET /api/v1/city/preview/{sourceId}` returns `application/vnd.connecttech.city-frame`:

```text
uint32 big-endian JSON byte length
UTF-8 JSON DTO (at most 512 KiB)
JPEG bytes (at most 2 MiB)
```

The DTO is:

```json
{
  "schemaVersion": "city.preview.v1",
  "sourceId": "registered-source-id",
  "sourceSessionId": "native-session-uuid",
  "sessionId": "engine-epoch-id",
  "sequence": "42",
  "sourceTimeNs": "1700000000123456789",
  "timestampBasis": "source-rtcp",
  "modelRevision": "actual-model-revision",
  "image": {"width": 1920, "height": 1080, "jpegWidth": 1920, "jpegHeight": 1080, "mimeType": "image/jpeg"},
  "provenance": {
    "kind": "native-post-inference-exact-frame",
    "correlation": "source-session-sequence-time",
    "clockAlignment": "source-frame-exact",
    "browserClockVerified": false
  },
  "snapshot": {}
}
```

`snapshot` is a display projection of the captured **single-source** CitySnapshot: source row, tracks, rule geometry, zone/metric state, events, revisions, mode and source/media clock. It is captured when the corresponding observation is accepted, so a later object movement, rule edit or incident clear cannot enter that frame. Source rows expose `sourceSessionId`, engine `sessionId`, decimal `sequence`, `lastSourceTimeNs` and model revision for validation. Existing `observedThisFrame`/`stale` flags remain authoritative; render boxes only for actually observed fresh tracks. Retained stale tracks must not become invented boxes.

The October 26 display projection retains every active event in that captured history row and the eight newest other outcomes, including unknown outcomes without relabelling them cleared. Each trail keeps at most twelve original samples, evenly selected across its original span with both endpoints preserved. No position or timestamp is interpolated. `displayScope` states these bounds and the number of omitted non-active outcomes. Full source history and event/report records remain available through their separate APIs; a live preview is not the complete event archive. This projection never edits a captured history row, changes event evaluation, or borrows newer state. Rules, metrics, current positions, bounding boxes, identities and calibration are unchanged.

The source's rule geometry is tied to the captured generation. The DTO's `snapshot.clockAligned` is null: source-frame identity proves this image/analytics pair, independently of the declared timestamp basis, and does not assert an absolute WebRTC clock link. Use the supplied exact snapshot for the map; do not perform another nearest-frame lookup. Camera-local identities remain camera-local.

Image and source-specific overlays must be decoded/committed together. Use one in-flight request, forwarding `If-None-Match`, with the native health rate limit (1–30 FPS; 15 when unknown). A matching immutable ETag returns `304`. With `waitMs=0..1000`, a conditional read can await the next accepted preview before responding; no frame queue is created. Publication wakes asynchronous readers, and timeout rechecks expiry/session validity. The UI uses a one-second wait inside its existing 1.5-second abort deadline and pauses reads while hidden. Responses use `Cache-Control: no-store`. `204` with `X-City-Preview-Status: waiting|stale` means no usable image; `404` means an unconfigured source. The same-origin UI proxy must preserve the binary envelope, enforce both size bounds, redact internal source configuration, and expose no browser write route.

Presentation prefers `bitmaprenderer.transferFromImageBitmap`, transferring ownership of the decoded image to the canvas, with opaque 2D drawing as the compatibility fallback. A consumed bitmap cannot be transferred to a different canvas; a replacement needs a new exact pair. SVG boxes and pixels are committed together before paint. Canvas data attributes expose renderer, request/read/parse time, decode time and ready-to-commit time; these are local stage timings, not measured capture-to-screen latency or proof of hardware acceleration. The source callback still publishes only once per exact frame.

For native cameras whose WebRTC capture clock is unverified, an unavailable analyzed preview offers **Play video only**. It does not automatically open a second Video I/O playback pipeline during detector startup or restart. Playback is released when exact previews recover or the camera is hidden. Legacy cameras with a verified WebRTC clock retain their existing playback path.

## Bounds and health

Only the latest pair for at most **two sources** is retained. An accepted preview expires after **two seconds of monotonic delivery age**; expired image bytes are released on the next store operation. A small stale identity marker remains bounded to those two sources. JPEGs and envelopes are never stored in SQLite, observation history, events or reports. Decoding/inference is not repeated in the gateway. Original source clocks are copied from the matched observation, never inferred from JPEG arrival.

Site, snapshot and SSE source rows expose `processedPreview: {available, status}`. Health exposes:

```text
processedPreview:
  enabled, acceptedFrames, maximumSources, maximumJpegBytes,
  maximumJsonBytes, ttlSeconds, retainedBytes, sources[{id,available,status}],
  nativeDelivery
```

`nativeDelivery` reads only the fixed `preview-stats.json` next to the native analytics acknowledgment, capped at **32 KiB**. It reports `status: not-connected|missing|invalid|fresh|stale`, `enabled`, `failed`, `updatedAtNs`, delivery age, the configured rate/quality/queue limits and safe per-source counters. Only currently configured source IDs are exposed, at most two. Private error text, input URLs, local paths and credentials are omitted. A delivery age from zero to five seconds marks these counters fresh; it does not prove a capture clock or create an available image.

Per-source fields are `sourceId`, `width`, `height`, `selected`, `rateDropped`, `sourceQueueOverruns`, `identityMissing`, `identityEvicted`, `identitiesPending`, `geometryMismatch`, `encoded`, `oversizeDropped`, `networkQueueDropped`, `published`, `postFailed`, `pendingDropped`, `lastPublishedAtNs`, `observedEncodedFps`, and `observedPublishedFps`. UTC publication timestamps describe delivery health only. Missing, malformed, oversized or stale native status cannot produce a false current preview.

CPU tests run through the actual FastAPI observation/preview endpoints and private engine/SQLite state. They cover metadata races, exact duplicate timestamps, supersession, resets/generations, stale object flags, geometry/model/source mismatches, bounds, TTL/ETag, privacy and native delivery counter sanitation. Runtime JPEG encoding, actual GPU overhead and browser atomic presentation require separate integration qualification.

The opt-in pinned Isaac `source-native-sei` profile also places the selected frame's six-field `sourceClockEvidence` in the envelope and its matched source DTO. The browser checks exact capture time, raw AU PTS, native counter, basis and model identity before presenting the pair. This is the encoded-AU wall-handoff clock, not a verified exposure/browser clock; `provenance.browserClockVerified` and the native source's `browserClockVerified` remain false. RTCP and native evidence cannot be mixed for a shared map marker. See [the current clock contract](../../../../../docs/smart-city-data-contracts.md).
