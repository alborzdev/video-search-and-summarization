# Search semantic current-runtime evidence

Status: **passed current; promotion eligible**

The 2026-08-10 Thor run exercised the current VSS 3.2.1 Search backend through
all four canonical routes with the production RT-CV text embedder,
Elasticsearch templates, VST source resolution, and video-analytics frame API.
The run completed in 44 bounded HTTP requests and 10 exact, owned mutations.

Runtime-proven semantics:

- the fixed behavior and raw templates both expose 1,152-dimensional vectors;
- the analytics frame route returned one frame containing two selectable
  bounding boxes;
- two adjacent segments for one tracked object were merged and extended to the
  one-second minimum clip duration;
- multi-attribute append mode returned both expected object identities;
- multi-attribute fuse mode returned both expected object identities with
  playable media metadata;
- both the base Search route and Search-by-Image alias performed object-level
  KNN from the selected object, returned the candidate, and excluded the seed;
- Agent-mode fusion returned exactly the requested top result, while container
  logs independently showed the embed, fusion, and RRF rerank branches once;
- an adjacent invalid source family was rejected with HTTP 422.

Cleanup and non-interference proof:

- the two fixed indices were HTTP 404 before the run;
- each created index UUID and its complete document inventory were matched
  before deletion;
- both fixed indices were HTTP 404 in two delayed post-delete checks;
- the analytics frame query was empty after cleanup;
- the pre-existing embedding index UUID and document count were unchanged;
- all five related container identities, start digests, health/lifecycle
  counters, and OOM states matched before and after;
- no stream, sensor, service lifecycle, or warehouse-sample mutation occurred.

The retained receipt passed its strict Draft 2020-12 schema, a source-lock and
artifact-digest verifier, retention-boundary checks, and 14 offline tests. The
receipt intentionally contains only hashes and semantic summaries; vectors,
prompts, raw API bodies, URLs, and runtime identifiers were discarded.

This evidence closes the backend Search semantic gap. The successor
`ui-search-selected-object-current-runtime-successor` package now also proves
the same selected-object path through the real browser, VST frame, canvas
overlay, and rendered result.

Canonical promotion is retained separately in
`canonical-runtime-evidence.json`. It binds this sealed run to the exact
`runtime.agent.search-profile` capability oracle, fixture digest, assertion
order, and cleanup postconditions without changing the richer qualification
summary above.
