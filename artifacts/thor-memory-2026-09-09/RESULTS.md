# Qualification results — 2026-09-09

The user-authorized memory experiment progressed from a clean baseline to all 33 full-profile service roles, keeping the exact local models. It established a bounded working configuration with about 41 GiB available after testing and a 40.204 GiB measured minimum after the final LVS configuration was applied. Host-wide available RAM is the relevant unified-memory measure; Docker and GPU process memory overlap and must not be summed.

## Stages

| Stage | Available GiB |
|---|---:|
| Initial VSS stopped, before reclaim | 88.431 |
| VSS stopped, after one-time reclaim | 111.343 |
| Five infrastructure services | 108.246 |
| Supporting services, both CV workers, media, UI and observability | 95.393 |
| Add Cosmos | 63.470 |
| Add Nemotron 32K/2 GiB, warmed | 54.283 |
| Add batch-2 Embed | 45.303 |
| All 33, original LVS pools | 42.243 |
| Repeated summaries, original LVS pools | about 38.95 |
| All 33, LVS capped at two concurrent streams, repeated summaries | about 43.7 |
| Final configuration, live workloads minimum | 40.204 |
| Final workload cleanup and one idle reclaim | about 41.4 |

These samples are measured at different times with unrelated desktop applications left running. Differences are approximate incremental footprints, not precise per-container allocations.

## Functional evidence

- `combined-nemotron-32k.json`: arithmetic, actual tool call, 25,376-token prompt, two passes each. Cold compilation overhead is recorded separately from warm latency.
- `combined-agent-probe.json` and `.log`: actual `vst_video_list` execution and a final answer based on its returned catalog. Missing timelines in old catalog entries caused retries; old sources were preserved.
- `combined-ingest-probe.json`: unique VIOS upload, five actual embedding chunks, indexed relevant results, negative unrelated query, successful deletion. A second unique receipt demonstrates thumbnail HTTP500 separately.
- `combined-lvs-probes.json`: final two-stream pool; three fresh 25-second summaries with five chunks, positive summary/aggregation tokens, owned-file cleanup.
- `combined-live-probe.json`: one 1080p10 warehouse source, actual CV detections in Elasticsearch, 12 nonempty SSE caption events, successful overlapping Agent request, five live search results, successful scoped deletion of 664 generated documents.
- `live-first-run.json`: additional 90-second live run, 18 caption updates; test harness incorrectly parsed an empty successful stop response, but source cleanup succeeded. This harness defect was corrected for the final pass.
- `combined-memory.jsonl`: one-second host samples through the trial. No 36 GiB stop or thermal telemetry stall occurred.
- `final-owned-resource-state.json`: both CV workers have zero streams; Embed/VLM live inventories and LVS file catalog are empty again.
- `final-index-cleanup-check.json`, `owned-lvs-index-removal.json`: no owned documents remained; six empty indexes created solely for these LVS tests were explicitly removed afterward.
- `manage-start-check.log`: idempotent candidate start succeeded, all 33 roles checked.

## Fixes necessary for testing

The evidence service's OpenAI embedding adapter accepted 32,768-character strings but forwarded them to an RT-Embed response schema limited to 1,000 characters. Long summaries therefore failed after inference and left LVS waiting for a nonexistent database write. The adapter now sends bounded text chunks, pools length-weighted vectors with L2 normalization, preserves one output per original input and short-input behavior, and rejects nonfinite vectors. Five unit tests pass; a real 3,510-character request returned finite 768-dimensional vectors. Pooling is an approximation for longer documents and does not certify retrieval quality.

LVS's default Elasticsearch mapping was 1,024 dimensions. The candidate sets `LVS_EMB_DIMENSIONS=768`, matching the shared local model. Existing user indexes were not migrated or deleted.

LVS's default `--max-live-streams 256` allowed context worker pools to grow in batches of ten. Setting its existing supported option to two bounded those pools and reduced observed LVS memory by roughly 4.8 GiB after repeat workloads. No LVS source patch was necessary.

The original model identities, old safety fuse, original image tags and prior user changes were preserved. Candidate models/support use separate container names and definitions; the original LVS service alone was recreated through a targeted `--no-deps` Compose operation.

## Limits

The previous two host watchdog freezes were not proven OOMs. NVIDIA R38.4 release notes independently document retained model memory and excessively large CUDA allocation hazards; the research note distinguishes that evidence from unproven root-cause attribution. This trial is a bounded operating result, not proof that all workloads are safe or that a driver/firmware problem has been eliminated.

Thumbnail retrieval returned HTTP500, and some generated captions hallucinated scene details. Those are remaining application/quality issues, not successful tests. No end-to-end browser playback or multi-camera endurance claim is made.
