# Event report handoff — September 28, 2026

Verified with Codex integrated browser, including 390×844 mobile viewport.

## Actual record

- Report: `afa08fcf-b4f2-4d50-a1ff-ef61dec5f108`
- Title: Conveyor replay — box-presence event review
- Event: `a02f86507251a9d877bc475edf06e5bf0a902350`
- Source: `6776f3a6-446f-4da8-832e-cfcf4507de8c`, Conveyor — Recorded Simulation (RTSP Replay)
- Exact bounds: `2026-09-29T00:59:35.846Z` → `2026-09-29T00:59:58.378Z`
- API verification: `inspection_source=retained_event_record`, `media_status=retained`, low priority, under review.

## Observed result

Saved from the real event viewer with reviewer notes. Open event report worked.
The report identifies the monitoring condition and explicitly says no new AI
analysis ran. Play exact clip displayed the retained footage; native controls
reached 0:22 / 0:22 with a box visible. A DOM video locator timed out, so no
new programmatic readyState measurement is claimed for this report page.
Copy briefing succeeded; actual clipboard contained the condition, saved event
record, original event ID, notes and evidence link. Back to demo returned Home;
temporary mobile viewport was reset.

Screenshots: [mobile form](event-report-mobile-form.png),
[retained playback](event-report-mobile-playback.png).

## Implementation and checks

EventReport.tsx builds a report from resolved source ID and exact event bounds.
ActivityInsightsWorkspace exposes the form after playable evidence and updates
the report list on save. The incident copy panel scrolls on small screens.
The investigations HTML/clipboard renderer distinguishes saved event provenance
from a saved AI answer. Retention messages reflect the API result.

Three focused Jest suites passed (15 tests): EventReport,
ActivityInsightsWorkspace and investigations. App TypeScript passed after the
final callback and renderer edits. No extra inference or runtime configuration
change was needed.

This validates one positive replay event and its report handoff. It does not
qualify negative-window accuracy, sustained monitoring, shorter cadence, Spark
scene reset or downloadable HTML/PDF delivery. See
[live event receipt](live-alert-event-proof.md) for the bounded alert run.
