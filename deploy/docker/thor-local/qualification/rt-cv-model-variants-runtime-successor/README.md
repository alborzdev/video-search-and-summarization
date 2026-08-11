# RT-CV detector-model variants runtime qualification

This package retains the Thor runtime proof for official VSS 3.2.1 row 376,
`manifest-entry.rt-cv-2d.01-warehouse-and-smart-city-rt-detr-gdino`.

The proof keeps the three advertised detector identities separate:

- Warehouse RT-DETR is inherited only from the strict, source-locked
  `rt-cv-2d-core-runtime-successor` receipt.
- Smart City RT-DETR runs its own TrafficCamNet model and five-class label map
  through `nvinfer`.
- Smart City Grounding DINO runs its own open-vocabulary model through Triton
  with the exact `person` prompt and threshold.

Both Smart City lanes launch the exact cached VSS 3.2.1 arm64 RT-CV image on
the isolated REST port 19004 and ingest the exact checked-in H.264 fixture from
an owned loopback MediaMTX publisher paced in real time. A separate generated
60-second copy proves deterministic bounded fixture construction. The lanes
publish protobuf detections to an owned Kafka topic and prove real detection
and NvDCF tracking. The oracle requires eight frames, at least one object,
Person class correlation, repeated track IDs, finite boxes/confidences, and
one exact non-empty sensor identity.

REST-added sources in the NVIDIA perception application select UDP after
startup, so the isolated MediaMTX instance uses host networking with dedicated,
loopback-only, collision-free RTSP, RTP, and RTCP ports. The executor disables
its unrelated protocols and verifies the effective listeners before adding
either stream. This keeps the dynamic REST path real while avoiding bridge-NAT
source-port rewriting.

The alerts developer profile now disables synthetic-data SEI timestamp
extraction and backward-SEI dropping, matching the current checked-in Smart
City RT-DETR and GDINO reference configs. Those gates are only appropriate for
simulation streams carrying the custom SEI payload; leaving them enabled drops
ordinary customer H.264 input before inference.

## Run

Plan mode is read-only:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-model-variants-runtime-successor/executor.py plan
```

Runtime mode requires the exact acknowledgement and writes the receipt only
after strict schema validation and exact cleanup:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-model-variants-runtime-successor/executor.py \
  execute \
  --ack I_ACK_ISOLATED_RT_CV_THREE_MODEL_VARIANT_PROOF_AND_EXACT_CLEANUP \
  --write-receipt
```

## Thor-specific first-build behavior

TensorRT 10 uses a strongly typed fallback for the Smart City RT-DETR FP16
ONNX on Thor. The launcher points the engine filename beside the writable
ONNX cache so the generated engine persists. If the engine does not yet exist,
the executor uses one isolated instance only to trigger that build, removes the
instance after the cache is durable, and launches a fresh inference instance
before starting the evidence consumer and source. Every API operation and both
runtime phases are hashed in the receipt, while no raw sensor identity or URL
is retained.

Tracker ReID is explicitly disabled when `DS_TRACKER_REID=false`; this avoids
building an unrelated ReID engine while preserving NvDCF object tracking.

## Safety and claim boundary

The executor never downloads the 100 GB Warehouse sample bundle. It uses only
the small checked-in fixture, cached detector models, an owned loopback RTSP
publisher, and isolated qualifier containers/topic. It makes no VSS Agent call
and never mutates the main RT-CV
or VIOS stream sets. Raw broker messages, camera IDs, stream URLs, and
credentials are not retained. Successfully generated TensorRT engines are
kept for reproducible local reuse while a 10 GiB free-space floor is enforced.
Completed engine caches remain reusable even if a later evidence assertion
fails; only missing, symlinked, or sub-50 MB partial build artifacts are
removed during failure cleanup.
