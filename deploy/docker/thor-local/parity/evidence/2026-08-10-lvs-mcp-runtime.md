# Thor LVS MCP runtime qualification — superseded evidence note

The exploratory 2026-08-10 narrative has been superseded by a bounded,
machine-verifiable 2026-08-11 qualification package:

- `deploy/docker/thor-local/qualification/lvs-mcp-current-runtime-successor/runtime-receipt.json`
- `deploy/docker/thor-local/qualification/lvs-mcp-current-runtime-successor/verify.py`
- `deploy/docker/thor-local/qualification/lvs-mcp-current-runtime-successor/official-runtime-evidence.json`
- `deploy/docker/thor-local/qualification/lvs-mcp-current-runtime-successor/canonical-runtime-evidence.json`

The sealed run used an actual MCP 1.28.1 client over numeric-loopback SSE. It
initialized protocol version `2025-11-25`, discovered exactly the 13 VSS 3.2.1
LVS tools with input schemas, passed 11 non-inference/readback/lifecycle calls,
and observed two expected sanitized file-tool errors. A generated one-second
H.264 fixture completed an `add_file` / `list_files` / `get_file_info` /
confirmed `delete_file` lifecycle.

The verifier proves the complete MCP and REST file catalogs and the complete
host media-root inventory match pre-state, the owned asset is absent, the LVS
container identity and restart state are unchanged, and no fallback deletion,
service lifecycle action, stream mutation, inference call, or Warehouse sample
operation occurred.

This retained note intentionally contains no raw asset identity, filename,
sensor name, host address, session detail, path, or response. The four
inference/stream tools were discovered but not semantically invoked by this
receipt; their behavior remains owned by the separate summarization,
captioning, and live-stream qualifications.
