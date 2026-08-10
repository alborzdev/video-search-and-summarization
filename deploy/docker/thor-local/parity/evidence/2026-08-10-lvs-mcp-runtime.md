# Thor LVS MCP runtime qualification — 2026-08-10

This note retains runtime evidence for the complete NVIDIA VSS 3.2.1 LVS MCP
registration contract and the Thor-local file-tool adapter. The run used an
actual MCP client over the service's SSE transport, not direct Python handler
calls or source-only inspection.

## Transport and discovery

The MCP listener was active only on `127.0.0.1:38112`. A connection to Thor's
non-loopback `10.88.8.175:38112` failed with curl exit 7 and HTTP code 000,
confirming that the unauthenticated legacy SSE transport is not exposed to the
physical network. `/sse` and `/messages` are the intended transport paths;
404 responses from `/mcp`, `/docs`, and `/health` are expected for this SSE
server and are not readiness failures.

An MCP 1.28.1 client initialized a live `/sse` session successfully:

```text
protocolVersion: 2025-11-25
server name:      lvs-engine
server version:   1.28.1
tools/listChanged: false
tool count:       13
```

`tools/list` returned exactly the 13 tools in NVIDIA's 3.2.1 documentation:

1. `health_ready`
2. `health_live`
3. `list_models`
4. `add_file`
5. `list_files`
6. `get_file_info`
7. `delete_file`
8. `summarize_video`
9. `generate_vlm_captions`
10. `generate_captions`
11. `stream_summarize`
12. `get_recommended_config`
13. `get_metrics`

Every tool carried an input schema. The four file-management schemas enforce
the Thor adapter's bounded local contract: normalized relative media-root
paths, UUID identities, no extra properties, and a repeated-ID confirmation
for deletion.

The same session invoked six non-inference tools successfully with
`isError: false`:

- `health_ready` returned `{status: "ready", code: 200}`.
- `health_live` returned `{status: "alive", code: 200}`.
- `list_models` returned exactly
  `nim_nvidia_cosmos3-nano-reasoner_bf16-final`.
- `get_recommended_config` returned `chunk_size: 60` for the same bounded
  300/60/5 request used in REST qualification.
- `get_metrics` returned one 9,021-byte MCP text response.
- `list_files` returned an empty vision-file catalog before the lifecycle.

The canonical JSON discovery/call receipt has SHA-256
`4735679bdc886835e0b4a23e1df8f4a11388b67240f01ada22e61d56099c34f7`.

## Disposable file lifecycle

A generated one-second MP4 fixture was placed temporarily in the configured
read-only host media root. It contained H.264 320x180 video at 5 fps, was
25,342 bytes, and had SHA-256
`c936a41de86b055dcde7df73d50c61383a9d5fec92783ea20aafeaf0db0049d7`.
The MCP client then performed one complete lifecycle in a single initialized
session:

1. `list_files` proved the catalog was initially empty.
2. `add_file` uploaded `vss-mcp-qualification-20260810.mp4` with creation time
   `2025-01-01T00:00:00.000Z` and sensor name `thor-mcp-qualification`.
3. The response returned UUID `b2747c00-be5c-4551-a72c-52e7d064b1f1`, the
   exact 25,342 bytes, `purpose: vision`, and `media_type: video`.
4. `list_files` returned exactly that one UUID and its metadata.
5. `get_file_info` returned the same UUID, filename, byte count, timestamp,
   purpose, and sensor name.
6. `delete_file` was called with identical `file_id` and `confirm_file_id` and
   returned `{object: "file", deleted: true}` for the exact UUID.
7. Both MCP `list_files` and REST `GET /files?purpose=vision` proved the final
   catalog was empty.

The canonical lifecycle receipt has SHA-256
`3ff50fcab11636fbb374e6d6479940254f83124bb6c3c57d9b1cdd944c234e4f`.
The generated source fixture was then removed from the host media root.

A preliminary harness run compared `add_file.bytes` to a stale expected size.
The assertion stopped after a valid upload, and its `finally` cleanup called
the same confirmed `delete_file` tool. The catalog was independently proven
empty before the corrected lifecycle above. This was a harness expectation
error and also exercised the transaction's failure cleanup.

## Negative controls and source verification

Two non-mutating MCP calls returned native tool errors with sanitized content:

- `add_file` rejected `../etc/passwd` without exposing a host path.
- `delete_file` rejected different `file_id` and `confirm_file_id` values
  before any REST deletion.

Both responses set `isError: true` and returned only
`<tool> failed; see the LVS service log for details`. Their canonical receipt
has SHA-256
`e641ce43cecf68301db54654c449cdb6654461e5994b2b4699661419ab997a51`.

The focused LVS source tests covering MCP schemas, file confinement, response
validation, cleanup, SSE bounds, request ownership, and API models also passed:

```text
85 passed, 82 subtests passed in 1.88s
```

This evidence closes the discovery and disposable add/list/info/delete gap in
`api.core.lvs-mcp-doc-13-repo-9`: the source-shipped nine tools plus the four
Thor-local adapters form the exact documented 13-tool surface at runtime. It
does not claim that every inference/stream tool was semantically invoked in
this one run. REST file summarization is retained separately; MCP semantic
summarization, caption generation, and live-stream calls remain bound to their
respective workflow qualifications.
