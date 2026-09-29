> Historical first-stage report. The later user-authorized full-stack trial and final operating configuration are documented in [RESULTS.md](RESULTS.md) and [README.md](README.md). Statements below about services remaining stopped describe the initial stage only.

# Thor memory investigation — 2026-09-09

## Findings

Thor has 122.824 GiB of Linux-visible unified CPU/GPU memory. At the first inspection all VSS containers were already stopped. `nvidia-smi` listed no compute processes, only Xorg, GNOME Shell, and the Codex desktop graphics process (about 353 MiB total reported graphics allocations). The displayed ~35 GB was therefore not evidence of a live VSS model.

Before reclaim, `/proc/meminfo` reported 128,790,152 KiB total and 92,726,184 KiB available: **34.393 GiB used, 88.431 GiB available**. Anonymous process pages were about 6.7 GiB, shared memory about 1.6 GiB, and slab about 3.6 GiB; these categories are not all additive. Approximately 24 GiB was outside normal process/file-cache/slab accounting. NVMap listed zero client allocations; exported DMA buffers totaled about 192 MiB. No periodic cache cleaner was running.

A single write of `2` to `vm.drop_caches` invoked kernel shrinkers without deliberately dropping filesystem page cache. It completed successfully. Immediately afterward memory available was 116,751,756 KiB: **11.481 GiB used, 111.343 GiB available**, a **22.913 GiB** improvement. Cached file pages were essentially unchanged (56,309,436 → 56,328,336 KiB); slab fell by only about 1.2 GiB. No application was stopped for this operation.

This establishes that the bulk of the unexplained usage was reclaimable kernel-held memory, not an active model. NVIDIA's enabled system-memory pools (`EnableSystemMemoryPools: 529`) are the leading explanation for the non-slab portion. The driver source implements cached pages and a shrinker that frees them; this is strong attribution by mechanism and controlled intervention, not a direct per-pool byte counter. See [NVIDIA's driver source](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/main/kernel-open/nvidia/nv-vm.c).

Other running applications were left intact: datasheet chatbot, its PostgreSQL/Redis and parser container, plus vision playground web/MediaMTX. The parser container's PID 1 is `sleep infinity`; Docker's ~3.8 GiB charge must not be interpreted as 3.8 GiB of active GPU model memory. Docker and host memory metrics overlap and should not be summed.

## Staged CPU bring-up

Existing persistent containers were started individually, without recreating containers, deleting volumes, pulling images, or activating sources. Each stage waits for its configured Docker health check, then ten additional seconds. An 80 GiB available-memory floor aborts the current stage. Samples are in `cpu-stages.jsonl`; these are host-wide idle measurements subject to background-application variation, not model-load or traffic peaks.

The selected stages are Redis, VIOS PostgreSQL, Kafka, Elasticsearch, and Neo4j. Model services, RT-Embed, RT-CV, GPU-backed VIOS, LVS, and the Agent remain stopped. This is a measured infrastructure baseline, not an operational full VSS deployment.

## Previous experiment and current blocker

The August 12 acceptance evidence is superseded by the August 30 safety note: two full local Nemotron + Cosmos3 runs froze the host and led to 120-second hardware-watchdog resets. No kernel/container OOM was recorded. The record does not establish that ordinary out-of-memory was the root cause.

The current exact-model audit passed the static contract, exact artifact trees, and pinned local image checks. After reclaim it still failed its empirical admission rule: measured full-graph commitment is budgeted at 64 GiB, and the guard requires another 64 GiB available afterward. It projected 47.3 GiB available. Since Linux exposes only 122.824 GiB total, this guard deliberately cannot admit the full graph on this host, even with an otherwise empty system. It is a conservative safety lock, not a new experimental proof that the weights cannot fit.

The dual-model gate, restart protections, and stopped periodic cleaner were preserved. Further GPU qualification requires a separately reviewed, mutually exclusive single-model topology or a user-selected remote/sibling-host endpoint for one model. Do not replay the old full Compose startup to test capacity.

Relevant local records:

- `deploy/docker/thor-local/DEMO.md`
- `deploy/docker/thor-local/official-edge/README.md`
- `deploy/docker/thor-local/official-edge/thor_demo.py`
- `deploy/docker/thor-local/qualification/demo-ready-current-successor/EVIDENCE.md`

## Completed measurements

| Cumulative stage | Used GiB | Available GiB |
|---|---:|---:|
| baseline | 11.476 | 111.348 |
| redis | 11.784 | 111.040 |
| vss-vios-postgres | 11.798 | 111.025 |
| kafka | 13.019 | 109.805 |
| elasticsearch | 13.968 | 108.856 |
| vss-graph-db | 14.577 | 108.246 |

All five infrastructure services passed Docker health checks and remain running. The final cumulative increment over baseline was 3.101 GiB. Other VSS services remain stopped. No full-stack/model fit or workload stability claim is made.
