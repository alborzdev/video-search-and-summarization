# Ten-second binary alert trial — September 28, 2026

## Question and scope

Can a binary visual rule produce useful replay alerts faster than the app's
30-second narrative-derived cadence? One bounded backend experiment used the
same conveyor replay, four fixed 512×512 frames, 2-second configured overlap,
128-token ceiling, audio/reasoning disabled, and the existing prompt:
“Is a box visible on the conveyor belt? Answer YES or NO only.”

This trial used Alert Bridge directly to vary cadence without changing the
app's enforced profile. No UI default or model memory budget changed. Both
detectors stayed stopped, initial RT-VLM stream and active rule lists were
empty, notifications were disabled, and the persistent 48 GiB guard remained
active. An additional watcher stopped below 48.75 GiB or after 90 seconds from
successful creation. This is a diagnostic backend test, not a repeated complete
UI rehearsal or qualification of other prompts.

## Timing and runtime evidence

- Rule `a82abc1e-5bd6-434b-ab94-b5ebcda403e1`, diagnostic category `box_presence_cadence_qualification`.
- Created `2026-09-29T01:23:07.681048Z`; first response 9.926 seconds later.
- Nine responses: NO, YES, NO, YES, NO, YES, NO, YES, NO.
- Response spacing 9.747–10.239 seconds, with no growing completion lag across these nine windows.
- Last sampled timestamp to logged response: 0.542–0.838 seconds. This is not a kernel inference benchmark or full event-to-screen latency.
- 97 host samples: 49.531–49.763 GiB available. Cleanup completed, remaining rules empty, RT-VLM stream count zero. Boot ID unchanged.
- All 31 core service checks pass after clip inspection, 49.82 GiB available.
- Four corresponding incident records found by exact alertRuleId.
- No ERROR/WARNING lines in the captured Cosmos interval. The metrics endpoint exposes file pending queries, not an observed live queue depth; do not claim direct live queue-depth measurement.

## Visual review changes the decision

Retrieved all nine exact timestamp intervals from the app's evidence endpoint.
For each retained clip, inspected four frames near beginning, one-third,
two-thirds and end. These are reconstructed review samples, **not captured
model input tensors**; clip alignment and model sampling remain possible causes
of discrepancies.

| Window | Model | Visible evidence |
| --- | --- | --- |
| 0 | NO | Box visible near end: discrepancy requiring diagnosis. |
| 1 | YES | Boxes visible. |
| 2 | NO | Box visible near end: discrepancy requiring diagnosis. |
| 3 | YES | Boxes visible. |
| 4 | NO | Four inspected frames show empty belt. |
| 5 | YES | Crumpled box visible; presence supported, no condition claim. |
| 6 | NO | Four inspected frames show empty belt. |
| 7 | YES | Box visible. |
| 8 | NO | Four inspected frames show empty belt. |

Do not report a success/accuracy percentage from this partial ground truth.
The two boundary discrepancies prevent calling this condition reliable. Source
inspection found a frame-cap path in the model adapter, but this run did not
capture effective child-process sampling values or exact input images; no root
cause is established. The next useful comparison is the same retained boundary
windows with captured effective samples and explicit “any frame” semantics,
not another uncontrolled sequence of prompt guesses.

## Decision

Keep the app's 30-second alert default unchanged pending discrepancy diagnosis
and repeated guarded trials. Ten seconds is now a measured feasible cadence for
this bounded binary workload; it is not an adopted or sustained-ready profile.
History/narrative captioning remains at 30 seconds. Diagnostic events are
preserved, not presented as customer incidents.

Evidence: [runtime and cleanup](alert-ten-second-trial.json),
[response log](alert-ten-second-responses.log), [window review](alert-ten-second-windows.json),
[generated incidents](alert-ten-second-events.json),
[frames 0–2](alert-ten-second-frames-1.jpg),
[frames 3–5](alert-ten-second-frames-2.jpg),
[frames 6–8](alert-ten-second-frames-3.jpg).
