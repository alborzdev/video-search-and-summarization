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
  deploy/docker/thor-local/qualification/protocol-cases/tests/test_protocol_cases.py
```

No command above starts a container, touches a broker, calls a data plane, or
downloads an artifact. A future runtime harness must use the declared owned
namespaces and cleanup rules and must preserve its structured evidence before
any case can advance.

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
