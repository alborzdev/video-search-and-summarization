# Thor RT-CV-3D audit — 2026-07-31

The VSS 3.2.1 warehouse configurator explicitly supports Jetson AGX Thor as a
single-GPU target. `AGX-THOR` is a YAML alias of the Thor warehouse profile,
and both its Sparse4D `3d` lane and `mv3dt` lane cap inputs at seven streams.
A four-camera acceptance run is therefore within the official Thor contract;
neither H100 nor a multi-GPU host is required.

The principal ARM64 images are already staged locally:

- `nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1`, image ID
  `sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458`.
- `nvcr.io/nvidia/vss-core/vss-rt-cv-mv3dt-bev-fusion:3.2.0`, image ID
  `sha256:b5286d97e82095c12ed90ca5ec9486ce2bf8897819fc1e995b0b9e166378265d`.

The VSS data directory includes
`models/rtdetr_warehouse_v1.0.2.fp16.onnx`. A BodyPose3DNet ONNX was found in
another local project, but it is not yet staged into lane-private VSS storage
and existing TensorRT engines have inconsistent hashes. MV3DT must stage the
ONNX explicitly and rebuild the RT-DETR and BodyPose engines in the 3.2.1
runtime rather than silently reusing incompatible engines.

Sparse4D still lacks both required files:

- `models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx`
- `models/sparse4d/ov/_ov_kmeans900_v2.2.npy`

Minimal custom-data Compose graphs render for Sparse4D and MV3DT. The repo has
the official four-camera calibration/top-view files but not the corresponding
videos. A separate five-second four-camera fixture exists on Thor, but its
projection matrices do not match those calibration files and it must not be
mixed with them. Runtime qualification therefore needs four synchronized,
overlapping operator videos or RTSP streams and their matching calibration;
MV3DT additionally needs matching `camInfo` files. Extended visualization also
needs matching `Top.png` and `imageMetadata.json`.

The roughly 100 GB NVIDIA warehouse sample bundle is not required and remains
explicitly excluded. Sparse4D and MV3DT should run sequentially, without the
LLM/VLM, after unrelated GPU workloads are temporarily stopped. Acceptance
must prove active sources/FPS, growing broker topics, valid persistent 3D
tracks/world coordinates, behavior-analytics consumption, the extended Video
Analytics/Kibana/VIOS top-view path, and a pull-free restart.
