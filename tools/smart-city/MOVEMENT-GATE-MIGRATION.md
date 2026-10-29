# Intersection A right-turn gate correction

The current northbound right route exits into the outer eastbound lane. Its
centre crosses x = −7.5 m at y = 74.077122 m. The existing
`mobility-isaac-east-exit` covers y = 75.833769–79.333769 m, so that finite gate
cannot count the right route. Zero right counts therefore have a structural
cause, even though light traffic can also produce an empty five-minute window.

The source generators now make these changes:

| Item | Correction |
| --- | --- |
| `cam_sw-northbound-line` | Move the common entry from y = 69.6 to y = 66.0 m, x = −23.62…−20.12 m. Keep it in image-normalized coordinates with the existing camera calibration. |
| `mobility-isaac-east-right-exit` | Add a separate full-width outer eastbound gate at x = −7.5 m, y ≈ 72.32707…75.82707 m. |
| `northbound-right.exitRuleId` | Reference the new outer gate. |
| Other configuration | Preserve the old inner east exit, north/west exits, classes, conditions, names, enable flags, unrelated rules, queue, crossing and curb settings. |

All three actual `TrafficSim` routes intersect the new entry once at
[−21.87, 66.0] m. The right route crosses the new exit once and never crosses
the old exit. Both complete lines project inside the southwest camera. The
entry is 0.521 m before the physical right fillet, `turn_meta.s_A`; the model's
earlier `branch_s` is a queue/heading coupling threshold and is not the
physical split. No camera, map, renderer, actor trajectory, model or threshold
change is needed.

## Prepared candidate; activation remains separate

The offline tool reads complete API snapshots and a matching static camera
export. It has no network or apply operation:

```sh
/tmp/vss-city-backend-test-env/bin/python tools/smart-city/isaac_movement_gates.py \
  --snapshot /absolute/path/full-site-rules-mobility.json \
  --camera-export /home/sparkdev/isaac_city_sim/logs/vss-integration/camera-map-export.json \
  --output /absolute/path/new-review-directory
```

It accepts the known previous entry geometry or the corrected geometry. It
rejects changed calibration, roads, camera ownership, disabled movement gates,
custom entry geometry, custom movement references, and conflicting use of the
new rule ID. It deep-copies actual operator settings instead of replacing them
with preset defaults. A second preparation of an already corrected snapshot
reports that no changes are required.

The initial review directory is
`.spark/city/runtime/movement-gate-candidate-20261026T072855Z`. Its input was
read from the live GET APIs without mutation: site revision 142, rules revision
405, mobility revision 4, calibration `isaac-live-e8b0fd8728666cd5`.
`before.json` preserves the complete input; `manifest.json` hashes input and
output bytes and describes exact changes. `source-check.json` pins the tested
sources. `route-geometry-check.json` records actual offline route intersections;
`schema-check.json` records validation with the real backend models and zero
configuration issues. These snapshots become stale when another operator
changes configuration; they are evidence, not permission to overwrite newer
settings.

For the coordinated cutover:

1. Keep both source owners admitted and active. Finish or cancel any scenario,
   and avoid Ask/index requests during cutover. Save site/rules/mobility GET
   responses. **Do not use the normal Agent pause before replacement:** it
   removes source owners and archives their rules, so a full two-camera rules
   PUT would reference unknown sources.
2. Re-fetch configuration and compare it with the candidate baseline. If any
   configuration changed, prepare a fresh candidate; review conflicts explicitly.
   No site PUT or calibration regeneration is required.
3. PUT `rules-put.json` to `/api/v1/city/rules` with its current
   `expectedRevision`. Wait for matching native analytics acknowledgement.
4. PUT `mobility-put.json` to `/api/v1/city/mobility/config` with its current
   `expectedRevision`, only if the movement reference still needs changing.
5. Verify ordinary detections, exact frame previews,
   matching rule revisions and a camera-derived right-turn journey. A route
   intersection test is not a substitute for this live observation.

Rules replacement marks active events unknown, clears transient rule/metric
state and resets mobility history. Mobility replacement resets its history
again. The API assigns a new rule revision to all saved rules; it retains their
semantic settings. Durable events remain and no successful clearance is
fabricated. Schedule cutover between scenarios and judge new counts from the
new measurement window.

## Rollback and verification limits

The candidate includes `rollback-rules-template.json` and
`rollback-mobility-template.json`, containing the complete original settings.
They contain a deliberately nonnumeric `expectedRevision` placeholder, which
the API rejects until the operator replaces it with a **current** GET revision.
Keep both source owners admitted, restore rules first, await acknowledgement,
then restore mobility. If calibration or other operator settings changed since
the baseline, merge explicitly instead of replacing newer settings. Rollback
also resets transient counts/history.

Focused CPU verification passed 18 tests: preservation of operator settings,
conflict rejection, idempotence, baseline/rollback files and their hashes,
generator references, and real-route intersections. The real backend accepted
all 16 candidate rules and reported no mobility configuration issues. No live
activation or right-turn detection success is claimed by these receipts.
Camera anchor error, detection loss, track discontinuity and low arrival rates
can still reduce observed counts after the structural correction.
