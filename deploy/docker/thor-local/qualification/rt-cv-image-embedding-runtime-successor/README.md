# RT-CV on-demand image-embedding runtime qualification

This package retains the Thor runtime proof for official VSS 3.2.1 row 379,
`manifest-entry.rt-cv-2d.04-on-demand-image-embedding`.

The executor launches one isolated copy of the exact cached VSS 3.2.1 RT-CV
arm64 image and mounts the exact cached SigLIP2 ONNX and TensorRT plan. It calls
`POST /api/v1/generate_image_embeddings` three times using two deterministic
256×256 P6 PPM images. The proof requires:

- HTTP 200 and a finite, non-zero 1,152-dimensional vector for every call;
- bit-for-bit repeatability for the same image;
- distinct vectors with cosine similarity below 0.99 for different images;
- successful operation with zero continuously ingested streams;
- a fail-closed HTTP 500 response for a missing image; and
- exact cleanup without changing the main RT-CV or paused workloads.

## Run

Plan mode is read-only:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-image-embedding-runtime-successor/executor.py plan
```

Runtime mode requires the exact acknowledgement and writes a receipt only after
the strict schema and all cleanup assertions pass:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-image-embedding-runtime-successor/executor.py \
  execute \
  --ack I_ACK_ISOLATED_RT_CV_ON_DEMAND_IMAGE_EMBEDDING_AND_EXACT_CLEANUP \
  --write-receipt
```

## Safety and claim boundary

The executor creates only `vss-rtcv-image-embedding-qual` plus a temporary
fixture/configuration directory. It performs no network download, VSS Agent
call, main RT-CV stream mutation, VIOS mutation, or Warehouse sample access.
No raw vector, request ID, or image path is retained.

This proof deliberately records the accepted image format. P6 PPM exercises
the complete request, decode, preprocess, TensorRT inference, and response
path. Separate Thor diagnosis found that the container's NVIDIA JPEG decoder
currently collapses different JPEG inputs to the same vector; this package
does not claim JPEG correctness. That compatibility defect remains explicit
rather than being hidden by the successful PPM result.
