# Progressive selected evidence — September 28

## Customer-facing change

Completed per-clip observations appear with playback citations while remaining
clips and the comparison are still processing. The UI calls these “Results so
far”, keeps the final answer separate, and exposes report saving only after a
complete response. On interruption it preserves already received observations
under an interruption label and offers retry. Evidence changes invalidate stale
progress using the existing request revision.

JSON clients remain supported. The browser requests an NDJSON stream; the agent
emits inspection, complete or error events. The app proxy drains the upstream
response even if the browser disconnects, keeping its Cosmos reservation through
processing. Agent stream closure cancels and awaits its task, releasing admission.
No parallel model calls, additional GPU budget or live ingestion were introduced.

## Real timing evidence

The [real two-clip stream](two-clip-progressive.json) used the identical 0–5/5–10 s
warehouse request from the comparison audit through the public app URL:

| Event | Arrival |
| --- | --- |
| E1 inspection | 13.462 s |
| E2 inspection | 25.990 s |
| Complete comparison | 27.581 s |

Early delivery is demonstrated through the proxy. Total latency is a single
sample and may include warm-cache effects; do not attribute the entire difference
from 30.762 s to streaming or claim a general latency percentile. The first useful
observation arrives before completion instead of sitting behind synthesis.

## UI and tests

- Real browser search initially failed during verification; retry returned HTTP
  200 and usable evidence. The transient failure's cause is not established.
- Browser selected the real grouped 0–10 s clip, asked a question, consumed the
  stream and displayed its completed answer with E1 and Save investigation.
- A clearly labeled temporary UI fixture held the partial state for visual
  inspection. [Screenshot](progressive-inspection-fixture.png) shows the fixture
  explicitly. Its citation opened the matching recording dialog; no Save control
  appeared. Fixture fetch override was removed and page reloaded afterward.
  Single-clip wording was subsequently corrected to “answer” rather than
  “comparison”; multi-clip wording remains “comparison”.
- 12 backend tests passed: callback delivery, progress before completion,
  reservation lifetime and generator cancellation, plus previous analysis cases.
- 30 distinct UI/API tests passed across four suites (28 in the initial run,
  followed by both updated suites after adding two cases). Includes fragmented
  stream parsing, truncated/error streams, partial UI state and proxy reservation.
- App TypeScript and diff checks passed. Agent-only restart applied the backend.
  [Core status](progressive-runtime-status.txt) records post-validation readiness.

## Unresolved accuracy and acceptance

The real 0–10 s browser answer said both holding the box and “has just placed it
on the shelf above him.” That contradiction is not fixed by streaming. D22 stays
open. Do not present response delivery as proof of factual correctness.

The two-clip API result and single-clip browser result do not qualify multi-source
selection, sustained live ingestion, actual alert latency or the business story.
Audience and current Spark RTSP scene details are still awaiting user input.
