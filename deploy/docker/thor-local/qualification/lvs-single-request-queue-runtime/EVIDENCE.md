# LVS one-video-at-a-time retained evidence

The retained 2026-08-10 Thor run launched two LVS summaries 0.000153 seconds
apart. Both returned HTTP 200, processed one chunk with the exact local model,
and produced nonempty semantic output. Across 130 bounded metric samples,
outstanding work moved from two requests with 20 completed, to one with 21
completed, to zero with 22 completed. The two responses completed in
22.625456 and 32.810724 seconds.

The running RT-VLM identity was independently bound to exactly one
`server.rtvi_vlm_server` process with `NUM_GPUS=1`, `VLM_BATCH_SIZE=1`, and
the `cosmos-reason3` model path. Exact source/image hashes prove that this
configuration exposes one in-flight model slot. The observed
`vlm_queue_time_seconds` delta is retained only as decode-admission telemetry;
it is not misrepresented as time waiting for the model worker.

Both fixed owned uploads were deleted. The complete LVS file list, RT-VLM
asset statistics, LVS readiness/model/metadata, and both container identities
matched pre-state exactly; both containers remained healthy with zero
restarts and no OOM. No summaries, prompts, request IDs, endpoints, headers,
credentials, SDP, or ICE material are retained.

This evidence corrects the historical planning paraphrase that implied an
internal LVS batch queue. The official boundary is one-video-at-a-time
processing with an external queue system required for batch scheduling.

- Contract SHA-256: `2065ca45457490b299bbde56dfa0fd64529cc857f7b5e4a34c34468cc29ab49c`
- Receipt SHA-256: `3359142428b97702c5a1524e66ece01db1adb7dfea13895c99c3dc928c1cc84f`
- Official evidence SHA-256: `7467cc46d9ebe25f6dec89dcacb60da602abce314c28b7c35bb11e13e708e9bf`
- Oracle SHA-256: `4d6fe29f9ca73b5402cbbc0fd9db4e033eaed2c4feeb6756628e17eabaa1925b`
