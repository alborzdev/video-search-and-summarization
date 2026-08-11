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

- Contract SHA-256: `d55420ca0f3da9fc82de4ab6d189df7fd41fff4848053fce5b1963b375546748`
- Receipt SHA-256: `58d02b1aad0b98fdec33824717eb9f59537a3b647b54e1d74b7536aad32fb2dc`
- Semantic actions: 8
- Bounded HTTP requests: 22
- Runtime duration: 10.014 seconds
- Warehouse sample bundle: excluded
- RTSP mutation: not performed
