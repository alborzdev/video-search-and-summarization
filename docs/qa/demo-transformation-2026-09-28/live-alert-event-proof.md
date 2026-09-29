# Bounded replay alert → event → evidence, September 28

## Actual run

Created **Replay diagnostic — box presence — 2026-09-28** through the Codex
integrated browser's rule builder. Source: Conveyor — Recorded Simulation
(RTSP Replay), `6776f3a6-446f-4da8-832e-cfcf4507de8c`.
Condition: “Is a box visible on the conveyor belt? Answer YES or NO only.”
Severity: Information. No external notification: checked deployed OpenClaw
webhook enabled=false before activation. No detector was started.

The local watchdog checked that no existing visual rules were active and host
availability was at least 49.3 GiB. It bounded this diagnostic to 90 seconds
from observing the new rule, with early cleanup below 48.75 GiB. This is an
additional diagnostic cutoff, not a change to the persistent 48 GiB guard.

- Backend rule: `dcf041ca-a4d5-4847-9dce-06390212a004`.
- Local rule: `35a039d9-9b83-438a-bfcd-68e9843a6ab1`.
- Backend active: 2026-09-29 00:59:09.182Z.
- Responses: NO at 00:59:29.033Z, YES at 00:59:58.953Z, NO at 01:00:28.959Z.
- Positive interval: 00:59:35.846Z–00:59:58.378Z.
- Incident: `a02f86507251a9d877bc475edf06e5bf0a902350`.
- [Raw event](live-alert-event-payload.json), [caption log](live-alert-caption-log.txt),
  [watchdog samples and cleanup](live-alert-bounded-run.json).

The watchdog stopped the runtime rule successfully, did not resume history,
marked the local diagnostic record paused, and confirmed no live rules remain.
RT-VLM stream count after cleanup was zero. The 108 pre-cleanup samples ranged
49.558–50.022 GiB available; no early cutoff or cleanup error occurred.
The sample series does not cover every moment of cleanup itself.

## Real defect discovered and fixed

The event arrived in Events & reports, but its card disabled playback as
**Timing only** because it lacked snapshot/videoSource fields. The viewer
already knew how to retrieve footage by source and exact time; the card gate
prevented access. A valid source/time interval now offers **Find footage**.
This makes no claim that footage is retained until retrieval succeeds. Invalid
or absent intervals without attachments remain disabled. Failed retrieval now
explains that footage may be expired or the video service unavailable.

Direct visual-rule triggers now say **Model match**, retain the backend verdict,
use the rule's readable title, and ask for footage review. The model trigger is
not presented as a human-reviewed conclusion. Aggregate backend-verdict counts
remain unchanged; workflow state separately records operator review.

In the browser, Find footage opened the real event's exact interval. The video
reported 22.5333 seconds, readyState 4, no error and advanced to 14.436 seconds.
Seeking to the beginning using native video controls visibly showed the box on
the conveyor. This supports the positive box-presence condition; the two NO
intervals were not independently reviewed and are not claimed correct.

Clicked Acknowledge after inspection. The dialog changed to Acknowledged and
the event left the default Needs attention filter, while remaining accessible
through other review filters. No incident was deleted or resolved.

[Before](live-alert-timing-only-before.png),
[playable positive evidence](live-alert-event-footage.png).
Ten focused component/model tests and app TypeScript check pass.

## Timing correction and remaining work

The earlier preflight overstated that a full 30-second window must elapse
before any response. In this run, four sampled frames span about 22.531 seconds;
responses were generated roughly 0.6 seconds after the last sampled timestamp,
on a 30-second cadence. The first response arrived about 24.5 seconds after rule
creation. The first YES arrived about 54.5 seconds after creation because the
first window returned NO. These are log-derived observations, not a complete
UI latency or general inference benchmark.

This is a successful bounded replay condition → model trigger → event →
playable evidence → acknowledgment path. It does not qualify sustained
monitoring, all scene conditions, false-positive/negative rates, concurrent
inference, a shorter cadence, or the Spark/reset workflow. The event dialog
still lacks a direct save-report handoff; that is the next concrete UI gap.
