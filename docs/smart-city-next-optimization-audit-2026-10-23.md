# Next optimization audit — October 23, 2026

This is a recommendation audit, not an implementation receipt. Three parallel code audits and an offline USD census were combined with read-only runtime/log inspection. No running service, camera, scene, model or tuning was changed. No GPU benchmark, build or new inference request was launched.

The objective is smoother camera views with useful detection, tracking and city measurements. Thirty FPS is an aspiration. The current evidence does not establish an achievable final FPS on a shared GB10 GPU.

## Starting point

Use [the completed performance pass](smart-city-performance-2026-10-23.md) and its linked receipts. The final integrated sample delivered 11.89 native frames/s per camera, 11.83 accepted observations/s, 10.39/10.41 exact preview publishes/s, and about 9–11 browser presentations/s. These are different stages. Increasing browser efficiency cannot create source images which Isaac did not render.

The earlier source-only sample reached 16.78 frames/s, with analysis paused. It was a different scene window and preceded the final gantry shutdown. It supports a contention investigation, not a matched estimate of inference's isolated cost.

Keep the current native NVIDIA H.264 RTSP path, 960×540 camera geometry, RF-DETR Medium 576×576 input, calibrated 640×384 tracker, exact image/metadata pairing, and reviewed map/rules as controls for the first comparisons.

## Recommended order

| Priority | Work | Evidence | What a useful result would mean |
| --- | --- | --- | --- |
| 1 | Recover frames lost by preview scheduling and reduce per-image metadata | Around 1 dropped frame/s/source in the sampler despite its 30-FPS ceiling; historical events and trails outweigh the JPEG | More of the existing analyzed images reach the screen, with less CPU/allocation work |
| 2 | Prepare a separate compact neighborhood composition with NVIDIA Scene Optimizer | Roughly 11,800 one-use prototypes and many repeated material networks across a much larger city than the two views require | Higher native camera delivery without shrinking distant road users |
| 3 | Add explicit indexing/workload controls | Both sources currently generate Cosmos Embed results about every five seconds | Establish whether background semantic indexing competes with live traffic; preserve honest feature availability |
| 4 | Compare a production UI package and isolate React update paths | Port 7782 currently leads to a Next development server; per-frame state updates reach broad workspace components | Lower UI overhead and steadier display, measured rather than assumed |
| 5 | Attribute GPU pipeline and tracker costs, then tune the expensive stages | Full-resolution color conversion, custom tensor synchronization and per-object DCF remain | Reduce actual critical-path work while preserving identities, projections and preprocessing semantics |
| 6 | Consider separate render hardware or a labelled replay presentation mode | Rendering and inference share the same GPU | A larger architectural improvement if the live shared-GPU ceiling is still too low |

Priorities 1 and 2 can be prepared independently. Do not rebuild models before addressing these leads.

## Preview: code-proven excess work

`services/rtvi/rt-cv/smart-city/src/preview_core.hpp:40–52` gates selection by wall-clock arrival spacing. Bursts can cause frame rejection even when average source FPS is far below the preview ceiling. The saved final sample had 65/62 sampler rate drops over 58.81 seconds. Selected frames were all encoded, so these receipts do not support blaming the JPEG encoder for this loss.

Try a bounded burst allowance or source-time-aware budget which resets on session changes and discontinuities. Keep only current frames; do not create a stale queue to raise a counter. Test reset, pause, back-to-back arrival, sustained ceiling and boundedness cases.

The final saved envelopes carried roughly 110–121 KB of metadata beside 48 KB JPEGs. Later read-only samples carried roughly 156–228 KB of metadata beside 49 KB JPEGs. The larger sample included about 145 KB of historical events and 50 KB of trails. These are samples, not a constant size guarantee.

Relevant paths:

- `services/analytics/behavior-analytics/apps/city/engine.py:651–665` copies tracks/trails and up to 100 recent events into each frame's history.
- `services/analytics/behavior-analytics/apps/city/preview.py:340–403` holds engine/preview locks while matching history and constructing/serializing an envelope.
- `services/ui/apps/nv-metropolis-bp-vss-ui/pages/api/vision/city/[...path].ts:62–91` buffers each envelope, parses its metadata, filters public fields and rebuilds JSON. It already reuses the JPEG slice; preserve that improvement.

Create a small immutable public frame contract: source/session/sequence/time, geometry and configuration revisions, boxes/anchors, required map hints and actual current measurement state. Send historical events, reports and static rule/calibration definitions separately or on revision changes. Retain the data needed to align map state with each camera's displayed frame. Move serialization outside the engine lock, with a generation/session check before publication. Do not simply remove the proxy's public-field filtering while forwarding the existing broad payload.

`city_worker.cpp:164–195` uses one blocking HTTP sender for both sources. The gateway can wait up to 200 ms for matching observations. Final-window latest-packet replacements cost roughly another 0.36–0.43 frame/s/source. Measure POST latency and metadata-pending frequency, then consider independent bounded source senders or a bounded gateway inbox that can acknowledge promptly. Preserve per-source ordering and exact matching.

A further option is independent display resolution: encode a 640×360 preview while retaining 960×540 acquisition and the existing detector/tracker sizes. That reduces display pixels by 55.6% without reducing detector input detail. The gateway permits a smaller image of matching aspect ratio, but native geometry checks and the overlay coordinate contract need explicit support. This is not a change to camera calibration.

Only after the simpler fixes, compare a persistent binary paired-image stream against polling. A video transport rewrite is a larger project: ordinary video playback does not by itself identify which inference frame is currently shown. Any H.264/WebRTC/WebCodecs approach must retain a validated timestamp/sequence join and bounded presentation buffering. A second encoder could add GPU work.

## Scene: strongest larger lead

The census opened `/home/sparkdev/isaac_city_sim/stages/smart_city_pilot.usda` with CPU USD libraries only. It did not render or modify the stage. It counted instance proxies for static composition; runtime-spawned actors are a separate population.

- 11,994 meshes total; 11,819 beneath the city geometry.
- 11,808 USD prototypes, each referenced by exactly one instance. This layout gives no sharing between those instances.
- City geometry totals about 209,428 triangulated faces. Primitive/material count is a stronger lead than a huge raw city polygon count.
- City bounds cover approximately 1.91×1.76 km. The union of the two authored camera frusta intersects 705 city mesh bounding boxes at the authored 1000 m far plane, or 245 at 150 m. These are conservative AABB tests, not visible-pixel counts. They do not justify clipping everything else without reflection, shadow, skyline and incoming-traffic margins.
- Normalized material-network inspection found repeated pavement/curb networks 1,714 times each, and 821 signatures across 11,808 prototype materials. Resolve actual textures, asset paths, bindings and primvars before declaring materials equivalent.

Installed Scene Optimizer core 110.2.1 provides analysis and operations including material optimization, spatial merge, clipping and geometry deduplication. Use its current argument metadata rather than stale examples. Its command undo implementation is empty, so run operations only on a separate derived composition. NVIDIA documents [deduplication and spatial merge presets](https://docs.omniverse.nvidia.com/extensions/latest/ext_scene-optimizer/user-manual.html).

Suggested derived asset: a buffered intersection neighborhood, deduplicated equivalent materials, and static meshes consolidated into spatial tiles. Do not merge the entire city into one object and lose useful culling. Per-prototype mesh merge alone will not address prototypes that each contain only one mesh. Keep originals, protected cameras, actor paths, navigation, map geometry and native ParticleField policy guards intact. Do not optimize the live stage or approve scene proposals.

Additional bounded scene candidates:

- Eleven construction cones each contain 9,968 triangles: 109,648 together. A derived low-detail cone with real geometry sharing is plausible. References begin in `stages/layers/intersection.usda:247`.
- A motorcycle/rider asset has 66,431 triangles, versus about 6,022–7,951 per car. Seven pooled motorcycles load 465,017 triangles. Visibility and actual render cost were not established; preserve recognizable road-user silhouettes and animation pivots.
- Twelve vehicle signal DiskLights have authored intensity 10,000. `scripts/traffic/light_controller.py:308–337` toggles lens meshes while retaining visible bulb parents; it does not control sibling DiskLight intensity. Trial signal-driven light intensity or daylight emissive lenses without local illumination, then inspect appearance. Streetlamps already have zero daylight intensity.
- `vehicle_controller.py:875` writes active and parked slot poses after each 60-Hz substep. Cache unchanged parked poses first. The older Python profile attributed about 0.42 s per 15 s to pose/park writes, so this is secondary to the larger leads. A final-pose scheduler must preserve spawn/despawn transitions.

No FPS gain from these scene proposals has been measured.

## Background AI and UI work

`services/agent/packages/vss_agents/src/vss_agents/api/rtsp_ingest.py:895` starts embedding generation as part of source reconciliation. Caption resource registration is separate; it does not establish continuous caption generation.

A read-only 60-second sample from `vss-rtvi-embed` contained 12 completed embedding inference spans per source, model `cosmos-embed1-448p-anomaly-detection`. Medians were 413.8 and 431.6 ms; ranges were 398.9–442.6 and 408.0–448.2 ms. These are logged elapsed inference spans, not isolated GPU kernel time or measured impact on camera FPS. The several-second decode spans include live chunk collection; do not interpret them as several seconds of busy CPU decoding.

Expose and compare workload policies rather than silently disabling features: normal indexing, lower-rate indexing, and event/on-demand processing. Decouple indexing control from CV pause/resume so a traffic-priority profile can retain detection, tracking, map and rules. Show whether semantic history is current or sampled. Keep on-demand visual questions usable. Resident model memory alone does not prove ongoing GPU computation.

The isolated UI currently runs `next dev --turbopack`. Compare a current production package against the same code in development. The older rollback package lacks recent features and is not a valid control. Do not claim a steady-state FPS gain before measurement.

`SmartCityWorkspace.tsx:79–83,177–182` connects presented source snapshots to map derivation, selection and inspector updates. Inline callbacks and newly allocated selection arrays can defeat memoization. Isolate per-camera presentation, stabilize callbacks/constants, and update reports/inspector at a lower appropriate cadence. Preserve the existing single in-flight request/decode, hidden-tab pause, bitmap cleanup and image/overlay commit ordering. Keep map timing explicit rather than showing newer invisible detections as current camera state.

## GPU pipeline and model choices

Current path includes CPU H.264 decode, GPU upload, mux, full-resolution RGBA conversion, custom RF-DETR tensor preparation, inference, DCF/MV3DT tracking, analytics, GPU download and software JPEG. Add lightweight stage and queue timing before rewriting this path. Measure full/partial batch occupancy, object and shadow-track counts, and GPU event timings without a device-wide synchronization probe.

`rfdetr_preprocess.cu:67` synchronizes its custom CUDA stream for each batch. An event-based handoff or fused YUV-to-normalized-tensor conversion could reduce waits/copies, but requires plugin lifetime/readiness integration. Preserve RGB order, half-pixel bilinear resize and normalization semantics. Do not simply delete synchronization or substitute a numerically different stock preprocessing path.

NvDCF currently enables HOG and ColorNames, feature size level 3, up to 100 targets/source and shadow age 49. Compare a smaller feature preset before changing calibrated tracker resolution. Evaluate ID continuity through occlusion, crossings, map position and event counts. Lower cost is useful only if this demo's tracking remains convincing. Existing experimental MV3DT display joins remain unqualified as production fused identities.

RF-DETR Medium is not the first change. Existing matched standalone batch-two measurements were about 9.423 ms for Medium and 8.247 ms for Small: about 1.18 ms saved in that benchmark, with an accuracy tradeoff. This is not an integrated FPS forecast. INT8/FP8, CUDA graphs and a smaller detector belong after attribution, not before.

Do not reintroduce the rejected inference-interval knob: this installed preprocessed-tensor path bypasses it. A real scheduler would also need prediction-aware map/speed and UI contracts. CPU quotas showed no sustained detector/gateway throttling in the audit; broad quota increases lack evidence. Live history is in RAM, and observation output fsync occurs at rotation, so per-frame SQLite/fsync is not the current explanation.

## Larger presentation architectures

1. **Live split deployment:** render Isaac on another suitable machine; send its two native RTSP feeds to Spark/Thor for actual live AI. This removes shared rendering/inference contention and matches camera-to-edge deployment. Measure end-to-end delay, synchronization and throughput; no speedup is promised.
2. **Explicit simulation replay with live AI:** pre-render a synchronized two-camera scenario and optional overview, replay it at a stable cadence, and run real detection/tracking/map/questions on Spark. Label it “Simulation replay · AI running live.” Do not fake boxes or claim interactive scene control. Loop/session/timestamp synchronization needs qualification. Keep live Isaac mode available when interaction matters.
3. **Dedicated smaller Kit experience:** preserve animation/streaming/native-policy dependencies while excluding unused authoring systems. A passive overview consuming an existing camera GPU drawable may avoid a third render; the normal interactive viewport must not be rebound to protected camera products. This is a separate startup design, not another unsafe live viewport-off probe.

## Short, meaningful verification plan

For each change, use the same deterministic scene phase or synchronized recording and comparable object load. Start with bounded 30–60-second matched controls, not a multi-hour qualification on every edit. Record native, analyzed, published and actually presented rates; median/p95 frame interval and age; batch occupancy; local/shadow object count; memory/queue bounds; exact-frame failures; and ID/event/map continuity.

Require real nonblack changing pictures. Counters alone accepted a failed black-image experiment previously. Do not repeat the known live viewport-off or native CPU-profiler stalls. Run native environment preflight for any environment opened later and preserve the original assets. Broad endurance and labelled accuracy checks follow promotion of a useful candidate.

## October 27: prioritized DeepStream documentation re-review

This section gives the current recommended order. The October 23 findings above remain historical evidence; several of their proposed fixes are now deployed. This pass reviewed the running worker arguments, generated inference/preprocess/tracker configs, worker and UI code, current status counters and previous trial receipts. No model, service, pipeline setting or simulator asset was changed, and no new GPU benchmark was run.

NVIDIA material consulted includes the development, configuration-audit, pipeline-profiling, MV3DT operation, RTSP inspection and stack inspection skills, plus relevant design-review, best-practice, tracker and profiling references. Public SDK 9.2 plugin documentation takes precedence over generic examples intended for other SDK versions or application shapes. The [reference manifest](qa/smart-city-deepstream-review-2026-10-27/references.json) records URLs and hashes of the downloaded skill material. This is a custom C++ pipeline/design review; the full `deepstream-app` config validator was not applied to an isolated `nvinfer` INI as though it were a complete application config.

### Current baseline and what is already done

- RF-DETR Medium 576×576, a locally built FP16-enabled TensorRT engine, batch range 1–2 with optimum 2; active mux/GIE batch size 2, source/mux geometry 960×540, tracker geometry 640×384.
- Every admitted frame currently reaches inference. Preprocessed-tensor input is enabled. The ordinary inference-interval knob was previously tested and proved ineffective in this path; the launcher explicitly rejects it.
- One native MV3DT tracking stage with its internal CUDA visual tracker. No separate camera-local NvDCF stage is active. Re-ID inference is disabled (`reidType: 0`), so reducing a Re-ID extraction interval is not an optimization of this deployment.
- GPU/NVMM conversion and tensor preparation are present. The source decoder is CPU-selected. The previously qualified NVDEC trial produced real results but did not establish a performance win in the shared simulation workload.
- No DeepStream OSD, tiler or display renderer in the worker; the sink is unsynchronized. The browser draws overlays. Simply applying the standard disable-OSD recommendation offers no new gain here.
- Source/preview queues are bounded; preview sends are independent by camera, obsolete previews can be replaced, and repeated event/trail metadata is already reduced. These deployed fixes should not be counted as future work.
- Both cameras currently report the `smart-city` profile with on-demand indexing, `indexingRequired: false` and embedding/indexing steps off. Registered caption resources alone do not establish active caption inference. Broadly stopping resident AI services is not justified by their presence in memory.

### Practical order of experiments

The order balances potential leverage, implementation effort and risk to the required people/vehicle tracking. It is not a measured ranking of bottlenecks. First take one short matched baseline of source, inference/tracker, publication and browser stages; then test one candidate at a time. NVIDIA recommends stage-level latency measurement before attributing a slow pipeline to a particular element. [SDK troubleshooting](https://docs.nvidia.com/deepstream/text/DS_troubleshooting)

| Priority | Change to try | Specific reason here | Effort and promotion condition |
| --- | --- | --- | --- |
| 1 | Run RF-DETR on every second admitted frame, keeping native MV3DT on every frame | Directly targets recurring inference work while retaining the Medium detector's pixel/detail budget. Every-third-frame processing is a later candidate. NVIDIA explicitly describes supplying frames without detector objects to the tracker between inference batches. | Medium: implement a real tensor/preprocess/inference scheduler, not just `interval=1`, and verify actual inference calls fall. Pass all frames through the tracker with honest inference-done/freshness metadata. The UI/map must support valid tracker updates between detections; fresh detector measurements must remain distinguishable for speed/events. Keep only if distant/new objects, occlusions and per-/cross-camera continuity remain acceptable. |
| 2 | Reduce exact-preview delivery overhead and separate preview resolution/rate from AI input | Current preview POST tails and replaced packets are a stronger immediate lead than JPEG encoding saturation. Smaller repeated metadata, less gateway/proxy work and a display-only 640×360 candidate can reduce CPU/serialization/download work without shrinking detector input. | Small to medium: retain exact source/session/sequence/timestamp joins and original coordinate geometry. Current native JPEG checks require source-sized output, so downscaling needs explicit contract changes. Do not increase queue depth to conceal stale frames or claim a WebRTC rewrite is necessary. |
| 3 | Check actual batch occupancy, mux wait and queue/buffer starvation | Batch two is already configured, but the active 10,000 µs mux timeout may emit partial batches depending on source arrival spacing. Matching dimensions and nominal batch counts does not establish that batches fill. | Small configuration trial after measurement: count full/partial batches and compare sensible waits against p95 frame age. Add decoder surfaces/pool capacity only if starvation is shown. Preserve capture timestamps, bounded queues and the existing cross-camera pairing checks. |
| 4 | Tune MV3DT's actual tracking workload if the trace shows it is expensive | The active visual module uses HOG/ColorNames, feature level 3, a 100-target/source allocation and shadow age 49. Per-target appearance work and shadow targets are relevant costs in a busy scene. | Moderate accuracy risk: inspect live/shadow load and test only supported backend settings. Compare ID continuity through occlusions/crossings before promoting any feature or lifecycle reduction. Target caps are hard capacity limits, not harmless speed sliders. Preserve native MV3DT and the calibrated tracker size. |
| 5 | Improve the GPU video/preprocess handoff where measured stalls justify it | The code has CPU decode/upload, full-frame RGBA conversion, a fused float resize/normalization kernel and a per-batch custom-stream synchronization. NVDEC/surface reuse and fewer conversions/waits are candidates, but no new speedup is established. | Start with a matched NVDEC versus CPU check only if stage attribution points there. A fused NV12-to-tensor path or asynchronous completion handoff is more invasive and should follow simpler wins. Preserve RF-DETR numerical preprocessing and buffer lifetimes; never simply remove the synchronization. |

Sources for these mechanisms: [tracker input on uninferenced frames](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker), [tensor-input interval caveat](https://docs.nvidia.com/deepstream/text/DS_RestServer), [mux timeout/batch behavior](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvstreammux), [decoder/surface/source controls](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvurisrcbin), and [conversion/memory semantics](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvvideoconvert).

### Current delivery evidence and interpretation

A read-only cumulative status sample in this review reported JPEG-selection-to-encode means near 3.9–4.1 ms, preview POST means near 27.6–32.7 ms, and POST p95 histogram upper bounds of 200 ms. About 8,283 images had been selected and encoded per camera; 273/282 obsolete pending packets had been replaced, with zero preview source-queue overruns or POST failures in that sample. This points toward delivery/matching/serialization investigation before replacing the JPEG encoder. POST duration includes server work and waits; it is not a measurement of network transport alone. These lifetime counters include changing scenes/startup and are not a steady-state bottleneck benchmark or capture-to-screen latency. A subsequent raw [status snapshot](qa/smart-city-deepstream-review-2026-10-27/preview-status.json) is retained separately.

### Important recommendations checked and deferred

- **Model/precision changes:** FP16 and prebuilt engines are already in place. The previous matched standalone Medium-to-Small batch-two comparison saved roughly 1.18 ms, with a detection-quality tradeoff. INT8/FP8 need an appropriate quantization workflow and scene accuracy checks; changing `network-mode` on a loaded FP16 engine does not quantize it. CUDA Graphs also require a supported execution path and evidence of launch overhead. These are later options, not assumed wins or immediate defaults.
- **Tracker shortcuts:** do not replace the native MV3DT file with the profiling skill's generic NvDCF `max_perf` preset or shrink 640×384 to its generic 480×288 recommendation without recalibrating/validating projection. The public tracker docs distinguish CUDA and PVA backends; do not infer that all backend feature restrictions or Jetson accelerator recommendations apply to Spark. Do not split the two cooperating views into tracker sub-batches merely because it is listed as a general throughput feature.
- **Memory knobs:** a profiling reference equates only memory type 0 with zero-copy, but SDK documentation also identifies type 2 as device CUDA memory. Our explicit device allocations are not, by themselves, evidence of a host-memory regression. Inspect actual surface conversions/copies, especially on Spark's unified-memory platform. A best-practices skill example also reverses INT8/FP16 numeric values; the SDK's authoritative mapping remains INT8=1 and FP16=2. [Inference properties](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvinfer)
- **Decoder frame dropping and ROI crops:** dropping before the tracker reduces the tracker update cadence too; it is a different tradeoff from skipping only inference. Cropping a road ROI or reducing source/model resolution can remove the distant people/vehicles the user wants to retain. These need explicit coverage/recall evidence, so they are not the first pass.
- **RTSP recovery:** source reconnection is an important availability improvement, particularly after the recorded simulator 404 incident. Start/Stop/Reconnect controls are now present. A later automatic source reconnect must reset/validate source clocks and tracking sessions; repeatedly reusing stale IDs/clocks for apparent uptime is not acceptable. This is reliability work, not a promised FPS increase.
- **Simulation/UI limits:** Isaac rendering and DeepStream share GB10. Record incoming camera rate alongside analyzed and displayed rate; the pipeline cannot display source pictures which were never rendered. Keep semantic work on demand. A current production UI package or a separate render machine may be later comparisons, but neither is required for this first DeepStream pass. Avoid known Kit viewport-off/profiler stalls.

For the first practical pass, prioritize the detector-cadence candidate and delivery work, then the inexpensive batch/queue check. Promote only measured improvements in current-frame delivery or resource use while retaining expected detections, tracking/association, map/events, clock identity and the saved memory reserve. No percentage FPS improvement is established by this review.

### October 27 implementation outcome

The user-requested optimization goal is implemented and validated in the [quality-first optimization receipt](smart-city-optimization-2026-10-27.md). Real inference cadence was implemented and tested, then restricted to offline trials after every-second-frame mode reduced exact-frame baseline box agreement to 87.6%. Preview envelope preparation now runs off the ASGI event loop; the first matched-configuration live windows reduced mean POST duration from about 25–29 ms to 15–19 ms. Pipeline/decoder diagnostics and explicit surface/low-latency controls are available. A 20 ms mux wait gave no measured rate gain. Tuned I/P hardware decoding passed repeated live starts but saved only about 0.05 CPU core, so CPU decoding remains selected given decoder-dependent box variation. The active configuration keeps RF-DETR Medium, every-frame detection, a 10 ms mux wait and one native MV3DT tracker with unchanged calibration/parameters. Both analyzed camera previews and map overlays were verified; 128 Python checks plus native/GPU controls passed.
