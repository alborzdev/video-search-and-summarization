# Smart City improvement sprint — 23 October 2026

**Latest user direction:** long live qualification is deferred. Additional [fast source improvements](source-only-fast-pass.md) are staged separately from the unchanged running demo; they need a later build and deployment.

Status: deployed changes are awaiting the fresh combined live qualification. Historical passes do not qualify this build.

## Changes

- The isolated demo at `http://127.0.0.1:7782/?workspace=smart-city` uses frozen production package `20261023T155304362915Z`, image `sha256:9650f8d01d2ade21157bc5e1559c17aafa80007580759c8ae784ead60e55531a`. The shared port-7777 UI was not recreated. This package is built and deployed; its combined live qualification remains pending.
- Camera names, source colours, map legends, shared-zone captions and rule metrics are clearer. Active zones draw above inactive zones. A green camera status requires fresh, accepted analyzed frames.
- Preview fetches account for request and image-decode time within the display cadence. Aborted requests release work; the proxy avoids redundant JPEG copies. Exact frame identity and bounded ownership remain required.
- Visual-analyst requests have an explicit timeout, cancellation and retry state. Historical event evidence remains distinct from a question about current footage.
- Calibration identity includes class-specific ground-plane transforms. Homography projection is invariant to matrix scale. Map positions and speed remain estimates from camera detections.
- Lost or predicted detections cannot silently extend occupancy and duration evidence. Gaps reset qualification, and unresolved aggregate incidents survive display-track expiry until evidence resolves them.
- RF-DETR emits at most one supported city class for each detector query. This prevents one query being counted as both bus and truck. Separate queries are retained, including genuinely overlapping objects. The runtime model revision declares this postprocessing policy.
- The launcher waits for its analytics gateway and existing controller after restart, verifies controller identity/capacity before changing sources, and reports an unavailable service without an unhandled status traceback. It validates exact source/profile identity and required service confirmations; an HTTP-200 partial resume or pause fails immediately. Live OpenCV admission makes at most two attempts inside one 20-second subprocess, using TCP; recorded probes retain their previous behavior.

## Completed checks before live qualification

- 160 UI/proxy tests and main-app TypeScript passed.
- 109 backend tests passed. An independent reviewer reproduced and retested gap, reacquisition, aggregate-continuity and expired-track uncertainty cases.
- Native compilation, core tests, actual exported parser tests, frame-limit tests and RTSP transport tests passed in a CPU-only container with no GPU and no package installation.
- The cached 100-image COCO comparison measured six-class AP50:95 changing from 57.803 to 57.681. At the live threshold, duplicate labels from a single query decreased from four to zero. This is a limited paired comparison, not full COCO or final intersection accuracy.
- The native engine weights and TensorRT engine are unchanged. The parser correction does not resolve a wrong winning vehicle label.
- The final package's [browser layout receipt](sprint-final-browser-layouts.json) records two fresh exact-frame previews, desktop/laptop/mobile checks, no horizontal overflow and no observed console warnings/errors. It does not measure browser end-to-end latency; rendered Ask answers remain a separate pending check.
- [Actual JSON/CSV report files](sprint-report-exports.json) were inspected after clicking the export buttons during the sprint. The JSON browser wait hook timed out, but the newly written file was independently confirmed; this check preceded the final UI package.

## Runtime policy and retained limits

The user explicitly disabled the Isaac-specific 23 GiB available-memory stop. The policy value is `null`, and the companion health receipt must show that value. The separately saved 20 GiB VSS guard/reserve, process limits, startup admission and disk checks remain active. Earlier receipts that used a 23 GiB stop remain historical evidence.

Only two continuously rendered cameras are allowed. MV3DT remains disabled after the earlier local accuracy trials; IDs remain local to each camera. Overlap can show the same physical object twice. No simulator actor identity drives the operational map or event rules.

A tipped spill drum appears to be an out-of-class detector false positive in the captured views. Bus/truck errors also remain. VLM prose can make visual errors; structured detection and rule outputs are authoritative for the displayed counts and events. Neither this sprint nor its endurance test establishes safety-critical accuracy.

Read-only review of the final screenshots found a remaining small-screen visual limitation: at laptop and mobile widths, the map legend can sit over pale map imagery and lose contrast. The desktop booth layout has a clear legend below the map. This is recorded as non-blocking responsive polish; no UI artifact was changed during qualification. The final unknown-rule label is **Not enough evidence**, which also covers track or speed uncertainty while cameras remain live.

## Reproducibility

- [Final frozen UI package](sprint-final-ui-package.json)
- [Final package browser layouts](sprint-final-browser-layouts.json)
- [Fresh detached qualification observer launch](sprint-final-observer-launch.json)
- [Native build and parser controls](sprint-native-build.json)
- [Backend tests and source identities](sprint-backend-final-qa.json)
- [Detector policy comparison](sprint-query-policy-comparison.json)
- [Runtime audit](sprint-runtime-audit.json)
- [Startup failure and control-path repair](sprint-startup-repair.json)
- [Controller startup-wait repair](sprint-controller-startup-wait-repair.json)
- [Generated dependency cleanup](sprint-generated-dependency-cleanup.json)
- [Final package generated build-output cleanup](sprint-final-build-output-cleanup.json)
- [Superseded package generated build-output cleanup](sprint-superseded-build-output-cleanup.json)

The earlier dependency-cleanup receipt records removal of duplicated generated dependency directories after that successful image build. Separate receipts identify the final and superseded packages' generated `.next` directories removed after packaging. Original installed dependencies, frozen source, complete artifact contexts, logs, receipts, media and fallback images remain available.
