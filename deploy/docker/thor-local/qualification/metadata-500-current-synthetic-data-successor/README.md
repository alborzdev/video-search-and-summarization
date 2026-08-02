# Metadata-500 current Synthetic Data successor

This immutable successor integrates one clean, target-bound Thor runtime aggregate into the selected Metadata-500 state for the four `synthetic-data-tools` capabilities. It produces:

- the unchanged checked 500-row executor-ready oracle document;
- four capability-specific official runtime receipts;
- a 500-row official ledger with only those four capabilities promoted to `passed_current`;
- a 55-family manifest with only `synthetic-data-tools` promoted to `passed_current`.

The compiler rebases the current root 289-row ledger prefix into the selected 500-row ledger and preserves the selected 211-row suffix. It deeply validates the aggregate receipt's clean checkout identity, locked contract/executor/oracle identities, exact ARM64 environment, ordered per-capability results, two-run determinism, adjacent negatives, exact oracle cleanup namespaces, repository cleanup, and zero network/Docker/service/model/download/Warehouse confinement before deriving any official receipt.

Each official receipt has the exact field set consumed by `verify_official_capabilities._validate_bound_runtime_evidence`. Its observation values bind both the aggregate receipt SHA-256 and the canonical per-capability result SHA-256. Assertions and cleanup are emitted in exact future-oracle order and semantics.

No Warehouse sample, network, Docker, service, model, credential, or download access is used. The selected acceptance document is locked and unchanged.

Run the fail-closed check and tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/compiler.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s deploy/docker/thor-local/qualification/metadata-500-current-synthetic-data-successor/tests -v
```

`--write` is reserved for reviewed deterministic regeneration of the oracle, ledger, and manifest after intentional source-lock changes. Checked runtime receipt files are added through reviewed patches.
