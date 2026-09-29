# Live report mobile check — September 28, 20:15 EDT

Codex integrated browser at http://10.88.9.12:7777/, source
`6776f3a6-446f-4da8-832e-cfcf4507de8c`, explicitly labeled recorded simulation
replayed over RTSP. Continuous AI analysis remained paused.

- Fresh question: “What moves along the conveyor?”
- Answer: “A brown box moves along the conveyor belt.”
- Observed complete by 10.390 seconds, with bounded browser element waits.
- Exact inspected interval: `2026-09-29T00:15:09.293000Z` through
  `2026-09-29T00:15:34.293000Z`.
- At 390×844, Play inspected clip opened a readable dialog. Video advanced to
  7.880/24.999 seconds, readyState 4, no error; brown carton visible near the
  bottom of the frame during playback.
- Closed evidence, opened Save report, entered title and provenance/limits in
  notes. All form actions remained reachable in the scrolling answer panel.
- Saved **Mobile RTSP review — conveyor movement**, ID
  `cd006a78-3e0e-431c-b59e-390ab9f8be97`. UI confirmed locally cached clip;
  API readback confirmed exact timestamps, under_review and media_status retained.
- Open report worked in the same mobile tab. Retained video reached its end,
  24.798 seconds, readyState 4, no error. The retained encoded media is slightly
  shorter than the requested 25-second interval; exact ISO request bounds remain
  in the record. Copy briefing succeeded and actual clipboard included notes.
- Restored desktop viewport. No source edits or redundant unit test run.

[Mobile form](live-report-mobile-form.png) ·
[Saved mobile report](live-report-mobile-saved.png).

Runtime started with 31 core roles passing, 48.95 GiB available, guard active.
Post-check memory was 48.82 GiB, same boot, guard active, but Elasticsearch was
unhealthy. Its allocation explanation identified an unassigned primary blocked
by the 12 GiB disk watermark. Storage recovery is documented separately; do
not describe this as a full healthy-stack rehearsal or sustained qualification.

This closes the live save-form mobile check. General model accuracy, repeated
continuous monitoring, export-file delivery and simulator qualification remain
separate requirements.
