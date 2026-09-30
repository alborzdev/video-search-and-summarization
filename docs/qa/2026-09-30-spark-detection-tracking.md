# Spark detection/tracking activation — September 30, 2026

The user requested detection and tracking on the live hospital Sim feed. The
previous Spark graph omitted both detector workers. A source toggle could not
start a worker absent from that graph. This stage adds one matching SBSA worker,
then configures and explicitly resumes the existing camera.

## Runtime and configuration

- Source: Spark Hospital Corridor, sensor/stream
  `3688c328-7e71-493c-a1c7-011ad2fb3893`,
  `rtsp://10.88.9.91:8554/digital-twin`.
- Spark-only service `spark-perception`, container `vss-rtvi-cv`, NVIDIA runtime,
  host networking, API bound to `127.0.0.1:9000`, Docker restart `no`.
- Image `nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1-sbsa`, digest
  `sha256:352a0dbaf7b8d4c14a0594be23ca675496de81562ea531573b6bb242bf1c65bf`.
  Official image pull is about 18.26 GB compressed. No image was rebuilt.
- RT-DETR Warehouse FP16 ONNX, batch one; CUDA NvDCF with GPU image conversion,
  50 targets maximum per stream, ReID disabled. No PVA or VIC settings are used.
  RTSP uses TCP for the existing MediaMTX publisher. Models and generated engine
  reside in ignored `.spark/data/models/spark-detector`.
- Worker ceiling: 6 GiB memory including swap, 2 GiB shared memory, four CPUs.
  First engine compilation completes in about 36 seconds. TensorRT's image
  retries without an explicit FP16 builder flag for the strongly typed FP16
  ONNX; the generated engine is 99,934,476 bytes and is reused on restart.
- Bootstrap persists `detector_enabled`; `--detector` enables the worker,
  `--no-detector` omits it, and omission preserves the saved mode. Default remains
  off on a new checkout. Startup orders this worker after the three model
  services and before the agent, with reserve + 6 GiB available required.
- The enabled agent has the warehouse endpoint and `VSS_WAREHOUSE_MAX_SOURCES=1`.
  Capacity reporting and source admission share that value. Existing Thor
  defaults remain eight. Invalid capacity values fail clearly.
- Only the new worker and the agent were started/recreated. Source-mounted UI,
  Sim, loaded AI models, existing model budgets and the 24 GiB guard are preserved.

Configuration generation validates NVIDIA's published model SHA256 before any
write, copies templates into private model storage and preserves the compiled
engine. Shared warehouse and Thor templates are unchanged. Model SHA256:
`0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267`.

## Observed output

Camera configuration and explicit resume return success. Agent status verifies
`analysisActive=true`, `detectionEnabled=true`, profile `warehouse-safety`, and
active detection, embedding and indexing. The worker lists exactly this camera.

The first advancing frame metrics appear at 18:48:19 UTC. Subsequent five-second
measurements stay around 29 fps through the recorded check at 18:59:44 UTC.
At 18:59:27 UTC, camera-scoped evidence shows:

| Check | Result |
| --- | --- |
| Raw metadata | 8,254 new observations; latest timestamp 18:59:25 UTC |
| Downstream behavior tracks | 89 documents for this sensor name |
| Person track continuity | ID 0 appears in 126 records across 4.3 seconds with valid boxes |
| Semantic index | 241 → 374 segments, searchable through 18:59:18.730 UTC |
| Index delay | Eight seconds, semantic freshness true |
| Live recording | On, preserved from the previous rehearsal |
| Live visual question | Completes while detection/indexing continue |
| Inspected replay | 25.001 seconds, 1280×720, readyState 4, no media error |

Raw CV metadata uses the camera name in `sensorId`, and behavior metadata uses
`sensor.id`. The exact worker registration remains the UUID above. Queries and
receipts include this identity mapping; aggregate document counts are not
treated as people counts. Tracker predictions can carry confidence -0.1 between
detector measurements, which is not a calibrated detection probability.

The question returned “A person is walking on the left side of the frame.” Its
inspected interval is 18:50:33–18:50:58 UTC. Playback works, but this response is
not scored as an accurate avatar observation. The warehouse model also emits
Forklift labels in the hospital scene, and the replay contains Person boxes on
scene equipment. Negative-window precision and person ID continuity against a
known avatar remain open. Do not present the observed document count as occupancy,
the model's industrial vocabulary as medical-object coverage, or these records
as verified incidents. No live alert rule was activated. Continuous captioning
is not configured; visual questions remain available.

## Memory and verification

The Spark guard remains active at the user-authorized 24 GiB reserve. The
separate half-second observation trace lasts 2070.237 seconds, including image
staging, engine build, activation and the question/replay check. Minimum available
memory is 29.422 GiB; boot ID is unchanged and no new guard trip is recorded.
During active ingestion, 18:48:19–18:59:48 UTC, available memory stays between
33.090 and 33.634 GiB. The first build lowers memory from about 34.98 to 29.42
GiB, supporting the new six-GiB startup admission allowance. This is a bounded
single-source result, not sustained tradeshow-duration qualification.

Twelve Spark bootstrap/configuration tests pass. They cover actual Compose
render/save/disable isolation, bounded worker configuration, startup order and
30-GiB admission boundary, checksum refusal, CUDA selection, batch-one consistency,
template preservation and engine reuse. Twenty-seven focused profile/admission
agent tests pass, with scoped Ruff, formatting and Mypy. Python compilation,
shell syntax and diff checks pass. Real NAT config loading verifies empty/unset
core endpoints and the enabled warehouse URL. Health probes pass for all existing
model/video/agent services plus the detector. The full agent unit-suite attempt
stops at collection because `langchain_core` is missing from the available QA
environment; it is not reported as passing.

Private receipts are in `.spark/detection-stage/`: memory trace/result,
image/model metadata, configure/resume responses, active output, type counts,
track continuity and full-suite collection log. UI proof is saved outside Git at
`/home/spark/.codex/visualizations/2026/09/30/live-cameras/detection-tracking-active.png`.

## Restore this setup

On this target the image, model and engine are staged. The saved detector mode is
enabled. After an explicitly requested staged restart, the existing cold-start
gate still leaves live source analysis paused; choose **Resume analysis** on the
hospital camera with **Warehouse** selected. Keep recording on for questions.
Opening a workspace does not start either control.

To reproduce on a new Spark checkout, stage the official image and checksum-verified
model first. Download the 87,890,438-byte FP16 ONNX from NVIDIA's public
[model endpoint](https://api.ngc.nvidia.com/v2/models/nvidia/tao/rtdetr_2d_warehouse/versions/deployable_rn50_v1.0.2/files/rtdetr_warehouse_v1.0.2.fp16.onnx)
to `DATA/models/spark-detector/rtdetr_warehouse_v1.0.2.fp16.onnx` with the published
hash above. Make that directory writable by image UID/GID 1000. Render with the
existing host/data/gateway/registry/reserve/cache settings plus `--detector`;
do not replace an active source UI by invoking whole-stack `up` during development.
For an already-running core stack, admit startup against reserve + 6 GiB and the
active guard, then target only `spark-perception` and `vss-agent` with Compose
`up -d --no-deps --no-build --pull never`. Worker health alone is insufficient:
repeat the frame, metadata, fresh index and visual/replay checks above.
