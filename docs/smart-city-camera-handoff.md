# Smart City camera and map handoff

The VSS implementation can be developed with recorded videos. The shared city map requires the final static camera package. This handoff does not open, change or approve an Isaac Sim environment.

Start with [the site template](../deploy/docker/smart-city/site.example.json). Replace its placeholder IDs with the actual UUIDs returned by VSS camera registration. Add the RTSP sources through the existing Agent first; the city controller verifies their registered URLs and dimensions. The final source order must match `deepstreamStreamIndex` when native analytics rules compile.

Provide these files for the approved scene:

| File | Required contents |
| --- | --- |
| Site geometry | One common, right-handed metre coordinate frame; XY ground plane, +Z up; map bounds; road centreline points with widths and building footprint polygons. |
| Camera calibration | Actual decoded width/height, image-to-ground homography, valid ground coverage polygon in site metres, calibration revision and lens convention. Export intrinsic K and world-to-OpenCV-camera extrinsics as well for reprojection checks and optional MV3DT. |
| Held-out landmarks | Pixel/world pairs that were not used to fit calibration; include near/far points, road edges and zone boundaries. Measure ground error rather than accepting a visually plausible overlay. |
| Timing | Camera source-clock basis, RTCP sender report evidence, paired timestamps and measured clock/video uncertainty. Clock offsets introduced by the VSS preview path must also be measured. |
| Paired recordings | Same episode from both final camera positions, covering overlap, occlusion, close same-class objects, ordinary traffic and each intended incident. Keep simulator labels separate from inference inputs. |

The map is a 2D vector view. Its road/building coordinates and projected track positions use the same site frame. Screen placement fits `map.bounds`, with north/up and metres kept explicit. A stable rendered top-down image can be used as a background only when its pixel-to-site transform matches those bounds. Animated ground-truth actors must not be drawn behind inference markers as if they were model output.

For each real observation, the backend takes the decoded bounding-box bottom centre, applies the camera homography and rejects points outside the qualified ground polygon. It preserves the source time and camera-local identity. This anchor is an approximation to ground contact, especially for long vehicles; it is not a verified object centroid or a precise collision-distance measurement. Measure its bias before setting narrow boundaries, speed thresholds or proximity claims. Missing calibration yields no ground position.

The existing `/home/sparkdev/isaac_city_sim/config/camera_calibration.json` is an unverified starting asset. Do not load its transforms into a different city or assume a new camera render resolution preserves its calibration. No manager-provided scene has been approved by this implementation.

Test camera-to-map selection and trails against the held-out landmarks, then test source loss, reconnect, timestamp rewind, camera crop/resolution change and rule edits. Keep `browserClockVerified` false until the actual presented video and native source timestamps have passed the temporal comparison. A matching timestamp alone is not evidence that the preview retained the correct clock.

For overlapping coverage, first define non-overlapping primary counting areas so a camera-local count is not presented as a deduplicated site-wide count. Keep identities camera-local while association is ambiguous. The [optional MV3DT preflight](../services/rtvi/rt-cv/smart-city/README.md#optional-mv3dt-package-preparation) requires full 3D calibration, synchronized same-resolution overlapping images, independent 3D landmarks and explicit per-class geometry. MV3DT is the first native fusion candidate to test for that calibrated overlap, rather than a prerequisite for per-camera ROI detection. Its generated configuration remains disabled until identity, duplicate rate, position error and occlusion recovery pass predeclared gates against the baseline on the paired recordings.

The present worker emits no global identity (`globalTrackId: null`), and the gateway does not fuse the unrelated traffic and pedestrian clips. Enabling MV3DT requires all of the following: validated same-episode equal-resolution images; source-clock alignment through the actual media path; full 3 × 4 world-to-pixel projections with non-ground held-out landmarks; class-appropriate geometry; an SDK-validated 3D/MQTT tracker profile; and a new fused-ID/position/event adapter with explicit observed versus predicted provenance. The existing utility generates disabled cylinder-only geometry for all six classes; a people-first experiment needs an explicit class-scoped runtime profile. Ground homographies alone, a common HTTP receive time, or a successful configuration-generation command do not enable fusion.

Start the paired evaluation with one pedestrian occluded by a bus in one camera while visible in the other, then nearby same-class objects, crossing trajectories, vehicle class geometry, asymmetric camera loss and reconnects. Compare ID switches, false merges, duplicate tracks/counts, occlusion recovery, metre-position error and full VSS resource use. No actual MV3DT runtime, fused-identity accuracy or speed has been validated here. See the [MV3DT decision and remaining enablement gates](smart-city-mv3dt-decision.md).

The supplied example is a configuration template, not a scene proposal approval or a deployment instruction. The approved scene package and its measured qualification receipt determine the final booth configuration.
