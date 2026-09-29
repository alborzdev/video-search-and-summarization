> Historical checkpoint collection, superseded by the current presenter runbook. Statements below describe different stages of the audit, not one current qualification.

# Edge video demo — presenter runbook

Working draft, September 28, 2026. Designed for a tradeshow visitor encountering
edge video AI for the first time. The industry emphasis and presentation length
remain open; the recorded warehouse example is the available starting point. This documents the recorded path verified during the UI audit; it is
not approval to present the full live stack as qualified.

## Latest rehearsal status — September 28, 18:46 EDT

Runtime recovery completed at 18:44:55 EDT. All 31 core service/API checks and
the Home → conveyor search handoff passed again. Post-search available memory:
50.97 GiB. The 48 GiB diagnostic reserve remains enabled. Repeated memory trips
mean sustained presentation readiness is still unqualified.

Home now offers **Warehouse — Box Handling** and **Conveyor — Box Movement**.
Choosing a recording changes its preview, business context and suggested query.
These are recorded examples; neither establishes active monitoring.

| Chapter | Verified evidence | Remaining qualification |
| --- | --- | --- |
| Find a moment | Both recordings retrieved through plain-language search; conveyor playback advanced without a media error. New Home CTA retrieved the scoped ten-second conveyor result after recovery. | Repeat during a sustained rehearsal. |
| Ask about visible movement | Warehouse answer: 11.2 s; conveyor answer: 7.5 s local analysis in individual fresh runs. | Repeatability and broader questions. These are samples, not latency guarantees. |
| Explain an ending | Short questions complete, but sometimes infer completed placement or leaving a belt. | Grounding failure remains; inspect the video before endorsing claims. |
| Compare clips | One passing comparison; reversed order reintroduced unsupported placement. | Not dependable for the main walkthrough. |
| Save and revisit | Saved report and its retained video reopened successfully. Copy briefing delivered answer, notes and evidence links to the integrated-browser clipboard. | Download delivery, consistent new-tab link activation and long-term retention are unqualified. |
| Live monitoring | Configured sources and honest unavailable states are visible. | Connected Spark feed, resettable scene, detection/event delay and sustained memory qualification. |

### Conveyor chapter — a second business example

Choose **Conveyor — Box Movement** on Home, then **Find a box moving on the
conveyor**. Play the result, choose **Ask about this clip**, and use **What
moves?**. Explain: “An operations team can find and review an item's movement
without watching the whole recording.” The inspected sample shows a box moving
around a bend and leaving the camera view; it does not show a defect or jam.

Fresh answer in the bounded rehearsal: “A box moves along a conveyor belt.”
Local analysis was 7.5 s, observed complete by 11.641 s. The ending follow-up
took 8.2 s but claimed the box moved off the belt: leaving the camera view is
visible, leaving the belt is not established. Do not use that follow-up as an
accuracy success. No report was saved from it.

## What works in the current recorded path

Open [Vision Intelligence](http://10.88.9.12:7777/). The indexed ten-second
warehouse recording is currently named **Warehouse — Box Handling** in the UI.
It is test footage, not a live camera or an example of a confirmed safety event.

| Step | Action | Point to make | Evidence to check |
| --- | --- | --- | --- |
| Start with footage | Home: play the featured recording, or choose the recording in Search video. | The system starts with ordinary video. | A moving picture, source name, and recording-relative time. |
| Find a moment | Home: choose Find a person carrying a box. The app opens Search video scoped to Warehouse — Box Handling. | Describe what to find instead of manually scrubbing video. | One five-second semantic match was verified at 0:00 into recording. Retrieval is relevance ranking, not an incident verdict. |
| Check the evidence | Play clip, then Ask about this clip. The question field receives focus. | The visitor can inspect the same footage the explanation will reference. | Playback, exact clip bounds, and selected-evidence state. |
| Ask locally | Enter the rehearsed visible-action question below, then Ask selected evidence. | A bounded visual explanation is grounded in the selected clip. | Fresh-inspection provenance and a playable citation. Watch/read the result before endorsing its interpretation. |
| Hand off | Save report; add an accurate title and review notes. Open report. | Useful output is a reviewable briefing, not just a chat answer. | Saved report, cited clip, and actual media-retention status. Saving creates real development data. |
| Share | Copy briefing; paste the answer, notes and evidence links into the intended handoff. Download briefing (.html) is also available but delivery remains unverified. | A reviewed answer can leave the chat with its evidence references. | Clipboard copy verified. Links return to this device and need connectivity; video is not included in copied text. |
| Explain the edge | System → Edge system. | Show the services and hardware actually hosting this run. | Current health, memory, coverage and workload admission. A healthy service alone does not prove active camera monitoring. |

The presenter can explain the clip and citation while a fresh analysis runs.
Measured single-clip answers after removing redundant synthesis ranged roughly
13–22 seconds in sampled runs. This is not a latency guarantee or a qualified
percentile. Multi-clip reasoning and continuous monitoring have different costs.
Do not fill delays with invented results or present a saved answer as fresh.

## Accuracy finding to address before presenting

The [rehearsal follow-up](qa/demo-transformation-2026-09-28/recorded-rehearsal.md)
found an unsupported completed-action claim in the saved answer. Prompt revisions
have not yet established reliable temporal grounding. Do not present that report
as an accuracy success; it remains useful for testing traceability and report
playback. Review the cited footage and qualify important claims before a demo.

## If fresh analysis is unavailable

Use Events & reports → Open report for **Tradeshow rehearsal — box held at final frame**
to demonstrate the reviewed, previously saved artifact ([receipt](qa/demo-transformation-2026-09-28/report-rehearsal.md)). Download delivery remains unverified in the integrated browser; do not promise that handoff until a file is received. Say explicitly that it is an earlier
verification run. Its retained clip uses an evictable local cache; verify playback
before the presentation. Do not promise indefinite retention.

If source playback fails, stop that portion of the demo and use only material
whose provenance and availability can be verified. Presentation Mode changes
shell styling; it does not repair services, cameras, admission or media.

## Live scenario gate — still open

Five configured live feeds were offline at the last source-status audit. Detection
workers are stopped and source ingestion is paused. Before adding a live chapter:

1. Confirm the intended audience and business question.
2. Obtain the current Spark address, Isaac Sim version, scene and camera RTSP URLs.
3. Choose one bounded scene action, a reset, and a camera viewpoint that makes it
   visible. The warehouse-flow scenario in the research note is a proposal.
4. Follow [runtime qualification](../tools/runtime/README.md), preserving the
   48 GiB diagnostic floor. Qualify the selected workload and connection rather
   than starting the entire stack to make service badges green.
5. Verify the exact journey: fresh frames → active analysis → scripted condition
   → correctly classified candidate/verified event → playable evidence → briefing.
6. Measure event delay, first useful result, answer completion, memory behavior,
   and repeatability across resets. Label simulation and replay explicitly.

No live demonstration is qualified by this runbook. Camera connectivity,
sustained ingestion and a complete rehearsal remain required work.

Earlier: [September 28 recorded-path rehearsal](qa/demo-transformation-2026-09-28/recorded-rehearsal.md) — 923 ms to search result and 15.244 s to fresh answer in one run.

## Rehearsal receipt

For each rehearsal record the date, boot/runtime state, source IDs, exact query,
clip bounds, request timings, outcome, media status and any failure. Link the
receipt from the [running progress](demo-transformation-progress.md). Record what
actually happened, including whether an answer was fresh or previously saved.

Related: [industry/scenario research](research/2026-09-28-edge-video-demo-scenarios.md)
and [QA evidence](qa/demo-transformation-2026-09-28/README.md).

Latest integrated-browser question check: [fresh answer receipt](qa/demo-transformation-2026-09-28/fresh-answer-codex.md).
A visible-action/final-frame question produced a matching observation, with
17.57 s logged VLM processing and browser completion observed by 27.136 s.
Use the exact prompt in the receipt as one rehearsed example, not an accuracy
or latency guarantee. While processing, point out the selected footage and
explain that the answer will link back to that same clip.

## Short visitor walkthrough — recorded chapter

This is a proposed talk track, with the opening search/viewer/question handoff
rechecked in the integrated browser on September 28. It is not a timed full
rehearsal or a claim that the remaining live chapter works.

1. **Start with the problem.** “When you need to find what happened on camera,
   the slow part is usually finding the right moment. Here we can describe it.”
   Point to the warehouse recording and identify it as prepared demonstration
   footage. Do not describe the burned-in date as today's event time.
2. **Find, then show.** Choose **Find a person carrying a box**. Explain:
   “This searches footage already indexed on the Jetson.” Open **Play clip**.
   Let the five-second result play so the visitor can see the person and box.
3. **Ask something the footage can answer.** Choose **Ask about this clip** and
   enter: “Describe only the person’s visible actions in this clip. Is the box
   still being held in the final frame?” Submit once. While it runs, explain:
   “It is inspecting this selected clip locally. We'll check its answer against
   the footage.” The two recent sampled runs are in the fresh-answer receipt;
   the repeat showed 17.2 seconds of local analysis and browser completion
   observed by 17.735 seconds. This is not an instantaneous-answer claim.
4. **Check, then save.** Read the answer, replay its cited clip, and point out
   whether its statements match what is visible. Save a report only after
   reviewing the answer; include any uncertainty in the notes. Explain:
   “The useful output is a short explanation with footage someone can verify.”
5. **Connect the business value.** “The same workflow can support reviewing
   warehouse activity or finding a relevant moment in other operations. Each
   live detection or alert scenario needs its own configured and tested setup.”
   Use **What it can do** for follow-up discussion and **System** for technical
   questions about this device. Industry examples are opportunities, not proof
   that every workload is operating here.

The opening recheck found one five-second result at recording offset 0:00,
a playable viewer, and a focused question field after the handoff. No new model
answer or saved report was created in that recheck. Keep the earlier accuracy
finding above visible in preparation notes; one rehearsed prompt does not
establish general reliability.

## Two-clip comparison — not qualified for the main walkthrough

Most recent check: reversing the selected clips kept citation labels correct
but brought back an unsupported completed-placement claim in both observation
and summary (23.0 s local analysis). Keep comparison outside the dependable
main walkthrough until the accuracy issue is resolved; the passing run below
is a historical sample, not repeatability evidence.

Latest update: concise per-clip instructions produced the first internally
consistent result for the original position comparison in 24.9 s local analysis,
observed complete by 28.796 s. E2 playback confirmed the final platform position.
This supersedes the claim that every tested comparison fails, but ordering,
question variation and repeatability still need validation before making it a
dependable main-demo step. See the latest entry in the comparison receipt below.

Latest single-clip alternative: use the editable **What moves?** starter
(`What moves in this clip?`). With the question-focused prompt, this returned a
matching description of walking, approaching the steps and still holding the
box in 11.2 s local analysis, observed complete by 14.557 s. See the
[fresh comparison of prompt behavior](qa/demo-transformation-2026-09-28/focused-single-clip-prompt.md).
The end-state starter was faster but still added an uncertain gaze direction;
review answers rather than presenting this as general accuracy qualification.
No new saved report was created from these checks.

The [September 28 comparison check](qa/demo-transformation-2026-09-28/comparison-check.md)
found unsupported placement claims, contradictory observations before a prompt
scope fix, and a synthesis-format failure afterwards. Local analysis took
29.5–33.0 seconds in two samples. Clip selection and playback can be shown;
do not present fresh multi-clip comparison as a reliable demonstrated result yet.

### RTSP preview checkpoint — September 28

System → Sources includes **Conveyor — Recorded Simulation (RTSP Replay)**. Its Play button was verified in Codex’s integrated browser with actual video frames. Explain that this is a recording streamed locally over RTSP. AI analysis is intentionally paused and remains paused after Agent restart. Do not present this as a qualified live-alert or sustained-ingestion demonstration. See [preview qualification](qa/demo-transformation-2026-09-28/preview-only-rtsp.md).

### Bounded RTSP question checkpoint

Two fresh visual questions against the conveyor RTSP replay completed by 11.7 and 14.9 seconds, with continuous analysis paused. This proves the on-demand path executes, not that all answers are accurate. The second answer's color claim is unverified. The current answer UI lacks the exact inspected live interval and replayable citation; address that before presenting the result as fully reviewable. [Receipt](qa/demo-transformation-2026-09-28/live-preview-questions.md).

### Live evidence handoff checkpoint — supersedes the missing-interval limitation

From the focused conveyor RTSP replay, ask “What is visible on the conveyor?” The latest bounded run completed by 12.4 seconds and now displayed the precise inspected window. Choose **Play inspected clip** to review that same 25-second interval. Say: “This answer inspects recent recorded footage from the stream; let's check the evidence.” Actual playback passed. This improves reviewability; the earlier unverified color claim and broader accuracy qualification remain open. [Receipt](qa/demo-transformation-2026-09-28/live-evidence-window.md).

### Home entrance to the stream demo

When a camera reports online, Home shows **Try a camera stream**, the exact feed name, and **Open camera stream**. This opens that source directly in focused Live view. The current conveyor entry explicitly identifies a recorded simulation replay. Continuous analysis can remain paused while the presenter asks an individual question and replays its inspected interval. Home routing/playback and mobile evidence layout were verified on September 28.

### Package review — retrieval demonstration, condition answers unqualified

Home → **Conveyor — Package Review** → **Find a box to inspect** retrieves a visibly crumpled carton in simulated footage. Play and inspect the result to demonstrate targeted video review. Do not present automated damage classification: both a condition question and a shape question missed the deformation in the current rehearsal. No cause, contents damage, rejection decision or alert is established. [Reproducible case](qa/demo-transformation-2026-09-28/package-review-scenario.md).

Package-condition diagnosis update: changing temporal bounds and question wording did not qualify this case. A single-frame reasoning probe took 33.5 seconds and still missed the deformation, so reasoning remains off in the demo path. See [diagnostic evidence](qa/demo-transformation-2026-09-28/package-condition-diagnosis.md).

### Complete RTSP briefing handoff

From a timestamped live answer: **Play inspected clip** → review the footage → **Save report** → add a title and qualified notes → **Save report with evidence**. The report starts under review. Reopen it from **Events & reports**, use **Play exact clip**, then **Copy briefing**. Verified with “RTSP demo — conveyor movement,” ID 3dce054a-3af9-43ec-aaa0-26d97d660e53. Report links now open in the current tab; browser Back returns to the app. [Rehearsal and retention limits](qa/demo-transformation-2026-09-28/live-report-handoff.md).
