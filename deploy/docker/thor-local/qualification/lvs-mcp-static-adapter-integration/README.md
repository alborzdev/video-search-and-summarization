# LVS MCP static-adapter integration

This package is the third deterministic static successor after the immutable
Wave 3, executor-case, and source-contract integrations. It records the four
Thor-local LVS file-management MCP adapters without rewriting historical
receipts or claiming upstream 13-tool parity.

The same live-current successor now also binds the two deterministic offline
MV3DT generator observations into their exact official oracles as non-advancing
static subsets. The immutable predecessor receipts remain unchanged; the live
aggregate is 26 planning bindings plus two offline-tool bindings.

The integration is offline and static. It creates no runtime evidence, makes
no `passed_current` promotion, and keeps the Warehouse sample excluded.

```bash
python3 deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py validate
python3 -m unittest discover -s deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/tests -p 'test*.py' -v
```
