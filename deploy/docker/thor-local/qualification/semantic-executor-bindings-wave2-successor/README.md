# Wave-2 semantic-executor candidate status

This additive, static-only package inventories the second wave of candidate
implementations without changing the already-published
`semantic-executor-bindings-current` package or any selected metadata.

| Selected capability | Wave-2 candidate | Honest boundary |
|---|---|---|
| Base chat/report | Concrete corrected 11-request HTTP envelope with report-step-derived exact Markdown/PDF cleanup | The frozen selected row is 8 requests/actions; report-object preexisting absence, canonical binding, and a live receipt are not proven. |
| Base HITL | Concrete corrected 12-request HTTP envelope with the same exact cleanup discipline | The frozen selected row is 11 requests/actions; report-object preexisting absence, canonical binding, and a live receipt are not proven. |
| LVS profile | Concrete 34-request/action NAT WebSocket plus HTTP successor for single/multi reports, prompt first/latest behavior, isolation, and six exact artifact objects | Five-tool runtime discovery, dependency identity, VST digest readback, live captions, cancellation quiescence, report-object preexisting absence, and complete unrelated Agent state restoration remain open; the selected row is 14/14. |
| Search profile | Source-locked proof that the public APIs cannot safely integrate the pre-provisioned fixture into the frozen 14-action executor | No runtime transport is added. Fixed identity, best-effort RTVI-CV registration, index mismatch, and non-exact cross-system rollback preserve the fixture blocker. |
| UI video management | Concrete regular-Playwright executor over an operator-preexisting numeric-loopback CDP browser, with exact owned-resource reconciliation | The Codex Browser plugin is absent, Playwright's transitive module graph is not pinned, the concrete bounds are 40 browser actions and 32 API exchanges rather than 11/11, and no rendered receipt exists. |

## Canonical truth

The compiler source-locks the published five-row registry and requires every
canonical row to remain `open_unexecuted` with null executors, empty collectors,
no fixture materialization, no runtime evidence, and no promotion. Canonical
executor-ready, fully-integrated, runtime-evidence, and promotion totals are all
exactly zero. Candidate counts are separate and do not advance those totals.

`exact_owned_cleanup: true` means only that the candidate derives finite exact
keys, deletes those keys, and verifies their absence afterward. It does not
mean that the same keys were proven absent before execution. For LVS it also
does not prove restoration of complete unrelated Agent state.

The Warehouse sample bundle remains excluded. No package in this registry
downloads, starts, stops, deploys, calls, or mutates it.

## Commands

Compile to stdout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-wave2-successor/compiler.py compile
```

Verify the checked artifact:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-wave2-successor/compiler.py check
```

Run static tests:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/semantic-executor-bindings-wave2-successor/tests/test_compiler.py
```

This registry is descriptive, non-promoting candidate evidence. It is not a
runtime receipt, canonical binding, deployment authorization, or permission to
use credentials or change host state.
