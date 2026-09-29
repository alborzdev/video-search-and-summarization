# cAdvisor filesystem-scan reduction — September 28

## Finding and change

The container-metrics collector used approximately 1001–1012 MiB of its 1 GiB
limit. A simple restart did not materially reduce this. Direct cgroup inspection
then showed 903,770,112 kernel bytes, including 902,331,488 reclaimable slab
bytes, versus 115,306,496 anonymous bytes; process RSS was 132,492 KiB. Logs
showed repeated container filesystem scans taking up to eight seconds. This is
not evidence that cAdvisor's Go heap itself leaked a gigabyte.

The installed binary's `--help` lists `disk` separately from `diskIO`.
The Thor overlay now adds `disk` to the existing default disabled groups.
Only cAdvisor was recreated using the existing managed Compose command with
`--no-deps --no-build --pull never`. Existing 1 GiB cAdvisor limit, all model
budgets, source desired states and the 48 GiB diagnostic guard are unchanged.

Tradeoff: per-container filesystem-usage metrics are no longer exported.
Host filesystem capacity and container block-I/O counters remain available.
No video/database/image/cache deletion or kernel-memory reclaim was performed.

## Validation

- Prometheus `up{job="cadvisor"}` returns 1.
- cAdvisor exports `container_cpu_usage_seconds_total`,
  `container_memory_working_set_bytes`, `container_network_receive_bytes_total`,
  and `container_fs_reads_bytes_total`.
- `container_fs_usage_bytes` is absent, as intended.
- Node exporter still exports root `node_filesystem_avail_bytes`: approximately
  18.47 GB at the measurement point.
- All 31 core roles pass; guard active; boot remains
  `ac75a3b5-980a-41c5-8301-200423326f72`.
- [Thirteen samples over sixty seconds](cadvisor-scan-samples.json) show cAdvisor
  healthy throughout, about 27–126 MiB cgroup memory and about 3.6 MiB reclaimable
  slab. The large scan-related charge did not recur during this bounded check.
- Host available memory initially remained about 49 GiB; the final sample rose
  to 49.901 GiB. This delayed rise is temporally associated with the change, not
  proof of exact memory attribution. [Follow-up samples](cadvisor-headroom-followup.json)
  capture whether it persists briefly.

This is a bounded observability resource improvement, not sustained live-alert
qualification. Recheck actual host availability before any additional workload;
Docker's cgroup totals do not establish unified GPU/driver memory capacity.
