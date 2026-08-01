# Remaining API and deployment candidate workloads

This planning-only package turns the 41 API and 19 deployment entries from the
locked 211-row candidate artifact into bounded workloads consumable by a future
`capability_oracles` successor. It does not edit or qualify the official
capability ledger, oracle ledger, protocol cases, wrapper, or runtime.

API workloads partition every advertised literal into exact operation or MCP
tool units. Compound literals enumerate every required operation. Each row
records four phases, per-unit request caps, setup/cleanup overhead, the checked
arithmetic total, and a maximum action count. The inventory contains 134 API
units across 41 candidates.

Deployment workloads contain ordered, literal-specific graphs: preconditions,
bounded actions, readiness observations, an adjacent negative, cleanup, per-
action request caps, calculated request total, and maximum actions. The
inventory contains 58 actions across 19 candidates; there is no generic
deployment default.

All rows are candidates only. Runtime evidence is empty and state promotion is
forbidden. The optional Warehouse sample bundle is excluded while custom-data
Warehouse planning remains in scope. The three external workloads (two Helm
rows and FRAG retrieval) are non-activating with zero requests and zero actions.

Validation from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/remaining-entry-workloads/compiler.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/remaining-entry-workloads/tests
```

`--write` deterministically regenerates only `workloads.json`. The compiler
performs no service, network, Docker, host, model, or runtime operation.
