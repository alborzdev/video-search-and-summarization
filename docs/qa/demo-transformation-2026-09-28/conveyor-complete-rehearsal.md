# Recorded visitor journey — September 28, 20:00–20:03 EDT

The current presenter path was exercised in Codex's integrated browser at
http://10.88.9.12:7777/, desktop viewport. This is one approximately three-minute
operator rehearsal with a repeated fresh question, not a sustained-load or
latency-percentile qualification. No models, source collection or budgets changed.

## Actual journey and observations

1. Home → Conveyor — Box Movement → Find a box moving on the conveyor.
   One ten-second result appeared by 3.185 seconds including UI navigation.
   Source `fb7dd760-dc03-4a43-9d5b-97225f9bc2d4`, offset 0:00.
2. Play clip: observed playback at 7.550/10 seconds, readyState 4, no error.
   The cited replay was also inspected at its beginning with the box visible.
3. Ask about this clip → “What moves?” → fresh answer:
   “A box moves along a conveyor belt.” UI local analysis 8.0 seconds.
   First completion observation was at 27.0 seconds because the browser's
   element wait stopped early after three seconds and the next observation was
   delayed; do not interpret 27.0 as precise request latency.
4. Reviewed the citation and saved **Conveyor walkthrough — reviewed movement**,
   manually selecting low priority / under review and adding simulation provenance
   and limits on condition, destination, jam and safety claims.
5. Repeated the exact fresh question in Search. Same answer, 7.6 seconds local
   analysis; observed complete by 9.691 seconds. This was a new inspection, not
   a saved response. The earlier saved report remained separate.
6. Events & reports → the saved report → Open report → Play exact clip.
   Retained playback reached 10/10 seconds, ended true, readyState 4, no error.
7. Copy briefing: actual clipboard contains question, answer, qualified notes,
   review status, recording-relative label and absolute #E1 evidence link.
8. Back to demo: returned to populated Home, recording playback controls and
   online RTSP invitation. Page title Vision Intelligence, no framework overlay;
   recent warning/error log empty.

Saved report ID: `f7bacd8b-d09e-4fd5-8db8-46e1f9ca12fe`.
The stored report starts under review; video is retained in an evictable local
cache. The original footage is a recorded simulation, not a live event.

## Runtime evidence

Core checks before and after: 31 roles, no failures. Available memory snapshots
49.53 / 49.52 GiB. Guard active at both checks. Boot ID unchanged:
`ac75a3b5-980a-41c5-8301-200423326f72`.

The guard's actual telemetry covers the 177-second search-to-return interval
with 176 samples, maximum gap 1.069 seconds, minimum available memory **49.085
GiB**, maximum 49.815 GiB, maximum thermal-sample age 1.0 seconds. The current
48 GiB floor was preserved. [Machine-readable summary](rehearsal-memory.json).
Disk remains 99% used, approximately 12 GiB available; no cleanup performed.

## Findings and remaining scope

- The recorded main story completes with real footage, fresh answers, persisted
  review notes, playable evidence and copied links.
- Search's save form defaults to medium/open whereas the new live form defaults
  to low/under review. This creates an unnecessary configuration step for a
  routine demonstration briefing; reconcile defaults in a subsequent UI pass.
- Returning from a standalone report resets Home to the default warehouse
  recording. This is understandable but does not preserve the chosen demo chapter.
- One three-minute rehearsal and two answers do not establish sustained
  presentation readiness. RTSP, populated monitoring, model failure cases,
  mobile save forms and export-file delivery retain their separate open gates.
- No source edits in this rehearsal, so no redundant unit test run.

[Repeated fresh answer](rehearsal-repeat-answer.png) ·
[Report playback/copy state](rehearsal-report-copy.png).
