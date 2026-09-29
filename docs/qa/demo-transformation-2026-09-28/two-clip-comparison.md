# Two-clip comparison — September 28

## Baseline

Two real, adjacent intervals from the ten-second warehouse recording: 0–5 s and
5–10 s. Requested through the app's admitted API: “What changes between the first
and second clip?” This is an API test; the current search UI groups these adjacent
matches, so it does not prove a customer can select these two slices separately.

The [baseline response](two-clip-comparison.json) took 40.178 s: inspection
25.326 s, synthesis 14.667 s. The synthesis summary incorrectly turned stopping
movement while holding a box into “stops holding the box”. Per-clip observations
retained the holding action. The second clip shows ascent onto rolling steps;
its [9.5-second frame](comparison-second-final-frame.png) still shows a box in hand.

## Change

Synthesis now generates only a concise comparison/answer. Per-clip observations
and citations are preserved verbatim from visual inspection; timeline entries
come from the same inspections. This avoids asking a second model to regenerate
all evidence, inferred interpretations, timeline labels and follow-up questions.
The synthesis prompt explicitly distinguishes stopping movement from releasing
an object, but a prompt is not proof of accuracy.

Nine focused backend tests pass, including retained inspection evidence despite
conflicting synthesis fields and coverage of both selected clips. Agent-only
restart applies the source change; model budgets, frames and guard are unchanged.

## Post-change result

The [identical repeated request](two-clip-comparison-compact.json) took 30.762 s:
inspection 25.805 s, synthesis 4.809 s. Compared with baseline, synthesis saved
9.858 s and end-to-end time saved 9.416 s. These are individual samples, not a
latency distribution or proof of a general speedup.

The summary now preserves holding the box in both clips and distinguishes stopping
near the ladder from climbing onto it. Original observations are unchanged and
correctly associated with E1/E2. The second original observation still says “to
place the box”, which infers purpose; broader visual accuracy remains open.

The result still exceeds 30 seconds. Sequential visual inspection dominates the
remaining delay; this flow does not meet the demo pacing criterion. Progressive
results or a separately qualified inference improvement remain needed. No new
concurrent GPU workload was introduced to force a faster measurement.

The core status after the check is recorded in
[two-clip-runtime-status.txt](two-clip-runtime-status.txt). This test does not
qualify live ingestion, multiple sources, or the selection UI for these slices.
