# Question-focused single-clip inspection

## Reproduction and change

The previous two app requests for the first five seconds of Warehouse — Box
Handling inferred “preparing to place” even though the person remains beside
the steps holding the box. Both received the actual final frame. General scene
description instructions competed with the operator's precise question.

Changed only the single-clip prompt in `_inspect_evidence`: identify the clip,
ask the active question, require a direct concise answer from visible frames,
explicit uncertainty when not visible, and no inferred intentions or predictions.
Omitted the original search query when a question is supplied; retained query
fallback when no question exists. Multi-clip prompts, clip bounds, sampling,
model settings and synthesis behavior unchanged. No extra model call added.

Actual-function AST scope probe passed five cases, including single-clip query
fallback and exclusion of a competing search phrase. Updated the corresponding
backend unit expectation; syntax passed. Full backend module suite was not run.
Restarted only Agent and verified API health before fresh app requests.

## Integrated-browser results

Same selected E1, recording interval 0:00–0:05; all requests decoded 20/20 frames
through 4.9 s. Completion times below are observation bounds, not exact latency.

| Question | Previous local analysis | Focused prompt | Complete observed by |
| --- | ---: | ---: | ---: |
| What is visible in the final frame? | 13.4 s | 9.3 s | 14.568 s |
| How does this clip end? | 14.7 s | 8.4 s | 17.186 s |
| What moves in this clip? | Not measured | 11.2 s | 14.557 s |

The first two focused responses omitted the unsupported placement intent. They
still asserted a specific upward gaze toward shelf D, which this review cannot
confidently establish. Therefore these are partial grounding improvements, not
fully verified answers. The movement answer was:

> A person wearing a yellow safety vest and hard hat walks through an aisle
> carrying a box. They approach a green rolling step ladder and pause near it
> while still holding the box.

That description matches the inspected footage and does not claim placement or
future intention. One matching answer is not general accuracy qualification.
Differences across one sample per wording are not a causal proof or a latency
percentile. Keeping the change because it better follows the explicit question,
adds no inference step, and improved focus/pacing in these app checks.

Screenshots: `focused-final-frame-answer.png`, `focused-starter-answer.png`,
`focused-motion-answer.png`. No report saved. Multi-clip contradictions and
other sources remain unqualified; do not generalize this result to them.
