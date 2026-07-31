# Thor-local Sparse4D warehouse lane

This lane prepares NVIDIA VSS 3.2.1 warehouse `MODE=3d` (Sparse4D) for
operator-owned data on Jetson AGX Thor. It deliberately does not use or
download `vss-warehouse-app-data` or the excluded
`warehouse-4cams-20mx20m-synthetic` sample.

The launcher is fail-closed and has no lifecycle implementation. `plan`,
`prepare`, `validate`, `preflight`, `launch-command`, and `qualify` never
start, stop, pull, build, delete, reset, or change permissions on a running
stack. `launch-command` prints the separately reviewable manual command.

## Input contract

Set an absolute input root with this layout:

```text
<input>/
  models/sparse4d/ov/
    sparse4d_warehouse_v2.2.onnx
    _ov_kmeans900_v2.2.npy
  videos/<custom-slug>/
    Camera.mp4
    Camera_01.mp4
    Camera_02.mp4
    Camera_03.mp4
  calibration/<custom-slug>/
    calibration.json
    images/
      Top.png
      imageMetadata.json
```

The source tree cannot contain symlinks. The model must parse and pass the
ONNX checker without external tensor files. The anchor must be a finite
float32/float64 NPY array with shape `(900, 11)`, matching the v2.2
configuration's 900 anchors.

Sparse4D's published warehouse contract is four synchronized cameras. The
validator requires exactly the four canonical names, one H.264/H.265 video
stream each, identical codec/resolution/fps/frame count, and start/duration
drift no greater than 100 ms. Calibration sensor order and names must match,
all cameras must share one `bev` group, video dimensions/fps must match sensor
attributes, and all intrinsic/extrinsic/camera/homography matrices and 2D/3D
correspondences must be finite. `Top.png` must have a structurally valid PNG
chunk stream, checksums, DEFLATE payload, scanline sizes, and filters;
plan-view metadata is also required so either minimal or extended can be
selected after one preparation.

Python needs `onnx`, `numpy`, and the standard VSS dependencies. `ffprobe` is
required for deterministic synchronization checks.

## Safe workflow

```bash
cd /home/nvidia/cti-saa-thor/video-search-and-summarization

export THOR_SPARSE4D_INPUT_DIR=/absolute/path/to/operator-input
export THOR_SPARSE4D_DATASET=operator-yard-4cams
# Optional; must not already exist.
export THOR_SPARSE4D_RUNTIME_DIR="$XDG_STATE_HOME/cti-vss/warehouse-sparse4d-yard"

deploy/docker/scripts/thor-warehouse-sparse4d.sh plan
deploy/docker/scripts/thor-warehouse-sparse4d.sh prepare
deploy/docker/scripts/thor-warehouse-sparse4d.sh validate-all
deploy/docker/scripts/thor-warehouse-sparse4d.sh preflight minimal
deploy/docker/scripts/thor-warehouse-sparse4d.sh launch-command minimal
```

`prepare` creates a new mode-0700 private runtime, copies validated inputs
(never hardlinks them), and re-runs the complete model/video/calibration
validator against those private copies immediately before freezing their
checksums and publishing the runtime directory. It also takes a
content-addressed `deploy/docker` snapshot and writes a mode-0600 generated
environment. Configurator mutations and TRT engine output are therefore
isolated from the checkout and operator source. Changing a snapshotted
immutable file or copied asset makes later gates fail.

The lane is pinned to:

- `MODE=3d`, `BP_PROFILE=bp_wh_redis`, `STREAM_TYPE=redis`
- `HARDWARE_PROFILE=AGX-THOR`, four streams, one local GPU
- `LLM_MODE=none`, `VLM_MODE=none`
- loopback public endpoints and nonempty loopback STUN sentinel
- no runtime package installs, pulls, or builds

Minimal resolves exactly 19 services. Extended resolves exactly 31 services:
the minimal graph plus ELK, Video Analytics API, HAProxy, Prometheus, Grafana,
node-exporter, and cAdvisor. DCGM exporter is intentionally excluded because
the published datacenter image has not been qualified for Jetson's integrated
GPU. Extended Redis Logstash requires the pre-staged
`vss-logstash-redis:9.3.3-input-3.1.0-thor-local` derivative; its build recipe
uses the SHA-256-pinned ARM64 Logstash base, verifies the checked-in
Redis-stream gem digest, and has Compose build networking disabled. The launch
command still uses `--no-build --pull never`.

`preflight` is read-only. It requires every resolved image to exist locally as
Linux/ARM64, no conflicting fixed-name containers or GPU workloads, idle host
ports, at least 50 GiB available unified memory, and 30 GiB free disk. Missing
items are reported without pulling or building anything.

## Qualification and current blockers

After an operator manually starts the printed command, qualify without making
changes:

```bash
deploy/docker/scripts/thor-warehouse-sparse4d.sh qualify minimal
```

Qualification proves project ownership and health, four exact online VST
sensors, Configurator and config-adaptor completion, four active Sparse4D
sources with FPS, absence of model/calibration/CUDA errors, growth of the
Redis `mdx-bev` stream, and behavior output. Extended also checks ELK/API,
monitoring health, and all one-shot importers.

As of 2026-07-31 Thor has the exact ARM64 `vss-rt-cv:3.2.1` image, but the
Sparse4D v2.2 ONNX and kmeans anchor are not staged. No custom aligned
four-camera dataset/calibration has been supplied, and several deterministic
extended images remain unstaged. Consequently this lane is statically wired
and tested, not runtime-qualified.
