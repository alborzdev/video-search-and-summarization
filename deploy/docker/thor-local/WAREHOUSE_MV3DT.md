# Custom-data MV3DT parity lane on Jetson AGX Thor

This lane prepares and qualifies NVIDIA VSS MV3DT—per-camera RT-DETR,
BodyPose3DNet tracking, BEV fusion, behavior analytics, and VIOS/VST—without
an LLM, VLM, Kafka, or the NVIDIA warehouse sample bundle. It is pinned to
`HARDWARE_PROFILE=AGX-THOR`, Redis, and the blueprint's authoritative
seven-stream MV3DT limit.

The helper is fail-closed and non-lifecycle. With no command it only validates
the operator input contract. It never starts/stops containers, pulls/builds
images, changes host permissions, removes volumes, or deletes state. It prints
the reviewed pull-free start command for an operator to run manually.

## The 100 GB sample is not required

The convenience resource below remains explicitly excluded:

```text
nvidia/vss-warehouse/vss-warehouse-app-data:3.2.0
```

Use an operator-owned absolute directory with this layout instead:

```text
<input>/
├── models/
│   ├── mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx
│   └── mv3dt/BodyPose3DNet/bodypose3dnet_accuracy.onnx
├── videos/<custom-slug>/
│   ├── Camera.mp4
│   ├── Camera_01.mp4
│   └── ... through Camera_06.mp4 at most
└── calibration/<custom-slug>/
    ├── calibration.json
    ├── camInfo/Camera.yml, Camera_01.yml, ...
    └── images/Top.png, imageMetadata.json
```

The two to seven MP4 files must be calibrated views of the same scene and
timeline. Validation requires H.264/H.265, identical frame rate and frame
count, and start/duration drift no greater than 100 ms. The ordered
`calibration.json` IDs, MP4 stems, and `camInfo` stems must be exactly
`Camera`, `Camera_01`, ... with no extras. Calibration also needs non-empty
group, region, and place fields; finite numeric group origin/dimensions and
camera coordinates; finite x/y for every image-coordinate point; and a
non-empty list of finite x/y/z global-coordinate points for every sensor.
Every `camInfo` file must be a safe, ordinary YAML mapping containing a finite
numeric 12-element `projectionMatrix_3x4_w2p`; malformed documents and unknown
YAML tags are rejected. `imageMetadata.json` must declare `Top.png` as a plan
view.

TensorRT engines are intentionally not accepted from the operator source.
Only the two ONNX files are copied, so engines are built by the pinned 3.2.1
runtime on Thor instead of reusing an engine from another TensorRT/GPU build.

## Dry-run and prepare private state

```bash
export THOR_MV3DT_INPUT_DIR=/absolute/path/to/operator-mv3dt-input
export THOR_MV3DT_DATASET=operator-yard-4cams
export THOR_MV3DT_RUNTIME_DIR="$XDG_STATE_HOME/cti-vss/mv3dt-yard-4cams"

# Default command is the read-only plan.
deploy/docker/scripts/thor-warehouse-mv3dt.sh

# Explicitly create a new private runtime after reviewing the plan.
deploy/docker/scripts/thor-warehouse-mv3dt.sh prepare
```

`prepare` refuses an existing destination. It copies the two ONNX files,
videos, calibration, and a mutable `deploy/docker` snapshot into the new
runtime; it never hard-links them. Configurator can therefore render configs
and TensorRT engines without changing the checkout or operator source.
Checksums cover every copied model, video, and calibration artifact. A second,
deterministically ordered checksum manifest covers the copied deployment
snapshot while excluding only private config directories that Configurator
legitimately rewrites. Its digest is recorded in the runtime marker and every
validation verifies the marker and immutable snapshot files. This captures
tracked, dirty, and untracked deployment sources present at prepare.

The private MV3DT VST and NvStreamer configs are patched to use the non-empty
loopback sentinel `127.0.0.1:3478`. An empty list is unsafe because VST inserts
its compiled public default when no server is configured. The loopback value
prevents DNS/egress to Google's STUN servers on an offline Thor. Local/LAN VST
playback can still be used; remote NAT traversal needs an explicitly reviewed
site-local STUN/TURN configuration.

## Resolve both supported profiles

```bash
export THOR_MV3DT_RUNTIME_DIR="$XDG_STATE_HOME/cti-vss/mv3dt-yard-4cams"

deploy/docker/scripts/thor-warehouse-mv3dt.sh validate-all
deploy/docker/scripts/thor-warehouse-mv3dt.sh config minimal > /tmp/mv3dt-minimal.yml
deploy/docker/scripts/thor-warehouse-mv3dt.sh config extended > /tmp/mv3dt-extended.yml
```

- `minimal` resolves exactly 20 services: MV3DT core, Redis, behavior
  analytics, and VIOS/VST. It has raw video but no indexed overlay path.
- `extended` resolves exactly 28 services: the same core plus Elasticsearch,
  Logstash, Kibana, Video Analytics API, HAProxy, and calibration import for
  top-view and VST overlays.

Extended Logstash uses the locally staged immutable
`vss-logstash-protobuf:9.3.3-codec-1.3.0-thor-local` derivative, an empty
Compose command, and its baked Kafka protobuf path. It never installs a plugin
from Rubygems during startup; preflight checks this image like every other
resolved image.

Both graphs enforce Redis, `AGX-THOR`, `NUM_STREAMS <= 7`, LLM/VLM `none`,
offline model flags, local ARM64 Thor images, protected loopback Redis, and
writable bind mounts only under the lane-private app/data roots (with the
existing Docker socket exception used by the blueprint coordinator).
Compose resolution and the printed launch command use the overlay copied into
that private snapshot, never the subsequently edited live checkout.

## Read-only staging and runtime gates

```bash
deploy/docker/scripts/thor-warehouse-mv3dt.sh preflight minimal
deploy/docker/scripts/thor-warehouse-mv3dt.sh preflight extended

# Prints a reviewed command containing --no-build --pull never. It does not run it.
deploy/docker/scripts/thor-warehouse-mv3dt.sh launch-command extended

# After an operator has started that exact private Compose project:
deploy/docker/scripts/thor-warehouse-mv3dt.sh qualify extended
```

Preflight checks copied checksums, exact local `linux/arm64` image metadata,
fixed container-name and port conflicts, other active GPU workloads, a Jetson
AGX Thor host, 24 GiB available unified memory, and 30 GiB free on
the private runtime filesystem. It never remediates a failure.

`qualify` is read-only. It verifies project ownership and container
health, Configurator readiness, the exact online VST sensor set, perception
`Active sources` and FPS evidence, no missing calibration lookup, and growing
`mdx-raw`/`mdx-bev` Redis streams plus behavior output. Extended qualification
also requires live Video Analytics/Kibana and successful one-shot index,
dashboard, and calibration imports.

## Lifecycle and resets

The helper deliberately has no start, stop, or reset command. Review the
printed `launch-command`, dedicate the single Thor GPU to this lane, and run it
manually only after preflight passes. Any `docker compose down -v`, host-side
`data_log` cleanup, ACL change, or sensor reset is destructive and must remain
a separate operator-confirmed action. Capture `compose ps`, relevant logs,
dataset/calibration identity, and broker offsets before authorizing a reset.

Runtime qualification of this lane still requires matching real operator
videos and calibration plus temporary release of unrelated GPU workloads. A
static pass is necessary but is not runtime acceptance.

The adjacent
[`qualification/mv3dt-entry-oracles/`](qualification/mv3dt-entry-oracles/README.md)
package now fixes the exact-four admission and future evidence contract for the
four advertised MV3DT semantics. Its default command remains inert: it checks
the current launcher, validator, configuration tools, and live-open oracle
bindings, but it does not run this lane or admit a receipt. Future qualification
must separately demonstrate per-camera `mdx-raw` detections, linked `mdx-bev`
fusion, actual BodyPose model load and use, calibrated cross-camera continuity,
and exact-owned cleanup against operator data.
