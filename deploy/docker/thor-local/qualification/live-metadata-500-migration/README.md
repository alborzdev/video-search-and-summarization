# Live metadata 500 migration candidate

This package deterministically stages—but does not apply—the complete five-file
VSS metadata post-state. It is intentionally isolated from the current live
files.

The staged set contains:

- the exact reviewed 500-row official capability ledger;
- the exact reviewed 55-feature aggregate manifest;
- the exact reviewed 55-feature acceptance inventory;
- a live-root-shaped v2 oracle registry with the exact preserved 289-row live
  prefix and exact 211-row planning-only candidate suffix;
- a compact, self-contained strict v2 oracle schema;
- an exact migration proof/schema with source locks, before/after raw and
  canonical SHA-256 values, Git blob OIDs, rollback order, and artifact hashes.

The 211 candidate rows do not claim runtime qualification: 205 remain
`not_qualified`, six external boundaries remain `not_applicable`, and none has
runtime evidence, executors, collectors, materialization, execution bounds, or
promotion authority. The Warehouse sample bundle is excluded.

## Verify

From the repository root:

```bash
python3 deploy/docker/thor-local/qualification/live-metadata-500-migration/compiler.py --check
pytest -q deploy/docker/thor-local/qualification/live-metadata-500-migration/tests/test_compiler.py
ruff check deploy/docker/thor-local/qualification/live-metadata-500-migration/compiler.py \
  deploy/docker/thor-local/qualification/live-metadata-500-migration/tests/test_compiler.py
```

`--write` only regenerates the seven declared outputs in this directory. The
compiler rejects unsafe input paths, symlinked inputs/outputs, non-package
writes, duplicate JSON keys, non-finite numbers, and source/hash drift. It does
not invoke Docker, services, the network, models, host inspection, or Warehouse.

## Not an apply package

Do not copy these five staged targets into their live locations yet. The
current live `capability_oracles.py` compiler only understands the v1 289-row
registry and cannot compile the 211 successor candidates. A separately
reviewed v2 live validator/compiler adapter must land in the same future atomic
commit as any live application. This package neither supplies that adapter nor
creates a Git patch.

See `EVIDENCE.md` for validation results and frozen hashes. `migration.json` is
the machine-readable authority for all source locks and rollback metadata.
