# Source claim-hash repair successor

This offline successor repairs exactly six stale
`sources[*].claim_set_sha256` leaves in the official capability ledger. The
values are recomputed with the authoritative verifier algorithm from the
already-reviewed LVS, LVS MCP, and Alerts capability contracts.

The successor preserves every capability and oracle record, the manifest,
acceptance inventory, zero runtime evidence and promotion, and the explicit
warehouse-sample exclusion. It writes only the official ledger and its receipt.

```bash
python3 integrate_live.py plan
python3 integrate_live.py review
python3 integrate_live.py write
python3 integrate_live.py validate
python3 integrate_live.py rollback-plan
python3 -m unittest discover -s tests -p 'test*.py' -v
```

`rollback-plan` is read-only. `rollback` restores the byte-exact locked
predecessor by reversing only the six allowlisted hash strings;
`validate-rollback` verifies that state. Normal validation is read-only.
