# Full application audit — September 9, 2026

Status: completed broad interactive audit with known runtime limitations below. This does **not** qualify every capability or sustained ingestion. This is the post-reboot audit, distinct from the earlier visual pass.

## Environment and scope

Thor, source-mounted Next.js development server at http://10.88.8.175:7777, Codex in-app browser through CUA. Dark mode primary; desktop (1078 × 926 capture), 390 × 844 responsive checks and a light-theme sanity check. Presentation mode entered and exited. No full image build. Original source definitions and operational rules preserved.

The flow under test was: load each main workspace, exercise its meaningful controls with real local data, verify rendered results, fix reproducible defects, and repeat affected checks. External notification delivery, unavailable simulator feeds, audio, calibration, and sustained heavy workloads were not qualified.

## Findings and fixes

| Finding | Change and evidence |
| --- | --- |
| Home/Live asserted connectivity or active pipelines from catalog presence, including paused/offline cameras | Distinguished configured sources, paused processing, unknown status and confirmed active analysis. Unknown sources no longer count as analyzing. Browser checked paused traffic and offline simulator cards. |
| Insights/rules implied configured sources and enabled rules were actively monitored | Labels now say configured sources, enabled rules and sources with rules. Paused source status remains visible. |
| Monitoring wizard discarded the operator's visual condition on Continue | Preserved typed intent after applying a template. Regression failed before fix and passed afterward. |
| Catalog outage looked like an empty account and generated a Next.js error overlay | Distinct unavailable state, Retry, unavailable counts instead of zero, and a 15-second catalog retry without remounting. Browser verified outage/recovery; regression tests cover both paths. |
| Search proxy outage surfaced a bare 503 | Actionable System/retry guidance that does not imply indexed evidence was lost. Regression passed. |
| Generic search result titles and awkward singular count | Source display names replace generic VST live-stream titles; one result says matching clip. |
| Investigation action implied more than it did; opening form duplicated Save actions | Renamed to Save investigation and hid the launch button while the form is open. Saved and reopened a real QA investigation. |
| HTML investigation report stayed light in dark mode | Report uses saved appearance preference (including system theme); print styling remains light. Browser inspected dark report and played embedded evidence. Download returned 200 with attachment header and HTML. |
| Source upload dialog could open below the viewport on a long catalog | Viewport overlay, bounded scrollable dialog; upload progress also fixed to viewport. Desktop/mobile inspected; real upload completed. |
| Small dark dialog text and unnamed source-search/close controls | Improved minimum text size and contrast; added accessible names. Source filtering and upload close exercised. |
| Supported source types disappeared from filter options | Keep supported video/live choices available even when a type currently has no sources. |
| Structured history admission refusal caused a null-status crash | Treat an explicit server refusal as final and guard absent build records. Browser now displays the actual telemetry prerequisite; regression passed. |
| Shared-package edits silently served stale compiled code | Corrected Turbopack aliases to app-relative lib-src entrypoints, including server entrypoints. Verified emitted browser modules and live source changes. See ../ui-development.md. |

Principal files: vision-intelligence workspace components and tests, useVisionStreams.ts, pages/api/vision/investigations.ts, styles/vision-intelligence.css, next.config.js, and video-management/lib-src components/hooks plus tests.

## Browser workflow coverage

| Workflow | Observed result |
| --- | --- |
| Home, Live, Monitoring, Explore, Events, Capabilities, System | All main surfaces rendered; navigation, filtering, descriptions, readiness and empty states inspected. |
| Dark/light appearance, presentation, mobile Home/Sources/upload | Controls responded; dark appearance and desktop viewport restored. CTAI logo retains colored AI. Screenshots captured in the audit conversation. |
| Sources outage and recovery | Clear unavailable/retry state; catalog recovered. Search by Traffic narrowed cards and Clear restored them. |
| Add RTSP source validation | Blank URL rejected by browser validation. No additional external camera registered. |
| Upload recorded footage | Uploaded 2.46 MB, ten-second repository fixture with Search only profile. Completed 1/1 and appeared in inventory. |
| Recording playback and source-scoped retrieval | Uploaded recording played to ten seconds, readyState 4, no media error. Query person in a warehouse returned one ten-second clip. |
| Semantic archive search | Find vehicles at intersection returned ten real traffic clips. Selected four-second clip played to completion. |
| Object selection/similarity | Four tracker boxes appeared; selected a blue car. Service correctly reported that this object was absent from the similarity index. Actual similarity results remain unqualified. |
| Evidence briefing | Selected real traffic evidence; Cosmos visual analysis and Nemotron synthesis produced a cited brief describing the blue car, yellow taxi and school bus. |
| Investigation persistence/export | Saved low-severity resolved QA investigation, reopened through Events, opened dark HTML report and played evidence. HTTP export returned attachment. |
| Source visual question | Asked school-bus color; real model answered yellow. |
| Traffic collection controls | Resumed and observed active detection/embedding/indexing, then paused. 196 traffic indexed moments were shown after the bounded check. |
| Structured monitoring wizard | Traffic source → area entry → three accessible polygon points → review → activate. QA rule persisted, then was paused. Original two enabled rules preserved. |
| Video history build | Safely refused with fresh-telemetry requirement; no null-status crash or misleading job polling. No heavy history build admitted. |
| Live preview | Reconnect exercised. VIOS rejects stream start; clearly labeled latest-frame fallback remains. Archived playback works. |

## Verification

- App/component/report/history tests: **83 passed in 20 suites**.
- Shared video-management tests: **122 passed in 10 suites**.
- Both affected workspace TypeScript checks passed.
- `git diff --check` passed.
- Page identity, meaningful content, screenshot inspection and real interaction checks passed. No framework overlay in final state. Historical console errors from the reproduced catalog outage and temporary alias experiment were resolved; they are not evidence of a clean entire-session console.

Commands from services/ui:

```sh
npm test --workspace=nv-metropolis-bp-vss-ui -- --testPathPatterns='components/vision-intelligence|__tests__/api/vision/investigations.test.ts|__tests__/api/vision/video-history.test.ts'
npm test --workspace=@nv-metropolis-bp-vss-ui/video-management
npm run typecheck --workspace=nv-metropolis-bp-vss-ui
npm run typecheck --workspace=@nv-metropolis-bp-vss-ui/video-management
```

Browser validation used getAXState/getAXStateAndScreenshot, role/label locators, file chooser upload, viewport capability, console logs and read-only video-element state. Automated tests supplement the real browser checks; they do not establish unavailable backend capabilities.

## Runtime findings and remaining limitations

1. **Full-stack development headroom is insufficient at the current budget.** Ordinary UI use crossed the 48 GiB reserve at 47.16 GiB (trip time 1788990424.395); the guard stopped AI workloads without reboot. The earlier five-minute full-stack test did not qualify active development. Models were restored one by one with the unused warehouse detector vss-rtvi-cv left stopped. Final available memory was about 52 GiB; guard remained active at 48 GiB. Do not lower this floor to enable history or more ingestion.
2. **No host reboot during this audit.** Boot ID remained ac75a3b5-980a-41c5-8301-200423326f72. This bounded observation is not sustained-runtime qualification.
3. **Vendor VIOS crash recovered, not fixed at source.** vss-vios-streamprocessing exited 139, not OOM, at 21:51:51 UTC after the traffic player had stopped. Stack implicated libstream_monitor.so QosRtspClient::updateStreamError/onError and live555 DESCRIBE handling. Restarted nvstreamer before streamprocessing; catalog and recording playback recovered. Proprietary binary root cause remains open. Trace: [VIOS crash excerpt](vios-segfault-2026-09-09.log).
4. **Live WebRTC playback remains blocked upstream.** Retry at 22:16:54 UTC reached VIOS successfully. PeerConnectionManager::checkStreamSanity rejected stream a0d44114-9947-4edf-8355-14e5732999db with Streaming not yet started for sample-sim-jaywalking.mp4, followed by Peer not found. Recording writer continued writing frames. This is a distinct backend live-playback failure, not a browser network connection failure. The UI still-frame fallback is verified; live motion is not.
5. **Four IsaacSim feeds are offline.** Definitions preserved; warehouse detection stays off. System correctly shows degraded/needs attention rather than claiming all capabilities ready.
6. **History generation is unqualified and blocked by admission.** The server requires fresh Thor telemetry before considering this very-heavy workload. This audit did not bypass admission or qualify simultaneous long history generation with the models.
7. Similarity-index coverage, external notification delivery, audio, calibration, every camera/network failure combination and long-duration workloads remain untested or unavailable. Avoid describing the app as fully operational across all capabilities.

## QA data and final state

Left clearly labeled fixtures for repeatable user testing:

- Recording: qa-app-audit-20260909, sensor af6b544d-3d9c-4951-b598-69165d76d11d; ten-second bundled warmup video.
- Rule: QA audit — zone editor and rule persistence; **paused**, in-app only.
- Investigation: QA audit — traffic evidence playback and briefing; **resolved**, low severity, explicitly marked non-operational QA. ID 7fcc4ac0-5eb7-4a46-881b-ee02b9ed88ee.

Original sources/rules retained. Traffic collection paused, models available, unused warehouse detector stopped, memory guard active. Site left on Home in dark mode at desktop size. See tools/runtime/README.md for startup restrictions and docs/ui-development.md for fast iteration.
