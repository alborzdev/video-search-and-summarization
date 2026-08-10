# NvStreamer file-workflow runtime qualification

This executor closes the exact NVIDIA VSS capability
`runtime.nvstreamer.file-streaming` on Thor. It creates a private, bounded
NvStreamer container from the existing offline ARM64 derivative and exercises
all three advertised inputs:

- direct single-part multipart upload;
- upload through the shipped VIOS/NvStreamer React UI in system Chromium; and
- automatic discovery of a local-mounted MP4.

It reads the generated RTSP identity, proves H.264 video and AAC audio with
`ffprobe`, retrieves a valid live JPEG snapshot, and drives the shipped Media
Streams UI until a real WebRTC video track is live and the browser video clock
advances. A nine-byte invalid MP4 must return HTTP 400. The executor then
deletes only its returned stream IDs, removes its exact container, requires the
pre-existing Docker inventory and running set to match, and requires every
reserved port to be free.

The qualifier does not add a sensor to main VIOS, hand a stream to RT-CV, call
the VSS Agent, use Warehouse data, download an image or package, or send a
browser request off-box. It uses loopback HTTP/RTSP and a private Docker bridge
for WebRTC media. The UI's independent calibration lookup at loopback port 8081
is retained as an adjacent unavailable-service observation; calibration is a
separate capability and is not required for NvStreamer file playback.

Run explicitly:

```bash
python3 deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/execute.py \
  --execute \
  --output deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/runtime-receipt.json
```

The retained 2026-08-10 raw receipt SHA-256 is
`2ab858671747ea315634d846e12c4c8d87abd690a52a8381a0a614fdbe2ef8a1`.
The canonical official evidence wrapper SHA-256 is
`a4daa8ba496146cfb09feba89131c103efa7211734cc60cd655a29ae812ac7b2`.
See `EVIDENCE.md` for the concise observed result.
