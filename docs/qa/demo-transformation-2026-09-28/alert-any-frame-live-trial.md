# Any-frame condition on live RTSP — September 28, 2026

## Bounded run

Repeated the ten-second binary replay trial with only the condition changed to
the explicit any-frame question from the fixed-clip diagnosis. Alert Bridge
rule `241322b1-4060-4694-a040-d739b92655df`; query
`22b3855c-3640-4881-ad54-759cd8273657`. Diagnostic category
`box_any_frame_qualification`. Source remains the recorded conveyor simulation
published locally over RTSP, not Spark.

Preflight: 31 core roles passed, 49.46 GiB available, guard active, zero active
rules and RT-VLM streams, external notification disabled. Used the existing
four fixed 512×512 frames, 2-second configured overlap, 128-token ceiling,
audio/reasoning disabled. The app profile was not changed.

Nine responses: YES, YES, YES, YES, NO, NO, YES, YES, YES. First at 10.101s
after creation; response spacing 9.934–10.074s; last-sampled-frame to response
lag 0.590–0.663s. Seven incident records match this exact rule ID. This measures
backend response timing, not a full end-to-screen latency percentile.

The watcher sampled host memory 97 times: 49.346–49.815 GiB available. Stopped
after 90 seconds from successful creation, cleanup succeeded, zero remaining
rules and RT-VLM streams, boot unchanged. Final core check after UI/report and
fixed-file follow-up passed all 31 roles at 49.44 GiB. Persistent 48 GiB guard,
model budgets and stopped detectors remain unchanged.

## Visual result and decision

Four reconstructed review frames per exact retained interval show boxes in all
seven YES windows (window 6 only a partial box at the final right edge). Window
4's NO is consistent with empty sampled frames. **Window 5 says NO despite a
visible crumpled box.** The explicit question therefore did not fully transfer
the prior fixed-clip success to this live run.

A fresh fixed-file replay of window 5 returned YES in 1.064s. That comparison
also differs in decoder/input timing and generation settings: fixed-file
probe pinned temperature 0/seed 42; live trial retained service defaults.
Do not conclude that the live decoder is at fault. The next useful diagnosis
needs actual live sampled inputs/effective parameters, or a controlled
comparison that removes those differences, not further unbounded prompt tweaks.

Keep the current app cadence. Two short trials support ten-second throughput
for this binary workload, but do not qualify detection accuracy or sustained
operation. Reconstructed review frames are not captured model input tensors;
negative intervals are not exhaustively annotated.

## UI defect found and fixed

Events from this new rule were labeled as triggered by the old paused rule
because incidentRule matched by camera and guessed rule kind. A regression test
reproduced the wrong association. It now matches only explicit backend/local
rule IDs; unknown or missing IDs cannot inherit another camera rule. Legacy
events without an ID retain their own event description and no guessed rule
association. Unknown rule records are identified explicitly.

The evidence viewer shows the condition recorded with the event. Reports prefer
that snapshot over a possibly edited rule prompt. Long headings and source
names now wrap in the viewer instead of creating horizontal overflow.

Codex browser verified desktop and 390×844 evidence view. Saved report
`a52b7b8c-4995-45e6-8f94-fd09463d29f1`, **Conveyor replay — brief box arrival**,
contains the original condition even though no local rule record exists.
Retained clip played through 0:07 / 0:07 with the arriving box visible; Copy
briefing contains the original condition and event ID. Notes explicitly identify
the diagnostic replay and the other window's miss. Default viewport and Needs
attention filter restored. Browser error/warning log empty.

Sixteen focused tests across ActivityInsightsWorkspace, EventReport and
incidentModel pass; TypeScript passes. No model request is made by report save.

## Evidence

- [Watcher and cleanup](alert-any-frame-live-trial.json), [responses](alert-any-frame-live-responses.log), [windows](alert-any-frame-live-windows.json), [incidents](alert-any-frame-live-events.json).
- [Frames 0–2](alert-any-frame-live-frames-1.jpg), [frames 3–5](alert-any-frame-live-frames-2.jpg), [frames 6–8](alert-any-frame-live-frames-3.jpg).
- [Fixed-file miss replay](alert-any-frame-live-miss-replay.json), [preserved miss fixture](alert-any-frame-live-miss-fixture.json).
- [Corrected desktop viewer](alert-rule-attribution-fixed.png), [mobile](alert-rule-attribution-mobile.png), [saved report](alert-any-frame-live-report.png).

## Later correction: seed configuration

The fixed-file request specified seed 42, but a later [adapter diagnosis](seed-propagation-diagnosis.md) found it was not passed to vLLM SamplingParams. Treat “pinned seed” above as request intent, not verified engine behavior. Temperature and input-path differences still require controlled comparison.
