# Evidence

The isolated Thor run passed in 99.12791 seconds with Docker using the required
`cgroupfs` driver and 16,330,854,400 bytes free afterward. It used the exact
cached VSS 3.2.1 arm64 RT-CV, consumer, and MediaMTX images and the signed NGC
`nvidia/tao/radio-clip:deployable_v1.0` artifact set. The ONNX, 5.49 GB external
weights, five-file tokenizer, NGC export spec, and 1,336,318,724-byte Thor
TensorRT plan are byte- and SHA-256-locked.

The real RTSP/Kafka/API run produced 156 detection messages. It attached finite
1,536-dimensional RADIO-CLIP vectors to both `Pallet` and `Person` detections
across 15 distinct object/track pairs. The two-cycle proof retained 70 person
embeddings in each cycle, observed 62 detection-silent occlusion frames, and
matched 70 known-scene bounding boxes. For the selected cross-cycle identity,
45 comparisons produced cosine similarity from 0.9997989146647734 to
0.9999664492625492 with median 0.9998744330310916. RADIO-CLIP appearance
embeddings re-associated the object even though the tracker assigned a new ID.

The same live run proves official rows 69 and 70: the effective runtime
configuration selected the documented `siglip2-onnx`
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

- contract: `6271f0913cab6ce73c4c41fa0b92dc19a3b79d58874e0354a4cff6cb5251c28e`
- receipt schema: `f535c2ad287acb64b648d54c3898d195a6565662d568794a0295bf4d6a06a330`
- runtime receipt: `228a8d041398ae5f9bfbc65437c0250bede3f722493e2bc6b47c0f30c6613297`
- executor: `389f4ba406b58e5ef3632abf6e19cd8e9265a79fa420c8c7d25e63a604f936d8`
