# Populated Insights audit — September 28, 2026

## Finding and change

The real direct-rule replay event appeared as “100% confirmed” in Insights,
despite the event viewer correctly calling it a model match. The page counted
all nine configured sources in its narrative although only one produced this
event. Its featured evidence path omitted events without attached media URLs.

Insights now separates direct model matches from model verification outcomes
and independent review state. Awaiting review counts only new, non-dismissed
events; acknowledgment does not alter model outcome. Dismissed candidates are
included in outcome statistics instead of a permanently zero dismissed row.
No outcome percentage is presented as accuracy. The narrative uses sources
with events, while the distinct configured-source metric remains explicit.

Added Activity at a glance heading and placed the featured event before the
chart, including events whose footage can be retrieved by source/time. Event
review has separate Model match and Verification passed filters. Chart labels
include date as well as hour, and its limited record scope is stated. Long
source names wrap. Mobile no longer hides the summary, and the rule/review
labels wrap rather than compressing the rule into a narrow column.

## Verification

- Codex integrated browser, http://10.88.9.12:7777/?workspace=events, default desktop and 390×844.
- Real state: 1 recorded event, 1 contributing source, 0 awaiting review, 1 direct model match; existing event acknowledged.
- Insights → Find footage opened the real event clip. Mobile Events & reports → Model match filter returned the same event → Find footage displayed its video through 0:22 / 0:22.
- Mobile summary and evidence action visible, no framework overlay or blank page. Console error/warning log returned empty.
- Two focused Jest suites: 11 tests passed, including acknowledged direct-rule outcome/filter distinction and evidence action. App TypeScript passed after final edits.
- DOM video inspection timed out; playback was verified visually, not through a new readyState measurement. Default viewport restored; no inference or runtime budget change.

Screenshots: [desktop](insights-model-outcomes-desktop.png),
[mobile overview](insights-model-outcomes-mobile.png),
[mobile event evidence](insights-mobile-evidence.png).

## Remaining scope

This is one populated replay event, not a multi-source or sustained analytics
qualification. Faster alert cadence, repeated positive/negative scoring,
Spark scene/reset and complete rehearsal remain open. Model verdicts remain
backend records; this UI change does not change model accuracy.
