# Smart City implementation progress

**Current goal — October 26 intersection rebuild:** the derived `pedestrian-pocket-v3/smart_city_expo_pedestrian.usda` and two 960×540 native cameras now run native image `4e6b73d1…`, profile `cadd8867…` and isolated UI package `20261026T102610382036Z` / image `1d94d035…`. Calibration remains `isaac-live-045c84fe5fda7a15`, with eight pins, **19 rules at revision 450** and mobility revision 6. The explicit native SEI clock carries exact encoded-AU wall-handoff proof before both trackers, through the gateway/proxy and into exact previews; browser/exposure timing is not thereby verified. The current server sample passed 29.9868 s at 9.403 handoffs/s each; separate 57.82 s browser counters rendered 9.011/9.132 FPS. All 11 latest pairs met 150 ms, and final dashboard pixels plus accessibility state showed one guarded shared person. One real Ask returned a five-second inspected clip that played to completion. A fresh native pedestrian episode passed 42.7099 s/restored; camera completion stayed 0→0 and pre-existing incomplete 3 stayed 3, with real detection gaps exceeding the unchanged 1 s bound. **Final health/artifact checks and handover passed. The booth prototype implementation is complete with these documented limits.** Earlier scenario passes,597 ms rejected cohort,intermediate failures and recorded-input soaks retain their original scope. [Current rates](qa/smart-city-2026-10-26/native-sei-final-native-performance.json), [browser](qa/smart-city-2026-10-26/native-sei-final-browser-performance.json), [paired map evidence](qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json), [goal ledger](smart-city-intersection-goal-2026-10-26.md).

**Historical — October 23 MV3DT demonstration increment:** Experimental shared person markers are connected through the native worker, gateway, exact-frame previews and UI. A pinned local profile selects the two current calibrated Isaac cameras; production promotion remains disabled. A real duplicate-SDK-ID frame caused a publisher failure in the first live check; the rebuilt demo worker now omits all ambiguous occurrences for that frame and reports counters, without invented identities or arbitrary winners. [Current demo/operator guide](smart-city-mv3dt-demo-map.md). Earlier unchanged-image statements are historical; the RF-DETR engine remains unchanged, while this native worker has been rebuilt.

**Historical increment (October 23):** Research-backed mobility analytics and their Insights UI are deployed through the isolated port-7782 dev profile. Both live cameras, calibrated regions and the existing detector are reused. [Operator guide](smart-city-mobility-2026-10-23.md). Long endurance and scene accuracy checks remain deferred. Earlier production-package statements below describe historical deployments.


**Historical October 23 direction:** long live qualification was deferred. The [fast source improvements](qa/smart-city-2026-10-23/source-only-fast-pass.md) describe their then-separate source snapshot. Do not read that checkpoint as the current image or deployment status.

Goal activated October 21, 2026, America/Toronto. Implementation is authorized in the existing `/home/sparkdev/vss` application.

**Historical checkpoint, October 23:** the two live Isaac intersection cameras feed isolated production UI package `20261023T155304362915Z` at port 7782. The shared development UI remains on port 7777. The improvement sprint's fresh combined live qualification is pending; earlier completed runs below apply only to their historical builds and inputs. See the [current sprint summary](qa/smart-city-2026-10-23/sprint-summary.md).

## Confirmed operating scope

- Primary implementation and runtime test device: this DGX Spark.
- Prepare a separate Thor / Anvil-T5 deployment profile. Actual Thor runtime qualification requires access to that device.
- Spark is dedicated to this work overnight. Schedule required service restarts and GPU tests within the existing guard and saved 20 GiB reserve.
- The original input plan used recorded traffic video and labelled deterministic fixtures. The current demonstration uses the two actual Isaac intersection streams; recorded and synthetic evidence remain separate.
- Reuse the approved CT AI Labs UI concepts in the Isaac workspace's `outputs/smart-city-vss-branded/2026-10-21/` directory.
- Build the selected detection/tracking/reasoning pipeline first; compare relevant detector alternatives after the integrated path works. The research shortlist does not require installing every alternative simultaneously.
- Preserve current warehouse/general VSS workflows and unrelated working-tree edits.

## Original starting points — October 21, historical

- Research: [architecture](smart-city-integration-research.md), [contracts](smart-city-data-contracts.md), [implementation plan](smart-city-implementation-plan.md).
- Static city calibration: `/home/sparkdev/isaac_city_sim/config/camera_calibration.json`, with four camera entries and image/intrinsic/extrinsic/homography data. Unverified against final scene/camera placement.
- Offline road/calibration examples: `deploy/docker/developer-profiles/dev-profile-thor-smartcity/assets/`.
- Current local clips are mainly conveyor evidence; representative traffic video still needs staging.
- Read-only preflight found approximately 101 GiB disk free and 46 GiB available memory. Use scoped image/model staging rather than the full initial installation path, which requires 200 GiB.
- RF-DETR is not currently cached. Existing Cosmos and other inference caches are retained.
- No configured current Thor remote access was identified. Do not infer it from historical receipts.

## Work tracking

| Work | Status |
| --- | --- |
| Research and current VSS audit | Complete |
| Goal and user scope alignment | Complete |
| Site/observation/rule contracts and fixtures | Implemented and reviewed; current 30-loop receipt passes all seven families, durable history and geometry/preview context |
| RF-DETR export, parser and DeepStream worker | Small/Medium hashes pinned; actual FP16 corpus and serial engine timing passed; native decoder/tracker/analytics and corrected pacing tested |
| Live metadata transport and map projection | HTTP ingestion, SSE, calibrated projection and durable frame history implemented. Two live Isaac views use static road/person-plane calibration. First native NvDCF IDs remain local authority; second native MV3DT hints support guarded experimental person display. Vehicle and metric identities remain camera-local |
| Smart City UI and editable rules | Port 7782 serves package `20261026T102610382036Z`, image `1d94d035…`; ten build tasks passed 2 m 4.333 s. Native proof survives JSON/exact-preview proxy; actual browser counters show both aligned views and an accessibility state reported one joined person. Final health checks passed; bounded booth acceptance is complete with the documented limits |
| Existing VSS evidence/Ask/report integration | Bounded October 26 indexing, scoped search, retained-clip playback and a separate five-second Ask passed their actual checks. Prose accuracy, sustained visitor load and final combined qualification remain separate |
| Recorded-video and bounded runtime validation | Historical October 22 replay/outage/paired-preview/Ask checks and two-hour endurance passed for their recorded inputs and packages. These are not v3 scene qualification |
| Thor deployment preparation | Separate render, actual-device/engine guards and BSP requirements implemented; no target runtime claim |
| Current Isaac city camera/map/event validation | v3 scene/startup and earlier bounded scenarios retain their receipts. Current native-SEI sample validates 22 exact envelopes,11 of 11 latest pairs within 150 ms and bounded browser/map display. The new native pedestrian pass lacks qualified camera completion under the original gap bound; final health passed and bounded booth acceptance is complete with those limits. Guarded hints are not promoted global fusion |

Final-scene accuracy, fused cross-camera identity, full booth-day stability and Thor runtime remain separate qualification work. Do not report simulated fixtures as live camera analytics or claim target-device qualification from source-only configuration.

The entries below preserve dated checkpoints. Earlier pending statements and temporary service states describe that checkpoint; the table above and latest entries supersede them. See the [as-built status](smart-city-as-built.md) for current qualification.

## October 26 rebuild evidence — historical checkpoints below

- The deployed [two-stage native tracker](smart-city-tracker-stages-2026-10-26.md) preserves first-stage camera-local IDs even when the second SDK target ID changes. Optional person-map hints require exact current-frame provenance and the existing class, time, visibility, calibration and position guards. No global vehicle or site-count qualification is claimed. The earlier continuity-only switch trial is retained as a separate experiment.
- Earlier v2 [normal-flow recovery](qa/smart-city-2026-10-26/normal-flow-live-acceptance.json) ran for 180.17 wall seconds and 67.70 simulation seconds. Two new WALK-gated admissions and one crossing already active at capture start reached far-side continuation; two native curb reapproaches completed. All eight walkers recorded zero new failures, rejects or timeouts. This is a bounded choreography observation, not an AI crossing score, real-time speed result or whole-cycle fairness proof.
- [Actual worker clock proof](qa/smart-city-2026-10-26/source-clock-actual-worker-proof.json) retained 634 frames, 317 per camera. All four reference stages were present, with SDK NTP within 3.555 microseconds absolute of the same-buffer RTCP reference. The diagnostic restart had already removed the persistent output offset before mux changes. This does not establish the earlier 450 ms cause, physical exposure synchronization or browser latency.
- The earlier v2 northbound queue scene control completed in 51.93 wall seconds. Its live camera measurements reached two stopped objects and estimated queue extent 10.98 metres, with the measurement boundary reached. The owned stop was released; the queue remained under the normal red at that control endpoint. The [active image](qa/smart-city-2026-10-26/queue-final-active.jpg) and [scene/UI trace](/home/sparkdev/isaac_city_sim/logs/vss-integration/rebuild-20261026/scenario-queue-final-early-ui.ndjson) establish queue formation, not AI clearance. Later discharge must be observed separately.
- A separate PTS-sync startup trial failed and its immediate rollback used diagnostics enabled with mux synchronization disabled. Preserve the [failure/rollback receipt](qa/smart-city-2026-10-26/source-clock-pts-sync-failure.json). The later current profile disables temporary source-clock diagnostics and keeps sync/latency/NTP window at off/0/0. The 317-frame-per-camera reference check and approximately 12.1 FPS server / 11.20–11.06 FPS browser samples belong to the earlier v2 configuration. They do not qualify v3 physical exposure timing, latency, reconnect robustness or performance.

## October 22 implementation evidence

- RF-DETR Small checkpoint SHA256: `d81979a9213a2109345158ce9232668df4c1ae52e9b8db3f2ec0a8cbad959b33`.
- Export: `rfdetr==1.11.2`, opset 17, FP32 input/output, dynamic batches one/two. Actual traffic positive control found road users; reference-to-ONNX maximum absolute error approximately `3.4e-4` for the tested frame. This is export parity, not dataset accuracy.
- DeepStream base: `ghcr.io/nvidia/deepstream:9.2-triton-sbsa-dgx-spark@sha256:87014f626496737dc888eb80d5de9baf5a37c834033cabfbbcc50139c7183251`. The vendor entrypoint enabled CUDA forward compatibility for the existing 580.142 kernel driver; no host driver change was needed.
- Native controls: production CUDA preprocessing, sparse class parsing, 30-frame positive control, two-source geometry, empty-video control and native rule reloads passed. Latest robustness code must still be included in the final built image and end-to-end retest.
- The first unpaced HTTP replay exhausted the bounded producer queue. The worker was corrected to apply lossless backpressure for unpaced files; a slow-consumer test delivered all 30 frames in order with a four-frame queue. Live/paced overload remains a visible failure rather than silent frame loss.
- Camera-local identity remains explicit. MV3DT supports per-class geometry and is not restricted to humans. An optional strict preparation utility was implemented; actual fusion is disabled until overlapping synchronized footage and suitable calibration/geometry pass evaluation.
- Public test recordings: NVIDIA's bundled DeepStream `sample_1080p_h264.mp4` (1080p30, 48.1 s, moving camera), and OpenCV's `vtest.avi` converted to H.264 MP4 (768×576, 10 FPS, 79.5 s). These are independent recordings, not two views of one site.
- VIOS registration completed through its existing media-only upload API; no embedding or detector postprocessing was triggered by upload. Actual VSS sensor IDs are stored in private `.spark/city/vss-media-registration.json`.
- Synthetic geometry fixtures remain a separate explicit mode; no real traffic video is attached to synthetic observations. Changing sites must isolate fixture and recorded event histories; a regression test was added after finding and fixing contamination.
- Runtime launch/guard integration and the host controller are implemented in `tools/smart-city/`; real Agent source lifecycle and capacity checks passed. The saved reserve remains 20 GiB.

Services and inference may be restarted during this authorized dedicated run. Existing model caches, configuration and memory reserves are retained. The goal remains active; this log is not a completion receipt.

## Historical October 22 integration findings

- Complete real two-file replay delivered all 2,238 frames, with durable exact-frame history and 26,510 tracked observations. Its initial double pacing was fixed; the bounded mixed-rate test measured 30.03 / 9.99 FPS.
- Small and Medium passed actual 100-image FP16 corpus evaluation at batches one and two. Batch-two AP was 55.884 / 57.803 on the fixed six-road-class subset. This is a proxy, not full COCO or final-city accuracy.
- Actual Agent source lifecycle, duplicate/absent operations, two-source capacity and unrelated-profile preservation passed. Controller rule archives preserve temporarily absent camera configuration.
- A UI source/mode race triggered two full file exports and exhausted the VIOS CPU memory cgroup. The no-export live guard and bounded static-site refresh fix have regression coverage; no resource limit was increased.
- Actual two-source RTSP integration exposed repeated pedestrian frame timestamps through VIOS. A preserved-original, manifest-verified single-slice low-latency derivative removed duplicates in the CPU original/proxy comparison. The combined native path is being rechecked before endurance qualification.
- The UI passed 11 suites / 67 tests and TypeScript. Actual recorded playback, zones, event review and responsive layout were browser-tested. Live WebRTC frame-clock inspection remains pending because the browser tool currently has no connected surface; no live clock verification flag was enabled.
- Goal remains active. Current receipts are under `docs/qa/smart-city-2026-10-22/`; prototype implementation is not a final-city or Thor booth qualification.

## Historical October 22 mixed-rate live timing investigation

The original 40,000 microsecond mux batch wait allowed the 30 FPS traffic timeline to fall behind the 10 FPS pedestrian timeline. A reversible VIOS 2-to-4 CPU experiment did not improve this; its original 2 CPUs / 2 GiB limits were restored. The worker now exposes a strictly bounded `--mux-timeout-us` option (1,000–1,000,000; native default remains 40,000). The Spark controller is testing 10,000 with all model and VIOS limits unchanged. Early source-clock progress is near one second per wall second; a passing bounded receipt and endurance test are still required. These are reported RTCP source clocks, not browser capture-to-screen latency.

## Historical October 22 bounded qualification receipts

- [Small: 10 ms mux, 300 seconds](qa/smart-city-2026-10-22/mux-10000-small-300s.json): two actual Agent RTSP sources, source clocks close to wall time, highest reported RTCP source age 0.441 seconds, minimum available memory 22.695 GiB.
- [Small: real Ask](qa/smart-city-2026-10-22/small-two-source-real-ask.json): one actual UI API answer in 14.77 seconds while both native sources ran. Its matching five-second evidence clip was decoded and sampled manually. The 90-second concurrent monitor passed, with a 22.011 GiB memory minimum. The answer was broadly consistent but omitted a bus; this does not establish event or count accuracy.
- [Medium: native pipeline, 300 seconds](qa/smart-city-2026-10-22/medium-native-300s.json): actual selected 576-pixel FP16 engine, source clocks close to wall time, highest reported source age 0.404 seconds, minimum available memory 21.783 GiB. Medium is the preferred candidate; combined Ask and long endurance tests remain pending.
- [Thirty synthetic rule loops](qa/smart-city-2026-10-22/synthetic-30-loop-rules-transition-history.json): 6,060 synthetic frames and 330 events across all seven rule families. Both durable report formats retained 330 rows after closing and reopening SQLite. These tests qualify geometry and rules, not detector accuracy.
- [MV3DT decision](smart-city-mv3dt-decision.md): documented Spark support and a staged overlapping-camera candidate. Current independent recordings cannot qualify fusion. No local MV3DT speed or cross-camera accuracy has been measured.

The largest VIOS memory jump occurred during a new five-second software-transcoded evidence export. Its allocations remained in RSS after completion; unreachable memory leakage versus allocator retention has not been established. Repeated uncached exports and a fresh final-runtime endurance test are still required.

At this October 22 checkpoint, both sources were temporarily paused and the existing Spark LLM was temporarily stopped for bounded CPU-only UI packaging. The required service restoration was part of the subsequent recorded-input qualification. This is not the current service state. The saved 20 GiB reserve, its guard, and the VIOS limits of two CPUs / 2 GiB remained unchanged.

## Production packaging and final review

The shared video preview now tears down failed sessions, received tracks and frame callbacks. A bounded late-answer drain and handoff delay prevent fast Retry from overlapping an old pending allocation. The UI passed 75 scoped tests and TypeScript; packaging controls passed separately.

The first two production dependency-install attempts failed before compilation because HTTPS requests to the npm registry were reset. The host also failed a direct verified HTTPS request, so this is not resolved by changing Docker networking. No TLS verification or lockfile checks were disabled. An explicit offline reuse path is being prepared for the installed, tested dependency tree, with lockfile checks and separate dependency hashes.

The final integration review corrected stopped-worker recovery, revoked-calibration archives, queue counts, rule invalidation history, reset retry deduplication and calibration-bound rule activation. Historical events now retain a bounded source-clock transition history so a transient unknown interval remains unknown after recovery. Current gateway tests passed; final CPU rule-loop receipts are being regenerated against the corrected source.

## Production candidate deployed

The offline dependency reuse build passed all ten tasks and produced image `sha256:55467243f9e783f82d00976bc86a4aea35c236387496c9d8d588b10580741171`. The source snapshot is `81028ddb5617ed2e19dd15dfb6768afa6b13b2737cfafe497f2df87436d0cb33`; private build receipts preserve dependency, lockfile and artifact hashes. Only the UI was recreated, with the original image retained for rollback. Production startup and HTTP page/runtime/city API checks passed. Initial idle UI memory was about 140 MiB, versus roughly 1.8 GiB for the development server.

The Spark LLM has been restored and is healthy. VIOS was recreated with the candidate process-local `MALLOC_ARENA_MAX=2`, retaining the same image and original two-CPU / 2 GiB limits. Neither repeated exports nor endurance has passed yet. The browser surface has returned, allowing final rendered UI and live timing checks. The duplicate earlier temporary QA tab was closed; current preview concurrency differs from the earlier four-peer investigation, so later memory improvements cannot all be attributed to the allocator setting.

## Exact live preview and repeated questions

The browser now plays both actual live RTSP replay views. Its video-frame callback exposes an RTP timestamp but no absolute capture time, so the existing guard correctly leaves live detection boxes hidden. A native post-inference JPEG branch and exact source/session/sequence/time metadata envelope are being added. Their bounded display queues may drop preview frames; they must not drop or retime observations. Source inference remains 30 / 10 FPS. Browser clock verification remains false.

Three sequential real Medium questions passed in 29.6, 23.9 and 24.5 seconds, each with a separately fetched five-second MP4 evidence window. An evidence-only repeat of the first window returned the same URI and byte hash. The runner made exactly three Ask requests; the earlier 64-KiB readiness cap failed before any Ask and was corrected to a bounded 1-MiB snapshot cap, with all ten offline controls passing. The concurrent ten-minute clock/memory monitor is still completing. This is operational delivery evidence, not a semantic accuracy score or proof of internal cache behavior.

The [ten-minute concurrent monitor](qa/smart-city-2026-10-22/medium-three-ask-600s.json) passed through 06:38 UTC. It observed 17,859 traffic and 5,953 pedestrian frames with no sequence gaps or clock rollbacks, at least 24.174 GiB available and no service OOM/restart. Peak VIOS cgroup usage was 1,068.6 MiB under the original 2 GiB limit. Bounded CPU compilation/tests overlapped late monitoring; preview concurrency and the UI also differ from the earlier allocator investigation, so this does not isolate the allocator change. Both analysis sources are now paused through their canonical Agent controls; the empty controller inventory was confirmed before new preview activation.


## Final paired-preview and five-second Ask qualification, 07:35 UTC

The final native worker passed the strict [480-frame paired-preview/outage check](qa/smart-city-2026-10-22/preview-native-480-outage.json): 136 exact JPEG/observation pairs, real detections from both original geometries, and 239 metadata frames after closing the display consumer. The [five-minute paired-preview runtime](qa/smart-city-2026-10-22/medium-paired-preview-300s.json) also passed through the production UI binary route with at least 24.572 GiB available. These are identity and operational checks, not final-city clock or detector-accuracy claims.

A separate [actual five-second semantic control](qa/smart-city-2026-10-22/medium-paired-five-second-semantic.json) returned in 9.37 seconds. The matching 150-frame clip agreed broadly with the described pedestrian/vehicle motion; the answer missed a fourth pedestrian appearing near the end. The prior one-frame answer was wrong and remains an unresolved, separately scoped decoder/model-path investigation.

The City UI now explicitly requests five seconds for live questions and pins each answer to its actual source and returned observation interval. Evidence exports occur only after an explicit button click. Its 119 scoped tests, TypeScript and independent review pass; actual rendered controls still require the new immutable production package. Both sources are temporarily paused for that CPU build. All normal model services remain loaded, the saved 20-GiB guard remains active, and temporary benchmark containers have been stopped. The final combined two-hour run has not started.


## Final UI deployed and endurance started

Production image `sha256:1b2db6c3e4e800c1f734ef696af75e68f63f73d06040ad18383231b74b284c8f` from the immutable `20261022T073106035307Z` package is running. All ten build tasks and actual root/site/health checks passed. Both camera panes displayed exact image/observation nanosecond matches; the real image ROI and occupancy event were visible. Desktop/mobile layouts had no horizontal overflow, the temporary viewport was reset and no browser console errors were observed.

The new Ask returned the correct source and a five-second observed interval. Explicit clip loading produced a playable/downloadable 1080p MP4 (5.1128 seconds/151 frames after export rounding). Changing the next camera cleared the loaded clip without rewriting the completed answer’s provenance. Manual review found a posture error and unreliable fine vehicle descriptions; this is an operational UI pass, not semantic accuracy qualification. See [final UI](qa/smart-city-2026-10-22/ui-final-production.json) and [answer evidence](qa/smart-city-2026-10-22/medium-final-ui-ask-evidence.json).

A 7,200-second monitor is running against the final deployed configuration with both RTSP sources, required exact processed previews and one real five-second question every 900 seconds. Private run: `.spark/city/runtime/medium-final-paired-ui-7200s-20261022T0743Z`. It has not yet passed; do not treat launch as completion.


### Endurance monitor coverage correction

The first final-UI monitor was deliberately interrupted after 372 seconds because its default container set omitted `vss-agent-ui`. Its receipt remains a failed/interrupted attempt; both explicit source-scoped pause requests completed. It is not a two-hour pass. No source, model, UI artifact or guard was changed.

The corrected 7,200-second run is `.spark/city/runtime/medium-final-all-ui-7200s-20261022T0749Z`, reading the new worker epoch `observations-20261022T074930Z.ndjson`. It explicitly adds `--container vss-agent-ui` to the default required set, retaining exact preview checks and 900-second real questions. The operator recovery section now records the 10-ms mux file, allocator-only VIOS overlay and exact production UI image/package. Full endurance remains pending until this run ends.


### Scheduled completion handoff

The thread heartbeat `finish-smart-city-vss-overnight` is active every 15 minutes to inspect the existing final-all-UI monitor, repair actual failures within the authorized scope, and finish receipts/documentation and goal completion only after qualification succeeds. It must pause itself after completion and must never launch duplicate monitors or competing GPU work. Current final-all-UI monitor PID at handoff: `1216547`; verify process identity before relying on that value. Its unified-exec session is `40662`. A temporary `systemd-inhibit` sleep/idle block follows that PID and exits with it or after 7,800 seconds; session `73622`. The host/app must remain running for local scheduled work.

At handoff, the corrected run had passed its first five minutes, with fresh exact previews and no failures; full two-hour qualification and scheduled model calls remained pending. No completion claim is made. The model/UI/native artifacts were left running, original caches/logs retained, and all final UI screenshots/operational receipts saved.


### 08:10 UTC scheduled check

The original corrected monitor process is still running, approximately 21 minutes into its requested two hours. Both processed previews are fresh and both source clocks advance at wall rate. Its first scheduled five-second question completed in 17.93 seconds with returned evidence metadata. Available memory has remained at least 23.809 GiB. All eight monitored containers, including the UI, report zero restarts and zero cgroup OOM events. This is interim operational evidence; full endurance and later scheduled questions remain pending. No services, models, sources or runtime limits were changed.


### 08:25 UTC scheduled check

The same corrected monitor remains healthy approximately 35.5 minutes into its two-hour request. Both exact processed previews are fresh, source clocks remain near wall rate, and all eight monitored containers retain zero restarts/OOM events. Two scheduled five-second questions have completed, in 17.93 and 14.93 seconds, with returned observation windows/evidence metadata. Minimum available memory is 23.791 GiB. No runtime, model, source or limit changes were made. Full endurance remains pending. The operator recovery section has been renumbered 13 and its controller/profile restoration order is being clarified without touching the running deployment.


### 08:40 UTC scheduled check

The same corrected monitor remains healthy approximately 50.5 minutes into its two-hour request. Three scheduled five-second questions have completed in 17.93, 14.93 and 23.81 seconds with returned observation windows/evidence metadata. Both exact processed previews remain fresh, source clocks stay near wall rate, and all eight monitored containers retain zero restarts and zero cgroup OOM events. Minimum available memory is 23.744 GiB; the current VIOS cgroup is approximately 1,323 MiB under its unchanged 2-GiB ceiling. The operator recovery-order clarification is complete. No running service, model, source or runtime limit was changed. Full endurance remains pending.


### 08:55 UTC scheduled check

The original corrected monitor is approximately 65.5 minutes into its two-hour request and remains healthy. Four scheduled five-second questions have completed (17.93, 14.93, 23.81 and 7.75 seconds), each returning observation-window and evidence metadata. Both exact processed previews remain fresh and source clocks advance near wall rate. All eight monitored containers retain zero restarts and zero cgroup OOM events. Minimum available memory remains 23.744 GiB; current VIOS usage is approximately 1,321 MiB under its unchanged 2-GiB ceiling. No runtime changes or additional model calls were made. Full endurance remains pending.


### 09:10 UTC scheduled check

The same corrected monitor remains healthy approximately 80.5 minutes into its two-hour request. Five scheduled five-second questions have completed; the fifth took 18.84 seconds and returned observation-window/evidence metadata. Both exact processed previews remain fresh, source clocks advance near wall rate, and all eight monitored containers retain zero restarts/OOM events. Minimum available memory is 23.602 GiB; current VIOS usage is approximately 1,366 MiB under its unchanged 2-GiB ceiling. No runtime changes or extra model calls were made. Full endurance remains pending.


### 09:25 UTC scheduled check

The same corrected monitor remains healthy approximately 95.5 minutes into its two-hour request. Six scheduled five-second questions have completed; the sixth took 9.96 seconds and returned observation-window/evidence metadata. Both exact processed previews remain fresh, source clocks remain near wall rate, and all eight monitored containers retain zero restarts/OOM events. Minimum available memory is 23.457 GiB; current VIOS usage is approximately 1,370 MiB under its unchanged 2-GiB ceiling. No runtime changes or extra model calls were made. Full endurance remains pending.


### 09:40 UTC scheduled check

The same corrected monitor remains healthy approximately 110.5 minutes into its two-hour request. All seven scheduled five-second questions have completed (7.75–24.33 seconds); the last returned observation-window/evidence metadata in 24.33 seconds. Both exact processed previews remain fresh, source clocks advance near wall rate, and all eight monitored containers retain zero restarts/OOM events. Minimum available memory is 23.168 GiB; current VIOS usage is approximately 1,419 MiB under its unchanged 2-GiB ceiling. The qualified question cadence is one per 900 seconds; this does not establish sustained visitor-rate questions or a full booth day. No runtime changes or extra model calls were made. Full endurance remains pending until the final receipt is written.


## Completed Spark implementation and final qualification

The corrected final-all-UI monitor passed its complete 7,200-second request, from 07:49:48 to 09:49:48 UTC. The [sanitized final receipt](qa/smart-city-2026-10-22/medium-final-all-ui-7200s.json) and [independently aggregated summary](qa/smart-city-2026-10-22/medium-final-all-ui-summary.json) are saved. Both the sample-file SHA256 and frozen monitor-source SHA256 were verified before summarizing.

Across 1,359 samples, the monitor observed 215,896 traffic and 71,966 pedestrian frames (287,862 total), no sequence gaps, backward source timestamps, clock rollbacks or session changes, and 1,359 valid exact image/observation-envelope reads per source. Seven sequential five-second questions at a 900-second cadence completed in 7.75–24.33 seconds with returned observation windows/evidence metadata. All eight required containers, including the production UI, kept the same identity/limits and recorded zero restarts and zero OOM events. Available memory remained at least 22.875 GiB against the saved 20-GiB reserve.

VIOS cgroup memory rose from 1,322.355 to 1,423.887 MiB during this run, peaking at 1,428.477 MiB under its unchanged 2-GiB limit. This is observed retention/growth; the run does not establish an unreachable leak, a day-long plateau or allocator causality. The sparse question cadence does not qualify sustained visitor-rate or concurrent questions, nor a full booth day. VLM prose still needs review and does not supply authoritative counts or rule events.

Post-run HTTP root/site/health returned 200. The running production UI, native image, actual native worker and selected Medium engine identities were checked against their receipts. The browser again displayed both exact-frame overlays, the real occupancy polygon/event and the explicit missing-calibration map state, with no console errors. A new actual screenshot is saved as `ui-final-endurance-desktop.jpg`; the temporary viewport override had already been reset. No extra model questions or runtime restarts were needed. The monitor ended and its process-bound sleep inhibitor released.

The implemented Spark version is complete within the user-approved recorded-video and labelled-fixture scope. Final Isaac camera calibration/event accuracy, active MV3DT fusion/native adapter and Thor runtime remain separate documented handoffs. Original media, model caches, prior failed/interrupted receipts and unrelated edits are preserved. The application remains running at `http://127.0.0.1:7777/?workspace=smart-city`. The overnight supervision heartbeat will be paused after final documentation review and goal completion.


### Final handoff closed

The sanitized receipt/summary passed independent read-only review. Post-run gateway source hashes match the tested implementation, all saved QA JSON parses, and final whitespace checks pass. The `finish-smart-city-vss-overnight` heartbeat has been paused after successful qualification. No additional source/model/build tasks remain in the agreed recorded-video-first Spark scope. The implementation is left running; final-city, fusion and Thor handoffs retain their stated limits.


## User-requested code audit and UI polish

The user requested further bug fixes, efficiency improvements and visual refinement after completion of the overnight scope. The [backend/native review](qa/smart-city-2026-10-22/polish-code-review.md) and [UI review](qa/smart-city-2026-10-22/polish-ui-review.md) document the resulting fixes and regressions. The native build passed its six CPU helper executables and the new 480-observation GPU preview/outage check. UI validation passed 152 tests across 20 suites, TypeScript and the immutable package's ten build tasks. The independent Python review passed 163 tests plus four subtests; the separate full soak group passed 46 controls. These counts overlap where noted in their receipts and should not be summed as unique coverage.

The candidate package is `.spark/smart-city-ui/20261022T141159952818Z`, image `sha256:066c450ffe1a5f557dc306cd835bd4237ae351334291dca9acc80666195e8fce`. The rebuilt native image is `sha256:403f58f44856eafe5ce6d1a42308203ed4d923bab91cf7a073aceb3a6a2a868e`, with worker SHA256 `bf807609fbf3412b6c96c1614822eac5fd3c7ecda86e56b6ffa89b432c6544c9`. The selected Medium engine is unchanged. Gateway/controller code was restarted with both sources paused, then the two registered sources resumed sequentially. Twelve rapid same-semantics rule updates reached the newest active revision within 0.7 seconds and left one current temporary INI. Managed live observations now append to the bounded manifest-backed `live-observations.ndjson` family.

The first 1,200-second combined run stopped after 214.06 seconds with `container-not-healthy:vss-agent-ui` when the parallel, user-authorized Defense implementation recreated that container into source mode at 14:26 UTC. Its failed receipt and successful source-scoped pauses are preserved. This was a deployment collision, not a passing run or an inferred detector/model failure. The user explicitly authorized messaging the Defense task; coordination messages were sent and its source edits/runtime were preserved.

The frozen Smart City UI now runs in a separate two-GiB/two-CPU `vss-city-polish-ui` container on loopback 7781, with the existing HAProxy template in `vss-city-polish-ingress` on loopback 7782. The latter provides the complete UI/media/inventory routes. This adds no duplicate detector or model. The shared development UI remains on 7777. The new combined monitor began at 14:31:14 UTC in `.spark/city/runtime/polish-isolated-ui-1200s-20261022T1431Z`, explicitly checking both isolated UI/ingress containers plus the seven default pipeline services. It retains the original clock, memory, exact-preview and failure gates, and schedules one real question at 900 seconds. No duplicate monitor is running.

An additional manual browser question during the isolated run returned the real traffic source and a five-second observation interval. Explicit clip loading produced a ready, error-free 1920×1080 video of 5.1472 seconds after export rounding; changing the next camera cleared the clip without changing the answer's provenance. The answer was checked for operation/layout, not semantic correctness. Desktop 1920×1080, laptop 1366×900 and mobile 390×844 layouts had no document horizontal overflow. Rendered evidence is in [the production UI receipt](qa/smart-city-2026-10-22/polish-ui-production.json).

The isolated run passed its full 1,200.0003 seconds with 232 samples and 47,848 observations. Both previews remained matched; no sequence gaps, clock rollbacks, source changes, container restarts or OOM events occurred. The scheduled five-second Ask completed in 12.02 seconds. Minimum available memory was 25.855 GiB. The [sanitized receipt](qa/smart-city-2026-10-22/polish-isolated-ui-1200s.json) and [independently aggregated summary](qa/smart-city-2026-10-22/polish-runtime-summary.json) were saved after checking source/sample hashes and deployed identities. This pass belongs to the 14:11 UI package.

Before handoff, host-level checks found Firefox image/shared memory growing outside the monitored service containers. The user confirmed the demo was open there and then closed that tab; its large shared allocation disappeared and available memory rose from approximately 26 to 39 GiB. Two focused tests reproduced an existing cleanup gap for decoded bitmaps skipped by batched React commits or unmounts. That gap and repeated same-size canvas allocations are now fixed. Independent review covered pending/committed ownership, generation changes, delayed decodes, StrictMode and presentation lifetime. The Firefox correlation is not proof that these defects explain all observed memory growth.

### Final browser cleanup and qualification

Package `20261022T150135382138Z`, image `sha256:dbf42268586b4979015a0ba15f2fc81cb41aec27a350c4b93785a9cfa3254a04`, passed all ten build tasks in 119.543 seconds. All 158 UI tests across 21 suites and TypeScript passed; the 22 focused lifecycle tests overlap this selection. All 35 compared Smart City source/test files match the snapshot. Only the isolated UI was recreated; shared development and Defense work were preserved.

The first new-package monitor was terminated after 130.08 seconds. Its signal sender is unknown; the failed receipt and both completed source-pause receipts are preserved. Cosmos had separately been stopped/restored for the user's authorized Photon experiment. After readiness checks and sequential source resumption, a fresh monitor ran as a bounded user service beside a bounded OS memory sampler. Both units completed and are now inactive.

The [final twenty-minute run](qa/smart-city-2026-10-22/polish-bitmap-managed-1200s.json) passed from 15:12:57 to 15:32:57 UTC, with 232 samples, 47,916 observations and one actual live-log rotation. There were no sequence gaps, clock rollbacks, source changes, restarts or OOM events. Both sources supplied 232 valid exact preview reads. One real five-second question returned in 13.60 seconds; minimum available memory was 40.170 GiB. The [verified summary](qa/smart-city-2026-10-22/polish-bitmap-runtime-summary.json) pins all nine monitored containers and the native binary.

After completion, monitor Docker readiness was strengthened to reject paused/nonrunning status, unknown health values and `starting` beyond its existing warmup. Production checks passed 50 tests and 68 subtests. An [offline differential replay](qa/smart-city-2026-10-22/polish-container-health-replay.json) passed all 232 original samples under the stronger gates while proving the remaining evaluation/preview code unchanged. Original source, candidate, CLI and audit are retained in the private run directory. No images were reconstructed, no questions repeated and no thresholds weakened.

The [final UI receipt](qa/smart-city-2026-10-22/polish-bitmap-ui.json) records desktop 1920×1080, mobile 390×844, Presentation Mode, Reports and both exact overlays, with no observed console warnings/errors. Full-page captures passed independent visual review. The viewport override was reset and the tested tab retained. [OS memory samples](qa/smart-city-2026-10-22/polish-browser-memory.json) cover one in-app renderer over 1,200 seconds; PSS ranged from approximately 1,376 to 1,833 MiB. Firefox was absent, so its specific long-run behavior remains unverified. JSON report download also remains unverified through browser automation. The tested UI remains at `http://127.0.0.1:7782/?workspace=smart-city`, with shared source development at 7777 and the saved 20-GiB reserve/guard intact.


## 2026-10-23: actual Isaac intersection integration

The user requested a new goal for the existing city, with a maximum of two cameras and no subagents. The main agent performed the work in `/home/sparkdev/isaac_city_sim` and this VSS checkout. The prepared launcher now loads the original mesh city, creates only southwest/northeast camera products, sends real 1280×720 software H.264 RTSP through VIOS, and starts the unchanged Medium/NvDCF production worker. Static geometry supplies calibration, an actor-free overhead map and six image-space rules. Separate person navigation-height homographies correct the road-height assumption. The UI is package `20261023T045540479675Z`, image `sha256:3134f445308c4ccf95d4b28b01b4b9b8e0a1f120957900c17b6f1f1c27d60f8e`, deployed only on the isolated 7782 path. Shared source/Defense work and original media remain preserved.

Native 9.2 MV3DT diagnostics completed two 2,200-observation runs. Both failed the position/identity promotion gates; a separate ground-association candidate also failed. They remain diagnostic tools. The map uses calibrated per-camera detections and does not claim fused IDs or unique cross-camera counts. The final profile captures no simulator actor labels. The held-out evaluator and its raw traces remain separate.

The first final-run attempt exposed southwest recording off after reconnect even though decoding/inference were live. That diagnostic monitor was deliberately interrupted after approximately three minutes and is not a pass. A source-scoped recording stop/start recovered the recorder without deleting evidence. The launcher now requires actual recent five-second footage from both views, and the companion qualification checks recording readiness continuously. Both cameras subsequently answered real UI questions; both inspected clips loaded at 1280×720. Full event clip attachment remains unimplemented and is labelled unavailable.

CPU validation passed 108 selected backend/controller/calibration/diagnostic tests, then the two new launcher tests and affected controller/site selection passed 37 tests (overlapping selection). Six static-map UI tests, the main app TypeScript check, ten frozen build tasks, six city-profile tests and eight native conversion tests passed. The bounded Kit native-policy check passed all six safety checks. The fresh final qualification passed its full 600.11-second pipeline run and 600.00-second simulator companion: 10,304 observations, 115 exact preview reads per camera, minimum 24.701 GiB available, and minimum rolling camera delivery 7.775 FPS. No source/session/sequence failures, container restarts or OOM events were observed. Both recent recording windows remained ready; the two manual UI questions and their actual clips occurred inside the monitored interval. Simulation advanced 234 seconds during the sampled period (about 0.39× wall rate). The demo remains running. See [the operator guide](smart-city-isaac-integration.md) and [QA receipts](qa/smart-city-2026-10-23/).


## 2026-10-23: disconnected cameras and map layout repaired

The original 05:07–05:17 qualification was followed by a real VIOS SIGSEGV at 05:22:07, not an OOM. Its stream-error writers were synchronized but QoS iteration/clear was not. The fix moves an entire error batch under one mutex and reports a private copy. The original crash log is preserved. A four-thread regression checked 40,000 unique errors; the affected native library rebuilt in a CPU-only two-GiB container. The deployed detector now explicitly selects RTSP-over-TCP; its actual GStreamer source-property regression passed. The Medium engine remains unchanged. Prepared canonical image tags retain both fixes and prior tags remain available for rollback.

The isolated port-7782 UI now uses source-mounted hot reload with independent public/build directories; the shared port-7777 UI was not recreated. The browser VST endpoint now uses port 7782 on localhost. The preview distinguishes failed inventory retrieval from an absent registered source. Two stacked camera views now sit alongside a large, correctly proportioned map. Six map tests, eight camera tests, the new inventory error test, five launcher tests and the main app TypeScript check passed. The launcher can restore the existing stopped video container after guard/headroom checks.

The first dev compile caused the unchanged Isaac 23-GiB floor to stop that earlier process. Compilation finished before the fresh scene launch and qualification. The final [repair run](qa/smart-city-2026-10-23/camera-map-repair-summary.json) passed 600 seconds with 9,995 observations, 113 exact preview reads per camera and 101 independent simulator/recorder samples. Both recordings remained ready; all ten monitored containers had no restarts or OOM events. Minimum available memory was 23.073 GiB and minimum rolling camera delivery 7.819 FPS. Browser checks covered real overlays, selection, zoom, editor, reports and responsive/presentation views. No additional VLM request was made during this run. At that checkpoint, camera-local identity was explicit and MV3DT was disabled. That build was running; see [the operator guide](smart-city-isaac-integration.md) for test and recovery steps.


## 2026-10-23 improvement sprint — memory policy

At 15:05:08 UTC the previous simulator supervisor stopped Isaac at 22.995 GiB available, below its former 23 GiB floor. The failure receipt remains in the city logs. The user then explicitly disabled this Isaac-specific available-memory stop. `config/vss_runtime_policy.json` in the city repository now sets `isaacAvailableMemoryStopGiB` to null. Five CPU boundary checks passed. Telemetry still records memory; the 20 GiB VSS reserve/guard, Isaac 20 GiB process limit, startup admission and disk checks are separate and unchanged. New simulator monitor receipts will declare the disabled floor; older receipts retain their historical criteria.

## 2026-10-23 improvement sprint — frozen package, live qualification pending

The final isolated UI is package `20261023T155304362915Z`, image `sha256:9650f8d01d2ade21157bc5e1559c17aafa80007580759c8ae784ead60e55531a`; [its receipt](qa/smart-city-2026-10-23/sprint-final-ui-package.json) pins the source and artifact identities. It replaces the earlier source-mounted port-7782 repair UI while preserving shared development on port 7777. Camera/map colors, shared geometry labels, rule metrics, displayed-analysis health, preview scheduling and Ask cancellation/deadlines were improved. Unknown rule evidence now says **Not enough evidence**, without displaying retained counts as current.

Backend review corrected observation-gap, aggregate-continuity and expired-track uncertainty handling. Detector postprocessing now retains one supported city class per query, with its measured COCO proxy tradeoff and remaining false detections recorded in the [sprint summary](qa/smart-city-2026-10-23/sprint-summary.md). At that checkpoint, MV3DT was disabled and all operational IDs were camera-local.

A subsequent launch exposed an HTTP-200 partial resume after the northeast CPU decode probe failed. The failed run is preserved. The [startup repair](qa/smart-city-2026-10-23/sprint-startup-repair.json) validates source/profile identity and required service confirmations, rejects partial pause/resume, and bounds live OpenCV readiness retries inside one 20-second subprocess with TCP transport. A [follow-up startup-wait repair](qa/smart-city-2026-10-23/sprint-controller-startup-wait-repair.json) waits for the existing controller to serve and confirms its identity/capacity before mutating sources; its CPU receipt records 77 passing checks. The final source set and package require a fresh complete qualification. **That live qualification remains pending.** No historical pass or partial run substitutes for it.

## October 23 — research-backed mobility increment deployed

Added three northbound turning movements, one approach queue and a pedestrian waiting-to-crossing journey from the exported static scene. Existing stopped-crossing rules now provide windowed episode/duration summaries. All 12 rule primitives are active with two live exact-frame previews. The UI exposes 1/5/15-minute source-time windows, four topic views, map links, saved setup, three-click queue-axis drawing, and CSV/JSON exports.

Corrected stale-history handling, minimum queue membership, uncertainty from vehicles outside the queue region, shared-entry turn alternatives and camera projection of site-metre regions. [Deployment receipt](qa/smart-city-2026-10-23/mobility-deployed-summary.json) records source hashes and bounded checks. The JSON browser export was downloaded and parsed. The earlier production build remains a rollback; new UI changes are running through the existing dev profile without a build. Model images and original recordings remain unchanged. Final scene accuracy and long runtime testing remain deferred.

## October 23 — curb access and spatial recovery deployed

Added Curb access configuration/reporting, camera-local arrivals/departures, union observed occupied/stopped intervals, partial/incomplete visits and completed-visit dwell. Two live cameras now have 14 enabled primitives and two pedestrian corridor directions. Fixed one-frame loss churn, bounded historical queue membership, stale current-count availability and far-edge detection with offset approach geometry. Approach-time labels explicitly include walking; no signal-delay or stationary-wait claim.

[Current receipt](qa/smart-city-2026-10-23/curb-reliability-deployed-summary.json) pins final source/artifact identities, 227 CPU/API/launcher tests, 30 UI tests, TypeScript, rendered browser checks and a 6,500-frame real-inference metadata replay. The live curb report and downloaded CSV contain real observed visits. Long accuracy/endurance work stays deferred. During cutover the saved 20 GiB reserve was retained; only this task's UI process was stopped briefly to release dev cache for normal detector admission, then restored.


## October 23 — NVIDIA native RTSP cutover

Replaced both external CPU camera encoders with Isaac 6.1 native H.264 RTSP at unchanged 1280×720. The packet relay preserves VIOS URLs, source UUIDs, recordings and calibration. Corrected four-camera native assumptions, applied profile FPS, fixed video timestamps to real-time encoded-frame handoff, and retained simulation timestamps in SEI. A rejected no-reader push initially caused a failed startup; its receipt is preserved and the wrapper now counts rejections without treating them as success or killing the server. Real exceptions still latch. The conservative setup limit is four two-camera setups, preserving the historical eight presumed-session budget rather than claiming a GB10 hardware cap. No render-policy guard changed.

Default launcher starts now preserve map/rules/calibration/MV3DT and validate configured versus attached backend and saved geometry. Explicit calibration refresh is separate. Readiness accounts for both native-compiled and declared backend-only world rules. Native queue bounds are explicitly unavailable. All 22 city CPU checks and 99 VSS CPU checks passed, plus focused Ruff. The source-frozen simulator/recording monitor passed 60 seconds with minimum rolling native handoff rate 9.46 FPS per camera and minimum 20.816 GiB available. The integrated 60-second monitor passed 1,104 new observations and 12 exact-preview checks per camera with no clock/sequence failures or monitored container restarts/OOM events. Browser inspection showed both live analyzed views, zones and the map. Default Start confirmed already ready without geometry regeneration.

RF-DETR Medium, the native worker image and experimental MV3DT map profile remain unchanged. This is short operational validation, not a controlled speedup claim, absolute camera synchronization, MV3DT accuracy or booth-day endurance. A 960×540 trial remains separate. [Current transport/operator guide](smart-city-native-rtsp.md), [receipts](qa/smart-city-2026-10-23/native-rtsp/deployed.json).


## October 23 — two-camera FPS pass complete

Reduced the live cameras to 960×540 and explicitly migrated calibration/MV3DT matrices and the gateway allowlist. Both UUIDs, the map, all 14 rules and mobility configuration revision 3 are preserved. DeepStream now uses matching 960×540 mux surfaces instead of its omitted-argument 1080p default. RF-DETR Medium 576×576 and calibrated tracker 640×384 are unchanged. The GUI viewport uses a 0.5 scale, and pre-stream preparation now stops the unused gantry UI/runtime through the normal Kit manager and verifies both are off on a later update. CLI disable flags alone were ineffective and were removed.

The final 60-second check passed: 11.89 native camera FPS each, 11.83 accepted observation FPS over the sampled span, 10.39/10.41exact-preview publishes/s. Both recent recordings stayed ready, exact image/metadata checks passed, and the rotation-aware monitor saw no sequence/timestamp/session failures or monitored restarts/OOM. All14rules remain accounted for and active. Saved 20-GiB guard retained. UI source supports a fresh-health preview ceiling up to 30 FPS. No native worker image, TensorRT engine or production UI was built.

Hardware decode worked but did not establish an advantage. Aggressive RTPT bounce settings caused black images and were reverted; a valid two-bounce control gave little gain and darker images, so normal 3/3 limits remain. Live viewport-off and native CPU profiling stalled this Kit build; their failed receipts are preserved. An attempted inference interval knob was removed after installed DeepStream source proved the tensor-input path bypasses it. True prediction-only skipping would also need map/speed contract changes.

[Full performance evidence and remaining costs](smart-city-performance-2026-10-23.md). Final focused controls: 167 VSS CPU tests, 12 city helper tests, 54 UI tests and TypeScript passed. Normal Start returns already ready. The final startup hook is CPU-tested; its equivalent runtime operations were verified live, without repeating a complete fresh load after the last hook edit. Full-day endurance, final-scene accuracy and MV3DT qualification remain separate.


## October 26 — deployed evidence repairs, partial live crossing result

The source-scoped gateway deployment now loads engine `aff5a638…`, mobility `d4bb65c3…` and spatial `04425575…`. Both sources resumed normally and all 19 native rules acknowledge revision 434 with mobility revision 6 and unchanged profile `55a3297a…`. The combined city suite passes 259 controls, including 54 pedestrian controls; independent pending-label UI controls pass 49. [Deployment/source checkpoint](qa/smart-city-2026-10-26/v3-evidence-repairs-checkpoint.json), [pedestrian confirmation/replay](qa/smart-city-2026-10-26/pedestrian-pending-exit.md).

The actual East south-to-north camera row shows one completed crossing, zero incomplete and one recovered exit candidate. This is a camera measurement, not a whole-episode pass or all-direction score. The native episode was cancelled at 133.844 wall seconds for `native-navigation-task-failed`, short of its requested far landing target, and restored normal flow. Its endpoint repair and fresh complete run remain pending. The first-seen approach yields only a lower-bound duration, not signal delay or a valid full wait sample.

Pending-evidence UI candidate `20261026T085059804419Z` is not yet confirmed deployed here. Keep the previous deployed UI identity until the cutover receipt. Repaired stopped-zone clearance, final browser/scenario acceptance and combined displayed-rate qualification remain open; the goal is active.


## October 26 — pending-label UI deployed and vehicle clearance observed

Package `20261026T085059804419Z` / image `6781e5ed…` / source `4f8174e4…` now replaces the prior UI on isolated port 7782. Ten build tasks passed in 2 minutes 8.18 seconds. The exact actor-free map is unchanged and matches image/HTTP bytes; only `city-polish-ui` changed. Actual rendered acceptance after this latest reload is pending. [Cutover checkpoint](qa/smart-city-2026-10-26/v3-ui-evidence-cutover-checkpoint.json).

The repaired crossing-obstruction UI story completed/restored in 34.299 wall seconds. Its actual camera alert was observed active then cleared, with 12.114 observed blocked seconds, one completed episode and zero unknown episodes. The [pinned scene/AI receipt](qa/smart-city-2026-10-26/v3-repaired-crossing-live-ui.json) scopes this result to one paired simulated-camera episode. It does not complete the goal: the native pedestrian far endpoint, fresh complete pedestrian run, latest UI browser walkthrough, remaining coverage and combined displayed rate remain pending.


## October 26 — current bounded curb, demand and cancel evidence

The curbside-lane story completed/restored in 42.040 wall seconds. Actual camera occupancy, stopping and the configured eight-second dwell were observed. Its row reported a maximum active observed dwell of 23.093 seconds, 17.511 observed stopped seconds at the end, departure counter 2→3 across the exit and final empty status with zero observed occupancy. These are rolling row/window measurements, not a legal parking/loading determination. The curb trace SHA was checked against its [receipt](qa/smart-city-2026-10-26/v3-repaired-curb-live-ui.json).

The normal-demand story completed/restored in 30.031 wall seconds and verified normal flow without requesting extra arrivals; it does not promise each turn or class in that interval. In a separate real UI cancel, the owned car was held at 0 m/s, released, then sampled moving 3.470 route metres farther at 4.158 m/s. The queue image showed at least two observed objects and an 11.2-metre lower-bound extent; camera queue clearance remains separate. [Demand](qa/smart-city-2026-10-26/v3-demand-live-ui.json), [cancel/motion](qa/smart-city-2026-10-26/v3-ui-cancel-motion.json).

Current production UI remains package `20261026T085059804419Z` / image `6781e5ed…`; all 19 rules acknowledge revision 434, mobility revision 6. The crossing-obstruction pass remains 34.299 wall seconds with 12.114 observed blocked seconds and actual active-to-cleared evidence. [Pinned bounded-scenario checkpoint](qa/smart-city-2026-10-26/v3-bounded-scenarios-checkpoint.json). These individual results are not a new combined soak; the October 22 recorded-input endurance applies only to its old inputs/artifacts. Native pedestrian whole-episode acceptance, final v3 FPS and any remaining package/reconnect checks remain open. The goal is active.


### Latest native pedestrian retry — still incomplete

The reviewed free-endpoint selector was loaded without a new UI build or backend restart. Its first actual retry failed before crossing at 41.344 wall seconds for `pedestrian-native-action-refused`: waiting avoidance had moved the actor beyond the unchanged 0.35-metre entry tolerance. Cleanup restored the normal program. The original trace hash was verified against the [preserved failure receipt](qa/smart-city-2026-10-26/pedestrian-free-endpoint-first-live.json). A bounded native reapproach to the same verified entry is being repaired/reviewed under the original episode deadline. No wider tolerance, automatic crossing count or complete pedestrian episode is claimed; final v3 FPS also remains pending.


## October 26 — final pedestrian, UI walkthrough and full queue passes

The final pedestrian UI episode completed/restored in97.123wallseconds with native SUCCEEDED arrival,0.03796m endpoint error and actual outside-crossing/normal-flow evidence. Independently, the East north→south camera completed counter advanced0→1. Current people/runtime/director source hashes match the [pinned receipt](qa/smart-city-2026-10-26/v3-final-pedestrian-live-ui.json). The earlier waiting-drift and WALK-deadline failures remain preserved; same-entry reapproach did not trigger in this successful episode. First-seen waiting remains a lower bound, not signal delay.

The actual rendered scenario/Insights walkthrough passed on production image6781. Final full queue control completed/restored in36.014wallseconds; native hold/release/departure were observed. The camera separately saw two objects and9.535m lower-bound extent, with candidate/incomplete membership; camera queue clearance is not claimed. [Queue receipt](qa/smart-city-2026-10-26/v3-final-queue-live-ui.json).

Only the current final FPS receipt and integration-owner health/artifact review remain named goal acceptance checks. The goal stays active pending those results. These are bounded prototype checks, not a new full-day or recorded-input-soak qualification.


## Historical October 26 checkpoint — rate recorded before clock repair

The 30.063-second native/server sample measured 10.120 camera handoffs/s each, 10.145/10.112 accepted observations/s and 10.046/10.012 exact-preview publishes/s. It validated 22 exact image/metadata envelopes and six unchanged container identities. Simulation/wall ratio was 0.337. The separate 44.073-second 1920×1080 browser sample measured 9.643/9.757 actually rendered FPS and 10.210/10.233 selected-frame FPS, with exact-frame alignment reported. These partly overlapping windows do not isolate a stage loss, prove a speedup or measure absolute capture-to-display latency. [Native receipt](qa/smart-city-2026-10-26/v3-final-native-performance.json), [browser receipt](qa/smart-city-2026-10-26/v3-final-browser-performance.json).

All eleven sampled latest-snapshot pairs were outside the unchanged 150 ms join guard: median 597.073 ms, maximum 597.315 ms, 0/11 within 150 ms. Shared-map joins were correctly rejected. Camera-local tracking/rules and per-frame previews do not qualify cross-camera identity; current MV3DT association remains unqualified. Sequential snapshot requests are not a physical-exposure synchronization test. A bounded read-only clock diagnosis is in progress, with no offset correction or relaxed guard claimed. [Scoped performance/timing summary](qa/smart-city-2026-10-26/v3-final-performance-summary.json).

The goal remains active pending timing disposition and the integration owner's final health/artifact review. Individual scenario passes and historical recorded-input endurance do not resolve this current timing limit.


## October 26 — native AU clock, exact proxy and guarded map display repaired

The final installed worker is image `4e6b73d1…`, profile `cadd8867…`; isolated UI package `20261026T102610382036Z` pins image `1d94d035…`, source `d4aee494…`. Ten UI tasks passed 2 m 4.333 s. Final installation preserved scene/publisher and the running CPU gateway, admitted new source sessions normally and kept recordings ready. Nineteen rules now acknowledge 450, mobility remains 6 and all eight tracker pins/calibration remain intact. The public proxy repair preserves the two explicit native clock fields; its real-metadata regression failed before the fix and all 88 proxy/guard controls passed afterward. The earlier `77c066` artifact and missing native publisher-gate failure remain separate retained evidence.

The source clock is explicitly `source-native-sei`: exact AU wall-handoff time, not reconstructed RTCP, simulation time, physical exposure or a verified browser clock. The final 29.9868 s server sample passed with 9.403 native handoffs/s per camera, 9.404/9.437 observations/s, 9.371 previews/s each, 22 exact envelopes and six stable container identities. Simulation/wall ratio was 0.3134. A separate 57.82 s browser sample rendered 9.011/9.132 FPS and selected 9.166/9.184 FPS with both views aligned. Eleven sequential latest pairs had 0.501168 ms median/123.68622 ms maximum skew; all 11 met the unchanged 150 ms guard. These are bounded transport/display samples, not latency or physical synchronization scores. [Native](qa/smart-city-2026-10-26/native-sei-final-native-performance.json), [browser](qa/smart-city-2026-10-26/native-sei-final-browser-performance.json).

Offline evaluation of retained current-session pairs found 83 initial map-guard passes, including 45 same-render-counter pairs. Separately, [final dashboard pixels](qa/smart-city-2026-10-26/native-sei-final-dashboard.jpg) and actual accessibility state reported one joined person/2 views. The older shared-person screenshot showed 0 joined with later accessibility 1; it is a separate instant. No claim that every frame joins or the SDK ID is independently validated physical identity. All clock/position/calibration/session/model/visibility guards remain; camera-local rule/count authority and false browserClockVerified are unchanged. [Evidence distinction](qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json).

One actual Southwest question about the last five seconds returned an answer and a 5.0304-second inspected clip which played to ended=true/error=null; on-demand indexing stayed inactive. This is real question/playback evidence, not a VLM accuracy or visitor-throughput score. [Ask](qa/smart-city-2026-10-26/native-sei-final-ask-browser.json). The new native pedestrian episode completed/restored in 42.7099 s with SUCCEEDED endpoint/error 0.03830 m/outside crossing. Camera completion stayed 0→0 and pre-existing incomplete 3 stayed 3. The same local ID persisted, but fresh-object 1.137 s/1.871 s observation gaps exceeded the unchanged 1 s bound, so no camera completion qualifies. [Current result](qa/smart-city-2026-10-26/native-sei-final-pedestrian.json). [Continuity audit](qa/smart-city-2026-10-26/native-sei-pedestrian-camera-continuity.json) confirms target-specific observation gaps while camera frames continued. The earlier 97.123 s native plus camera 0→1 pass retains its old artifact scope. [Final health](qa/smart-city-2026-10-26/native-sei-final-health.json) passed 19 rules at revision 450, mobility revision 6, eight pins, served map hash, current recordings, inactive indexing and five available/restored stories; it is not a new five-story execution or endurance run. The implementation is accepted as a bounded booth prototype with these limits. The 597 ms/0 of 11 failure and older soaks remain historical.

## October 26 — implementation delivered

The final owner review accepts the implemented booth prototype with the documented limits. Both source sessions remained live in the final read-only check, all five controls were available, normal traffic was restored and the browser was left on live Insights with its temporary viewport override removed. The saved dashboard shows actual two-view person sharing. The overnight heartbeat remains paused. No new full-day, model-accuracy, fused-count or Thor result is claimed. See the [delivery manifest](qa/smart-city-2026-10-26/final-intersection-delivery.json) and [goal ledger](smart-city-intersection-goal-2026-10-26.md).
