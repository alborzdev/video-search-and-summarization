# Evidence

The isolated Thor run passed in 96.961393 seconds with Docker using the
required `cgroupfs` driver. It used the exact cached VSS 3.2.1 arm64 RT-CV,
consumer, and MediaMTX images plus the exact SigLIP2 v1.1 ONNX, external
weights, five-file tokenizer bundle, and TensorRT plan.

The real RTSP/Kafka/API run produced 156 detection messages over both replay
cycles. It retained 70 person embeddings before the occlusion and 71 after
re-entry, observed 62 detection-silent frames, and matched 70 known-scene
bounding boxes. Every embedding was finite and exactly 1,152 dimensions. The
selected identity comparison had 45 occurrences; cross-cycle cosine similarity
ranged from 0.9999663695948764 to 1.0000000000000002 with median 1.0, while
the minimum matched-box IoU was 0.9342690020681759. The tracker assigned a
different ID after the gap, and SigLIP2 appearance embeddings successfully
re-associated those distinct IDs.

The exact effective configuration selected `siglip2-onnx`, TensorRT vision
inference, smart inference and OFA prediction, and the expected model and
tokenizer paths. Legacy 256-dimensional tracker embeddings were disabled. A
corrupted tokenizer copy was rejected before any qualification container
launched, while the locked exact bundle remained valid.

Real add, active-metrics, and remove calls passed. The isolated workload had
positive frame and FPS counters, finite latency, no OOM event, and no restart.
Cleanup removed all owned containers, topic, consumer state, configuration,
and fixtures. The healthy main `vss-rtvi-cv` remained exactly unchanged with
zero streams, and the intentionally paused workloads remained stopped. The run
performed no network download, VSS Agent call, main RT-CV stream mutation,
VIOS mutation, or Warehouse sample access and retained no sensitive runtime
payloads.

Artifact locks:

- contract: `7af6d0b07db3515794f909eacfcd2b8c040961e3edd24ba57e385e77c464242c`
- receipt schema: `df588ebd11e0ea48bb0e967767b24b72910bab692b210174d8467b998e6a8f7a`
- runtime receipt: `bc60861c521b62d72bfdc17362deb9a4751b207df653e0e9b03f06aa4ee2a46a`
- executor: `e71ee0f0f705acab84aa25b05f2c3be4afb5f8b83ec69357b2fe359c7f8aa084`
