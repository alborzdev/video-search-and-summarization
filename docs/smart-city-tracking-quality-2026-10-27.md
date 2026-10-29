# Smart City native tracking quality — October 27

The selected detector remains RF-DETR Large, using the cached TensorRT FP16-enabled engine at 704×704, on every admitted camera frame. The application uses one NVIDIA MV3DT tracker with its internal CUDA DCF module. No separate NvDCF tracker or heuristic cross-camera ID aliases are added.

This audit separates detector classification, native track continuity, native world-position accuracy, and map presentation. The previous UI cleanup did not establish correct vehicle identity fusion. Vehicle fusion remains an experimental capability, with explicit limitations below.

## Controlled comparison

Two separate 60-second encoded camera cohorts from the same scene were retained with a separate read-only simulator reference trace. Each candidate sees the same encoded footage, calibration, static class priors and RF-DETR engine. Actual actor poses and reference identities are never mounted into the inference container or sent to analytics. The reference reads actual USD vehicle transforms and native person-agent world translations; a separate world-bound audit verified that vehicle transform origins coincide with footprint centers in XY.

The new offline mode preserves the original native SEI capture timestamps through exact access-unit PTS correspondence into DeepStream metadata. It is explicitly labeled `recorded-native-sei`, accepts file inputs only, and refuses HTTP analytics or preview posting. The analytics schema also rejects this offline clock basis. Live clock freshness checks remain unchanged.

Reference assignment uses a unique projected actor body/foot probe inside the original detector box. It does not select a reference by proximity to the tracker’s estimated world position. Missing tracker outputs stay in the co-detected denominator. Ambiguous image objects and unregistered actors remain unknown. Physical camera exposure/render latency is unmeasured; comparisons include −100, −50, 0, +50 and +100ms reference offsets. These conditional engineering checks are not HOTA, IDF1, complete detector recall, or general vehicle qualification.

The ordinary trials have identical raw detector input hashes within each cohort, after excluding the intentional internal association-class field. The ReID trial has small confidence/box differences in two of 1,352 frames, with no changed detection counts or classes; its comparison is therefore less exact. Six source-frame/PTS-verified image spot checks were rendered for correspondence review.

## Repairs

RF-DETR can alternate between car and truck on one vehicle. Native strict class matching then alternates or fragments target handles. Simply disabling class matching is unsafe in this integration: the installed `gst-nvtracker` source skips bounding-box and 3D-metadata updates when its detector and tracked classes disagree.

The explicit `car-truck-family-v1` input policy maps truck to car only inside native association, while keeping strict matching for people, buses and bikes. Exact current-object metadata retains the raw detector class and restores it after tracking, before native analytics. SDK-created peer or prediction objects cannot borrow another detection’s class or observation stamp. Raw classes and per-camera analytics remain intact. The map permits a car/truck label difference only when both current observations explicitly carry this native policy and pass all existing SDK-ID, clock, session, calibration, distance and visibility checks.

NVIDIA BodyPose3DNet is evaluated on person class 0 only, once at target creation. The pose model and TensorRT engine are SHA256-pinned; startup verifies both, and the engine is reused rather than built on restart. This improves geometric agreement for people without applying human pose inference to vehicles.

## Comparison and selection

Twenty-two completed paced comparisons were run across the two cohorts. The selected deployment uses the car/truck input policy, person-only pose refinement at keypoint confidence 0.75, and the original strict native peer gates: three common frames, match score 0.5 and one-meter fusion distance. ReID remains disabled after the reference model trial. The original class geometry and 10ms mux wait remain selected.

| Conditional measurement | Before | Selected |
| --- | ---: | ---: |
| Shared pedestrian IDs, first cohort | 307 / 557 (55%) | 446 / 557 (80%) |
| Shared pedestrian IDs, second cohort | 98 / 253 (39%) | 185 / 253 (73%) |
| Pedestrian pairs also within the one-meter map entry gate, first cohort | 255 / 557 | 348 / 557 |
| Pedestrian pairs also within that gate, second cohort | 77 / 253 | 163 / 253 |
| Observed pedestrian outputs, first cohort | 5,184 / 5,300 | 5,184 / 5,300 |
| Observed pedestrian outputs, second cohort | 4,068 / 4,135 | 4,066 / 4,135 |
| Native ID changes on evaluated pickups, first cohort | 107 | 2 |
| Native ID changes on evaluated cars, second cohort | 28 | 6 |
| Shared car IDs, second cohort | 74 / 251 | 75 / 251 |

The selected configuration has no wrong shared-ID pairs among the uniquely matched registered actors across either cohort at any of the five time offsets. Unregistered and ambiguous actors remain unverified. ID-change counts include native ID corrections and are not an IDF1 score. Position jitter is broadly unchanged; this is an identity/continuity improvement, not a claim that raw detector boxes are stabilized.

**Vehicle cross-camera sharing is still inadequate.** The car sharing result barely changes; median second-cohort car position error remains about 1.1m and bus error about 3.5m. Pickup shared-ID pairs in the first cohort decrease from 12 to 6 despite much better local continuity; the selected policy is not presented as a complete vehicle fusion fix.

The [machine-readable comparison](qa/smart-city-tracking-quality-2026-10-27/comparison.json) records metrics, model/image/configuration hashes, limitations and live checks. Both cohorts were used to compare candidates; there is no final blind third dataset, and no model weights were trained. The recorded comparisons use full batches, whereas the live pipeline receives partial batches. Live delivery and restart were verified; live identity accuracy has not been independently qualified with full image annotations.

A larger peer distance, including a longer five-frame history candidate, produced a wrong pedestrian join on the first cohort. The bus-only footprint-area prior lowered median bias but increased position steps over one meter from 13 to 57 and lost 16 observed bus outputs. Both were rejected. A 50ms mux wait reproduced the selected quality scores on both recorded cohorts and supplies no quality reason to add latency.

## Live deployment and rollback

The new hash-pinned bundle is `native/mv3dt-demo/tracking-quality-20261027`; worker image is `sha256:8ec3f40e06b0d6e6e9b91258b1519c51e5189e1b60ffcb5b6c1cefdc96d60633`. Both camera streams returned with native SEI proof and matching analyzed previews. UI Stop detections → Start detections passed, and both source sessions changed and recovered. No browser warnings/errors, SDK class-mismatch messages, or pose-engine rebuild were observed during those checks.

The sequential live windows measured about 12.24 and 12.41 analyzed FPS per camera before/after, with approximately 11 published preview FPS per camera. These are input-limited live windows, not maximum-throughput benchmarks. The saved 20GiB reserve and active guard were preserved; the lowest available memory across trials was about 35.5GiB. The RF-DETR selection and runtime tuning files are unchanged.

Validation passed: 168 Python tests, 52 scoped UI map tests, the app typecheck, 23 native capture-clock CPU control groups, native observation/class-policy checks, and real replay/live verification. The [live screenshot](qa/smart-city-tracking-quality-2026-10-27/live.png) shows both analyzed cameras after the UI restart.

Rollback: stop detections in the UI, restore `.spark/city/runtime/tracking-quality-20261027/active.before.json` to `.spark/city/state/native/mv3dt-demo/active.json`, restart `vss-city-controller-spark.service`, then start detections. The original bundle/image and RF-DETR engine remain cached. Deployment and rollback-profile hashes are retained in the comparison receipt.

Changes rejected during this audit include a global footprint-area radius change, permissive class matching, wider matching/fusion without adequate temporal evidence, person-pose confidence 0.925, and the person-trained reference ReID network as a default for mixed traffic. Lower keypoint confidence improves sharing but can reduce observation coverage; selection uses both metrics. Reducing common peer frames from three to two did not provide a useful improvement.

## Practical limits

NVIDIA’s native peer matcher compares calibrated 3D tracklets. Enabling ReID is not a direct replacement for that geometric association and does not correct biased world positions. The supplied reference ReID network is trained for people; no vehicle ReID model is claimed qualified here.

The native projection model provides a cylinder or square-base cuboid with per-class height/radius. It does not provide an oriented long rectangular vehicle footprint through the documented class-prior interface. Cars with different heights and long buses can therefore produce view-dependent center estimates even with the correct camera matrices. The road plane is at world Z −0.2m and vehicle roots at about −0.202m, so a common vehicle ground-plane offset is not the missing correction. People walk on elevated sidewalks around Z +0.01…+0.05m, which is another limit of a single flat native ground plane. Current static calibration and tracker-resolution scaling match the live scene; a stale calibration was not found. Exact handoff timestamps do not establish physical camera exposure alignment, which remains unverified. Illumination can affect detection/appearance, but these comparisons do not establish sun differences as the cause.

The map keeps native SDK identity and current native world-foot evidence. It does not average different anchors, create simulator-derived identities, or merge different SDK IDs by proximity. Remaining disagreements are visible rather than relabeled as successful tracking.

## NVIDIA sources

- [DeepStream 9.2 MV3DT](https://docs.nvidia.com/deepstream/9.2/text/DS_MV3DT): timestamp/frame alignment, MQTT peers, tracklet matching and measurement-fusion gates.
- [DeepStream 9.2 tracker](https://docs.nvidia.com/deepstream/9.2/text/DS_plugin_gst-nvtracker): multi-class 3D priors, pose class filters/confidence, ReID modes and reference model setup.
- [NVIDIA reference ReID model card](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/reidentificationnet): person-training scope and input format.
- [NVIDIA reference tracker configuration](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/config_templates/config_tracker.yml).

Runtime scripts preserve the active memory guard and the saved 20GiB Spark reserve, with four GiB additional admission headroom. Each GPU comparison pauses only the live city detector and restores it in a `finally` block. Simulator, VLM and other service budgets are unchanged. Original profile, configuration and image remain available for rollback.
