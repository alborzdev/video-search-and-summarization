# Evidence

The isolated Thor run passed in 28.606109 seconds with Docker using the
required `cgroupfs` driver. It used the exact cached VSS 3.2.1 arm64 RT-CV
image and exact cached SigLIP2 ONNX and TensorRT plan. The effective runtime
configuration selected `siglip2-onnx`, the TensorRT vision backend, the
expected model paths, REST port 19003, and a disabled message sink.

Three real `POST /api/v1/generate_image_embeddings` calls passed with zero
active streams. Repeating the primary 256×256 P6 PPM image produced the exact
same finite, non-zero 1,152-dimensional vector. A contrasting image produced
a distinct vector with cosine similarity 0.8704016749813162. The vector norms
were 1.0001919959048393 and 0.9997976685651033. A missing-image request
returned the exact expected HTTP 500 error without an embedding.

The isolated container had no OOM event, automatic restart, or `VPI_ERROR`.
Cleanup removed it and its temporary configuration and fixtures. The healthy
main `vss-rtvi-cv` remained byte-for-byte identical with zero streams, and the
three intentionally paused workloads remained stopped. The run performed no
network download, VSS Agent call, main RT-CV stream mutation, VIOS mutation,
or Warehouse sample access. No raw vector, request ID, image path, or
credential is retained.

The capability claim is intentionally format-specific: the accepted P6 PPM
path is exercised end to end. Separately, different JPEG inputs were observed
to collapse to the same vector through the container's NVIDIA JPEG decoder on
Thor; JPEG correctness is therefore not claimed and remains an explicit
compatibility defect.

Artifact locks:

- contract: `75e1bb3092dd0f80e6c04f7b2d05c4b7eb579a9d1520b9df046ad66b686ec9b0`
- receipt schema: `1641923e6ca7e8b545c25013d416e76431ff40e7f0a4fb1a1fe028823e624df2`
- runtime receipt: `3cf8e74aff606ed35b126892a5a8e1db0ce69c5591a6ee7e56d44055406b3ffc`
- executor: `c1895987895b5ef676c3c56101fe9c3bf9f204db8af8631b7aeec059578b571b`
