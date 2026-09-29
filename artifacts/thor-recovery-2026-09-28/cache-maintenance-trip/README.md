# September 28, 20:21 EDT — cache maintenance reserve trip

Disk inspection found about 39 GB reclaimable Docker build cache, alongside
preserved 11 GB old traffic footage and 530 MB current conveyor RTSP recording.
VIOS quota is 100000 MB; it exceeds currently available disk.

Ran the installed Buildx command:

```sh
docker buildx prune --filter 'until=168h' --min-free-space 30GB --reserved-space 20GB --force
```

It reclaimed 5.05 GB. The 30 GB free-space target was not reached under the
age/reservation constraints. Host available disk became approximately 18 GiB;
no images, containers, volumes, video, model or database data were removed.
Rebuilding affected old layers may now take longer.

During maintenance, the active guard observed 47.901 GiB available (floor 48)
and stopped Agent, LVS, all three models and NvStreamer. This is temporal
association, not a complete attribution of kernel/GPU/process memory growth.
Boot stayed `ac75a3b5-980a-41c5-8301-200423326f72`.

Evidence: `trip.json`, `stop-results.json`, `stopped-state.json`,
`build-cache-prune.txt`. These are preserved copies, not references to mutable
runtime telemetry.

Recovery: verified stopped workloads, performed the already-documented one-time
idle reclaim, and invoked `manage.py start --profile core`. Available memory at
first Nemotron loading sample was 100.041 GiB. Restored the existing NvStreamer
publisher; VIOS streamprocessing remained running with restart count zero.
Startup completion and functional verification are pending until appended below.

Do not run disk-cache maintenance under a marginal loaded-model reserve. The
runtime README now requires stopped workloads for this maintenance. Disk space
and runtime memory are separate constraints; both must be checked.


## Recovery completed, approximately 20:31 EDT

The original staged-startup process exited zero. Its final status reported all
31 core roles passing and 51.55 GiB available. An independent check, now including
Elasticsearch primary-shard health, also passed at 51.63 GiB.

Codex browser verification: Home's recording preview initially retained the
transient fetch error; its Retry action restored ten-second playback. Home then
correctly changed from preview-only wording back to individual-question wording
once Agent/VLM readiness returned. Source-scoped conveyor search returned one
ten-second clip; a fresh “What moves?” returned “A box moves along a conveyor
belt.” Local analysis 7.9s; observed complete by 8.196s. No new report saved.

After fresh inference, core checks still passed at 50.14 GiB, guard active,
unchanged boot. Available disk approximately 18 GiB. This recovers the bounded
recorded/on-demand demonstration; sustained ingestion is still unqualified.
`staged-startup.txt` preserves the actual startup output.

Final RTSP check: Home → Open camera stream selected the same replay; video
advanced to 27.489s, readyState 4, playing, no media error. UI still reported
Analysis paused. No detector or continuous AI collection was enabled.
