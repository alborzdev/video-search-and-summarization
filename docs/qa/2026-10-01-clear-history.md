# Clear history verification — October 1, 2026

The top bar and **System → Clear history** open one cleanup controller. A
read-only preview displays category counts and a cutoff. The explicit
**Clear all previous history** action starts a background operation with
per-step progress, completion or a truthful partial-failure result.

## Scope and continuity

Cleanup snapshots indexed moments, detections/tracks, past incidents, captions,
AI graph knowledge, completed live recordings, generated evidence clips, saved
answers/reports and event workflow states. It keeps cameras, monitoring rules,
source configuration, analysis profiles, settings, cached models and uploaded
source videos. It never calls source, capture, ingestion or model stop APIs.

Snapshots protect concurrent work: Elasticsearch uses point-in-time readers
and sequence-number checks; recordings are checked against immutable metadata
and physical files; graph nodes/relationships and evidence files are checked
again before deletion. Open recordings, cutoff-spanning intervals, new data,
updated records and fresh graph references survive. The last graph predecessor
can remain as an empty structural anchor, with old semantic content removed.

The app removes old visible answers/results and refreshes read-only evidence
lists after successful or partial cleanup. It keeps the live player mounted.
Closing progress does not stop cleanup. Repeated submissions return the same
operation. An interrupted operation cannot silently report success.

## Verification

- Disposable Elasticsearch fixtures: old content removed; newly created,
  late-arriving and updated records retained; repeated execution safe.
- Namespaced Neo4j fixtures: old knowledge removed; updated/fresh nodes and new
  references retained; empty predecessor and FIRST_CHUNK structure repaired.
- Disposable VST file/metadata fixtures: one old completed recording removed
  from disk and metadata; a new open recording retained. Only exact storage-file
  calls were used. Test fixtures were removed afterward.
- Evidence cache tests: new/regenerated files retained, exact old pairs removed,
  preview cancellation releases resources without deleting files. One host
  ffmpeg-dependent test is skipped because ffmpeg is unavailable on the host;
  the running evidence image includes ffmpeg.
- Backend history API: 15 focused tests; media/knowledge cleanup: 19; custom
  worker registration: 9 in the cached agent runtime; evidence service: 20
  collected tests, including the expected host-only skip.
- Spark helpers: 3 metadata, 6 bootstrap and 14 desktop tests passed.
- UI/storage/API final run: 45 tests in 7 suites passed. After a compact-screen
  layout correction, the two affected component suites passed 23 tests, including
  the new modal stacking regression. App strict TypeScript check passed.
- Additional affected workspace/event-hook tests passed earlier (80 tests).
  Scoped backend lint, format and type checks passed. Existing unrelated errors
  prevent claiming a clean full-agent lint/type-check run.

## Browser checks

Verified both entry points in the Codex in-app browser. At 1280 × 720, the
counts and confirmation controls fit. At 640 × 480, the dialog scrolls, its
actions remain visible, and the mobile navigation stays behind the modal.
The viewport override was reset afterward. The modal stays inside the app's
theme boundary but outside the header's stacking context.

The live-data Cancel check preserved exactly:

| Store | Before Cancel | After Cancel |
| --- | ---: | ---: |
| Indexed moments | 7,034 | 7,034 |
| Raw detections | 426,823 | 426,823 |
| Recording metadata rows | 831 | 831 |
| Open Elasticsearch search contexts | 62 | 31 |

This confirms Cancel released this preview's search snapshots while preserving
history. The private evidence cancellation endpoint is also called during
resource release. Invalid confirmation input returned HTTP 422 without starting
an operation. No browser console warnings or errors were recorded in the final
System preview check.

Screenshots are saved at:

- `/home/spark/.codex/visualizations/2026/10/01/vss-clear-history/desktop-preview.png`
- `/home/spark/.codex/visualizations/2026/10/01/vss-clear-history/compact-preview.png`

## Runtime and limits

The new CPU maintenance service and read-only localhost metadata bridge use
cached runtime components. Desktop startup starts them explicitly; desktop Stop
stops them. The bridge is not enabled at login. Its token remains private, and
the helper exposes no SQL or mutation interface. No downloads, image builds,
model restarts or memory-budget changes were needed; the Spark reserve remains
24 GiB.

The simulator publisher was unavailable during the cleanup verification. The
user requested completion with the stream offline. Existing demo history was
not cleared. The fixtures verify concurrency protections, but this receipt does
not claim a full live-stream reset/ingestion soak test.

The current generated-agent-report directory contains only retained source
configuration. Any future non-UUID agent report whose writer lacks the shared
locking contract is retained with an explicit warning/failure instead of being
deleted unsafely or counted as a successful cleanup.
