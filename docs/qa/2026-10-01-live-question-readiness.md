# Live question readiness and 15-second default

The previous hook started a fixed 30-second timer whenever capture was first
observed as on. That included reopening an already-recording camera, producing
a disabled Ask button despite usable footage already existing.

The live capture API now verifies actual retained recording intervals. It
reports recording state separately from question readiness. The UI enables
questions immediately when a continuous recent 15-second interval is available,
and polls readiness every three seconds without overlapping reads. A new
capture waits for real footage; the question stays typed and the explanation
appears next to the Ask form. Missing/stale footage, unavailable visual AI,
disconnected cameras and busy requests still block submission.

The analyst uses the same interval selector and forwards exact retained bounds
to the inspector. The inspector validates timezone, duration, five-second
storage margin and recency, preserving those bounds in the result. The fallback
live duration is also 15 seconds. Recording gaps are never joined, and an old
completed segment cannot stand in for an incomplete restarted recording.

## Verification

- 77 focused Jest tests across six API, recording-window, hook, source-boundary
  and live-demo suites passed.
- Strict app TypeScript check passed.
- 16 custom worker Python tests passed in the cached agent runtime; focused
  Ruff lint/format checks passed. Existing broader Python lint/type-check failures
  remain unrelated to this change.
- The live capture API reported `recordingStatus: on`, `questionReady: true`,
  and `remainingSeconds: 0` for the simulator camera.
- Browser navigation to Live view followed by typing immediately enabled Ask.
- A real warehouse question returned HTTP 200. The agent logged a 15.0-second
  clip and the UI displayed **Recorded interval · 15 seconds**, from
  `2026-10-01T15:30:08.772Z` to `2026-10-01T15:30:23.772Z`.
- A second browser question returned a 15-second interval from 11:32:53 AM to
  11:33:08 AM. **Replay inspected clip** loaded recorded evidence with video
  duration exactly 15 seconds and readyState 4; playback was visible. The proof
  is `/home/spark/.codex/visualizations/2026/10/01/vss-live-question/15-second-replay.png`.

Only the CPU API agent was restarted to load its new request validation. The
model and embedding services stayed running. Analysis profiles and live-alert
rules compared equal before and after. Capture remained on, the source stayed
connected, and the Spark 24 GiB reserve and guard were preserved.

## Performance interpretation

Shorter footage reduces the required recording interval and clip preparation
work. The existing visual profile samples two frames per second, capped at 30
frames. Both the previous 25-second interval and the new 15-second interval hit
that cap; this change does not guarantee faster Cosmos inference. No frame
sampling, quality, model budget or concurrency settings were altered.

The Clear history work is documented separately in
[its verification receipt](2026-10-01-clear-history.md).
