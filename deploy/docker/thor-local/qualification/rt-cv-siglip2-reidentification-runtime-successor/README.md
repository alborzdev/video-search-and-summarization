# RT-CV SigLIP2 re-identification runtime qualification

This package retains the Thor runtime proof for official VSS 3.2.1 row 378,
`manifest-entry.rt-cv-2d.03-siglip2-re-identification`.

The executor launches an isolated copy of the exact cached VSS 3.2.1 RT-CV
arm64 image with the exact SigLIP2 v1.1 ONNX, external weights, tokenizer, and
TensorRT plan. It publishes a deterministic 14-second H.264 RTSP fixture made
from one visible scene, 60 black occlusion frames, and the same visible scene
again. A protobuf consumer then proves that RT-CV emits finite 1,152-dimensional
appearance embeddings and that cosine matching associates the same visible
object across the occlusion even when the tracker assigns a different ID.

The proof also requires real add/metrics/remove lifecycle calls, positive FPS
and latency metrics, exact artifact and image identities, rejection of a
mismatched tokenizer before container launch, and exact cleanup without
changing the main RT-CV or paused workloads.

## Run

Plan mode verifies the locked local inputs and is read-only:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-siglip2-reidentification-runtime-successor/executor.py plan
```

Runtime mode requires the exact acknowledgement and writes a receipt only
after the strict schema and all cleanup assertions pass:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-siglip2-reidentification-runtime-successor/executor.py \
  execute \
  --ack I_ACK_ISOLATED_SIGLIP2_REENTRY_EMBEDDING_PROOF_AND_EXACT_CLEANUP \
  --write-receipt
```

## Safety and claim boundary

The executor creates three namespaced containers, one namespaced Kafka topic,
one namespaced consumer group, and a temporary fixture/configuration directory.
It performs no network download, VSS Agent call, main RT-CV stream mutation,
VIOS mutation, or Warehouse sample access. Raw embeddings, broker messages,
camera IDs, stream URLs, and credentials are not retained.

This is an appearance-re-identification claim. The observed tracker ID changed
across the synthetic occlusion, while the SigLIP2 embeddings re-associated the
object at cosine similarity above 0.9999. It does not claim that the legacy
DeepStream tracker preserved one ID across the gap.
