# Bound Agent background workers on Thor

September 28, 2026. This is an idle-overhead optimization, not a root-cause
claim for the memory guard trips.

## Baseline and one-variable change

Inspected the installed NAT FastAPI frontend source. It creates a local Dask
cluster with `n_workers = max_running_async_jobs + 1`; the extra worker handles
cleanup. The default is ten async jobs with one thread per process. Docker
process inspection confirmed eleven roughly 100 MiB workers, plus Agent and
Python's resource tracker.

Changed only the Thor profile's existing frontend settings:

```yaml
max_running_async_jobs: 2
dask_threads_per_worker: 1
```

This retains two job workers plus cleanup. Restarted Agent only; model
containers, weights, context/cache limits and 48 GiB reserve were unchanged.
No generic framework code or configuration schema was modified.

## Measurement

Read `/proc/*/smaps_rollup` and cgroup memory inside Agent using Python without
site initialization, before and after its restart. Both measurements include
the small measurement process. These are single settled snapshots, not a
controlled multi-trial estimate of host-wide savings.

| Metric | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Process proportional set size | 1477.19 MiB | 859.43 MiB | 617.75 MiB |
| Container memory | 1434.86 MiB | 781.82 MiB | 653.04 MiB |
| Dask workers | 11 | 3 | 8 |

Raw evidence: `agent-workers-before.json`, `agent-workers-after.json`.
All 31 core/API checks passed after restart; 51.65 GiB host memory available.

## Actual demo verification

Codex integrated browser: existing conveyor source → Search → ten-second result
→ Ask about this clip → What moves? → submit. A fresh inspection returned
“A box moves along a conveyor belt.” Local analysis 7.8 s, first observed
complete by 11.876 s. Prior identical question was 7.5 s; these two samples do
not establish a latency improvement or regression. Footage agreement passed.
During the question, one host sample showed 51.487 GiB available.

Screenshot: `bounded-agent-workers-answer.png`.

The tradeoff is lower simultaneous background-job capacity. The tested search
and fresh-question paths work; multi-user throughput and queued async-job
stress were not tested. Repeated ingestion, live detection, temporal grounding
and sustained memory stability remain unqualified. This recovers useful margin
but does not establish that the reserve will never trip again.
