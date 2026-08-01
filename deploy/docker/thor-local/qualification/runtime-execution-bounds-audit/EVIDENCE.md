# Static evidence record

Scope: exact 20 local-runtime planning rows remaining after Warehouse exclusion.

Canonical input:

- path: `deploy/docker/thor-local/parity/capability-oracles.json`
- current raw SHA-256: `c85729f691377f6f3d7e4080458789a9df3d9c394762c5ab20ee81b72a3451c3`
- historical generic-baseline raw SHA-256: `a061b5aca1a27df1e34a8a6480d01843b77609821b93792ed9047c8209ce808f`
- selected oracle count: 20
- selected starting state: 20 `open_unexecuted`, 20 empty evidence arrays
- historical selected bound: 20 `max_requests: 2`, no `max_actions` field
- current selected bounds: exact per-row request budgets plus independent action budgets
- selected materialized executors/collectors: zero
- Warehouse sample bundle: excluded from every case

Static compilation result:

- exact cases: 20
- historical two-request bounds proved inadequate: 20
- current exact integrations verified: 20
- minimum request budget total: 202
- minimum action budget total: 207
- official state promotions: zero
- state/evidence/executor/collector mutations: zero

The committed `verified-integrations.json` is compiler-generated and byte-reproducible. Each entry includes historical and current selected-oracle digests, prior and integrated bounds, derived request/action budgets, expanded-workflow digest, and the exact execution-bound target. No target reaches `current_state`, `evidence`, executors, collectors, fixtures, or cleanup policy.

The adversarial suite covers denominator reorder, exact bound drift, false state promotion, materialized executor drift, unresolved canonical pointers, request-cost understatement, removed actions, duplicate workflow steps, Warehouse reintroduction, duplicate JSON keys, non-finite JSON, schema extension, verification-artifact drift, unsafe repository paths, and forbidden runtime-capable imports.

No Docker call, network request, artifact download, subprocess, host inspection, service lifecycle, or live workflow was performed to produce this record.
