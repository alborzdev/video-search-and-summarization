# Thor-local AutoMagicCalib lane

This is a sample-free, pull-free qualification lane for the VSS 3.2.1
AutoMagicCalib (AMC) service. It uses custom synchronized MP4s or operator-owned
RTSP cameras and does not require the warehouse sample bundle.

The lane does not start or stop containers. It validates inputs, inventories
local artifacts, renders a hardened Compose overlay, and performs GET-only
runtime qualification after an operator has separately authorized deployment.

## Current exact artifact state

`artifact-inventory.json` is the source of truth:

- UI: ARM64 and locally staged at
  `nvcr.io/nvidia/vss-core/vss-auto-calibration-ui@sha256:e86c16ac9e88241dabd35e6f44c2d5086a77551a3e3654b4905e51bbf4cdf6a4`.
- Backend: official 3.2.1 source tag is known, but the image is not staged and
  its immutable ARM64 digest/image ID have not been captured. This is a hard
  unavailable state, not a wildcard.
- VGGT: `vggt_1B_commercial.pt` is absent and its checksum is unset. VGGT is
  optional for base AMC; only refinement needs it.

Inspect that state without registry access:

```bash
deploy/docker/scripts/thor-auto-calibration.sh inventory
deploy/docker/scripts/thor-auto-calibration.sh plan
```

The backend tag reportedly represents about 14.07 GB of compressed layers.
This lane never pulls it. After the user authorizes staging with a credential
that can access `vss-core`, capture both the ARM64 `RepoDigest` and local image
ID, then replace the two null backend lock fields. Do the same for VGGT with
`sha256sum` after its separate commercial license is accepted and its download
is authorized. A null digest always blocks preflight.

## Custom synchronized MP4 path

Name cameras contiguously from `cam_00.mp4`; upload order is lexical camera
order. The validator checks that containers are readable and agree on
resolution, frame rate, duration, and start time (100 ms tolerance). It warns
when media is shorter than the recommended 2–3 minutes or differs from the
recommended 1920x1080. Matching container timestamps cannot prove physical
camera synchronization, so the operator still owns that assertion.

Place exactly one `alignment_data.json` and `layout.png` in the video directory
or its parent before preflight. Calibration settings are optional; supported
auto-detected names match the AMC skill.

```bash
deploy/docker/scripts/thor-auto-calibration.sh validate-videos /data/my-cameras
deploy/docker/scripts/thor-auto-calibration.sh preflight \
  --mode videos \
  --input /data/my-cameras
```

For a fast codec/naming check, create a tiny local fixture:

```bash
fixture_dir="$(mktemp -d /tmp/vss-amc-fixture.XXXXXX)"
deploy/docker/scripts/thor-auto-calibration.sh fixture "$fixture_dir"
deploy/docker/scripts/thor-auto-calibration.sh validate-videos "$fixture_dir"
```

The generated pair is intentionally too short, has no real multi-view
parallax, and has no alignment/layout. It tests only the local media contract;
it is not evidence that AMC can calibrate or meet accuracy thresholds.

## Custom RTSP path

RTSP capture requires a running VIOS endpoint reachable by AMC. Keep secrets
out of tracked files. A local plan has this shape:

```json
{
  "duration_seconds": 180,
  "streams": [
    {"camera_name": "north", "rtsp_url": "rtsp://camera-a/live", "sensor_id": null},
    {"camera_name": "south", "rtsp_url": "rtsp://camera-b/live", "sensor_id": null}
  ],
  "settings_json": "calibration_settings.json",
  "alignment_json": "alignment_data.json",
  "layout_png": "layout.png"
}
```

Attachment paths may be absolute or relative to the plan. Settings are
optional, but alignment and layout are required for preflight. Without a
settings file, select the detector and confirm default/UI-tuned parameters in
the calibration skill before its mutating `/calibrate` request.

```bash
deploy/docker/scripts/thor-auto-calibration.sh validate-rtsp /secure/path/rtsp-plan.json
deploy/docker/scripts/thor-auto-calibration.sh preflight \
  --mode rtsp \
  --input /secure/path/rtsp-plan.json
```

Validator output never contains RTSP hosts, paths, usernames, or passwords. It
reports only scheme/port and whether credentials are present.

## Pull-free deployment boundary

Once `preflight` passes and the user authorizes a launch, use the upstream graph
plus `compose.yml`. The overlay requires an immutable backend reference,
content-addresses the UI, binds both endpoints to loopback by default, disables
automatic restarts, and bounds local logs.

```bash
export COMPOSE_PROFILES=auto_calib
export VSS_APPS_DIR="$PWD/deploy/docker"
export VSS_DATA_DIR="$PWD/deploy/docker/data-dir"
export THOR_AMC_BACKEND_IMAGE='nvcr.io/nvidia/vss-core/vss-auto-calibration@sha256:<audited-arm64-digest>'

docker compose \
  -f deploy/docker/services/auto-calibration/compose.yml \
  -f deploy/docker/thor-local/auto-calibration/compose.yml \
  config

# Operator-authorized lifecycle command only:
docker compose \
  -f deploy/docker/services/auto-calibration/compose.yml \
  -f deploy/docker/thor-local/auto-calibration/compose.yml \
  up -d --pull never --no-build
```

Use an SSH tunnel for the loopback UI/API. Override the bind addresses only
with an explicit network/firewall decision. The projects directory must also
be writable by container UID 1000; follow the scoped ACL procedure in the AMC
skill rather than making it world-writable.

## Read-only runtime qualification

After the stack is running, this command issues GET requests only. It verifies
backend readiness, all 26 operations advertised by the checked-in AMC skill,
and the UI. The contract covers base project/upload/config/alignment/layout/
calibration/results/log operations, optional VGGT and ground-truth operations,
the RTSP capture/status/ingest/stop/list/delete lifecycle, and project stop/
delete. RTSP mode can also check the VIOS sensor-list endpoint without creating
a sensor or capture session.

The 26-operation count is exact: 1 readiness operation; 7 project creation,
upload, and configuration operations; 5 verify/run/stop/status/delete
operations; 5 result and log operations; 2 VGGT operations; and 6 RTSP
start/status/ingest/stop/list/delete operations. OpenAPI parameter names are
normalized when matching (for example `{id}` and `{project_id}`), but paths and
HTTP methods are otherwise strict.

```bash
deploy/docker/scripts/thor-auto-calibration.sh qualify

deploy/docker/scripts/thor-auto-calibration.sh qualify \
  --vios-url http://127.0.0.1:30888
```

Backend, UI, and VIOS arguments accept only `http`/`https` origins whose host
is a numeric loopback address (for example `127.0.0.1` or `[::1]`). Hostnames,
credentials, queries, fragments, unexpected paths, proxies, and redirects are
rejected. Error messages identify the endpoint role but never reproduce a
caller-supplied URL or credential.

Exit status is `0` for passed checks, `1` for a reachable contract failure, and
`2` when required artifacts or endpoints are unavailable. Runtime completion,
overlay review, and optional accuracy metrics still require a real calibration
project driven through the `vss-generate-video-calibration` skill.
