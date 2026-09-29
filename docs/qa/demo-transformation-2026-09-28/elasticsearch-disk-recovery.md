# Elasticsearch disk recovery — September 28, approximately 20:18 EDT

## Failure and authoritative cause

After the mobile RTSP report check, core status reported Elasticsearch unhealthy.
Docker health checks returned HTTP 408 while waiting for yellow health. Direct
cluster health was red: 159 active primaries and one unassigned primary.
Allocation explanation identified `default_ce3305a3_5bf4_423f_af33_f313ddcaf8cd`,
created at 00:00:34 UTC, blocked by the disk-threshold decider: 11.6 GiB available
was below the existing 12 GiB high watermark. Earlier process-health snapshots
had not yet exposed the long failing streak; they are not proof that allocation
was healthy throughout the prior rehearsal.

## Recovery performed

1. Inspected disk/cache sizes. pip reported 1164.2 MB HTTP download cache and
   1.4 MB locally built wheels.
2. Removed only `/home/nvidia/.cache/pip/http-v2`, a regenerable package-download
   cache. Retained locally built wheels, model caches, database, video and all
   application data. Did not lower disk or memory safeguards.
3. Available disk rose to 13,715,750,912 bytes (approximately 12.77 GiB).
4. Initial bounded health wait still returned red, but a fresh allocation
   explanation changed to `can_allocate: yes`.
5. Called normal `POST /_cluster/reroute?retry_failed=true&metric=none` with no
   allocation commands. Acknowledged; cluster reached yellow with no unassigned
   primaries. No forced stale/empty-primary allocation was used.
6. Later shard inventory: 163 started primaries and 39 unassigned replicas.
   Core status returned all 31 roles passing, 48.86 GiB available.

The replicas remain unassigned on this single-node cluster; this recovery does
not claim green cluster health. Memory guard stayed active and boot ID unchanged.
No model restart, source-state change or runtime-budget change was required.

## Remaining risk

Disk is still 99% used, with limited headroom. This was a bounded recovery, not
a long-term storage plan. Before a sustained presentation, inspect growth and
retention of generated video/index/log data and choose an explicit retention or
additional-storage plan. Do not repeatedly delete user data or lower watermarks
to keep the demo running. Newly downloaded Python packages may need a network
fetch now that their HTTP cache has been removed.
