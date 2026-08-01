# Thor UI runtime contracts

This isolated package prepares, but does not execute or admit, the first
post-Wave 11 local UI group:

| Planning requirement | Capability | Oracle |
|---|---|---|
| `ui-alert-api` | `runtime.ui.alerts-tab` | `oracle.runtime.ui.alerts-tab` |
| `ui-search-api` | `runtime.ui.search-tab` | `oracle.runtime.ui.search-tab` |
| `ui-tiny-media` | `runtime.ui.video-management-tab` | `oracle.runtime.ui.video-management-tab` |

The compiler raw-locks four canonical inputs and re-derives each complete
planning-requirement, capability, contract, and oracle digest. It fails unless
all three requirements remain unmaterialized and unexecuted, all capabilities
remain `partial` / `not_qualified`, and all oracles remain
`planning_index_only` / `open_unexecuted` with no evidence.

## Commands

Compile the default inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/ui-runtime-contracts/validator.py plan --pretty
```

Offline-validate a separately collected, sanitized future receipt:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/ui-runtime-contracts/validator.py validate-evidence --evidence /absolute/path/to/ui-evidence.json --pretty
```

Run the mock-only validator tests:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/ui-runtime-contracts/tests/test_ui_runtime_contracts.py
```

There is intentionally no `execute` command and no browser, HTTP, Docker,
socket, subprocess, or process-lifecycle client in this package. Neither
command calls a UI, API, browser, container, or process. The acknowledgement
string in the contract is a future evidence requirement, not approval stored by
this repository and not a callable gate in this package.

## Future-run boundary

A future collector must be separately reviewed and authorized with the exact,
single-use run/authorization identity. It must use four pre-existing, distinct
numeric-loopback endpoints: one UI origin plus the alerts, search, and video
mock APIs. DNS and external network access are forbidden. The package requires
locally generated, run-bound, digested mock JSON and tiny MP4/MKV artifacts,
Thor memory/disk/cgroup gates before and after the run, sanitized traces, and
exact-owned cleanup.

Mock API responses do **not** prove these UI-tab capabilities. Every case
requires a real browser driver, rendered DOM observations, UI actions, trace,
DOM snapshot, and screenshot hashes correlated with bounded mock API exchanges.
The evidence validator still reports only `candidate_evidence_only`; a later
review/integration step must decide admission and is outside this package.

The Warehouse sample bundle is excluded.

## Remaining blocker

No browser driver or runtime collector exists here. Live qualification still
requires a separately approved non-lifecycle collector, an already running UI
origin and three loopback mock endpoints, locally generated fixtures, passing
Thor preflight gates, browser/API evidence, and exact-owned cleanup. Until that
receipt is collected and reviewed, all three canonical rows remain open and no
live acceptance state is advanced.
