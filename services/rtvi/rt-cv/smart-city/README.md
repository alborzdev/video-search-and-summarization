# Smart City native perception worker

The selected Spark application uses RF-DETR → one native MV3DT tracker → `nvdsanalytics` in DeepStream 9.2. NVIDIA's DCF visual tracking runs inside that native tracker; no separate NvDCF stage is selected. The worker also retains historical diagnostic modes. Integration/configuration launch scripts live in `tools/smart-city/`.

## Quality-first scheduling and decoder experiments

The [October 27 optimization receipt](../../../../docs/smart-city-optimization-2026-10-27.md) records the measured promotion decisions. Live detection remains on every admitted frame. In the preprocessed-tensor path, stock `nvinfer.interval` does not control inference; the launcher still rejects the ineffective `inferenceInterval` setting.

`--detector-cadence 2` or `3` is an **offline native-MV3DT quality experiment**, with `--output` and no HTTP observations/preview. A schedule stamped before preprocessing counts admitted frames independently for each source, including partial mux batches. The custom tensor callback packs only selected frame ROIs; when none are selected it returns `NVDSPREPROCESS_TENSOR_NOT_READY`. The SDK keeps video buffers ordered, forwards frames without tensor inference, and updates MV3DT on every admitted frame. `detectorRan`, `detectorCadence`, exact detection stamps, null confidence on tracker-only outputs and the SDK's `bInferDone` are checked independently. Live consumers conservatively require detector observations, and these candidates failed the current quality comparison, so they cannot be selected accidentally for live delivery.

Native preview status now includes bounded `pipeline` counters for full/partial batching, inferred/tracked frame counts and preprocess/inference and tracker/analytics path latency. These include asynchronous waiting and downstream contention; they are not isolated GPU-kernel times or physical capture-to-screen measurements. With `--tracker-diagnostics`, observations also include per-frame path timings and batch occupancy.

The decoder's optional `--decoder-extra-surfaces 0..8` and `--decoder-low-latency` controls are explicit experiments. The latter requires a verified I/P-only stream; it must not be enabled for arbitrary cameras with B frames. `runtime-tuning.json` accepts `decoderExtraSurfaces` and `decoderLowLatency` only with explicit hardware decoding. Status reports the selected decoder factory and surface count. More surfaces alone do not establish correctness or faster live playback; fresh delivery, restarts, exact capture-clock correlation and latency must pass together. Existing source/preview queue limits and memory guard remain active.

The [October 28 quality investigation](../../../../docs/smart-city-mv3dt-quality-2026-10-28.md) selects a 50 ms live mux wait and an 8 FPS display-preview ceiling after CPU delivery repairs. Detection and native tracking still run on every admitted frame. Temporary raw tracker diagnostics are disabled in the selected live profile. This bounded setup improves batching and keeps delivery current; shared vehicle identities, especially buses, remain incomplete.

## Native capture startup and source colours

A live RTSP join can begin after a picture’s native SEI was transmitted. Before the first proven picture only, the worker discards at most eight such incomplete pictures, within two seconds, before decode. It still requires exact native evidence for every admitted picture. Invalid metadata, recordings without proof, and missing proof after the first valid picture remain fatal; timestamps are never fabricated.

Each source converts to CUDA RGBA **before** muxing, preserving its decoded YUV range and matrix. Batching NV12 first introduced a small colour shift on the full-range BT.709 Isaac recordings. Exact first-frame tensors now match NVIDIA’s reference source pipeline byte for byte on both cameras. Emitted observation and preview revisions include `;color=source-rgba-v1`. This establishes input parity, not tracking accuracy.

## Build and model contract

Build in the pinned DGX Spark DeepStream 9.2 container. The tested package versions are **TensorRT `10.16.1.11-1+cuda13.2`** and CUDA runtime `13.2.75-1`, from `ghcr.io/nvidia/deepstream:9.2-triton-sbsa-dgx-spark`. The stock image already contains the compiler, CUDA toolkit, GStreamer development packages and libcurl development package:

```sh
make -C services/rtvi/rt-cv/smart-city
make -C services/rtvi/rt-cv/smart-city test
```

Install the resulting worker/libraries into `/opt/city` and configs into `/opt/city/configs`, or set their absolute paths in runtime configs. Do not reuse a binary or TensorRT engine built against another DeepStream/CUDA/device combination.

The model contract is RGB with a direct square resize and NCHW FP32 input named `input`: Small uses 512 × 512 and Medium uses 576 × 576. Large uses 704 × 704. Medium is the current explicit Spark selection (576 × 576, FP16-enabled TensorRT, batch two), restored on October 28 for the smaller-model trial. Large remains staged for comparison; Small remains the generic fallback when no device-local selection exists. The launcher materializes matching model/preprocess configs rather than changing the source templates. The exported graph exposes `dets` (normalized centre-X, centre-Y, width, height) and `labels` (raw independent logits), both FP32 outputs; TensorRT may use FP16 internally. Match the actual pinned graph names and batch profile. The reference decoder uses sigmoid and global query/class top-300, then filters the city capabilities. The live parser additionally applies the explicit query policy below. Spatial NMS is disabled. Custom models with contiguous category IDs require their own explicit parser map; they must not use the pretrained sparse COCO map accidentally.

For the live tracker, the parser now applies `one-city-class-per-query-v1` after the reference selection: only the highest-scoring city class from each RF-DETR query becomes an object. The reference `decode` remains unchanged for benchmark comparisons; `decode_for_tracking` adds this explicit object-counting policy. This removes a single query's competing bus/truck labels from the tracker input. It does not merge distinct queries by spatial overlap, and it does not correct a wrong winning class. The worker appends `;postprocess=one-city-class-per-query-v1` to its emitted model revision; the selected engine and its historical reference-quality receipts keep their existing hashes.

The [paired cached-output comparison](../../../../docs/qa/smart-city-2026-10-23/sprint-query-policy-comparison.json) used the existing actual Medium FP16 batch-two outputs on all 100 pinned COCO images, with no new GPU inference. Six-class AP changed 57.803→57.681 (−0.122 percentage points); coarse AP changed 56.700→56.706. At the live 0.35 threshold, 826 predictions contained 4 extra labels for already-selected queries; the new policy retains 822 predictions and zero same-query extra labels. This small aggregate tradeoff is accepted for object counting. These results are a paired engineering proxy, not final simulated-camera accuracy. `make parser-test` checks the actual exported parser with CPU tensors; GPU and live tracking qualification remain separate.

The six **DeepStream class IDs** are: person=0, bicycle=1, car=2, motorcycle=3, bus=4, truck=5. COCO van is not a separate class. `rfdetr_core.hpp` maps sparse pretrained slots 1,2,3,4,6,8 explicitly.

`nvdspreprocess` establishes full-frame ROI/tensor ownership. The custom tensor function samples the original RGBA GPU surface directly, implements bilinear half-pixel resize in float (`align_corners=false`, `antialias=false`), and applies ImageNet mean/std per channel. It intentionally does not normalize a byte-quantized resized image or use the shared `nvinfer` scale. The transformation callback's intermediate byte pool is not sampled. NVMM GPU RGBA input is mandatory and validated. `make test-gpu` checks the production kernel against a CPU reference, including nontrivial row pitch and unequal input/output aspect ratios. Run it under the same GPU memory guard as inference.

## Run

Example paths and IDs below must be replaced with registered source IDs and pinned model files:

```sh
/opt/city/city-worker \
  --source traffic-west=file:///data/traffic-west.mp4 \
  --source traffic-east=file:///data/traffic-east.mp4 \
  --site-id expo-intersection \
  --config-dir /opt/city/configs \
  --analytics-config /opt/city/generated/analytics.ini \
  --analytics-ack-file /opt/city/generated/analytics-ack.json \
  --post-url http://vss-city-analytics:9184/api/v1/city/observations \
  --output /data/observations.ndjson \
  --cpu-decode
```

`--cpu-decode` skips the NVIDIA hardware decoder and uploads CPU-decoded frames through GPU `nvvideoconvert`; use it on Spark if its platform codec path requires CPU decode. The software path passed actual H.264 traffic and pedestrian decoding. Stock DS 9.2 omits runtime codec libraries: the derived image must install `gstreamer1.0-libav` and restore the packaged-but-removed libraries with `apt-get install --reinstall libvpx9 libmp3lame0 libx264-164 libx265-199 libmpg123-0t64`, then regenerate its GStreamer plugin registry. The hardware path remains device-specific. `--width/--height` control mux geometry (default 1920 × 1080); all boxes are explicitly scaled back into each original decoded image. For representative benchmark timings, `--unpaced` removes playback pacing; normal demo playback is paced. `--frames N` bounds a validation run. EOS exits cleanly; a runtime restart creates new source sessions. Each new worker run uses a new per-source UUID and starts local sequence at zero.

File observations carry `mediaTimeSeconds` from `gst_segment_to_stream_time`, applying the decoded stream's actual segment/edit-list mapping to raw PTS. They preserve `rawSourcePtsNs` separately and label `mediaTimeBasis: "gstreamer-segment-stream-time"`. `sourceTimeNs` uses one replay epoch plus this media timeline. The provided traffic clip starts at raw PTS 66.7 ms and the pedestrian clip at 200 ms, but both segment mappings put their first displayed frame at media time zero. Subtracting an arbitrary first PTS would mishandle seek segments with a nonzero timeline; raw PTS alone would misalign browser playback by those offsets. Missing file segment mapping stops inference visibly. This is labeled `recorded-pts`; it is not a recorded UTC capture date. RTSP uses source RTCP time when present, otherwise explicitly labels its session-clock approximation `arrival-pts-unsynchronized`. Cross-camera identity claims require proper source synchronization. In every case, image/event time remains separate from HTTP receipt time. Zero-object frames are emitted. The publisher queue is bounded (default 1024, adjustable with `--publisher-queue-size`). Unpaced file evaluation blocks the producer until the consumer catches up, preserving every observation. Live or paced overload stops visibly rather than silently dropping event data. Shutdown reports enqueued/published counts, peak queue size and producer waits. HTTP 200 alone is insufficient: the worker requires the backend acceptance receipt, with idempotent duplicate handling.

`observedThisFrame` is false for tracker-only objects with absent detector confidence. Confidence remains null in that case. Tracker IDs are strings; uint64 IDs are never sent as JavaScript numbers. Untracked provisional objects are omitted until the selected native tracker assigns an ID. The selected MV3DT mode exports native SDK world-foot metadata separately from the backend’s homography projection; the map uses only qualified native positions in this mode.

Recorded playback is paced once, on each source's `identity` element using that source's segment clock. The terminal `fakesink` has `sync=false`: waiting again on a mixed-frame-rate mux's batched timestamp caused a measured throughput regression. RTSP uses its own source/jitterbuffer clock, with no additional file pacing. This pacing rule is separate from timestamp provenance and does not make unrelated input clips synchronized views of one scene.

`--mux-timeout-us` sets the old mux's `batched-push-timeout` using a strict integer from 1000 to 1000000 microseconds. Its default remains 40000, preserving the measured file controls. Invalid values are rejected during CLI parsing before GStreamer or GPU initialization. A shorter timeout, such as 10000, is available for a controlled unequal-frame-rate **live** scheduling experiment; it is not a qualified preset merely because the flag exists. Compare source-clock advance against wall time, capture age, unique PTS, throughput and reserve with all other pipeline and resource settings fixed before retaining a live tuning value. The controller owns the bounded runtime-tuning setting and launch lifecycle.

### Optional correlated frame preview

Preview is off by default. The controller can enable it for the live Smart City profile with:

```sh
--preview-url http://127.0.0.1:9184/api/v1/city/preview \
--preview-fps 15 --preview-stats-file /state/native/preview-stats.json
```

This adds no RTSP reader and changes no inference interval. A post-analytics tee retains the lossless observation path and sends a separate, bounded display branch through `nvstreamdemux`, per-source leaky queues, GPU conversion/download to system-memory I420, software `jpegenc` and `appsink`. The FPS option is a per-source ceiling (integer 1–30, default 15), rather than a measured display rate. A 10 FPS source cannot provide 15 distinct frames per second. JPEG quality is 70; each body is capped at 2 MiB. Installed `jpegenc` 1.24.2 exposes no codec thread-count option; each source has one GStreamer encoding stream worker. Encoding throughput and contention still require the actual two-source load test.

Each observation's immutable source ID, session, sequence, source time, model revision and original image dimensions are attached to its frame before demux. An opaque unique encoder PTS maps to that provenance in a bounded 32-entry map per source. Only the preview buffer header and its private zero-based segment use that token. Camera PTS, observation timestamps and durable event ingestion remain unchanged. Duplicate camera timestamps and session resets cannot be paired by nearest timestamp or HTTP arrival. A JPEG without its exact token or with different encoded geometry is discarded. There is no OSD in the image; the UI draws boxes from the matched observation.

`nvstreamdemux` retains references to the batched surfaces and does not restore source resolution. The branch therefore restores each source's original dimensions after demux and bounds both batch and per-source queue depth at one, dropping old display work. Sources 1920×1080 and 768×576 keep their original aspect and bbox coordinate system. This restores geometry from the same processed frame; resizing can change individual pixel values. [NVIDIA DeepStream 9.2 demux behavior](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvstreamdemux). CPU encoding uses the documented I420 input and JPEG output path. [GStreamer jpegenc](https://gstreamer.freedesktop.org/documentation/jpeg/jpegenc.html).

The separate HTTP sender retains one latest pending JPEG per source and one request in flight, connects within 100 ms and times out each request after 500 ms. It never waits in the observation publisher or retries old images. Preview-consumer outages, pending metadata and rejected preview requests drop only display images. Headers are `X-City-Source-Id`, `X-City-Session-Id`, `X-City-Sequence`, `X-City-Source-Time-Ns`, `X-City-Width`, `X-City-Height` and `X-City-Model-Revision`; content type is `image/jpeg`. HTTP 201/new or 200/idempotent accept increments `published`; 202 increments `pendingDropped`; other results increment `postFailed`. The gateway owns exact-history matching and generation/session/model rejection. It does not insert a second observation.

`--preview-stats-file` writes atomic `city.preview-native-status.v1` JSON once per second and at shutdown. If omitted, it defaults to `preview-stats.json` beside the analytics acknowledgement, or to `OUTPUT.preview.json` for file output. With only HTTP observations and no explicit stats/ack/output path, no stats file is written. Global fields include `enabled`, `failed`, `error`, `updatedAtNs`, `fpsLimitPerSource`, `jpegQuality`, `maxJpegBytes`, `identityLimitPerSource`, `pendingJpegs` and `batchQueueOverruns`. Per-source counters include `selected`, `rateDropped`, `sourceQueueOverruns`, `identityMissing`, `identityEvicted`, `identitiesPending`, `geometryMismatch`, `encoded`, `oversizeDropped`, `networkQueueDropped`, `published`, `postFailed`, `pendingDropped` and `lastPublishedAtNs`. Queue overruns are overrun signals, not a claim of exact dropped-frame counts. `observedEncodedFps` and `observedPublishedFps` are successive status-sample counter deltas divided by elapsed monotonic time; they are initially null. Publish UTC is delivery health, never capture-time identity.

`make test` covers duplicate-time and epoch identity separation, out-of-order JPEG completion, bounded map eviction, 100,000-frame consumption/replacement controls, rate sampling, header safety and CLI bounds. `make preview-jpeg-test` runs four synthetic CPU I420 frames through the installed `jpegenc` and proves their token PTS, original geometry and JPEG boundaries survive. It loads only CPU app/core/jpeg plugins and neither opens RTSP nor initializes CUDA.

`--frames N` also checks the budget before each observation is serialized, including the last multi-source batch and any callback racing the asynchronous main-loop quit. It leaves `--frames 0`/continuous mode unlimited and preserves the publisher's existing queue drain. `make frame-limit-test` exercises the actual production observation callback with CPU-only synthetic `NvDsBatchMeta`: limits1 and3 across two-frame batches, unlimited mode and explicit stopping. It creates no video source, GPU surface or inference context.

The worker and CPU path compile/pass checks in a 2 GiB/2 CPU runc container. **GPU conversion/demux correlation, dynamic caps negotiation, source-clock/fps impact, preview HTTP outages and browser rendering are not yet runtime-qualified by those CPU checks.** Activation needs a bounded two-source run, exact identity and JPEG-dimension checks, sustained source-clock/metadata throughput, a consumer-unavailable control and a visual box check. A pipeline codec/conversion error is distinct from a network-consumer outage and must be included in fault testing before claiming full optional-branch fault isolation.

A timestamp-basis change starts a new source session and resets its observation sequence, even if raw PTS increases. This covers the first RTCP sender report arriving after a local-clock approximation and later loss of source timing. Raw PTS rewind or computed source-time rewind also starts a new session. `sourceEpochReason` explains the reset on its first frame. NvDCF local IDs may remain the same internally, but their new source session prevents carrying dwell, speed or crossing history across incompatible clocks. CPU epoch controls cover forward/backward basis transitions and source-time rewind with monotonic raw PTS.

The base `tracker.yml` explicitly selects VPI NvDCF (`visualTrackerType: 2`) with the **CUDA** VPI backend (`vpiBackend4DcfTracker: 1`); PVA is never selected. ReID is disabled for the baseline. Tracker tuning is provisional until evaluated on city occlusion sequences.

## Editable native analytics

The backend owns the canonical rule set and durable event lifecycle. `nvdsanalytics` provides object-level ROI, line crossing and direction evidence in `nativeAnalytics`; it must not independently publish duplicate incidents. ROI class filters are section-wide in native config, so the backend must label all-class native counts honestly and apply each rule's own class filter for authoritative counts.

The backend atomically writes a controlled shared `analytics.ini` with:

```ini
# city-rules-revision=rules-12
[property]
enable=1
config-width=10000
config-height=10000
osd-mode=0
```

It may append validated `roi-filtering-stream-N`, `line-crossing-stream-N` and `direction-detection-stream-N` sections. Source index N is the order of worker `--source` arguments, never a name guess. Normalized geometry can be scaled independently by X/Y into the 10000 × 10000 configured coordinate system. Directed lines contain the direction-vector endpoints followed by crossing-line endpoints, per NVIDIA's native format.

The worker checks file modifications every 250 ms and supports `SIGHUP` as an explicit reload. It reads bytes and device/inode/mtime/ctime/size from one open descriptor, rejecting an in-place mixed write. A replacement that arrives during that read remains a distinct unseen generation. It validates the INI envelope and freezes its bytes into an immutable temporary snapshot. One persistent blocking buffer probe applies the newest pending configuration at the next buffer boundary, then passes that buffer. Rapid edits replace the pending snapshot rather than adding probes; at most the current and pending snapshots are retained. The old current file is retired after the plugin consumes its replacement.

The worker writes `analytics-ack.json` atomically and acknowledges `active` only after a successful post-analytics frame. The acknowledgement contains revision, counter epoch, source time, status and error. A plugin parse failure terminates inference visibly and writes an error acknowledgement. Backend/UI native-analytics activation must remain pending until the active acknowledgement is observed; writing a file is not an activation receipt. A reload creates a fresh native counter epoch, so never add a new cumulative counter to old counts as if continuous.

## Bounded live observation files

Managed continuous inference uses `/state/live-observations.ndjson` with `--output-max-bytes 268435456 --output-retained-files 2`. Each complete NDJSON record fits in one file; rotation happens before a record would exceed 256 MiB. The named current plus two previous files contain at most 768 MiB of NDJSON, excluding small manifest/lock files and any retired inode still held open by a reader. The stable family survives ordinary worker restarts. Finite qualification runs keep their timestamped files and default to rotation disabled (`--output-max-bytes 0`); original media and historical evidence are untouched.

The writer holds a stable exclusive `.lock` and commits an atomic, fsynced `city.observations.rotation.v1` manifest before writing the first record of a new generation. The manifest identifies filenames, monotonic generations and device/inode pairs. Native retention accepts zero through eight previous files; the managed monitor supports one through eight and is configured for two. A record larger than the cap fails visibly.

Startup accepts a new empty family without a manifest and creates its first manifest. It refuses a nonempty output without a trusted manifest, partial final records, invalid manifests, unexpected family members, config mismatches and interrupted rotations. It never silently truncates or reconstructs evidence. For recovery, pause the owned sources through the canonical Agent controls, preserve the complete failed log family and receipt in a separate diagnostic directory, then explicitly prepare a fresh family and resume. Do not move a family while its writer or qualification monitor is active, remove its lock under a live writer, or edit a receipt to turn a failure into a pass. See [monitor behavior](../../../../tools/smart-city/SOAK.md) and [CPU source review](../../../../docs/qa/smart-city-2026-10-22/polish-code-review.md).

## Overlapping cameras and MV3DT

MV3DT is worth testing when the final two cameras overlap. The current DeepStream 9.2 reference requires synchronized, same-resolution inputs and calibrated 3 × 4 projection matrices. It adds geometric object models, peer-camera communication over MQTT and multi-view association. Merely viewing overlapping videos does not establish those inputs.

The reference supports people and warehouse detectors. Current SV3DT supports **per-class `modelInfo` arrays**, cylinder/cuboid object models, and optional human pose estimation with a class filter. It is not limited to people. Its documented cuboid has a square ground footprint, so fitting long buses, variable vehicle sizes and riders still needs evaluation. RF-DETR custom-detector integration is supported in principle; class-specific geometry, synchronization and fused-ID export remain separate validation tasks. Human pose inference must be disabled for vehicles or explicitly restricted to the person class.

The selected Spark application runs **one native MV3DT stage**, with calibrated same-resolution overlapping Isaac cameras, native encoded-frame capture evidence, MQTT peer communication, native uint64 SDK IDs and native world-foot metadata. DCF is the supported internal visual tracker. The separate NvDCF stage is historical. The six classes are enabled, but reliable vehicle association and long-vehicle geometry remain unqualified; do not equate positive detections with correct shared IDs. See the [October 28 investigation](../../../../docs/smart-city-mv3dt-quality-2026-10-28.md) for controlled comparisons, the map identity repair and remaining failures.

The official 9.2 README also documents a Thor 12-camera libmosquitto file-descriptor issue; two-camera qualification remains a separate test. It documents a Blackwell RT-DETR strongly typed engine requirement. That warning is a reason to verify positive detections after every engine build, not proof that arbitrary RF-DETR graphs should have a builder flag applied without checking their tensor types.

Primary references:

- [DeepStream 9.2 preprocess API](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvdspreprocess)
- [RF-DETR ONNX output and preprocessing contract](https://rfdetr.roboflow.com/latest/exports/onnx/)
- [DeepStream tracker](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvtracker)
- [Native analytics](https://docs.nvidia.com/deepstream/text/DS_plugin_gst-nvdsanalytics)
- [Official MV3DT reference and customization requirements](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/reference_apps/deepstream-tracker-3d-multi-view/README.md)

Qualification receipts belong in the project progress log. CPU parser controls alone do not qualify CUDA preprocessing, TensorRT output correctness, decoder support, two-camera timing, final-city map accuracy or Thor deployment.

## Optional MV3DT package preparation

`prepare_mv3dt.py` prepares an **experimental, disabled** package for the official tracker. It stops if full camera calibration, measured common-clock timing, same-resolution images, visible overlap, held-out 3D landmarks or class geometry are missing. It never upgrades a ground homography into a guessed 3D camera matrix. It writes camera files using the explicit `projectionMatrix_3x4_w2p` convention, per-class `modelInfo`, peer MQTT configuration and an optional tracker configuration. The tracker stays on CUDA and pose inference is disabled. The generator uses only the documented cylinder template and requires all six class geometries; selecting approximate vehicle geometry requires explicit acknowledgement and provenance. A people-first MV3DT experiment still needs a reviewed class-scoped runtime profile. The worker’s selected native mode extracts SDK target IDs and 3D user metadata; this older preparation utility alone does not enable that runtime. See the [decision and promotion gates](../../../../docs/smart-city-mv3dt-decision.md).

```sh
python3 services/rtvi/rt-cv/smart-city/prepare_mv3dt.py \
  city-mv3dt-package.json paired-source-timestamps.json prepared-mv3dt \
  --container-root /opt/city/mv3dt --mqtt-host vss-city-mqtt
python3 -m unittest discover -s services/rtvi/rt-cv/smart-city/tests -p 'test_mv3dt.py'
```

Input package fields are `schemaVersion: "city.mv3dt.preflight.v1"`, `siteId`, `units: "metres"`, `axes: "right-handed-x-y-ground-z-up"`, `overlapPolygonM`, `classGeometry` and `cameras`. Every camera needs `sourceId`, `width`, `height`, `lensModel: "pinhole-rectified"`, `calibrationRevision`, and either a 3 × 4 `projectionMatrix3x4` or `K` plus `T_cv_from_site`. It needs at least six independently checked `landmarks` containing `worldM` and `imagePx`; they must span 3D to test vertical projection. Geometry entries contain `class`, `shape: "cylinder"`, measured `heightM`, `radiusM`, `provenance`, and `approximationAcknowledged: true` for non-person classes. All six detector classes must be covered explicitly.

Timing evidence contains `kind: "source-clock-measurement"`, `clockBasis: "source-rtcp"` or `"recorded-common-clock"`, and at least 100 `pairs`. Each pair maps every source ID to its integer nanosecond timestamp as a string. Samples must increase, with default maximum skew 50 ms. This checks supplied source timestamps; timestamp acquisition itself must also be validated against the actual camera/media gateway. Initial preparation limits are maximum 3-pixel held-out reprojection error and 50-ms measured skew; they are test gates to tighten for the final scene, not achieved runtime claims.

Tests explicitly label synthetic evidence `test-fixture`. The command rejects it unless `--allow-test-fixtures` is passed, and output still records `fixtureOnly: true`, `enabled: false`, `runtimeQualified: false`. Real metadata also leaves the generated package disabled and unqualified until paired inference and fused-ID adapter checks pass. This utility does not start a broker, replace the running tracker, or turn on UI global-identity badges.

## Validation performed on Spark

The implementation log and `.spark/city/runtime/` receipts contain the authoritative hashes and commands. Initial checks passed against DS 9.2 and the actual exported RF-DETR FP16 engine:

- Native C++ worker/parser/CUDA preprocessor build; CPU sparse-COCO/global-top-k controls.
- Production CUDA resize/normalization kernel versus its CPU numerical reference: maximum error zero in the bounded unequal-aspect/pitched-buffer case.
- One H.264 traffic stream: 30 frames, nonempty bus/car/person/truck observations after tracker probation.
- Two differently sized streams: 60 frames, original 1920 × 1080 and 768 × 576 coordinate bounds verified, 4.90 seconds wall time including startup with pacing enabled. These are different scenes at different frame rates; they do not qualify shared-view synchronization, cross-camera identity or final throughput.
- Native full-image ROI changes: 180 frames, three active revision acknowledgements with separate counter epochs. An invalid-width revision was rejected and never applied; the last valid stream continued. Configured directed-line inference still needs an event accuracy dataset.
- Synthetic black-video negative control: 15 frames, zero tracked detections.
- Twelve MV3DT preparation tests, including missing 3D calibration, source skew, repeated timestamps, invisible overlap, missing vehicle geometry and fixture promotion rejection.

None of these bounded checks proves the final scene, live RTSP timing, long-duration stability, semantic accuracy, multi-view tracking, or Thor qualification.

The explicit GPU/HTTP backpressure regression uses a deliberately slow local consumer and never changes VSS site state:

```sh
python3 /opt/city/tests/native_backpressure.py --state-dir /state
```

With a four-frame queue, the tested 30-frame unpaced run delivered all 30 observations in order, blocked the producer when required, handled an idempotent duplicate receipt and ended successfully. It also rechecks positive real-video detections and post-snapshot native analytics application. The receipt is `native-backpressure-receipt.json`.

File timeline controls run without allocating the GPU:

```sh
make -C /opt/city test-time
```

They cover both measured edit-list offsets, nonzero seek timeline offsets and invalid PTS/segment formats. File observations require the matching source segment mapping before they may be published. Browser-frame comparison remains a separate integrated check.

The explicit `python3 /opt/city/tests/native_pacing.py` GPU regression measures request-body receipt times at a fast local HTTP consumer. With a 30 FPS 1080p traffic file and a 10 FPS 768 × 576 pedestrian file, the fixed pipeline delivered 480/480 observations, peak queue two, no producer waits and exit zero. After the first two seconds of media, traffic delivery was 30.03 FPS (media/wall ratio 1.0011) and pedestrian delivery 9.99 FPS (ratio 0.9986). Relative drift over roughly ten seconds was −10.5 ms and +15.0 ms respectively. Total wall time including native startup was 16.36 seconds. `native-pacing-receipt.json` and `native-pacing-receive.ndjson` retain the measurements. This short local-consumer result does not establish browser display latency, HTTP performance across a network, live-camera synchronization, or long-run load capacity.

### In-place prepared-scene tracker reset

The worker watches `scenario-boundary.ini` beside its existing analytics INI;
there are no additional startup flags. The gateway writes an opaque UUID and
capture fence, never actor positions. At inference output, before either
tracker, the worker sends serialized NVIDIA `GST_NVEVENT_STREAM_RESET` events
for every source. Both trackers use `tracking-id-reset-mode=1`; installed DS9.2
`gstnvtracker.cpp` drains pending tracker work and calls
`removeSource(source_id, false)` for this event. Output-pad event probes verify
that each tracker received every source reset. The unchanged analytics INI is
reloaded to begin a new native primitive counter epoch.

A successful `scenario-boundary-ack.json` names the reset UUID, stages and
source IDs. New observations carry `trackingEpoch`; the experimental fusion
UUID also changes. Source sessions, sequences, H264/RTSP flow, native SEI proof,
PTS and capture time remain continuous. The downstream-only events never reach
the decoder, mux or native capture cache. A missing tracker acknowledgement
fails the worker and leaves the gateway's operational gate closed.

An explicit reset opens a maximum 20-second backlog drain. Exact records that
were fresh when parsed but aged in a blocked decoder/mux/inference queue are
discarded as whole batches before tracking, consuming each proof once. Missing,
duplicate, unqualified or future evidence still fails closed. Admission keeps
the existing two-second capture-age bound, checked again after the synchronous
tracker reset. The drain closes only after each source emits at least three
fresh post-tracker observations spanning one capture-clock second, so a first
carrier cannot end it before lazy tracker/MQTT initialization completes;
outside it, stale evidence retains the normal fatal policy. Reset drain counts
are logged, and failures preserve their first qualification reason.

`make scenario-boundary-test native-capture-clock-test staged-tracking-test`
checks actual CPU Gst event/probe propagation, refusal when the second stage
misses an event, bounded/idempotent request parsing, unchanged source identity,
clock guard regressions and staged metadata. These tests do not execute GPU
trackers; each deployment needs a bounded actual reset/continuity check.

### Shared analyzed WebRTC preview (Spark candidate)

The explicit `previewTransport: "webrtc"` setting in the local runtime tuning
selects one NVENC H.264 encoder per camera. It keeps NV12 surfaces on the GPU,
publishes to the pinned CPU MediaMTX relay, and posts compact identities to
`/api/v1/city/video/frame`. Viewers reuse those encoded streams through a
same-origin WHEP broker; opening another viewer does not create another native
encode or inference pipeline. `previewFps` is a ceiling, not a promised frame rate.

An RTP payloader probe records the actual timestamp of each completed access
unit and looks up its exact immutable source/session/sequence/time/model/image
identity by encoder PTS. The backend joins that identity only to an accepted
native observation. The browser uses `requestVideoFrameCallback().rtpTimestamp`
to choose that frame's metadata. Missing, expired or obsolete identities clear
the overlay; there is no nearest-time association or guessed RTP offset. This
proves frame correspondence, not physical exposure-to-screen latency.

The local TCP RECORD sink must have its internal appsinks' `sync` and `async`
properties disabled through `deep-element-added`: this live source is already
paced. Leaving their default synchronization enabled retained several frames,
starved the demux branch and made the initial candidate substantially worse.
The fixed branch measured a steady 1–7 ms in an isolated encoder/publisher test
and a <=5 ms measured p95 after selection in the short live trial. Startup RTSP
negotiation is included in lifetime maxima and can still take about a second.
Do not shorten the TCP control read timeout below the RTCP interval.

Health and both cameras' metadata share one SSE connection per browser tab.
Static calibration and rule geometry are sent as a manifest; dynamic frame
records reuse it. The native sender queues up to 16 small metadata records per
source in order, independently of the latest-only JPEG queue. Dropping a JPEG
can drop its matching image/metadata together; dropping video metadata alone
leaves an otherwise valid playing frame without labels. The shared 4 Hz status
snapshot is serialized once across viewers, with immediate configuration
invalidation, so those summaries do not starve frame metadata admission. The server retains 16 metadata frames per source with a
two-second expiry; client RTP caches are bounded to 64. Slow viewer output is
bounded and disconnected, rather than growing an unbounded queue. WHEP leases
expire after 90 seconds, with explicit release on unmount and source retirement.
The broker permits at most 16 simultaneous camera peers.

Native browser video playback and a display-resolution canvas draw the overlay
in one batch per presented frame. The canvas keeps the existing label placement,
quiet dark label background and thin boxes; map/summary React updates are
separately limited and scheduled as transitions. The browser's jitter preference
is 200 ms where supported; actual buffering is measured independently. Hardware
browser decoding is not assumed when the browser does not report its decoder.

The RTP marker now waits for the metadata sender's gateway-admission receipt
before completing video publication. This wait ends on HTTP 200/201, rejection
or a 200 ms deadline; it is not a fixed video delay. It runs only on the isolated
preview branch behind its leaky queue, independently of tracking. Health reports
`metadataReadyBeforeVideo`, `metadataUnconfirmedBeforeVideo` and
`metadataAdmissionWait`. Admission does not prove browser receipt: exact RTP
matching remains mandatory.

The shared SSE route gives frame records priority while status serialization
runs in a bounded background task. HAProxy routes just `/api/vision/city/stream`
and the legacy per-camera metadata route through `bk_city_events` with
`option http-no-delay`. Without that scoped setting, the ingress added a measured
median 95 ms and maximum 220 ms to otherwise prompt metadata, producing brief
blank overlays despite zero lost records. The corrected ingress added a measured
median 2 ms and p95 15 ms on the same path. A graceful proxy reload preserves old
connections; refresh an already open page once to acquire the new route.
After this correction, the two-camera browser displayed 1,726/1,726 frames with
metadata already available, zero late repairs and zero decode drops over about
143 seconds. The preceding 25-second reproduction had 11 and 12 late frames per
camera. This is a bounded local display check, independently of tracking accuracy.

The October 28 bounded two-camera browser trial retained every metadata record:
all 1,431 presented frames acquired their exact matching detections. Three
records arrived after presentation and were repaired within 31 ms in that
window. Native metadata queue drops and failed posts were zero. That first trial
did not eliminate the later-discovered ingress delay described above. This short
trial exercises display continuity; it does not qualify MV3DT identity accuracy,
physical capture-to-screen latency or a sustained ingestion workload.

The previous JPEG path remains selectable with `previewTransport: "jpeg"` and
`previewFps: 8`. Detection controls still start, stop and reconnect the native
worker. An outage does not automatically open a second, video-only VSS decoder;
that fallback is an explicit UI action. See the local deployment receipt for
the selected image and the bounded live checks that were performed.
