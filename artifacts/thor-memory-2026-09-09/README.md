# Thor VSS memory fit — measured local candidate

Historical pre-reboot measurement: all 33 service roles fit with a minimum 40.204 GiB available. This is **not current sustained-ingestion qualification**. The later reboot investigation found a PVA kernel BUG; the CUDA bypass and 48 GiB diagnostic reserve now govern restoration. Read [the incident record](../reboot-2026-09-09/README.md) and [runtime guidance](../../tools/runtime/README.md) before startup.

This directory is operational: retain its YAML files and scripts. It references the existing local model caches, images, Docker volumes, networks, protected environment files and repository source. It is specific to this Thor checkout, not a portable installer.

## Operate

Run from the repository root:

```bash
python3 artifacts/thor-memory-2026-09-09/manage.py status
python3 artifacts/thor-memory-2026-09-09/manage.py start
python3 artifacts/thor-memory-2026-09-09/manage.py stop
```

`start` now defaults to the 31-role `core` development profile: supporting services and models in measured order, then LVS and the Agent, without starting either detector. `--profile full` explicitly includes both detectors; it is not sustained-load qualified. `stop` still stops all candidate services. See `../thor-recovery-2026-09-28/README.md` for the current recovery receipt. It is idempotent and uses local images without pulls or builds. Cold model startup requires at least 90 GiB available after supporting services settle. A partially running unhealthy model requires investigation before restarting it.

`stop` stops this VSS configuration, preserves its persistent data and volumes, and performs one idle kernel-memory reclaim. Other application stacks are left running. Neither command enables periodic cache dropping.

The current application is at **http://10.88.9.12:7777/**; the generated environment owns the current address.

The user service `vss-memory-budget.service` watches a 48 GiB diagnostic available-memory floor and thermal telemetry liveness. It attempts concurrent bounded stops of the models, agent, streamer, detectors and LVS on a breach. Inspect it with:

```bash
systemctl --user status vss-memory-budget
journalctl --user -u vss-memory-budget -n 30
```

It is a persistent enabled user service with lingering, also ensured by `manage.py start`. It does not automatically start the models. Its existence does not guarantee protection from the previously observed driver/firmware freezes. The old 64+64 GiB launcher fuse remains unchanged; use this candidate's manager instead of the old full-stack launcher. Do not start the original model/support containers alongside their replacements.

## Configuration and measured bounds

September 28 Agent adjustment: the Thor profile explicitly allows two Dask
background jobs plus cleanup instead of the framework default ten plus cleanup.
An Agent-only before/after measurement recovered approximately 618 MiB PSS;
recorded search and fresh visual-question checks passed. This lowers concurrent
background-job capacity and does not qualify sustained load. See the
[measurement receipt](../../docs/qa/demo-transformation-2026-09-28/agent-worker-budget.md).

| Component | Configuration |
|---|---|
| Nemotron 3 Nano 4B FP8 | Exact pinned image/model; 2 GiB KV; 32K context; eager; one sequence; 2,048-token prefill batches |
| Cosmos3 Nano BF16 | Exact pinned image/model; 3 GiB KV; 16K context; eager; one sequence; processor cache disabled |
| Cosmos Embed | Existing exact model; batch 2; separately built TensorRT cache volume, preserving batch 8/64 artifacts |
| LVS | Shared model endpoints; 768-dimensional indexes; `--max-live-streams 2` bounds context pools |
| Text embedding adapter | Local support service chunks long documents, pools their vectors, returns one finite 768-vector per document |

The measured workload is **one 1920×1080, 10 FPS live source**, live detection/embedding/captioning, an overlapping Agent request, plus repeated sequential 25-second file summaries. This is not an eight-camera qualification, long-duration soak, unlimited-history guarantee, or summary-accuracy certification. Multi-sequence inference queues, so latency rises under contention. The UI's larger advertised source limits have not been newly qualified.

The existing warehouse and traffic detector services, analytics, databases, media services, observability and UI stay enabled. Six successful one-shot initializers do not need to remain running; two calibration helpers and optional NVStreamer are not required for this path.

## Results and remaining issues

- Original ~35 GiB unexplained usage was mostly retained kernel memory: one idle reclaim recovered **22.913 GiB**, with no active VSS models present.
- Batch-2 Embed saved about **1.6 GiB** over batch 8 in isolated comparison.
- Bounding LVS reduced its observed container memory from **6.4 to 1.6 GiB** after repeated summaries.
- Real Agent tool execution passed; fresh video ingestion produced five chunks and relevant indexed search results.
- Three final bounded-pool summaries completed in **60.4, 60.1 and 48.2 seconds**, each processing five chunks with local LLM aggregation; no repeated-job worker growth was observed afterward.
- Final live test produced **618 indexed detection records**, **12 caption updates**, five semantic search results, and a successful overlapping Agent request. All owned live sources, files and indexed test documents were cleaned up.
- A direct returned thumbnail URL responded HTTP 500. Ingestion/search and summary generation succeeded, but thumbnail/browser playback QA is not passed.
- Generated descriptions sometimes invent objects or people. Memory fit does not establish semantic accuracy.

See [RESULTS.md](RESULTS.md), JSON receipts here, and [the research note](../../docs/research/2026-09-09-thor-vss-memory-runtime.md).
