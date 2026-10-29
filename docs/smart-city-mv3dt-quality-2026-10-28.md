# Smart City MV3DT investigation — October 28, 2026

The application uses NVIDIA’s native multi-view tracker. There is one tracker stage, with NVIDIA’s internal CUDA DCF visual tracking, RF-DETR Large 704 TensorRT inference, person-only BodyPose3DNet, calibrated overlapping cameras and native encoded-frame capture evidence. Reliable shared identities for every traffic vehicle have **not** been achieved. Buses remain particularly poor. This investigation separates duplicate rendering from actual native association failures.

## Confirmed fixes

**The map split identities MV3DT had already shared.** It required camera positions to be within one metre before displaying one marker, even when both observations already had the same native SDK identity. In a fresh bounded live sample, 153 of 248 uniquely identified, simultaneously detected car pairs shared a native ID, but only 44 also had positions within one metre. Many successful native matches therefore looked like failed fusion.

The map now preserves one marker for the same qualified native ID and shows a dashed amber ring when camera positions disagree by more than one metre. Site, current frame, source clock proof, session, model, calibration, class policy, visibility and epoch checks remain. It uses a fixed camera representative; it neither averages positions nor merges different IDs by proximity. Historical homography-based joins retain their distance hysteresis. Invalid native positions remain withheld.

**A live RTSP join could stop detections before the first frame.** The join can receive a picture after its native SEI has already passed. The worker now drops at most eight incomplete startup pictures, within two seconds and before decode, only until the first proven picture. Malformed evidence, missing evidence in recordings, and missing evidence after the first valid picture still stop the worker. No timestamps or identities are fabricated.

**Source colour conversion differed from NVIDIA’s app.** The simulator recordings are full-range BT.709. Uploading NV12 before the mux and converting to RGBA afterwards produced slightly different model inputs. Per-source RGBA conversion before batching preserves the decoded source colour information. On exact first-picture PTS from both cameras, the corrected FP32 tensors are byte-identical to NVIDIA’s reference application. Mean RGB error against independent libav conversion falls from approximately 1.0 to 0.10–0.11 levels out of 255. The two-frame tensor check establishes conversion parity; it is not an accuracy benchmark. Observation and preview revisions identify this with `color=source-rgba-v1`.

**Short batch waiting can harm native association.** A controlled 35 ms difference in source arrival scheduling, with original images and capture evidence unchanged, made almost all batches partial. Native car sharing fell from 75/251 pairs to 26/248. A 50 ms mux timeout restored full batches and 75/251 sharing. This is stronger evidence than testing mux timeouts on already aligned arrivals. Live delivery and the selected final timeout are recorded in the deployment receipt below.

## Live comparison and display backpressure

The original 10 ms live window had 52% full batches. The 50 ms window had 98%. Its uniquely corresponding pedestrian pairs shared 507/520 IDs, cars 81/139, trucks 5/60 and buses 0/8. Median native car position error was 0.65 m and bus error 3.76 m. These are different traffic windows; they cannot establish a causal accuracy gain over the earlier 153/248 cars, 173/184 people and 0/42 buses. Three within-camera actor switches were observed in the new sample.

Longer live validation exposed CPU backpressure at the analytics/preview service: with the original 30 FPS preview ceiling, source-clock age grew and exact previews stopped publishing. Disabling temporary detector diagnostics alone did not resolve it. The 10 ms configuration restored fresh delivery; a separate 50 ms experiment limits display work while retaining per-frame detection/tracking. Final selection is recorded with the actual health samples, rather than treating successful startup or one short quality sample as delivery qualification.

## Analytics CPU changes

Frame-cache profiling identified generic deep copying as the main sampled ingest cost. Public track snapshots now copy through the C JSON codec, retaining nested isolation and the same wire values. On the same populated real track with a 40-point trail, the median of three 2,000-copy runs improved from 0.122 to 0.107 seconds (1.14×). Instrumented whole-replay timings exaggerated this relative to the uninstrumented microbenchmark; neither is a live throughput claim.

The UI’s SSE endpoint also constructed full state snapshots synchronously on the async request loop at 10 Hz per viewer. It now performs that work in the thread pool at 4 Hz. This is health/configuration/display-state delivery; durable observations, rules, tracking and exact-frame preview correlation remain unchanged. Tests verify another async request can progress while a slow snapshot is built. All 328 analytics tests pass, including nested snapshot isolation and existing history/preview/clock contracts.

The final combined setup passed a roughly two-minute live check with the browser open: **50 ms mux timeout, 8 FPS preview ceiling, diagnostics off, CPU decode, detection on every admitted frame**. After warmup, all batches were full; detector throughput was 24.48 total frames/s across both cameras. The exact analyzed previews published 7.07 and 7.19 FPS. Reported producer-capture-to-ingest age had median 126 ms and maximum 284 ms over the sampled window; this is not physical exposure-to-screen latency. Minimum available memory was 29.23 GiB with the saved 20 GiB guard active. Full-rate preview experiments that accumulated delay remain rejected.

The immutable worker image is `sha256:fcadb80034cdc8673073d6c32022a3c159abfc0c07b72f8db7c58dd4a4823ea8`. The backend uses the source-mounted `engine.py` and `main.py` hashes in `final-selection.json`. This image includes its current worker source, tests and source manifest. The selected native tracker configuration and model weights are unchanged; ReID remains disabled. Reliable vehicle identity remains unqualified.

## Native tracking limits and rejected changes

The native tracker’s calibrated 3D feet remain view dependent, particularly on long vehicles. The supplied class geometry uses approximate cylinder priors. Matching static camera matrices and image resize conventions does not establish correct shape fitting for every bus/SUV/rider. The current bus frequently alternates between raw bus and truck detections, producing different native tracks. The existing explicit car/truck family handles SUV ambiguity while retaining the raw detector class, but does not include buses with their different geometry.

NVIDIA’s `checkClassMatch` is global across local association, trajectory management and multi-view association. A private class-agnostic experiment reduced bus ID changes dramatically, but harmed pedestrian sharing and motorcycle coverage, and still did not produce shared bus identities. It was rejected. No patched NVIDIA plugin is selected.

Controlled replay results used the retained train and holdout-labelled recordings. Both have now been used for tuning; neither is a blind final test. Pair counts are conditional on unique raw-detector image/body/foot correspondence to an independently recorded real simulator actor. They are not general precision/recall, HOTA or IDF1.

| Experiment | Observed result | Decision |
| --- | --- | --- |
| Peer match threshold 0.45, fusion gate 1.25 m | Holdout car sharing 75→128/251; train pedestrian sharing 446→267/557 | Reject |
| Larger car/bus radii | Holdout car sharing 33/251; bus position jumps worsen | Reject |
| Larger DCF feature image | Fewer matched pedestrians and lower sharing | Reject |
| Lower new-target IoU gate | Loses pedestrian observations without useful ID gain | Reject |
| Lower size-similarity gate | Little change | Keep existing |
| Per-camera tracker sub-batches | Wrong ID collisions with nonunique IDs; unique IDs remove collisions but sharing worsens | Offline only |
| Synchronous peer messages with source frame counters | No worthwhile gain in full/partial batches; additional synchronization dependency | Keep existing |
| Smaller Kalman process noise | Strong smoothing reduces car sharing 51→36/247; moderate change is marginal | Keep existing |
| Class-agnostic matching/private metadata exporter | Bus local changes 222→0 in one clip, but train pedestrian sharing 446→306/557; bus cross-camera sharing remains zero | Reject |
| Source RGBA colour correction | NVIDIA input parity; holdout car sharing 75→51/247, train pedestrian sharing 446→270/563; raw coverage slightly changes | Correctness fix with explicit tracking regression; further general accuracy unqualified |

The colour correction exposes substantial native association sensitivity to small detector changes. It must not be described as a demonstrated tracking improvement. Conservative matching gates remain because looser settings improved one sequence at the expense of another. Detector skipping, hardware decoding and larger models were not promoted by this investigation.

## Source service failure during live validation

The final restart initially failed on both the new and previous worker because the registered RTSP URLs were unavailable. The simulator was still publishing. Docker confirmed the existing VIOS stream-processing service was OOM-killed at its unchanged 2 GiB container limit. Its state and logs were preserved; the canonical recovery restored the same existing service and both registered RTSP ports. No model/container limit or reserve was increased. This is a separate live-service capacity limitation, not evidence of an MV3DT matching failure or sustained full-stack qualification.

## Independent NVIDIA and timing checks

The selected low-level tracker library is byte-identical to the pinned NVIDIA DeepStream image (`24a960f66b721b2dda4db360a5620b9ed19df65ef4e69eb093eceb9b8e708c22`). The unmodified NVIDIA `deepstream-test5-app` ran with the documented custom detector/preprocessor, static calibration and the NVIDIA compatibility entrypoint. Against the corrected worker, all 27,469 raw detections matched by class and box IoU ≥0.99 over 1,330 source frames. This confirms the detector adapter and source colour path match the reference application.

The reference with the application’s tracking configuration also exhibited roughly metre-scale car position error and large bus error. KITTI exports do not carry the worker’s exact detector-object stamps, so reference identity rates cannot be treated as directly equivalent to worker accuracy. The stock warehouse tracking defaults are not a qualified traffic configuration: many pedestrian/bus outputs did not yield unique usable correspondences or world positions.

Earlier reference attempts bypassed NVIDIA’s entrypoint and failed CUDA forward compatibility (unsupported PTX toolchain), despite an application-success message. Those empty runs are invalid controls. The repaired launcher checks positive detections and retains compatibility initialization.

All paired producer frame counters in the two retained recordings carried equal simulator timestamps. The matrix resize agrees with the installed plugin’s independent x/y scaling. No simple camera ordering, projection-resize or large relative simulator clock error was found. Producer handoff time is not independently measured physical exposure time. Lighting can affect detector boxes; it does not explain the confirmed map duplication of an already shared ID.

ReID remains disabled: the available person appearance model is not a qualified vehicle model, and the native peer matcher uses calibrated geometric tracklets. Enabling person ReID globally is not evidence of better cross-camera vehicle association. Human pose inference remains explicitly scoped to people.

## Evidence, checks and rollback

Full experiment commands, immutable images, static config hashes, observations and resource receipts are in `.spark/city/runtime/mv3dt-diagnostics-20261028/`. Key records:

- `color-parity.json`: exact-PTS tensor comparison.
- `runs/*/receipt.json`, `analysis.json`: controlled trials, including rejected candidates.
- `runs/nvidia-default-reference-qualified/reference-analysis.json`: independent NVIDIA application and raw-input parity.
- `clock-alignment.json`: producer clock comparison.
- `live-mux10/`: frozen original live sample; clock basis remains `source-native-sei`.
- `final-deployment.json`, `live-final50/`: completed tracking-quality capture; its unrestricted-preview delivery configuration was subsequently rejected.
- `final-selection.json`, `live-delivery-optimized.ndjson`: selected configuration and passing bounded delivery measurements; prior delivery trials are retained separately.
- `active.before.json`, `tuning.before.json`: original selection; `active.before-final.json` and `tuning.before-final.json` preserve the startup-repaired checkpoint.

The read-only capture and freeze tools keep simulator actor traces outside inference and the backend. They require an unchanged profile, completed independent capture, one uninterrupted tracking epoch/session/model, advancing native clocks, bounded frame gaps, trusted log generations and no duplicate observation rows. New captures bind runtime tuning and actual worker arguments. The evaluator reports within-camera actor identity switches as well as cross-camera collisions; zero observed cross-camera collisions does not imply perfect tracking.

Scoped checks: native worker build; 24 CPU native-clock control groups; six-class native metadata, uint64 ID and no-separate-stage controls; bounded tracker diagnostics; 54 Python evaluator/profile/frozen-window checks; map grouping/rendering tests and app TypeScript check. Browser validation at `http://127.0.0.1:7782/?workspace=smart-city` used the CUA in-app browser/Playwright surface (1280 × 720). The page identity, meaningful content, absence of framework overlays, empty warning/error console, map key interaction and canonical **Stop detections → Detections off → Start detections → Detections on · 2 cameras** sequence passed. Both feeds displayed exact matched analyzed frames. A shared native person ID rendered as one map marker with two original member IDs; a later click on that moving marker timed out after the live object changed. Shared-vehicle rendering and position-disagreement rings have unit coverage; broad vehicle fusion did not pass. The final screenshot is `/tmp/smart-city-mv3dt-live-20261028.png`; private browser results are in `browser-qa.json`. Mobile and other browsers were not tested.

Verification commands used the current DeepStream image for `make city-worker native-capture-clock-test native-mv3dt-test tracker-diagnostics-test`, the source-mounted UI for its scoped Jest suites and `tsc --noEmit --incremental false`, and the control Python environment with temporary test dependencies for the city analytics suite and evaluator/profile/frozen-window suites. No test dependencies were installed into running services. The saved Spark reserve remains **20 GiB**, guard active, unchanged model/container budgets. Thor configuration is untouched.

To roll back, stop the managed detector using its canonical controls, restore the chosen saved profile and runtime-tuning files, then start it again. Keep pinned static bundles and model files intact. A new worker epoch is expected. Reverting the map would reintroduce duplicate rendering for shared IDs with disagreeing positions.

Primary references: [NVIDIA MV3DT](https://docs.nvidia.com/deepstream/9.2/text/DS_MV3DT), [native tracker configuration](https://docs.nvidia.com/deepstream/9.2/text/DS_plugin_gst-nvtracker), [official reference application](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/README.md). NVIDIA’s DeepStream development, tracker configuration and MV3DT workflow skills were consulted alongside the installed plugin source.
