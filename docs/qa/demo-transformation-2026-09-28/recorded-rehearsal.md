# Recorded-path rehearsal — September 28, 17:55–17:58 UTC

Scope: Home → source-scoped search → playback → select evidence → fresh visual
analysis → save investigation → Events → reopen report → retained clip playback.
Export was verified earlier, not repeated in this run. This is not a live-camera
or sustained-ingestion qualification.

## Runtime and inputs

- Core manager: 31 roles, no reported failures. Available memory before: 49.68 GiB;
  after analysis: 49.81 GiB. These are endpoint samples, not a peak-memory trace.
- Memory guard active before and after. The 48 GiB diagnostic floor was unchanged.
- Admission allowed evidence_analysis; Cosmos reservation inactive before the run.
  Admission GPU-utilization telemetry was unknown, so no utilization claim is made.
- Boot ID read after run: `ac75a3b5-980a-41c5-8301-200423326f72`. No before-run boot
  ID was collected, so this receipt does not establish unchanged boot ID by comparison.
- Source: `edfe78cd-2a6d-47c2-8317-57e1ade9aafc` / Qa Recovery 20260928.
- Query: `people moving`. Actual selected range: `2025-01-01T00:00:00Z` through
  `2025-01-01T00:00:05Z`; displayed correctly as 0:00 into recording.

## Observed results

| Action | Observed result |
| --- | --- |
| Home Find people in this recording → matching clip available | 923 ms, one five-second result |
| Play clip | Five-second video advanced while playing; start latency not separately measured |
| Analyze selected evidence | HTTP 200; complete rendered answer in 15,244 ms |
| Backend stage timings | Inspection 15,000.7 ms; synthesis 0.1 ms; total 15,000.7 ms |
| Provenance | `fresh_cosmos_inspection`, one E1 citation; no cached answer used |
| Save investigation | HTTP 201, low severity, resolved, explicit QA notes |
| Events → saved report | Newly saved title present; report opened |
| Report clip | Duration 5 seconds; currentTime advanced; paused=false |

The generated answer describes a person moving a box toward warehouse shelving.
This run proves the request/response and evidence linkage, not correctness of
every detail in the model's description. Human review remains necessary.

## Artifact

Saved development record: `04e7d61f-17d2-44da-ae2d-ec064629b61c`.
[Device report](http://10.88.9.12:7777/api/vision/investigations?id=04e7d61f-17d2-44da-ae2d-ec064629b61c&format=html)
and [screenshot](rehearsal-report.png).
Media status retained; cache key
`d626dc3483c9d1b91c86cf18a6f2891ba2326861a25050fa916b7e0c58647bbb`.
This local cache is evictable, not permanent archival storage.

## Execution notes and remaining work

The first form locator used the visible title rather than its actual accessible
name, Investigation title, and timed out before writing or submitting. Corrected
locators completed the save. An initial localhost:7777 probe failed; the documented
LAN host succeeded. Neither failure triggered a service restart.

This is a single sample, not a latency percentile or a complete demo acceptance
result. Live feed recovery, event generation, sustained memory behavior, scenario
alignment, full populated analytics and audience rehearsal remain open.

## Follow-up accuracy inspection

Frame inspection at 0.1, 2.5, 4.7 and 4.96 seconds supports a worker carrying a box
and approaching the rolling steps. The final frame still shows the box in the
worker's hands. The saved answer's assertion that the worker places the box on
an elevated platform is not supported by this selected interval. The original
report is preserved as the actual model output, not silently rewritten.

[Final frame](rehearsal-final-frame.png). Intermediate enlarged inspection used
a temporary browser-only layout change; it was discarded by navigating away.
This finding is tracked in the progress log and prompted a temporal-grounding
instruction change. A citation alone does not establish factual correctness.
