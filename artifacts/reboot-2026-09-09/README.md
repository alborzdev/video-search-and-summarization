# Reboot investigation — September 9, 2026

Status: second reboot traced to a PVA kernel BUG; CUDA bypass passed isolated and combined probes. Full-stack qualification remains in progress; do not treat service readiness as sustained-ingestion evidence.

Traffic analysis resumed 19:25:52 UTC. Last observed available memory was 37.67 GiB. Embedding and detector logs end abruptly around 19:26:33–35 UTC. Current boot begins about 19:28:58 UTC. The host enables a two-minute Tegra hardware watchdog. Timing is consistent with a hang followed by watchdog reset, but the triggering cause is not established.

No persistent previous-boot journal was available; archived pstore is empty. Docker reports exit 255 and OOMKilled=false for models/agent/detector; that does not exclude host-level memory or GPU allocation problems. The guard event file still contains an earlier 19:02 event, not this failure. The transient user guard unit vanished on reboot. It polled host available memory and thermal liveness, then attempted serial Docker stops; it was not a hard allocation limit or a watchdog-proof safety guarantee.

All GPU models, detectors, agent and traffic streamer remain stopped after reboot. Traffic desired analysis state has been persistently paused so later agent startup does not resume it automatically. Approximately 106 GiB is now available. UI/support services are up; AI functionality is unavailable.

Before another sustained-ingestion run: establish persistent host/kernel and per-process GPU-memory telemetry, use a durable guard, and isolate live decoding/embedding/detection under a larger measured reserve. An idle/service-health or one-query smoke test is insufficient acceptance evidence. Avoid replaying the complete crash workload as the first diagnostic step.

## Second reboot: captured kernel failure

Persistent logs now show a PVA KMD ASSERT at 15:59:12 EDT in `pva_kmd_shared_buffer.c:238`, followed by a kernel BUG in `pva_kmd_linux_misc.c:81`. Faulting task: `irq/438-pva-isr`; trace includes `pva_kmd_fault` and `pva_kmd_shared_buffer_process` in `nvhost_pva`. Last fsynced memory sample: **98.273 GiB available**, 82.007 GiB free, thermal sample age 0.62s. Thus ordinary host-memory exhaustion is not supported for this second reboot. First reboot remains unproven.

The traffic runtime config enabled `compute-hw=2`; `deploy/docker/services/rtvi/rtvi-cv/ds-start.sh` explicitly applies Thor VPI tuning with `visualTrackerType: 2` and `vpiBackend4DcfTracker: 2`. Keep detector startup stopped until this PVA execution path is addressed; do not repeat the same combined workload merely with more memory reserve.

Post-reboot inventory at 16:47 EDT: no inference models or detector containers running. Only NVIDIA-runtime container is the telemetry exporter. `nvidia-smi` reports Xorg 114 MiB, GNOME Shell 82 MiB, and the desktop/browser process 178 MiB, with no compute processes. Host MemAvailable ~105.7 GiB. Larger resident allocations are ordinary UI, database, Kafka, metrics and desktop memory. No unrelated model server was found. Raw GPU totals are unsupported by nvidia-smi on this Thor, so reported graphics allocations are not a complete unified-memory accounting.

Full prior-boot log and captured telemetry are under `second-reboot/`. All probes have stopped; no restart scheduled. The persistent guard survived reboot and remains active.

## PVA bypass validation

Changed the Thor NvDCF VPI backend from PVA (2) to CUDA (1) in both perception startup scripts. Kept the tracker algorithm and existing per-source target cap. NVIDIA documents CUDA=1/PVA=2: https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html . The effective container tracker YAML was copied and inspected before stream registration; it contains `visualTrackerType: 2` and `vpiBackend4DcfTracker: 1`.

The executable regression probe `tools/runtime/test_tracker_backend.py` verifies replacement of an existing PVA setting and idempotent repeated startup tuning. It passes, as do the three guard tests. The prior source-locked qualification suite reports its startup hash changed (and rejects its old plan); its historical receipt is not silently re-stamped as evidence for this new backend.

CUDA detector-only probe: 300 seconds at approximately 30 FPS, minimum MemAvailable 104.464 GiB, no new kernel BUG/PVA assertion or reboot. See `cuda-detector-soak.json`. This is bounded validation, not a claim that the underlying NVIDIA driver bug is fixed.

Combined CUDA detector + embedding probe also passed: 300 seconds of detection, 303 seconds of embedding (59 results), minimum available memory 97.725 GiB, unchanged boot ID and no new PVA/kernel BUG entries. `cuda-workaround-receipt.json` records the script hashes and measured results.

The startup manager now uses the persistent guard, a 48 GiB stage floor, and explicitly allows the known traffic streamer. It starts Nemotron, then embeddings, then Cosmos so each model starts while sufficient allocation headroom remains. These changes preserve model identities and weights.

## Full-stack restoration checks

The first complete restore crossed the 48 GiB diagnostic floor at 17:15:37 EDT (47.975 GiB available). The persistent guard stopped all eight targeted workloads successfully, without a reboot. This is a contained capacity failure, separate from the earlier PVA crash. Its trip and stop outcomes remain under `artifacts/runtime-telemetry/`.

cAdvisor had accumulated about 3 GiB of reclaimable kernel slab, while its anonymous memory was only about 163 MiB. The Thor compose overlay now caps it at 1 GiB including swap, tracks Docker containers only, and uses 15-second collection with one minute of in-memory history. This preserves its endpoint and labels. The recreated container is healthy. Do not mistake its former Docker memory accounting for model VRAM or a JavaScript heap leak.

A clean stop and one-time idle reclaim recovered 116.44 GiB available with no NVIDIA compute processes. The next restore reached Cosmos readiness, but refused to start embeddings because the generic preflight requires floor + 15 GiB. Startup order now puts both smaller models before Cosmos. Stopping Cosmos alone left about 24 GiB retained; one idle-boundary reclaim recovered it (64 to 89 GiB available). No periodic cache dropping is enabled.

## Final bounded full-stack result

All 33 service roles passed Docker/API readiness after the ordered restore. One normal agent-managed traffic source then ran for **305 seconds**, with CUDA detection at approximately 30 FPS and continuously fresh indexed embeddings. Minimum available memory was **48.710 GiB**, above the unchanged 48 GiB diagnostic reserve. The boot ID remained unchanged and the current boot journal contained no new PVA assertion or kernel BUG. See `agent-cuda-soak.json`, `final-service-status.txt` and the updated `cuda-workaround-receipt.json`.

Collection is deliberately paused after the test; all 33 roles and the source player remain running, and the site is available. Original source definitions and input media remain preserved. No model identities, weights or context budgets changed during this workaround. The earlier four offline Isaac Sim sources remain paused.

This result covers one live detector/embedding/indexing workload with Cosmos and Nemotron resident and ready. It does **not** qualify concurrent heavy summarization, additional live sources, or unattended sustained ingestion. Only about 0.7–1 GiB separates this workload from the conservative diagnostic guard; preserve 48 GiB until further measured validation. The CUDA backend bypasses the implicated PVA path but does not fix the underlying NVIDIA kernel driver.
