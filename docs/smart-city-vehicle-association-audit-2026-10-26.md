# Vehicle map association audit — 2026-10-26

**Decision: retain camera-local vehicle markers and the existing guarded person
joins. Do not deploy the vehicle geometry prototype or change live anchors.**
SDK world-foot positions are a better vehicle-center candidate than the current
rect-bottom homography. However, correct native ID agreement is still low, and
the strict geometry alternative covers only about 7% of the evaluable car pairs
in this short run. That does not justify presenting an all-vehicle fusion
feature. No association threshold, model, camera, source input, map anchor or
live UI/backend was changed for this audit.

## Evidence capture

The normal-flow capture is preserved at:

```
.spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/
  vehicle-gt-normal-1792992512654735340/
    manifest.json
    ground-truth.ndjson
    observations.ndjson
    evaluation.json
    geometry-evaluation-checked.json
    calibrations.json
    artifact-identities-final.json
```

The parent task kept scenario episodes idle for this window. The recorder ran
for 60.043 wall seconds and saved 181 world-pose snapshots at a 3 Hz target rate,
plus 1,725 existing native observations (7.66 MB). It stayed within one scene,
controller generation, source session per camera and native fusion epoch
`d2b1cdad-02fb-4f97-92f9-d55aedd29b79`.

The new helper
`/home/sparkdev/isaac_city_sim/scripts/tools/inspect_vehicle_ground_truth.py`
reads the actual world translation of each active vehicle slot and its stable
arrival ID. It also reads the controller model position, asset, dimensions,
heading, scenario ownership and wall/simulation clocks. All sampled actual
world positions agreed with the model to **0.0 m**. All 181 snapshots were
playing, with no active episode or owned scenario hold. Median helper execution
was 0.300 ms, p90 0.392 ms and maximum 1.394 ms.

This helper creates no subscriptions, moves no actor, edits no stage and starts
no render product or GPU workload. The collector is finished. Ground truth was
saved only for offline evaluation; none entered inference, tracking, map
association or event/count logic.

Vehicle origins are documented ground centers in
`isaac_city_sim/scripts/traffic/vehicle_lib.py:15`; the controller writes these
coordinates directly to each slot in `vehicle_controller.py:356`. Reading the
actual slot transform checks that the model state was applied to the scene.

## Time and identity matching

Timeline time is not a valid shortcut for vehicle state time here: the initial
feasibility read showed timeline 991.9 s and integrated traffic `sim_t`
974.1167 s. This is not evidence of signal phase drift: `phase_t()` includes a
separate offset, and a later direct signal read showed only 0.05 s between
compensated phase time and the timeline. The evaluator therefore uses wall
timestamps sampled **inside Kit** around the
actual world-pose read. It linearly interpolates only between snapshots at most
500 ms apart, with the same stage/controller generation and same active arrival
ID, asset and prim path on both sides. It never extrapolates across a spawn,
despawn, generation change, staged episode or large position discontinuity.

The model outputs use their existing `source-rtcp` clock. Camera frame pairs are
nearest-clock pairs within **50 ms**, with observed native metadata, matching
calibration/class/current epoch and visibility at least 0.25. The run supplied
861 such frame pairs.

For each tested anchor, a GT correspondence requires the closest actual vehicle
center to be at most **2 m** away, with at least **1 m** margin over the next
closest actual vehicle. The closest actor must have the predicted class; the
evaluator cannot skip a closer wrong-class actor to find a convenient match.
An asset-based class mapping was fixed before results: `car_pickup.usdc` is
truck; other authored simulation classes remain unchanged. TrafficSim itself
uses a broader car kinematic family that includes the pickup. Ambiguous
multiple same-camera observations assigned to one actor are excluded from the
GT co-observation opportunity count.

**These are geometry-based GT correspondences, not independent image identity
annotations or a complete accuracy benchmark.** Native SEI timestamps measure
encoded handoff, not exposure. To expose that timing limit, the evaluator uses
all fixed wall offsets −100, −50, 0, +50 and +100 ms. It does not choose the offset
that produces a better score. See the separate
[clock-path audit](smart-city-clock-path-audit-2026-10-26.md).

## Native SDK world foot versus rect bottom

There were 130 same-SDK-ID car pair observations, involving four SDK IDs.

| Anchor | Same GT actor at nominal time | Unmatched at nominal time | Different GT actor at nominal time | Same GT actor at all five time offsets |
| --- | ---: | ---: | ---: | ---: |
| Post-tracker rect-bottom homography | 57 | 73 | 0 | 3 |
| Native SDK world foot | 118 | 12 | 0 | 114 |

No different-actor assignments were measured under these strict GT gates.
Unmatched cases remain unknown; they are not counted as correct identities.
The result supports evaluating native world feet as vehicle-center anchors. It
does not support changing every map anchor or declaring the shared SDK IDs
qualified.

Using the world-foot correspondences, 641 car actor-pair observations were
evaluable in both cameras. Only 118 had the same SDK ID; **523 had different SDK
IDs**. Thus native ID agreement in this conditional set was **18.4%**. Eight
evaluable truck pairs and 20 motorcycle pairs all had different SDK IDs. There
were no qualifying bus actor pairs or bicycle observations. This does not prove
that buses never overlapped or that no bus was detected: large/uncertain center
estimates and class mismatches can leave observations unmatched.

If a hypothetical vehicle map join also required world-foot separation at most
1 m, only 41 same-SDK-ID car pairs would qualify: 36 have the same GT actor at
nominal time, and five remain unmatched. Vehicle map joins are **not currently
deployed**; this is a comparison baseline, not a claim about live UI behavior.

Matched position-error medians in `evaluation.json` are conditional on passing
the 2 m GT gate. Do not present them as unconditional model accuracy.

## Separate geometry association prototype

The prototype is CPU-only, offline and separate from VSS. It has no GT input.
It does not relabel native IDs or change camera counts/events. Its output label
is `calibrated-geometry-demo`, with `nativeIdFusion: false`.

Its rules were fixed before examining association results:

* Vehicles only; observed native 3D metadata, visibility at least 0.25, same
  class/calibration/epoch and capture clocks at most 50 ms apart.
* World-foot separation at most **1 m**.
* Mutual nearest neighbors, with at least **0.5 m** runner-up margin in **both**
  camera directions; one observation can belong to only one pair.
* Three confirmations using distinct fresh images from both cameras. Repeating
  one peer image cannot build the confirmation count.
* A 500 ms internal lease TTL. Display grouping stops immediately whenever a
  current gate fails; retained lease identity never displays a stale join.
* Camera-session or SDK-class/member changes retire affected leases. An epoch
  change refuses further use. No trail averaging, heading/velocity extrapolation
  or distance hysteresis is enabled.

| Geometry result | Car | Motorcycle | Truck / bus / bicycle |
| --- | ---: | ---: | ---: |
| Raw candidate pair observations | 87 | 2 | 0 |
| Confirmed pair observations | 54 | 0 | 0 |
| Distinct map leases | 9 | 0 | 0 |
| Confirmed pairs with different native SDK IDs | 27 | 0 | 0 |
| Confirmed same GT actor at nominal time | 46 | 0 | 0 |
| Confirmed same GT actor at all five offsets | 46 | 0 | 0 |
| Confirmed unmatched at all five offsets | 8 | 0 | 0 |
| Confirmed different GT actor | 0 | 0 | 0 |

The geometry association can add some pairs with different native IDs. Its
coverage is still too small for the intended display:

| Comparison on 641 conditional GT car-pair opportunities | Covered pairs | Coverage |
| --- | ---: | ---: |
| Equal native SDK ID, before a position gate | 118 | 18.4% |
| Equal native SDK ID plus 1 m world-foot gate | 36 | 5.6% |
| Geometry prototype before confirmations | 70 | 10.9% |
| Geometry prototype after three confirmations | 46 | 7.2% |

This is a modest increase over the equally strict position-gated baseline,
with eight confirmed associations still unverified by the GT class/distance
rules. It does not justify another live identity scheme or a larger
"no duplicates" claim. No threshold search or wider matching window was used.

## What remains useful for a future trial

The active native tracker configuration has `ReID.reidType: 0` and
`PoseEstimator.poseEstimatorType: 0`. No ReID embedding model or body-pose
refinement is enabled; cross-camera peer association is geometry based. Better
per-class physical priors/calibration and a separately measured model-backed
ReID trial are possible next steps. ReID would not itself repair a biased world
position. Raw detector versus reconstructed tracker-box diagnostics should be
included before drawing conclusions about the detector's geometry. These are
future trials; no model build, GPU job or additional live experiment was started.

The current deliverable can honestly show all camera observations and the
guarded experimental person map joins. Native multi-camera vehicle identity
fusion remains unqualified.

## Source and checks

```
tools/smart-city/evaluate_vehicle_ground_truth.py
tools/smart-city/prototype_vehicle_map_association.py
tools/smart-city/evaluate_vehicle_map_geometry.py
tools/smart-city/tests/test_evaluate_vehicle_ground_truth.py
tools/smart-city/tests/test_prototype_vehicle_map_association.py
```

Seven GT matching/interpolation tests and 15 prototype lease/gate tests pass.
They cover timeline/generation boundaries, no extrapolation, spawn/despawn,
strict distance/margin/class gates, both-direction uniqueness, cross-class SDK
ID ambiguity, repeated peer frames, current-frame splitting and session/lease
retirement. A reanalysis with the final checked prototype reproduces every saved
association record and all reported counts.

Reproduce without touching a live service:

```
python3 tools/smart-city/evaluate_vehicle_map_geometry.py \
  --capture .spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/vehicle-gt-normal-1792992512654735340 \
  --calibrations .spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/vehicle-gt-normal-1792992512654735340/calibrations.json \
  --output NEW_UNIQUE_RECEIPT.json
```

The saved receipts contain capture, observation, GT, calibration and source
hashes. Output files are created exclusively and never overwrite earlier
receipts. The subsequent parent-coordinated worker deployment is a different
epoch; it is not silently mixed into this run.
