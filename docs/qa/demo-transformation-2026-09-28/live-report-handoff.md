# Live answer → saved briefing — September 28

## Implemented

Timestamped single-source live answers now offer Save report. A compact form accepts a title and review notes. It saves the original question/answer, source identity and exact inspected ISO interval through the existing investigation API, initially under review with low review priority. It reuses the existing evidence-cache preparation and reports whether video was retained or still depends on source retention. Failure keeps the entered notes for retry. Report actions across live, search and Events now use same-tab navigation, avoiding the new-tab behavior that failed in Codex's integrated browser.

## Actual rehearsal

Home → Open camera stream → “What moves along the conveyor?” returned “Boxes move along the conveyor belt,” observed complete by 16.38s. Played its 25-second interval and checked a box on the conveyor and later outside the camera view. Saved **RTSP demo — conveyor movement**, adding simulation provenance and limits on condition/cause/destination claims.

Report ID `3dce054a-3af9-43ec-aaa0-26d97d660e53`. Stored evidence confirmed:
- Source `6776f3a6-446f-4da8-832e-cfcf4507de8c` — Conveyor — Recorded Simulation (RTSP Replay).
- Start `2026-09-28T23:48:35.034000Z`; end `2026-09-28T23:49:00.034000Z`.
- Disposition under_review; media_status retained.

Navigated away, found the saved report in Events & reports, and opened it with the normal link in the current Codex browser tab. Report playback reached 9.254/24.967 seconds, readyState 4, no error. Copy briefing succeeded; actual clipboard includes the question, review notes and #E1 link. The cache is evictable; this is not a permanent retention guarantee.

- [Saved answer state](live-report-saved.png)
- [Report playback and copy confirmation](live-report-playback.png)

## Validation and remaining scope

34 affected tests and app typecheck pass. Tests cover exact source/window mapping, invalid intervals, real API submission, retention messaging, save failure retry, and existing report/evidence flows. Desktop Codex browser exercised creation, persistence, report navigation, playback and clipboard. No new Python/runtime configuration changes. Core status after work: 31 roles, no failures, 49.65 GiB available. Continuous analysis remains paused.

New save-form mobile layout and HTML/PDF file delivery remain unverified. General model accuracy and sustained ingestion remain open; this handoff does not qualify those workloads.
