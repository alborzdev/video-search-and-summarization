# Candidate execution bindings Wave 1 rebase successor

This immutable sibling rebases the two LVS/MCP partial binding rows onto the
final execution-binding registry, candidate-admission set, Wave1 observer chain,
and candidate-authority registry. It retains exactly the historical action,
executor, service/profile, cleanup, postcondition, authorization, and runtime
meaning while updating source provenance and the repaired LVS source locks.

The two rows remain source-proven static wiring only. They identify Compose
service `lvs-server`, container `vss-lvs`, host networking, and source-default
profile `bp_developer_thor_full_2d`; effective profile/endpoints, actions,
executors, fixtures, cleanup executors, collectors, runtime evidence, and
admission remain unresolved and fail closed.

The finalized authority registry and signed-receipt set are both exactly empty.
The admission index has zero admitted/executable candidates and its receipt set
is empty. Wave1 remains observer-only with no runtime evidence or promotion.
Consequently this overlay has zero action contracts, executors, cleanup
contracts, evidence contracts, postcondition collectors, admission-grade rows,
runtime-evidence records, or promotions.

Safe read-only validation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1-rebase-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1-rebase-successor/compiler.py \
  --emit
```

There is no write, execute, network, socket, Docker, service-lifecycle, model,
download, credential, or Warehouse-sample mode.

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1-rebase-successor/tests
```
