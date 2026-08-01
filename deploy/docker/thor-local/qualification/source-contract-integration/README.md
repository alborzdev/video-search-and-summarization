# Source-contract second successor

This package deterministically installs the sixteen reviewed source-contract
cases after the immutable ten-case static successor. It first replays and
byte-checks the historical receipt, stages that exact predecessor acceptance
and ledger in a temporary repository, copies the digest-locked assertion
sources, and executes all sixteen cases against that staged state.

The resulting live state has 26 of 110 planning requirements materialized and
executor-ready, leaving 84 open. The oracle compiler exposes 26 bounded static
subset bindings, while all 276 full capability oracles remain
`planning_index_only`. No runtime evidence is created, no full oracle gains an
executor, and no capability is promoted to `passed_current`.

Current outcomes are 15 matches and one honest mismatch in this tranche, or 23
matches and three mismatches cumulatively. The optional Warehouse sample bundle
is excluded.

Run the deterministic validation from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/source-contract-integration/integrate_live.py \
  validate-predecessor
python3 deploy/docker/thor-local/qualification/source-contract-integration/integrate_live.py \
  validate
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/source-contract-integration/tests \
  -p 'test*.py' -v
```

These commands are file-only. They do not use Docker, the network, downloads,
credentials, subprocesses, or environment mutation.
