# Five-second diagnostic: empty inputs and an edge-entry miss

September28,23:15–23:16EDT. Same conveyor simulation replay and explicit any-frame
box-presence condition. Only diagnostic chunk duration changed10→5seconds;
four512×512 samples, overlap2seconds and generation settings remained unchanged.
The app's30-second default remains unchanged.

## Results from exact engine inputs

The50-second bounded run produced11 captures/responses, including startup and
cleanup time. All array hashes, shapes and response IDs verified. Manual review
of all44 frames:

| Windows | Captured content | Answer | Review |
| --- | --- | --- | --- |
| 0,3,4,5,8 | Clearly visible boxes | YES | Supported |
| 1,6,7,9,10 | No box in any of the four samples | NO | Supported within sampled input |
| 2 | Thin slice of an entering package at the right edge in final frame | NO | Boundary miss under the any-visible-frame condition |

Window2 request`bbd51dd0-a5b0-49b0-bc51-73c424149667`, frame3, contains the
package slice. This is actual input sent to the model, not a reconstructed
recording. The evidence places this particular mismatch at model interpretation
of partial visibility, rather than absence from the engine input. It does not
explain the older ten-second crumpled-box miss or establish a general root cause.
Do not count window2 as an empty-input success or claim all11passed.

## Timing and runtime

- First logged response5.939s after rule creation.
- Input cadence4.986–5.013s; response logs0.555–0.675s after last-frame NTP.
  This excludes downstream event/UI display latency.
- Maximum export overhead18.8ms.
- Minimum available memory54.267GiB across57samples;48GiB guard retained.
- Rule`42d30f55-489e-456a-be15-129e25a5668c` deleted; zero remaining rules and
  AI streams. Boot ID unchanged; diagnostic process35994completed successfully.

## Implication for the demo

Fast bounded local monitoring can distinguish clear box and empty inputs in this
sample, but the broader any-part-visible condition still misses an edge case.
Keep the five-second cadence diagnostic until repeated operation and event-to-UI
delivery are verified. Use the captured boundary case for a controlled follow-up,
not another unscored live run. A clearly defined demonstration region/visibility
condition may be appropriate, but must be stated and tested rather than silently
relabelling failures. Package damage recognition remains a separate unqualified
capability.

Evidence: `live-input-capture-five-second.json`,
`live-input-capture-five-second-timing.json`, and
`artifacts/live-input-capture-20260929-five-second/` at the repository root.
The latter contains lossless arrays, raw responses,44preview frames, contact
sheets and the manually annotated`review-index.json`.
