# Thor RT-VLM runtime qualification — 2026-08-10

## Result

The exact NVIDIA VSS 3.2.1 RT-VLM image and local Cosmos3 Nano Reasoner ran
successfully on AGX Thor. The live container used both reference and image ID
`nvcr.io/nvidia/vss-core/vss-rt-vlm@sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504`,
advertised only model
`nim_nvidia_cosmos3-nano-reasoner_bf16-final`, remained healthy with zero
automatic restarts and no OOM, and exposed 28 methods in its live OpenAPI
document. Twenty-seven are NVIDIA's documented RT-VLM surface; the additional
method is Thor's exact-request cancellation extension.

The tracked input was the ten-second H.264 1920x1080 file
`services/alert/warmup/test.mp4`, 2,575,454 bytes, SHA-256
`f2c16bf02e1d43fa52faf902ff981185c62df092189b41c735c5c27647b44205`.
Every uploaded asset owned by this run was deleted by exact UUID. Final asset
statistics were `asset_count=0`, `asset_count_with_storage=0`, and
`aged_out_count=0`.

## Captioning, streaming, and video chat

Post-correction non-streaming captioning split the fixture into two five-second
chunks. The first response described a safety-vested, hard-hatted worker
carrying a box through a warehouse aisle; the second described workers near
shelves D and F. The service reported two processed chunks, seven seconds of
query processing, 456 prompt tokens, 73 completion tokens, and 529 total
tokens.

Normal SSE captioning returned two non-empty timed chunk events and terminal
`data: [DONE]`. A second request with
`stream_options.include_usage=true` returned the two caption events, one usage
event, and `[DONE]`; usage reported two chunks, six seconds, 452 prompt tokens,
55 completion tokens, and 507 total tokens.

Uploaded-file-backed `POST /v1/chat/completions` returned the correct concise
answer that the worker carries a box on his shoulder. The bounded API sweep
also exercised readiness/liveness/startup/model/metrics/asset endpoints; file
upload, listing, metadata, exact-content download, and delete; and schema
limits for prompt length, system-prompt length, and maximum generation tokens.
The documented legacy text-only `/v1/completions` behavior returned HTTP 400.

No RTSP stream was invented. Singular and plural stream inventories were
empty, and no operator-provided `RTSP_SAMPLE_URL` was available. Live-stream
mutation therefore remains separately unqualified rather than being inferred
from file captioning.

## Exact request cancellation repair

The first live negative cancellation probe returned HTTP 500 because only
`rtvi_vlm_server.py` was mounted into the pinned image. That server called
`RTVIStreamHandler.abort_request`, while the running handler and worker
pipeline still came from the stock image and did not implement the method.
The observed exception was:

```text
AttributeError: 'RTVIStreamHandler' object has no attribute 'abort_request'
```

The committed exact-cancellation implementation is one four-file unit. The
official-edge lane now mounts all four files read-only and hash-locks them:

- `server/rtvi_vlm_server.py`:
  `24f6f968cbfac481dd1d310f4fe278b9db2311ec16f3f613c0525e8b77834a0d`;
- `server/rtvi_stream_handler.py`:
  `0a76e5e574d9466662d3424f45fc62ca26313577e87379e25fc4940d1c9bc52d`;
- `vlm_pipeline/vlm_pipeline.py`:
  `76e8f53931f600cc6c8f05cf7d1f752688f6ed1e574fecf911e8b8dfee84df44`;
  and
- `vlm_pipeline/process_base.py`:
  `a56ecdb52ef125b1f0b33b57c8b55a9f4e547a6e53a26bfb6a9d68590b1dea91`.

Host and container SHA-256 values matched for every file. Runtime class
inspection confirmed handler abort, pipeline abort, and exact live-stream
abort methods were all loaded. A nonexistent UUID then returned controlled
HTTP 400 `InvalidParameter`, never HTTP 500.

A real SSE caption request produced request ID
`d0d2c1f0-1f54-47c4-8984-5fdc807a37ac`. Exact DELETE was submitted about
104 ms after inference began and returned HTTP 200 after 12 seconds. The log
proved the request entered failed state, worker output drained, and the handler
recorded `Aborted exact VLM request ... after quiescence`. No caption chunk was
published after cancellation; the SSE connection closed with a failure stub
and its terminal marker. The source file was then deleted with HTTP 200 and
asset statistics returned to zero.

The dependency-free cancellation suite passed all 18 tests, including exact
request scoping, queued-work suppression, quiescent drain, bounded tombstone
cleanup, sibling ownership, live-stream isolation, late-output suppression,
and route separation. All 28 official-edge contract tests also passed.

## Local security and final readiness

RT-VLM has no application-level authentication when the exact local lane
blanks API credentials. Its upstream host publication initially resolved to
`0.0.0.0:8018`. The Thor overlay now replaces that mapping with
`127.0.0.1:8018:8000`. Loopback readiness returned HTTP 200; a request to
Thor's physical address `10.88.8.175:8018` could not connect.

Host-network Agent, Alert Bridge, LVS, and VA-MCP model settings are now
explicitly locked to the local Edge4B and Cosmos3 loopback endpoints in the
official-edge overlay. Bridge-network Prometheus continues to scrape RT-VLM
through the internal Compose service name and port. After isolated recreation,
RT-VLM, LVS, and VA-MCP were healthy, Alert Bridge was running, and the exact
model Thor demo runtime identity/readiness contract passed. A direct local
Edge4B chat request with thinking disabled returned the exact sentinel
`THOR_EDGE_OK` with finish reason `stop`.

At final observation Thor had about 39 GiB available unified memory, no swap,
and 30 GiB free disk. The system cache cleaner was active. No model cache,
VIOS media, analytics index, or unrelated user workload was deleted.
