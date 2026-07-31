# 2026-07-31 static protocol-case contract

Scope: source-only extraction for the seven current non-REST capability IDs.
No container, network data plane, broker, browser session, model, or VIOS
runtime was started or contacted.

The contract is pinned to checkout commit
`ae0fceee78a117a418fb4afb73209156a00a32fc`. It records source byte hashes and
Git blob OIDs, not merely filenames. The bounded vectors are future runtime
recipes and all seven states remain `unexecuted`.

Source extraction results:

- Agent WebSocket: `/websocket`; exact UI `user_message` body and accepted
  inbound response/intermediate/interaction/error types. The server comes from
  the agent runtime dependency, so server auth, close codes, heartbeat, and
  deadline remain explicitly unavailable.
- Alert WebSocket: `/ws/alerts`; ping/pong/status, disabled-service close 1013,
  alert frame fields, callback-before-XACK ordering, and Redis block/count/
  reconnect defaults.
- RT-VLM SSE: `POST /v1/generate_captions`; exact `VlmQuery` bounds, caption and
  usage event fields, `[DONE]`, 409 duplicate-reader window, 5-second send
  timeout, and 1-second ping.
- Kafka NvSchema: default `mdx-alerts`/`mdx-incidents`, protobuf bytes, derived
  key, produce then flush, and the checked-in generated `nv.Behavior`/
  `nv.Incident` descriptor. Proto3 contains no required wire fields.
- Redis Streams: configured `mdx-events`, XADD `key`/`value`/`headers`, bounded
  MAXLEN, XREADGROUP `>`, decode-before-XACK, and pinned 200/100 ms/10000
  settings.
- VIOS live and replay WebRTC: versioned local OpenAPI 1.0.0 plus C++ route
  dispatch; client-offer start, answer, ICE exchange, bearer-secured mutating
  calls, explicit stop, and replay seek. Undefined position units and missing
  timing bounds are not guessed.

Static verification commands and expected result:

```text
python3 deploy/docker/thor-local/qualification/protocol-cases/validate_protocol_cases.py
PASS: seven exact non-REST protocol cases are statically pinned; runtime remains unexecuted

python3 -m unittest discover -s deploy/docker/thor-local/qualification/protocol-cases/tests -v
14 tests; all pass
```

This evidence is not current runtime evidence and must never be cited as a
protocol pass.
