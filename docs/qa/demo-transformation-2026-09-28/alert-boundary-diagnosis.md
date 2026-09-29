# Late-box boundary diagnosis — September 28, 2026

## Repeatable symptom

Two live ten-second windows returned NO while a box was visible near the end
of their retained clips. The fixed-file baseline reproduced both misses with
four frames and the same question: “Is a box visible on the conveyor belt?
Answer YES or NO only.” The empty-belt control also returned NO, as expected.
Initial baseline took 0.756–0.776s per clip and exited 1. Repeating it after the
comparison again returned NO for both positive boundary clips and the control
(0.760–0.985s), exit 1. The red signal is an explicit expected-YES comparison,
not merely successful HTTP status.

## Ranked comparisons and result

1. Missing late input: if frame selection omitted the late box, final-frame
   recognition could succeed while the four-frame clip failed. File decoder
   logs report all four planned frames decoded including final times 7.500s
   and 7.466s. Exact live input tensors were not captured.
2. Time-scope interpretation: if the model treats mostly empty footage as a
   negative, explicit any-frame wording could resolve the fixed-clip mismatch.
3. Small object/edge visibility: if the endpoint box were not recognizable,
   the isolated final-frame question would also fail.

Both final-frame image questions returned YES (0.885–1.275s). Both complete
clips returned YES with only the question changed to:

> Does any frame in this video show a box on the conveyor belt? Answer YES if at least one frame shows a box, otherwise NO. Answer YES or NO only.

This supports time-scope wording as a fix for these **fixed-file cases** and
argues against omission by the file decoder or inability to recognize those
final-frame boxes. It does not identify a mechanism inside the model or prove
that the live decoder sampled identical images.

## Expanded regression

Replayed all nine saved intervals twice with the explicit question, fixed
seed 42 and temperature zero. All 18 answers agreed with reviewed fixture
labels. Each call took 0.883–1.038s. A reusable probe then passed one additional
nine-case run at 0.883–1.055s. Six windows have visible boxes; three negative
labels are based on sampled empty frames, not exhaustive whole-interval
annotation. Do not convert these results into a general accuracy percentage.

No model restart, runtime default, inference budget or continuous stream was
changed. The final core check passed 31 roles with 49.64 GiB available.
The next trial must transfer this exact question to bounded live RTSP at the
candidate ten-second cadence, then inspect event timing, positives, negatives,
cleanup and UI handoff before changing the app default.

## Durable evidence

- [Original baseline](alert-boundary-fixed-probe.json), [repeat](alert-boundary-baseline-repeat.json).
- [Final-frame and wording comparison](alert-boundary-comparison.json).
- [Two complete passes](alert-any-frame-repeated-probe.json).
- [Reusable probe run](alert-boundary-reusable-probe.json), [decoder sampling](alert-boundary-sampling.log).
- [Hashed local fixtures and executable probe](../../../artifacts/demo-boundary-probe-2026-09-28/README.md).
- [Earlier live trial and visual sheets](alert-ten-second-trial.md).

A clearer rule-authoring experience should require a concrete visual condition
and explicit temporal scope when relevant. Do not silently wrap arbitrary
customer conditions in “any frame”: persistence, transitions and sequence
conditions have different meanings. The exact box-presence question is a
candidate example, not a universal prompt replacement.
