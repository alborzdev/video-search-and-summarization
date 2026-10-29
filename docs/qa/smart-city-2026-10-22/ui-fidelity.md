# Smart City UI implementation and visual QA

The workspace is part of the existing VSS shell at `/?workspace=smart-city`. It is dynamically imported and does not replace the other workspaces.

## Accepted visual references

- `/home/sparkdev/Documents/ChatGPT/isaacsim-6/outputs/smart-city-vss-branded/2026-10-21/01-live-overview.png`
- `/home/sparkdev/Documents/ChatGPT/isaacsim-6/outputs/smart-city-vss-branded/2026-10-21/02-active-event.png`
- `/home/sparkdev/Documents/ChatGPT/isaacsim-6/outputs/smart-city-vss-branded/2026-10-21/03-ask-with-evidence.png`

All three references were inspected with `view_image` before implementation. Browser verification uses the Codex in-app browser through CUA, including screenshots. The Node filesystem is used only to save returned screenshot bytes as QA artifacts; no alternative browser automation is used. Initial captures exposed an existing `live-demo.css` specificity conflict that constrained presentation mode to the 224-pixel navigation column. The Smart City shell now explicitly uses one full-width column in presentation mode. The invalid temporary capture was removed.

## Fidelity ledger

| Comparison | Accepted reference | Implemented surface / repair |
| --- | --- | --- |
| Main composition | Two camera panes above a map, approximately 74% of the width; inspector on the right | Same composition with a 3:1 grid, equal camera panes, map below, and shared bottom timeline. Existing navigation remains in operator mode and collapses in presentation mode. |
| Branding and palette | White CT AI Labs logo, dark green-black surfaces, restrained teal and amber | Actual repository logo and Manrope are used. Workspace colors are `#08100f`, `#101918`, `#273936`, teal `#3fc2bd`, and amber `#f4bb43`. The fixed palette applies only to Smart City; other workspace appearance preferences remain saved. |
| Header | Quiet branding, scene name, local processing and presentation control | Branding remains in the existing rail in operator mode and appears in the header in presentation mode. Clear History and Appearance are hidden in this fixed-palette workspace, leaving the common actions available elsewhere. |
| Inspector | Now / Ask / Reports with large clear event text and evidence actions | These tabs are real controls. Now links objects and events; Ask calls the existing analyst API; Reports loads durable events and exports JSON/CSV. Event headings use plain descriptions rather than internal rule-kind names. |
| Camera framing | Camera imagery with boxes and translucent polygons | Real `<video>` media, SVG boxes, polygons and directed lines. `object-fit:contain` and an actual aspect-aware coordinate transform preserve letterboxing. Label hit regions were repaired so overlay labels do not steal clicks from neighboring object boxes. Full native IDs remain in the inspector; long labels use visible ellipses. |
| Map | Street plan, trails, selected objects and reset/zoom | Native SVG roads/buildings, calibrated observations, trails, pan, zoom and reset. Missing calibration produces a clear empty state. Camera identities remain local; the browser does not perform identity association, deduplication or invent fused positions. |
| Time | Shared timeline and selected event markers | Both recorded cameras seek together. Observations are requested by media time; overlays are hidden if the source reports a clock mismatch. Unverified live overlays are suppressed while the actual VSS live preview remains available. |
| Mobile | Not specified in the original desktop concepts | At 390×844 the cameras stack, followed by map and inspector. The shared timeline stays above the existing bottom navigation. The question input was measured above the navigation, and no horizontal page overflow was observed. |

## Intentional differences from the concept

The approved images show a future simulated intersection and an illustrative street-plan background. The test recordings contain two different real locations, including a moving camera, and have no common metric calibration. Their map therefore remains explicitly uncalibrated. A separately labelled geometry fixture validates the map, polygons, line crossings and event transitions with exact known transforms. Its camera panes say “Geometry fixture · synthetic observations” and “No camera video or AI inference in this view.” They are coordinate diagrams rather than synthetic camera photographs.

Visible copy added for these concrete states includes “Recorded video · real inference”, “Labelled fixture replay”, “Map calibration is not configured”, source-clock/geometry notices, setup errors and rule editing controls. Numerical counts and event messages come from gateway observations and rules. The illustrative “3 people crossing” and specific van/bus narrative are not hard-coded into the application. Current test footage and missing calibration prevent a claim of pixel-for-pixel scene fidelity to the simulated-city imagery.

## Verified interactions

- Loaded the workspace through the real Next.js route and inspected unavailable/retry behavior before the gateway started.
- Played a 20-second labelled fixture from both cameras. Inspected local track selection, map highlighting, map zoom/reset and changing rule counts.
- Drew two line endpoints in the camera image, reversed direction, saved a real versioned rule through the gateway, then removed that QA rule with the UI confirmation control. Fixture rules were retained.
- Opened Reports and loaded 11 durable fixture events. A scoped test reads the actual JSON Blob and verifies that it contains returned durable event records. The in-app browser download-event wait did not complete for a Blob download; the application export path is tested directly rather than claiming a successful browser download receipt.
- Played both real recordings and inspected actual RF-DETR / NvDCF observations. One bounded check showed 26 boxes at approximately 11.68 seconds, with 68 ms between the two paused media positions. Native segment-time correction subsequently tightened the source clock contract; final receipts must use the corrected worker session.
- Tested 390×844: document width 375 pixels within a 390-pixel viewport; the question input bottom was 731 pixels and navigation top 767 pixels. The viewport override was reset afterward.
- Scoped tests verify the actual analyst request uses the VSS sensor ID and selected playback time, displays upstream failures without canned text, and exports durable event data.
- Live overlay tests reject decoder-arrival timestamps and unverified clocks. Live boxes require matching preview aspect, verified browser/source correspondence, `source-rtcp` observations, and a nearest frame within the accepted skew. An estimated WebRTC capture timestamp alone does not set the verification flag.
- Read the real browser-facing site, snapshot and SSE gateway responses and confirmed that internal input URIs and filenames are absent.

## Runtime boundaries to retain

`browserClockVerified` defaults to absent/false. It must be set only after the actual RTSP → VSS/WebRTC route has a measured source-frame correspondence. If capture timestamps or correspondence are unavailable, live preview remains visible and overlay status explains the limitation. Camera-local IDs and per-camera event totals must not be marketed as deduplicated site-wide identities. The final Isaac Sim street plan, transforms and source calibration remain a scene handoff, with independent qualification of final-city timing and Thor performance.

## Final recorded-session receipts

After the corrected native worker completed all 2,238 frames, the browser was paused at 4.8 seconds. Both camera elements reported decoded media time `4.8`, observation media time `4.8` and `data-overlay-aligned=true`; the two cameras displayed 13 and 8 real tracked boxes. The current-activity caption correctly directs the viewer to the active event rather than claiming the worker is still awaited.

- `ui-real-desktop.jpg`: 1920×1080, presentation mode, corrected native history, actual media and missing-calibration state. Inspected with `view_image` against the accepted desktop composition.
- `ui-real-mobile.jpg`: full-page capture at a 390×844 viewport, corrected history, stacked cameras/map/inspector. Inspected with `view_image`. The document width was 375 pixels; the question input bottom was 753 pixels within the 844-pixel viewport. The temporary viewport override was reset. A malformed secondary screenshot returned after full-page capture was discarded.
- Event review: candidate onset `00:00.2`, activation `00:00.7`. Selecting the event sought both decoded cameras and observations to exactly `0.7`. “Ask about this event” kept the actual pedestrian source selected at activation. This check did not invoke the model while GPU benchmarking was in progress.
- Event timing uses explicit backend start/trigger media times when supplied, with a backward-compatible onset-plus-activation-delay calculation for earlier records. Fractional labels round once to tenths instead of flooring binary floating-point values.
- Fixture questions are disabled and explain that registered camera video is required; synthetic IDs are never submitted to the visual analyst.
- Live clock diagnostics are available as camera `data-*` attributes (capture time, RTP timestamp, observation source time, skew, gate and aspect match), without adding technical clutter to the presentation. These diagnostics do not set clock verification automatically.

Scoped validation passed TypeScript with `--noEmit --incremental false`, all 10 UI suites / 57 tests, and `git diff --check`. This includes saved-rule version conflicts, source-clock rejection, real analyst payloads and failures, durable JSON bytes, proxy redaction/range/status handling, and recorded-to-live refresh without stale replay requests suppressing live updates. The real GPU analyst and real RTSP route remain separate runtime qualification steps until their receipts are recorded.

The final small UI pass also verifies that the mobile presentation control fits fully inside the viewport (36-pixel icon button, x=327–363 in a 390-pixel viewport). A pending analyst request is aborted when site/source identity changes, so its answer cannot be shown over a different scene. The two affected suites passed 7 tests, including the added stale-answer regression; TypeScript passed again. These checks follow the complete 57-test run above. Actual analyst evidence ranges replace internal tool names in the visible answer footer.


## Source-transition hardening

A later runtime test exposed an automatic recording-export race during a recorded-to-RTSP configuration change. The causal path, two timestamped requests, safeguards and regression tests are documented in [ui-source-transition-regression.md](ui-source-transition-regression.md). Live preview is now RTSP-only, incompatible snapshots are suppressed, and static configuration follows bounded automatic SSE refresh. The existing recorded screenshots remain evidence of their stated recorded session; they are not live RTSP timing evidence. The browser surface disconnected before live-frame verification, and no verification flag was enabled.

Final source-transition regression run: all **11 suites / 64 tests passed**, TypeScript passed, and `git diff --check` was clean. UI request logs inspected after `05:01:00Z` contained no further `/api/vision/evidence` calls during this check; this is an endpoint observation, not a substitute for actual WebRTC frame qualification.


## Final source-clock and report truthfulness pass

Safe source telemetry (`ingestAgeSeconds`, `sourceClockAgeSeconds`, `sourceClockProgressRatio`, `sourceClockPrecision`, `sourceClockStatus`) passes through the credential-stripping proxy. A delayed/unsynchronized status takes priority over the generic unverified-overlay notice, even while editing: “Video is delayed or its clock needs checking.” A numerical age is labelled **reported source clock age**, comes directly from the backend, and is omitted if unavailable. It is not presented as measured end-to-end video latency. A fresh ingest timestamp cannot suppress this warning. Delayed cameras use an amber status indicator.

Reports say **SITE REPORT** and **Saved events** because event history is durable per site. View-time counts are labelled separately; JSON declares `historyScope: site` and the metric time scope. Ask links to “View site report”. Current-view empty copy does not claim the stored history is empty.

The final complete scoped run passed **11 suites / 67 tests**, including fresh-ingest/100-second-source-age priority, missing-age handling during editing, safe proxy telemetry, and durable site-report scope. No new browser or GPU qualification is claimed; the browser surface remains disconnected and clock verification remains unset.

## Live-event and preview lifecycle qualification

Live event timestamps now use the source clock and explicitly say that the clock is unverified. Processor-relative media offsets cannot be used to seek a live preview. A selected live event offers **Ask current camera**, with a notice that event-time footage has not been selected. It does not offer event review or silently imply that the current question is event evidence. Recorded events retain exact activation-time review and analyst context.

The shared WebRTC component had a concrete terminal-state bug: its no-frame deadline and ICE failure changed the visible state without releasing the mounted connection. Terminal failure now performs idempotent local peer/track/frame-callback cleanup, sends the remote stop request when its media-session ID is known, and closes signaling. An allocation whose answer is still pending retains only signaling for a maximum two seconds; a late answer is used solely to send stop and is never applied as SDP. A replacement of the same source waits for that full two-second bound plus the existing 1.2-second decoder handoff. Healthy peers are preserved across metadata and callback rerenders. This code finding does not attribute all VIOS process memory to WebRTC; the separate recording-export incident remains documented above.

The final scoped run passed **11 suites / 75 tests** and TypeScript `--noEmit --incremental false`. Tests cover no-frame cleanup, ICE failure, video-element failure, unmount before the allocation answer, the two-second unanswered bound, fast Retry during a late answer, and two healthy peers across repeated rerenders and a 30-minute fake clock. The CPU-only production-packaging controls passed **11 tests**, including deadline rejection before launch and explicit compiler-container cleanup after timeout. No production build, service recreation, browser session or model question was performed by this UI validation pass.

## Analyzed frame preview transport

The production browser subsequently played both WebRTC videos but provided RTP timestamps without `requestVideoFrameCallback.captureTime`. The existing overlay gate remained closed. The Smart City camera now supports an alternate native analyzed preview through `GET /api/vision/city/preview/{sourceId}`. Its binary envelope contains a four-byte big-endian JSON length, an exact frame DTO, and its JPEG. The DTO identifies native and engine sessions, source, sequence and nanosecond source time, and includes the exact accepted history snapshot. It never uses a nearest-time observation lookup.

The browser verifies all four identity fields against the snapshot source row, original/JPEG geometry, provenance and JPEG bounds. It decodes the image before committing the pair. The matching SVG is committed with the pair, and a canvas layout effect draws the decoded pixels before paint. Only a successful draw notifies the shared workspace; map/Now receive that exact snapshot directly. Normal camera/map geometry, zone states, events and metrics use its rule revision. Proposed geometry remains visible while editing. Predicted/unobserved and stale tracks are not drawn.

The new mode says **Frame matched · analyzed preview**. This proves image/metadata identity independently of the physical source clock. `browserClockVerified` is never enabled and `videoClockAligned` remains false for these pairs. Delayed-clock warnings retain their priority. When calibrated, the map says “Frame-matched ground positions · source clock unverified.” Each camera remains its own identity domain.

Requests are sequential, delayed at least 67 ms after a successful read/decode, with a 1.5-second request deadline, conditional ETags and a two-second independent stale-image deadline. Metadata is capped at 512 KiB and JPEGs at 2 MiB. The proxy reserializes a credential-scrubbed DTO before returning the bounded binary envelope. No object URLs are created; replaced/unmounted `ImageBitmap`s are closed. Source/session changes abort old requests and reject late decoded images. Raw WebRTC is unmounted while a decoded processed pair is available. Missing, stale, invalid or unconfigured frames return to raw preview with the existing unverified overlay gate. Previously frame-matched map positions are cleared on loss rather than replaced by future processor positions.

Native preview delivery health is read every two seconds with a 1.5-second timeout. Camera status tooltips report delivery status, published rate, intentional preview-rate skips, network queue drops and post failures. DOM diagnostics expose those reported values plus original/JPEG geometry, actual presentation rate/count, exact source/session/sequence/time, provenance and model revision. These values describe preview presentation/delivery, not detector throughput, measured end-to-end latency or physical-clock precision. Native inference remains separate from the display-rate ceiling.

This section describes the implementation and scoped CPU validation. New native GPU transport, production packaging and actual browser receipts must be recorded by the runtime qualification pass; the earlier recorded screenshots remain evidence only of their stated session.

Final paired-preview CPU receipt: **14 suites / 94 tests passed**, TypeScript `--noEmit --incremental false` passed with the canonical DASH source mounted read-only, and `git diff --check` was clean. Tests cover exact identity/geometry rejection, bounded binary proxy redaction, image/box selection and revision coherence, explicit unobserved-track suppression, conditional reads, the display-rate ceiling, stale expiry, bitmap disposal, stale-generation rejection, request cancellation, direct map receipt without a nearest-time call, and native health-counter failure states. Tests ran serially in temporary CPU-only `runc` containers with read-only source, no network, two CPUs and a two-GiB ceiling after fresh reserve/guard admission. The first temporary test environment inherited `NODE_ENV=production` and was corrected to `test`; the first typecheck omitted the canonical DASH mount and was corrected. Neither environmental failure was treated as a successful validation.

An independent review then found that source/session identity alone did not close a same-camera site/calibration-refresh race. The corrected path carries an explicit site/configuration generation key, requires the DTO's exact site ID/revision, mode, original dimensions and calibration geometry, and requires a known current session. A configuration change hides retained pairs synchronously and closes their bitmaps during layout cleanup; an old decode completing afterward is disposed without presentation. Configuration loading disables processed preview, and a disappearing expected session fails closed. Map receipt acceptance checks the current key/context/session again; stale cleanup callbacks cannot clear a newer generation. The map merger independently rejects old site revisions and geometry. The prepared package that preceded this fix is superseded rather than edited in place.

Generation regression receipt: **14 suites / 98 tests passed**, the canonical DASH-bound TypeScript check passed, and whitespace checks were clean. Focused controls hold an old decode through a same-source revision change/session disappearance, verify immediate disposal of an already retained pair, reject old site/geometry/calibration DTOs before decoding, and reject stale-generation map acceptance. This pass changes source/tests only; production and prepared-package runtime operations remain separately owned.

## Five-second live Ask and answer evidence

Smart City live questions now explicitly submit `lookbackSeconds: 5` to the existing analyst API. Recorded questions keep their media-offset behavior and omit this live-only field. The global VSS default and model/decoder configuration are unchanged. The prior one-frame path remains a separate runtime investigation; this change does not assert a proven decoder cause.

Each answer pins the exact city source, VSS sensor ID, source name, mode and site context at submission. The answer shows that source identity and the actual returned `observedWindow`, including dates and timezone; generation time is no longer labelled as an observation interval. A completed answer retains its pinned provenance if a different camera is chosen for the next question. Pending questions are cancelled when the effective camera changes through the selector, map track or event. Site/revision/catalog changes invalidate old answers and abort pending work.

**Load inspected clip (up to 5 s)** is an explicit user action. It requests only the pinned sensor and returned observation interval through the existing `/api/vision/evidence` API. No clip export occurs on render, answer arrival, SSE updates or camera selection. Missing/invalid/long intervals do not fall back to a full recording or a newly invented current interval. A changed returned start time is rejected. URLs are limited to the configured public VST/same-origin MP4 export path or the same-origin SHA-256-key evidence proxy. The public VST origin may differ from the browser loopback origin. The resulting player/link belongs to that answer/window; clip metadata longer than 5.5 seconds is rejected rather than presented as five-second evidence.

Preparation has a 90-second browser deadline, explicit cancellation, late-result guards and visible errors. Selection cancellation also clears an already loaded clip. New answers/site contexts unmount and cancel old evidence; recorded-camera links remain unchanged. Browser abort cancels the browser request; the existing evidence server retains its own bounded preparation/caching behavior and is not promised a remote stop by this UI.

An independent read-only review identified the loaded-link cleanup and effective map/event source cancellation gaps; both were fixed and re-reviewed with no remaining actionable findings. The final complete scoped UI run passed **16 suites / 119 tests**, including explicit five-second payloads, no automatic exports, original-source pinning after a selector change, actual-window labels, unsafe/shifted media rejection, full-recording rejection, timeout/cancellation and stale source/site responses. No runtime/model/Ask/build operation was performed by this source validation pass; production/browser verification remains separately qualified.


## Final production browser qualification

The immutable production package `20261022T073106035307Z` is deployed (source SHA256 `7cc24b10bab0ebfb6cb4b8aa216d73fb645058f3b00ef72c81dfec9001e13b5b`). All ten serial production build tasks completed. Root/site/health HTTP checks passed. Actual live camera DOM diagnostics showed `exact-processed-frame`, aligned overlays, one canvas/no raw video per pane, and identical preview/observation nanoseconds for each camera. No physical-clock verification flag was enabled.

An actual rendered live Ask returned its pinned source UUID and the interval 07:39:27.496–07:39:32.496 UTC. Clicking **Load inspected clip** prepared a playable 1920×1080 MP4, duration 5.1128 seconds (151 frames after export-boundary rounding). Native video playback advanced with no error; the real evidence link downloaded successfully. Changing the next-question camera removed the loaded clip while retaining the completed answer’s original source/window. This is an operational pass; manual frame review found a wrong posture description and unreliable fine vehicle types. Generated prose remains distinct from structured counts/events. See [the exact receipt](medium-final-ui-ask-evidence.json).

Presentation-mode desktop QA measured 1920-pixel document width in a 1920×1080 viewport. Mobile QA measured 375-pixel document width in a 390×844 viewport; no horizontal overflow. The temporary viewport was reset. The final browser error log was empty. Saved actual screenshots: `ui-final-live-desktop.jpg` and `ui-final-live-mobile.jpg`. These show independent recorded RTSP replays with real inference, the real image occupancy polygon and an explicitly uncalibrated map. They do not depict the future Isaac intersection. The [package/browser receipt](ui-final-production.json) pins image and source hashes.

The final two-hour combined runtime run started after this cutover. Its result must be added separately; these rendered controls do not imply endurance passed.


## Post-endurance browser verification

After the actual two-hour Spark run passed, the same production UI image remained running. The browser again showed both frame-matched camera previews, the image occupancy polygon and active event, and an explicitly uncalibrated map. Both camera DOM gates were `exact-processed-frame`, aligned, with identical image/observation nanoseconds and one canvas/no raw video. The browser console error log was empty. The normal viewport was 1920×1080 with a 1920-pixel document width; no temporary viewport override was added. `ui-final-endurance-desktop.jpg` is the new actual post-test screenshot. The [summary](medium-final-all-ui-summary.json) records these checks, screenshot hash and actual deployed artifact identities. This does not add final-city calibration, fused IDs, VLM factual accuracy or Thor qualification.
