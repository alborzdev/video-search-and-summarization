# Thor Global Chat sidebar runtime evidence

This package retains a bounded rendered-browser qualification of
`runtime.ui.global-chat-sidebar` against the already-running Thor VSS UI. It
launches three isolated Playwright contexts on numeric loopback and leaves all
server-side state untouched.

The current-profile path proves the exact visible tab set, dark/light theme
switching, sidebar collapse state, one-third to two-thirds resize clamp,
history-folder controls, MP4/MKV upload controls, endpoint/schema/intermediate
step settings, `+ Chat` context chips, and the unseen-context indicator. A
second context changes only `NEXT_PUBLIC_ENABLE_CHAT_TAB` in an intercepted
runtime-environment response to prove profile-controlled legacy/global Chat
coexistence without changing the deployed container. A third context supplies
one valid and one adjacent fallback incident to the compiled Alerts UI and
proves the `Generate Report` action is offered only for the valid incident.

The report context captures the compiled WebSocket frame in browser memory and
suppresses the transport call. It never sends a report request to the Agent and
does not call the Agent `/generate` endpoint. The retained receipt contains
only hashes, counts, booleans, local protocol/scope classifications, and UI
state—not raw endpoints, prompts, payloads, incident IDs, sensor IDs, request
IDs, conversation IDs, or session IDs.

The one-key synthetic profile override causes React production hydration to
recover with reviewed codes 418 and 423 because the intercepted client runtime
flag intentionally differs from the initially rendered page. Those codes are
accepted only in that isolated fixture context. Both live-profile contexts had
zero page errors, console warnings/errors, failing responses, or non-loopback
responses.

```bash
node deploy/docker/thor-local/qualification/ui-global-chat-sidebar-runtime-successor/harness.mjs plan
python3 deploy/docker/thor-local/qualification/ui-global-chat-sidebar-runtime-successor/verify.py
python3 deploy/docker/thor-local/qualification/ui-global-chat-sidebar-runtime-successor/build_official_evidence.py
pytest -q deploy/docker/thor-local/qualification/ui-global-chat-sidebar-runtime-successor/tests
```

An authorized rerun requires the exact acknowledgement, target commit,
numeric-loopback UI origin, installed Playwright module, and browser executable.
The harness prints a sanitized receipt to stdout, creates only temporary
screenshots outside the repository, hashes them, and deletes them before
success.

`runtime-receipt.json` is the complete sanitized run receipt.
`official-runtime-evidence.json` is its deterministic projection bound to the
canonical capability oracle. The verifier fails closed if the receipt,
contract, schema, source locks, runtime identities, evidence, oracle, cleanup,
or target ancestry drifts.
