# Camera evidence fixes for the v3 junction

The northbound movement counter missed real vehicles because its finite entry
line did not cover their observed bottom-centre box anchors. A separate stopped
vehicle issue made a confirmed incident become unknown after one missed frame.
Both fixes preserve the existing camera, model, tracker and one-second gap limit.

The [sanitized receipt](v3-entry-and-stopped-evidence-fixes.json) contains exact
source and input hashes, test commands, replay results and remaining limits.

## Northbound entry

The original line ran from `[-23.62,66]` to `[-20.12,66]`. In 3,796 actual SW
camera observations over 359.559 source seconds, continuous northbound cars
crossed the infinite line at x −23.84 and −24.00, and a bus at approximately
−24.23. All were outside its finite west endpoint. Their real observation gaps
were below one second. They reached valid north or west exit gates, but no
journey could start.

The reviewed change extends only the west endpoint by 0.75 m, to `[-24.37,66]`.
The other endpoint, crossing direction, classes, hysteresis, gap policy, all other
18 rules and the six-item mobility configuration remain unchanged. The line still
precedes the physical turn arcs. The adjacent southbound lane centre and a
retained outside-anchor crossing at x −25.71 remain outside it.

An isolated replay through the actual `CityEngine` produced five entries and
three complete journeys: one bus through and two cars left. The old line produced
zero. Class changes and later observation gaps still produce incomplete records;
the replay did not invent a right turn. The parent subsequently reported actual
live rule426/native19 acknowledgement and two through plus one right journey in
a separate cohort; see its `v3-live-movement-through-right` receipt and screenshot.

Cold site generation now uses this west-only margin. The migration accepts only
the exact known old69.6 m, narrow66 m and reviewed wide66 m generated forms. It
still rejects a changed operator line. Five retained camera-anchor examples test
three northbound positives and two direction/finite-segment negatives. No
simulator actor identity or position is supplied to the camera analytics.

## Brief losses during a stopped incident

The held car retained local SDK ID `5527462707671859405` and class `car`. The
incident became unknown at source sequence4307, after sequence4306 missed it.
Only 0.299 seconds separated the real sightings. The old code discarded real
motion history on a prediction and required the immediately previous frame to
be observed. Speed therefore became unavailable on reacquisition, which broke
the stopped rule and required the full duration again.

The engine now retains its bounded real-only motion samples. Predictions add no
sample and publish no speed. A real observation can resume speed only within the
existing one-second source gap and wall freshness, with the same source session
and class. Invalid projection, longer loss or a changed identity breaks proof.

A brief loss keeps the incident identity with separate `stopEvidenceStatus`
`pending`. The rule metric is unknown and the UI says **Checking evidence**.
Fresh movement or an observed exit uses the existing clear hysteresis and says
**Checking clearance**. Pending incidents do not count as confirmed active events.
Only a fresh real stopped observation can confirm the condition again.

Observed duration accumulates only between consecutive fresh stopped samples.
The obstruction aggregator also requires a confirmed stop at the exact current
source time. Pending, missing, moving and clearance-check intervals do not add
blocked time. Historical replay does not substitute elapsed incident age for
continuous proof after a gap.

The exact 260-frame retained-camera replay preserves the original event ID,
recovers from eight brief losses, and records 9.316 seconds of observed blocked
time. A ninth pending boundary ends in a genuine loss longer than one second
after release. It remains unknown. A simulator release does not prove a camera
clear. The retained first-tracker boxes do not establish whether a missing frame
was caused by the detector, the local tracker or their interaction.

## Verification and deployment boundary

The combined city CPU suite passed255 tests, including13 new stopped-evidence
tests and the separate pedestrian agent's changes. Site and movement controls
passed25 tests. Fatal Ruff and scoped mypy passed. The49 focused React tests and
the strict whole-app TypeScript check passed in a bounded CPU-only container.
An independent backend review found no blocker and repeated16 stopped/motion
tests successfully. A separate reviewer repeated all49 UI tests successfully
and reported259 city tests passing after adding four actual-ingest pedestrian
controls; the stopped engine and aggregator hashes stayed unchanged.

This subtask made source and private review artifacts only. The parent owns the
consolidated backend/UI deployment and actual rendered-browser acceptance. These
retained replays are regression evidence, not a held-out detector accuracy study
or a production qualification.
