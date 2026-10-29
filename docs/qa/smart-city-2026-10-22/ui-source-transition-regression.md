# Static-site / live-snapshot transition regression

## Observed evidence

The UI log contains two full-recording evidence requests at the time of the reported VIOS streamprocessing OOM:

- `2026-10-22T04:54:17.749Z`: pedestrian recording, `2025-01-01T00:00:00.000Z` through `00:01:19.500Z`, HTTP 502.
- `2026-10-22T04:54:17.785Z`: traffic recording, `2025-01-01T00:00:00.000Z` through `00:00:48.100Z`, HTTP 502.

These were not deliberate QA exports or visual-analyst questions. Code inspection found a source-transition path that explains both requests: streamed `snapshot.mode=live` could reach a camera before its static recorded site/source configuration refreshed. The camera entered live-preview rendering with an old recorded-file ID. The catalog resolved that file, and the shared `VisionStreamCanvas` correctly selected its recording path, requesting its entire retained timeline through `/api/vision/evidence`. The endpoint requests `transcode=full`, so two automatic file previews could initiate two concurrent full transcodes.

The recorded Smart City `<video>` path itself serves registered local files through the city range proxy. Catalog listing and sensor-status polling request metadata only; they do not export recordings. The problem was mounting a recording-capable shared canvas from a purported live-only wrapper during a configuration race.

## Repairs

- `CityLivePreview` refuses non-RTSP catalog entries before mounting `VisionStreamCanvas`. No recording-export effect can run from this wrapper. Snapshot picture export is disabled. Connection/retry errors remain visible.
- `CityCamera` takes its mode from the static site, rather than inferring it from a potentially mismatched snapshot.
- The city hook compares SSE site ID, mode, source IDs and optional `siteRevision` with the loaded static site. A mismatch suppresses the incompatible snapshot and frame requests until the configuration reload completes.
- Static refresh is debounced without being postponed by every video frame; requests start at most once per second, use bounded outage backoff and a ten-second timeout, abort superseded fetches, and reject late responses by generation.
- Current activity excludes retired sources/modes. Durable report exports retain historical events; unavailable retired-source review controls are disabled.
- The city streaming proxy marks its asynchronous response handling explicitly for Next.js, removing the false “API resolved without sending a response” warning while preserving actual upstream errors.

## Regression checks

- A stale file catalog entry does not mount the shared canvas.
- A real RTSP catalog entry mounts only the WebRTC adapter, with snapshot export disabled and status visible.
- Forty repeated SSE updates cause one bounded configuration refresh, rather than one request per frame.
- Source/mode and static-revision changes refresh configuration.
- A newer SSE configuration aborts an older static fetch; its late response cannot overwrite the new site.

Actual RTSP preview timing remains a separate qualification. The CUA browser surface disconnected during this pass (surface inventory empty, direct IAB creation unavailable), so no live-frame screenshot, capture/NTP correspondence, or successful GPU analyst call is claimed here. `browserClockVerified` remains unset.

Final source-transition regression run: all **11 suites / 64 tests passed**, TypeScript passed, and `git diff --check` was clean. UI request logs inspected after `05:01:00Z` contained no further `/api/vision/evidence` calls during this check; this is an endpoint observation, not a substitute for actual WebRTC frame qualification.
