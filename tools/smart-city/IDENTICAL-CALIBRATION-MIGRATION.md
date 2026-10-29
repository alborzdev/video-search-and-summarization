# Geometry-identical Isaac stage migration

`isaac_identical_calibration.py` prepares files only. It has no apply flag, network client, service command, simulator call or approval bypass. It does not modify the MV3DT loader.

Use it only when the full old and new exports differ in **stage** and **calibrationRevision**. Every other field must have exactly equal values, including the cameras, map, road/person planes, crosswalks, qualification and camera order. JSON `0` and `0.0` are equivalent; no numeric tolerance is used. Even a small camera change stops preparation. Source, native package and archived camera geometry must also match the old export.

The candidate retains every operator rule, enabled choice, geometry, duration and mobility reference. It changes the rule/source calibration pins, retains unrelated controller archives, and clones the native configuration into a new directory. Camera YAML, MQTT settings and peer topics retain their bytes. Tracker paths alone change to point at the clone. The package receives the new revision, and a seventh pinned manifest records that migration is **not** runtime, clock or production qualification. `active.json` pins the actual Docker image `.Id`, not a build-log digest.

The current review artifact is `.spark/city/runtime/intersection-rebuild-20261026/review-migration-final`. Its `review-receipt.json` contains input preconditions and hashes for every candidate. It is a dry run, not an applied-state receipt.

Run from `/home/sparkdev/vss`:

```sh
python3 tools/smart-city/isaac_identical_calibration.py \
  --before-export .spark/city/runtime/intersection-rebuild-20261026/before-camera-map-export.json \
  --candidate-export .spark/city/runtime/intersection-rebuild-20261026/candidate-camera-map-export.json \
  --site .spark/city/runtime/intersection-rebuild-20261026/before-site.json \
  --rules .spark/city/runtime/intersection-rebuild-20261026/before-rules.json \
  --mobility .spark/city/runtime/intersection-rebuild-20261026/before-mobility.json \
  --registration .spark/city/isaac-registration.json \
  --calibrations-archive .spark/city/controller-calibrations.json \
  --rules-archive .spark/city/controller-source-rules.json \
  --sources-archive .spark/city/controller-sources.json \
  --demo-directory .spark/city/state/native/mv3dt-demo \
  --image-id sha256:6b74dbe97296e40adcd019f20422d4a1dc3b7f301e0bff2e9fab88f24f705cf1 \
  --snapshot intersection-rebuild-20261026-e8b0fd \
  --output .spark/city/runtime/intersection-rebuild-20261026/review-migration-final
```

An existing output directory is refused. Use a new output name when refreshing a review. The tool accepts a controller archive with both cameras desired-active or both paused; it rejects a partially paused pair. It preserves that desired-source state. It does not reactivate absent cameras.

The following procedure is for the root operator to execute after reviewing the candidate. The preparing agent did not execute it.

1. Verify the tool tests below, all `review-receipt.json` output hashes, and the immutable image with `docker image inspect sha256:6b74dbe97296e40adcd019f20422d4a1dc3b7f301e0bff2e9fab88f24f705cf1 --format '{{.Id}}'`. Confirm the live static export is still equal to `candidate-camera-map-export.json`. Preserve the existing full site/rules/mobility and active native profile for rollback.
2. Pause both source UUIDs through `manage.py source-analysis --kind live --profile smart-city --source-id UUID --name EXACT_NAME --action pause`. Require the Agent's successful pause receipts. Stop the existing controller (its actual user service or `manage.py controller-stop`) so it cannot overwrite archives during installation. Keep Isaac publishing, and keep unrelated services intact.
3. Read the latest controller archive files. If any receipt precondition changed during pause, rerun the preparation command with a new output directory while retaining the original full `before-site.json` and `before-rules.json`. Normal per-rule revision updates are allowed; changed geometry, enabled choices or missing rule sets stop the tool. Review those changes instead of overwriting them.
4. With the controller stopped, copy the candidate's `native/mv3dt-demo/intersection-rebuild-20261026-e8b0fd/` directory into the **same relative path** under `.spark/city/state/`. Require that the destination does not already exist. Replace `.spark/city/state/native/mv3dt-demo/active.json` from the reviewed candidate using a temporary file and atomic rename. Atomically replace only `controller-calibrations.json` and `controller-source-rules.json` from that same review. Keep the controller's **current paused desired-source file**; never restore the pre-pause active list from an older review. Preserve all original profile files and exports.
5. Load the installed profile with the unchanged `mv3dt_demo_profile.load(ROOT, 'spark')`; call its `native_args` against the candidate site. The hash and calibration checks must pass. Install the reviewed `camera-map-export.json` as the simulator's saved static export only if it is not already identical. Keep the 960×540 camera profile and existing UUID/proxy URLs.
6. Read `GET http://127.0.0.1:9184/api/v1/city/site` immediately before saving. Build the PUT from the candidate `site.json`, set `expectedRevision` to that live revision and `revision` to live revision + 1, then PUT the same endpoint. Stop on a conflict. A site change can disable old metric rules temporarily; do not use that transient rules state as the operator baseline.
7. Read `GET .../rules` after the site PUT. PUT `{rules: candidate.rules, expectedRevision: currentRules.revision}` to `/api/v1/city/rules`. This restores all 14 reviewed rules with new calibration pins. The server assigns their new rule revision. Check every rule's ID, enabled state, geometry, conditions and calibration against the candidate. Compare `GET .../mobility`'s `config` with candidate `mobility.json`; the same site ID retains it, so no mobility PUT is required.
8. Render the Smart City configuration with `python3 tools/smart-city/manage.py render`. Recreate only the CPU gateway using the saved `.spark/city/compose.json` and `city-analytics` service, preserving limits. This refreshes its two-camera MV3DT calibration allowlist. Restart the stopped controller so it reads the new archives and image pin. Resume southwest, then northeast through the Agent. Keep indexing on-demand; a healthy CV resume does not require an embedding producer.
9. Verify both native camera counters advance, both processed previews are fresh, rules use the applied revision, the map uses the new calibration and native MV3DT output has its actual epoch/IDs. Verify recent five-second recordings before asking one bounded question. Test one explicit indexing capture/search/cancel separately. Source history/rolling analytics reset across configuration changes; old events and recordings remain historical evidence. No new synchronization or accuracy qualification is implied.

If any identity, hash or API revision check fails, stop and retain the failed receipt. Do not remove guards, relax the loader, force an expected revision or clear existing evidence. Rollback requires the old site/rule/archive/profile set together, not merely the old Docker image.

Scoped CPU verification:

```sh
/tmp/vss-city-backend-test-env/bin/python -m pytest \
  tools/smart-city/tests/test_isaac_identical_calibration.py \
  tools/smart-city/tests/test_mv3dt_demo_profile.py \
  tools/smart-city/tests/test_isaac_demo.py -q --tb=short
```

This passed 121 tests. New migration source/tests also passed Ruff and formatting. The separate launcher fix requires explicit `indexingRequired: false` and `indexingPolicy: on-demand|disabled` for embedding-independent resume; missing or inconsistent metadata is rejected. Pause continues to require successful stop receipts.
