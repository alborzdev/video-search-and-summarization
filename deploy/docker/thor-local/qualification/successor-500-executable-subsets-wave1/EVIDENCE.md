# Executable-subset evidence

Status: **two deterministic executable subsets annotated; zero oracle-row
mutation and zero runtime promotion**.

## Exact identities

- Selected set: `thor-vss-3.2.1-metadata-500-staged`.
- Selected descriptor SHA-256:
  `4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca`.
- Selected oracle document raw SHA-256:
  `911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021`.
- Selected oracle document canonical SHA-256:
  `540242022bd50ef2d52d5ee610b4b2ae2ada041da4a6603b174c61e80154c2eb`.
- Deterministic Wave 8 result canonical SHA-256:
  `fa3f9188eb30d9f952053c2af626ee73cbb49840fd4843382d111877f47c9a3e`.
- Ephemeral fixture SHA-256:
  `8828ea64e48f0b522ee57e9878f1a1dcd41acd430687f223fd1f393603ad6602`.

The exact row bindings are:

| Index | Capability | Canonical row SHA-256 |
| ---: | --- | --- |
| 310 | `manifest-entry.video-summarization-live.05-sse-mcp-server` | `b523becd0b511f975d38eb3947504e8185c8fe38b12b323838d32b514d664c07` |
| 468 | `manifest-entry.agent-and-mcp-apis.06-lvs-mcp` | `e06850f09ddaadfb6ab40324816f2bff0b19eae5341ec3b7df4e1955f431bc3d` |

The 498-row unannotated partition canonical SHA-256 is
`2ff618019fade2f4bd7ffc5451348ce7087d4e229e9540b40b3c35dec482443c`.
The complete ordered 500-row hash-list SHA-256 is
`a894d73f92b6df3b495c8117a6344e844a071f119ecbc9e61aeb28089a1be34a`.

## Executed observations

Wave 8 executed the production LVS MCP module with exact 13-tool registration,
in-process health dispatch, dependency-error propagation, bounded local file
add/list/info/delete, traversal and symlink rejection, size and UUID rejection,
invalid-metadata rollback, and sanitized public file errors. External action
entry points were guarded, and the temporary fixture was removed.

The receipt also binds static identities for the SSE ownership-cleanup wrapper,
delete/collection-cleanup implementation and regressions, exact Thor wrapper
copy, pinned offline MCP wheel checks, package list, and SSE limit propagation.
Those identities are not live cleanup, image-build, or container evidence.

Focused validation result:

```text
PASS: two Wave 8 executable-subset annotations; 500 oracle rows byte-identical; zero runtime promotions
24 passed
```

## Explicit non-evidence

No SSE or MCP transport/session/handshake, live session cleanup, deployed
delete/collection cleanup, live service, summarization, HITL, VLM inference,
Thor runtime readiness, network, socket, subprocess, Docker, model, download,
credential, Warehouse sample, or canonical metadata mutation occurred.
`execution-receipt.json` and both strict schemas reject contrary claims.
