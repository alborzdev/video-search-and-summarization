# Executable-subset evidence

Status: **two deterministic executable subsets annotated; zero oracle-row
mutation and zero runtime promotion**.

## Exact identities

- Selected set: `thor-vss-3.2.1-metadata-500-staged`.
- Selected descriptor SHA-256:
  `56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9`.
- Selected oracle document raw SHA-256:
  `17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271`.
- Selected oracle document canonical SHA-256:
  `1c2dae973a8ad69b02730f21d1d504fb9f80e3a6200bc98e1f435fad195ef286`.
- Deterministic Wave 8 result canonical SHA-256:
  `a000f8db5b3bcec6f0da50828dcf9e31126655fe0962f964491317c29218c823`.
- Ephemeral fixture SHA-256:
  `8828ea64e48f0b522ee57e9878f1a1dcd41acd430687f223fd1f393603ad6602`.

The exact row bindings are:

| Index | Capability | Canonical row SHA-256 |
| ---: | --- | --- |
| 310 | `manifest-entry.video-summarization-live.05-sse-mcp-server` | `daf6d4a628c8e972d2eb996b3d56f2d6f814d584a378be06f80a3e7a50cc0974` |
| 468 | `manifest-entry.agent-and-mcp-apis.06-lvs-mcp` | `e06850f09ddaadfb6ab40324816f2bff0b19eae5341ec3b7df4e1955f431bc3d` |

The 498-row unannotated partition canonical SHA-256 is
`133610f03b53bdcc447bd5440b955ee8ad159f3fed3b5263daa9bc881b52a84b`.
The complete ordered 500-row hash-list SHA-256 is
`8aa755010f7e40dd045380a652f0f5a7c56b31b86db71c9d6c8baee35ce0157d`.

## Executed observations

Wave 8 executed the production LVS MCP module with exact 13-tool registration,
in-process health dispatch, dependency-error propagation, bounded local file
add/list/info/delete, traversal and symlink rejection, size and UUID rejection,
invalid-metadata rollback, and sanitized public file errors. External action
entry points were guarded, and the temporary fixture was removed.

Focused validation result:

```text
PASS: two Wave 8 executable-subset annotations; 500 oracle rows byte-identical; zero runtime promotions
21 passed
```

## Explicit non-evidence

No SSE or MCP transport/session/handshake, live service, summarization, HITL,
VLM inference, Thor runtime readiness, network, socket, subprocess, Docker,
model, download, credential, Warehouse sample, or canonical metadata mutation
occurred. `execution-receipt.json` and both strict schemas reject contrary
claims.
