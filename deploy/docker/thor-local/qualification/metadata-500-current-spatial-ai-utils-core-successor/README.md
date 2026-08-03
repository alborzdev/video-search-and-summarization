# Metadata-500 SpatialAI core executor-ready projection

This package is the isolated Stage-1 oracle projection for the three SpatialAI
utilities that are runnable locally on Thor:

- `manifest-entry.spatial-ai-utils.01-3d-2d-geometry`
- `manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count`
- `manifest-entry.spatial-ai-utils.05-nvschema-conversion`

It binds those rows to the runtime producer committed at
`c06932bd641b00ac67df4508e5831644544f9ac1`. The producer's contract, contract
schema, executor, result schema, fixture payloads, source controls, action and
request counts, product-call maps, Linux/AArch64 Python 3.12 target, cleanup
namespaces, and no-external-activity policy are all raw-SHA-256 locked.

The compiler rebases the current canonical 289-row prefix into the latest
checked MV3DT-based Metadata-500 selection and preserves its 211-row suffix.
Exactly three oracle rows change. Each remains `open_unexecuted`, has empty
`evidence`, and becomes `executor_ready` with an exact fixture, executor,
collector, cleanup, workload, source-control, and runtime-namespace binding.
The package-local 500-row official ledger projection is unchanged, proving
that this stage performs no receipt admission or promotion. All 497 other
oracle rows and all 500 ledger rows are preserved.

The four non-core local SpatialAI entries `00`, `02`, `03`, and `06` remain
`planning_index_only`. External provider entry `07` remains byte-semantically
unchanged as `external_optional` / `not_applicable` /
`external_boundary_unexecuted`. No Warehouse sample is needed.

Run the fail-closed derivation check and focused tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-successor/compiler.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-successor/tests
```

`--write` is reserved for reviewed deterministic regeneration inside this
package after an intentional source-lock change. The compiler does not import
or execute the runtime producer, call GitHub, use the network, download data,
start services or containers, access models, or mutate canonical parity files.
