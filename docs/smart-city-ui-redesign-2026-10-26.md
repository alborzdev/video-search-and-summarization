# Smart City UI redesign — October 26, 2026

Status: complete. User authorized a full redesign around the approved graphite concept, preserving VSS global left navigation. Generate an image before implementing each major new screen or interaction. This record tracks implementation and real verification; generated data is never deployed as live analytics.

## Baseline and design authority

- Audit: `/home/sparkdev/Documents/Smart City UI Audit/2026-10-26/smart-city-ui-audit.html` (49 screenshots and transcripts).
- Approved direction: `docs/design/smart-city-graphite-2026-10-26/approved-direction.png`.
- References: Linear's restrained hierarchy and neutral surfaces; Flighty's contextual map/result; Michael Filipiuk's spacing and sidebar alignment examples. Reference study is outside the app in the audit's `design-references` directory.
- User amendment: keep all global navigation on the LEFT. Smart City local navigation is Overview, Measurements, Search & reports. Do not move Defense to the Smart City header.

## Intended scope

1. Overview: two camera views, large calibrated map, meaningful current observation, clear map camera directions, class labels replacing truncated IDs, focused regions and bottom scenario shelf.
2. Measurements: a readable dedicated results workspace, per-camera scope and evidence limits, map linkage, existing five measurement topics, exports and configuration.
3. Search & reports: clear current-camera questions, finite capture search and saved-event review, each with explicit source/time and evidence status.
4. Presenter tools: coherent zone editor, measurement settings, diagnostics/technical details behind deliberate controls.
5. Scenario interaction: existing Prepare → Ready → Play → Normal traffic transaction, explicit scripted versus observed result states and strict preparation/recovery covers. No new scenario/runtime implementation in this chat.
6. Browser and scoped source checks, concept/render comparison and a written fidelity/limit ledger.

## Design system extracted before implementation

- Background: neutral graphite #151617, no all-over green tint. Surfaces #1b1d1f / #202224; subtle border #303438. Primary #f0f2f3, secondary #a4adb3. CTAI teal #37d5c1, camera 02 blue #679dff; amber only for actual warning states.
- Typography: existing locally available sans family, deliberate 14–16px controls and body, 18–20px region headings, 28–30px workspace title, 28px focal observation; no promotional hero heading. Tabular figures only for measured values.
- Geometry: 8px spacing rhythm, 24px primary gutters, 8px corners, hairline dividers, minimal shadows; avoid nested card grids.
- Icons: existing Tabler outline components, 18–20px, consistent 1.6–1.8 stroke. Real logo assets. Real camera/map assets; generated image is design reference only.
- Containers: retained sidebar, compact header/local tabs, camera rail, one map canvas, contextual observation detail, scenario shelf, drawers for deliberate detail/configuration.
- Media: preserve exact decoded frame/overlay geometry, contain media without destructive crop, no tint. Map uses actual calibrated static image and genuine camera-footprint geometry; no guessed camera extrinsics or actor truth.
- Source truth: scope, frame-match, calibration, timing, stale, preparation and missing-evidence protections remain authoritative. Human-readable labels never replace internal stable IDs.

## Runtime coordination

The user's migration chat “Investigate Isaac Sim FPS usage” (01a178f2-c7cc-7170-aa4e-5f56ed6d35ee) owns Isaac/stream deployment. It confirmed stable source UUIDs and dimensions (960×540), 19 rules/mobility revision 6 and unchanged scenario operation contract. A real exported calibration revision will change after the path migration. The migration chat cold-started the new host and restored the original two sources; during its finite five-scenario acceptance, preparation covers and pauses are expected. This chat owns frontend changes and will not resume sources or change the sim.

Existing isolated UI: vss-city-polish-ui, Next/Turbopack source mounts, app 7781 behind ingress 7782. The generic Spark UI helper reports its separate UI stopped; do not launch a competing UI container through that helper.

## Progress

- Read repository workflow, frontend design/testing and React performance guidance.
- Audited current code/data contracts and shared working-tree changes; preserve unrelated edits.
- Created goal and coordinated frontend/runtime ownership with migration chat.
- Generated seven accepted-style screen/interaction references before code; images are documentation only.
- Rebuilt the Smart City layout and extracted a single graphite style system. Global VSS navigation and other workspaces remain available.
- Overview now has two exact-frame camera panels, friendly Person/Car class labels, one focused rule, a large overhead map, actual calibrated camera pins/coverage and a bottom scenario shelf.
- Measurements has dedicated topic navigation, turning table, owner-camera labels, map linkage, window controls, actual CSV/JSON exports and deliberate setup forms. Existing evidence-gap and incomplete-membership semantics remain.
- Search & reports separates current-camera questions, finite capture search/retained clip review and durable event history. Camera changes abort old work and retire old answer/clip context. Historical events explicitly distinguish current Ask from event-time footage.
- Preserved Prepare/Ready/Play/recovery gates, exact run IDs and opaque full-content preparation covers. Removed duplicate drawer question/options clutter; bottom shelf is the scenario selector.
- Static camera metadata was available in the gateway but omitted by the UI proxy. Added bounded, finite, calibrated-only pass-through; private inputs/credentials remain removed.
- Hidden camera panels stop preview decoding. The class labels preserve stable internal tracking identifiers and frame/epoch/calibration checks.
- First browser pass completed on actual 960×540 Isaac sources after migration restored revision199/live/two sources. Real footprints and exact analyzed camera frames rendered. No scenario or source commands issued by this chat.
- Strict TypeScript check passed after the new screens and header portal. Scoped regression checks are being updated for intentional navigation/label changes; frame/clock/readiness assertions remain.


## Verification ledger

Verified at1920×1080,1265×712 and390×844, with desktop and mobile screenshot evidence. Keep proof outside the application. Explicitly record current live availability and intentional differences from illustrative footage; do not claim model accuracy or scenario acceptance from UI screenshots.

### Concept references completed before code

All seven major surfaces now have a full generated reference under `docs/design/smart-city-graphite-2026-10-26/`: `overview.png`, `measurements.png`, `ask.png`, `find-clips.png`, `events-reports.png`, `scenario.png`, `zone-editor.png`. The shared detail panel comes from the event reference; measurement forms use the editor family. The original approved direction remains separate.

Copy fidelity excludes illustrative numbers, timestamps, generated-date mistakes and unimplemented media claims. Runtime values, actual source names/status and missing evidence replace illustrations. No invented camera pose: footprints must derive from exported calibration/camera metadata or be omitted with an honest state. Generated footage will never replace real camera evidence. The images' shape/rhythm/typography are the spec.

### Development-container recovery

At 17:47 UTC, running TypeScript and Jest concurrently beside the Next/Turbopack compiler exhausted the pre-existing 4 GiB UI-container cgroup. The dev UI exited with OOMKilled=true. The interrupted run is not a pass. Earlier complete suite:31 suites/404 tests passed. The UI was restarted with its same mounts, source, ports and command, using a6GiB memory/8GiB total memory+swap cap in `.spark/city/polish-ui-dev.json`; host available memory was39GiB after recovery. Source services, inference worker and simulation were not restarted by this chat. Fresh post-recovery strict TypeScript completed successfully, and final Jest is run sequentially. Avoid parallel compiler/test jobs inside this dev container. Production package settings remain separate.

## Presenter guide

- Open `http://127.0.0.1:7782/?workspace=smart-city`. The global VSS sidebar remains available; the three header tabs belong only to Smart City.
- **Overview:** the two panels show actual camera video. Boxes use class names such as Person and Car, while stable tracking IDs remain in technical details. The map uses the real actor-free overhead image, exported camera position/ground coverage and estimated track ground anchors. Click an object for its owner camera and map-association context. A selected rule is highlighted in both image and map; unrelated rules stay hidden.
- **View measurement:** opens the relevant topic in Measurements. Turning traffic, Crossing access, Queues, Walking and Curb access retain the existing real report calculations and camera ownership. Choose1/5/15min, inspect evidence/coverage if needed, or export actual CSV/JSON. Zero observed objects does not establish physical clearance when membership is incomplete.
- **Demo scenarios:** choose a bottom-shelf scene to read its city question, prepared starting state and what to watch. Selecting does not move actors. Prepare/Ready/Play uses the existing controller and exact run identity. An opaque cover hides stale cameras/map during preparation and recovery. Play enables only after actual scene and analytics readiness. Normal flow resumes through the controller; a failure stays visible with its actual recovery action.
- **Search & reports → Ask scene:** select one camera, choose/edit a prompt, then Ask the camera. The analyst inspects the recent5seconds. Switching cameras retires the prior answer and pending work. Structured counts/durations belong in Measurements. Answers can be wrong; inspected evidence remains accessible where returned by the existing service.
- **Find clips:** optionally index one finite2minute capture; there is no always-on indexing action in the new page. Search only that camera/capture, select a result, and review its retained interval. The viewer validates the existing source/time/media contract and reports expired/unavailable clips rather than substituting live video. Changing the search camera closes the old clip context.
- **Events & reports:** review retained history in pages of6, filter state, select an event and export. Pending stop evidence is excluded from the Active filter. Each event keeps its own run/scope; history is not labelled as the current live event count. Asking the current camera does not silently replay an earlier event. Exports retain full history returned by the service, not just the current page.
- **Presenter tools → Edit monitoring areas:** draw a new area/line, choose classes/conditions, validate then explicitly save. Saved overlays are hidden initially and available through Show saved areas. Selecting an existing rule preserves its backend settings/revision and uses the existing conflict/save protections. Closing or changing the top-level view discards the unsaved editor. This redesign did not change the19live rules.
- Shared map markers remain explicitly experimental display association. This UI does not promote MV3DT to an accuracy-validated unique-person counter. Measurements remain camera-owned.

## Scope of verification

Generated illustrations are design specifications, not footage or measured results. Preserve actual scene content and source readiness even when it differs from the illustration. Browser evidence covers navigation, layout, source labels, geometry, selection and honest waiting/recovery states; model/scenario accuracy is owned by the existing pipeline and the separate migration acceptance.

The full post-recovery scoped suite completed:31suites /408tests passed in7.379seconds. Strict TypeScript passed after restart. Additional final metadata/UI refinements are checked separately below. The failed/interrupted4GiB concurrent run remains documented and is not counted.

### Real-data checks and final interaction refinements

- A real Measurements CSV download completed in the browser (the browser download-event hook timed out, but the actual new file in Downloads was verified). It contains88structured rows across crossing/curb/gate/movement/obstruction/queue sections, two owner cameras and scope fields.
- Real retained history rendered and selected an actual line-crossing event. Paging is6rows so exports fit at1920×1080. Raw direction vectors are in technical evidence, not presented as an unexplained headline metric. Explicit event-time footage/current-camera Ask distinction is preserved.
- Browser map selection highlighted the actual owner camera box and opened a readable Car detail. Object details no longer append unrelated recent events/rule inventories; those remain in the separate activity drawer.
- A live search initially exposed a redesign bug: display-formatted camera names had been sent as registered source names. Fixed by preserving the original name in API requests and formatting only visible copy. No source-verification guard was removed. Also separated action errors from status-poll errors so a successful poll cannot erase a failed search. A regression test covers both.
- After that fix, the actual finite retained capture returned6matching clips for “People near the crossing”, within its acknowledged01:20:08–01:22:07camera/session interval. The first actual clip was opened for retained-interval verification.
- Final migration handoff confirms both feeds publishing while Isaac is paused, fresh exact processed previews/native SEI, all19rules preserved and questionReady=true. This chat did not issue scene/source/rule operations.

- Real retained clip loaded and its4.4second metadata passed the existing interval-duration check. Search thumbnails initially used Docker-only VST URLs; switched them to the app’s existing allowlisted, bounded CPU picture proxy, preserving the retained source/time path. No extra GPU snapshot decoder was introduced.
- The final paused-state drawer explicitly tells the presenter to press Play in Isaac Sim before preparing a scenario. The simulation remains under the migration chat’s control.

## Fidelity ledger

Concept pair inspected together using the image-view tool: `docs/design/smart-city-graphite-2026-10-26/overview.png` and `/home/sparkdev/Documents/Smart City UI Redesign/2026-10-26/overview-1920.png`.

| Checkpoint | Final implementation | Result |
| --- | --- | --- |
| Navigation | Real CTAI Labs logo, left global VSS navigation, local Overview/Measurements/Search & reports | Matches user amendment |
| Hierarchy | One intersection title, paired camera rail, larger map, one lower-right finding, bottom numbered scenario shelf | Matches concept structure |
| Typography | Clean local sans; 28px workspace title, readable class labels, restrained weight hierarchy, technical IDs disclosed only | Matches visual direction |
| Surfaces | Neutral graphite, fine borders, restrained teal and source-blue; amber reserved for evidence/warnings | Matches direction |
| Geometry | Actual overhead image fills the rectangular map; real calibrated pin/coverage data; one selected zone and clean markers | Matches structure; genuine footprints replace illustrated cones |
| Detection labels | Person/Car/etc rather than arbitrary truncated track IDs; full IDs retained in technical detail | Matches requested behavior |
| Media/evidence | Existing actual Isaac scene/camera footage and actor-free map; no generated vehicles/people or fabricated counts | Intentional difference from illustrative scene |
| Scenario interaction | Numbered bottom shelf; selected-scene explanation and strict Prepare/Ready/Play/recovery states | Matches direction; real readiness governs controls |
| Measurement/report separation | Dedicated topic/result view, camera owner, windows/exports; paged retained history with explicit source/scope | Matches screen references |
| Search distinction | Current5second questions versus finite capture search versus selected historical event | Audit ambiguity removed |
| Compact/mobile layout |1265×712 retains sidebar and two-column overview;390×844 stacks content, has two-row local header and scrollable main with existing global bottom navigation | Intentional responsive adaptation |

Remaining visual difference is the real simulation’s art/actor content and static-overhead background. This UI task does not replace the environment with generated concept footage. The paused simulation is labelled as paused while analyzed camera feeds continue to publish. No count/model-accuracy claim is inferred from the concept.

## Completion evidence

- Final expanded scoped run:33suites /428tests passed. Final readiness/selection refinement:2suites /66tests passed. Final strict TypeScript:exit0. Test logs are saved beside the browser proof.
- Browser proof directory: `/home/sparkdev/Documents/Smart City UI Redesign/2026-10-26`. It includes the Overview, Measurements, walking/map link, event review, real analyst answer/inspected clip, real finite-capture results/player, scenario explanation, zone editor, focused object details, compact desktop and mobile/map screens, actual CSV export and a sanitized final browser receipt.
- Final browser receipt confirms both original sources have `overlayAligned=true` and `clockGate=exact-processed-frame`; two actual calibrated footprints and the retained global sidebar are present. Native1920render has no horizontal overflow.
- The actual5second analyst request returned an answer in about6seconds. Its retained inspected clip loaded with duration4.9672seconds and readyState4. Switching the selected camera cleared the prior answer and clip. No model-quality claim follows from this UI check.
- Search returned6real matches; first retained clip passed duration validation at4.4seconds. Corrected thumbnails loaded successfully through the local picture proxy (naturalWidth1280). No new capture or always-on indexing producer was started during QA.
- The browser downloaded a new88row/two-camera structured CSV, with camera and scope fields verified on disk. Its rows remain actual data rather than concept illustration values.
- Global navigation was exercised Smart City→Defense→Smart City; existing Defense remained available. The final tab is on Overview, temporary viewport overrides were reset, and the UI is available at7782.
- Migration left Isaac paused with both native feeds publishing. Press Play in Isaac Sim before preparing a scene. This chat issued no scene, source or rule mutations.
- Dev UI is healthy after recovery, using about1.74GiB of its6GiB cap at final inspection. Production packaging was not rebuilt in this UI task; the existing source-mounted7782deployment serves the redesign.

### Follow-up: keep selected-area findings off the map

Moved the Overview finding from its floating map card into a compact, full-width footer below the map viewport. Result, camera/area context, explanation, measurement/event actions and selection dismissal remain available. Map controls, legend and calibration interactions stay within the viewport; Measurements and the zone editor do not gain a finding footer. Responsive layouts wrap the footer without covering the junction.

Verified in the browser at 1920×1080, 1265×900 and 700×900: no finding/map overlap or horizontal page overflow; gate focus and return-to-automatic finding work. Strict TypeScript and both map/workspace suites passed (36 tests). Camera feeds and demo controls were unavailable during this follow-up, so live object selection and populated measurement actions were not requalified. No simulator or service lifecycle changes were made. Screenshot: `/home/sparkdev/Documents/Smart City UI Redesign/2026-10-26/map-finding-strip-1920.png`.

### Follow-up: camera direction and interactive monitoring areas

The map now uses short teal/blue gradient fans beside the actual exported camera positions. The fan bearings come from the calibrated ground rays and camera forward axis; their short radius is a visual direction cue, not a detection-range claim. Hovering, focusing or clicking a camera reveals its unchanged full calibrated ground footprint. Missing or invalid exported calibration still produces no invented camera pose or cone.

Enabled monitoring geometries are discoverable by default with quiet, thin outlines. Hover/focus explains the configured detection classes and rule purpose in the fixed strip below the map; click pins the details. Shared geometry describes each associated check. View measurement focuses that rule and opens the corresponding measurement topic. The Areas toggle hides background outlines while retaining a focused rule. No rules or thresholds are changed. Count-area explanations omit internal alert thresholds and do not invent live counts.

The large persistent legend has been replaced by an on-demand Map key in the header. It retains person/vehicle symbols, source colors and the warning that camera-owned observations can overlap. Camera and region keyboard focus now uses native SVG highlights rather than the global HTML outline, which previously scaled into a large map-obscuring rectangle. The footer reserves its space during hover, so the viewport does not jump. The narrow map is tall enough to keep both camera markers visible.

Verification: strict app TypeScript passed; 3 scoped suites / 43 tests passed. Browser checks on the restored real two-camera workspace verified a camera footprint, area selection, East crossing → Walking measurement navigation, desktop and narrow layouts, both mobile camera pins, and no finding/map overlap or horizontal overflow. A temporary, clearly labelled component preview used saved calibration while the simulator task repaired its source lifecycle; that route and tab were removed. The simulator task restored site revision215 with both native feeds; this UI work made no simulator/source/rule mutations. Screenshots: `map-polish-overview-1920.png`, `map-polish-camera-1920.png`, `map-polish-area-1920.png`, `map-polish-area-1265.png`, and `map-polish-mobile.png` in the existing browser proof directory. The underlying scene art and overhead image remain real simulator assets, so their visual detail differs from the generated design reference.

### Follow-up: shared camera highlights and simpler selection

The default visible title is now “City intersection”; the internal site ID and user-customized site names remain unchanged. Overview media fills each camera panel, eliminating CSS side bars. Its SVG overlays use the same centered cover crop, and editing coordinates support that transform. Editing and analyst views keep the full frame with matching contain geometry to avoid hiding footage in their taller panels.

Map hover/keyboard focus now previews the physical monitoring region in both calibrated cameras wherever visible. The owner keeps its original rule overlay. Other cameras receive a presentation-only ground-plane guide: the owned region is lifted into site coordinates, clipped to each target camera's calibrated ground footprint, projected through that camera's inverse homography, then clipped to image bounds. Invalid, stale-owner or missing calibration and non-overlapping areas produce no invented guide. No additional analytics rule, event or count is created.

Hover is transient. Clicking or pressing Enter pins the area; moving away preserves the pin. Empty-map clicks and starting a pan clear it, as do outside-map clicks, the close button and Escape. Clearing also removes the shared camera highlights instead of immediately selecting the automatic finding's region again. Hovering a different region temporarily previews it; leaving restores the pinned region. The measurement link appears after pinning, so a transient hover does not offer a disappearing link.

At the user's request, camera inspection no longer draws the large calibrated footprint or long dotted centerline. Only the short calibrated direction fans and camera pins remain; full coverage metadata is retained solely for geometric projection/clipping.

Validation: strict TypeScript passed and five scoped suites / 71 tests passed. Tests cover clipped cross-camera regions/lines, absent or incompatible calibration, shared preview state, hover/pin/clear behavior, media coordinate transforms and existing frame/clock/scope guards. Browser proof on both real analyzed feeds verified North crossing and Junction preview before selection, East crossing in both views, pinning, clearing with blank/outside clicks, the simpler camera cues and a smaller desktop layout without horizontal overflow. Final screenshot: `/home/sparkdev/Documents/Smart City UI Redesign/2026-10-26/map-linked-areas-final.png`. Additional proof: `map-shared-hover-north.png`, `map-simplified-camera.png`, `map-linked-areas-1265.png`. No simulator, source, rule or inference service configuration was changed.
