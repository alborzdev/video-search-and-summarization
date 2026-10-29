# Defense workspace: UI and implementation plan

Updated 2026-10-22. Route: `/?workspace=defense`.

## Delivered now

Defense is an additional workspace inside the existing Vision Intelligence application. The original sidebar is retained, with one Defense entry. The workspace has three distinct layouts: site event review, drone survey/image comparison, and vehicle camera awareness. Presentation Mode uses the existing shell control.

The current data modes are **Design preview** and **No sources connected**. Seven generated illustrative stills support layout review before Isaac footage exists. Events, times, footprints, annotations and sample answers are authored examples. None are inference results. Switching to disconnected mode clears preview evidence. An unavailable vehicle camera shows an empty state instead of another camera's image.

Working interactions include scenario switching, event cue selection, local preview acknowledgement, evidence review, image enlargement, survey-to-finding navigation, two-image comparison, camera selection, editable report notes and preview JSON download. Reports contain explicit illustrative provenance and limitations. Notes and acknowledgement are local component state, not durable records. Closing the draft discards its notes. Selecting an event cue does not seek these static illustrations.

The source-readiness panel links to existing VSS camera management. Missing footage, calibration and capture-controller dependencies are explained in the relevant controls. No operational alert, report, camera command or model request is sent by the Defense preview. The existing global service-readiness indicator describes VSS services; it does not mean a Defense source is connected.

Main implementation: `services/ui/apps/nv-metropolis-bp-vss-ui/components/vision-intelligence/DefenseWorkspace.tsx` and `defense/`. Generated images and exact prompts are under `public/defense-preview/`.

## Recommended implementation, grounded in the current repository

The [independent Defense model review](defense-model-research-2026-10-22.md) updates the selection below: treat RF-DETR as a baseline, compare PeopleNet for fixed RGB site views, use custom debris training plus tiled inference for drone inspection, and evaluate ESS stereo depth for vehicle awareness. Thermal/Prism and compact reasoners are separate candidate branches. No candidate has been promoted by this research alone.

The [Smart City as-built record](smart-city-as-built.md) is the source for what is already deployed and tested. Reuse its services and frame/evidence safeguards; keep the Defense task layouts independent.

| UI promise | Starting components | Work still required |
| --- | --- | --- |
| Person entered a defined site zone | Existing RF-DETR Medium 576 TensorRT engine, NvDCF CUDA tracker, DeepStream 9.2 analytics, authoritative Python rule engine | Defense analysis profile, source/zone configuration, exact-frame UI adapter, event acknowledgement persistence and real entry/exit evaluation |
| Ask what happened and review evidence | Existing VIOS recording, scoped clip service, Cosmos3 Nano NVFP4 analyst endpoint and Cosmos Embed search | Bind each question to the selected source/session/time interval; retain returned evidence with the answer; handle expired clips, errors and unsupported answers |
| Find a possible loose object on an apron | A task-specific detector; RF-DETR fine-tuning is a practical first candidate using the existing export path | Labelled object/background data, held-out evaluation, appropriate image resolution or tiling, new TensorRT engine, finding association and review state |
| Compare inspection captures | Recorded stills/clips with capture IDs, camera intrinsics and timestamped camera pose | Capture service, target/viewpoint association, image quality checks and valid map projection; preserve both images and their provenance |
| Show what is around a vehicle | Existing detector and camera-local tracker on independently identified camera streams | Vehicle analysis profile, per-camera health and exact-frame rendering; synchronized calibration/depth only when metric position or fused identity is promised |

[DeepStream analytics](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvdsanalytics) provides ROI and crossing primitives over detection/tracking metadata. Its bottom-centre anchor is useful for ground rules; it does not establish identity, authorization or exact collision distance. The current six road-user classes do not establish a general debris or damage detector.

[RF-DETR](https://github.com/roboflow/rf-detr) supports task-specific fine-tuning. Treat a debris model as a new training/evaluation effort, not a configuration change that makes the present road-user model recognize every object. Pin the checkpoint, licence, training data, export/preprocessing version, engine hash and device compatibility.

[VSS](https://docs.nvidia.com/vss) supports real-time vision, semantic search and downstream answers/reports. For this implementation, the existing local endpoints are preferable to adding a second inference stack. Structured detector/rule records supply event facts; generated prose is a review aid. The existing as-built report records limitations in fine visual descriptions and counting, so do not use a VLM to certify clearance or issue immediate proximity decisions.

## Drone: implementable scope

Start with **visible loose-object review on an airfield service apron**. The first pass selects a candidate; the operator compares a closer capture and writes a review. A model score is not a measured probability of danger. Do not label the surface clear solely because no detections were returned.

Choose camera height, focal length and output resolution from the smallest object that must be visible. Evaluate recall and false alarms by object size, background, lighting, blur and occlusion. Synthetic Isaac footage can test the pipeline; generated UI stills are not validation data, and simulated accuracy does not establish real-world accuracy.

The overhead view is a static reference map. It is not a live satellite feed or automatically reconstructed terrain. Real footprints need timestamped pose, intrinsics, map coordinates and a ground plane or terrain intersection. Mark uncertain/occluded regions separately. Captured area and adequately inspected area are different measurements. The present preview polygons are illustrative.

For the first sim demo, use bounded, preconfigured camera viewpoints and an explicit capture request/result service. Implement request states `requested`, `accepted`, `capturing`, `complete`, `failed`, `cancelled`; only a returned capture ID enables the new image. UI success must not be inferred from sending a command. Scene Director proposals still require human review. Before Kit opens an environment, apply `marble.importer.native_policy.ensure_native_environment`; native ParticleField rendering remains mandatory.

A full flight-physics stack is not needed to prove the camera-to-finding workflow. Add Pegasus/PX4 only if flight behaviour itself is part of the demonstration, after a separate Isaac-version compatibility check. A future compatible physical drone could use [MAVSDK gimbal controls](https://mavsdk.mavlink.io/main/en/cpp/guide/gimbal.html); availability of that API does not establish support for a particular aircraft or authorize flight.

## Vehicle: implementable scope

Start with independent front/rear/side camera views, person detections and per-camera alert regions. Camera-local IDs must stay scoped to camera and source session. Show disconnected/stale/occluded views explicitly. Keep the schematic vehicle diagram separate from a measured occupancy map.

To add reliable metric distances, first obtain and validate camera intrinsics/extrinsics and an appropriate depth source. Flat-ground projection has a limited valid region. Stereo/depth plus pose can support a measured local map. [Isaac ROS cuVSLAM](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_visual_slam) is a possible visual-odometry component; [nvblox](https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_nvblox) is a possible reconstruction/costmap component. Neither is required for the initial camera UI, and neither is installed or qualified by this change. Check supported OS/BSP/ROS combinations and the actual camera configuration before selecting them.

Cross-camera identity and a stitched bird's-eye view need separate synchronization, calibration and association validation. An overlay alone does not supply these. This demo provides operator awareness; it does not implement braking or certified collision prevention.

## Backend adapter contract to build next

The current `DefenseSnapshot` only supports illustrative and disconnected states. Adding recorded/live operation requires a real adapter and expanded state model, not simply changing a label or supplying an RTSP URL.

Reuse the existing Agent camera registry, VIOS evidence path, native processed-preview envelope and HTTP/SSE pattern. See [data contracts](smart-city-data-contracts.md), [camera handoff](smart-city-camera-handoff.md) and [preview contract](../services/analytics/behavior-analytics/apps/city/PREVIEW.md). Avoid introducing another registry, message broker or GPU decoder solely for Defense.

The adapter must provide:

- Source health: source ID, session/epoch, mode, last accepted frame time, clock trust, stale/error state and dropped-frame counters.
- Frame identity: exact source/session/sequence, original image dimensions, timestamp, model/preprocessing identity and paired image/metadata. Hide overlays if pairing fails.
- Events: durable event ID, local track scope, rule and calibration revisions, onset/activation time, evidence references and acknowledgement history.
- Inspection captures: immutable capture ID, original media, camera geometry, pose/map frame, quality flags and viewpoint request state.
- Evidence/answers: selected source and time window, retained server-issued media reference, request state, model identity and limitations. An old event must never silently ask about the current camera window.
- Reports: durable backend record plus evidence references, analyst notes and export provenance. Keep preview exports out of that store.

Keep human-review state distinct from detection state. Keep unknown/no data distinct from zero detections. Abort or clearly mark a draft if the source/session changes while a request is in progress.

## Build order and acceptance gates

1. Site: connect one actual camera, one zone, matched observations and a retained event clip. Verify entry, exit, occlusion, duplicate suppression and reconnect/session reset. Then connect Ask and durable reports.
2. Vehicle: add the separate camera profile and stale/offline states. Verify camera names, orientation and annotations against the exact displayed frame. Add metric geometry only after calibration/depth tests.
3. Drone: establish smallest visible object and camera geometry, collect data, evaluate the detector, then implement capture/result and comparison. Add map footprints only when pose and projection are valid.

For each, measure end-to-end source-to-display latency, sustained stream rates, event delay, evidence alignment, false alarms, missed events and concurrent Ask load on the actual target. Record source-clock uncertainty separately from network arrival time. Existing Spark replay receipts are useful engineering evidence, not Defense or Thor qualification.

Preserve memory guards: Spark's saved 20 GiB reserve and Thor's separately selected 10 GiB reserve. This UI change does not alter model budgets, restart inference or qualify a full booth day. Engines and concurrent workloads need separate Anvil-T5 testing.

## UI verification

Scoped app TypeScript and Defense/route Jest tests are required. Browser checks cover scenario navigation, evidence review, image comparison, missing cameras, disconnected mode, report drafts, existing Smart City navigation, Presentation Mode and responsive layouts. The JSON download dispatch can be checked in the browser; a success message does not prove a file was saved by the client. Final receipt and screenshots are stored outside the repository in the task's `defense-implementation` visualization directory.

The source-mounted Spark dev UI serves this change. The last built image is older. Returning the helper to built mode will hide Defense until the app is packaged; no production-image refresh is claimed here.

## Defense trade-show explainer (2026-10-22)

Open **Defense → How it works**, or `/?workspace=capabilities&story=defense`.
The general VSS explainer also links to the Defense story. The existing sidebar
and Smart City story are preserved. The new nine-step narrative covers:

1. Three products from camera input: site event, inspection finding, vehicle warning.
2. Site boundary detection and an operator event with source/time context.
3. Drone first-pass inspection followed by point and mask comparison.
4. Rear/side camera awareness, including an explicit unavailable front view.
5. Evidence handover and the local-compute deployment target.

The pinned presentation supports scroll, chapter jumps, previous/next, keyboard
navigation, a timed loop, reduced motion, and pause on interaction or hidden tab.
Use the existing Presentation Mode for the booth. The inspection and final
chapters open the actual Local vision inspector. On inspection, it can capture
the displayed source image and run a fresh local request.

The illustrated story does not trigger live events or control a drone. Its
segmentation slide is different: `public/defense-story/panel-input.jpg` and
`panel-mask.png` preserve a real Moondream 2 / Photon → SAM 2.1 Tiny result on an
AI-generated source image. `panel-result.json` records model identity, input
hash, point and measured timings. The displayed 637 ms is that one warm model
request on Spark, not end-to-end stream latency or Thor performance. A fresh
browser request through the explainer also returned one mask (691 ms observed
request time). Real source footage, operational rules and durable Defense
reports remain the integration work described above.

## Defense briefing revision — 2026-10-22

The first explainer did not adequately connect camera analytics to an operational need or explain why Anvil belonged in the system. Its isolated panel mask was an inference example, not a compelling inspection mission. Small scenes and a product image at the end made the hardware feel incidental. This revision replaces that narrative and its visual composition at `/?workspace=capabilities&story=defense`.

### Decision and evidence

The briefing now follows one recognizable airfield context across three distinct camera systems. This is a booth communication choice, not a claim that airfields account for the largest defense AI market or that a prospect study has proved conversion rates.

| Job | Primary evidence | What the demo shows | What remains unproven |
| --- | --- | --- | --- |
| Airfield recovery: give engineers visible damage to review | [AFIT, September 24, 2026: Eyes on the Airfield](https://www.afit.edu/EN/news.cfm?article=0360410F7B). Research studies small drones for assessing damaged airfields and converting collection into useful analyst output. | A downward drone view of damaged pavement, source-linked finding, real local mask on the illustrated input, engineer review. Anvil is at the ground station. | Field damage-detection accuracy, survey localization, physical measurements, structural condition and clearance. This is not autonomous runway clearance or ordnance detection. |
| Site security: focus the operator on an entry | [U.S. Army, July 23, 2025: Blue Grass Army Depot technology demonstration](https://www.army.mil/article/287276/technology_demonstration_showcases_innovations_set_to_incorporate_into_huntsville_center_electronic_security_contracts). Demonstrated AI video analytics alongside other installation security technology. | Hangar gate camera, authored boundary-crossing event, source and example event time, operator review. Anvil is on the local camera network. | Our false-alarm rate, access authorization, and a live Defense tracker/rule/event integration. A still cannot establish temporal crossing. |
| Vehicle visibility: show personnel behind the vehicle | [Rheinmetall, November 21, 2023: rear safety cameras for 359 Warrior vehicles](https://www.rheinmetall.com/en/media/news-watch/news/2023/11/2023-11-21-rheinmetall-delivers-trailblazer-to-uk). Contract specifically supports recognition of terrain/personnel behind vehicles. | Rear camera, person cue, explicit unavailable-camera state. Anvil is inside the vehicle. | Incremental benefit and reliability of our AI cue; vehicle qualification, automatic braking, calibrated distances or safety certification. The source validates camera demand, not our implementation. |
| Local processing under unreliable remote connectivity | [U.S. Army: cybersecurity approach](https://www.army.mil/article/263153/army_to_implement_new_cybersecurity_approach_to_safeguard_network?trk=article-ssr-frontend-pulse_little-text-block) discusses disconnected, intermittent and low-bandwidth conditions. | A simulated uplink-loss control leaves local camera processing/review present and marks remote sharing queued. | Actual offline acceptance testing and a durable store-and-forward queue. The control changes UI state only. |

### Why Anvil is visible throughout

Every step retains camera input → Connect Tech Anvil-T5 → operator output, with the installation location and processing task changing for each mission. Drone imagery reaches the ground station over its video downlink; the briefing does not put Anvil on a small quadcopter. Site cameras connect over the local network. Vehicle cameras use a suitable GMSL configuration.

[Connect Tech's Anvil-T5 manual](https://connecttech.com/ftp/pdf/CTIM-ESG625_Manual.pdf) and [product announcement](https://connecttech.com/anvil-t5-first-to-market-multi-vision-jetson-thor-robotics/) are the hardware references. Select the camera expansion board and interfaces for the configuration. Anvil-T5's specified input is 36–60 VDC: vehicle power integration must provide the correct supply. Do not advertise direct 12/24 V input, Ethernet PoE, military qualification, or simultaneous inference throughput without separate verification. The current demonstrated inference host is DGX Spark; Thor/Anvil performance has not been measured here.

### Visual and interaction changes

- Four new photographic illustrations: coastal airfield, downward pavement inspection, dusk hangar gate, rear vehicle camera. These are explicitly labeled illustrations, not Isaac captures or operational footage.
- Larger evidence view with a concise operator-result column; clean neutral green palette and restrained amber attention cues. Actual Anvil product image replaces the fictional device in generated layout concepts.
- Mission navigation, pinned scroll, keyboard control, autoplay/reduced-motion handling, and existing VSS exits retained. Smart City and the application sidebar are not restyled.
- Image/box/mask comparison for the real recorded local result; optional illustrative person/zone cues; simulated camera and remote-link loss; mission-specific deployment selector; expandable primary-source evidence.
- Live Local Vision workbench receives the displayed source image, without painted UI annotations. Recorded output is not misrepresented as continuous live inference.

### Local inspection test and implementation implications

Input: generated damaged-pavement scene, resized to 1024×576 JPEG. Resident Moondream 2 through Photon + SAM 2.1 Tiny on Spark, existing local vision service, no model restart.

1. `object="damaged pavement", grounded_by="point", presence="off"`: 955.5 ms engine total. A central point returned a mask of only 83 pixels (0.014% of image). This did not meaningfully outline the damage.
2. `object="pothole", grounded_by="detect", presence="off"`: 654.2 ms engine total; 662.3 ms service total. A bounding box guided SAM to a 49,467-pixel depression mask (8.39% of image). Visually useful on this illustration, but excludes surrounding cracks/fragments. Only this output is displayed as the recorded result.

Both responses are preserved in `public/defense-story/v2/`; mask confidence is an uncalibrated predicted mask-IoU score, not damage-class accuracy. Do not infer that box grounding is always faster or better from two different single requests. Presence checks were off. Native Moondream segmentation has not been fixed or used in this test.

Next implementation work should connect real camera/video sequences, timestamps, persistent evidence and human review. Site/vehicle use the existing RF-DETR direction with tracking/rules as needed; the story's person rectangles are authored examples. Inspection uses Moondream grounding and SAM masks as a prototype until real-data evaluation establishes suitability. Pose/calibration is required before placing findings on a survey map or reporting physical size. Offline operation, latency and thermal/power behavior must be tested on the target Anvil configuration.

### Verification of the revision

- 39 focused tests passed across DefenseStoryWorkspace, DefenseWorkspace, SmartCityStoryWorkspace, VssStoryWorkspace, workspaceRoute and LocalVisionInspector. Includes real request payload selection for point/box guidance, stale overlay clearing, missing-camera behavior, remote-link illustration, primary-source links and chapter preservation when a browser clamps scroll during resize.
- Strict application TypeScript check passed (`tsc --noEmit --incremental false`).
- Browser walkthrough at normal 1440×900 and 1920×1080 Presentation Mode. Reviewed overview, inspection mask, site, vehicle, local-link and deployment layouts. Verified source disclosure, image/mask switch, camera-loss replacement, uplink simulation and presentation toggles. No browser warning/error logs in the final check.
- At 390×844, DOM viewport/page/story widths were all 390 pixels and chapter 8 persisted. Narrow-screen layout check only; no claim of a full mobile device interaction audit.
- The live model workbench originally hardcoded point guidance. Added a point/box guidance choice (point stays the default), preserving other task behavior. Browser run: displayed inspection image → Box guidance → pothole → Run segment; 1 mask returned, 1,028 ms browser request, 918 ms grounding, 51 ms mask stages. Browser canvas/JPEG preparation makes this a separate request from the recorded engine sample.
- No model/container restarts or real network changes. Viewport override reset; normal VSS shell restored; rebuilt overview left open.

Screenshots are under `/home/sparkdev/.codex/visualizations/2026/10/15/01a14131-5490-7330-82eb-ed3fb525304d/defense-explainer/`: `v2-overview.png`, `v2-airfield.png`, `v2-airfield-1080.png`, `v2-site.png`, `v2-vehicle.png`, `v2-local-edge.png`, `v2-anvil-1080.png`, `v2-live-segmentation.png`.

## Connected diorama revision — 2026-10-22

User direction: retain the Smart City explainer's spatial continuity and progressive reveal. Separate cinematic slides still reset too much context. The defense briefing now keeps one illustrated airfield mounted throughout all nine steps.

Sequence: establish the whole airfield → focus on the drone and open its camera → expand that same camera to review the real recorded mask → pan to the hangar while retaining the damage finding in the trail → expand the gate event → follow the road to the vehicle and open its rear camera → review the person/coverage state → pull back to local processing locations → compare three Anvil installation locations. The finding trail is authored narrative progress, not live incident history.

Implementation: `defense/DefenseDiorama.tsx` owns the persistent SVG image and camera inset, result copy, retained evidence links and local workbench handoff. `defenseDioramaMotion.ts` interpolates framing from scroll position; paired context/detail steps deliberately use identical world framing. Only the camera inset expands between each pair. Reduced-motion users receive immediate framing. Existing pause-on-interaction, keyboard navigation and resize-position preservation remain in the parent. The application sidebar and Smart City components remain unchanged.

The diorama is a rendered illustrative asset, not an actual reconstruction, live overhead camera, measured survey, or Isaac environment. Its sightlines and local-compute positions are conceptual. Existing illustrated camera images are explanatory views, not geometrically rendered from this asset. Ground-station, site-network and vehicle-compute paths remain separate; a single ground-station server is not implied to serve all vehicle cameras.

### Visual specification and fidelity notes

Concept: `/home/sparkdev/.codex/generated_images/01a14131-5490-7330-82eb-ed3fb525304d/exec-d643f0b9-2816-4b4a-80e1-919040cc4694.png`. Production asset: `public/defense-story/v2/airfield-diorama.png`. Prompts: adjacent `diorama-prompts.json`. Both generated with the built-in image tool.

- Composition: persistent detailed architectural diorama on the left; editorial story on the right; small camera inset that expands for evidence. Checked against the concept and rendered context/detail screenshots.
- Palette: retained #101715 background, sage/mint location cues, restrained amber camera detections, warm photographic scene lighting. No neon tactical dashboard.
- Typography: retained the app's sans-serif system instead of the concept's incidental serif heading. Intentional consistency choice; compact desktop headings reduced to avoid unnecessary third lines and result-column scrolling.
- Asset: generated standalone diorama, not a crop of the UI concept. A small quadcopter replaces the concept's fixed-wing drone. Actual Anvil product image is retained.
- Continuity: one scene/image DOM node persists; paired camera images persist; progress is interpolated instead of replacing a world per slide. Previous findings remain in the trail.
- Copy: intentionally revised from the concept's generic “Start with the place” to the nine-step connected narrative in `defenseStory.ts`. All new explanatory copy serves location, camera, finding, or handoff continuity. Existing evidence/limitation text retained.
- Navigation: existing VSS shell and chapter controls retained; code-native chapter/trail controls navigate the story. Scene markers label locations; they are not controls hidden behind an expanded camera inset.

Verification for the connected revision: 17 focused tests passed (Defense story, diorama interpolation and Smart City story); strict app TypeScript passed. Browser verified the overview → drone camera → expanded mask → gate camera → event → vehicle sequence, cumulative finding trail, local-link toggle, and source-image handoff to the live workbench. Source capture prepared the correct 1024×576 inspection image. No browser warning/error logs in the final check. No inference/model service changes were needed.

Visual comparison used `view_image` on the generated concept and browser screenshots, including the concept's 1672×941 viewport, plus normal 1440×900. The IAB native-size screenshot contained capture padding/scaling; default-viewport screenshots provide the clearer visual receipt. At 390×844, page/story/viewport widths were all 390 and the chapter stayed at 7 across the resize. This is a narrow-layout check, not a full mobile-device audit. Temporary viewport override reset; normal shell and overview restored.

The spatial composition, muted palette, detailed diorama, camera-inset hierarchy and persistent hardware path were checked against the concept. Deliberate deviations are the app's existing sans-serif typography/shell, actual Anvil photo, quadcopter asset and connected narrative copy documented above. Final default screenshots: `v3-diorama-overview.png`, `v3-drone-context.png`, `v3-drone-finding.png`, `v3-gate-context.png`, `v3-gate-event.png` in the same screenshot directory. Prompts/provenance remain with the production asset. The expanded inset replaces its controls as it changes missions; it does not replace the persistent world.
