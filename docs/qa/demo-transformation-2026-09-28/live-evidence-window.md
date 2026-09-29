# Live answer → exact inspected clip — September 28

## Verified behavior

Codex integrated browser at http://10.88.9.12:7777/?workspace=live, desktop 1265×712. Source: Conveyor — Recorded Simulation (RTSP Replay), sensor 6776f3a6-446f-4da8-832e-cfcf4507de8c.

Sent “What is visible on the conveyor?” through the focused source. Fresh answer “Boxes are moving along the conveyor belt” was observed complete by 12.437 seconds. The answer displayed Sep 28, 07:28:27–07:28:52 PM EDT and Play inspected clip. Backend log confirms model input interval `2026-09-28T23:28:27.627000Z`–`2026-09-28T23:28:52.627000Z`.

Clicked Play inspected clip. Actual 25-second video loaded, advanced from 6.304 to 21.259 seconds, readyState 4, no media error. A box was visible moving out of the frame at the first captured playback check. This proves interval traceability/playback, not comprehensive accuracy of every answer. No framework overlay or recent browser errors/warnings.

- [Answer with timestamp and action](live-answer-timestamps.jpg)
- [Inspected interval player](live-inspected-clip.jpg)

## Change

Agent returns observed_window with the exact ISO timestamps passed to video_understanding_iso. UI API maps these to observedWindow. The answer shows the dated local-time interval with time zone. Clip playback passes these absolute timestamps directly to the evidence endpoint. Recorded-file relative offsets retain their existing timeline mapping. The player explains the live answer inspects a recent recorded interval rather than the current frame.

## Validation

- 15 UI/API tests passed, including absolute-window propagation and exact start/end parameters on the live evidence request; app typecheck passed.
- Agent live inspection unit test now asserts returned timestamps. Full local pytest could not collect because NAT is absent. Actual-source AST contract probe passed with a stubbed tool: returned interval equals the model input.
- Full Agent Ruff lint passed; modified Python file formatting passes. Full-source formatting still flags five previously modified files. Configured mypy remains blocked by the Python 3.11 target versus installed NumPy typing syntax. No full Python test/typecheck pass is claimed.
- Agent restarted to load the code. After browser validation: all 31 core roles passed, 49.64 GiB available. Source still paused with embedding/detection/indexing false.

## Remaining

Mobile layout, retained-report handoff from this live result, broad model accuracy, sustained live ingestion and long rehearsal remain unqualified. Evidence uses the existing temporary clip storage path; it is not permanent retention. This receipt supersedes the missing-live-window/playback finding in live-preview-questions.md.
