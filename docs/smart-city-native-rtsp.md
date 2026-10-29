# Two-camera native Isaac RTSP — October 23

**Current performance profile:** the two cameras now use **960×540** with a 30-FPS target and matching processing surfaces. Normal RTPT image quality and every-frame inference are retained. Calibration revision is `isaac-live-1769960ebf2c79c5`; all 14 rules and the mobility setup were preserved. [Performance work and current checks](smart-city-performance-2026-10-23.md).

The following transport qualification is the earlier **1280×720 cutover**, before the resolution change.

The original Spark cutover used NVIDIA's native H.264 RTSP writer for both cameras. It kept 1280×720 resolution, the same camera poses, the same VSS source UUIDs and the same calibration revision. RF-DETR Medium FP16 and the experimental MV3DT map profile are unchanged. This replaces the external CPU `libx264` camera encoders. The detector still uses CPU decoding; this change does not qualify a new decoder.

## Data path

| Step | Southwest | Northeast |
| --- | --- | --- |
| Isaac native H.264 origin | `rtsp://127.0.0.1:18560/cam_SW` | `rtsp://127.0.0.1:18561/cam_NE` |
| Existing packet relay | `rtsp://172.17.0.1:18556/cam_SW` | `rtsp://172.17.0.1:18556/cam_NE` |
| Existing VIOS UUID | `997d3a69-e052-45a4-a1ce-be1b046670c4` | `40af41ea-2180-4b7b-83d6-bb5d08ff094a` |

The origin uses Isaac 6.1's `LdrColor` H.264 render path and in-process RTSP server. The native plugin loads the NVIDIA encode library. MediaMTX pulls the already encoded streams over TCP and relays packets; it does not decode or encode them. VIOS retains recording and its existing proxy URLs. DeepStream processes those same registered sources, then posts exact image/metadata pairs to the Smart City UI. Native GPU encode utilization was not independently measured: `nvidia-smi` reports zero active encoder sessions on this host even while the native stream decodes. Do not use that counter as a throughput result.

Only two camera stream render products exist, plus the separate GUI viewport. At this cutover the profile requested 15 FPS; this is a target, not a measured 15-FPS result. The native bitstream can advertise 60 FPS in its codec metadata despite the server's 15-FPS caps. Measured frame timestamps and received progress take precedence over that advertised number.

## Timing correction

The stock H.264 writer uses simulation time for RTP timestamps. The city runs below wall rate under the combined workload. Initial real decode confirmed about 1.1 seconds of media progression across 34 frame intervals, while frames arrived more slowly. That would distort retained-video timing.

The city wrapper now passes monotonic real-time intervals to NVIDIA's pre-encoded streaming API. It preserves the original encoded bytes and puts both simulation time and UTC in SEI metadata. The timestamp is sampled when the encoded image reaches the Python callback; it is **not measured sensor exposure time**. UTC changes do not rewind the monotonic RTP clock.

Two 80-frame relay decode checks measured:

| Camera | Media interval | Received interval |
| --- | ---: | ---: |
| Southwest | 6.089 s | 6.080 s |
| Northeast | 5.827 s | 5.821 s |

The later integrated check also measured source-clock/wall-clock ratios near 1.0. These results verify time progression. They do not prove absolute synchronization between cameras, exposure timing or end-to-end latency. The existing experimental MV3DT display still applies its own time, geometry, identity and visibility gates; rules and counts remain camera-local.

The native server can return `False` before a reader connects or while downstream is full. The wrapper counts those rejected handoffs and keeps the server available. They are not counted as successful pushes. Actual exceptions record the first failure and latch the stream, even if cleanup also fails. The rejected-first-frame development failure is preserved in the QA directory.

## Checks and evidence

The [60-second pipeline check](qa/smart-city-2026-10-23/native-rtsp/pipeline-60s.json) passed with 552 new observations per camera, 12 exact processed-preview checks per camera, no duplicate/backward timestamps, sequence gaps, session changes, clock rollbacks or monitored container restarts/OOM events. Minimum available memory was 20.956 GiB with the saved 20-GiB guard active. No VLM question was run during this check.

The [final simulator/recording check](qa/smart-city-2026-10-23/native-rtsp/isaac-final-60s.json) passed 60 seconds using the final monitor source. Both native cameras stayed above **9.46 FPS** in its rolling handoff windows; both recent five-second recording windows stayed ready. Minimum available memory was 20.816 GiB. A prior 60-second check passed with a 9.28-FPS minimum and is retained separately. Neither monitor claims a measured bound for native encoder queues; that API does not expose queue depth.

The immediately preceding software sample was 8.96 FPS over eight seconds. This is not a controlled performance benchmark. Workload and scene variation prevent a defensible speedup percentage. The main verified change is removal of external CPU camera encoding; rendering, fixed 576×576 detector inference and other VSS work still limit throughput.

Twenty-two city CPU tests cover profile limits, selected-camera native setup, runtime checks and encoded-frame clock/failure behavior. Ninety-nine VSS CPU tests cover launcher/monitor, geometry reuse and MV3DT profile controls. The browser showed both frame-matched camera views, detections, zones and the live map. `isaac_demo.py start` returned already ready without regenerating site geometry. See [deployed identities and limits](qa/smart-city-2026-10-23/native-rtsp/deployed.json).

This is short operational validation. Full-day endurance, detector accuracy, absolute camera synchronization, native queue bounds and MV3DT tracking accuracy remain separate work. No model image or TensorRT engine was rebuilt. The camera resolution was not reduced.

## Operator controls

Use the existing commands from `/home/sparkdev/vss`:

```sh
python3 tools/smart-city/isaac_demo.py status
python3 tools/smart-city/isaac_demo.py start
```

Open **http://127.0.0.1:7782/?workspace=smart-city**. Default Start validates the saved stage, camera prims, dimensions and calibration identity. It preserves the map, 14 rules, source UUIDs and MV3DT profile. It checks both configured and attached backends, so an old software dropdown selection cannot pass as native readiness. Native and explicitly backend-only world rules must all be accounted for at the current applied revision.

Reviewed camera changes can use `start --refresh-calibration`; this refreshes the site and mobility preset and is not required for a codec-only change. New resolution or camera geometry also requires review/regeneration of image-space rules and the MV3DT calibration/profile and gateway allowlist. Do not reduce the resolution while retaining stale matrices.

Source configuration:

- City `config/survey_intersection_A.json`: `rtsp.backend=native`, native `encoding=h264`, ports 18560/18561.
- City `config/vss_camera_profile.json`: southwest/northeast, now 960×540 with a 30-FPS target.
- City `config/vss_rtsp_relay.json`: saved native pull-relay configuration. Its active copy is `logs/vss-integration/mediamtx.yml` and the existing user service reads that copy.
- The native setup guard remains. This two-camera profile permits four setups, retaining the historical conservative eight presumed-session budget from the earlier four-camera x86 configuration. This is not a measured GB10 hardware/session limit. Three setups were used during this cutover. If the guard is exhausted, use the reviewed Isaac restart workflow; do not reset the counter to bypass it.

The first detector resume was refused because available memory was below the reserve plus 4-GiB cold-start margin. Releasing only this task's UI development cache allowed normal source resume; the same UI container was then restored. The saved reserve and guard were retained. Current combined headroom is narrow, so do not add another heavy GPU job during the demo. Existing media and unrelated services were preserved.

The **960×540** change is now deployed through the separate reviewed migration linked above. It has 43.75% fewer source pixels, but the detector's fixed input remains 576×576. Any measured improvement must be weighed against lost detail for distant people and bikes.
