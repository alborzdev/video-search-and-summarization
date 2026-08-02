# Metadata-500 activation-rebase successor

This check-only package projects the reviewed
`live-metadata-500-migration-rebase-successor` into a new immutable
Metadata-500 descriptor and a selector rebind. It does not rewrite the
currently applied descriptor or selector and does not provide an apply/write
mode.

The new descriptor retains the existing set ID, `live_ready` lifecycle, mode,
target, and 500-capability / 500-oracle / 55-family counts. It rebinds the
migration-owned document paths to the migration-rebase successor and changes
only the two content hashes that actually differ: the official-capability
ledger and v2 oracle registry. Unchanged manifest, acceptance, and oracle
schema hashes remain identical while their paths move into the rebase package.

The staged immutable target path is hash-addressed by the migration proof:

```text
deploy/docker/thor-local/parity/metadata_sets/sets/
thor-vss-3.2.1-metadata-500-staged-rebase-
771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c.json
```

The projected selector preserves `selected_set`, both set IDs and their order,
and the entire 289 row. Only the selected Metadata-500 row's descriptor path
and raw hash change.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/live-metadata-500-activation-rebase-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/live-metadata-500-activation-rebase-successor/tests

ruff check \
  deploy/docker/thor-local/qualification/live-metadata-500-activation-rebase-successor/compiler.py \
  deploy/docker/thor-local/qualification/live-metadata-500-activation-rebase-successor/tests/test_compiler.py
```

The compiler constructs a temporary isolated metadata repository, resolves the
projected selector/descriptor pair with the real resolver, and runs the
authoritative bundle verifier. Temporary overlay writes never target the
workspace. The compiler has no package or canonical writer.

The rollback contract restores the exact predecessor selector and removes only
the exact new hash-addressed descriptor. The old descriptor remains intact.
Partial or unknown states are rejected, and any future apply requires an
external atomic transition review.

Runtime execution, network access, Docker access, candidate promotion, and the
optional Warehouse sample bundle remain excluded.
