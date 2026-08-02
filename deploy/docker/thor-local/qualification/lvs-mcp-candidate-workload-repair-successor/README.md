# LVS MCP candidate workload repair rebase

This in-place package rebases the existing inert LVS MCP workload repair onto finalized production, metadata, mapping-v2, and execution-binding identities.

Stable bindings now include:

- the 13-tool manifest raw hash `6768be99…4383c` and canonical hash `939cdcea…ad865`;
- `lvs_mcp.py` at `32a4cc09…c211` and `lvs_mcp_sse.py` at `94306d18…06f8`;
- the projected metadata selector/descriptor and migration→activation receipts;
- mapping-v2 rebase `cb9bea95…4507f`, schema `78c118cc…ccaba`.

The obsolete deferred/null production identity is removed. Both production files are direct source locks. The catalog truthfully distinguishes the only two planned positive tool calls (`health_ready`, `summarize_video`) from eleven catalog-only tools.

The workload remains inert. Its summarize path still has an unresolved fail-closed cleanup blocker: no reviewed candidate-scoped executor removes the stream-settings cache entry and verifies per-source CA-RAG or Elasticsearch state is absent. Runtime evidence, authorization, admission, execution, readiness, and promotion remain zero/false. No network, runtime, Docker, or lifecycle action is performed.

`compiler.py --check` validates the pinned checked-in artifact without executing a workload. `compiler.py --emit` deterministically emits the same canonical contract to standard output and does not write files.
