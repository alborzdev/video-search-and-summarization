# LVS/RT-VLM current-contract source-claim layered successor

This read-only successor binds the existing Alerts current-contract,
source-claim repair, and layered-observation packages to the current LVS,
LVS MCP, and RT-VLM cancellation contracts. The predecessor packages and
historical receipts remain immutable.

The allowlist covers exactly three live capability records and their three
oracle records:

- `api.core.rt-vlm-27`, whose identity retains the documented 27-operation
  denominator while its contract records 28 Thor-local operations and the
  exact request-id abort extension;
- `api.core.lvs-17`, whose 18-operation manifest receives its frozen source
  digest; and
- `api.core.lvs-mcp-doc-13-repo-9`, whose 13-tool manifest receives its
  frozen source digest.

The transition also updates the four verifier-derived official source
claim-set hashes affected by those contracts. It preserves every other live
capability, oracle, manifest, and acceptance identity. It adds no runtime
evidence, performs no promotion, and keeps the Warehouse sample excluded.

The focused tests in this directory validate the current 330-declared / 329-
unique REST contract. They do not replay or reinterpret frozen historical
qualification suites whose older denominators remain evidence of their own
predecessors.

All supported commands are read-only:

```bash
python3 compiler.py plan
python3 compiler.py review
python3 compiler.py validate
python3 compiler.py rollback-plan
python3 -m unittest discover -s tests -p 'test_*.py'
```
