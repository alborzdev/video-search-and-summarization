# Focused RTSP questions and presentation — September 28

Source: Conveyor — Recorded Simulation (RTSP Replay), sensor `6776f3a6-446f-4da8-832e-cfcf4507de8c`. Codex integrated browser, desktop 1265×712, http://10.88.9.12:7777/?workspace=live.

## Fresh interaction

Live cameras → Focus conveyor → “What is visible on the conveyor?” → Send.

- First answer: “A cardboard box is visible on the conveyor belt.” Observed complete by 11.685 seconds. Consistent with the visible box, but the precise inspected clip was not replayed.
- Second fresh answer: “A white box with a red stripe is moving along the conveyor belt.” Observed complete by 14.848 seconds. Color detail is unverified; this is not an accuracy pass.
- Backend confirms real video_understanding_iso calls, 25-second windows, 30 sampled frames, reasoning false. First window 23:22:00.758–23:22:25.758 UTC; second 23:23:18.278–23:23:43.278 UTC. These are sampled completion observations, not a latency guarantee.
- Important gap: backend sets observed_range null for live requests. The UI consequently omits inspected times and Play inspected clip. Answers refer to the preceding 30-to-5-second window, not necessarily the currently displayed frame. Next work must expose that absolute interval and clip playback before describing this as a fully reviewable live answer.

## UI change

The technical intelligence panel previously covered a large part of the scene. It now starts collapsed on desktop as well as mobile, with an accessible expand/collapse button. Browser verified expansion reveals source status and Resume analysis; collapsing restores the unobstructed scene. Status says “RTSP feed · Analysis paused,” separating transport from continuous analysis.

Twelve OperationsWorkspace tests and app typecheck pass. Page identity/content, no framework overlay, expand/collapse interaction and actual playback verified in Codex browser; recent warning/error log empty. [Rendered result](live-conveyor-answer.jpg). Mobile not rechecked in this pass. Hot reload cleared the first answer; screenshot records the second answer.

Post-question runtime: 31 core roles, no failures, 49.64 GiB available. Agent still reports analysisActive false, state paused, embedding/detection/indexing false. No continuous ingestion or detector was enabled. Sustained live workloads remain unqualified.
