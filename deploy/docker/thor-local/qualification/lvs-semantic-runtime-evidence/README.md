# LVS semantic runtime evidence

This package closes the executor-shape gap for
`runtime.agent.lvs-profile`. It binds the current Thor runtime-lane oracle to
an authorization-gated, 14-request/14-action semantic executor and a strict
receipt schema. It does not contain deployed runtime evidence and does not
promote the capability.

The default command is inert:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/lvs-semantic-runtime-evidence/executor.py plan
```

The executor performs no Docker, subprocess, filesystem mutation, network,
download, or service-lifecycle work by itself. Runtime access is possible only
through an operator-reviewed `SemanticAdapter` injected into `run_executor`.
The adapter owns deployed protocol details; the executor owns admission,
ordering, budgets, semantic validation, exact ownership, cleanup, and receipt
sanitization.

## Exact 14-transition envelope

| # | Transition | Required meaning |
|---:|---|---|
| 1 | `capture-pre-state` | run namespace absent; unrelated state captured by digestable value |
| 2 | `discover-five-tools` | exact ordered five-tool catalog |
| 3 | `verify-local-dependencies` | local LVS, RTVI-VLM, Elasticsearch, Kafka, Logstash, and inference ready |
| 4 | `setup-owned-fixtures` | two distinct digest-pinned clips admitted under the exact run identity |
| 5 | `single-video-report` | correlated non-empty one-source report |
| 6 | `multi-video-report` | correlated non-empty two-source report with distinct sources |
| 7 | `start-live-caption` | caption start plus Kafka and Logstash delivery observations |
| 8 | `retrieve-live-caption` | at least one caption correlated to the owned stream |
| 9 | `write-shared-prompt-first` | first prompt write by agent A |
| 10 | `overwrite-shared-prompt-latest` | latest query overwrites the shared prompt |
| 11 | `reject-cross-agent-prompt-visibility` | adjacent agent B cannot see agent A's prompt |
| 12 | `probe-disconnect-cancel-quiescence` | one disconnect, exact cancellation, quiescence, sibling preservation, CA-RAG cleanup support |
| 13 | `cleanup-exact-owned` | delete only the ledger-owned run namespace after quiescence; prove CA-RAG scope absent |
| 14 | `verify-owned-absence-and-restore` | owned reports/stream/namespace absent and unrelated pre-state restored |

Transitions 13 and 14 are reserved atomically by
`runtime-evidence-common.ResourceLedger` before cleanup can mutate state.
Ownership is registered only after transition 4 proves the exact run ID,
resource ID, both fixture digests, and Warehouse exclusion. An ambiguous setup
cannot enter the ledger and therefore cannot trigger deletion.

## Runtime adapter contract

An adapter implements three methods:

```python
invoke(*, run_id, action_id, request) -> {"status", "result_code", "facts"}
cleanup_exact_owned(*, run_id, resource_id) -> cleanup_proof
verify_postcondition(*, run_id, resource_id) -> postcondition_proof
```

Each call consumes one request. `invoke` payloads are canonicalized only for
byte count and SHA-256 evidence. Raw payloads, prompts, media paths, resource
IDs, authorization material, headers, and URLs are not written to the receipt.
The exact resource ID is passed only to the two ownership callbacks.

Cleanup must prove exactly: `disconnect_delivered_once`,
`exact_cancel_accepted`, `quiescent_before_cleanup`, `ca_rag_scope_absent`,
and `only_owned_targets_deleted`. The postcondition proves owned namespace,
report, and stream state absence plus digest equality for unrelated state.

`run_executor` requires a unique plain run ID, the exact acknowledgement in
`contract.json`, two distinct lowercase SHA-256 fixture identities, and an
already-running, separately approved local Thor LVS profile. It never starts,
stops, or reconfigures that profile.

## Focused tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/lvs-semantic-runtime-evidence/tests/test_executor.py
```

Tests use an in-memory fake adapter only. They cover the exact passing
sequence, sanitized receipt, authorization gate, ambiguous-setup no-delete
rule, cleanup after semantic failure, cleanup-proof failure, and fixture
identity validation.
