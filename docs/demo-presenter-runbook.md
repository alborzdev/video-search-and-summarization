# Live digital twin analytics — presenter runbook

Current Spark walkthrough, September 30, 2026. Open
[Vision Intelligence](http://10.88.9.91:7777/) beside the user's live Isaac Sim.
The primary source is **Spark Hospital Corridor**, published at
`rtsp://10.88.9.91:8554/digital-twin`. The intended story is a broad operations
and safety demonstration; audience details and the repeatable avatar controls
are still pending. Earlier Thor and recorded-only scripts are preserved in the
[historical checkpoints](qa/demo-transformation-2026-09-28/presenter-runbook-checkpoints.md).

## What the visitor should understand

“Video can answer a question, take you to a relevant moment, surface a visible
condition, and keep the footage behind a review. We are showing that analytics
layer on this live digital twin, with the video and AI running on this device.”

Start with the scene and a question. Show one clear result and its footage before
opening technical service information. Describe AI observations as observations
for review. Search relevance, an alert match, a tracked person and a distinct
physical event are different things.

## Prepare the desk

1. Open **Live demo**. Confirm the correct source and actual advancing **Live
   preview**. A stored preview or connected-source label alone does not prove
   live frames are advancing.
2. Check System if visual AI is unavailable. The hospital detector is now active;
   a visual question also works independently of detection. Use the saved
   single-camera setup; do not restart the full stack to improve a status badge.
3. Keep the Spark memory guard active at the user-authorized **24 GiB** reserve.
   Moondream must stay stopped and must require explicit opt-in to start.
4. Check a previously reviewed retained report as a fallback. **Earlier evidence**
   is explicitly historical; do not present it as a new discovery.
5. Select **Start live capture**. Wait for the 30-second preparation period and
   **Live questions ready**. The same preparation period applies when the desk
   first observes recording already on, so returning to the desk may require
   a short wait. Starting capture starts recording only. It does not start
   background indexing, captions, object detection or an alert rule.
6. Run the agreed avatar sequence in the Sim. Keep the relevant action in view
   long enough to be included in the inspected interval. Current visual analysis
   samples footage; a brief appearance can be missed.

Opening the page never starts capture or AI ingestion. Capture continues across
workspace navigation until **Stop capture** is used. Presentation Mode adjusts
the display; it does not qualify any workload.

## Review cameras and recordings

Open **Live cameras** for the source browser, then **Review source** for the
hospital camera. The full camera frame stays visible; **Ask this camera** sits
below it. The activity rail separates **Live recording** (needed for recent
questions and replay) from **Search indexing** (background searchable history).
The current hospital recording and search indexing are on, with detection and
tracking enabled. Choose a
starter to fill the question, then choose **Ask the video** to run it.

**Video history** opens this source's existing history workflow; building history
is an explicit additional processing action. **Processing details** reveals
caption/tracking coverage and analysis profiles. The current profile is
**Warehouse**, using its Person class for the avatar rehearsal. This model can
mislabel hospital equipment; tracked observations are repeated metadata records,
not a people count. Keep this profile while testing the configured one-camera
worker. **Sources**
returns to the browser, where recordings have their own **Open recording** action.
The primary camera card uses a live preview; static VST pictures can still be
damaged on this Spark, so use the advancing live video for the demonstration.

## Two-minute core story — watch, ask, verify, save

| Action | Suggested wording | Visitor takeaway |
| --- | --- | --- |
| Show an avatar in the live scene | “Here is activity in the digital twin.” | The source is visibly connected to the simulation. |
| Choose **Describe the people and their activity**, then **Ask the video** | “We can ask a question in ordinary language.” | The selected scene is inspected locally. |
| Read the answer and its inspected time window | “This answer refers to these recorded seconds.” | The answer has a defined scope, rather than an assumed current-frame view. |
| Choose **Replay inspected clip** | “Let's check what the video actually shows.” | The customer can verify or challenge the observation. |
| Choose **Save report**, add a useful title and review notes, then save | “We can keep the answer and its footage for someone to review.” | The output is evidence someone can open and discuss. |
| Open the report and play its retained video | “The evidence stays available after live capture stops.” | A retained report is useful beyond the live demonstration. |

Use **Return to live** to restore the current scene. If no person is visible,
accept a supported “no people visible” answer as a baseline, then repeat after
an avatar appears. Do not suggest that a plausible answer proves a calibrated
occupancy count or continuous person tracking.

## Extend the story — search and alerts

**Find a moment.** Select **Search this scene**. The source remains scoped to the
Sim and the query starts with “person walking through a hospital corridor.”
Search uses indexed video. Hospital analysis is currently active; confirm that
**Searchable through** advances to the time of the avatar activity, then search.
If analysis was paused between rehearsals, use **Resume analysis** in **Live
cameras** first. Play the retrieved interval
before making a claim about its contents. A semantic match is not automatically
verified by the visual model.

**Watch a condition.** Select **Set an alert**. The Sim camera is preselected.
**Person appears** and **Corridor obstruction** fill plain-language examples
for review; neither activates a rule by itself. Start with a visible, repeatable
condition. Review the prompt, activate one rule, then inspect matching footage
in **Events & reports**. Visual rules inspect sampled windows and can emit
repeated observations of the same condition. Do not describe three matching
observations as three different people or incidents.

A live visual rule reserves the visual lane. Pause or remove it before returning
to interactive questions. Recording, source analysis and monitoring are separate
controls: pausing analysis does not stop recording, and stopping capture does
not disable a rule. End a rehearsal by removing its rules, pausing background
analysis and stopping capture. Verify the resulting state.

## Confirmed scope and remaining rehearsal gates

The prior Spark trial demonstrated advancing 1280×720 preview, fresh visual
inspection, exact 25-second evidence, retained report playback after capture
stopped, semantic indexing and a bounded positive cart-condition rule.
[Exact joint trial receipt](qa/2026-09-29-spark-sim-joint.md).
This is a foundation for the avatar story, not a scored avatar evaluation.

The September 30 desk rehearsal also passes capture → question → 25-second
replay → saved report → retained playback after capture stops. Its actual
answer, “There are no people present in the scene,” matches the empty-corridor
baseline. The [UI receipt](qa/2026-09-30-spark-tradeshow-ui.md) records checks and
limits; the [retained baseline report](http://10.88.9.91:7777/api/vision/investigations?id=8b984b20-7482-4c9c-8048-d553848c5a54&format=html)
is available in **Earlier evidence**.

The Sim's population +/- controls stage scenario configuration; they are not
individual live spawn/despawn controls. Its allow-listed web protocol currently
has no per-avatar spawn command. **Reset Demo** clears actors but incoming Kafka
updates may recreate them; `scene.reset` reloads the stage and interrupts RTSP.
The hospital near-fall scenario is blocked pending a qualified adapter. Agree on
a repeatable external avatar sequence before promising customer-triggered
entrances, exits or a deterministic reset.

Do not promise occupancy totals, movement trajectories, heatmaps, calibrated
safety decisions, perfect brief-event detection or sustained tradeshow duration.
The [Spark detector check](qa/2026-09-30-spark-detection-tracking.md) now verifies
frames, tracking metadata and semantic indexing together. Avatar label accuracy
remains unqualified, with industrial mislabels observed in the hospital scene.
Rehearse an empty-scene baseline,
a visible entrance, a person held in view, an exit, and a repeat; score answers
and both positive and negative alert windows against the actual footage.

For fast iteration, use the [Spark source-mounted UI workflow](ui-development.md).
Only the UI is recreated. The existing built UI is a rollback to its previous
screen until deliberately refreshed; switching to it does not package the new
live desk.
