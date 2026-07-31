# Exact non-REST protocol cases

This directory is the static, fail-closed contract for the seven non-REST VSS
capabilities currently named by the Thor parity ledger:

- Agent WebSocket;
- alert WebSocket;
- RT-VLM caption SSE;
- Kafka NvSchema publication;
- Redis Streams events;
- VIOS live WebRTC; and
- VIOS replay WebRTC, including one seek.

`protocol-cases.json` pins the exact endpoint or topic, handshake, auth and
headers, wire fields and types, event sequence, terminal and error behavior,
source-defined timing, a bounded loopback-only positive vector, an adjacent
negative vector, mutation ownership, and cleanup. Every case is deliberately
`runtime_state: unexecuted` with no runtime evidence. Static validation is not
a runtime pass.

Every implementation or local versioned-API source has both its current Git
blob OID and its byte SHA-256 recorded. The validator refuses missing,
symlinked, escaping, or changed sources; duplicate JSON keys; any denominator
other than the exact seven capabilities; unbounded vectors; non-contiguous
sequences; non-namespaced mutations; and any attempt to replace `unexecuted`
with a runtime claim. The top-level `contract_set_sha256` binds the complete
reviewed transcription. It does not hash a remote web page.

The Agent route is the one important source boundary: this checkout pins the
deployed `/websocket` route and the exact UI request/inbound-frame contract,
but the server implementation is provided by the agent runtime dependency.
The contract records that limitation instead of inferring server behavior.
Similarly, protobuf v3 has no wire-required NvSchema fields; the positive
fixture's ID and timestamps are test requirements, not a claim that protobuf
marks those fields `required`.

Run the isolated static lane:

```bash
python3 deploy/docker/thor-local/qualification/protocol-cases/validate_protocol_cases.py
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/protocol-cases/tests -v
ruff check \
  deploy/docker/thor-local/qualification/protocol-cases/validate_protocol_cases.py \
  deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py \
  deploy/docker/thor-local/qualification/protocol-cases/tests/test_protocol_cases.py \
  deploy/docker/thor-local/qualification/protocol-cases/tests/test_protocol_case_executor.py
```

No command above starts a container, touches a broker, calls a data plane, or
downloads an artifact.

## Bounded executor

`protocol_case_executor.py` is inert by default. With no arguments (or with
`plan`) it only reads local contracts and prints plans. It has no process,
container, or service-lifecycle primitive. No runtime case was executed while
adding it.

```bash
python3 deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py
python3 deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py \
  plan --case-id protocol-case.redis.events
```

The plan currently reports five activation-ready cases and two blocked cases.
Four ready cases exercise a product protocol. Redis is the fifth, but it is
explicitly `transport_fixture_only` and its evidence always has
`can_advance_capability: false`: XADD followed by XREADGROUP validates the
envelope and Redis mechanics, not that VSS Behavior Analytics emitted it.
Kafka is blocked because producing the fixture from the harness would both
leave a durable record in a pre-existing topic and test the broker rather than
VSS's NvSchema publisher. It needs a bounded VSS product trigger plus an
absent, disposable, namespaced topic that the harness creates, deletes, and
verifies absent afterward. Agent WebSocket remains blocked until a local,
SHA-pinned external server contract also guarantees that disconnect discards
the owned conversation.

Execution is a separate explicit subcommand and requires a request conforming
to `execution-request.schema.json`, including the exact acknowledgement
`I_ACK_VSS_PROTOCOL_CASE_LIFECYCLE_AND_MUTATIONS`. Admission accepts only
numeric loopback IP literals or exact compose-service allowlist names. It
rejects proxies and redirects, endpoint discovery outside the admitted class,
non-loopback ICE candidates, unknown vectors, non-owned namespaces, excessive
bounds, credential-name drift, and evidence paths outside this lane. Do not run
this command merely to inspect a plan:

```bash
python3 deploy/docker/thor-local/qualification/protocol-cases/protocol_case_executor.py \
  execute --request /path/to/operator-reviewed-request.json
```

Runtime evidence conforms to `runtime-evidence.schema.json` and binds the
target commit, whole contract file, contract set, case, vector, request, and
every pinned source. Payloads are represented by byte counts and SHA-256, not
stored verbatim. Evidence records pre-state, strict operation and cleanup
bounds, LIFO cleanup, evidence class, and whether it may advance the product
capability. Evidence files are created exclusively with mode `0600` and are
never overwritten.

## Oracle cross-link

The capability-oracle layer should later cross-link this lane without copying
its prose. For each of the seven capability IDs, record:

1. the repo-relative path
   `deploy/docker/thor-local/qualification/protocol-cases/protocol-cases.json`;
2. the exact whole-file SHA-256;
3. `contract_set_sha256`; and
4. the matching `case_id`.

The oracle validator should verify all four values and require runtime evidence
to name the same case ID, target commit, positive-vector ID, source hashes, and
cleanup result. That prevents an unrelated generic scenario from satisfying a
specific protocol capability.
