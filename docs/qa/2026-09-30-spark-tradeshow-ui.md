# Spark tradeshow desk and bounded rehearsal — September 30, 2026

The primary screen now presents the user's live Sim as an understandable video
analytics demonstration: watch the scene, ask in ordinary language, check the
inspected footage, then keep a review. Search and monitoring have visible entry
points scoped to that same source. This receipt covers the new desk and one
empty-scene rehearsal; avatar accuracy and sustained tradeshow duration remain open.

## Implementation and target state

- Target: GB10 DGX Spark, `10.88.9.91`, branch `agent/vss-3.2.1-thor-parity`.
- Source: Spark Hospital Corridor,
  `rtsp://10.88.9.91:8554/digital-twin`, stream/sensor ID
  `3688c328-7e71-493c-a1c7-011ad2fb3893`.
- UI: [Vision Intelligence](http://10.88.9.91:7777/), running from source with
  Next.js Turbopack via `python3 tools/spark/ui.py dev`.
- Only the UI container was recreated. Sim, model budgets and the user-authorized
  24 GiB Spark guard were preserved. The UI has a 2 GiB JavaScript heap and a
  4 GiB container ceiling, with no additional swap.
- Final state: preview available, source analysis paused, recording off,
  detection disabled and no live rule active. Moondream remains stopped with
  Docker restart policy `no`; Sim remains running.

`LiveDemoWorkspace` replaces the recorded-first home when a live RTSP source is
registered, including an offline source that needs recovery. It prefers the
digital twin and clears its answer when the selected camera changes. Recorded-only
installations retain their existing entry workflow.

Opening the desk makes read-only capture-status and saved-report calls. **Start
live capture** records video without starting indexing, captions, detectors or
rules. Newly observed recording, including an already-on state at desk mount,
has a 30-second preparation period before questions are enabled. Every question
uses exactly the selected source. Replay uses its VST stream ID; analysis and
retained report provenance preserve the sensor ID contract.

The capture API verifies registered live-source membership and the VST final
recording state. VIOS modes `user`, `schedule` and `alwaysOn` establish continuous
recording; `event` does not establish continuous footage for recent-window
questions. Repeated start/stop commands return success only when the requested
final state is verified. An unverified stop leaves questions disabled. Poll
generation checks prevent an older GET from overriding a later capture mutation.
Question submission waits while an inspected clip is being prepared, preserving
the relationship between the visible answer and its footage.

“Live preview” follows video playback/decoded-frame evidence. An ICE connection
alone does not establish visible video; a stored preview is explicitly historical.
Device branding is neutral across the shell, source status, search and reports.

The alert builder has Sim-specific **Person appears** and **Corridor obstruction**
examples. Clicking either fills a prompt for review; it does not activate a rule.
Search copy describes ranked candidate clips rather than verified appearances.
While indexing is paused, the desk explicitly says search uses earlier indexed
video and links to the existing control for resuming it.

## Actual browser rehearsal

The integrated Codex browser completed these operations against the running stack:

1. Open the live desk and confirm advancing 1280×720 video with `readyState=4`.
2. Start recording, wait through preparation, and ask **Describe the people and
   their activity**. The actual answer is **“There are no people present in the
   scene.”** The visible corridor contains equipment and no person.
3. Inspect the returned interval, `2026-09-30T04:09:23.638000Z` through
   `2026-09-30T04:09:48.638000Z`, and select **Replay inspected clip**. The video
   has duration 25.001 seconds, dimensions 1280×720 and no media error.
4. Save **Digital twin demo — empty-scene baseline** with review notes identifying
   this as an empty-scene baseline and avatar testing as pending.
5. Stop capture, open the retained report and play the video through its end:
   `ended=true`, `currentTime=25.001`, `duration=25.001`, no media error.
6. Select **Search this scene**. Spark Hospital Corridor stays selected; the query
   “person walking through a hospital corridor” returns nine ranked historical
   candidates from one source. This is source-scoping/retrieval evidence, not
   proof of an avatar appearance. The current summary explains that distinction.
7. Select **Set an alert**. The same camera is preselected; **Person appears**
   fills the intended prompt and allows review. Close without activation.
8. Check Presentation Mode, restore normal navigation, and check desktop,
   narrow and default browser layouts. Temporary viewport overrides are reset.

Retained report: ID `8b984b20-7482-4c9c-8048-d553848c5a54`, created
`2026-09-30T04:11:14.699Z`, evidence `media_status=retained`.
[Open the baseline report](http://10.88.9.91:7777/api/vision/investigations?id=8b984b20-7482-4c9c-8048-d553848c5a54&format=html).

During the bounded 555.337-second observation, one-second host-memory samples
record a **36.792 GiB minimum**. The 24 GiB guard remains active and boot ID
`6b100cd0-2daa-4ef5-8db5-2b4c0bee5201` is unchanged. Capture and the single
interactive visual question were tested without enabling background indexing or
a visual rule. This interval does not qualify a concurrent or sustained workload.

The first watchdog cleanup retried stop after the UI had already stopped
recording. VIOS rejected that duplicate command, initially producing HTTP 502.
The API now re-reads status after a rejected command; the real repeated stop
returns HTTP 200 with `recordingStatus=off`, `vstRecordingMode=off`. The original
watchdog result is preserved alongside the verified correction.

## Visual fidelity ledger

The `imagegen` skill and ImageGen tool produced one full-screen concept before
implementation, using the actual hospital screenshot as the scene reference.
The accepted concept is **1536×1024** at private path
`/home/spark/video-search-and-summarization/.spark/tradeshow-ui/concept.png`.
It guided code-native CSS/components; it is not used as a background or substitute
for video, interface text or analytics. No people, detections or counts were
invented for the live implementation.

Final QA viewed the accepted concept and current desktop render together in the
same pass, with a 1536×1024 browser viewport. A full-page screenshot includes the
content below that viewport. The 390×844 narrow layout and restored 345×392
default viewport also pass; the narrow document has no horizontal overflow.

| Comparison point | Current implementation and disposition |
| --- | --- |
| Scene/question composition | Larger live scene on the left, questions on the right; preserved two-column hierarchy and quiet utility header. Narrow screens stack the same content. |
| Palette and surfaces | Dark `#101b1c`, mint `#48d3c5`, thin `#2b4142` dividers and restrained corners match the reference. Disabled question state is deliberately muted while capture is off. |
| Type hierarchy | Manrope Variable, 46px desktop heading, 18px introduction and 22px inspector heading keep the reference hierarchy. Actual text and controls are selectable DOM content. |
| Footage and state | Real 16:9 video, source name, connected state, live/stored/recorded labels and paused indexing are visible. The concept's wider generated video framing was not copied: source aspect ratio and playback controls are preserved. |
| Feature and evidence progression | Three numbered feature columns lead to real source-scoped actions; saved evidence rows use actual titles, dates and retention status. Empty/loading/failure states are distinct. |

Copy comparison: the headline, introduction, question examples, **Ask this
scene**, **Show what video can do**, three feature names/descriptions/actions,
step sequence and **Earlier evidence** wording follow the accepted concept.
Added functional copy includes explicit capture start/stop and preparation state,
unknown/error states, the inspected interval and duration, the replay/report
actions, and the explanation that paused search uses earlier indexed video.
Public device copy uses “On this device” and “Local video + AI.”

Intentional deviations: existing CTAI branding/icons are preserved; there is no
decorative fullscreen affordance without an implemented action. The real 16:9
frame plus capture controls makes the page taller, placing saved evidence below
the first desktop viewport. Saved records add rows absent from the concept's
empty evidence strip. Mobile has the existing fixed navigation; a full-page
screenshot places that fixed strip at the original viewport boundary, which can
overlay content in the long screenshot. Viewport use remains scrollable.

Private proof is under `.spark/tradeshow-ui/`: `desktop-final-full.png`,
`mobile-final.png`, `default-final.png`, the actual `desktop-answer.png`,
`runtime-samples.jsonl`, `runtime-result.json`, `cleanup-verified.json` and
`final-runtime.json`. These local receipts are ignored by Git.

## Scoped verification and remaining work

The app's strict TypeScript check passes. **Eleven affected Jest suites / 128
tests pass**, covering the desk, home entry/utilities, shell, canvas, operations,
alerts, investigation search, capture API, saved reports and source resolution.
Changed-file ESLint passes. **Six Spark UI helper tests pass**, and
`git diff --check` passes. Private command receipts are `final-tests.log`,
`final-typecheck.log` and `final-lint.log` under `.spark/tradeshow-ui/`.
Source-resolution regressions cover Nemo's development entries, internal aliases,
locales and VSS/common packages. The UI helper tests cover saved-reserve admission,
dependency integrity and Compose isolation. The broader Nemo implementation
diagnostic still exposes preexisting strict chat/markdown errors; passing the
app's public-contract check does not claim that diagnostic passes.

The source-mounted workflow is intentionally the active runtime. No full image
build was performed. The built fallback remains its prior screen until deliberately
refreshed. See [UI development](../ui-development.md) and the updated
[presenter runbook](../demo-presenter-runbook.md).

The final avatar rehearsal needs a repeatable entrance, visible hold, exit and
reset sequence. Current Sim controls are not a qualified individual-avatar
spawn/despawn interface. Score both person-present and person-absent answers,
positive/negative alert windows and semantic retrieval against that footage.
Do not infer calibrated occupancy, tracking, trajectories, heatmaps, brief-event
accuracy or sustained tradeshow readiness from this empty-scene trial.
