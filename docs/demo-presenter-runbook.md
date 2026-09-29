# Edge video demo — presenter runbook

Current preparation guide, September 28, 2026. Replaces the accumulated
[historical checkpoints](qa/demo-transformation-2026-09-28/presenter-runbook-checkpoints.md).
The goal remains a convincing tradeshow demonstration of local video AI.
Audience and duration are still proposed: industrial operations, about five
minutes, with optional technical discussion. Spark access and a resettable
Isaac Sim scene remain pending.

## The story a visitor should understand

“Finding what happened on camera takes time. Describe the moment, inspect the
footage, ask a focused question, and save a briefing someone can verify. The
video and this analysis run locally on the Jetson.”

Lead with the footage and a business question. Show technical services only
when explaining where the work runs. Distinguish the available **recorded
examples**, **recorded simulation streamed over RTSP**, and the still-unqualified
**continuous monitoring/alert scenario**.

## Current scope

| Demonstration | Evidence | Limit |
| --- | --- | --- |
| Search indexed recordings and play a match | Warehouse, conveyor movement and package-review examples retrieved and played in Codex browser | Relevance is not an incident verdict. |
| Ask about visible movement | Warehouse 11.2 s and conveyor 7.5 s local analysis in sampled runs | Samples, not latency percentiles; verify the actual answer. |
| Inspect recent RTSP footage | Fresh answer completed by 12.4 s; exact 25-second inspected interval played | Local replay of a simulation; continuous AI analysis remains paused. |
| Save and reopen a briefing | Recorded and RTSP reports reopened with retained video; actual copied text includes evidence links | Evictable cache, network access required; HTML/PDF delivery unverified. |
| Find a package for human inspection | Retrieved clip visibly contains a crumpled carton | Current model repeatedly misses deformation; automated condition classification is not qualified. |
| Monitor and alert | Bounded replay rule produced NO → YES → NO; positive event clip reviewed, acknowledged and saved as a report | Negative windows not scored; no qualified Spark reset, repeated latency or sustained ingestion. |

The last report-handoff runtime check passed all 31 core roles with 49.65 GiB
available. This is a point-in-time check, not sustained readiness. The active
48 GiB diagnostic guard must remain enabled; both detectors remain stopped.
Prior memory trips still require a sustained rehearsal before public use.

Latest complete recorded rehearsal: search → two matching fresh answers → save
→ reopen → play → copy → Home passed. Fresh local analysis 8.0s and 7.6s;
repeat completion observed by 9.691s. Minimum available memory across the
177-second measured interval was 49.085 GiB. This is one bounded rehearsal,
not a sustained qualification. [Exact receipt](qa/demo-transformation-2026-09-28/conveyor-complete-rehearsal.md).

A subsequent recorded rehearsal again completed search, fresh answer, retained
report playback, clipboard and Home. Local analysis reported 7.6 seconds; minimum
available memory was 48.466 GiB across 240 samples. This narrow headroom is not
sustained qualification. [Repeat receipt](qa/demo-transformation-2026-09-28/rehearsal-repeat.md).

## Before the visitor arrives

1. Open [Vision Intelligence](http://10.88.9.12:7777/). Confirm Home has real
   footage and the expected source labels, not an error or empty preview.
2. Follow [runtime qualification](../tools/runtime/README.md) for current health,
   storage and memory checks. Do not restart all services to make badges green.
3. Check playback for the selected recording and the saved fallback report.
   Reports depend on retained media that can expire.
4. If showing the RTSP chapter, confirm the Home camera entry names
   **Conveyor — Recorded Simulation (RTSP Replay)** and frames advance.
5. Presentation Mode changes shell branding only. Inspect real readiness in
   System; presentation styling does not qualify the workload.

## Main walkthrough — find, inspect, ask, hand off

| Step | Presenter action | Visitor takeaway |
| --- | --- | --- |
| 1. Start with a concrete task | On Home choose **Conveyor — Box Movement**. Identify it as recorded simulation footage. | “Find an item's movement without watching the whole recording.” |
| 2. Find the moment | Choose **Find a box moving on the conveyor**. Play the returned clip. | Plain-language search takes the visitor to actual footage. |
| 3. Ask a bounded question | Choose **Ask about this clip** and ask **What moves?** | A fresh local model inspects the selected footage. While it runs, point out the clip and source. |
| 4. Check the answer | Read the answer and replay the citation. The rehearsed answer was “A box moves along a conveyor belt.” | The answer is reviewable against video. Leaving the camera view does not establish leaving the belt. |
| 5. Save useful output | **Save report**; add an accurate title and review notes. Open the report and play its clip. | The result is a briefing with evidence, not a disconnected chat response. |
| 6. Hand off and return | **Copy briefing**. Use **Back to demo** to return to Home. | The copied text includes evidence links; video stays on the device and needs network access. |

Home now remembers the explicitly chosen recording within the browser-tab session,
including when returning from a standalone report. Recorded and live reports
start at low review priority / under review; recorded review controls remain editable.

If the model adds an unsupported claim, say so and inspect the footage. Do not
save an unqualified answer as an accuracy success. Use the previously reviewed
report **Conveyor demo — box movement** for a saved-artifact explanation if fresh
analysis is unavailable. Explicitly identify it as a previous run.

Warehouse — Box Handling is a second recorded example. Its **What moves?**
question has a supported sampled result. Questions about completed placement
and two-clip comparisons remain unreliable; keep those out of the main script.

## Optional RTSP chapter — the same workflow on a stream

1. Home → **Open camera stream**. Name it accurately: a recorded simulation
   replay published locally over RTSP, not the user's live Spark scene.
2. Ask **What moves along the conveyor?** once. In the latest report rehearsal,
   the answer completed by 16.38 seconds. Explain that this inspects a recent
   recorded window, not necessarily the frame currently on screen.
3. **Play inspected clip**. Point out the exact timestamps and check the answer
   against the 25-second interval.
4. **Save report** → title and qualified notes → **Save report with evidence**.
   The record starts under review and reports actual media-retention status.
5. Open it, play the clip and **Copy briefing**. **Back to demo** returns Home.
   The existing reviewed example is **RTSP demo — conveyor movement**,
   ID `3dce054a-3af9-43ec-aaa0-26d97d660e53`.

This chapter demonstrates on-demand visual questions and traceable reports.
It does not qualify always-on analysis, automated detection, alerts or sustained
load. [Exact report rehearsal](qa/demo-transformation-2026-09-28/live-report-handoff.md).

## Optional event chapter — review a real prior match

Use **Events & reports** to open the saved **Conveyor replay — box-presence
event review** (report `afa08fcf-b4f2-4d50-a1ff-ef61dec5f108`). Identify it as a
previous bounded test of recorded simulation streamed over RTSP. The rule is
now paused. Its condition was “Is a box visible on the conveyor belt?”

For an overview, choose **Insights**: the acknowledged event remains a model
match while Awaiting review is zero. **Find footage** opens its clip. Model
outcome counts are not an accuracy score. The **Model match** filter in event
review finds these direct-rule results separately from verification results.

Show the retained 22-second clip and reviewer notes, then **Copy briefing**.
Explain that a model match brings footage to a reviewer; it does not establish
a safety incident. In an event viewer, **Save event report** preserves the
original event interval and notes without another AI request. The report names
that provenance explicitly. [Verified handoff](qa/demo-transformation-2026-09-28/event-report-handoff.md).

The bounded rule's first response arrived about 24.5 seconds after creation;
its first YES about 54.5 seconds after creation because the first window was NO.
A later ten-second backend trial produced nine timely responses but exposed two
NO-window/footage discrepancies; it has not replaced the app default. See the
[trial receipt](qa/demo-transformation-2026-09-28/alert-ten-second-trial.md).
The boundary cases pass repeated fixed-clip checks with explicit “any frame”
wording. A subsequent live trial stayed near ten seconds but missed one window
with a visible crumpled box; the faster default remains unadopted.
[Live trial and provenance fix](qa/demo-transformation-2026-09-28/alert-any-frame-live-trial.md).
Do not promise instantaneous alerts or restart monitoring for a visitor until
shorter cadence and repeated positive/negative trials pass the runtime gates.

Later exact-input diagnostics produced18supported positive results at ten-second
cadence. A five-second diagnostic produced five supported positive and five
supported empty-input results, plus a miss when only a thin package slice entered
the image edge. First response was5.94seconds; this excludes downstream event/UI
handoff. This is promising diagnostic evidence, not a qualified five-second live
demo or resolution of all earlier misses. Keep partial-visibility and automated
damage claims out of the pitch. [Captured inputs and limits](qa/demo-transformation-2026-09-28/live-input-five-second-result.md).

## Optional industry discussion

For package review, Home → **Conveyor — Package Review** → **Find a box to
inspect** shows targeted retrieval and human inspection of a visibly crumpled
carton. Do not pitch the current run as automated damage recognition: interval,
wording and single-frame reasoning probes failed that case. See the
[diagnosis](qa/demo-transformation-2026-09-28/package-condition-diagnosis.md).

Use the [industry research](research/2026-09-28-edge-video-demo-scenarios.md) and
**What it can do** to discuss potential workflows. Tie each example to its
required camera, model, evidence and operational decision. Potential use cases
are not claims that those workloads are running here.

## Explaining a monitoring rule

Start with the connected source and describe one visible condition. The builder
now requires a concrete visual condition and preserves it through review.
Explain that local AI checks sampled video windows, and matching windows may
each create an event. Visual rules do not currently support the detection-rule
cooldown. Test the condition against footage before presenting it as dependable;
the live any-frame trial still had a miss. [Authoring QA](qa/demo-transformation-2026-09-28/rule-authoring-clarity.md).

## Remaining qualification gates

- Agree audience and presentation length; obtain current Spark connection,
  scene, RTSP cameras and who operates/reset the simulator.
- Qualify one visible, repeatable simulated event from fresh frames through
  analysis, correct event classification, playable evidence and briefing.
- Rehearse the complete settled app journey repeatedly with timings and memory
  measurements; prior fast samples do not establish repeatability.
- Resolve or explicitly constrain temporal/comparison/package-condition model
  failures. Do not mask them with saved responses presented as fresh.
- Complete the populated monitoring/analytics audit, file-export delivery checks; the recorded and live report forms now pass
  their bounded mobile checks.

For every rehearsal record boot/runtime state, source IDs, exact query, evidence
bounds, timings, answer accuracy, retention and failures. The
[running progress](demo-transformation-progress.md) is the authoritative ledger
of changes; linked receipts establish their precise verification scope.


Latest mobile RTSP report check passed through retained playback and clipboard,
with one fresh answer observed by 10.390 seconds. [Receipt](qa/demo-transformation-2026-09-28/live-report-mobile.md).
The following runtime check found a disk-blocked Elasticsearch primary. Recovery
restored all core checks without lowering safeguards, but disk remains nearly
full. Include free-space/allocation checks before presenting; [recovery and limits](qa/demo-transformation-2026-09-28/elasticsearch-disk-recovery.md).


Storage maintenance later reclaimed another 5.05 GB of old build cache but
coincided with a memory reserve trip. Perform such maintenance with models
stopped, never during a presentation. The guard remains at 48 GiB. The runtime
preflight now checks Elasticsearch primary shards directly. See the
[incident and recovery](../artifacts/thor-recovery-2026-09-28/cache-maintenance-trip/README.md).
