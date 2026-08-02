# LVS MCP candidate workload repair successor v2

Rebinds the four-unit candidate workload and exact 13-tool catalog to the repaired production LVS MCP source and final expected manifest.

## Static contract

The predecessor repair overlay, schema, and compiler are frozen. Workload-unit and tool-catalog order are unchanged. Warehouse sample data is excluded. This package is additive and does not edit historical qualification artifacts.

The cleanup boundary remains unresolved_fail_closed. No workload, transport, inference, runtime evidence, admission, or promotion occurred.

Run:

```bash
python deploy/docker/thor-local/qualification/lvs-mcp-candidate-workload-repair-successor-v2/compiler.py --check
python -m pytest -q deploy/docker/thor-local/qualification/lvs-mcp-candidate-workload-repair-successor-v2/tests
```
