# Runtime evidence

On 2026-08-10 the isolated Thor qualifier exercised NvStreamer
`2.1.0-26.05.4` from ARM64 image
`sha256:b3e5b92fa2546e9b69a3dba7cac324ce36a3cce65f2e0d61ad41a8a84a74a563`.
The run recorded:

- a 55,942-byte, two-second H.264 baseline/AAC fixture at 320×180 with no
  B-frames;
- HTTP 200 direct multipart upload, HTTP 200 shipped-UI upload, and automatic
  online discovery of the local-mounted copy;
- an automatic loopback RTSP URL whose live probe contained H.264 320×180
  video and AAC 48 kHz mono audio;
- a valid 6,804-byte MJPEG live snapshot at 320×180;
- a real UI WebRTC session with 5 WebSocket frames sent and 11 received, ICE
  connected, a live video track, `readyState=4`, and an advancing video clock;
- HTTP 400 with `Failed to get media information` for the adjacent invalid MP4;
- three HTTP 200 exact file/stream removals with no owned sensor or media
  residue; and
- exact pre/post non-owned Docker inventory and running-set equality, with all
  24 reserved TCP/UDP bindings released.

The browser made 29 loopback API requests and zero external requests. Its one
failed request was the UI's separate calibration integration at
`127.0.0.1:8081`; it remained loopback-only and did not affect media playback.
The oracle permits NvStreamer's configured 16:9 WebRTC output scaling—the
source codec and dimensions are independently bound by RTSP and snapshot
probes—while requiring a real advancing frame and live track.

Raw receipt SHA-256:
`2ab858671747ea315634d846e12c4c8d87abd690a52a8381a0a614fdbe2ef8a1`.
Official evidence SHA-256:
`a4daa8ba496146cfb09feba89131c103efa7211734cc60cd655a29ae812ac7b2`.
