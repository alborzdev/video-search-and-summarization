# Warehouse video workflow — booth playbook

Use [Video workflow](http://127.0.0.1:7777/?workspace=guided) on the Spark for the repeatable
flow: **Watch → Ask → Find → Follow → Monitor → Review**. The product uses ordinary
workspace language; optional **Workflow tips** explain each tool. The explainer’s
**Explore your video** button opens the same workspace.

The planned scene is a warehouse published at `rtsp://127.0.0.1:8554/digital-twin`
on the Spark. The local launcher uses stable addresses without venue Internet.
The September 30 recorded rehearsal used the earlier hospital scene. Those old
reports demonstrate the plumbing, not verified warehouse behavior. Do a fresh
warehouse rehearsal after changing the simulator scene. The source currently
retains its original registered name; confirm the actual footage before renaming
it, and preserve the source ID and earlier evidence attribution.

## Before opening

Start the simulator using its existing Desktop shortcut, then double-click
**Start VSS**. Allow about 10 minutes for a cold start and wait for the readiness
message. **Stop VSS** ends the VSS session while retaining recordings and reports;
the Sim stays separate. See [desktop startup instructions](spark-desktop-startup.md).

1. Confirm the warehouse is visible in Watch, connection is healthy, capture is
   enabled, and searchable coverage advances. Recording supports questions and
   replay; semantic indexing supports search.
2. Keep visual monitoring paused while asking questions. One continuous visual
   rule occupies the local visual reasoning slot.
3. Run a short warehouse sequence: empty aisle, person in view, forklift in view
   if supported. Let coverage pass the activity and verify search and replay.
4. Keep old hospital rules paused. Create warehouse rules from the new examples;
   do not rename historical medical-cart evidence to imply warehouse activity.
5. Rehearse an actual positive and negative rule window. Do not promise alerts
   for unsupported simulator objects or behaviors.

## The walkthrough

### Watch

Show the live warehouse feed and the advancing indexed coverage.

Say: “This is an RTSP camera from our simulator. The same workflow can take a
network camera feed. Video is recorded and indexed here on the device.”

Point to camera connection, local AI availability and searchable history. An
indexed segment is a video interval, not a count of objects or people.

### Ask

Choose **Summarize this scene**, then **Ask the video**. Replay the inspected
interval. Ask about equipment or people only when their presence is unambiguous.

Use **Recent footage** to choose 1–60 seconds; the default is 3 seconds.
For a quick scene description, try 2–5 seconds. Keep 15 seconds or more when
asking about activity over time. Sampling uses about one frame per second,
capped at 20 frames across the selected interval; a two-second question requests
two frames. Longer intervals provide more context but can miss brief activity
between sampled frames.

Live questions inspect the latest retained interval, allowing five seconds for
recording storage to settle. An already running recording becomes ready as soon
as the chosen interval is verified; a newly started recording waits for actual
footage. Changing the duration leaves capture and indexing running. The answer
shows the precise inspected timestamps.

Say: “The agent inspects recorded footage and gives us an answer we can check
against the exact clip.”

The model can misinterpret distant objects. Review before calling an answer
confirmed. Save useful, verified answers as reports.

### Find

Search **pallets and storage racks** for a static warehouse scene. After a person
appears, try **person walking through a warehouse aisle**. Use **forklift near a
pallet** only if a forklift is actually present. The default window is the last
15 minutes; broaden it through Refine search when needed.

Open **How this was answered**, then play a candidate clip.

Say: “Cosmos Embed represents visual meaning in an index. We search with a
phrase and retrieve relevant intervals with the camera and time attached.”

A ranked result is a candidate to inspect. Use **Ask about this clip** for a
question about a specific retrieved interval.

### Follow

Open a clip and choose **Inspect detected objects**. Compare its boxes, labels
and track IDs against the actual frame. Tracking links recorded observations;
it does not prove identity across cameras.

**Find similar** compares the selected object's appearance with other retained
moments from the same camera. When a detection has no appearance features yet,
VSS prepares crops from retained footage with the local Cosmos Embed model and
caches the features. The first lookup can take around 20 seconds; cached lookups
are faster. Review the ranked clips: similar appearance does not prove identity.

### Monitor

Choose **New monitoring rule**. The current camera is preselected. Examples:

- **Forklift visible** — a clearly identifiable forklift in a sampled frame.
- **Person in aisle** — a clearly visible person, without assuming motion.
- **Aisle obstruction** — an object blocking passage, excluding normally stored pallets.

Choose a condition the scene can actually demonstrate. Review the exact prompt
and rule name before **Activate monitoring**. These visual conditions are model
assessments, not measured safety distances or certified safety alarms.

Say: “We describe the condition and let local visual reasoning examine sampled
windows. When it finds a match, there is footage to review.”

Allow a sampling window plus processing time. Pause the rule after the example
and before asking another visual question.

### Review

Choose **Refresh**, check the rule, camera and time, then **Find footage**. Replay
and verify what matched. Acknowledge or resolve only after reviewing the evidence.
Save a report with notes about what was actually confirmed.

**Show saved reports** reveals retained evidence. Reports open separately so the
workflow stays in place. Earlier hospital reports remain historical examples.
Repeated windows of the same condition are not counts of unique incidents.

Choose **Back to the live scene** for the next walkthrough. Confirm monitoring is
paused. Capture and indexing can stay enabled for the agreed session.

## Verification history

The earlier browser rehearsals verified real question submission, semantic
search, recorded playback, monitoring activation/pause and a positive medical-cart
alert with evidence. They did not qualify warehouse recognition, avatar motion,
multi-camera capacity or a full show-day workload. The October 1 appearance-search
check returned nine ranked moments for Person 523, including earlier and later
moments of the same track, and confirmed a result preview loads. The cached API
lookup took 0.29 seconds; the initial preparation took about 21 seconds.

See [guided workflow receipt](qa/2026-09-30-guided-demo.md) and
[earlier browser rehearsal](qa/2026-09-30-booth-browser-rehearsal.md).


## Start with fresh history

Use **Clear history** in the top bar, or **System → Clear history**. Review the counts, then choose **Clear all previous history**. Wait for **History cleared**; the dialog can close while cleanup continues in the background.

This removes the old indexed moments, completed live recordings, detections/tracks, caption and AI knowledge, retained evidence clips, saved reports and past event states captured by that preview. Cameras, rules, analysis profiles, preferences, cached models and uploaded source videos stay in place. Capture and ingestion keep their current state: a running camera keeps producing fresh history; a paused source stays paused. The open recording fragment, cutoff-spanning intervals and anything newly created or updated during cleanup are retained. Counts can start rising again immediately.

If a step fails, the dialog reports **Some history remains** with the affected step. Use **Review remaining history** to create a new preview and retry. Canceling the confirmation only releases the preview; it does not delete data. Clear history cannot undo a completed reset.
