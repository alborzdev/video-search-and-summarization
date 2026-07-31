# Thor audio-understanding audit — 2026-07-31

VSS 3.2.1 contains native audio-in-video plumbing across RT-VLM, VIOS, the
agent, LVS, and alerts. Native Omni models pass decoded audio to the VLM and do
not require a separate Riva ASR service. Both the service capability flag and
the per-request audio flag must be enabled.

The default Thor lane remains intentionally image-only:

- the local provider is Qwen3-VL-8B through the OpenAI-compatible adapter;
- `ENABLE_AUDIO` and `REALTIME_ALERT_ENABLE_AUDIO` are false; and
- no Nemotron/Qwen Omni model snapshot is staged.

The released and Thor-derived RT-VLM images are already local ARM64 images and
contain the native audio source path. The missing artifact is a pinned Omni
snapshot plus a codec-ready offline derivative; enabling upstream's proprietary
codec install flag during an offline restart would otherwise require network
access. The smallest intended alternate lane uses the RT-VLM
`vllm-compatible` backend with one pinned Nemotron-3-Nano-Omni 30B FP8
snapshot, batch/process/sequence counts of one, and a measured unified-memory
gate before integration.

Thor's agent configuration now propagates `${ENABLE_AUDIO:-false}` through
streaming ingest, both direct video-understanding functions, VIOS clip/URL
tools, LVS, and report generation. A structural regression test covers every
one of those paths. This closes a wiring defect but does not change the current
default from image-only.

Local AAC fixtures can smoke-test media retention, but none contains a tracked,
known spoken phrase suitable for a deterministic transcript oracle. Complete
runtime acceptance therefore also needs a tiny versioned H.264/AAC fixture
with known speech. No warehouse dataset is involved.
