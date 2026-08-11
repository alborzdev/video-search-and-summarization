# Video Analytics and VA-MCP manifest runtime successor

This package binds complete retained Thor runtime evidence to the eight VSS
3.2.1 Video Analytics API manifest rows and the required-local VA-MCP row.

The HTTP evidence covers the exact 56-operation OpenAPI surface, all 40
data-bearing GET families with non-empty semantic fixtures, all eight positive
and adjacent-negative POST workflows, Kafka-backed configuration/calibration,
and the brokerless Kafka boundary. Fresh VA-MCP evidence covers JSON-RPC over
SSE, header sessions, the exact nine-tool inventory, all eight read-only tools,
real local sensors and incidents, and metric probes. `react_agent` was not
invoked.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/video-analytics-va-mcp-manifest-runtime-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/video-analytics-va-mcp-manifest-runtime-successor/tests/test_compiler.py
```
