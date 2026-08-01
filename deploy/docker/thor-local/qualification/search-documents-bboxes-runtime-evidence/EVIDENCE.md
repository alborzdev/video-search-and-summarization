# Evidence state

Status: **candidate planning scaffold only; not runtime evidence**.

The package source-locks the current oracle, acceptance row, integrated
execution bound, local20 fixture, Search profile, and implementation sources.
`plan` verifies those locks and proves that the canonical capability is still
`open_unexecuted` with an empty evidence array. `validate-simulation` verifies
only the shape and internal consistency of a fake transcript.

The following have not been observed:

- a Search service or exact immutable image/model identity;
- an Elasticsearch query, document/index write, or response;
- the required `/api/v1/search/attribute`, `/fusion`, or `/image` endpoints;
- image bytes or a digest for the selected-bbox fixture;
- merge, append, rerank/fallback, fusion, top-k, or object-KNN semantics;
- an invalid-family HTTP rejection;
- actual resource deletion, cleanup-race behavior, or delayed reappearance.

Accordingly, both plan and fake-validation results are non-promoting and report
zero runtime requests/actions. A future authorized runtime collector and the
missing route/image implementation work remain necessary.
