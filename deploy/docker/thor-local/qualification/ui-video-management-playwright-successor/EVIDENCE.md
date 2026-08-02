# Evidence state

- Browser implementation: concrete Playwright `connectOverCDP` client.
- Browser plugin in this Codex session: absent; regular Playwright fallback is
  recorded in the contract.
- Static source locks: verified by `executor.py plan`.
- Browser/API execution: not performed.
- Runtime receipt count: zero.
- Tool provenance: selected Node and Playwright entry files are pinned; the
  transitive Playwright module graph is not yet pinned.
- Canonical binding: false.
- Executor-ready: false.
- Promotion eligible: false.
- Warehouse sample: excluded.

Passing mock tests prove authorization ordering, manifest confinement,
subprocess-output sanitization, strict candidate-receipt validation, and the
absence of browser-launch primitives. They do not prove a rendered deployment.
