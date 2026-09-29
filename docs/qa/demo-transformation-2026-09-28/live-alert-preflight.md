# Live event demonstration — preflight, September 28

Historical preflight. The subsequent [bounded run](live-alert-event-proof.md) succeeded and corrected the first-window timing assumption below.

Status at this checkpoint: **not run**. No continuous rule was created, no incident fabricated,
no external notification configured, and no detector started.

## Confirmed path

The installed custom UI has a direct, coordinated Alert Bridge path:
`AlertRulesWorkspace.tsx` → `/api/vision/live-alert-rules` →
`/api/v1/realtime` → existing RT-VLM. The endpoint checks existing rules,
workload admission and caption ownership, writes a local reservation, and
attempts rollback on failure. GET on the local Alert Bridge realtime catalog
returned success, zero rules. This establishes an available control-plane
route, not successful stream registration, inference, or incident delivery.

The stock alert skill's deployment-mode assumptions do not describe this
custom Thor integration completely; its creation workflow was not executed.
No redeployment is required by the inspected UI code merely to request a
visual rule. Runtime capacity and actual operation still require validation.

The existing source is Conveyor — Recorded Simulation (RTSP Replay),
`6776f3a6-446f-4da8-832e-cfcf4507de8c`. It remains paused. A proposed diagnostic
condition is box presence, explicitly labeled as a replay test, not a safety
incident. Audience and Spark scene/reset alignment remain pending user input.

## Latency limitation identified

`server/vision/liveCaptionProfile.ts` applies `THOR_LIVE_ALERT_PROFILE` with
30-second chunks, two-second overlap, four frames, 512×512 input, no audio or
reasoning, and 128 output tokens. The UI overrides the deployed bridge's
10-second default. A newly collected complete 30-second window plus inference
cannot meet a sub-30-second first-event target. This is a configuration-derived
constraint, not an observed event-latency benchmark.

Do not simply lower the interval: the existing profile documents past queue
backlog with narrative generation. A binary verdict may be cheaper, but it
needs measured per-window latency and queue behavior before a shorter cadence
is qualified. Record source window end, inference completion, event arrival,
and UI visibility separately. Retain an explicit replay label throughout.

## Runtime preflight result

- Before restart: UI cgroup memory 1.891 GiB; host available roughly 49 GiB.
- Ran the documented `python3 tools/dev/ui.py dev` workflow to restart only UI.
  Command completed successfully. One immediate core check reported UI API
  unavailable during initial compilation; subsequent browser and manager checks
  verified recovery.
- After loading System: UI 1.774 GiB; host available 49.02 GiB; all 31 core roles
  pass. Thus restarting the development UI did not recover sufficient useful
  headroom for an additional continuous workload. Avoid repeating this restart
  as a presumed memory fix.
- The 48 GiB diagnostic reserve and model budgets remain unchanged. No kernel
  reclaim, unrelated-stack shutdown, detector startup or alert creation was
  performed.

The current workload admission policy checks VLM readiness, lane ownership,
selected qualification gates and GPU telemetry. It **does not read host
MemAvailable or the guard reserve**. An allow decision must not be used as a
memory-capacity qualification. System now calls this Visual workload scheduling
and labels allow as Lane available, with the limitation visible.

## Required evidence for the next bounded run

1. Establish measured headroom for decoder/stream registration and inference
   with the 48 GiB guard active. Do not infer it from Docker RAM (which omits
   parts of unified GPU/driver usage) or a free Cosmos lane.
2. Select one explicit scene condition, clear camera view and negative/positive
   windows. For Spark, record the scene reset and trigger; for replay, label the
   fixed media and record its phase. Match observed frames to the verdict.
3. Create one local rule through the app, with no external notification, under
   a bounded observation period and known cleanup route. Observe actual event
   delivery, timestamps, UI source binding, and playable evidence.
4. Stop the test rule, verify caption ownership released and source desired state
   still paused; verify the saved evidence/report remains accessible.
5. Only shorten the cadence after measured verdict latency, queue depth and
   memory slope support it. Repeat positive and negative windows, then qualify
   the complete event → review → report → reset presentation.

None of these runtime gates is closed by the service catalog response or the
readiness wording correction.
