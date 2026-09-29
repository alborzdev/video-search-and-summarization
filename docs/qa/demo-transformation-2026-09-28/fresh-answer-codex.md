# Fresh recorded question in Codex browser — September 28

Scope: Home/search-selected warehouse clip, first five seconds, fresh local
visual question through the real UI. No injected response or retained caption.

Question:
> Describe only the person’s visible actions in this clip. Is the box still being held in the final frame?

Observed answer:
> A worker wearing a yellow safety vest and hard hat walks through a warehouse aisle while holding a cardboard box. They approach a green rolling step ladder, pause near it, and continue to hold the box as they stand beside the ladder. The box remains in their hands throughout.

The five-second footage previously played in this same browser shows the worker
carrying the box toward the green steps and holding it at the final frame.
This answer is consistent with that visible sequence. It does not infer placing
the box on a shelf or claim a policy violation. This single success does not
supersede earlier accuracy failures on other prompts.

Timing:
- Browser still showed inspection at 17.635 seconds after submit.
- Completed answer observed at 27.136 seconds. These are observation bounds,
  not an exact browser completion measurement.
- Cosmos query b434b98c-3537-4750-a907-da5064a8a900 logged VLM pipeline time
  17.57 seconds; completion 19:55:45.065 UTC. Agent began video handling at
  19:55:27 UTC. Ten sampled frames, five-second video, reasoning mode false.
- A browser wait for exact text “AI answer” did not match the uppercase rendered
  label. Its timeout was not treated as inference failure or a reason to retry.

Runtime: core status before/after reported 31 roles, no failures, 49.57/49.67 GiB
available. The 48 GiB guard remained active, boot ID
ac75a3b5-980a-41c5-8301-200423326f72. These point samples do not measure peak
memory or qualify sustained ingestion. No budgets or live feeds changed.

[Answer screenshot](fresh-answer-codex.png). No additional saved report was
created for this run. Overall latency/accuracy and live-scene qualification
remain open.

## Repeat with visible service timing

After exposing the existing backend timing fields in the UI, repeated the exact
question through Codex browser. Answer text was identical. The new disclosure
showed total 17.2 s, inspection 17.2 s, answer preparation 0.0 s (rounded to tenths).
Browser answer observed by 17.735 s after submit. No inferred six-to-nine-second
browser overhead from the previous coarse observation is supported by this run.
[Timing disclosure](local-analysis-timing.png).
