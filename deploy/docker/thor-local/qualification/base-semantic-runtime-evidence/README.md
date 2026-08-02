# Base semantic runtime evidence

This Warehouse-free package binds `tiny-agent-media`,
`hitl-state-transcript`, and `ui-tiny-media` to their exact canonical
8/11/11 request/action envelopes.

The default command is inert:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/executor.py plan
```

After reviewing one closed request manifest, Base and HITL may be exercised
against an already-running numeric-loopback agent. This command never starts a
service, invokes Docker, downloads artifacts, or writes a receipt:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/executor.py \
  execute-http --manifest /absolute/reviewed.json --run-id RUN \
  --origin http://127.0.0.1:8000 \
  --acknowledgement I_ACK_BASE_SEMANTIC_LOCAL_RUNTIME
```

The executor disables proxies and redirects, caps bodies, binds every POST and
conversation header to the run ID, checks fixed JSON/SSE response assertions,
and emits only digests. Cleanup is admitted only after a run-owned response or
readback, targets only `/static/<run-id>`, and requires a 404 postcondition.
The static DELETE route is a real declared NAT/Base route; because deployed
object-store implementations may not support namespace deletion, this receipt
is deliberately candidate-only and must not be promoted without reviewer proof
that every generated Markdown/PDF key was removed. A 404 for the namespace
alone is not sufficient promotion evidence.

`ui-tiny-media` remains a manual browser-receipt lane: HTTP mocks cannot prove
rendered upload progress, multi-upload, RTSP controls, or confirmation UI.
`validate-receipt` enforces the exact 11-step order and exact-owned cleanup
claims but never advances canonical state.

```bash
pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/tests
```
