# Thor VIOS SDR camera lifecycle runtime qualification — 2026-08-10

## Result

The VSS 3.2.1 Thor-local graph now includes the NVIDIA SDR dispatcher omitted
from the released split-VIOS Compose path. The deployed, content-addressed
image was `nvcr.io/nvidia/vss-core/sdr:3.1.0` at digest
`sha256:d9912bc9b412188b9beae5948f93a1be2a86affdb3df1a0e0c1933bb1c05d24d`.
It consumed the current `vst.event` Redis stream and forwarded `camera_proxy`
and `camera_remove` requests to the local `vss-vios-streamprocessing` target.

The complete live path passed with an owned local NvStreamer H.264 fixture:

- POSTing one tagged RTSP sensor produced one online sensor, one generated
  proxy, one VOD URL, and `alwaysOn` recording in two seconds.
- The UI-facing all-streams API reported H.264, 1280x720, 60 fps, proxy port
  30555, and VOD port 30564.
- `ffprobe` decoded actual H.264 1280x720 60 fps media through the generated
  VIOS proxy.
- The native live-picture route returned a 136,636-byte 1280x720 JPEG with
  SHA-256 `5d68e2804d3c64a353990026b989df9d4a917b6491ab99e17a6e3382632e2b87`.
- Recording produced a non-empty timeline from
  `2026-08-10T11:08:21.706Z` through `2026-08-10T11:09:39.789Z`.
- Restarting only the Compose-managed dispatcher preserved exactly one proxy
  and `alwaysOn` recording. The Redis last-delivered ID and `entries-read=259`
  remained unchanged, with `pending=0` and `lag=0`; no historical event was
  replayed.

## Correct event and startup contract

The current VIOS sensor service publishes to `vst.event`, not the older
`vst_events` name present in an upstream example. A durable consumer group,
`sdr-streamprocessing-vios-cg`, is therefore created at Redis `$` before the
sensor and stream-processor producers start. A pre-existing group is an
expected idempotent `BUSYGROUP` result. This makes first deployment ignore old
events while retaining at-least-once current-event delivery across reboots.

The dispatcher runs on the private Compose bridge. Its health endpoint is
published only as `127.0.0.1:4003`, all Linux capabilities are dropped,
`no-new-privileges` is set, memory is capped at 300 MiB, and the unused
cluster-controller FQDN resolves to `127.0.0.1`. Redis listens only on
`127.0.0.1` and Docker's private `172.17.0.1` gateway; it has no physical/LAN
listener. Protected mode is disabled because Redis otherwise rejects the
explicitly bound bridge client even though the actual bind already excludes
all public interfaces.

The Thor operator script now carries the SDR port through its protected runtime
environment, collision checks, readiness gate, doctor report, and firewall
inventory. A normal Compose start therefore owns the service and fails
readiness if the dispatcher is absent.

## Cleanup and boundary

The exact tagged sensor was deleted, the generated proxy count returned to
zero, the recorded timeline returned `null`, and storage deletion reported 60
MB reclaimed. The owned NvStreamer fixture container and the earlier manual
SDR test container were removed. The Compose SDR remained healthy; Redis ended
with zero pending messages and zero lag. No warehouse sample, external camera,
user sensor, or user recording was used or removed.

Machine-readable evidence and a networkless source/evidence verifier live in
`qualification/vios-sdr-compose-runtime/`. This receipt qualifies the local
RTSP add → dispatch → proxy → snapshot → recording → removal lifecycle. It does
not claim physical-camera behavior, ONVIF discovery, multi-camera calibration,
or warehouse data.
