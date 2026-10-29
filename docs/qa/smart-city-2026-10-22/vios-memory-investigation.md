# VIOS memory growth: read-only investigation

The strongest observed increase follows the five-second evidence export, rather than continuous recording alone. This is an allocation-retention finding, not proof of an unreachable memory leak. No runtime settings, services, limits, RTSP readers or GPU jobs were changed by this investigation. The sanitized [receipt](vios-memory-investigation.json) retains exact sample times, hashes and resource counters; it contains no source URLs or credentials.

## What the existing run establishes

| Existing observation | VIOS cgroup memory |
| --- | ---: |
| 05:23:35, initial two-source Small window | 1,032.90 MiB |
| 05:24:49–05:29:19, two-source recording/inference without Ask | About 1,095–1,101 MiB |
| 05:29:19, before evidence export | 1,098.45 MiB |
| 05:29:30, while export completes | 1,648.30 MiB |
| 05:30:33, after export cleanup | 1,636.49 MiB |
| 05:35:47, Medium test startup | 1,783.25 MiB |
| 05:36:19, after startup settles | 1,697.21 MiB |
| 05:40:06, same Medium run | 1,753.42 MiB |

The main step is approximately 549.85 MiB. Existing logs place the export at 05:29:25.69–05:29:30.28. The request uses a five-second window, `transcode=full`, software encoding, no overlay and no audio. VIOS creates `ClipReaderProducer` and `TranscodeWriterConsumer`, reaches EOS, sets the pipelines to NULL, exits the reader main loop and logs the reader destructor. At 05:30:20 it reuses the same cached clip without another similar increase. A one-hour temporary-file retention timer explains keeping the output on disk; it does not by itself explain retaining hundreds of MiB of anonymous RAM.

The earlier five-minute observation shows a plateau after initial growth. The Medium window shows a startup peak, a reduction, then slower growth. These data do not establish linear growth forever, nor separate every source of the remaining drift. Native restarts, browser connections and the export all occurred during this process lifetime; they were not isolated experiments.

At 05:38:22, `memory.current` was 1,754.63 MiB: anonymous 1,705.8 MiB, file 33.1 MiB and kernel 15.2 MiB. OOM and OOM-kill counters were zero. This is not predominantly file cache. One `launch_vst` process held the memory and had 275 threads. Read-only `smaps` showed many roughly 60–64 MiB anonymous resident mappings. Their layout is consistent with heap arenas, but these maps cannot identify which allocations are live or free.

Recording queues are normally logged as zero bytes; a nonzero sample was 97,924 bytes. The configured encoded recorder queue limit is 16,000,000 bytes per source, with frame dropping enabled. The code applies the limit while playing. These two queues alone do not account for the observed anonymous footprint. This does not rule out other recording allocations.

The live query reported four WebRTC peers, two per camera, and the RTSP proxy reported six active sessions. Existing logs include peer hangups and decoder cleanup, so there is no demonstrated simple accumulation of every old peer. There are still many late-frame and same/old-NTP drops in the browser-delivery path. A direct detector input would not remove these browser or recording paths.

## Relevant local code

- `services/vios/src/framework/media/media_pipelines/VideoQueue.cpp`: encoded recorder queue cap, frame-drop logic and queue counters.
- `services/vios/src/modules/storage_management/video_download.cpp`: export objects stop and reset in a detached cleanup thread; the observed cleanup completed. A returned HTTP response alone is insufficient evidence of cleanup.
- `services/vios/src/framework/media/media_pipelines/transcode_writer_consumer.cpp`: video appsrc is blocking with a 2 MB encoded-byte limit; the export selects software decoding/encoding when hardware paths are unavailable. H264 uses x264 with zero B frames and disabled lookahead. There is no explicit encoder thread cap in this path. Teardown unreferences the pipeline.
- `services/vios/src/framework/media/video_source/processors/transforms/ll_transform.cpp`: decoded-picture transformation has its own queue. Unlike `VideoQueue`, its enqueue path has no explicit count/byte bound. It is a separate candidate for browser-delivery pressure, not proven to cause the export step.

Local source hashes and the running binary/image hashes are pinned in the receipt. Inspection of local code does not assert that an unverified source edit is present in the running binary.

## A scoped allocator trial is applicable

The running container is Ubuntu 24.04.5, aarch64, glibc 2.39-0ubuntu8.9. The process maps glibc, `LD_PRELOAD` is empty, and no alternative allocator or arena setting was found. It reports 20 online processors despite its two-CPU quota.

GNU documents `MALLOC_ARENA_MAX` as a process-start limit on allocator arenas. In this glibc version the default 64-bit ceiling depends on online CPU count, potentially 160 here, rather than the two-CPU quota. An explicit value of 2 is therefore a reasonable experiment. Fewer arenas can increase contention; this is not a memory guarantee or a claim of zero performance cost. [GNU glibc 2.39 allocator parameters](https://sourceware.org/glibc/manual/2.39/html_node/Malloc-Tunable-Parameters.html).

Free heap storage can remain resident and be reused. GNU describes separate mmap and trimming thresholds; changing them simultaneously would prevent attribution. Leave those thresholds, per-thread cache settings and preload libraries unchanged for the first trial. [GNU glibc 2.39 allocation tunables](https://sourceware.org/glibc/manual/2.39/html_node/Memory-Allocation-Tunables.html).

## Controlled next test, not yet run

After the coordinated UI/controller changes finish, use a fresh VIOS process and set only `MALLOC_ARENA_MAX=2` in the VIOS streamprocessing service environment before launch. Keep the same image, two-CPU quota, 2 GiB memory cap, 20 GiB available-memory reserve, codec fixtures, native Medium profile and 10 ms mux setting. Do not add host-wide allocator variables or settings to model services.

1. Start the usual two sources with native Medium and the existing embedding, VLM and LLM services. Record a stable pre-Ask baseline, including anonymous/file memory, process RSS/threads, OOM/restart counters, native PTS uniqueness and source-clock progress/age.
2. Make exactly three sequential real Ask requests, each selecting a different recent five-second window. Confirm each creates a new export, completes inference and serves its actual evidence clip. Do not overlap requests. Sample before, during and at least 60 seconds after each export; log cleanup completion and retained-memory plateaus.
3. Request one identical already-exported window to identify the cache path. Keep that separate from the three new-export measurements.
4. Compare retained increments, peaks and post-export trend with the existing baseline. Keep all clock, freshness, duplicate, memory-reserve, OOM and restart gates. A lower RSS with stale video is a failed trial. Pause the specified analysis sources on failure through the canonical controls; do not raise budgets to hide it.

This test can show reuse or improvement under the proposed cap, but its historical comparison has other lifecycle differences. A strict causal comparison needs a fresh process without the cap and the same sequence, then a fresh capped process, with all other settings identical. If each fresh export still adds a similar persistent increment, inspect allocation ownership with a separate instrumented reproduction before calling it an unreachable leak.

## Optional direct detector input

The native detector can consume the original registered RTSP source while VSS retains source identity, recording, playback and Ask. The current controller validates URLs against registered sensor/stream metadata and a host allowlist, then uses the submitted camera URL. A future explicit source-input policy could choose the exact registered original URI, preserve the VSS sensor ID and prohibit arbitrary unregistered URLs.

That would remove the detector's two proxy readers from VIOS and avoid relying on proxy frame assembly for perception. It would not fix the software-transcoded export allocation or remove the four browser peers. Qualify original-source RTCP timing, frame uniqueness, reconnect epochs, browser-to-detection alignment and Agent pause/resume before adopting it. Keep the already-qualified proxy path as the current setting until that test passes; do not change this variable during the allocator trial.
