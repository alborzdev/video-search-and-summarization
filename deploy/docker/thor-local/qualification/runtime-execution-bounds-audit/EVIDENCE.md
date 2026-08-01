# Static evidence record

Scope: exact 20 local-runtime planning rows remaining after Warehouse exclusion.

Canonical input:

- path: `deploy/docker/thor-local/parity/capability-oracles.json`
- raw SHA-256: `a061b5aca1a27df1e34a8a6480d01843b77609821b93792ed9047c8209ce808f`
- selected oracle count: 20
- selected starting state: 20 `open_unexecuted`, 20 empty evidence arrays
- selected starting bound: 20 `max_requests: 2`
- selected materialized executors/collectors: zero
- Warehouse sample bundle: excluded from every case

Static compilation result:

- exact cases: 20
- two-request bounds proved inadequate: 20
- minimum request budget total: 202
- minimum action budget total: 207
- official state promotions: zero
- canonical mutations: zero

The committed `proposed-overrides.json` is compiler-generated and byte-reproducible. Each entry includes the selected oracle digest, current bound, derived request/action budgets, expanded-workflow digest, exact execution-bound target, and proposed workload override. No target reaches `current_state`, `evidence`, executors, collectors, fixtures, or cleanup policy.

The adversarial suite covers denominator reorder, selected-oracle drift, rebased false state promotion, materialized executor drift, baseline alteration, unresolved canonical pointers, request-cost understatement, removed actions, duplicate workflow steps, Warehouse reintroduction, duplicate JSON keys, non-finite JSON, schema extension, proposal drift, unsafe repository paths, and forbidden runtime-capable imports.

No Docker call, network request, artifact download, subprocess, host inspection, service lifecycle, or live workflow was performed to produce this record.
