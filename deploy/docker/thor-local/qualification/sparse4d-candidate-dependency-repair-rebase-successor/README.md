# Sparse4D candidate dependency repair rebase successor

This sibling package preserves the historical Sparse4D planning repair while
rebasing its provenance to the final Metadata-500 candidate chain. The
historical `../sparse4d-candidate-dependency-repair/` package is raw-hash and
Git-blob locked and is never modified.

The repair remains exactly one field:

```text
ledger_binding.contract.dependency_capability_ids
runtime.warehouse.profile-mv3dt-pipeline
  -> runtime.warehouse.profile-3d-sparse4d-pipeline
```

The compiler reconstructs that edit from the activation-rebase projected
selector and descriptor, all migration-rebase Metadata-500 members, the final
candidate-approval mapping rebase, and final protocol-v2 artifact. It proves
the Sparse4D candidate, correct Sparse4D dependency, and wrong MV3DT dependency
retain their historical canonical identities. Every other candidate mapping
and approval state remains owned by the unmodified mapping-rebase artifact.

## Boundary

This is an inert planning overlay. It creates no approval, admission, receipt,
executor, runtime evidence, state promotion, service action, network request,
Docker action, model access, host inspection, or canonical metadata mutation.
The operator gate remains unmet and the Warehouse sample bundle remains
excluded.

`--check` is read-only. `--emit` writes only to standard output. `--write`
atomically replaces only this package's `repair.json`; it rejects symlinked or
non-regular output targets and leaves no temporary file behind.

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair-rebase-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair-rebase-successor/tests

ruff check \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair-rebase-successor/compiler.py \
  deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair-rebase-successor/tests/test_compiler.py
```
