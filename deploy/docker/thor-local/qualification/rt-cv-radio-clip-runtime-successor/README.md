# RT-CV RADIO-CLIP runtime qualification

This package retains the Thor runtime proof for official VSS 3.2.1 row 377,
`manifest-entry.rt-cv-2d.02-radio-clip`.

The executor launches an isolated copy of the exact cached VSS 3.2.1 RT-CV
arm64 image with the signed NGC `nvidia/tao/radio-clip:deployable_v1.0`
ONNX, external weights, tokenizer, and a Thor-built TensorRT plan. It publishes
a deterministic 14-second H.264 RTSP fixture, consumes real protobuf output,
and requires finite expected-dimension embeddings attached to detected object
and track identifiers. The replay contains a visible scene, a 60-frame black
occlusion, and the same scene again, permitting same-object cross-cycle
correlation as additional evidence.

## Local model preparation

The signed NGC package is 5,534,521,620 bytes. Inspect it before downloading:

```bash
ngc registry model info \
  nvidia/tao/radio-clip:deployable_v1.0 \
  --files \
  --format_type json
```

The standard Search profile accepts:

```bash
VISION_ENCODER_MODEL=radio-clip
VISION_ENCODER_VERSION=v1.0
ELASTICSEARCH_RTVI_CV_EMBEDDINGS_DIM=1536
```

Normal profile startup downloads the NGC package into `$VSS_DATA_DIR/models`
and builds the host-specific
`radio-clip_v1.0.onnx_batch16.plan` when it is absent. Preserve at least 10 GiB
free after the 5.49 GB weights and approximately 1.34 GB Thor plan are stored.
Switching between SigLIP2 (1,152 dimensions) and RADIO-CLIP (1,536 dimensions)
requires a matching Elasticsearch vector dimension and re-indexing existing
object vectors.

## Run

Plan mode verifies every locked local artifact and is read-only:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-radio-clip-runtime-successor/executor.py plan
```

Runtime mode requires the exact acknowledgement and writes a receipt only
after schema validation and exact cleanup:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-radio-clip-runtime-successor/executor.py \
  execute \
  --ack I_ACK_ISOLATED_RADIO_CLIP_OBJECT_CORRELATION_AND_EXACT_CLEANUP \
  --write-receipt
```

## Dimension and safety boundary

NVIDIA's VSS 3.2 documentation currently presents conflicting RADIO-CLIP
dimensions: the Object Detection and Tracking model table says 1,024, while
the Search Workflow deployment contract says 1,536. The exact signed v1.0 NGC
artifact emitted 1,536-dimensional protobuf vectors on this Thor. This package
therefore treats 1,536 as authoritative for this exact artifact and explicitly
rejects a 1,024-dimension admission.

The executor creates only namespaced containers, Kafka resources, and temporary
fixtures/configuration. It performs no network download, VSS Agent call, main
RT-CV stream mutation, VIOS mutation, or Warehouse sample access. Raw vectors,
broker messages, camera IDs, stream URLs, and credentials are not retained.
