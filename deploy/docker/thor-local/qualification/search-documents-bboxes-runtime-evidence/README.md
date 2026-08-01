# Search documents and bounding-boxes runtime-evidence scaffold

This isolated package binds planning requirement
`search-documents-and-bboxes` to required-local capability
`runtime.agent.search-profile` and its exact 14-request/14-action execution
envelope. It compiles an inert plan and validates one closed, plain-JSON fake
transcript. It does not execute or qualify Search.

The exact workflow is:

1. `capture-pre-state`
2. `search-route`
3. `attribute-route`
4. `fusion-route`
5. `image-route`
6. `same-object-merge`
7. `append-multiple-attributes`
8. `rerank-or-fallback`
9. `fuse-multiple-attributes`
10. `same-video-top-k`
11. `selected-bbox-knn`
12. `reject-invalid-index-family`
13. `restore-owned-state`
14. `verify-postconditions`

Every step costs exactly one planned request and one planned action. The fake
receipt records zero runtime requests and actions, 14 simulated requests and
actions, `promotion_eligible=false`, canonical state `open_unexecuted`, and an
empty canonical evidence array.

## Commands

Compile the inert plan:

```bash
python3 deploy/docker/thor-local/qualification/search-documents-bboxes-runtime-evidence/collector.py plan
```

Validate the checked-in plain-JSON fake transcript:

```bash
python3 deploy/docker/thor-local/qualification/search-documents-bboxes-runtime-evidence/collector.py \
  validate-simulation \
  deploy/docker/thor-local/qualification/search-documents-bboxes-runtime-evidence/fake-simulation.json
```

Run the adversarial suite:

```bash
pytest -q deploy/docker/thor-local/qualification/search-documents-bboxes-runtime-evidence/test_collector.py
```

There is no `execute` command. The module imports no HTTP client, socket,
subprocess, Docker, or service-lifecycle adapter. It exposes no caller callback
and writes no file. `validate-simulation` reads a bounded JSON document,
requires recursively exact built-in JSON types, validates a closed schema, and
returns only a non-advancing validation result on stdout.

JSON files are bounded before parsing, reject duplicate keys, and must be
regular non-symlink files. The contract schema pins the exact ordered 16-file
source-lock set, including equality between the fixture binding, fixture lock,
and actual fixture bytes.

## Deliberately unresolved gaps

The official contract requires exact paths `/api/v1/search/attribute`,
`/api/v1/search/fusion`, and `/api/v1/search/image`. The current Search profile
does not register them. Its `/api/v1/attribute_search` and
`/api/v1/embed_search` endpoints are recorded as aliases that cannot satisfy
those exact contracts.

The local20 selected-bbox row contains a frame identifier and coordinates, but
no image bytes or image digest. The fake transcript preserves that absence; it
cannot stand in for object-level KNN evidence.

Future cleanup may delete only exact document IDs registered after successful
create plus exact readback. It is LIFO. Index deletion, ambiguous ownership,
and foreign-resource mutation are forbidden. The adjacent invalid index family
must be rejected with 400 or 422 before any backend query or write.

These gaps, the absence of actual Search/Elasticsearch responses, and the lack
of a cleanup-race/delayed-reappearance observation keep the capability open.
No canonical parity, acceptance, oracle, or evidence file is changed by this
package.
