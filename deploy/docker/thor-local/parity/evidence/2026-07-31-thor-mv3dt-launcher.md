# Thor custom-data MV3DT launcher evidence — 2026-07-31

## Result

A source-only custom-data MV3DT lane is implemented for Jetson AGX Thor. It
uses the official `AGX-THOR` warehouse blueprint profile (MV3DT cap seven),
Redis, local RT-CV and BEV Fusion, and no LLM/VLM. The approximately 100 GB
NVIDIA warehouse sample resource is not used or required; its canonical sample
slug is rejected by the input validator.

The launcher defaults to a non-mutating plan and contains no Compose lifecycle,
image pull/build, sudo, ACL, delete, or reset execution. Preparation writes
only a newly selected private runtime. It copies, rather than hard-links, two
operator ONNX files, two to seven synchronized videos, matching calibration,
`camInfo`, `Top.png`, and `imageMetadata.json`, plus a mutable deployment
snapshot. TensorRT engine files are not imported.

The custom source contract is strict:

- `calibration.json` contains 2–7 sensors ordered `Camera`, `Camera_01`, ...;
- MP4 and camInfo stems match that set exactly with no extras;
- videos are H.264/H.265 with equal FPS/frame count and <=100 ms timeline drift;
- every sensor has group/region/place fields, finite group/camera/image
  coordinates, and non-empty finite x/y/z global coordinates;
- every camInfo is safe mapping-only YAML with a finite numeric 12-element
  `projectionMatrix_3x4_w2p` required by BEV fusion;
- extended visualization assets describe `Top.png` as a plan view.

The lane-private MV3DT VST and NvStreamer configs replace both public Google
STUN endpoints with the non-empty loopback sentinel
`network.stunurl_list=["127.0.0.1:3478"]` and leave Twilio STUN/TURN disabled.
This is deliberately non-empty because VST falls back to its compiled public
STUN URL for an empty list. Configurator mutates those private copies only.
The extended graph also replaces base Logstash's startup Rubygems installer
with the staged `vss-logstash-protobuf:9.3.3-codec-1.3.0-thor-local` image,
an empty command, and `STREAM_TYPE=kafka`.

## Static qualification

Command:

```bash
bash deploy/docker/test-scripts/test-thor-warehouse-mv3dt.sh
```

Result: all 16 focused checks passed. This includes:

- shell and three Python source syntax checks;
- source-only helper exposure and absence of lifecycle/privileged execution;
- Thor/Redis/offline Compose overlay invariants;
- immutable extended Logstash image/command/stream-type invariants;
- dry-run immutability of operator inputs and the checked-in warehouse `.env`;
- private copied state, no imported engines, mode-0600 environment, checksums,
  and non-empty loopback-only STUN lists;
- exact private-overlay use plus deterministic checksum coverage for the copied
  dirty/untracked deployment snapshot;
- exact minimal 20-service and extended 28-service Compose graphs;
- a pull-free/build-free non-executing launch command;
- fail-closed video timeline drift, non-finite 3D calibration, malformed
  camInfo projection, excluded sample slug, failed-prepare cleanup, and private
  snapshot-tamper tests.

Additional source checks:

```text
bash -n deploy/docker/scripts/thor-warehouse-mv3dt.sh
python3 -m py_compile <three MV3DT Python helpers>
git diff --check -- <MV3DT-owned files>
```

All passed. No containers were started, stopped, pulled, built, or reset.

## Runtime acceptance still open

This milestone is `wired/static_only`, not runtime-qualified. Thor does not
currently have a matching operator-owned synchronized multi-camera video and
calibration set staged in this lane. Runtime qualification also requires the
single GPU to be free of unrelated workloads and every resolved ARM64 image to
be local. When those prerequisites are available:

```bash
deploy/docker/scripts/thor-warehouse-mv3dt.sh preflight extended
deploy/docker/scripts/thor-warehouse-mv3dt.sh launch-command extended
# operator reviews and runs the printed command
deploy/docker/scripts/thor-warehouse-mv3dt.sh qualify extended
```

The read-only qualification requires exact online VST sensors, perception FPS
and active-source count, healthy fusion, growing `mdx-raw` and `mdx-bev`,
behavior output, no calibration lookup failures, and the extended
Video-Analytics/Kibana/import path. A future pull-free restart must also be
recorded before complete MV3DT parity can be claimed.
