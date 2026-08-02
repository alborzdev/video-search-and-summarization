# Current semantic-executor bindings

This additive package is a deterministic status registry for exactly five
canonical schema-v2 rows in the selected 500-row metadata artifact:

| Canonical capability | Current candidate reality |
|---|---|
| Base chat/report | A concrete full-workflow HTTP predecessor exists, but its namespace cleanup does not delete timestamped report files. The exact-file cleanup successor is a concrete seven-request partial slice and derives a corrected 11-request full envelope; it is not canonically bound. |
| Base HITL | The same invalid predecessor cleanup applies. The exact-file successor derives a corrected 12-request full envelope; it is still only a partial cleanup slice and is not canonically bound. |
| LVS profile | The core validates a 14-action semantic envelope through an injected `SemanticAdapter`. The reviewed successor adds a concrete bounded 14-request LVS HTTP partial candidate: fixture setup is complete, five predecessor actions are partially observed, and eight still require Agent/session/stream adapters. |
| Search profile | A concrete exact-14 numeric-loopback Search/Elasticsearch transport exists, but fixture creation is outside the envelope and operator-attested. It remains non-promoting and unbound. |
| UI video management | Only strict manual-receipt and future-receipt validators exist. There is no browser executor. |

## Canonical boundary

For all five selected rows, the compiler verifies the exact normalized row
SHA-256 and requires:

- `current_state: open_unexecuted` and no evidence;
- `acceptance_readiness.classification: planning_index_only`;
- null execution and cleanup executors, empty collectors;
- an unmaterialized fixture;
- exact request/action bounds of 8, 11, 14, 14, and 11.

Therefore the canonical executor-ready, fully integrated, runtime-evidence,
and promotion counts are all exactly zero. Candidate transport counts are
reported separately and never added to canonical totals.

Twenty locks bind the selected metadata plus the relevant Base predecessor,
Base exact-cleanup successor, LVS core, reviewed LVS HTTP successor, Search
successor, and UI contract artifacts. The compiler reads only bounded,
regular, non-symlink repository files and has no network, browser, Docker,
subprocess, credential, lifecycle, write, or canonical-mutation path.

## Commands

Compile to stdout without changing a file:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-current/compiler.py compile
```

Verify the checked registry is current (the default command):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-current/compiler.py check
```

Run mocked/static tests:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-current/tests/test_compiler.py
```

The checked artifact is descriptive, non-promoting status evidence. It is not
a runtime receipt, integration decision, canonical executor binding, or
authorization to run any candidate executor.
