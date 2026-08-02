# Advertised-entry Wave8 + successor-500 source rebase

Rebinds the two Wave8 advertised-entry cases and their two successor-500 subset bindings to the repaired LVS cancellation/cleanup sources and final expected/live ledgers.

## Static contract

Both predecessor packages are frozen byte-for-byte. Case order and subset binding order remain unchanged. Warehouse sample data is excluded. This package is additive and does not edit historical qualification artifacts.

No live MCP/SSE transport, deployed cleanup, inference, or Thor runtime was executed. Runtime evidence, admission, and promotion remain zero.

Run:

```bash
python deploy/docker/thor-local/qualification/advertised-entry-executors-wave8-cancellation-successor/compiler.py --check
python -m pytest -q deploy/docker/thor-local/qualification/advertised-entry-executors-wave8-cancellation-successor/tests
```
