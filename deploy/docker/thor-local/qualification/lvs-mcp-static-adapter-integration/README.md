# LVS MCP static-adapter integration

This package replays the immutable third static-adapter successor, then applies
the current LVS/LVS-MCP expected-manifest hashes to the newer live aggregate.
The current delta is exactly two ledger leaves and their six oracle copies; it
preserves every unrelated current record and every historical receipt.

The same live-current successor now also binds the two deterministic offline
MV3DT generator observations into their exact official oracles as non-advancing
static subsets. The immutable predecessor receipts remain unchanged; the live
aggregate is 26 planning bindings plus two offline-tool bindings.

The integration is offline and static. It creates no runtime evidence, makes
no `passed_current` promotion, and keeps the Warehouse sample excluded.
Its reviewed inputs now cover the current LVS/MCP sources, the SSE transport
helper, their focused regression tests, the LVS package-file list, the Thor
image/Compose wiring, and the checksum-locked MCP wheel contract.

```bash
python3 deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py plan
python3 deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py review
python3 deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py write
python3 deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/integrate_live.py validate
python3 -m unittest discover -s deploy/docker/thor-local/qualification/lvs-mcp-static-adapter-integration/tests -p 'test*.py' -v
```

`review` is read-only and prints the exact three-file successor write set with
current and prospective digests. `write` updates the ledger and oracle copies,
keeps the manifest and acceptance aggregate byte-identical, and writes this
package's receipt. The immutable source-contract predecessor and its receipt
are replayed and digest-checked, never rewritten.
