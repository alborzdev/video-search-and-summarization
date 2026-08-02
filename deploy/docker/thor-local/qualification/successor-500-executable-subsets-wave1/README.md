# Metadata-500 executable-subset successor: Wave 1

This package binds the Wave 8 production-code executable subsets to exactly two
planning-only rows in the selected Metadata-500 oracle set:

- `manifest-entry.video-summarization-live.05-sse-mcp-server`;
- `manifest-entry.agent-and-mcp-apis.06-lvs-mcp`.

The predecessor Wave 8 executor imports the production `LvsMCPServer`,
registers its exact 13-tool catalog, and exercises bounded health and file
operations through an in-process ASGI application. Its fixture exists only in
an executor-owned mode-0700 temporary directory and is removed before the
receipt is accepted. The rebase additionally binds the source-locked SSE
session-cleanup and delete/collection-cleanup implementations, their focused
regressions, and the Thor packaging/limit wiring without relabelling them as
live observations.

## Successor shape

The selected schema-v2 document remains byte-for-byte unchanged. Adding an
unknown property to either oracle row would invalidate that schema, so
`successor-capability-oracles.json` is a separate, reconstructable annotation
index. It binds each annotation to:

- the selected Metadata-500 descriptor;
- the exact oracle index, capability ID, and canonical row hash;
- the deterministic Wave 8 result hash;
- the ephemeral fixture identity, matched assertions, and retained blockers;
- the checked execution receipt.

The compiler proves all 500 oracle rows are identical to the selected document,
exactly two are annotated, and the remaining 498 form an exact ordered digest
partition. The selected metadata files are never written.

The selected bundle is the activation-rebase projection: the compiler resolves
its projected selector and immutable descriptor in a private temporary overlay,
without changing the canonical selector or descriptor. It also derives a
result directly from the current Wave 8 inventory, whose live ledger/oracle
locks now match the separately pinned live identities. The contract directly
pins both live identities, the migration-rebase oracle document, projected
selector and descriptor, and the current protocol-v2 artifact and schema.

## Run

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/successor-500-executable-subsets-wave1/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/successor-500-executable-subsets-wave1/tests
```

`--emit receipt` and `--emit successor` print freshly generated artifacts to
standard output without changing files.

## Non-promotion boundary

This tranche records executable-subset evidence only. Both source oracles keep
`current_state=open_unexecuted`, `runtime_state=not_qualified`, empty
`evidence`, `can_promote_runtime_state=false`, `executor_ready=false`, and an
unmet operator-approval gate.

The SSE row still lacks a live SSE connection, MCP transport/session/handshake,
live transport-session cleanup, deployed LVS readiness, and Thor runtime
evidence. The LVS-MCP row still lacks MCP transport, deployed delete/collection
cleanup, live LVS, summarization/HITL/video-identity behavior, VLM inference,
and Thor readiness. None of those gaps can be inferred from the in-process or
source-locked subsets.

There is no network, socket, subprocess, Docker, service lifecycle, model,
download, credential, retained-write, or Warehouse-sample path.
