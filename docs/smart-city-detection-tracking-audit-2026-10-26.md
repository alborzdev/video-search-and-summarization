# RF-DETR and native MV3DT audit — October 26, 2026

The current implementation passes the tested detector/preprocessing/provenance checks. It is **not yet qualified as the best configuration for the simulated intersection**, because that requires independently annotated scene footage, including small people, bicycles/motorcycles, occlusions, and cross-camera identities. Published-ID gaps are diagnostics, not measured identity switches or detection recall. No UI smoothing, detector threshold, tracker policy, live source, or simulator scenario was changed by this audit.

## Checks and findings

- The active detector is RF-DETR Medium, engine SHA256 `9228a9c88bbde75a867b0ed92bd400da520e9b867baf855ea7343ce3c60866b0`. It runs every frame at 576×576, using RGB float/ImageNet normalization and the checked sparse COCO mapping. Global query/class top-300 happens before capability filtering, followed by the existing one-city-class-per-query policy. No spatial NMS was added. A CPU check of a global-class-exclusive alternative found identical results at 0.20/0.35/0.50 on the pinned 100-image proxy; this is not a reason to change the live parser.
- The CUDA kernels passed CPU-reference parity, including nontrivial row pitch, unequal image dimensions and odd source extents. The test uses NVIDIA's compatibility entrypoint; bypassing it on this host gives invalid test results. This is a kernel/reference test, not independent verification of every possible camera's color calibration.
- Exactly one native MV3DT tracker is configured. Its internal DCF uses CUDA. Neither a separate NvDCF stage nor a 2D fallback is present. Per-camera MQTT channels are reciprocal and were isolated into unique audit topics for testing. The production MQTT topics were not written by the tests.
- The 640×384 tracker matrices are scaled from the calibrated 960×540 projections. Their maximum absolute element differences from the expected scaled matrices are `4.55e-13` and `2.50e-12`. A mismatch between tracker and source dimensions is not itself an error when the projection matrices are scaled consistently. Reprojection consistency does not prove that the estimated cylinder foot belongs to the correct object.
- SDK source review confirms an associated detection reuses its input `NvDsObjectMeta` through `associatedObjectIn->pPreservedData`. Tracker-generated objects receive negative detector confidence. The new per-input audit verifies this exact relationship rather than assigning objects by IoU or proximity.
- The active tracker parameters are largely inherited and have not been optimized against labeled intersection identities. `minDetectorConfidence≈0.059` and `tentativeDetectorConfidence≈0.077` are both below the detector's 0.35 cutoff, so the nominal low-confidence association path does not receive detections in that lower range. This is a tuning opportunity, not proof that a particular replacement threshold is better.
- Fixed class geometry is used, with no learned ReID or body-pose model. This preserves the tested workload but does not qualify distant-person feet, vehicle shape approximations, or cross-camera identity accuracy. Adding networks or changing tracker resolution requires separate resource and accuracy checks.

## Actual paired native replay

Four isolated runs used the same retained two-camera encoded files, same RF-DETR weights and calibrated native MV3DT architecture. Each produced 600 frame observations. We compared only the **599 identical per-camera source frame/PTS/image-size records shared by all runs** (299 southwest and 300 northeast). The independent files do not have a qualified shared physical replay clock; this experiment makes no claim about cross-camera ID correctness. The source frames cover approximately 18.4 seconds per view.

| Configuration | Detector inputs | Current detector inputs returned by SDK | SDK confidence without a current stamp | Published-ID disappearance/return gaps |
| --- | ---: | ---: | ---: | ---: |
| Current cutoff 0.35 | 6,287 | 6,016 | 0 | 221 |
| Cutoff 0.20, otherwise current tracker | 10,127 | 9,169 | 0 | 571 |
| Cutoff 0.20, tentative-detection boundary 0.50, probation 4 | 10,128 | 5,751 | 0 | 34 |
| Current configuration repeated | 6,287 | 6,016 | 0 | 221 |

The small difference in input counts between the two 0.20 runs should not be interpreted as a tracker effect: asynchronous batching/mixed batch sizes and FP16 numerics can change borderline detections. The baseline and repeat returned the same counts. Counts and gap metrics alone cannot rank accuracy. A tracker can look smoother by refusing to publish real objects. For example, southwest published motorcycle observations fell from 60 to 12 under the stricter candidate, while person observations fell from 1,418 to 1,360. We did not promote either candidate.

There were zero current-stamp/SDK-confidence disagreements, duplicate input ordinal associations, or ambiguous output IDs in the compared frames. Baseline SDK output included one explicitly unobserved prediction. Its other 271 detector inputs not returned as current objects can reflect ordinary late activation, association filtering or shadow tracking. They are not evidence of exporter metadata loss and are not labeled false detections. The audit does not expose all internal SDK shadow state.

## Labeled detection threshold check

The existing hash-pinned TensorRT batch-two outputs were re-scored against the same 100-image COCO road subset and crowd-ignore rules, at IoU 0.50 and max 100 detections per image/class. This uses the current one-city-class-per-query policy. These fixed-threshold metrics are not AP and are not accuracy measurements on the simulated intersection.

| Detector cutoff | Six-class micro precision | Six-class micro recall | Person precision | Person recall |
| --- | ---: | ---: | ---: | ---: |
| 0.20 | 57.2% | 84.3% | 64.3% | 84.8% |
| 0.35 (current) | 82.8% | 75.3% | 87.5% | 75.7% |
| 0.50 | 94.3% | 66.0% | 94.6% | 65.3% |

Lowering the cutoff alone is a substantial false-positive trade-off. Raising it loses many already difficult objects. A scene-qualified decision needs class/size-specific precision/recall and physical identity annotations, not visual calmness alone.

## Code changes and validation

The worker's opt-in `--tracker-diagnostics` now captures bounded detector inputs before tracking and reports exact SDK output stamps, confidence, input ordinals and rejected/untracked identities. The existing diagnostic `detectorObservedThisFrame` field now uses the same exact provenance rule as production when running native MV3DT; positive SDK confidence alone is insufficient. Production object selection, IDs, scores and boxes are unchanged. Input snapshots are retained only when diagnostics are requested.

`tools/smart-city/summarize_native_tracking_audit.py` validates complete snapshots and source/epoch sequences, then reports provenance conservation and clearly scoped ID-gap diagnostics. Four Python tests cover missing stamps, omitted inputs, epoch resets and invalid/partial evidence. The native C++ controls cover the actual callback, all six RF-DETR classes, SDK frame-number replacement, 64-bit IDs, omitted tentative inputs and positive-confidence objects without current stamps. The test fixture clears recycled metadata callbacks before borrowing static payloads.

These source changes were built and tested in the isolated worker, not installed into the live detector. They provide audit evidence and do not purport to fix detection quality by themselves.

Artifacts live under `.spark/city/runtime/detection-tracking-audit-20261026/`: exact source/build hashes, `gpu-parity.log`, `baseline/`, `lower-threshold/`, `two-stage-confidence/`, `baseline-repeat/`, `common-frame-manifest.json`, `paired-comparison.json`, `threshold-coco-results.json`, input-file hashes and each bounded test's command/guard receipt. The Spark guard remained active at its saved 20 GiB floor; tests stopped below 24 GiB and sampled no lower than 34.4 GiB during native replay. The live RF-DETR selection/profile were not replaced.

## Qualification to do next

Annotate a held-out paired intersection clip at the exact encoded-frame clocks. Include true visible boxes, physical per-camera trajectories, cross-camera identity pairs, and occlusion intervals; keep simulator actor information exclusively in the evaluator. Score detection precision/recall by class and size, then identity/continuity errors and ground-position errors using the same native pipeline. Trial lower association thresholds with stricter births and improved distant-object pixels or detector resolution only against that evidence. This is required before calling a configuration better or promoting it to the default.

References used: [NVIDIA DeepStream development skill](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-dev/SKILL.md), [code-review route of the configuration auditor](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-audit-config/references/design_review.md), [tracker configuration reference](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-dev/references/tracker_config.md), and [NVIDIA native MV3DT configuration template](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/config_templates/config_tracker.yml). Reference sample values describe their own models/scenes and were not copied blindly into this application.

## October 27 camera presentation follow-up

The camera overlay previously re-ranked its eight class labels by bounding-box area on every frame and independently chose above/below placement. Small changes could replace a label or move it to the other side even when the detection remained present. The new `cameraLabelLayout.ts` retains label priority and placement within the current camera/session/model/configuration/analytics epoch. A small position deadband affects text only. Suppressed labels need 180 ms of clear space before returning; distant labels use separate entry/exit size thresholds. Selection always receives priority. Preference history expires after 400 ms, resets on backward time/seek or geometry changes, and never supplies visible labels for missing, stale or predicted-only observations.

Car, truck, bus and generic vehicle detections use the overview label **Vehicle**. This is deliberately a broader display category: it does not fix detector class confusion, merge class-dependent tracker IDs, or change rule classes. The raw class and confidence remain available in the box tooltip and existing track inspector. Detection boxes still use the current exact frame coordinates without smoothing. Smaller text and unbordered label backgrounds reduce clutter while keeping every current box in the overlay.

Validation used the existing source-mounted `vss-city-polish-ui`, without restarting inference or changing memory/model/tracker budgets. Four affected Jest suites passed (67 tests), and the app's strict TypeScript check passed. Tests cover jitter, label admission/ranking, collision recovery, precise box preservation, class/category separation, distant-object selection, missing observations and epoch/clock resets. Browser verification at `http://127.0.0.1:7782/?workspace=smart-city` showed both cameras using `exact-processed-frame`, no console warnings/errors, and original class/confidence/local ID in the inspector. One sampled frame retained 39 boxes with eight visible label elements across both cameras; that is a point observation, not a continuity benchmark. Evidence: [live overview](qa/smart-city-labels-2026-10-27/overview.jpg), [selected distant car details](qa/smart-city-labels-2026-10-27/details.jpg).

The held-out detector/physical-identity evaluation above remains necessary before promoting a larger model or claiming better detection/tracking accuracy. Presentation cleanup does not provide that qualification.

## October 27 simulator restart recovery and detection controls

The restart incident left both cameras registered but the detector stopped. `.spark/city/runtime/detector-20261027T150034Z.log` records an RTSP 404 from `source1`, followed by worker exit 1 and zero published observations in that attempt. The host controller intentionally renews only successfully completed live segments; it does not automatically retry failed workers. Agent desired-state status still reported analysis active, which did not establish that a worker or fresh analyzed frames existed. Restarting the simulator therefore did not by itself recover detections.

Smart City now has visible **Start detections**, **Stop detections** and **Reconnect detections** controls above the cameras. The new bounded, local controller operation stops/restarts the shared RF-DETR/MV3DT/analytics worker without removing the registered cameras, their calibration, rules or VIOS recording. It retains an explicit off setting in `controller-detections.json`; source reconciliation and scenario preparation cannot silently override that setting. Start/reconnect use the existing guarded cold-start recovery path. Worker failures still require an explicit retry. The HTTP analytics container receives no Docker socket.

`GET /api/v1/detections` reports the actual worker state separately from resource readiness. Its same-origin UI adapter strips camera URLs and accepts only start/stop/restart writes. The UI shows detections on only when all registered cameras have fresh accepted displayed frames, and offers reconnect if a running worker is waiting for frames. Failed control/admission requests remain visible rather than optimistically showing success. Stop additionally checks container state when the Docker stop command fails, so an unconfirmed stop cannot be reported as off.

Validation: 37 CPU controller tests and 46 affected UI/API tests passed; the app TypeScript check and scoped Python lint passed. Added coverage includes failed-worker recovery, idempotent starts, durable pause, calibration/rule preservation, reconciliation while paused, memory admission refusal, stop failure, invalid requests, URI stripping, pending/double actions and stale site completions. The existing source-mounted UI was used at `http://127.0.0.1:7782/?workspace=smart-city`; only the CPU controller service was reloaded to activate its new endpoint. Spark's guard stayed active at 20 GiB; model, tracker and container budgets were preserved.

The new UI recovered the failed worker, then passed a live stop/start and reconnect check. During off, there was no detector container, zero overlay boxes and two configured cameras with both original calibration revisions. After reconnect, both cameras again used exact processed-frame overlays with current detections and map observations. Detections were left on. Screenshots: [off](qa/smart-city-detection-controls-2026-10-27/off.jpg), [recovered live view](qa/smart-city-detection-controls-2026-10-27/on.jpg). These are bounded recovery checks, not a new sustained-ingestion qualification.
