# Evidence

The isolated Thor run passed in 26.592039 seconds with Docker using the
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

- contract: `06d737dbe886b13bbd0aaf955144c5b67245e1b7d37f6f8b6d426386af32c23a`
- receipt schema: `a22f77c54d16e5046515af27ba702914df6173acc6341b92f079424fa244dee8`
- runtime receipt: `f985c66989368cca35ea6c006a00ddfeb49af9153ed2ba4ab146a58e0396ead6`
- executor: `7c7ba8ec08fc9154808a21033bfd0cf76041962cdde87e294f40cc525864743a`
