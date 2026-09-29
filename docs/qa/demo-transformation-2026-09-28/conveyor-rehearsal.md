# Conveyor rehearsal and Home scenario choice

September 28, 2026. UI: http://10.88.9.12:7777/, Codex integrated browser.

## Footage and observations

Local source: `sample-sim-box-conveyor.mp4`, 81.566667 s, H.264, 1920×1080,
30 fps. Inspected frames at 1, 4, 8, 35 and 70 seconds. Prepared the first
ten seconds via stream copy (1,070,470 bytes), uploaded using the Sources
Agent-backed flow, and observed Upload Complete (1/1). No detection worker
or live ingestion was started.

Query: `box moving on a conveyor belt`, scoped to the new recording. One
ten-second result grouped two adjacent matches. Playback observed at 4.713 s,
duration 10 s, readyState 4, paused false, no media error.

| Question | Fresh local analysis | Answer assessment |
| --- | --- | --- |
| What moves in this clip? | 7.5 s | “A box moves along a conveyor belt.” Matches footage. Completion first observed by 11.641 s. |
| How does this clip end? | 8.2 s | “The box has moved off the conveyor belt and out of view.” Out of view is supported; off the belt is not established. Completion observed by 19.282 s; polling interval prevents an exact user-perceived latency claim. |

## UI change

Home's suggestion previously assumed a person carrying a box regardless of
the featured source. Recording choice now updates preview, context and search
together. Known inspected recordings have explicit suggested queries. Unknown
recordings receive a neutral search action. Source aliases do not change IDs.

Two focused entry tests and app typecheck passed. Desktop and 390×844 browser
layouts inspected; no framework overlay or relevant browser console error.
The new CTA handed off the correct query and source, but the actual search
failed because the runtime guard had stopped Agent/models. Recheck this
end-to-end action after recovery; earlier successful manual search is not proof
of the new CTA's completed retrieval.

## Guard event and attribution limits

At 18:34:20 EDT the guard recorded 47.689 GiB available against its unchanged
48 GiB floor. Boot ID stayed `ac75a3b5-980a-41c5-8301-200423326f72`.
Agent, LVS, Cosmos, Embed and Nemotron were verified exited. Guard remained
active. Copied full event to `conveyor-pass-guard-trip.json`.

Telemetry from 18:28:22 to the trip shows available memory falling from about
50 GiB. Next.js RSS increased from 1686 to 1709 MiB, VST RSS by about 96 MiB.
Process RSS does not account for the full host change; the data does not identify
the allocation cause or establish a UI leak. Replay component source inspection
shows abort/pause/src removal/load cleanup on unmount; that alone does not prove
native decoder or server allocations are released.

One documented idle reclaim ran with models stopped, followed by manager
session 30856. Nemotron reached ready-settled at 18:37:54; Embed then began.
Recovery remains in progress. No reserve or model budget was changed.

Evidence: `conveyor-movement-answer.png`, `conveyor-ending-answer.png`,
`home-conveyor-choice.png`, `home-recordings-mobile.png`.

## Recovery and Home handoff verified

Manager session 30856 completed with exit 0 at 18:44:55 EDT. All 31 core/API
checks passed at 50.96 GiB available. In the integrated browser, selected
Conveyor on Home and clicked its suggested search. The app passed the correct
query and source, then returned one ten-second result. Completion was first
observed by 5.119 s (not an exact response latency measurement).
Screenshot: `home-conveyor-search-recovered.png`.

Post-search all 31 checks still passed, 50.97 GiB available, guard active.
No additional fresh VLM request was made during this recovery check. Sustained
headroom and grounding remain unresolved. Source inspection found that NAT's
FastAPI frontend creates `max_running_async_jobs + 1` Dask workers; measure this
pool's overhead before considering a separate concurrency adjustment. No such
setting was changed in this pass.
