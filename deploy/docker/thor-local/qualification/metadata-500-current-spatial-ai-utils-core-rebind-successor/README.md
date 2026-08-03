# Metadata-500 SpatialAI core producer rebind

This immutable successor rebinds the already executor-ready SpatialAI core
oracles to the current fail-closed runtime producer. The retained rows are:

- `manifest-entry.spatial-ai-utils.01-3d-2d-geometry`
- `manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count`
- `manifest-entry.spatial-ai-utils.05-nvschema-conversion`

The runtime interface locks the current producer contract, contract schema,
executor, result schema, fixture payloads, source controls, action/request
bounds, product-call maps, and Linux/AArch64 Python 3.12 boundary by raw
SHA-256. Its base is canonical commit
`548f7fdda9148b3ee521c09dcdb298309f25fe2b`; raw source locks bind the
same-checkpoint producer changes without claiming a self-referential commit.

The compiler rebases the canonical 289-row prefix into the current SpatialAI
Stage-1 500-row selection. The result is byte-identical: all 500 oracle rows
and all 500 ledger rows are preserved. Entries 01, 04, and 05 remain
`executor_ready`, `open_unexecuted`, and evidence-empty. Entries 00, 02, 03,
and 06 remain `planning_index_only`; external-provider entry 07 remains
unchanged. No runtime evidence or state promotion is performed.

Run the static derivation check and focused tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/compiler.py

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/metadata-500-current-spatial-ai-utils-core-rebind-successor/tests
```

`--write` is reserved for reviewed deterministic regeneration inside this
package. The compiler does not import or execute the runtime producer, use the
network, download data, start services or containers, access models, or use the
Warehouse sample bundle.
