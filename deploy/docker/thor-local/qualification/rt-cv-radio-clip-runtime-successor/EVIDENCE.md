# Evidence

The isolated Thor run passed in 99.334343 seconds with Docker using the required
`cgroupfs` driver and 16,336,470,016 bytes free afterward. It used the exact
cached VSS 3.2.1 arm64 RT-CV, consumer, and MediaMTX images and the signed NGC
`nvidia/tao/radio-clip:deployable_v1.0` artifact set. The ONNX, 5.49 GB external
weights, five-file tokenizer, NGC export spec, and 1,336,318,724-byte Thor
TensorRT plan are byte- and SHA-256-locked.

The real RTSP/Kafka/API run produced 156 detection messages. It attached finite
1,536-dimensional RADIO-CLIP vectors to both `Pallet` and `Person` detections
across 17 distinct object/track pairs. The two-cycle proof retained 70 person
embeddings in each cycle, observed 62 detection-silent occlusion frames, and
matched 70 known-scene bounding boxes. For the selected cross-cycle identity,
45 comparisons produced cosine similarity from 0.9999958799323881 to
0.9999989304855814 with median 0.9999986928972935. RADIO-CLIP appearance
embeddings re-associated the object even though the tracker assigned a new ID.

The effective runtime configuration selected the documented `siglip2-onnx`
combined-ONNX text path, RADIO-CLIP v1.0 ONNX/tokenizer, TensorRT vision plan,
smart inference, and OFA prediction. Legacy 256-dimensional tracker embeddings
were disabled. A corrupted tokenizer was rejected before launch. After runtime
established the exact 1,536-dimensional output, a competing 1,024-dimension
configuration was rejected before capability acceptance.

Real add, active-metrics, and remove calls passed with positive frame/FPS
counters and finite latency. The isolated workload had no OOM event or restart.
Cleanup removed all owned containers, Kafka state, configuration, and fixtures.
The healthy main `vss-rtvi-cv` remained exactly unchanged with zero streams,
and the intentionally paused workloads remained stopped. The qualification
performed no download, VSS Agent call, main RT-CV stream mutation, VIOS
mutation, or Warehouse sample access and retained no sensitive runtime payloads.

Artifact locks:

- contract: `0e1d3242689ca7ef32bd43fdea817cda5f0fc6119e780a1ab7c5c713ef12d804`
- receipt schema: `21a2536395a4f8377bbb8dfacec1e19b46de3326c8d522fc641bd5ab04247672`
- runtime receipt: `e700dd0bacb0d89f38829a610b93ce24ea65af3ec168bc84f9684e38101c80cb`
- executor: `a8d80557fed8d3f47d259565a9fb2885c7a8682745abf94da43f81a17b6ad254`
