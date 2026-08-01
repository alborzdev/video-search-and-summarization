# Runtime evidence common

This package provides fail-closed building blocks for future Thor runtime
qualification executors. It is a library and static contract, not a runtime
executor. Its default command validates package JSON only. Its optional
`self-test` uses an in-memory fake opener and fake resources only.

It does not create a network opener, use environment proxy settings, resolve a
hostname, call Docker, invoke a subprocess, inspect host state, start or stop a
service, or write an evidence receipt. Importing the module has no operational
side effects.

## Public API

- `LoopbackTarget.admit(origin, allowed_paths)` accepts only an `http` or
  `https` origin with a numeric loopback literal and explicit port. Request
  paths must match an exact allowlist; queries, fragments, percent encoding,
  backslashes, and traversal segments are rejected.
- `BoundedHTTPTransport` requires an injected opener whose
  `proxies_enabled` and `redirects_enabled` declarations are both exactly
  `False`. There is no default opener. Requests and responses are byte-bounded,
  final URLs must remain exact, redirects are rejected, and every returned
  response is closed on success and failure.
- `ExecutionBudget` shares monotonic request and action counters. A cleanup
  callback and its required absence check are distinct transitions. Each
  consumes one action, and both slots are reserved atomically before cleanup
  mutates anything. The per-run ceiling remains 64 actions. The canonical 207
  figure is an aggregate across 20 independent, non-inheriting runs; the
  largest individual canonical run is 14 actions.
- `RunAuthorizationGuard` binds one exact run ID and authorization ID to the
  SHA-256 of one authorization token. Raw authorization tokens are never
  retained in an admitted identity or evidence.
- `ResourceLedger` admits only resources owned by the exact admitted run,
  removes them in LIFO order, passes only the exact registered ID to the
  cleanup and postcondition callbacks, and records only a target digest. It
  stops and retains the top resource for recovery when cleanup or the required
  absence postcondition fails.
- `DigestComparison.compare(...)` records bounded canonical pre/post hashes and
  an exact `equal` or `different` expectation, never the state values.
- `EvidenceRecorder` records fixed labels, result codes, payload lengths, and
  payload SHA-256 values. It cannot record raw payloads, headers, URLs,
  resource IDs, exception text, or authorization tokens.
- `strict_json` and `validate_schema` reject duplicate JSON keys, non-finite
  numbers, invalid schemas, extra fields, and evidence that does not satisfy
  `evidence.schema.json`.

## Future executor integration

A future authorized executor must construct one `ExecutionBudget`, admit an
exact `EvidenceIdentity`, and share that budget with the transport, ledger, and
recorder. It must supply an opener that has already disabled proxy and redirect
behavior; this package deliberately does not construct one. The caller admits
every exact path before transport and registers a resource only after it owns
that exact resource ID.

Cleanup must run before evidence is finalized. A passing result requires no
active ledger entries, passing cleanup action and postcondition records, passing
semantic actions, and passing pre/post comparisons. An authorization for one
executor or run must never be reused for another.

## Static and fake-only checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-evidence-common/common.py check

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-evidence-common/common.py self-test

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/runtime-evidence-common/test_common.py
```

Neither command authorizes runtime evidence collection. `self-test` is only a
deterministic demonstration using `_FakeOpener`, `_FakeResponse`, and an
in-memory set.
