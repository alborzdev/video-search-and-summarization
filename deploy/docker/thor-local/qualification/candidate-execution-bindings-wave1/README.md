# Candidate execution bindings: Wave 1 LVS/MCP

This additive package narrows two Metadata-500 candidates from completely
unresolved execution projections to **source-proven static service/profile
wiring** on Thor:

- `manifest-entry.video-summarization-live.05-sse-mcp-server`;
- `manifest-entry.agent-and-mcp-apis.06-lvs-mcp`.

Both resolve to Compose service `lvs-server`, container `vss-lvs`, host
networking, and the source-default profile `bp_developer_thor_full_2d`. The
compiler locks the complete Compose include chain, Thor overlay and wrapper,
profile sources, production LVS sources, the 13-tool manifest, planning rows,
the predecessor registry/Wave 1 artifacts, and the checked-empty authority and
admission boundaries.

## What this does not bind

This is deliberately not an executable or admission-grade binding. The action,
argv, executor, model, fixture, runtime request, cleanup, postcondition
collector, evidence destination, effective resolved endpoint/profile, and
runtime evidence fields remain null or empty. Source defaults such as port
38112 are labeled defaults; wrapper overrides and protected generated runtime
state mean they cannot establish effective deployed values.

The predecessor Wave 1 receipt is observer-only in-process evidence. It did not
open an SSE connection, perform an MCP initialize/session/handshake, observe a
deployed LVS service, use a real video, run VLM inference, or prove Thor
readiness. No authority or completion receipt is consumed here.

## Source contradictions retained as blockers

- Workload unit labels such as `get_lvs_hitl_state` are planning labels, not
  production MCP tool names; no HITL-state MCP tool or completion field exists.
- Unknown-tool dispatch returns ordinary `TextContent` error JSON, not the
  planned JSON-RPC protocol error.
- `summarize_video(stream=true)` is schema-allowed, but its adapter always
  parses the HTTP result as JSON while the route emits SSE.
- File deletion can report success after Elasticsearch collection cleanup
  fails; a future collector must independently prove `default_<file_id>` is
  absent.
- The Wave 1 27-byte text fixture is not a runtime video.
- `thor-local.sh restart` operates the entire stack and is prohibited as a
  candidate-specific executor.
- Candidate authorization cannot imply profile-lifecycle authority. Any future
  bounded action must consume an already-running, separately authorized Thor
  LVS profile and preserve its pre-state; its local model and image identities
  must be bound by the runtime receipt.

## Check

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1/tests
```

`--emit` prints the deterministic overlay to stdout. There is no execute,
write, Docker, socket, network, model, download, or service-lifecycle mode.
The Warehouse sample bundle stays excluded and cloud inference is not required.
