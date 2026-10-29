# Native RTSP / VIOS clock and MV3DT anchor audit — 2026-10-26

This is a bounded diagnostic, not a multi-camera accuracy qualification. No
camera, detector input, model, fusion threshold, class eligibility or runtime
service setting was changed by this audit. The parent task separately restarted
the CV workers while reloading the normal demo/controller code; the old and new
worker epochs must be assessed separately.

## Main finding

The old worker's roughly 449 ms difference between its newest camera timestamps
was real in its emitted metadata. It is not explained by sustained encoded-video
delivery delay through VIOS in the simultaneous 30-second experiment. The same
844 encoded camera access units arrived through both paths. Median extra parsed
AU delivery time through the relay chain was about 0.7 ms, with about 41 ms at the
90th percentile. After the independently coordinated normal worker restart, the
large clock separation disappeared without changing its RTSP inputs.

Keep the existing capture-time, class, session, epoch, visibility and distance
guards. Do not widen them to hide an input clock issue, or assume that another
shared SDK ID necessarily identifies the same physical object.

## Preserved old-worker evidence

Receipt and exact 500-row tail:

```
.spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/
  1792991526595279087-receipt.json
  1792991526595279087-tail.ndjson
```

The read was bounded to 16 MiB of the rolling observation file; it did not load
the full recording. Epoch `fc3ef4af-8bd7-4982-b55f-75b9e9242c9c` had 250 frames per
camera over 16.745 seconds, all `source-rtcp`, without a session/clock reset.

| Measurement | Result |
| --- | --- |
| Newest-per-camera clock difference | 448.774 ms |
| Reconstructed newest-per-source states within 150 ms | 0 / 499 |
| Historical nearest-clock frame difference | median 12.72 ms, p90 44.07 ms, maximum 58.67 ms |
| Historical directional frame pairs within 50 ms | 229 / 243 |
| Same SDK person ID, observed in both, visibility at least 0.25, within 50 ms | 168 candidate pair observations, 3 IDs |
| Current post-tracker rect-bottom homography disagreement | median 0.654 m, p90 1.167 m; 132 / 168 within 1 m |
| Native SDK world-foot disagreement | median 0.328 m, p90 0.946 m; 155 / 168 within 1 m |
| Native SDK image-foot projected through person-plane homography | median 1.117 m; 62 / 168 within 1 m |

The old receipt's newest northeast source timestamp was approximately 331 ms
**ahead** of the analyzer's wall clock; southwest was about 118 ms behind. Since
the native publisher and worker share this host, an incorrect RTCP-to-frame
mapping must be considered alongside queue backlog. The 449 ms difference must
not be described simply as proof of an old southwest pixel queue.

These distances compare consistency between views, not independently measured
position errors. The image-foot and world-foot values should not be treated as
interchangeable anchors merely because they are in the same SDK record. Some
later new-epoch windows favor the current rect anchor instead. These results do
not justify replacing the current map anchor globally.

For vehicles in particular, opposite-view bbox-bottom rays can land on opposite
parts of the visible vehicle rather than its ground footprint center. A large
rect-anchor disagreement can therefore occur even with correct detections and
calibration. SDK world-foot consistency is a useful separate candidate, but
neither its better agreement nor a shared ID proves center accuracy or identity.

The live invocation did not enable `--tracker-diagnostics`. Therefore `bboxPx`
is the worker's clipped **post-tracker `rect_params`**, not an independent raw
detector box. The source already supports the optional diagnostic export of
`detector_bbox_info`, `tracker_bbox_info` and native 3D metadata; see
[smart-city-tracker-diagnostics.md](smart-city-tracker-diagnostics.md).

## Simultaneous encoded-only path experiment

Both captures began at 2026-10-26 05:14:36.777 UTC, within 0.6 ms of each other,
and ran for 29.995 wall seconds. The names are experiment labels; manifest
timestamps are the clock authority. Two existing utility instances ran under
`--runtime=runc`, one CPU and 512 MiB each, with no NVIDIA device runtime,
decoding, rendering, inference, installation or service restart.

| Camera | Native origin | Existing VIOS proxy |
| --- | --- | --- |
| Southwest / `997d3a69-e052-45a4-a1ce-be1b046670c4` | `rtsp://127.0.0.1:18560/cam_SW` | `rtsp://127.0.0.1:30557/live/997d3a69-e052-45a4-a1ce-be1b046670c4` |
| Northeast / `40af41ea-2180-4b7b-83d6-bb5d08ff094a` | `rtsp://127.0.0.1:18561/cam_NE` | `rtsp://127.0.0.1:30558/live/40af41ea-2180-4b7b-83d6-bb5d08ff094a` |

Preserved captures:

```
.spark/city/media/expo-origin-ab-20261026T0516Z/
.spark/city/media/expo-vios-ab-20261026T0516Z/
```

Each has `capture.json`, two MKV files and per-AU timing sidecars. Both manifests
are complete, EOS-finalized and error-free, with 422 AUs per camera. The clients
use the same existing 200 ms jitter-buffer configuration.

VIOS adds its own SEI, so full AU hashes differ. The CPU-only analyzer verifies
each stored packet against its timing-sidecar hash, then compares canonical VCL
NAL hashes **and** the original native UUID SEI (`timestamp`, `frame_num`,
`publish_sim_time_ns`). All 422 AUs per camera match, including identical native
SEI. The tool refuses ambiguous repeated matches and never decodes a picture.

Final enriched comparison receipt:

```
.spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/
  origin-vios-clock-ab-20261026T0516Z-final.json
```

| Same-AU measurement | Southwest | Northeast |
| --- | --- | --- |
| Matched VCL + original native SEI | 422 / 422 | 422 / 422 |
| Extra proxy receive time, all matched AUs | median 0.705 ms, p90 41.369 ms, max 57.032 ms | median 0.666 ms, p90 41.446 ms, max 71.211 ms |
| Extra proxy receive time, after both references available | median 0.670 ms, p90 41.356 ms | median 0.655 ms, p90 41.446 ms |
| Proxy minus origin RTCP reference for the identical AU | median 0.061 ms, range 0.011–0.082 ms | median 14.925 ms, range 14.886–14.957 ms |
| Matched AUs with both RTCP references | 303 | 338 |

Some initial receive differences are negative because the independent jitter
buffers release startup data differently. These are observation timestamps at
the parser, not network transit measurements. Missing initial sender-report
references remain missing; they are not treated as zero time.

All 422 camera pairs also share the exact native `frame_num` and
`publish_sim_time_ns`. Southwest encoded-frame handoff occurs a median 0.337 ms
before northeast (maximum absolute difference 1.108 ms). For those same render
ticks, RTCP reference southwest-minus-northeast is about 29.40 ms on the two
direct origin clients and 14.52 ms on the two VIOS clients. This separates a
shared simulation tick and closely timed encoded handoff from the RTCP-derived
reference clock. It does not prove simultaneous sensor exposure.

## What the code/configuration proves

### Five-minute check of the fresh worker epoch

The parent task restarted the normal CV worker without changing its native
image, detector inputs or RTSP configuration. A CPU-only observer then sampled
the last 500 complete observation rows every 30 wall seconds for 300.033
seconds. All 11 saved windows retain the same fresh epoch
`d2b1cdad-02fb-4f97-92f9-d55aedd29b79`; no restart or adjustment was performed by
the observer.

```
.spark/city/runtime/intersection-rebuild-20261026/mv3dt-bounded-audit/
  current-epoch-monitor-1792991921884553623/summary.json
```

The windows contain 5,500 distinct observations, with no duplicated rows
between samples. They are sparse diagnostic windows, not a continuous endurance
or accuracy qualification. Current-epoch newest-pair skew has a per-window
median of 35.37–41.12 ms. A total of 5,441 / 5,487 reconstructed newest-per-source
states meet the unchanged 150 ms window. There are occasional larger gaps
(maximum 344.17 ms), but the old sustained 449 ms separation did not recur.
At each sample, both newest source clocks were behind analyzer wall time
(38–156 ms), rather than ahead of it.

All six configured city classes were considered. The following are **same SDK
ID candidate pairs** with both objects observed, visibility at least 0.25,
matching class/calibration/current epoch and at most 50 ms source-clock
difference. These are anchor-consistency counts, not actual UI join rates or
independently labelled identity/position accuracy.

| Class | Candidate pairs / distinct SDK IDs | Rect-bottom disagreement median / p90 | Native world-foot disagreement median / p90 | Rect / world within 1 m |
| --- | --- | --- | --- | --- |
| Person | 2,058 / 29 | 0.925 / 1.338 m | 0.735 / 1.106 m | 1,196 / 1,684 |
| Car | 258 / 9 | 2.579 / 3.152 m | 0.954 / 1.340 m | 0 / 144 |
| Truck | 15 / 2 | 2.889 / 3.401 m | 0.975 / 1.319 m | 0 / 9 |
| Bicycle, motorcycle, bus | 0 shared-ID candidate pairs | Not measured | Not measured | Not measured |

Motorcycles and buses do have many native observed records in both cameras;
zero shared-ID pairs does not establish zero physical overlap, nor successful
fusion. No bicycle observations occurred in these sampled records. No
same-frame SDK-ID omissions or cross-camera class contradictions were recorded
in this sampled dataset. Raw tracker diagnostics remained disabled throughout.

The better vehicle world-foot consistency is a reason to evaluate that anchor
against a few labelled same-vehicle frames. It is not authorization to admit
vehicle map joins or widen the 1 m distance gate. Person world-foot consistency
also varies by window, so it needs the same local validation.

All original window metrics were reproduced from their saved tails with the
checked-in audit helper; the summary records its hash and the calibration-file
hash. The encoded A/B manifests, timing sidecars, MKVs and analysis source hashes
are listed in `origin-vios-artifact-identities.json` beside the A/B receipt.

### Source/configuration observations

* The worker obtains `sourceTimeNs` from `NvDsFrameMeta.ntp_timestamp`, uses
  `attach-sys-ts=false`, TCP RTSP and `configure_source_for_ntp_sync`. It does not
  parse the native source SEI into each inference observation. See
  `services/rtvi/rt-cv/smart-city/src/city_worker.cpp` at the source-time selection,
  `source_setup` and mux construction.
* The current worker uses the two VIOS proxy URLs above. The map frontend groups
  only currently displayed, observed people with the same SDK association,
  current sessions/calibration/epoch, at most 150 ms apart and within 1 m on
  initial joining. Vehicles remain camera-local.
* The active VIOS configuration has `network.use_sensor_ntp_time=true`.
  `services/vios/src/modules/rtsp_server/rtspserver.cpp:446` passes this to
  `ProxyServerMediaSession::useCameraNtpTime(true)`.
* There is another hop before VIOS: native per-camera servers → MediaMTX at
  18556 → VIOS. The running MediaMTX executable reports v1.21.2; its active
  `isaac_city_sim/logs/vss-integration/mediamtx.yml` omits
  `useAbsoluteTimestamp`. In that exact release, the default is false and the
  RTSP source sets `ReplaceNTP: !pathConf.UseAbsoluteTimestamp`. Thus that hop
  normally replaces incoming absolute time. This explains why it must be
  included in clock provenance review, but the measured same-AU reference
  changes above are small and do not explain the old 449 ms disparity.
  [Version-pinned configuration](https://github.com/bluenviron/mediamtx/blob/v1.21.2/mediamtx.yml#L490),
  [version-pinned RTSP source](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/staticsources/rtsp/source.go#L379).

The source code alone cannot establish whether the old worker had unequal
decoder backlog, a long-lived sender-report mapping error, or another startup
clock effect. A fresh external capture does not reproduce that existing
worker's RTCP client state. Restarting that worker also changes its client
state, so disappearance after restart narrows the fault but does not identify
one of those causes conclusively.

## Recommended next bounded trial

1. Preserve the normal current worker epoch and observe whether its clock
   separation reappears. Record same-epoch per-source clock age as well as the
   newest-pair difference; do not compare across restart boundaries.
2. On recurrence, correlate a bounded native SEI AU identity and independent
   RTCP reference with the matching decoded PTS and DeepStream frame metadata.
   The existing SEI is preserved by both relay hops, so this can be CPU-only
   diagnostic metadata with a bounded PTS lookup. It can distinguish old pixels
   from a bad timestamp assigned to current pixels. No extra model is needed.
3. Use a short diagnostic run with the already available
   `--tracker-diagnostics` export before testing alternate map anchors. Compare
   independent detector boxes, tracker boxes, rect boxes and SDK world feet on
   the same labelled people/vehicle frames. Keep the existing association gates
   and report each class separately.
4. Test direct-origin detector input only as an isolated path change if the
   measured evidence identifies the relay/client path as the cause. Keep the
   same VSS source IDs, calibration and UI. A common-time preview buffer is a
   separate remedy for genuinely unequal pixel arrival, not a substitute for
   repairing an incorrect source clock.

NVIDIA describes NTP-based peer tracklet alignment and explicitly warns that
proximity/similar motion can cause incorrect SDK associations. Native IDs and
world feet still need local accuracy checks before vehicle map grouping is
enabled. [DeepStream 9.2 MV3DT](https://docs.nvidia.com/deepstream/9.2/text/DS_MV3DT).

## Reproduction tools

```
.spark/city/export-env/bin/python tools/smart-city/compare_rtsp_clocks.py \
  --origin .spark/city/media/expo-origin-ab-20261026T0516Z \
  --proxy .spark/city/media/expo-vios-ab-20261026T0516Z \
  --output NEW_UNIQUE_RECEIPT.json

python3 tools/smart-city/audit_live_tail.py
```

The comparison output is created exclusively and refuses to overwrite a
receipt. The live-tail audit reads at most 4 MiB and analyzes at most 500 complete
rows, pairing only the newest common epoch/sessions. Eight comparison parser
tests and six tail/guard tests pass, including added SEI, malformed inputs,
ambiguous IDs, epoch boundaries and unchanged 50/150 ms windows. No changes were
made to the people controller during this diagnostic.
