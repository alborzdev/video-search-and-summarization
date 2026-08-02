# Advertised-entry executors: Wave 8

This isolated package upgrades exactly two existing source-only candidates to
an executable, offline subset:

- `manifest-gap.video-summarization-live.05-sse-mcp-server` — `SSE MCP server`
- `manifest-gap.agent-and-mcp-apis.06-lvs-mcp` — `LVS MCP`

The executor imports the digest-locked production `LvsMCPServer` from
`services/video-summarization/src/lvs_mcp.py` together with its digest-locked
`lvs_mcp_sse.py` session-cleanup dependency. Because the checkout does not
contain the MCP Python package, it supplies only the registration record types
needed during import. The actual production tool catalog, validation, file
opening, rollback, error sanitization, and in-process `httpx.ASGITransport`
dispatch execute unchanged.

The deterministic backend is an in-process FastAPI application. The bounded
fixture exists only inside an executor-owned mode-0700 temporary directory and
is removed before a successful receipt is emitted. The probe covers:

- exact registration of all 13 production tools;
- ready/live dispatch and dependency-error propagation;
- add/list/info/delete of one bounded local file;
- traversal, absolute-path, missing-file, leaf/directory-symlink, oversize,
  unknown-argument, nil-UUID, and mismatched-delete-confirmation rejection;
- rollback after invalid upload metadata; and
- sanitized public errors for file tools.

The live denominator also source-locks the focused SSE ownership-cleanup and
delete/collection-cleanup regressions, `via_stream_handler.py`, both relevant
Compose overlays, the Thor derivative Dockerfile, and the service package list.
Static checks require the exact offline `mcp==1.23.0` wheel verification and
wrapper-copy wiring. This does not claim that an image was built or a deployed
SSE/delete-cleanup transaction was observed.

## Commands

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave8/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave8/tests
```

Use `--list` to print the two exact entries or `--case <entry-id>` for a
single-entry human-facing receipt. Full `--check` output is validated against
`result.schema.json`.

## Qualification boundary

Every result is `candidate_executable_subset_non_advancing`, has
`runtime_evidence: []`, and has `official_capability_effect:
none_candidate_only`. This package does not edit the acceptance inventory,
official-capability ledger, capability-oracle ledger, or any predecessor.

The `SSE MCP server` entry receives only shared production server construction,
tool-registration, and tool-dispatch subset evidence. No live SSE connection,
MCP transport, MCP session or handshake is executed. Neither entry proves a
deployed LVS service, summarization, VLM inference, service lifecycle, or Thor
readiness. Live transport-session cleanup and deployed RT-VLM/Elasticsearch
delete cleanup remain explicit blockers.

The executor has no socket-connect/bind/listen path, subprocess, Docker,
download, credential, caller-supplied callback, Warehouse sample, or retained
file-write path. Internal fixed FastAPI route functions and production MCP
registration closures are not caller-supplied callbacks.
