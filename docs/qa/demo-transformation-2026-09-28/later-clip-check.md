# Later warehouse interval — September 28

Codex integrated browser; source scoped to Warehouse — Box Handling.

- `person climbing the green steps` returned zero results on two attempts.
- `person climbing a ladder` returned one semantic match at 0:05 into recording,
  labeled five seconds. Playback showed the person ascending the green steps
  and ending on the platform near shelf E. This is a wording-sensitive retrieval
  miss, not proof that the later footage is missing. Root cause remains open.
- Fresh question: “How does the person’s position change during this clip?
  Describe only visible movement and where the person is standing in the final
  frame?”
- Answer: “The person climbs a green rolling step ladder toward shelf E, holding
  a box. In the final frame, they stand on the top platform of the ladder,
  positioned near shelf E, still holding the box.” The movement and final
  position agree with inspected footage. This narrow check does not establish
  general temporal or safety reasoning reliability.
- Local analysis reported 12.4 seconds. Completed answer observed by 17.033 s
  after submit; observation bound, not exact browser completion timing.
- Core before/after: 31 roles, no failures, 49.51/49.71 GiB available. No guard,
  model budget or live-feed changes. No report saved for this question.

Fixed misleading empty-state instructions: zero-result searches no longer say
“Play a clip.” They explain that no playable match does not establish absence
and suggest a shorter main-action description or broader filters. Repeated the
actual failing query to verify this rendered state. Eighteen workspace tests and
app TypeScript passed; retrieval behavior itself has not been changed.

Evidence: [final frame](later-clip-final-frame.png),
[answer](later-clip-answer.png), [empty state](search-empty-guidance.png).

## Follow-up: scoped discovery cutoff fixed

Read-only agent API probes at min_cosine_similarity 0.0 returned these actual
scores for the same recording (no critic or LLM query planner):

| Query | Later interval, 0:05–0:10 | Earlier interval, 0:00–0:05 |
| --- | --- | --- |
| person climbing the green steps | 0.12 | 0.03 |
| person climbing a ladder | 0.21 | 0.10 |

The later interval ranked first for both. Scoped search first required 0.25,
then retried at 0.15; all-source search already used 0.12. Thus the UI request
cutoff, rather than a missing interval or post-retrieval filter, explains the
observed miss. Unified the scoped fallback with the existing all-source 0.12
constant. The stricter first request remains. No query rewriting, fabricated
matches or extra model stage was added.

A regression test models a 0.12 candidate at the real workspace request seam:
it failed before the change and passes afterwards. All 19 workspace tests and
app TypeScript passed. Re-ran the original full query in the Codex browser;
it now returns the later five-second clip, still labeled Semantic Match.
[Fixed original query](search-scoped-cutoff-fixed.png).

This resolves this exact miss; changing the discovery cutoff can admit weaker
matches, so reviewing footage remains necessary. It does not qualify retrieval
precision/recall across a representative multi-industry dataset.
