# Smart City implementation and evaluation plan

October 21, 2026 initial plan against existing `/home/sparkdev/vss`. Current implementation and measured status are in [the as-built record](smart-city-as-built.md); this plan preserves the original implementation order. Medium is now explicitly selected on Spark, with Small retained as the tested baseline. Read [decisions](smart-city-integration-research.md) and [contracts](smart-city-data-contracts.md) first.

## 1. Implementation order

### Step 1 — Contract and fixture slice

Add the site/calibration and city observation types; reuse the existing source UUIDs. Implement validated coordinate transforms, explicit unknown/stale states and source epochs. Prepare recorded RTSP-equivalent city clips plus an offline fixture dataset. Fixtures are test inputs, never substituted into the live booth without an explicit replay label.

Prove one observation can select its source frame, project to the correct map location and clear when absent. Cover missing calibration, bad units, crop, portrait video, stream reset and empty frames before polishing UI.

### Step 2 — Isolated DeepStream 9.2 worker

Read current runtime and device instructions before launch. Inventory host/container compatibility. Build a derived RT-CV image and recompile application/parsers/converters; do not copy the DS 9.1 plugin binaries blindly. Preserve the current VSS stack and saved reserves.

Implement RF-DETR Small preprocessing/parser and engine lock. Validate reference → ONNX → TensorRT → DeepStream outputs, including batch one/two, class slots, inverse resize and empty frames. Add the city analysis profile and endpoint with capacity one until two sources pass.

Run file input first, then one bounded live source, then two. Use CUDA NvDCF. Confirm source UUID equivalence in object and dummy paths. Verify existing Kafka consumers accept the metadata.

### Step 3 — Projection and shared live map

Extend Cartesian calibration in shared behavior analytics with explicit validity; remove the new path's dependence on pixel fallbacks and four-corner-only ROI helpers. Add short observation history, primary coverage zones, bounded live gateway and native `SpatialMapView`.

Wire the existing video components to a shared presentation clock. Synchronize the map and overlays with displayed video. If gateway timing cannot support this, qualify a timestamp-preserving annotated video path before proceeding. Do not hide this issue with decorative animation.

### Step 4 — Rules and event lifecycle

Extend the current region editor to polygons plus directed lines. Extend the existing monitoring API with class capability checks, per-rule thresholds, revisioning and pending/applied states. Compile native analytics rules, wire reload acknowledgement and serialize its metadata.

Add backend dwell, stopped-in-zone and queue state with event-time semantics. Use one crossing publisher per rule. Link existing events/evidence; test persistence through source reconnect and worker restart. Deliver entry/crossing/occupancy first, then stopped-in-zone, bus dwell and queue.

### Step 5 — Industry workspace and Ask

Use the current React shell and CT AI Labs design. Reuse camera, evidence, question and report components. Add shared track/event selection and timeline state. Keep the two camera panes, map and a single active detail panel readable at booth distance.

Add evidence-based explanations through the current Cosmos endpoint after structured events work. Keep the VLM request budget independent; one admitted explanation initially. Test brief-event evidence with and without EVS before choosing a city preset. Retain structured results if explanation fails.

### Step 6 — Model competition and capacity qualification

Run RF Small/Medium, YOLO26s/m (subject to deployment terms), RT-DETRv4-M and the existing NVIDIA baseline on identical captured footage. Test models serially to avoid competition artifacts. Escalate to RF Large or conditional candidates if the initial set fails important recall targets.

Pick the model by event quality and latency on target hardware. Rebuild and measure on Thor; Spark is the development machine, not proof of Thor performance. Only then raise advertised capacity and enable the final booth profile.

### Step 7 — Multi-camera association and soak

Primary coverage-zone counts are acceptable for the first complete demo. Add cross-camera identity only if calibrated timing and position quality pass; test duplicates, two nearby same-class objects, crossing trajectories, occlusion and asymmetric camera loss. For calibrated overlapping fixed cameras, evaluate MV3DT as the first native fusion candidate using the [current decision and enablement gates](smart-city-mv3dt-decision.md). Until its 3D/peer runtime and fused metadata/event adapter are qualified, keep per-camera NvDCF identities and do not fuse the unrelated test clips.

After bounded stages pass, run progressively longer workload tests and finally the proposed two-hour booth soak. Repeat the full scripted event loop at least 30 times. Include live Ask/report activity, reconnects and rule edits. Follow existing runtime guard/stop conditions; do not interpret a memory reserve as permission to run an unqualified sustained workload immediately.

## 2. Main integration files

Paths below are existing unless marked proposed. Implementation should follow local AGENTS instructions and scoped UI development guidance.

| Area | Files / change |
| --- | --- |
| Model/profile routing | `services/agent/packages/vss_agents/src/vss_agents/api/analysis_profiles.py`; add city taxonomy/capability/worker mapping and qualified source limit. |
| RT-CV | `services/rtvi/rt-cv/src/metropolis_perception_app.c`, `metropolis_perception_app.h`, `src/Makefile`; generic model mapping or explicit RF mode, frame metadata, analytics extraction. |
| Export/parsing | Proposed `services/rtvi/rt-cv/models/rfdetr/` and dedicated C++ preprocessing/parser sources; inspect repository conventions before choosing final locations. |
| Build | `services/rtvi/rt-cv/docker/Dockerfile`, `docker/sbsa.Dockerfile`; DS 9.2 build, correct platform dependencies. |
| Deployment | `tools/spark/bootstrap.py`, current Thor renderer/start scripts, `deploy/docker/spark/`; derived image/profile and capacity, preserving unrelated edits and memory settings. |
| Shared analytics | `services/analytics/behavior-analytics/apps/composite/main_composite_app.py`; `src/mdx/analytics/core/transform/calibration/`; event/space modules. |
| Protocol | `services/analytics/video-analytics-api/src/web-api-core/schemas/proto/schema.proto`; prefer existing fields/info initially and compatibility tests before schema edits. |
| UI workspace | `services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/`; workspace routing, camera canvases, event/evidence components. |
| Rules | `components/vision-intelligence/MonitoringRegionEditor.tsx`; `pages/api/vision/monitoring-rules.ts`; monitoring types/utilities. |
| Admission | Existing UI `server/vision/workloadAdmission*` and source/profile routing; capabilities from actual worker. |
| Map / live transport | Proposed shared `SpatialMapView`, site state/hook and gateway; keep current camera/evidence API as owner of sources/media. |

Do not start a second obsolete Smart Cities Compose stack or replace the current VSS application. Existing warehouse profiles must remain usable.

## 3. Evaluation data

Build an initial labelled set of roughly 500–1,000 representative frames plus event clips; this is a proposed starting size, not an existing benchmark. Increase it if rare cases remain poorly sampled. Include:

- Every required class at near/mid/far distances; log pixel-size bins after model resize.
- Bus versus truck, van-like cars, riders, groups and partial occlusions.
- Each intended event, its onset and clearance; normal stops at lights and valid bus-stop dwell as negative controls.
- Boundary jitter, turn paths, people beside rather than within a crossing, stationary background objects.
- Both cameras independently and their overlap, different light/shadow/weather settings when available.
- Empty streets, RTSP dropout, timestamp reset, source reorder, duplicate delivery and rule changes.

Split by complete episode/camera condition/scene seed, not adjacent random frames. Keep a held-out set untouched while tuning. Simulator labels may support evaluation and training; operational inference must not read them. For claims beyond this booth, add licensed representative real traffic video and report its results separately.

## 4. What to measure

| Layer | Measurements |
| --- | --- |
| Detector | Per-class precision/recall and AP, small-object recall, bus/truck confusion, confidence calibration; accuracy before and after export/precision conversion. |
| Tracker | ID switches, fragmented tracks, reacquisition delay, IDF1/HOTA where ground truth supports them; stationary-object persistence. |
| Map | Ground anchor error by class, distance and camera; p50/p95; rejected projection fraction and error near decision boundaries. |
| Association | False merges and duplicate rate, handoff correctness, performance on nearby similar objects. |
| Rules | Event precision/recall, onset/clearance error, crossing count error, dwell error; replay/restart idempotency. |
| Timing | Source→decode→inference→metadata→browser stages; video/overlay skew and capture-to-screen p50/p95/p99. |
| Runtime | Per-source processed FPS, queue depth, drop rate, GPU/CPU/RAM, temperature/power, reserve margin, simultaneous VLM impact. |
| Analyst | Correct facts, unsupported statements, brief-event misses, time to first useful answer and completed answer; evidence validity. |

Use synchronized clocks or verified clock mappings for cross-service latency. Network arrival time alone cannot measure capture latency. Report warmup/engine build separately from steady state and include test duration, sample counts, model settings, image size and active services.

## 5. Proposed acceptance targets

These are engineering targets to validate, not measured promises. Freeze exact thresholds after first representative footage and camera placement review; document changes instead of silently relaxing them.

| Gate | Initial target |
| --- | --- |
| Two-camera rate | Sustained 15 analyzed FPS per source at 1080p ingest; prefer 30 if full workload permits. No growing queue. |
| Display timing | p95 capture-to-screen ≤750 ms; p95 overlay/video mismatch ≤100 ms. Separately report source-clock uncertainty. |
| Structured event delay | p95 publication ≤500 ms after the configured dwell/confirmation condition has become true. |
| Core event quality | ≥95% precision and ≥95% recall on held-out scripted events, with sample counts and per-event breakdown. |
| Counting | ≥98% correct annotated line-crossing count on the chosen evaluation sequence, with exact misses/duplicates disclosed. |
| Map anchor quality | Initial p95 target ≤0.75 m for people and ≤1.5 m for vehicles within qualified coverage; measure actual bias. |
| Zone confidence | Do not make precise boundary/near-miss claims where position uncertainty is comparable to the zone margin. |
| Identity | No false global merges in the controlled close-object test set; retain separate IDs when ambiguous. |
| Recovery | No duplicate event, stale moving marker or inherited dwell timer after reconnect/reset; affected state visibly unknown until recovered. |
| Memory/stability | Saved reserves maintained; no GPU errors, OOM or monotonically growing queues during the qualified workload. |
| VLM | Structured event pipeline stays responsive while Ask runs; unsupported text and brief-event misses are reported, not hidden by average latency. |
| Booth repetition | At least 30 normal/event/clearance loops and a two-hour soak only after shorter stages pass. |

If map anchors fail, first correct calibration/framing/contact estimation. If distant objects fail, compare input resolution and camera placement before selecting a larger model blindly. If compute fails, reduce explicitly admitted workload or choose the measured lighter model; never fabricate freshness or disable the reserve guard.

## 6. Definition of implementation-ready and booth-ready

This research is implementation-ready: selected architecture, shortlist, actual code boundaries, data contracts and evaluation gates are documented. It is not a runtime qualification receipt.

Booth-ready requires a pinned artifact lock and a reproducible report demonstrating the chosen model, two actual RTSP cameras, active rules, synchronized map, retained evidence, live questions and sustained operation on the Anvil-T5. The UI must distinguish configured, loading, ready, stale and failed states. A screenshot or healthy container is insufficient evidence.
