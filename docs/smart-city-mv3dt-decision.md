# MV3DT decision for the Smart City demo

## Current experimental tradeshow selection

The user explicitly prioritized a smooth tradeshow demo over production qualification. The separately named, opt-in `mv3dt-demo` profile now supplies experimental person-association hints to the map. Failed production receipts are retained. Canonical `mv3dt`, fused counts, vehicle map fusion and SDK world-position display remain disabled. See [the active demo policy and operator controls](smart-city-mv3dt-demo-map.md). The earlier decision below remains the production-qualification result.

## 2026-10-23 production qualification decision

The new paired Isaac intersection replaces the unrelated inputs described in the historical review below. Actual DeepStream 9.2 MV3DT/MQTT diagnostics now run on Spark, and a native diagnostic metadata adapter exports SDK feet/visibility/3D state. **Do not promote them as production-qualified fusion:** two completed 2,200-observation runs failed the saved position and identity gates. The first run's person-position median/p95 was 0.520/1.349 m; the person-plane candidate was 1.225/2.322 m. A conservative ground-association replay also failed. The camera-local person-plane projection scored 0.420/0.947 m in its separate 209.20-second observation window (300-second labelled capture). These are bounded image-space label assignments, not HOTA/IDF1 or field accuracy. Occlusion can make evaluator labels ambiguous; disagreements were retained as failed gates.

The [integration guide](smart-city-isaac-integration.md) and [saved comparison](qa/smart-city-2026-10-23/mv3dt-road-plane-comparison.json) give the current evidence. At that diagnostic checkpoint both live views used the RF-DETR Medium/NvDCF worker without global identity, fused counts or SDK position display. The subsequently selected experimental map-only demo is described above. In the installed SDK, the correct communicator format is `host:port;topic`, visibility is emitted with `TargetManagement.outputVisibility`, and projection matrices must match the 640 × 384 tracker coordinates. These runtime checks resolve the preparation issues described below; they do not establish tracking accuracy.

## Historical research and initial gates

Reviewed 2026-10-22 against NVIDIA's current DeepStream **9.2** documentation and official source at commit [`844bff0c44f691fe392e10d692f349da20431a71`](https://github.com/NVIDIA/DeepStream/tree/844bff0c44f691fe392e10d692f349da20431a71). This review made no GPU calls or runtime changes. It extends the existing [camera handoff](smart-city-camera-handoff.md) and [native worker documentation](../services/rtvi/rt-cv/smart-city/README.md).

**Decision: test MV3DT as the first native multi-camera tracking candidate when the final intersection has calibrated, overlapping, fixed cameras. Keep it disabled for the current independent traffic and pedestrian fixtures.** Keep the explicitly selected RF-DETR Medium 576 and CUDA NvDCF as the working detector and local tracker on Spark; retain Small 512 as the tested lower-cost baseline. The generic model selector still defaults to Small on a device with no saved selection, and neither Spark profile qualifies Thor. Add the 3D and peer-association stages as a separate qualified profile. Do not make a fusion badge or a unique cross-camera count depend only on a configuration file being present.

The current implementation has **no active cross-camera association**. The native worker writes `globalTrackId: null`, and the gateway preserves camera/session/local identities while projecting calibrated ground anchors. It does not merge those identities or consume MV3DT 3D metadata. The optional preparation utility is a configuration preflight, not a connected fused-track adapter. Thus the present recordings cannot demonstrate an MV3DT benefit even if they play at the same time.

| Deployment gate | Present status | Required before enabling fusion |
| --- | --- | --- |
| Detector and per-camera tracker | Medium 576 selected on Spark; Small baseline available; CUDA NvDCF | Reuse the same detector/thresholds for a fair paired-episode comparison. |
| Shared static view | Current traffic and pedestrian clips are unrelated and unequal-resolution | Two fixed overlapping views of the same episode, equal decoded dimensions, validated 3D calibration and measured source-clock skew. |
| Native 3D and peer runtime | Experimental configuration preparation only | Verified SV3DT metadata, SDK-accepted configuration, MQTT peer association, explicit source order and reconnect handling. |
| Fused metadata and events | No fused ID/position export or deduplicated global-event authority | Implement observed/predicted/peer provenance, ID-correction aliases, trusted world-position ingestion and event deduplication; retain per-camera evidence. |
| Promotion | No local MV3DT runtime, speed or tracking-accuracy result | Pass the paired geometric/identity/event/load gates below, then explicitly select the separate qualified profile. |

The best demonstration would be one pedestrian passing behind a bus in camera A while camera B can still see that pedestrian. The map should keep one qualified identity and indicate which camera supplies current evidence. This is our proposed demonstration, not a result already achieved.

## Support and the limits of the published evidence

| Question | Evidence and decision |
| --- | --- |
| Can Spark run it? | Yes, as a documented platform path. The official reference names `ghcr.io/nvidia/deepstream:9.2-triton-sbsa-dgx-spark` for ARM SBSA. Its general prerequisites are Ubuntu 24.04 and driver 580.xx or newer. This does not qualify our complete VSS workload or every host/runtime combination. |
| Is a different detector required? | No. NVIDIA documents conversion of an existing 2D DeepStream pipeline with a custom detector and preprocessing section. Its example detectors are PeopleNet Transformer, PeopleNet 2.6.3 and a warehouse RT-DETR. RF-DETR integration still needs its own paired-camera test. |
| Are there relevant known issues? | The reference warns that its RT-DETR needs strongly typed TensorRT mode on Blackwell, including GB10/Spark. That is not a reason to rebuild our separately validated RF-DETR engines blindly. It also notes a libmosquitto file-descriptor hang for the Thor 12-camera Inference Builder example. Neither warning is evidence that our two-camera deployment has passed. |

These platform/customization facts come from the [official reference README](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/apps/reference_apps/deepstream-tracker-3d-multi-view/README.md).

NVIDIA's **publisher benchmark**, not our measurement, lists these aggregate application FPS values:

| Reference FP16 detector + MV3DT | DGX Spark | Jetson AGX Thor |
| --- | ---: | ---: |
| Warehouse RT-DETR, 3 × 544 × 960 input | 106 | 95 |
| PeopleNet 2.6.3 | 341 | 349 |
| PeopleNet Transformer | 26 | 25 |

The benchmark includes video decode, preprocessing, batching, inference and metadata processing, with rendering disabled. Its warehouse model is trained for classes such as people, forklifts and humanoid robots. These are not RF-DETR city results, a two-camera latency guarantee, MQTT fault tests, final tracking accuracy, or performance alongside our embedding, captioning, LLM and UI workloads. **No MV3DT speed has been measured in this repository.** [Official 9.2 performance table and method](https://docs.nvidia.com/deepstream/text/DS_Performance).

## What must be supplied

The reference requires synchronized streams, equal image resolution and camera projection matrices. For our first experiment, choose equal frame rates too; that is a project simplification, not a claimed NVIDIA hard limit. Use fixed intersection cameras. Arbitrary unrelated cameras, a moving vehicle camera with an unchanged calibration file, and merely simultaneous video playback do not meet this handoff.

Our site package should contain:

- Stable source IDs and stream order; actual decoded dimensions, crop, rectification and lens convention.
- A shared metre coordinate frame, axes and ground plane. For each camera, intrinsic `K`, explicit world-to-camera extrinsics, and the corresponding 3 × 4 world-to-pixel matrix. Prefer `projectionMatrix_3x4_w2p`, which already includes the principal-point translation. A ground homography alone does not determine full vertical projection.
- Held-out 3D/pixel landmarks across the used region, including non-ground points; a measured overlap polygon; calibration revision; and explicit handling of slopes or regions outside the model's ground-plane assumptions.
- Paired capture timestamps, common-clock provenance and measured skew through the actual RTSP/media path. Retain raw PTS, source sessions, clock basis and discontinuities. Shared HTTP arrival time is insufficient.
- Per-class object-model dimensions with units and provenance, plus an actor-free static map/world-to-map transform. MV3DT supplies tracks; it does not create the street plan.

The projection convention and class geometry are documented in [SV3DT](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker#single-view-3d-tracking). NVIDIA's [neighbor-generation source](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/apps/reference_apps/deepstream-tracker-3d-multi-view/utils/generate_pub_sub_configs.py) also contains dataset-specific metre/feet handling. Audit those conversions rather than copying a synthetic warehouse transform into the city. Our proposed landmark/skew acceptance thresholds belong to the project preflight, not an NVIDIA accuracy guarantee.

## Classes, timing and output semantics

SV3DT supports per-class `modelInfo` arrays and cylinder/cuboid models. It is not human-only. However, the documented cuboid has a **square** ground footprint. A long bus, variable truck sizes, a turning bicycle and its rider can violate a simple fixed-shape approximation. Start fusion with people, then qualify vehicle classes separately. Retain our native class IDs: person 0, bicycle 1, car 2, motorcycle 3, bus 4, truck 5. Keep class matching enabled. Pose stays disabled initially; if added later, restrict human pose with `PoseEstimator.operateOnClassIds: [0]`. Do not apply it to buses. [Tracker class/pose configuration](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker).

MV3DT adds peer tracklet matching, ID propagation/correction and measurement fusion. Its documented peer transport is MQTT; messages include camera/class/target identity, frame numbers, an NTP-based timestamp and recent 3D tracklets. `useBatchNumForFrameId` can provide shared batch counters when per-source counters do not align; it does not repair invalid capture clocks. Late association and ID correction mean IDs can change when earlier matches were wrong. Nearby objects with similar motion can still be confused. No universal millisecond skew tolerance is promised. [MV3DT architecture and cross-stream alignment](https://docs.nvidia.com/deepstream/text/DS_MV3DT).

For our adapter, preserve camera/session/local identity and add a separate qualified global identity with association provenance and correction history. Keep integer IDs as strings. A peer-supported or predicted object must not be labeled as a new detector observation in an occluded camera. Do not treat tracker confidence as a calibrated position-error bound. Deduplicate global events only after the alias/correction policy passes tests; keep ambiguous identities separate.

The installed plugin source attaches world-foot, image-foot, visibility and 3D-object user metadata when requested. The 3D box structure includes world centre, dimensions, rotations and velocity. Our current JSON worker does not export these fields, and the backend currently computes map positions from calibrated anchors. Add an explicit trusted MV3DT position path and provenance; silently adding an ignored `positionM` field would not integrate fusion. Direct metadata extraction can feed our HTTP/SSE contract. Kafka is used by NVIDIA's sample viewer, but need not become an extra UI dependency. [Official tracker metadata implementation](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/gst-plugins/gst-nvtracker/nvtracker_proc.cpp).

## Existing preparation utility: useful, still unqualified

[`prepare_mv3dt.py`](../services/rtvi/rt-cv/smart-city/prepare_mv3dt.py) already checks full calibration, same resolution, visible overlap, class dimensions, held-out landmarks and measured common-clock timing. It emits a disabled experimental package. Its synthetic-test override still leaves `enabled: false` and `runtimeQualified: false`. Reuse this preflight; do not add a second generator to bypass it.

The utility currently emits only `objectModelType: 0` cylinders and requires explicit geometry for all six detector classes. It does **not** implement a people-only runtime switch or generate cuboid models, although the SDK supports more geometry choices. The proposed people-first experiment therefore needs a reviewed class-scoped tracker/profile change or equivalent isolation before running; supplying arbitrary vehicle dimensions is not an acceptable shortcut. Its default preflight gates are at least six non-coplanar held-out 3D landmarks per camera, maximum 3-pixel reprojection error and at least 100 strictly increasing timestamp pairs with maximum 50-ms skew. These are preparation criteria, not achieved tracking accuracy or a universal MV3DT timing tolerance.

One **unresolved documentation/source discrepancy** needs an installed-SDK check before promotion:

| Evidence | `outputVisibility` location |
| --- | --- |
| Current 9.2 tracker documentation, metadata section and parameter table | `TargetManagement` |
| Official pinned MV3DT `config_tracker.yml` and auto-configurator | `ObjectModelProjection` |
| Our disabled preparation utility | Follows the reference template's `ObjectModelProjection` location |

The [pinned template](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/apps/reference_apps/deepstream-tracker-3d-multi-view/config_templates/config_tracker.yml) and [auto-configurator](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/apps/reference_apps/deepstream-tracker-3d-multi-view/utils/deepstream_auto_configurator.py) both show the latter location. CPU inspection of the installed 9.2 `nvtracker_proc.cpp` shows that the plugin obtains `outputVisibility` from the low-level library query; it does not expose that library's YAML section parser. This does **not** establish whether one or both locations are accepted. No runtime query or GPU validation was performed. Require parser/log checks and actual `NVDS_OBJ_VISIBILITY` output before claiming visibility support. Also reconcile local re-association settings with the official profile rather than treating the preparer's small YAML additions as a complete tuned configuration.

Installed inspection pins: `nvtracker_proc.cpp` SHA256 `a54f2b26fe3822b6780f251a3101cdc065b9bff92a89fbe6af75c5be47e37234`; low-level tracker library SHA256 `24a960f66b721b2dda4db360a5620b9ed19df65ef4e69eb093eceb9b8e708c22`. Existing disabled/unqualified manifest status remains appropriate; native files were not changed for this review.

## Staged integration and promotion

1. **Keep the present baseline.** Current traffic and pedestrian recordings are independent, have different dimensions and have no shared calibration. Keep camera-local IDs, no global count, and unavailable map positions where calibration is absent. Improving their RTSP codec/timing does not make them overlapping views.
2. **Obtain one paired intersection episode.** Use two fixed, equal-resolution cameras with validated projection, overlap and common capture time. Include pedestrian occlusion, two nearby people moving together, a stationary vehicle, entry/exit, reconnect, and a deliberate peer-message outage. Keep simulator actor labels only in the held-out evaluator.
3. **Qualify single-view 3D first.** Reuse RF-DETR preprocessing/parser and NvDCF CUDA. Add class-appropriate camera files and 3D state estimation. Verify metre positions and output metadata against landmarks and object trajectories before turning on peer association. Test people first; leave other classes on the baseline path until their geometry is qualified.
4. **Add local peer communication.** Generate and review the native `ObjectModelProjection`, `MultiViewAssociator` and `Communicator` sections against the pinned SDK. Use explicit CUDA, no PVA, pose off, strict class matching, isolated MQTT topics and correct camera/source ordering. Resolve the visibility discrepancy. The [official utility documentation](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/src/apps/reference_apps/deepstream-tracker-3d-multi-view/utils/README.md) explains the existing-2D-config conversion path. The auto-configurator can enable pose by default, so inspect its generated result.
5. **Implement the metadata/event adapter.** Preserve separate observed, predicted and peer-supported states; map ID corrections safely; test JSON/metadata serialization, missing peer data and restart epochs. Show one fused map track only when its identity and position are qualified. Keep per-camera ROI evidence and backend event authority.
6. **Compare and then promote.** Use the same detector and episodes for baseline versus MV3DT. Measure IDF1/HOTA, ID switches, false merges, duplicate global tracks, occlusion recovery, per-class position error, event count error, capture-to-display timing, CPU/GPU/memory and MQTT delay. Set numeric acceptance gates before tuning. Run the full VSS/Ask soak with the saved reserve; build and test Thor separately. Configuration presence and a publisher FPS table do not pass these gates.

A proposed deployment status remains explicit until those steps pass:

```json
{"enabled":false,"runtimeQualified":false,"reason":"overlapping calibrated episode and native metadata adapter not yet qualified"}
```

## License boundary

The reference source files carry Apache-2.0 notices; the repository's root license separately identifies documentation/assets terms. The packaged SDK runtime and low-level tracker remain subject to NVIDIA's DeepStream terms. Model checkpoints and third-party MQTT components retain their own terms; a repository's Apache license does not relicense all runtime binaries or downloaded models. Keep required notices and pin the actual chosen assets. [Reference source license](https://github.com/NVIDIA/DeepStream/blob/844bff0c44f691fe392e10d692f349da20431a71/LICENSE), [DeepStream EULA](https://developer.nvidia.com/deepstream-eula).
