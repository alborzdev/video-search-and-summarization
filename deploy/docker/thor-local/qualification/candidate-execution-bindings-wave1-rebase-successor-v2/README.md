# Candidate execution bindings Wave1 rebase successor v2

Rebinds the two Wave1 candidate rows to the repaired LVS MCP/server/handler sources and final expected MCP manifest.

## Static contract

The predecessor overlay is frozen and the original two-candidate order is unchanged. The protocol candidate remains byte-locked. Warehouse sample data is excluded. This package is additive and does not edit historical qualification artifacts.

No MCP transport or SSE session was opened. Cleanup execution, runtime evidence, admission, and promotion remain absent.

Run:

```bash
python deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1-rebase-successor-v2/compiler.py --check
python -m pytest -q deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1-rebase-successor-v2/tests
```
