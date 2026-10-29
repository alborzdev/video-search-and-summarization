# Smart City quality-first DeepStream optimization — October 27, 2026

The implementation goal balances efficiency with current people/vehicle detection, track continuity, exact frame delivery and map/event integrity. Faster processing alone does not qualify a candidate. This receipt covers the current Spark GB10, DeepStream 9.2, RF-DETR Medium 576 FP16 engine and **one native MV3DT tracker with NVIDIA's internal CUDA DCF**.

## Implemented

- Real per-source detector scheduling in the custom preprocessing path. This bypasses tensor preparation and TensorRT inference for selected frames while keeping every admitted video frame in the SDK's ordered path through MV3DT. It handles partial mux batches, independent camera counters and PTS rewind. The infer completion probe checks scheduling against the SDK's `bInferDone`; exact detector stamps remain authoritative for observations. Every-second/every-third-frame modes are restricted to offline quality trials because they failed the current comparison and live display/analytics conservatively require detector observations.
- Preview envelope hashing/serialization runs in the Starlette worker pool instead of blocking the ASGI event loop. Immutable captured history, final generation/session checks, lossless observations and bounded per-camera preview outboxes remain in use.
- Pipeline diagnostics report actual full/partial batch occupancy, inferred/tracked frame counts and preprocess/inference and tracker/analytics path latency. Timing includes asynchronous waits and contention; it is not isolated kernel time. Public health diagnostics whitelist bounded counters and omit private/invalid data.
- Explicit bounded hardware decoder surface and low-latency controls, including actual decoder selection/status. Low-latency mode is an opt-in for verified I/P-only H.264 input; it is unsuitable for arbitrary B-frame cameras. Both simulator encoder implementations explicitly configure `bframes=0` in `isaac_city_sim/scripts/rtsp/gst_rtsp_streamer.py` and `software_encoder.py`.
- An exact-frame comparison tool and regression controls for one-to-one box matching, source/PTS/geometry boundaries, tracker-only frames, appearance-delay diagnostics, strict runtime tuning and event-loop isolation.

## Matched native replay

Six bounded runs used the same retained encoded camera pair, same model engine, tracker/calibration files and isolated MQTT topics. Each produced 600 observations. All scheduling/provenance checks passed: 600/301/201 inferred frames for cadence 1/2/3 respectively; no skipped frame contained a current detector observation or fabricated detector confidence. The production CUDA preprocessing test matched the CPU reference with maximum error **0**. No observations were posted to the live gateway by these tests.

The table compares only identical source-frame/PTS/geometry records shared with the baseline, using deterministic one-to-one greedy IoU ≥ 0.50 matching. “Small” means baseline box height <40 source pixels. Identity appearance delay refers to first matching a baseline SDK identity, which can itself be a fragmented identity. These are **baseline-agreement diagnostics**, not labeled recall/precision, physical identity switches or IDF1. The independently zeroed files do not establish synchronized cross-camera identity truth.

| Candidate | Common frames | Baseline box agreement | Small-box agreement | p95 first baseline-ID match delay |
| --- | ---: | ---: | ---: | ---: |
| Baseline repeated | 596 | 99.82% | 99.98% | 0 ms |
| Detect every second admitted frame | 598 | 87.61% | 90.97% | 333 ms |
| Detect every third admitted frame | 599 | 82.97% | 86.27% | 1,044 ms |
| Mux wait 20 ms, detect every frame | 597 | 99.92% | 99.98% | 0 ms |
| Hardware decoding, detect every frame | 597 | 98.91% | 98.79% | 0 ms |

Cadence 2 also matched only 171 of 226 baseline motorcycle boxes. Cadence 3 matched 150. The current detector and native tracker settings therefore remain the quality reference. Reducing raw inference work did not justify the continuity/box differences. Wall time for these short runs includes startup/cache effects and is not used as a capacity claim.

## Live delivery and batching

Thirty-second samples before and after the preview worker-pool change kept CPU decoding, a 10 ms mux wait, every-frame detection and full 960×540 preview geometry. Preview POST means were computed from timing-count/total deltas over each sampled window:

| Window | Southwest POST mean | Northeast POST mean | Analyzed FPS per camera |
| --- | ---: | ---: | ---: |
| Original | 29.42 ms | 25.08 ms | 6.72 / 6.72 |
| Candidate | 19.22 ms | 15.27 ms | 6.69 / 6.72 |
| Candidate repeated | 19.07 ms | 15.80 ms | 6.72 / 6.76 |

These are prototype live windows, not a controlled capture-to-screen benchmark. They support the delivery change; they do not establish a higher incoming camera rate. Exact source clocks, detection cadence, calibration and tracker parameters are unchanged.

Increasing mux wait from 10 to 20 ms produced more full batches (41/385 in that worker's cumulative sample versus 4/425 at 10 ms), but analyzed rate stayed about 6.65 FPS per camera and source-age p95 increased. **Keep 10 ms.** Do not enlarge the queues or drop frames before MV3DT to claim higher throughput.

## Decoder qualification

Hardware decoding without extra surfaces stalled after only a few live frames despite passing the file replay. Four extra surfaces delivered both cameras for a minute, but eight surfaces stalled on restart. The successful four-surface window also had higher source-age p95 (approximately 0.40/0.38 seconds versus 0.25/0.21 in the CPU candidate). Thus a successful file replay or a single surface-pool adjustment does not qualify hardware decoding.

With **four extra surfaces and I/P low-latency mode**, two separate starts each delivered both cameras for 45 seconds. Source-age p95 was 0.243/0.180 seconds, then 0.255/0.200 seconds; the following CPU comparison was 0.248/0.193 seconds. Per-container cgroup CPU usage averaged 0.178 and 0.173 CPU cores versus 0.224 cores for CPU decoding. This is roughly 0.05 of one CPU core saved, with no demonstrated camera-rate gain.

**Retain CPU decoding as the default.** The hardware mode is now a tested opt-in for this I/P simulator, but its small absolute CPU saving does not justify promoting decoder-dependent box differences without independent scene accuracy labels. Low-latency mode must not be generalized to unverified cameras. Default-decoder hardware, larger surface pools alone and the 20 ms mux candidate are not selected.

## Final active configuration

- RF-DETR Medium 576, existing TensorRT FP16 engine and query/cutoff policy.
- Every-frame detection, one native MV3DT tracker, unchanged calibration and tracker parameters.
- CPU decode, 10 ms mux wait, unchanged bounded queues, 30 FPS preview ceiling and full-resolution preview images.
- Preview envelope preparation off the ASGI event loop, plus active pipeline/decoder diagnostics.
- Offline-only real inference-cadence trials; no ineffective stock interval setting and no tracker predictions presented as detections.

Both analyzed camera previews and their map overlays were verified in the browser after restoring this configuration. The UI reported the simulator paused at final review; it was left in that user-selected state. Live delivery samples are therefore transport/resource tests, not qualification of moving-object recall or occlusion handling. The retained moving replay supplies the matched-frame quality comparison, within its stated limits.

The Python checks passed **128 tests** across preview handling, strict tuning, comparison metrics, native-clock/session boundaries, motion and MV3DT profile validation. Native CPU controls passed scheduling, exact provenance, six-class/64-bit identity export, boundary/clock handling and independent bounded preview delivery; the GPU preprocessing reference check passed. Deployment identities and the final active configuration are retained in the private receipt directory.

Public verification: [active configuration and checks](qa/smart-city-optimization-2026-10-27/verification.json), [live camera/map screenshot](qa/smart-city-optimization-2026-10-27/live-verification.jpg). The browser reported no console errors or warnings.

## Quality and resource boundaries

The RF-DETR engine, detector cutoff/query policy, 640×384 calibrated tracker geometry, source cameras, rule geometry, target capacity, shadow age and native association parameters remain the reference. ReID inference is already disabled. A generic NvDCF performance preset, lower tracker/source resolution, smaller model, lower threshold, ROI crop, shorter shadow history or quantization would change quality/coverage and needs separate evidence. Removing the custom CUDA synchronization without a supported lifetime handoff would be incorrect. Those are not promoted as speculative wins.

The Spark guard stays active at the saved **20 GiB reserve**, with bounded trials stopping below reserve +4 GiB. Native replay minimum available memory was at least 30.94 GiB; the one-minute hardware trial stayed above 33.72 GiB. This is bounded two-camera validation, not sustained-ingestion capacity qualification. Shared physical identities and independent scene accuracy remain unqualified; the optimizations do not change that status.

## Evidence and reproduction

Raw logs, guard receipts, exact commands, source/config/engine hashes, recorded outputs, comparisons, live samples and rollback profiles are retained under `.spark/city/runtime/optimization-20261027/`. The helper scripts there run serially, isolate MQTT topics, pause only the existing detector during replay and restore live detection in `finally` blocks. No additional simulation render products or model workloads are started.

The comparison tool is `tools/smart-city/compare_pipeline_runs.py BASELINE CANDIDATE... --output RESULT.json`. The native CPU controls include `make detector-cadence-test native-mv3dt-test staged-tracking-test test`; GPU preprocessing parity runs through NVIDIA's compatibility entrypoint in the pinned image. Decoder settings are private local `runtime-tuning.json` choices and are not applied to unknown cameras automatically.

NVIDIA fundamentals reviewed: [DeepStream development skill](https://github.com/NVIDIA/DeepStream/tree/main/skills/deepstream-dev), [pipeline profiling skill](https://github.com/NVIDIA/DeepStream/tree/main/skills/deepstream-profile-pipeline), [native MV3DT skill](https://github.com/NVIDIA/DeepStream/tree/main/skills/deepstream-run-mv3dt), [tensor-input interval caveat](https://docs.nvidia.com/deepstream/text/DS_RestServer), [tracker behavior](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker), [mux batching](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvstreammux), and [decoder properties](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvvideo4linux2). The exact installed SDK source and GObject properties take precedence over generic skill examples.
