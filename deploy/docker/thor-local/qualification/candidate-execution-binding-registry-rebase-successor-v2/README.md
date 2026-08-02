# Candidate execution-binding registry rebase successor v2

Rebinds the inert 208-row registry to all eight repaired production overrides and the final expected/live ledgers.

## Static contract

The predecessor registry, schema, compiler, and locator-lock documents are frozen. Binding order plus semantic-base and active-lane locator order are unchanged. Warehouse sample data is excluded. This package is additive and does not edit historical qualification artifacts.

All bindings remain non-authoritative and non-executable. Cleanup executors, rollback contracts, runtime evidence, admission, and promotion remain absent.

Run:

```bash
python deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor-v2/compiler.py --check
python -m pytest -q deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor-v2/tests
```
