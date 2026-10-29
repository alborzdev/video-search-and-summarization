# Smart City: single native MV3DT migration — October 26

The active Spark profile now runs **RF-DETR → one native MV3DT tracker → native
analytics → observations/map**. The separate NvDCF tracker is no longer in the
active pipeline. The profile also uses MV3DT during either camera's individual
startup, with that camera's correctly ordered calibration and MQTT identity;
there is no automatic 2D fallback. Selecting the native architecture together
with a separate local tracker is rejected.

This completes the architecture migration, not an all-class identity-accuracy
qualification. The bounded motion test below still shows weak cross-camera ID
agreement. The user explicitly selected NVIDIA's native MV3DT pipeline, retaining
its internal DCF module, rather than an experimental DCF-free variant.

## NVIDIA guidance reviewed

The audit loaded NVIDIA's actual skills and the applicable tracking and design
references, rather than treating tracker names as mutually exclusive algorithms:

- [DeepStream development skill](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-dev/SKILL.md), including its tracker and plugin references.
- [DeepStream configuration auditor](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-audit-config/SKILL.md), using its design/code-review route because this application constructs its GStreamer pipeline in C++, rather than supplying a deepstream-app main config.
- [Run MV3DT skill](https://github.com/NVIDIA/DeepStream/blob/main/skills/deepstream-run-mv3dt/SKILL.md), inspected for reference-app fundamentals; its sample MP4 workflow was not substituted for the existing live application.
- [MV3DT SDK architecture](https://docs.nvidia.com/deepstream/9.2/text/DS_MV3DT) and [NVIDIA reference tracker configuration](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/config_templates/config_tracker.yml).
- The repository's [3D tracking deployment skill](../skills/deployment/vss-deploy-detection-tracking-3d/SKILL.md).

MV3DT extends NVIDIA's shared tracking library with calibrated 3D projection,
peer association and MQTT communication. NVIDIA's reference configuration also
uses an internal DCF visual tracker. Removing the application's extra tracker
stage therefore does not require disabling the reference implementation's DCF
module. RF-DETR remains the object detector.

## Findings and repairs

The deployed parent profile explicitly selected `nvdcf-local-then-mv3dt-v1`.
Its first tracker supplied camera-local identity, while the second supplied an
optional cross-camera identity. The native exporter, analytics adapter and UI
map each restricted shared identity to people. Vehicle map positions used a
rectangle-bottom homography even when native SDK world feet were available.
The prior [vehicle audit](smart-city-vehicle-association-audit-2026-10-26.md)
already measured poor native agreement; removing the first tracker alone could
not establish good shared IDs.

The replacement uses `mv3dt-native-v1`:

- One SDK target ID supplies the observation's native/local target and its
  cross-camera proposal. No independent NvDCF ID, geometric alias, numeric-bit
  heuristic or simulator actor ID supplies identity.
- All six detector classes can carry native shared-ID evidence: person,
  bicycle, car, motorcycle, bus and truck. Existing camera calibration files
  already contain explicit priors for all six classes.
- A current detector-object stamp proves an actual observation and preserves
  the source frame number before MV3DT can replace `frame_num` with its batch
  counter. Newly created peer/shadow objects cannot claim a detector observation.
- The map adapter uses validated SDK world feet for native associations, with
  source/session, calibration, epoch, visibility, image-foot validity, map
  bounds, matching class, capture-skew and position gates. The existing
  `validGroundPolygon` is an **image-space** polygon; its check uses image feet.
- The UI supports all six classes and rejects equal IDs across different
  classes or position authorities. It retains the existing 150 ms capture and
  1 m entry / 1.5 m established-pair distance gates. It never groups different
  SDK IDs by proximity. Linked labels now say objects rather than people.
- Image-rule measurements retain camera scope. They are not advertised as
  deduplicated site-wide counts. MV3DT ID adoption/correction can still split a
  camera journey; this path does not fabricate an immutable local handle.

The preparation helper clones and pins the tracker, camera, package and broker
files, removes the separate local config, and generates distinct singleton
tracker/pub-sub files for the two cameras. It exercises the actual production
profile loader on an isolated review bundle and preserves exact rollback bytes.

## Installed SDK checks and bounded trials

The newer NVIDIA reference puts `outputVisibility` under
`ObjectModelProjection`. A first live candidate using only that placement
emitted null visibility on this installed SDK. Its observations were correctly
rejected by the shared-ID guards. The final profile retains the installed
SDK's `TargetManagement.outputVisibility: 1` alongside the reference projection
flag. The measured final native output has visibility metadata.

A separate `enableMsgSync: 1` trial produced only three frame pairs before
observations stopped advancing. The bounded recorder collected no subsequent
frames. That trial was rejected and its exact parent profile restored. The
final configuration retains measured asynchronous MQTT communication
(`enableMsgSync: 0`), native late association and ID correction, and disabled
see-through output. This evidence is specific to this installed application;
it is not a claim that NVIDIA's sample synchronization configuration is
universally broken.

## Measured motion result

A 60.098-second normal-playback window captured 230 observation frames in one
fusion epoch, 115 from each source. Each camera supplied approximately
**1.92 observation frames/s**. The median paired capture-clock skew was
**0.371 ms**, maximum **0.991 ms**. Minimum sampled available host memory was
**34.93 GiB**, above the unchanged Spark 20 GiB reserve. These are bounded
measurements, not sustained-load qualification or physical-exposure timing.

| Class | Object observations | With native 3D / visibility | Shared-ID proposals exported | Equal native IDs across paired views | Equal-ID pairs within 1 m |
| --- | ---: | ---: | ---: | ---: | ---: |
| Car | 302 | 302 | 201 | 8 | 1 |
| Person | 703 | 703 | 664 | 0 | 0 |
| Motorcycle | 4 | 4 | 4 | 0 | 0 |

These are repeated frame observations, not unique people/vehicles or accuracy
percentages. An exported proposal does not establish that a second camera
sees the same object. The window had no bicycle, bus or truck observations;
those classes have CPU contract coverage, not live acceptance from this test.
No independent identity annotations or ground truth were used. Zero matched
person IDs does not by itself establish how many people were jointly visible.

The current app therefore must not be described as reliable shared identity
for every road-user class. Further acceptance needs representative paired
footage and independent correspondences, per-class localization/geometry checks,
and evaluation of any separately justified model-backed pose/ReID configuration.
The current configuration still disables pose and ReID; non-person cylinder
priors remain approximations. Wider gates are not a substitute for that work.

## Deployment and verification

The immutable native image is
`sha256:78a03a276a2412f61f390c4e3ca560d8222aecbe5eaa554aa1c0b03eee01fd84`.
The active profile is `single-native-visibility-20261026` with 11 file pins,
`source-native-sei` clocks, original camera calibration and RF-DETR Medium
engine. Its profile SHA256 is
`0d6210c8c4379d7a996b1212a2f5047e052f59fdc2189e35fbb705ee31f21904`.
The memory guard remains active. Thor settings and its reserve were not changed.

Validation passed:

- 555 scoped Python backend/configuration/runtime tests, followed by the
  focused preparation tests after the receipt-helper correction.
- 55 UI map/clock tests and the affected application's strict TypeScript check.
- CPU-only actual DeepStream metadata/observation tests, including six classes,
  current detector provenance, full uint64 IDs, source frame preservation,
  rejection of the extra tracker, scenario boundaries and native capture clocks.
- Real GPU worker initialization, reciprocal MQTT connections, fresh output
  from both cameras, and the bounded motion capture above.
- Rendered Smart City page, both live analyzed camera views, map-key interaction,
  and a clean browser console after reconnecting. Browser plugin was unavailable;
  existing Playwright/Chromium were used. Desktop screenshot:
  `/tmp/vss-smart-city-native-mv3dt-desktop.png`. The displayed instant had zero
  linked objects; it is not presented as proof of successful shared identity.

Runtime artifacts, exact original/staged rollback, rejected trials, capture,
source/image identities and logs are retained under:

`.spark/city/runtime/mv3dt-native-20261026/`

The initial preparation receipts used the shared review writer's generator
hash; final deployed source identities separately pin the native preparation
script. The helper now records its own generator hash for future reviews.
The source-mounted UI was used without a full UI image build. Playback was
started only for bounded motion validation and returned to its original paused
state afterward; the two existing camera publishers remain selected.

To prepare a future review without applying it:

```bash
python3 tools/smart-city/prepare_mv3dt_native.py \
  --snapshot UNIQUE-SNAPSHOT --image-id sha256:REVIEWED-WORKER-IMAGE \
  --output NEW-REVIEW-DIRECTORY
```

Use the actual immutable image ID and a new snapshot/output. Service cutovers
must pause the two sources first, preserve the active profile and start new
source/tracking epochs. Retain the current guarded map policy until measured
identity evidence supports a different one.
