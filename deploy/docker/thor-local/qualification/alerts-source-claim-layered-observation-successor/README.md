# Alerts/source-claim layered observation successor

This package closes the aggregate validation gap created when the six-leaf
source-claim repair was layered after the twelve-leaf Alerts current-contract
successor. It does not replace or modify either predecessor package, receipt,
or live ledger.

The observation proves, with exact locked bytes and the two locked transition
algorithms:

1. current official ledger `61c2a4...` reverses by exactly six source-claim
   pointers to the Alerts post-state `fb1638...`;
2. that Alerts post-state reverses by exactly two official-capability pointers
   to predecessor `d1a047...`;
3. current oracle ledger `242145...` reverses by exactly ten Alerts oracle
   pointers to predecessor `4625c8...`.

Both original receipts are validated as a composable chain. Runtime evidence,
`passed_current` promotion, writes, network, Docker, services, and the Warehouse
sample remain forbidden or zero.

All supported commands are read-only:

```bash
python3 compiler.py plan
python3 compiler.py review
python3 compiler.py validate
python3 compiler.py rollback-plan
```

There is intentionally no `write`, `apply`, `rollback`, or execution mode. The
old single-layer Alerts validator remains historically correct for its direct
post-state, but is not a standalone validator of the later layered live state.
