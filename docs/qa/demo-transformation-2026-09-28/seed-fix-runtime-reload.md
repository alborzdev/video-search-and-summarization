# Seed fix runtime reload — service recovery completed

September 28, approximately 22:08 EDT.

- Before stopping: guard active, no RT-VLM streams or Alert Bridge rules; about
  49 GiB available. Stopped only Cosmos first, but available memory reached only
  about 54 GiB, below the existing 63 GiB startup gate (48 floor + 15 headroom).
- Used documented `manage.py stop` plus stopping the replay publisher before
  idle reclaim. Manager completed successfully; available memory rose from
  72.77 to 112.67 GiB. Persistent data preserved.
- Invoked `python3 artifacts/thor-memory-2026-09-09/manage.py start --profile core`.
  Existing process remains active; do not start a duplicate. At the last check,
  Redis, Postgres and Kafka had settled, Elasticsearch was healthy, available
  memory 110.932 GiB. The UI/models are not yet restored.
- Startup output: `/tmp/seed-fix-staged-startup.log`; exec session 26951.
- Prepared `/tmp/seed-miss-recheck.py`: four bounded file requests with the original
  exact any-frame/system prompts, fixed four frames at 512×512, alternating
  temperature 0/seed42 with temperature0.4/seed1. Requires guard, no live streams
  and at least49.3GiB before each request. Not yet run.

Next: wait on the same startup process; restore the existing NvStreamer publisher,
verify source-mounted UI remains active, run core checks, verify the seeded
adapter in the new worker and run the preserved clip checks. Record final state
and copy the startup log here when complete. No live registration is planned until
this comparison is reviewed. Runtime reserve/budgets are unchanged.

## Verified continuation, 22:18 EDT

Re-polled exec session 26951 throughout this continuation; it remains running.
Video storage, event-processing, analytics and monitoring stages progressed.
Kibana settled healthy at 106.473 GiB available; node exporter is now starting.
No startup failure or reserve trip has been reported. Remaining infrastructure
and model stages still need to finish. Do not infer readiness or launch a second
manager process. The same `/tmp/seed-fix-staged-startup.log` is authoritative.

Confirmed the earlier live trial used system prompt “Answer yes or no”, matching
the prepared fixed-clip comparison. Live request omitted generation overrides;
source defaults are temperature0.4, seed1, top_p0.8, top_k20. Engine seed was
previously omitted, so a new seeded run cannot retrospectively reproduce that
unseeded RNG state. Container configuration has absolute video timestamps false;
actual live frame capture and timestamp-prefix behavior still need verification.

## Recovery and file checks completed, approximately 22:31 EDT

Original startup session 26951 terminated with exit1 only because the final UI
HTTP check timed out during first Turbopack compilation. UI log shows compilation
7s, first page8315ms; subsequent HTTP200 in0.378s. No second startup was launched.
An independent core check passed; UI remains source-mounted Turbopack. Cosmos
container started at2026-09-29T02:22:47.12540953Z after the seed patch, and its mounted
adapter includes all three sampling seed assignments plus debug-log seed field.
This establishes code availability after worker restart; no engine argument trace
was emitted at current log level.

Restored existing NvStreamer publisher. Old diagnostic RTSP port30556 returned404.
Sensor rescan through `/vst/api/v1/sensor/scan` completed and sensor reports online.
The current `/v1/live/streams` record returns port30557 for the same sensor; ffprobe
confirms H2641920×1080 there. Do not hardcode the previous diagnostic port in the
next trial. Probe emits a truncated SEI warning but returns the video stream.

Four requests to the preserved live-miss clip all returned YES:

| Temperature | Seed | Seconds |
| --- | --- | --- |
| 0 | 42 | 0.956 |
| 0.4 | 1 | 0.931 |
| 0.4 | 1 | 0.964 |
| 0 | 42 | 0.996 |

Memory after these calls52.474–52.531GiB. Both settings recognize the box in the
saved file, so this comparison does not reproduce the original live NO. Actual
live frames, timing and effective request metadata remain the next discriminating
evidence. A seed fix does not establish deterministic GPU results or live accuracy.

All nine preserved fixtures also match their reviewed labels in one pass,
0.872–1.065s. Negative labels still use sampled review, not exhaustive annotation.
Final core check:31roles pass,52.26GiB available, zero RT-VLM streams and Alert
Bridge rules, boot unchanged `ac75a3b5-980a-41c5-8301-200423326f72`. Guard/budgets
unchanged, detectors remain stopped. No new live AI ingestion was registered.

Browser revalidation is outstanding: Codex browser policy blocked reload of the
outage-affected tab for a non-HTTP(S) protocol; no alternate browser/navigation
workaround was attempted. Asked user to reopen the HTTP demo in Codex. API and
RTSP recovery are verified; rendered post-restart UI is not yet reverified.

Evidence: [startup](seed-fix-staged-startup.log), [final status](seed-fix-final-status.txt),
[four comparisons](seed-miss-recheck.json), [comparison script](seed-miss-recheck.py),
[nine fixtures](seed-nine-fixture-recheck.json).
