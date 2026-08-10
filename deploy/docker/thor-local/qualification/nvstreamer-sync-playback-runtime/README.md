# NvStreamer synchronized playback runtime qualification

This package proves `configuration.nvstreamer.sync` on Thor with the exact
`vss-vios-nvstreamer:3.2.1-thor-local` arm64 image. It derives an isolated
configuration with `nv_streamer_sync_file_count=2`, serves two byte-identical
H.264 files, and establishes two TCP RTSP clients in sequence.

The acceptance oracle requires the first client to remain blocked for three
seconds, no shared-clock start marker before the second client, one shared
GStreamer base clock after the second client joins, successful first-frame
decode by both clients, no more than 250 ms completion skew, and exact
restoration of the prior Docker inventory, running set, and reserved ports.

The run uses only loopback HTTP/RTSP ports, generates its small fixture locally,
and does not use the warehouse sample, main VIOS, RT-CV, or VSS Agent `/generate`.
The checked-in receipt is a current passing Thor execution and the official
ledger row is `wired` / `passed_current` with hash-bound evidence.

Run from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/nvstreamer-sync-playback-runtime/execute.py \
  --execute \
  --output deploy/docker/thor-local/qualification/nvstreamer-sync-playback-runtime/runtime-receipt.json
```
