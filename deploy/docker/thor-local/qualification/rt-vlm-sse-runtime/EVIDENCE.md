# RT-VLM SSE retained evidence

Result: **passed current on Thor**.

The retained loopback-only run used the arm64 NVIDIA RT-VLM image digest
`sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504`
and the locally cached artifact
`ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final`. The live model inventory
reported only `nim_nvidia_cosmos3-nano-reasoner_bf16-final`.

One fixed owned upload of `services/alert/warmup/test.mp4` produced five ordered,
non-empty caption chunks covering 0–10 seconds, one usage event after captions,
and terminal `data: [DONE]`. Request, model, and created identity stayed stable;
the dynamic request ID and caption text were deliberately not retained.

The live schema and HTTP results proved these boundary pairs:

- generation tokens: 16,384 accepted by schema; 16,385 rejected with HTTP 422;
- user prompt: 10,240 characters accepted; 10,241 rejected with HTTP 422;
- system prompt: 10,240 characters accepted; 10,241 rejected with HTTP 422; and
- blank prompt: rejected with HTTP 422 and no SSE stream.

The 28-operation OpenAPI document contained `POST /v1/generate_captions` and did
not contain `/v1/generate_captions_alerts`. Final cleanup returned both asset
counters to zero. RT-VLM remained healthy with zero restarts and no OOM.

- Contract SHA-256: `63dd1f62586621d057c8a962de5dfbef67995f5d9c563cf115311159393dafdc`
- Receipt SHA-256: `a8320800f229625a61fb4381d231fa9dd6cc95464fc0533a37eb7788e7fe9f4d`
- Semantic actions: 8
- Bounded HTTP requests: 22
- Runtime duration: 9.489 seconds
- Warehouse sample bundle: excluded
- RTSP mutation: not performed
