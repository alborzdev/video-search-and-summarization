# VSS prerelease 2026-08-02 Warehouse-exclusion successor

This additive static package advances the observed NVIDIA prerelease authority
from `a34c6b040` to `nightly-20260802` / `8db763b46` without rewriting the
immutable 2026-08-01 watchlist and exhaustive denominator.

The exact delta is one commit and one modified path. It adds `phoenix` to the
Warehouse 2D Compose profile so the agent's tracing exporter has a collector.
It changes no REST or MCP API, schema, model, inference path, skill, or stable
VSS 3.2.1 capability. Warehouse is outside the operator-approved scope, the
100 GB sample remains excluded, and no upstream source is ported. Thor's older
Compose layout already selects the Phoenix service with `bp_wh_2d`; that local
equivalence is source-locked here but is not runtime evidence.

Run:

```bash
python3 deploy/docker/thor-local/qualification/prerelease-20260802-warehouse-exclusion-successor/compiler.py --check
pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/prerelease-20260802-warehouse-exclusion-successor/tests
```

The compiler uses only checked-in files. It does not call Git, use the network,
start services, or create runtime evidence.
