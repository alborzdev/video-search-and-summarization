# Evidence state

- Browser implementation: concrete Playwright `connectOverCDP` client.
- Browser plugin in this Codex session: absent; regular Playwright fallback is
  recorded in the contract.
- Static source locks: all 22 declarations, including the shared chunked-upload
  implementation, exact-success lifecycle helpers, and deployed UI/HAProxy
  topology, are verified by `executor.py plan`.
- Browser/API execution: not performed.
- Runtime receipt count: zero.
- Tool provenance: selected Node and Playwright entry files plus the complete
  `playwright` and `playwright-core` package trees are digest-pinned; matching
  package versions and their direct dependency edge are required.
- Canonical binding: false.
- Executor-ready: false.
- Promotion eligible: false.
- Warehouse sample: excluded.

Passing mock tests prove authorization ordering, manifest confinement,
subprocess-output sanitization, strict candidate-receipt validation, and the
absence of browser-launch primitives. Adversarial helper tests reject partial,
failed, unknown, missing-status, and identity-mismatched HTTP-200 lifecycle
responses. Static harness assertions cover bounded JSON parsing, exact
success/identity enforcement, preservation of empty-sensor identities, the
175+45+20-second workflow/cleanup/parent deadline split, AbortSignal-bound VST
and Agent calls, and the exact irreversible-warning observation.
The gated browser client is now capable of proving two ordered chunks per
fixture and byte-exact browser-side `send(FormData)` media payloads without
depending on CDP `request.postDataBuffer()`, which Chromium does not retain for
these 10 MiB multipart XHRs. No live receipt exists, so these capabilities
remain unexecuted and do not prove a rendered deployment.
