# Edge video AI demo — running progress

Started: September 28, 2026. Status: recorded-fixture acceptance passes on DGX
Spark, including a fresh visual answer and saved evidence replay. A cache-only
recovery now passes with the Cosmos initialization fix, successful video/text
warmup, fresh answers and retained-report playback. The 180-second post-request
observation passes with a 27.818 GiB minimum and no new guard trip. The user's Sim
stream and joint live operation remain
unqualified. See the [Spark startup receipt](qa/2026-09-29-spark-startup.md) for
current target evidence. Full rehearsal and live monitoring qualification remain open.
Use the [current presenter guide](demo-presenter-runbook.md) for the coherent
walkthrough; dated entries below preserve the development history.

## Current Spark checkpoint — September 29

- Target preflight, six bootstrap tests, Git LFS integrity and fixture hashes pass.
- The independent 36-service graph is rendered. The user explicitly authorized
  a 24 GiB Spark trial reserve; the active guard confirms that setting. Thor's
  reserve remains unchanged.
- The user supplied NGC credentials locally and provisioned the 21 fresh data roots.
- Eight public source derivatives, including the current UI, build on ARM64.
  A registry TLS failure was diagnosed and addressed with the explicit HTTPS
  registry override; package versions and lockfile integrity are preserved.
- Complete image staging and first full serial startup pass.
  Build-memory minimum so far is 85.893 GiB. Existing Isaac Sim MCP and Moondream
  containers remain running; an active Sim renderer has not been established.
- Fresh-data topic ordering, Compose shell-dollar escaping and empty Nemotron
  cache permissions were diagnosed and fixed. Early infrastructure/video
  services are up. Nemotron completed first download/GB10 compilation and serves
  requests initially with a verified 0.13 GPU allocation and 32K context. Available
  memory recovered to approximately 64.6 GiB. Embedding's initial Jetson base
  failed decoding-library initialization; the corrected SBSA base passes that
  import. Fresh SBSA TensorRT 10.14 engines work; earlier incompatible 10.13
  plans are retained outside active filenames. Cosmos initializes, but its
  first visual warmup exposes a file-cache/CUDA allocation failure despite
  ample MemAvailable. Targeted unprivileged cache advice resolves the actual
  inference failure; model files remain intact. The bootstrap now advises only
  candidate cache files after each model loads.
- First full startup: 820.23 seconds, minimum MemAvailable 27.585 GiB, unchanged
  boot ID and no 24 GiB guard trip. Cache-only restart passes in 465.157 seconds,
  minimum 25.286 GiB. Fresh post-restart Cosmos inference passes in 5.678 seconds;
  sequential inference probes reach 24.349 GiB, close to the authorized floor.
  That restart still suppresses a built-in Cosmos warmup allocation error;
  attempt 10 below verifies the opt-in cache release before visual warmup.
- A later guard sample reaches 23.985 GiB and stops all 30 running VSS containers
  cleanly, without reboot or stopping the two pre-existing workloads. Recovery
  retains the 24 GiB floor and lowers Nemotron's allocation fraction to 0.11,
  keeping 32K context/batch 1.
- Attempt 10 verifies the source fix and full cache-only recovery in 640.224
  seconds: startup minimum 28.445 GiB, unchanged boot ID, no reserve trip.
  Checkpoint-scoped advice raises MemFree from 7.087 to 23.421 GiB; the four
  safetensors remain intact. Cosmos video/text and decoder warmup pass, with
  zero warmup/CUDA-allocation/no-frame errors in startup logs. Fresh direct
  movement/end-location answers are correct in 1.423/0.942 seconds; Nemotron
  returns `Ready.` in 0.168 seconds. The 180.620-second post-request observation
  records 902 samples at 200 ms cadence: minimum 27.818 GiB, first 28.249 GiB,
  last 27.978 GiB, no new guard trip and unchanged boot ID. The historical
  attempt 9 trip receipt is retained. Six bootstrap tests, four cache-helper
  tests and 32 reasoning methods pass. These sequential checks do not prove
  joint Sim capacity.
- Real browser upload indexes two segments from a 7.535-second recorded conveyor
  fixture. Natural-language search returns playable evidence; a fresh selected
  clip question answers correctly in 7.501 seconds. The saved report replays
  its retained local video to completion. Single-clip synthesis is bypassed, so
  multi-clip language-model synthesis is not established by this journey.
  Following attempt 10 recovery, browser reload and retained-report playback
  pass again (`readyState=4`, `ended=true`, `error=null`, duration 7.535 seconds),
  with no console warnings or errors.
- The gateway's agent target was corrected to loopback; its public analysis
  profiles endpoint and browser upload now work. UI/report hardware labels and
  missing Spark GPU metrics remain limitations; detector profiles are omitted.
- The Sim RTSP URL and reset steps are requested for later live acceptance.
  No Sim renderer has yet been established. The historical Thor browser error
  below does not describe the now-tested Spark browser.

## Historical Thor checkpoint — September28, after23:16EDT

- **Visible UI work completed:** redesigned Home; clearer recording/camera entry;
  source-scoped search; retained search/answer state; evidence playback and report
  handoff; monitoring authoring and provenance fixes; desktop/mobile checks for
  the flows linked below. This is more than a backend-only pass.
- **Demonstrated main journey:** recording → search → inspect → fresh answer →
  save report → replay retained clip → copy briefing → Home. Repeated local
  movement answers were7.6–8.0seconds in the recorded rehearsal.
- **Live diagnostic evidence:** exact inputs now captured. Two ten-second runs
  supported18positive answers. A five-second run supported five clear positives
  and five empty inputs, with one missed partial package at the image edge.
  First response5.94seconds; event-to-UI timing is still unverified. These
  bounded results do not qualify continuous monitoring or change app defaults.
- **Runtime:** latest core check31roles passing,54.43GiB available,48GiB guard
  retained, detectors stopped. Diagnostic rules/AI streams removed. Cold UI
  compilation now gets a15-second readiness allowance; backend probes stay5s.
- **What prevents completion:** current Codex browser tab needs the user reopen
  requested after its policy-blocked error page; populated monitoring/export
  delivery/final rendered rehearsal remain open. Audience alignment and current
  Spark scene/camera/reset access are also still missing.

Use this checkpoint and the requirement table for current state. The chronological
finding ledger below preserves what was observed at each stage; an early “Open”
entry is not proof that no later fix exists. Linked receipts define verification
scope and known exceptions.

### Resume prerequisites

The latest browser inventory still contains only the old connection-error tab.
An earlier automatic approval review rejected reloading its restricted `data:`
URL; no alternate browser/navigation workaround was attempted. The app's latest
independent runtime check passes. User reopening `http://10.88.9.12:7777/` inside
Codex unblocks the rendered monitoring/export checks and presenter rehearsal.

For the requested Spark chapter, provide current scene/RTSP access and reset
operation, plus confirm the proposed industrial-operations/five-minute audience
and format or supply alternatives. The existing replay remains clearly labelled.
All diagnostic trials and startup processes are terminal; no agent process is
waiting in the background. Resume the UI review first once browser access is
restored; retain the captured edge-entry miss as a known limitation pending a
controlled follow-up. The overall goal is not complete.

This is the running record for the customer-demo transformation goal. Update it
after each meaningful audit, decision, implementation, or verification step.
Observed behavior, proposals, and verified changes are separate below. This
document does not supersede runtime safeguards or qualification receipts.

## Goal

Make this local Jetson application a compelling demonstration of what video,
livestreams, and AI can do for a business. A visitor should quickly understand
the problem, see useful intelligence grounded in real footage, and understand
the significance of processing it locally. The objective is a persuasive,
reliable demonstration, not a product being prepared for sale.

The scope includes every page and end-to-end flow, rigorous critique, industry
research, a cohesive visual and interaction redesign, fast responses, and
verification on the running device. Isaac Sim on the user's DGX Spark can
provide repeatable scenarios and RTSP cameras once access is established.

## Success criteria and evidence required

| Requirement | Evidence needed | Current state |
| --- | --- | --- |
| Clear business story and audience | Agreed audience, scenario, and presenter journey | Awaiting alignment |
| Complete UI audit | Every page, subview, and meaningful flow inspected; findings tracked | Primary pages, recorded journeys and bounded RTSP report flow inspected; populated monitoring/analytics and remaining responsive/export checks incomplete |
| Relevant industry use cases | Primary-source research connected to actual app capabilities | [Scenario research completed](research/2026-09-28-edge-video-demo-scenarios.md); selection pending |
| Cohesive, compelling UI | Implemented experience reviewed in browser, with before/after evidence | Home redesigned; Explore, Events, Insights, reports and source states improved; full cohesion/rehearsal still open |
| Fast demonstration | Measured time to useful evidence and answer completion for key actions; no routine 30+ second waits in the core presentation | Recorded movement answers 7.5–11.2 s; recent RTSP questions observed complete by 12.4–16.4 s. Five-second monitoring diagnostic first response5.94s; full event-to-UI timing and sustained rehearsal remain unqualified |
| Real video and live intelligence | Working playback, retrieval, visual reasoning, monitoring, evidence/report flow; explicit distinction between live and recorded examples | Recorded search/answer/report and RTSP replay → fresh question → exact interval → saved report verified in bounded runs; continuous monitoring/alerts unqualified |
| Repeatable simulator scenario | Known scene, camera connection, scripted incident, and repeatable reset | Spark access/scenario details pending |
| Reliable local operation | Demo rehearsal with memory guard preserved and runtime/storage checks | Latest core check:31roles passing,54.43GiB available; bounded five-second trial minimum54.267GiB. Historical guard trips and storage constraints mean sustained presentation/ingestion remains unqualified |
| Running documentation | Findings, decisions, changes, tests, open work updated as work proceeds | Incremental findings, screenshots, validations and limitations recorded |

## Alignment still open

1. First audience/industry. Proposed default: warehouse/industrial operations,
   with other industry examples around a strong central story. Not yet agreed.
2. Presentation format. Proposed default: a five-minute guided path with deeper
   exploration available. Not yet agreed.
3. DGX Spark access, existing Isaac Sim scenes, and RTSP URLs; whether the user
   or this task will operate the simulator.

The user subsequently said **“please fix these as you go”**, authorizing fixes
to confirmed findings alongside the audit. Broader audience/scenario choices
remain proposals; they are not inferred from the absence of a reply.

## Baseline and constraints

- Running URL: `http://10.88.9.12:7777/`, page title `Vision Intelligence`.
- Source-mounted Next.js/Turbopack development. Follow
  [UI development](ui-development.md); avoid full image rebuilds for UI work.
- Preserve the active 48 GiB diagnostic memory guard. Earlier 36 GiB references
  are not authorization to lower this floor.
- September 28 status check: 31 core service roles, no failures reported by
  `python3 artifacts/thor-memory-2026-09-09/manage.py status`; 50.97 GiB available.
  Some roles only have process status, not Docker health checks.
- UI returned HTTP 200; sampled recent UI/agent logs contained no errors.
- Disk: 99% used, approximately 14 GiB free. No cleanup performed.
- Both detectors stopped; live ingestion paused. Do not infer live readiness
  from healthy core services.
- Existing extensive uncommitted changes are part of the baseline. Preserve
  them; do not attribute them to this goal.
- Supporting runtime evidence: [September 28 recovery](../artifacts/thor-recovery-2026-09-28/README.md),
  [runtime rules](../tools/runtime/README.md), and
  [prior full app audit](qa/2026-09-09-full-app-audit.md).

## Audit findings

Severity here means impact on a persuasive and trustworthy demonstration.
Findings are not resolved until the changed behavior is verified.

| ID | Surface | Observed evidence | Demo impact / proposed direction | Status |
| --- | --- | --- | --- | --- |
| D01 | Home | Previously led with paused-camera brief and unavailable previews. | Now leads with real recording preview, source-scoped search, and Find → Inspect → Ask/share journey. Source rows retain paused states. Real playback and search verified. | UI improved; audience/scenario and QA source naming remain open |
| D02 | Capabilities | All six entries previously labeled themselves `Ready on this Thor`, including blocked history and paused live intelligence. | Now uses workload admission and retained/indexed evidence; live and alerts explicitly require checking sources. Source-level live readiness is not claimed. | Fixed; regression + desktop/mobile browser verified |
| D03 | Navigation | Primary navigation has Live, Monitoring, and Events; these also share Monitor, Activity, Insights, and Rules tabs. | Multiple naming/navigation layers make the story harder to explain. Assess consolidation around customer tasks after full flow audit. | Open; observed; proposed remedy not decided |
| D04 | Explore | Entry view shows source, time, footage, and verification filters before a broad search invitation and generic prompts. | Visitor must invent a useful query and understand filters before seeing evidence. Provide scenario-specific starting questions grounded in available footage. | Open; entry view observed; search flow pending |
| D05 | Events / Activity | Zero incidents; the only saved investigation is a resolved QA audit from September 9. Empty state suggests changing filters or refreshing. | No convincing incident-to-evidence story is available from the default view. Need repeatable, honestly labeled scenario evidence, not fabricated incidents. | Open; observed in browser |
| D06 | Events / Insights | Operational Briefing, incident chart, source breakdown, and verification outcomes all show zero/no events. | Empty analytics consume attention without explaining a business outcome. Design useful scenario context and evidence-aware empty states. | Open; observed in browser |
| D07 | System | Exposes useful local pipeline, service health, memory, and workload admission, including blocked history/calibration/audio. | Strong proof of local operation exists, but it needs a concise presenter treatment and consistent capability claims elsewhere. | Opportunity; observed in browser |
| D08 | Live | Unknown source state was treated as healthy; `Review source` opened Events instead of that source. Settled sources were paused. | Unknown/delayed/changing sources now use attention styling; source items open their focused camera. Removed `No action needed` inference. | Fixed; component regression and real source handoff verified |
| D09 | Monitoring | Initial loading view reported zero rules, then settled at two enabled rules. Fetch failure could also imply no rules existed. | Shows checking/unavailable counts until the catalog is known; outage no longer renders the empty-catalog invitation. | Fixed; pending/failure regression and settled browser state verified |
| D10 | Rule builder | Default unavailable Isaac Sim camera advanced to a blank black zone editor. | Editor now waits for decoded image/playing video, blocks drawing/review without a frame, and offers retry/back after an eight-second wait. | Fixed; failing regression turned green; unavailable and recovered real source paths verified |
| D11 | Explore navigation | Search, source filter, selection, and completed briefing disappeared after visiting Live and returning. | Lazily retains Explore within the app session, releases the viewer on departure, pauses inactive catalog retries, and preserves in-flight analysis. | Fixed; failing shell regression turned green; real in-flight and completed AI result preserved across navigation |
| D12 | Fresh evidence analysis | One ten-second clip took 25.862 s, then 34.382 s. Instrumented baseline: 21.803 s (12.803 s inspection + 8.793 s synthesis). | Single fresh clip now returns the original cited visual answer without redundant synthesis: 13.262 s in browser. Multiple clips and retained captions still use synthesis. | Improved; first-answer streaming and broader latency qualification remain open |
| D13 | Evidence timestamps | Recorded search result correctly says `0:00 into recording`; selected-evidence tray, timeline, and report showed synthetic calendar time. | Tray, timeline, and newly saved reports preserve the recording-offset label; exact retrieval timestamps stay intact. Older saved records without this metadata keep their old display. | Fixed for new flow; browser report and API regression verified |
| D14 | Source management | Opening the source inventory requests pictures for four unavailable simulator cameras, producing four upstream HTTP 500 console errors. | Handle unavailable preview states consistently; connectivity still needs repair. | Preview handling fixed; browser fallback labels and retained thumbnails verified; camera connectivity remains open |
| D15 | Evidence lifecycle | A pending response could restore an answer after its selected evidence changed; previous saved-report state could survive a new analysis. | Invalidate responses by selection/analysis revision and reset panel state for a new revision. | Fixed; delayed-response regression passes |
| D16 | Single-clip answer | Fresh answer repeated verbatim as both headline and observed claim. | Show once with its playable citation. | Fixed in app and standalone report; see D18 |
| D17 | Report media retention | Uploaded recording path rejected; after mounting it, epoch-based seek generated a one-second clip for a five-second request. | Read-only recording root, VIOS recording timeline origin, and duration validation before reuse/save. | Fixed for sampled file flow; 0–5 and 3–8 second outputs verified as five seconds |
| D18 | Standalone report/export | Report repeated its answer in three locations, showed an empty interpretation panel, and downloaded HTML used relative API URLs. | One answer with citations; only populated/distinct claims; offline briefing export with absolute links back to device-hosted video. | Fixed for verified single-clip flow; offline file, local citations, return link, mobile, and print styling checked |
| D19 | Live connectivity | All five configured live sources report offline from VIOS, while app mostly said Paused. | Connection state now overrides analysis status for disconnected sources in Home/Live, with camera/simulator recovery guidance. | Fixed; actual VIOS states and rendered labels verified; recovery polling unit-tested |
| D20 | Preview integrity | Proxy unavailable illustrations could be accepted as real camera frames and unlock zone editing. | Reject responses marked `X-Vision-Image-Fallback` in both the canvas and inventory preview loader; explain missing previews. | Fixed in code; canvas regression and inventory browser verification pass |
| D21 | Saved evidence availability | Incident-request failure prevented rendering saved investigations even when their independent request succeeded. | Separate saved-report refresh from incident availability and retain labeled previous results if refresh fails. | Fixed; unit tests and browser fault injection verified report access |
| D22 | Visual answer accuracy | Saved five-second answer claims box placement; final cited frame still shows the worker holding it. Revised prompts also produced unsupported action continuations. | Temporal grounding and concise answer instructions added; inspect model/frame handling and qualify answers against footage. | Open; prompt revisions alone did not establish accuracy |
| D23 | Inference request fidelity | Deployed vLLM wrapper drops explicit temperature zero and applies nonzero values after construction. | Pass temperature into SamplingParams construction in all generation paths. | Deployed; 2 focused tests pass; two identical supported answers at 12.0/10.6 s; broader accuracy remains open |
| D24 | Evidence recovery | Try again dropped a failed specific question and submitted general analysis. | Retain the last submitted question and use a dedicated retry callback. | 19 scoped tests and TypeScript pass; browser request equality verified under injected 503 |
| D25 | Multi-clip pacing and fidelity | Real two-clip answer took 40.2 s; synthesis changed stopping movement into stopping holding a box. | Generate only a concise comparison and preserve original per-clip observations. | 9 backend tests pass; real repeat 40.2→30.8 s, still above pacing target |
| D26 | Perceived multi-clip wait | Completed inspections were hidden until all clips and synthesis finished. | Stream cited per-clip observations and distinguish partial results from final analysis. | Real E1 at 13.5 s, final at 27.6 s; backend/UI tests and browser checks pass within documented scope |

The initial pass inspected Home, Capabilities, Live, Monitoring, Explore,
Events/Activity, Events/Insights, and System. It does **not** constitute a full
flow audit. Sources administration, rule creation, source focus/history, real
search, playback, visual questions, evidence synthesis/export, and responsive
behavior still require current-session inspection.

## Decisions

- September 28: keep a single linked progress record and add supporting evidence
  as needed. User explicitly requested running documentation.
- September 28: perform read-only discovery before audience/scenario alignment.
  No runtime changes, service restarts, data deletion, or UI edits in this pass.
- Proposed, not accepted: one central industrial story rather than many shallow
  industry demos; a short guided path with optional depth.
- September 28: user explicitly authorized fixing findings as the audit proceeds.
- September 28: preserve the accepted general-app architecture in ADR 0005.
  Industry scenarios should use common workflows, not separate industry apps.

## Change and verification log

### September 28 — goal creation and baseline discovery

- Created the persistent goal covering the full transformation, including
  research, all UI flows, performance, actual local functionality, and testing.
- Read runtime and source-mounted UI workflow guidance; inspected current git
  status and the September 28 recovery receipt.
- Checked HTTP, container status, memory guard, disk space, and recent logs.
- Used the frontend testing skill. Browser plugin/skill was not available;
  used the available Playwright MCP browser tools against the existing server.
- Navigated primary workspaces through visible navigation controls, inspected
  accessibility/visible text, and exercised the Insights subview.
- Browser console inspection returned zero errors and zero warnings for this
  limited navigation session. This is not a claim about untested workflows.
- Saved a Home screenshot through Playwright (`demo-audit-home-before.png` in
  the tool output). Screenshot was captured, but a detailed visual inspection
  is still pending; findings above rely on browser text/state and source.
- Inspected `CapabilitiesWorkspace.tsx` to confirm the readiness logic behind
  D02. Located long timeout paths in evidence/analyst APIs; timeout values alone
  are not latency measurements and no performance claim is made from them.
- Added this progress record and linked it from the documentation index.

### September 28 — deeper audit, research, and first fixes

- Research skill delegated a bounded primary-source investigation. Result:
  [industry scenarios](research/2026-09-28-edge-video-demo-scenarios.md). Proposed
  story is notice → inspect → find → explain → share. Isaac Sim 6.x documents
  camera RTSP, but the Spark's installed version and connectivity remain unknown.
- Inspected source administration, RTSP configuration, rule-builder entry and
  zone drawing, recorded source focus, history panel, source Q&A, evidence
  selection/analysis, and the save-investigation form. Cancelled creation forms;
  did not save rules, add feeds, upload a new file, or start ingestion.
- Real scoped search `person in a warehouse` found the ten-second QA recording
  in 224 ms from click to rendered matching result. Playback began in 301 ms,
  with duration 10 seconds, readyState 4, and no media error. These are individual
  warm small-fixture samples, not capacity or percentile benchmarks.
- Two fresh evidence-analysis HTTP requests completed in 25,862.4 ms and
  34,381.5 ms using browser resource timing. Both returned cited observations.
  The source-specific question about helmet color returned yellow with an
  inspected range of 0:03–0:10. Its timing was not captured because the browser
  resource buffer was full; buffer capacity was increased for subsequent checks.
- Confirmed serial per-clip fresh inspection followed by synthesis in
  `services/agent/src/vss_agents/api/evidence_analysis.py`. Model-output accuracy
  beyond the inspected helmet-color example has not been independently scored.
- Implemented D02/D08/D09/D11 in `CapabilitiesWorkspace.tsx`,
  `VisionIntelligenceApp.tsx`, `InvestigateWorkspace.tsx`, `useVisionStreams.ts`,
  `OperationsWorkspace.tsx`, `AlertRulesWorkspace.tsx`, and scoped CSS.
- The investigation regression failed before the fix with an empty draft after
  navigation. After the fix, the browser preserved a real running analysis while
  visiting Capabilities, then preserved its completed result through Live →
  Explore. Query, source filter, selection, and answer were retained; only one
  analysis request was recorded. Persistence is within this page session, not
  across a browser reload.
- Tests: 27 passed across shell, Capabilities, source hook, and Investigate;
  16 passed across Operations and Monitoring. A new live-source unit test first
  hit JSDOM's missing MediaStream API; the test now isolates the preview component
  while exercising the actual navigation/status behavior. Live transport is
  covered separately by browser observations, not this mock.
- Browser: 1440×900 desktop, 390×844 mobile Capabilities check with no horizontal
  overflow. Meaningful rendered content, correct page title/route, and no
  framework overlay. Four inventory-picture HTTP 500 errors and a failed live
  playback request mean the full audit session is **not console-clean**.
- Evidence screenshots and verification details:
  [September 28 evidence](qa/demo-transformation-2026-09-28/README.md).
- Final checks for this batch: affected app TypeScript check and `git diff --check`
  passed. Core status still reports 31 roles and no failures, with 49.98 GiB
  available. The 48 GiB guard and paused-ingestion configuration were preserved.

### September 28 — zone-editor recovery fix

- Reproduced the blind-drawing defect in a focused regression: Add point was
  enabled before any source frame existed.
- `VisionStreamCanvas` now reports usable preview availability from actual video
  playback or successful image decoding, not merely a returned image URL.
- `MonitoringRegionEditor` waits for that availability, disables polygon creation
  while unavailable, and shows an actionable timeout with Retry preview. The
  wizard also gates Review rule and explains that a retained frame may be used.
- Real browser check: Isaac Sim CamNE → zone editor showed the unavailable state
  and disabled Add point/Review rule. Back → Traffic source loaded a real 1280 px
  retained image; three points could be added and Review rule became enabled.
  Closed the wizard without creating or activating a rule. Live motion remains
  unqualified; retained preview success does not establish live playback.
- Scoped tests: 24 unique tests passed across region editor, stream canvas, rules,
  and Operations in the scoped runs. The new timeout test needed
  a named status locator because the harness's output element also has status
  semantics. TypeScript and diff checks passed for the code changes.
- Desktop screenshots inspected: [unavailable](qa/demo-transformation-2026-09-28/rule-zone-unavailable-after.png)
  and [recovered](qa/demo-transformation-2026-09-28/rule-zone-recovered-after.png).
  Screenshots precede the final retained-frame explanatory wording.

### September 28 — measured single-clip latency improvement

- Added server timings for inspection, synthesis, and total to the evidence-analysis
  response. A real browser request on the retained 10-second warehouse QA clip
  measured 21.803 s end-to-end: 12.803 s inspection and 8.793 s synthesis.
- The fresh visual inspection already receives and answers the current question.
  For exactly one selected, freshly inspected clip, return that answer directly,
  retaining its uncertainty, source citation, and timestamps. Do not invoke a
  second text model solely to rewrite it. Multiple selections (including partially
  available selections) and stored captions keep the synthesis path.
- Repeated the real browser request after the change: 13.262 s end-to-end,
  13.102 s inspection, effectively zero synthesis. About 39% lower elapsed time
  for this pair of runs, not a percentile benchmark or a universal latency claim.
  Earlier uninstrumented runs ranged 25.862–34.382 s. No frame-count reduction,
  model-budget changes, fabricated output, or response cache was used.
- Nine backend tests pass, including fresh single-clip bypass, stored-caption
  synthesis, multi-clip coverage, follow-up grounding, and degraded synthesis.
  Test dependencies were installed only into `/tmp/vss-demo-test-deps` inside
  the running agent container; application dependencies were unchanged.
- Restarted only the source-mounted agent to load Python changes; its health
  endpoint returned 200 for the timed browser requests. Ingestion auto-resume
  remains disabled and the 48 GiB guard unchanged. Updated loading text to describe
  local evidence inspection without implying every response uses two models.
- Still open: progressive results, multi-clip latency, repeated fresh/follow-up
  measurements, concise answer presentation, and verification against a live
  scenario. This does **not** meet the complete demo goal yet.
- A further real run after the final agent restart measured 21.002 s server
  inspection with 0.1 ms synthesis (21.374 s browser test including render and
  screenshot). The longer visual answer shows substantial inspection variance;
  do not advertise a consistent 13-second response. Agent health returned 200.

### September 28 — recording offsets through the evidence workspace

- Selected evidence now carries its existing recording-relative label from
  search into the tray and generated timeline. Exact timestamps used for video
  retrieval and citations are unchanged. Unknown offsets retain the clock display.
- Browser verified both locations show `0:00 into recording` for the warehouse
  QA clip; timeline label is now a concise `Visual inspection` for direct answers.
  [Screenshot](qa/demo-transformation-2026-09-28/analysis-time-and-offset-after.png)
  was inspected. The developer hot reload reset the search, which was rebuilt;
  this was not a workspace-navigation persistence failure.
- Sixteen investigation UI tests and the affected app TypeScript check pass;
  backend tests remain nine passing, and `git diff --check` passes.
- Remaining: persisted/exported report timestamp presentation, overly long answers,
  and the duplicate summary/observation presentation visible in the screenshot.


### September 28 — evidence-first Home implementation

- Previous turn classified as progress: real measured latency reduction and
  rendered recording-offset fixes, not a status-only continuation.
- Replaced the environment-brief/card-grid opening with a dominant real source
  preview, scoped search action, three-step evidence journey, and compact source
  rows. Indexed recordings outrank paused cameras in the initial source choice.
  Retained the broad environment analyst under an optional disclosure and linked
  local processing proof directly to System. Removed unconditional replay “Ready”
  while index status is still unknown.
- Created and inspected a built-in Image Gen concept, then implemented using real
  source footage only. The generated warehouse illustration is documentation,
  never evidence. [Working spec and visual comparison](qa/demo-transformation-2026-09-28/home-design.md)
  record intentional shell/media/copy adaptations; industry alignment stays open.
- Browser: actual 10-second/1920px recording plays and pauses; Home search hands
  off `people moving` scoped to the exact recording and returns one usable match.
  System link opens System. Desktop 1440×900 and mobile 390×844 screenshots
  inspected with no mobile horizontal overflow. Source rows still label live
  feeds Paused; no live-ready claim is made.
- Fixed inherited Home playback-bar positioning and Presentation exit contrast,
  including hover. Retained-image preview can appear before playback; it is not
  counted as playback proof. Real source name remains a QA name pending scenario
  selection; the visual redesign does not solve demo content quality by itself.
- Eight scoped tests pass across Home and shell, including the exact source
  handoff. TypeScript and diff checks pass. An initial test command used the wrong
  working directory and failed to create its new test; rerun from correct paths
  passed. No runtime services or budgets changed in this UI pass.
- Core status: 31 service roles, no failures, 50.24 GiB available. Existing
  diagnostic reserve and paused ingestion preserved.

### September 28 — evidence lifecycle, report offsets, and retained clip repair

- Previous turn was progress: implemented and browser-verified Home redesign.
- Evidence selection changes now invalidate pending analysis results. Starting a
  new analysis clears the old answer and resets the report form/save state, so
  users cannot save an obsolete answer during a follow-up. A delayed-response
  test changes selection during analysis and proves the old result is discarded.
- Exact duplicate summary/observation text now appears once in the app with its
  citation. The existing test tried saving before follow-up completion; it now
  waits for the current answer. New recording-offset metadata survives server
  validation, persistence, and HTML rendering. Old records are not rewritten.
- Real Home → search → fresh inspection → save → report → playback completed.
  Inspection measured 22.324 s on a five-second result; latency remains variable.
  Report save first returned in 140 ms but correctly marked source-retention
  fallback. The report displayed `0:00 into recording` and played five seconds
  through VIOS. This exposed that local clip retention itself was broken.
- Root cause: VIOS imports use `/home/vst/vst_release/streamer_videos`, but the
  support service only mounted camera archives. Added `/recordings` read-only
  mapping to the active support Compose and checked-in Thor Compose. The active
  support service now source-mounts `server.py`; the built fallback needs its
  normal future image rebuild to include the Python changes.
- Second defect discovered during verification: imported media PTS starts at
  zero; treating it as epoch time produced a one-second output. File-backed clips
  now resolve their origin from VIOS timelines. Output duration must match within
  250 ms, including cached outputs; incomplete old clips are rebuilt. Path
  traversal/symlink escape protections remain enforced for both read-only roots.
- Verified 0–5 and 3–8 second requests both produce five-second files. The saved
  retained report plays the corrected five-second media in-browser. Exact semantic
  correctness of every generated description is not certified by playback alone.
- Created two explicitly labeled, resolved, low-severity QA reports:
  `6857ccd8-440a-44e7-bc14-ca3304c211db` (fallback) and
  `de58b97b-8912-4a93-bfdf-ebec066250b8` (retained). The second reused the real
  recorded analysis via the same API; no model result was fabricated. Its initial
  one-second cached media was rebuilt under the same key and rechecked at five
  seconds. The clip cache remains bounded/evictable, not permanent preservation.
- Checks: 20 UI/API tests, 8 support-service tests, TypeScript, and diff checks
  pass. Only the small support service was recreated/restarted; no models or
  ingestion started. Final core status: 31 roles, no failures, 50.04 GiB available.
  Guard remains 48 GiB. Browser screenshots are in the linked evidence record.
- Still open: standalone report hierarchy/export, latency consistency, actual
  live flow, and the wider audience/scenario alignment and final rehearsal.

### September 28 — report presentation and usable offline briefing export

- Previous turn was progress: stale-result/offset fixes and repaired retained
  media path/timestamp calculation, verified against actual five-second clips.
- Report now displays a duplicated single-clip answer once, retaining its
  citations; distinct observed claims remain. Empty interpretation sections are
  omitted. Evidence rows give inspection provenance instead of repeating the
  answer again. Added Export briefing and Print / Save PDF actions to the report.
- Downloaded HTML contains the briefing, notes, source context, and local anchor
  citations without remote images, videos, fonts, or stylesheets. Video links use
  the request's validated device origin and open the hosted report's exact
  evidence anchor. Export explicitly states that playback needs Jetson network
  access and cached clips can expire. This is not an offline video package.
- Browser: existing real QA report renders the shorter hierarchy. Export link
  triggered a browser download; the automation's `saveAs` encountered a missing
  transient download artifact. Retrieved the same download endpoint to the
  documented HTML file, then opened it with `file://` and browser networking
  disabled. Briefing remained visible and View E1 navigated locally. Restored
  networking; Open playable evidence opened a new device report and played the
  retained five-second clip. No new report/model output was created in this pass.
- Desktop, 390×844 mobile, and print-media screenshots inspected; no mobile
  horizontal overflow. Print styling checked in browser, not physical printing
  or a paginated PDF export. Four API tests, TypeScript, and diff check pass.
- Evidence: [offline HTML](qa/demo-transformation-2026-09-28/exported-briefing.html),
  [desktop report](qa/demo-transformation-2026-09-28/report-simplified-desktop.png),
  [mobile export](qa/demo-transformation-2026-09-28/report-export-mobile.png),
  [print styling](qa/demo-transformation-2026-09-28/report-export-print.png).
- No runtime services, model budgets, guard settings, or source states changed.
  Full demo completion remains unproven: live scenario/access, complete flow
  coverage, latency consistency, and audience alignment still require work.

### September 28 — live connectivity discovery and truthful source states

- Previous turn was progress: report simplification and offline briefing export
  verified with browser networking disabled and a working link back to playback.
- Asked for current DGX Spark address, RTSP URLs, and whether Isaac Sim is running.
  This is missing integration context, not a request to approve already-authorized
  fixes. Audience and presentation-format questions remain open.
- Read VIOS sensor status, stream catalog, and sensor list using the video I/O
  skill's documented API. Version endpoint is healthy. All five registered live
  feeds report offline/CameraNotFoundError; the QA file is online. Simulator sensor
  records point to `10.88.8.191`; proxy stream URLs still advertise former Thor
  address `10.88.8.175`. These are stale-looking catalog facts, not proof of the
  current Spark address or permission to rewrite camera configuration blindly.
  One unnamed sensor has no streams and inconsistent list/status error metadata.
- `useVisionStreams` now retrieves independent connection states without delaying
  initial catalog display, polls every 15 seconds while active, and stops polling
  in hidden workspaces. Status failures yield unknown rather than asserting an
  online/offline state. Unchanged polling responses preserve stream identities.
- Home and Live show Disconnected for observed offline/removed sources even when
  AI is paused; guidance directs the operator to camera/simulator connectivity.
  Known disconnected sources do not count as actively analyzing. No inference,
  service restarts, live registration, or ingestion was performed.
- Thirty-three scoped tests passed across source hook, Operations, Home entry,
  and investigation. Focused rerun after the nonblocking catalog adjustment passed;
  TypeScript and diff checks pass. Tests cover offline→online status recovery and
  stopping background polling; real camera recovery remains untested until a feed
  is available. Browser verified Home and Live against actual offline sources.
- Screenshots: [Live status](qa/demo-transformation-2026-09-28/live-connection-status.png)
  and [Home source rows](qa/demo-transformation-2026-09-28/home-connection-status.png).
  Live screenshot precedes the final wording “reports this source as disconnected”;
  Home screenshot caught the recording index check before it settled Searchable.
- Live playback/ingestion qualification is still open. There is further independent
  UI/audit work, so missing simulator details do not block the entire goal yet.

### September 28 — unavailable previews and camera onboarding audit

- Same-origin source pictures now use the existing image proxy, matching remote
  picture handling. The shared loader rejects marked fallback illustrations;
  source cards display “Preview unavailable” instead of an unexplained icon.
- VisionStreamCanvas also rejects proxy fallback illustrations before decoding.
  This prevents a placeholder from satisfying the real-frame prerequisite for
  zone editing. Temporary fallback text no longer asserts the camera is connected.
- Scoped validation: 12 canvas/proxy tests and 24 shared picture/card tests passed;
  app and shared-package TypeScript checks passed. The final text-label change
  was followed by another passing 24-test run. Diff check passed.
- Browser: System → Sources renders four unavailable simulator previews and two
  valid retained thumbnails. Sampled picture requests used the same-origin proxy
  with HTTP 200; no console errors in the sampled interaction. This does not
  establish full-session console cleanliness or working live connectivity.
- Add RTSP camera opens and loads installed profiles. Both detection profiles
  correctly report their detector worker offline. No camera was submitted or
  registered; actual onboarding awaits current simulator connection details.
- QA script initially timed out after reload because System defaults to Edge
  system, not Sources. Explicitly selecting Sources completed verification.
- Evidence: [source inventory](qa/demo-transformation-2026-09-28/source-preview-fallbacks.png).
  Remaining visual issue: shared inventory uses green LIVE/source-type badges
  even for offline cameras, unlike the corrected Home/Live connection labels.
  Keep this distinction open for the next source-management pass.
- No services, inference workloads, memory reserves, or ingestion states changed.

### September 28 — source type versus preview provenance

- Previous turn made progress: placeholder rejection, readable missing previews,
  and camera-form inspection. Continued the identified misleading green badges.
- Inventory now labels RTSP source type neutrally as “RTSP CAMERA”. Successful
  replay thumbnails explicitly say “Recorded preview”; freshly requested camera
  images say “Camera snapshot”. Neither implies a currently healthy connection.
  Unavailable images retain one clear message instead of duplicate status text.
- Browser verified two recorded previews and zero green live/source badges.
  Source-card tests cover the retained-preview label. The new assertion initially
  failed because its fixture intentionally rejected every thumbnail; providing a
  successful image fixture corrected the test. 22 scoped tests pass;
  package TypeScript passed before the final label-only cleanup. One existing
  clipboard test emits an async act warning; this is not a browser runtime error.
- [Rendered evidence](qa/demo-transformation-2026-09-28/source-preview-provenance.png).
  Preview failures can still take multiple seconds while upstream requests time
  out and queue; reducing that delay is a remaining source-management issue.
- No live feeds, models, services, or memory budgets changed. Full goal remains
  open, including scenario alignment, live qualification and final rehearsal.

### September 28 — Events entry and next actions

- Previous goal turn made progress by separating camera type from preview provenance.
  This pass inspected settled Events: zero incidents and three QA/demo verification
  investigations, rather than the original single September 9 report.
- Replaced the empty-state green check and generic refresh advice. With no records,
  Events explains the monitored-condition → footage → verification journey and
  provides Check cameras / Review monitoring rules actions. With records hidden
  by a filter, it offers Show all records. Empty data does not imply active monitoring.
- Intro no longer implies every displayed event has already been verified; individual
  verification and review states remain the evidence of that status.
- Browser verified both navigation actions, settled Monitoring catalog, and Events
  at 390×844 (document width 390, no horizontal overflow). Desktop screenshot
  inspected. Three existing incident tests and app TypeScript passed; diff check passed.
- Evidence: [desktop](qa/demo-transformation-2026-09-28/events-next-actions.png),
  [mobile](qa/demo-transformation-2026-09-28/events-next-actions-mobile.png).
- D05 is improved, not closed: there is still no actual triggered event to rehearse
  end-to-end. The filter-specific branch is code-reviewed, not exercised against
  a live incident catalog. Existing tests cover incident evidence retrieval.
- No ingestion, service configuration, model budgets, or memory safeguards changed.

### September 28 — Insights explains evidence before presenting metrics

- Previous turn made progress on Events empty-state actions. This pass confirmed
  Insights displayed zero-filled charts and “0% confirmed” with no incidents.
- With no operator-relevant incidents, Insights now explains three concrete
  questions: when activity concentrates, where to look, and which observations
  need verification. Charts render when event evidence exists. Actions lead to
  cameras, monitoring rules, and the actual saved-investigation count.
- Browser verified the three-investigation handoff, desktop and 390px layouts,
  and mobile rule navigation after scrolling. No horizontal overflow. The mobile
  full-page screenshot includes the fixed bottom navigation; real scrolling and
  click verified the controls remain reachable.
- Four scoped tests pass, including absence of a zero confirmation percentage
  without records. App TypeScript and diff checks pass. Actual populated analytics
  remains unverified because the current catalog has no operator incidents.
- Evidence: [desktop](qa/demo-transformation-2026-09-28/insights-evidence-entry.png),
  [mobile](qa/demo-transformation-2026-09-28/insights-evidence-entry-mobile.png).
- D06 improved for empty data, not closed for the complete demo. Runtime and
  ingestion untouched; no simulated statistics or incidents were introduced.

### September 28 — simpler Explore entry

- Previous turn improved Insights with evidence-aware entry and verified handoffs.
  Current Explore entry still exposed four selectors before explaining its flow.
- Kept source selection visible; grouped time, footage type, and review status
  under a native keyboard-accessible Refine search disclosure. Nondefault controls
  contribute to a visible active count even when collapsed.
- Entry now describes search → watch → select evidence → ask with citation.
  Suggestions use concrete visual descriptions; removed the “restricted areas”
  wording that implied policy understanding from semantic retrieval alone.
- Browser selected the actual QA recording and searched “People moving”, returning
  one five-second clip with recording-relative time. This pass used an explicit
  1.8-second observation wait, so it is not a search latency measurement.
- Browser verified footage refinement, rerun, collapsed active count, and 390px
  no-overflow layout. Seventeen Explore tests, app TypeScript, and diff check pass.
- Evidence: [entry](qa/demo-transformation-2026-09-28/explore-simple-entry.png),
  [mobile refinement](qa/demo-transformation-2026-09-28/explore-refinement-mobile.png).
- D04 improved but not fully closed: scenario-specific prompts still require
  audience/scene alignment, and generic examples are queries rather than promises
  that every source contains those objects. No model or live workload started.

### September 28 — consistent destinations and presenter runbook

- Previous turn improved Explore and verified real retrieval. Navigation now uses
  Live, Events, Insights and Monitoring consistently instead of Monitor/Activity/Rules
  aliases for the same destinations. Events content is headed Event review.
- Browser exercised Events → Live → Monitoring → Events with the matching URLs.
  Twenty-one scoped tests passed after updating one remaining old-label assertion;
  the initial run failed on that obsolete Rules/Monitor expectation.
- Added [presenter runbook](demo-presenter-runbook.md), documenting the verified
  recorded path, exact source/query, expected evidence, saved-report alternative,
  export limitation and unfulfilled live qualification gate. It is a working draft,
  not user agreement on audience or a declaration of demo readiness.
- Refreshed the top-level success table, which still described the initial audit
  despite subsequent work. D03 label consistency is improved; duplicate navigation
  layers remain a broader design consideration.
- Runtime untouched. Goal remains active; no completion claim.

### September 28 — saved briefings survive analytics failure

- Previous turn made progress on navigation consistency and a presenter runbook.
  Code audit found its saved-report fallback was coupled to incident API success.
- Saved investigations now load before incident-result handling and render even
  when analytics fails. Failed analytics is explicitly unavailable, not an empty
  catalog; stale incident rows are hidden and filters disabled in that state.
- A saved-report refresh failure preserves previously loaded links with a clear
  last-successful-load notice instead of silently clearing the list.
- Five scoped tests and app TypeScript pass. Browser-only injected incident HTTP
  503 left all three real saved reports visible and successfully opened the retained
  warehouse report. Injected saved-list 503 preserved three links with the notice.
  Interception was removed and ordinary refresh restored after each test.
- [Fault-injection screenshot](qa/demo-transformation-2026-09-28/events-analytics-outage.png).
  These are simulated request failures, not evidence that runtime analytics was
  actually down. No backend services or stored reports changed.
- Full demo remains incomplete; live scenario, sustained qualification and final
  rehearsal remain open. This pass strengthens the honest recorded fallback.

### September 28 — measured recorded-path rehearsal

- Previous turn fixed saved-report availability during analytics failure.
- Rehearsed Home → search → playback → evidence → fresh analysis → save → Events
  → report playback on the current app. Search result ready in 923 ms; fresh answer
  rendered in 15.244 s. Five-second playback verified in Explore and saved report.
- New low-severity resolved QA record explicitly identifies recorded test footage;
  no live incident was fabricated. Model-detail accuracy is not asserted by this
  integration rehearsal. Export was not repeated in this run.
- Core stayed at 31 roles/no failures in before/after samples; memory 49.68 then
  49.81 GiB; guard active. These endpoint samples do not establish peak usage.
- [Full rehearsal receipt](qa/demo-transformation-2026-09-28/recorded-rehearsal.md)
  records exact source, timestamps, API results, provenance, report ID, tool
  corrections and limitations. Goal remains active; full live demo unqualified.

### September 28 — older investigations remain reachable

- Previous turn completed a measured recorded-path rehearsal and saved a fourth
  report. Code audit found the list was permanently sliced to four entries, and
  the API selected 100 filenames before date sorting, silently losing visibility.
- Added Show older investigations in increments of eight, preserving a compact
  first view. Removed the API's arbitrary pre-sort cutoff so local saved records
  remain discoverable. This prototype still reads its local report collection;
  large-scale storage pagination is outside this change.
- Eleven scoped tests pass, including a temporary 101-file API fixture and six
  UI records. App TypeScript passed before test-only additions; diff check passes.
- Browser intercepted only the list response to add two explicitly labeled QA
  fixtures: four links initially, six after Show older investigations, no redundant
  more button. Interception removed and page reloaded; no demo records added.
- Runtime, model and ingestion settings untouched. Full goal remains incomplete.

### September 28 — remaining-goal audit and live prerequisite recheck

- Previous turn restored discoverability of older saved reports. This pass
  rechecked live prerequisites rather than treating recorded success as completion.
- Current VIOS status: four Isaac cameras and traffic offline; QA recording online.
  Registered simulator IP 10.88.8.191 responds to two ICMP probes (~0.94 ms).
  This establishes reachability, not Spark identity or working scene cameras.
- Requested current Spark/RTSP scene details and first audience. No remote
  configuration, camera rewriting, model startup or ingestion was attempted.
- Added [requirement-by-requirement acceptance audit](qa/demo-transformation-2026-09-28/acceptance-audit.md),
  covering real evidence and unresolved proof across every major surface. Full
  goal remains incomplete; populated live/incident/analytics and final audience
  rehearsal are the consequential next dependencies.

### September 28 — accuracy audit found unsupported action completion

- Previous turn rechecked live prerequisites and recorded acceptance gaps. This
  pass inspected actual cited frames at 0.1, 2.5, 4.7 and 4.96 seconds. The worker
  carries a box toward rolling steps; the final frame still shows it held. The
  saved answer's completed placement is not supported. Original report preserved.
- Updated the fresh-inspection prompt to distinguish observed movement from
  completed actions, avoid predicting the next action, check the final visible
  state, and use at most two short sentences/60 words without irrelevant inventory.
- Two fresh evaluations remain insufficient: initial revision took 23.885 s and
  inferred “begins to place”; concise revision took 12.474 s and inferred beginning
  to ascend. Neither demonstrates a reliable correction. D22 remains open.
- Checked agent logs for actual input and ffprobe on its generated MP4: request
  was 0–5 seconds and media duration exactly 5.000 seconds, start PTS zero. This
  rules out a simple full-ten-second input explanation for the sampled request;
  it does not audit every frame of the model's internal sampling.
- Agent only restarted twice to load changes; no models/detectors restarted.
  First test execution printed nine passes but was terminated during restart
  (exit 137); rerun after restart exited cleanly with nine passes, as did the final
  prompt's run. Agent health recovered; core 31 roles/no failures, 49.89 GiB available
  before final evaluation. Search during startup failed and succeeded on retry.
- [Rehearsal accuracy follow-up](qa/demo-transformation-2026-09-28/recorded-rehearsal.md)
  and [final frame](qa/demo-transformation-2026-09-28/rehearsal-final-frame.png).
  A citation proves traceability, not factual correctness. Final demo acceptance
  must include comparison of important model claims with the video.

### September 28 — frame-path inspection and usable report review

- Previous turn identified unsupported temporal claims (D22). Read the actual
  model/decoder path: agent logs request ten frames for five seconds; the fixed
  sampler targets start + i×duration/N, so nominal targets run 0–4.5 seconds.
  Request media_io_kwargs overrides the service's one-frame default. This is
  source/log evidence, not captured model-input tensors; D22 remains open.
- No model settings, frame counts, memory budgets or inference services changed.
  Did not claim a sampling bug or launch more prompt-only retries without a new
  hypothesis. A real accuracy evaluation remains required.
- Report playback was only 280 px wide on desktop. Clicking Play exact clip now
  expands its evidence card and displays the full frame with native controls,
  preserving aspect ratio rather than cropping it into the thumbnail.
- Browser measured 280→1118 px width after the actual play button, confirmed
  advancing playback, and checked mobile width 348 px within a 390 px viewport
  with no overflow. Five report API tests pass. Diff whitespace issue corrected.
- [Expanded review screenshot](qa/demo-transformation-2026-09-28/report-expanded-review.png).
  Better review access does not itself correct generated claims. The goal remains
  incomplete pending accuracy, scene/audience alignment and live qualification.

### September 28 — ask a specific question before general analysis

- Previous turn audited frame selection and expanded report playback. A bounded
  end-state question through the admitted app API returned “still holding a
  cardboard box” in 16.105 s, consistent with the inspected final frame.
  [Exact request/response](qa/demo-transformation-2026-09-28/final-frame-question.json).
- Found the UI required general analysis before exposing its question input.
  The same question form is now available immediately after evidence selection,
  avoiding an unwanted preliminary model call. General analysis remains available.
- Browser selected the real clip and submitted the question directly: one request,
  HTTP 200, rendered answer in about 17 s. Its first sentence correctly says holding
  a box, but its final sentence speculates about placement. D22 remains unresolved;
  the earlier good response is not evidence of consistent correctness.
- Eighteen scoped tests pass, including direct submission without onAnalyze;
  TypeScript and diff check pass. No model configuration or runtime budget changed.
- [Rendered direct question](qa/demo-transformation-2026-09-28/direct-evidence-question.png).
  This improves question-to-answer pacing but does not qualify temporal accuracy
  or finish the live/customer scenario goal.

### September 28 — honor requested inference temperature

- Confirmed active Cosmos3 Nano runtime identity and found the wrapper silently
  discarded temperature zero. All three generation paths now pass temperature
  directly to SamplingParams construction. The runtime has a read-only source
  mount for this fix; model weights, frame counts and reserve remain unchanged.
- Two focused regression cases (zero and nonzero) passed. The broader 26-case
  run was interrupted when available memory reached 47.958 GiB and the 48 GiB
  guard stopped model workloads. It did **not** pass. Do not run this broader
  model-import suite beside the loaded inference stack again.
- Guard remained active and the host did not reboot. With model processes
  confirmed stopped, the documented one-time idle reclaim recovered 101.93 GiB.
  Staged recovery restored all 31 core roles with no readiness failures. Guard
  remains active, boot ID unchanged; detectors and live ingestion remain paused.
- Identical final-frame questions returned identical supported answers in 12.005
  and 10.557 s. General description took 13.031 s without the earlier completed
  action claims, but object counts/spatial labels remain unverified.
  [Full evaluation and recovery receipt](qa/demo-transformation-2026-09-28/temperature-fix-evaluation.md).
- [Research and confirmed defect](research/2026-09-28-visual-grounding-diagnostics.md)
  and [guard trip receipt](qa/demo-transformation-2026-09-28/inference-test-reserve-trip.json).
  D22 factual accuracy remains open; deterministic sampling alone is not a
  correctness guarantee.

### September 28 — preserve the question through failure recovery

- The prior goal turn made progress: deployed temperature correction, repeated
  real-answer checks and restored runtime. This pass inspected selected-evidence
  recovery while auditing the multi-clip investigation flow.
- Reproduced D24 in the running browser using real search results and an injected
  HTTP 503: the original request included the question; Try again omitted it.
  Retry now uses the last submitted question. General analysis remains an explicit
  separate action, and changing evidence still clears the old error/answer.
- Nineteen tests across InvestigateWorkspace and EvidenceAnalysisPanel pass. New
  regression coverage selects two distinct clips, fails a specific question,
  asserts identical retry payload, then checks intentional general analysis.
  TypeScript and diff checks pass.
- Browser verified identical initial/retry payloads for the real ten-second QA
  recording under the simulated error. The interception was removed afterward.
  This verifies error recovery, not successful multi-clip inference or latency.
- [Recovery receipt](qa/demo-transformation-2026-09-28/evidence-retry.md).
  Full multi-clip narrative and live scenario acceptance remain unfinished.

### September 28 — real multi-clip comparison and synthesis correction

- Previous turn made progress by fixing failed-question retry. This pass submitted
  two real adjacent warehouse intervals through the admitted app API. Search UI
  currently groups those intervals; this does not qualify multi-clip selection.
- Baseline took 40.178 s, including 14.667 s synthesis. Synthesis changed stopping
  movement while holding a box into “stops holding the box”, contrary to its own
  source observation. D25 records both latency and the distortion.
- Synthesis now produces only a concise comparison. Original visual observations
  and citations are preserved, with timeline entries derived from them. Nine
  backend tests pass. Applied with agent-only restart; models and reserves unchanged.
- Identical request returned a faithful comparison in 30.762 s, including 4.809 s
  synthesis. This still misses the pacing target. Per-clip inspection took 25.805 s;
  no concurrent GPU workload was introduced. Original visual text still infers
  purpose (“to place”), so D22 remains open too.
- [Exact baseline, changed result and scope](qa/demo-transformation-2026-09-28/two-clip-comparison.md).
  Requested first audience/current Spark RTSP endpoint again; no response yet.
  Full live/customer-story acceptance remains incomplete.

### September 28 — show useful evidence before the full comparison

- Previous turn made progress with compact synthesis but still measured 30.762 s.
  Added progressive observations through agent, same-origin proxy and evidence UI.
  Each completed inspection gets a playback citation; partial results cannot be
  saved as a finished report. Existing JSON clients remain supported.
- Real two-clip request: first observation at 13.462 s, second at 25.990 s, final
  comparison at 27.581 s. This proves early delivery, not a latency percentile.
  No concurrent GPU work, reserve change or live-ingestion activation.
- 12 backend tests and 30 distinct UI/API tests pass across scoped runs. Tests
  cover fragmented/truncated streams, partial results, reservation lifetime and
  cancellation. TypeScript and diff checks pass. Agent-only restart applied it.
- Browser search transiently failed, then recovered on retry. Real one-clip
  streaming completed; temporary labeled fixture verified partial rendering,
  citation navigation and withheld Save action. Fixture was removed afterward.
- The real one-clip answer again contradicted itself about holding/placing a box;
  D22 remains open. [Progressive evidence receipt](qa/demo-transformation-2026-09-28/progressive-evidence.md)
  records timings, exact scope, screenshot and limitations. Full goal remains open.

### September 28 — live-scene dependency revalidated (blocked audit 1)

- Previous goal turn was progress: progressive evidence delivery implemented and
  verified. This turn rechecked the external dependency before attempting further
  live-demo changes.
- Current VIOS sensor list/status still reports all four Isaac Sim cameras offline
  with CameraNotFoundError. Stream records contain VIOS relay URLs on former Thor
  address 10.88.8.175; they do not expose a usable current Spark publisher endpoint.
  September 9 source receipts likewise identify only the old simulator host.
- Project setup documents treat simulation as operator-managed. Existing SSH
  configuration identifies a different host without evidence linking it to Spark;
  no connection to that unrelated host was attempted. No source rewrite, GPU
  startup or live ingestion was performed.
- Audience, current Spark/scene identity and actual RTSP publishing endpoint remain
  unanswered. These determine the representative business event and are necessary
  for meaningful populated Live/Events/Insights validation and final rehearsal.
- This is the first consecutive blocked audit after concrete independent progress.
  Goal remains active and incomplete. Do not count the earlier productive turns
  toward the three-turn blocked threshold. Further cosmetic changes or repeating
  the same clip cannot substitute for the missing live/customer scenario.

### September 28 — live dependency unchanged (blocked audit 2)

- Previous goal turn was no progress toward implementation: it revalidated the
  missing external scene/audience dependency. No user scene details have arrived.
- Fresh VIOS status again reports NE, SW, SE and NW offline/CameraNotFoundError.
  There is no confirmed running simulator job to wait on and no new RTSP endpoint.
- Meaningful remaining integrated validation requires the chosen audience and
  working scene. Existing recorded tests do not satisfy live event generation,
  populated analytics or end-to-end business rehearsal. No additional code or
  runtime changes were made solely to keep the goal moving superficially.
- Second consecutive blocked audit; goal remains active pending the required
  user input or a verified external-state change.

### September 28 — external dependency blocks continuation (audit 3)

- Previous turn was no progress: the required external dependency was unchanged.
  Third consecutive check again reports all four Isaac Sim cameras offline with
  CameraNotFoundError. No audience decision or current publisher/access details
  have arrived, and no confirmed running simulator job is available to wait on.
- Marking the goal blocked, not complete. Resume with the target industry/audience
  and a working Spark camera RTSP URL or sufficient scene access to establish one.
- Remaining scope includes representative accuracy evaluation, real live playback
  and event generation, populated Events/Insights, multi-source customer narrative,
  and a full timed rehearsal. Existing fixes and evidence remain in this log.
  Preserve the 48 GiB diagnostic floor when resuming staged live validation.

### September 28 — resume with existing footage; tradeshow-first opening

- User clarified that existing footage should support continued work and stressed
  the perspective of a tradeshow visitor with no prior product knowledge. Earlier
  broad blocked status was an incorrect scope judgment: simulator availability
  gates live integration, not recorded-demo design and usability improvements.
- Reworked Home around “Video AI · On this Jetson” and “Ask your video what
  happened.” Real recorded footage starts muted beside the explanation, with a
  single concrete action: “Find a person carrying a box”. Setup/source rows now
  expand from a disclosure; disconnected count remains visible while collapsed.
- The exact inspected recording has a visitor-facing alias, Warehouse — Box
  Handling, through the existing display-name mapping. Underlying source name,
  index identity and media are unchanged. Recorded/live labeling remains explicit.
- Browser verified moving recorded playback and a real source-scoped search for
  person carrying a box: HTTP 200, one five-second match. Mobile at 390 px has no
  horizontal overflow and shows the video by y=449–649 in an 844 px viewport.
- Home/utility tests: eight passed after updating stale copy assertions. Shell and
  Explore suites: 23 passed. TypeScript and diff checks pass.
- Simplified Home/Explore section captions and result instructions. Further visitor
  journey refinement remains active; live proof is still a separate dependency.
- [Design intent](qa/demo-transformation-2026-09-28/tradeshow-opening.md),
  [desktop](qa/demo-transformation-2026-09-28/home-tradeshow-desktop.png),
  [mobile](qa/demo-transformation-2026-09-28/home-tradeshow-mobile.png).

### September 28 — make search-to-question understandable to a first-time visitor

- Previous turn made progress on the tradeshow opening. Followed its actual CTA
  into Explore and found a small single match, repeated result counts, duplicate
  analysis actions, and the opaque “Use as evidence” transition.
- A single match now uses a large 16:9 preview with preserved full-frame contents.
  Its actions are Play clip and Ask about this clip; the latter selects the clip
  and focuses the question input. Multi-result selection remains available.
- Removed the redundant toolbar analysis action. The selected-footage panel now
  says Ask about this footage, with Describe what happens as its general-answer
  option. Shorter question placeholders fit mobile. Technical match explanation
  is behind Why this matched; source/time/provenance remain visible.
- Sorting actions are hidden when there is only one match. Larger single-result
  buttons improve the visible action hierarchy. No API semantics or models changed.
- Twenty scoped tests pass; TypeScript and diff checks pass. Browser verified real
  source-scoped search, input focus, and five-second selected-clip playback.
  At 390 px, document width equals viewport width. Hot reload reset state during
  the check; repeated the real Home/search/selection path afterward.
- [Desktop result](qa/demo-transformation-2026-09-28/search-tradeshow-result.png)
  (before the final larger buttons/single-result sort removal), and
  [mobile question handoff](qa/demo-transformation-2026-09-28/search-question-mobile.png)
  (before shortening the placeholder). Full visitor journey refinement continues.

### September 28 — explain the answer and simplify saving

- Previous turn improved search-to-question. This pass followed a fresh recorded
  question through answer, save, report open and retained playback.
- Answer now says AI answer, preserves the original question, and labels its
  playback column Check the video. Provenance says Based on AI-inspected clips,
  without suggesting the model claim was independently verified.
- Save report replaces Create/Save investigation. Title defaults to the question,
  notes are optional, and review priority/status sit in an expandable section
  whose summary shows their current values. Saved state offers Open report and
  Download report instead of an internal UUID. Report headings use matching
  review-priority/notes wording; API fields and saved records are unchanged.
- Twenty affected component/workspace tests pass; TypeScript/diff checks pass.
  Real fresh inspection took 15.526 s (backend timing). Save returned HTTP 201.
  Report dcbae592-ef1f-43c5-bf71-7577ac317f38, “Demo walkthrough — warehouse box
  handling”, opened and played its retained five-second clip.
- Model still inferred possible placement intent. Saved notes explicitly record
  that unsupported detail and identify this as a recorded UI rehearsal, not a
  live incident. Accuracy remains open; this is workflow validation.
- [Save form](qa/demo-transformation-2026-09-28/save-report-tradeshow.png) precedes
  the final expanded review choices and strengthened note. Review priority was
  set low and status resolved for this development rehearsal.

### September 28 — visitor-facing navigation and consistent report naming

- Previous turn simplified answer/save. This pass changed visible destinations to
  Search video, Live cameras, Events & reports, Alert rules, and What it can do.
  Search follows Home. Route IDs and workspace state behavior are unchanged.
- Page headers and shared live/event/rule tabs use the same labels. Saved
  investigations is now Saved reports, matching the action that creates them.
  Updated the presenter runbook's navigation and recording display name.
- Mobile check initially exposed label overlap from nowrap styling. Corrected
  wrapping and increased label text to 10 px; every label fits its measured width
  at 390 px and the document has no horizontal overflow. Two-line tab labels were
  visually inspected. No claim that seven mobile destinations are an ideal final
  information architecture; further simplification remains possible.
- Scoped shell/operations/insights/rules tests cover navigation, current-page state
  and saved-report behavior. Initial failures were stale labels and an ambiguous
  test selector; corrected to the primary navigation scope, then reran affected
  suites. TypeScript and diff checks included in the final verification.
- Browser navigated Events & reports and What it can do using the renamed controls;
  routes remained events/capabilities. [Mobile navigation](qa/demo-transformation-2026-09-28/navigation-visitor-mobile.png).
  No inference or runtime configuration changes.

### September 28 — explain capabilities as visitor tasks

- Replaced feature-oriented capability copy with six concrete tasks: Find a
  moment, Ask about a clip, Watch camera activity, Compare and share, Review
  activity over time, and Flag activity for review. Each includes a business
  example and a concrete question or action. Industry examples describe possible
  applications, not newly implemented or validated industry scenarios.
- Search, clip questions and comparison now start with the available box-handling
  search instead of vague queries or an offline live view. Browser verification
  of Ask about a clip returned one ten-second warehouse result grouping two
  adjacent matches. No fresh model call was needed for this navigation check.
- Moved technical service details into How it runs locally. Preserved existing
  service, admission and footage checks; unavailable history and unverified live
  camera readiness remain visible.
- Changed CapabilitiesWorkspace.tsx, its scoped tests and vision-intelligence.css.
  Four tests passed, app TypeScript passed, and git diff --check passed. Browser
  verified launch and disclosure behavior. At 390 px document width is 390 px,
  with no horizontal overflow. A first navigation selector timed out; direct
  route verification succeeded. No runtime or model budget changes.
- Evidence: [desktop task page](qa/demo-transformation-2026-09-28/capabilities-business-tasks.png)
  and [mobile task page](qa/demo-transformation-2026-09-28/capabilities-business-tasks-mobile.png).
  Desktop screenshot uses Presentation Mode. Existing recordings remain enough
  for ongoing design work; live scenario qualification still needs working feeds.

### September 28 — disconnected live introduction and browser handover

- Live cameras now explains when no live feeds are connected, what enabling
  analysis adds, and offers Open available recording. Confirmed the action opens
  Warehouse — Box Handling; its video reached readyState 4 with duration 9.9 s.
- Removed the unsupported reassurance that no operator action is waiting when
  there are no verified alerts. Updated references to Search video and Events &
  reports. Twelve OperationsWorkspace tests and TypeScript passed; Jest emitted
  existing jsdom media pause warnings. Corrected the CTA's CSS class afterward.
- User explicitly requested the Codex browser integration. Switched to cua_repl
  and opened the running app in the visible Codex in-app browser. Use this for
  subsequent UI interaction and visual checks; the previous standalone
  Playwright fallback is superseded. Existing command-line component tests remain
  useful for code verification.
- Initial in-app browser state confirms the disconnected-camera introduction and
  recording action. Full live qualification and the overall demo goal remain open.

### September 28 — saved-report language verified in Codex browser

- Integrated browser showed leftover investigation/briefing/citation terminology
  in Events & reports. Changed visible labels to reports and video references;
  explained that reports contain answers, notes and video references saved on
  this device. For references without retained media, the list now explicitly
  says video depends on source availability. Backend record fields are unchanged.
- Six ActivityInsightsWorkspace tests, app TypeScript and diff checks passed.
  Verified hot-reloaded text and layout through cua_repl in the Codex browser.
  [Screenshot](qa/demo-transformation-2026-09-28/reports-codex-browser.png).
- Attempted recording navigation in the integrated browser did not establish a
  stable focused viewer before the page changed to Events & reports. Did not
  attribute that transition to an app defect without evidence or repeat navigation
  against the current view. Integrated-browser recording flow remains to verify.

### September 28 — integrated-browser recorded journey

- Verified Home's box-handling shortcut scopes search to Warehouse — Box Handling,
  returns a five-second match, and opens the question panel. Opened the clip
  viewer and observed playback reach 0:05 / 0:05 with the actual warehouse frame.
- Pointer clicks in the integrated browser did not consistently activate controls;
  keyboard Enter did. AX described a pressed-state button as a checkbox while
  the DOM correctly exposed a button. Used current DOM evidence to select it.
  These observations do not establish an application navigation defect.
- Removed internal filenames from preview accessible names and fallback images.
  Simplified viewer instructions around watching the moment and object-search
  availability, keeping limitations visible without detector/index jargon.
- Eighteen InvestigateWorkspace tests passed after the final copy changes;
  TypeScript passed after accessible-label changes; diff check passed.
  [Real clip viewer](qa/demo-transformation-2026-09-28/clip-viewer-codex.png).
  No fresh inference or runtime changes. Burned-in synthetic timestamps remain
  visible and unresolved; this pass does not qualify live streams or AI accuracy.

### September 28 — connect watching directly to asking

- Added Ask about this clip inside the footage viewer. It closes the viewer and
  selects the clip in the existing question panel, preserving other selected
  clips, avoiding duplicate selection and retaining the six-clip limit. It does
  not start inference automatically. Shared selection logic with result cards.
- Extended the existing analysis/save workflow test to enter via the viewer.
  All 18 InvestigateWorkspace tests and app TypeScript passed. Integrated browser
  verified the real warehouse viewer opens the panel with one selected clip.
- [Handoff screenshot](qa/demo-transformation-2026-09-28/viewer-question-handoff.png).
  Browser verification found focus restores to the preview trigger rather than
  the new question input. Follow up on intentional focus transfer; selection
  and visible panel are verified, keyboard handoff is not fully polished.

### September 28 — complete the viewer's keyboard handoff

- Resolved the focus issue discovered in the preceding browser check. Parent
  workspace now deliberately focuses the question input after the viewer cleanup
  when Ask about this clip is chosen. Ordinary modal dismissal retains existing
  opener restoration. Uses an explicit input ref and effect, without timers or
  changes to the shared dialog hook.
- Codex browser verified focus on the question field for both a newly selected
  clip and an already selected clip, and focus back on the opener after ordinary
  Close evidence. No duplicate selection or automatic inference occurred.
- Added the focus assertion to the viewer-to-analysis workflow test. Twenty
  affected tests, app TypeScript and diff check passed.
  [Focused question panel](qa/demo-transformation-2026-09-28/question-focus-handoff.png).

### September 28 — fresh answer and pacing check in Codex browser

- Asked a new visible-action/final-frame question about the real five-second
  warehouse clip. Answer correctly described approaching the steps while holding
  the box, without claiming placement. One successful bounded question does not
  resolve the earlier general-description failures.
- Cosmos logged 17.57 s processing. Browser inspection was still pending at
  17.635 s and complete by 27.136 s; exact UI completion was not measured.
- Core before/after: 31 roles, no failures, 49.57/49.67 GiB available, guard active
  and same boot ID. No runtime configuration changes or parallel inference.
- [Full receipt](qa/demo-transformation-2026-09-28/fresh-answer-codex.md) records
  exact question, answer, timing limitations and screenshot. Updated presenter
  action wording to match the current UI.

### September 28 — expose measured analysis time and locate the delay

- The backend already returns inspection/synthesis/total timings, but UI types
  and rendering omitted them. Added optional timings and an expandable Local
  analysis duration. It explicitly excludes upload, queue and browser delivery;
  missing, negative or nonfinite totals render no timing claim.
- Six panel tests and app TypeScript passed; diff check passed. Actual fresh
  repeated question in Codex browser showed 17.2 s local analysis, 17.2 s footage
  inspection and 0.0 s rounded answer preparation. Completed answer observed by
  17.735 s after submit. Same visible-action answer as the preceding run.
- Source trace: agent awaits the VLM response; RT-VLM nonstreaming handler waits
  for request completion, while its streaming poll constant is 0.001 s. No
  demonstrated multi-second polling overhead was found. This run points to
  inspection itself, not redundant answer synthesis, as the dominant delay.
- [Timing disclosure screenshot](qa/demo-transformation-2026-09-28/local-analysis-timing.png).
  Measurement visibility is improved; this is not a latency optimization or a
  broad performance qualification. No runtime/model budget changes.

### September 28 — explain rule intent and source readiness

- Inspected the current Alert rules page and builder in Codex browser. Two
  existing enabled rules were visible despite live sources being disconnected.
  Existing records were not changed. The prior engine/slot-led introduction did
  not explain the visitor's task clearly.
- Reframed the page as What should trigger a review?, with a visible-condition
  example and the Events & reports destination. Added a definition of enabled
  configuration versus actual running monitoring. Rule source options now show
  connected/disconnected/unverified for live sources; disconnected selection
  explicitly explains that preparing a rule does not start monitoring.
- Five scoped rule tests and app TypeScript passed. Browser verified real offline
  source labels, warning, page explanation and ordinary builder dismissal.
  No rule was saved, enabled, paused or deleted; no live inference was started.
- [Builder screenshot](qa/demo-transformation-2026-09-28/rule-source-readiness.png).
  Populated incident generation and live timing still require a working feed.

### September 28 — source setup exposed another runtime interruption

- Source audit found raw proxy HTML in Add RTSP camera. Runtime inspection
  confirmed a reserve-guard trip at 47.659 GiB (48 GiB floor) at 16:01:58 EDT;
  five core AI/service roles stopped, with no host reboot. Actual demo reliability
  remains unresolved despite successful earlier questions.
- Started documented idle reclaim and staged core recovery, preserving guard,
  model budgets and paused live ingestion. [Recovery receipt](qa/demo-transformation-2026-09-28/memory-guard-1601.md)
  and telemetry record the interruption. Recovery completed at 16:12 EDT: 31
  roles passed manager checks with 52.76 GiB available; camera profiles loaded
  again in Codex browser. Detector profiles stayed disabled. Root cause remains open.
- Fixed the profile helper's raw-HTML error handling with a red/green regression
  test, retaining structured service messages. Four relevant package tests and
  app TypeScript passed; verified the actionable fallback in the actual failed
  state through Codex browser. Aligned the recording display alias in Sources.
- Did not register or modify cameras. No conclusion yet about the precise cause
  of the brief memory dip. Avoid tests/typechecks alongside further startup.

### September 28 — describe source setup by its outcome

- Added shared display wording for the three installed analysis profile IDs:
  Find activity and ask questions, Track warehouse activity, Track road activity.
  Camera and upload selectors use the same task names and short explanations;
  model labels, object classes, availability, profile IDs and submission remain
  unchanged. Unknown profile IDs retain their backend name/description.
- Camera setup now asks What should this camera help you do? and explains the
  installed-option recommendation without pipeline jargon. Codex browser verified
  semantic selection and disabled detector profiles; no camera was submitted.
- Four focused profile/camera tests and app TypeScript passed after correcting a
  stale test label. Post-check core status: 31 roles, no failures, 51.09 GiB
  available. This is a point check, not stability qualification.
- [Camera task choices](qa/demo-transformation-2026-09-28/camera-task-choices.png).
  Upload rendering shares the helper but was not separately exercised this pass.

### September 28 — clarify recording preparation

- Used Codex browser file chooser with the existing ten-second sample to inspect
  upload setup. Selection opens the configuration dialog before upload; cancelled
  without submitting a duplicate or starting ingestion.
- Title now Make a video searchable, with explicit upload → processing → search
  wording. Removed the unsupported claim that semantic indexing is always
  available. Profile loading has a visible status, and the fixed enabled embedding
  option reads Video search / Included in processing instead of a disabled
  embedding: Yes switch. Other configurable fields retain their controls.
- Verified current shared task names, selected search option, disabled detector
  choices and upload readiness in the rendered dialog. App TypeScript and diff
  check passed. No new end-to-end ingestion claimed for this form-only pass.
- [Upload setup](qa/demo-transformation-2026-09-28/upload-searchable-setup.png).
  The narrow, scroll-heavy dialog remains a visual refinement opportunity.

### September 28 — upload layout and integrated browser workflow

- Continued visual checks through the Codex in-app browser. Use this integration
  for subsequent walkthroughs and screenshots instead of standalone Playwright.
- Widened AgentUploadDialog, separated its scrollable contents from its heading
  and footer, and kept Cancel / Upload visible while choices scroll.
- At 390 × 844, found the mobile navigation overlaid the dialog actions. Raised
  the viewport dialog above navigation; verified both actions remain visible at
  the top and bottom of the form. Restored the desktop viewport afterwards.
- App TypeScript passed for the layout changes; the subsequent overlay adjustment
  changes only a CSS utility. Verified the rendered result via hot reload.
  Selected the existing sample for form inspection and cancelled without upload.
- Evidence: [desktop](qa/demo-transformation-2026-09-28/upload-layout-desktop.png)
  and [mobile](qa/demo-transformation-2026-09-28/upload-layout-mobile.png).
  This validates upload setup layout, not ingestion or runtime stability.

### September 28 — camera setup mobile action visibility

- Reproduced a second navigation overlap in Sources → Add RTSP camera at
  390 × 844: the bottom navigation covered Cancel / Connect camera.
- Raised AddRtspDialog's viewport overlay to the same layer as the upload modal.
  Verified actions remain visible while scrolling to authentication settings.
- Codex in-app browser checks: intended System page and meaningful content,
  no framework overlay, no captured warning/error console entries, open/scroll/
  cancel interaction passed. Also inspected 1440 × 900, then reset viewport.
- CSS-only utility change; no inference, ingestion, camera submission or runtime
  configuration changes. Live connection and sustained analysis remain unqualified.
- Evidence: [mobile](qa/demo-transformation-2026-09-28/camera-layout-mobile.png),
  [desktop](qa/demo-transformation-2026-09-28/camera-layout-desktop.png).

### September 28 — refresh the visitor walkthrough

- Rechecked Home → Find a person carrying a box → one five-second matching
  clip → Play clip → Ask about this clip in the Codex browser. Recording
  playback settled successfully and the handoff focused the question field.
- Corrected outdated presenter instructions (People moving / Use as evidence)
  to the current controls. Added a short tradeshow talk track, exact previously
  checked visual question, local-processing timing evidence, and clear separation
  between the recorded chapter and unqualified live/industry scenarios.
- This pass did not submit another model request or create a report. It verifies
  navigation and evidence preparation, not the full answer/save/export lifecycle.
- [Presenter runbook](demo-presenter-runbook.md) remains a working draft; complete
  rehearsal, broader accuracy and runtime stability remain open.

### September 28 — fresh answer, retained report and question context

- Completed a fresh bounded visual question, cited playback, reviewed report
  save and retained five-second playback through the Codex integrated browser.
  Local analysis reported 15.5 s; answer observed by 20.533 s after submit.
- Fixed missing original-question context in HTML reports and exports. Saved
  reports now show Question asked before the answer, with HTML escaping.
  Five API tests and app TypeScript passed; rendered report verified.
- Export endpoint returned 200, but browser download handle timed out. Delivery
  remains unverified; no full lifecycle completion claim.
- [Rehearsal receipt](qa/demo-transformation-2026-09-28/report-rehearsal.md)
  records report ID, timing bounds, playback proof and runtime headroom.

### September 28 — show the finished output from capabilities

- What it can do → Compare and share previously only led back to search.
  Added View saved reports so a visitor can inspect the finished output without
  repeating selection and inference. The existing compare action remains.
- Codex browser verified the shortcut opens Events & reports with the current
  rehearsal report listed. Desktop and 390 × 844 layouts show both actions;
  no captured console warnings/errors. Viewport reset after verification.
- Four focused capabilities tests and app TypeScript passed. Evidence:
  [desktop](qa/demo-transformation-2026-09-28/capabilities-report-shortcut.png),
  [mobile](qa/demo-transformation-2026-09-28/capabilities-report-shortcut-mobile.png).
- No fresh AI request, source mutation or runtime budget change. This improves
  demonstration navigation; it does not qualify multi-clip or live workloads.

### September 28 — second-moment retrieval and visual question

- Expanded checking beyond the repeatedly used first clip. The later interval
  is retrievable with person climbing a ladder; person climbing the green steps
  returned no matches twice. Wording sensitivity remains an open retrieval issue.
- Fresh question correctly described ascent and final position near shelf E.
  Local analysis 12.4 s; browser completion observed by 17.033 s. No extra report.
- Fixed zero-result copy that instructed the visitor to play a nonexistent clip.
  Actual failed query now gives shorter-action/filter guidance and avoids an
  absence claim. Eighteen workspace tests and TypeScript passed.
- [Second-moment receipt](qa/demo-transformation-2026-09-28/later-clip-check.md)
  records exact queries, answer, scope and screenshots. General accuracy and
  retrieval reliability remain unqualified.

### September 28 — resolve the scoped-search cutoff miss

- Traced the actual green-steps query through the agent: later clip ranked first
  at 0.12; scoped fallback required 0.15 while all-source search allowed 0.12.
- Reused the all-source cutoff for scoped fallback, preserving the stricter first
  attempt. A request-boundary regression failed before and passed after; all 19
  workspace tests and app TypeScript passed.
- Codex browser recheck of the original query now returns the correct interval.
  [Diagnosis and limits](qa/demo-transformation-2026-09-28/later-clip-check.md).
  This exact miss is resolved; broad retrieval quality remains unqualified.

### September 28 — collect evidence across searches

- Reproduced loss of the first selected clip when searching for a second moment.
  This broke the natural before/after comparison workflow.
- Selected clips now retain snapshots of their result, original query label and
  match type independently of current results. Text and visual searches retain
  the selection; Remove and Clear explicitly discard it. Existing six-clip limit
  and analysis revision invalidation remain.
- Added a workspace regression covering two different searches, stable labels,
  and both exact source intervals in the analysis request. All 20 workspace tests
  and app TypeScript passed.
- Codex browser: selected carrying-box 0:00, searched green-steps 0:05, added the
  second result, and reopened the first from the selected-evidence tray. Original
  title and offset remained correct. Selection is session state, not persisted
  across a full page reload. Fresh multi-clip inference remains to be measured.
- [Collected clips](qa/demo-transformation-2026-09-28/cross-search-evidence.png).

### September 28 — comparison qualification failed; isolate inspection scope

- Tested two separately selected moments with a real comparison question.
  Baseline 33.0 s local analysis produced contradictory per-clip observations:
  each visual call invented information about the other clip.
- Fixed multi-clip prompt scope: each inspection now describes only its supplied
  clip; comparison question belongs to synthesis. Agent-only restart reached
  healthy. Syntax and isolated actual-function prompt harness passed.
- Repeat stopped cross-clip inventions but still hallucinated box placement and
  failed synthesis JSON parsing. 29.5 s reported local analysis. No successful
  comparison claim or saved report; full backend suite not run at tight headroom.
- [Failure receipt](qa/demo-transformation-2026-09-28/comparison-check.md) records
  exact question, timing bounds, scope changes and outstanding work. Core remains
  up with 48.99 GiB available; preserve guard and avoid concurrent heavy work.

### September 28 — enforce the local comparison response format

- Confirmed local server JSON-schema support, then bound a required summary
  schema on the vLLM synthesis call. Retained malformed-output degradation and
  unchanged calls for other providers; no memory or token-budget changes.
- Direct server format probe passed in 2.742 s. Actual synthesis function with
  real local client and fixture observations returned complete in 1.450 s.
  The text changed beside to on, so accuracy is explicitly not a pass.
- Syntax checks passed; backend unit expectations updated but full module not
  run due to tight memory headroom. Retained a repeatable isolated probe and
  [detailed limits](qa/demo-transformation-2026-09-28/comparison-check.md).
- Agent-only restart loads the format fix; full fresh comparison and factual
  grounding remain required work.

### September 28 — isolate and improve comparison synthesis fidelity

- Revised the text synthesis prompt to preserve spatial phrases and action state,
  while comparing per-clip observations without assuming shared identity.
- Actual synthesis function + real local client passed four text fixtures:
  beside/on, outside/inside, stopping motion/holding, and incomplete/completed
  entry. Summaries manually checked; model calls took 1.023–4.132 s.
- Syntax checks passed, backend prompt expectations updated, and agent-only
  restart loads the change. Full backend suite not run at tight headroom.
- [Probe and limits](qa/demo-transformation-2026-09-28/comparison-check.md).
  This improves synthesis in bounded tests; video-inspection placement claims
  and complete two-clip latency remain unresolved.

### September 28 — trace final-frame sampling before further inference

- At 48.64 GiB available, deferred another model run and traced recorded input.
  Running fixed-count sampler omits the last decoded frame: a 5 s / 10 fps
  fixture requesting ten frames selects through 4.5 s, not its last 4.9 s frame.
- Verified with the actual container's selector class and no GPU imports.
  Retained an executable failing final-frame-inclusion probe and documented the
  decoder-boundary requirements for a frame-budget-preserving fix.
- [Sampling evidence](qa/demo-transformation-2026-09-28/comparison-check.md).
  This is a demonstrated input limitation, not a proven explanation of the
  hallucination. No further prompt or runtime changes made in this pass.

### September 28 — integrated browser workflow confirmed

- User explicitly requested Codex/ChatGPT integrated web app tools. All browser
  walkthroughs, interactions, screenshots and visual checks use the Codex in-app
  browser through `cua_repl`; no standalone Playwright browser session.
- Reconnected to the existing Search video tab and verified the current two-clip
  evidence workspace. The displayed prior synthesis failure remains visible;
  this browser verification does not qualify inference or runtime health.
- Code edits and scoped tests continue through repository tools. Progress and
  evidence remain in this documentation.

### September 28 — native decoder endpoint probe

- A CPU-only GStreamer fixture exercised the installed native timestamp filter.
  Replacing the tenth target (4.5 s) with the known final frame (4.9 s) preserved
  the ten-frame budget and included the endpoint. No model inference or runtime
  configuration changes were made.
- This is a diagnostic result, not a production fix: discovering the correct
  final timestamp for variable-rate video and chunk boundaries remains open.

### September 28 — report export expectations and browser delivery check

- Clarified the HTML download format and Jetson-network playback dependency
  beside report actions, added explicit download semantics and wrapping actions.
- Renamed report “Observed facts” to “AI observations” to avoid treating model
  output as established fact. Existing copy tests updated; five API tests and
  app typecheck passed.
- Integrated-browser desktop/mobile rendering and console checks passed.
  Download events still time out despite successful server responses, including
  after the change; delivery is explicitly unverified.
- [Rehearsal evidence and limits](qa/demo-transformation-2026-09-28/report-rehearsal.md).

### September 28 — live overview separates usable demos from offline cameras

- Replaced five empty live preview tiles and repeated warnings with a compact,
  expandable connection list; kept every camera's detail access. Recordings now
  have an explicitly separate entry and source counts distinguish live/replay.
- Corrected disconnected camera detail claims of Q&A/detection readiness.
- Integrated-browser desktop/mobile checks, disconnected detail navigation and
  actual recorded playback passed. Twelve scoped tests and app typecheck passed.
- [Evidence and limitations](qa/demo-transformation-2026-09-28/live-availability.md).
  Five live feeds remain disconnected; no ingestion or memory configuration changed.

### September 28 — final-frame discovery tested without inference

- Reproduced the current sampler's final-frame omission and tested native MP4
  demux against independent decoded timestamps on four cases: CFR, VFR, B-frame
  reordering/nonzero starts, and the warehouse recording.
- All timestamp and bounded-chunk comparisons passed after segment conversion.
  Raw native PTS differs from playback time on the generated cases, ruling out
  a naive endpoint patch tested only on our zero-offset warehouse recording.
- Retained reproducible probe and timings (2.638–5.065 ms native demux;
  170.938–191.481 ms full probe invocation). No production decoder/runtime change.
- [Findings and next decoder seam](qa/demo-transformation-2026-09-28/comparison-check.md).
  Production endpoint coverage and answer correctness remain unresolved.

### September 28 — hardware decoder confirms final-frame target behavior

- Ran nine bounded low-resolution decoder/filter cases across CFR, VFR and
  nonzero starts. Corrected targets retained exactly ten full-file or five
  post-seek frames, including the last frame, without VLM inference.
- Found preroll can consume a target in the component harness. Resetting targets
  on SEGMENT restores the count; production's different appsink/seek sequence
  must be tested before treating that as a production bug or applying the fix.
- Preserved the 48 GiB guard, recorded memory endpoint samples, and verified all
  31 core roles after the probe. No production decoder or runtime changes.
- [Decoder evidence and integration limits](qa/demo-transformation-2026-09-28/comparison-check.md).

### September 28 — reusable endpoint-aware sampling component

- Implemented bounded local-MP4 discovery and temporal target selection in
  `utils/frame_sampling.py`, preserving decoder/playback timestamp coordinates.
- Nine unit tests, nine hardware/filter cases driven by the actual new planner,
  and six native discovery/failure checks passed. The real warehouse first
  five-second interval selects ten targets ending at 4.9 s.
- [Implementation evidence and integration status](qa/demo-transformation-2026-09-28/comparison-check.md).
  The production frame getter is not connected to the module yet; runtime and
  inference behavior remain unchanged. Caller/seek/cache integration is next.

### September 28 — endpoint planner connected to decoder source

- Wired bounded video-only MP4 requests through the frame planner; preserved
  native/Python selection agreement, reset planned targets on new file segments,
  and converted returned timestamps back to playback time for citations.
- Added explicit legacy fallback logging and a rollback switch. Unsupported
  paths are not claimed to have endpoint coverage.
- Fifteen scoped tests and nine hardware/filter cases using actual repository
  selector targets passed; syntax checks passed.
- [Integration evidence and deployment gate](qa/demo-transformation-2026-09-28/comparison-check.md).
  Running service has not loaded these files yet. Source mounts, full decoder
  validation and a fresh AI-answer comparison remain next.

### September 28 — guarded endpoint deployment underway

- Added and validated persistent read-only Cosmos mounts for the decoder and
  sampling helper; verified both container hashes after recreation.
- Cosmos-only stop did not free the 15 GiB restart headroom. Used the documented
  all-model idle reclaim, preserving the guard, then started the core manager.
- Nemotron and Embed settled ready; Cosmos is running and profiling its video
  encoder after loading model weights. The existing manager is still live;
  do not start another instance. Latest sampled reserve exceeds 62 GiB.
- [Deployment receipt](qa/demo-transformation-2026-09-28/endpoint-deployment.md).
  API recovery and fresh endpoint/answer verification remain pending.

### September 28 — endpoint sampling deployed and exercised through the app

- Guarded recovery completed: all 31 core roles/API checks passed, guard remained
  active. Verified read-only mounts and source hashes in the recreated Cosmos.
- Fresh integrated-browser single-clip question logged 20 decoded / 20 planned
  frames ending at the expected 4.9 s. Frame/model budget configuration unchanged.
- Answer's “still holding” conclusion matched the cited final frame. Local
  analysis 14.8 s; completion observed by 24.713 s. Afterward 50.53 GiB available.
- [Deployment and verification receipt](qa/demo-transformation-2026-09-28/endpoint-deployment.md).
  This proves endpoint delivery for the rehearsed path, not general accuracy or
  the unresolved multi-clip/live demo gates.

### September 28 — multi-clip retest isolates remaining question-focus issue

- Retested the actual two-clip comparison after deployment. Both final frames
  were decoded, but E2 still claimed completed placement; local analysis 32.4 s.
  Synthesis formatting now succeeded. Accuracy and pacing remain failed gates.
- The same second clip with its specific position question produced a matching
  final-platform/holding description in 11.1 s local analysis. Multi-clip visual
  prompts currently omit that question and request a general description.
- [Contrasting results and limitations](qa/demo-transformation-2026-09-28/comparison-check.md).
  This guides the next prompt-scope change; it does not qualify comparison or
  prove general accuracy. No report or additional runtime change was made.

### September 28 — multi-clip question focus restored, accuracy still fails

- Multi-clip inspections now retain the user's question with explicit per-clip
  scope; single-clip behavior and runtime/model budgets unchanged.
- Actual-function scope probe and syntax passed; updated backend expectations.
  Agent-only restart loaded the change; full heavy backend suite not run.
- Same browser comparison took 25.0 s local analysis versus 32.4 s previously.
  Summary looks correct, but E2 still claims placement, contradicting it.
- [Retest evidence](qa/demo-transformation-2026-09-28/comparison-check.md).
  Per-clip scope held in this sample, but accuracy and general pacing are still
  unqualified. No report saved; next investigate explicit visual-task decomposition.

### September 28 — measured question rewriting before adopting it

- Confirmed Codex integrated browser remains the UI testing surface. The prior
  browser-switch turn confirmed tooling but made no demo implementation progress.
- Tested five local Nemotron question decompositions with recorded outputs and
  timings. Calls took 1.2–3.1 s; position/counting/clip-specific scope survived,
  but the identity request became an unanswerable per-clip identity question.
- Kept the planner out of the app: formatting success is insufficient, and no
  visual accuracy benefit has been measured. Core runtime passed 31 checks;
  observed available memory stayed above 49.7 GiB with safeguards unchanged.
- [Diagnostic evidence and next experiment](qa/demo-transformation-2026-09-28/comparison-check.md).
  Comparison accuracy and general pacing remain unqualified.

### September 28 — make the first evidence question easier to start

- Rehearsed Home → search → clip viewer → selected-evidence question in Codex's
  integrated browser; the existing navigation and focus behavior passed.
- Added two short, editable question starters, with no automatic inference.
  Mobile inspection prompted shorter wording and a cleaner two-button row.
- Typecheck and 20 existing investigation tests passed; desktop/mobile
  interaction and screenshot checks passed. Browser warning/error log empty.
- [Change and QA receipt](qa/demo-transformation-2026-09-28/question-starters.md).
  Fresh-answer rehearsal deferred at 48.78 GiB available; runtime guard unchanged.
  This improves visitor guidance, not the unresolved model accuracy gate.

### September 28 — correct clip-question readiness and inspect narrow headroom

- Previous turn made UI progress: editable question starters and desktop/mobile
  checks. Continued by investigating the runtime margin before more inference.
- Host telemetry does not support blaming UI-server RSS for the available-memory
  drop. Closed completed verification tabs; 31 core checks passed with 48.91 GiB
  available. Root cause and sustained capacity remain unproven; guard unchanged.
- Fixed “Ask about a clip” readiness to follow recorded evidence admission and
  fresh retained/indexed footage. Four capability tests passed; integrated
  browser verified the new status and its completed search action.
- [Evidence and limits](qa/demo-transformation-2026-09-28/readiness-and-headroom.md).
  Requested live Spark/RTSP scene details; no new visual workload started.

### September 28 — distinguish the actual selected video interval

- Reproduced a five-second scoped result and ten-second grouped result with
  identical titles/source/start labels. The selected tray previously omitted
  duration, making preserved selections ambiguous after searching again.
- Added each selected snapshot's clip length, separated its source/time lines,
  and increased tray text sizes. Request intervals and selection identity unchanged.
- Actual cross-search selection checked in Codex browser on desktop and mobile;
  26 existing tests passed and browser warning/error log was empty.
- [Receipt and screenshots](qa/demo-transformation-2026-09-28/evidence-duration-clarity.md).
  No extra inference; model accuracy and runtime headroom still need work.

### September 28 — reopen the saved finding through the actual report list

- Previous turn improved evidence interval clarity. Continued the end-to-end
  review through Events & reports and its real Open report link.
- Saved briefing opened in a new integrated-browser tab; its retained five-second
  video played to the end without a media error. Question and review notes present.
- Export HTTP response passed attachment/content/link checks. Browser download
  event still timed out through both documented interaction methods, so delivery
  remains unverified. No inference or new report; completed tab closed.
- [Rehearsal update](qa/demo-transformation-2026-09-28/report-rehearsal.md).

### September 28 — guarded recovery to resume actual AI rehearsal

- Inspected empty Insights; its evidence prerequisites and limits are clear.
- Actual Cosmos logs confirm 3 GiB KV supports 21,840 tokens. A reduction to
  2 GiB would not fit the existing 16K context; left budgets intact.
- Stopped only Agent/LVS/models, verified them idle, reclaimed once and started
  the documented core manager with the 48 GiB guard continuously active.
- [Recovery receipt](qa/demo-transformation-2026-09-28/rehearsal-runtime-recovery.md).
  Startup is still running; initial headroom 101.636 GiB. Continue the existing
  manager before attempting inference or claiming service recovery.

### September 28 — recovery complete; ordinary question still exposes grounding gap

- Resumed the same live manager; it exited successfully with all 31 checks and
  51.87 GiB available. Guard active, budgets unchanged. UI typecheck passed.
- Rehearsed the actual “How does it end?” starter: 14.7 s local analysis, answer
  observed by 20.120 s. Literal final-frame follow-up: 13.4 s, observed by 17.290 s.
- Both decoded the final frame but inferred a future placement. Playback review
  does not establish that intent. No report saved; neither answer counts as a pass.
- [Recovery and answer evidence](qa/demo-transformation-2026-09-28/rehearsal-runtime-recovery.md).
  Investigate prompt focus next; changing starter wording alone was insufficient.

### September 28 — shorter single-clip prompts improve focus and pacing

- Removed competing general-description/search instructions from single-clip
  visual questions; preserved explicit question/query fallback and exact footage.
- Actual-function probe passed five cases and syntax passed; Agent-only restart
  deployed the change. No model/frame budget change or extra model call.
- Same app questions improved from 13.4/14.7 s to 9.3/8.4 s local analysis and
  stopped predicting placement. Gaze-direction details remain unverified.
- “What moves in this clip?” produced a matching movement/holding answer in
  11.2 s. [Measured results](qa/demo-transformation-2026-09-28/focused-single-clip-prompt.md).
  These samples improve the recorded demo, not general or multi-clip qualification.

### September 28 — first consistent answer to the original two-clip comparison

- Extended the concise question-focused suffix to multi-clip inspection while
  preserving clip isolation, labels and the active question. No added model call.
- Five-case scope probe/syntax passed; Agent-only restart and core health passed.
- Same two clips/question now produced consistent near-steps versus top-platform
  observations and summary, with no invented placement. Replayed E2 to verify.
- Local analysis 24.9 s; completion observed by 28.796 s. This is one bounded
  accuracy improvement, not a proven latency improvement or repeatability claim.
- [Comparison evidence](qa/demo-transformation-2026-09-28/comparison-check.md).
  All 31 post-checks passed, 50.12 GiB available; broader validation remains open.

### September 28 — reversed-order comparison exposes remaining reliability failure

- Reversed the same two clips without changing model/prompt settings. Labels
  followed the footage, but the climbing observation and summary again claimed
  completed placement. Local analysis 23.0 s; observed complete by 29.575 s.
- Prior passing comparison is therefore not sufficient qualification. No new
  report saved; all 31 core checks passed with 50.13 GiB available afterward.
- Changed “Observed” to “AI observations” in the answer panel. Six component
  tests passed; hot reload reset the result before populated visual verification.
- [Failure and verification limits](qa/demo-transformation-2026-09-28/comparison-check.md).

### September 28 — integrated browser upload and second recorded scenario

- Confirmed Codex's integrated browser is the UI interaction surface. The
  Sources upload control opens a file chooser; registering the chooser listener
  before clicking resolved the apparent no-op. No app fix was necessary.
- Inspected the bundled conveyor recording at 1, 4, 8, 35 and 70 seconds. A box
  travels around the bend and exits view; later frames show an empty belt.
  This does not establish a jam, defect or machine failure.
- Prepared a 10-second, 1,070,470-byte stream-copy excerpt and uploaded it
  through the actual Agent-backed Sources flow using the integrated browser.
  The UI showed **Upload Complete (1/1)** and the new recorded source;
  source counts changed to five live and two recorded. Search-only processing
  was available; offline detector profiles were correctly disabled.
- Pre-upload core check: all 31 service roles passed, 49.98 GiB available.
  No runtime budgets or memory guard settings changed. Search retrieval,
  playback and fresh visual-question quality for this clip remain unverified.
- [Upload evidence](qa/demo-transformation-2026-09-28/conveyor-upload-complete.png).

### September 28 — conveyor answers and scenario-aware Home

- Search for “box moving on a conveyor belt” scoped to the uploaded recording
  returned one ten-second result (two adjacent indexed intervals grouped).
  Browser playback advanced with readyState 4 and no media error.
- “What moves in this clip?” returned “A box moves along a conveyor belt.”
  Fresh local inspection: 7.5 s; observed complete by 11.641 s. This bounded
  answer agrees with the inspected footage.
- “How does this clip end?” took 8.2 s and said the box moved off the belt and
  out of view. Leaving view is supported; leaving the belt is not established.
  This is an unresolved grounding limitation, not a fully passing answer.
- Home now offers an explicit recording choice. Preview, business context and
  suggested search change together. Known warehouse/conveyor recordings get
  matching prompts; unknown footage gets a neutral search action rather than
  an invented person/box scenario. Source identities remain unchanged.
- Two Home entry tests and app typecheck passed. Desktop and 390×844 layouts
  inspected in Codex's integrated browser; no relevant console warnings/errors.
  Home CTA passed the correct source/query, but backend completion was blocked
  by the guard event below. Recheck that handoff after recovery.
- Runtime guard tripped at 18:34:20 EDT, 47.689 GiB available, floor 48 GiB;
  boot ID unchanged. Agent, LVS and all three models exited. This occurred
  during UI development/verification; exact allocation cause is not established.
  Preserved receipt: `qa/demo-transformation-2026-09-28/conveyor-pass-guard-trip.json`.
- Verified those five workloads stopped and guard active; ran one documented
  idle reclaim, then started the existing core manager. **Recovery remains in
  progress in shell session 30856**. Resume it; do not launch a second manager.
  No model budget or reserve change. Demo readiness is not yet restored.
- Screenshots: `conveyor-movement-answer.png`, `conveyor-ending-answer.png`,
  `home-conveyor-choice.png`, `home-recordings-mobile.png` in the dated QA folder.

### September 28 — core recovered; Home-to-conveyor retrieval verified

- Resumed existing manager session 30856; it completed exit 0 at 18:44:55 EDT.
  All 31 core/API checks passed with 50.96 GiB available. No second manager,
  model-budget change or guard bypass.
- Integrated-browser Home → Conveyor → suggested search returned the correct
  scoped ten-second result. First observed complete by 5.119 s. Post-search
  all 31 checks passed, 50.97 GiB available, guard active.
- Added a current qualification table and second business-example talk track
  to the presenter runbook. Preserved unsupported ending claims as failures.
- [Detailed receipt](qa/demo-transformation-2026-09-28/conveyor-rehearsal.md).
  Sustained memory, reliable temporal grounding, live scenario and download
  delivery remain open. Agent's generic Dask concurrency setting is a candidate
  for an overhead measurement, not yet a verified cause or applied fix.

### September 28 — reduced measured Agent idle overhead

- Measured eleven default Dask workers in Agent. Set the Thor profile to two
  concurrent background jobs plus cleanup, preserving all model budgets and
  the active 48 GiB guard. Agent-only restart loaded three workers.
- Proportional process memory fell 617.75 MiB; container memory fell 653.04 MiB
  in before/after snapshots. All 31 post-restart core checks passed.
- Integrated-browser search and a fresh conveyor movement question passed.
  Correct answer in 7.8 s local analysis; observed complete by 11.876 s.
  This reduces background concurrency, not visual model capability. No
  multi-user throughput or sustained-memory qualification claim.
- [Configuration, measurement and verification](qa/demo-transformation-2026-09-28/agent-worker-budget.md).

### September 28 — verified report clipboard handoff

- Saved **Conveyor demo — box movement** with reviewed simulation provenance,
  then played its retained ten-second clip through the report.
- Added Copy briefing: answer, notes and absolute evidence links in plain text.
  Verified actual integrated-browser clipboard contents. Denied/unavailable
  clipboard access exposes selected text with explicit instructions.
- Five API tests and app typecheck passed; all 31 core/API checks passed with
  51.31 GiB available. Desktop confirmation verified; mobile DOM fits but its
  anomalous screenshot does not qualify as visual proof.
- HTML download still times out through the integrated browser; Open report
  click did not open a tab in this session, while its displayed URL worked.
  [Complete handoff receipt](qa/demo-transformation-2026-09-28/conveyor-report-handoff.md).

### September 28 — clarify review workflow and cross-search selections

- Rechecked What it can do → review action → search and the Live cameras page
  in the integrated browser. Live correctly reports no connected cameras,
  zero analyzed sources, and two separate recordings. No live workload started.
- Reframed the capability as **Review and share**, keeping multi-clip comparison
  available while explaining review, playable references and copied briefings.
  Its CTA clears the previous source filter and retrieves warehouse footage.
- Found a visitor-facing ambiguity: a prior conveyor selection remained above
  a new warehouse search, by design for cross-search comparison. Changed the
  panel heading to **Ask about selected clips** and explicitly label clips
  outside the current results **Selected earlier**. A context sentence explains
  which footage questions use. Selections and source identity remain intact.
- Reproduced the reverse journey (select warehouse, search conveyor) and verified
  the earlier-selection label in the browser. Regression test also checks the
  label disappears when the selected clip returns to the result set.
- Four capability tests, 27 search/panel tests and app typecheck passed.
  [Rendered selection context](qa/demo-transformation-2026-09-28/earlier-selection-context.png).

### September 28 — restored and verified local RTSP replay transport

- Found stopped NvStreamer and old proxy addresses in existing RTSP records;
  VIOS reports CameraNotFoundError for their active stream state.
- Started only the existing local replay publisher. It advertises current Thor
  addresses and successfully delivered a decoded conveyor frame over RTSP/TCP.
  Available memory stayed about 50.1 GiB; the 48 GiB guard remains active.
- No new camera, detector or analysis job started. The current Agent onboarding
  endpoint automatically starts analysis, so preview-only registration needs
  explicit support before the next staged browser-playback test.
- [Transport receipt and next stage](qa/demo-transformation-2026-09-28/rtsp-replay-transport.md).

### September 28 — preview-only camera connection verified in Codex browser

- Added explicit preview-only onboarding, defaulting AI analysis off in the camera dialog. Legacy API callers keep their existing default.
- Registered the conveyor recorded-simulation RTSP replay through the UI and verified real 1920-pixel playback without errors.
- Agent confirmed embedding, detection and indexing paused before and after restart. All 31 core roles passed; 49.83 GiB available; guard active.
- Three dialog tests, app typecheck, contract probe and Agent lint passed. Whole-agent formatting/typecheck have documented existing limitations. Inventory refresh timing remains a follow-up.
- [Implementation, evidence and validation scope](qa/demo-transformation-2026-09-28/preview-only-rtsp.md).

### September 28 — camera onboarding feedback and replay labeling

- Fixed the silent gap between successful camera registration and eventual source-catalog visibility. The dialog passes the registered identity to Sources; Sources clears excluding filters, reports the paused/requested analysis state, and refreshes every two seconds for at most ten attempts. It stops when the camera appears or gives a specific Refresh instruction without encouraging duplicate registration.
- Player subtitle now says “RTSP video preview”; the source title explicitly identifies the conveyor as a recorded simulation replay.
- Twelve affected package tests and app typecheck pass. Tests cover delayed catalog arrival, cancellation after arrival, and the bounded timeout. A second real source was not created merely to test catalog delay.
- Codex integrated browser at http://10.88.9.12:7777 verified Sources → conveyor Play: correct label, actual moving box, readyState 4, paused false, no video error. Desktop 1265×712; meaningful page content, no framework overlay, recent error/warning log empty. Mobile was not rechecked for this pass.
- [Rendered player evidence](qa/demo-transformation-2026-09-28/rtsp-preview-label.jpg). Sustained live AI remains unqualified; analysis stays paused.

### September 28 — focused live questions and clearer video view

- Two fresh questions against the RTSP replay completed by 11.7 and 14.9 seconds while continuous analysis remained paused. The second answer contains unverified color detail; this is not a general accuracy qualification.
- Collapsed the technical panel by default on desktop, preserving expand/collapse access. Clarified source status as “RTSP feed · Analysis paused.”
- Found a substantive grounding gap: live answers inspect a 25-second past window but omit that interval and inspected-clip playback. This is the next evidence-chain fix.
- Twelve focused-workspace tests and app typecheck pass; Codex browser confirmed interaction/playback, no recent console errors. All 31 core roles pass after questions, 49.64 GiB available.
- [Question results, UI evidence and exact remaining gap](qa/demo-transformation-2026-09-28/live-preview-questions.md).

### September 28 — live answers now expose replayable evidence

- Closed the live evidence gap: the Agent returns its exact inspected timestamps; the answer displays the dated interval and offers Play inspected clip for RTSP sources.
- Fresh browser answer completed by 12.4 seconds. Its exact 25-second clip played through the new action, readyState 4, no error. This verifies traceability, not general model accuracy.
- 15 affected UI/API tests and app typecheck pass. Agent lint and actual-source contract probe pass; Python pytest/mypy environment limitations are documented. Runtime remains at 31 healthy core roles, 49.64 GiB available, analysis paused.
- [Implementation and browser evidence](qa/demo-transformation-2026-09-28/live-evidence-window.md).

### September 28 — clear Home entrance to the connected stream; mobile evidence checked

- Added a Home camera invitation only when a source is explicitly online. It names the feed, distinguishes continuous paused analysis from individual questions, and opens that exact source in focused Live view. Offline/unknown cameras are excluded from this entry.
- Fixed the inspected-clip player's fixed 420px minimum at mobile widths; video now uses its 16:9 area without excessive blank space.
- Codex integrated browser verified Home → Open camera stream selects the conveyor simulation replay and plays it (readyState 4, currentTime 13.1s, no error). Home and inspected-evidence layouts checked at 390×844; no horizontal overflow, readable headings/actions. Returned browser to desktop and checked Home there, with no recent console warnings/errors or framework overlay.
- Three Home entry tests and app typecheck pass. The test covers absent/unknown cameras and exact connected-source routing.
- [Desktop Home](qa/demo-transformation-2026-09-28/home-camera-entry.png), [mobile Home](qa/demo-transformation-2026-09-28/home-camera-mobile.png), [mobile evidence player](qa/demo-transformation-2026-09-28/live-evidence-mobile.png).
- Browser capture finding: native getScreenshot scales the desktop surface despite a viewport override; tab.screenshot({fullPage:true}) captures the actual responsive page. Mobile evidence in this pass uses the latter, alongside DOM dimensions.

### September 28 — stronger package-review scenario and reproducible accuracy failure

- Audited more of the bundled conveyor simulation and found a clearly deformed carton near 44 seconds. Prepared and uploaded an eight-second excerpt; indexed successfully through the UI.
- Home → package review search retrieved the correct five-second interval and playback verified the carton. Scenario is labeled simulation and human inspection.
- Two fresh questions completed quickly (8.3/7.7s local analysis), but missed the condition/deformation. Preserved exact inputs and outputs for diagnosis; no successful damage-detection claim or report created.
- Existing rehearsed recording remains the default. Three Home tests and typecheck pass. Core runtime stays healthy at 49.80 GiB available.
- [Scenario, evidence and unresolved model accuracy](qa/demo-transformation-2026-09-28/package-review-scenario.md).

### September 28 — isolated the package-condition failure; reasoning does not fix it

- Added a repeatable app-endpoint diagnostic; it reproduces the missed-deformation answer in 7.1s.
- Shorter evidence, surfaces/edges wording and neutral package wording did not resolve it. Single-frame controls show media sensitivity but unreliable condition/shape recognition.
- A bounded reasoning-mode probe took 33.5s and still failed. Kept the app's fast mode and all budgets unchanged; no speculative fix shipped.
- [Hypotheses, exact probes, outputs and remaining uncertainty](qa/demo-transformation-2026-09-28/package-condition-diagnosis.md). Core runtime remains healthy, 49.99 GiB available.

### September 28 — live answer-to-report handoff completed

- Added Save report to live answers with exact inspected windows. Preserves question, answer, source, timestamps and review notes; starts under review and exposes actual clip-retention status.
- Saved a real conveyor RTSP answer, navigated away, reopened it from Events & reports, played retained video and verified copied question/notes/evidence link.
- Fixed report links to use the current tab after new-tab navigation failed in the integrated browser. This also improves existing Search report links.
- 34 affected tests and app typecheck pass. All 31 core roles pass, 49.65 GiB available. Mobile save form and file-download delivery remain unverified.
- [Report ID, exact timestamps, evidence and test scope](qa/demo-transformation-2026-09-28/live-report-handoff.md).

### September 28 — report return path and current presenter guide

- Confirmed that standalone reports offered no app-return action after the move
  to same-tab navigation. Added **Back to demo**, returning to Home.
- Codex integrated browser verified the actual saved RTSP report at desktop and
  390×844, then activated the return link and confirmed a populated Home with
  video controls and the online RTSP entry. No framework overlay or recent
  console warnings/errors. Reset viewport afterwards.
- Five investigation API tests and app typecheck pass. No model/runtime changes.
- Replaced the presenter guide's contradictory accumulated checkpoints with a
  current, ordered walkthrough and explicit qualification gates. Preserved the
  original text as [historical checkpoints](qa/demo-transformation-2026-09-28/presenter-runbook-checkpoints.md).
- Updated the success-criteria matrix above to reflect bounded RTSP progress
  without treating it as continuous monitoring qualification.
- [Desktop report](qa/demo-transformation-2026-09-28/report-return-desktop.png),
  [mobile report](qa/demo-transformation-2026-09-28/report-return-mobile.png).

### September 28 — complete recorded rehearsal with repeated fresh answer

- Exercised Home → source-scoped search → playback → fresh question → reviewed
  report → Events reopening → retained playback → clipboard → Home.
- Search handoff completed by 3.185s. Two fresh answers matched the footage:
  8.0s / 7.6s local analysis; repeat observed complete by 9.691s.
- Actual guard telemetry across 177 seconds: 176 samples, minimum 49.085 GiB
  available, same boot, no gap over 1.069s. Core checks pass before and after.
- Recorded report defaults differ from Live; returning Home loses the selected
  chapter. These are follow-up UX findings, not blockers to this bounded run.
- [Exact rehearsal, report ID, limits and screenshots](qa/demo-transformation-2026-09-28/conveyor-complete-rehearsal.md).

### September 28 — preserve the demo chapter and unify report defaults

- Home remembers an explicitly chosen recording for the browser-tab session.
  Returning from a standalone report restores its preview, context and suggested
  query. Missing recordings fall back to an available source; unavailable
  session storage does not prevent selection. Nothing changes source ingestion.
- Recorded report defaults now match live: low review priority, under review.
  The existing editable review controls remain available.
- Codex browser: conveyor Home → Events → saved report → Back to demo retained
  conveyor selection. A fresh recorded answer then exposed the revised defaults;
  answer completed by 8.175s with 8.0s reported local analysis.
- Recorded report form checked at 390×844: notes editable, title/review summary
  and save/cancel controls visible, no horizontal overflow. Cancelled test draft
  and restored desktop. No new report saved, no console warnings/errors.
- Eleven focused Home/evidence tests and app typecheck pass. Tests exercise
  remount persistence, exact source routing, missing-source fallback and storage
  failure. No runtime/model configuration changes.
- [Restored chapter](qa/demo-transformation-2026-09-28/home-chapter-return.png),
  [mobile form](qa/demo-transformation-2026-09-28/recorded-report-form-mobile-viewport.png).
- The two UX follow-ups in the complete rehearsal receipt are now resolved.
  The separate live save-form mobile check and export delivery remain open.

### September 28 — live status request failure and readable-name validation fixed

- A real Home → camera transition produced a Next runtime overlay: uncaught
  TypeError `Failed to fetch` in OperationsWorkspace.loadIntelligence. The
  source-intelligence Promise.all had no per-source rejection handling, so one
  failed request discarded independent analysis states and rejected the effect.
- Added per-source error isolation. A regression rejects intelligence while
  analysis status succeeds and verifies the usable camera/paused state.
- The same audit found the replay's name, **Conveyor — Recorded Simulation
  (RTSP Replay)**, consistently returned HTTP 400. The endpoint incorrectly
  applied the identifier allowlist to the human-readable name. Names now allow
  Unicode/punctuation with bounded length and no control characters; identifiers
  retain their existing restrictions. Query values remain JSON-encoded terms.
- Actual endpoint now returns HTTP 200 with the exact source name and zero
  indexed/caption/event counts, consistent with continuous analysis paused.
- Event-candidate display now distinguishes unavailable counts from zero saved
  candidates; it no longer infers “None detected” from missing data.
- Codex browser reload → focused replay → expand intelligence: no runtime
  overlay, paused status settled, video advanced to 10.018s (readyState 4,
  no error). Console retains two pre-fix errors at 00:08:01 UTC; no newer
  warnings/errors appeared in the checked log. [Recovered page](qa/demo-transformation-2026-09-28/live-status-recovered.png).
- 18 targeted tests, app typecheck and diff check pass. Core checks pass with
  48.58 GiB available after playback. No model/budget changes; analysis stays
  paused. Left playback for Insights and deferred fresh inference near the
  48 GiB floor. Live save-form mobile qualification remains open.

### September 28 — per-rule source readiness, plus memory investigation

- Alert rules now pairs configuration status with actual source availability:
  loading, catalog failure, missing source, disconnected/unconfirmed camera,
  connected camera with analysis still needing verification, or recorded-run
  scope. This prevents an Enabled badge alone from implying active monitoring.
- Uses the existing source catalog/status hook; Refresh updates both rule and
  source information. No rule was enabled, disabled or deleted.
- Real browser cards identify the old warehouse recording as missing and the
  traffic camera as disconnected. Refresh preserves those settled facts.
- Eight rule-workspace tests and app typecheck pass, including online/offline/
  unknown source cases. Codex desktop and 390×844 layouts inspected; mobile
  Refresh and Manage sources bounding rectangles end at x=361 within the
  375px content viewport. Desktop restored afterwards.
- [Desktop rules](qa/demo-transformation-2026-09-28/rule-source-readiness.png),
  [mobile rules](qa/demo-transformation-2026-09-28/rule-source-readiness-mobile.png).
- Memory investigation: core still passes all 31 roles, available memory
  recovered to 48.85 GiB at 20:11 EDT. Thirty-minute telemetry process snapshots
  (356 samples with process lists) show 49.713→49.072 GiB available; largest
  listed RSS increases were VLLM engine +53 MiB, Python +32 MiB, VIOS +28 MiB.
  This does not identify the approximately 0.64 GiB change or prove a leak;
  sparse RSS lists exclude smaller processes and GPU/driver allocations.
  No speculative process termination, budget change or model restart performed.
  Continuous analysis remains paused; further inference/rehearsal must account
  for narrow headroom above the diagnostic floor.

### September 28 — mobile live-report path verified; disk-blocked search recovered

- Closed the live report mobile gap: fresh RTSP answer completed by 10.390s,
  exact inspected clip played at 390×844, title/notes were entered, report saved
  with retained media, and its report link/playback/clipboard worked. Restored
  desktop afterwards. [Full mobile receipt](qa/demo-transformation-2026-09-28/live-report-mobile.md).
- Runtime check then exposed Elasticsearch red/unhealthy: a primary shard could
  not allocate below the 12 GiB disk watermark. This limits prior readiness claims.
- Removed only 1.16 GB regenerable pip HTTP cache, preserving wheels/models/
  video/database. Allocation became permitted; normal retry recovered yellow
  with zero unassigned primaries. All 31 core roles passed again, 48.86 GiB
  available; guard and budgets unchanged.
- [Exact storage diagnosis, commands, outcomes and remaining headroom risk](qa/demo-transformation-2026-09-28/elasticsearch-disk-recovery.md).

### September 28 — storage maintenance, reserve trip and staged recovery

- Identified 11 GB preserved old traffic footage, about 530 MB current replay,
  a 100000 MB VIOS quota and about 39 GB reclaimable Docker build cache.
- Age-limited Buildx prune (older than seven days, retaining 20 GB, requesting
  30 GB free) reclaimed 5.05 GB; free disk became about 18 GiB. No images,
  containers, volumes, recordings or models were deleted.
- During maintenance, memory crossed the preserved 48 GiB floor (47.901 GiB).
  Guard stopped the AI workloads and NvStreamer; boot unchanged. Preserved
  incident evidence and started documented idle reclaim/staged core recovery.
  [Incident and recovery receipt](../artifacts/thor-recovery-2026-09-28/cache-maintenance-trip/README.md).
- Runtime guidance now requires cache maintenance with model workloads stopped.
  Added immediate Elasticsearch primary-shard health to manage.py status,
  rather than relying only on Docker's delayed unhealthy transition. Three
  focused tests cover healthy/yellow, unavailable/red/missing and malformed data.
- During the real outage, fixed Home's camera invitation: it now offers preview
  and states that local answers are unavailable/checking until readiness is true.
  Five Home tests and typecheck pass; captured the real unavailable state.
- Events → existing saved report → retained playback still worked with models
  restarting (24.798/24.798s, readyState 4, no error). This is a previously saved
  artifact, not fresh inference. [Home outage state](qa/demo-transformation-2026-09-28/home-ai-recovery-state.png),
  [retained playback during recovery](qa/demo-transformation-2026-09-28/saved-report-during-recovery.png).
- Recovery completed: original startup exited zero; all 31 core checks pass,
  including new primary-shard check. Fresh source-scoped search returned the
  conveyor clip and a new supported answer completed by 8.196s (7.9s local).
  After inference: 50.14 GiB available, guard active, boot unchanged, ~18 GiB
  disk free. [Fresh post-recovery answer](qa/demo-transformation-2026-09-28/post-maintenance-fresh-answer.png).
  This does not qualify sustained load or erase the maintenance-triggered trip.

### September 28 — readiness explained by demo action

- Previous browser-switch turn confirmed the requested tooling but made no goal
  implementation progress. Revalidated the runtime before continuing: all 31
  core roles passed with 49.70 GiB available, only 1.70 GiB above the preserved
  diagnostic reserve. Historical detector startup checkpoints varied by roughly
  1–1.8 GiB, so this is not sufficient evidence to start another detector safely.
  Both detectors remain stopped; no workload or budget was changed.
- Replaced the readiness popover's technical-first list with service availability
  for Play video, Search recorded video, Ask about a video clip, and Detect & track
  objects. Technical probes remain in an expandable disclosure. Explicit copy
  distinguishes service availability from camera connection, analysis settings,
  compute capacity and live monitoring readiness. Aggregate degraded status stays
  visible; there is no unsupported “all ready” claim.
- Missing dependency probes produce Not checked, not Available. Known failed
  dependencies affect only the relevant actions. Twelve focused tests and the
  app typecheck pass.
- Codex integrated browser: real running state shows the first three actions
  Available and object detection Unavailable. Expanded technical details show
  the failed detector check. Verified desktop and 390×844 mobile, disclosure,
  closeable panel, and Open full system view navigation. Mobile height now keeps
  the scrollable popover above bottom navigation. Browser error/warning log
  returned no entries in this validation; no framework overlay appeared.
- [Desktop evidence](qa/demo-transformation-2026-09-28/demo-service-readiness-desktop.png)
  and [mobile evidence](qa/demo-transformation-2026-09-28/demo-service-readiness-mobile.png).
  This improves presenter diagnosis; it does not qualify live ingestion or
  solve the remaining event-to-evidence demo. Next runtime qualification must
  establish measured detector headroom before attempting concurrent operation.

### September 28 — recorded coverage uses recording time, not synthetic dates

- Previous goal turn made verified UI progress (action-oriented readiness).
  Revalidated core this turn: 31 roles pass, 49.05 GiB available. Detectors remain
  stopped; no ingestion or model-budget change.
- System coverage still displayed uploaded file timeline values as December
  2024/January 2025 dates. VIOS identifies these uploads as FileDownload; they
  are synthetic recording timelines, not capture dates. Propagated source kind
  from catalog metadata through search coverage. RTSP URLs take precedence over
  file-like names/type, keeping recorded simulation transported over RTSP on its
  actual wall-clock timeline. Unknown metadata is not guessed from a filename.
- For recorded files, show the retained window span and Recorded file label;
  suppress synthetic calendar values. Preserve real live-stream timestamps.
  A span is the timeline envelope, not a claim of continuous coverage or full
  original-file retention. Backend retrieval/index timestamps remain unchanged.
- System now uses the established readable source aliases. Mobile inspection
  exposed ellipsis hiding the recording span and replay provenance; names and
  coverage facts now wrap, verified at 390×844. Desktop restored afterwards.
- Six API/component tests and TypeScript pass. Actual integrated-browser System
  view shows Box Movement 0:10, Package Review 0:08, Warehouse Box Handling 0:10,
  and the RTSP replay's real September 28 timestamp. No framework overlay;
  browser warning/error log returned no entries. Readiness and other workflows
  were not requalified by this display change.
- [Desktop](qa/demo-transformation-2026-09-28/coverage-recording-times.png),
  [mobile](qa/demo-transformation-2026-09-28/coverage-recording-times-mobile.png).

### September 28 — live alert path and latency preflight

- Previous turn made verified provenance/responsive UI progress. This turn
  inspected the actual visual-alert path and confirmed Alert Bridge has zero
  active rules. The existing Cosmos route can request visual conditions without
  starting another detector; operation remains unverified.
- Identified a concrete pacing constraint: the UI applies 30-second alert chunks
  despite the bridge's 10-second default. A full first window plus inference
  cannot meet the intended first-event pace. A shorter cadence needs binary-
  verdict/backlog measurements, not an untested configuration change.
- A UI-only restart completed and recovered after compilation, but did not
  establish useful additional memory headroom: 49.02 GiB available, UI 1.774 GiB,
  all 31 core roles pass. No continuous rule or detector was started.
- Corrected System's scheduling claim: Lane available means execution-lane
  ownership checks pass; it does not measure the host reserve or qualify live
  monitoring. Inspected the changed running panel in Codex's integrated browser.
- [Preflight findings and bounded-run evidence gates](qa/demo-transformation-2026-09-28/live-alert-preflight.md).
  Requested audience/presentation alignment and Spark scene/address/reset details
  through the asynchronous question interface; no answer assumed.

### September 28 — removed expensive container filesystem scans

- Previous turn established the live-alert path, 30-second cadence limitation
  and narrow reserve headroom. This turn investigated the collector consuming
  almost its full 1 GiB cap; restarting it alone did not help.
- Cgroup evidence identified roughly 860 MiB reclaimable slab versus 110 MiB
  anonymous memory. Disabled only cAdvisor's per-container disk-usage metric
  group through the Thor overlay; preserved CPU, memory, network, block-I/O,
  host disk capacity metrics, existing resource limits and the memory guard.
- Recreated only cAdvisor. Thirteen samples over 60 seconds show healthy status
  and about 27–126 MiB total cgroup memory, with about 3.6 MiB reclaimable slab.
  Prometheus scraping and retained metric families were verified; all 31 core
  roles pass and the boot ID is unchanged.
- Available host memory initially stayed near 49 GiB, then rose to 49.901 GiB
  in the final sample. Follow-up measurements are retained; this is not a
  sustained-capacity result or exact causal attribution of the host change.
- [Receipt and tradeoff](qa/demo-transformation-2026-09-28/cadvisor-scan-reduction.md).
  No alert rule, detector, or additional inference workload was started. The
  live path still needs an explicit scene condition and bounded qualification.

### September 28 — real replay alert reached playable evidence

- Previous turn reduced cAdvisor scan overhead with measured evidence. This turn
  ran one bounded visual rule on the conveyor replay through the real UI.
  Model responses were NO → YES → NO. A real event arrived; the positive clip
  visibly contained a box. Negative windows were not independently scored.
- Fixed the newly exposed Timing only gate: events with a valid source/time can
  now retrieve footage even without attached media URLs. Changed direct-rule
  trigger display to Model match, readable rule title and review guidance.
- Exact event clip played (22.5333s, readyState 4, no error). Acknowledge changed
  review state and removed it from Needs attention. Ten focused tests and app
  TypeScript pass. [Full receipt](qa/demo-transformation-2026-09-28/live-alert-event-proof.md).
- Watchdog stopped the rule after 90 seconds, released its reservation, left the
  diagnostic local record paused, and confirmed zero RT-VLM streams/rules.
  108 samples ranged 49.558–50.022 GiB available; persistent 48 GiB guard stayed
  enabled. No external notifications or detector startup.
- Corrected earlier pacing inference: actual sampled windows span ~22.5s on a
  30s cadence; first response ~24.5s after creation. First YES ~54.5s after
  creation. This is not a complete UI-latency or sustained-load qualification.
- Next concrete gap: the incident viewer can review/acknowledge but has no direct
  event-to-report handoff. Faster cadence and repeated positive/negative trials
  remain unqualified; Spark scene/reset access and audience alignment still open.

### September 28 — event-to-report handoff verified in Codex browser

- Added a report form directly to playable event evidence, preserving the exact
  source, event interval, monitoring condition and reviewer notes. Saving does
  not run another model request. Saved reports update the workspace list.
- HTML and copied briefings explicitly identify saved event records and their
  provenance; retention messaging uses actual storage status. The incident
  panel scrolls so the form remains reachable on mobile.
- Saved the real box-presence event as **Conveyor replay — box-presence event
  review**. Reopened its retained 22-second footage and verified actual copied
  text in Codex's integrated browser at 390×844. Returned to desktop Home.
- Fifteen focused tests (three suites) and app TypeScript pass. No additional
  inference workload or runtime-budget change. [Receipt](qa/demo-transformation-2026-09-28/event-report-handoff.md).
- This closes the previous direct event-to-report UI gap. Faster alert cadence,
  independently scored negative windows and Spark scene/reset qualification
  remain open; HTML/PDF file delivery is still unverified.

### September 28 — populated Insights now distinguishes model output from review

- Real event exposed a misleading “100% confirmed” summary and missing featured
  footage access. Replaced it with separate model outcomes and awaiting-review
  counts, added a direct model-match filter, and restored footage access from
  Insights for events without attached URLs. Dismissed candidates now contribute
  to outcome statistics. Counts explicitly describe loaded records, not accuracy.
- Added a clear page heading, moved the real event ahead of charts, displayed
  dates on hourly buckets and wrapped source names. Mobile previously hid the
  entire summary; it now remains readable with wrapping rule/review labels.
- Codex browser verified desktop Insights → footage and mobile Model match →
  footage. Real acknowledged event shows one model match and zero awaiting
  review. Clip reached 0:22 / 0:22. Eleven focused tests and TypeScript pass;
  browser error/warning log empty. [Receipt](qa/demo-transformation-2026-09-28/insights-model-outcomes.md).
- No model request, runtime restart or safeguard change. Repeated live-event
  speed/accuracy and multi-source analytics still need qualification.

### September 28 — measured faster alerts, exposed boundary misses

- Ran one guarded 90-second binary replay experiment directly through Alert
  Bridge at 10-second cadence; app default remains unchanged. Nine responses
  arrived 9.747–10.239 seconds apart, first response at 9.926 seconds. Last-frame
  to response lag 0.542–0.838 seconds without growth across the sample.
- Inspected four reconstructed frames from each of nine exact retained clips.
  Four YES windows show boxes; three NO windows show empty sampled frames;
  two NO windows contain a box near the end. These discrepancies now define
  the next diagnosis: exact model samples/alignment and any-frame semantics.
  No accuracy percentage or safe-negative claim is justified.
- 97 samples stayed 49.531–49.763 GiB available. Automatic cleanup left no rule
  or RT-VLM stream, boot unchanged; 31 core checks pass at 49.82 GiB afterward.
  Four diagnostic incident records preserved. No notification or detector startup.
- [Full receipt and frame evidence](qa/demo-transformation-2026-09-28/alert-ten-second-trial.md).
  Ten seconds is a measured candidate, not yet the default or sustained-ready.

### September 28 — reproduced and corrected fixed-clip boundary misses

- Built a sub-second fixed-clip baseline that fails on the same two late-box
  cases, with an empty-belt control. The baseline failed again after comparison.
- Final-frame images return YES. The four-frame file path includes its endpoint;
  changing only the question to explicitly ask about **any frame** corrects both
  clips. This supports a time-scope wording fix for the fixed-file cases, while
  exact live input alignment remains unproven.
- Two passes across all nine saved intervals agree with reviewed fixture labels
  (18 responses, 0.883–1.038s). The durable nine-case probe also passes. Preserved
  hashed clips and an executable local probe so the result can be reproduced.
- [Diagnosis and comparison evidence](qa/demo-transformation-2026-09-28/alert-boundary-diagnosis.md).
  Three NO labels use sampled review, not exhaustive annotation or an accuracy
  benchmark. No runtime/default change; all 31 core roles pass at 49.64 GiB.
- Next: transfer the explicit condition to a bounded ten-second live trial and
  verify actual event/evidence handoff before adopting a faster demo setting.

### September 28 — live any-frame trial and exact rule provenance

- Repeated bounded ten-second RTSP test with the explicit any-frame condition.
  Nine responses spaced 9.934–10.074s; first at 10.101s. Seven YES windows have
  visible supporting boxes; one NO is consistent with empty sampled frames;
  one NO contains a crumpled box. Fixed-file replay of that missed interval
  returns YES, but live sampling/generation settings remain confounders.
- Found and fixed a real UI provenance bug: new events inherited an unrelated
  old rule through source-only matching. Rule association now requires exact
  ID. Viewer shows the recorded condition; report saving preserves it ahead
  of edited current-rule prompts. Long title/source text wraps.
- Codex browser verified desktop/mobile evidence and a real report save, retained
  playback and clipboard with the correct condition. Sixteen focused tests and
  TypeScript pass. [Receipt](qa/demo-transformation-2026-09-28/alert-any-frame-live-trial.md).
- 97 samples stayed 49.346–49.815 GiB. Trial stopped cleanly, zero rules/streams,
  boot unchanged, 31 final core checks pass at 49.44 GiB. No default or safeguard
  change. Faster throughput has evidence; reliable live classification remains
  incomplete and must not be represented as solved by the fixed-clip wording.

### September 28 — clearer monitoring authoring in the Codex browser

- Prefer the connected camera, require a concrete visual condition, and preserve
  typed intent and the chosen rule type across the builder.
- Removed unsupported visual-rule cooldown claims; explain sampled windows and
  repeated matches. Detection rules retain their supported cooldown.
- Ten focused tests and TypeScript pass. Desktop/mobile Codex browser checks
  pass, draft closed without activation; no browser warnings/errors captured.
- [Receipt and screenshots](qa/demo-transformation-2026-09-28/rule-authoring-clarity.md).
  Live classification reliability remains open; runtime defaults unchanged.

### September 28 — align capability examples with demonstrated workflows

- Re-audited Home and What it can do in the Codex integrated browser. Found the
  clip-question example still recommended end-of-clip temporal reasoning, and
  Review and share promoted comparison despite the recorded reliability issues.
- Changed the example to visible activity and the review description to checking
  an answer against its supporting clip. Comparison remains available in the app;
  this change does not represent the underlying model issues as fixed.
- Four capability tests and app TypeScript pass. Desktop and 390 × 844 mobile
  content inspected; View saved reports reaches Events & reports with all 12
  reports listed in the count. No console warnings/errors captured. No inference
  or runtime change. Mobile viewport reset after inspection.
- Screenshots: [desktop](qa/demo-transformation-2026-09-28/capabilities-evidence-guidance.png)
  and [mobile](qa/demo-transformation-2026-09-28/capabilities-evidence-guidance-mobile.png).
- Next: complete a timed presenter rehearsal and resolve remaining live accuracy,
  repeatable simulator reset and export delivery gates.

### September 28 — repeat recorded presenter journey

- Search → fresh answer → report → clipboard → Home completed in 96.028 seconds
  including agent inspection pauses. Search observed by 3.410 seconds; answer
  reports 7.6 seconds local analysis and correctly describes conveyor movement.
- Saved and reopened report `700d0588-90f7-4afd-8a19-0cbd15309388`; actual copied
  text verified and retained video reaches 0:10 / 0:10. Home keeps the source.
- Replaced remaining end-state question shortcut with a visible-objects question;
  six panel tests, TypeScript and rendered fill behavior pass.
- Found two follow-ups: Home briefly exposes a media error while reconnecting,
  and report playback label remains “Playing” after completion.
- [Receipt and runtime evidence](qa/demo-transformation-2026-09-28/rehearsal-repeat.md).
  This adds a bounded repeat, not sustained or live qualification.

### September 28 — report playback completion and replay

- Fixed the stale disabled “Playing exact clip” button after saved report video
  completion. Media events now drive the button: playing disables it, pause offers
  Resume, ended offers Replay, and media errors offer Retry.
- Codex browser verified Play → ended at 0:10 / 0:10 → Replay → playing → ended
  again on report `700d0588-90f7-4afd-8a19-0cbd15309388`. Five report API tests and
  app TypeScript pass; no browser warnings/errors captured.
- [Rendered replay control](qa/demo-transformation-2026-09-28/report-replay-control.png).
  Pause/error branches were not browser-exercised. No new inference or runtime
  changes. Home's transient loading/media-error flash remains to investigate.

### September 28 — Home preview loading state

- The media element existed before its URL/frame was ready, exposing the browser's
  empty-player error during report → Home navigation. Keep it visually hidden
  and out of the accessibility tree until loaded data provides a decoded frame;
  clear frame readiness on emptied/error. Ignore media error events only when
  neither a URL nor a stream object is assigned; real source errors remain visible.
- Added a regression covering empty/loading/decoded/emptied/source-error states.
  Seven canvas tests and app TypeScript pass. Jest includes jsdom media cleanup
  warnings from unimplemented pause/load; actual browser console is clean.
- Codex browser verified report → Home loading has no false media error, followed
  by visible conveyor playback, pause and resume. [Screenshot](qa/demo-transformation-2026-09-28/home-preview-loaded.png).
- No inference or runtime changes. This is a presentation-state fix, not a claim
  that unavailable sources can play or that live monitoring is qualified.

### September 28 — inference seed propagation bug isolated

- Found request seeds omitted at all three vLLM SamplingParams boundaries.
  Prior fixed-file requests specified seed 42 but did not pin engine sampling.
- Regression reproduced nine failing seed/path cases; passing the configured
  seed fixes all nine. Full GPU model test extended but not run this pass.
- [Diagnosis and deployment boundary](qa/demo-transformation-2026-09-28/seed-propagation-diagnosis.md).
  Source change awaits staged model restart. No inference or restart performed;
  live miss causality and accuracy remain unproven.

### September 28 — staged runtime reload underway

- Seed fix requires new model workers. Cosmos-only stop did not free the startup
  headroom, so used the documented full stop and idle reclaim; 112.67 GiB recovered.
- Core startup process is active, with infrastructure health checks progressing.
  Models/UI are not yet restored. [Live work receipt](qa/demo-transformation-2026-09-28/seed-fix-runtime-reload.md)
  identifies the existing process and required follow-up; do not launch duplicates.

### September 28 — seeded runtime recovered and fixed-file comparisons passed

- Staged recovery completed; original manager exited only on cold UI compile
  timeout. Subsequent HTTP check and all31core checks pass,52.26GiB available.
  New Cosmos worker has patched source. Replay restored on API-returned port30557.
- Preserved live-miss file returns YES under both zero-temperature/seed42 and
  default-temperature/seed1 (four calls0.931–0.996s). Nine prior fixtures pass,
  0.872–1.065s. This does not reproduce or resolve the live NO.
- Zero active AI streams/rules; unchanged boot and memory safeguards. Browser
  reload hit a protocol policy block after outage; user asked to reopen HTTP demo.
- [Completed recovery receipt](qa/demo-transformation-2026-09-28/seed-fix-runtime-reload.md).
  Next diagnosis needs actual live model frames and metadata; rendered UI recovery
  still needs verification after browser access is restored.

### September 28 — live input capture seam identified

- Inspected the actual live decoder → model path. Existing published frame records
  provide timestamps, not pixel data; cache-directory references do not establish
  an existing capture facility. Another reconstructed-clip trial would retain the
  same ambiguity.
- [Capture plan and falsifiable hypotheses](qa/demo-transformation-2026-09-28/live-input-capture-plan.md)
  specifies the engine input boundary, bounded opt-in export and metadata needed
  to distinguish input mismatch from model judgment. No runtime change this pass.
- Confirmed inspected app alert paths forward the selected RTSP URL without fixed
  proxy ports; future diagnostics must discover the current URL after recovery.

### September 28 — bounded model-input capture implemented

- Added disabled-by-default lossless engine input export with request/byte limits,
  pixel hashes, timing/metadata/sampling arguments and linked successful responses.
  Capture errors do not alter inference; raw token IDs preserve the exact prompt.
- Six capture tests and the seed-boundary regression pass. Compose mounts the
  helper and defaults its directory setting to empty. Current workers unchanged;
  live capture/performance validation still requires staged loading and a bounded run.
- [Implementation scope and limits](qa/demo-transformation-2026-09-28/live-input-capture-plan.md).
  This enables the next diagnosis; it does not resolve the classification miss.

### September 28 — diagnostic source isolation and conversion check

- Verified capture is restricted to one exact RTSP URL, excludes warmup/recorded
  requests, and expires after 120 seconds with a persisted directory timestamp.
- Extended the actual adapter-method test through its asynchronous tensor-to-NumPy
  conversion. Capture and inference receive the same array; all seven capture
  tests pass. GPU capture remains unverified and is not enabled in running workers.
- Updated the [capture receipt](qa/demo-transformation-2026-09-28/live-input-capture-plan.md)
  with source-path evidence and the remaining live checks. This diagnoses the
  visible-box miss; it is not evidence that the model accuracy issue is fixed.
- Codex integrated browser inventory still shows the connection-error tab.
  Rendered review awaits the requested user reopen after the browser policy
  rejected reloading that error page. No alternate browser workaround was used.

### September 28 — capture hook staged loading underway

- Runtime preflight passed all 31 core checks with no active AI streams/rules.
  Stopped the publisher and stack through documented management tooling; idle
  reclaim recovered 112.40 GiB available without changing budgets or saved data.
- Started the existing staged core manager with capture restricted to the conveyor
  replay. Exec session 86552 is active; runtime recovery is not yet complete.
- [Reload receipt and exact continuation](qa/demo-transformation-2026-09-28/capture-hook-runtime-reload.md)
  records the live process handle, logs, preconditions and prepared bounded trial.
  The live capture and box-miss diagnosis remain outstanding.

### September 28 — first exact live-input review completed

- Reload completed; all31 core service checks pass and replay is restored. The
  manager's cold UI probe timed out, but the subsequent check passed without a
  duplicate restart. Both manager and trial processes are now terminal.
- A90-second trial captured nine real model inputs and linked answers. Reviewed
  all36 frames: each input contains a box and each answer isYES, including a box
  appearing only in the final sampled frame. There were no fully negative inputs,
  so the historical miss and false-positive behavior remain unresolved.
- Export overhead7.3–15.8ms, input cadence9.968–10.004s; these are not response
  latency measurements. Minimum memory54.413GiB; cleanup leaves zero rules and
  AI streams. App cadence and48GiB guard unchanged.
- [Evidence and next discriminating check](qa/demo-transformation-2026-09-28/live-input-capture-result.md).

### September 28 — response timing and repeat sample reviewed

- Extracted first-run response timing:0.558–0.709s from last-frame timestamp to
  model response log, excluding the sampling window and UI/event delivery.
- A second bounded run captured another nine positive inputs; all returnedYES.
  Manually reviewed all36 additional frames. Cleanup again left zero rules and
  AI streams. This run also lacked fully negative inputs and does not close the
  live accuracy gate. Stop random-start repetition; use a controlled negative
  interval for the next discriminating test.
- [Updated receipt](qa/demo-transformation-2026-09-28/live-input-capture-result.md).

### September28 — faster diagnostic captured negatives and an actual edge miss

- Five-second diagnostic windows supplied five clear positive and five empty
  inputs, all correctly classified, plus oneNO whose final sample contains a
  thin slice of an entering package. The exact engine pixels now preserve this
  boundary miss; it is not counted as a negative success.
- First response5.939s; subsequent input cadence4.986–5.013s. Last-frame to
  response log0.555–0.675s, excluding UI/event delivery. Memory minimum54.267GiB.
- Trial cleaned up to zero rules/AI streams. App defaults unchanged. Follow up
  on the captured boundary rather than repeating unscored live runs.
- [Full result and scope](qa/demo-transformation-2026-09-28/live-input-five-second-result.md).

### September28 — corrected false cold-start failure

- Two staged recoveries reported onlyUI API failure while the first page compiled
  for8.3–8.5seconds, exceeding the manager's5-second deadline. Both subsequently
  passed without another restart.
- The manager now grants only the UI root request15seconds; all model/backend
  probes retain5seconds. Actual timeouts/non200responses still fail readiness.
- Two scoped regression tests pass. Current runtime check passes all31core roles
  at54.43GiB available. No service restart or memory-budget change was needed.
  Updated the development workflow and presenter guidance with current scope.

## Next work (current)

1. Agree audience/presentation emphasis and obtain Spark scene/RTSP/reset access.
   This remains open, but does not block existing-footage improvements.
2. Run a complete timed rehearsal of the current guide, with repeated samples,
   actual playback/answer checks and memory measurements; fix interruptions.
3. Complete populated monitoring/analytics and remaining responsive/export
   checks. Mobile live save now passes; HTML/PDF file delivery remains unverified.
4. Resolve or constrain model failures in temporal endings, comparisons and
   package condition using reproducible evidence, not additional blind prompts.
5. Qualify a bounded Isaac Sim condition → analysis → event → evidence → report
   path and repeatable reset, following the target's runtime gates: the authorized
   Spark trial reserve is 24 GiB; Thor's diagnostic reserve remains 48 GiB.
6. Re-audit every original requirement against actual current-state evidence.
   A working recorded/replay path does not complete the requested live demo.

## Recording convention

For each future change, record the finding addressed, changed files or runtime
action, visible outcome, exact validation scope, evidence location, and remaining
limitations. Keep historical observations dated. Mark proposals as proposals;
only mark a finding verified after inspecting the changed running behavior.

## September 29 — prepare Git / DGX Spark handoff

The user is moving continued development to a DGX Spark running Isaac Sim at the
same time, with a Sim RTSP feed. They requested preparation here, without SSH.
Preserved the accumulated demo work and added an independent Spark deployment
candidate, memory guard, source-build/download steps and a concrete Codex handoff.
See [Spark handoff](spark-handoff.md) and [preparation receipt](qa/2026-09-29-spark-handoff.md).

This is a source/deployment handoff milestone, not completion of the tradeshow
demo goal or Spark runtime qualification. Target model warm-up, shared Sim memory,
actual RTSP ingestion, answer quality/latency and browser rehearsal remain to be
measured on Spark. Thor runtime and its 48 GiB diagnostic reserve stay unchanged.

## September 29 — begin preparation on the Spark target

The user authorized the next deployment stage on the GB10 Spark. Target preflight
and three bootstrap tests pass; Git LFS and fixture integrity are restored; the
independent 35-service graph is rendered for `10.88.9.91`; and the Spark 48 GiB
guard is installed and active. Existing Isaac Sim MCP and Moondream containers
remain running. Public images/source builds are being prepared while local NGC
credentials and privileged data-directory setup are requested. This is preparation,
not target inference or joint-workload acceptance. See the
[target startup receipt](qa/2026-09-29-spark-startup.md) for exact state and limits.
