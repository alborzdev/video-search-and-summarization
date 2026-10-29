# Smart City map and rule correctness review

Reviewed 2026-10-23 during the improvement sprint. This work used CPU tests and saved evaluation data. It did not start a simulator, run a model, change calibration or enable global tracking. Deployment/restart and integrated qualification are recorded separately by the sprint owner.

## Defects fixed

1. **Tracker predictions could preserve known occupancy and dwell through a long blind interval.** Each predicted object updated the frame timestamp, and the rule engine used that timestamp as the last observation. A test with one detection followed by four prediction-only frames stayed `active` after the 200 ms observation limit. A separate dwell test triggered immediately on reacquisition after a 500 ms prediction-only interval. The engine now tracks the last actual detection independently of frame identity. Both cases become unknown after their allowed observation gap, and reacquired candidate dwell starts from the new detection. Exact preview frame timestamps and consecutive-observation velocity are unchanged.
2. **An image-space wrong-way alert could clear when metric projection became unavailable.** The image velocity remained available while the required metre speed became unknown. The previous code treated that as a known false condition. It now preserves `unknown`; the regression crosses the map's calibrated extent while remaining inside the image rule.
3. **Valid equivalent homography scales could hide map positions.** Validation normalized matrix coefficients, but projection used their original scale. A valid matrix multiplied by `1e-12` or `1e308` passed validation but returned an unstable projection. Projection now uses the same normalized coefficients. Small, large and negative scalar multiples agree; singular and horizon cases remain rejected. The actual saved camera matrices change projected positions by less than `4.5e-14 m` in the audit below.
4. **Exact preview metadata omitted person-plane calibration.** The backend preview source whitelist now retains `classImageToGroundHomographies`. A regression verifies the original road matrix, the person matrix and the correct person position survive the envelope, while private source credentials remain excluded. The UI proxy and client context checks are handled by the other sprint changes.
5. **An already active duration alert resumed too early after observation loss.** A single reacquired condition previously restored `active`, regardless of `minimumDurationMs`. The unresolved incident keeps its ID, but the fresh continuous interval must now meet its duration requirement again. Zero-duration rules still resume immediately. An unknown event also stays unknown during clear hysteresis instead of reporting a misleading active metric.
6. **Source stalls could be hidden by a media clock resuming one frame later.** Source loss now resets duration candidates, clear candidates and pending line segments even when no health poll ran during the stall. The first reacquired frame cannot derive velocity across that wall-clock loss. Regressions cover both with/without health polling and reject a phantom crossing across the gap.
7. **Historical duration counted blind intervals as observed time.** A historical event with an unknown interval previously displayed selected time minus its original start as observed duration. It now returns unavailable duration for that discontinuous history, while retaining the original proven `triggerMetrics` and state transitions. Continuous pre-gap history still reports its observed duration.
8. **Aggregate rules bypassed two loss guards.** Independent review reproduced an occupancy/queue candidate triggering across a 600 ms source-clock gap despite its 200 ms maximum, and known occupancy recovering from a wall-clock stall with no new detection. Camera-wide frame gaps now reset the aggregate candidate as well as per-track candidates. Rule speed proof also respects the rule's observation-gap limit. Wall loss invalidates retained occupancy evidence until a fresh detection arrives, while retaining uncertainty instead of inventing a clear. Regressions cover missing and prediction-only recovery, an already active aggregate, and a reacquired extra track that must not reset an aggregate already proven by other continuously observed tracks.
9. **Track eviction erased unresolved aggregate membership.** After the 15-second display-track TTL, an unknown occupancy incident could clear on the next empty frame. Aggregate rules now retain bounded unresolved identities after track eviction, resolving an identity only when its valid geometry is actually observed again. Enough known qualifying objects can still prove the threshold; an unrelated outside object cannot resolve a lost member. The set is bounded by the existing maximum-track setting. Overflow remains unknown until a source/session/configuration reset. Tests cover expiry, continuous proof from another object, the bound and reset.

Files changed here are `apps/city/engine.py`, `geometry.py`, `preview.py`, `tests/test_city.py` and `tests/test_preview.py` under `services/analytics/behavior-analytics`.

## CPU validation

The initial three gap/wrong-way regressions and the follow-up duration/clear/source-stall/aggregate regressions failed before their fixes with the incorrect outcomes described above. After the fixes, all **109 city backend tests passed**:

```sh
/tmp/vss-city-backend-test-env/bin/python -m pytest -q services/analytics/behavior-analytics/apps/city/tests
```

The suite has one existing Starlette/httpx deprecation warning. It includes the preview API, source/session resets, durable history, rules, synthetic geometry and all seven event families. The fixture's exact floating-point coordinate equality was changed to a `1e-12 m` absolute tolerance after normalization produced a `4e-15 m` rounding difference; no event or runtime threshold was relaxed.

## Saved episode audit

[The receipt](sprint-map-offline-audit.json) records hashes for the original 3,701 observation frames, separate evaluation-only actor labels and camera package. [The reproducer](sprint-map-offline-audit.py) reads only those files:

```sh
/tmp/vss-city-backend-test-env/bin/python docs/qa/smart-city-2026-10-23/sprint-map-offline-audit.py
```

| Camera | Matched person samples | Position median / p95 | Consecutive speed pairs | Absolute speed error median / p95 |
| --- | ---: | ---: | ---: | ---: |
| Southwest | 4,682 | 0.391 / 0.934 m | 3,759 | 0.271 / 1.653 m/s |
| Northeast | 3,696 | 0.450 / 0.965 m | 2,876 | 0.273 / 1.479 m/s |

Labels are assigned independently in image space with the existing one-to-one assignment method, confidence at least 0.55 and a maximum normalized cost of 1. Speed comparisons require consecutive source frames, the same local track and person label, and both timing intervals above zero and at most 0.3 seconds. Occlusion can make these labels ambiguous. The speed values are diagnostic and are not a validation of vehicle speeds, rule thresholds, missed detections, collision distance or field accuracy.

These results support retaining the camera-local baseline and labelling speed as estimated. They do not support promoting MV3DT, adding a site-wide unique count, or hiding coordinate uncertainty with untested smoothing. Existing fusion failures and promotion gates remain unchanged. Actor labels stay in offline evaluation and never supply operational detections, map markers or events.
