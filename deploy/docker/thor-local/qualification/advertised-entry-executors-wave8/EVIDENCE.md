# Wave 8 evidence boundary

## Static identities

`inventory.json` locks the 87-entry advertised gap plan, parity manifest, live
official-capability and capability-oracle ledgers, the original Wave 3 cases,
the complete pre-Wave-8 Wave 7 denominator, and five exact production/test/
deployment sources. Validation requires both selected proposed capabilities and
oracles to remain absent from the live ledgers and their gap-plan entries to
remain open with empty runtime evidence.

## Executed candidate evidence

The checked executor runs production `LvsMCPServer` behavior through an
in-process deterministic FastAPI backend. It verifies the exact tool catalog,
health dispatch, bounded file lifecycle, rejection matrix, rollback, and
sanitized file-tool errors. Socket connection/binding/listening and subprocess
entry points are replaced by fail-closed guards during semantic execution.

This is executable candidate evidence, not runtime evidence. The result schema
requires all live-service and transport observations to remain false and
rejects any promotion or non-empty `runtime_evidence` value.

## Deliberately unexecuted

- SSE connection and message transport
- MCP initialization, session, and handshake
- stdio MCP transport
- Uvicorn or any service lifecycle
- deployed LVS/RTVI services
- summarization or VLM/model inference
- sockets, network, subprocesses, Docker, downloads, credentials
- Warehouse sample data
- Thor runtime readiness

Closing either advertised entry still requires its original live oracle and
reproducible runtime transcript; this package cannot mark it `passed_current`.
Each entry's evidence-scope sentence is schema-pinned to its exact identity, so
free-form or cross-entry wording cannot contradict these retained blockers.
