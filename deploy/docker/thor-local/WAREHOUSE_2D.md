# Warehouse 2D parity lane on Jetson AGX Thor

This is the first deliberately narrow warehouse milestone: one to three
loading-dock cameras, RT-DETR/NvDCF perception, Redis event transport,
behavior analytics, and VIOS/VST. It selects NVIDIA's minimal warehouse
profile and does not include the warehouse agent, LLM/VLM, Elasticsearch,
Video Analytics API, dashboards, or overlays.

The milestone currently prepares and validates the lane only. It has no
container start, stop, pull, build, disk cleanup, or privileged command. A
passing static preflight is necessary but is not runtime qualification.

## Why it is a separate lane

Warehouse services use fixed container names and host-network ports, while
RT-CV, NvStreamer, and VST all use Thor's single GPU. Run this lane mutually
exclusively with `thor-full`, local model servers, other DeepStream demos, and
the Sparse4D/MV3DT/calibration lanes.

Configurator receives read-write app and data mounts. To protect the checkout
and the operator's source assets, `prepare` creates:

- a private snapshot of non-ignored `deploy/docker` working-tree sources;
- an independent copy of the selected RT-DETR ONNX and only the requested
  loading-dock MP4 files;
- private Redis/VST data directories;
- a mode-`0600` `generated.env` with literal minimal/Redis/AGX-Thor selectors.

The destination must not already exist. Refreshing always means choosing a new
runtime directory; the helper never replaces or deletes prior state.

## Custom-data contract (NVIDIA sample is optional)

The roughly 100 GB NVIDIA resource below is a convenience fixture for
reproducing NVIDIA's sample deployment; it is excluded from Thor parity and is
not required:

```text
nvidia/vss-warehouse/vss-warehouse-app-data:3.2.0
```

`THOR_WAREHOUSE_APP_DATA_SOURCE` may instead point to any operator-owned
absolute directory that provides this input layout:

```text
models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx
videos/warehouse-loading-dock-3cams-synthetic/*.mp4
```

The ONNX must be compatible with the checked-in warehouse RT-DETR config. The
video files may be custom MP4s; `prepare` selects the first one to three names
in lexical order and copies them into lane-private state. This milestone does
not yet adapt analytics rules or calibration for a new camera geometry, so
custom-data support remains static/partial until that configuration and a
runtime qualification are recorded.

The following images must also be staged locally as `linux/arm64`. Preflight
checks local metadata only and never pulls a missing image:

```text
nvcr.io/nvidia/vss-core/vss-configurator:3.2.1
nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1
nvcr.io/nvidia/vss-core/sdr-mw-l:3.2.0
nvcr.io/nvidia/vss-core/vss-vios-sensor:3.2.1
nvcr.io/nvidia/vss-core/vss-vios-ingress:3.2.1
nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1
vss-vios-nvstreamer:3.2.1-thor-local
vss-vios-streamprocessing:3.2.1-thor-local
cti-vss-warehouse-configurator-init:3.2.1-thor-local
cti-vss-warehouse-broker-health:3.2.1-thor-local
postgres:17.9-alpine
redis:8.6.2-alpine
alpine:3.23.4
busybox:1.37.0
```

The two VIO Thor-local images bake NVIDIA's released codec repair into the
image. Their runtime entrypoints do not perform APT operations. Private NGC
access is a hard staging prerequisite; a GitHub login is not an NGC
entitlement. Building the NvStreamer derivative additionally requires its
`nvcr.io/nvidia/vss-core/vss-vios-nvstreamer:3.2.1` ARM64 base image.

## Prepare one-camera smoke state

Use a new absolute destination:

```bash
export THOR_WAREHOUSE_APP_DATA_SOURCE=/absolute/path/to/custom-warehouse-assets
export THOR_WAREHOUSE_RUNTIME_DIR="$HOME/.local/state/cti-vss/warehouse-2d-smoke-1"
export THOR_WAREHOUSE_NUM_STREAMS=1

deploy/docker/scripts/thor-warehouse-2d.sh prepare
```

`prepare` copies assets; it does not hard-link them. Configurator can trim or
rewrite only the private lane state. Asset checksums are stored beside the
generated environment.

## Read-only validation

```bash
export THOR_WAREHOUSE_RUNTIME_DIR="$HOME/.local/state/cti-vss/warehouse-2d-smoke-1"

deploy/docker/scripts/thor-warehouse-2d.sh validate
deploy/docker/scripts/thor-warehouse-2d.sh preflight
deploy/docker/scripts/thor-warehouse-2d.sh config > /tmp/thor-warehouse-2d.resolved.yml
```

`validate` enforces the exact 18-service minimal Redis graph, Thor NVIDIA
runtime and library fixes, offline model flags, loopback Redis, and bind mounts
limited to the private app/data roots. `preflight` additionally requires:

- an AGX/IGX Thor-class `aarch64` host;
- copied assets with matching checksums;
- every resolved image present locally as `linux/arm64`;
- no existing fixed-name container and no running GPU-enabled container;
- every required host-network port idle;
- at least 8 GiB available unified memory and 20 GiB free runtime disk.

Failures are instructions to stage or free the exact missing resource. The
helper never attempts remediation itself.

## Qualification sequence

Runtime enablement should be added only after static preflight passes on a
clean host. The first acceptance sequence is one camera, followed by a fresh
three-camera runtime directory. Qualification must prove RT-CV liveness,
readiness, startup and metrics; growing `mdx-raw` and `mdx-behavior` Redis
streams; exact VST sensor registration; timeline/snapshot/RTSP access; exact
stream cleanup; and a pull-free/build-free offline restart.

Do not mark warehouse parity complete from this lane alone. Sparse4D, MV3DT,
auto-calibration, and extended warehouse overlays remain separate milestones.
