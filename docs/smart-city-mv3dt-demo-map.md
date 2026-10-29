# Experimental MV3DT map display

This mode supplies an experimental association hint for the Smart City map. Rule events, occupancy, crossing counts and mobility reports remain camera-scoped; the map does not deduplicate those analytics. However, the underlying tracker is now MV3DT, whose SDK ID correction can change a camera's local ID and reset journey, wait or dwell history. Keeping the analytics camera-scoped does not establish tracking continuity or count accuracy. Neither is qualified by this demo. The backend still computes map positions from each camera's configured class homography. SDK native 3D positions are checked for finite evidence but are not substituted for those map coordinates.

The server must explicitly enable `CITY_MV3DT_DEMO_ENABLED=true`, set `CITY_MV3DT_DEMO_SITE_ID`, and supply `CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS` as a JSON object containing exactly the two approved source IDs and their calibration revisions. The configured live site's complete source/calibration pair must match. Site/API extras cannot enable the feature. The current authorized deployment is `isaac-intersection-a`, sources `997d3a69-e052-45a4-a1ce-be1b046670c4` and `40af41ea-2180-4b7b-83d6-bb5d08ff094a`, both with revision `isaac-live-6aaa6befcc1f190b`.

An eligible observation has `trackingMode: mv3dt-demo`, an explicit shared fusion epoch and `timestampBasis: source-rtcp`. The object must be an observed person, have visibility at least 0.25, finite SDK world/image feet, the exact approved camera calibration, a matching raw target ID and a correctly scoped `mv3dt-demo:<epoch>:<targetId>` ID. Reused epochs after camera session resets and retired epochs are refused. Missing, stale and predicted objects have no current map hint.

The public track contains a typed `mapAssociation`:

```json
{
  "method": "mv3dt-demo",
  "globalTrackId": "mv3dt-demo:<epoch>:<targetId>",
  "targetId": "<raw SDK ID>",
  "fusionEpoch": "<shared worker epoch>",
  "calibrationRevision": "<this camera's approved revision>",
  "visibility": 0.8,
  "sourceClockBasis": "source-rtcp"
}
```

For demo objects, the track's older top-level `globalTrackId` and `associationMethod` remain null. Exact processed-preview metadata carries the same frame's map hint. Snapshot and health association metadata continue to report `mode: camera-local` and `globalFusionEnabled: false`; a separate `mapFusion` object reports whether the experimental display is enabled and has fresh evidence from both sources. It always reports `qualified: false`.

The frontend owns display joining. It checks the actual displayed camera frames, current site/source calibration and sessions, observed-person evidence, matching shared ID/epoch, at most **150 ms frame separation** and at most **1 m disagreement** between the two camera-local homography positions. It chooses one deterministic representative rather than averaging positions. The user-authorized 150 ms window is a demo display policy intended to tolerate roughly one frame of separation at the observed preview rate. It does not synchronize capture, interpolate positions or establish simultaneous observations. The production evaluator retains its **50 ms** gate, and its qualification still fails. Those display checks do not convert the local analytics into fused counts.

The backend/preview controls pass **122 tests in 1.76 seconds**, including preservation of camera-scoped event/count processing, non-person and invalid-evidence rejection, epoch/session changes, stale tracks and exact-frame metadata. This is source validation; it is not deployment or production qualification and does not prove SDK tracking/count accuracy. The source receipt is [saved separately](qa/smart-city-2026-10-23/mv3dt-demo-map-source-controls.json).

A bounded offline estimate on the new no-see-through diagnostic run used unchanged image-space actor assignment and the current person homographies. Of 1,002 nearest camera-frame pairs, 774 met the 50 ms bound. Of 362 shared-SDK-person-ID pairs in those frames, 265 met the 1 m position bound: 255 had the same assigned actor and 10 lacked a usable label in one view. None had two different assigned actor labels. There were 235 same-actor cases isolated under the original image matching gate in both views. The guard accepted 22.85% of 1,116 same-actor labelled opportunities, so partial map joining is expected.

There were already zero differently-labelled shared-ID pairs after the time gate in that slice; the 1 m gate cannot be credited with removing a demonstrated false merge there. The ten unmatched-label cases are not counted as correct. Repeated nearest frames and the actual UI preview cadence also limit interpretation. Counts describe frame-pair observations, not unique people. The original production gates still fail. See the [saved estimate](qa/smart-city-2026-10-23/mv3dt-demo-map-guard-offline-estimate.json) and [CPU replay](qa/smart-city-2026-10-23/mv3dt-demo-map-guard-replay.py).

A separate **150 ms display estimate** uses the same saved inference, held-out labels, original image-space assignment and pinned static person homographies. All 1,002 nearest camera-frame pairs meet that display window. There are 454 shared-SDK-person-ID pairs; 335 meet the unchanged 1 m bound. Of those, 324 have the same assigned actor, 11 lack a usable label in one view, and zero have two different assigned actor labels. There are 298 same-actor cases isolated under the original image matching gate in both views. The estimate accepts 22.22% of 1,458 labelled same-actor opportunities. It reuses a second-camera frame 141 times, versus 36 at 50 ms. Thus the larger window adds eligible pairs, but also more temporal and label ambiguity. It does not establish a higher accuracy rate. The unlabelled cases are not successes, and zero differently-labelled pairs in this slice is not proof of zero real false merges. This is partial display evidence, not a production test or a measurement of the deployed UI's cadence. See the [separate 150 ms receipt](qa/smart-city-2026-10-23/mv3dt-demo-map-guard-150ms-offline-estimate.json) and [offline-only replay](qa/smart-city-2026-10-23/mv3dt-demo-map-guard-150ms-replay.py). No production threshold or old receipt was changed.

The first deployed demo exposed two NE objects with SDK ID `9` in one frame. The gateway correctly rejected that frame with HTTP 422, and the publisher stopped after 2,338 frames. The [failure receipt](qa/smart-city-2026-10-23/mv3dt-demo-duplicate-id-failure.json) is preserved. The native repair omits **all** objects with a colliding SDK ID within that frame, across classes, in demo mode only. It does not choose a winner, invent a replacement ID or relax gateway uniqueness validation. Its bounded 4,096-ID capacity also omits all tracked objects if exceeded. The raw observation records `nativeTrackAmbiguity` counters (`duplicateIdCount`, `omittedObjectCount`, `capacityExceeded`). Omitted observations must follow existing gap/unknown handling; they are not evidence of departure. This repair and its source controls do not qualify tracking or counts. Deployment verification belongs to the separate runtime handoff.

## Operator enable and disable

The deployment switch is `/home/sparkdev/vss/.spark/city/state/native/mv3dt-demo/active.json`. Keep its pinned image, camera order, calibration revisions and config hashes. Change only `enabled` to `true` for this demo or `false` for ordinary NvDCF. Enabling fails closed if its pinned files, exact camera pair or current calibration no longer match. Do not substitute an image tag or edit a calibration hash to bypass that check. The loader is Spark-only. This procedure does not stop Isaac or alter actors, recordings, the saved 20 GiB VSS reserve, or the disabled Isaac-only 23 GiB floor.

Run from `/home/sparkdev/vss`. First pause analysis for exactly the two saved Isaac cameras through the Agent. The helper validates the response's source/profile identity and all required pause steps; HTTP 200 alone is insufficient. Stop here if any call fails.

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, 'tools/smart-city')
import isaac_demo
sources = isaac_demo.sources()
isaac_demo.wait_for_gateway()
isaac_demo.wait_for_controller(sources)
for source in sources:
    isaac_demo.analysis(source, 'pause')
PY
```

Set `enabled` below to the desired Boolean. This preserves all other profile fields and replaces the file atomically. When enabling, validation runs immediately; if it fails, keep analysis paused and correct the actual profile discrepancy.

```bash
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, 'tools/smart-city')
import mv3dt_demo_profile
root = Path('/home/sparkdev/vss')
path = root / '.spark/city/state/native/mv3dt-demo/active.json'
profile = json.loads(path.read_text())
profile['enabled'] = False  # True enables the experimental map demo.
temporary = path.with_suffix('.operator.tmp')
temporary.write_text(json.dumps(profile, indent=2) + '\n')
temporary.replace(path)
mv3dt_demo_profile.load(root, 'spark')
PY
python3 tools/smart-city/manage.py --device spark render
docker compose -f .spark/city/compose.json up -d --no-deps --force-recreate --wait --wait-timeout 60 city-analytics
```

`render` writes the city compose configuration using the active profile. Recreating only `city-analytics` applies or removes the explicit gateway environment allowlist. It does not restart the main VSS Agent, UI or video service. Run each command only after the preceding command succeeds. Then resume the same two sources in their saved SW/NE order:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, 'tools/smart-city')
import isaac_demo
sources = isaac_demo.sources()
isaac_demo.wait_for_gateway()
isaac_demo.wait_for_controller(sources)
for source in sources:
    isaac_demo.analysis(source, 'resume')
health = isaac_demo.wait_for(isaac_demo.ready, 'Waiting for both exact previews and compiled rules', 60)
print(health.get('association', {}))
PY
```

The existing controller invokes `manage.py analyze` for each new worker, so it reloads this profile without a controller restart. The initial one-camera admission uses ordinary NvDCF; the two-camera restart enables MV3DT only when the saved pair and calibration match. Resume creates new tracking sessions; do not compare pre/post-toggle journey histories as continuous. If readiness fails, preserve the error and pause both sources again with the first block. Do not bypass admission by launching a separate detector container.

After enabling, confirm the association reports `globalFusionEnabled: false` and `mapFusion.enabled: true`, with `qualified: false`. Fresh eligible evidence from both cameras is still required for `available`; individual map joins additionally require the displayed-frame guards. After disabling, the gateway should have no enabled `mapFusion`, and the newly launched worker uses ordinary NvDCF. API health alone does not prove a join was displayed or that the tracker is accurate.

## Active live deployment

The opt-in profile is active at `http://127.0.0.1:7782/?workspace=smart-city`. The final native image is pinned in `.spark/city/state/native/mv3dt-demo/active.json`; only the worker was rebuilt on the cached base, using the existing detector engine. The dedicated loopback MQTT broker has an `unless-stopped` restart policy. Two live cameras and both exact previews passed a 40-second smoke check, with about 8.8 analyzed frames per second per camera. This is a short functional check, not sustained-load or identity-accuracy qualification. The live UI showed a joined marker count; cross-camera selection has scoped component coverage, but its very brief live state was not captured in the browser.

To reduce display flicker, a newly joined person still needs camera projections within 1 m. Only the same already joined member IDs may remain grouped out to 1.5 m; time, visibility, session, calibration, ID and current-frame checks still apply, and the marker uses the current representative position. No previous camera position or pixels are held to manufacture agreement. Canonical production qualification retains its original thresholds.

Current deployment identity, health, source rates and check limits are recorded in [the deployment receipt](qa/smart-city-2026-10-23/mv3dt-demo-deployed-summary.json). The final worker remained live beyond sequence6,237 in both sources, past the first attempt's duplicate-ID shutdown near sequence1,107. That observation is not an endurance qualification.
