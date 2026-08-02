# Search semantic runtime evidence successor

This additive package turns the frozen
`search-semantic-runtime-readiness-successor` boundary into an executable,
authorization-gated Search candidate-evidence lane. It does not change the
predecessor, canonical metadata, acceptance state, or any deployed service.

The default command is inert. Runtime activation requires all of the
following explicit inputs:

- an exact run ID and acknowledgement;
- separate, explicit numeric-loopback Search and Elasticsearch origins;
- a reviewed manifest containing an operator ownership attestation;
- six already-provisioned Elasticsearch documents in the exact run-derived
  namespace plus one non-owned sentinel document.

The fixture must be provisioned before this executor starts because the
selected Search oracle is frozen at exactly 14 requests/actions and contains
no setup action. The receipt says `operator_preprovisioned_attestation`; it
does not claim that the executor created the fixture. This is why even a
complete receipt remains non-promoting.

## Exact execution

The executor performs exactly 14 HTTP requests and 14 action transitions:

1. `POST /_mget` reads six exact `(index, document ID, source SHA-256)` tuples
   and one sentinel. Cleanup authority is registered only after every tuple
   matches and the manifest carries the exact run-ownership attestation.
2. Requests 2–11 call the four canonical Search routes and validate external
   response semantics for direct Search, attributes, fusion, selected-object
   image search, same-object time merging, append/fuse multi-attribute modes,
   rerank-or-fallback outcome, same-video `top_k=1`, and object-level KNN.
3. Request 12 sends `source_type: vss-invalid-search-*` to `SearchInput` and
   requires FastAPI/Pydantic HTTP 422 validation. Because `SearchInput` is
   `extra="forbid"` and `source_type` is a literal, this is rejected before
   the Search handler can issue a backend query or write.
4. `POST /_bulk` deletes exactly the six registered document tuples in reverse
   order. Index deletion, wildcard deletion, and foreign deletion cannot be
   expressed by the executor.
5. After the manifest's bounded 2–30 second delay, a final `POST /_mget`
   requires all six documents to remain absent and the sentinel source digest
   to remain unchanged. Any late reappearance fails cleanup closed.

All HTTP transport uses `runtime-evidence-common`: numeric IP loopback only,
explicit ports, an exact path allowlist, no proxies, no redirects, bounded
request/response bodies, ten-second request timeouts, and a shared exact
14-request budget.

Both image-route actions must carry the exact `ReferenceObject` from the
digest-pinned `thor-search-selected-bbox-v2` fixture. The executor rechecks its
strict base64 image digest and normalized bbox but, matching the shipped API,
sends only selected-object metadata—not raw image or bbox fields—to
`SearchInput`.

The selected schema-v2 500-row metadata set is source-locked. Its Search row
must remain `open_unexecuted`, evidence-empty, executor/collector-null, 14/14,
and carry the exact Search attribute/fusion/image/index/route contract. This
package does not mutate or advance that row.

## Commands

Static plan and fake-only tests (safe by default):

```bash
python3 deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor/executor.py plan
pytest -q deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor/tests/test_executor.py
```

Authorized runtime execution is deliberately not given default endpoints:

```bash
python3 deploy/docker/thor-local/qualification/search-semantic-runtime-evidence-successor/executor.py execute-http \
  --manifest /reviewed/path/search-runtime-manifest.json \
  --run-id RUN_ID \
  --acknowledgement I_ACK_SEARCH_SEMANTIC_RUNTIME_AND_EXACT_OWNED_CLEANUP \
  --search-origin http://127.0.0.1:SEARCH_PORT \
  --elasticsearch-origin http://127.0.0.1:ELASTICSEARCH_PORT
```

The command prints a sanitized receipt to stdout. It never writes a receipt,
starts/stops Docker, downloads an artifact, reads credentials, stages a model,
or changes host configuration. The caller must separately review profile
configuration so the exact namespaced indices are the ones queried by the
deployed Search tools.

## Evidence boundary

The receipt stores response sizes and SHA-256 digests, origin hashes, a
namespace hash, semantic booleans, and cleanup facts. It omits raw response
payloads, URLs, Elasticsearch sources, document IDs, and the namespace.

`rerank_or_fallback_outcome` proves the required externally visible ordering
for the reviewed fixture. The non-streaming Search response does not identify
which internal branch produced it, so the receipt does not claim an internal
trace. Likewise, canonical promotion requires separately reviewed deployed
evidence and an explicit canonical-state migration; this executor never makes
that transition itself.
