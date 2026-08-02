# Metadata 500 composition successor

This isolated package composes the settled Ledger-500, Oracle-500,
policy-valid Manifest-500 aggregate, and Acceptance-500 successors. It invokes
the raw-hash-locked authoritative official-capability validator with the
projected ledger, manifest, and acceptance inventory and records its exact
result: 500 capabilities, 55 feature families, 126 sources, and 47 source
discrepancies, with zero policy-correct aggregate drift and zero acceptance
coverage gaps.

The composition also proves that the ordered 500 oracle capability IDs equal
the projected ledger IDs and that every oracle retains the exact ledger
binding. The live manifest, official capability ledger, acceptance inventory,
and oracle registry remain separately locked predecessor files; the live
ledger and oracle registry remain at 289 records.

## Honest boundary

This proof is not a live merge or runtime qualification result. Three blockers
remain explicit:

- the four composed metadata successors have not replaced the live predecessor
  files;
- all 211 candidate oracles are non-executable planning records with no staged
  fixture, executor, collectors, runtime evidence, or promotion authority; and
- historical/live oracle registry migration from 289 to the reviewed ordered
  500-row successor remains pending.

Runtime, network, Docker, host, GPU, model, cloud, and Warehouse sample actions
are forbidden. The package only performs bounded, raw-hash-locked reads of
regular non-symlink repository files and writes its own deterministic proof and
exact-value schema.

## Check

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/metadata-500-composition-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/metadata-500-composition-successor/tests/test_compiler.py

ruff check \
  deploy/docker/thor-local/qualification/metadata-500-composition-successor/compiler.py \
  deploy/docker/thor-local/qualification/metadata-500-composition-successor/tests/test_compiler.py
```

`--write` regenerates only `composition.json` and `composition.schema.json`
through same-directory regular temporary files.
