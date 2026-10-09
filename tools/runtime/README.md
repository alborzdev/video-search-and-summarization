# Thor runtime qualification

**October 9 operator setting:** the user explicitly selected a **10 GiB**
memory reserve for this Anvil T5 demo. The active systemd guard and
`.thor/settings.json` use that floor; current Thor startup, UI and NVStreamer
tools preserve it. See [configuration](../thor/README.md#staged-startup).
The 36/48 GiB instructions and measurements below describe historical
qualification conditions; they do not override the saved operator setting.
Model/container budgets remain unchanged, and this setting does not qualify
additional ingestion workloads.

**October 8 bounded NVStreamer result:** one single-slice H.264 720p/10 FPS
mock camera passed a ten-minute run with recording, CUDA detection, embeddings,
captions and browser workflows. Minimum one-second telemetry was 51.372 GiB
available with the 48 GiB guard active and no reboot. A prior gallery-triggered
reserve trip was corrected by moving recorded thumbnails to a serial CPU reader.
See [acceptance receipt](../../docs/qa/2026-10-08-thor-nvstreamer.md) for the
failure, fixes, exact scope and AI accuracy limitations. This does not qualify
unlimited ingestion or additional concurrent sources; retain the 48 GiB floor.

The full VSS stack is **not qualified for sustained live ingestion**. A live traffic run was followed by a host hang/reboot on September 9, 2026. See `artifacts/reboot-2026-09-09/README.md` before starting the full stack or changing live-ingestion capacity.

`guard.py` logs host memory, thermal/power readings, and large/D-state processes into `artifacts/runtime-telemetry/`. Samples are fsynced each second and rotated at 32 MiB, retaining one prior file. A trip writes `trip.json` and attempts concurrent, bounded Docker stops of the agent, streamer, models, detectors and LVS. This cannot guarantee recovery from a kernel/GPU hang.

The installed user unit `vss-memory-budget.service` is enabled persistently, with user lingering enabled. Its current diagnostic floor is **48 GiB available**, above the normal minimum 36 GiB. Keep this larger floor during staged qualification. The checked-in unit records the current Thor path; install it under `~/.config/systemd/user/` and run `systemctl --user daemon-reload && systemctl --user enable --now vss-memory-budget` when restoring this setup.

Host kernel logs now persist under `/var/log/journal`, with a 256 MiB cap and five-second sync interval configured in `/etc/systemd/journald.conf.d/60-vss-diagnostics.conf`. Read prior-boot evidence with `journalctl -b -1 -k`; abrupt power loss may still lose the final seconds.

Run `python3 tools/runtime/test_guard.py` for the guard's boundary/timeout checks. `soak_embed.py` uses the existing traffic source, requires an already-ready embedding service and live VIOS feed, collects five minutes of progress/memory samples, and stops the embedding job when done. This is an explicit diagnostic action, not an automatic startup task. It writes new embeddings to the development data store.

Use per-stage evidence: sustained output, stable memory slope, thermal telemetry liveness, and an unchanged boot ID. Service health alone is insufficient. Keep source desired states paused until a tested workload has been selected.

**Second-reboot finding:** the captured failure is a PVA driver kernel BUG with 98.3 GiB available, not evidence of exhausted host memory. Keep the PVA-enabled traffic detector stopped until its backend is corrected; increasing the reserve alone does not address it. See `artifacts/reboot-2026-09-09/second-reboot/previous-boot.log` and the parent incident README.

The tracker startup scripts now select `visualTrackerType: 2` with `vpiBackend4DcfTracker: 1` (VPI CUDA), replacing PVA backend 2. `compute-hw=2` remains the separate image-conversion setting. The bounded `soak_detector.py` probe verifies the effective CUDA setting before registering the traffic feed. Historical source-locked qualification receipts do not qualify this changed script.

The startup manager uses Nemotron → embeddings → Cosmos order, retaining the 48 GiB runtime floor and 15 GiB additional model-start headroom. The Thor cAdvisor overlay is capped at 1 GiB. After stopped model processes, driver-retained allocations may require the documented one-time idle reclaim; stopping a container alone does not establish a clean baseline.

**Earlier bounded result:** CUDA detector-only, detector+embedding, and a 305-second agent-managed ingestion run with all 33 service roles passed. Full-stack minimum: 48.710 GiB available. Source collection is paused after the bounded test. All services were ready at that checkpoint, but sustained ingestion, additional sources and concurrent heavy summarization remain unqualified. See the incident receipt for exact scope; do not lower the 48 GiB floor from readiness alone.

**Later UI-audit result (September 9):** normal development use crossed the 48 GiB floor (47.16 GiB); the guard stopped workloads without reboot. The current audit runtime leaves the unused warehouse detector `vss-rtvi-cv` stopped, with traffic collection paused and about 52 GiB available. A separate VIOS streamprocessing exit 139 was recovered by restoring the player before restarting VIOS; live WebRTC still rejects stream start although archive playback works. This supersedes the earlier all-services-ready snapshot. See [full application audit](../../docs/qa/2026-09-09-full-app-audit.md) for fixes, evidence and remaining limitations.

**September 28 recovery:** the default candidate manager profile is now `core` (31 service roles; both detectors omitted). Retained memory reclaim recovered about 40 GiB before model startup. VIOS MCP health probes were leaking persistent sessions; a dedicated `/health` probe and 1 GiB cap are now applied. Core upload, playback, fresh search and visual evidence analysis passed, with about 51–53 GiB available. All-service/concurrent ingestion remains unqualified. See [recovery receipt](../../artifacts/thor-recovery-2026-09-28/README.md).


**September 28 maintenance finding:** an age-limited Docker build-cache prune
reclaimed 5.05 GB but coincided with a reserve trip at 47.901 GiB while the core
models were loaded. The guard stopped the AI workloads and replay publisher;
the boot ID did not change. Do storage/build-cache maintenance with the model
workloads stopped, then use the documented idle reclaim and staged startup.
Do not assume reclaiming disk is memory-neutral, lower the guard, or repeat
cleanup against a running model stack with marginal headroom. Preserve
`trip.json` and stop results before recovery. Details are in
`artifacts/thor-recovery-2026-09-28/cache-maintenance-trip/`.

VIOS currently has a 100000 MB recording quota, while available host disk is
much smaller. That quota is not a host free-space reservation and does not
protect Elasticsearch's 12 GiB high watermark. Before extended recording,
measure available space and video growth and agree retention/additional storage.
Changing retention can remove historical evidence: preserve needed clips first;
do not silently shrink the quota to reclaim recordings.

**September 28 cAdvisor scan reduction:** the Thor overlay disables the `disk`
metric group (per-container filesystem usage scans), preserving its existing
other disabled groups, 1 GiB memory limit, CPU/memory/network/disk-I/O counters,
and Prometheus scraping. Host root free-space metrics remain available through
node-exporter. This addresses observed recursive scans and about 860 MiB of
cgroup-charged reclaimable slab; it is not a new live-workload qualification or
permission to lower the reserve. See
[measurement receipt](../../docs/qa/demo-transformation-2026-09-28/cadvisor-scan-reduction.md).
