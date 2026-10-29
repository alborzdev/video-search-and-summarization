# MV3DT saved-data audit — 23 October 2026

**Decision: retain the failed promotion gates.** Both historical two-camera runs reproduce their saved metrics exactly. There are real evaluator limitations, but the available evidence does not support blaming the failures on a swapped camera, a source-index mistake in our adapter, or clock/session mixing. The person-plane run contains a repeated simultaneous ID conflict even in image-space matches with no competing candidate under the original matching gate.

This audit ran on saved NDJSON and calibration files only. It did not start a model, change a tracker, restart a service, edit the scene, or supply actor truth to the live system. The original comparisons and thresholds are unchanged. The active camera-local pipeline is outside this audit's mutation scope.

## Evidence and reproducibility

| Run | Road plane | Person plane |
| --- | --- | --- |
| Saved run | `mv3dt/probe-20261023T043825Z` | `mv3dt-person-plane/probe-20261023T044318Z` |
| Observation count | 2,200 | 2,200 |
| Matched person observations | 5,441 | 7,419 |
| Native position median / p95 | 0.520 / 1.349 m | 1.225 / 2.322 m |
| Same-ID paired matches | 732 / 1,333 (54.9%) | 5 / 2,165 (0.23%) |
| IDs assigned more than one actor label | 6 | 9 |
| Original result | Failed | Failed |

Runs live below `.spark/city/state/native/`. The offline labels are `evaluation-ground-truth-1792730163503929787.ndjson` and `evaluation-ground-truth-1792730597793823324.ndjson` in `/home/sparkdev/isaac_city_sim/logs/vss-integration/`. Their SHA256 values match the original comparison receipts. Both new JSON audit receipts record those hashes and the observation hashes. The package, both camera files, tracker configuration, promotion gates and broker topic configuration still match the hashes saved at invocation. Camera order in the package matches the ordered `--source` arguments.

Supporting files:

- [Road-plane audit](qa/smart-city-2026-10-23/mv3dt-road-plane-offline-audit.json).
- [Person-plane audit](qa/smart-city-2026-10-23/mv3dt-person-plane-offline-audit.json).
- [CPU audit replay](qa/smart-city-2026-10-23/mv3dt-audit-replay.py), which only reads saved diagnostic inputs and writes the two audit receipts.
- [Original road comparison](qa/smart-city-2026-10-23/mv3dt-road-plane-comparison.json) and [original person comparison](qa/smart-city-2026-10-23/mv3dt-person-plane-comparison.json).

## What the camera and time audit rules out

Each scored camera has strictly increasing RTCP-derived timestamps and one source session. Each run has one fusion epoch. There is no reuse of a second-camera observation by multiple accepted first-camera pairs in these runs. The source-pair p95 skew is 1.617 ms and 0.887 ms respectively. Thus the evaluator's assumptions about ordered observations and a single ID epoch happen to hold for these files.

The native adapter copies the full `NvDsObjectMeta.object_id` into both `localTrackId` and `native3D.targetId` as a decimal string. It uses `frame->source_id` to select the configured source; it does not export that source index as a target ID or truncate object IDs itself. The diagnostic tracker uses `useUniqueID: 0`, late reassociation and ID correction. The field name `localTrackId` is therefore misleading in diagnostic MV3DT mode: it is the SDK's current target ID, whose correction and namespace semantics must be preserved by any future adapter. Equality alone is not proof that the association is correct.

NVIDIA documents that the lower ID counter is shared across streams in one tracker instantiation, including with `useUniqueID: 0`. This worker has one tracker and no sub-batches. Ordinary per-camera numeric collisions therefore do not explain the simultaneous same-ID conflicts in this single diagnostic epoch. MV3DT can propagate or correct IDs during association. Sources: [DeepStream 9.2 target ID management](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker) and [MV3DT ID correction](https://docs.nvidia.com/deepstream/text/DS_MV3DT).

There is a remaining timing limitation. The offline writer samples actor roots when it queues both camera images. The encoder assigns PTS from that capture timestamp, but the saved evaluator joins RTCP-derived source time to the nearest actor sample. It does not join an encoded frame identifier to an exact capture record. Nearest actor samples are typically later by 39.4 ms and 36.2 ms, with signed p95 offsets of 55.9 ms and 56.7 ms. Shared low cross-camera skew does not independently prove absolute alignment to actor labels or exact render-to-root synchronization.

A diagnostic sensitivity check keeps every original assigned actor fixed and looks up its position at offsets from −250 to +250 ms. Road native median/p95 ranges from 0.502/1.342 m to 0.562/1.370 m; person-plane ranges from 1.197/2.266 m to 1.266/2.396 m. No offset is adopted. The person-plane error is too large to dismiss as this modest timing offset, and neither p95 gate becomes acceptable in this check.

## Ambiguous matches versus identity failures

The existing evaluator projects every simulator root that lies in the camera image. It does not have independent occlusion/visibility labels. Its visibility filter is the tracker's estimate, not ground-truth visibility. Its global one-to-one image assignment can also assign an object to its second-best root to avoid a duplicate label. Therefore its `falseMergedNativeIds` value is an alarm: it combines genuine merges, label ambiguity, ID changes and possible tracking errors. It is not a verified count of physical people merged.

For diagnosis only, an **isolated image match** has exactly one candidate root within the existing normalized distance gate, and that root has exactly one eligible detection within the same gate. This definition uses neither native world coordinates nor desired outcomes. It does not prove visibility. All original samples remain in the original promotion result.

| Diagnostic | Road plane | Person plane |
| --- | --- | --- |
| Isolated image matches | 4,968 / 5,441 | 6,618 / 7,419 |
| Assigned matches not isolated | 473 | 801 |
| Assignment chose a non-nearest root | 16 | 15 |
| Native median / p95 in isolated matches | 0.534 / 1.284 m | 1.278 / 2.383 m |
| Isolated same-ID camera pairs | 630 / 1,188 | 2 / 1,831 |
| Same-ID pairs with different actor labels | 16 | 30 |
| Such conflicts isolated in both views | 1 | 22 |

The person-plane conflicts all involve SDK ID `25`. In 22 image-isolated camera pairs, it is assigned to `Character_07` in one view and `Character_06` in the other. Their simulator-root separation has median 2.585 m and maximum 3.541 m. The two native positions have median separation only 0.300 m. The first such pair has roots 2.060 m apart and native positions 0.086 m apart. This is much stronger evidence of a bad cross-view association than a single ambiguous label at an occlusion. It still merits review against retained camera pixels before it is treated as a human-verified identity label.

There are no duplicate eligible person IDs within a single saved frame. Across camera views, however, separate IDs persist for the same assigned person: the same-ID fractions above show the problem directly. Per actor, the road run has 3–9 distinct assigned SDK IDs and the person run 4–9. There are 48 and 49 same-camera actor-ID changes with gaps no larger than 500 ms; 26 and 22 occur between isolated matches. These counts include late SDK ID correction and evaluator label changes. They are not a formal fragmentation or IDF1 score.

## Native position versus ground-anchor position

Projecting the SDK's own image-foot location through the supplied ground homography agrees closely with its world-foot output: median errors are 0.022 m and 0.021 m. This supports the adapter's coordinate units and camera mapping; it does not establish that the estimated foot is on the correct person.

The SDK world-foot estimate differs substantially from the detector box-bottom ground anchor. In the person-plane run, isolated box-bottom errors are 0.445 / 0.965 m median/p95, while isolated native errors are 1.278 / 2.383 m. The cylinder/foot estimation, association, calibration-height assumptions and state-estimator settings need investigation together. The road and person runs were recorded at different times; their difference is not a controlled same-video A/B comparison of only the ground plane.

Using camera-local box-bottom projection while experimentally studying SDK IDs can be an explicitly different candidate. It cannot be described as a passed MV3DT native-position pipeline, and its ID-quality gates still need to pass independently.

## Evaluator corrections made in this audit

`tools/smart-city/evaluate_mv3dt_probe.py` now refuses malformed or incomplete NDJSON rather than silently dropping lines that do not end in `}`. It accepts valid trailing whitespace, which the old parser silently skipped. It rejects non-monotonic scored source times, mixed source sessions, mixed fusion epochs and observations from an unexpected source. It requires exactly two distinct cameras and finite nonnegative warm-up time.

The evaluator also verifies calibration-package and promotion-gate hashes against the saved invocation. Missing pinning evidence produces a failed `inputIntegrity` check; changed pinned files stop evaluation. This prevents rescoring old output against silently changed geometry or thresholds. No accuracy threshold or matching rule was relaxed. All original checks reproduce the same outcomes, and the added integrity check passes for both saved runs.

The focused regression suite passes **14 tests in 0.03 seconds**. The bounded saved-data audit takes about one second. These are CPU checks, not a runtime or endurance qualification.

## Recommended next test

Capture one bounded paired-camera episode with exact per-access-unit PTS/DTS and original RTCP reference timestamps, plus the separate held-out actor-label trace. Preserve source identity, clock discontinuities and capture metadata. Retain both camera pixels. Do not infer synchronization from a common recorder start or independently zero both camera clocks.

Replay that identical episode for the existing road-plane and person-plane tracker configurations. Before interpreting identity scores, verify independent visible image landmarks and frame-to-label timing. Review a fixed evidence list that includes person-plane ID25's conflict interval, same-person different-ID intervals, and occluded intervals; mark uncertainty explicitly, without deleting inconvenient samples. Keep the existing identity, position and runtime gates. This single controlled replay separates scene variation, time alignment and configuration effects far better than another live run with different traffic.
