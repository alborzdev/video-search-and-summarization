# Search semantic runtime readiness successor

This additive successor closes the predecessor's three static Search gaps
without rewriting its immutable evidence:

- both the canonical Search profile and the Thor-full profile register exact
  `/api/v1/search/{attribute,fusion,image}` routes while retaining the legacy
  `/attribute_search` and `/embed_search` endpoints;
- the route bindings are checked against the actual NAT input models using a
  Python AST, not inferred from endpoint names;
- a bounded selected-bbox SVG is stored as strict base64 with an exact SHA-256.

It also preserves the exact preceding LVS/RT-VLM current-contract layer while
superseding only that layer's now-stale aggregate API-inventory input with the
reviewed Search totals. The three unrelated LVS/RT-VLM counts stay 18, 13, and
28 respectively.

`/api/v1/search/image` deliberately accepts `SearchInput.reference_object`
metadata (`object_id`, sensor identities, and timestamp), matching the shipped
UI. Raw image bytes and bbox coordinates prove fixture integrity; they are not
misrepresented as HTTP request fields.

Run the deterministic read-only executor and tests:

```bash
python3 deploy/docker/thor-local/qualification/search-semantic-runtime-readiness-successor/executor.py
pytest -q deploy/docker/thor-local/qualification/search-semantic-runtime-readiness-successor/test_executor.py
```

The checked-in receipt is static and non-promoting: it performs no network,
Docker, subprocess, service lifecycle, write, or Warehouse operation. Live
Search/Elasticsearch semantics and cleanup observations remain required.
